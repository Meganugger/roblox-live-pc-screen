"""Hybrid frame encoder (FMT_HYBRID): lossless RGBA8 tiles where the budget allows, DCT tiles for moving content, and
lossless refinement of tiles that stopped changing.

The encoder owns the *decoder-side reconstruction* (``recon``): what every client shows after applying everything sent
so far. Each frame it sends tiles whose reconstruction differs from the new source, choosing per frame:

1. **moving tiles** (changed within the last ``refine_after`` captures): lossless if they fit the byte budget, else DCT at
   the highest quality step that fits (binary search, warm-started from the previous frame's step);
2. **settled tiles** (unchanged for ``refine_after`` captures but still lossy or stale): lossless, oldest first, with the
   budget left over — so a still screen converges to a pixel-exact copy of the desktop.

If even the lowest DCT quality does not fit, the frame is skipped (the budget accumulates); keyframes are always sent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import codec, dct
from . import protocol as P

T = P.HYBRID_TILE


@dataclass
class HybridInfo:
    keyframe: bool = False
    moving_tiles: int = 0
    refined_tiles: int = 0
    mode: str = ""  # "lossless" | "dct" | "" (nothing sent)
    quality: int = -1  # IJG quality of DCT tiles in this frame (-1 = none)
    bytes: int = 0
    skipped: bool = False  # over budget: nothing sent this time


class HybridEncoder:
    def __init__(self, width: int, height: int, *, packer: codec.FrameEncoder | None = None, refine_after: int = 2):
        if width % T or height % T or not (T <= width <= P.MAX_DIM and T <= height <= P.MAX_DIM):
            raise ValueError(f"hybrid frames need dimensions divisible by {T} within {P.MAX_DIM}, got {width}x{height}")
        self.w, self.h = width, height
        self.tx, self.ty = width // T, height // T
        self.count = self.tx * self.ty
        self.packer = packer or codec.FrameEncoder(tile_size=T, max_part_raw_bytes=96 * 1024)
        if self.packer.tile_size != T:
            raise ValueError("packer tile size must be 16")
        self.refine_after = refine_after
        self.recon: np.ndarray | None = None  # (H, W, 4) uint8, decoder-side picture
        self.src_prev: np.ndarray | None = None
        self.still = np.zeros(self.count, np.int64)  # captures since the tile's source last changed
        self.stale = np.ones(self.count, bool)  # source changed since the tile was last sent
        self.q_index = len(dct.QUALITIES) - 1
        self.lossless_tile_bytes = 400.0  # running estimate of one compressed lossless tile (skips hopeless attempts)

    def reset(self) -> None:
        """Forget the decoder state: the next frame is a keyframe."""
        self.recon = None

    def _tiles(self, img: np.ndarray) -> np.ndarray:
        """(H, W, C) -> (count, 16, 16, C) view in row-major tile order."""
        c = img.shape[2]
        return img.reshape(self.ty, T, self.tx, T, c).swapaxes(1, 2).reshape(self.count, T, T, c)

    def _pack(self, entries, *, session_id, seq, base_seq, keyframe) -> bytes:
        entries.sort(key=lambda e: e[0])
        return self.packer.pack(entries, P.FMT_HYBRID, self.w, self.h, session_id=session_id, seq=seq,
                                base_seq=base_seq, keyframe=keyframe)

    def encode(self, src: np.ndarray, *, session_id: int, seq: int, base_seq: int, budget: float | None = None,
               force_keyframe: bool = False) -> tuple[bytes | None, HybridInfo]:
        """Encode ``src`` ((H, W, 4) uint8 RGBA). ``budget`` = max container bytes (None = unlimited).

        Returns (container or None, info). The reconstruction is only updated when a container is returned."""
        if src.shape != (self.h, self.w, 4) or src.dtype != np.uint8:
            raise ValueError(f"expected ({self.h}, {self.w}, 4) uint8, got {src.shape} {src.dtype}")
        info = HybridInfo()
        keyframe = force_keyframe or self.recon is None
        info.keyframe = keyframe
        st = self._tiles(src)
        if self.src_prev is None or keyframe:
            changed = np.ones(self.count, bool)
        else:
            changed = (st != self._tiles(self.src_prev)).reshape(self.count, -1).any(axis=1)
        self.src_prev = src.copy()
        self.still = np.where(changed, 0, self.still + 1)
        self.stale |= changed
        if keyframe:
            need = np.ones(self.count, bool)
            moving = need.copy()
        else:
            need = (st != self._tiles(self.recon)).reshape(self.count, -1).any(axis=1)
            moving = need & self.stale  # new content not shown yet
        self.stale &= need  # a stale tile whose old reconstruction happens to match needs nothing
        settled = need & ~moving & (self.still >= self.refine_after)  # shown lossy, stopped changing: refine
        if not need.any():
            return None, info
        args = dict(session_id=session_id, seq=seq, base_seq=0 if keyframe else base_seq, keyframe=keyframe)
        moving_idx = np.flatnonzero(moving)
        raw_entries = {int(i): bytes((P.TILE_MODE_RAW,)) + st[i].tobytes() for i in moving_idx}

        # 1. moving tiles: lossless if it fits, else the best DCT quality that fits
        dct_q: int | None = None
        dct_recon = None
        if moving_idx.size:
            hopeless = budget is not None and moving_idx.size * self.lossless_tile_bytes > budget * 2
            lossless = None if hopeless else self._pack(list(raw_entries.items()), **args)
            if lossless is not None:
                self.lossless_tile_bytes = 0.7 * self.lossless_tile_bytes + 0.3 * len(lossless) / moving_idx.size
            if lossless is not None and (budget is None or len(lossless) <= budget):
                chosen = list(raw_entries.items())
                size = len(lossless)
            else:
                coefs = dct.forward_coefficients(st[moving_idx][..., :3])
                # Search the quality on a sample of the tiles (sizes scale with the tile count), then encode once.
                n = moving_idx.size
                stride = max(1, n // 192)
                sample = np.arange(0, n, stride)
                scale = n / sample.size
                cache: dict[int, int] = {}

                def attempt(qi: int) -> bool:
                    if qi not in cache:
                        qz = dct.quantize(coefs[sample], qi)
                        ent = list(zip(moving_idx[sample].tolist(), dct.pack_entries(qz, qi)))
                        cache[qi] = int(len(self._pack(ent, **args)) * scale)
                    return cache[qi] <= budget

                top = len(dct.QUALITIES) - 1
                guess = min(max(self.q_index, 0), top)
                # invariant: lo fits (or -1), hi does not fit (or top + 1); gallop from last frame's step, then bisect
                if attempt(guess):
                    lo, hi, step = guess, top + 1, 1
                    while lo + step <= top:
                        if attempt(lo + step):
                            lo, step = lo + step, step * 2
                        else:
                            hi = lo + step
                            break
                else:
                    lo, hi, step = -1, guess, 1
                    while hi - step >= 0:
                        if attempt(hi - step):
                            lo = hi - step
                            break
                        hi, step = hi - step, step * 2
                while hi - lo > 1:
                    mid = (lo + hi) // 2
                    if attempt(mid):
                        lo = mid
                    else:
                        hi = mid
                if lo < 0 and not keyframe:
                    info.skipped = True
                    return None, info
                lo = max(lo, 0)
                while True:  # the real encode; step down if the sample estimate was optimistic
                    qz = dct.quantize(coefs, lo)
                    chosen = list(zip(moving_idx.tolist(), dct.pack_entries(qz, lo)))
                    size = len(self._pack(list(chosen), **args))
                    if size <= budget or lo == 0 or stride == 1:
                        break
                    lo -= 1
                if size > budget and not keyframe:
                    info.skipped = True
                    return None, info
                self.q_index = lo
                dct_q, dct_recon = lo, dct.reconstruct(qz, lo)
            info.moving_tiles = int(moving_idx.size)
        else:
            chosen, size = [], 0

        # 2. settled tiles: lossless refinement with what is left of the budget (oldest first)
        refine_idx = np.flatnonzero(settled)
        if refine_idx.size:
            refine_idx = refine_idx[np.argsort(-self.still[refine_idx], kind="stable")]
            take = refine_idx.size if budget is None else int(min(refine_idx.size, max(0, budget - size) // 300))
            for _ in range(4):  # estimate from the measured bytes per tile, shrink until it fits
                if take <= 0:
                    break
                extra = [(int(i), bytes((P.TILE_MODE_RAW,)) + st[i].tobytes()) for i in refine_idx[:take]]
                trial = len(self._pack(chosen + extra, **args))
                if budget is None or trial <= budget:
                    chosen = chosen + extra
                    info.refined_tiles = take
                    break
                per_tile = max(1.0, (trial - size) / take)
                take = min(take - 1, int((budget - size) / per_tile * 0.9))
        if not chosen:
            return None, info
        container = self._pack(chosen, **args)

        # 3. the reconstruction follows exactly what was sent
        if keyframe or self.recon is None:
            self.recon = np.zeros_like(src)
        rt = self.recon.reshape(self.ty, T, self.tx, T, 4).swapaxes(1, 2)  # (ty, tx, 16, 16, 4) view of recon
        sent_raw = np.asarray([i for i, e in chosen if e[0] == P.TILE_MODE_RAW], np.int64)
        if sent_raw.size:
            rt[sent_raw // self.tx, sent_raw % self.tx] = st[sent_raw]
        if dct_recon is not None:
            rt[moving_idx // self.tx, moving_idx % self.tx] = dct_recon
        self.stale[moving_idx] = False
        if keyframe:
            self.stale[:] = False
        info.mode = "dct" if dct_q is not None else "lossless"
        info.quality = dct.QUALITIES[dct_q] if dct_q is not None else -1
        info.bytes = len(container)
        return container, info
