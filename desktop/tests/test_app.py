"""Sharing controller / capture loop / config tests. The screen source is a test double (no display in the agent
sandbox); real Windows capture is verified by the owner (KNOWN_ISSUES KI-0001)."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from rlps import app, capture, codec, server
from rlps import protocol as P
from tests.test_server import TOKEN, Client


class FakeSource:
    """Yields BGRA frames whose top-left block changes colour on every grab; can fail the first N grabs."""

    def __init__(self, w=320, h=180, fail_first=0):
        self.w, self.h, self.fail_first = w, h, fail_first
        self.grabs, self.closed, self.lock = 0, False, threading.Lock()

    def frame(self, n):
        px = np.zeros((self.h, self.w, 4), np.uint8)
        px[..., 0], px[..., 1], px[..., 2] = 40, 80, 120
        px[:16, :16, 2] = (n * 37) % 256
        return px

    def grab_bgra(self):
        with self.lock:
            self.grabs += 1
            n = self.grabs
        if n <= self.fail_first:
            raise capture.CaptureError("desktop switched")
        return self.frame(n)

    def close(self):
        self.closed = True


def wait_for(pred, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.01)
    return False


FAST = app.Profile("test", 320, 180, P.FMT_RGB565, 50.0)


class ProfileTests(unittest.TestCase):
    def test_profiles_valid(self):
        for p in app.PROFILES.values():
            self.assertIn(p.fmt, P.BYTES_PER_PIXEL)
            self.assertTrue(1 <= p.max_w <= P.MAX_DIM and 1 <= p.max_h <= P.MAX_DIM and 0 < p.fps <= 10)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.store = server.FrameStore()
        self.sources = []

        def factory():
            src = FakeSource()
            self.sources.append(src)
            return src

        self.ctl = app.SharingController(self.store, factory, FAST)

    def tearDown(self):
        self.ctl.stop()

    def test_nothing_captured_until_started(self):
        time.sleep(0.1)
        self.assertEqual(self.sources, [])
        self.assertFalse(self.store.live)
        self.assertFalse(self.ctl.active)

    def test_start_publishes_and_stop_cleans_up(self):
        sid = self.ctl.start()
        self.assertEqual(self.ctl.start(), sid)  # idempotent
        self.assertTrue(wait_for(lambda: self.store.seq >= 3))
        self.ctl.stop()
        src = self.sources[0]
        self.assertTrue(src.closed)
        self.assertFalse(self.store.live)
        self.assertEqual(len(self.store._frames), 0)
        grabs = src.grabs
        time.sleep(0.15)
        self.assertEqual(src.grabs, grabs)  # no capture after stop
        self.assertEqual(self.ctl.stats.snapshot()["state"], "stopped")
        self.ctl.stop()  # idempotent

    def test_restart_gives_new_session_and_source(self):
        sid1 = self.ctl.start()
        self.assertTrue(wait_for(lambda: self.store.seq >= 1))
        self.ctl.stop()
        sid2 = self.ctl.start()
        self.assertNotEqual(sid1, sid2)
        self.assertEqual(len(self.sources), 2)

    def test_interruption_recovers(self):
        self.ctl.source_factory = lambda: self.sources.append(FakeSource(fail_first=2)) or self.sources[-1]
        self.ctl.start()
        self.assertTrue(wait_for(lambda: self.store.seq >= 1, timeout=8))
        s = self.ctl.stats.snapshot()
        self.assertEqual(s["errors"], 2)
        self.assertEqual(s["last_error"], "desktop switched")

    def test_profile_change_restarts_when_active(self):
        self.ctl.start()
        self.assertTrue(wait_for(lambda: self.store.seq >= 1))
        self.ctl.set_profile(app.Profile("t2", 160, 90, P.FMT_RGB888, 50.0))
        self.assertTrue(self.ctl.active)
        self.assertTrue(wait_for(lambda: (self.store.width, self.store.fmt) == (160, P.FMT_RGB888)))


class EndToEndServiceTests(unittest.TestCase):
    """Fake screen → capture loop → frame store → real HTTP service → reference decoder."""

    def test_pixels_reach_the_poller_and_stop_is_reported(self):
        store = server.FrameStore()
        svc = server.FrameService(store, TOKEN, port=0, rate=1000, burst=1000)
        svc.start()
        src = FakeSource()
        ctl = app.SharingController(store, lambda: src, app.Profile("slow", 320, 180, P.FMT_RGB565, 2.0))
        try:
            c = Client(svc.address[1])
            self.assertEqual(c.poll().state, P.STATE_STOPPED)
            sid = ctl.start()
            self.assertTrue(wait_for(lambda: store.seq >= 1))
            k = c.poll(after=0, session=sid, wait=0)
            self.assertTrue(k.keyframe)
            img = codec.apply_container(None, k)
            with store._cond:
                latest = store._frames[k.seq]
            self.assertTrue(np.array_equal(img, codec.expand_to_rgba(latest, P.FMT_RGB565)))
            d = c.poll(after=k.seq, session=sid, wait=3000)  # next capture changes the top-left tile only
            self.assertFalse(d.keyframe)
            self.assertEqual(sum(p.tile_count for p in d.parts), 1)
            img = codec.apply_container(img, d)
            ctl.stop()
            self.assertEqual(c.poll(after=d.seq, session=sid).state, P.STATE_STOPPED)
            self.assertGreater(svc.bytes_sent, 0)
            self.assertIn("roblox server: last poll", ctl.status_text(svc))
        finally:
            ctl.stop()
            svc.close()


class ConfigTests(unittest.TestCase):
    def test_create_reuse_rotate(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "config.json"
            cfg, created = app.load_or_create_config(path)
            self.assertTrue(created)
            self.assertGreaterEqual(len(cfg["token"]), 24)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            again, created2 = app.load_or_create_config(path)
            self.assertFalse(created2)
            self.assertEqual(again["token"], cfg["token"])
            rotated, created3 = app.load_or_create_config(path, rotate=True)
            self.assertTrue(created3)
            self.assertNotEqual(rotated["token"], cfg["token"])

    def test_rejects_short_token(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text(json.dumps({"token": "short"}))
            with self.assertRaises(ValueError):
                app.load_or_create_config(path)


class ConsoleTests(unittest.TestCase):
    def test_console_start_status_stop_quit(self):
        import builtins
        import contextlib
        import io

        store = server.FrameStore()
        src = FakeSource()
        ctl = app.SharingController(store, lambda: src, FAST)
        cmds = iter(["start", "status", "stop", "quit"])
        orig = builtins.input
        builtins.input = lambda _prompt="": next(cmds)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                app.run_console(ctl, None)
        finally:
            builtins.input = orig
            ctl.stop()
        self.assertIn("SHARING YOUR SCREEN", out.getvalue())
        self.assertIn("sharing stopped", out.getvalue())
        self.assertFalse(store.live)


if __name__ == "__main__":
    unittest.main()
