"""Hybrid (DCT + lossless) encoder tests: the reference decoder must rebuild exactly the encoder's reconstruction,
budgets must be respected, and a still picture must converge to a pixel-exact copy."""

import unittest

import numpy as np

from rlps import codec, dct, hybrid
from rlps import protocol as P

W, H = 160, 96


def noise(seed, h=H, w=W):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def smooth(t, h=H, w=W):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([128 + 100 * np.sin((xx + 5 * t) / 13), 128 + 100 * np.sin((yy - 3 * t) / 9),
                    128 + 90 * np.sin((xx + yy) / 17)], axis=2)
    return np.clip(img, 0, 255).astype(np.uint8)


def tile_modes(container: bytes) -> set[int]:
    """Tile entry modes used in a hybrid container."""
    sizes = {P.TILE_MODE_RAW: P.HYBRID_RAW_ENTRY, P.TILE_MODE_DCT: P.HYBRID_DCT_ENTRY,
             P.TILE_MODE_DCT2: P.HYBRID_DCT_ENTRY, P.TILE_MODE_COPY: P.HYBRID_COPY_ENTRY}
    modes = set()
    for part in codec.parse_container(container).parts:
        raw = codec.decompress_part(part)
        off = 2 * part.tile_count
        for _ in range(part.tile_count):
            modes.add(raw[off])
            off += sizes[raw[off]]
    return modes


class Chain:
    def __init__(self):
        self.enc = hybrid.HybridEncoder(W, H)
        self.img = None
        self.seq = 0

    def push(self, rgb, budget=None, force=False):
        c, info = self.enc.encode(codec.quantize(rgb, P.FMT_HYBRID), session_id=7, seq=self.seq + 1,
                                  base_seq=self.seq, budget=budget, force_keyframe=force)
        if c is not None:
            self.seq += 1
            parsed = codec.parse_container(c)
            self.img = codec.apply_container(self.img, parsed)
        return c, info


