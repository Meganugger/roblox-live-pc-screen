"""Desktop capture: grab a monitor (or a fixed screen region) with ``mss`` and turn it into a small RGB frame.

``mss`` instances are not thread-safe and are bound to the thread that created them, so a :class:`MssSource` must be
opened, used and closed by the capture thread only. Monitor geometry is re-read every ``refresh_s`` seconds (and after
any grab error) so resolution changes and display switches are picked up without restarting.

Pixels leave this module only as (H, W, 3) uint8 RGB arrays that fit the active quality profile (<= 1024 px per side,
the EditableImage limit, F-0001). Nothing is written to disk.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from dataclasses import dataclass

import numpy as np

from . import protocol as P

log = logging.getLogger("rlps.capture")


class CaptureError(RuntimeError):
    """The screen could not be captured (no such monitor, desktop switched or locked, driver error)."""


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> Region:
        """Parse ``left,top,width,height`` (virtual-screen pixels)."""
        try:
            left, top, width, height = (int(v) for v in text.split(","))
        except ValueError:
            raise ValueError("region must be 'left,top,width,height'") from None
        if width < 1 or height < 1 or width > 16384 or height > 16384:
            raise ValueError("region width/height must be 1..16384")
        return cls(left, top, width, height)

    def as_mss(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


def fit_size(src_w: int, src_h: int, max_w: int, max_h: int, align: int = 1) -> tuple[int, int]:
    """Largest (w, h) <= (max_w, max_h) and <= MAX_DIM with the source aspect ratio; never upscales.

    ``align`` > 1 rounds both sides down to a multiple of it (hybrid frames need 16; the picture is scaled to fit,
    a deviation of at most align-1 pixels per side)."""
    if src_w < 1 or src_h < 1 or max_w < 1 or max_h < 1 or align < 1:
        raise ValueError("sizes must be positive")
    max_w, max_h = min(max_w, P.MAX_DIM), min(max_h, P.MAX_DIM)
    scale = min(max_w / src_w, max_h / src_h, 1.0)
    w, h = min(max_w, max(1, round(src_w * scale))), min(max_h, max(1, round(src_h * scale)))
    if align > 1:
        w, h = max(align, w // align * align), max(align, h // align * align)
    return w, h


def _bilinear(img: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Bilinear resample of an (H, W, C) array to (out_h, out_w, C) float32 (pixel-centre aligned)."""
    h, w = img.shape[:2]
    xs = np.clip((np.arange(out_w, dtype=np.float32) + 0.5) * (w / out_w) - 0.5, 0, w - 1)
    ys = np.clip((np.arange(out_h, dtype=np.float32) + 0.5) * (h / out_h) - 0.5, 0, h - 1)
    x0 = np.floor(xs).astype(np.intp)
    y0 = np.floor(ys).astype(np.intp)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    wx = (xs - x0)[None, :, None]
    wy = (ys - y0)[:, None, None]
    src = img.astype(np.float32, copy=False)
    top = src[y0][:, x0] * (1 - wx) + src[y0][:, x1] * wx
    bottom = src[y1][:, x0] * (1 - wx) + src[y1][:, x1] * wx
    return top * (1 - wy) + bottom * wy


