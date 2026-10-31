--!strict
--!native
--!optimize 2
-- RLPS client script (T-0012, T-0024): rebuilds the shared desktop on this client and shows it on the in-world TV,
-- and offers viewer modes: full screen, cinema (camera framing the TV) and a mini player.
--
-- Receives part records from RlpsServer over ReplicatedStorage.RlpsFrames, assembles frames with RlpsClientCore
-- (zstd via EditableImage-independent EncodingService:DecompressBuffer) and writes only what changed — a few dirty
-- rectangles, once per game frame — into one EditableImage. Every view shows that same image: a SurfaceGui per screen
-- part tagged "RlpsScreen" (fallback: Workspace.RlpsTV.Screen), the full-screen overlay and the mini player.
-- EditableImage changes do not replicate, which is why every client decodes the stream itself.
--
-- Redraws are skipped while nobody can see a picture (every screen too far, behind the camera or seen from behind,
-- and no overlay open); the dirty rectangles accumulate and are drawn when a screen comes back into view. Far screens
-- are redrawn at most 10 times per second.
--
-- Screen states: CONNECTING (no picture yet), LIVE (picture + red LIVE badge), STOPPED (owner not sharing: every pixel
-- is dropped from memory), ERROR (frame service unreachable / misconfigured: picture hidden, assembler kept so the
-- stream resumes without a keyframe when the service comes back).

local AssetService = game:GetService("AssetService")
local CollectionService = game:GetService("CollectionService")
local ContextActionService = game:GetService("ContextActionService")
local EncodingService = game:GetService("EncodingService")
local Lighting = game:GetService("Lighting")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")

local Shared = ReplicatedStorage:WaitForChild("Rlps")
local ClientCore = require(Shared:WaitForChild("RlpsClientCore"))
local View = require(Shared:WaitForChild("RlpsView"))
local frames = ReplicatedStorage:WaitForChild("RlpsFrames") :: RemoteEvent

local SCREEN_TAG = "RlpsScreen"
local DEFAULT_DECODE_BUDGET_MS = 10 -- per Heartbeat; the server may override it (RemoteEvent attribute DecodeBudgetMs)
local ACK_INTERVAL = 0.1 -- seconds between "ack" messages (congestion control on the server)
local MAX_QUEUE = 4000 -- queued messages; beyond it the stream is dropped and re-synced (should never happen)
local SYNC_COOLDOWN = 3 -- seconds between sync requests (startup retry / desync recovery)
local RENDER_DISTANCE = 300 -- studs; farther away a screen is not redrawn (frames are still assembled)
local FAR_DISTANCE = 120 -- studs; beyond it a screen is redrawn at most every FAR_REDRAW_INTERVAL
local FAR_REDRAW_INTERVAL = 0.1
local MAX_RECTS = 12 -- dirty rectangles per redraw; more → their bounding box (each WritePixelsBuffer call costs)
local CONTROLS_DISTANCE = 45 -- studs; closer to a screen the viewer controls appear
local CINEMA_BAR = 0.08 -- cinema letterbox bar height (fraction of the viewport, top and bottom)
local CINEMA_ACTION = "RlpsCinemaHoldStill"
local IMAGE_API_HELP = "the owner must enable Allow Mesh / Image APIs (Game Settings > Security; needs a 13+ "
	.. "ID-verified owner)"
local PIXELS_PER_STUD = 50 -- until the first picture; then the canvas matches the image resolution
local IMAGE_RETRY = 5 -- seconds between EditableImage creation attempts after a failure

type State = "connecting" | "live" | "stopped" | "error"
type Mode = "none" | "fullscreen" | "cinema" | "mini"

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
local lastRender = 0
local redraws, redrawPixels, skippedRedraws = 0, 0, 0

-- ---------------------------------------------------------------------------------------------------------- views

-- A view = one place the picture is shown: a TV screen (SurfaceGui), the full-screen overlay or the mini player.
type Panel = { image: ImageLabel, status: TextLabel, badge: TextLabel }
type Screen = Panel & { part: BasePart, gui: SurfaceGui, face: Enum.NormalId }
local screens: { [BasePart]: Screen } = {}
local overlays: { Panel } = {}
local state: State = "connecting"
local detail: string? = nil
local mode: Mode = "none"
local hiddenByMe = false -- this player hid the screen (nothing is received or drawn until shown again)

