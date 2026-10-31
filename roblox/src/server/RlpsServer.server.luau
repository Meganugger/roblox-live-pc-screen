--!strict
-- RLPS server script: the single frame-service poll loop of this experience server, playout and fan-out to viewers,
-- and congestion control from client acknowledgements.
--
-- Polls GET <FrameServiceUrl>/v1/frames (desktop/rlps/server.py) with the Bearer token stored as an experience secret.
-- Each response is a bundle of containers (several frames per request — HttpService allows 500 requests/min); every
-- container goes through RlpsRelayCore and the resulting messages are played out at the frames' capture spacing over
-- one reliable RemoteEvent:
--   server -> client: ("status", status, detail?) | ("part", record: buffer) | ("advance", sessionId, fromSeq, toSeq)
--                     | ("reset")  [start of a sync: drop local state, a status + keyframe chain follows]
--   client -> server: ("sync")                         [late joiner / desynced client: send me the relay history]
--                     ("ack", sessionId, seq, costMs)  [frame seq is on my screen; decoding a frame costs costMs]
-- EditableImage changes never replicate, so every client rebuilds the picture itself (RlpsClient.client.luau).
--
-- Congestion control: the stream byte rate starts at StartBytesPerSecond and adapts (AIMD) to what every viewer keeps
-- up with, measured as the age of the oldest frame a viewer has not acknowledged. The rate is sent with every poll;
-- the desktop app encodes at that budget (quality and frame rate follow). Clients also report their decode time per
-- frame, which caps the frame rate (FpsCap) so that the slowest viewer's CPU keeps up. A viewer that falls more than LagDropSeconds
-- behind stops receiving frames until it caught up, then it is re-synced — one slow player does not stall everyone.
--
-- Configuration = attributes on this script (Studio: select the script, edit Attributes):
--   FrameServiceUrl      string  public HTTPS base URL of the frame service (tunnel), e.g. https://xyz.trycloudflare.com
--   SecretName           string  experience secret holding the token (default "rlps_token")
--   PollWaitMs           number  long-poll wait (default 15000, service max 25000; halved on request timeouts)
--   MinPollInterval      number  seconds between poll starts (default 0.15 => <= 400 requests/min of the 500 allowed)
--   StoppedPollInterval  number  seconds between polls while the owner is not sharing (default 1)
--   BatchMs              number  frames collected per response after the first new one (default 150 ms)
--   MaxBytesPerSecond    number  upper bound of the stream rate (default 8000000)
--   StartBytesPerSecond  number  initial stream rate (default 1000000)
--   MinBytesPerSecond    number  lower bound (default 100000)
--   TargetLagSeconds     number  acceptable age of the oldest unacknowledged frame (default 0.35)
--   LagDropSeconds       number  a viewer further behind is paused and re-synced (default 4)
--   ClientDecodeBudgetMs number  decode time per client Heartbeat (default 10 ms; replicated to clients)
--   ViewerUserIds        string  optional comma-separated UserIds allowed to see the screen (empty = everyone)
-- Read-only status attributes: Status, StatusDetail, Containers, ForwardedBytes, Dropped, LastError, RateBps,
-- MaxLagMs, FpsCap, Viewers, LaggingViewers, BodyMode, ForwardFps.

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local RelayCore = require(script.Parent.RlpsRelayCore)
local Decoder = require(script.Parent.RlpsDecoder)
local Base64 = require(script.Parent.RlpsBase64)

local REMOTE_NAME = "RlpsFrames"
local SYNC_COOLDOWN = 2 -- seconds between history syncs for one player
local KEYFRAME_COOLDOWN = 2 -- seconds between keyframe requests caused by clients
local HISTORY_HARD_LIMIT = 48 * 1024 * 1024 -- relay history cap: beyond it the next poll asks for a keyframe
local SYNC_HISTORY_LIMIT = 8 * 1024 * 1024 -- larger histories are not replayed: a fresh keyframe is requested first
local SYNC_HISTORY_FRAMES = 24 -- nor histories with more frames than a client should decode at once
local CONTROL_INTERVAL = 0.5
local MAX_PLAYOUT_BACKLOG = 1.0 -- seconds; beyond it queued frames are forwarded at once (catch up)
local FORWARD_LOG_SECONDS = 15

