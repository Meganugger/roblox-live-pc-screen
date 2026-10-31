# PR #3 explainer: draw only what changed, show it anywhere, share only what you choose

This PR does three things:
- makes the Roblox client draw only what actually changed, and only when someone can see it;
- adds three viewer modes: full screen, cinema and a mini player;
- lets the owner share one app window or one browser tab instead of a whole monitor.

## Context

### For newcomers

The owner's PC encodes the desktop into a stream of **tiles** (16×16 pixel squares). A tile is sent only when it
changed (D-0007). Lossless tiles carry exact pixels, DCT tiles carry compressed photo-like content, and COPY tiles say
"same as the previous picture, shifted" (scrolling).

The Roblox game server relays that stream to every player (D-0009). Each player's client (`RlpsClient`) decodes it
into a frame buffer, then copies it into an **EditableImage**: a texture that scripts can write, shown on the TV
through a `SurfaceGui`. EditableImage writes don't replicate, so every client does this work itself, on the player's
own CPU.

> **Key concept — two kinds of "delta".** *Wire delta*: only changed tiles travel and get decoded (already in place).
> *Draw delta*: only changed pixels are written to the EditableImage (this PR). The second matters because
> `WritePixelsBuffer` and the copy before it cost time in proportion to the rectangle's area.

### What the client did before

`RlpsClientCore` kept **one bounding rectangle** of everything that changed. A blinking cursor top-left plus a clock
bottom-right produced a rectangle covering almost the whole 1024×576 picture: 2.4 MB copied and written per frame.

The client also redrew after **every completed frame**, even when several completed within one game frame. And it
redrew TVs nobody could see, as long as they were within 300 studs.

On the PC side, the app shared a monitor or a fixed rectangle. Anything on top of the shared area, such as a chat
notification, was shared too.

## Intuition

**Dirty cells instead of a dirty box.** While decoding, mark every 16×16 *cell* that a tile touched. When drawing, scan
the marked cells row by row into runs, and stack a run onto the one directly above when they span the same cells.

Two changed corners become two small rectangles:

```
cells (200×120 frame, 13×8 cells)     rectangles written
X . . . . . . . . . . . .            (0,0) 16×16
. . . . . . . . . . . . .
. . . . . . . . . . . X X            (176,96) 24×24 (clamped to the frame)
. . . . . . . . . . . X X
```

If there are more than 12 rectangles, or they cover ≥ 75 % of their bounding box, one bounding-box write is cheaper,
because each `WritePixelsBuffer` call has a fixed cost.

**Draw once per game frame, and only when visible.** Frames are still decoded every time; the chain must not break,
and the server's flow control needs the acks. But writing the EditableImage waits until a screen is in front of the
camera and facing it, or an overlay is open. Dirty cells keep accumulating, so the first redraw after looking back is
exact.

**One image, many views.** The full-screen overlay and the mini player are `ImageLabel`s showing the *same*
EditableImage. They cost no extra decoding and no extra image memory.

> **Key concept — framing distance.** To fill the view with a w×h screen, the camera must be at
> d = max((h/2) / (tan(fov/2)·usable), (w/2) / (tan(fov/2)·aspect)) / margin. Here `usable` is the share of the
> viewport height left between the cinema bars. For the 16×9-stud TV, a 70° field of view, a 16:9 window and 8 % bars,
> d = 7.97 studs (E2E-26).

**Share a window from the window itself.** `PrintWindow(hwnd, PW_RENDERFULLCONTENT)` asks Windows (DWM) for the
window's own pixels, so whatever covers it is not in the picture. Chromium browsers draw the page in a child window
of class `Chrome_RenderWidgetHostHWND`; cropping to it shows only the page.

The browser's window title is the active tab's title. When it stops containing the shared tab's title, sharing
**pauses**: another tab is never shared.

## Code

### Decoder and assembler (`roblox/src/shared/`)

