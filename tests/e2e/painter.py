"""Test-only desktop content for the live pipeline test: a full-screen X11 window that draws known scenes.

Reads one command per line on stdin: ``scene A`` | ``scene B`` | ``quit``. Prints ``ready <scene>`` after the X server
has processed the drawing (XSync), so the test knows when the *real* screen shows the new content. Uses python-xlib
(pure-Python X client) because the sandbox Python has no Tk. Never used by the product.
"""

from __future__ import annotations

import sys

from Xlib import X, display

# Scene geometry in screen pixels (the test converts it to captured-frame pixels).
BACKGROUND = (20, 40, 120)
SCENES = {
    "A": {"rect": (100, 100, 400, 300), "color": (230, 30, 30)},
    "B": {"rect": (700, 250, 400, 350), "color": (30, 200, 60)},
}
CHECKER = (560, 40, 160, 80, 8)  # x, y, w, h, cell: fine detail (text-like high-frequency content)


def main() -> int:
    d = display.Display()
    screen = d.screen()
    w, h = screen.width_in_pixels, screen.height_in_pixels
    cmap = screen.default_colormap

    def pixel(rgb):
        r, g, b = rgb
        return cmap.alloc_color(r * 257, g * 257, b * 257).pixel

    win = screen.root.create_window(0, 0, w, h, 0, screen.root_depth, X.InputOutput, X.CopyFromParent,
                                    override_redirect=True, background_pixel=pixel(BACKGROUND))
    win.map()
    gc = win.create_gc()

    def draw(name: str) -> None:
        gc.change(foreground=pixel(BACKGROUND))
        win.fill_rectangle(gc, 0, 0, w, h)
        x, y, rw, rh = SCENES[name]["rect"]
        gc.change(foreground=pixel(SCENES[name]["color"]))
        win.fill_rectangle(gc, x, y, rw, rh)
        cx, cy, cw, ch, cell = CHECKER
        gc.change(foreground=pixel((255, 255, 255)))
        for yy in range(cy, cy + ch, cell):
            for xx in range(cx, cx + cw, cell):
                if ((xx - cx) // cell + (yy - cy) // cell) % 2 == 0:
                    win.fill_rectangle(gc, xx, yy, cell, cell)
        d.sync()

    for line in sys.stdin:
        cmd = line.split()
        if not cmd:
            continue
        if cmd[0] == "quit":
            break
        if cmd[0] == "scene" and len(cmd) == 2 and cmd[1] in SCENES:
            draw(cmd[1])
            print(f"ready {cmd[1]}", flush=True)
    win.destroy()
    d.sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
