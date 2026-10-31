-- Standalone-Luau spec for RlpsRelayCore (server relay): poll cursor, chain-validated forwarding, stale/duplicate
-- drops, advances, status transitions, failure threshold, fresh-keyframe requests, and relay -> RlpsClientCore end to
-- end. (Late joiners replay the played history: RlpsFanout.spec.luau.)
local Protocol = require("./RlpsProtocol")
local RelayCore = require("./RlpsRelayCore")
local ClientCore = require("./RlpsClientCore")
local H = require("./spec_helpers")
local V = require("./vectors")

local T = H.counter()

-- Part-less container (STOPPED, or LIVE + UNCHANGED), same layout as codec.status_container.
local function status(state: number, sessionId: number, seq: number, w: number?, h: number?): buffer
	local b = buffer.create(Protocol.CONTAINER_HEADER_SIZE)
	buffer.writestring(b, 0, Protocol.MAGIC)
	buffer.writeu8(b, 4, Protocol.VERSION)
	buffer.writeu8(b, 5, state)
	buffer.writeu8(b, 6, if state == Protocol.STATE_LIVE then Protocol.CFLAG_UNCHANGED else 0)
	buffer.writeu32(b, 8, sessionId)
	buffer.writeu32(b, 12, seq)
	buffer.writeu32(b, 16, seq)
	buffer.writeu16(b, 20, w or 0)
	buffer.writeu16(b, 22, h or 0)
	buffer.writeu8(b, 24, if state == Protocol.STATE_LIVE then Protocol.FMT_RGB565 else 0)
	buffer.writeu8(b, 25, 16)
	return b
end

local function kinds(msgs: { any }?): string
	if msgs == nil then
		return "nil"
	end
	local t = {}
	for _, m in msgs do
		table.insert(t, if m.kind == "status" then "status:" .. tostring(m.status) else m.kind)
	end
	return table.concat(t, ",")
end

