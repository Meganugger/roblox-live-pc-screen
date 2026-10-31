"""Frame service tests (real HTTP on 127.0.0.1, ephemeral port): python -m unittest discover -s tests -t ."""

import os
import threading
import time
import unittest
import urllib.error
import urllib.request

import numpy as np

from rlps import codec, server
from rlps import protocol as P

TOKEN = "t" * 32


def frame(w=64, h=48, value=0x1234):
    return np.full((h, w), value, np.uint16)


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def get(self, path="/v1/frames?wait=0", token=TOKEN, method="GET", headers=None):
        req = urllib.request.Request(self.base + path, method=method)
        if token is not None:
            req.add_header("Authorization", f"Bearer {token}")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def poll(self, after=0, session=0, key=0, wait=0, idle=0, extra=""):
        """-> list of parsed containers of the response bundle."""
        status, body = self.get(f"/v1/frames?after={after}&session={session}&key={key}&wait={wait}&idle={idle}{extra}")
        assert status == 200, (status, body)
        return [codec.parse_container(c) for _, c in server.parse_bundle(codec.from_body(body))]

    def last(self, **kw):
        return self.poll(**kw)[-1]


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.store = server.FrameStore()
        self.svc = server.FrameService(self.store, TOKEN, port=0, rate=1000, burst=1000)
        self.svc.start()
        self.c = Client(self.svc.address[1])

    def tearDown(self):
        self.svc.close()


