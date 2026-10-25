--!strict
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
local SYNC_COOLDOWN = 3 -- seconds between sync requests (startup retry / desync recovery)
local RENDER_DISTANCE = 300 -- studs; farther away the picture is not redrawn (frames are still assembled)
local PIXELS_PER_STUD = 50

type State = "connecting" | "live" | "stopped" | "error"

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui") :: PlayerGui

-- ------------------------------------------------------------------------------------------------- frame assembly

local function decompress(payload: buffer, rawLength: number): (buffer?, string?)
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
	local faceName = part:GetAttribute("RlpsFace")
	gui.Face = if typeof(faceName) == "string" and (Enum.NormalId :: any)[faceName] then (Enum.NormalId :: any)[faceName]
		else Enum.NormalId.Front
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
	dropPicture()
	local ok, res = pcall(function(): EditableImage
		return AssetService:CreateEditableImage({ Size = Vector2.new(w, h) })
	end)
	if not ok or res == nil then
		setState("error", "cannot create the screen image (" .. tostring(res) .. ")")
		return nil
	end
	editable = res
	needFullRedraw = true
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

frames.OnClientEvent:Connect(function(kind: unknown, a: unknown, b: unknown, c: unknown)
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
		local s = if typeof(a) == "string" then a else "error"
		local d = if typeof(b) == "string" then b else nil
		if s == "live" then
			setState(if core.framesCompleted > 0 and editable then "live" else "connecting", d)
			renderPending = true
		elseif s == "stopped" or s == "error" or s == "connecting" then
			setState(s :: State, d)
		end
	elseif kind == "reset" then
		core:reset()
		needFullRedraw = true
	end
end)

RunService.Heartbeat:Connect(function()
	if renderPending or needFullRedraw then
		render()
	end
	if state == "connecting" and core.framesCompleted == 0 then
		requestSync() -- rate-limited: retries until the server answers with its history
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
