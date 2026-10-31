--!strict
-- RLPS server script: the single frame-service poll loop of this experience server, playout, per-viewer delivery
-- (RlpsFanout) and congestion control from client acknowledgements.
--
-- Polls GET <FrameServiceUrl>/v1/frames (desktop/rlps/server.py) with the Bearer token stored as an experience secret.
-- Each response is a bundle of containers (several frames per request — HttpService allows 500 requests/min); every
-- container goes through RlpsRelayCore and the resulting messages are played out at the frames' capture spacing over
-- one reliable RemoteEvent:
--   server -> client: ("status", status, detail?) | ("part", record: buffer) | ("advance", sessionId, fromSeq, toSeq)
--                     | ("reset")  [start of a sync: drop local state, a status + keyframe chain follows]
--   client -> server: ("sync", processed)                        [join / lost the chain: send me the stream]
--                     ("ack", sessionId, seq, costMs, processed) [frame seq is on my screen; decoding a frame costs
--                                                                 costMs; I processed `processed` bytes of parts]
-- EditableImage changes never replicate, so every client rebuilds the picture itself (RlpsClient.client.luau).
--
-- Congestion control: each viewer's backlog (bytes sent, not yet processed) stays within about one second of its own
-- measured delivery rate (RlpsFanout: a slow viewer is held, then catches up or waits for a keyframe — it never slows
-- the others down or piles up minutes of stream). The stream byte rate starts at StartBytesPerSecond and adapts
-- (AIMD) to how far behind the median viewer is (age of the oldest frame it has not processed). The rate is sent with
-- every poll; the desktop app encodes at that budget (quality and frame rate follow). Clients also report their
-- decode time per frame, which caps the frame rate (FpsCap) so that the median viewer's CPU keeps up.
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
--   TargetLagSeconds     number  acceptable delay of the median viewer (default 0.35)
--   ClientDecodeBudgetMs number  decode time per client Heartbeat (default 10 ms; replicated to clients)
--   ViewerUserIds        string  optional comma-separated UserIds allowed to see the screen (empty = everyone)
-- Read-only status attributes: Status, StatusDetail, Containers, ForwardedBytes, Dropped, LastError, RateBps, LagMs
-- (median viewer delay), MaxLagMs, FpsCap, Viewers, LaggingViewers (held or waiting for a keyframe), BodyMode,
-- ForwardFps.

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local RelayCore = require(script.Parent.RlpsRelayCore)
local Fanout = require(script.Parent.RlpsFanout)
local Decoder = require(script.Parent.RlpsDecoder)
local Base64 = require(script.Parent.RlpsBase64)

local REMOTE_NAME = "RlpsFrames"
local KEYFRAME_COOLDOWN = 2 -- seconds between keyframe requests made for viewers
local CONTROL_INTERVAL = 0.5
local MAX_PLAYOUT_BACKLOG = 1.0 -- seconds; beyond it queued frames are forwarded at once (catch up)
local NOT_AUTHORIZED = "not authorized to view this screen"

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

local relay = RelayCore.new({ errorThreshold = 3 })

-- --------------------------------------------------------------------------------------------- viewers / fan-out

local fan = Fanout.new(function(player: Player, kind: string, ...: any)
	frames:FireClient(player, kind, ...)
end)
local forwardedFrames = 0

local allowed: { [number]: boolean }? = nil
local function canView(player: Player): boolean
	local set = allowed
	return set == nil or set[player.UserId] == true
end

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
script:GetAttributeChangedSignal("ViewerUserIds"):Connect(function()
	readViewers()
	for _, p in Players:GetPlayers() do
		if fan:viewer(p) and not canView(p) then
			fan:remove(p) -- no further pixel; its client hides the picture on the error status
			frames:FireClient(p, "status", "error", NOT_AUTHORIZED)
		elseif canView(p) and fan:viewer(p) == nil then
			frames:FireClient(p, "status", "connecting", nil) -- newly allowed: its client asks for the stream
		end
	end
end)

local function broadcast(m: RelayCore.Message)
	fan:broadcast(m, os.clock())
	if m.kind ~= "status" then
		forwardedFrames += 1
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
			broadcast(m)
		end
	end
	publishStatus()
end

-- Server-side status that does not come from the frame service (configuration problems): immediate.
local function setServerStatus(status: RelayCore.Status, detail: string?)
	if relay.status ~= status or relay.detail ~= detail then
		relay.status, relay.detail = status, detail
		broadcast({ kind = "status", status = status, detail = detail } :: RelayCore.Message)
		publishStatus()
	end
end