class AuthAndRoutingTests(ServiceTestCase):
    def test_auth_required(self):
        self.assertEqual(self.c.get(token=None)[0], 401)
        self.assertEqual(self.c.get(token="x" * 32)[0], 401)
        self.assertEqual(self.c.get(token=TOKEN + "x")[0], 401)
        self.assertEqual(self.c.get()[0], 200)

    def test_routes_methods_and_params(self):
        self.assertEqual(self.c.get("/")[0], 404)
        self.assertEqual(self.c.get("/v1/frames/../x")[0], 404)
        self.assertEqual(self.c.get(method="POST")[0], 405)
        self.assertEqual(self.c.get(method="DELETE")[0], 405)
        req = urllib.request.Request(self.c.base + "/v1/frames?wait=0", data=b"hello", method="GET",
                                     headers={"Authorization": f"Bearer {TOKEN}"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 400)  # request bodies are never accepted
        for q in ("after=-1", "after=abc", "after=4294967296", "key=2", "wait=999999", "foo=1", "after=1&after=2"):
            with self.subTest(q=q):
                self.assertEqual(self.c.get("/v1/frames?" + q)[0], 400)

    def test_failed_auth_rate_limited(self):
        svc = server.FrameService(server.FrameStore(), TOKEN, port=0, fail_rate=0.001, fail_burst=3)
        svc.start()
        try:
            c = Client(svc.address[1])
            codes = [c.get(token="bad" * 10)[0] for _ in range(5)]
            self.assertEqual(codes, [401, 401, 401, 429, 429])
        finally:
            svc.close()

    def test_request_rate_limited(self):
        svc = server.FrameService(server.FrameStore(), TOKEN, port=0, rate=0.001, burst=2)
        svc.start()
        try:
            c = Client(svc.address[1])
            self.assertEqual([c.get()[0] for _ in range(3)], [200, 200, 429])
        finally:
            svc.close()

    def test_poller_hanging_up_mid_long_poll_is_not_an_error(self):
        import socket
        errors = []
        self.svc.httpd.handle_error = lambda request, address: errors.append(address)
        self.store.start()
        sock = socket.create_connection(self.svc.address)
        sock.sendall(f"GET /v1/frames?wait=300 HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer {TOKEN}\r\n\r\n"
                     .encode())
        import struct
        linger = struct.pack("HH", 1, 0) if os.name == "nt" else struct.pack("ii", 1, 0)  # on, 0 s: close sends RST
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
        sock.close()  # RST: the response write after the long-poll fails with a broken pipe / reset
        time.sleep(0.6)
        self.assertEqual(errors, [])
        self.assertEqual(self.c.get()[0], 200)  # service still healthy

    def test_short_token_refused(self):
        with self.assertRaises(ValueError):
            server.FrameService(server.FrameStore(), "short", port=0)


class FrameFlowTests(ServiceTestCase):
    def test_stopped_when_not_sharing(self):
        [c] = self.c.poll()
        self.assertEqual(c.state, P.STATE_STOPPED)
        self.assertEqual(c.parts, [])
        t0 = time.monotonic()
        self.assertEqual(self.c.last(wait=3000).state, P.STATE_STOPPED)  # not idle: STOPPED at once
        self.assertLess(time.monotonic() - t0, 1.0)
        t0 = time.monotonic()
        self.assertEqual(self.c.last(wait=300, idle=1).state, P.STATE_STOPPED)  # idle: held for the wait
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)

    def test_poll_while_stopped_is_answered_when_sharing_starts(self):
        result = {}

        def poll():
            result["c"] = self.c.poll(wait=5000, idle=1)
            result["t"] = time.monotonic()

        t = threading.Thread(target=poll)
        t.start()
        time.sleep(0.2)
        self.store.start()
        t_start = time.monotonic()
        self.store.publish(frame(), P.FMT_RGB565)
        t.join(5)
        [c] = result["c"]
        self.assertEqual((c.state, c.keyframe, c.seq), (P.STATE_LIVE, True, 1))
        self.assertLess(result["t"] - t_start, 1.0)  # answered right away, not after the 5 s wait

    def test_keyframe_delta_unchanged_cycle(self):
        sid = self.store.start()
        live = self.c.last(wait=0)  # live, no frame yet
        self.assertEqual((live.state, live.seq), (P.STATE_LIVE, 0))
        self.assertTrue(live.flags & P.CFLAG_UNCHANGED)
        a = frame()
        self.assertTrue(self.store.publish(a, P.FMT_RGB565))
        [k] = self.c.poll(after=0, session=sid)
        self.assertTrue(k.keyframe)
        self.assertEqual((k.session_id, k.seq), (sid, 1))
        img = codec.apply_container(None, k)
        b = a.copy()
        b[0:5, 0:5] = 0xFFFF
        self.assertTrue(self.store.publish(b, P.FMT_RGB565))
        [d] = self.c.poll(after=1, session=sid)
        self.assertFalse(d.keyframe)
        self.assertEqual((d.seq, d.base_seq, sum(p.tile_count for p in d.parts)), (2, 1, 1))
        img = codec.apply_container(img, d)
        self.assertTrue(np.array_equal(img, codec.expand_to_rgba(b, P.FMT_RGB565)))
        u = self.c.last(after=2, session=sid, wait=50)
        self.assertTrue(u.flags & P.CFLAG_UNCHANGED)
        self.assertEqual(u.seq, 2)

    def test_several_frames_per_poll_with_capture_offsets(self):
        sid = self.store.start()
        self.store.publish(frame(value=1), P.FMT_RGB565)
        for v in (2, 3):
            self.store.publish(frame(value=v), P.FMT_RGB565)
        got = self.c.poll(after=1, session=sid, wait=0)
        self.assertEqual([c.seq for c in got], [2, 3])  # everything newer than `after`, oldest first
        # batch window: frames published while the poll is held are collected into the same response
        def producer():
            for v in (4, 5, 6):
                time.sleep(0.08)
                self.store.publish(frame(value=v), P.FMT_RGB565)
        threading.Thread(target=producer).start()
        status, body = self.c.get(f"/v1/frames?after=3&session={sid}&wait=3000&batch=400")
        entries = server.parse_bundle(codec.from_body(body))
        self.assertEqual([codec.parse_container(c).seq for _, c in entries], [4, 5, 6])
        offsets = [t for t, _ in entries]
        self.assertEqual(offsets[0], 0)
        self.assertTrue(offsets[0] < offsets[1] < offsets[2])

    def test_max_bytes_limits_a_response(self):
        sid = self.store.start()
        for v in range(1, 6):
            self.store.publish(np.random.default_rng(v).integers(0, 65535, (48, 64), dtype=np.uint16), P.FMT_RGB565)
        got = self.c.poll(after=0, session=sid, wait=0, extra="&max=65536")
        total = sum(len(c.parts) for c in got)
        self.assertGreaterEqual(len(got), 1)
        self.assertLessEqual(len(got), 5)
        self.assertGreater(total, 0)

    def test_identical_frame_not_republished(self):
        self.store.start()
        self.assertTrue(self.store.publish(frame(), P.FMT_RGB565))
        self.assertFalse(self.store.publish(frame(), P.FMT_RGB565))
        self.assertEqual(self.store.seq, 1)

    def test_long_poll_wakes_on_publish(self):
        sid = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        threading.Timer(0.3, lambda: self.store.publish(frame(value=7), P.FMT_RGB565)).start()
        t0 = time.monotonic()
        d = self.c.last(after=1, session=sid, wait=5000)
        self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(d.seq, 2)

    def test_stop_wakes_waiters_and_drops_frames(self):
        sid = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        threading.Timer(0.3, self.store.stop).start()
        c = self.c.last(after=1, session=sid, wait=5000)
        self.assertEqual(c.state, P.STATE_STOPPED)
        self.assertEqual(len(self.store._ring), 0)
        self.assertIsNone(self.store.latest)
        self.assertFalse(self.store.publish(frame(), P.FMT_RGB565))

    def test_unknown_chain_gets_the_newest_keyframe_onwards(self):
        sid = self.store.start()
        for v in range(1, 4):
            self.store.publish(frame(value=v), P.FMT_RGB565)
        for args in (dict(after=2, session=sid + 1), dict(after=0, session=sid), dict(after=2, session=sid, key=1)):
            got = self.c.poll(wait=0, **args)
            self.assertEqual([c.seq for c in got], [1, 2, 3], args)
            self.assertTrue(got[0].keyframe)
        self.assertEqual([c.seq for c in self.c.poll(after=2, session=sid, wait=0)], [3])

    def test_fresh_continues_the_chain_and_forces_one_new_keyframe(self):
        sid = self.store.start()
        for v in range(1, 4):
            self.store.publish(frame(value=v), P.FMT_RGB565)
        got = self.c.poll(after=2, session=sid, wait=0, extra="&fresh=1")
        self.assertEqual([c.seq for c in got], [3])  # no rewind to the old keyframe (key=1 would replay 1, 2, 3)
        self.store.publish(frame(value=4), P.FMT_RGB565)
        [k] = self.c.poll(after=3, session=sid, wait=0, extra="&fresh=1")
        self.assertTrue(k.keyframe)
        self.assertEqual(k.seq, 4)
        # the chain already holds a keyframe newer than `after`: another fresh=1 must not force a second one
        self.c.poll(after=3, session=sid, wait=0, extra="&fresh=1")
        self.store.publish(frame(value=5), P.FMT_RGB565)
        [d] = self.c.poll(after=4, session=sid, wait=0)
        self.assertFalse(d.keyframe)
        self.assertEqual((d.seq, d.base_seq), (5, 4))
        # a poller of another session gets nothing forced (its chain is unknown: key semantics apply)
        self.c.poll(after=5, session=sid + 1, wait=0, extra="&fresh=1")
        self.store.publish(frame(value=6), P.FMT_RGB565)
        self.assertFalse(self.c.poll(after=5, session=sid, wait=0)[-1].keyframe)

    def test_keyframe_forced_when_the_ring_lost_it(self):
        store = server.FrameStore(ring_records=2)
        svc = server.FrameService(store, TOKEN, port=0, rate=1000, burst=1000)
        svc.start()
        try:
            c = Client(svc.address[1])
            sid = store.start()
            for v in range(1, 5):  # ring keeps seq 3 and 4 (deltas): no keyframe left
                store.publish(frame(value=v), P.FMT_RGB565)
            st = c.last(after=3, session=sid, key=1, wait=100)  # no keyframe yet: "no news" never jumps ahead
            self.assertTrue(st.flags & P.CFLAG_UNCHANGED)
            self.assertLessEqual(st.seq, 3)
            self.assertEqual(c.last(after=0, session=sid, wait=100).seq, 0)
            threading.Timer(0.2, lambda: store.publish(frame(value=9), P.FMT_RGB565)).start()
            got = c.poll(after=0, session=sid, wait=3000)
            self.assertEqual(len(got), 1)
            self.assertTrue(got[0].keyframe)
            self.assertEqual(got[0].seq, 5)
        finally:
            svc.close()

    def test_new_session_after_restart(self):
        sid1 = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        self.store.stop()
        sid2 = self.store.start()
        self.assertNotEqual(sid1, sid2)
        self.store.publish(frame(value=9), P.FMT_RGB565)
        c = self.c.last(after=1, session=sid1)
        self.assertTrue(c.keyframe)
        self.assertEqual(c.session_id, sid2)

    def test_resolution_change_gives_keyframe(self):
        sid = self.store.start()
        self.store.publish(frame(64, 48), P.FMT_RGB565)
        self.store.publish(frame(80, 48), P.FMT_RGB565)
        c = self.c.last(after=1, session=sid)
        self.assertTrue(c.keyframe)
        self.assertEqual((c.width, c.height), (80, 48))

    def test_reported_rate_sets_the_budget_and_skips_frames(self):
        sid = self.store.start()
        self.c.poll(wait=0, extra="&rate=2000")
        self.assertEqual(self.store.current_rate(), 2000)
        rng = np.random.default_rng(1)
        self.assertTrue(self.store.publish(rng.integers(0, 65535, (48, 64), dtype=np.uint16), P.FMT_RGB565))
        for _ in range(3):  # keyframe spent the budget: noisy deltas are skipped (coalesced) for now
            self.store.publish(rng.integers(0, 65535, (48, 64), dtype=np.uint16), P.FMT_RGB565)
        self.assertGreaterEqual(self.store.status.skipped, 1)
        self.assertEqual(self.store.seq, 1)

    def test_hybrid_chain_reconstructs_the_encoder_picture(self):
        sid = self.store.start()
        rng = np.random.default_rng(3)
        base = np.full((96, 160, 3), 200, np.uint8)
        img = None
        after = 0
        for k in range(4):
            f = base.copy()
            f[16:64, 16 + 8 * k:80 + 8 * k] = rng.integers(0, 255, (48, 64, 3))
            self.store.publish(codec.quantize(f, P.FMT_HYBRID), P.FMT_HYBRID)
            for c in self.c.poll(after=after, session=sid, wait=0):
                img = codec.apply_container(img, c)
                after = c.seq
        self.assertTrue(np.array_equal(img, self.store._hybrid.recon))

    def test_probe_and_raw_bodies(self):
        status, body = self.c.get("/v1/probe")
        self.assertEqual((status, body), (200, server.PROBE_BODY))
        self.assertEqual(self.c.get("/v1/probe?x=1")[0], 400)
        self.assertEqual(self.c.get("/v1/probe", token=None)[0], 401)
        sid = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        status, body = self.c.get(f"/v1/frames?after=0&session={sid}&wait=0&enc=1")
        [(t, c)] = server.parse_bundle(body)
        self.assertTrue(codec.parse_container(c).keyframe)

    def test_concurrent_pollers_get_identical_bodies(self):
        sid = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        self.store.publish(frame(value=3), P.FMT_RGB565)
        bodies = set()
        def go():
            bodies.add(self.c.get(f"/v1/frames?after=1&session={sid}&wait=0")[1])
        ts = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(bodies), 1)


