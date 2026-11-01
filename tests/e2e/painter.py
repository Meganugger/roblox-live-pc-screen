"""Test-only desktop content for the live pipeline test: a full-screen window that draws known scenes.

Prints ``size <W> <H>`` (real screen size) at startup, then reads one command per line on stdin:
``scene A`` | ``scene B`` | ``noise <seed>`` | ``quit`` and prints ``ready <scene>`` once the window system has drawn it, so the test knows
when the *real* screen shows the new content. Scene geometry is defined on a 1280x720 reference and scaled to the real
screen. Backends: python-xlib (Linux/Xvfb; the sandbox Python has no Tk) or tkinter (Windows/macOS). Never used by the
product.
"""

from __future__ import annotations

import sys
import time

REF_W, REF_H = 1280, 720
BACKGROUND = (20, 40, 120)
SCENES = {
    "A": {"rect": (100, 100, 400, 300), "color": (230, 30, 30)},
    "B": {"rect": (700, 250, 400, 350), "color": (30, 200, 60)},
    # scene A plus two small squares in opposite corners: a change whose bounding box is almost the whole screen
    "D": {"rect": (100, 100, 400, 300), "color": (230, 30, 30), "dots": ((40, 620, 24, 24), (1200, 40, 24, 24))},
}
DOT_COLOR = (250, 220, 40)
CHECKER = (560, 40, 160, 80, 8)  # x, y, w, h, cell: fine detail (text-like high-frequency content)
NOISE_RECT = (300, 150, 480, 320)  # "noise <seed>": smooth moving colours + grain here (forces lossy DCT tiles)
# "clock <n> <motion>": a 16-bit counter drawn as 16 black / white blocks (bit i = block i), for glass-to-glass latency
# measurements; motion=1 also animates NOISE_RECT (video-like load). Blocks are large so lossy tiles keep them readable.
MARKER = (40, 640, 40, 40, 16)  # x, y, block width, block height, bits (reference coordinates)


