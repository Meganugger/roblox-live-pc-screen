--!nocheck
-- Minimal Roblox engine emulation for the live pipeline test (tests/e2e/run_e2e.py). Test-only, never shipped.
--
-- Runs the UNMODIFIED RlpsServer.server.luau and N copies of RlpsClient.client.luau, wired exactly as in
-- default.project.json, under Lune. Every peer (game server, each client) gets its own DataModel built from the Rojo
-- project. Emulated engine pieces, each reduced to the behaviour the scripts rely on and documented by Roblox:
--   * Instances: Name/Parent/children, property bag, attributes (+ changed signals), FindFirstChild/WaitForChild/IsA,
--     tags (CollectionService), Destroy; unknown members raise "X is not a valid member of …" like the engine.
--   * Replication: a RemoteEvent the server parents to ReplicatedStorage appears on every client; reliable RemoteEvent
--     delivery is ordered per client and arguments are copied (buffers are copied, like the engine does).
--   * HttpService:RequestAsync -> real HTTP (Lune net) to the real Python frame service. The public HTTPS tunnel hop
--     is emulated by rewriting RLPS_PUBLIC_URL to RLPS_BASE_URL. HttpEnabled is honoured; 500 requests/min enforced.
--   * HttpService:GetSecret -> server-only secret store with Secret:AddPrefix (the value never reaches script code);
--     a secret only attaches to requests for its domain (RLPS_SECRET_DOMAIN: exact host, *.parent or *, default *).
--   * EncodingService: Base64Decode (strict) and DecompressBuffer(Zstd) (Lune serde zstd).
--   * AssetService:CreateEditableImage + EditableImage:WritePixelsBuffer (RGBA8, bounds + size checks, max 1024²).
--   * RunService.Heartbeat at ~60 Hz per client; task library from Lune.
-- What the emulation can NOT prove: real Roblox networking/limits, real EditableImage rendering or memory budget,
-- Roblox's request timeouts, Studio/published settings. Those remain owner tests (KNOWN_ISSUES KI-0002).
--
-- Control (files in RLPS_OUT, polled every 0.1 s): join-<name> | leave-<name> | snap-<tag> | quit.
-- Output: RLPS_OUT/state.json (every 0.2 s, atomic), <client>-<tag>.rgba + <tag>.done for snapshots, log lines on stdout.

local fs = require("@lune/fs")
local net = require("@lune/net")
local luau = require("@lune/luau")
local process = require("@lune/process")
local serde = require("@lune/serde")
local task = require("@lune/task")

local ENV = process.env
local REPO = assert(ENV.RLPS_REPO, "RLPS_REPO")
local OUT = assert(ENV.RLPS_OUT, "RLPS_OUT")
local BASE_URL = assert(ENV.RLPS_BASE_URL, "RLPS_BASE_URL")
local PUBLIC_URL = ENV.RLPS_PUBLIC_URL or "https://rlps-e2e.test"
local SECRET_VALUE = ENV.RLPS_TOKEN
local SECRET_DOMAIN = string.lower(ENV.RLPS_SECRET_DOMAIN or "*")

-- Roblox secret domain patterns (creator docs, cloud-services/secrets): "*", "*.example.com", "my.example.com"
local function domainAllows(pattern: string, host: string): boolean
	host = string.lower(host)
	if pattern == "*" then
		return true
	end
	local parent = string.match(pattern, "^%*%.(.+)$")
	if parent then
		return #host > #parent + 1 and string.sub(host, -(#parent + 1)) == "." .. parent
	end
	return host == pattern
end
local MAX_SECONDS = tonumber(ENV.RLPS_MAX_SECONDS) or 180
local started = os.clock()

local function log(...)
	print(string.format("[emu %7.2f]", os.clock() - started), ...)
end

-- --------------------------------------------------------------------------------------------------- datatypes

local Vector3 = {}
local V3MT = {}
local V3methods = {}
V3MT.__index = function(v, k)
	if k == "Magnitude" then
		return math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
	elseif k == "Unit" then
		local m = math.sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z)
		return Vector3.new(v.X / m, v.Y / m, v.Z / m)
	end
	return V3methods[k]
end
V3MT.__sub = function(a, b)
	return Vector3.new(a.X - b.X, a.Y - b.Y, a.Z - b.Z)
end
V3MT.__add = function(a, b)
	return Vector3.new(a.X + b.X, a.Y + b.Y, a.Z + b.Z)
end
V3MT.__mul = function(a, b)
	if type(a) == "number" then
		a, b = b, a
	end
	return Vector3.new(a.X * b, a.Y * b, a.Z * b)
end
V3MT.__div = function(a, b)
	return Vector3.new(a.X / b, a.Y / b, a.Z / b)
end
V3MT.__unm = function(a)
	return Vector3.new(-a.X, -a.Y, -a.Z)
end
function V3methods.Dot(a, b)
	return a.X * b.X + a.Y * b.Y + a.Z * b.Z
end
function V3methods.Cross(a, b)
	return Vector3.new(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X)
end
function Vector3.new(x, y, z)
	return setmetatable({ X = x or 0, Y = y or 0, Z = z or 0 }, V3MT)
end

-- CFrame: position + rotation matrix m (row-major R00 R01 R02 R10 … R22), Roblox component order.
local CFrame = {}
local CFMT = {}
CFMT.__index = function(cf, k)
	local m = rawget(cf, "m")
	if k == "Position" then
		return Vector3.new(rawget(cf, "x"), rawget(cf, "y"), rawget(cf, "z"))
	elseif k == "RightVector" then
		return Vector3.new(m[1], m[4], m[7])
	elseif k == "UpVector" then
		return Vector3.new(m[2], m[5], m[8])
	elseif k == "LookVector" then
		return Vector3.new(-m[3], -m[6], -m[9])
	end
	return nil