local function statusText(): string
	if state == "connecting" then
		return if detail then "Connecting to the shared screen…\n" .. detail else "Connecting to the shared screen…"
	elseif state == "stopped" then
		return if detail then "Screen sharing is off\n(" .. detail .. ")" else "Screen sharing is off"
	elseif state == "error" then
		return "Screen unavailable\n" .. (detail or "unknown error")
	end
	return ""
end

local function refreshPanel(s: Panel)
	local showPicture = state == "live" and editable ~= nil and not hiddenByMe
	s.image.Visible = showPicture
	s.badge.Visible = showPicture
	s.status.Visible = not showPicture
	s.status.Text = if showPicture then ""
		elseif hiddenByMe then "You hid the screen\nPress H or Show screen to watch again"
		elseif state == "live" then "Waiting for the first frame…"
		else statusText()
	s.image.ImageContent = if editable then Content.fromObject(editable) else Content.none
end

local refreshControls: () -> () -- defined with the viewer controls below

local function refreshAll()
	for _, s in screens do
		refreshPanel(s)
	end
	for _, s in overlays do
		refreshPanel(s)
	end
	refreshControls()
end

-- Black background, the picture (letterboxed), a status text and the LIVE badge, inside `parent`.
local function buildPanel(parent: GuiObject): Panel
	local image = Instance.new("ImageLabel")
	image.Name = "Picture"
	image.Size = UDim2.fromScale(1, 1)
	image.BackgroundTransparency = 1
	image.ScaleType = Enum.ScaleType.Fit
	image.ResampleMode = Enum.ResamplerMode.Default
	image.Visible = false
	image.Parent = parent

	local status = Instance.new("TextLabel")
	status.Name = "Status"
	status.Size = UDim2.fromScale(0.9, 0.5)
	status.Position = UDim2.fromScale(0.05, 0.25)
	status.BackgroundTransparency = 1
	status.TextColor3 = Color3.fromRGB(200, 200, 200)
	status.TextScaled = true
	status.TextWrapped = true
	status.Font = Enum.Font.GothamMedium
	status.Parent = parent

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
	badge.Parent = parent
	return { image = image, status = status, badge = badge }
end

local function faceOf(part: BasePart): Enum.NormalId
	-- RlpsFace attribute picks the face; an unknown name falls back to Front (indexing Enum.NormalId with an unknown
	-- name raises, so look it up among the enum items instead)
	local faceName = part:GetAttribute("RlpsFace")
	for _, item in Enum.NormalId:GetEnumItems() do
		if item.Name == faceName then
			return item
		end
	end
	return Enum.NormalId.Front
end

-- World-space outward normal and "up" of a screen face, the face's width/height in studs and the part's depth.
local function faceGeometry(part: BasePart, face: Enum.NormalId): (Vector3, Vector3, number, number, number)
	local cf, size = part.CFrame, part.Size
	if face == Enum.NormalId.Back then
		return -cf.LookVector, cf.UpVector, size.X, size.Y, size.Z
	elseif face == Enum.NormalId.Right then
		return cf.RightVector, cf.UpVector, size.Z, size.Y, size.X
	elseif face == Enum.NormalId.Left then
		return -cf.RightVector, cf.UpVector, size.Z, size.Y, size.X
	elseif face == Enum.NormalId.Top then
		return cf.UpVector, -cf.LookVector, size.X, size.Z, size.Y
	elseif face == Enum.NormalId.Bottom then
		return -cf.UpVector, cf.LookVector, size.X, size.Z, size.Y
	end
	return cf.LookVector, cf.UpVector, size.X, size.Y, size.Z
end

local function addScreen(part: Instance)
	if not part:IsA("BasePart") or screens[part] then
		return
	end
	local gui = Instance.new("SurfaceGui")
	gui.Name = "RlpsScreenGui"
	gui.Adornee = part
	local face = faceOf(part)
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
	local panel = buildPanel(bg)

	gui.Parent = playerGui
	local s: Screen = { part = part, gui = gui, face = face, image = panel.image, status = panel.status,
		badge = panel.badge }
	screens[part] = s
	refreshPanel(s)
end

