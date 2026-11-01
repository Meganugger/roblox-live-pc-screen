--!strict
-- RLPS fan-out (T-0021): delivers the played-out stream to every viewer with per-viewer flow control. Pure Luau (no
-- Roblox APIs) so the standalone specs can drive it; RlpsServer.server.luau owns the RemoteEvent, players and clock.
--
-- Every viewer acknowledges how many bytes of part records it has processed. What it was sent but has not processed
-- yet is its backlog — in the network or in its decode queue — and reliable RemoteEvents cannot be recalled. So the
-- backlog of each viewer is kept inside a window of about half a second of what that viewer actually processes (its
-- delivery rate, measured from its acks; at least `minWindow`): a slow player never piles up minutes of stream, and
-- every later message (Stop included) reaches it in bounded time. A viewer is
--   live     receiving the stream while its backlog stays inside the window;
--   held     its window is full: it gets status messages only until it processed everything it was sent, then it
--            catches up from the played history — just the frames it missed — and is live again; or, when replaying
--            costs more than a fresh keyframe would,
--   waiting  for the next keyframe (`wantsKeyframe` asks the server to request one).
-- Late joiners and desynced clients ("sync") start the same way from the played history: the last keyframe and the
-- frames after it, in the order they were broadcast.

local RelayCore = require(script.Parent.RlpsRelayCore)

type Message = RelayCore.Message

local Fanout = {}
Fanout.__index = Fanout

-- Fires one message to one viewer: ("part", record) | ("advance", sessionId, fromSeq, toSeq) | ("status", status,
-- detail) | ("reset").
export type Send = (key: any, kind: string, ...any) -> ()

export type Config = {
	minWindow: number?, -- backlog bytes allowed whatever the viewer's measured rate (default 64 KB)
	windowSeconds: number?, -- backlog allowed, in seconds of the viewer's delivery rate (default 0.5)
	baseWindow: number?, -- seconds of delay samples behind a viewer's base (uncongested) delay (default 10)
	rateWindow: number?, -- seconds of delivery-rate samples behind the estimate (windowed maximum, default 5)
	maxReplayFrames: number?, -- a catch-up never replays more frames than this (default 24)
	maxReplayBytes: number?, -- nor more bytes (default 8 MB)
	historyLimit: number?, -- played history beyond this asks for a keyframe, which restarts it (default 48 MB)
	syncInterval: number?, -- seconds between two sync answers for one viewer (default 1)
	warmup: number?, -- seconds after a (re)start during which a viewer does not count for rate control (default 1)
}

type Flight = { cum: number, t: number, delivered: number } -- one records message in flight
type Sample = { t: number, rate: number }
type DelaySample = { t: number, d: number }

export type State = "live" | "held" | "waiting"

export type Viewer = {
	state: State,
	sent: number, -- bytes of part records sent to it
	acked: number, -- bytes it reported processed (never more than `sent`)
	syncEnd: number, -- `sent` after its last fresh start: sync requests wait until it processed that much
	syncAt: number,
	session: number, -- chain position = last frame message sent to it
	seq: number,
	flights: { Flight },
	samples: { Sample },
	rate: number, -- delivery-rate estimate, bytes/s (0 = unknown)
	delays: { DelaySample }, -- send -> processed delay of recent messages (seconds)
	baseDelay: number, -- the smallest of them: network + decode time without any queue (math.huge = unknown)
	queueDelay: number, -- smoothed delay above baseDelay: time messages wait in queues (network or decode)
	decodeWait: number, -- smoothed client-reported wait in its decode queue (seconds): the CPU part of queueDelay
	since: number, -- last (re)start: join or sync
	waitingSince: number,
	costMs: number, -- client-reported decode time per frame
	needsReset: boolean, -- next fresh start begins with "reset" (sync request)
	holds: number, -- how often its window filled (diagnostics)
}

