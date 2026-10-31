"""Capture one window — an app, or the browser window showing a tab — instead of a whole monitor (Windows).

``PrintWindow(hwnd, PW_RENDERFULLCONTENT)`` (Windows 8.1+) renders the window's own pixels, so other windows covering it
are *not* shared, and it works for hardware-accelerated apps such as Chromium browsers. When an app answers with an
all-black picture (some DirectX / protected content), the window's on-screen rectangle is grabbed instead (other
windows overlapping it would then be visible: a warning is logged once).

* **Window** (``--window QUERY``): the topmost visible window whose title contains QUERY (case-insensitive), or whose
  process is QUERY (``chrome.exe``), or ``hwnd:<number>``. The capture follows the window when it moves or resizes.
* **Browser tab** (``--tab QUERY``): the browser window whose active tab title contains QUERY, cropped to the page
  (Chromium's ``Chrome_RenderWidgetHostHWND`` child; other apps: the client area). Sharing **pauses** while the
  window shows another tab (its title no longer contains QUERY): other tabs are never shared.

All Win32 calls go through :class:`Win32`; tests substitute a fake with the same methods.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass

import numpy as np

from .capture import CaptureError

log = logging.getLogger("rlps.windows")

PW_RENDERFULLCONTENT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
CHROMIUM_CONTENT_CLASS = "Chrome_RenderWidgetHostHWND"

Rect = tuple[int, int, int, int]  # left, top, right, bottom (screen pixels)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process: str  # executable name, lower case ("chrome.exe"); "" when unknown
    rect: Rect  # visible frame on screen


class Win32:  # pragma: no cover - exercised on Windows (desktop/tests/test_windows.py runs there in CI)
    """Thin ctypes layer over user32 / gdi32 / dwmapi / kernel32."""

    def __init__(self):
        if sys.platform != "win32":
            raise CaptureError("window capture is only available on Windows")
        import ctypes
        from ctypes import wintypes as wt

        self.ct, self.wt = ctypes, wt
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            self.dwm = ctypes.WinDLL("dwmapi")
        except OSError:
            self.dwm = None
        try:
            self.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: real pixel sizes
        except (AttributeError, OSError):
            pass
        u, g = self.user32, self.gdi32
        self.ENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        u.EnumWindows.argtypes = [self.ENUMPROC, wt.LPARAM]
        u.EnumChildWindows.argtypes = [wt.HWND, self.ENUMPROC, wt.LPARAM]
        for name in ("IsWindowVisible", "IsWindow", "IsIconic"):
            getattr(u, name).argtypes = [wt.HWND]
        u.GetWindowTextLengthW.argtypes = [wt.HWND]
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
        u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
        u.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
        u.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
        u.GetDC.argtypes = [wt.HWND]
        u.GetDC.restype = wt.HDC
        u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        g.CreateCompatibleDC.argtypes = [wt.HDC]
        g.CreateCompatibleDC.restype = wt.HDC
        g.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                       wt.DWORD]
        g.CreateDIBSection.restype = wt.HBITMAP
        g.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        g.SelectObject.restype = wt.HGDIOBJ
        g.DeleteObject.argtypes = [wt.HGDIOBJ]
        g.DeleteDC.argtypes = [wt.HDC]
        k = self.kernel32
        k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        k.OpenProcess.restype = wt.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        k.CloseHandle.argtypes = [wt.HANDLE]

    # ---- queries
    def _text(self, fn, hwnd, size=512) -> str:
        buf = self.ct.create_unicode_buffer(size)
        fn(hwnd, buf, size)
        return buf.value

    def title(self, hwnd: int) -> str:
        n = self.user32.GetWindowTextLengthW(hwnd)
        return self._text(self.user32.GetWindowTextW, hwnd, n + 1) if n > 0 else ""

    def is_window(self, hwnd: int) -> bool:
        return bool(self.user32.IsWindow(hwnd))

    def is_minimized(self, hwnd: int) -> bool:
        return bool(self.user32.IsIconic(hwnd))

    def window_rect(self, hwnd: int) -> Rect:
        r = self.wt.RECT()
        if not self.user32.GetWindowRect(hwnd, self.ct.byref(r)):
            raise CaptureError("cannot read the window position")
        return r.left, r.top, r.right, r.bottom

    def frame_rect(self, hwnd: int) -> Rect:
        """Visible frame (without the invisible resize borders of Windows 10/11)."""
        if self.dwm is not None:
            r = self.wt.RECT()
            if self.dwm.DwmGetWindowAttribute(self.wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, self.ct.byref(r),
                                              self.ct.sizeof(r)) == 0:
                return r.left, r.top, r.right, r.bottom
        return self.window_rect(hwnd)

    def content_rect(self, hwnd: int) -> Rect:
        """Browser page area (Chromium render widget) or, for other apps, the client area — screen coordinates."""
        found: list[int] = []

        def visit(child, _lparam):
            if self._text(self.user32.GetClassNameW, child, 256) == CHROMIUM_CONTENT_CLASS and \
                    self.user32.IsWindowVisible(child):
                found.append(child)
            return True

        self.user32.EnumChildWindows(hwnd, self.ENUMPROC(visit), 0)
        best = None
        for child in found:  # the largest visible render widget is the page (others: popups, side panels)
            r = self.window_rect(child)
            if best is None or (r[2] - r[0]) * (r[3] - r[1]) > (best[2] - best[0]) * (best[3] - best[1]):
                best = r
        if best is not None:
            return best
        cr = self.wt.RECT()
        self.user32.GetClientRect(hwnd, self.ct.byref(cr))
        p = self.wt.POINT(0, 0)
        self.user32.ClientToScreen(hwnd, self.ct.byref(p))
        return p.x, p.y, p.x + cr.right, p.y + cr.bottom

    def process_name(self, hwnd: int) -> str:
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ct.byref(pid))
        h = self.kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ""
        try:
            buf = self.ct.create_unicode_buffer(1024)
            n = self.wt.DWORD(1024)
            if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, self.ct.byref(n)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            self.kernel32.CloseHandle(h)

    def _shown(self, hwnd: int) -> bool:
        if not self.user32.IsWindowVisible(hwnd) or self.user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return False
        if self.dwm is not None:  # cloaked = on another virtual desktop / a suspended UWP app
            cloaked = self.wt.DWORD()
            if self.dwm.DwmGetWindowAttribute(self.wt.HWND(hwnd), DWMWA_CLOAKED, self.ct.byref(cloaked),
                                              self.ct.sizeof(cloaked)) == 0 and cloaked.value:
                return False
        return True

    def windows(self) -> list[WindowInfo]:
        """Visible top-level windows with a title, topmost first (EnumWindows z-order)."""
        hwnds: list[int] = []
        self.user32.EnumWindows(self.ENUMPROC(lambda h, _l: hwnds.append(h) or True), 0)
        out = []
        for h in hwnds:
            if self._shown(h):
                t = self.title(h)
                if t:
                    try:
                        out.append(WindowInfo(int(h), t, self.process_name(h), self.frame_rect(h)))
                    except CaptureError:
                        continue
        return out

    # ---- pixels
    def print_window(self, hwnd: int) -> tuple[np.ndarray, Rect]:
        """The whole window (GetWindowRect area) as BGRA, rendered by the window itself; plus that rectangle."""
        left, top, right, bottom = self.window_rect(hwnd)
        w, h = right - left, bottom - top
        if w < 1 or h < 1:
            raise CaptureError("the shared window has no area")
        ct = self.ct

        class BITMAPINFOHEADER(ct.Structure):
            _fields_ = [("biSize", ct.c_uint32), ("biWidth", ct.c_int32), ("biHeight", ct.c_int32),
                        ("biPlanes", ct.c_uint16), ("biBitCount", ct.c_uint16), ("biCompression", ct.c_uint32),
                        ("biSizeImage", ct.c_uint32), ("biXPelsPerMeter", ct.c_int32),
                        ("biYPelsPerMeter", ct.c_int32), ("biClrUsed", ct.c_uint32), ("biClrImportant", ct.c_uint32)]

        bih = BITMAPINFOHEADER(ct.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down 32 bpp
        screen = self.user32.GetDC(None)
        mem = self.gdi32.CreateCompatibleDC(screen)
        bits = ct.c_void_p()
        bmp = self.gdi32.CreateDIBSection(mem, ct.byref(bih), 0, ct.byref(bits), None, 0)
        if not bmp:
            self.gdi32.DeleteDC(mem)
            self.user32.ReleaseDC(None, screen)
            raise CaptureError("cannot allocate the window capture bitmap")
        old = self.gdi32.SelectObject(mem, bmp)
        try:
            if not self.user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT):
                raise CaptureError("PrintWindow failed for the shared window")
            data = np.ctypeslib.as_array(ct.cast(bits, ct.POINTER(ct.c_uint8)), shape=(h, w, 4)).copy()
        finally:
            self.gdi32.SelectObject(mem, old)
            self.gdi32.DeleteObject(bmp)
            self.gdi32.DeleteDC(mem)
            self.user32.ReleaseDC(None, screen)
        return data, (left, top, right, bottom)


def match(windows: list[WindowInfo], query: str) -> WindowInfo | None:
    """First (topmost) window matching QUERY: ``hwnd:<n>``, an executable name, or a title substring."""
    q = query.strip()
    if q.lower().startswith("hwnd:"):
        try:
            want = int(q[5:], 0)
        except ValueError:
            return None
        return next((w for w in windows if w.hwnd == want), None)
    ql = q.lower()
    if ql.endswith(".exe"):
        return next((w for w in windows if w.process == ql), None)
    return next((w for w in windows if ql in w.title.lower()), None)


_BROWSER_SUFFIX = re.compile(r"\s+[-\u2013\u2014]\s+(Google Chrome|Chromium|Brave|Opera|Vivaldi|Mozilla Firefox|"
                             r"Firefox|Microsoft\u200b?\s?Edge)$")


def tab_query(window_title: str) -> str:
    """The active tab's title from a browser window title ("Video - YouTube - Google Chrome" -> "Video - YouTube";
    Edge: "Page - Profile 1 - Microsoft Edge" -> "Page")."""
    t = window_title.strip()
    m = _BROWSER_SUFFIX.search(t)
    if not m:
        return t
    t = t[:m.start()]
    if "Edge" in m.group(1) and " - " in t:  # Edge inserts " - <profile name>" before its name
        t = t.rsplit(" - ", 1)[0]
    return t.strip() or window_title.strip()


def _crop(img: np.ndarray, origin: Rect, want: Rect) -> np.ndarray:
    """Crop `img` (covering `origin` on screen) to the screen rectangle `want`, clamped to the image."""
    x0, y0 = max(0, want[0] - origin[0]), max(0, want[1] - origin[1])
    x1 = min(img.shape[1], want[2] - origin[0])
    y1 = min(img.shape[0], want[3] - origin[1])
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise CaptureError("the shared area is empty (window moved off its content?)")
    return img[y0:y1, x0:x1]


class WindowSource:
    """Capture source for one window (``content_only`` = page / client area; ``follow_title`` = pause while the title
    no longer contains the query, i.e. the browser shows another tab). Same interface as ``capture.MssSource``."""

    def __init__(self, query: str, *, content_only: bool = False, follow_title: bool = False, api=None,
                 screen_grab=None):
        if not query.strip():
            raise CaptureError("empty window query")
        self.query, self.content_only, self.follow_title = query, content_only, follow_title
        self._api, self._screen_grab = api, screen_grab
        self.hwnd: int | None = None
        self.title = ""
        self.geometry: dict | None = None
        self._black_warned = False

    @property
    def api(self):
        if self._api is None:
            self._api = Win32()
        return self._api

    def open(self) -> None:
        w = match(self.api.windows(), self.query)
        if w is None:
            raise CaptureError(f"no window matches {self.query!r} (python -m rlps.app --list-windows)")
        self.hwnd, self.title = w.hwnd, w.title
        log.info("sharing window %r (%s, hwnd %d)", w.title, w.process or "?", w.hwnd)

    def grab_bgra(self) -> np.ndarray:
        if self.hwnd is None:
            self.open()
        api, hwnd = self.api, self.hwnd
        if not api.is_window(hwnd):
            self.hwnd = None
            raise CaptureError("the shared window was closed")
        if api.is_minimized(hwnd):
            raise CaptureError("the shared window is minimized (restore it to continue)")
        title = api.title(hwnd)
        if self.follow_title and self.query.lower() not in title.lower():
            raise CaptureError(f"paused: the window no longer shows {self.query!r} (switch back to that tab)")
        self.title = title
        img, origin = api.print_window(hwnd)
        want = api.content_rect(hwnd) if self.content_only else api.frame_rect(hwnd)
        out = _crop(img, origin, want)
        if not out[..., :3].any():  # all black: the app does not render for PrintWindow
            grab = self._screen_grab or _mss_grab
            if not self._black_warned:
                self._black_warned = True
                log.warning("the window renders black for PrintWindow; capturing its screen area instead (windows on "
                            "top of it become visible)")
            out = grab(want)
        self.geometry = {"left": want[0], "top": want[1], "width": want[2] - want[0], "height": want[3] - want[1]}
        return np.ascontiguousarray(out)

    def close(self) -> None:
        pass


def _mss_grab(rect: Rect) -> np.ndarray:  # pragma: no cover - Windows fallback path
    from .capture import MssSource, Region

    src = MssSource(region=Region(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]))
    try:
        return src.grab_bgra().copy()
    finally:
        src.close()


def list_windows(api=None) -> list[WindowInfo]:
    return (api or Win32()).windows()