local function removeScreen(part: Instance)
	local s = screens[part :: BasePart]
	if s then
		screens[part :: BasePart] = nil
		s.gui:Destroy()
	end
end

-- Nearest screen to the camera and its distance (nil when there is none).
local function nearestScreen(): (Screen?, number)
	local camera = workspace.CurrentCamera
	local best: Screen?, bestDist = nil, math.huge
	if camera == nil then
		return next(screens) and (select(2, next(screens)) :: Screen) or nil, 0
	end
	local pos = camera.CFrame.Position
	for part, s in screens do
		local d = (part.Position - pos).Magnitude
		if d < bestDist then
			best, bestDist = s, d
		end
	end
	return best, bestDist
end

-- Is any picture visible right now, and how far is the closest visible screen?
local function anyVisible(): (boolean, number)
	if mode ~= "none" then
		return true, 0 -- an overlay or cinema shows the picture
	end
	local camera = workspace.CurrentCamera
	if camera == nil then
		return true, 0
	end
	local cf = camera.CFrame
	local pos, look = cf.Position, cf.LookVector
	local best = math.huge
	for part, s in screens do
		local normal, _, _, _, depth = faceGeometry(part, s.face)
		local centre = part.Position + normal * (depth / 2)
		local toCam = pos - centre
		local dist = toCam.Magnitude
		if View.visible(dist, normal:Dot(toCam), look:Dot(-toCam), part.Size.Magnitude / 2, RENDER_DISTANCE) then
			best = math.min(best, dist)
		end
	end
	return best < math.huge, best
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
	if ok and res ~= nil then
		-- creation can succeed while the API is disabled for this experience: only writing fails, so write once now
		local probe = res :: EditableImage
		local wrote = pcall(function()
			probe:WritePixelsBuffer(Vector2.zero, Vector2.new(1, 1), buffer.create(4))
		end)
		if not wrote then
			probe:Destroy()
			imageRetryAt = os.clock() + IMAGE_RETRY * 6
			setState("error", "cannot draw the screen image: " .. IMAGE_API_HELP)
			return nil
		end
	end
	if not ok or res == nil then
		imageRetryAt = os.clock() + IMAGE_RETRY
		local why = if ok then "this device's image memory is full" else tostring(res)
		setState("error", "cannot create the screen image (" .. why .. "); " .. IMAGE_API_HELP)
		return nil
	end
	editable = res
	needFullRedraw = true
	for _, s in screens do -- one canvas pixel per image pixel across the screen's width: no extra blur
		local _, _, faceW = faceGeometry(s.part, s.face)
		s.gui.PixelsPerStud = math.clamp(w / math.max(faceW, 0.1), 10, 400)
	end
	refreshAll()
	return res
end

-- Write what changed since the last redraw into the EditableImage: a few dirty rectangles (or everything after a new
-- image / reset). Skipped while no picture is visible — except to show the very first picture.
local function render(now: number)
	if core.frame == nil or core.pendingSeq ~= 0 or hiddenByMe then
		return -- nothing yet, or in the middle of a multi-part frame (avoid tearing): try again next frame
	end
	local firstPicture = editable == nil or state ~= "live"
	if not firstPicture then
		local visible, dist = anyVisible()
		if not visible or (dist > FAR_DISTANCE and now - lastRender < FAR_REDRAW_INTERVAL) then
			skippedRedraws += 1
			return -- keep the dirty rectangles; draw them when a screen is visible again
		end
	end
	local img = ensureImage(core.width, core.height)
	if img == nil then
		return
	end
	local rects = core:takeDirtyRects(MAX_RECTS)
	if needFullRedraw then
		rects = { { x = 0, y = 0, w = core.width, h = core.height } }
	end
	renderPending = false
	if rects == nil then
		return
	end
	local pixels = 0
	local ok, err = pcall(function()
		for _, r in rects :: { ClientCore.Rect } do
			img:WritePixelsBuffer(Vector2.new(r.x, r.y), Vector2.new(r.w, r.h), core:copyRect(r.x, r.y, r.w, r.h))
			pixels += r.w * r.h
		end
	end)
	if ok then
		needFullRedraw = false
		lastRender = now
		redraws += 1
		redrawPixels = pixels
		if state ~= "live" then
			setState("live", nil)
		end
	else
		setState("error", "cannot draw the screen image (" .. tostring(err) .. ")")
	end
