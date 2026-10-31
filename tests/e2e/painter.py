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
}
CHECKER = (560, 40, 160, 80, 8)  # x, y, w, h, cell: fine detail (text-like high-frequency content)
NOISE_RECT = (300, 150, 480, 320)  # "noise <seed>": smooth moving colours + grain here (forces lossy DCT tiles)


def noise_image(seed: int, w: int, h: int):
    import numpy as np
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([128 + 110 * np.sin((xx + 13 * seed) / 23), 128 + 110 * np.sin((yy - 7 * seed) / 17),
                    128 + 100 * np.sin((xx + yy + 11 * seed) / 31)], axis=2)
    img += np.random.default_rng(seed).normal(0, 10, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def noise_geometry(w: int, h: int):
    x, y, rw, rh = NOISE_RECT
    sx, sy = w / REF_W, h / REF_H
    return round(x * sx), round(y * sy), round(rw * sx), round(rh * sy)


def shapes(name: str, w: int, h: int):
    """Yield (rgb, x, y, w, h) rectangles of a scene in real screen pixels, background first."""
    sx, sy = w / REF_W, h / REF_H
    yield BACKGROUND, 0, 0, w, h
    x, y, rw, rh = SCENES[name]["rect"]
    yield SCENES[name]["color"], round(x * sx), round(y * sy), round(rw * sx), round(rh * sy)
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

    def pixel(self, rgb):
        r, g, b = rgb
        return self.cmap.alloc_color(r * 257, g * 257, b * 257).pixel

    def draw(self, name: str) -> None:
        for rgb, x, y, w, h in shapes(name, self.w, self.h):
            self.gc.change(foreground=self.pixel(rgb))
            self.win.fill_rectangle(self.gc, x, y, w, h)
        self.d.sync()

    def noise(self, seed: int) -> None:
        from Xlib import X
        self.draw("A")
        x, y, w, h = noise_geometry(self.w, self.h)
        img = noise_image(seed, w, h)
        bgrx = bytearray(w * h * 4)
        bgrx[0::4], bgrx[1::4], bgrx[2::4] = img[..., 2].tobytes(), img[..., 1].tobytes(), img[..., 0].tobytes()
        rows = max(1, 60000 // (w * 4))  # stay below the X request size limit
        for r0 in range(0, h, rows):
            r1 = min(h, r0 + rows)
            self.win.put_image(self.gc, x, y + r0, w, r1 - r0, X.ZPixmap, 24, 0, bytes(bgrx[r0 * w * 4:r1 * w * 4]))
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
        elif cmd[0] == "noise" and len(cmd) == 2 and cmd[1].isdigit():
            backend.noise(int(cmd[1]))
            print(f"ready noise{cmd[1]}", flush=True)
    backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
