--!strict
-- RLPS server script (T-0012): the single frame-service poll loop of this experience server + RemoteEvent fan-out.
--
-- Polls GET <FrameServiceUrl>/v1/frames (desktop/rlps/server.py) with the Bearer token stored as an experience secret,
-- feeds every container to RlpsRelayCore and forwards the resulting messages, in order, over one reliable RemoteEvent:
--   server -> client: ("status", status, detail?) | ("part", record: buffer) | ("advance", sessionId, fromSeq, toSeq)
--                     | ("reset")  [start of a sync: drop local state, a status + keyframe chain follows]
--   client -> server: ("sync")     [late joiner / desynced client: send me the relay history]
-- EditableImage changes never replicate, so every client rebuilds the picture itself (RlpsClient.client.luau).
--
-- Layout (default.project.json): ServerScriptService.Rlps = this Script + RlpsRelayCore + RlpsProtocol + RlpsDecoder +
-- RlpsBase64 (server copies of the shared modules). The RemoteEvent ReplicatedStorage.RlpsFrames is created here.
--
-- Configuration = attributes on this script (Studio: select the script, edit Attributes; no code changes needed):
--   FrameServiceUrl      string  public HTTPS base URL of the frame service (tunnel), e.g. https://xyz.trycloudflare.com
--   SecretName           string  experience secret holding the token (default "rlps_token"; Creator Hub > Secrets)
--   PollWaitMs           number  long-poll wait sent to the service (default 15000, service maximum 25000)
--   MinPollInterval      number  seconds between poll starts (default 0.2 => <= 300 requests/min; HttpService allows 500)
--   StoppedPollInterval  number  seconds between polls while the owner is not sharing (default 3)
--   ViewerUserIds        string  optional comma-separated UserIds allowed to see the screen (empty = everyone)
-- Read-only status attributes written here: Status, StatusDetail, Containers, ForwardedBytes, Dropped, LastError.

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local RelayCore = require(script.Parent.RlpsRelayCore)
local Base64 = require(script.Parent.RlpsBase64)

local REMOTE_NAME = "RlpsFrames"
local SYNC_COOLDOWN = 2 -- seconds between history syncs for one player
local KEYFRAME_COOLDOWN = 2 -- seconds between keyframe requests caused by clients
local HISTORY_LIMIT = 384 * 1024 -- late-joiner history bound (bytes); beyond it the next poll asks for a keyframe

local function attr(name: string, default: any): any
	local v = script:GetAttribute(name)
	if v == nil then
		script:SetAttribute(name, default)
		return default
	end
	return v
end

local remote = ReplicatedStorage:FindFirstChild(REMOTE_NAME) :: RemoteEvent?
if remote == nil then
	local r = Instance.new("RemoteEvent")
	r.Name = REMOTE_NAME
	r.Parent = ReplicatedStorage
	remote = r
end
local frames = remote :: RemoteEvent

local relay = RelayCore.new({ historyLimitBytes = HISTORY_LIMIT, errorThreshold = 3 })

-- ------------------------------------------------------------------------------------------------- viewers / fan-out

local allowed: { [number]: boolean }? = nil
local function readViewers()
	local raw = tostring(attr("ViewerUserIds", ""))
	local set: { [number]: boolean } = {}
	local any = false
	for id in string.gmatch(raw, "%d+") do
		set[tonumber(id) :: number] = true
		any = true
	end
	allowed = if any then set else nil
end
readViewers()
script:GetAttributeChangedSignal("ViewerUserIds"):Connect(readViewers)

local function canView(player: Player): boolean
	local set = allowed
	return set == nil or set[player.UserId] == true
end

local function fire(target: Player?, ...: any)
	if target then
		if canView(target) then
			frames:FireClient(target, ...)
		end
	elseif allowed == nil then
		frames:FireAllClients(...)
	else
		for _, p in Players:GetPlayers() do
			if canView(p) then
				frames:FireClient(p, ...)
			end
		end
	end
end

local function send(target: Player?, m: RelayCore.Message)
	if m.kind == "records" then
		for _, record in m.records :: { buffer } do
			fire(target, "part", record)
		end
	elseif m.kind == "advance" then
		fire(target, "advance", m.sessionId, m.fromSeq, m.toSeq)
	else
		fire(target, "status", m.status, m.detail)
	end
end

local function broadcast(messages: { RelayCore.Message }?)
	if messages then
		for _, m in messages do
			send(nil, m)
		end
	end
	script:SetAttribute("Status", relay.status)
	script:SetAttribute("StatusDetail", relay.detail or "")
	script:SetAttribute("Containers", relay.containers)
	script:SetAttribute("ForwardedBytes", relay.forwardedBytes)
	script:SetAttribute("Dropped", relay.dropped)
end

-- Server-side status that does not come from the frame service (configuration problems).
local function setServerStatus(status: RelayCore.Status, detail: string?)
	if relay.status ~= status or relay.detail ~= detail then
		relay.status, relay.detail = status, detail
		broadcast({ { kind = "status", status = status, detail = detail } :: RelayCore.Message })
	end
end

-- ------------------------------------------------------------------------------------------------------ client sync

local lastSync: { [Player]: number } = {}
local lastKeyframeRequest = 0