end

-- --------------------------------------------------------------------------------------------------- viewer modes

local allowed: { [string]: boolean } = View.parseModes(frames:GetAttribute("ViewerModes"))

local function button(parent: Instance, name: string, text: string, size: UDim2, pos: UDim2): TextButton
	local b = Instance.new("TextButton")
	b.Name = name
	b.Text = text
	b.Size = size
	b.Position = pos
	b.BackgroundColor3 = Color3.fromRGB(25, 25, 30)
	b.BackgroundTransparency = 0.2
	b.BorderSizePixel = 0
	b.TextColor3 = Color3.new(1, 1, 1)
	b.TextScaled = true
	b.Font = Enum.Font.GothamBold
	b.ZIndex = 5
	b.Parent = parent
	return b
end

local function screenGui(name: string, order: number): ScreenGui
	local g = Instance.new("ScreenGui")
	g.Name = name
	g.ResetOnSpawn = false
	g.IgnoreGuiInset = true
	g.DisplayOrder = order
	g.Enabled = false
	g.Parent = playerGui
	return g
end

-- Viewer controls (shown near a screen while the picture is live)
local controlsGui = screenGui("RlpsViewerControls", 20)
local bar = Instance.new("Frame")
bar.Name = "Bar"
bar.AnchorPoint = Vector2.new(0.5, 1)
bar.Position = UDim2.fromScale(0.5, 0.97)
bar.Size = UDim2.fromScale(0.42, 0.06)
bar.BackgroundTransparency = 1
bar.Parent = controlsGui
local fullscreenButton = button(bar, "FullscreenButton", "⛶ Full screen (F)", UDim2.fromScale(0.32, 1), UDim2.fromScale(0, 0))
local cinemaButton = button(bar, "CinemaButton", "🎬 Cinema (C)", UDim2.fromScale(0.32, 1), UDim2.fromScale(0.34, 0))
local miniButton = button(bar, "MiniButton", "▣ Mini player (M)", UDim2.fromScale(0.32, 1), UDim2.fromScale(0.68, 0))
-- Hide / show the screen for this player only (also stops the server sending anything to this player)
local hideButton = button(controlsGui, "HideButton", "🚫 Hide (H)", UDim2.fromScale(0.09, 0.045),
	UDim2.fromScale(0.795, 0.925))

-- Moderators (ModeratorUserIds / the owner): withhold the screen for everyone in this server
local moderatorGui = screenGui("RlpsModerator", 25)
local modButton = button(moderatorGui, "ModHideButton", "⛔ Hide screen for everyone", UDim2.fromScale(0.22, 0.045),
	UDim2.fromScale(0.39, 0.02))
modButton.BackgroundColor3 = Color3.fromRGB(140, 20, 20)

-- Full screen: the picture over the whole window, letterboxed (Fit) or filling it (Fill = crop)
local fullscreenGui = screenGui("RlpsFullscreen", 100)
local fsBackground = Instance.new("Frame")
fsBackground.Name = "Background"
fsBackground.Size = UDim2.fromScale(1, 1)
fsBackground.BackgroundColor3 = Color3.new(0, 0, 0)
fsBackground.BorderSizePixel = 0
fsBackground.Parent = fullscreenGui
local fsPanel = buildPanel(fsBackground)
table.insert(overlays, fsPanel)
local fsExit = button(fsBackground, "ExitButton", "✕ Exit (F)", UDim2.fromScale(0.1, 0.05), UDim2.fromScale(0.89, 0.01))
local fsFit = button(fsBackground, "FitButton", "Fill", UDim2.fromScale(0.07, 0.05), UDim2.fromScale(0.81, 0.01))
local fsSharp = button(fsBackground, "SharpButton", "Sharp", UDim2.fromScale(0.07, 0.05), UDim2.fromScale(0.73, 0.01))

