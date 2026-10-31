-- Standalone-Luau spec for RlpsFanout (per-viewer delivery with flow control).
--   A. Real vectors: relay -> fan-out -> RlpsClientCore for an early viewer and a late joiner after every step.
--   B. Unit behaviour: acks (clamping, NaN), sync while a fresh start is in flight, hold + suffix catch-up, waiting for
--      a keyframe, Stop reaching held viewers, remove, history limit, lower-median stats.
--   C. Network simulation (per-viewer bandwidth + latency, 60 Hz steps): a fast viewer is never slowed down by a 10 KB/s
--      viewer, the slow viewer's backlog stays bounded, every viewer's chain stays valid, both end on the last frame.
local RelayCore = require("./RlpsRelayCore")
local Fanout = require("./RlpsFanout")
local ClientCore = require("./RlpsClientCore")
local H = require("./spec_helpers")
local V = require("./vectors")

local T = H.counter()

-- ------------------------------------------------------------------------------------------- A. real vectors

type Out = { kind: string, a: any, b: any, c: any }

local function realClient()
	return { core = ClientCore.new(H.decompress), inbox = {} :: { Out }, processed = 0, bad = 0 }
end

-- deliver everything queued for this client the way RlpsClient does; returns the processed byte count
local function drain(c: any): number
	for _, m in c.inbox do
		if m.kind == "part" then
			c.processed += buffer.len(m.a)
			local r = c.core:push(m.a)
			if r == "desync" then
				c.bad += 1
			end
		elseif m.kind == "advance" then
			if c.core:advance(m.a, m.b, m.c) == "desync" then
				c.bad += 1
			end
		elseif m.kind == "reset" or (m.kind == "status" and m.a == "stopped") then
			c.core:reset()
		end
	end
	table.clear(c.inbox)
	return c.processed
end

local function crc(c: any): number
	return if c.core.frame then H.crc32(c.core.frame) else -1
end

for _, s in V.sequences do
	local clients: { [string]: any } = {}
	local fan = Fanout.new(function(key: any, kind: string, a: any, b: any, c: any)
		table.insert(clients[key].inbox, { kind = kind, a = a, b = b, c = c })
	end)
	local r = RelayCore.new()
	clients.early = realClient()
	fan:sync("early", 0, 0)
	fan:ack("early", drain(clients.early), 0)
	local now = 0
	for i, st in s.steps do
		now += 0.1
		local name = s.name .. "#" .. i
		for _, m in r:ingest(buffer.fromstring(st.data)) :: { any } do
			fan:broadcast(m, now)
		end
		for key, c in clients do -- every viewer so far (early, earlier joiners) follows the new frame
			fan:ack(key, drain(c), now)
			T.eq(crc(c), st.crc, name .. " " .. key .. " crc")
		end
		local late = "late" .. i
		clients[late] = realClient()
		fan:sync(late, 0, now)
		fan:ack(late, drain(clients[late]), now)
		T.eq(crc(clients[late]), st.crc, name .. " late joiner crc")
	end
	for key, c in clients do
		T.eq(c.bad, 0, s.name .. " " .. key .. " never desynced")
		local v = fan:viewer(key) :: any
		T.check(v.state == "live" and v.sent == v.acked, s.name .. " " .. key .. " live and caught up", v.state)
	end
	-- Stop: every viewer drops its pixels; the played history is gone (a joiner gets only the status)
	fan:broadcast({ kind = "status", status = "stopped" } :: any, now + 1)
	for key, c in clients do
		drain(c)
		T.check(c.core.frame == nil, s.name .. " " .. key .. " dropped pixels on stop")
	end
	clients.afterStop = realClient()
	fan:sync("afterStop", 0, now + 1)
	local kinds = {}
	for _, m in clients.afterStop.inbox do
		table.insert(kinds, m.kind .. (if m.kind == "status" then ":" .. tostring(m.a) else ""))
	end
	T.eq(table.concat(kinds, ","), "reset,status:stopped", s.name .. " joiner after stop")
