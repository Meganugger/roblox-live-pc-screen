--!strict
--!native
-- RLPS v1 decoder: container validation (server relay) and part decoding into an RGBA8 frame buffer (client).
-- Check-for-check mirror of desktop/rlps/codec.py (parse_container, parse_part_header, decompress_part,
-- apply_part). Functions return `nil, reason` instead of throwing so callers can recover without pcall.

local Protocol = require(script.Parent.RlpsProtocol)
local Dct = require(script.Parent.RlpsDct)

local VERSION = Protocol.VERSION
local BPP = Protocol.BYTES_PER_PIXEL
local TILE_SIZES = Protocol.ALLOWED_TILE_SIZES
local MAX_DIM = Protocol.MAX_DIM
local MAX_PARTS = Protocol.MAX_PARTS
local MAX_RAW = Protocol.MAX_PART_RAW_BYTES
local CH = Protocol.CONTAINER_HEADER_SIZE
local PH = Protocol.PART_HEADER_SIZE

local readu8, readu16, readu32 = buffer.readu8, buffer.readu16, buffer.readu32
local writeu32 = buffer.writeu32
local band, bor, lshift, rshift = bit32.band, bit32.bor, bit32.lshift, bit32.rshift

export type PartHeader = {
	compression: number,
	format: number,
	flags: number,
	tileSize: number,
	partIndex: number,
	partCount: number,
	width: number,
	height: number,
	tileCount: number,
	sessionId: number,
	seq: number,
	baseSeq: number,
	rawLength: number,
	compLength: number,
	keyframe: boolean,
	usesRef: boolean,
}

export type PartRef = { header: PartHeader, offset: number, length: number } -- record = header + payload

-- Union of the pixel rectangles written by applyRecord (x1/y1 exclusive); start from Decoder.emptyBounds().
export type Bounds = { x0: number, y0: number, x1: number, y1: number }

export type Container = {
	state: number,
	flags: number,
	sessionId: number,
	seq: number,
	baseSeq: number,
	width: number,
	height: number,
	format: number,
	tileSize: number,
	keyframe: boolean,
	unchanged: boolean,
	parts: { PartRef },
}

-- decompress(payload: buffer, rawLength: number) -> buffer? , reason?
export type Decompress = (buffer, number) -> (buffer?, string?)

local Decoder = {}

function Decoder.parsePartHeader(data: buffer, off: number): (PartHeader?, string?)
	if off < 0 or off + PH > buffer.len(data) then
		return nil, "truncated part header"
	end
	local version, comp, fmt, flags, ts =
		readu8(data, off), readu8(data, off + 1), readu8(data, off + 2), readu8(data, off + 3), readu8(data, off + 4)
	local partIndex, partCount = readu16(data, off + 6), readu16(data, off + 8)
	local width, height, tileCount = readu16(data, off + 10), readu16(data, off + 12), readu16(data, off + 14)
	local sessionId, seq, baseSeq = readu32(data, off + 16), readu32(data, off + 20), readu32(data, off + 24)
	local rawLength, compLength = readu32(data, off + 28), readu32(data, off + 32)
	if version ~= VERSION then
		return nil, "unsupported part version"
	end
	if comp ~= Protocol.COMP_NONE and comp ~= Protocol.COMP_ZSTD then
		return nil, "unknown compression"
	end
	local bpp = BPP[fmt]
	if bpp == nil or not TILE_SIZES[ts] then
		return nil, "invalid part format/tile size"
	end
	if band(flags, bit32.bnot(bor(Protocol.PFLAG_KEYFRAME, Protocol.PFLAG_REF))) ~= 0 then
		return nil, "unknown part flags"
	end
	if band(flags, Protocol.PFLAG_KEYFRAME) ~= 0 and band(flags, Protocol.PFLAG_REF) ~= 0 then
		return nil, "keyframe parts cannot use a reference"
	end
	if band(flags, Protocol.PFLAG_REF) ~= 0 and fmt ~= Protocol.FMT_HYBRID then
		return nil, "only hybrid parts can use a reference"
	end
	if width < 1 or width > MAX_DIM or height < 1 or height > MAX_DIM then
		return nil, "invalid part dimensions"
	end
	if partCount < 1 or partCount > MAX_PARTS or partIndex >= partCount then
		return nil, "invalid part index"
	end
	local tilesX, tilesY = Protocol.tilesPerAxis(width, height, ts)
	if tileCount < 1 or tileCount > tilesX * tilesY then
		return nil, "invalid tile count"
	end
	local maxRaw = math.min(tileCount * Protocol.maxRawPerTile(fmt, ts), MAX_RAW)
	if not (2 * tileCount < rawLength and rawLength <= maxRaw) then
		return nil, "invalid raw length"
	end
	if comp == Protocol.COMP_NONE and compLength ~= rawLength then
		return nil, "uncompressed part length mismatch"
	end
	if compLength == 0 or compLength > MAX_RAW + 1024 then
		return nil, "invalid compressed length"
	end
	return {
		compression = comp,
		format = fmt,
		flags = flags,
		tileSize = ts,
		partIndex = partIndex,
		partCount = partCount,
		width = width,
		height = height,
		tileCount = tileCount,
		sessionId = sessionId,
		seq = seq,
		baseSeq = baseSeq,
		rawLength = rawLength,
		compLength = compLength,
		keyframe = band(flags, Protocol.PFLAG_KEYFRAME) ~= 0,
		usesRef = band(flags, Protocol.PFLAG_REF) ~= 0,
	},
		nil