class BundleTests(unittest.TestCase):
    def test_round_trip_and_rejections(self):
        b = server.bundle([(0, b"abc"), (40, b"de")])
        self.assertEqual(server.parse_bundle(b), [(0, b"abc"), (40, b"de")])
        for bad in (b[:-1], b + b"x", b"XXXX" + b[4:], b[:4] + b"\x09" + b[5:], b[:11]):
            with self.assertRaises(P.ProtocolError):
                server.parse_bundle(bad)
        with self.assertRaises(P.ProtocolError):
            server.parse_bundle(server.bundle([]))


class QueryParserTests(unittest.TestCase):
    def test_defaults_and_values(self):
        self.assertEqual(server.parse_query(""), server.Query())
        q = server.parse_query("after=5&session=7&key=1&wait=0&idle=1&rate=500000&batch=150&max=65536&enc=1&fresh=1")
        self.assertEqual((q.after, q.session, q.key, q.wait_ms, q.idle, q.rate, q.batch_ms, q.max_bytes, q.raw,
                          q.fresh), (5, 7, True, 0, True, 500000, 150, 65536, True, True))
        for bad in ("idle=2", "batch=1001", "max=10", "enc=2", "rate=-1", "foo=1", "after=1&after=2", "fresh=2"):
            with self.assertRaises(ValueError, msg=bad):
                server.parse_query(bad)


if __name__ == "__main__":
    unittest.main()