end

-- --------------------------------------------------------------------------------------- B. unit behaviour

-- synthetic part record: u32 seq, u32 baseSeq, u8 keyframe, padding up to `size` bytes
local function rec(seq: number, base: number, key: boolean, size: number): buffer
	local b = buffer.create(math.max(size, 12))
	buffer.writeu32(b, 0, seq)
	buffer.writeu32(b, 4, base)
	buffer.writeu8(b, 8, if key then 1 else 0)
	return b
end

local SID = 77
local function frame(seq: number, key: boolean, size: number): any
	local b = rec(seq, if key then 0 else seq - 1, key, size)
	return { kind = "records", records = { b }, bytes = buffer.len(b), keyframe = key, sessionId = SID, toSeq = seq }
end

local function recorder()
	local log: { [any]: { Out } } = {}
	local function send(key: any, kind: string, a: any, b: any, c: any)
		log[key] = log[key] or {}
		table.insert(log[key], { kind = kind, a = a, b = b, c = c })
	end
	return log, send
end

local function sentSeqs(out: { Out }?): string
	local t = {}
	for _, m in out or {} do
		if m.kind == "part" then
			table.insert(t, tostring(buffer.readu32(m.a, 0)))
		elseif m.kind ~= "status" then
			table.insert(t, m.kind)
		end
	end
	return table.concat(t, ",")
end

-- acks: clamped to what was sent, monotonic, NaN ignored; delivery-rate estimate from the flight
do
	local log, send = recorder()
	local fan = Fanout.new(send, { minWindow = 1000 })
	fan:broadcast(frame(1, true, 500), 0)
	fan:sync("a", 0, 0)
	local v = fan:viewer("a") :: any
	T.eq(v.sent, 500, "sync replays the keyframe")
	fan:ack("a", 99999, 0.5)
	T.eq(v.acked, 500, "ack clamped to bytes sent")
	fan:ack("a", 10, 0.6)
	T.eq(v.acked, 500, "acks never go back")
	fan:ack("a", 0 / 0, 0.7)
	T.eq(v.acked, 500, "NaN ack ignored")
	T.check(math.abs(v.rate - 1000) < 1e-6, "delivery rate = bytes / flight time", tostring(v.rate))
	T.eq(sentSeqs(log.a), "reset,1", "fresh start = reset, status, keyframe chain")
	fan:remove("a")
	fan:broadcast(frame(2, false, 100), 1)
	T.eq(sentSeqs(log.a), "reset,1", "removed viewer gets nothing")
	T.eq(fan:viewer("a"), nil, "removed viewer forgotten")
end

-- sync requests while the previous fresh start is still being processed are ignored (no repeated history)
do
	local log, send = recorder()
	local fan = Fanout.new(send, { minWindow = 1 })
	fan:broadcast(frame(1, true, 400), 0)
	fan:broadcast(frame(2, false, 100), 0)
	fan:sync("s", 0, 0)
	for t = 1, 6 do
		fan:sync("s", 100, t) -- client keeps asking (no picture yet) but processed only 100 of 500 bytes
	end
	T.eq(sentSeqs(log.s), "reset,1,2", "one fresh start while it is in flight")
	fan:sync("s", 500, 7) -- it processed the answer and still asks: a new fresh start
	T.eq(sentSeqs(log.s), "reset,1,2,reset,1,2", "answered again once processed")
	fan:sync("s", 1000, 7.5)
	T.eq(sentSeqs(log.s), "reset,1,2,reset,1,2", "at most one answer per syncInterval")
end