```lua
-- RlpsDecoder.grow: besides the bounding box, mark every 16 px cell a tile touched
for cy = y0 // 16, (y0 + th - 1) // 16 do
	for c = x0 // 16, (x0 + tw - 1) // 16 do
		buffer.writeu8(cells, cy * cx + c, 1)
	end
end
```

- `RlpsClientCore`:
  - `takeDirtyRects(maxRects)` builds the rectangles described above, with the fallback to the bounding box;
  - `copyRect` reuses scratch buffers by size, and copies a full-width band in one go;
  - `--!native --!optimize 2`.
- `RlpsView` (new, pure): `fitDistance`, the visibility rule and `parseModes`. It is unit-tested without Roblox.

### Client (`RlpsClient.client.luau`)

- **Views:** every tagged TV screen plus the two overlays share `refreshPanel`. `render(now)` writes the rectangles
  once per Heartbeat. `anyVisible()` decides whether to draw at all, and far screens are drawn at most 10 times per
  second.
- **Viewer modes:** `setMode("fullscreen" | "cinema" | "mini")` switches between them.
  - Cinema sets the camera to `Scriptable` at the framing distance.
  - It adds a local `DepthOfFieldEffect` and sinks movement with
    `ContextActionService:BindActionAtPriority(…, High + 1, PlayerActions…)`.
  - Leaving restores the camera type and subject.
- **Controls:** a bar of buttons appears within 45 studs of a TV while the picture is live. F, C and M toggle the modes
  (ignored while typing). The server's `ViewerModes` attribute selects which modes exist.
- **Diagnostics:** new attributes `ViewMode`, `Redraws`, `LastRedrawPixels` and `SkippedRedraws`.

### Desktop (`desktop/rlps/`)

- `windows.py` (new):
  - `Win32` is a small ctypes layer (EnumWindows, DWM frame bounds, the Chromium child, PrintWindow into a DIB section);
  - `match` and `tab_query` turn a query or a browser window title into the window to share;
  - `WindowSource` handles the follow/pause rules and the fallback to the screen area when the window renders black.
- `capture.make_source(window=…, tab=…)`.
- `app.py`:
  - new options `--window`, `--tab` and `--list-windows`;
  - `SharingController.set_source`;
  - the **Change what is shared…** picker, with a checkbox to share only the browser tab's page.

## Verification

- **`RlpsClientCore.spec`:** a new vector sequence with scattered changes. The rectangles match their expected
  positions, and a "shadow" picture painted only from the rectangles equals the frame exactly (CRC). The cap of one
  rectangle falls back to the bounding box, and scratch buffers are reused.
- **`RlpsView.spec`:** framing for 16:9 and 4:3 windows, the cinema bars and the margin; visibility cases; mode
  parsing.
- **Live test** (real capture → frame service → the unmodified scripts under the emulator, which now implements
  CFrame, ContextActionService, UserInputService and Lighting):
  - **E2E-23:** a change in two opposite corners wrote 6,144 of 589,824 pixels.
  - **E2E-24:** while Alice looked away, 45 redraws were skipped and her picture went stale; looking back showed the
    exact picture.
  - **E2E-25:** full screen and the mini player show the same live image; Fill, Exit, expand and the F key work.
  - **E2E-26:** the cinema camera sits 7.97 studs away and aims straight at the TV, with the blur on and movement
    held; leaving restores the camera.
  - **E2E-27:** `ViewerModes=cinema` offers only the cinema button.
- **`test_windows.py`:**
  - the logic with a fake Win32 layer, on every OS;
  - **on the Windows CI runner:** a real Tk window covered by another is captured with its own colour; the crop drops
    the title bar; minimizing and closing are reported. If Chrome or Edge is installed, a page opened in a new window
    is cropped to the page only, and sharing pauses when another tab opens.

### Manual QA

1. Run `python -m rlps.app --list-windows` and check that your browser and a text editor are listed.
2. Run `python -m rlps.app --window "Notepad" --start`. Drag another window over Notepad: the TV still shows Notepad
   only. Move and resize Notepad: the TV follows.