local function attr(name: string, default: any): any
	local v = script:GetAttribute(name)
	if v == nil then
		script:SetAttribute(name, default)
		return default
	end
	return v
end

local function num(name: string, default: number, lo: number, hi: number): number
	return math.clamp(tonumber(attr(name, default)) or default, lo, hi)
end

local remote = ReplicatedStorage:FindFirstChild(REMOTE_NAME) :: RemoteEvent?
if remote == nil then
	local r = Instance.new("RemoteEvent")
	r.Name = REMOTE_NAME
	r.Parent = ReplicatedStorage
	remote = r
end
local frames = remote :: RemoteEvent

local relay = RelayCore.new({ historyLimitBytes = HISTORY_HARD_LIMIT, errorThreshold = 3 })

-- --------------------------------------------------------------------------------------------- viewers / fan-out

type Viewer = {
	joined: number,
	syncedAt: number,
	ackSession: number,
	ackSeq: number,
	lagging: boolean,
	lastSentSession: number,
	lastSentSeq: number,
	costMs: number, -- client's moving-average decode time per frame
}
local viewers: { [Player]: Viewer } = {}

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

local function viewerOf(player: Player): Viewer
	local v = viewers[player]
	if v == nil then
		local now = os.clock()
		v = { joined = now, syncedAt = now, ackSession = 0, ackSeq = 0, lagging = false, lastSentSession = 0, lastSentSeq = 0,
			costMs = 0 }
		viewers[player] = v
	end
	return v :: Viewer
end

local function anyLagging(): boolean
	for _, v in viewers do
		if v.lagging then
			return true
		end
	end
	return false
end

-- target nil = every eligible viewer (allowed and not lagging)
local function fire(target: Player?, ...: any)
	if target then
		if canView(target) then
			frames:FireClient(target, ...)
		end
	elseif allowed == nil and not anyLagging() then
		frames:FireAllClients(...)
	else
		for _, p in Players:GetPlayers() do
			local v = viewers[p]
			if canView(p) and not (v and v.lagging) then
				frames:FireClient(p, ...)
			end
		end
	end
end

type LogEntry = { session: number, seq: number, t: number }
local forwardLog: { LogEntry } = {}
local forwardedFrames = 0

local function noteForwarded(target: Player?, sessionId: number, seq: number)
	if target then
		local v = viewers[target]
		if v then
			v.lastSentSession, v.lastSentSeq = sessionId, seq
		end
		return
	end
	local now = os.clock()
	table.insert(forwardLog, { session = sessionId, seq = seq, t = now })
	while #forwardLog > 0 and now - forwardLog[1].t > FORWARD_LOG_SECONDS do
		table.remove(forwardLog, 1)
	end
	forwardedFrames += 1
	for p, v in viewers do
		if not v.lagging and canView(p) then
			v.lastSentSession, v.lastSentSeq = sessionId, seq
		end
	end
end

local function send(target: Player?, m: RelayCore.Message)
	if m.kind == "records" then
		for _, record in m.records :: { buffer } do
			fire(target, "part", record)
		end
		noteForwarded(target, m.sessionId :: number, m.toSeq :: number)
	elseif m.kind == "advance" then
		fire(target, "advance", m.sessionId, m.fromSeq, m.toSeq)
		noteForwarded(target, m.sessionId :: number, m.toSeq :: number)
	else
		fire(target, "status", m.status, m.detail)
	end
end

local function publishStatus()
	script:SetAttribute("Status", relay.status)
	script:SetAttribute("StatusDetail", relay.detail or "")
	script:SetAttribute("Containers", relay.containers)
	script:SetAttribute("ForwardedBytes", relay.forwardedBytes)
	script:SetAttribute("Dropped", relay.dropped)
end

-- Playout queue: messages of one container become due at its capture-time offset within the bundle.
type Due = { due: number, messages: { RelayCore.Message } }
local playout: { Due } = {}
local lastDue = 0

local function enqueue(messages: { RelayCore.Message }, due: number)
	if #messages == 0 then
		return
	end
	local now = os.clock()
	due = math.max(due, lastDue)
	if due - now > MAX_PLAYOUT_BACKLOG then
		due = now -- far behind: stop pacing, catch up
	end
	lastDue = due
	table.insert(playout, { due = due, messages = messages })
end