def noise_image(seed: int, w: int, h: int):
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([128 + 110 * np.sin((xx + 13 * seed) / 23), 128 + 110 * np.sin((yy - 7 * seed) / 17),
                    128 + 100 * np.sin((xx + yy + 11 * seed) / 31)], axis=2)
    img += np.random.default_rng(seed).normal(0, 10, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def page_image(offset: int, w: int, h: int):
    """A white page of black 'text' lines, scrolled down by ``offset`` screen pixels (deterministic)."""
    import numpy as np
    page_h = h * 4
    rng = np.random.default_rng(42)
    page = np.full((page_h, w, 3), 248, np.uint8)
    line_h, gap = max(8, h // 45), max(5, h // 70)
    for y in range(10, page_h - line_h, line_h + gap):
        x = 20
        while x < w - 40:
            word = int(rng.integers(3, 12)) * max(5, w // 160)
            page[y:y + line_h, x:min(w - 20, x + word)] = (20, 20, 30)
            page[y + line_h // 3:y + line_h // 3 + 2, x:min(w - 20, x + word):3] = (248, 248, 248)  # "letter" gaps
            x += word + max(6, w // 120)
    o = offset % (page_h - h)
    return np.ascontiguousarray(page[o:o + h])


def noise_geometry(w: int, h: int):
    x, y, rw, rh = NOISE_RECT
    sx, sy = w / REF_W, h / REF_H
    return round(x * sx), round(y * sy), round(rw * sx), round(rh * sy)


def marker_blocks(n: int, w: int, h: int):
    """(rgb, x, y, w, h) of the counter blocks for value ``n`` in real screen pixels."""
    sx, sy = w / REF_W, h / REF_H
    x0, y0, bw, bh, bits = MARKER
    for i in range(bits):
        rgb = (255, 255, 255) if (n >> i) & 1 else (0, 0, 0)
        yield rgb, round((x0 + i * bw) * sx), round(y0 * sy), round(bw * sx), round(bh * sy)


def shapes(name: str, w: int, h: int):
    """Yield (rgb, x, y, w, h) rectangles of a scene in real screen pixels, background first."""
    sx, sy = w / REF_W, h / REF_H
    yield BACKGROUND, 0, 0, w, h
    x, y, rw, rh = SCENES[name]["rect"]
    yield SCENES[name]["color"], round(x * sx), round(y * sy), round(rw * sx), round(rh * sy)
    for dx, dy, dw, dh in SCENES[name].get("dots", ()):
        yield DOT_COLOR, round(dx * sx), round(dy * sy), round(dw * sx), round(dh * sy)
    cx, cy, cw, ch, cell = CHECKER
    for yy in range(cy, cy + ch, cell):
        for xx in range(cx, cx + cw, cell):
            if ((xx - cx) // cell + (yy - cy) // cell) % 2 == 0:
                yield (255, 255, 255), round(xx * sx), round(yy * sy), max(1, round(cell * sx)), max(1, round(cell * sy))


class XlibBackend:
    def __init__(self):
        from Xlib import X, display

        self.d = display.Display()
        screen = self.d.screen()
        self.w, self.h = screen.width_in_pixels, screen.height_in_pixels
        self.cmap = screen.default_colormap
        self.win = screen.root.create_window(0, 0, self.w, self.h, 0, screen.root_depth, X.InputOutput,
                                             X.CopyFromParent, override_redirect=True,
                                             background_pixel=self.pixel(BACKGROUND))
        self.win.map()
        self.gc = self.win.create_gc()
        # images are uploaded into an off-screen pixmap first and then copied in one request, so a capture never
        # sees a half-drawn picture (a screen grab between two upload chunks would show a torn frame)
        self.pixmap = self.win.create_pixmap(self.w, self.h, screen.root_depth)
        self.pgc = self.pixmap.create_gc()

    def pixel(self, rgb):
        r, g, b = rgb
        return self.cmap.alloc_color(r * 257, g * 257, b * 257).pixel

    def draw(self, name: str) -> None:
        for rgb, x, y, w, h in shapes(name, self.w, self.h):
            self.gc.change(foreground=self.pixel(rgb))
            self.win.fill_rectangle(self.gc, x, y, w, h)
        self.d.sync()

    def _blit(self, img, x: int, y: int) -> None:
        """Upload an (h, w, 3) RGB image to the pixmap in chunks, then copy it to the window atomically."""
        from Xlib import X
        h, w = img.shape[:2]
        bgrx = bytearray(w * h * 4)
        bgrx[0::4], bgrx[1::4], bgrx[2::4] = img[..., 2].tobytes(), img[..., 1].tobytes(), img[..., 0].tobytes()
        rows = max(1, 60000 // (w * 4))  # stay below the X request size limit
        for r0 in range(0, h, rows):
            r1 = min(h, r0 + rows)
            self.pixmap.put_image(self.pgc, 0, r0, w, r1 - r0, X.ZPixmap, 24, 0, bytes(bgrx[r0 * w * 4:r1 * w * 4]))
        self.win.copy_area(self.gc, self.pixmap, 0, 0, w, h, x, y)
        self.d.sync()

    def noise(self, seed: int) -> None:
        self.draw("A")
        x, y, w, h = noise_geometry(self.w, self.h)
        self._blit(noise_image(seed, w, h), x, y)

    def page(self, offset: int) -> None:
        self._blit(page_image(offset, self.w, self.h), 0, 0)

    def clock(self, n: int, motion: bool) -> None:
        if motion:
            x, y, w, h = noise_geometry(self.w, self.h)
            self._blit(noise_image(n, w, h), x, y)
        for rgb, x, y, w, h in marker_blocks(n, self.w, self.h):
            self.gc.change(foreground=self.pixel(rgb))
            self.win.fill_rectangle(self.gc, x, y, w, h)
        self.d.sync()

    def close(self) -> None:
        self.win.destroy()
        self.d.sync()


class TkBackend:
    def __init__(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.w, self.h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.overrideredirect(True)
        self.root.geometry(f"{self.w}x{self.h}+0+0")
        self.root.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.root.update()

    def draw(self, name: str) -> None:
        self.canvas.delete("all")
        for (r, g, b), x, y, w, h in shapes(name, self.w, self.h):
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.canvas.create_rectangle(x, y, x + w, y + h, fill=color, outline="")
        self.root.update()
        time.sleep(0.15)  # let the compositor present the frame before reporting "ready"

    def noise(self, seed: int) -> None:
        import tkinter as tk
        self.draw("A")
        x, y, w, h = noise_geometry(self.w, self.h)
        img = noise_image(seed, w, h)
        self._photo = tk.PhotoImage(data=b"P6 %d %d 255 " % (w, h) + img.tobytes(), format="PPM")
        self.canvas.create_image(x, y, image=self._photo, anchor="nw")
        self.root.update()
        time.sleep(0.15)

    def page(self, offset: int) -> None:
        import tkinter as tk
        img = page_image(offset, self.w, self.h)
        self.canvas.delete("all")
        self._photo = tk.PhotoImage(data=b"P6 %d %d 255 " % (self.w, self.h) + img.tobytes(), format="PPM")
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        self.root.update()
        time.sleep(0.15)

    def close(self) -> None:
        self.root.destroy()


def main() -> int:
    try:
        backend = XlibBackend() if sys.platform.startswith("linux") else TkBackend()
    except ImportError:
        backend = TkBackend()
    print(f"size {backend.w} {backend.h}", flush=True)
    for line in sys.stdin:
        cmd = line.split()
        if not cmd:
            continue
        if cmd[0] == "quit":
            break
        if cmd[0] == "scene" and len(cmd) == 2 and cmd[1] in SCENES:
            backend.draw(cmd[1])
            print(f"ready {cmd[1]}", flush=True)
        elif cmd[0] == "page" and len(cmd) == 2 and cmd[1].isdigit():
            backend.page(int(cmd[1]))
            print(f"ready page{cmd[1]}", flush=True)
        elif cmd[0] == "clock" and len(cmd) == 3 and cmd[1].isdigit() and cmd[2] in ("0", "1") \
                and hasattr(backend, "clock"):
            backend.clock(int(cmd[1]), cmd[2] == "1")
            print(f"ready clock{cmd[1]}", flush=True)
        elif cmd[0] == "noise" and len(cmd) == 2 and cmd[1].isdigit():
            backend.noise(int(cmd[1]))
            print(f"ready noise{cmd[1]}", flush=True)
    backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