end
function CFrame.new(x, y, z, ...)
	local r = { ... }
	if #r ~= 9 then
		r = { 1, 0, 0, 0, 1, 0, 0, 0, 1 }
	end
	return setmetatable({ x = x or 0, y = y or 0, z = z or 0, m = r }, CFMT)
end
function CFrame.lookAt(eye, target, up)
	up = up or Vector3.new(0, 1, 0)
	local look = (target - eye).Unit
	local right = look:Cross(up).Unit
	local up2 = right:Cross(look)
	return CFrame.new(eye.X, eye.Y, eye.Z, right.X, up2.X, -look.X, right.Y, up2.Y, -look.Y, right.Z, up2.Z, -look.Z)
end

local Vector2 = {}
function Vector2.new(x, y)
	return table.freeze({ X = x or 0, Y = y or 0 })
end
Vector2.zero = Vector2.new(0, 0)

local UDim2 = {}
function UDim2.fromScale(x, y)
	return { kind = "UDim2", sx = x, sy = y }
end
function UDim2.new(sx, ox, sy, oy)
	return { kind = "UDim2", sx = sx, ox = ox, sy = sy, oy = oy }
end

local Color3 = {}
function Color3.new(r, g, b)
	return { R = r, G = g, B = b }
end
function Color3.fromRGB(r, g, b)
	return { R = r / 255, G = g / 255, B = b / 255 }
end

local Content = { none = table.freeze({ kind = "Content", Object = nil }) }
function Content.fromObject(obj)
	return table.freeze({ kind = "Content", Object = obj })
end

-- Only the enums the scripts use; unknown items raise like the engine ("X is not a valid member of Y").
-- Items are listed in value order (0, 1, …) unless given as { name, value }.
local ENUMS = {
	NormalId = { "Right", "Top", "Back", "Left", "Bottom", "Front" },
	SurfaceGuiSizingMode = { "FixedSize", "PixelsPerStud" },
	ScaleType = { "Stretch", "Slice", "Tile", "Fit", "Crop" },
	Font = { "GothamMedium", "GothamBold", "SourceSans" },
	CompressionAlgorithm = { "Zstd", "Gzip", "Deflate" },
	CameraType = { "Fixed", "Attach", "Watch", "Track", "Follow", "Custom", "Scriptable", "Orbital" },
	ContextActionPriority = { { "Low", 1000 }, { "Medium", 2000 }, { "Default", 2000 }, { "High", 3000 } },
	ContextActionResult = { "Sink", "Pass" },
	PlayerActions = { "CharacterForward", "CharacterBackward", "CharacterLeft", "CharacterRight", "CharacterJump" },
	KeyCode = { { "C", 99 }, { "F", 102 }, { "H", 104 }, { "M", 109 }, { "X", 120 } },
	ResamplerMode = { "Default", "Pixelated" },
	CreatorType = { "User", "Group" },
	UserInputType = { "MouseButton1", "MouseButton2", "MouseButton3", "MouseWheel", "MouseMovement", "Touch",
		"Keyboard" },
}
local Enum = {}
for enumName, items in ENUMS do
	local e = { _items = {} }
	for i, spec in items do
		local itemName, value = spec, i - 1
		if type(spec) == "table" then
			itemName, value = spec[1], spec[2]
		end
		local item = table.freeze({ Name = itemName, Value = value, EnumType = enumName })
		e[itemName] = item
		table.insert(e._items, item)
	end
	local list = e._items
	e._items = nil
	e.GetEnumItems = function()
		return table.clone(list)
	end
	Enum[enumName] = setmetatable(e, {
		__index = function(_, k)
			error(tostring(k) .. " is not a valid member of \"Enum." .. enumName .. "\"", 2)
		end,
	})
end
setmetatable(Enum, {
	__index = function(_, k)
		error(tostring(k) .. " is not a valid member of \"Enum\"", 2)
	end,
})

-- ------------------------------------------------------------------------------------------------------ signals

local function newSignal()
	local handlers = {}
	local sig = {}
	function sig:Connect(fn)
		local c = { fn = fn, Connected = true }
		function c:Disconnect()
			c.Connected = false
		end
		table.insert(handlers, c)
		return c
	end
	function sig:Fire(...)
		for _, c in table.clone(handlers) do
			if c.Connected then
				task.spawn(c.fn, ...)
			end
		end
	end
	return sig
end

-- ---------------------------------------------------------------------------------------------------- instances

local IS_A = {
	Part = { "Part", "BasePart", "PVInstance", "Instance" },
	SpawnLocation = { "SpawnLocation", "Part", "BasePart", "PVInstance", "Instance" },
	Model = { "Model", "PVInstance", "Instance" },
	Script = { "Script", "BaseScript", "LuaSourceContainer", "Instance" },
	LocalScript = { "LocalScript", "Script", "BaseScript", "LuaSourceContainer", "Instance" },
	ModuleScript = { "ModuleScript", "LuaSourceContainer", "Instance" },
}

local internals = setmetatable({}, { __mode = "k" })
local classMethods = {}
local InstanceMT = {}

local function I(inst)
	return internals[inst]
end

local function newInstance(className, peer)
	local inst = setmetatable({}, InstanceMT)
	internals[inst] = {
		ClassName = className,
		Name = className,
		Parent = nil,
		children = {},
		props = {},
		attrs = {},
		attrSignals = {},
		tags = {},
		peer = peer,
		childAdded = newSignal(),
		destroyed = false,
	}
	return inst
end

local methods = {}

InstanceMT.__index = function(inst, k)
	local s = internals[inst]
	if k == "ClassName" or k == "Name" or k == "Parent" then
		return s[k]
	end
	local m = methods[k] or (classMethods[s.ClassName] and classMethods[s.ClassName][k])
	if m then
		return m
	end
	local p = s.props[k]
	if p ~= nil then
		return p
	end
	for _, c in s.children do
		if internals[c].Name == k then
			return c
		end
	end
	error(tostring(k) .. " is not a valid member of " .. s.ClassName .. " \"" .. s.Name .. "\"", 2)
