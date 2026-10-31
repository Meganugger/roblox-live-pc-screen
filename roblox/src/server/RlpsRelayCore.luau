--!strict
-- RLPS server relay core (T-0012). Turns frame-service containers into the ordered message stream that the server
-- script plays out to viewers (RlpsFanout keeps the history late joiners replay) and tracks the poll cursor
-- (after/session/key). Pure Luau (no Roblox APIs) so the standalone harness can test it; RlpsServer.server.luau owns
-- HttpService, the RemoteEvent and the single poll loop of the experience server.
--
-- Invariant: the forwarded stream is always a valid chain for RlpsClientCore — a keyframe, then deltas whose baseSeq
-- is the previous seq, or advances; anything that does not extend the chain is dropped and a keyframe is requested.

local Protocol = require(script.Parent.RlpsProtocol)
local Decoder = require(script.Parent.RlpsDecoder)

local RelayCore = {}
RelayCore.__index = RelayCore

export type Status = "connecting" | "live" | "stopped" | "error"

-- "records": part records of one container (forward in order; keyframe = it starts a new chain); "advance": frame
-- toSeq looks like fromSeq; "status": sharing/connection state changed.
export type Message = {
	kind: "records" | "advance" | "status",
	records: { buffer }?,
	bytes: number?,
	keyframe: boolean?,
	sessionId: number?,
	fromSeq: number?,
	toSeq: number?,
	status: Status?,
	detail: string?,
}

export type Config = {
	errorThreshold: number?, -- consecutive poll failures before status becomes "error"
}

export type Relay = typeof(setmetatable(
	{} :: {
		status: Status,
		detail: string?,
		sessionId: number, -- chain position = last forwarded complete frame (0 = none)
		seq: number,
		width: number,
		height: number,
		wantKeyframe: boolean, -- the chain is unknown or broken: the next poll asks for the chain from a keyframe
		wantFresh: boolean, -- viewers need a new keyframe: the chain continues, the next captured frame is one
		errorThreshold: number,
		consecutiveErrors: number,
		containers: number,
		forwardedBytes: number,
		dropped: number,
		lastDrop: string?,
	},
	RelayCore
))

function RelayCore.new(config: Config?): Relay
	local cfg = (config or {}) :: Config
	return setmetatable({
		status = "connecting" :: Status,
		detail = nil :: string?,
		sessionId = 0,
		seq = 0,
		width = 0,
		height = 0,
		wantKeyframe = true,
		wantFresh = false,
		errorThreshold = cfg.errorThreshold or 3,
		consecutiveErrors = 0,
		containers = 0,
		forwardedBytes = 0,
		dropped = 0,
		lastDrop = nil :: string?,
	}, RelayCore)
end

-- Query parameters for the next GET /v1/frames poll: after, session, key, idle (idle = the relay already reports
-- "stopped", so the frame service may hold the poll until sharing starts), fresh (continue the chain, but make the
-- next captured frame a keyframe).
function RelayCore.pollParams(self: Relay): (number, number, boolean, boolean, boolean)
	local key = self.wantKeyframe or self.seq == 0
	return self.seq, self.sessionId, key, self.status == "stopped", self.wantFresh and not key
end

local function setStatus(self: Relay, out: { Message }, status: Status, detail: string?)
	if self.status ~= status or self.detail ~= detail then
		self.status, self.detail = status, detail
		local m: Message = { kind = "status", status = status, detail = detail }
		table.insert(out, m)
	end
end

local function clearChain(self: Relay)
	self.sessionId, self.seq, self.width, self.height = 0, 0, 0, 0
	self.wantKeyframe, self.wantFresh = true, false
end

local function drop(self: Relay, reason: string, needKeyframe: boolean)
	self.dropped += 1
	self.lastDrop = reason
	if needKeyframe then
		self.wantKeyframe = true
	end
end