end

-- Validate a whole container (as returned by the frame service after base64 decoding).
function Decoder.parseContainer(data: buffer): (Container?, string?)
	local n = buffer.len(data)
	if n > Protocol.MAX_CONTAINER_BYTES then
		return nil, "container too large"
	end
	if n < CH then
		return nil, "truncated container header"
	end
	if buffer.readstring(data, 0, 4) ~= Protocol.MAGIC then
		return nil, "bad magic"
	end
	local version, state, flags = readu8(data, 4), readu8(data, 5), readu8(data, 6)
	local sessionId, seq, baseSeq = readu32(data, 8), readu32(data, 12), readu32(data, 16)
	local width, height, fmt, ts = readu16(data, 20), readu16(data, 22), readu8(data, 24), readu8(data, 25)
	local partCount, bodyLength = readu16(data, 26), readu32(data, 28)
	if version ~= VERSION then
		return nil, "unsupported version " .. version
	end
	if bodyLength ~= n - CH then
		return nil, "body length mismatch (truncated or trailing bytes)"
	end
	if band(flags, bit32.bnot(bor(Protocol.CFLAG_KEYFRAME, Protocol.CFLAG_UNCHANGED))) ~= 0 then
		return nil, "unknown container flags"
	end
	local keyframe = band(flags, Protocol.CFLAG_KEYFRAME) ~= 0
	local unchanged = band(flags, Protocol.CFLAG_UNCHANGED) ~= 0
	local c: Container = {
		state = state,
		flags = flags,
		sessionId = sessionId,
		seq = seq,
		baseSeq = baseSeq,
		width = width,
		height = height,
		format = fmt,
		tileSize = ts,
		keyframe = keyframe,
		unchanged = unchanged,
		parts = {},
	}
	if state == Protocol.STATE_STOPPED or unchanged then
		if partCount ~= 0 or bodyLength ~= 0 then
			return nil, "stopped/unchanged container must not carry parts"
		end
		if state ~= Protocol.STATE_STOPPED and state ~= Protocol.STATE_LIVE then
			return nil, "unknown state " .. state
		end
		return c, nil
	end
	if state ~= Protocol.STATE_LIVE then
		return nil, "unknown state " .. state
	end
	if width < 1 or width > MAX_DIM or height < 1 or height > MAX_DIM then
		return nil, "invalid dimensions"
	end
	if BPP[fmt] == nil then
		return nil, "unknown pixel format " .. fmt
	end
	if not TILE_SIZES[ts] then
		return nil, "invalid tile size " .. ts
	end
	if partCount < 1 or partCount > MAX_PARTS then
		return nil, "invalid part count"
	end
	if fmt == Protocol.FMT_HYBRID and (ts ~= Protocol.HYBRID_TILE or width % ts ~= 0 or height % ts ~= 0) then
		return nil, "hybrid frames need tile size 16 and dimensions divisible by 16"
	end
	if seq == 0 or (not keyframe and (baseSeq == 0 or baseSeq == seq)) then
		return nil, "invalid sequence numbers"
	end
	local off = CH
	for i = 0, partCount - 1 do
		if off + PH > n then
			return nil, "truncated part header " .. i
		end
		local h, err = Decoder.parsePartHeader(data, off)
		if h == nil then
			return nil, err
		end
		if
			h.format ~= fmt
			or h.tileSize ~= ts
			or h.partIndex ~= i
			or h.partCount ~= partCount
			or h.width ~= width
			or h.height ~= height
			or h.sessionId ~= sessionId
			or h.seq ~= seq
			or h.baseSeq ~= baseSeq
			or h.keyframe ~= keyframe
			or (#c.parts > 0 and h.usesRef ~= c.parts[1].header.usesRef)
		then
			return nil, "part " .. i .. " header inconsistent with container"
		end
		if off + PH + h.compLength > n then
			return nil, "truncated part payload " .. i
		end
		table.insert(c.parts, { header = h, offset = off, length = PH + h.compLength })
		off += PH + h.compLength
	end
	if off ~= n then
		return nil, "trailing bytes after last part"
	end
	return c, nil
end

-- Copy one part record (header + payload) out of a container into its own buffer (what the relay forwards).
function Decoder.extractRecord(data: buffer, ref: PartRef): buffer
	local out = buffer.create(ref.length)
	buffer.copy(out, 0, data, ref.offset, ref.length)
	return out
end

-- Parse a standalone part record (as received by a client) and check its exact length.
function Decoder.parseRecord(record: buffer): (PartHeader?, string?)
	local h, err = Decoder.parsePartHeader(record, 0)
	if h == nil then
		return nil, err
	end
	if buffer.len(record) ~= PH + h.compLength then
		return nil, "part record length mismatch"
	end
	return h, nil
end

local function payloadRaw(record: buffer, h: PartHeader, decompress: Decompress?): (buffer?, string?)
	local raw: buffer?
	if h.compression == Protocol.COMP_NONE then
		local b = buffer.create(h.rawLength)
		buffer.copy(b, 0, record, PH, h.rawLength)
		raw = b
	else
		if decompress == nil then
			return nil, "no zstd decompressor available"
		end
		local payload = buffer.create(h.compLength)
		buffer.copy(payload, 0, record, PH, h.compLength)
		local out, err = decompress(payload, h.rawLength)
		if out == nil then
			return nil, err or "zstd decode failed"
		end
		raw = out
	end
	if raw == nil or buffer.len(raw) ~= h.rawLength then
		return nil, "decompressed length mismatch"
	end
	return raw, nil
end

-- RGB565 -> packed little-endian RGBA8 (bit replication, alpha 255); built on first use (64 Ki entries).
local lut565: { number }? = nil
local function getLut565(): { number }
	local lut = lut565
	if lut then
		return lut
	end
	local t = table.create(65536, 0)
	for v = 0, 65535 do
		local r5, g6, b5 = band(rshift(v, 11), 31), band(rshift(v, 5), 63), band(v, 31)
		local r = bor(lshift(r5, 3), rshift(r5, 2))
		local g = bor(lshift(g6, 2), rshift(g6, 4))
		local b = bor(lshift(b5, 3), rshift(b5, 2))
		t[v + 1] = bor(r, lshift(g, 8), lshift(b, 16), 0xFF000000)
	end
	lut565 = t
	return t
end

function Decoder.emptyBounds(): Bounds
	return { x0 = math.huge, y0 = math.huge, x1 = -1, y1 = -1 }
end

local function grow(bounds: Bounds?, x0: number, y0: number, tw: number, th: number)
	if bounds then
		bounds.x0 = math.min(bounds.x0, x0)
		bounds.y0 = math.min(bounds.y0, y0)
		bounds.x1 = math.max(bounds.x1, x0 + tw)
		bounds.y1 = math.max(bounds.y1, y0 + th)
	end
end

-- Decode one part record into `frame` (width*height*4 RGBA8 bytes). Validates everything before writing.
-- Returns the number of tiles written, or nil + reason. When `bounds` is given it is grown to cover every written tile.
function Decoder.applyRecord(
	frame: buffer,
	frameWidth: number,
	frameHeight: number,
	record: buffer,
	decompress: Decompress?,
	bounds: Bounds?,
	ref: buffer? -- the picture as it was before this frame (COPY tiles of PFLAG_REF parts)
): (number?, string?)
	local h, herr = Decoder.parseRecord(record)
	if h == nil then
		return nil, herr
	end
	if h.width ~= frameWidth or h.height ~= frameHeight or buffer.len(frame) ~= frameWidth * frameHeight * 4 then
		return nil, "frame buffer size does not match part dimensions"
	end
	local raw, rerr = payloadRaw(record, h, decompress)
	if raw == nil then
		return nil, rerr
	end
	local n, ts, w, hgt = h.tileCount, h.tileSize, h.width, h.height
	local tilesX, tilesY = Protocol.tilesPerAxis(w, hgt, ts)
	local total = tilesX * tilesY
	local last = -1
	for i = 0, n - 1 do
		local idx = readu16(raw, 2 * i)
		if idx <= last or idx >= total then
			return nil, "tile indices must be strictly increasing and in range"
		end
		last = idx
	end
	local rawLen = buffer.len(raw)
	local stride = w * 4
	if h.format == Protocol.FMT_HYBRID then
		if ts ~= Protocol.HYBRID_TILE or w % ts ~= 0 or hgt % ts ~= 0 then
			return nil, "hybrid frames need tile size 16 and dimensions divisible by 16"
		end
		local nq = #Dct.QUALITIES
		local off = 2 * n
		for i = 1, n do -- validate every entry before writing a single pixel
			if off >= rawLen then
				return nil, "tile data length mismatch"
			end
			local mode = readu8(raw, off)
			local size = if mode == Protocol.TILE_MODE_RAW
				then Protocol.HYBRID_RAW_ENTRY
				elseif mode == Protocol.TILE_MODE_DCT then Protocol.HYBRID_DCT_ENTRY
				elseif mode == Protocol.TILE_MODE_COPY then Protocol.HYBRID_COPY_ENTRY
				else 0
			if size == 0 then
				return nil, "unknown tile mode"
			end
			if off + size > rawLen then
				return nil, "tile data length mismatch"
			end
			if mode == Protocol.TILE_MODE_DCT and readu8(raw, off + 1) >= nq then
				return nil, "invalid DCT quality"
			end
			if mode == Protocol.TILE_MODE_COPY then
				if not h.usesRef then
					return nil, "copy tile without reference"
				end
				local x0, y0 = Protocol.tileRect(readu16(raw, 2 * (i - 1)), w, hgt, ts)
				local sx, sy = x0 + buffer.readi16(raw, off + 1), y0 + buffer.readi16(raw, off + 3)
				if sx < 0 or sx > w - ts or sy < 0 or sy > hgt - ts then
					return nil, "copy tile outside the frame"
				end
			end
			off += size
		end
		if off ~= rawLen then
			return nil, "tile data length mismatch"
		end
		if h.usesRef and (ref == nil or buffer.len(ref :: buffer) ~= buffer.len(frame)) then
			return nil, "copy tile without reference"
		end
		off = 2 * n
		for i = 0, n - 1 do
			local x0, y0 = Protocol.tileRect(readu16(raw, 2 * i), w, hgt, ts)
			grow(bounds, x0, y0, 16, 16)
			local mode = readu8(raw, off)
			if mode == Protocol.TILE_MODE_RAW then
				local src = off + 1
				for row = 0, 15 do
					buffer.copy(frame, (y0 + row) * stride + x0 * 4, raw, src, 64)
					src += 64
				end
				off += Protocol.HYBRID_RAW_ENTRY
			elseif mode == Protocol.TILE_MODE_COPY then
				local sx, sy = x0 + buffer.readi16(raw, off + 1), y0 + buffer.readi16(raw, off + 3)
				local r = ref :: buffer
				for row = 0, 15 do
					buffer.copy(frame, (y0 + row) * stride + x0 * 4, r, (sy + row) * stride + sx * 4, 64)
				end
				off += Protocol.HYBRID_COPY_ENTRY
			else
				Dct.decodeTile(raw, off, frame, stride, x0, y0)
				off += Protocol.HYBRID_DCT_ENTRY
			end
		end
		return n, nil
	end
	local bpp = BPP[h.format]
	local expected = 2 * n
	for i = 0, n - 1 do
		local _, _, tw, th = Protocol.tileRect(readu16(raw, 2 * i), w, hgt, ts)
		expected += tw * th * bpp
	end
	if expected ~= rawLen then
		return nil, "tile data length mismatch"
	end
	local src = 2 * n
	if h.format == Protocol.FMT_RGB565 then
		local lut = getLut565()
		for i = 0, n - 1 do
			local x0, y0, tw, th = Protocol.tileRect(readu16(raw, 2 * i), w, hgt, ts)
			grow(bounds, x0, y0, tw, th)
			for row = 0, th - 1 do
				local dst = (y0 + row) * stride + x0 * 4
				for _ = 1, tw do
					writeu32(frame, dst, lut[readu16(raw, src) + 1])
					src += 2
					dst += 4
				end
			end
		end
	elseif h.format == Protocol.FMT_RGBA8 then
		for i = 0, n - 1 do
			local x0, y0, tw, th = Protocol.tileRect(readu16(raw, 2 * i), w, hgt, ts)
			grow(bounds, x0, y0, tw, th)
			local rowBytes = tw * 4
			for row = 0, th - 1 do
				buffer.copy(frame, (y0 + row) * stride + x0 * 4, raw, src, rowBytes)
				src += rowBytes
			end
		end
	else
		for i = 0, n - 1 do
			local x0, y0, tw, th = Protocol.tileRect(readu16(raw, 2 * i), w, hgt, ts)
			grow(bounds, x0, y0, tw, th)
			for row = 0, th - 1 do
				local dst = (y0 + row) * stride + x0 * 4
				for _ = 1, tw do
					writeu32(frame, dst, bor(readu8(raw, src), lshift(readu8(raw, src + 1), 8), lshift(readu8(raw, src + 2), 16), 0xFF000000))
					src += 3
					dst += 4
				end
			end
		end
	end
	return n, nil
end

export type BundleEntry = { tOffsetMs: number, offset: number, length: number }

-- Validate an RLPB bundle (the frame service's response) and locate its containers (oldest first).
function Decoder.parseBundle(data: buffer): ({ BundleEntry }?, string?)
	local n = buffer.len(data)
	if n > Protocol.MAX_BUNDLE_BYTES then
		return nil, "bundle too large"
	end
	if n < Protocol.BUNDLE_HEADER_SIZE then
		return nil, "truncated bundle header"
	end
	if buffer.readstring(data, 0, 4) ~= Protocol.BUNDLE_MAGIC then
		return nil, "bad bundle magic"
	end
	if readu8(data, 4) ~= VERSION then
		return nil, "unsupported bundle version"
	end
	local count, bodyLength = readu16(data, 6), readu32(data, 8)
	if bodyLength ~= n - Protocol.BUNDLE_HEADER_SIZE then
		return nil, "bundle length mismatch"
	end
	if count < 1 or count > Protocol.MAX_BUNDLE_ENTRIES then
		return nil, "invalid bundle entry count"
	end
	local out: { BundleEntry } = {}
	local off = Protocol.BUNDLE_HEADER_SIZE
	for _ = 1, count do
		if off + Protocol.BUNDLE_ENTRY_SIZE > n then
			return nil, "truncated bundle entry"
		end
		local t, len = readu32(data, off), readu32(data, off + 4)
		off += Protocol.BUNDLE_ENTRY_SIZE
		if off + len > n then
			return nil, "truncated bundle entry"
		end
		table.insert(out, { tOffsetMs = t, offset = off, length = len })
		off += len
	end
	if off ~= n then
		return nil, "trailing bytes after bundle"
	end
	return out, nil
end

-- Copy one bundle entry (a container) into its own buffer.
function Decoder.extractEntry(data: buffer, e: BundleEntry): buffer
	local out = buffer.create(e.length)
	buffer.copy(out, 0, data, e.offset, e.length)
	return out
end

return Decoder