end

local function setParent(inst, parent)
	local s = internals[inst]
	if s.Parent == parent then
		return
	end
	if s.Parent then
		local siblings = internals[s.Parent].children
		local i = table.find(siblings, inst)
		if i then
			table.remove(siblings, i)
		end
	end
	s.Parent = parent
	if parent then
		table.insert(internals[parent].children, inst)
		internals[parent].childAdded:Fire(inst)
	end
end

InstanceMT.__newindex = function(inst, k, v)
	local s = internals[inst]
	if k == "Parent" then
		setParent(inst, v)
	elseif k == "Name" then
		s.Name = tostring(v)
	else
		s.props[k] = v
	end
end
InstanceMT.__tostring = function(inst)
	return internals[inst].Name
end

function methods.GetAttribute(inst, name)
	return I(inst).attrs[name]
end
function methods.SetAttribute(inst, name, value)
	local s = I(inst)
	if s.mirror then -- server-side Player: attributes replicate to that client's Player
		methods.SetAttribute(s.mirror, name, value)
	end
	if s.attrs[name] ~= value then
		s.attrs[name] = value
		local sig = s.attrSignals[name]
		if sig then
			sig:Fire()
		end
	end
end
function methods.GetAttributes(inst)
	return table.clone(I(inst).attrs)
end
function methods.GetAttributeChangedSignal(inst, name)
	local s = I(inst)
	s.attrSignals[name] = s.attrSignals[name] or newSignal()
	return s.attrSignals[name]
end
function methods.FindFirstChild(inst, name)
	for _, c in I(inst).children do
		if I(c).Name == name then
			return c
		end
	end
	return nil
end
function methods.WaitForChild(inst, name, timeout)
	local deadline = os.clock() + (timeout or math.huge)
	local warned = false
	while true do
		local c = methods.FindFirstChild(inst, name)
		if c then
			return c
		end
		if os.clock() >= deadline then
			return nil
		end
		if not warned and timeout == nil and os.clock() > deadline - math.huge + 5 then
			warned = true
		end
		task.wait(0.03)
	end
end
function methods.GetChildren(inst)
	return table.clone(I(inst).children)
end
function methods.GetDescendants(inst)
	local out = {}
	local function walk(x)
		for _, c in I(x).children do
			table.insert(out, c)
			walk(c)
		end
	end
	walk(inst)
	return out
end
function methods.IsA(inst, className)
	local s = I(inst)
	local chain = IS_A[s.ClassName]
	if chain then
		return table.find(chain, className) ~= nil
	end
	return className == s.ClassName or className == "Instance"
end
function methods.Destroy(inst)
	local s = I(inst)
	s.destroyed = true
	setParent(inst, nil)
	for _, c in table.clone(s.children) do
		methods.Destroy(c)
	end
end

-- -------------------------------------------------------------------------------------------------------- peers

local server -- the game server peer
local clients = {} -- name -> client peer
local clientOrder = {}

local function argCopy(...)
	local n = select("#", ...)
	local packed = { n = n }
	local bytes = 0
	for i = 1, n do
		local v = select(i, ...)
		if type(v) == "buffer" then
			local b = buffer.create(buffer.len(v))
			buffer.copy(b, 0, v)
			v = b
			bytes += buffer.len(b)
		elseif type(v) == "string" then
			bytes += #v
		elseif type(v) == "number" then
			bytes += 8
		end
		packed[i] = v
	end
	return packed, bytes
end

local function deliverToClient(peer, replica, packed, bytes)
	if not peer.alive then
		return
	end
	table.insert(peer.inbox, { replica, packed, bytes })
	if not peer.pumping then
		peer.pumping = true
		task.defer(function()
			while #peer.inbox > 0 do
				local item = table.remove(peer.inbox, 1)
				if peer.throttle then -- emulated slow connection: bytes/s, in order (reliable remotes queue up)
					task.wait(item[3] / peer.throttle)
				end
				if not peer.alive then
					break
				end
				peer.recvBytes += item[3]
				peer.recvMessages += 1
				I(item[1]).props.OnClientEvent:Fire(table.unpack(item[2], 1, item[2].n))
			end
			peer.pumping = false
		end)
	end
end

classMethods.RemoteEvent = {
	FireClient = function(remote, player, ...)
		local s = I(remote)
		assert(s.peer == server, "FireClient can only be called from the server")
		local peer = server.peerOfPlayer[player]
		if peer == nil then
			error("FireClient: player argument must be a Player object", 2)
		end
		local packed, bytes = argCopy(...)
		local replica = s.replicas[peer]
		if replica then
			deliverToClient(peer, replica, packed, bytes)
		end
	end,
	FireAllClients = function(remote, ...)
		local s = I(remote)
		assert(s.peer == server, "FireAllClients can only be called from the server")
		for _, name in clientOrder do
			local peer = clients[name]
			local replica = s.replicas[peer]
			if peer.alive and replica then
				local packed, bytes = argCopy(...)
				deliverToClient(peer, replica, packed, bytes)
			end
		end
	end,
	FireServer = function(replica, ...)
		local s = I(replica)
		assert(s.peer ~= server, "FireServer can only be called from a client")
		local packed = argCopy(...)
		if packed[1] == "ack" then
			s.peer.lastAck = { packed[2], packed[3], packed[4] }
			s.peer.acks = (s.peer.acks or 0) + 1
		end
		local serverRemote = s.serverRemote
		local player = s.peer.serverPlayer
		task.defer(function()
			if s.peer.alive then
				I(serverRemote).props.OnServerEvent:Fire(player, table.unpack(packed, 1, packed.n))
			end
		end)
	end,
}

