#!/usr/bin/env python3
"""Live pipeline test (verification level L3, see docs/testing/E2E.md).

Real screen pixels go through every component except the Roblox engine itself:

    X11 desktop (Xvfb + painter.py) --mss--> rlps.app SharingController/CaptureLoop --> rlps.server FrameService (HTTP)
    --> unmodified RlpsServer.server.luau (HttpService emulated with real HTTP) --> RemoteEvent (emulated, ordered,
    copied) --> 2x unmodified RlpsClient.client.luau --> EditableImage (emulated pixel store) on the TV SurfaceGui

and the test asserts, byte for byte, that each client's EditableImage equals the newest captured frame
(``codec.expand_to_rgba`` of what the frame service holds), plus the screen states the players see.

Scenarios: ``live`` (stopped -> start -> picture -> late joiner -> desktop change -> rapid changes -> service outage
and recovery -> stop) and ``badtoken`` (wrong secret -> error screen). Writes report.json and PNG snapshots to --out.

Usage: python3 tests/e2e/run_e2e.py [--out DIR] [--lune PATH] [--profile balanced] [--scenario live|badtoken|all]
Requires: Xvfb (unless DISPLAY is set), python-xlib, lune >= 0.10, and desktop/requirements.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "desktop"))

import numpy as np  # noqa: E402

from rlps import app, capture, codec, server  # noqa: E402

sys.path.insert(0, HERE)
import painter as scenes  # noqa: E402  (only constants; the drawing runs in a subprocess)

SCREEN_W, SCREEN_H = scenes.REF_W, scenes.REF_H  # scene coordinates (the painter scales them to the real screen)
XVFB_SIZE = "1280x720x24"


class Failure(AssertionError):
    pass


class RecordingStore(server.FrameStore):
    """FrameStore that remembers, per published frame, the SHA-256 of the decoder-side picture and whether it was
    lossy (picture != captured frame) — lets the test prove that clients show lossy frames bit-exactly."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.history: dict[str, bool] = {}

    def publish(self, q, fmt):
        added = super().publish(q, fmt)
        if added:
            _, rgba = self.picture()
            if rgba is not None:
                self.history[hashlib.sha256(rgba.tobytes()).hexdigest()] = not np.array_equal(rgba, q)
        return added