export type Stats = {
	viewers: number,
	lagging: number, -- held + waiting
	measured: number, -- viewers past their warm-up
	lag: number, -- lower median over measured viewers of how far behind they are (seconds; see Fanout.stats)
	queueDelay: number, -- lower median over measured live viewers of their *network* queueing delay (seconds)
	decodeWait: number, -- lower median of their decode-queue waits (seconds): clients short of CPU
	deliveryRate: number, -- lower median of their delivery-rate estimates (bytes/s; 0 = unknown)
	maxLag: number, -- the largest of those
	costMs: number, -- lower median decode cost per frame (0 = none reported)
}

export type Fanout = typeof(setmetatable(
	{} :: {
		send: Send,
		viewers: { [any]: Viewer },
		played: { Message }, -- broadcast stream since its last keyframe
		playedBytes: number,
		keyBytes: number, -- size of that keyframe
		status: RelayCore.Status,
		detail: string?,
		session: number, -- position of the last broadcast frame message
		seq: number,
		minWindow: number,
		windowSeconds: number,
		baseWindow: number,
		rateWindow: number,
		maxReplayFrames: number,
		maxReplayBytes: number,
		historyLimit: number,
		syncInterval: number,
		warmup: number,
	},
	Fanout
))

function Fanout.new(send: Send, config: Config?): Fanout
	local cfg = (config or {}) :: Config
	return setmetatable({
		send = send,
		viewers = {} :: { [any]: Viewer },
		played = {} :: { Message },
		playedBytes = 0,
		keyBytes = 0,
		status = "connecting" :: RelayCore.Status,
		detail = nil :: string?,
		session = 0,
		seq = 0,
		minWindow = cfg.minWindow or 64 * 1024,
		windowSeconds = cfg.windowSeconds or 0.5,
		baseWindow = cfg.baseWindow or 10,
		rateWindow = cfg.rateWindow or 5,
		maxReplayFrames = cfg.maxReplayFrames or 24,
		maxReplayBytes = cfg.maxReplayBytes or 8 * 1024 * 1024,
		historyLimit = cfg.historyLimit or 48 * 1024 * 1024,
		syncInterval = cfg.syncInterval or 1,
		warmup = cfg.warmup or 1,
	}, Fanout)
end

local function bytesOf(m: Message): number
	if m.kind ~= "records" then
		return 0
	end
	if m.bytes then
		return m.bytes
	end
	local n = 0
	for _, r in m.records :: { buffer } do
		n += buffer.len(r)
	end
	return n
end

local function window(self: Fanout, v: Viewer): number
	return math.max(self.minWindow, v.rate * self.windowSeconds)
end

local function sendFrame(self: Fanout, key: any, v: Viewer, m: Message, now: number)
	if m.kind == "records" then
		local n = 0
		for _, r in m.records :: { buffer } do
			self.send(key, "part", r)
			n += buffer.len(r)
		end
		v.sent += n
		table.insert(v.flights, { cum = v.sent, t = now, delivered = v.acked })
	else
		self.send(key, "advance", m.sessionId, m.fromSeq, m.toSeq)
	end
	v.session, v.seq = m.sessionId :: number, m.toSeq :: number
end

-- Index in `played` of the first message a viewer still needs, and whether that is a fresh start (from the keyframe).
local function replayStart(self: Fanout, v: Viewer): (number, boolean)
	if not v.needsReset and v.session ~= 0 and v.session == self.session then
		for i = #self.played, 1, -1 do
			if self.played[i].toSeq == v.seq then
				return i + 1, false
			end
		end
	end
	return 1, true
end

-- A held (drained) or newly synced viewer rejoins the stream: replay what it misses, or wait for a keyframe.
local function resume(self: Fanout, key: any, v: Viewer, now: number)
	local first, fresh = replayStart(self, v)
	local bytes, frames = 0, 0
	for i = first, #self.played do
		local m = self.played[i]
		if m.kind == "records" then
			bytes += bytesOf(m)
			frames += 1
		end
	end
	if fresh then
		if v.needsReset then
			self.send(key, "reset")
		end
		self.send(key, "status", self.status, self.detail)
	end
	local reset = v.needsReset
	v.needsReset = false
	-- replaying costs `bytes`; a fresh keyframe costs about the keyframe and its refinement plus a wait
	if frames > self.maxReplayFrames or bytes > self.maxReplayBytes
		or bytes > 2 * self.keyBytes + math.max(window(self, v), 2 * self.minWindow)
	then
		v.state, v.waitingSince = "waiting", now
		if reset and self.status == "live" then
			self.send(key, "status", "connecting", "catching up with the stream")
		end
		return
	end
	for i = first, #self.played do
		sendFrame(self, key, v, self.played[i], now)
	end
	v.state = "live"
	if fresh then
		v.syncEnd = v.sent
	end
