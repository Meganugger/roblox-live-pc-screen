"""RLPS frame service: one authenticated long-poll endpoint that serves on-demand delta containers.

``GET /v1/frames?after=<seq>&session=<id>&key=<0|1>&wait=<ms>[&idle=1]`` with ``Authorization: Bearer <token>``.
The body is the base64 text of one RLPS container (``codec.to_body``):

* STOPPED (no parts) while the owner is not sharing — no pixel data exists then. A poll with ``idle=1`` (the poller
  already knows sharing is off) that arrives while sharing is off is held for up to ``wait`` ms and answered as soon as
  sharing starts, so Start shows at once; every other poll learns STOPPED immediately (also when sharing stops while
  the poll is held);
* LIVE + UNCHANGED (no parts) when no newer frame appeared within ``wait`` ms, or when the newer frame looks the same;
* a KEYFRAME when ``key=1``, ``after=0``, ``session`` is not the current session or ``after`` left the ring;
* otherwise a DELTA with exactly the tiles that differ between frame ``after`` and the latest frame.

The service binds to 127.0.0.1 by default; publish it over HTTPS with a tunnel or reverse proxy. It has no other
routes, accepts no request bodies and never exposes files, commands, input control or anything but the shared frames.
"""

from __future__ import annotations

import collections
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import numpy as np

from . import codec
from . import protocol as P

log = logging.getLogger("rlps.server")

MAX_WAIT_MS = 25_000
DEFAULT_WAIT_MS = 10_000
FRAMES_PATH = "/v1/frames"


class TokenBucket:
    """Simple thread-safe token bucket (``rate`` tokens per second, ``burst`` capacity)."""

    def __init__(self, rate: float, burst: int, clock=time.monotonic):
        self.rate, self.burst, self._clock = rate, burst, clock
        self._tokens, self._last = float(burst), clock()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = self._clock()
            self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False


@dataclass
class _Snapshot:
    live: bool
    session_id: int
    seq: int
    fmt: int
    width: int
    height: int