local function replicateRemote(serverRemote, peer)
	local s = I(serverRemote)
	if s.replicas[peer] then
		return
	end
	local replica = newInstance("RemoteEvent", peer)
	I(replica).props.OnClientEvent = newSignal()
	I(replica).serverRemote = serverRemote
	I(replica).attrs = s.attrs -- attributes replicate server -> client (shared table: read-only use on clients)
	replica.Name = s.Name
	s.replicas[peer] = replica
	replica.Parent = peer.game.ReplicatedStorage
end

-- ----------------------------------------------------------------------------------------------- engine services

local httpRequests = { count = 0, failures = 0, bytes = 0, times = {} }

local SecretMT = {}
SecretMT.__index = SecretMT
SecretMT.__tostring = function()
	return "Secret"
end
function SecretMT.AddPrefix(sec, p)
	return setmetatable({ value = rawget(sec, "value"), prefix = p .. rawget(sec, "prefix"), suffix = rawget(sec, "suffix") }, SecretMT)
end
function SecretMT.AddSuffix(sec, p)
	return setmetatable({ value = rawget(sec, "value"), prefix = rawget(sec, "prefix"), suffix = rawget(sec, "suffix") .. p }, SecretMT)
end

local B64 = {}
do
	local alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	for i = 1, 64 do
		B64[string.byte(alphabet, i)] = i - 1
	end