end

local function newViewer(now: number): Viewer
	return {
		state = "held",
		sent = 0,
		acked = 0,
		syncEnd = 0,
		syncAt = -math.huge,
		session = 0,
		seq = 0,
		flights = {},
		samples = {},
		rate = 0,
		delays = {},
		baseDelay = math.huge,
		queueDelay = 0,
		decodeWait = 0,
		since = now,
		waitingSince = now,
		costMs = 0,
		needsReset = true,
		holds = 0,
	}
end

local function addSample(self: Fanout, v: Viewer, rate: number, now: number)
	local kept: { Sample } = {}
	local best = rate
	for _, s in v.samples do
		if now - s.t <= self.rateWindow then
			table.insert(kept, s)
			best = math.max(best, s.rate)
		end
	end
	table.insert(kept, { t = now, rate = rate })
	v.samples = kept
	v.rate = best
end

local function noteProcessed(self: Fanout, v: Viewer, processed: number, now: number, ageMs: number?)
	if processed ~= processed then
		return -- NaN
	end
	processed = math.clamp(processed, v.acked, v.sent) -- monotonic, never beyond what it was sent
	if processed <= v.acked then
		return
	end
	v.acked = processed
	local last: Flight? = nil
	while v.flights[1] and v.flights[1].cum <= processed do
		last = table.remove(v.flights, 1)
	end
	if last then
		-- delivery rate over the flight of the newest fully processed message (BBR-style sample)
		addSample(self, v, (processed - last.delivered) / math.max(now - last.t, 0.02), now)
		-- and its delay. The smallest delay of the last baseWindow seconds is the path without queues (LEDBAT-style
		-- base delay); what exceeds it is time spent queued — the signal the rate control keeps small.
		-- (minus the time the ack itself waited on the client after the part was processed: not a queue)
		local d = math.max(0, now - last.t - (ageMs or 0) / 1000)
		local kept: { DelaySample } = {}
		local base = d
		for _, s in v.delays do
			if now - s.t <= self.baseWindow then
				table.insert(kept, s)
				base = math.min(base, s.d)
			end
		end
		table.insert(kept, { t = now, d = d })
		v.delays, v.baseDelay = kept, base
		v.queueDelay = v.queueDelay * 0.5 + (d - base) * 0.5
	end
end

-- One played-out relay message, in stream order.
function Fanout.broadcast(self: Fanout, m: Message, now: number)
	if m.kind == "status" then
		self.status, self.detail = m.status :: RelayCore.Status, m.detail
		if m.status == "stopped" then
			table.clear(self.played)
			self.playedBytes, self.keyBytes, self.session, self.seq = 0, 0, 0, 0
		end
		for key in self.viewers do -- every viewer, held ones included: Stop must reach all screens
			self.send(key, "status", m.status, m.detail)
		end
		return
	end
	local bytes = bytesOf(m)
	if m.kind == "records" and m.keyframe then
		table.clear(self.played)
		self.playedBytes, self.keyBytes = 0, bytes
	end
	table.insert(self.played, m)
	self.playedBytes += bytes
	self.session, self.seq = m.sessionId :: number, m.toSeq :: number
	for key, v in self.viewers do
		if v.state == "live" then
			local backlog = v.sent - v.acked
			if bytes > 0 and backlog > 0 and backlog + bytes > window(self, v) then
				v.state = "held" -- resumes once it processed everything (Fanout.ack)
				v.holds += 1
			else
				sendFrame(self, key, v, m, now)
			end
		elseif v.state == "waiting" and m.kind == "records" and m.keyframe then
			sendFrame(self, key, v, m, now)
			v.state = "live"
			v.syncEnd = v.sent
		end
	end
end