-- hold + catch-up: a full window holds the viewer; once drained it gets exactly the frames it missed (no reset)
do
	local log, send = recorder()
	local fan = Fanout.new(send, { minWindow = 250 })
	fan:broadcast(frame(1, true, 200), 0)
	fan:sync("h", 0, 0)
	fan:broadcast(frame(2, false, 40), 0.1) -- backlog 200 + 40 <= 250: sent
	fan:broadcast(frame(3, false, 40), 0.2) -- 240 + 40 > 250: held
	local v = fan:viewer("h") :: any
	T.eq(v.state, "held", "window full -> held")
	fan:broadcast({ kind = "advance", sessionId = SID, fromSeq = 3, toSeq = 5 } :: any, 0.3)
	fan:broadcast(frame(6, false, 30), 0.4)
	T.eq(sentSeqs(log.h), "reset,1,2", "nothing sent while held")
	fan:ack("h", 200, 0.5)
	T.eq(v.state, "held", "still held until everything is processed")
	fan:ack("h", 240, 0.6)
	T.eq(v.state, "live", "drained -> live")
	T.eq(sentSeqs(log.h), "reset,1,2,3,advance,6", "catch-up = exactly the missed frames, in order")
	T.eq(v.holds, 1, "one hold counted")
	fan:broadcast(frame(7, false, 30), 0.7)
	T.eq(sentSeqs(log.h), "reset,1,2,3,advance,6,7", "live again")
end

-- catching up would cost more than a keyframe: wait for one; the keyframe makes it live
do
	local log, send = recorder()
	local fan = Fanout.new(send, { minWindow = 100 })
	fan:broadcast(frame(1, true, 100), 0)
	fan:sync("w", 0, 0)
	fan:broadcast(frame(2, false, 50), 0.1) -- backlog 100 + 50 > 100: held
	for seq = 3, 10 do
		fan:broadcast(frame(seq, false, 50), seq / 10)
	end
	T.eq(fan:wantsKeyframe(), false, "no keyframe wanted yet")
	fan:ack("w", 100, 1.1) -- drained: missing 9 frames x 50 = 450 > 2 x 100 + 100
	local v = fan:viewer("w") :: any
	T.eq(v.state, "waiting", "expensive catch-up -> waiting")
	T.eq(fan:wantsKeyframe(), true, "a waiting viewer wants a keyframe")
	local st = fan:stats(3.1)
	T.check(st.lagging == 1 and math.abs(st.lag - 2) < 1e-9, "waiting counts as lagging, behind by its wait",
		st.lagging .. " " .. st.lag)
	fan:broadcast(frame(11, false, 50), 1.2)
	T.eq(sentSeqs(log.w), "reset,1", "no deltas while waiting")
	fan:broadcast(frame(12, true, 120), 1.3)
	T.eq(v.state, "live", "keyframe -> live")
	T.eq(sentSeqs(log.w), "reset,1,12", "got the keyframe")
	T.eq(fan:wantsKeyframe(), false, "nobody waits any more")
	fan:sync("w", 100, 1.4)
	T.eq(sentSeqs(log.w), "reset,1,12", "sync ignored until the keyframe is processed")
end

-- a late joiner: replay when cheap, wait for a keyframe when the history is long (video) or too many frames
do
	local log, send = recorder()
	local fan = Fanout.new(send, { minWindow = 1000, maxReplayFrames = 4 })
	fan:broadcast(frame(1, true, 400), 0)
	for seq = 2, 4 do
		fan:broadcast(frame(seq, false, 20), seq)
	end
	fan:sync("cheap", 0, 5)
	T.eq(sentSeqs(log.cheap), "reset,1,2,3,4", "cheap history replayed")
	fan:broadcast(frame(5, false, 20), 6)
	fan:sync("many", 0, 7)
	T.eq(sentSeqs(log.many), "reset", "5 frames > maxReplayFrames: wait")
	local statuses = {}
	for _, m in log.many do
		if m.kind == "status" then
			table.insert(statuses, tostring(m.a))
		end
	end
	T.eq(table.concat(statuses, ","), "connecting", "joiner told it is catching up")
end

