--!strict
--!native
--!optimize 2
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

local CELL = Decoder.DIRTY_CELL
local readu8 = buffer.readu8

local ClientCore = {}
ClientCore.__index = ClientCore

export type Result = "applied" | "frame" | "ignored" | "desync"

export type Rect = { x: number, y: number, w: number, h: number }

export type Assembler = typeof(setmetatable(
	{} :: {
		decompress: Decoder.Decompress?,
		width: number,
		height: number,
		frame: buffer?,
		ref: buffer?, -- snapshot of the frame before a PFLAG_REF frame (COPY tiles read from it)
		sessionId: number, -- chain position = last complete frame (0 = none)
		seq: number,
		pendingSession: number, -- frame being assembled (pendingSeq 0 = none)
		pendingSeq: number,
		nextPart: number,
		partCount: number,
		desynced: boolean,
		dirty: Decoder.Bounds,
		scratch: { [number]: buffer }, -- reusable copyRect buffers by byte length (written out synchronously)
		scratchCount: number,
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
		ref = nil :: buffer?,
		sessionId = 0,
		seq = 0,
		pendingSession = 0,
		pendingSeq = 0,
		nextPart = 0,
		partCount = 0,
		desynced = false,
		dirty = Decoder.emptyBounds(),
		scratch = {} :: { [number]: buffer },
		scratchCount = 0,
		lastError = nil :: string?,
		lastDetail = nil :: string?,
		framesCompleted = 0,
		partsApplied = 0,
		desyncs = 0,
	}, ClientCore)
	return self
end

-- Dirty tracking for a w x h frame: bounding box plus one byte per CELL x CELL cell.
local function newDirty(w: number, h: number): Decoder.Bounds
	local b = Decoder.emptyBounds()
	if w > 0 and h > 0 then
		local cx = (w + CELL - 1) // CELL
		b.cells = buffer.create(cx * ((h + CELL - 1) // CELL))
		b.cellsX = cx
	end
	return b
end

local function clearDirty(b: Decoder.Bounds)
	b.x0, b.y0, b.x1, b.y1 = math.huge, math.huge, -1, -1
	if b.cells then
		buffer.fill(b.cells :: buffer, 0, 0)
	end
end

-- Drop every pixel (sharing stopped / session ended): nothing of the shared screen stays in client memory.
function ClientCore.reset(self: Assembler)
	self.frame = nil
	self.ref = nil
	table.clear(self.scratch)
	self.scratchCount = 0
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
				self.dirty = newDirty(h.width, h.height)
				table.clear(self.scratch)
				self.scratchCount = 0
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
		if h.usesRef then -- keep the picture as it was before this frame: its COPY tiles read from it
			local f = self.frame :: buffer
			local r = self.ref
			if r == nil or buffer.len(r) ~= buffer.len(f) then
				r = buffer.create(buffer.len(f))
				self.ref = r
			end
			buffer.copy(r :: buffer, 0, f)
		end
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
	local n, aerr = Decoder.applyRecord(frame, self.width, self.height, record, self.decompress, self.dirty,
		if h.usesRef then self.ref else nil)
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
	local x, y, w, h = b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0
	clearDirty(b)
	return x, y, w, h
end

-- Pop what changed since the last call as at most `maxRects` rectangles: runs of dirty cells per cell row, stacked
-- with the run above when they span the same cells. Falls back to the bounding box when that is nearly as small or
-- would need more rectangles (each WritePixelsBuffer call has a fixed cost). nil when nothing changed.
function ClientCore.takeDirtyRects(self: Assembler, maxRects: number): { Rect }?
	local b = self.dirty
	if b.x1 < 0 then
		return nil
	end
	local bx0, by0, bx1, by1 = b.x0, b.y0, b.x1, b.y1
	local box: Rect = { x = bx0, y = by0, w = bx1 - bx0, h = by1 - by0 }
	local cells, cx = b.cells, b.cellsX
	local out: { Rect } = { box }
	if cells and cx and maxRects > 1 then
		local rects: { Rect } = {}
		local open: { [number]: Rect } = {} -- runs that ended on the previous cell row, by first * 65536 + last cell
		local c0, c1 = bx0 // CELL, (bx1 - 1) // CELL
		local area, tooMany = 0, false
		for cy = by0 // CELL, (by1 - 1) // CELL do
			local nextOpen: { [number]: Rect } = {}
			local base = cy * cx
			local c = c0
			while c <= c1 do
				if readu8(cells, base + c) ~= 0 then
					local first = c
					while c < c1 and readu8(cells, base + c + 1) ~= 0 do
						c += 1
					end
					local key = first * 65536 + c
					local above = open[key]
					local r: Rect
					if above then
						above.h += CELL
						r = above
					else
						r = { x = first * CELL, y = cy * CELL, w = (c - first + 1) * CELL, h = CELL }
						table.insert(rects, r)
						if #rects > maxRects then
							tooMany = true
							break
						end
					end
					nextOpen[key] = r
				end
				c += 1
			end
			if tooMany then
				break
			end
			open = nextOpen
		end
		if not tooMany and #rects > 0 then
			for _, r in rects do
				r.w = math.min(r.w, self.width - r.x)
				r.h = math.min(r.h, self.height - r.y)
				area += r.w * r.h
			end
			if area < box.w * box.h * 0.75 then
				out = rects
			end
		end
	end
	clearDirty(b)
	return out
end

-- RGBA8 copy of a rectangle of the frame (the whole frame buffer itself when the rectangle covers it). The returned
-- buffer is reused by the next call with the same size: write it out (WritePixelsBuffer copies) before asking again.
function ClientCore.copyRect(self: Assembler, x: number, y: number, w: number, h: number): buffer
	local frame = assert(self.frame, "no frame")
	assert(x >= 0 and y >= 0 and w >= 1 and h >= 1 and x + w <= self.width and y + h <= self.height, "rect out of frame")
	if x == 0 and y == 0 and w == self.width and h == self.height then
		return frame
	end
	local len = w * h * 4
	local out = self.scratch[len]
	if out == nil then
		if self.scratchCount >= 32 then
			table.clear(self.scratch)
			self.scratchCount = 0
		end
		out = buffer.create(len)
		self.scratch[len] = out
		self.scratchCount += 1
	end
	local stride, rowBytes = self.width * 4, w * 4
	if x == 0 and w == self.width then
		buffer.copy(out, 0, frame, y * stride, len) -- full-width band: one contiguous copy
	else
		for row = 0, h - 1 do
			buffer.copy(out, row * rowBytes, frame, (y + row) * stride + x * 4, rowBytes)
		end
	end
	return out
end

return ClientCore