-- A viewer processed `processed` bytes of part records in total (its decode cost per frame is costMs).
function Fanout.ack(self: Fanout, key: any, processed: number, now: number, costMs: number?, waitMs: number?,
	ageMs: number?)
	local v = self.viewers[key]
	if v == nil then
		return
	end
	if costMs then
		v.costMs = costMs
	end
	if waitMs then
		v.decodeWait = v.decodeWait * 0.5 + waitMs / 1000 * 0.5
	end
	noteProcessed(self, v, processed, now, ageMs)
	if v.state == "held" and v.acked >= v.sent then
		resume(self, key, v, now)
	end
end

-- A viewer asks for the stream from scratch (it joined, or lost the chain). `processed` as in Fanout.ack.
function Fanout.sync(self: Fanout, key: any, processed: number?, now: number)
	local v = self.viewers[key]
	if v == nil then
		v = newViewer(now)
		self.viewers[key] = v
	else
		if processed then
			noteProcessed(self, v, processed, now)
		end
		if v.state == "waiting" or v.acked < v.syncEnd or now - v.syncAt < self.syncInterval then
			return -- a fresh start is already on its way
		end
		v.needsReset, v.since = true, now
		if v.state == "live" then
			v.state = "held"
		end
	end
	v.syncAt = now
	if v.acked >= v.sent then
		resume(self, key, v, now)
	end
end

function Fanout.remove(self: Fanout, key: any)
	self.viewers[key] = nil
end

-- The server should ask the frame service for a keyframe: a viewer waits for one, or the history grew too long.
function Fanout.wantsKeyframe(self: Fanout): boolean
	if self.playedBytes > self.historyLimit then
		return true
	end
	for _, v in self.viewers do
		if v.state == "waiting" then
			return true
		end
	end
	return false
end

-- Rate-control inputs. A viewer is behind by the age of the oldest frame it was sent and has not processed yet (or,
-- waiting for a keyframe, by how long it has waited). Lower medians: the stream follows what the majority of viewers
-- keeps up with; a minority of slow viewers is held and caught up instead of slowing everyone down.
function Fanout.stats(self: Fanout, now: number): Stats
	local lags: { number } = {}
	local costs: { number } = {}
	local queues: { number } = {}
	local waits: { number } = {}
	local rates: { number } = {}
	local count, lagging, maxLag = 0, 0, 0
	for _, v in self.viewers do
		count += 1
		if v.state ~= "live" then
			lagging += 1
		end
		if now - v.since >= self.warmup then
			local lag = if v.state == "waiting" then now - v.waitingSince
				elseif v.flights[1] then now - v.flights[1].t
				else 0
			maxLag = math.max(maxLag, lag)
			table.insert(lags, lag)
			if v.state == "live" and v.costMs > 0 then
				table.insert(costs, v.costMs)
			end
			if v.state ~= "waiting" and v.baseDelay < math.huge then -- held viewers too: they are held *because* queued
				-- nothing acked for a while counts as queued: the oldest message still in flight has waited `lag`
				-- (minus the ~0.15 s a message may normally wait for the next ack and the next frame). Time spent in
				-- the client's own decode queue is the CPU's, not the network's.
				table.insert(queues, math.max(0, math.max(v.queueDelay, lag - v.baseDelay - 0.15) - v.decodeWait))
				table.insert(waits, v.decodeWait)
				if v.rate > 0 then
					table.insert(rates, v.rate)
				end
			end
		end
	end
	table.sort(lags)
	table.sort(costs)
	table.sort(queues)
	table.sort(waits)
	table.sort(rates)
	return {
		viewers = count,
		lagging = lagging,
		measured = #lags,
		lag = if #lags > 0 then lags[(#lags + 1) // 2] else 0,
		maxLag = maxLag,
		queueDelay = if #queues > 0 then queues[(#queues + 1) // 2] else 0,
		deliveryRate = if #rates > 0 then rates[(#rates + 1) // 2] else 0,
		decodeWait = if #waits > 0 then waits[(#waits + 1) // 2] else 0,
		costMs = if #costs > 0 then costs[(#costs + 1) // 2] else 0,
	}
end

function Fanout.viewer(self: Fanout, key: any): Viewer?
	return self.viewers[key]
end

return Fanout