-- Stop reaches held and waiting viewers at once; held viewers resume after it with nothing to replay
do
	local log, send = recorder()
	local fan = Fanout.new(send, { minWindow = 100 })
	fan:broadcast({ kind = "status", status = "live" } :: any, 0)
	fan:broadcast(frame(1, true, 100), 0)
	fan:sync("x", 0, 0)
	fan:broadcast(frame(2, false, 60), 0.1)
	T.eq((fan:viewer("x") :: any).state, "held", "held")
	fan:broadcast({ kind = "status", status = "stopped" } :: any, 0.2)
	local last = log.x[#log.x]
	T.check(last.kind == "status" and last.a == "stopped", "held viewer gets the stop status immediately")
	fan:ack("x", 100, 0.3)
	T.eq((fan:viewer("x") :: any).state, "live", "drained after stop -> live (nothing to replay)")
	T.eq(sentSeqs(log.x), "reset,1", "no frames after stop")
end

-- history limit and stats (lower medians, warm-up)
do
	local _, send = recorder()
	local fan = Fanout.new(send, { historyLimit = 1000, minWindow = 1e9 })
	fan:broadcast(frame(1, true, 600), 0)
	T.eq(fan:wantsKeyframe(), false, "short history")
	fan:broadcast(frame(2, false, 600), 0)
	T.eq(fan:wantsKeyframe(), true, "history over the limit wants a keyframe")
	fan:broadcast(frame(3, true, 100), 0)
	T.eq(fan:wantsKeyframe(), false, "keyframe restarted the history")
	for _, k in { "p", "q", "r" } do
		fan:sync(k, 0, 0)
	end
	fan:ack("p", 100, 0.1, 5)
	fan:ack("q", 100, 0.1, 50)
	fan:ack("r", 100, 0.1, 9)
	fan:broadcast(frame(4, false, 20), 1.0)
	fan:ack("p", 120, 1.5)
	fan:ack("q", 120, 1.5) -- r keeps frame 4 unprocessed: behind by now - 1.0
	local st = fan:stats(4.0)
	T.check(st.viewers == 3 and st.measured == 3 and st.lagging == 0, "counts", st.viewers .. "/" .. st.measured)
	T.eq(st.lag, 0, "lower median of (0, 0, 3)")
	T.eq(st.maxLag, 3, "max lag")
	T.eq(st.costMs, 9, "median decode cost of (5, 9, 50)")
	fan:ack("q", 120, 4.0)
	fan:remove("p")
	T.eq(fan:stats(4.0).lag, 0, "two viewers: the faster one rules")
	fan:sync("new", 0, 4.0)
	T.eq(fan:stats(4.5).measured, 2, "a viewer in its warm-up is not measured")
end

-- --------------------------------------------------------------------------------------- C. network simulation

type Sim = {
	name: string,
	bw: number,
	lat: number,
	queue: { { kind: string, a: any, b: any, c: any, left: number } },
	arriving: { { t: number, m: any } },
	processed: number,
	seq: number,
	desynced: boolean,
	desyncs: number,
	pictures: number,
	lastAckAt: number,
	ackedBytes: number,
	lastSyncAt: number,
	maxBacklog: number,
	seen: { [number]: boolean },
}

local function simulate(opts: any): any
	local DT = 1 / 60
	local sims: { [string]: Sim } = {}
	local fan = Fanout.new(function(key: any, kind: string, a: any, b: any, c: any)
		local s = sims[key]
		table.insert(s.queue, { kind = kind, a = a, b = b, c = c, left = if kind == "part" then buffer.len(a) else 0 })
	end)
	local toServer: { { t: number, f: () -> () } } = {}
	local function later(t: number, f: () -> ())
		table.insert(toServer, { t = t, f = f })
	end
	local seq, nextFrame, forceKey, lastKeyReq, lastControl = 0, 0, true, -math.huge, 0
	local now = 0
	local joinAt = opts.join or {}
	local stats = { fastGaps = 0, keyframes = 0, fastHoldsAfterWarmup = 0 }
	local firstChecked, lastAnimated, holdsAtWarmup = 0, 0, -1
	while now < opts.duration do
		now += DT
		-- viewers join
		for name, cfg in opts.viewers do
			if sims[name] == nil and now >= (joinAt[name] or 0) then
				local s: Sim = { name = name, bw = cfg.bw, lat = cfg.lat, queue = {}, arriving = {}, processed = 0, seq = 0,
					desynced = false, desyncs = 0, pictures = 0, lastAckAt = 0, ackedBytes = 0, lastSyncAt = now,
					maxBacklog = 0, seen = {} }
				sims[name] = s
				later(now + s.lat, function()
					fan:sync(name, 0, now)
				end)
			end
		end
		-- the desktop: frames at opts.fps while animating, a keyframe when asked for (or every keyEvery frames)
		if (now < opts.animateUntil or forceKey) and now >= nextFrame then
			nextFrame = now + 1 / opts.fps
			seq += 1
			local key = forceKey or seq % opts.keyEvery == 1
			forceKey = false
			if key then
				stats.keyframes += 1
			end
			fan:broadcast(frame(seq, key, if key then opts.keySize else opts.deltaSize), now)
		end
		-- server control: keyframe requests (2 s cooldown, as RlpsServer)
		if now - lastControl >= 0.5 then
			lastControl = now
			if fan:wantsKeyframe() and now - lastKeyReq >= 2 then
				lastKeyReq, forceKey = now, true
			end
		end
		-- network + clients
		for name, s in sims do
			local budget = s.bw * DT
			while s.queue[1] do
				local q = s.queue[1]
				if q.left > budget then
					q.left -= budget
					break
				end
				budget -= q.left
				table.remove(s.queue, 1)
				table.insert(s.arriving, { t = now + s.lat, m = q })
			end
			while s.arriving[1] and s.arriving[1].t <= now do
				local m = table.remove(s.arriving, 1).m
				if m.kind == "part" then
					s.processed += buffer.len(m.a)
					local fseq, base, key = buffer.readu32(m.a, 0), buffer.readu32(m.a, 4), buffer.readu8(m.a, 8) == 1
					if key then
						s.seq, s.desynced = fseq, false
						s.pictures += 1
						s.seen[fseq] = true
					elseif s.desynced or s.seq == 0 or fseq <= s.seq then
						-- waiting for a keyframe / stale
					elseif base == s.seq then
						s.seq = fseq
						s.pictures += 1
						s.seen[fseq] = true
					else
						s.desynced = true
						s.desyncs += 1
					end
				elseif m.kind == "advance" then
					if not s.desynced and s.seq == m.b then
						s.seq = m.c
					elseif s.seq < m.c and s.seq ~= 0 then
						s.desynced = true
						s.desyncs += 1
					end
				elseif m.kind == "reset" then
					s.seq, s.desynced = 0, false
				end
			end
			if now - s.lastAckAt >= 0.1 and s.processed ~= s.ackedBytes then
				s.lastAckAt, s.ackedBytes = now, s.processed
				local p = s.processed
				later(now + s.lat, function()
					fan:ack(name, p, now)
				end)
			end
			if s.desynced and now - s.lastSyncAt >= 3 then
				s.lastSyncAt = now
				local p = s.processed
				later(now + s.lat, function()
					fan:sync(name, p, now)
				end)
			end
			local v = fan:viewer(name)
			if v then
				s.maxBacklog = math.max(s.maxBacklog, v.sent - v.acked)
			end
		end
		-- messages reaching the server
		local i = 1
		while i <= #toServer do
			if toServer[i].t <= now then
				table.remove(toServer, i).f()
			else
				i += 1
			end
		end
		-- after a 3 s warm-up the fast viewer must receive every frame and never be held again
		local fv = fan:viewer(opts.fast or "")
		if fv and now > (joinAt[opts.fast] or 0) + 3 then
			if holdsAtWarmup < 0 then
				holdsAtWarmup, firstChecked = fv.holds, seq
			end
			stats.fastHoldsAfterWarmup = fv.holds - holdsAtWarmup
		end
		if now < opts.animateUntil then
			lastAnimated = seq
		end
	end
	local fast = sims[opts.fast or ""]
	if fast and firstChecked > 0 then
		for k = firstChecked + 1, lastAnimated do
			if not fast.seen[k] then
				stats.fastGaps += 1
			end
		end
	end
	return { sims = sims, fan = fan, lastSeq = seq, stats = stats }
end

-- one fast viewer and one 10 KB/s viewer on a 1 MB/s, 30 fps stream
do
	local r = simulate({
		duration = 70,
		animateUntil = 40,
		fps = 30,
		keyEvery = 300,
		keySize = 120 * 1024,
		deltaSize = 33 * 1024,
		fast = "Fast",
		viewers = { Fast = { bw = 8e6, lat = 0.05 }, Slow = { bw = 10e3, lat = 0.1 } },
		join = { Fast = 0, Slow = 5 },
	})
	local fast, slow = r.sims.Fast, r.sims.Slow
	local vf, vs = r.fan:viewer("Fast") :: any, r.fan:viewer("Slow") :: any
	T.eq(r.stats.fastGaps, 0, "fast viewer receives every frame although a 10 KB/s viewer watches")
	T.eq(r.stats.fastHoldsAfterWarmup, 0, "fast viewer never held after its warm-up")
	T.check(vf.holds <= 2, "fast viewer held at most twice while warming up", tostring(vf.holds))
	T.check(fast.maxBacklog < 400 * 1024, "fast viewer backlog small", tostring(fast.maxBacklog))
	T.eq(fast.desyncs + slow.desyncs, 0, "no viewer ever desynced")
	T.check(slow.maxBacklog <= 2 * 120 * 1024 + 128 * 1024 + 33 * 1024, "slow viewer backlog bounded (keyframe-sized)",
		tostring(slow.maxBacklog))
	T.check(slow.pictures >= 3, "slow viewer still gets pictures (slideshow)", tostring(slow.pictures))
	T.check(r.stats.keyframes <= 16, "keyframes for the slow viewer are rate-limited", tostring(r.stats.keyframes))
	T.eq(fast.seq, r.lastSeq, "fast viewer ends on the last frame")
	T.eq(slow.seq, r.lastSeq, "slow viewer ends on the last frame (after the stream went still)")
	T.check(vf.rate > 1e6, "fast viewer's delivery rate measured above the stream rate", tostring(vf.rate))
	T.check(vs.rate > 5e3 and vs.rate < 30e3, "slow viewer's delivery rate ~10 KB/s", tostring(vs.rate))
	local st = r.fan:stats(70)
	T.eq(st.lagging, 0, "both live at the end")
end

-- several viewers of similar speed: nobody is held after warm-up, nothing skipped
do
	local r = simulate({
		duration = 20,
		animateUntil = 18,
		fps = 60,
		keyEvery = 600,
		keySize = 200 * 1024,
		deltaSize = 40 * 1024,
		fast = "A",
		viewers = { A = { bw = 5e6, lat = 0.08 }, B = { bw = 4e6, lat = 0.12 }, C = { bw = 6e6, lat = 0.03 } },
		join = { A = 0, B = 1, C = 2 },
	})
	T.eq(r.stats.fastHoldsAfterWarmup, 0, "A never held after its warm-up")
	for _, name in { "A", "B", "C" } do
		local v = r.fan:viewer(name) :: any
		T.check(v.holds <= 3, name .. " held at most a few times while warming up", tostring(v.holds))
		T.eq(r.sims[name].seq, r.lastSeq, name .. " on the last frame")
		T.eq(r.sims[name].desyncs, 0, name .. " never desynced")
	end
	T.eq(r.stats.fastGaps, 0, "A got every frame")
end

T.summary()