local function flushPlayout(now: number)
	while #playout > 0 and playout[1].due <= now do
		local item = table.remove(playout, 1) :: Due
		for _, m in item.messages do
			send(nil, m)
		end
	end
	publishStatus()
end

-- Server-side status that does not come from the frame service (configuration problems): immediate.
local function setServerStatus(status: RelayCore.Status, detail: string?)
	if relay.status ~= status or relay.detail ~= detail then
		relay.status, relay.detail = status, detail
		send(nil, { kind = "status", status = status, detail = detail } :: RelayCore.Message)
		publishStatus()
	end
end

local function broadcastNow(messages: { RelayCore.Message }?)
	if messages then
		for _, m in messages do
			send(nil, m)
		end
	end
	publishStatus()
end

-- -------------------------------------------------------------------------------------------------- client sync

local lastSync: { [Player]: number } = {}
local pendingSync: { [Player]: boolean } = {}
local lastKeyframeRequest = 0

local function syncPlayer(player: Player, force: boolean?)
	if not canView(player) then
		frames:FireClient(player, "status", "error", "not authorized to view this screen")
		return
	end
	local now = os.clock()
	if not force and now - (lastSync[player] or -math.huge) < SYNC_COOLDOWN then
		return
	end
	lastSync[player] = now
	if relay.historyBytes > SYNC_HISTORY_LIMIT or #relay.history > SYNC_HISTORY_FRAMES then
		pendingSync[player] = true -- replaying that much would take longer than a fresh keyframe
		if now - lastKeyframeRequest >= KEYFRAME_COOLDOWN then
			lastKeyframeRequest = now
			relay:requestKeyframe()
		end
		frames:FireClient(player, "status", "connecting", "catching up with the stream")
		return
	end
	pendingSync[player] = nil
	local v = viewerOf(player)
	v.syncedAt, v.lagging = now, false
	frames:FireClient(player, "reset")
	local messages = relay:syncMessages()
	for _, m in messages do
		send(player, m)
	end
	if relay.seq > 0 then
		v.lastSentSession, v.lastSentSeq = relay.sessionId, relay.seq
	end
	if #messages <= 1 and relay.status == "live" and now - lastKeyframeRequest >= KEYFRAME_COOLDOWN then
		lastKeyframeRequest = now
		relay:requestKeyframe() -- no keyframe in the history yet: the next poll asks for one (broadcast to all)
	end
end

frames.OnServerEvent:Connect(function(player: Player, kind: unknown, a: unknown, b: unknown, c: unknown)
	if kind == "sync" then
		syncPlayer(player)
	elseif kind == "ack" and typeof(a) == "number" and typeof(b) == "number" then
		local v = viewerOf(player)
		local session, seq = a :: number, b :: number
		if typeof(c) == "number" and c == c and c >= 0 and c < 10000 then
			v.costMs = c :: number
		end
		if session ~= v.ackSession then
			v.ackSession, v.ackSeq = session, seq
		elseif seq > v.ackSeq then
			v.ackSeq = seq
		end
		if v.lagging and v.ackSession == v.lastSentSession and v.ackSeq >= v.lastSentSeq then
			v.lagging = false -- caught up with everything it was sent: rejoin the live stream with a fresh sync
			syncPlayer(player, true)
		end
	end
end)

Players.PlayerRemoving:Connect(function(player: Player)
	lastSync[player] = nil
	pendingSync[player] = nil
	viewers[player] = nil
end)

-- ---------------------------------------------------------------------------------------------- rate control

local rate = num("StartBytesPerSecond", 1000000, 10000, 1e9)
local fpsCap = 10 -- frames/s every viewer can decode (from the decode cost reported with acks); ramps up from 10
local controlBytes, controlAt = 0, os.clock()

local function viewerLag(v: Viewer, now: number): number
	for _, e in forwardLog do
		if e.t >= v.syncedAt and not (e.session == v.ackSession and e.seq <= v.ackSeq) then
			return now - e.t
		end
	end
	return 0
end