class FrameStore:
    """Thread-safe ring of the most recent quantized frames of the current sharing session.

    The capture loop calls :meth:`publish`; HTTP handlers call :meth:`respond`. Stopping drops every stored frame."""

    def __init__(self, ring_size: int = 8, encoder: codec.FrameEncoder | None = None, cache_size: int = 16):
        if ring_size < 1:
            raise ValueError("ring_size must be >= 1")
        self.ring_size = ring_size
        self._encoder = encoder or codec.FrameEncoder()
        self._enc_lock = threading.Lock()  # FrameEncoder reuses one zstd context (not thread-safe)
        self._cond = threading.Condition()
        self._frames: collections.OrderedDict[int, np.ndarray] = collections.OrderedDict()
        self._cache: collections.OrderedDict[tuple, bytes] = collections.OrderedDict()
        self._cache_size = cache_size
        self.live = False
        self.session_id = 0
        self.seq = 0
        self.fmt = 0
        self.width = self.height = 0
        self.last_poll: float | None = None  # monotonic time of the last authorized poll (viewer indicator)
        self.polls = 0

    # ------------------------------------------------------------------------------------------- producer side

    def start(self) -> int:
        """Begin a new sharing session (new random session id; old deltas become invalid)."""
        with self._cond:
            self._frames.clear()
            self._cache.clear()
            self.session_id = secrets.randbelow(0xFFFFFFFF) + 1
            self.seq = 0
            self.width = self.height = self.fmt = 0
            self.live = True
            self._cond.notify_all()
            return self.session_id

    def stop(self) -> None:
        """Stop sharing immediately: drop all frames and wake every waiting poll (they answer STOPPED)."""
        with self._cond:
            self.live = False
            self._frames.clear()
            self._cache.clear()
            self.seq = 0
            self._cond.notify_all()

    def publish(self, q: np.ndarray, fmt: int) -> bool:
        """Store a quantized frame. Returns False (no new seq) when not live or identical to the latest frame."""
        h, w = q.shape[:2]
        with self._cond:
            if not self.live:
                return False
            if self._frames and (w, h, fmt) != (self.width, self.height, self.fmt):
                self._frames.clear()  # geometry/format change: deltas against older frames are impossible
            elif self._frames and np.array_equal(self._frames[self.seq], q):
                return False
            if self.seq >= 0xFFFFFFFF:  # practically unreachable; restart the session rather than wrap
                self._frames.clear()
                self.session_id = secrets.randbelow(0xFFFFFFFF) + 1
                self.seq = 0
            self.seq += 1
            self.width, self.height, self.fmt = w, h, fmt
            self._frames[self.seq] = q
            while len(self._frames) > self.ring_size:
                self._frames.popitem(last=False)
            self._cond.notify_all()
            return True

    # ------------------------------------------------------------------------------------------- consumer side

    def _snapshot(self) -> _Snapshot:
        return _Snapshot(self.live, self.session_id, self.seq, self.fmt, self.width, self.height)

    def respond(self, after: int, session: int, key: bool, wait_s: float, idle: bool = False) -> bytes:
        """Return the container for one poll, waiting up to ``wait_s`` seconds for a frame newer than ``after``.

        ``idle``: the poller already shows STOPPED; hold the poll while sharing is off instead of answering at once."""
        deadline = time.monotonic() + max(0.0, wait_s)
        with self._cond:
            self.last_poll, self.polls = time.monotonic(), self.polls + 1
            hold_while_stopped = idle and not self.live  # never delays news of a stop: only already-idle pollers
            while True:
                s = self._snapshot()
                if not s.live:
                    remaining = deadline - time.monotonic()
                    if not hold_while_stopped or remaining <= 0:
                        return codec.status_container(P.STATE_STOPPED)
                    self._cond.wait(remaining)
                    continue
                hold_while_stopped = False
                same_session = session == s.session_id
                if s.seq > 0 and (key or not same_session or after != s.seq):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return codec.status_container(P.STATE_LIVE, session_id=s.session_id, seq=s.seq, width=s.width,
                                                  height=s.height, fmt=s.fmt, tile_size=self._encoder.tile_size)
                self._cond.wait(remaining)
            cur = self._frames[s.seq]
            base = self._frames.get(after) if (same_session and not key and 0 < after < s.seq) else None
            cache_key = (s.session_id, s.seq, after if base is not None else 0)
            hit = self._cache.get(cache_key)
            if hit is not None:
                self._cache.move_to_end(cache_key)
                return hit
        # Encode outside the condition lock (frames are immutable once published).
        with self._enc_lock:
            if base is None:
                data = self._encoder.encode(cur, s.fmt, session_id=s.session_id, seq=s.seq)
            else:
                data = self._encoder.encode(cur, s.fmt, session_id=s.session_id, seq=s.seq, base_seq=after,
                                            prev=base)
                if data is None:  # frame `after` looks identical to the latest one: just advance the base
                    data = codec.status_container(P.STATE_LIVE, session_id=s.session_id, seq=s.seq, width=s.width,
                                                  height=s.height, fmt=s.fmt, tile_size=self._encoder.tile_size)
        with self._cond:
            if self.live and self.session_id == s.session_id:
                self._cache[cache_key] = data
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return data


