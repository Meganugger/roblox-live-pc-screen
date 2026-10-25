--!strict
-- RLPS server relay core (T-0012). Turns frame-service containers into the ordered message stream that the server
-- script fans out to every client, tracks the poll cursor (after/session/key) and keeps the late-joiner history
-- (last keyframe + later deltas/advances). Pure Luau (no Roblox APIs) so the standalone harness can test it;
-- RlpsServer.server.luau owns HttpService, the RemoteEvent and the single poll loop of the experience server.
--
-- Invariant: the forwarded stream is always a valid chain for RlpsClientCore — a keyframe, then deltas whose baseSeq
-- is the previous seq, or advances; anything that does not extend the chain is dropped and a keyframe is requested.

local Protocol = require(script.Parent.RlpsProtocol)
local Decoder = require(script.Parent.RlpsDecoder)

local RelayCore = {}
RelayCore.__index = RelayCore

export type Status = "connecting" | "live" | "stopped" | "error"

-- "records": part records of one container (forward in order); "advance": frame toSeq looks like fromSeq;
-- "status": sharing/connection state changed.
export type Message = {
	kind: "records" | "advance" | "status",
	records: { buffer }?,
	bytes: number?,
	sessionId: number?,
	fromSeq: number?,
	toSeq: number?,
	status: Status?,
	detail: string?,
}

export type Config = {
	historyLimitBytes: number?, -- ask for a fresh keyframe when the late-joiner history grows beyond this
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
		wantKeyframe: boolean,
		history: { Message },
		historyBytes: number,
		historyLimit: number,
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
		history = {} :: { Message },
		historyBytes = 0,
		historyLimit = cfg.historyLimitBytes or 1536 * 1024,
		errorThreshold = cfg.errorThreshold or 3,
		consecutiveErrors = 0,
		containers = 0,
		forwardedBytes = 0,
		dropped = 0,
		lastDrop = nil :: string?,
	}, RelayCore)
end

-- Query parameters for the next GET /v1/frames poll.
function RelayCore.pollParams(self: Relay): (number, number, boolean)
	return self.seq, self.sessionId, self.wantKeyframe or self.seq == 0
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
	table.clear(self.history)
	self.historyBytes = 0
	self.wantKeyframe = true
end

local function drop(self: Relay, reason: string, needKeyframe: boolean)
	self.dropped += 1
	self.lastDrop = reason
	if needKeyframe then
		self.wantKeyframe = true
	end
end

-- Feed one decoded frame-service container. Returns the messages to broadcast (possibly none), or nil + reason when
-- the container is invalid (nothing is forwarded then).
function RelayCore.ingest(self: Relay, data: buffer): ({ Message }?, string?)
	local c, err = Decoder.parseContainer(data)
	if c == nil then
		self:fail("invalid container: " .. tostring(err))
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
				table.insert(self.history, m)
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
	local m: Message = { kind = "records", records = records, bytes = bytes, sessionId = c.sessionId, toSeq = c.seq }
	if c.keyframe then
		table.clear(self.history)
		self.historyBytes = 0
		self.wantKeyframe = false
	end
	table.insert(self.history, m)
	self.historyBytes += bytes
	if self.historyBytes > self.historyLimit then
		self.wantKeyframe = true -- next poll asks for a keyframe, which also resets the history
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

-- A client lost the chain (desync): ask the frame service for a keyframe on the next poll.
function RelayCore.requestKeyframe(self: Relay)
	self.wantKeyframe = true
end

-- Everything a late joiner needs, in order: current status, then the last keyframe and every later delta/advance.
function RelayCore.syncMessages(self: Relay): { Message }
	local first: Message = { kind = "status", status = self.status, detail = self.detail }
	local out: { Message } = { first }
	for _, m in self.history do
		table.insert(out, m)
	end
	return out
end

return RelayCore
