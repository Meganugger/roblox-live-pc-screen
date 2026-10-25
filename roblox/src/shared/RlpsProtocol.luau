--!strict
-- RLPS wire protocol v1: constants and binary header layouts.
-- Mirror of desktop/rlps/protocol.py (normative); keep both in sync. All integers are little-endian,
-- which matches the Luau `buffer` library.

local Protocol = {}

Protocol.VERSION = 1
Protocol.MAGIC = "RLPS"

Protocol.FMT_RGB565 = 1 -- 2 bytes/pixel, u16 = r5 << 11 | g6 << 5 | b5
Protocol.FMT_RGB888 = 2 -- 3 bytes/pixel: R, G, B
Protocol.BYTES_PER_PIXEL = { [1] = 2, [2] = 3 } :: { [number]: number }

Protocol.COMP_NONE = 0
Protocol.COMP_ZSTD = 1 -- one zstd frame with content size (EncodingService Zstd)

Protocol.STATE_STOPPED = 0
Protocol.STATE_LIVE = 1

Protocol.CFLAG_KEYFRAME = 0x01
Protocol.CFLAG_UNCHANGED = 0x02
Protocol.PFLAG_KEYFRAME = 0x01

Protocol.ALLOWED_TILE_SIZES = { [8] = true, [16] = true, [32] = true } :: { [number]: boolean }
Protocol.MAX_DIM = 1024 -- EditableImage maximum
Protocol.MAX_PARTS = 512
Protocol.MAX_PART_RAW_BYTES = 256 * 1024
Protocol.MAX_CONTAINER_BYTES = 4 * 1024 * 1024

-- Container header (32 bytes): magic[4] version u8, state u8, flags u8, reserved u8, sessionId u32, seq u32,
-- baseSeq u32, width u16, height u16, format u8, tileSize u8, partCount u16, bodyLength u32
Protocol.CONTAINER_HEADER_SIZE = 32
-- Part header (36 bytes): version u8, compression u8, format u8, flags u8, tileSize u8, reserved u8,
-- partIndex u16, partCount u16, width u16, height u16, tileCount u16, sessionId u32, seq u32, baseSeq u32,
-- rawLength u32, compLength u32
Protocol.PART_HEADER_SIZE = 36

function Protocol.tilesPerAxis(width: number, height: number, tileSize: number): (number, number)
	return (width + tileSize - 1) // tileSize, (height + tileSize - 1) // tileSize
end

-- (x0, y0, w, h) of tile `index` (row-major), clipped to the frame.
function Protocol.tileRect(index: number, width: number, height: number, tileSize: number): (number, number, number, number)
	local tilesX = (width + tileSize - 1) // tileSize
	local ty = index // tilesX
	local tx = index - ty * tilesX
	local x0, y0 = tx * tileSize, ty * tileSize
	return x0, y0, math.min(tileSize, width - x0), math.min(tileSize, height - y0)
end

return Protocol
