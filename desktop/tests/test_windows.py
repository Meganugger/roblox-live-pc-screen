"""Window / browser-tab capture (rlps.windows): logic with a fake Win32 layer everywhere, real capture on Windows.

The Windows tests (skipped elsewhere; they run in the CI job "Python tests (windows-latest)"):
* a real Tk window is found by title and captured with PrintWindow, even while another window covers it, and the
  content crop drops its title bar; minimizing and closing it are reported;
* if Google Chrome or Microsoft Edge is installed, a page is opened in a new browser window and shared as a tab: the
  crop contains only the page (no tab strip / address bar), and sharing pauses when another tab is shown.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import numpy as np

from rlps import app, capture, windows
from rlps.capture import CaptureError


class FakeApi:
    """Windows of solid colours: each window image is (frame + 8 px invisible border); content = frame minus a 30 px
    title bar."""

    def __init__(self):
        self.wins = {}  # hwnd -> dict(title, process, frame, color, minimized, black)

    def add(self, hwnd, title, frame, color=(10, 20, 30), process="app.exe", black=False):
        self.wins[hwnd] = dict(title=title, process=process, frame=frame, color=color, minimized=False, black=black)

    def windows(self):
        return [windows.WindowInfo(h, w["title"], w["process"], w["frame"]) for h, w in self.wins.items()]

    def is_window(self, h):
        return h in self.wins

    def is_minimized(self, h):
        return self.wins[h]["minimized"]

    def title(self, h):
        return self.wins[h]["title"]

    def frame_rect(self, h):
        return self.wins[h]["frame"]

    def content_rect(self, h):
        l, t, r, b = self.wins[h]["frame"]
        return l, t + 30, r, b

    def print_window(self, h):
        w = self.wins[h]
        l, t, r, b = w["frame"]
        origin = (l - 8, t - 8, r + 8, b + 8)
        img = np.zeros((origin[3] - origin[1], origin[2] - origin[0], 4), np.uint8)
        if not w["black"]:
            img[8:-8, 8:-8, :3] = w["color"]  # BGR
            img[8:38, 8:-8, :3] = (200, 200, 200)  # title bar
        return img, origin


class MatchAndTitleTests(unittest.TestCase):
    def test_match_by_title_process_and_hwnd_topmost_first(self):
        ws = [windows.WindowInfo(5, "Report.docx - Word", "winword.exe", (0, 0, 10, 10)),
              windows.WindowInfo(7, "Video - YouTube - Google Chrome", "chrome.exe", (0, 0, 10, 10)),
              windows.WindowInfo(9, "Other report", "notepad.exe", (0, 0, 10, 10))]
        self.assertEqual(windows.match(ws, "REPORT").hwnd, 5)  # case-insensitive, topmost first
        self.assertEqual(windows.match(ws, "chrome.exe").hwnd, 7)
        self.assertEqual(windows.match(ws, "hwnd:9").hwnd, 9)
        self.assertEqual(windows.match(ws, "hwnd:0x7").hwnd, 7)
        self.assertIsNone(windows.match(ws, "hwnd:zz"))
        self.assertIsNone(windows.match(ws, "excel.exe"))
        self.assertIsNone(windows.match(ws, "nothing like it"))

    def test_tab_query_strips_the_browser_name(self):
        q = windows.tab_query
        self.assertEqual(q("Video - YouTube - Google Chrome"), "Video - YouTube")
        self.assertEqual(q("Docs — Mozilla Firefox"), "Docs")
        self.assertEqual(q("Inbox - Personal - Microsoft\u200b Edge"), "Inbox")
        self.assertEqual(q("Notes - Brave"), "Notes")
        self.assertEqual(q("Untitled - Notepad"), "Untitled - Notepad")  # not a browser: unchanged


class WindowSourceTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.api.add(11, "Cat video - YouTube - Google Chrome", (100, 50, 420, 290), color=(128, 0, 255))
        self.api.add(12, "Mail", (0, 0, 200, 100), color=(0, 255, 0))

    def test_window_frame_crop_drops_the_invisible_border(self):
        src = windows.WindowSource("youtube", api=self.api)
        img = src.grab_bgra()
        self.assertEqual(img.shape, (240, 320, 4))
        self.assertTrue(np.array_equal(img[-1, -1, :3], [128, 0, 255]))
        self.assertTrue(np.array_equal(img[0, 0, :3], [200, 200, 200]))  # title bar kept for a window
        self.assertEqual(src.geometry, {"left": 100, "top": 50, "width": 320, "height": 240})

    def test_tab_mode_crops_to_the_page_and_pauses_on_another_tab(self):
        src = capture.make_source(tab="Cat video")
        src._api = self.api
        img = src.grab_bgra()
        self.assertEqual(img.shape[:2], (210, 320))  # title bar / toolbar removed
        self.assertTrue((img[..., :3] == [128, 0, 255]).all())
        self.api.wins[11]["title"] = "Bank - Google Chrome"  # the user switched tabs
        with self.assertRaises(CaptureError) as cm:
            src.grab_bgra()
        self.assertIn("paused", str(cm.exception))
        self.api.wins[11]["title"] = "Cat video - YouTube - Google Chrome"
        self.assertEqual(src.grab_bgra().shape[:2], (210, 320))

    def test_follows_moves_and_resizes(self):
        src = windows.WindowSource("Mail", api=self.api)
        self.assertEqual(src.grab_bgra().shape[:2], (100, 200))
        self.api.wins[12]["frame"] = (300, 300, 700, 520)
        self.assertEqual(src.grab_bgra().shape[:2], (220, 400))

    def test_minimized_closed_and_missing_windows(self):
        src = windows.WindowSource("Mail", api=self.api)
        src.grab_bgra()
        self.api.wins[12]["minimized"] = True
        with self.assertRaisesRegex(CaptureError, "minimized"):
            src.grab_bgra()
        del self.api.wins[12]
        with self.assertRaisesRegex(CaptureError, "closed"):
            src.grab_bgra()
        with self.assertRaisesRegex(CaptureError, "no window matches"):
            src.grab_bgra()  # looks it up again: gone
        with self.assertRaises(CaptureError):
            windows.WindowSource("  ", api=self.api)

    def test_black_window_falls_back_to_its_screen_area(self):
        self.api.add(13, "Game", (10, 10, 74, 58), black=True)
        grabbed = []

        def screen(rect):
            grabbed.append(rect)
            return np.full((rect[3] - rect[1], rect[2] - rect[0], 4), 77, np.uint8)

        src = windows.WindowSource("Game", api=self.api, screen_grab=screen)
        img = src.grab_bgra()
        self.assertEqual(grabbed, [(10, 10, 74, 58)])
        self.assertTrue((img == 77).all())

    def test_source_choices_and_switching_the_shared_source(self):
        mons = [{"left": 0, "top": 0, "width": 3840, "height": 1080}, {"left": 0, "top": 0, "width": 1920,
                                                                       "height": 1080},
                {"left": 1920, "top": 0, "width": 1920, "height": 1080}]
        ch = app.source_choices(mons, self.api.windows())
        self.assertEqual([c.label for c in ch][:3], ["All monitors (3840x1080)", "Monitor 1 (1920x1080)",
                                                      "Monitor 2 (1920x1080)"])
        tab = ch[3]
        self.assertEqual((tab.kind, tab.window), ("window", "hwnd:11"))
        factory, label = tab.factory("mss", tab_only=True)
        self.assertEqual(label, "browser tab 'Cat video - YouTube'")
        src = factory()
        self.assertIsInstance(src, windows.WindowSource)
        self.assertTrue(src.content_only and src.follow_title)
        factory, label = tab.factory("mss")
        self.assertFalse(factory().follow_title)
        store = app.server.FrameStore()
        ctl = app.SharingController(store, lambda: None, app.PROFILES["low"], "monitor 1")
        ctl.set_source(factory, label)
        self.assertEqual(ctl.source_label, label)
        self.assertIn("source: window", ctl.status_text())


@unittest.skipUnless(sys.platform == "win32", "real window capture needs Windows")
class RealWindowsTests(unittest.TestCase):  # pragma: no cover - Windows CI
    def test_tk_window_captured_by_title_even_when_covered(self):
        import tkinter as tk

        title = "RLPS-WINDOW-TEST-" + uuid.uuid4().hex[:8]
        root = tk.Tk()
        root.title(title)
        root.geometry("320x200+120+120")
        root.configure(bg="#ff0080")
        cover = tk.Toplevel(root)
        cover.title("RLPS-COVER")
        cover.geometry("400x300+60+60")
        cover.configure(bg="#00ff00")
        cover.attributes("-topmost", True)
        for _ in range(20):
            root.update()
            time.sleep(0.05)
        try:
            info = windows.match(windows.list_windows(), title)
            self.assertIsNotNone(info)
            api = windows.Win32()
            raw, origin = api.print_window(info.hwnd)
            stats = f"raw {raw.shape} mean {raw[..., :3].mean(axis=(0, 1)).round(1)} origin {origin} " \
                    f"frame {api.frame_rect(info.hwnd)} content {api.content_rect(info.hwnd)} title {info.title!r}"
            src = windows.WindowSource(title, content_only=True)
            img = src.grab_bgra()
            self.assertFalse(src.fallback, "PrintWindow rendered black: " + stats)
            h, w = img.shape[:2]
            self.assertGreaterEqual((w, h), (300, 180))
            centre = img[h // 2, w // 2, :3].astype(int)  # BGR of #ff0080
            self.assertTrue(np.abs(centre - [128, 0, 255]).max() <= 8, f"{centre} {stats}")
            self.assertTrue(np.abs(img[2, 2, :3].astype(int) - [128, 0, 255]).max() <= 8, "client area: no title bar")
            self.assertTrue(any(title in w.title for w in windows.list_windows()))
            root.iconify()
            for _ in range(10):
                root.update()
                time.sleep(0.05)
            with self.assertRaisesRegex(CaptureError, "minimized"):
                src.grab_bgra()
        finally:
            root.destroy()
        with self.assertRaisesRegex(CaptureError, "closed"):
            src.grab_bgra()

    def test_browser_tab_page_only_and_pause_on_other_tab(self):
        exe = next((p for p in (
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe")) if os.path.isfile(p)), None)
        if exe is None:
            self.skipTest("no Chromium browser installed")
        tag = "RLPS-TAB-" + uuid.uuid4().hex[:8]
        page = f"data:text/html,<title>{tag}</title><body style='margin:0;background:%23ff0080'></body>"
        profile = tempfile.mkdtemp(prefix="rlps-browser-")
        args = [exe, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate", "--window-position=50,50", "--window-size=900,700", "--new-window"]
        proc = subprocess.Popen(args + [page])
        try:
            deadline = time.monotonic() + 40
            info = None
            while time.monotonic() < deadline and info is None:
                info = windows.match(windows.list_windows(), tag)
                time.sleep(0.5)
            self.assertIsNotNone(info, "browser window did not appear")
            time.sleep(2.0)  # first paint
            src = windows.WindowSource(windows.tab_query(info.title), content_only=True, follow_title=True)
            img = src.grab_bgra()
            frame = windows.Win32().frame_rect(info.hwnd)
            self.assertLess(img.shape[0], frame[3] - frame[1] - 40, "page crop excludes tab strip + address bar")
            px = img[img.shape[0] // 2, img.shape[1] // 2, :3].astype(int)
            self.assertTrue(np.abs(px - [128, 0, 255]).max() <= 12, px)
            self.assertTrue(np.abs(img[3, 3, :3].astype(int) - [128, 0, 255]).max() <= 12, "top of the crop is page")
            # open another tab in the same window: the title changes, sharing pauses
            subprocess.Popen(args[:2] + ["data:text/html,<title>other</title><body>x</body>"])
            deadline = time.monotonic() + 20
            paused = False
            while time.monotonic() < deadline and not paused:
                try:
                    src.grab_bgra()
                except CaptureError as exc:
                    paused = "paused" in str(exc)
                time.sleep(0.5)
            self.assertTrue(paused, "sharing did not pause on another tab")
        finally:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            time.sleep(1.0)
            shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
