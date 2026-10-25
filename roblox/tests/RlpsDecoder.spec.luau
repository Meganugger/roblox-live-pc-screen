-- Standalone-Luau spec for RlpsDecoder (run through roblox/tests/run_luau_tests.py, which generates ./vectors.luau
-- with the Python reference codec and rewrites the shared modules' Roblox requires to relative path requires).
local Protocol = require("./RlpsProtocol")
local Decoder = require("./RlpsDecoder")
local V = require("./vectors")

local passed, failed = 0, 0
local function ok(name: string)
	passed += 1
end
local function fail(name: string, detail: string)
	failed += 1
	print("FAIL " .. name .. ": " .. detail)
end

-- CRC-32 (IEEE, same as Python zlib.crc32)
local crcTable = table.create(256, 0)
for i = 0, 255 do
	local c = i
	for _ = 1, 8 do
		if bit32.band(c, 1) == 1 then
			c = bit32.bxor(0xEDB88320, bit32.rshift(c, 1))
		else
			c = bit32.rshift(c, 1)
		end
	end
	crcTable[i + 1] = c
end
local function crc32(b: buffer): number
	local crc = 0xFFFFFFFF
	local band, bxor, rshift, readu8 = bit32.band, bit32.bxor, bit32.rshift, buffer.readu8
	for i = 0, buffer.len(b) - 1 do
		crc = bxor(crcTable[band(bxor(crc, readu8(b, i)), 0xFF) + 1], rshift(crc, 8))
	end
	return bxor(crc, 0xFFFFFFFF)
end

-- Test stand-in for EncodingService:DecompressBuffer (maps payloads encoded by the Python side to their raw bytes).
local function decompress(payload: buffer, rawLength: number): (buffer?, string?)
	local raw = V.zstd[buffer.tostring(payload)]
	if raw == nil then
		return nil, "zstd decode failed (test shim: unknown payload)"
	end
	if #raw ~= rawLength then
		return nil, "zstd content size does not match rawLength"
	end
	return buffer.fromstring(raw), nil
end

local FIELDS = { "state", "flags", "sessionId", "seq", "baseSeq", "width", "height", "format", "tileSize" }
local function compareFields(c: any, f: any): string?
	for _, k in FIELDS do
		if c[k] ~= f[k] then
			return k .. "=" .. tostring(c[k]) .. " expected " .. tostring(f[k])
		end
	end
	if #c.parts ~= f.partCount then
		return "partCount=" .. #c.parts .. " expected " .. f.partCount
	end
	return nil
end

-- Apply every part of a parsed LIVE container; returns error string or nil.
local function applyAll(frame: buffer, c: any, data: buffer): string?
	for _, ref in c.parts do
		local rec = Decoder.extractRecord(data, ref)
		local before = crc32(frame)
		local n, err = Decoder.applyRecord(frame, c.width, c.height, rec, decompress)
		if n == nil then
			if crc32(frame) ~= before then
				return "FRAME MODIFIED BY FAILED PART: " .. tostring(err)
			end
			return err
		end
		if n ~= ref.header.tileCount then
			return "tile count returned " .. tostring(n)
		end
	end
	return nil
end

-- 1. valid keyframe/delta sequences: fields + reconstructed frame CRC after every container
for _, s in V.sequences do
	local frame: buffer? = nil
	local fw, fh = 0, 0
	for i, st in s.steps do
		local name = s.name .. "#" .. i
		local data = buffer.fromstring(st.data)
		local c, err = Decoder.parseContainer(data)
		if c == nil then
			fail(name, "parse error " .. tostring(err))
			break
		end
		local d = compareFields(c, st.fields)
		if d then
			fail(name, d)
			break
		end
		if c.keyframe and (frame == nil or fw ~= c.width or fh ~= c.height) then
			frame, fw, fh = buffer.create(c.width * c.height * 4), c.width, c.height
		end
		if frame == nil then
			fail(name, "delta without base")
			break
		end
		local aerr = applyAll(frame, c, data)
		if aerr then
			fail(name, "apply error " .. aerr)
			break
		end
		local crc = crc32(frame)
		if crc ~= st.crc then
			fail(name, string.format("crc %08x expected %08x", crc, st.crc))
			break
		end
		ok(name)
	end
end

-- 2. corruption: truncation / truncation with fixed bodyLength / single-byte mutation / trailing byte / status blobs
local function check(name: string, data: buffer, case: any)
	local c, err = Decoder.parseContainer(data)
	if case.err ~= nil then
		if c ~= nil then
			fail(name, "accepted; expected error '" .. case.err .. "'")
		elseif err ~= case.err then
			fail(name, "error '" .. tostring(err) .. "' expected '" .. case.err .. "'")
		else
			ok(name)
		end
		return
	end
	if c == nil then
		fail(name, "rejected with '" .. tostring(err) .. "'; Python accepted")
		return
	end
	local d = compareFields(c, case.fields)
	if d then
		fail(name, d)
		return
	end
	if case.crc ~= nil then
		local frame = buffer.create(c.width * c.height * 4)
		local aerr = applyAll(frame, c, data)
		if case.applyErr == "*" then
			if aerr == nil then
				fail(name, "apply succeeded; expected a decompression error")
				return
			end
		elseif aerr ~= case.applyErr then
			fail(name, "apply error '" .. tostring(aerr) .. "' expected '" .. tostring(case.applyErr) .. "'")
			return
		end
		local crc = crc32(frame)
		if crc ~= case.crc then
			fail(name, string.format("crc %08x expected %08x", crc, case.crc))
			return
		end
	end
	ok(name)
end

for _, case in V.corruption do
	local blob = V.blobs[case.blob]
	local name, data
	if case.op == "trunc" or case.op == "truncfix" then
		name = case.blob .. ":" .. case.op .. "@" .. case.n
		data = buffer.create(case.n)
		buffer.copy(data, 0, buffer.fromstring(blob), 0, case.n)
		if case.op == "truncfix" then
			buffer.writeu32(data, 28, case.n - Protocol.CONTAINER_HEADER_SIZE)
		end
	elseif case.op == "set" then
		name = case.blob .. ":set@" .. case.off .. "=" .. case.v
		data = buffer.fromstring(blob)
		buffer.writeu8(data, case.off, case.v)
	elseif case.op == "append" then
		name = case.blob .. ":append"
		data = buffer.fromstring(blob .. "\0")
	else
		name = case.blob
		data = buffer.fromstring(blob)
	end
	check(name, data, case)
end

-- 3. hand-built payloads (tile index rules, data length)
for _, case in V.payload do
	check("payload:" .. case.name, buffer.fromstring(case.data), case)
end

-- 4. record-level checks used by clients receiving relayed parts
do
	local data = buffer.fromstring(V.blobs.key)
	local c = Decoder.parseContainer(data)
	assert(c, "key blob must parse")
	local rec = Decoder.extractRecord(data, c.parts[1])
	local h, err = Decoder.parseRecord(rec)
	if h and h.partIndex == 0 and err == nil then
		ok("record:parse")
	else
		fail("record:parse", tostring(err))
	end
	local longer = buffer.create(buffer.len(rec) + 1)
	buffer.copy(longer, 0, rec)
	local _, e2 = Decoder.parseRecord(longer)
	if e2 == "part record length mismatch" then
		ok("record:trailing")
	else
		fail("record:trailing", tostring(e2))
	end
	local frame = buffer.create(c.width * c.height * 4)
	local _, e3 = Decoder.applyRecord(frame, c.width + 1, c.height, rec, decompress)
	if e3 == "frame buffer size does not match part dimensions" then
		ok("record:frame-size")
	else
		fail("record:frame-size", tostring(e3))
	end
	local small = buffer.create(c.width * c.height * 4 - 4)
	local _, e4 = Decoder.applyRecord(small, c.width, c.height, rec, decompress)
	if e4 == "frame buffer size does not match part dimensions" then
		ok("record:frame-buffer-len")
	else
		fail("record:frame-buffer-len", tostring(e4))
	end
end

print(string.format("SUMMARY passed=%d failed=%d", passed, failed))
