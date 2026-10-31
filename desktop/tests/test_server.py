"""Frame service tests (real HTTP on 127.0.0.1, ephemeral port): python -m unittest discover -s tests -t ."""

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

    def get(self, path="/v1/frames", token=TOKEN, method="GET", headers=None):
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

    def poll(self, after=0, session=0, key=0, wait=0):
        status, body = self.get(f"/v1/frames?after={after}&session={session}&key={key}&wait={wait}")
        assert status == 200, (status, body)
        return codec.parse_container(codec.from_body(body))


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.store = server.FrameStore(ring_size=3)
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
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
        sock.close()  # RST: the response write after the long-poll fails with a broken pipe / reset
        time.sleep(0.6)
        self.assertEqual(errors, [])
        self.assertEqual(self.c.get()[0], 200)  # service still healthy

    def test_short_token_refused(self):
        with self.assertRaises(ValueError):
            server.FrameService(server.FrameStore(), "short", port=0)


class FrameFlowTests(ServiceTestCase):
    def test_stopped_when_not_sharing(self):
        c = self.c.poll()
        self.assertEqual(c.state, P.STATE_STOPPED)
        self.assertEqual(c.parts, [])

    def test_keyframe_delta_unchanged_cycle(self):
        sid = self.store.start()
        live = self.c.poll(wait=0)  # live, no frame yet
        self.assertEqual((live.state, live.seq), (P.STATE_LIVE, 0))
        self.assertTrue(live.flags & P.CFLAG_UNCHANGED)
        a = frame()
        self.assertTrue(self.store.publish(a, P.FMT_RGB565))
        k = self.c.poll(after=0, session=sid)
        self.assertTrue(k.keyframe)
        self.assertEqual((k.session_id, k.seq), (sid, 1))
        img = codec.apply_container(None, k)
        b = a.copy()
        b[0:5, 0:5] = 0xFFFF
        self.assertTrue(self.store.publish(b, P.FMT_RGB565))
        d = self.c.poll(after=1, session=sid)
        self.assertFalse(d.keyframe)
        self.assertEqual((d.seq, d.base_seq, sum(p.tile_count for p in d.parts)), (2, 1, 1))
        img = codec.apply_container(img, d)
        self.assertTrue(np.array_equal(img, codec.expand_to_rgba(b, P.FMT_RGB565)))
        u = self.c.poll(after=2, session=sid, wait=50)
        self.assertTrue(u.flags & P.CFLAG_UNCHANGED)
        self.assertEqual(u.seq, 2)

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
        d = self.c.poll(after=1, session=sid, wait=5000)
        self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(d.seq, 2)

    def test_stop_wakes_waiters_and_drops_frames(self):
        sid = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        threading.Timer(0.3, self.store.stop).start()
        c = self.c.poll(after=1, session=sid, wait=5000)
        self.assertEqual(c.state, P.STATE_STOPPED)
        self.assertEqual(len(self.store._frames), 0)
        self.assertFalse(self.store.publish(frame(), P.FMT_RGB565))

    def test_keyframe_on_unknown_session_evicted_base_or_key(self):
        sid = self.store.start()
        for v in range(1, 6):  # ring_size 3 -> seq 1, 2 evicted
            self.store.publish(frame(value=v), P.FMT_RGB565)
        self.assertTrue(self.c.poll(after=4, session=sid + 1).keyframe)
        self.assertTrue(self.c.poll(after=1, session=sid).keyframe)
        self.assertTrue(self.c.poll(after=4, session=sid, key=1).keyframe)
        self.assertFalse(self.c.poll(after=4, session=sid).keyframe)

    def test_new_session_after_restart(self):
        sid1 = self.store.start()
        self.store.publish(frame(), P.FMT_RGB565)
        self.store.stop()
        sid2 = self.store.start()
        self.assertNotEqual(sid1, sid2)
        self.store.publish(frame(value=9), P.FMT_RGB565)
        c = self.c.poll(after=1, session=sid1)
        self.assertTrue(c.keyframe)
        self.assertEqual(c.session_id, sid2)

    def test_resolution_change_gives_keyframe(self):
        sid = self.store.start()
        self.store.publish(frame(64, 48), P.FMT_RGB565)
        self.store.publish(frame(80, 48), P.FMT_RGB565)
        c = self.c.poll(after=1, session=sid)
        self.assertTrue(c.keyframe)
        self.assertEqual((c.width, c.height), (80, 48))

    def test_reverted_change_advances_base_without_parts(self):
        sid = self.store.start()
        self.store.publish(frame(value=1), P.FMT_RGB565)
        self.store.publish(frame(value=2), P.FMT_RGB565)
        self.store.publish(frame(value=1), P.FMT_RGB565)
        c = self.c.poll(after=1, session=sid)
        self.assertTrue(c.flags & P.CFLAG_UNCHANGED)
        self.assertEqual(c.seq, 3)

    def test_concurrent_pollers_share_cached_container(self):
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


class QueryParserTests(unittest.TestCase):
    def test_defaults_and_values(self):
        self.assertEqual(server.parse_query(""), (0, 0, False, server.DEFAULT_WAIT_MS))
        self.assertEqual(server.parse_query("after=5&session=7&key=1&wait=0"), (5, 7, True, 0))


if __name__ == "__main__":
    unittest.main()
