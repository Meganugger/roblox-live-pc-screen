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
        self.painter.stdin.write(f"scene {name}\n")
        self.painter.stdin.flush()
        line = self.painter.stdout.readline().strip()
        if line != f"ready {name}":
            raise Failure(f"painter answered {line!r}")
        return time.monotonic()

    def start_emulator(self, base_url: str, token: str, ctl: str, attrs: dict | None = None) -> subprocess.Popen:
        env = dict(os.environ, RLPS_REPO=REPO, RLPS_OUT=ctl, RLPS_BASE_URL=base_url, RLPS_TOKEN=token,
                   RLPS_PUBLIC_URL="https://rlps-e2e.test", RLPS_MAX_SECONDS="240")
        env.update({f"RLPS_ATTR_{k}": str(v) for k, v in (attrs or {}).items()})
        log = open(os.path.join(ctl, "emulator.log"), "w")
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
    def read_state(ctl: str) -> dict:
        try:
            with open(os.path.join(ctl, "state.json"), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):  # missing, or being replaced right now (Windows: PermissionError)
            return {}

    def wait_for(self, ctl: str, pred, timeout: float, what: str):
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            st = self.read_state(ctl)
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
        with store._cond:  # test-only access to the newest published frame
            seq = store.seq
            q = store._frames.get(seq)
            fmt = store.fmt
        if q is None:
            return seq, "", np.zeros((0, 0, 4), np.uint8)
        rgba = codec.expand_to_rgba(q, fmt)
        return seq, hashlib.sha256(rgba.tobytes()).hexdigest(), rgba

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
            if other != scene:
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
        emu = self.start_emulator(f"http://127.0.0.1:{port}", token, ctl)
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
                       (a["image_w"], a["image_h"]) == capture.fit_size(*self.screen, profile.max_w,
                                                                        profile.max_h),
                       size=[a["image_w"], a["image_h"]])
            snap = self.snapshot(ctl, "sceneA", ["Alice"], a["image_w"], a["image_h"])
            self.check("E2E-05", "snapshot pixels == expected frame", np.array_equal(snap["Alice"], rgba))
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
                       store.seq == 0 and not store._frames and self.metrics["stop_to_tv_off_s"] < 5,
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
        controller = app.SharingController(store, lambda: capture.MssSource(1, None), app.PROFILES["balanced"])
        self.scene("A")
        controller.start()
        emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl,
                                  {"MaxBytesPerSecond": budget})
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
        emu = self.start_emulator(f"http://127.0.0.1:{service.address[1]}", token, ctl, {"ViewerUserIds": "1001"})
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
            m = self.read_state(ctl)["clients"]["Mallory"]
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=os.path.join(REPO, "build", "e2e"))
    ap.add_argument("--lune", default=shutil.which("lune") or "lune")
    ap.add_argument("--profile", choices=sorted(app.PROFILES), default="balanced")
    ap.add_argument("--scenario", choices=["live", "pacing", "viewers", "badtoken", "all"], default="all")
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
        if args.scenario in ("pacing", "all"):
            h.scenario_pacing()
        if args.scenario in ("viewers", "all"):
            h.scenario_viewers()
        if args.scenario in ("badtoken", "all"):
            h.scenario_badtoken()
    except Failure as exc:
        ok = False
        print(f"E2E FAILED: {exc}", flush=True)
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
