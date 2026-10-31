--!strict
--!native
-- RLPS DCT tile decoder (FMT_HYBRID, tile mode DCT): one 16x16 macroblock = 4 luma + 1 Cb + 1 Cr 8x8 blocks,
-- 384 little-endian int16 coefficients in zigzag order, JPEG tables scaled to one of 16 quality steps.
-- Pure integer arithmetic, bit-identical to desktop/rlps/dct.py `reconstruct` (the encoder keeps the decoder's
-- picture, so any difference would accumulate). Every intermediate value is an integer < 2^53, so Luau's double
-- arithmetic is exact and `//` floors exactly like numpy's `>>`.

local Dct = {}

Dct.QUALITIES = { 10, 20, 30, 40, 50, 60, 70, 75, 80, 85, 88, 90, 92, 94, 96, 98 }

-- natural (row-major) index of zigzag position k (0-based values, 1-based table)
local ZIGZAG = {
	0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
	35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
}
local BASE_LUMA = {
	16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
	18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
}
local BASE_CHROMA = {
	17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
}
-- M[k*8 + n + 1] = round(4096 * dct_basis[k][n])
local M = {
	1448, 1448, 1448, 1448, 1448, 1448, 1448, 1448, 2009, 1703, 1138, 400, -400, -1138, -1703, -2009,
	1892, 784, -784, -1892, -1892, -784, 784, 1892, 1703, -400, -2009, -1138, 1138, 2009, 400, -1703,
	1448, -1448, -1448, 1448, 1448, -1448, -1448, 1448, 1138, -2009, 400, 1703, -1703, -400, 2009, -1138,
	784, -1892, 1892, -784, -784, 1892, -1892, 784, 400, -1138, 1703, -2009, 2009, -1703, 1138, -400,
}
local ROUND = 8388608 -- 2^23
local SCALE = 16777216 -- 2^24

local readu8, readi16, writeu32 = buffer.readu8, buffer.readi16, buffer.writeu32

-- Dequantization multiplier per zigzag position (1-based), per quality index: { luma, chroma }
local tables: { [number]: { { number } } } = {}
local function getTables(qi: number): { { number } }
	local t = tables[qi]
	if t then
		return t
	end
	local q = Dct.QUALITIES[qi + 1]
	local s = if q < 50 then 5000 // q else 200 - 2 * q
	local luma, chroma = table.create(64, 0), table.create(64, 0)
	for k = 1, 64 do
		local pos = ZIGZAG[k] + 1
		luma[k] = math.clamp((BASE_LUMA[pos] * s + 50) // 100, 1, 255)
		chroma[k] = math.clamp((BASE_CHROMA[pos] * s + 50) // 100, 1, 255)
	end
	local created = { luma, chroma }
	tables[qi] = created
	return created
end

-- scratch state (single-threaded Luau: one decode at a time)
local deq = table.create(64, 0)
local tmp = table.create(64, 0)
local nzPos = table.create(64, 0)
local colUsed = table.create(8, false)
local Y = table.create(256, 0) -- 16x16 luma samples
local CB = table.create(64, 0)
local CR = table.create(64, 0)

-- Decode block `b` (0..5) whose coefficients start at `coef` into `dst` (a 16- or 8-wide sample table).
local function idctBlock(raw: buffer, coef: number, tab: { number }, dst: { number }, dstW: number, ox: number, oy: number)
	local count = 0
	for k = 1, 64 do
		local v = readi16(raw, coef + (k - 1) * 2)
		if v ~= 0 then
			local pos = ZIGZAG[k]
			deq[pos + 1] = v * tab[k]
			count += 1
			nzPos[count] = pos
		end
	end
	if count == 0 then
		for y = 0, 7 do
			local row = (oy + y) * dstW + ox + 1
			for x = 0, 7 do
				dst[row + x] = 128
			end
		end
		return
	end
	if count == 1 and nzPos[1] == 0 then -- DC only: M[0][*] = 1448 everywhere, so out = 1448^2 * d for every sample
		local d = deq[1]
		deq[1] = 0
		local v = (2096704 * d + ROUND) // SCALE + 128
		v = if v < 0 then 0 elseif v > 255 then 255 else v
		for y = 0, 7 do
			local row = (oy + y) * dstW + ox + 1
			for x = 0, 7 do
				dst[row + x] = v
			end
		end
		return
	end
	-- tmp[i][l] = sum_k M[k][i] * deq[k][l]  over the non-zero coefficients (k, l)
	for i = 1, 64 do
		tmp[i] = 0
	end
	for c = 1, count do
		local pos = nzPos[c]
		local k, l = pos // 8, pos % 8
		local d = deq[pos + 1]
		deq[pos + 1] = 0
		colUsed[l + 1] = true
		local mk = k * 8 + 1
		for i = 0, 7 do
			tmp[i * 8 + l + 1] += M[mk + i] * d
		end
	end
	-- out[i][j] = sum_l tmp[i][l] * M[l][j]
	for i = 0, 7 do
		local ti = i * 8 + 1
		local row = (oy + i) * dstW + ox + 1
		for j = 0, 7 do
			local s = 0
			for l = 0, 7 do
				if colUsed[l + 1] then
					s += tmp[ti + l] * M[l * 8 + j + 1]
				end
			end
			local v = (s + ROUND) // SCALE + 128
			dst[row + j] = if v < 0 then 0 elseif v > 255 then 255 else v
		end
	end
	for l = 1, 8 do
		colUsed[l] = false
	end
end

-- Decode the DCT entry at `off` (its mode byte) of `raw` into the 16x16 RGBA8 rectangle at (x0, y0) of `frame`
-- (row stride `stride` bytes). The caller has validated the entry length and the quality byte.
function Dct.decodeTile(raw: buffer, off: number, frame: buffer, stride: number, x0: number, y0: number)
	local qi = readu8(raw, off + 1)
	local t = getTables(qi)
	local luma, chroma = t[1], t[2]
	local coef = off + 2
	idctBlock(raw, coef, luma, Y, 16, 0, 0)
	idctBlock(raw, coef + 128, luma, Y, 16, 8, 0)
	idctBlock(raw, coef + 256, luma, Y, 16, 0, 8)
	idctBlock(raw, coef + 384, luma, Y, 16, 8, 8)
	idctBlock(raw, coef + 512, chroma, CB, 8, 0, 0)
	idctBlock(raw, coef + 640, chroma, CR, 8, 0, 0)
	for cy = 0, 7 do
		for cx = 0, 7 do
			local cb = CB[cy * 8 + cx + 1] - 128
			local cr = CR[cy * 8 + cx + 1] - 128
			local dr = (91881 * cr + 32768) // 65536
			local dg = (22554 * cb + 46802 * cr + 32768) // 65536
			local db = (116130 * cb + 32768) // 65536
			for sy = 0, 1 do
				local py = cy * 2 + sy
				local dst = (y0 + py) * stride + (x0 + cx * 2) * 4
				local yrow = py * 16 + cx * 2 + 1
				for sx = 0, 1 do
					local y = Y[yrow + sx]
					local r, g, b = y + dr, y - dg, y + db
					r = if r < 0 then 0 elseif r > 255 then 255 else r
					g = if g < 0 then 0 elseif g > 255 then 255 else g
					b = if b < 0 then 0 elseif b > 255 then 255 else b
					writeu32(frame, dst + sx * 4, r + g * 256 + b * 65536 + 0xFF000000)
				end
			end
		end
	end
end

return Dct
