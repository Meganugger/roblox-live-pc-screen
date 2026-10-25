"""Capture tests with a fake mss backend (no real screen in the agent sandbox): python -m unittest discover -s tests -t ."""

import unittest
from types import SimpleNamespace

import numpy as np

from rlps import capture as C


class FakeSct:
    """Minimal stand-in for an mss instance: ``monitors``, ``grab(dict)``, ``close()``."""

    def __init__(self, world, monitors):
        self.world, self.monitors, self.closed = world, monitors, False

    def grab(self, geom):
        self.world.grabs.append(dict(geom))
        if self.world.fail_next > 0:
            self.world.fail_next -= 1
            raise OSError("desktop switched")
        w, h = geom["width"], geom["height"]
        px = np.zeros((h, w, 4), np.uint8)
        px[..., 2] = 200  # BGRA: red channel
        px[..., 1] = 100
        px[..., 0] = 50
        return SimpleNamespace(size=(w, h), raw=bytearray(px.tobytes()))

    def close(self):
        self.closed = True


class FakeWorld:
    def __init__(self, monitors):
        self.monitors, self.grabs, self.fail_next, self.instances = monitors, [], 0, []

    def factory(self):
        sct = FakeSct(self, [dict(m) for m in self.monitors])
        self.instances.append(sct)
        return sct


ALL = {"left": 0, "top": 0, "width": 3200, "height": 1080}
PRIMARY = {"left": 0, "top": 0, "width": 1920, "height": 1080}
SECOND = {"left": 1920, "top": 0, "width": 1280, "height": 1024}


class ResizeTests(unittest.TestCase):
    def test_fit_size(self):
        self.assertEqual(C.fit_size(1920, 1080, 480, 270), (480, 270))
        self.assertEqual(C.fit_size(1920, 1200, 480, 270), (432, 270))
        self.assertEqual(C.fit_size(100, 50, 480, 270), (100, 50))  # never upscales
        self.assertEqual(C.fit_size(5000, 100, 4000, 4000), (1024, 20))  # EditableImage limit
        with self.assertRaises(ValueError):
            C.fit_size(0, 10, 10, 10)

    def test_box_reduction_is_block_mean(self):
        img = np.random.default_rng(1).integers(0, 256, (8, 12, 3), dtype=np.uint8)
        out = C.resize(img, 3, 2)
        expect = img.reshape(2, 4, 3, 4, 3).mean(axis=(1, 3))
        self.assertTrue(np.array_equal(out, np.floor(expect + 0.5).astype(np.uint8)))

    def test_non_integer_factor_and_solid_preserved(self):
        img = np.full((768, 1366, 3), 77, np.uint8)
        out = C.resize(img, 480, 270)
        self.assertEqual(out.shape, (270, 480, 3))
        self.assertTrue((out == 77).all())

    def test_bgra_to_rgb_order_and_contiguity(self):
        bgra = np.zeros((1080, 1920, 4), np.uint8)
        bgra[..., 0], bgra[..., 1], bgra[..., 2] = 10, 20, 30
        rgb = C.bgra_to_rgb(bgra, 480, 270)
        self.assertEqual(rgb.shape, (270, 480, 3))
        self.assertTrue(rgb.flags["C_CONTIGUOUS"])
        self.assertEqual(rgb[0, 0].tolist(), [30, 20, 10])
        with self.assertRaises(ValueError):
            C.bgra_to_rgb(np.zeros((4, 4, 3), np.uint8), 4, 4)

    def test_region_parse(self):
        self.assertEqual(C.Region.parse("10,20,300,200"), C.Region(10, 20, 300, 200))
        for bad in ("1,2,3", "a,b,c,d", "0,0,0,10"):
            with self.assertRaises(ValueError):
                C.Region.parse(bad)


class MssSourceTests(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld([ALL, PRIMARY, SECOND])
        self.now = 0.0

    def source(self, **kw):
        return C.MssSource(factory=self.world.factory, clock=lambda: self.now, **kw)

    def test_primary_monitor_default(self):
        src = self.source()
        px = src.grab_bgra()
        self.assertEqual(px.shape, (1080, 1920, 4))
        self.assertEqual(self.world.grabs[-1], PRIMARY)
        self.assertEqual(C.bgra_to_rgb(px, 480, 270)[0, 0].tolist(), [200, 100, 50])

    def test_second_monitor_and_region(self):
        self.source(monitor=2).grab_bgra()
        self.assertEqual(self.world.grabs[-1], SECOND)
        self.source(region=C.Region(5, 6, 70, 80)).grab_bgra()
        self.assertEqual(self.world.grabs[-1], {"left": 5, "top": 6, "width": 70, "height": 80})

    def test_missing_monitor(self):
        with self.assertRaises(C.CaptureError):
            self.source(monitor=3).grab_bgra()
        self.assertTrue(self.world.instances[-1].closed)

    def test_grab_error_then_recovery(self):
        src = self.source()
        src.grab_bgra()
        self.world.fail_next = 1
        with self.assertRaises(C.CaptureError):
            src.grab_bgra()
        self.assertTrue(self.world.instances[-1].closed)
        self.assertEqual(src.grab_bgra().shape, (1080, 1920, 4))  # reopened
        self.assertEqual(len(self.world.instances), 2)

    def test_resolution_change_picked_up_after_refresh(self):
        src = self.source(refresh_s=3.0)
        src.grab_bgra()
        self.world.monitors[1] = {"left": 0, "top": 0, "width": 1280, "height": 720}
        self.now = 1.0
        self.assertEqual(src.grab_bgra().shape, (1080, 1920, 4))  # cached geometry until refresh
        self.now = 3.5
        self.assertEqual(src.grab_bgra().shape, (720, 1280, 4))
        self.assertTrue(self.world.instances[0].closed)

    def test_close_is_idempotent(self):
        src = self.source()
        src.grab_bgra()
        src.close()
        src.close()
        self.assertTrue(self.world.instances[0].closed)

    def test_list_monitors(self):
        self.assertEqual(C.list_monitors(self.world.factory), [ALL, PRIMARY, SECOND])


if __name__ == "__main__":
    unittest.main()
