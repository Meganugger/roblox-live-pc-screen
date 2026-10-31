--!strict
-- RLPS client frame assembler (T-0012). Applies relayed part records, in arrival order, to an RGBA8 frame buffer,
-- follows the (sessionId, seq) chain, accumulates the dirty rectangle and detects desync. Pure Luau (no Roblox APIs)
-- so the standalone harness can test it; RlpsClient.client.luau owns the EditableImage and the networking.
--
-- Chain rules (the relay forwards whole containers, part 0 first, never interleaved — reliable RemoteEvents are ordered):
--   * a keyframe part 0 always starts a new frame (resync point); its later parts must follow in order;
--   * a delta part 0 applies only on top of the last complete frame: same session and baseSeq == seq;
--   * advance(session, fromSeq, toSeq) moves seq forward when the frame service found frame toSeq identical to fromSeq;
--   * anything else breaks the chain: the assembler reports "desync" and ignores deltas until the next keyframe.

local Decoder = require(script.Parent.RlpsDecoder)

local ClientCore = {}
ClientCore.__index = ClientCore

export type Result = "applied" | "frame" | "ignored" | "desync"

export type Assembler = typeof(setmetatable(
	{} :: {
		decompress: Decoder.Decompress?,
		width: number,
		height: number,
		frame: buffer?,
		sessionId: number, -- chain position = last complete frame (0 = none)
		seq: number,
		pendingSession: number, -- frame being assembled (pendingSeq 0 = none)
		pendingSeq: number,
		nextPart: number,
		partCount: number,
		desynced: boolean,
		dirty: Decoder.Bounds,
		lastError: string?,
		lastDetail: string?, -- numbers behind the last desync (diagnostics)
		framesCompleted: number,
		partsApplied: number,
		desyncs: number,
	},
	ClientCore
))

function ClientCore.new(decompress: Decoder.Decompress?): Assembler
	local self = setmetatable({
		decompress = decompress,
		width = 0,
		height = 0,
		frame = nil :: buffer?,
		sessionId = 0,
		seq = 0,
		pendingSession = 0,
		pendingSeq = 0,
		nextPart = 0,
		partCount = 0,
		desynced = false,
		dirty = Decoder.emptyBounds(),
		lastError = nil :: string?,
		lastDetail = nil :: string?,
		framesCompleted = 0,
		partsApplied = 0,
		desyncs = 0,
	}, ClientCore)
	return self
end

-- Drop every pixel (sharing stopped / session ended): nothing of the shared screen stays in client memory.
function ClientCore.reset(self: Assembler)
	self.frame = nil
	self.width, self.height = 0, 0
	self.sessionId, self.seq = 0, 0
	self.pendingSession, self.pendingSeq, self.nextPart, self.partCount = 0, 0, 0, 0
	self.desynced = false
	self.dirty = Decoder.emptyBounds()
end

local function breakChain(self: Assembler, reason: string): Result
	self.pendingSeq, self.nextPart, self.partCount = 0, 0, 0
	if not self.desynced then
		self.desyncs += 1
	end
	self.desynced = true
	self.lastError = reason
	return "desync"
end

-- Feed one part record (header + payload buffer). Returns what happened plus a reason for "ignored"/"desync".
function ClientCore.push(self: Assembler, record: buffer): (Result, string?)
	local h, err = Decoder.parseRecord(record)
	if h == nil then
		return breakChain(self, "bad record: " .. tostring(err)), self.lastError
	end
	if h.partIndex == 0 then
		if h.keyframe then
			if self.frame == nil or self.width ~= h.width or self.height ~= h.height then
				self.frame = buffer.create(h.width * h.height * 4)
				self.width, self.height = h.width, h.height
				self.dirty = Decoder.emptyBounds()
			end
			self.desynced = false
		else
			if self.desynced or self.frame == nil then
				return "ignored", "waiting for a keyframe"
			end
			if h.sessionId == self.sessionId and h.seq <= self.seq and self.pendingSeq == 0 then
				return "ignored", "stale delta"
			end
			if h.sessionId ~= self.sessionId or h.baseSeq ~= self.seq or self.pendingSeq ~= 0 then
				self.lastDetail = string.format("delta %d<-%d on frame %d (assembling %d)", h.seq, h.baseSeq, self.seq,
					self.pendingSeq)
				return breakChain(self, "delta does not follow the current frame"), self.lastError
			end
		end
		self.pendingSession, self.pendingSeq, self.nextPart, self.partCount = h.sessionId, h.seq, 0, h.partCount
	else
		if self.pendingSeq == 0 then
			if self.desynced or (h.sessionId == self.sessionId and h.seq <= self.seq) then
				return "ignored", "part of a frame that is not being assembled"
			end
			return breakChain(self, "part without its first part"), self.lastError
		end
		if h.sessionId ~= self.pendingSession or h.seq ~= self.pendingSeq or h.partIndex ~= self.nextPart
			or h.partCount ~= self.partCount then
			return breakChain(self, "part out of order"), self.lastError
		end
	end
	local frame = self.frame :: buffer
	local n, aerr = Decoder.applyRecord(frame, self.width, self.height, record, self.decompress, self.dirty)
	if n == nil then
		return breakChain(self, "apply failed: " .. tostring(aerr)), self.lastError
	end
	self.partsApplied += 1
	self.nextPart += 1
	if self.nextPart < self.partCount then
		return "applied", nil
	end
	self.sessionId, self.seq = self.pendingSession, self.pendingSeq
	self.pendingSeq, self.nextPart, self.partCount = 0, 0, 0
	self.framesCompleted += 1
	return "frame", nil
end

-- The frame service reported that frame `toSeq` looks exactly like `fromSeq`: move the chain forward.
function ClientCore.advance(self: Assembler, sessionId: number, fromSeq: number, toSeq: number): Result
	if self.desynced or self.frame == nil then
		return "ignored"
	end
	if self.pendingSeq == 0 and self.sessionId == sessionId then
		if self.seq == fromSeq then
			self.seq = toSeq
			return "applied"
		elseif self.seq >= toSeq then
			return "ignored"
		end
	end
	return breakChain(self, "advance does not follow the current frame")
end

-- Pop the accumulated dirty rectangle (x, y, w, h) or nil when nothing changed since the last call.
function ClientCore.takeDirty(self: Assembler): (number?, number?, number?, number?)
	local b = self.dirty
	if b.x1 < 0 then
		return nil, nil, nil, nil
	end
	self.dirty = Decoder.emptyBounds()
	return b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0
end

-- RGBA8 copy of a rectangle of the frame (the whole frame buffer itself when the rectangle covers it).
function ClientCore.copyRect(self: Assembler, x: number, y: number, w: number, h: number): buffer
	local frame = assert(self.frame, "no frame")
	assert(x >= 0 and y >= 0 and w >= 1 and h >= 1 and x + w <= self.width and y + h <= self.height, "rect out of frame")
	if x == 0 and y == 0 and w == self.width and h == self.height then
		return frame
	end
	local out = buffer.create(w * h * 4)
	local stride, rowBytes = self.width * 4, w * 4
	for row = 0, h - 1 do
		buffer.copy(out, row * rowBytes, frame, (y + row) * stride + x * 4, rowBytes)
	end
	return out
end

return ClientCore