class FrameService:
    """HTTP front end for a :class:`FrameStore` (stdlib ``ThreadingHTTPServer``)."""

    def __init__(self, store: FrameStore, token: str, host: str = "127.0.0.1", port: int = 8787, *,
                 max_concurrent: int = 8, rate: float = 20.0, burst: int = 40, fail_rate: float = 0.5,
                 fail_burst: int = 10):
        if len(token) < 24:
            raise ValueError("token must be at least 24 characters (use secrets.token_urlsafe(32))")
        self.store = store
        self._token = token.encode("utf-8")
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._ok_bucket = TokenBucket(rate, burst)
        self._fail_bucket = TokenBucket(fail_rate, fail_burst)
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "rlps"
            sys_version = ""
            timeout = 30  # socket timeout: drops idle/slow connections

            def log_message(self, fmt, *args):  # never logs headers (token)
                log.debug("%s %s", self.address_string(), fmt % args)

            def do_GET(self):
                service._handle(self)

            def _not_allowed(self):
                service._send(self, 405, b"method not allowed\n", extra={"Allow": "GET"})

            do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_allowed

        self.responses = 0  # counters for the app's status line (bandwidth measurement)
        self.bytes_sent = 0
        self._count_lock = threading.Lock()
        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self.httpd.server_address[:2]

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="rlps-http", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------------------------------------------ handling

    @staticmethod
    def _send(h: BaseHTTPRequestHandler, status: int, body: bytes, extra: dict | None = None) -> None:
        try:
            h.send_response(status)
            h.send_header("Content-Type", "text/plain; charset=us-ascii")
            h.send_header("Content-Length", str(len(body)))
            h.send_header("Cache-Control", "no-store")
            h.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                h.send_header(k, v)
            h.end_headers()
            h.wfile.write(body)
        except ConnectionError:  # poller/tunnel hung up mid long-poll (broken pipe / reset / aborted): not an error
            h.close_connection = True
            log.debug("client disconnected before the response was written")

    def _authorized(self, h: BaseHTTPRequestHandler) -> bool:
        auth = h.headers.get("Authorization", "")
        scheme, _, presented = auth.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(presented.strip().encode("utf-8"), self._token)

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        if h.headers.get("Content-Length", "0") not in ("", "0") or h.headers.get("Transfer-Encoding"):
            h.close_connection = True
            return self._send(h, 400, b"request body not allowed\n")
        url = urlsplit(h.path)
        if url.path != FRAMES_PATH:
            return self._send(h, 404, b"not found\n")
        if not self._authorized(h):
            if not self._fail_bucket.take():
                return self._send(h, 429, b"too many failed requests\n", {"Retry-After": "5"})
            return self._send(h, 401, b"unauthorized\n", {"WWW-Authenticate": "Bearer"})
        if not self._ok_bucket.take():
            return self._send(h, 429, b"rate limited\n", {"Retry-After": "1"})
        try:
            after, session, key, wait_ms, idle = parse_query(url.query)
        except ValueError as exc:
            return self._send(h, 400, f"bad request: {exc}\n".encode("ascii", "replace"))
        if not self._slots.acquire(blocking=False):
            return self._send(h, 503, b"too many concurrent polls\n", {"Retry-After": "1"})
        try:
            container = self.store.respond(after, session, key, wait_ms / 1000.0, idle)
        finally:
            self._slots.release()
        body = codec.to_body(container)
        self._send(h, 200, body)
        with self._count_lock:
            self.responses += 1
            self.bytes_sent += len(body)


def parse_query(query: str) -> tuple[int, int, bool, int, bool]:
    """Strictly parse ``after``, ``session``, ``key``, ``wait``, ``idle``. Raises ValueError on anything unexpected."""
    allowed = {"after", "session", "key", "wait", "idle"}
    values: dict[str, str] = {}
    for name, value in parse_qsl(query, keep_blank_values=True, strict_parsing=bool(query), max_num_fields=8):
        if name not in allowed or name in values:
            raise ValueError(f"unexpected or repeated parameter {name!r}")
        values[name] = value

    def uint(name: str, default: int, hi: int) -> int:
        raw = values.get(name)
        if raw is None:
            return default
        if not raw.isdigit() or len(raw) > 10:
            raise ValueError(f"{name} must be a non-negative integer")
        v = int(raw)
        if v > hi:
            raise ValueError(f"{name} out of range")
        return v

    after = uint("after", 0, 0xFFFFFFFF)
    session = uint("session", 0, 0xFFFFFFFF)
    key = uint("key", 0, 1) == 1
    wait = uint("wait", DEFAULT_WAIT_MS, MAX_WAIT_MS)
    idle = uint("idle", 0, 1) == 1
    return after, session, key, wait, idle
