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

    def test_dimensions_must_be_multiples_of_16(self):
        with self.assertRaises(ValueError):
            hybrid.HybridEncoder(100, 96)
        with self.assertRaises(ValueError):
            codec.quantize(np.zeros((90, 160, 3), np.uint8), P.FMT_HYBRID)

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