end
local function base64Decode(src)
	local n = buffer.len(src)
	if n % 4 ~= 0 then
		error("Base64Decode: invalid input length", 2)
	end
	local pad = 0
	if n > 0 and buffer.readu8(src, n - 1) == 61 then
		pad += 1
		if buffer.readu8(src, n - 2) == 61 then
			pad += 1
		end
	end
	local out = buffer.create(n // 4 * 3 - pad)
	local o = 0
	for i = 0, n - 1, 4 do
		local v = 0
		for j = 0, 3 do
			local c = buffer.readu8(src, i + j)
			local d = B64[c]
			if d == nil then
				if c == 61 and i + j >= n - pad then
					d = 0
				else
					error("Base64Decode: invalid character", 2)
				end
			end
			v = v * 64 + d
		end
		for j = 2, 0, -1 do
			if o + (2 - j) < buffer.len(out) then
				buffer.writeu8(out, o + (2 - j), bit32.band(bit32.rshift(v, j * 8), 255))
			end
		end
		o += 3
	end
	return out
end

local function makeServices(peer)
	local svc = {}
	svc.HttpService = {
		GetSecret = function(_, key)
			if peer ~= server then
				error("Can't find secret with given key", 2)
			end
			local v = peer.secrets[key]
			if v == nil then
				error("Can't find secret with given key", 2)
			end
			return setmetatable({ value = v, prefix = "", suffix = "" }, SecretMT)
		end,
		RequestAsync = function(_, opts)
			if peer ~= server then
				error("Http requests can only be executed by game server", 2)
			end
			if not peer.httpEnabled then
				error("Http requests are not enabled. Enable via game settings", 2)
			end
			local now = os.clock()
			local times = httpRequests.times
			while #times > 0 and now - times[1] > 60 do
				table.remove(times, 1)
			end
			if #times >= 500 then
				error("Number of requests exceeded limit", 2)
			end
			table.insert(times, now)
			local url = opts.Url
			if string.sub(url, 1, #PUBLIC_URL) ~= PUBLIC_URL then
				httpRequests.failures += 1
				error("HttpError: DnsResolve", 2)
			end
			local host = string.match(url, "^https?://([^/:]+)") or ""
			url = BASE_URL .. string.sub(url, #PUBLIC_URL + 1)
			local headers = {}
			for k, v in opts.Headers or {} do
				if getmetatable(v) == SecretMT and not domainAllows(SECRET_DOMAIN, host) then
					error("This secret cannot be used for a specified domain", 2)
				end
				if getmetatable(v) == SecretMT then
					headers[k] = rawget(v, "prefix") .. rawget(v, "value") .. rawget(v, "suffix")
				else
					headers[k] = tostring(v)
				end
			end
			httpRequests.count += 1
			local ok, res = pcall(net.request, { url = url, method = opts.Method or "GET", headers = headers })
			if not ok then
				httpRequests.failures += 1
				error("HttpError: ConnectFail", 2)
			end
			httpRequests.bytes += #res.body
			local body = res.body
			if ENV.RLPS_EMU_TEXT_BODIES == "1" then
				-- simulate an HTTP stack that treats bodies as text: every byte >= 0x80 becomes '?'
				body = string.gsub(body, "[\128-\255]", "?")
			end
			return {
				Success = res.ok,
				StatusCode = res.statusCode,
				StatusMessage = res.statusMessage,
				Headers = res.headers,
				Body = body,
			}
		end,
	}
	svc.EncodingService = {
		Base64Decode = function(_, input)
			assert(type(input) == "buffer", "Base64Decode expects a buffer")
			return base64Decode(input)
		end,
		GetDecompressedBufferSize = function(_, input, algorithm)
			-- zstd frame header (RFC 8878 §3.1.1): magic, frame header descriptor, optional window/dict id, FCS
			assert(type(input) == "buffer", "GetDecompressedBufferSize expects a buffer")
			if algorithm ~= Enum.CompressionAlgorithm.Zstd then
				error("unsupported algorithm in emulator", 2)
			end
			if buffer.len(input) < 6 or buffer.readu32(input, 0) ~= 0xFD2FB528 then
				return nil
			end
			local fhd = buffer.readu8(input, 4)
			local fcsFlag = bit32.rshift(fhd, 6)
			local single = bit32.band(bit32.rshift(fhd, 5), 1) == 1
			local dictFlag = bit32.band(fhd, 3)
			local off = 5 + (if single then 0 else 1) + ({ 0, 1, 2, 4 })[dictFlag + 1]
			local fcsSize = ({ if single then 1 else 0, 2, 4, 8 })[fcsFlag + 1]
			if fcsSize == 0 or buffer.len(input) < off + fcsSize then
				return nil
			end
			if fcsSize == 1 then
				return buffer.readu8(input, off)
			elseif fcsSize == 2 then
				return buffer.readu16(input, off) + 256
			elseif fcsSize == 4 then
				return buffer.readu32(input, off)
			end
			return buffer.readu32(input, off) + buffer.readu32(input, off + 4) * 4294967296
		end,
		DecompressBuffer = function(_, input, algorithm)
			assert(type(input) == "buffer", "DecompressBuffer expects a buffer")
			if algorithm ~= Enum.CompressionAlgorithm.Zstd then
				error("unsupported algorithm in emulator", 2)
			end
			return buffer.fromstring(serde.decompress("zstd", input))
		end,
	}
	svc.AssetService = {
		CreateEditableImage = function(_, options)
			local size = (options and options.Size) or Vector2.new(512, 512)
			local w, h = size.X, size.Y
			if w ~= math.floor(w) or h ~= math.floor(h) or w < 1 or h < 1 or w > 1024 or h > 1024 then
				error("CreateEditableImage: invalid size", 2)
			end
			local img = newInstance("EditableImage", peer)
			I(img).pixels = buffer.create(w * h * 4)
			I(img).props.Size = Vector2.new(w, h)
			peer.imagesCreated += 1
			return img
		end,
	}
	peer.cas = {}
	svc.ContextActionService = {
		BindActionAtPriority = function(_, name, fn, _touch, priority, ...)
			assert(type(fn) == "function" and type(priority) == "number", "BindActionAtPriority arguments")
			peer.cas[name] = { priority = priority, inputs = select("#", ...) }
		end,
		UnbindAction = function(_, name)
			peer.cas[name] = nil
		end,
	}
	svc.UserInputService = { InputBegan = newSignal() }
	svc.CollectionService = {
		GetTagged = function(_, tag)
			local out = {}
			for _, d in methods.GetDescendants(peer.game) do
				if table.find(I(d).tags, tag) then
					table.insert(out, d)
				end
			end
			return out
		end,
		GetInstanceAddedSignal = function()
			return newSignal()
		end,
		GetInstanceRemovedSignal = function()
			return newSignal()
		end,
	}
	return svc
end

classMethods.EditableImage = {
	WritePixelsBuffer = function(img, position, size, buf)
		local s = I(img)
		if ENV.RLPS_EMU_IMAGE_API_DISABLED == "1" then
			-- what a published game without "Allow Mesh / Image APIs" does: creation works, writing fails
			error("EditableImage is not enabled for this experience", 2)
		end
		if s.destroyed then
			error("EditableImage was destroyed", 2)
		end
		local W, H = s.props.Size.X, s.props.Size.Y
		local x, y, w, h = position.X, position.Y, size.X, size.Y
		if x ~= math.floor(x) or y ~= math.floor(y) or w ~= math.floor(w) or h ~= math.floor(h) then
			error("WritePixelsBuffer: non-integer rectangle", 2)
		end
		if x < 0 or y < 0 or w < 1 or h < 1 or x + w > W or y + h > H then
			error("WritePixelsBuffer: rectangle outside the image", 2)
		end
		if buffer.len(buf) ~= w * h * 4 then
			error("WritePixelsBuffer: buffer size does not match the rectangle", 2)
		end
		for row = 0, h - 1 do
			buffer.copy(s.pixels, ((y + row) * W + x) * 4, buf, row * w * 4, w * 4)
		end
		s.peer.pixelWrites += 1
	end,
}

-- ------------------------------------------------------------------------------------------- DataModel building

local projectJson = serde.decode("json", fs.readFile(REPO .. "/default.project.json"))
local SERVICES = {
	HttpService = true,
	ReplicatedStorage = true,
	ServerScriptService = true,
	StarterPlayer = true,
	Workspace = true,
	Players = true,
	RunService = true,
	AssetService = true,
	CollectionService = true,
	EncodingService = true,
	ContextActionService = true,
	Lighting = true,
	UserInputService = true,
}

local function convertProp(name, v)
	if type(v) == "table" and name == "Size" and #v == 3 then
		return Vector3.new(v[1], v[2], v[3])
	end
	return v
end

local function applyProps(inst, props)
	for k, v in props or {} do
		if k == "Tags" then
			I(inst).tags = table.clone(v)
		elseif k == "CFrame" then
			I(inst).props.CFrame = CFrame.new(table.unpack(v))
			I(inst).props.Position = Vector3.new(v[1], v[2], v[3])
		else
			I(inst).props[k] = convertProp(k, v)
		end
	end
end

local function buildModel(peer, node, name)
	local inst = newInstance(node.ClassName, peer)
	inst.Name = node.Name or name
	applyProps(inst, node.Properties)
	for k, v in node.attributes or node.Attributes or {} do
		I(inst).attrs[k] = v
	end
	for _, child in node.Children or {} do
		buildModel(peer, child, child.Name).Parent = inst
	end
	return inst
end

local function buildNode(peer, node, name, parent, isClient)
	local inst
	if node["$path"] then
		local path = node["$path"]
		if string.match(path, "%.model%.json$") then
			inst = buildModel(peer, serde.decode("json", fs.readFile(REPO .. "/" .. path)), name)
		else
			local class = if string.match(path, "%.server%.luau$")
				then "Script"
				elseif string.match(path, "%.client%.luau$") then "LocalScript"
				else "ModuleScript"
			inst = newInstance(class, peer)
			I(inst).source = fs.readFile(REPO .. "/" .. path)
			I(inst).path = path
		end
	else
		inst = newInstance(node["$className"] or name, peer)
	end
	inst.Name = name
	applyProps(inst, node["$properties"])
	for k, v in node["$attributes"] or {} do
		I(inst).attrs[k] = v
	end
	for childName, child in node do
		if string.sub(childName, 1, 1) ~= "$" and type(child) == "table" then
			if not (isClient and parent == nil and childName == "ServerScriptService") then
				buildNode(peer, child, childName, inst, isClient)
			end
		end
	end
	if parent then
		inst.Parent = parent
	end
	return inst
end

local function newPeer(name, isClient)
	local peer = {
		name = name,
		isClient = isClient,
		alive = true,
		modules = {},
		inbox = {},
		pumping = false,
		recvBytes = 0,
		recvMessages = 0,
		pixelWrites = 0,
		imagesCreated = 0,
		errors = {},
		secrets = {},
		peerOfPlayer = {},
	}
	local game = newInstance("DataModel", peer)
	game.Name = "Game"
	peer.game = game
	-- services: built from the project tree (client copies exclude ServerScriptService), engine services added
	for childName, child in projectJson.tree do
		if string.sub(childName, 1, 1) ~= "$" then
			if not (isClient and childName == "ServerScriptService") then
				buildNode(peer, child, childName, nil, isClient).Parent = game
			end
		end
	end
	for svcName in SERVICES do
		if methods.FindFirstChild(game, svcName) == nil then
			newInstance(svcName, peer).Parent = game
		end
	end
	local services = makeServices(peer)
	for svcName, impl in services do
		local inst = methods.FindFirstChild(game, svcName)
		for k, fn in impl do
			I(inst).props[k] = fn
		end
	end
	peer.httpEnabled = I(game.HttpService).props.HttpEnabled == true
	I(game.Players).props.PlayerRemoving = newSignal()
	I(game.Players).props.PlayerAdded = newSignal()
	I(game.Players).props.GetPlayers = function(players)
		local out = {}
		for _, c in I(players).children do
			if I(c).ClassName == "Player" then
				table.insert(out, c)
			end
		end
		return out
	end
	I(game.RunService).props.Heartbeat = newSignal()
	I(game).props.CreatorId = 0 -- an unpublished place: no owner UserId
	I(game).props.CreatorType = Enum.CreatorType.User
	I(game).props.GetService = function(g, svcName)
		local s = methods.FindFirstChild(g, svcName)
		if s == nil or not SERVICES[svcName] then
			error("'" .. tostring(svcName) .. "' is not a valid Service name", 2)
		end
		return s
	end
	peer.workspace = game.Workspace
	return peer
end

-- ---------------------------------------------------------------------------------------------- script running

local function makeEnv(peer, scriptInst, requireFn)
	return {
		game = peer.game,
		workspace = peer.workspace,
		script = scriptInst,
		Instance = {
			new = function(className)
				local inst = newInstance(className, peer)
				if className == "RemoteEvent" then
					I(inst).props.OnServerEvent = newSignal()
					I(inst).props.OnClientEvent = newSignal()
					I(inst).replicas = {}
				elseif className == "TextButton" or className == "ImageButton" then
					I(inst).props.Activated = newSignal()
				end
				return inst
			end,
		},
		Enum = Enum,
		Vector2 = Vector2,
		Vector3 = Vector3,
		CFrame = CFrame,
		UDim2 = UDim2,
		Color3 = Color3,
		Content = Content,
		task = task,
		require = requireFn,
		warn = function(...)
			log("[" .. peer.name .. "] WARN", ...)
		end,
		print = function(...)
			log("[" .. peer.name .. "]", ...)
		end,
	}
end

local function requireModule(peer, moduleInst)
	if type(moduleInst) ~= "table" or getmetatable(moduleInst) ~= InstanceMT or I(moduleInst).ClassName ~= "ModuleScript" then
		error("Attempted to call require with invalid argument(s).", 2)
	end
	local cached = peer.modules[moduleInst]
	if cached ~= nil then
		return cached.value
	end
	local s = I(moduleInst)
	local env = makeEnv(peer, moduleInst, function(m)
		return requireModule(peer, m)
	end)
	local fn = luau.load(s.source, { debugName = peer.name .. ":" .. s.path, environment = env })
	local value = fn()
	peer.modules[moduleInst] = { value = value }
	return value
end

local function runScript(peer, scriptInst)
	local s = I(scriptInst)
	local env = makeEnv(peer, scriptInst, function(m)
		return requireModule(peer, m)
	end)
	task.spawn(function()
		local ok, err = pcall(function()
			local fn = luau.load(s.source, { debugName = peer.name .. ":" .. s.path, environment = env })
			fn()
		end)
		if not ok then
			table.insert(peer.errors, tostring(err))
			log("[" .. peer.name .. "] SCRIPT ERROR", err)
		end
	end)
end

-- ------------------------------------------------------------------------------------------------- game server

server = newPeer("server", false)
server.secrets.rlps_token = SECRET_VALUE
do
	local serverScript = methods.FindFirstChild(server.game.ServerScriptService.Rlps, "RlpsServer")
	serverScript:SetAttribute("FrameServiceUrl", PUBLIC_URL)
	for k, v in ENV do -- RLPS_ATTR_<Name>=<value>: override a server configuration attribute (test knobs)
		local attrName = string.match(k, "^RLPS_ATTR_(%w+)$")
		if attrName then
			serverScript:SetAttribute(attrName, tonumber(v) or v)
		end
	end
	-- replicate every RemoteEvent the server parents to ReplicatedStorage
	I(server.game.ReplicatedStorage).childAdded:Connect(function(child)
		if I(child).ClassName == "RemoteEvent" then
			for _, name in clientOrder do
				if clients[name].alive then
					replicateRemote(child, clients[name])
				end
			end
		end
	end)
	task.spawn(function() -- server Heartbeat (~60 Hz)
		local last = os.clock()
		while true do
			task.wait(1 / 60)
			local now = os.clock()
			I(server.game.RunService).props.Heartbeat:Fire(now - last)
			last = now
		end
	end)
	-- any script error is collected as a test failure
	for _, d in methods.GetDescendants(server.game.ServerScriptService) do
		if I(d).ClassName == "Script" then
			runScript(server, d)
		end
	end
end

local nextUserId = 1001
local function join(name)
	if clients[name] then
		return
	end
	local peer = newPeer(name, true)
	peer.throttle = tonumber(ENV["RLPS_EMU_THROTTLE_" .. name]) -- optional bytes/s for this client
	clients[name] = peer
	table.insert(clientOrder, name)
	-- client-side LocalPlayer + PlayerGui; camera placed in front of the TV
	local player = newInstance("Player", peer)
	player.Name = name
	I(player).props.UserId = nextUserId
	I(player).props.Character = false -- no avatar in the emulator
	local gui = newInstance("PlayerGui", peer)
	gui.Name = "PlayerGui"
	gui.Parent = player
	local scripts = newInstance("PlayerScripts", peer)
	scripts.Name = "PlayerScripts"
	scripts.Parent = player
	player.Parent = peer.game.Players
	I(peer.game.Players).props.LocalPlayer = player
	local camera = newInstance("Camera", peer)
	camera.Name = "Camera"
	-- the spawn-side viewer looks at the TV screen (Workspace.RlpsTV.Screen centre = 0, 8, -30)
	I(camera).props.CFrame = CFrame.lookAt(Vector3.new(0, 6, -12), Vector3.new(0, 8, -30))
	I(camera).props.FieldOfView = 70
	I(camera).props.ViewportSize = Vector2.new(1280, 720)
	I(camera).props.CameraType = Enum.CameraType.Custom
	I(camera).props.CameraSubject = false
	camera.Parent = peer.workspace
	I(peer.workspace).props.CurrentCamera = camera
	-- server-side Player object
	local sp = newInstance("Player", server)
	sp.Name = name
	I(sp).props.UserId = nextUserId
	nextUserId += 1
	server.peerOfPlayer[sp] = peer
	peer.serverPlayer = sp
	I(sp).mirror = player
	sp.Parent = server.game.Players
	I(server.game.Players).props.PlayerAdded:Fire(sp)
	-- replicate existing remotes, then start the client scripts (StarterPlayerScripts are copied to PlayerScripts)
	for _, c in I(server.game.ReplicatedStorage).children do
		if I(c).ClassName == "RemoteEvent" then
			replicateRemote(c, peer)
		end
	end
	for _, d in methods.GetDescendants(peer.game.StarterPlayer) do
		if I(d).ClassName == "LocalScript" then
			runScript(peer, d)
		end
	end
	task.spawn(function()
		local last = os.clock()
		while peer.alive do
			task.wait(1 / 60)
			local now = os.clock()
			I(peer.game.RunService).props.Heartbeat:Fire(now - last)
			last = now
		end
	end)
	log("client joined:", name)
end

local function leave(name)
	local peer = clients[name]
	if peer == nil or not peer.alive then
		return
	end
	peer.alive = false
	local sp = peer.serverPlayer
	sp.Parent = nil
	I(server.game.Players).props.PlayerRemoving:Fire(sp)
	log("client left:", name)
end

-- ------------------------------------------------------------------------------------------ observation/output

local function findScreenGui(peer)
	for _, c in I(peer.game.Players.LocalPlayer.PlayerGui).children do
		if I(c).Name == "RlpsScreenGui" then
			return c
		end
	end
	return nil
end

local function clientState(peer)
	local st = {
		alive = peer.alive,
		recv_bytes = peer.recvBytes,
		queued_messages = #peer.inbox,
		last_ack = peer.lastAck,
		script_attributes = (function()
			for _, d in methods.GetDescendants(peer.game.StarterPlayer) do
				if I(d).ClassName == "LocalScript" then
					return methods.GetAttributes(d)
				end
			end
			return nil
		end)(),
		acks = peer.acks or 0,
		recv_messages = peer.recvMessages,
		pixel_writes = peer.pixelWrites,
		images_created = peer.imagesCreated,
		errors = peer.errors,
		gui = false,
	}
	local gui = findScreenGui(peer)
	if gui then
		local bg = I(gui).props
		st.gui = true
		st.face = I(gui).props.Face and I(gui).props.Face.Name
		st.adornee = I(gui).props.Adornee and I(I(gui).props.Adornee).Name
		local background = methods.FindFirstChild(gui, "Background")
		local picture = methods.FindFirstChild(background, "Picture")
		local status = methods.FindFirstChild(background, "Status")
		local badge = methods.FindFirstChild(background, "LiveBadge")
		st.picture_visible = I(picture).props.Visible == true
		st.status_visible = I(status).props.Visible == true
		st.status_text = I(status).props.Text
		st.badge_visible = I(badge).props.Visible == true
		local content = I(picture).props.ImageContent
		local img = content and content.Object
		if img and not I(img).destroyed then
			st.image_w = I(img).props.Size.X
			st.image_h = I(img).props.Size.Y
			st.image_sha256 = serde.hash("sha256", I(img).pixels)
		else
			st.image_w, st.image_h = 0, 0
		end
		local _ = bg
	end
	return st, gui
end

local function findGui(peer, name)
	for _, c in I(peer.game.Players.LocalPlayer.PlayerGui).children do
		if I(c).Name == name then
			return c
		end
	end
	return nil
end

local function contentOf(inst)
	local content = inst and I(inst).props.ImageContent
	return content and content.Object
end

-- viewer modes: overlays, cinema camera, controls (what a player would see)
local function viewState(peer, tvImage)
	local v = {}
	local controls = findGui(peer, "RlpsViewerControls")
	v.controls_enabled = controls ~= nil and I(controls).props.Enabled == true
	local shown = {}
	local barFrame = controls and methods.FindFirstChild(controls, "Bar")
	for _, c in if barFrame then I(barFrame).children else {} do
		if I(c).props.Visible ~= false then
			table.insert(shown, I(c).Name)
		end
	end
	table.sort(shown)
	v.buttons = table.concat(shown, ",")
	local hide = controls and methods.FindFirstChild(controls, "HideButton")
	v.hide_text = hide and I(hide).props.Text
	local mod = findGui(peer, "RlpsModerator")
	v.moderator_enabled = mod ~= nil and I(mod).props.Enabled == true
	local modButton = mod and methods.FindFirstChild(mod, "ModHideButton")
	v.moderator_text = modButton and I(modButton).props.Text
	for key, name, holder in
		string.gmatch("fullscreen=RlpsFullscreen/Background mini=RlpsMiniPlayer/Window cinema=RlpsCinema/", "(%a+)=(%a+)/(%a*)")
	do
		local g = findGui(peer, name)
		v[key .. "_enabled"] = g ~= nil and I(g).props.Enabled == true
		if g and holder ~= "" then
			local h = methods.FindFirstChild(g, holder)
			local pic = h and methods.FindFirstChild(h, "Picture")
			v[key .. "_same_image"] = pic ~= nil and tvImage ~= nil and contentOf(pic) == tvImage
			v[key .. "_picture_visible"] = pic ~= nil and I(pic).props.Visible == true
			v[key .. "_scale"] = pic and I(pic).props.ScaleType and I(pic).props.ScaleType.Name
			v[key .. "_resample"] = pic and I(pic).props.ResampleMode and I(pic).props.ResampleMode.Name
		end
	end
	local cam = peer.workspace.CurrentCamera
	local cf = I(cam).props.CFrame
	local centre = Vector3.new(0, 8, -30 + 0.1) -- screen face centre (front face, depth 0.2)
	local toTv = centre - cf.Position
	v.camera_type = I(cam).props.CameraType.Name
	v.camera_distance = toTv.Magnitude
	v.camera_aim = cf.LookVector:Dot(toTv.Unit)
	v.blur = methods.FindFirstChild(peer.game.Lighting, "RlpsCinemaBlur") ~= nil
	v.movement_held = peer.cas.RlpsCinemaHoldStill ~= nil
	return v
end

local function writeState()
	local serverScript = methods.FindFirstChild(server.game.ServerScriptService.Rlps, "RlpsServer")
	local state = {
		t = os.clock() - started,
		server = {
			attributes = methods.GetAttributes(serverScript),
			errors = server.errors,
			http_requests = httpRequests.count,
			http_failures = httpRequests.failures,
			http_body_bytes = httpRequests.bytes,
		},
		clients = {},
	}
	for _, name in clientOrder do
		local st, gui = clientState(clients[name])
		local tvImage = nil
		if gui then
			tvImage = contentOf(methods.FindFirstChild(methods.FindFirstChild(gui, "Background"), "Picture"))
		end
		st.view = viewState(clients[name], tvImage)
		state.clients[name] = st
	end
	fs.writeFile(OUT .. "/state.json.tmp", serde.encode("json", state))
	-- Windows: the replace fails while the test reads the file; the next cycle (0.1 s) writes it again
	pcall(fs.move, OUT .. "/state.json.tmp", OUT .. "/state.json", true)
end

local function snapshot(tag)
	for _, name in clientOrder do
		local peer = clients[name]
		local _, gui = clientState(peer)
		if gui then
			local picture = methods.FindFirstChild(methods.FindFirstChild(gui, "Background"), "Picture")
			local content = I(picture).props.ImageContent
			local img = content and content.Object
			if img and not I(img).destroyed then
				fs.writeFile(OUT .. "/" .. name .. "-" .. tag .. ".rgba", I(img).pixels)
			end
		end
	end
	fs.writeFile(OUT .. "/" .. tag .. ".done", "ok")
end

local ok, err = pcall(function()
	while os.clock() - started < MAX_SECONDS do
		for _, entry in fs.readDir(OUT) do
			local kind, arg = string.match(entry, "^(%a+)%-([%w_]+)$")
			if entry == "quit" then
				writeState()
				log("quit")
				process.exit(0)
			elseif kind == "join" then
				fs.removeFile(OUT .. "/" .. entry)
				join(arg)
			elseif kind == "leave" then
				fs.removeFile(OUT .. "/" .. entry)
				leave(arg)
			elseif kind == "snap" then
				fs.removeFile(OUT .. "/" .. entry)
				snapshot(arg)
			end
			-- press-<client>-<ButtonName> | key-<client>-<KeyCode> | look-<client>-<away|tv>
			local cmd, who, what = string.match(entry, "^(%a+)%-(%w+)%-(%w+)$")
			local peer = who and clients[who]
			if peer and (cmd == "press" or cmd == "key" or cmd == "look" or cmd == "fire") then
				fs.removeFile(OUT .. "/" .. entry)
				if cmd == "press" then
					local found = false
					for _, d in methods.GetDescendants(peer.game.Players.LocalPlayer.PlayerGui) do
						if I(d).Name == what and I(d).ClassName == "TextButton" then
							I(d).props.Activated:Fire()
							found = true
						end
					end
					if not found then
						log("press: no button", what)
					end
				elseif cmd == "fire" then -- a (possibly malicious) client sends a raw message: modhide / modshow / leave
					local remote = methods.FindFirstChild(peer.game.ReplicatedStorage, "RlpsFrames")
					local args = ({ modhide = { "moderate", "hide" }, modshow = { "moderate", "show" },
						leave = { "leave" } })[what]
					if remote and args then
						classMethods.RemoteEvent.FireServer(remote, table.unpack(args))
					end
				elseif cmd == "key" then
					local input = { KeyCode = Enum.KeyCode[what], UserInputType = Enum.UserInputType.Keyboard }
					I(peer.game.UserInputService).props.InputBegan:Fire(input, false)
				else
					local cam = peer.workspace.CurrentCamera
					local target = if what == "away" then Vector3.new(0, 6, 40) else Vector3.new(0, 8, -30)
					I(cam).props.CFrame = CFrame.lookAt(Vector3.new(0, 6, -12), target)
				end
			end
		end
		writeState()
		task.wait(0.1)
	end
end)
if not ok then
	log("emulator failure:", err)
	process.exit(3)
end
log("max runtime reached")
process.exit(4)