local function control()
	local now = os.clock()
	local dt = now - controlAt
	if dt < CONTROL_INTERVAL then
		return
	end
	local maxRate = num("MaxBytesPerSecond", 8000000, 10000, 1e9)
	local minRate = math.min(num("MinBytesPerSecond", 100000, 10000, 1e9), maxRate)
	local target = num("TargetLagSeconds", 0.35, 0.05, 10)
	local dropLag = num("LagDropSeconds", 4, 0.5, 60)
	local demand = (relay.forwardedBytes - controlBytes) / dt
	controlBytes, controlAt = relay.forwardedBytes, now
	local budgetMs = num("ClientDecodeBudgetMs", 10, 2, 50)
	local decodeFps = 60
	local maxLag, measured, lagging, count = 0, 0, 0, 0
	for p, v in viewers do
		if canView(p) then
			count += 1
			if v.lagging then
				lagging += 1
			elseif now - v.syncedAt > 2 then
				local lag = viewerLag(v, now)
				measured += 1
				if lag > dropLag then
					v.lagging = true -- stop feeding it; it rejoins once it acknowledged what it was sent
					lagging += 1
					warn(string.format("[RLPS] %s is %.1f s behind: paused until it catches up", p.Name, lag))
				else
					maxLag = math.max(maxLag, lag)
					if v.costMs > 0 then -- a client decodes for budgetMs per Heartbeat (~60 Hz); keep 30 % headroom
						decodeFps = math.min(decodeFps, budgetMs * 60 * 0.7 / v.costMs)
					end
				end
			end
		end
	end
	if measured > 0 then
		if maxLag > target * 2 then
			rate = math.max(minRate, rate * 0.7)
		elseif maxLag > target then
			rate = math.max(minRate, rate * 0.9)
		elseif demand >= rate * 0.6 then
			rate = math.min(maxRate, rate * 1.12 + 20000) -- the stream uses the budget and everyone keeps up: grow
		end
	end
	rate = math.clamp(rate, minRate, maxRate)
	if measured > 0 then
		local fpsTarget = math.clamp(decodeFps, 2, 60)
		fpsCap = if fpsTarget < fpsCap then fpsTarget else math.min(fpsTarget, fpsCap + 2) -- drop at once, recover slowly
		if maxLag > num("TargetLagSeconds", 0.35, 0.05, 10) * 2 then
			fpsCap = math.max(2, fpsCap * 0.8)
		end
	end
	script:SetAttribute("FpsCap", math.floor(fpsCap * 10 + 0.5) / 10)
	script:SetAttribute("RateBps", math.floor(rate))
	script:SetAttribute("MaxLagMs", math.floor(maxLag * 1000))
	script:SetAttribute("Viewers", count)
	script:SetAttribute("LaggingViewers", lagging)
	script:SetAttribute("ForwardFps", math.floor(forwardedFrames / dt * 10 + 0.5) / 10)
	forwardedFrames = 0
	frames:SetAttribute("DecodeBudgetMs", num("ClientDecodeBudgetMs", 10, 2, 50))
end

RunService.Heartbeat:Connect(function()
	flushPlayout(os.clock())
	control()
end)

-- ---------------------------------------------------------------------------------------------------- polling

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

local function decodeBase64(body: string): (buffer?, string?)
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

local MIN_WAIT_MS = 2000
local effectiveWaitMs: number? = nil
local function isTimeout(reason: string): boolean
	local l = string.lower(reason)
	return string.find(l, "timedout", 1, true) ~= nil or string.find(l, "timed out", 1, true) ~= nil
		or string.find(l, "timeout", 1, true) ~= nil
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

-- Binary bodies save the base64 overhead (25 %) but Roblox does not document that response bodies are binary-safe:
-- they are used only when /v1/probe (all 256 byte values) arrives unchanged. Re-probed when the URL changes.
local PROBE: string
do
	local b = buffer.create(1024)
	for i = 0, 1023 do
		buffer.writeu8(b, i, i % 256)
	end
	PROBE = buffer.tostring(b)
end
local bodyMode: "raw" | "base64" | nil = nil
local probedUrl = ""

local function probe(base: string, auth: any)
	local ok, res = pcall(function(): any
		return HttpService:RequestAsync({ Url = base .. "/v1/probe", Method = "GET", Headers = { Authorization = auth } })
	end)
	bodyMode = if ok and res.Success and res.Body == PROBE then "raw" else "base64"
	probedUrl = base
	script:SetAttribute("BodyMode", bodyMode)
end