-- Feed one decoded frame-service container. Returns the messages to broadcast (possibly none), or nil + reason when
-- the container is invalid (nothing is forwarded then; the caller reports it once with `fail`, which broadcasts the
-- error status at the threshold — counting it here as well made the error status reach clients never).
function RelayCore.ingest(self: Relay, data: buffer): ({ Message }?, string?)
	local c, err = Decoder.parseContainer(data)
	if c == nil then
		return nil, err
	end
	self.consecutiveErrors = 0
	self.containers += 1
	local out: { Message } = {}
	if c.state == Protocol.STATE_STOPPED then
		clearChain(self)
		setStatus(self, out, "stopped", nil)
		return out, nil
	end
	if c.unchanged then
		if c.sessionId ~= 0 and c.sessionId == self.sessionId and self.seq > 0 then
			if c.seq > self.seq then
				local m: Message = { kind = "advance", sessionId = c.sessionId, fromSeq = self.seq, toSeq = c.seq }
				self.seq = c.seq
				table.insert(out, m)
			end
			setStatus(self, out, "live", nil)
		else
			-- live but nothing forwarded yet for this session (or a new session started): need a keyframe
			if c.sessionId ~= self.sessionId and self.sessionId ~= 0 then
				clearChain(self)
			end
			self.wantKeyframe = true
			setStatus(self, out, "live", if c.seq == 0 then "waiting for the first frame" else nil)
		end
		return out, nil
	end
	local accept = false
	if c.keyframe then
		accept = self.wantKeyframe or c.sessionId ~= self.sessionId or c.seq > self.seq
		if not accept then
			drop(self, "duplicate keyframe", false)
		end
	elseif c.sessionId == self.sessionId and self.seq > 0 and c.baseSeq == self.seq then
		accept = true
	elseif c.sessionId == self.sessionId and c.seq <= self.seq then
		drop(self, "stale delta", false)
	else
		drop(self, "delta does not extend the forwarded chain", true)
	end
	if not accept then
		setStatus(self, out, "live", nil)
		return out, nil
	end
	local records: { buffer } = {}
	local bytes = 0
	for i, ref in c.parts do
		records[i] = Decoder.extractRecord(data, ref)
		bytes += ref.length
	end
	local m: Message = { kind = "records", records = records, bytes = bytes, keyframe = c.keyframe,
		sessionId = c.sessionId, toSeq = c.seq }
	if c.keyframe then
		self.wantKeyframe, self.wantFresh = false, false
	end
	self.sessionId, self.seq, self.width, self.height = c.sessionId, c.seq, c.width, c.height
	self.forwardedBytes += bytes
	setStatus(self, out, "live", nil)
	table.insert(out, m)
	return out, nil
end

-- A poll failed (HTTP error, timeout, bad body). The chain is kept (the next poll continues from it); after
-- `errorThreshold` consecutive failures the status becomes "error". Returns the messages to broadcast.
function RelayCore.fail(self: Relay, reason: string): { Message }
	self.consecutiveErrors += 1
	local out: { Message } = {}
	if self.consecutiveErrors >= self.errorThreshold then
		setStatus(self, out, "error", reason)
	end
	return out
end

-- The screen is withheld in this server (a moderator hid it): forget the chain (the next poll after resuming starts from
-- a keyframe) and report "stopped" with `detail`. Returns the messages to broadcast.
function RelayCore.suspend(self: Relay, detail: string): { Message }
	clearChain(self)
	local out: { Message } = {}
	setStatus(self, out, "stopped", detail)
	return out
end

-- Viewers need a new keyframe (late joiners, slow viewers, a long history): polls ask for one until it arrives. The
-- chain continues meanwhile (`key` would make the frame service replay its newest keyframe chain: old frames).
function RelayCore.requestFreshKeyframe(self: Relay)
	if self.seq == 0 then
		self.wantKeyframe = true
	else
		self.wantFresh = true
	end
end

return RelayCore
