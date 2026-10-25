-- Shared helpers for the standalone-Luau specs (copied next to the specs by run_luau_tests.py).
local Decoder = require("./RlpsDecoder")
local V = require("./vectors")

local H = {}

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

function H.crc32(b: buffer): number
	local crc = 0xFFFFFFFF
	local band, bxor, rshift, readu8 = bit32.band, bit32.bxor, bit32.rshift, buffer.readu8
	for i = 0, buffer.len(b) - 1 do
		crc = bxor(crcTable[band(bxor(crc, readu8(b, i)), 0xFF) + 1], rshift(crc, 8))
	end
	return bxor(crc, 0xFFFFFFFF)
end

-- Test stand-in for EncodingService:DecompressBuffer (maps payloads encoded by the Python side to their raw bytes).
function H.decompress(payload: buffer, rawLength: number): (buffer?, string?)
	local raw = V.zstd[buffer.tostring(payload)]
	if raw == nil then
		return nil, "zstd decode failed (test shim: unknown payload)"
	end
	if #raw ~= rawLength then
		return nil, "zstd content size does not match rawLength"
	end
	return buffer.fromstring(raw), nil
end

-- Part records of a container (what the server relay forwards), in order.
function H.records(data: string): { buffer }
	local b = buffer.fromstring(data)
	local c, err = Decoder.parseContainer(b)
	assert(c, "vector container must parse: " .. tostring(err))
	local out = {}
	for _, ref in c.parts do
		table.insert(out, Decoder.extractRecord(b, ref))
	end
	return out
end

function H.sequence(name: string): any
	for _, s in V.sequences do
		if s.name == name then
			return s
		end
	end
	error("no vector sequence " .. name)
end

export type Counter = {
	ok: (string) -> (),
	fail: (string, string) -> (),
	check: (boolean, string, string?) -> boolean,
	eq: (any, any, string) -> boolean,
	summary: () -> (),
}

function H.counter(): Counter
	local passed, failed = 0, 0
	local t = {} :: Counter
	t.ok = function(_name: string)
		passed += 1
	end
	t.fail = function(name: string, detail: string)
		failed += 1
		print("FAIL " .. name .. ": " .. detail)
	end
	t.check = function(cond: boolean, name: string, detail: string?): boolean
		if cond then
			t.ok(name)
		else
			t.fail(name, detail or "check failed")
		end
		return cond
	end
	t.eq = function(got: any, want: any, name: string): boolean
		return t.check(got == want, name, "got " .. tostring(got) .. ", expected " .. tostring(want))
	end
	t.summary = function()
		print(string.format("SUMMARY passed=%d failed=%d", passed, failed))
	end
	return t
end

return H