local function schedule(data: buffer): (boolean, string?)
	local entries, berr = Decoder.parseBundle(data)
	if entries == nil then
		return false, "invalid bundle: " .. tostring(berr)
	end
	local arrival = os.clock()
	for _, e in entries do
		local container = Decoder.extractEntry(data, e)
		local messages, ierr = relay:ingest(container)
		if messages == nil then
			return false, "invalid container: " .. tostring(ierr)
		end
		if relay.status == "stopped" then
			table.clear(playout) -- sharing stopped: nothing queued may still reach a screen
			lastDue = 0
			broadcastNow(messages)
		else
			enqueue(messages, arrival + e.tOffsetMs / 1000)
		end
		if next(pendingSync) and #relay.history <= 2 and relay.history[1] and relay.history[1].records then
			for p in pendingSync do -- a keyframe just restarted the history: replay it to the waiting players
				task.defer(syncPlayer, p, true)
			end
		end
	end
	return true, nil
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
	if bodyMode == nil or probedUrl ~= base then
		probe(base, auth)
	end
	local after, session, key, idle = relay:pollParams()
	local configuredMs = math.floor(num("PollWaitMs", 15000, 0, 25000))
	local waitMs = math.min(configuredMs, effectiveWaitMs or configuredMs)
	local batchMs = math.floor(num("BatchMs", 150, 0, 1000))
	local maxBytes = math.floor(math.clamp(rate * 1.5, 256 * 1024, 8 * 1024 * 1024))
	local url = string.format(
		"%s/v1/frames?after=%d&session=%d&key=%d&wait=%d&idle=%d&rate=%d&batch=%d&max=%d&enc=%d&fps=%d",
		base, after, session, if key then 1 else 0, waitMs, if idle then 1 else 0, math.floor(rate), batchMs, maxBytes,
		if bodyMode == "raw" then 1 else 0, math.max(1, math.floor(fpsCap)))
	local ok, res = pcall(function(): any
		return HttpService:RequestAsync({ Url = url, Method = "GET", Headers = { Authorization = auth } })
	end)
	if not ok then
		local reason = friendly(tostring(res))
		if isTimeout(reason) and waitMs > MIN_WAIT_MS then
			effectiveWaitMs = math.max(MIN_WAIT_MS, math.floor(waitMs / 2))
			warn(string.format("[RLPS] frame request timed out; long-poll wait lowered to %d ms", effectiveWaitMs :: number))
		end
		script:SetAttribute("LastError", reason)
		broadcastNow(relay:fail("request failed: " .. reason))
		return math.min(30, 2 ^ math.min(relay.consecutiveErrors, 5))
	end
	if not res.Success then
		local code = res.StatusCode :: number
		local reason = "HTTP " .. code .. " " .. tostring(res.StatusMessage)
		if code == 401 then
			reason = "frame service rejected the token (HTTP 401): check the secret"
		end
		script:SetAttribute("LastError", reason)
		broadcastNow(relay:fail(reason))
		local retry = tonumber(header(res.Headers, "retry-after") or "")
		if retry then
			return math.clamp(retry, 1, 60)
		end
		return math.min(30, 2 ^ math.min(relay.consecutiveErrors, 5))
	end
	local body = res.Body :: string
	local data: buffer?, derr: string?
	if bodyMode == "raw" then
		data = buffer.fromstring(body)
	else
		data, derr = decodeBase64(body)
	end
	if data == nil then
		script:SetAttribute("LastError", "bad body: " .. tostring(derr))
		broadcastNow(relay:fail("bad response body: " .. tostring(derr)))
		return 2
	end
	local scheduled, serr = schedule(data :: buffer)
	if not scheduled then
		if bodyMode == "raw" then
			bodyMode = "base64" -- bytes were altered on the way: never trust raw bodies on this server again
			probedUrl = base
			script:SetAttribute("BodyMode", "base64")
			warn("[RLPS] binary response body was altered in transit; switched to base64")
		end
		script:SetAttribute("LastError", tostring(serr))
		broadcastNow(relay:fail(tostring(serr)))
		return 2
	end
	publishStatus()
	if relay.status == "stopped" then
		return num("StoppedPollInterval", 1, 0.5, 30)
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
	publishStatus()
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
		local minInterval = num("MinPollInterval", 0.15, 0.05, 60)
		local elapsed = os.clock() - started
		task.wait(math.max(delay, minInterval - elapsed, 0.03))
	end
end)
