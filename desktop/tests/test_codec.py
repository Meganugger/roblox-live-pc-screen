"""Codec + protocol tests (stdlib unittest): python -m unittest discover -s desktop/tests -t desktop"""

import struct
import unittest

import numpy as np

from rlps import codec
from rlps import protocol as P
from rlps.protocol import ProtocolError

FORMATS = (P.FMT_RGB565, P.FMT_RGB888)


def solid(w, h, rgb=(10, 200, 30)):
    img = np.empty((h, w, 3), np.uint8)
    img[:] = rgb
    return img


def gradient(w, h):
    x = np.linspace(0, 255, w, dtype=np.float64)[None, :]
    y = np.linspace(0, 255, h, dtype=np.float64)[:, None]
    img = np.empty((h, w, 3), np.uint8)
    img[..., 0] = x
    img[..., 1] = y
    img[..., 2] = (x + y) / 2
    return img


def text_like(w, h, seed=0):
    """White page with dark glyph-like strokes (desktop/browser-like content)."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 250, np.uint8)
    for row in range(8, h - 10, 14):
        for col in range(6, w - 10, 7):
            if rng.random() < 0.8:
                gh, gw = rng.integers(5, 10), rng.integers(2, 6)
                img[row : row + gh, col : col + gw] = rng.integers(0, 80)
    return img


def noise(w, h, seed=0):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def roundtrip(img, fmt, encoder=None, **kw):
    q = codec.quantize(img, fmt)
    enc = encoder or codec.FrameEncoder()
    data = enc.encode(q, fmt, session_id=kw.get("session_id", 1234), seq=kw.get("seq", 1))
    out = codec.apply_container(None, codec.parse_container(data))
    return q, data, out


class QuantizeTests(unittest.TestCase):
    def test_rgb565_known_values(self):
        img = np.array([[[255, 255, 255], [0, 0, 0], [255, 0, 0], [0, 255, 0], [0, 0, 255], [8, 4, 8]]], np.uint8)
        q = codec.quantize(img, P.FMT_RGB565)
        self.assertEqual(q.tolist(), [[0xFFFF, 0x0000, 0xF800, 0x07E0, 0x001F, 0x0821]])
        rgba = codec.expand_to_rgba(q, P.FMT_RGB565)
        self.assertEqual(rgba[0, 0].tolist(), [255, 255, 255, 255])
        self.assertEqual(rgba[0, 1].tolist(), [0, 0, 0, 255])
        self.assertEqual(rgba[0, 2].tolist(), [255, 0, 0, 255])

    def test_rgb565_error_bounded(self):
        img = noise(64, 64)
        rgba = codec.expand_to_rgba(codec.quantize(img, P.FMT_RGB565), P.FMT_RGB565)
        err = np.abs(rgba[..., :3].astype(int) - img.astype(int))
        self.assertLessEqual(err[..., 0].max(), 7)
        self.assertLessEqual(err[..., 1].max(), 3)
        self.assertLessEqual(err[..., 2].max(), 7)

    def test_rgb888_lossless(self):
        img = noise(40, 30)
        rgba = codec.expand_to_rgba(codec.quantize(img, P.FMT_RGB888), P.FMT_RGB888)
        self.assertTrue(np.array_equal(rgba[..., :3], img))
        self.assertTrue((rgba[..., 3] == 255).all())

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            codec.quantize(np.zeros((10, 10, 4), np.uint8), P.FMT_RGB565)
        with self.assertRaises(ValueError):
            codec.quantize(np.zeros((10, 1025, 3), np.uint8), P.FMT_RGB565)
        with self.assertRaises(ValueError):
            codec.quantize(np.zeros((10, 10, 3), np.uint8), 99)


class KeyframeRoundTripTests(unittest.TestCase):
    def test_images_formats_and_sizes(self):
        sizes = [(1, 1), (16, 16), (17, 15), (37, 23), (320, 180), (480, 270)]
        makers = [solid, gradient, text_like, noise]
        for fmt in FORMATS:
            for w, h in sizes:
                for make in makers:
                    with self.subTest(fmt=fmt, size=(w, h), image=make.__name__):
                        q, data, out = roundtrip(make(w, h), fmt)
                        self.assertTrue(np.array_equal(out, codec.expand_to_rgba(q, fmt)))

    def test_max_dimension(self):
        q, data, out = roundtrip(gradient(1024, 1024), P.FMT_RGB565)
        self.assertTrue(np.array_equal(out, codec.expand_to_rgba(q, P.FMT_RGB565)))

    def test_uncompressed_mode_and_tile_sizes(self):
        for ts in P.ALLOWED_TILE_SIZES:
            enc = codec.FrameEncoder(compression=P.COMP_NONE, tile_size=ts)
            q, data, out = roundtrip(text_like(100, 60), P.FMT_RGB565, enc)
            c = codec.parse_container(data)
            self.assertTrue(all(p.compression == P.COMP_NONE for p in c.parts))
            self.assertEqual(c.tile_size, ts)
            self.assertTrue(np.array_equal(out, codec.expand_to_rgba(q, P.FMT_RGB565)))

    def test_parts_respect_raw_limit_and_cover_all_tiles(self):
        enc = codec.FrameEncoder(max_part_raw_bytes=4096)
        q = codec.quantize(noise(200, 120), P.FMT_RGB565)
        c = codec.parse_container(enc.encode(q, P.FMT_RGB565, session_id=1, seq=5))
        self.assertGreater(len(c.parts), 1)
        self.assertTrue(all(p.raw_length <= 4096 for p in c.parts))
        frame = np.zeros((120, 200, 4), np.uint8)
        covered = []
        for p in c.parts:
            covered += codec.apply_part(frame, p)
        tx, ty = P.tiles_per_axis(200, 120, 16)
        self.assertEqual(covered, list(range(tx * ty)))

    def test_compression_effective_on_desktop_like_content(self):
        stats = codec.EncodeStats()
        q = codec.quantize(text_like(480, 270), P.FMT_RGB565)
        codec.FrameEncoder().encode(q, P.FMT_RGB565, session_id=1, seq=1, stats=stats)
        self.assertLess(stats.compressed_bytes, stats.raw_bytes / 4)
        stats = codec.EncodeStats()
        codec.FrameEncoder().encode(codec.quantize(solid(480, 270), P.FMT_RGB565), P.FMT_RGB565, session_id=1,
                                    seq=1, stats=stats)
        self.assertLess(stats.container_bytes, 2000)


class DeltaTests(unittest.TestCase):
    def test_delta_contains_only_changed_tiles_and_reconstructs(self):
        for fmt in FORMATS:
            enc = codec.FrameEncoder()
            a = text_like(330, 190, seed=1)
            b = a.copy()
            b[20:40, 100:150] = (255, 0, 0)  # spans tiles x 6..9, y 1..2
            b[185:190, 325:330] = (0, 0, 255)  # bottom-right partial tile
            qa, qb = codec.quantize(a, fmt), codec.quantize(b, fmt)
            frame = codec.apply_container(None, codec.parse_container(enc.encode(qa, fmt, session_id=9, seq=1)))
            data = enc.encode(qb, fmt, session_id=9, seq=2, base_seq=1, prev=qa)
            c = codec.parse_container(data)
            self.assertFalse(c.keyframe)
            self.assertEqual((c.seq, c.base_seq), (2, 1))
            idx = [i for p in c.parts for i in codec.apply_part(frame, p)]
            tiles_x, tiles_y = P.tiles_per_axis(330, 190, 16)
            expected = sorted({ty * tiles_x + tx for ty in (1, 2) for tx in range(6, 10)} |
                              {(tiles_y - 1) * tiles_x + tiles_x - 1})
            self.assertEqual(idx, expected)
            self.assertTrue(np.array_equal(frame, codec.expand_to_rgba(qb, fmt)))

    def test_sub_quantization_change_is_invisible(self):
        a = solid(64, 64, (100, 100, 100))
        b = a.copy()
        b[5, 5] = (101, 101, 101)  # same RGB565 value
        qa, qb = codec.quantize(a, P.FMT_RGB565), codec.quantize(b, P.FMT_RGB565)
        self.assertIsNone(codec.FrameEncoder().encode(qb, P.FMT_RGB565, session_id=1, seq=2, base_seq=1, prev=qa))

    def test_sequence_of_changing_frames(self):
        enc = codec.FrameEncoder()
        rng = np.random.default_rng(3)
        img = text_like(256, 144)
        prev_q, frame = None, None
        for seq in range(1, 30):
            x, y = rng.integers(0, 240), rng.integers(0, 130)
            img = img.copy()
            img[y : y + 14, x : x + 16] = rng.integers(0, 256, 3)
            q = codec.quantize(img, P.FMT_RGB565)
            data = enc.encode(q, P.FMT_RGB565, session_id=5, seq=seq, base_seq=seq - 1, prev=prev_q)
            if data is not None:
                frame = codec.apply_container(frame, codec.parse_container(data))
            prev_q = q
        self.assertTrue(np.array_equal(frame, codec.expand_to_rgba(prev_q, P.FMT_RGB565)))

    def test_resolution_change_forces_keyframe_semantics(self):
        qa = codec.quantize(solid(32, 32), P.FMT_RGB565)
        qb = codec.quantize(solid(48, 32), P.FMT_RGB565)
        self.assertEqual(len(codec.changed_tiles(qa, qb)), 3 * 2)
        with self.assertRaises(ProtocolError):  # delta against a frame of another size is rejected by the client
            data = codec.FrameEncoder().encode(qb, P.FMT_RGB565, session_id=1, seq=2, base_seq=1, prev=qa)
            codec.apply_container(np.zeros((32, 32, 4), np.uint8), codec.parse_container(data))

    def test_delta_without_base_raises(self):
        q = codec.quantize(solid(16, 16), P.FMT_RGB565)
        with self.assertRaises(ValueError):
            codec.FrameEncoder().encode(q, P.FMT_RGB565, session_id=1, seq=2, base_seq=1, keyframe=False)


class StatusAndBodyTests(unittest.TestCase):
    def test_status_containers(self):
        stopped = codec.parse_container(codec.status_container(P.STATE_STOPPED))
        self.assertEqual((stopped.state, stopped.parts), (P.STATE_STOPPED, []))
        unchanged = codec.parse_container(codec.status_container(P.STATE_LIVE, session_id=3, seq=42, width=320,
                                                                 height=180, fmt=P.FMT_RGB565))
        self.assertTrue(unchanged.flags & P.CFLAG_UNCHANGED)
        self.assertEqual((unchanged.seq, unchanged.base_seq, unchanged.session_id), (42, 42, 3))

    def test_base64_body(self):
        q, data, _ = roundtrip(gradient(64, 32), P.FMT_RGB565)
        body = codec.to_body(data)
        self.assertTrue(body.isascii())
        self.assertEqual(codec.from_body(body), data)
        self.assertEqual(codec.from_body(body.decode()), data)
        with self.assertRaises(ProtocolError):
            codec.from_body(b"!!!not base64!!!")


def _container_fields(data):
    return list(P.CONTAINER_HEADER.unpack_from(data, 0))


def _repack_container(data, **changes):
    names = ["magic", "version", "state", "flags", "reserved", "session", "seq", "base", "width", "height", "fmt",
             "ts", "parts", "body"]
    f = dict(zip(names, _container_fields(data)))
    f.update(changes)
    return P.CONTAINER_HEADER.pack(*[f[n] for n in names]) + data[P.CONTAINER_HEADER_SIZE:]


class MalformedInputTests(unittest.TestCase):
    def setUp(self):
        self.enc = codec.FrameEncoder()
        self.q = codec.quantize(text_like(64, 48), P.FMT_RGB565)
        self.data = self.enc.encode(self.q, P.FMT_RGB565, session_id=77, seq=3)

    def assertRejected(self, data):
        with self.assertRaises(ProtocolError):
            c = codec.parse_container(data)
            codec.apply_container(None, c)

    def test_truncation_at_every_length(self):
        for n in range(0, len(self.data)):
            with self.subTest(n=n):
                self.assertRejected(self.data[:n])

    def test_trailing_bytes(self):
        self.assertRejected(self.data + b"\0")

    def test_header_fields(self):
        self.assertRejected(b"XXXX" + self.data[4:])
        self.assertRejected(_repack_container(self.data, version=2))
        self.assertRejected(_repack_container(self.data, state=7))
        self.assertRejected(_repack_container(self.data, flags=0x80))
        self.assertRejected(_repack_container(self.data, width=0))
        self.assertRejected(_repack_container(self.data, width=1025))
        self.assertRejected(_repack_container(self.data, height=2000))
        self.assertRejected(_repack_container(self.data, fmt=9))
        self.assertRejected(_repack_container(self.data, ts=12))
        self.assertRejected(_repack_container(self.data, parts=0))
        self.assertRejected(_repack_container(self.data, parts=P.MAX_PARTS + 1))
        self.assertRejected(_repack_container(self.data, seq=0))
        self.assertRejected(_repack_container(self.data, body=len(self.data)))
        self.assertRejected(_repack_container(self.data, session=78))  # parts disagree with container

    def test_delta_sequence_rules(self):
        self.assertRejected(_repack_container(self.data, flags=0))  # delta with baseSeq 0 (parts say keyframe too)

    def test_stopped_with_parts_rejected(self):
        self.assertRejected(_repack_container(self.data, state=P.STATE_STOPPED))

    def _mutate_part(self, **changes):
        names = ["version", "comp", "fmt", "flags", "ts", "reserved", "index", "count", "width", "height", "tiles",
                 "session", "seq", "base", "raw", "complen"]
        off = P.CONTAINER_HEADER_SIZE
        f = dict(zip(names, P.PART_HEADER.unpack_from(self.data, off)))
        f.update(changes)
        return self.data[:off] + P.PART_HEADER.pack(*[f[n] for n in names]) + self.data[off + P.PART_HEADER_SIZE:]

    def test_part_header_fields(self):
        self.assertRejected(self._mutate_part(version=0))
        self.assertRejected(self._mutate_part(comp=5))
        self.assertRejected(self._mutate_part(index=1))
        self.assertRejected(self._mutate_part(tiles=0))
        self.assertRejected(self._mutate_part(tiles=1000))
        self.assertRejected(self._mutate_part(raw=P.MAX_PART_RAW_BYTES + 1))
        self.assertRejected(self._mutate_part(complen=0))
        self.assertRejected(self._mutate_part(flags=0))  # keyframe flag disagrees with container
        self.assertRejected(self._mutate_part(raw=self.enc.max_part_raw_bytes - 1))  # zstd content size mismatch

    def test_corrupted_zstd_payload(self):
        off = P.CONTAINER_HEADER_SIZE + P.PART_HEADER_SIZE
        bad = bytearray(self.data)
        for i in range(off + 8, len(bad), 3):
            bad[i] ^= 0x5A
        self.assertRejected(bytes(bad))

    def _uncompressed_one_part(self, tile_indices):
        """Hand-built COMP_NONE part with arbitrary tile indices (64x48 RGB565, 16x16 tiles)."""
        raw = struct.pack(f"<{len(tile_indices)}H", *tile_indices) + b"\0\0" * 256 * len(tile_indices)
        part = P.PART_HEADER.pack(1, P.COMP_NONE, P.FMT_RGB565, P.PFLAG_KEYFRAME, 16, 0, 0, 1, 64, 48,
                                  len(tile_indices), 1, 1, 0, len(raw), len(raw)) + raw
        return P.CONTAINER_HEADER.pack(b"RLPS", 1, P.STATE_LIVE, P.CFLAG_KEYFRAME, 0, 1, 1, 0, 64, 48,
                                       P.FMT_RGB565, 16, 1, len(part)) + part

    def test_tile_index_validation(self):
        codec.apply_container(None, codec.parse_container(self._uncompressed_one_part([0, 1, 11])))
        self.assertRejected(self._uncompressed_one_part([0, 12]))  # 4x3 tiles -> max index 11
        self.assertRejected(self._uncompressed_one_part([3, 3]))  # duplicate
        self.assertRejected(self._uncompressed_one_part([5, 2]))  # not increasing

    def test_failed_part_does_not_write(self):
        frame = np.full((48, 64, 4), 7, np.uint8)
        c = codec.parse_container(self._uncompressed_one_part([0, 1, 11]))
        c.parts[0].payload = c.parts[0].payload[:-2] + b"\0\0"  # still valid; then break the index list
        c.parts[0].payload = struct.pack("<H", 40) + c.parts[0].payload[2:]
        with self.assertRaises(ProtocolError):
            codec.apply_part(frame, c.parts[0])
        self.assertTrue((frame == 7).all())


if __name__ == "__main__":
    unittest.main()