-- Mini player: a small always-visible picture in the bottom-right corner, wherever the player walks
local miniGui = screenGui("RlpsMiniPlayer", 40)
local miniFrame = Instance.new("Frame")
miniFrame.Name = "Window"
miniFrame.AnchorPoint = Vector2.new(1, 1)
miniFrame.Position = UDim2.fromScale(0.985, 0.88)
miniFrame.Size = UDim2.fromScale(0.3, 0.3)
miniFrame.BackgroundColor3 = Color3.new(0, 0, 0)
miniFrame.BorderSizePixel = 0
miniFrame.Parent = miniGui
local miniAspect = Instance.new("UIAspectRatioConstraint")
miniAspect.AspectRatio = 16 / 9
miniAspect.Parent = miniFrame
table.insert(overlays, buildPanel(miniFrame))
local miniExpand = button(miniFrame, "ExpandButton", "⛶", UDim2.fromScale(0.12, 0.18), UDim2.fromScale(0.74, 0.02))
local miniClose = button(miniFrame, "CloseButton", "✕", UDim2.fromScale(0.12, 0.18), UDim2.fromScale(0.87, 0.02))

-- Cinema: the camera frames the nearest TV, black bars top and bottom, the background blurred, movement paused
local cinemaGui = screenGui("RlpsCinema", 30)
for i, y in { 0, 1 - CINEMA_BAR } do
	local f = Instance.new("Frame")
	f.Name = if i == 1 then "TopBar" else "BottomBar"
	f.Position = UDim2.fromScale(0, y)
	f.Size = UDim2.fromScale(1, CINEMA_BAR)
	f.BackgroundColor3 = Color3.new(0, 0, 0)
	f.BorderSizePixel = 0
	f.Parent = cinemaGui
end
local cinemaExit = button(cinemaGui, "ExitButton", "✕ Exit cinema (C)", UDim2.fromScale(0.16, 0.045),
	UDim2.fromScale(0.83, 0.97 - CINEMA_BAR))
local cinemaScreen: Screen? = nil
local savedCameraType: Enum.CameraType? = nil
local blur: DepthOfFieldEffect? = nil

local function cinemaCFrame(s: Screen): (CFrame, number)
	local camera = workspace.CurrentCamera
	local normal, up, w, h, depth = faceGeometry(s.part, s.face)
	local vp = camera.ViewportSize
	local d = View.fitDistance(w, h, camera.FieldOfView, vp.X / math.max(vp.Y, 1), 1 - 2 * CINEMA_BAR, 0.96)
	local centre = s.part.Position + normal * (depth / 2)
	return CFrame.lookAt(centre + normal * d, centre, up), d
end

local function holdStill(): Enum.ContextActionResult
	return Enum.ContextActionResult.Sink
end

local function enterCinema(): boolean
	local s = nearestScreen()
	local camera = workspace.CurrentCamera
	if s == nil or camera == nil then
		return false
	end
	cinemaScreen = s
	savedCameraType = camera.CameraType
	camera.CameraType = Enum.CameraType.Scriptable
	local cf, d = cinemaCFrame(s)
	camera.CFrame = cf
	local _, _, w, h = faceGeometry(s.part, s.face)
	local effect = Instance.new("DepthOfFieldEffect") -- local effect (created by this client): the TV stays sharp
	effect.Name = "RlpsCinemaBlur"
	effect.FocusDistance = d
	effect.InFocusRadius = math.max(w, h)
	effect.FarIntensity = 0.6
	effect.NearIntensity = 0
	effect.Parent = Lighting
	blur = effect
	ContextActionService:BindActionAtPriority(CINEMA_ACTION, holdStill, false, Enum.ContextActionPriority.High.Value + 1,
		Enum.PlayerActions.CharacterForward, Enum.PlayerActions.CharacterBackward, Enum.PlayerActions.CharacterLeft,
		Enum.PlayerActions.CharacterRight, Enum.PlayerActions.CharacterJump)
	cinemaGui.Enabled = true
	return true
end

local function exitCinema()
	cinemaGui.Enabled = false
	ContextActionService:UnbindAction(CINEMA_ACTION)
	if blur then
		blur:Destroy()
		blur = nil
	end
	local camera = workspace.CurrentCamera
	if camera then
		camera.CameraType = savedCameraType or Enum.CameraType.Custom
		local character = player.Character
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")
		if humanoid then
			camera.CameraSubject = humanoid
		end
	end
	cinemaScreen, savedCameraType = nil, nil
end