class DctTests(unittest.TestCase):
    def test_quality_tables_monotonic_and_bounded(self):
        prev = None
        for i in range(len(dct.QUALITIES)):
            luma, chroma = dct.tables(i)
            self.assertTrue(((1 <= luma) & (luma <= 255)).all() and ((1 <= chroma) & (chroma <= 255)).all())
            if prev is not None:
                self.assertTrue((luma <= prev).all())  # better quality -> finer steps
            prev = luma

    def test_higher_quality_is_closer(self):
        tiles = smooth(0, 16, 16)[None]
        coefs = dct.forward_coefficients(tiles)
        errs = []
        for qi in (0, 7, 15):
            rec = dct.reconstruct(dct.quantize(coefs, qi), qi)[0, ..., :3].astype(int)
            errs.append(np.abs(rec - tiles[0].astype(int)).mean())
        self.assertTrue(errs[0] > errs[1] > errs[2])
        self.assertLess(errs[2], 3.0)

    def test_float_blas_idct_equals_integer_specification(self):
        """dct.reconstruct uses float64 matmul for speed; it must equal the pure-integer formula of the Luau decoder."""
        rng = np.random.default_rng(0)
        qz = np.concatenate([rng.integers(-32768, 32768, (3, 6, 64)), rng.normal(0, 40, (5, 6, 64))]).astype(np.int16)
        qis = np.array([15, 0, 7, 3, 9, 15, 0, 12])
        fast = dct.reconstruct(qz, qis)
        mi = dct.M.tolist()
        for n in range(qz.shape[0]):
            luma, chroma = dct.tables(int(qis[n]))
            samples = []
            for b in range(6):
                nat = [0] * 64
                for k in range(64):
                    nat[int(dct.ZIGZAG[k])] = int(qz[n, b, k])
                tab = (luma if b < 4 else chroma).tolist()
                d = [[nat[r * 8 + c] * tab[r * 8 + c] for c in range(8)] for r in range(8)]
                samples.append([[min(255, max(0, ((sum(mi[k][i] * d[k][l] * mi[l][j] for k in range(8) for l in range(8))
                                                  + (1 << 23)) >> 24) + 128)) for j in range(8)] for i in range(8)])
            y = lambda py, px: samples[(py // 8) * 2 + px // 8][py % 8][px % 8]  # noqa: E731
            for py in range(0, 16, 5):
                for px in range(0, 16, 3):
                    cb, cr = samples[4][py // 2][px // 2] - 128, samples[5][py // 2][px // 2] - 128
                    yy = y(py, px)
                    want = (min(255, max(0, yy + ((91881 * cr + 32768) >> 16))),
                            min(255, max(0, yy - ((22554 * cb + 46802 * cr + 32768) >> 16))),
                            min(255, max(0, yy + ((116130 * cb + 32768) >> 16))))
                    self.assertEqual(tuple(int(v) for v in fast[n, py, px, :3]), want, (n, py, px))

    def test_entry_round_trip_and_rejection(self):
        tiles = noise(1, 16, 16)[None]
        qz = dct.quantize(dct.forward_coefficients(tiles), 9)
        entry = dct.pack_entries(qz, 9)[0]
        self.assertEqual(len(entry), P.HYBRID_DCT_ENTRY)
        self.assertTrue(np.array_equal(dct.decode_entry(entry), dct.reconstruct(qz, 9)[0]))
        for bad in (entry[:-1], bytes((0,)) + entry[1:], entry[:1] + bytes((99,)) + entry[2:]):
            with self.assertRaises(P.ProtocolError):
                dct.decode_entry(bad)


class HybridTests(unittest.TestCase):
    def test_unlimited_budget_is_lossless(self):
        ch = Chain()
        c, info = ch.push(noise(1))
        self.assertTrue(info.keyframe and info.mode == "lossless")
        self.assertTrue(np.array_equal(ch.img[..., :3], noise(1)))

    def test_decoder_matches_encoder_reconstruction_exactly(self):
        ch = Chain()
        ch.push(smooth(0), budget=4000, force=True)
        for t in range(1, 6):
            ch.push(smooth(t), budget=6000)
            self.assertTrue(np.array_equal(ch.img, ch.enc.recon), t)

    def test_budget_respected_and_skip_when_too_small(self):
        ch = Chain()
        c, info = ch.push(smooth(0), budget=100)  # keyframes always go out (lowest quality)
        self.assertIsNotNone(c)
        self.assertEqual(info.quality, dct.QUALITIES[0])
        for t in range(1, 4):
            c, info = ch.push(smooth(t), budget=9000)
            if c is not None:
                self.assertLessEqual(len(c), 9000)
        c, info = ch.push(noise(5), budget=50)
        self.assertIsNone(c)
        self.assertTrue(info.skipped)

    def test_still_picture_converges_to_pixel_exact(self):
        ch = Chain()
        ch.push(smooth(0), budget=3000, force=True)
        target = smooth(3)
        for _ in range(60):
            ch.push(target, budget=8000)
        self.assertTrue(np.array_equal(ch.img[..., :3], target))
        self.assertTrue(np.array_equal(ch.img, ch.enc.recon))
        c, _ = ch.push(target, budget=8000)
        self.assertIsNone(c)  # nothing left to send

    def test_scrolling_is_sent_as_copies(self):
        rng = np.random.default_rng(4)
        page = np.full((H * 3, W, 3), 245, np.uint8)
        for y in range(4, page.shape[0] - 10, 9):  # text-like lines
            page[y:y + 6, 8:W - 8] = rng.integers(0, 80, (6, W - 16, 3))
        ch = Chain()
        ch.push(page[:H])
        sizes = []
        for k in range(1, 6):
            c, info = ch.push(page[8 * k:8 * k + H])
            self.assertGreater(info.copied_tiles, 0)
            self.assertTrue(np.array_equal(ch.img[..., :3], page[8 * k:8 * k + H]))  # still lossless
            self.assertTrue(np.array_equal(ch.img, ch.enc.recon))
            sizes.append(len(c))
        lossless_only = Chain()
        lossless_only.push(page[:H])
        lossless_only.enc._scroll_copies = lambda src, moving: {}  # same chain without scroll detection
        plain = [len(lossless_only.push(page[8 * k:8 * k + H])[0]) for k in range(1, 6)]
        self.assertLess(sum(sizes), sum(plain) * 0.6)

    def test_copy_tiles_validated(self):
        ch = Chain()
        ch.push(smooth(0))
        base = ch.img.copy()

        def container(dx, dy, ref_flag=True):
            entry = bytes((P.TILE_MODE_COPY,)) + dx.to_bytes(2, "little", signed=True) + dy.to_bytes(2, "little",
                                                                                                    signed=True)
            enc = codec.FrameEncoder(compression=P.COMP_NONE, tile_size=16)
            return enc.pack([(0, entry)], P.FMT_HYBRID, W, H, session_id=7, seq=2, base_seq=1, keyframe=False,
                            ref=ref_flag)

        ok = codec.apply_container(base.copy(), codec.parse_container(container(16, 32)))
        self.assertTrue(np.array_equal(ok[:16, :16], base[32:48, 16:32]))
        with self.assertRaisesRegex(P.ProtocolError, "outside the frame"):
            codec.apply_container(base.copy(), codec.parse_container(container(-1, 0)))
        with self.assertRaisesRegex(P.ProtocolError, "without reference"):
            codec.apply_container(base.copy(), codec.parse_container(container(0, 16, ref_flag=False)))

    def test_dimensions_must_be_multiples_of_16(self):
        with self.assertRaises(ValueError):
            hybrid.HybridEncoder(100, 96)
        with self.assertRaises(ValueError):
            codec.quantize(np.zeros((90, 160, 3), np.uint8), P.FMT_HYBRID)

    def test_large_moving_area_goes_half_resolution(self):
        """Video-like motion over the whole frame: complete 2x2 groups become TILE_MODE_DCT2 (a quarter of the decode
        work); the reference decoder still rebuilds the encoder's picture exactly, and a still picture refines to
        the exact source."""
        def video(t):  # every tile changes, nothing a scroll copy could predict
            return np.clip(smooth(0).astype(np.float32) * (0.55 + 0.1 * t), 0, 255).astype(np.uint8)

        ch = Chain()
        ch.push(video(0), budget=4000, force=True)
        modes = set()
        for t in range(1, 5):
            c, info = ch.push(video(t), budget=6000)
            self.assertEqual(info.mode, "dct")
            modes |= tile_modes(c)
            self.assertTrue(np.array_equal(ch.img, ch.enc.recon), t)
        self.assertIn(P.TILE_MODE_DCT2, modes)
        for _ in range(60):
            ch.push(video(4), budget=8000)
        self.assertTrue(np.array_equal(ch.img[..., :3], video(4)))

    def test_small_moving_area_and_disabled_half_res_stay_full_resolution(self):
        for enc_kw, img_t in (({}, None), ({"half_res": False}, 1)):
            ch = Chain()
            ch.enc = hybrid.HybridEncoder(W, H, **enc_kw)
            ch.push(smooth(0), budget=4000, force=True)
            src = smooth(0).copy()
            if img_t is None:
                src[:32, :32] = smooth(9)[:32, :32]  # 4 moving tiles: below the half-resolution threshold
            else:
                src = smooth(img_t)
            c, _ = ch.push(src, budget=1500)
            if c is None:
                continue
            self.assertNotIn(P.TILE_MODE_DCT2, tile_modes(c))
            self.assertTrue(np.array_equal(ch.img, ch.enc.recon))

    def test_half_resolution_tile_must_fit_the_frame(self):
        entry = bytes((P.TILE_MODE_DCT2, 5)) + bytes(768)
        packer = codec.FrameEncoder(tile_size=16)
        last_col = W // 16 - 1  # its 32x32 area would leave the frame
        for idx, ok in ((0, True), (last_col, False), ((H // 16 - 1) * (W // 16), False)):
            c = packer.pack([(idx, entry)], P.FMT_HYBRID, W, H, session_id=1, seq=1, base_seq=0, keyframe=True)
            img = np.zeros((H, W, 4), np.uint8)
            if ok:
                codec.apply_container(img, codec.parse_container(c))
                self.assertTrue(np.all(img[:32, :32, 3] == 255) and np.all(img[32:, :, 3] == 0))
            else:
                with self.assertRaises(P.ProtocolError):
                    codec.apply_container(img, codec.parse_container(c))

    def test_corrupt_hybrid_parts_rejected(self):
        ch = Chain()
        c, _ = ch.push(smooth(0), budget=3000, force=True)
        part = codec.parse_container(c).parts[0]
        raw = bytearray(codec.decompress_part(part))
        raw[2 * part.tile_count] = 7  # unknown tile mode
        bad = codec.Part(P.COMP_NONE, part.fmt, part.flags, part.tile_size, part.part_index, part.part_count,
                         part.width, part.height, part.tile_count, part.session_id, part.seq, part.base_seq,
                         len(raw), bytes(raw))
        with self.assertRaises(P.ProtocolError):
            codec.apply_part(np.zeros((H, W, 4), np.uint8), bad)


if __name__ == "__main__":
    unittest.main()