local function syncPlayer(player: Player)
	if not canView(player) then
		frames:FireClient(player, "status", "error", "not authorized to view this screen")
		return
	end
	local now = os.clock()
	if now - (lastSync[player] or -math.huge) < SYNC_COOLDOWN then
		return
	end
	lastSync[player] = now
	frames:FireClient(player, "reset")
	local messages = relay:syncMessages()
	for _, m in messages do
		send(player, m)
	end
	if #messages <= 1 and relay.status == "live" and now - lastKeyframeRequest >= KEYFRAME_COOLDOWN then
		lastKeyframeRequest = now
		relay:requestKeyframe() -- no keyframe in the history yet: the next poll asks for one (broadcast to all)
	end
end

frames.OnServerEvent:Connect(function(player: Player, kind: unknown)
	if kind == "sync" then
		syncPlayer(player)
	end
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastSync[player] = nil
end)

-- -------------------------------------------------------------------------------------------------------- poll loop

local function header(headers: { [string]: string }?, name: string): string?
	if headers == nil then
		return nil
	end
	for k, v in headers do
		if string.lower(k) == name then
			return v
		end
	end
	return nil
end

local function decodeBody(body: string): (buffer?, string?)
	local ok, out = pcall(function(): buffer
		return game:GetService("EncodingService"):Base64Decode(buffer.fromstring(body))
	end)
	if ok then
		return out, nil
	end
	return Base64.decode(body) -- strict Luau fallback (same result for canonical bodies)
end

local function friendly(err: string): string
	if string.find(err, "Http requests are not enabled", 1, true) then
		return "HTTP requests are disabled (Game Settings > Security > Allow HTTP Requests)"
	end
	return err
end

local authSecret: any = nil
local function getAuth(): (any, string?)
	if authSecret then
		return authSecret, nil
	end
	local name = tostring(attr("SecretName", "rlps_token"))
	local ok, res = pcall(function(): any
		return HttpService:GetSecret(name):AddPrefix("Bearer ")
	end)
	if not ok then
		return nil, "secret '" .. name .. "' is not available: " .. tostring(res)
	end
	authSecret = res
	return res, nil
end

-- One poll. Returns the number of seconds to wait before the next poll.
local function pollOnce(): number
	local base = tostring(attr("FrameServiceUrl", ""))
	base = string.gsub(base, "/+$", "")
	if not string.match(base, "^https://[%w%.%-]+[:%d]*") then
		setServerStatus("error", "FrameServiceUrl is not set to an https:// URL")
		return 5
	end
	local auth, aerr = getAuth()
	if auth == nil then
		setServerStatus("error", aerr)
		return 10
	end
	local after, session, key = relay:pollParams()
	local waitMs = math.clamp(math.floor(tonumber(attr("PollWaitMs", 15000)) or 15000), 0, 25000)
	local url = string.format("%s/v1/frames?after=%d&session=%d&key=%d&wait=%d", base, after, session,
		if key then 1 else 0, waitMs)
	local ok, res = pcall(function(): any
		return HttpService:RequestAsync({ Url = url, Method = "GET", Headers = { Authorization = auth } })
	end)
	if not ok then
		local reason = friendly(tostring(res))
		script:SetAttribute("LastError", reason)
		broadcast(relay:fail("request failed: " .. reason))
		return math.min(30, 2 ^ math.min(relay.consecutiveErrors, 5))
	end
	if not res.Success then
		local code = res.StatusCode :: number
		local reason = "HTTP " .. code .. " " .. tostring(res.StatusMessage)
		if code == 401 then
			reason = "frame service rejected the token (HTTP 401): check the secret"
		end
		script:SetAttribute("LastError", reason)
		broadcast(relay:fail(reason))
		local retry = tonumber(header(res.Headers, "retry-after") or "")
		if retry then
			return math.clamp(retry, 1, 60)
		end
		return math.min(30, 2 ^ math.min(relay.consecutiveErrors, 5))
	end
	local data, derr = decodeBody(res.Body :: string)
	if data == nil then
		script:SetAttribute("LastError", "bad body: " .. tostring(derr))
		broadcast(relay:fail("bad response body: " .. tostring(derr)))
		return 2
	end
	local messages, ierr = relay:ingest(data)
	if messages == nil then
		script:SetAttribute("LastError", "invalid container: " .. tostring(ierr))
		broadcast(relay:fail("invalid container: " .. tostring(ierr)))
		return 2
	end
	broadcast(messages)
	if relay.status == "stopped" then
		return math.max(1, tonumber(attr("StoppedPollInterval", 3)) or 3)
	end
	return 0
end

local function anyViewer(): boolean
	for _, p in Players:GetPlayers() do
		if canView(p) then
			return true
		end
	end
	return false
end

task.spawn(function()
	broadcast({})
	while true do
		if not anyViewer() then
			task.wait(1) -- nobody can see the screen: do not pull frames from the owner's PC
			continue
		end
		local started = os.clock()
		local okPoll, delayOrErr = pcall(pollOnce)
		local delay = if okPoll then delayOrErr :: number else 5
		if not okPoll then
			script:SetAttribute("LastError", "poll loop error: " .. tostring(delayOrErr))
			warn("[RLPS] poll loop error:", delayOrErr)
		end
		local minInterval = math.max(0.05, tonumber(attr("MinPollInterval", 0.2)) or 0.2)
		local elapsed = os.clock() - started
		task.wait(math.max(delay, minInterval - elapsed, 0.03))
	end
end)
