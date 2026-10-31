"""RLPS desktop app: explicit Start/Stop sharing, a visible sharing indicator, the capture loop and the frame service.

    python -m rlps.app                 # small always-visible window with Start/Stop sharing (Tk, stdlib)
    python -m rlps.app --no-gui        # console: start | stop | status | quit
    python -m rlps.app --list-monitors

Nothing is captured until sharing is started explicitly (button, ``start`` command or ``--start``). Stopping ends the
capture thread, drops every stored frame and makes the frame service answer STOPPED immediately. The app never
records to disk, never captures webcam/microphone/input, and offers no remote control.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import capture, codec, server
from . import protocol as P

log = logging.getLogger("rlps.app")


@dataclass(frozen=True)
class Profile:
    name: str
    max_w: int
    max_h: int
    fmt: int
    fps: float


# Hybrid profiles: lossless tiles where the bandwidth allows, DCT for moving content, lossless refinement when still
# (rlps.hybrid). The byte rate is not fixed here: the Roblox server measures what its players keep up with (client
# acks) and reports it with every poll; --max-rate caps it. 1024 px is the EditableImage maximum width.
PROFILES = {
    "max": Profile("max", 1024, 576, P.FMT_HYBRID, 30.0),
    "high": Profile("high", 768, 432, P.FMT_HYBRID, 30.0),
    "balanced": Profile("balanced", 640, 352, P.FMT_HYBRID, 24.0),
    "low": Profile("low", 512, 288, P.FMT_HYBRID, 15.0),
    "lossless": Profile("lossless", 1024, 576, P.FMT_RGBA8, 15.0),  # never lossy (text work on fast networks)
}
DEFAULT_PROFILE = "max"


@dataclass
class CaptureStats:
    state: str = "stopped"  # stopped | starting | capturing | interrupted
    frames_captured: int = 0
    frames_published: int = 0
    errors: int = 0
    last_error: str = ""
    last_capture_ms: float = 0.0
    frame_size: tuple[int, int] = (0, 0)
    source_size: tuple[int, int] = (0, 0)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def snapshot(self) -> dict:
        with self.lock:
            return {k: getattr(self, k) for k in ("state", "frames_captured", "frames_published", "errors",
                                                  "last_error", "last_capture_ms", "frame_size", "source_size")}


class CaptureLoop(threading.Thread):
    """Capture → resize → quantize → publish at most ``profile.fps`` times per second until ``stop_event`` is set."""

    def __init__(self, source, store: server.FrameStore, profile: Profile, stop_event: threading.Event,
                 stats: CaptureStats, clock=time.monotonic):
        super().__init__(name="rlps-capture", daemon=True)
        self.source, self.store, self.profile = source, store, profile
        self.stop_event, self.stats, self.clock = stop_event, stats, clock

    def run(self) -> None:
        backoff = 0.5
        interval = 1.0 / self.profile.fps
        try:
            while not self.stop_event.is_set():
                t0 = self.clock()
                try:
                    bgra = self.source.grab_bgra()
                    align = P.HYBRID_TILE if self.profile.fmt == P.FMT_HYBRID else 1
                    rgb = capture.bgra_to_rgb(bgra, self.profile.max_w, self.profile.max_h, align)
                    q = codec.quantize(rgb, self.profile.fmt)
                except capture.CaptureError as exc:
                    with self.stats.lock:
                        self.stats.errors += 1
                        self.stats.state, self.stats.last_error = "interrupted", str(exc)
                    log.warning("capture interrupted: %s (retrying in %.1f s)", exc, backoff)
                    self.stop_event.wait(backoff)
                    backoff = min(backoff * 2, 5.0)
                    continue
                backoff = 0.5
                if self.stop_event.is_set():  # never publish once stop was requested
                    break
                published = self.store.publish(q, self.profile.fmt)
                with self.stats.lock:
                    self.stats.state = "capturing"
                    self.stats.frames_captured += 1
                    self.stats.frames_published += bool(published)
                    self.stats.last_capture_ms = (self.clock() - t0) * 1000.0
                    self.stats.frame_size = (rgb.shape[1], rgb.shape[0])
                    self.stats.source_size = (bgra.shape[1], bgra.shape[0])
                self.stop_event.wait(max(0.0, interval - (self.clock() - t0)))
        except Exception:  # pragma: no cover - unexpected bug: stop sharing rather than leave a zombie session
            log.exception("capture loop crashed; sharing stopped")
            self.store.stop()
            with self.stats.lock:
                self.stats.state, self.stats.last_error = "stopped", "internal error (see log)"
        finally:
            self.source.close()


class SharingController:
    """Owns the sharing state. ``start``/``stop`` are idempotent and safe to call from any thread."""

    def __init__(self, store: server.FrameStore, source_factory, profile: Profile):
        self.store, self.source_factory, self.profile = store, source_factory, profile
        self.stats = CaptureStats()
        self._lock = threading.RLock()
        self._thread: CaptureLoop | None = None
        self._stop_event: threading.Event | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._thread is not None

    def start(self) -> int:
        with self._lock:
            if self._thread is not None:
                return self.store.session_id
            session = self.store.start()
            with self.stats.lock:
                self.stats.state, self.stats.last_error = "starting", ""
            self._stop_event = threading.Event()
            self._thread = CaptureLoop(self.source_factory(), self.store, self.profile, self._stop_event, self.stats)
            self._thread.start()
            log.warning("SHARING STARTED (profile %s, session %d)", self.profile.name, session)
            return session

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            if self._thread is None:
                return
            self._stop_event.set()
            self.store.stop()  # immediate: frames dropped, waiting polls answer STOPPED
            self._thread.join(timeout)
            if self._thread.is_alive():  # pragma: no cover - a grab hung; the store already refuses its frames
                log.error("capture thread did not exit within %.1f s", timeout)
            self._thread = self._stop_event = None
            with self.stats.lock:
                self.stats.state = "stopped"
            log.warning("SHARING STOPPED")

    def set_profile(self, profile: Profile) -> None:
        with self._lock:
            was_active = self._thread is not None
            self.stop()
            self.profile = profile
            if was_active:
                self.start()

    def status_text(self, service: server.FrameService | None = None) -> str:
        s = self.stats.snapshot()
        lines = [f"sharing: {'ON' if self.active else 'off'} ({s['state']}), profile {self.profile.name}"]
        if self.active:
            lines.append(f"frames: {s['frames_published']} sent / {s['frames_captured']} captured, "
                         f"{s['frame_size'][0]}x{s['frame_size'][1]} from {s['source_size'][0]}x{s['source_size'][1]}"
                         f", {s['last_capture_ms']:.0f} ms/frame, errors {s['errors']}")
            e = self.store.status
            quality = f"DCT q{e.last_quality}" if e.last_mode == "dct" else (e.last_mode or "-")
            lines.append(f"stream: budget {e.rate / 1e6:.2f} MB/s, last frame {quality}, "
                         f"encode {e.last_encode_ms:.0f} ms, skipped {e.skipped} (over budget)")
            if s["last_error"]:
                lines.append(f"last error: {s['last_error']}")
        last = self.store.last_poll
        lines.append("roblox server: " + ("never polled" if last is None else
                                          f"last poll {time.monotonic() - last:.1f} s ago ({self.store.polls} polls)"))
        if service is not None:
            lines.append(f"served: {service.responses} responses, {service.bytes_sent / 1024:.0f} KiB")
        return "\n".join(lines)


# ------------------------------------------------------------------------------------------------- configuration


def default_config_path() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "rlps" / "config.json"


def load_or_create_config(path: Path, rotate: bool = False) -> tuple[dict, bool]:
    """Return (config, created). The config holds the Bearer token the Roblox server must present."""
    cfg: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            raise ValueError(f"{path}: expected a JSON object")
    created = rotate or not isinstance(cfg.get("token"), str)
    if created:
        cfg["token"] = secrets.token_urlsafe(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    if len(cfg["token"]) < 24:
        raise ValueError(f"{path}: token must be at least 24 characters")
    return cfg, created


# ------------------------------------------------------------------------------------------------------------ UI


def run_console(controller: SharingController, service: server.FrameService) -> None:
    print("commands: start | stop | status | quit   (Ctrl+C stops sharing and quits)")
    try:
        while True:
            try:
                cmd = input("rlps> ").strip().lower()
            except EOFError:
                break
            if cmd == "start":
                controller.start()
                print("*** SHARING YOUR SCREEN *** — type 'stop' to stop")
            elif cmd == "stop":
                controller.stop()
                print("sharing stopped")
            elif cmd == "status":
                print(controller.status_text(service))
            elif cmd in ("quit", "exit", "q"):
                break
            elif cmd:
                print("unknown command")
    except KeyboardInterrupt:
        print()
    finally:
        controller.stop()


def run_gui(controller: SharingController, service: server.FrameService) -> None:  # pragma: no cover - needs a display
    import tkinter as tk

    root = tk.Tk()
    root.title("RLPS screen sharing")
    root.resizable(False, False)
    banner = tk.Label(root, width=28, font=("Segoe UI", 15, "bold"), pady=6)
    banner.pack(fill="x")
    buttons = tk.Frame(root)
    buttons.pack(pady=4)
    start_btn = tk.Button(buttons, text="Start sharing", width=14, command=controller.start)
    stop_btn = tk.Button(buttons, text="Stop sharing", width=14, command=controller.stop)
    start_btn.pack(side="left", padx=4)
    stop_btn.pack(side="left", padx=4)
    profile_var = tk.StringVar(value=controller.profile.name)
    tk.OptionMenu(root, profile_var, *PROFILES, command=lambda n: controller.set_profile(PROFILES[n])).pack()
    info = tk.Label(root, justify="left", anchor="w", font=("Consolas", 9), padx=6, pady=6)
    info.pack(fill="x")

    def refresh():
        on = controller.active
        banner.config(text="● SHARING YOUR SCREEN" if on else "Not sharing", bg="#c62828" if on else "#9e9e9e",
                      fg="white")
        root.title("● SHARING — RLPS" if on else "RLPS screen sharing")
        root.attributes("-topmost", on)  # the indicator stays visible while sharing
        start_btn.config(state="disabled" if on else "normal")
        stop_btn.config(state="normal" if on else "disabled")
        info.config(text=controller.status_text(service))
        root.after(500, refresh)

    def close():
        controller.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda _e: controller.stop())
    refresh()
    try:
        root.mainloop()
    finally:
        controller.stop()


# ---------------------------------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rlps.app", description=__doc__.split("\n\n")[0])
    ap.add_argument("--profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE)
    ap.add_argument("--backend", choices=("auto", "mss", "dxgi"), default="auto",
                    help="capture backend: auto = DXGI Desktop Duplication on Windows when dxcam is installed")
    ap.add_argument("--max-rate", type=float, default=8.0, metavar="MB/s",
                    help="upper bound of the stream byte rate (default 8 MB/s; Roblox reports what it sustains)")
    ap.add_argument("--monitor", type=int, default=1, help="mss monitor index: 1 = primary (default), 0 = all")
    ap.add_argument("--region", type=capture.Region.parse, help="capture left,top,width,height instead")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (keep loopback; publish with a tunnel)")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--config", type=Path, default=default_config_path())
    ap.add_argument("--rotate-token", action="store_true", help="generate a new token (old one stops working)")
    ap.add_argument("--show-token", action="store_true", help="print the token (store it as a Roblox secret)")
    ap.add_argument("--token-only", action="store_true",
                    help="print the token (creating it on first use) and exit without starting anything")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--start", action="store_true", help="start sharing immediately")
    ap.add_argument("--list-monitors", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.list_monitors:
        for i, m in enumerate(capture.list_monitors()):
            print(f"{i}: {m['width']}x{m['height']} at ({m['left']},{m['top']})" + ("  (all)" if i == 0 else ""))
        return 0
    cfg, created = load_or_create_config(args.config, rotate=args.rotate_token)
    if created or args.show_token or args.token_only:
        print(f"token ({'new' if created else 'existing'}, saved in {args.config}):\n  {cfg['token']}\n"
              "store it in the Roblox experience secrets (see docs/deployment) — never share it or commit it")
    if args.token_only:
        return 0
    if args.host not in ("127.0.0.1", "::1", "localhost"):
        log.warning("binding to %s exposes the frame service beyond this PC; prefer 127.0.0.1 + a tunnel", args.host)
    store = server.FrameStore(max_rate=args.max_rate * 1e6)
    try:
        service = server.FrameService(store, cfg["token"], host=args.host, port=args.port)
    except OSError as exc:
        log.error("cannot listen on %s:%d (%s) - is the app already running? Close it or pass --port",
                  args.host, args.port, exc)
        return 2
    service.start()
    log.info("frame service on http://%s:%d%s", *service.address, server.FRAMES_PATH)
    controller = SharingController(store, lambda: capture.make_source(args.backend, args.monitor, args.region),
                                   PROFILES[args.profile])
    try:
        if args.start:
            controller.start()
        if args.no_gui:
            run_console(controller, service)
        else:
            run_gui(controller, service)
    finally:
        controller.stop()
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