-- Deliver relay messages to a client assembler the way RlpsClient does; returns false on any unexpected result.
local function deliver(client: any, msgs: { any }, name: string): boolean
	for _, m in msgs do
		if m.kind == "records" then
			for j, rec in m.records do
				local r, why = client:push(rec)
				local want = if j == #m.records then "frame" else "applied"
				if r ~= want then
					T.fail(name, string.format("record %d/%d -> %s (%s)", j, #m.records, r, tostring(why)))
					return false
				end
			end
		elseif m.kind == "advance" then
			local r = client:advance(m.sessionId, m.fromSeq, m.toSeq)
			if r ~= "applied" then
				T.fail(name, "advance -> " .. tostring(r))
				return false
			end
		elseif m.kind == "status" and m.status == "stopped" then
			client:reset()
		end
	end
	return true
end

local function crc(client: any): number
	return if client.frame then H.crc32(client.frame) else -1
end

local TEXT = H.sequence("320x180-rgb565-t16-zstd-text") -- key, delta, delta
local SID = TEXT.steps[1].fields.sessionId

-- 1. Fresh relay asks for a keyframe; STOPPED reports the stopped state once.
do
	local r = RelayCore.new()
	local after, session, key, idle = r:pollParams()
	T.check(after == 0 and session == 0 and key == true, "fresh poll params", after .. "/" .. session)
	T.check(idle == false, "fresh relay is not idle (first poll must learn the state at once)")
	T.eq(r.status, "connecting", "fresh status")
	local msgs = r:ingest(status(Protocol.STATE_STOPPED, 0, 0))
	T.eq(kinds(msgs), "status:stopped", "stopped message")
	local _, _, _, idle2 = r:pollParams()
	T.check(idle2 == true, "relay reporting stopped polls with idle=1")
	T.eq(kinds(r:ingest(status(Protocol.STATE_STOPPED, 0, 0))), "", "stopped again is silent")
end

-- 2. Keyframe, delta, delta: forwarded in order; cursor follows; client reproduces the reference frames.
do
	local r = RelayCore.new()
	local client = ClientCore.new(H.decompress)
	for i, st in TEXT.steps do
		local msgs, err = r:ingest(buffer.fromstring(st.data))
		T.check(msgs ~= nil, "seq step " .. i .. " ingest", tostring(err))
		local want = if i == 1 then "status:live,records" else "records"
		T.eq(kinds(msgs), want, "seq step " .. i .. " messages")
		if msgs and deliver(client, msgs, "seq step " .. i) then
			T.eq(crc(client), st.crc, "seq step " .. i .. " client crc")
		end
		local after, session, key = r:pollParams()
		T.check(after == st.fields.seq and session == SID and key == false, "seq step " .. i .. " cursor",
			after .. "/" .. session .. "/" .. tostring(key))
	end

	-- 3. Re-delivered delta: dropped as stale, nothing forwarded, no keyframe needed.
	local msgs = r:ingest(buffer.fromstring(TEXT.steps[2].data))
	T.eq(kinds(msgs), "", "stale delta forwards nothing")
	T.check(r.lastDrop == "stale delta" and not r.wantKeyframe, "stale delta dropped", tostring(r.lastDrop))

	-- 4. Duplicate keyframe of an older frame: dropped (keyframes only win when newer or wanted).
	msgs = r:ingest(buffer.fromstring(TEXT.steps[1].data))
	T.eq(kinds(msgs), "", "old keyframe forwards nothing")
	T.eq(r.lastDrop, "duplicate keyframe", "old keyframe dropped")

	-- 5. UNCHANGED with a newer seq: advance; same seq: nothing.
	local seq = r.seq
	msgs = r:ingest(status(Protocol.STATE_LIVE, SID, seq + 4, 320, 180))
	T.eq(kinds(msgs), "advance", "unchanged newer -> advance")
	if msgs and msgs[1] then
		T.check(msgs[1].fromSeq == seq and msgs[1].toSeq == seq + 4 and msgs[1].sessionId == SID, "advance fields")
	end
	if msgs then
		deliver(client, msgs, "advance delivery")
	end
	T.eq(client.seq, seq + 4, "client advanced")
	T.eq(kinds(r:ingest(status(Protocol.STATE_LIVE, SID, seq + 4, 320, 180))), "", "unchanged same seq is silent")

	-- 6. Fresh keyframe for viewers: the chain continues (fresh=1, never key=1), a newer keyframe answers it.
	r:requestFreshKeyframe()
	local a6, s6, k6, _, f6 = r:pollParams()
	T.check(a6 == seq + 4 and s6 == SID and k6 == false and f6 == true, "fresh request keeps the cursor",
		a6 .. "/" .. s6 .. "/" .. tostring(k6) .. "/" .. tostring(f6))

	-- 7. STOPPED: clears the chain, clients reset, next poll asks for a keyframe.
	msgs = r:ingest(status(Protocol.STATE_STOPPED, 0, 0))
	T.eq(kinds(msgs), "status:stopped", "stop message")
	if msgs then
		deliver(client, msgs, "stop delivery")
	end
	T.check(client.frame == nil, "client dropped pixels on stop")
	local after, session, key = r:pollParams()
	local _, _, _, _, fresh = r:pollParams()
	T.check(after == 0 and session == 0 and key and not fresh, "stop clears chain (and the fresh request)")
	r:requestFreshKeyframe()
	local _, _, key7, _, fresh7 = r:pollParams()
	T.check(key7 and not fresh7, "fresh request without a chain is a keyframe request")
end

-- 8. A delta that skips a frame never reaches clients; the relay asks for a keyframe instead.
do
	local r = RelayCore.new()
	r:ingest(buffer.fromstring(TEXT.steps[1].data))
	local msgs = r:ingest(buffer.fromstring(TEXT.steps[3].data))
	T.eq(kinds(msgs), "", "skipping delta forwards nothing")
	local _, _, key = r:pollParams()
	T.check(key and r.lastDrop == "delta does not extend the forwarded chain", "skipping delta wants keyframe")
	msgs = r:ingest(buffer.fromstring(TEXT.steps[1].data))
	T.eq(kinds(msgs), "records", "wanted keyframe forwarded even if not newer")
	local _, _, key2 = r:pollParams()
	T.eq(key2, false, "keyframe satisfies the request")
end

-- 9. Live session without frames yet, then a session change mid-stream.
do
	local r = RelayCore.new()
	local msgs = r:ingest(status(Protocol.STATE_LIVE, SID, 0))
	T.eq(kinds(msgs), "status:live", "live without frames")
	T.eq(r.detail, "waiting for the first frame", "waiting detail")
	r:ingest(buffer.fromstring(TEXT.steps[1].data))
	T.eq(r.detail, nil, "detail cleared by the first frame")
	msgs = r:ingest(status(Protocol.STATE_LIVE, SID + 1, 3, 320, 180))
	local _, session, key = r:pollParams()
	T.check(key and session == 0 and r.seq == 0, "new session clears the chain and wants a keyframe")
	T.eq(kinds(msgs), "", "new session unchanged forwards nothing")
	-- the old session's delta must not be forwarded after the switch
	T.eq(kinds(r:ingest(buffer.fromstring(TEXT.steps[2].data))), "", "old-session delta dropped")
end

-- 10. Failures: invalid containers and poll errors keep the chain; the error status appears at the threshold.
do
	local r = RelayCore.new({ errorThreshold = 3 })
	r:ingest(buffer.fromstring(TEXT.steps[1].data))
	local seq = r.seq
	local msgs, err = r:ingest(buffer.fromstring("garbage"))
	T.check(msgs == nil and err == "truncated container header", "invalid container rejected", tostring(err))
	T.eq(r.consecutiveErrors, 0, "ingest does not count the failure itself")
	T.eq(kinds(r:fail("invalid container: " .. tostring(err))), "", "first failure silent (reported by the server)")
	T.eq(kinds(r:fail("HTTP 502")), "", "second failure silent")
	local m3 = r:fail("HTTP 502")
	T.eq(kinds(m3), "status:error", "third failure -> error status")
	T.eq(r.detail, "HTTP 502", "error detail")
	T.eq(kinds(r:fail("HTTP 502")), "", "error not repeated")
	T.eq(r.seq, seq, "chain kept across failures")
	msgs = r:ingest(buffer.fromstring(TEXT.steps[2].data))
	T.eq(kinds(msgs), "status:live,records", "recovery forwards the next delta")
	T.eq(r.consecutiveErrors, 0, "errors reset")
end

-- 11. A keyframe whose parts disagree with the container header is rejected; records carry the keyframe flag.
do
	local r = RelayCore.new()
	local copy = buffer.fromstring(TEXT.steps[1].data)
	buffer.writeu32(copy, 12, 9) -- container seq 9 (still a valid keyframe; parts carry their own seq)
	local msgs, err = r:ingest(copy)
	T.check(msgs == nil and err == "part 0 header inconsistent with container", "inconsistent keyframe rejected",
		tostring(err))
	local k = r:ingest(buffer.fromstring(TEXT.steps[1].data)) :: { any }
	local d = r:ingest(buffer.fromstring(TEXT.steps[2].data)) :: { any }
	T.check(k[#k].keyframe == true and d[#d].keyframe == false, "records messages carry the keyframe flag")
	r:requestFreshKeyframe()
	local _, _, _, _, fresh = r:pollParams()
	T.eq(fresh, true, "fresh request pending")
	r:ingest(buffer.fromstring(TEXT.steps[3].data))
	local _, _, _, _, fresh2 = r:pollParams()
	T.eq(fresh2, true, "a delta does not answer a fresh request")
	local newer = r:ingest(buffer.fromstring(TEXT.steps[1].data)) -- not newer, not wanted: dropped
	T.eq(kinds(newer), "", "old keyframe does not answer it either")
end

-- 12. Every vector sequence through relay + client.
for _, s in V.sequences do
	local r = RelayCore.new()
	local client = ClientCore.new(H.decompress)
	for i, st in s.steps do
		local name = s.name .. "#" .. i
		local msgs = r:ingest(buffer.fromstring(st.data))
		if msgs and deliver(client, msgs, name) then
			T.eq(crc(client), st.crc, name .. " relayed crc")
		end
	end
	T.eq(r.dropped, 0, s.name .. " nothing dropped")
end

T.summary()
