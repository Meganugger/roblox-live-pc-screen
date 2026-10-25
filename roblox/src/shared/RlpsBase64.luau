--!strict
-- Strict RFC 4648 base64 decoder (standard alphabet, padded): fallback for EncodingService:Base64Decode when the
-- frame-service body (codec.to_body) must be decoded in Luau. Like Python base64.b64decode(validate=True) it rejects
-- non-alphabet bytes (whitespace included), lengths that are not a multiple of 4 and misplaced padding.

local Base64 = {}

local INVALID = 256
local DEC = table.create(256, INVALID)
do
	local alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
	for i = 1, 64 do
		DEC[string.byte(alphabet, i) + 1] = i - 1
	end
end

local readu8, writeu8 = buffer.readu8, buffer.writeu8
local band, bor, lshift, rshift = bit32.band, bit32.bor, bit32.lshift, bit32.rshift

function Base64.decode(s: string): (buffer?, string?)
	local n = #s
	if n % 4 ~= 0 then
		return nil, "invalid base64 length"
	end
	local pad = 0
	if n > 0 and string.byte(s, n) == 61 then
		pad = if string.byte(s, n - 1) == 61 then 2 else 1
	end
	local src = buffer.fromstring(s)
	local out = buffer.create(n // 4 * 3 - pad)
	local full = if pad > 0 then n - 4 else n
	local o = 0
	for i = 0, full - 4, 4 do
		local a, b = DEC[readu8(src, i) + 1], DEC[readu8(src, i + 1) + 1]
		local c, d = DEC[readu8(src, i + 2) + 1], DEC[readu8(src, i + 3) + 1]
		if bor(a, b, c, d) >= INVALID then
			return nil, "invalid base64 character"
		end
		local v = bor(lshift(a, 18), lshift(b, 12), lshift(c, 6), d)
		writeu8(out, o, rshift(v, 16))
		writeu8(out, o + 1, band(rshift(v, 8), 255))
		writeu8(out, o + 2, band(v, 255))
		o += 3
	end
	if pad > 0 then
		local i = n - 4
		local a, b = DEC[readu8(src, i) + 1], DEC[readu8(src, i + 1) + 1]
		if pad == 2 then
			if bor(a, b) >= INVALID then
				return nil, "invalid base64 character"
			end
			writeu8(out, o, band(bor(lshift(a, 2), rshift(b, 4)), 255))
		else
			local c = DEC[readu8(src, i + 2) + 1]
			if bor(a, b, c) >= INVALID then
				return nil, "invalid base64 character"
			end
			local v = bor(lshift(a, 18), lshift(b, 12), lshift(c, 6))
			writeu8(out, o, rshift(v, 16))
			writeu8(out, o + 1, band(rshift(v, 8), 255))
		end
	end
	return out, nil
end

return Base64
