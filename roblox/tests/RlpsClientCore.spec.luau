-- Standalone-Luau spec for RlpsClientCore (frame assembler): relayed part records in arrival order, chain rules,
-- desync detection and recovery, advance, dirty rectangles, reset and copyRect. Vectors come from the Python encoder.
local ClientCore = require("./RlpsClientCore")
local H = require("./spec_helpers")
local V = require("./vectors")

local T = H.counter()

local function pushAll(a: any, recs: { buffer }, name: string): boolean
	for j, rec in recs do
		local r, why = a:push(rec)
		local want = if j == #recs then "frame" else "applied"
		if r ~= want then
			T.fail(name, string.format("part %d/%d -> %s (%s), expected %s", j, #recs, r, tostring(why), want))
			return false
		end
	end
	return true
end

local function frameCrc(a: any): number
	return if a.frame then H.crc32(a.frame) else -1
end

local function rectStr(x: number?, y: number?, w: number?, h: number?): string
	return string.format("%s,%s %sx%s", tostring(x), tostring(y), tostring(w), tostring(h))
end

-- 1. Every vector sequence, part by part: "applied" … "frame", CRC = reference decoder, chain position, dirty rect.
for _, s in V.sequences do
	local a = ClientCore.new(H.decompress)
	for i, st in s.steps do
		local name = s.name .. "#" .. i
		if pushAll(a, H.records(st.data), name) then
			T.eq(frameCrc(a), st.crc, name .. " crc")
			T.check(a.width == st.fields.width and a.height == st.fields.height, name .. " size",
				a.width .. "x" .. a.height)
			T.check(a.sessionId == st.fields.sessionId and a.seq == st.fields.seq, name .. " chain",
				a.sessionId .. "/" .. a.seq)
			local x, y, w, h = a:takeDirty()
			local d = st.dirty
			T.check(x == d[1] and y == d[2] and w == d[3] and h == d[4], name .. " dirty",
				rectStr(x, y, w, h) .. " expected " .. rectStr(d[1], d[2], d[3], d[4]))
			T.check(a:takeDirty() == nil, name .. " dirty popped")
		end
	end
	T.eq(a.framesCompleted, #s.steps, s.name .. " framesCompleted")
	T.eq(a.desyncs, 0, s.name .. " no desync")
end

local TEXT = H.sequence("320x180-rgb565-t16-zstd-text") -- key (4 parts), delta, delta
local GRAD = H.sequence("160x90-rgb888-t16-zstd-gradient") -- key (6 parts), delta (1 part), delta (6 parts)
assert(#H.records(TEXT.steps[1].data) >= 3 and #H.records(GRAD.steps[3].data) >= 3, "multi-part vectors expected")

local function fresh(): any
	return ClientCore.new(H.decompress)
end

-- 2. A delta before any keyframe is ignored (nothing to apply it to).
do
	local a = fresh()
	local r, why = a:push(H.records(TEXT.steps[2].data)[1])
	T.check(r == "ignored" and why == "waiting for a keyframe", "delta-first", tostring(r) .. " " .. tostring(why))
	T.check(a.frame == nil and a.desyncs == 0, "delta-first no state")
end

-- 3. A later part without its first part breaks the chain; deltas are ignored until the next keyframe resyncs.
for _, s in { TEXT, GRAD } do
	local a = fresh()
	local key = H.records(s.steps[1].data)
	local r, why = a:push(key[2])
	T.check(r == "desync" and why == "part without its first part", s.name .. " orphan part", tostring(why))
	r, why = a:push(H.records(s.steps[2].data)[1])
	T.check(r == "ignored" and why == "waiting for a keyframe", s.name .. " delta while desynced", tostring(why))
	if pushAll(a, key, s.name .. " resync keyframe") then
		T.eq(frameCrc(a), s.steps[1].crc, s.name .. " resync crc")
		T.check(not a.desynced, s.name .. " resynced")
	end
	if pushAll(a, H.records(s.steps[2].data), s.name .. " delta after resync") then
		T.eq(frameCrc(a), s.steps[2].crc, s.name .. " delta after resync crc")
	end
	T.eq(a.desyncs, 1, s.name .. " one desync counted")
end

-- 4. A missing middle part: desync, the rest of that frame is ignored, the next keyframe recovers.
do
	local a = fresh()
	local key = H.records(GRAD.steps[1].data)
	T.eq(a:push(key[1]), "applied", "gap part 1")
	local r, why = a:push(key[3])
	T.check(r == "desync" and why == "part out of order", "gap detected", tostring(why))
	r, why = a:push(key[4])
	T.check(r == "ignored", "gap rest ignored", tostring(r) .. " " .. tostring(why))
	T.eq(a.seq, 0, "gap no completed frame")
	if pushAll(a, key, "gap recovery") then
		T.eq(frameCrc(a), GRAD.steps[1].crc, "gap recovery crc")
	end
	T.eq(a.desyncs, 1, "gap desync count")
end

-- 5. A skipped delta (baseSeq does not match) breaks the chain; advance is ignored while desynced.
do
	local a = fresh()
	pushAll(a, H.records(TEXT.steps[1].data), "skip key")
	local r, why = a:push(H.records(TEXT.steps[3].data)[1])
	T.check(r == "desync" and why == "delta does not follow the current frame", "skipped delta", tostring(why))
	T.eq(a:advance(a.sessionId, a.seq, a.seq + 1), "ignored", "advance while desynced")
	T.eq(frameCrc(a), TEXT.steps[1].crc, "skipped delta leaves the frame")
end

-- 6. Re-delivered (stale) deltas are ignored without breaking the chain.
do
	local a = fresh()
	pushAll(a, H.records(TEXT.steps[1].data), "stale key")
	local d = H.records(TEXT.steps[2].data)
	pushAll(a, d, "stale delta first")
	local r, why = a:push(d[1])
	T.check(r == "ignored" and why == "stale delta", "stale delta ignored", tostring(r) .. " " .. tostring(why))
	T.check(not a.desynced and a.desyncs == 0, "stale delta no desync")
	T.eq(frameCrc(a), TEXT.steps[2].crc, "stale delta frame intact")
	if pushAll(a, H.records(TEXT.steps[3].data), "stale then next") then
		T.eq(frameCrc(a), TEXT.steps[3].crc, "stale then next crc")
	end
end

-- 7. A new delta while a frame is incomplete means parts were lost: desync.
do
	local a = fresh()
	local key = H.records(GRAD.steps[1].data)
	for j = 1, #key - 1 do
		a:push(key[j])
	end
	local r, why = a:push(H.records(GRAD.steps[2].data)[1])
	T.check(r == "desync" and why == "delta does not follow the current frame", "incomplete then delta", tostring(why))
end

-- 8. A keyframe part 0 restarts a pending frame (resync point).
do
	local a = fresh()
	local key = H.records(GRAD.steps[1].data)
	a:push(key[1])
	a:push(key[2])
	if pushAll(a, key, "keyframe restart") then
		T.eq(frameCrc(a), GRAD.steps[1].crc, "keyframe restart crc")
		T.eq(a.desyncs, 0, "keyframe restart no desync")
	end
end

-- Rewrite seq/baseSeq in every part header of a record list (headers are not checksummed).
local function reseq(recs: { buffer }, seq: number, baseSeq: number): { buffer }
	local out = {}
	for _, rec in recs do
		local b = buffer.create(buffer.len(rec))
		buffer.copy(b, 0, rec)
		buffer.writeu32(b, 20, seq)
		buffer.writeu32(b, 24, baseSeq)
		table.insert(out, b)
	end
	return out
end

-- 9. advance: identical frame -> chain moves forward; following deltas must use the new base.
do
	local a = fresh()
	pushAll(a, H.records(TEXT.steps[1].data), "adv key")
	local sid = a.sessionId
	T.eq(a:advance(sid, 1, 5), "applied", "advance 1->5")
	T.eq(a.seq, 5, "advance seq")
	T.check(a:takeDirty() ~= nil and a:takeDirty() == nil, "advance adds no dirty rect")
	T.eq(a:advance(sid, 3, 4), "ignored", "advance behind the chain")
	local r, why = a:push(H.records(TEXT.steps[2].data)[1]) -- baseSeq 1: before the advance
	T.check(r == "ignored" and why == "stale delta", "old-base delta after advance", tostring(r) .. " " .. tostring(why))
	if pushAll(a, reseq(H.records(TEXT.steps[2].data), 6, 5), "delta on advanced base") then
		T.eq(frameCrc(a), TEXT.steps[2].crc, "delta on advanced base crc")
		T.eq(a.seq, 6, "delta on advanced base seq")
	end
	T.eq(a:advance(sid, 9, 12), "desync", "advance from an unknown seq")
	local b = fresh()
	pushAll(b, H.records(TEXT.steps[1].data), "adv2 key")
	T.eq(b:advance(b.sessionId + 1, 1, 2), "desync", "advance of another session")
	T.eq(fresh():advance(1, 0, 1), "ignored", "advance without a frame")
end

-- 10. Dirty rectangles accumulate across frames until taken.
do
	local a = fresh()
	pushAll(a, H.records(GRAD.steps[1].data), "acc key")
	a:takeDirty()
	pushAll(a, H.records(GRAD.steps[2].data), "acc d1")
	pushAll(a, H.records(GRAD.steps[3].data), "acc d2")
	local d1, d2 = GRAD.steps[2].dirty, GRAD.steps[3].dirty
	local ux0, uy0 = math.min(d1[1], d2[1]), math.min(d1[2], d2[2])
	local ux1, uy1 = math.max(d1[1] + d1[3], d2[1] + d2[3]), math.max(d1[2] + d1[4], d2[2] + d2[4])
	local x, y, w, h = a:takeDirty()
	T.check(x == ux0 and y == uy0 and w == ux1 - ux0 and h == uy1 - uy0, "dirty union",
		rectStr(x, y, w, h) .. " expected " .. rectStr(ux0, uy0, ux1 - ux0, uy1 - uy0))
end

-- 11. reset drops every pixel; deltas are then ignored until a keyframe.
do
	local a = fresh()
	pushAll(a, H.records(TEXT.steps[1].data), "reset key")
	a:reset()
	T.check(a.frame == nil and a.width == 0 and a.seq == 0 and a.sessionId == 0, "reset state")
	T.check(a:takeDirty() == nil, "reset clears dirty")
	local r, why = a:push(H.records(TEXT.steps[2].data)[1])
	T.check(r == "ignored" and why == "waiting for a keyframe", "delta after reset", tostring(why))
	if pushAll(a, H.records(TEXT.steps[1].data), "key after reset") then
		T.eq(frameCrc(a), TEXT.steps[1].crc, "key after reset crc")
	end
end

-- 12. Malformed records: truncated header, failing apply (bad tile list), corrupt compressed payload.
do
	local a = fresh()
	local rec = H.records(TEXT.steps[1].data)[1]
	local short = buffer.create(10)
	buffer.copy(short, 0, rec, 0, 10)
	local r, why = a:push(short)
	T.check(r == "desync" and why == "bad record: truncated part header", "truncated record", tostring(why))

	local dup
	for _, c in V.payload do
		if c.name == "dup-index" then
			dup = c
		end
	end
	local b = fresh()
	local recs = H.records(dup.data)
	r, why = b:push(recs[1])
	T.check(r == "desync" and why == "apply failed: tile indices must be strictly increasing and in range",
		"apply failure", tostring(why))

	local c = fresh()
	local bad = buffer.create(buffer.len(rec))
	buffer.copy(bad, 0, rec)
	local last = buffer.len(bad) - 1
	buffer.writeu8(bad, last, bit32.bxor(buffer.readu8(bad, last), 0xFF))
	r, why = c:push(bad)
	T.check(r == "desync" and string.find(tostring(why), "apply failed: zstd decode failed", 1, true) == 1,
		"corrupt payload", tostring(why))
	T.eq(c.desyncs, 1, "corrupt payload desync count")
end

-- 13. copyRect: sub-rectangles are exact copies; the full rectangle is the frame buffer itself; bounds enforced.
do
	local a = fresh()
	pushAll(a, H.records(GRAD.steps[1].data), "copy key")
	local frame = a.frame :: buffer
	local x, y, w, h = 3, 5, 7, 2
	local sub = a:copyRect(x, y, w, h)
	local same = buffer.len(sub) == w * h * 4
	for row = 0, h - 1 do
		for col = 0, w - 1 do
			if buffer.readu32(sub, (row * w + col) * 4) ~= buffer.readu32(frame, ((y + row) * a.width + x + col) * 4) then
				same = false
			end
		end
	end
	T.check(same, "copyRect sub-rectangle")
	T.check(a:copyRect(0, 0, a.width, a.height) == frame, "copyRect full frame is the buffer")
	T.check(not pcall(a.copyRect, a, a.width - 1, 0, 2, 1), "copyRect rejects out-of-frame")
	T.check(not pcall(a.copyRect, fresh(), 0, 0, 1, 1), "copyRect without a frame")
end

-- 14. Without a decompressor zstd parts fail cleanly (desync), uncompressed sequences still work.
do
	local a = ClientCore.new(nil)
	local r, why = a:push(H.records(TEXT.steps[1].data)[1])
	T.check(r == "desync" and why == "apply failed: no zstd decompressor available", "no decompressor", tostring(why))
	local plain = H.sequence("17x9-rgb888-t8-none")
	local b = ClientCore.new(nil)
	if pushAll(b, H.records(plain.steps[1].data), "plain key") then
		T.eq(frameCrc(b), plain.steps[1].crc, "plain key crc")
	end
end

T.summary()
