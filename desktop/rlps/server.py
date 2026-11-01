"""RLPS frame service: one authenticated long-poll endpoint serving bundles of encoded frames from one chain.

``GET /v1/frames?after=<seq>&session=<id>&key=<0|1>&fresh=<0|1>&wait=<ms>&idle=<0|1>&rate=<B/s>&batch=<ms>&max=<bytes>&enc=<0|1>``
with ``Authorization: Bearer <token>``. The body is one **bundle** (``protocol.BUNDLE_*``) of containers, oldest
first, as standard base64 text (``enc=0``) or raw bytes (``enc=1``, only after ``GET /v1/probe`` proved that the
poller receives bytes unchanged). See docs/PROTOCOL.md.

Frames are encoded **once, at capture time**, into a chain (keyframe, then deltas against the decoder-side picture)
under a byte-rate budget (``rate`` reported by the Roblox server's congestion control, capped by the app's
``max_rate``). A poll gets every record newer than ``after`` (several frames per request: ``batch`` ms are collected
after the first new frame), or the chain from its latest keyframe when ``after`` is unknown (or ``key=1``), or
STOPPED / UNCHANGED. ``fresh=1`` continues the chain but makes the next captured frame a keyframe (viewers of the
poller need one), unless the chain already has a keyframe newer than ``after``.

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

from . import codec, hybrid
from . import protocol as P

log = logging.getLogger("rlps.server")

MAX_WAIT_MS = 25_000
DEFAULT_WAIT_MS = 10_000
MAX_BATCH_MS = 1_000
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
FRAMES_PATH = "/v1/frames"
PROBE_PATH = "/v1/probe"
PROBE_BODY = bytes(range(256)) * 4  # every byte value, 1 KiB: the poller checks it arrives unchanged
RATE_HOLD_S = 5.0  # a poller's reported rate is honoured this long
KEYFRAME_REPLAY_MAX = 24  # a poller that needs a keyframe gets a fresh one rather than more frames than this
IDLE_ENCODE_S = 10.0  # nobody polled for this long: stop encoding (CPU), next poll gets a fresh keyframe
BURST_S = 0.25  # token bucket depth in seconds of the stream rate (bigger bursts = longer queues on the way)


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
class Record:
    seq: int
    t: float  # capture time (monotonic)
    keyframe: bool
    data: bytes  # one container


@dataclass
class EncodeStatus:
    rate: float = 0.0  # bytes/s budget in force
    frames: int = 0  # records encoded
    skipped: int = 0  # captures not sent (over budget)
    fps_skipped: int = 0  # captures not encoded (viewers' frame-rate cap)
    copied: int = 0  # tiles sent as copies of the previous picture (scrolling)
    bytes: int = 0
    last_mode: str = ""
    last_quality: int = -1
    last_encode_ms: float = 0.0


class FrameStore:
    """The current sharing session's frame chain.

    The capture loop calls :meth:`publish` with each captured frame (quantized to the session format); the frame is
    encoded at once (hybrid DCT/lossless for FMT_HYBRID, lossless deltas otherwise) under the byte budget and appended
    to a bounded ring. HTTP handlers call :meth:`respond`. Stopping drops everything."""

    def __init__(self, ring_bytes: int = 64 * 1024 * 1024, ring_records: int = 1024, max_rate: float = 8e6,
                 start_rate: float = 1e6, encoder: codec.FrameEncoder | None = None, clock=time.monotonic):
        self.ring_bytes, self.ring_records = ring_bytes, ring_records
        self.max_rate, self.start_rate = float(max_rate), float(start_rate)
        self._clock = clock
        self._packer = encoder or codec.FrameEncoder(level=1, max_part_raw_bytes=96 * 1024)
        self._enc_lock = threading.Lock()
        self._cond = threading.Condition()
        self._ring: collections.deque[Record] = collections.deque()
        self._ring_size = 0
        self.live = False
        self.session_id = 0
        self.seq = 0
        self.fmt = 0
        self.width = self.height = 0
        self.last_poll: float | None = None  # monotonic time of the last authorized poll (viewer indicator)
        self.polls = 0
        self.status = EncodeStatus()
        self._hybrid: hybrid.HybridEncoder | None = None
        self._last_sent: np.ndarray | None = None  # lossless formats: the picture clients have
        self._force_key = True
        self._requested_rate: float | None = None
        self._requested_at = -1e9
        self._requested_fps: float | None = None
        self._last_record_t = -1e9
        self._tokens: float | None = None  # None = full bucket at the next capture (start of a session)
        self._tokens_at = clock()
        self.latest: np.ndarray | None = None  # newest *captured* frame (quantized)

    def picture(self) -> tuple[int, np.ndarray | None]:
        """(seq, RGBA picture every up-to-date client shows after frame seq) — tests and diagnostics."""
        with self._enc_lock, self._cond:
            if self.fmt == P.FMT_HYBRID and self._hybrid is not None and self._hybrid.recon is not None:
                return self.seq, self._hybrid.recon.copy()
            if self._last_sent is not None:
                return self.seq, codec.expand_to_rgba(self._last_sent, self.fmt)
            return self.seq, None

    # ------------------------------------------------------------------------------------------- producer side

    def start(self) -> int:
        """Begin a new sharing session (new random session id; old chains become invalid)."""
        with self._cond:
            self._reset_chain()
            self.session_id = secrets.randbelow(0xFFFFFFFF) + 1
            self.live = True
            self._tokens = None
            self._cond.notify_all()
            return self.session_id

    def stop(self) -> None:
        """Stop sharing immediately: drop every frame and wake every waiting poll (they answer STOPPED)."""
        with self._cond:
            self.live = False
            self._reset_chain()
            self._cond.notify_all()

    def _reset_chain(self) -> None:
        self._ring.clear()
        self._ring_size = 0
        self.seq = 0
        self.width = self.height = self.fmt = 0
        self._hybrid = None
        self._last_sent = None
        self.latest = None
        self._force_key = True

    def current_fps(self) -> float | None:
        now = self._clock()
        if self._requested_fps is not None and now - self._requested_at <= RATE_HOLD_S:
            return self._requested_fps
        return None

    def current_rate(self) -> float:
        now = self._clock()
        if self._requested_rate is not None and now - self._requested_at <= RATE_HOLD_S:
            return min(self.max_rate, self._requested_rate)
        return min(self.max_rate, self.start_rate)

    def publish(self, q: np.ndarray, fmt: int) -> bool:
        """Encode and append a captured frame. Returns True when a new record was added to the chain."""
        h, w = q.shape[:2]
        with self._cond:
            if not self.live:
                return False
            self.latest = q
            if (w, h, fmt) != (self.width, self.height, self.fmt):  # geometry/format change: new chain
                self._hybrid = None
                self._last_sent = None
                self._force_key = True
                self.width, self.height, self.fmt = w, h, fmt
            if self.last_poll is not None and self._clock() - self.last_poll > IDLE_ENCODE_S:
                self._force_key = True  # nobody watches: save the CPU, resume with a keyframe
                return False
            session, seq, force_key = self.session_id, self.seq + 1, self._force_key
            fps = self.current_fps()
            if fps and not force_key and self._clock() - self._last_record_t < 1.0 / fps - 0.002:
                self.status.fps_skipped += 1  # viewers cannot decode more frames/s: the next record covers this one
                return False
            rate = self.current_rate()
            now = self._clock()
            cap = max(rate * BURST_S, 4096)  # small bursts: a burst sits in the players' network queues
            # (a full bucket at the start: Windows' monotonic clock ticks every ~16 ms, so dt can be 0)
            self._tokens = cap if self._tokens is None else min(cap, self._tokens + (now - self._tokens_at) * rate)
            self._tokens_at = now
            budget = self._tokens
        t0 = time.perf_counter()
        with self._enc_lock:
            data, keyframe, mode, quality = self._encode(q, fmt, session, seq, force_key, budget)
        with self._cond:
            st = self.status
            st.rate, st.last_encode_ms = rate, (time.perf_counter() - t0) * 1000
            if not self.live or self.session_id != session:
                return False
            if data is None:
                if mode == "skipped":
                    st.skipped += 1
                return False
            if seq >= 0xFFFFFFFF:  # practically unreachable; restart the chain rather than wrap
                self.session_id = secrets.randbelow(0xFFFFFFFF) + 1
                self._reset_chain()
                return False
            self.seq = seq
            if keyframe:
                self._force_key = False  # only a keyframe answers a keyframe request (one may arrive mid-encode)
            self._tokens -= len(data)
            self._last_record_t = self._clock()
            self._ring.append(Record(seq, self._last_record_t, keyframe, data))
            self._ring_size += len(data)
            while len(self._ring) > 1 and (self._ring_size > self.ring_bytes or len(self._ring) > self.ring_records):
                self._ring_size -= len(self._ring.popleft().data)
            st.frames += 1
            st.bytes += len(data)
            st.copied += self._last_copied
            st.last_mode, st.last_quality = mode, quality
            self._cond.notify_all()
            return True

    def _encode(self, q, fmt, session, seq, force_key, budget):
        """-> (container | None, keyframe, mode, quality). Runs outside the condition lock."""
        self._last_copied = 0
        base = seq - 1
        if fmt == P.FMT_HYBRID:
            if self._hybrid is None or force_key:
                if self._hybrid is None or (self._hybrid.w, self._hybrid.h) != (q.shape[1], q.shape[0]):
                    self._hybrid = hybrid.HybridEncoder(q.shape[1], q.shape[0],
                                                        packer=codec.FrameEncoder(level=1, tile_size=16,
                                                                                  max_part_raw_bytes=96 * 1024))
                self._hybrid.reset()
            data, info = self._hybrid.encode(q, session_id=session, seq=seq, base_seq=base, budget=budget,
                                             force_keyframe=force_key)
            self._last_copied = info.copied_tiles if data is not None else 0
            mode = "skipped" if info.skipped else info.mode
            return data, info.keyframe, mode, info.quality
        key = force_key or self._last_sent is None
        if not key and budget <= 0:
            return None, False, "skipped", -1  # over budget: coalesce into the next delta
        data = self._packer.encode(q, fmt, session_id=session, seq=seq, base_seq=0 if key else base,
                                   prev=None if key else self._last_sent, keyframe=key)
        if data is not None:
            self._last_sent = q
        return data, key, "lossless" if data is not None else "", -1

    # ------------------------------------------------------------------------------------------- consumer side

    def _status(self, after: int = 0, session: int = 0) -> bytes:
        """LIVE + UNCHANGED "no news". Its seq never exceeds the poller's ``after``: a newer seq would tell the relay
        that later frames look identical (v1 'advance' semantics) and make it skip deltas."""
        seq = after if session == self.session_id and 0 < after <= self.seq else 0
        return codec.status_container(P.STATE_LIVE, session_id=self.session_id, seq=seq, width=self.width,
                                      height=self.height, fmt=self.fmt, tile_size=self._packer.tile_size)

    def _available_from(self, after: int, session: int, key: bool) -> int | None:
        """Index into the ring of the first record to send, or None when the chain cannot serve this poller."""
        if not self._ring:
            return None
        if not key and session == self.session_id and after > 0:
            first = self._ring[0].seq
            if first - 1 <= after <= self.seq:
                return after - first + 1  # == len(ring) when the poller is up to date
        for i in range(len(self._ring) - 1, -1, -1):  # newest keyframe in the ring, unless replaying is too long
            if self._ring[i].keyframe:
                return i if len(self._ring) - i <= KEYFRAME_REPLAY_MAX else None
        return None

    def respond(self, after: int, session: int, key: bool, wait_s: float, idle: bool = False, *,
                rate: float | None = None, batch_s: float = 0.0, max_bytes: int = DEFAULT_MAX_BYTES,
                fps: float | None = None, fresh: bool = False) -> bytes:
        """Return the bundle for one poll (see module docstring)."""
        deadline = self._clock() + max(0.0, wait_s)
        with self._cond:
            now = self._clock()
            self.last_poll, self.polls = now, self.polls + 1
            if rate is not None and rate > 0:
                self._requested_rate, self._requested_at = float(rate), now
                self._requested_fps = float(fps) if fps else None
            if fresh and self.live and session == self.session_id and not any(
                    r.keyframe and r.seq > after for r in self._ring):
                self._force_key = True  # the poller's viewers need a new keyframe; its chain continues until then
            hold_while_stopped = idle and not self.live  # never delays news of a stop: only already-idle pollers
            asked_key = False
            while True:
                if not self.live:
                    remaining = deadline - self._clock()
                    if not hold_while_stopped or remaining <= 0:
                        return bundle([(0, codec.status_container(P.STATE_STOPPED))])
                    self._cond.wait(remaining)
                    continue
                hold_while_stopped = False
                start = self._available_from(after, session, key)
                if start is None and not asked_key:
                    self._force_key, asked_key = True, True  # chain unknown to this poller: next capture = keyframe
                if start is not None and start < len(self._ring):
                    break
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return bundle([(0, self._status(after, session))])
                self._cond.wait(remaining)
            # collect `batch_s` worth of frames after the first one (several frames per HTTP request)
            first_t = self._ring[start].t
            batch_end = min(deadline, max(self._clock(), first_t + batch_s))
            sid = self.session_id
            while self.live and self.session_id == sid and self._clock() < batch_end:
                if sum(len(r.data) for r in list(self._ring)[start:]) >= max_bytes:
                    break
                self._cond.wait(batch_end - self._clock())
            if not self.live or self.session_id != sid:
                return bundle([(0, codec.status_container(P.STATE_STOPPED) if not self.live
                                   else self._status(after, session))])
            start = self._available_from(after, session, key)
            if start is None or start >= len(self._ring):  # ring rolled over while batching (huge stream)
                return bundle([(0, self._status(after, session))])
            records, total = [], 0
            for r in list(self._ring)[start:]:
                if records and (total + len(r.data) > max_bytes or len(records) >= P.MAX_BUNDLE_ENTRIES):
                    break
                records.append(r)
                total += len(r.data)
            t0 = records[0].t
            return bundle([(int(round((r.t - t0) * 1000)), r.data) for r in records])


def bundle(entries: list[tuple[int, bytes]]) -> bytes:
    """Wrap containers (tOffsetMs, container) into one RLPB bundle."""
    body = b"".join(P.BUNDLE_ENTRY.pack(max(0, min(t, 0xFFFFFFFF)), len(c)) + c for t, c in entries)
    return P.BUNDLE_HEADER.pack(P.BUNDLE_MAGIC, P.VERSION, 0, len(entries), len(body)) + body


def parse_bundle(data: bytes) -> list[tuple[int, bytes]]:
    """Reference parser (mirrors RlpsDecoder.parseBundle). Raises ProtocolError."""
    if len(data) > P.MAX_BUNDLE_BYTES:
        raise P.ProtocolError("bundle too large")
    if len(data) < P.BUNDLE_HEADER.size:
        raise P.ProtocolError("truncated bundle header")
    magic, version, _r, count, body_len = P.BUNDLE_HEADER.unpack_from(data, 0)
    if magic != P.BUNDLE_MAGIC:
        raise P.ProtocolError("bad bundle magic")
    if version != P.VERSION:
        raise P.ProtocolError("unsupported bundle version")
    if body_len != len(data) - P.BUNDLE_HEADER.size:
        raise P.ProtocolError("bundle length mismatch")
    if not (1 <= count <= P.MAX_BUNDLE_ENTRIES):
        raise P.ProtocolError("invalid bundle entry count")
    out, off = [], P.BUNDLE_HEADER.size
    for _ in range(count):
        if off + P.BUNDLE_ENTRY.size > len(data):
            raise P.ProtocolError("truncated bundle entry")
        t, n = P.BUNDLE_ENTRY.unpack_from(data, off)
        off += P.BUNDLE_ENTRY.size
        if off + n > len(data):
            raise P.ProtocolError("truncated bundle entry")
        out.append((t, data[off:off + n]))
        off += n
    if off != len(data):
        raise P.ProtocolError("trailing bytes after bundle")
    return out


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

            def handle(self):
                try:
                    super().handle()
                except ConnectionError:  # poller/tunnel went away (read or write side): normal for long-polls
                    log.debug("%s disconnected", self.address_string())

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
    def _send(h: BaseHTTPRequestHandler, status: int, body: bytes, extra: dict | None = None,
              content_type: str = "text/plain; charset=us-ascii") -> None:
        try:
            h.send_response(status)
            h.send_header("Content-Type", content_type)
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
        if url.path not in (FRAMES_PATH, PROBE_PATH):
            return self._send(h, 404, b"not found\n")
        if not self._authorized(h):
            if not self._fail_bucket.take():
                return self._send(h, 429, b"too many failed requests\n", {"Retry-After": "5"})
            return self._send(h, 401, b"unauthorized\n", {"WWW-Authenticate": "Bearer"})
        if not self._ok_bucket.take():
            return self._send(h, 429, b"rate limited\n", {"Retry-After": "1"})
        if url.path == PROBE_PATH:
            if url.query:
                return self._send(h, 400, b"bad request: the probe takes no parameters\n")
            return self._send(h, 200, PROBE_BODY, content_type="application/octet-stream")
        try:
            q = parse_query(url.query)
        except ValueError as exc:
            return self._send(h, 400, f"bad request: {exc}\n".encode("ascii", "replace"))
        if not self._slots.acquire(blocking=False):
            return self._send(h, 503, b"too many concurrent polls\n", {"Retry-After": "1"})
        try:
            data = self.store.respond(q.after, q.session, q.key, q.wait_ms / 1000.0, q.idle,
                                      rate=q.rate or None, batch_s=q.batch_ms / 1000.0, max_bytes=q.max_bytes,
                                      fps=q.fps or None, fresh=q.fresh)
        finally:
            self._slots.release()
        if q.raw:
            self._send(h, 200, data, content_type="application/octet-stream")
            body_len = len(data)
        else:
            body = codec.to_body(data)
            self._send(h, 200, body)
            body_len = len(body)
        with self._count_lock:
            self.responses += 1
            self.bytes_sent += body_len


@dataclass(frozen=True)
class Query:
    after: int = 0
    session: int = 0
    key: bool = False
    fresh: bool = False  # continue the chain, next captured frame = keyframe
    wait_ms: int = DEFAULT_WAIT_MS
    idle: bool = False
    rate: int = 0  # bytes/s the poller can forward (0 = not reported)
    batch_ms: int = 0
    max_bytes: int = DEFAULT_MAX_BYTES
    raw: bool = False  # enc=1: binary body
    fps: int = 0  # frames/s the viewers can decode (0 = not reported)


def parse_query(query: str) -> Query:
    """Strictly parse the poll parameters. Raises ValueError on anything unexpected."""
    allowed = {"after", "session", "key", "fresh", "wait", "idle", "rate", "batch", "max", "enc", "fps"}
    values: dict[str, str] = {}
    for name, value in parse_qsl(query, keep_blank_values=True, strict_parsing=bool(query), max_num_fields=12):
        if name not in allowed or name in values:
            raise ValueError(f"unexpected or repeated parameter {name!r}")
        values[name] = value

    def uint(name: str, default: int, hi: int, lo: int = 0) -> int:
        raw = values.get(name)
        if raw is None:
            return default
        if not raw.isdigit() or len(raw) > 10:
            raise ValueError(f"{name} must be a non-negative integer")
        v = int(raw)
        if v > hi or v < lo:
            raise ValueError(f"{name} out of range")
        return v

    return Query(
        after=uint("after", 0, 0xFFFFFFFF),
        session=uint("session", 0, 0xFFFFFFFF),
        key=uint("key", 0, 1) == 1,
        fresh=uint("fresh", 0, 1) == 1,
        wait_ms=uint("wait", DEFAULT_WAIT_MS, MAX_WAIT_MS),
        idle=uint("idle", 0, 1) == 1,
        rate=uint("rate", 0, 1_000_000_000),
        batch_ms=uint("batch", 0, MAX_BATCH_MS),
        max_bytes=uint("max", DEFAULT_MAX_BYTES, P.MAX_BUNDLE_BYTES, lo=64 * 1024),
        raw=uint("enc", 0, 1) == 1,
        fps=uint("fps", 0, 240),
    )
