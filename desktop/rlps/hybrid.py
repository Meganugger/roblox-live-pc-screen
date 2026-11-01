"""Hybrid frame encoder (FMT_HYBRID): lossless RGBA8 tiles where the budget allows, DCT tiles for moving content, and
lossless refinement of tiles that stopped changing.

The encoder owns the *decoder-side reconstruction* (``recon``): what every client shows after applying everything sent
so far. Each frame it sends tiles whose reconstruction differs from the new source, choosing per frame:

1. **moving tiles** (changed within the last ``refine_after`` captures): lossless if they fit the byte budget, else DCT at
   the highest quality step that fits (binary search, warm-started from the previous frame's step). In a large moving
   area (video) every complete, aligned 2x2 group of moving tiles is sent as one **half-resolution** macroblock
   (TILE_MODE_DCT2): a quarter of the bytes and of the clients' decode work — which decides the frame rate players
   get, because clients decode in interpreted Luau;
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
    copied_tiles: int = 0  # scrolled tiles sent as copies from the previous picture
    mode: str = ""  # "lossless" | "dct" | "" (nothing sent)
    quality: int = -1  # IJG quality of DCT tiles in this frame (-1 = none)
    bytes: int = 0
    skipped: bool = False  # over budget: nothing sent this time


class HybridEncoder:
    HALF_RES_MIN_SHARE = 0.06  # moving area (share of the frame's tiles) from which 2x2 groups go half-resolution
    HALF_RES_MIN_TILES = 48

    def __init__(self, width: int, height: int, *, packer: codec.FrameEncoder | None = None, refine_after: int = 2,
                 half_res: bool = True):
        if width % T or height % T or not (T <= width <= P.MAX_DIM and T <= height <= P.MAX_DIM):
            raise ValueError(f"hybrid frames need dimensions divisible by {T} within {P.MAX_DIM}, got {width}x{height}")
        self.w, self.h = width, height
        self.tx, self.ty = width // T, height // T
        self.count = self.tx * self.ty
        self.packer = packer or codec.FrameEncoder(tile_size=T, max_part_raw_bytes=96 * 1024)
        if self.packer.tile_size != T:
            raise ValueError("packer tile size must be 16")
        self.refine_after = refine_after
        self.half_res = half_res
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

    def _groups(self, moving: np.ndarray) -> np.ndarray:
        """Top-left tile indices of the complete, aligned 2x2 groups of moving tiles (TILE_MODE_DCT2 candidates)."""
        ey, ex = self.ty // 2 * 2, self.tx // 2 * 2
        if not (self.half_res and ey and ex) or moving.sum() < max(self.HALF_RES_MIN_TILES,
                                                                   self.count * self.HALF_RES_MIN_SHARE):
            return np.zeros(0, np.int64)
        m = moving.reshape(self.ty, self.tx)[:ey, :ex].reshape(ey // 2, 2, ex // 2, 2).all(axis=(1, 3))
        gy, gx = np.nonzero(m)
        return (gy * 2 * self.tx + gx * 2).astype(np.int64)

    def _pack(self, entries, *, session_id, seq, base_seq, keyframe, ref=False) -> bytes:
        entries.sort(key=lambda e: e[0])
        return self.packer.pack(entries, P.FMT_HYBRID, self.w, self.h, session_id=session_id, seq=seq,
                                base_seq=base_seq, keyframe=keyframe, ref=ref)

    COPY_RELATIVE_ERR = 0.8  # a copy must predict a tile at least this much better than the unshifted picture
    COPY_MAX_MEAN_ERR = 40.0  # a copy never predicts a tile worse than this (mean abs difference per channel)

    def _scroll_copies(self, src: np.ndarray, moving: np.ndarray) -> dict[int, tuple[int, int]]:
        """Moving tiles of ``src`` best predicted by the client's picture shifted vertically (scrolling):
        {tile: (dx, dy)}, sent as 5-byte copies. The shift is measured against the client's picture itself (not the
        previous capture), so rounding a sub-pixel scroll (non-integer downscale) never accumulates into drift.

        A copy is exact when content and picture were exact there; otherwise it is a close prediction (e.g. text
        shifted by under half a pixel), refined to lossless once the content stops moving."""
        if self.recon is None or moving.sum() < max(8, self.count // 20):  # only worth it when a sizeable area moved
            return {}
        h, w = self.h, self.w
        # green channel ~ luminance; row profiles of one band per tile column (narrow enough to keep words apart)
        bands = w // T
        prof_a = src[..., 1].reshape(h, bands, T).sum(axis=2, dtype=np.int32).astype(np.float64) / T
        prof_b = self.recon[..., 1].reshape(h, bands, T).sum(axis=2, dtype=np.int32).astype(np.float64) / T
        if prof_a.std() < 1.0:
            return {}
        # mean squared difference between src rows r and recon rows r + dy for every dy at once (FFT correlation;
        # summed over the bands below)
        n = 2 * h
        corr = np.fft.irfft(np.conj(np.fft.rfft(prof_a, n, axis=0)) * np.fft.rfft(prof_b, n, axis=0), n, axis=0)
        corr = corr.sum(axis=1)
        ca = np.concatenate([[0.0], np.cumsum((prof_a ** 2).sum(axis=1))])
        cb = np.concatenate([[0.0], np.cumsum((prof_b ** 2).sum(axis=1))])
        dys = np.arange(-(h // 3), h // 3 + 1)  # per-frame scroll distance; beyond a third it is not scrolling
        lo, hi = np.maximum(0, -dys), np.minimum(h, h - dys)
        length = hi - lo
        sse = (ca[hi] - ca[lo]) + (cb[hi + dys] - cb[lo + dys]) - 2 * corr[dys % n]
        valid = (dys != 0) & (length >= h // 4)
        if not valid.any():
            return {}
        mse = np.where(valid, sse / np.maximum(length, 1) / bands, np.inf)
        best = float(mse.min())
        if not best < 0.25 * float(np.median(mse[valid])):  # no clear vertical motion (0.5 x in RMS terms)
            return {}
        # Periodic content (lines of text) gives several near-equal minima of the row-profile error, so the profile
        # only proposes candidates (the deepest local minima); each is judged by how many tiles it predicts well.
        order = np.argsort(mse)
        candidates: list[int] = []
        for k in order[:128].tolist():
            if not np.isfinite(mse[k]):
                break
            if all(abs(int(dys[k]) - c) > 2 for c in candidates):
                candidates.append(int(dys[k]))
            if len(candidates) == 8:
                break
        all_idx = np.flatnonzero(moving)
        g_src, g_rec = src[..., 1], self.recon[..., 1]
        sub = np.arange(0, T, 2)

        def judge(dy: int, idx: np.ndarray):
            ty, tx = idx // self.tx, idx % self.tx
            ok = (ty * T + dy >= 0) & (ty * T + dy <= h - T)
            idx, ty, tx = idx[ok], ty[ok], tx[ok]
            if not idx.size:
                return idx, np.zeros(0, bool), np.zeros(0)
            y_cur = (ty * T)[:, None] + sub[None, :]
            y_src = (ty * T + dy)[:, None] + sub[None, :]
            x = (tx * T)[:, None] + sub[None, :]
            cur = g_src[y_cur[:, :, None], x[:, None, :]].astype(np.int16)
            stay = g_rec[y_cur[:, :, None], x[:, None, :]].astype(np.int16)
            shifted = g_rec[y_src[:, :, None], x[:, None, :]].astype(np.int16)
            err_copy = np.abs(cur - shifted).reshape(idx.size, -1).mean(axis=1)
            err_stay = np.abs(cur - stay).reshape(idx.size, -1).mean(axis=1)
            # accept when the shifted picture predicts the tile clearly better than leaving it: a sub-pixel
            # misaligned copy of sharp text keeps some error but looks right while moving, and is refined once still
            good = (err_copy == 0) | ((err_copy <= self.COPY_RELATIVE_ERR * err_stay)
                                      & (err_copy <= self.COPY_MAX_MEAN_ERR))
            return idx, good, err_copy

        # the true shift is the candidate with the smallest typical prediction error (another line of text one
        # line-period away has the same layout but different words: a much larger error)
        probe = all_idx[:: max(1, all_idx.size // 256)]
        scores = []
        for c in candidates:
            pidx, pgood, perr = judge(c, probe)
            if pidx.size:
                scores.append((float(np.median(perr)), abs(c), c, int(pgood.sum()), pidx.size))
        if not scores:
            return {}
        _, _, dy, n_good, n_probe = min(scores)
        if n_good < max(4, n_probe // 10):
            return {}
        idx, good, _ = judge(dy, all_idx)
        return {int(i): (0, int(dy)) for i in idx[good]}

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
        prev_src = self.src_prev
        if prev_src is None or keyframe:
            changed = np.ones(self.count, bool)
        else:
            changed = (st != self._tiles(prev_src)).reshape(self.count, -1).any(axis=1)
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
        if not need.any():
            return None, info
        copies: dict[int, tuple[int, int]] = {}
        if not keyframe and prev_src is not None:
            copies = self._scroll_copies(src, moving)
        if copies:  # scrolled content: 5-byte copies from the previous picture instead of pixels
            cidx = np.fromiter(copies, np.int64, len(copies))
            moving[cidx] = False  # new content shown; if the copied picture was lossy it is refined once still
            self.stale[cidx] = False
        settled = need & ~moving & (self.still >= self.refine_after)  # shown lossy, stopped changing: refine
        copy_entries = [(i, bytes((P.TILE_MODE_COPY,)) + int(dx).to_bytes(2, "little", signed=True)
                         + int(dy).to_bytes(2, "little", signed=True)) for i, (dx, dy) in copies.items()]
        args = dict(session_id=session_id, seq=seq, base_seq=0 if keyframe else base_seq, keyframe=keyframe,
                    ref=bool(copies))
        moving_idx = np.flatnonzero(moving)
        raw_entries = {int(i): bytes((P.TILE_MODE_RAW,)) + st[i].tobytes() for i in moving_idx}

        # 1. moving tiles: lossless if it fits, else the best DCT quality that fits
        dct_q: int | None = None
        dct_recon = None
        if moving_idx.size:
            # (keyframes always try lossless: text and desktops compress far better than the running estimate says)
            hopeless = (budget is not None and not keyframe
                        and moving_idx.size * self.lossless_tile_bytes > budget * 2)
            lossless = None if hopeless else self._pack(list(raw_entries.items()) + copy_entries, **args)
            if lossless is not None:
                self.lossless_tile_bytes = 0.7 * self.lossless_tile_bytes + 0.3 * len(lossless) / moving_idx.size
            if lossless is not None and (budget is None or len(lossless) <= budget):
                chosen = list(raw_entries.items()) + copy_entries
                size = len(lossless)
            else:
                # DCT: single tiles, plus 2x2 groups of a large moving area at half resolution
                groups = self._groups(moving)
                covered = np.zeros(self.count, bool)
                if groups.size:
                    for d in (0, 1, self.tx, self.tx + 1):
                        covered[groups + d] = True
                single_idx = np.flatnonzero(moving & ~covered)
                ent_idx = np.concatenate([single_idx, groups])
                modes = np.concatenate([np.full(single_idx.size, P.TILE_MODE_DCT),
                                        np.full(groups.size, P.TILE_MODE_DCT2)])
                parts_rgb = [st[single_idx][..., :3]]
                if groups.size:
                    gy, gx = groups // self.tx * T, groups % self.tx * T
                    yy = gy[:, None] + np.arange(2 * T)[None, :]
                    xx = gx[:, None] + np.arange(2 * T)[None, :]
                    parts_rgb.append(dct.downscale2(src[yy[:, :, None], xx[:, None, :], :3]))
                coefs = dct.forward_coefficients(np.concatenate(parts_rgb))

                def entries(qz, qi, sel=slice(None)):
                    blobs = dct.pack_entries(qz, qi)
                    return [(int(i), bytes((int(m),)) + b[1:]) for i, m, b in zip(ent_idx[sel], modes[sel], blobs)]

                # Search the quality on a sample of the tiles (sizes scale with the tile count), then encode once.
                n = ent_idx.size
                stride = max(1, n // 192)
                sample = np.arange(0, n, stride)
                scale = n / sample.size
                cache: dict[int, int] = {}

                def attempt(qi: int) -> bool:
                    if qi not in cache:
                        qz = dct.quantize(coefs[sample], qi)
                        cache[qi] = int(len(self._pack(entries(qz, qi, sample), **args)) * scale) + 5 * len(copy_entries)
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
                    chosen = entries(qz, lo) + copy_entries
                    size = len(self._pack(list(chosen), **args))
                    if size <= budget or lo == 0 or stride == 1:
                        break
                    lo -= 1
                if size > budget and not keyframe:
                    info.skipped = True
                    return None, info
                self.q_index = lo
                rec = dct.reconstruct(qz, lo)
                dct_q, dct_recon = lo, (single_idx, rec[:single_idx.size], groups, dct.upscale2(rec[single_idx.size:]))
        else:
            chosen = list(copy_entries)
            size = len(self._pack(list(chosen), **args)) if chosen else 0

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
                    break
                per_tile = max(1.0, (trial - size) / take)
                take = min(take - 1, int((budget - size) / per_tile * 0.9))
        if not chosen:
            return None, info
        container = self._pack(chosen, **args)

        # 3. the reconstruction follows exactly what was sent (copies read the picture as it was before this frame)
        before = self.recon.copy() if copies else None
        if keyframe or self.recon is None:
            self.recon = np.zeros_like(src)
        rt = self.recon.reshape(self.ty, T, self.tx, T, 4).swapaxes(1, 2)  # (ty, tx, 16, 16, 4) view of recon
        sent_raw = np.asarray([i for i, e in chosen if e[0] == P.TILE_MODE_RAW], np.int64)
        if sent_raw.size:
            rt[sent_raw // self.tx, sent_raw % self.tx] = st[sent_raw]
        if dct_recon is not None:
            single_idx, single_rec, groups, group_rec = dct_recon
            rt[single_idx // self.tx, single_idx % self.tx] = single_rec
            for g, block in zip(groups.tolist(), group_rec):
                gy, gx = g // self.tx * T, g % self.tx * T
                self.recon[gy:gy + 2 * T, gx:gx + 2 * T] = block
        for i, (dx, dy) in copies.items():
            ty, tx = divmod(i, self.tx)
            self.recon[ty * T:ty * T + T, tx * T:tx * T + T] = before[ty * T + dy:ty * T + dy + T,
                                                                       tx * T + dx:tx * T + dx + T]
        info.copied_tiles = len(copies)
        self.stale[moving_idx] = False
        if keyframe:
            self.stale[:] = False
        info.mode = "dct" if dct_q is not None else ("lossless" if len(chosen) > len(copy_entries) else "copy")
        info.quality = dct.QUALITIES[dct_q] if dct_q is not None else -1
        info.bytes = len(container)
        return container, info