-- Switch to `newMode`; asking for the active mode again closes it.
local function setMode(newMode: Mode)
	if newMode == mode then
		newMode = "none"
	end
	if newMode ~= "none" and not allowed[newMode] then
		return
	end
	if mode == "cinema" then
		exitCinema()
	end
	fullscreenGui.Enabled = false
	miniGui.Enabled = false
	mode = "none"
	if newMode == "cinema" then
		if not enterCinema() then
			newMode = "none"
		end
	elseif newMode == "fullscreen" then
		fullscreenGui.Enabled = true
	elseif newMode == "mini" then
		miniGui.Enabled = true
	end
	mode = newMode
	needFullRedraw = needFullRedraw or (newMode ~= "none" and editable ~= nil) -- overlays may have missed redraws
	renderPending = true
	refreshControls()
end

refreshControls = function()
	local _, dist = nearestScreen()
	local near = dist <= CONTROLS_DISTANCE
	local watching = state == "live" and editable ~= nil and not hiddenByMe
	controlsGui.Enabled = mode == "none" and near and (watching or hiddenByMe)
	bar.Visible = watching and next(allowed) ~= nil
	fullscreenButton.Visible = allowed.fullscreen == true
	cinemaButton.Visible = allowed.cinema == true
	miniButton.Visible = allowed.mini == true
	hideButton.Text = if hiddenByMe then "👁 Show screen (H)" else "🚫 Hide (H)"
	local serverHidden = frames:GetAttribute("Hidden") == true
	moderatorGui.Enabled = player:GetAttribute("RlpsModerator") == true -- anywhere in the game: it is a kill switch
	modButton.Text = if serverHidden then "▶ Show screen for everyone" else "⛔ Hide screen for everyone"
end

fullscreenButton.Activated:Connect(function()
	setMode("fullscreen")
end)
cinemaButton.Activated:Connect(function()
	setMode("cinema")
end)
miniButton.Activated:Connect(function()
	setMode("mini")
end)
fsExit.Activated:Connect(function()
	setMode("none")
end)
fsSharp.Activated:Connect(function()
	local sharp = fsPanel.image.ResampleMode ~= Enum.ResamplerMode.Pixelated
	fsPanel.image.ResampleMode = if sharp then Enum.ResamplerMode.Pixelated else Enum.ResamplerMode.Default
	fsSharp.Text = if sharp then "Smooth" else "Sharp"
end)
modButton.Activated:Connect(function()
	frames:FireServer("moderate", if frames:GetAttribute("Hidden") == true then "show" else "hide")
end)
fsFit.Activated:Connect(function()
	local fill = fsPanel.image.ScaleType == Enum.ScaleType.Fit
	fsPanel.image.ScaleType = if fill then Enum.ScaleType.Crop else Enum.ScaleType.Fit
	fsFit.Text = if fill then "Fit" else "Fill"
end)
miniExpand.Activated:Connect(function()
	setMode("fullscreen")
end)
miniClose.Activated:Connect(function()
	setMode("none")
end)
cinemaExit.Activated:Connect(function()
	setMode("none")
end)

local setHiddenByMe: (boolean) -> () -- defined with the networking below

UserInputService.InputBegan:Connect(function(input: InputObject, processedByGame: boolean)
	if processedByGame then
		return -- typing in chat, a text box, a game menu
	end
	local key = input.KeyCode
	if key == Enum.KeyCode.H then
		local _, dist = nearestScreen()
		if hiddenByMe or dist <= CONTROLS_DISTANCE or mode ~= "none" then
			setHiddenByMe(not hiddenByMe)
		end
		return
	end
	local want: Mode? = if key == Enum.KeyCode.F then "fullscreen"
		elseif key == Enum.KeyCode.C then "cinema"
		elseif key == Enum.KeyCode.M then "mini"
		else nil
	if want == nil then
		return
	end
	-- opening needs a live picture and (except closing) a screen close enough to have shown the controls
	local _, dist = nearestScreen()
	if want == mode or mode ~= "none" or (state == "live" and dist <= CONTROLS_DISTANCE) then
		setMode(want)
	end
end)