local function broadcastNow(messages: { RelayCore.Message }?)
	if messages then
		for _, m in messages do
			broadcast(m)
		end
	end
	publishStatus()
end

-- ------------------------------------------------------------------------------------------------ client messages

local function count(x: unknown, hi: number): number?
	if typeof(x) == "number" and x == x and x >= 0 and x < hi then
		return x :: number
	end
	return nil
end

frames.OnServerEvent:Connect(function(player: Player, kind: unknown, a: unknown, _b: unknown, c: unknown, d: unknown)
	if kind == "sync" then
		if not canView(player) then
			frames:FireClient(player, "status", "error", NOT_AUTHORIZED)
			return
		end
		fan:sync(player, count(a, 1e15), os.clock())
	elseif kind == "ack" then
		local processed = count(d, 1e15)
		if processed then
			fan:ack(player, processed, os.clock(), count(c, 10000))
		end
	end
end)

Players.PlayerRemoving:Connect(function(player: Player)
	fan:remove(player)
end)

-- ---------------------------------------------------------------------------------------------- rate control

local rate = num("StartBytesPerSecond", 1000000, 10000, 1e9)
local fpsCap = 10 -- frames/s the median viewer can decode (from the decode cost reported with acks); ramps up from 10
local controlBytes, controlAt = 0, os.clock()
local lastKeyframeRequest = -math.huge

local function control()
	local now = os.clock()
	local dt = now - controlAt
	if dt < CONTROL_INTERVAL then
		return
	end
	local maxRate = num("MaxBytesPerSecond", 8000000, 10000, 1e9)
	local minRate = math.min(num("MinBytesPerSecond", 100000, 10000, 1e9), maxRate)
	local target = num("TargetLagSeconds", 0.35, 0.05, 10)
	local demand = (relay.forwardedBytes - controlBytes) / dt
	controlBytes, controlAt = relay.forwardedBytes, now
	local budgetMs = num("ClientDecodeBudgetMs", 10, 2, 50)
	local st = fan:stats(now)
	if st.measured > 0 then
		if st.lag > target * 2 then
			rate = math.max(minRate, rate * 0.7)
		elseif st.lag > target then
			rate = math.max(minRate, rate * 0.9)
		elseif demand >= rate * 0.6 then
			rate = math.min(maxRate, rate * 1.12 + 20000) -- the stream uses the budget and viewers keep up: grow
		end
		-- a client decodes for budgetMs per Heartbeat (~60 Hz); keep 30 % headroom
		local decodeFps = if st.costMs > 0 then budgetMs * 60 * 0.7 / st.costMs else 60
		local fpsTarget = math.clamp(decodeFps, 2, 60)
		fpsCap = if fpsTarget < fpsCap then fpsTarget else math.min(fpsTarget, fpsCap + 2) -- drop at once, recover slowly
		if st.lag > target * 2 then
			fpsCap = math.max(2, fpsCap * 0.8)
		end
	end
	rate = math.clamp(rate, minRate, maxRate)
	if fan:wantsKeyframe() and now - lastKeyframeRequest >= KEYFRAME_COOLDOWN then
		lastKeyframeRequest = now
		relay:requestFreshKeyframe() -- late joiners / slow viewers wait for it; the next polls ask for one
	end
	script:SetAttribute("FpsCap", math.floor(fpsCap * 10 + 0.5) / 10)
	script:SetAttribute("RateBps", math.floor(rate))
	script:SetAttribute("LagMs", math.floor(math.min(st.lag, 999) * 1000))
	script:SetAttribute("MaxLagMs", math.floor(math.min(st.maxLag, 999) * 1000))
	script:SetAttribute("Viewers", st.viewers)
	script:SetAttribute("LaggingViewers", st.lagging)
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
	local after, session, key, idle, fresh = relay:pollParams()
	local configuredMs = math.floor(num("PollWaitMs", 15000, 0, 25000))
	local waitMs = math.min(configuredMs, effectiveWaitMs or configuredMs)
	local batchMs = math.floor(num("BatchMs", 150, 0, 1000))
	local maxBytes = math.floor(math.clamp(rate * 1.5, 256 * 1024, 8 * 1024 * 1024))
	local url = string.format(
		"%s/v1/frames?after=%d&session=%d&key=%d&fresh=%d&wait=%d&idle=%d&rate=%d&batch=%d&max=%d&enc=%d&fps=%d",
		base, after, session, if key then 1 else 0, if fresh then 1 else 0, waitMs, if idle then 1 else 0,
		math.floor(rate), batchMs, maxBytes, if bodyMode == "raw" then 1 else 0, math.max(1, math.floor(fpsCap)))
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