def write_png(path: str, rgba: np.ndarray) -> None:
    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class Harness:
    def __init__(self, args, out: str):
        self.args, self.out = args, out
        self.procs: list[subprocess.Popen] = []
        self.checks: list[dict] = []
        self.metrics: dict = {}

    # -------------------------------------------------------------------------------------------- environment

    def start_display(self) -> None:
        if not sys.platform.startswith("linux") or (os.environ.get("DISPLAY") and not self.args.xvfb):
            return  # Windows/macOS: the real desktop; Linux with DISPLAY: that X server
        disp = ":%d" % (90 + os.getpid() % 9)
        p = subprocess.Popen(["Xvfb", disp, "-screen", "0", XVFB_SIZE, "-nolisten", "tcp"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        os.environ["DISPLAY"] = disp
        for _ in range(50):
            if os.path.exists(f"/tmp/.X11-unix/X{disp[1:]}"):
                return
            time.sleep(0.1)
        raise Failure("Xvfb did not start")

    def start_painter(self) -> None:
        self.painter = subprocess.Popen([sys.executable, os.path.join(HERE, "painter.py")], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True)
        self.procs.append(self.painter)
        line = self.painter.stdout.readline().split()
        if len(line) != 3 or line[0] != "size":
            raise Failure(f"painter did not start: {line!r}")
        self.screen = (int(line[1]), int(line[2]))
        self.metrics["screen"] = f"{self.screen[0]}x{self.screen[1]}"

    def scene(self, name: str) -> float:
        """Show scene A/B, or 'noise<seed>' (moving colours + grain in NOISE_RECT)."""
        cmd = (f"noise {name[5:]}" if name.startswith("noise") else f"page {name[4:]}" if name.startswith("page")
               else f"scene {name}")
        self.painter.stdin.write(cmd + "\n")
        self.painter.stdin.flush()
        line = self.painter.stdout.readline().strip()
        if line != f"ready {name}":
            raise Failure(f"painter answered {line!r}")
        return time.monotonic()

    def start_emulator(self, base_url: str, token: str, ctl: str, attrs: dict | None = None, *,
                       public_url: str = "https://rlps-e2e.test", secret_domain: str = "*") -> subprocess.Popen:
        env = dict(os.environ, RLPS_REPO=REPO, RLPS_OUT=ctl, RLPS_BASE_URL=base_url, RLPS_TOKEN=token,
                   RLPS_PUBLIC_URL=public_url, RLPS_SECRET_DOMAIN=secret_domain, RLPS_MAX_SECONDS="240")
        env.update({f"RLPS_ATTR_{k}": str(v) for k, v in (attrs or {}).items()})
        with open(os.path.join(ctl, "emulator.log"), "w") as log:  # the child keeps its own handle
            p = subprocess.Popen([self.args.lune, "run", os.path.join(HERE, "roblox_emulator.luau")], env=env,
                                 stdout=log, stderr=subprocess.STDOUT, cwd=REPO)
        self.procs.append(p)
        return p

    def close(self) -> None:
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()

    # -------------------------------------------------------------------------------------------------- checks

    def check(self, cid: str, desc: str, ok: bool, **evidence) -> None:
        self.checks.append({"id": cid, "check": desc, "pass": bool(ok), **evidence})
        print(f"{'PASS' if ok else 'FAIL'} {cid}: {desc} {json.dumps(evidence, default=str) if evidence else ''}",
              flush=True)
        if not ok:
            raise Failure(f"{cid}: {desc}")

    @staticmethod
    def read_state(ctl: str, timeout: float = 3.0) -> dict:
        """Newest emulator state; retries while the file is missing or being replaced (Windows: PermissionError)."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                with open(os.path.join(ctl, "state.json"), encoding="utf-8") as fh:
                    st = json.load(fh)
                if "server" in st and "clients" in st:
                    return st
            except (OSError, json.JSONDecodeError):
                pass
            if time.monotonic() >= deadline:
                return {}
            time.sleep(0.02)

    def wait_for(self, ctl: str, pred, timeout: float, what: str):
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            st = self.read_state(ctl, timeout=0.2)
            if st:
                last = st
                errs = st["server"]["errors"] or [e for c in st["clients"].values() for e in (c["errors"] or [])]
                if errs:
                    raise Failure(f"script error while waiting for {what}: {errs}")
                got = pred(st)
                if got:
                    return got, st
            time.sleep(0.05)
        raise Failure(f"timeout ({timeout:.0f} s) waiting for {what}; last state: {json.dumps(last)[:1500]}")

    @staticmethod
    def expected(store: server.FrameStore) -> tuple[int, str, np.ndarray]:
        """(seq, sha256, RGBA) of the picture every up-to-date client must show: the encoder's decoder-side
        reconstruction after the newest frame of the chain (lossy tiles included, bit-exact)."""
        seq, rgba = store.picture()
        if rgba is None:
            return seq, "", np.zeros((0, 0, 4), np.uint8)
        return seq, hashlib.sha256(rgba.tobytes()).hexdigest(), rgba

    @staticmethod
    def captured(store: server.FrameStore) -> np.ndarray | None:
        """The newest captured frame (what the desktop really looks like, at stream resolution)."""
        with store._cond:
            q, fmt = store.latest, store.fmt
        return None if q is None else codec.expand_to_rgba(q, fmt)

    def wait_match(self, ctl: str, store, names: list[str], timeout: float, what: str, after_seq: int = 0):
        """Wait until every named client's EditableImage equals the newest captured frame, which must be newer than
        ``after_seq`` (so a change is only accepted once the capture loop has really seen it)."""
        def pred(st):
            seq, sha, rgba = self.expected(store)
            if not sha or seq <= after_seq:
                return None
            for n in names:
                c = st["clients"].get(n)
                if not c or c.get("image_sha256") != sha or not c.get("picture_visible"):
                    return None
            return seq, sha, rgba
        return self.wait_for(ctl, pred, timeout, what)

    def snapshot(self, ctl: str, tag: str, names: list[str], w: int, h: int) -> dict[str, np.ndarray]:
        open(os.path.join(ctl, f"snap-{tag}"), "w").close()
        deadline = time.monotonic() + 10
        while not os.path.exists(os.path.join(ctl, f"{tag}.done")):
            if time.monotonic() > deadline:
                raise Failure(f"snapshot {tag} not written")
            time.sleep(0.05)
        out = {}
        for n in names:
            raw = np.fromfile(os.path.join(ctl, f"{n}-{tag}.rgba"), np.uint8).reshape(h, w, 4)
            write_png(os.path.join(self.out, f"tv-{n}-{tag}.png"), raw)
            out[n] = raw
        return out

    # --------------------------------------------------------------------------------------------- scenarios

    @staticmethod
    def sample(img: np.ndarray, sx: float, sy: float) -> tuple[int, int, int]:
        """Pixel of the captured frame at screen coordinate (sx, sy)."""
        h, w = img.shape[:2]
        return tuple(int(v) for v in img[min(h - 1, int(sy * h / SCREEN_H)), min(w - 1, int(sx * w / SCREEN_W)), :3])

    @staticmethod
    def near(rgb, want, tol=12) -> bool:
        return all(abs(a - b) <= tol for a, b in zip(rgb, want))

    def semantic(self, cid: str, img: np.ndarray, scene: str) -> None:
        x, y, w, h = scenes.SCENES[scene]["rect"]
        inside = self.sample(img, x + w / 2, y + h / 2)
        self.check(cid + "a", f"scene {scene}: rectangle colour visible on the TV at its screen position",
                   self.near(inside, scenes.SCENES[scene]["color"]), pixel=inside, want=scenes.SCENES[scene]["color"])
        for other, spec in scenes.SCENES.items():
            if other != scene and spec["rect"] != scenes.SCENES[scene]["rect"]:
                ox, oy, ow, oh = spec["rect"]
                bg = self.sample(img, ox + ow / 2, oy + oh / 2)
                self.check(cid + "b", f"scene {scene}: scene {other}'s rectangle is gone (background there)",
                           self.near(bg, scenes.BACKGROUND), pixel=bg, want=scenes.BACKGROUND)
        cx, cy, cw, ch, _ = scenes.CHECKER
        region = img[int(cy * img.shape[0] / SCREEN_H):int((cy + ch) * img.shape[0] / SCREEN_H),
                     int(cx * img.shape[1] / SCREEN_W):int((cx + cw) * img.shape[1] / SCREEN_W), :3]
        self.check(cid + "c", "fine checkerboard detail survives (bright and dark pixels in the region)",
                   region.max() > 200 and region[..., 0].min() < 60, max=int(region.max()), min_r=int(region[..., 0].min()))

    def scenario_live(self) -> None:
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-live-", dir=self.out)
        token = secrets.token_urlsafe(32)
        profile = app.PROFILES[self.args.profile]
        store = server.FrameStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        port = service.address[1]
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), profile)
        self.scene("A")
        emu = self.start_emulator(f"http://127.0.0.1:{port}", token, ctl, {"ModeratorUserIds": "1001"})  # Alice
        try:
            open(os.path.join(ctl, "join-Alice"), "w").close()

            # L1: before the owner shares, the TV says so and no pixels exist anywhere
            _, st = self.wait_for(ctl, lambda s: s.get("clients", {}).get("Alice", {}).get("status_text")
                                  == "Screen sharing is off", 20, "STOPPED screen on Alice")
            a = st["clients"]["Alice"]
            self.metrics["join_to_stopped_screen_s"] = round(st["t"], 3)
            self.check("E2E-01", "not sharing: TV shows 'Screen sharing is off', no picture, server polls the service",
                       not a["picture_visible"] and a["image_w"] == 0 and store.polls > 0 and store.seq == 0
                       and st["t"] < 10,
                       status=st["server"]["attributes"].get("Status"), polls=store.polls, face=a.get("face"),
                       adornee=a.get("adornee"))
            self.check("E2E-02", "TV SurfaceGui adorned to the tagged screen part, Front face",
                       a.get("adornee") == "Screen" and a.get("face") == "Front")

            # L2: explicit start -> real captured pixels on the TV, byte for byte
            t0 = time.monotonic()
            controller.start()
            (seq, sha, rgba), st = self.wait_match(ctl, store, ["Alice"], 30, "Alice shows the captured frame")
            self.metrics["start_to_picture_s"] = round(time.monotonic() - t0, 3)
            a = st["clients"]["Alice"]
            self.check("E2E-03", "after Start: Alice's EditableImage == newest captured frame (SHA-256), LIVE badge on",
                       a["badge_visible"] and not a["status_visible"] and self.metrics["start_to_picture_s"] < 5,
                       seq=seq, sha256=sha[:16],
                       size=[a["image_w"], a["image_h"]], latency_s=self.metrics["start_to_picture_s"])
            self.check("E2E-04", "frame geometry matches the profile and the 16:9 desktop",
                       (a["image_w"], a["image_h"]) == capture.stream_size(*self.screen, profile.max_w,
                                                                           profile.max_h, 16)[2:],
                       size=[a["image_w"], a["image_h"]])
            snap = self.snapshot(ctl, "sceneA", ["Alice"], a["image_w"], a["image_h"])
            self.check("E2E-05", "snapshot pixels == expected frame and == the captured desktop (lossless when still)",
                       np.array_equal(snap["Alice"], rgba) and np.array_equal(rgba, self.captured(store)))
            self.semantic("E2E-06", snap["Alice"], "A")

            # L3: a late joiner gets the keyframe chain from the server history
            t1 = time.monotonic()
            open(os.path.join(ctl, "join-Bob"), "w").close()
            (seq, sha, _), st = self.wait_match(ctl, store, ["Alice", "Bob"], 30, "late joiner Bob shows the frame")
            self.metrics["late_joiner_s"] = round(time.monotonic() - t1, 3)
            self.check("E2E-07", "late joiner Bob shows the same frame as Alice (server-side history sync)", True,
                       seq=seq, latency_s=self.metrics["late_joiner_s"])

            # L4: the desktop changes -> both TVs follow
            t2 = self.scene("B")
            (seq_b, sha_b, rgba_b), st = self.wait_match(ctl, store, ["Alice", "Bob"], 30, "both show scene B",
                                                         after_seq=seq)
            self.metrics["desktop_change_to_both_tvs_s"] = round(time.monotonic() - t2, 3)
            self.check("E2E-08", "desktop change reaches both TVs (new frame, delta path)", sha_b != sha,
                       seq=seq_b, latency_s=self.metrics["desktop_change_to_both_tvs_s"])
            snap = self.snapshot(ctl, "sceneB", ["Alice", "Bob"], st["clients"]["Alice"]["image_w"],
                                 st["clients"]["Alice"]["image_h"])
            self.semantic("E2E-09", snap["Bob"], "B")

            # L5: rapid changes (motion) -> chain stays valid, final frame exact
            for i in range(8):
                self.scene("A" if i % 2 == 0 else "B")
                time.sleep(0.15)
            self.scene("A")
            time.sleep(0.5)  # > one capture interval: the newest published frame is the final scene A
            (seq_m, _, rgba_m), st = self.wait_match(ctl, store, ["Alice", "Bob"], 30, "both settle after rapid changes",
                                                     after_seq=seq_b)
            self.check("E2E-10", "after 9 rapid desktop changes both TVs settle on the exact newest frame (scene A)",
                       self.near(self.sample(rgba_m, 300, 250), scenes.SCENES["A"]["color"]), seq=seq_m,
                       frames_between=seq_m - seq_b, dropped=st["server"]["attributes"].get("Dropped"))

            # L5b: redraw economy and viewer modes (RlpsClient)
            seq_m = self.view_checks(ctl, store, controller, seq_m)

            # L6: frame service outage -> error screen; service back -> picture resumes
            service.close()
            _, st = self.wait_for(ctl, lambda s: all(s["clients"][n]["status_text"].startswith("Screen unavailable")
                                                     for n in ("Alice", "Bob")), 40, "error screen during outage")
            self.check("E2E-11", "frame service down: both TVs show 'Screen unavailable' and hide the picture",
                       not any(st["clients"][n]["picture_visible"] for n in ("Alice", "Bob")),
                       detail=st["clients"]["Alice"]["status_text"], last_error=st["server"]["attributes"].get("LastError"))
            service = server.FrameService(store, token, port=port)
            service.start()
            t3 = time.monotonic()
            self.scene("B")
            (seq_r, _, _), st = self.wait_match(ctl, store, ["Alice", "Bob"], 60, "recovery after outage",
                                                after_seq=seq_m)
            self.metrics["outage_recovery_s"] = round(time.monotonic() - t3, 3)
            self.check("E2E-12", "service back: both TVs resume with the exact newest frame",
                       all(st["clients"][n]["badge_visible"] for n in ("Alice", "Bob")), seq=seq_r,
                       latency_s=self.metrics["outage_recovery_s"])

            # L7: explicit stop -> every TV says so and every client dropped its pixels
            t4 = time.monotonic()
            controller.stop()
            _, st = self.wait_for(ctl, lambda s: all(s["clients"][n]["status_text"] == "Screen sharing is off"
                                                     and s["clients"][n]["image_w"] == 0 for n in ("Alice", "Bob")),
                                  30, "STOPPED on both TVs")
            self.metrics["stop_to_tv_off_s"] = round(time.monotonic() - t4, 3)
            self.check("E2E-13", "after Stop: both TVs show 'Screen sharing is off', EditableImages destroyed, "
                       "no frames left in the service, within 5 s",
                       store.seq == 0 and not store._ring and store.latest is None and self.metrics["stop_to_tv_off_s"] < 5,
                       latency_s=self.metrics["stop_to_tv_off_s"], status=st["server"]["attributes"].get("Status"))

            # L8: a player leaving is handled; no script errors anywhere
            open(os.path.join(ctl, "leave-Bob"), "w").close()
            time.sleep(1.0)
            st = self.read_state(ctl)
            errs = st["server"]["errors"] or [e for c in st["clients"].values() for e in (c["errors"] or [])]
            self.check("E2E-14", "no script errors on the server or any client during the whole run", not errs,
                       errors=errs)
            self.metrics.update({
                "profile": profile.name,
                "frame_service_responses_after_outage": service.responses,
                "http_requests_by_roblox_server": st["server"]["http_requests"],
                "http_body_bytes": st["server"]["http_body_bytes"],
                "server_forwarded_part_bytes": st["server"]["attributes"].get("ForwardedBytes"),
                "server_containers": st["server"]["attributes"].get("Containers"),
                "server_dropped": st["server"]["attributes"].get("Dropped"),
                "alice_received_bytes": st["clients"]["Alice"]["recv_bytes"],
                "alice_remote_messages": st["clients"]["Alice"]["recv_messages"],
                "alice_pixel_writes": st["clients"]["Alice"]["pixel_writes"],
                "frames_published": controller.stats.frames_published,
                "frames_captured": controller.stats.frames_captured,
            })
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-live.log"))

    def scenario_pacing(self) -> None:
        """Backpressure: with a tiny byte budget, rapid desktop changes are coalesced, not queued."""
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-pacing-", dir=self.out)
        token = secrets.token_urlsafe(32)
        budget = 3000
        store = server.FrameStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["low"])
        self.scene("A")
        controller.start()
        emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl,
                                  {"MaxBytesPerSecond": budget, "StartBytesPerSecond": budget,
                                   "MinBytesPerSecond": budget})
        try:
            open(os.path.join(ctl, "join-Dave"), "w").close()
            (seq0, _, _), st = self.wait_match(ctl, store, ["Dave"], 40, "Dave shows the first frame")
            time.sleep(4)  # let the pacing delay of the keyframe elapse
            st = self.read_state(ctl)
            f0, c0, t0 = st["server"]["attributes"]["ForwardedBytes"], st["server"]["attributes"]["Containers"], st["t"]
            changes = 0
            end = time.monotonic() + 10
            while time.monotonic() < end:
                self.scene("B" if changes % 2 == 0 else "A")
                changes += 1
                time.sleep(0.37)  # not a multiple of the capture interval (no aliasing)
            st = self.read_state(ctl)
            f1, t1 = st["server"]["attributes"]["ForwardedBytes"], st["t"]
            (seq1, _, _), st2 = self.wait_match(ctl, store, ["Dave"], 40, "Dave settles after the churn",
                                                after_seq=seq0)
            rate = (f1 - f0) / max(0.001, t1 - t0)
            published = controller.stats.frames_published
            self.metrics["pacing"] = {"budget_Bps": budget, "measured_Bps": round(rate), "desktop_changes": changes,
                                      "frames_published": published, "containers_ingested_during_churn":
                                      st["server"]["attributes"]["Containers"] - c0}
            self.check("E2E-16", f"pacing: forwarded stream stays near the {budget} B/s budget during 10 s of "
                       "~2.7 changes/s (one container of slack), frames coalesced, final frame exact",
                       rate <= budget * 1.6 and seq1 > seq0, **self.metrics["pacing"])
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-pacing.log"))

    def scenario_quality(self) -> None:
        """Moving grain under a byte budget: lossy DCT tiles through the real Luau decoder (bit-exact), then the
        still picture converges to the exact desktop; also exercises the base64 fallback when bodies are mangled."""
        for mangle in (False, True):
            ctl = tempfile.mkdtemp(prefix="rlps-e2e-quality-", dir=self.out)
            token = secrets.token_urlsafe(32)
            store = RecordingStore()
            service = server.FrameService(store, token, port=0)
            service.start()
            controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["max"])
            self.scene("A")
            controller.start()
            budget = 150_000
            env_attrs = {"MaxBytesPerSecond": budget, "StartBytesPerSecond": budget, "MinBytesPerSecond": budget}
            if mangle:
                os.environ["RLPS_EMU_TEXT_BODIES"] = "1"
            try:
                emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl, env_attrs)
            finally:
                os.environ.pop("RLPS_EMU_TEXT_BODIES", None)
            tag = "E2E-19" if mangle else "E2E-18"
            try:
                open(os.path.join(ctl, "join-Gwen"), "w").close()
                self.wait_match(ctl, store, ["Gwen"], 40, "first picture")
                modes, lossy_seen = set(), set()
                for k in range(1, 13):
                    self.scene(f"noise{k}")
                    deadline = time.monotonic() + 0.6
                    while time.monotonic() < deadline:  # the client's picture must be one the encoder produced
                        modes.add(store.status.last_mode)
                        sha = self.read_state(ctl).get("clients", {}).get("Gwen", {}).get("image_sha256")
                        if sha and store.history.get(sha):
                            lossy_seen.add(sha)  # a lossy (DCT) picture, shown bit-exactly
                        time.sleep(0.03)
                lossy_matches = len(lossy_seen)
                (seq_m, _, rgba_m), st = self.wait_match(ctl, store, ["Gwen"], 40, "Gwen matches the lossy stream",
                                                         after_seq=1)
                body_mode = st["server"]["attributes"].get("BodyMode")
                dct_seen = "dct" in modes
                # still now: keep waiting until the refinement made the picture pixel-exact
                def exact(s):
                    seq, sha, rgba = self.expected(store)
                    c = s["clients"].get("Gwen", {})
                    cap = self.captured(store)
                    return (cap is not None and rgba.shape == cap.shape and np.array_equal(rgba, cap)
                            and c.get("image_sha256") == sha) or None
                t0 = time.monotonic()
                self.wait_for(ctl, exact, 60, "refinement to the exact desktop")
                self.metrics[f"{tag}_refine_s"] = round(time.monotonic() - t0, 2)
                self.check(tag, ("binary bodies mangled -> base64 fallback, " if mangle else "") +
                           "moving grain at 150 KB/s: lossy DCT frames decoded bit-exactly by the client, then the "
                           "still picture refines to the exact captured desktop",
                           dct_seen and lossy_matches >= 3 and body_mode == ("base64" if mangle else "raw"),
                           modes=sorted(m for m in modes if m), lossy_pictures_matched=lossy_matches,
                           body_mode=body_mode, seq=seq_m,
                           refine_s=self.metrics[f"{tag}_refine_s"], errors=st["server"]["errors"])
            finally:
                open(os.path.join(ctl, "quit"), "w").close()
                try:
                    emu.wait(10)
                except subprocess.TimeoutExpired:
                    emu.kill()
                controller.stop()
                service.close()
                shutil.copy(os.path.join(ctl, "emulator.log"),
                            os.path.join(self.out, f"emulator-quality{'-mangled' if mangle else ''}.log"))

    def scenario_scroll(self) -> None:
        """Scrolling a text page (non-integer downscale 1280 -> 1024): copy tiles from the previous picture keep the
        stream small; the client follows bit-exactly and ends on the exact page."""
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-scroll-", dir=self.out)
        token = secrets.token_urlsafe(32)
        store = RecordingStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["max"])
        self.scene("page0")
        controller.start()
        emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl,
                                  {"StartBytesPerSecond": 1_000_000})
        try:
            open(os.path.join(ctl, "join-Sam"), "w").close()
            (seq0, _, first), _ = self.wait_match(ctl, store, ["Sam"], 40, "first page")
            keyframe_bytes = store.status.bytes
            copied0, bytes0 = store.status.copied, store.status.bytes
            for k in range(1, 16):
                self.scene(f"page{12 * k}")
                time.sleep(0.12)
            sent = store.status.bytes - bytes0
            copied = store.status.copied - copied0
            def exact(s):
                seq, sha, rgba = self.expected(store)
                cap = self.captured(store)
                c = s["clients"].get("Sam", {})
                return (cap is not None and np.array_equal(rgba, cap) and c.get("image_sha256") == sha) or None
            self.wait_for(ctl, exact, 60, "page exact after scrolling")
            self.metrics["scroll"] = {"keyframe_bytes": keyframe_bytes, "bytes_for_15_scroll_steps": sent,
                                      "copied_tiles": copied}
            tiles = (store.width // 16) * (store.height // 16)
            # without copies every step changes ~every tile: about one keyframe per step, lossless. Copies cost a few
            # bytes per tile; the pauses between steps are (correctly) spent refining approximate copies to lossless —
            # how much refinement fits in a pause depends on machine load (measured 262-386 kB for the same ~32,400
            # copied tiles), hence a 2/3 bound rather than a tight one.
            self.check("E2E-21", "scrolling a text page: most changed tiles sent as copies of the previous picture, "
                       "15 scroll steps cost less than 2/3 of resending them, client ends on the exact page",
                       copied > 15 * tiles * 0.5 and sent < 2 / 3 * 15 * keyframe_bytes, tiles_per_frame=tiles,
                       **self.metrics["scroll"])
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-scroll.log"))

    def scenario_congestion(self) -> None:
        """Adaptive rate: grows while every viewer keeps up; a throttled viewer pulls it down or gets paused,
        the fast viewer keeps receiving frames, and both end on the exact picture."""
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-congestion-", dir=self.out)
        token = secrets.token_urlsafe(32)
        store = server.FrameStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["high"])
        self.scene("A")
        controller.start()
        start_rate = 300_000
        os.environ["RLPS_EMU_THROTTLE_Slow"] = "10000"
        try:
            emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl,
                                      {"StartBytesPerSecond": start_rate, "MaxBytesPerSecond": 4_000_000,
                                       "MinBytesPerSecond": 50_000})
        finally:
            os.environ.pop("RLPS_EMU_THROTTLE_Slow", None)
        try:
            open(os.path.join(ctl, "join-Fast"), "w").close()
            self.wait_match(ctl, store, ["Fast"], 40, "Fast shows the first frame")
            k = 100
            def animate(seconds):
                nonlocal k
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    k += 1
                    self.scene(f"noise{k}")
                    time.sleep(0.05)
            animate(8)
            grown = self.read_state(ctl)["server"]["attributes"].get("RateBps", 0)
            open(os.path.join(ctl, "join-Slow"), "w").close()
            fast_shas, min_rate, max_lagging = set(), grown, 0
            end = time.monotonic() + 14
            while time.monotonic() < end:
                k += 1
                self.scene(f"noise{k}")
                st = self.read_state(ctl)
                a = st["server"]["attributes"]
                min_rate = min(min_rate, a.get("RateBps", grown))
                max_lagging = max(max_lagging, a.get("LaggingViewers", 0))
                fast_shas.add(st["clients"]["Fast"].get("image_sha256"))
                time.sleep(0.05)
            self.scene("A")
            (seq, _, _), st = self.wait_match(ctl, store, ["Fast", "Slow"], 90, "both settle after the congestion")
            self.metrics["congestion"] = {"start_rate": start_rate, "rate_after_growth": grown,
                                          "min_rate_with_slow_viewer": min_rate, "max_lagging_viewers": max_lagging,
                                          "fast_distinct_pictures_meanwhile": len(fast_shas)}
            self.check("E2E-20", "adaptive rate: grows above the start rate with one fast viewer; a 10 KB/s viewer "
                       "makes it back off or gets paused while the fast viewer keeps getting frames; both end exact",
                       grown > start_rate * 1.3 and (min_rate < grown * 0.6 or max_lagging >= 1)
                       and len(fast_shas) >= 5, **self.metrics["congestion"])
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-congestion.log"))

    def scenario_viewers(self) -> None:
        """ViewerUserIds allowlist: only listed players receive pixels."""
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-viewers-", dir=self.out)
        token = secrets.token_urlsafe(32)
        store = server.FrameStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["low"])
        self.scene("A")
        controller.start()
        # the emulator hands out UserIds 1001, 1002, … in join order: Erin = 1001 (allowed), Mallory = 1002 (not)
        emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl,
                                  {"ViewerUserIds": "1001", "ViewerModes": "cinema"})
        try:
            open(os.path.join(ctl, "join-Erin"), "w").close()
            self.wait_match(ctl, store, ["Erin"], 40, "allowed viewer Erin shows the frame")
            open(os.path.join(ctl, "join-Mallory"), "w").close()
            _, st = self.wait_for(ctl, lambda s: "not authorized" in (s.get("clients", {}).get("Mallory", {})
                                                                      .get("status_text") or ""), 30,
                                  "Mallory sees the not-authorized message")
            self.scene("B")
            self.wait_match(ctl, store, ["Erin"], 30, "Erin follows a change", after_seq=0)
            time.sleep(1.0)
            st = self.read_state(ctl)
            m = st["clients"]["Mallory"]
            self.press(ctl, "key-Erin-F")  # full screen is not offered by this owner
            time.sleep(0.8)
            ev = self.read_state(ctl)["clients"]["Erin"]["view"]
            self.check("E2E-27", "ViewerModes = 'cinema': players get only the cinema button, the F key does nothing; "
                       "a non-authorized player gets no viewer controls",
                       ev["buttons"] == "CinemaButton" and ev["controls_enabled"] and not ev["fullscreen_enabled"]
                       and not st["clients"]["Mallory"]["view"]["controls_enabled"], erin=ev["buttons"])
            self.check("E2E-17", "ViewerUserIds: a non-listed player gets 'not authorized', no image and no pixel data",
                       not m["picture_visible"] and m["images_created"] == 0 and m["pixel_writes"] == 0,
                       text=m["status_text"], mallory_received_bytes=m["recv_bytes"])
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-viewers.log"))

    def scenario_badtoken(self) -> None:
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-badtoken-", dir=self.out)
        store = server.FrameStore()
        service = server.FrameService(store, secrets.token_urlsafe(32), port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["low"])
        controller.start()
        emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", secrets.token_urlsafe(32), ctl)
        try:
            open(os.path.join(ctl, "join-Carol"), "w").close()
            _, st = self.wait_for(ctl, lambda s: "rejected the token" in (s.get("clients", {}).get("Carol", {})
                                                                          .get("status_text") or ""), 40,
                                  "token error on Carol's TV")
            c = st["clients"]["Carol"]
            self.check("E2E-15", "wrong secret: TV shows the 401 token error, no picture ever reaches the client",
                       not c["picture_visible"] and c["images_created"] == 0 and c["pixel_writes"] == 0,
                       text=c["status_text"])
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-badtoken.log"))

    def press(self, ctl: str, what: str) -> None:
        """Emulator command: press-<client>-<Button>, key-<client>-<KeyCode> or look-<client>-<away|tv>."""
        open(os.path.join(ctl, what), "w").close()

    def view_checks(self, ctl: str, store, controller, after_seq: int) -> int:
        """Dirty-rectangle redraws, redraw culling, full screen, cinema and mini player on Alice (Bob untouched)."""
        def view(s):
            return s["clients"]["Alice"].get("view", {})

        def attrs(s):
            return s["clients"]["Alice"].get("script_attributes") or {}

        # 1. two small squares in opposite corners: only their tiles are rewritten, not the bounding box (≈ the screen)
        self.scene("D")
        (seq_d, _, _), st = self.wait_match(ctl, store, ["Alice", "Bob"], 30, "scene D on both", after_seq=after_seq)
        time.sleep(1.3)  # client diagnostics are published once per second
        st = self.read_state(ctl)
        a = st["clients"]["Alice"]
        px, full = attrs(st).get("LastRedrawPixels", -1), a["image_w"] * a["image_h"]
        self.check("E2E-23", "a change in two opposite corners redraws only those tiles (dirty rectangles), not "
                   "their bounding box", 0 < px <= 0.02 * full, last_redraw_pixels=px, frame_pixels=full)

        # 2. Alice looks away: her TV is not redrawn (Bob's is); looking back draws everything that changed meanwhile
        self.press(ctl, "look-Alice-away")
        time.sleep(0.4)
        before = attrs(self.read_state(ctl))
        self.scene("A")
        (seq_a, sha_a, _), _ = self.wait_match(ctl, store, ["Bob"], 30, "scene A on Bob", after_seq=seq_d)
        time.sleep(1.3)
        st = self.read_state(ctl)
        after = attrs(st)
        stale = st["clients"]["Alice"]["image_sha256"] != sha_a
        self.press(ctl, "look-Alice-tv")
        (seq_a, _, _), _ = self.wait_match(ctl, store, ["Alice"], 30, "Alice catches up when looking back",
                                           after_seq=seq_d)
        self.check("E2E-24", "TV out of view: no redraws while frames are still decoded; looking back shows the exact "
                   "current picture", stale and after.get("Redraws") == before.get("Redraws")
                   and after.get("SkippedRedraws", 0) > before.get("SkippedRedraws", 0)
                   and after.get("FramesCompleted", 0) > before.get("FramesCompleted", 0),
                   redraws=[before.get("Redraws"), after.get("Redraws")],
                   skipped=[before.get("SkippedRedraws"), after.get("SkippedRedraws")])

        # 3. full screen (key F), Fill, exit; mini player, expand to full screen, close
        _, st = self.wait_for(ctl, lambda s: view(s).get("controls_enabled"), 20, "viewer controls near the TV")
        self.press(ctl, "key-Alice-F")
        _, st = self.wait_for(ctl, lambda s: view(s).get("fullscreen_enabled") and not view(s).get("controls_enabled"),
                              20, "full screen open")
        v = view(st)
        fs_ok = v.get("fullscreen_same_image") and v.get("fullscreen_picture_visible")
        self.press(ctl, "press-Alice-FitButton")
        _, st = self.wait_for(ctl, lambda s: view(s).get("fullscreen_scale") == "Crop", 20, "full screen fill")
        self.press(ctl, "press-Alice-SharpButton")
        _, st = self.wait_for(ctl, lambda s: view(s).get("fullscreen_resample") == "Pixelated", 20, "sharp pixels")
        self.press(ctl, "press-Alice-ExitButton")
        self.wait_for(ctl, lambda s: not view(s).get("fullscreen_enabled") and view(s).get("controls_enabled"), 20,
                      "full screen closed")
        self.press(ctl, "press-Alice-MiniButton")
        _, st = self.wait_for(ctl, lambda s: view(s).get("mini_enabled"), 20, "mini player open")
        mini_ok = view(st).get("mini_same_image") and view(st).get("mini_picture_visible")
        self.press(ctl, "press-Alice-ExpandButton")
        _, st = self.wait_for(ctl, lambda s: view(s).get("fullscreen_enabled") and not view(s).get("mini_enabled"), 20,
                              "mini player expanded to full screen")
        self.press(ctl, "key-Alice-F")
        self.wait_for(ctl, lambda s: not view(s).get("fullscreen_enabled"), 20, "full screen closed by key")
        self.check("E2E-25", "full screen (key F) and mini player show the live picture (same EditableImage as the "
                   "TV); Fill crops; Exit, expand and the key close/switch modes; controls hide while a mode is open",
                   bool(fs_ok and mini_ok), fullscreen=fs_ok, mini=mini_ok)

        # 4. cinema: camera framing the TV, blur, movement held; exit restores the normal camera
        self.press(ctl, "press-Alice-CinemaButton")
        _, st = self.wait_for(ctl, lambda s: view(s).get("cinema_enabled") and view(s).get("camera_type") == "Scriptable",
                              20, "cinema on")
        v = view(st)
        t = math.tan(math.radians(70) / 2)
        want = max(4.5 / (t * (1 - 2 * 0.08)), 8 / (t * 1280 / 720)) / 0.96
        cinema_ok = (abs(v["camera_distance"] - want) < 0.05 and v["camera_aim"] > 0.9999 and v["blur"]
                     and v["movement_held"])
        self.press(ctl, "key-Alice-C")
        _, st = self.wait_for(ctl, lambda s: not view(s).get("cinema_enabled") and view(s).get("camera_type") == "Custom",
                              20, "cinema off")
        v2 = view(st)
        self.check("E2E-26", "cinema: camera looks straight at the TV from the distance that frames it between the "
                   "bars, background blurred, movement held; leaving restores the player's camera",
                   cinema_ok and not v2["blur"] and not v2["movement_held"],
                   camera_distance=round(v["camera_distance"], 3), want=round(want, 3), aim=v["camera_aim"])
        # 5. Alice hides the screen for herself: no pixel kept, the server sends her nothing; showing again is exact
        self.press(ctl, "press-Alice-HideButton")
        _, st = self.wait_for(ctl, lambda s: "You hid" in (s["clients"]["Alice"].get("status_text") or ""), 20,
                              "Alice hid the screen")
        a = st["clients"]["Alice"]
        hid_ok = not a["picture_visible"] and a["image_w"] == 0 and "Show" in (view(st).get("hide_text") or "")
        time.sleep(0.5)
        recv0 = self.read_state(ctl)["clients"]["Alice"]["recv_bytes"]
        self.scene("B")
        (seq_b, _, _), _ = self.wait_match(ctl, store, ["Bob"], 30, "Bob follows while Alice hid it", after_seq=seq_a)
        time.sleep(1.0)
        got = self.read_state(ctl)["clients"]["Alice"]["recv_bytes"] - recv0
        self.press(ctl, "press-Alice-HideButton")
        (seq_b, _, _), _ = self.wait_match(ctl, store, ["Alice", "Bob"], 30, "Alice shows the screen again",
                                           after_seq=seq_a)
        self.check("E2E-28", "a player hides the screen for herself: picture and pixels dropped, the server stops sending "
                   "to her while the others update; showing it again resyncs to the exact current picture",
                   hid_ok and got < 1024, bytes_received_while_hidden=got)

        # 6. moderators: Bob (not one) cannot hide it; Alice (ModeratorUserIds) hides it for everyone and shows it again
        st = self.read_state(ctl)
        roles = (view(st).get("moderator_enabled"), st["clients"]["Bob"]["view"].get("moderator_enabled"))
        self.press(ctl, "fire-Bob-modhide")
        time.sleep(1.5)
        st = self.read_state(ctl)
        bob_denied = st["server"]["attributes"].get("Hidden") is not True and st["clients"]["Bob"]["picture_visible"]
        self.press(ctl, "press-Alice-ModHideButton")
        _, st = self.wait_for(ctl, lambda s: all("hidden by a moderator" in (s["clients"][n].get("status_text") or "")
                                                 for n in ("Alice", "Bob")), 20, "screen hidden for everyone")
        dropped = all(st["clients"][n]["image_w"] == 0 and not st["clients"][n]["picture_visible"] for n in ("Alice", "Bob"))
        polls0 = st["server"]["http_requests"]
        time.sleep(2.0)
        st = self.read_state(ctl)
        no_polls = st["server"]["http_requests"] == polls0
        show_text = view(st).get("moderator_text") or ""
        polls_hidden = st["server"]["http_requests"] - polls0
        self.press(ctl, "press-Alice-ModHideButton")
        (seq_c, _, _), _ = self.wait_match(ctl, store, ["Alice", "Bob"], 40, "screen shown again for everyone")
        # hidden again, and the owner stops sharing meanwhile: showing it must say "sharing is off" at once (not keep
        # the moderator message through an idle long-poll), and the next Start brings the exact picture back
        self.press(ctl, "press-Alice-ModHideButton")
        self.wait_for(ctl, lambda s: all("hidden by a moderator" in (s["clients"][n].get("status_text") or "")
                                         for n in ("Alice", "Bob")), 20, "screen hidden again")
        controller.stop()
        time.sleep(0.5)
        self.press(ctl, "press-Alice-ModHideButton")
        t_show = time.monotonic()
        self.wait_for(ctl, lambda s: all(s["clients"][n].get("status_text") == "Screen sharing is off"
                                         for n in ("Alice", "Bob")), 10, "'sharing is off' right after showing")
        show_to_off_s = round(time.monotonic() - t_show, 3)
        controller.start()
        (seq_c, _, _), _ = self.wait_match(ctl, store, ["Alice", "Bob"], 40, "screen shown again for everyone")
        self.check("E2E-29", "moderator kill switch: only listed moderators get the button and can use it (a forged "
                   "request is ignored); hiding drops every viewer's pixels and stops polling the PC; showing it again "
                   "restores the exact picture; showing it while sharing is off says so at once, and after Start the "
                   "exact picture returns",
                   roles == (True, False) and bob_denied and dropped and no_polls and "Show" in show_text
                   and show_to_off_s < 5, roles=list(roles), bob_denied=bob_denied, dropped=dropped,
                   polls_while_hidden=polls_hidden, show_to_sharing_off_s=show_to_off_s)
        return seq_c

    def scenario_imageapi(self) -> None:
        """A published game without "Allow Mesh / Image APIs": creating the EditableImage works, writing fails."""
        ctl = tempfile.mkdtemp(prefix="rlps-e2e-imageapi-", dir=self.out)
        token = secrets.token_urlsafe(32)
        store = server.FrameStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["low"])
        self.scene("A")
        controller.start()
        os.environ["RLPS_EMU_IMAGE_API_DISABLED"] = "1"
        try:
            emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl)
        finally:
            os.environ.pop("RLPS_EMU_IMAGE_API_DISABLED", None)
        try:
            open(os.path.join(ctl, "join-Ivy"), "w").close()
            _, st = self.wait_for(ctl, lambda s: "Allow Mesh / Image APIs" in (s["clients"].get("Ivy", {})
                                                                            .get("status_text") or ""), 40,
                                  "image API explanation on Ivy's TV")
            c = st["clients"]["Ivy"]
            time.sleep(2.0)
            c2 = self.read_state(ctl)["clients"]["Ivy"]
            self.check("E2E-30", "image API disabled (creation works, writing fails): the TV explains the owner setting "
                       "and the ID-verification requirement instead of a raw error, and does not retry every frame",
                       "ID-verified" in c["status_text"] and not c["picture_visible"]
                       and c2["images_created"] - c["images_created"] <= 1, text=c["status_text"],
                       images_created=c2["images_created"])
        finally:
            open(os.path.join(ctl, "quit"), "w").close()
            try:
                emu.wait(10)
            except subprocess.TimeoutExpired:
                emu.kill()
            controller.stop()
            service.close()
            shutil.copy(os.path.join(ctl, "emulator.log"), os.path.join(self.out, "emulator-imageapi.log"))

    def scenario_secretdomain(self) -> None:
        """The secret's domain must allow the tunnel host (Roblox refuses to attach it otherwise)."""
        token = secrets.token_urlsafe(32)
        store = server.FrameStore()
        service = server.FrameService(store, token, port=0)
        service.start()
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["low"])
        self.scene("A")
        controller.start()
        public = "https://word-word-word.trycloudflare.com"
        try:
            for domain, name in (("trycloudflare.com", "Dana"), ("*.trycloudflare.com", "Eve")):
                ctl = tempfile.mkdtemp(prefix="rlps-e2e-secretdomain-", dir=self.out)
                emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl, public_url=public,
                                          secret_domain=domain)
                try:
                    open(os.path.join(ctl, "join-" + name), "w").close()
                    if name == "Dana":
                        _, st = self.wait_for(ctl, lambda s: "*.trycloudflare.com" in (
                            s.get("clients", {}).get("Dana", {}).get("status_text") or ""), 40,
                            "domain hint on Dana's TV")
                        c = st["clients"]["Dana"]
                        bad = c
                    else:
                        self.wait_match(ctl, store, ["Eve"], 40, "Eve shows the desktop")
                finally:
                    open(os.path.join(ctl, "quit"), "w").close()
                    try:
                        emu.wait(10)
                    except subprocess.TimeoutExpired:
                        emu.kill()
                    shutil.copy(os.path.join(ctl, "emulator.log"),
                                os.path.join(self.out, f"emulator-secretdomain-{name}.log"))
            self.check("E2E-22", "secret domain without the wildcard: the TV names the host and the domain to enter, "
                       "no picture; with *.trycloudflare.com the picture appears",
                       "word-word-word.trycloudflare.com" in bad["status_text"] and not bad["picture_visible"]
                       and bad["pixel_writes"] == 0, text=bad["status_text"])
        finally:
            controller.stop()
            service.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(REPO, "build", "e2e"))
    ap.add_argument("--lune", default=shutil.which("lune") or "lune")
    ap.add_argument("--profile", choices=sorted(app.PROFILES), default=app.DEFAULT_PROFILE)
    ap.add_argument("--scenario", choices=["live", "quality", "scroll", "congestion", "pacing", "viewers", "badtoken",
                                           "secretdomain", "imageapi", "all"], default="all")
    ap.add_argument("--xvfb", action="store_true", help="start Xvfb even if DISPLAY is set")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    h = Harness(args, args.out)
    ok = True
    started = time.monotonic()
    try:
        h.start_display()
        h.start_painter()
        if args.scenario in ("live", "all"):
            h.scenario_live()
        if args.scenario in ("quality", "all"):
            h.scenario_quality()
        if args.scenario in ("scroll", "all"):
            h.scenario_scroll()
        if args.scenario in ("congestion", "all"):
            h.scenario_congestion()
        if args.scenario in ("pacing", "all"):
            h.scenario_pacing()
        if args.scenario in ("viewers", "all"):
            h.scenario_viewers()
        if args.scenario in ("badtoken", "all"):
            h.scenario_badtoken()
        if args.scenario in ("secretdomain", "all"):
            h.scenario_secretdomain()
        if args.scenario in ("imageapi", "all"):
            h.scenario_imageapi()
    except Failure as exc:
        ok = False
        print(f"E2E FAILED: {exc}", flush=True)
    except Exception:  # a harness/product exception is a failure too, never a silent pass
        import traceback
        ok = False
        traceback.print_exc()
        print("E2E FAILED: unexpected exception", flush=True)
    finally:
        h.close()
        report = {"ok": ok, "duration_s": round(time.monotonic() - started, 1), "checks": h.checks,
                  "metrics": h.metrics}
        with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(json.dumps({"ok": ok, "passed": sum(c["pass"] for c in h.checks), "checks": len(h.checks),
                          "metrics": h.metrics}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