local lastModeCheck = 0
local function updateModes(now: number)
	if cinemaScreen and mode == "cinema" then
		local camera = workspace.CurrentCamera
		if camera then
			camera.CFrame = (cinemaCFrame(cinemaScreen)) -- keeps framing when the window is resized
		end
	end
	if now - lastModeCheck < 0.25 then
		return
	end
	lastModeCheck = now
	allowed = View.parseModes(frames:GetAttribute("ViewerModes"))
	if mode ~= "none" and not allowed[mode] then
		setMode("none") -- the owner disabled this mode
	end
	refreshControls()
end

-- ------------------------------------------------------------------------------------------------------ networking

-- Bytes of part records processed (or dropped) so far. The server keeps what it sent but this client has not
-- processed yet — its backlog — within about a second of this client's speed (RlpsFanout); acks report it.
local processed = 0

local lastSync = -math.huge
local function requestSync()
	local now = os.clock()
	if now - lastSync >= SYNC_COOLDOWN then
		lastSync = now
		frames:FireServer("sync", processed)
	end
end

-- Messages are queued and processed on Heartbeat within a time budget, so a large frame never freezes the game:
-- a frame may be assembled over several game frames (the EditableImage keeps showing the previous complete one).
type Msg = { kind: string, a: unknown, b: unknown, c: unknown }
local queue: { Msg } = {}
local qHead, qTail = 1, 0 -- explicit bounds: processed slots are set to nil, so `#queue` would be meaningless
local lastAckAt = 0
local ackedSession, ackedSeq, ackedBytes = 0, 0, 0
local decodeSpent = 0 -- seconds of decoding spent on the frame being assembled
local costMs = 0 -- moving average decode cost of one complete frame (sent with acks: the server derives a fps cap)

local function countPart(a: unknown)
	if typeof(a) == "buffer" then
		processed += buffer.len(a :: buffer)
	end
end

local function dropQueue()
	for i = qHead, qTail do
		local m = queue[i]
		if m and m.kind == "part" then
			countPart(m.a) -- dropped parts count as processed: the server must not wait for them
		end
	end
	table.clear(queue)
	qHead, qTail = 1, 0
end

local function handle(m: Msg)
	local kind, a, b, c = m.kind, m.a, m.b, m.c
	if kind == "part" then
		countPart(a)
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
	local isStatus = kind == "status"
	if hiddenByMe and not isStatus then
		return -- the screen is hidden for this player: nothing of the stream is kept (the server stops sending)
	end
	if kind == "status" and a == "stopped" then
		-- sharing stopped: drop everything still queued at once (no further pixel of the owner's screen is shown)
		dropQueue()
	end
	if qTail - qHead + 1 >= MAX_QUEUE then
		dropQueue()
		if kind == "part" then
			countPart(a)
		end
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
	if now - lastAckAt < ACK_INTERVAL then
		return
	end
	if core.sessionId ~= ackedSession or core.seq ~= ackedSeq or processed ~= ackedBytes then
		lastAckAt = now
		ackedSession, ackedSeq, ackedBytes = core.sessionId, core.seq, processed
		frames:FireServer("ack", core.sessionId, core.seq, costMs, processed)
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
	script:SetAttribute("ViewMode", mode)
	script:SetAttribute("Redraws", redraws)
	script:SetAttribute("LastRedrawPixels", redrawPixels)
	script:SetAttribute("SkippedRedraws", skippedRedraws)
end

-- Hide the screen for this player (no pixel kept, the server stops sending) or show it again (a fresh sync).
setHiddenByMe = function(hide: boolean)
	if hide == hiddenByMe then
		return
	end
	if hide then
		if mode ~= "none" then
			setMode("none")
		end
		hiddenByMe = true
		frames:FireServer("leave")
		dropQueue()
		core:reset()
		dropPicture()
	else
		hiddenByMe = false
		processed, ackedBytes = 0, 0 -- the server counts this player's bytes from zero again
		setState("connecting", nil)
		lastSync = -math.huge
		requestSync()
	end
	refreshAll()
end
hideButton.Activated:Connect(function()
	setHiddenByMe(not hiddenByMe)
end)

RunService.Heartbeat:Connect(function()
	local now = os.clock()
	processQueue()
	if renderPending or needFullRedraw then
		render(now)
	end
	updateModes(now)
	diagnostics()
	sendAck()
	if not hiddenByMe and ((state == "connecting" and core.framesCompleted == 0) or (core.desynced and state == "live")) then
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