def resize(img: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Downscale (H, W, C) uint8 to (out_h, out_w, C) uint8: integer box pre-reduction, then bilinear.

    The box stage averages whole k*k blocks (k = floor of the scale factor), which keeps thin text strokes visible;
    the bilinear stage covers the remaining factor (< 2). Up to k-1 edge rows/columns are dropped by the box stage."""
    h, w, c = img.shape
    if (w, h) == (out_w, out_h):
        return np.ascontiguousarray(img)
    fx, fy = max(1, w // out_w), max(1, h // out_h)
    work = img
    if fx > 1 or fy > 1:
        hh, ww = (h // fy) * fy, (w // fx) * fx
        work = img[:hh, :ww].reshape(hh // fy, fy, ww // fx, fx, c).mean(axis=(1, 3), dtype=np.float32)
    if work.shape[:2] != (out_h, out_w):
        work = _bilinear(work, out_w, out_h)
    return np.clip(work + 0.5, 0, 255).astype(np.uint8) if work.dtype != np.uint8 else work


def stream_size(src_w: int, src_h: int, max_w: int, max_h: int, align: int = 1) -> tuple[int, int, int, int]:
    """(content_w, content_h, frame_w, frame_h) for streaming a src_w x src_h screen.

    The content keeps the source aspect ratio; an *integer* downscale factor is preferred when it keeps >= 90 % of
    the width (integer area averaging maps scrolled content to identical pixels, so scrolling is sent as exact
    copies). With ``align`` > 1 the frame is the content letterboxed (black bars) to a multiple of ``align``."""
    cw, ch = fit_size(src_w, src_h, max_w, max_h)
    if (cw, ch) != (src_w, src_h):
        k = -(-src_w // cw) if src_w * ch >= src_h * cw else -(-src_h // ch)
        iw, ih = src_w // k, src_h // k
        while (iw > max_w or ih > max_h) and k < 64:
            k += 1
            iw, ih = src_w // k, src_h // k
        if iw >= 0.9 * cw and iw >= 1 and ih >= 1:
            cw, ch = iw, ih
    if align <= 1:
        return cw, ch, cw, ch
    fw = min(max(align, -(-cw // align) * align), max(align, min(max_w, P.MAX_DIM) // align * align))
    fh = min(max(align, -(-ch // align) * align), max(align, min(max_h, P.MAX_DIM) // align * align))
    return min(cw, fw), min(ch, fh), fw, fh


try:  # optional, much faster area-averaging resize (opencv-python-headless); numpy fallback otherwise
    import cv2 as _cv2
except ImportError:  # pragma: no cover - depends on the machine
    _cv2 = None


def bgra_to_rgb(bgra: np.ndarray, max_w: int, max_h: int, align: int = 1, use_cv2: bool = True) -> np.ndarray:
    """(H, W, 4) BGRA screen pixels -> contiguous (h, w, 3) RGB uint8 that fits (max_w, max_h)."""
    if bgra.ndim != 3 or bgra.shape[2] != 4 or bgra.dtype != np.uint8:
        raise ValueError(f"expected (H, W, 4) uint8 BGRA, got {bgra.shape} {bgra.dtype}")
    h, w = bgra.shape[:2]
    cw, ch, out_w, out_h = stream_size(w, h, max_w, max_h, align)
    if use_cv2 and _cv2 is not None:
        small = bgra if (w, h) == (cw, ch) else _cv2.resize(bgra, (cw, ch), interpolation=_cv2.INTER_AREA)
        rgb = _cv2.cvtColor(small, _cv2.COLOR_BGRA2RGB)
    else:
        small_bgr = resize(bgra[:, :, :3], cw, ch)  # resize first, reorder channels on the small image
        rgb = np.ascontiguousarray(small_bgr[:, :, ::-1])
    if (cw, ch) == (out_w, out_h):
        return rgb
    out = np.zeros((out_h, out_w, 3), np.uint8)  # letterbox: content centred, black bars
    y0, x0 = (out_h - ch) // 2, (out_w - cw) // 2
    out[y0:y0 + ch, x0:x0 + cw] = rgb
    return out


def _default_factory():
    try:
        import mss  # imported lazily: tests and the codec do not need it
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise CaptureError("the 'mss' package is required for screen capture (pip install mss)") from exc
    factory = getattr(mss, "MSS", None) or mss.mss  # mss >= 10 names the class MSS; mss.mss() is deprecated there
    return factory()


class MssSource:
    """One monitor (mss numbering: 1 = primary, 2… = others, 0 = all monitors combined) or a fixed region."""

    def __init__(self, monitor: int = 1, region: Region | None = None, *, factory=_default_factory,
                 refresh_s: float = 3.0, clock=time.monotonic):
        self.monitor, self.region = monitor, region
        self._factory, self._refresh_s, self._clock = factory, refresh_s, clock
        self._sct = None
        self._geom: dict | None = None
        self._opened_at = 0.0

    @property
    def geometry(self) -> dict | None:
        return dict(self._geom) if self._geom else None

    def open(self) -> None:
        self.close()
        try:
            sct = self._factory()
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureError(f"cannot initialise screen capture: {exc}") from exc
        try:
            monitors = list(sct.monitors)
            if self.region is not None:
                geom = self.region.as_mss()
            elif 0 <= self.monitor < len(monitors):
                m = monitors[self.monitor]
                geom = {k: int(m[k]) for k in ("left", "top", "width", "height")}
            else:
                raise CaptureError(f"monitor {self.monitor} not found (available: 0..{len(monitors) - 1})")
            if geom["width"] < 1 or geom["height"] < 1:
                raise CaptureError(f"monitor {self.monitor} has an empty area")
        except BaseException:
            sct.close()
            raise
        if geom != self._geom:
            log.info("capture area %s", geom)
        self._sct, self._geom, self._opened_at = sct, geom, self._clock()

    def grab_bgra(self) -> np.ndarray:
        """Capture once. Returns an (H, W, 4) uint8 BGRA view of the screen pixels (alpha is meaningless)."""
        if self._sct is None or self._clock() - self._opened_at >= self._refresh_s:
            self.open()
        try:
            shot = self._sct.grab(self._geom)
            w, h = shot.size
            data = np.frombuffer(shot.raw, np.uint8)
            if data.size != w * h * 4:
                raise CaptureError(f"unexpected capture buffer size {data.size} for {w}x{h}")
            return data.reshape(h, w, 4)
        except CaptureError:
            self.close()
            raise
        except Exception as exc:  # mss.exception.ScreenShotError, OSError (desktop switch, lock screen, UAC)
            self.close()
            raise CaptureError(f"screen grab failed: {exc}") from exc

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass
            self._sct = None


class DxgiSource:
    """Windows DXGI Desktop Duplication through the optional ``dxcam`` package: much faster than GDI and it also
    captures hardware-accelerated video. ``monitor`` uses mss numbering (1 = primary). Only whole monitors."""

    def __init__(self, monitor: int = 1):
        if monitor < 1:
            raise CaptureError("DXGI capture needs a single monitor (1, 2, …)")
        if importlib.util.find_spec("dxcam") is None:
            raise CaptureError("the optional 'dxcam' package is not installed (pip install dxcam)")
        self.monitor = monitor
        self._cam = None
        self._last: np.ndarray | None = None

    def _open(self):
        import dxcam
        try:
            self._cam = dxcam.create(output_idx=self.monitor - 1, output_color="BGRA")
        except Exception as exc:
            raise CaptureError(f"cannot initialise DXGI capture: {exc}") from exc
        if self._cam is None:
            raise CaptureError("DXGI capture is not available for this monitor")

    def grab_bgra(self) -> np.ndarray:
        if self._cam is None:
            self._open()
        try:
            frame = self._cam.grab()
        except Exception as exc:  # desktop switch, mode change, lost device
            self.close()
            raise CaptureError(f"DXGI grab failed: {exc}") from exc
        if frame is None:  # dxcam returns None when the screen did not change since the last grab
            if self._last is None:
                for _ in range(10):
                    time.sleep(0.01)
                    frame = self._cam.grab()
                    if frame is not None:
                        break
                if frame is None:
                    raise CaptureError("DXGI capture returned no frame")
            else:
                return self._last
        self._last = np.ascontiguousarray(frame)
        return self._last

    def close(self) -> None:
        if self._cam is not None:
            try:
                self._cam.release()
            except Exception:  # pragma: no cover - best effort cleanup
                pass
            self._cam = None
        self._last = None


def make_source(backend: str = "auto", monitor: int = 1, region: Region | None = None):
    """``mss`` (GDI/X11/Quartz), ``dxgi`` (dxcam), or ``auto``: DXGI on Windows when available, otherwise mss."""
    if backend not in ("auto", "mss", "dxgi"):
        raise ValueError(f"unknown capture backend {backend!r}")
    if backend == "dxgi" or (backend == "auto" and sys.platform == "win32" and region is None and monitor >= 1):
        try:
            src = DxgiSource(monitor)
            src.grab_bgra()  # fail now (and fall back) rather than in the capture loop
            src.close()  # reopened lazily by the capture thread that uses it
            return src
        except CaptureError as exc:
            if backend == "dxgi":
                raise
            log.info("DXGI capture unavailable (%s); using mss", exc)
    return MssSource(monitor, region)


def list_monitors(factory=_default_factory) -> list[dict]:
    """Monitor geometries as reported by mss (index 0 = all monitors combined)."""
    sct = factory()
    try:
        return [{k: int(m[k]) for k in ("left", "top", "width", "height")} for m in sct.monitors]
    finally:
        sct.close()
