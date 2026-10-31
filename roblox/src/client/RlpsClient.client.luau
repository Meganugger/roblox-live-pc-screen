--!strict
--!native
-- RLPS client script (T-0012): rebuilds the shared desktop on this client and shows it on the in-world TV.
--
-- Receives part records from RlpsServer over ReplicatedStorage.RlpsFrames, assembles frames with RlpsClientCore
-- (zstd via EncodingService:DecompressBuffer) and writes the changed rectangle into one EditableImage that every
-- screen part tagged "RlpsScreen" (fallback: Workspace.RlpsTV.Screen) shows through a SurfaceGui in PlayerGui.
-- EditableImage changes do not replicate, which is why every client decodes the stream itself.
--
-- Screen states: CONNECTING (no picture yet), LIVE (picture + red LIVE badge), STOPPED (owner not sharing: every pixel
-- is dropped from memory), ERROR (frame service unreachable / misconfigured: picture hidden, assembler kept so the
-- stream resumes without a keyframe when the service comes back).

local AssetService = game:GetService("AssetService")
local CollectionService = game:GetService("CollectionService")
local EncodingService = game:GetService("EncodingService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Shared = ReplicatedStorage:WaitForChild("Rlps")
local ClientCore = require(Shared:WaitForChild("RlpsClientCore"))
local frames = ReplicatedStorage:WaitForChild("RlpsFrames") :: RemoteEvent

local SCREEN_TAG = "RlpsScreen"
local DEFAULT_DECODE_BUDGET_MS = 10 -- per Heartbeat; the server may override it (RemoteEvent attribute DecodeBudgetMs)
local ACK_INTERVAL = 0.1 -- seconds between "ack" messages (congestion control on the server)
local MAX_QUEUE = 4000 -- queued messages; beyond it the stream is dropped and re-synced (should never happen)
local SYNC_COOLDOWN = 3 -- seconds between sync requests (startup retry / desync recovery)
local RENDER_DISTANCE = 300 -- studs; farther away the picture is not redrawn (frames are still assembled)
local PIXELS_PER_STUD = 50 -- until the first picture; then the canvas matches the image resolution
local IMAGE_RETRY = 5 -- seconds between EditableImage creation attempts after a failure

type State = "connecting" | "live" | "stopped" | "error"

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui") :: PlayerGui

-- ------------------------------------------------------------------------------------------------- frame assembly

local function decompress(payload: buffer, rawLength: number): (buffer?, string?)
	-- the declared content size is checked before decompressing, so a bad part can never allocate more than rawLength
	local okSize, size = pcall(function(): number?
		return EncodingService:GetDecompressedBufferSize(payload, Enum.CompressionAlgorithm.Zstd)
	end)
	if not okSize or size ~= rawLength then
		return nil, "zstd content size does not match rawLength"
	end
	local ok, out = pcall(function(): buffer
		return EncodingService:DecompressBuffer(payload, Enum.CompressionAlgorithm.Zstd)
	end)
	if not ok then
		return nil, "zstd decode failed: " .. tostring(out)
	end
	if buffer.len(out) ~= rawLength then
		return nil, "zstd content size does not match rawLength"
	end
	return out, nil
end

local core = ClientCore.new(decompress)
local editable: EditableImage? = nil
local needFullRedraw = false
local renderPending = false
local imageRetryAt = 0

-- ----------------------------------------------------------------------------------------------------- screen GUIs

type Screen = { part: BasePart, gui: SurfaceGui, image: ImageLabel, status: TextLabel, badge: TextLabel }
local screens: { [BasePart]: Screen } = {}
local state: State = "connecting"
local detail: string? = nil

local function statusText(): string
	if state == "connecting" then
		return if detail then "Connecting to the shared screen…\n" .. detail else "Connecting to the shared screen…"
	elseif state == "stopped" then
		return "Screen sharing is off"
	elseif state == "error" then
		return "Screen unavailable\n" .. (detail or "unknown error")
	end
	return ""
end

local function refreshScreen(s: Screen)
	local showPicture = state == "live" and editable ~= nil
	s.image.Visible = showPicture
	s.badge.Visible = showPicture
	s.status.Visible = not showPicture
	s.status.Text = if showPicture then "" else (if state == "live" then "Waiting for the first frame…" else statusText())
	s.image.ImageContent = if editable then Content.fromObject(editable) else Content.none
end

local function refreshAll()
	for _, s in screens do
		refreshScreen(s)
	end
end

local function addScreen(part: Instance)
	if not part:IsA("BasePart") or screens[part] then
		return
	end
	local gui = Instance.new("SurfaceGui")
	gui.Name = "RlpsScreenGui"
	gui.Adornee = part
	-- RlpsFace attribute picks the face; an unknown name falls back to Front (indexing Enum.NormalId with an unknown
	-- name raises, so look it up among the enum items instead)
	local faceName = part:GetAttribute("RlpsFace")
	local face = Enum.NormalId.Front
	for _, item in Enum.NormalId:GetEnumItems() do
		if item.Name == faceName then
			face = item
		end
	end
	gui.Face = face
	gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
	gui.PixelsPerStud = PIXELS_PER_STUD
	gui.LightInfluence = 0
	gui.ResetOnSpawn = false
	gui.ClipsDescendants = true

	local bg = Instance.new("Frame")
	bg.Name = "Background"
	bg.Size = UDim2.fromScale(1, 1)
	bg.BackgroundColor3 = Color3.new(0, 0, 0)
	bg.BorderSizePixel = 0
	bg.Parent = gui

	local image = Instance.new("ImageLabel")
	image.Name = "Picture"
	image.Size = UDim2.fromScale(1, 1)
	image.BackgroundTransparency = 1
	image.ScaleType = Enum.ScaleType.Fit
	image.Visible = false
	image.Parent = bg

	local status = Instance.new("TextLabel")
	status.Name = "Status"
	status.Size = UDim2.fromScale(0.9, 0.5)
	status.Position = UDim2.fromScale(0.05, 0.25)
	status.BackgroundTransparency = 1
	status.TextColor3 = Color3.fromRGB(200, 200, 200)
	status.TextScaled = true
	status.TextWrapped = true
	status.Font = Enum.Font.GothamMedium
	status.Parent = bg

	local badge = Instance.new("TextLabel")
	badge.Name = "LiveBadge"
	badge.Size = UDim2.fromScale(0.14, 0.08)
	badge.Position = UDim2.fromScale(0.015, 0.02)
	badge.BackgroundColor3 = Color3.fromRGB(200, 20, 20)
	badge.BackgroundTransparency = 0.15
	badge.BorderSizePixel = 0
	badge.Text = "● LIVE"
	badge.TextColor3 = Color3.new(1, 1, 1)
	badge.TextScaled = true
	badge.Font = Enum.Font.GothamBold
	badge.Visible = false
	badge.ZIndex = 2
	badge.Parent = bg

	gui.Parent = playerGui
	local s: Screen = { part = part, gui = gui, image = image, status = status, badge = badge }
	screens[part] = s
	refreshScreen(s)
end

local function removeScreen(part: Instance)
	local s = screens[part :: BasePart]
	if s then
		screens[part :: BasePart] = nil
		s.gui:Destroy()
	end
end

-- ------------------------------------------------------------------------------------------------- EditableImage

local function dropPicture()
	if editable then
		editable:Destroy()
		editable = nil
	end
	refreshAll()
end

local function setState(newState: State, newDetail: string?)
	if newDetail and #newDetail > 160 then
		newDetail = string.sub(newDetail, 1, 160) .. "…"
	end
	state, detail = newState, newDetail
	if newState == "stopped" then
		core:reset() -- sharing stopped: nothing of the owner's screen stays in this client's memory
		dropPicture()
	end
	refreshAll()
end

local function ensureImage(w: number, h: number): EditableImage?
	local img = editable
	if img and img.Size.X == w and img.Size.Y == h then
		return img
	end
	if os.clock() < imageRetryAt then
		return nil -- creation failed recently: retry later instead of on every frame
	end
	dropPicture()
	local ok, res = pcall(function(): EditableImage?
		-- nil when the device's EditableImage memory budget is exhausted; an error when the API is disabled
		return AssetService:CreateEditableImage({ Size = Vector2.new(w, h) }) :: EditableImage?
	end)
	if not ok or res == nil then
		imageRetryAt = os.clock() + IMAGE_RETRY
		local why = if ok then "image memory budget exhausted" else tostring(res)
		setState("error", "cannot create the screen image (" .. why .. "); published games need Allow Mesh / Image APIs")
		return nil
	end
	editable = res
	needFullRedraw = true
	for _, s in screens do -- one canvas pixel per image pixel across the screen's width: no extra blur
		s.gui.PixelsPerStud = math.clamp(w / math.max(s.part.Size.X, 0.1), 10, 400)
	end
	refreshAll()
	return res
end

local function nearAnyScreen(): boolean
	local camera = workspace.CurrentCamera
	if camera == nil then
		return true
	end
	local pos = camera.CFrame.Position
	for part in screens do
		if (part.Position - pos).Magnitude <= RENDER_DISTANCE then
			return true
		end
	end
	return false
end

local function render()
	if core.frame == nil or core.pendingSeq ~= 0 then
		return -- nothing yet, or in the middle of a multi-part frame (avoid tearing): try again next frame
	end
	if next(screens) == nil or not nearAnyScreen() then
		return -- keep the dirty rectangle; redraw when a screen is close again
	end
	local img = ensureImage(core.width, core.height)
	if img == nil then
		return
	end
	local x, y, w, h = core:takeDirty()
	if needFullRedraw then
		x, y, w, h = 0, 0, core.width, core.height
	end
	renderPending = false
	if x == nil then
		return
	end
	local ok, err = pcall(function()
		img:WritePixelsBuffer(Vector2.new(x, y), Vector2.new(w :: number, h :: number),
			core:copyRect(x :: number, y :: number, w :: number, h :: number))
	end)
	if ok then
		needFullRedraw = false
		if state ~= "live" then
			setState("live", nil)
		end
	else
		setState("error", "cannot draw the screen image (" .. tostring(err) .. ")")
	end
end

-- ------------------------------------------------------------------------------------------------------ networking

local lastSync = -math.huge
local function requestSync()
	local now = os.clock()
	if now - lastSync >= SYNC_COOLDOWN then
		lastSync = now
		frames:FireServer("sync")
	end
end

-- Messages are queued and processed on Heartbeat within a time budget, so a large frame never freezes the game:
-- a frame may be assembled over several game frames (the EditableImage keeps showing the previous complete one).
type Msg = { kind: string, a: unknown, b: unknown, c: unknown }
local queue: { Msg } = {}
local qHead, qTail = 1, 0 -- explicit bounds: processed slots are set to nil, so `#queue` would be meaningless
local lastAckAt = 0
local ackedSession, ackedSeq = 0, 0
local decodeSpent = 0 -- seconds of decoding spent on the frame being assembled
local costMs = 0 -- moving average decode cost of one complete frame (sent with acks: the server derives a fps cap)

local function handle(m: Msg)
	local kind, a, b, c = m.kind, m.a, m.b, m.c
	if kind == "part" then
		if typeof(a) ~= "buffer" then
			return
		end
		local result = core:push(a :: buffer)
		if result == "frame" then
			renderPending = true
		elseif result == "desync" then
			requestSync()
		end
	elseif kind == "advance" then
		if typeof(a) == "number" and typeof(b) == "number" and typeof(c) == "number" then
			if core:advance(a :: number, b :: number, c :: number) == "desync" then
				requestSync()
			end
		end
	elseif kind == "status" then
		local st = if typeof(a) == "string" then a else "error"
		local d = if typeof(b) == "string" then b else nil
		if st == "live" then
			setState(if core.framesCompleted > 0 and editable then "live" else "connecting", d)
			renderPending = true
		elseif st == "stopped" or st == "error" or st == "connecting" then
			setState(st :: State, d)
		end
	elseif kind == "reset" then
		core:reset()
		needFullRedraw = true
	end
end

frames.OnClientEvent:Connect(function(kind: unknown, a: unknown, b: unknown, c: unknown)
	if typeof(kind) ~= "string" then
		return
	end
	if kind == "status" and a == "stopped" then
		-- sharing stopped: drop everything still queued at once (no further pixel of the owner's screen is shown)
		table.clear(queue)
		qHead, qTail = 1, 0
	end
	if qTail - qHead + 1 >= MAX_QUEUE then
		table.clear(queue)
		qHead, qTail = 1, 0
		core:reset()
		requestSync()
		return
	end
	qTail += 1
	queue[qTail] = { kind = kind :: string, a = a, b = b, c = c }
end)

local function processQueue()
	local budgetMs = frames:GetAttribute("DecodeBudgetMs")
	local budget = (if typeof(budgetMs) == "number" then budgetMs else DEFAULT_DECODE_BUDGET_MS) / 1000
	local started = os.clock()
	while qHead <= qTail do
		local m = queue[qHead]
		queue[qHead] = nil :: any
		qHead += 1
		local t0 = os.clock()
		handle(m)
		decodeSpent += os.clock() - t0
		if m.kind == "part" and renderPending and core.pendingSeq == 0 then
			local ms = decodeSpent * 1000
			costMs = if costMs == 0 then ms else costMs * 0.8 + ms * 0.2
			decodeSpent = 0
		end
		if renderPending and core.pendingSeq == 0 then
			render() -- each completed frame goes to the EditableImage before the next one is assembled
		end
		if os.clock() - started >= budget then
			break
		end
	end
	if qHead > qTail then
		table.clear(queue)
		qHead, qTail = 1, 0
	end
end

local function sendAck()
	local now = os.clock()
	if core.framesCompleted == 0 or now - lastAckAt < ACK_INTERVAL then
		return
	end
	if core.sessionId ~= ackedSession or core.seq ~= ackedSeq then
		lastAckAt = now
		ackedSession, ackedSeq = core.sessionId, core.seq
		frames:FireServer("ack", core.sessionId, core.seq, costMs)
	end
end

local lastDiag = 0
local function diagnostics()
	-- visible in the client's Explorer / F9 console: StarterPlayerScripts.RlpsClient attributes
	local now = os.clock()
	if now - lastDiag < 1 then
		return
	end
	lastDiag = now
	script:SetAttribute("State", state)
	script:SetAttribute("Seq", core.seq)
	script:SetAttribute("FramesCompleted", core.framesCompleted)
	script:SetAttribute("Desyncs", core.desyncs)
	script:SetAttribute("LastError", core.lastError or "")
	script:SetAttribute("LastDetail", core.lastDetail or "")
	script:SetAttribute("QueueLength", qTail - qHead + 1)
	script:SetAttribute("DecodeMsPerFrame", math.floor(costMs * 10 + 0.5) / 10)
end

RunService.Heartbeat:Connect(function()
	processQueue()
	diagnostics()
	if renderPending or needFullRedraw then
		render()
	end
	sendAck()
	if (state == "connecting" and core.framesCompleted == 0) or (core.desynced and state == "live") then
		requestSync() -- rate-limited: retries until the server answers with its history / a keyframe arrives
	end
end)

for _, part in CollectionService:GetTagged(SCREEN_TAG) do
	addScreen(part)
end
CollectionService:GetInstanceAddedSignal(SCREEN_TAG):Connect(addScreen)
CollectionService:GetInstanceRemovedSignal(SCREEN_TAG):Connect(removeScreen)
if next(screens) == nil then
	task.spawn(function()
		local tv = workspace:WaitForChild("RlpsTV", 30)
		local screen = tv and tv:WaitForChild("Screen", 30)
		if screen then
			addScreen(screen)
		end
	end)
end

requestSync()