3. Run `python -m rlps.app --tab "YouTube" --start` with a YouTube tab open. The TV shows the page without the address
   bar. Switch to another tab: the status line says "paused" and the TV keeps the last YouTube picture. Switch back.
4. In Roblox, walk up to the TV:
   - Press **F**: full screen. Try **Fill**, then **Exit**.
   - Press **C**: cinema. The TV fills the view between bars and WASD does nothing. Press **C** again.
   - Press **M**: mini player. Walk away; it stays. Use ⛶ to go to full screen.
5. In Studio, watch `RlpsClient.LastRedrawPixels` while typing in the shared window: it should be a few thousand pixels,
   not 589,824. Turn away from the TV: `SkippedRedraws` rises.

## Alternatives

### A. Windows Graphics Capture instead of PrintWindow

| Pros | Cons |
| --- | --- |
| Also captures exclusive-full-screen and swap-chain content that PrintWindow renders black | Needs WinRT bindings (an extra dependency) and a yellow capture border on older Windows versions |
| Pushes frames on change | Larger, async API; no gain for ordinary apps and browsers |

### B. A browser extension for tab sharing

| Pros | Cons |
| --- | --- |
| True per-tab capture (`tabCapture`), even when the tab is in the background | Users must install an extension in every browser; a second component holds frames; another trust boundary |
| Exact page pixels | Doesn't help with non-browser apps |

## People to talk to

- **Sivalmagic** (GitHub `Meganugger`), the owner, who wrote most of the commits before session 28. They know the
  intended in-game experience: whether cinema should also dim the room, and which modes their game needs. They can
  check the viewer controls against their game's own camera scripts.
- Nobody else has committed to `RlpsClient.client.luau`, `RlpsClientCore.luau` or `capture.py`. The rest of the history
  is AI sessions.

## Quiz

<details><summary>1. A cursor blinks top-left and a clock ticks bottom-right. How many pixels does the client now write per redraw, roughly?</summary>

- A. The whole picture (589,824 px), because their bounding box covers it.
- B. Only the 16 px cells around each change: a few hundred to a few thousand pixels, as two rectangles.
- C. Nothing: the server skips such small changes.

**Answer: B.** The bounding box (A) was the old behaviour. C is wrong: every change is sent and drawn (E2E-23 measured
6,144 px for two corner squares).
</details>

<details><summary>2. Why does the client keep decoding frames while no TV is visible?</summary>

- A. To keep the delta chain intact and its acks flowing, so the picture is exact the moment a TV is visible again.
- B. Because EditableImage requires it.
- C. It doesn't; it stops decoding.

**Answer: A.** Skipping frames would break the chain (a delta needs its predecessor) and stall the server's flow
control. Only the EditableImage writes are skipped; the dirty cells accumulate.
</details>

<details><summary>3. Why do full screen and the mini player cost no extra decoding or image memory?</summary>

- A. They show a lower resolution.
- B. Their ImageLabels display the same EditableImage as the TV.
- C. The server sends them a separate stream.

**Answer: B.** One image per client (memory budget, F-0002), shown by several GUI objects.
</details>

<details><summary>4. In tab mode the owner switches to their bank's tab. What do players see?</summary>

- A. The bank page.
- B. The last picture of the shared tab: the window's title no longer contains the tab's title, so capture pauses.
- C. A black screen.

**Answer: B.** `WindowSource.follow_title` raises "paused" and nothing new is published.
</details>

<details><summary>5. A window is half covered by a notification. With <code>--window</code>, is the notification shared?</summary>

- A. Yes, everything on screen in that rectangle is shared.
- B. No. PrintWindow renders the window's own pixels, unless the app renders black for it, in which case the screen
  area is used (with a warning).
- C. Only if it is a Windows toast.

**Answer: B.** That is the point of capturing from the window rather than from the screen. The fallback is the
documented exception (KI-0009).
</details>
