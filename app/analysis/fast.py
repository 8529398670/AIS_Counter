"""Settings' Method "ais_auto.m (fast)": the same answers as ais_auto.py,
detect.py and learned.py, worked out on crops around each object instead of
on whole images.

Those keep, for every click, whole-image masks, and for every re-threshold a
whole-image label map. Here a component is a Crop: its mask in its bounding
box plus a pixel of margin, and where that box sits. A re-threshold segments
a window around the click, grown until the component is known to end inside
it. Everything that leaves this module is in whole-image coordinates, and
every result must equal the original's byte for byte (tests/test_fast.py):
a click this cannot settle from a window goes through the whole image, as
the original does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage as ndi

from app.analysis import ais_auto as aa
from app.analysis import area
from app.analysis import detect as auto
from app.analysis import learned
from app.analysis import mlcompat as ml
from app.analysis.mlcompat import MatlabError
from app.analysis.soma import Somata

START_PAD = 24   # px a first window leaves around what is known of the component


@dataclass
class Crop:
    """One component: mask is its pixels in a box whose top left is (r, c),
    with a pixel of margin on every side but the image's own edges."""
    mask: np.ndarray
    r: int
    c: int
    thin: np.ndarray | None = None
    peak: float | None = None

    def skeleton(self) -> np.ndarray:
        if self.thin is None:
            self.thin = ml.bwmorph_thin(self.mask)
        return self.thin

    def brightest(self, D: np.ndarray) -> float:
        """Line 125's max over the component."""
        if self.peak is None:
            h, w = self.mask.shape
            self.peak = float((self.mask * D[self.r:self.r + h, self.c:self.c + w]).max())
        return self.peak

    def holds(self, row: int, col: int) -> bool:
        r, c = row - self.r, col - self.c
        return 0 <= r < self.mask.shape[0] and 0 <= c < self.mask.shape[1] and bool(self.mask[r, c])

    def box(self) -> tuple[slice, slice]:
        h, w = self.mask.shape
        return slice(self.r, self.r + h), slice(self.c, self.c + w)


@dataclass
class Trace:
    """ais_auto.Trace with selected and skeleton as Crop's, r and c saying
    where; start, passes and path are whole-image, 1-based."""
    threshold_initial: float
    threshold: float
    rethresholded: bool
    max_ais: float
    max_all: float
    clicks: list[tuple[int, int]]
    selected: np.ndarray
    skeleton: np.ndarray
    r: int
    c: int
    start: tuple[int, int]
    passes: list[list[tuple[int, int]]]
    longest: int
    path: list[tuple[int, int]]


def _count(cache: dict, what: str) -> None:
    stats = cache.setdefault("stats", {})
    stats[what] = stats.get(what, 0) + 1


def _labels(prep: aa.PreparedImage, level: float, settings: aa.Settings, cache: dict) -> tuple[np.ndarray, list]:
    """The whole image's labels at level, and each one's box."""
    L = aa._cached(cache, ("L", level), lambda: aa.segment(prep, level, settings))
    return L, aa._cached(cache, ("boxes", level), lambda: ndi.find_objects(L))


def _select(L: np.ndarray, X: int, Y: int, level: float, cache: dict) -> int:
    """ais_auto._select, the labelled pixels found once per level."""
    label = L[Y - 1, X - 1]
    if label == 0:
        rows, cols = aa._cached(cache, ("on", level), lambda: np.nonzero(L > 0))
        if rows.size == 0:
            raise MatlabError("Index in position 1 is invalid (no components above 70 px)")
        d2 = (rows - (Y - 1)) ** 2 + (cols - (X - 1)) ** 2            # ml.bwdist_nearest
        best = np.flatnonzero(d2 == d2.min())
        lin = cols[best] * L.shape[0] + rows[best]
        k = best[np.argmin(lin)]
        label = L[rows[k], cols[k]]
    return int(label)


def _labelled(L: np.ndarray, boxes: list, label: int, level: float, cache: dict) -> Crop:
    def make() -> Crop:
        rows, cols = boxes[label - 1]
        r0, c0 = max(rows.start - 1, 0), max(cols.start - 1, 0)
        r1, c1 = min(rows.stop + 1, L.shape[0]), min(cols.stop + 1, L.shape[1])
        return Crop(L[r0:r1, c0:c1] == label, r0, c0)
    return aa._cached(cache, ("crop", level, label), make)


def _window(prep: aa.PreparedImage, level: float, settings: aa.Settings, row: int, col: int,
            known: tuple[int, int, int, int]) -> Crop | None:
    """The component holding (row, col) at level, segmented around known
    (top, bottom, left, right; what it must at least span), or None when
    that pixel is not on a component big enough to keep. Opening and closing
    see 4 * (strel // 2) px, so what far from a cut edge is exactly the whole
    image's segmentation; a component that stays clear of that band ends
    inside it. An image edge is no cut: the same padding rules apply there."""
    H, W = prep.pic.shape
    k = settings.strel
    reach = 4 * (k // 2) + 1
    top, bottom, left, right = known
    pad = START_PAD
    while True:
        r0, r1 = max(top - pad - reach, 0), min(bottom + pad + reach, H)
        c0, c1 = max(left - pad - reach, 0), min(right + pad + reach, W)
        bw = ml.im2bw(prep.smooth[r0:r1, c0:c1], level)
        closed = ml.imclose_square(ml.imopen_square(bw, k), k)
        t, b = reach if r0 > 0 else 0, reach if r1 < H else 0
        l, r = reach if c0 > 0 else 0, reach if c1 < W else 0
        core = closed[t:closed.shape[0] - b, l:closed.shape[1] - r]
        y, x = row - r0 - t, col - c0 - l
        if not core[y, x]:
            return None
        lab, _ = ndi.label(core, structure=np.ones((3, 3), bool))
        comp = lab == lab[y, x]
        if not ((t and comp[0].any()) or (b and comp[-1].any()) or (l and comp[:, 0].any()) or (r and comp[:, -1].any())):
            break
        pad = 2 * pad + 1
    if int(comp.sum()) < settings.min_pixels:
        return None
    rows, cols = np.flatnonzero(comp.any(axis=1)), np.flatnonzero(comp.any(axis=0))
    a, z = max(int(rows[0]) - 1, 0), min(int(rows[-1]) + 2, comp.shape[0])
    u, v = max(int(cols[0]) - 1, 0), min(int(cols[-1]) + 2, comp.shape[1])
    return Crop(comp[a:z, u:v].copy(), r0 + t + a, c0 + l + u)


def _whole(prep: aa.PreparedImage, level: float, settings: aa.Settings, X: int, Y: int) -> Crop:
    """The original's way, for a click a window cannot settle: its nearest
    component, from the whole image's segmentation."""
    L = aa.segment(prep, level, settings)
    label = aa._select(L, X, Y)
    rows, cols = np.nonzero(L == label)
    r0, c0 = max(int(rows.min()) - 1, 0), max(int(cols.min()) - 1, 0)
    r1, c1 = min(int(rows.max()) + 2, L.shape[0]), min(int(cols.max()) + 2, L.shape[1])
    return Crop(L[r0:r1, c0:c1] == label, r0, c0)


def _rethresholded(prep: aa.PreparedImage, level: float, settings: aa.Settings, X: int, Y: int,
                   first: Crop, cache: dict) -> Crop:
    if ("L", level) in cache:
        L, boxes = _labels(prep, level, settings, cache)
        return _labelled(L, boxes, _select(L, X, Y, level, cache), level, cache)
    row, col = Y - 1, X - 1
    found = cache.setdefault(("crops", level), [])
    for crop in found:
        if crop.holds(row, col):
            return crop
    aside = cache.setdefault(("aside", level), {})
    if (row, col) in aside:
        return aside[(row, col)]
    known = (min(first.r, row), max(first.r + first.mask.shape[0], row + 1),
             min(first.c, col), max(first.c + first.mask.shape[1], col + 1))
    crop = _window(prep, level, settings, row, col, known)
    if crop is not None:
        _count(cache, "windows")
        found.append(crop)
        return crop
    _count(cache, "whole")
    crop = aside[(row, col)] = _whole(prep, level, settings, X, Y)
    return crop


def _selected(prep: aa.PreparedImage, queue: list[tuple[float, float]], threshold: float, settings: aa.Settings,
              cache: dict) -> tuple[Crop, float, bool, float, list[tuple[int, int]]]:
    """Lines 55-133: the clicked component, re-thresholded once. Returns it,
    the threshold it is at, whether that changed, its peak and the clicks."""
    shape = prep.pic.shape
    L, boxes = _labels(prep, threshold, settings, cache)
    X, Y = aa._click_to_pixel(*queue[0], shape)
    clicks = [(X, Y)]
    crop = _labelled(L, boxes, _select(L, X, Y, threshold, cache), threshold, cache)
    max_ais = crop.brightest(prep.D)
    if prep.max_all == max_ais:
        return crop, threshold, False, max_ais, clicks
    level = (max_ais / prep.max_all) * threshold
    X, Y = aa._click_to_pixel(*queue[1], shape)
    clicks.append((X, Y))
    return _rethresholded(prep, level, settings, X, Y, crop, cache), level, True, max_ais, clicks


def _initial(prep: aa.PreparedImage, threshold: float, cache: dict) -> float:
    return aa._cached(cache, "otsu", lambda: ml.graythresh(prep.smooth)) if threshold == 0 else threshold


def trace(prep: aa.PreparedImage, click: tuple[float, float], click2: tuple[float, float] | None = None,
          threshold: float = 0.01, settings: aa.Settings = aa.DEFAULT, cache: dict | None = None) -> Trace:
    """ais_auto.trace on the component's Crop. cache: what a run of clicks
    on one image shares; a new one each call is fine."""
    cache = {} if cache is None else cache
    threshold_initial = _initial(prep, threshold, cache)
    crop, threshold, rethresholded, max_ais, clicks = _selected(
        prep, [click, click2 if click2 is not None else click], threshold_initial, settings, cache)

    skel = crop.skeleton()
    X, Y = clicks[-1]
    r0, c0 = ml.bwdist_nearest(skel, Y - 1 - crop.r, X - 1 - crop.c)  # lines 166-168
    H, W = prep.pic.shape
    dr, dc = crop.r, crop.c

    traceq = skel.copy()
    traceq[r0, c0] = False                                            # lines 173-176
    work = traceq.copy()
    passes: list[list[tuple[int, int]]] = []
    loop2 = 0
    while True:                                                       # line 183
        loop2 += 1
        path = [(r0, c0)]
        branch = None                                                 # MATLAB's q
        while work.any():                                             # line 186
            r, c = path[-1]
            if r + dr < 1 or c + dc < 1 or r + dr + 1 >= H or c + dc + 1 >= W:
                raise MatlabError("Index in position 1 exceeds array bounds (skeleton touches the image border)")
            win = work[r - 1:r + 2, c - 1:c + 2]
            nb = [(r - 1 + i, c - 1 + j) for j in range(3) for i in range(3) if win[i, j]]  # find(temp), column-major
            if len(path) > settings.max_path:
                work[:] = False
            elif len(nb) > 1:
                branch = nb[0]                                        # line 195
                path.append(branch)
                work[branch] = False
            elif len(nb) == 1:
                path.append(nb[0])
                work[nb[0]] = False
            else:
                work[:] = False
        passes.append(path)
        again = False
        if branch is not None:                                        # line 218
            qdel = path.index(branch)
            rows = sorted({p[0] for p in path[qdel:]})
            cols = sorted({p[1] for p in path[qdel:]})
            traceq[np.ix_(rows, cols)] = False                        # line 223: rows x cols, not pairs
            work = traceq.copy()
            work[r0, c0] = False
            again = True
        if loop2 > settings.max_passes:
            again = False
        if not again:
            break

    lengths = [len(p) for p in passes]
    longest = lengths.index(max(lengths))                             # line 244: first of the longest
    one = lambda p: [(r + dr + 1, c + dc + 1) for r, c in p]
    return Trace(
        threshold_initial=threshold_initial, threshold=threshold, rethresholded=rethresholded,
        max_ais=max_ais, max_all=prep.max_all, clicks=clicks, selected=crop.mask, skeleton=skel, r=dr, c=dc,
        start=(r0 + dr + 1, c0 + dc + 1), passes=[one(p) for p in passes], longest=longest,
        path=one(passes[longest]),
    )


def shape(sel: np.ndarray, top: int, left: int, raw: np.ndarray, pixels: list[list[int]], ais_start: float,
          ais_end: float, pixconv: float, bright_ref: float) -> dict[str, float]:
    """service.shape, for a mask whose box starts at (top, left)."""
    n = len(pixels)
    a, b = max(int(ais_start), 1), min(int(ais_end), n)
    section = np.array(pixels[a - 1:b] if b - a >= 1 else pixels)
    rows, cols = np.flatnonzero(sel.any(axis=1)), np.flatnonzero(sel.any(axis=0))
    r0, c0 = rows[0], cols[0]
    crop = np.pad(sel[r0:rows[-1] + 1, c0:cols[-1] + 1], 1)
    near = ndi.maximum_filter(ndi.distance_transform_edt(crop), size=3)
    r = np.clip(section[:, 1] - 1 - (r0 + top) + 1, 0, crop.shape[0] - 1)
    c = np.clip(section[:, 0] - 1 - (c0 + left) + 1, 0, crop.shape[1] - 1)
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    level = raw[section[:, 1] - 1, section[:, 0] - 1].astype(np.float64).mean()
    return ({"width_um": float(np.median(2 * near[r, c]) * pixconv), "brightness": float(level / bright_ref)}
            | area.areas(sel, top, left, pixels, ais_start, ais_end, pixconv))


def run_click(prep: aa.PreparedImage, raw: np.ndarray | None, click: tuple[float, float],
              click2: tuple[float, float] | None, threshold: float, settings: aa.Settings = aa.DEFAULT,
              cache: dict | None = None, outline: bool = True, bright_ref: float | None = None) -> dict[str, Any]:
    """service.run_click on this module's trace."""
    from app.analysis.service import _xy, bright_level

    out: dict[str, Any] = {"ok": False, "stage": "trace", "error": None,
                           "settings": settings.to_dict(), "settings_changed": settings.changed()}
    try:
        tr = trace(prep, click, click2, threshold, settings, cache)
    except MatlabError as exc:
        out["error"] = str(exc)
        return out
    sel = tr.selected
    rows, cols = np.nonzero(sel)
    out.update({
        "threshold_initial": tr.threshold_initial,
        "threshold": tr.threshold,
        "rethresholded": tr.rethresholded,
        "clicks": [list(c) for c in tr.clicks],
        "component": {
            "pixels": int(rows.size),
            "bbox": [int(cols.min()) + tr.c + 1, int(rows.min()) + tr.r + 1,
                     int(cols.max()) + tr.c + 1, int(rows.max()) + tr.r + 1],
        },
        "start": [tr.start[1], tr.start[0]],
        "passes": len(tr.passes),
        "path": _xy(tr.path),
    })
    if outline:
        here = np.array([tr.r + 1, tr.c + 1])
        out["component"]["edge"] = _xy(np.argwhere(sel & ~ml.imerode_square3(sel)) + here)
        out["skeleton"] = _xy(np.argwhere(tr.skeleton) + here)
    if raw is None:
        out.update({"stage": "measure", "error": "no raw image: the original reads the profile from <cell>.tif"})
        return out
    out["stage"] = "measure"
    try:
        ms = aa.measure(tr.path, raw, settings)
    except MatlabError as exc:
        out["error"] = str(exc)
        return out
    out.update({
        "ok": True,
        "stage": "done",
        "spline": np.round(ms.xysm.T, 3).tolist(),
        "pixels": [[int(x), int(y)] for x, y in zip(ms.x_pix, ms.y_pix)],
        "profile": {"lv_ss": ms.lv_ss.tolist(), "norm_lv": ms.norm_lv.tolist(), "max_i": ms.max_i,
                    "ais_start": ms.ais_start, "ais_end": ms.ais_end, "f": settings.f, "pixconv": settings.pixconv},
        "measures": {"start_um": ms.debut, "end_um": ms.fin, "mid_um": ms.mid, "max_um": ms.maxi,
                     "length_um": ms.lngth, "length_str": ms.lngth_str, "arc_um": ms.arc_um},
        "notes": ms.notes,
    })
    out["shape"] = shape(sel, tr.r, tr.c, raw, out["pixels"], ms.ais_start, ms.ais_end, settings.pixconv,
                         bright_ref if bright_ref is not None else bright_level(raw))
    return out


def detect(prep: aa.PreparedImage, raw: np.ndarray | None, threshold: float = 0.01,
           settings: aa.Settings = aa.DEFAULT, start: str = "both",
           exclude: list[list[list[int]]] | None = None, soma: Somata | None = None,
           stats: dict | None = None) -> dict[str, Any]:
    """detect.detect on this module's run_click. stats: filled with how many
    re-thresholds took a window and how many the whole image."""
    from app.analysis.service import bright_level

    if start not in auto.STARTS:
        raise ValueError("start must be one of " + ", ".join(auto.STARTS))
    if start == "learned":
        return detect_learned(prep, raw, threshold, settings, exclude, soma, stats)
    if start == "soma" and soma is None:
        raise ValueError('start "soma" needs the somata')
    fitted2 = start == "fitted2"
    fitted = start in ("fitted", "fitted2")
    if fitted:
        start = "soma" if soma is not None else "both"
    profile = raw if raw is not None else prep.pic
    if profile.ndim == 3:
        profile = profile[:, :, 0]
    cache: dict = {}
    reference = bright_level(profile)
    level = _initial(prep, threshold, cache)
    L, boxes = _labels(prep, level, settings, cache)
    sizes = np.bincount(L.ravel())
    labels = [k for k in range(1, len(boxes) + 1) if boxes[k - 1] is not None and sizes[k]]
    order = sorted(labels, key=lambda k: -sizes[k])[:auto.MAX_COMPONENTS]
    shape_ = prep.pic.shape
    known = auto._mask([p for trace_ in exclude or [] for p in trace_], shape_, auto.EXCLUDE_REACH)
    claimed = np.zeros(shape_, bool)
    out: dict[str, Any] = {"candidates": [], "components": len(labels), "merged": 0, "known": 0, "failed": 0}
    if soma is not None:
        out["somata"] = soma.outlines

    clicked: dict[tuple[int, int], dict[str, Any]] = {}
    smooth3: list[np.ndarray] = []

    def smooth() -> np.ndarray:
        if not smooth3:
            smooth3.append(ndi.uniform_filter(profile.astype(np.float64), 3))
        return smooth3[0]

    def plain_click(rc: tuple[int, int]) -> dict[str, Any]:
        if rc not in clicked:
            clicked[rc] = run_click(prep, raw, (rc[1] + 1.0, rc[0] + 1.0), None, threshold, settings, cache,
                                    outline=False, bright_ref=reference) | {"seed": [rc[1] + 1, rc[0] + 1]}
        return clicked[rc]

    def click(rc: tuple[int, int]) -> dict[str, Any]:
        found = dict(plain_click(rc))
        m = found.get("measures")
        if found["ok"] and m["length_um"] > m["arc_um"] + settings.pixconv and (
                not fitted2 or not auto.reaches_end(found)
                or m["length_um"] > (1 + auto.GATE_EXCESS) * m["arc_um"] + settings.pixconv):
            found.update({"ok": False, "error": "length longer than the trace"})
        return found

    def refit(tr: Trace, ends: tuple[tuple[int, int], tuple[int, int]]) -> dict[str, Any] | None:
        bright = [auto._brightness(profile, rc) for rc in ends]
        if soma is not None and max(bright) < auto.RATIO_END * min(bright):
            first = 0 if soma.gap_um[ends[0]] <= soma.gap_um[ends[1]] else 1
        else:
            first = 0 if bright[0] >= bright[1] else 1
        tries = [ends[first], ends[1 - first]]
        path = [(r + tr.r, c + tr.c) for r, c in auto.skeleton_path(
            tr.skeleton, *((r - tr.r, c - tr.c) for r, c in tries))]
        if path:
            tries.insert(0, auto.fitted_seed(path, smooth(), settings.pixconv))
        return next((plain_click(rc) for rc in tries if auto.reaches_end(plain_click(rc))), None)

    for label in order:
        box = boxes[label - 1]
        comp = L[box] == label
        if (comp & claimed[box]).sum() > auto.OVERLAP * comp.sum():
            out["merged"] += 1
            continue
        local = np.unravel_index(int(np.argmax(np.where(comp, prep.D[box], -1.0))), comp.shape)
        bright = (box[0].start + int(local[0]), box[1].start + int(local[1]))
        try:
            tr = trace(prep, (bright[1] + 1.0, bright[0] + 1.0), None, threshold, settings, cache)
        except MatlabError:
            out["failed"] += 1
            continue
        h, w = tr.selected.shape
        here = (slice(tr.r, tr.r + h), slice(tr.c, tr.c + w))
        if (tr.selected & claimed[here]).sum() > auto.OVERLAP * tr.selected.sum():
            out["merged"] += 1
            continue
        claimed[here] |= tr.selected
        claimed[box] |= comp
        a, b = auto.skeleton_ends(tr.skeleton, (tr.start[0] - 1 - tr.r, tr.start[1] - 1 - tr.c))
        ends = ((a[0] + tr.r, a[1] + tr.c), (b[0] + tr.r, b[1] + tr.c))
        if start == "both":
            best = auto._better(click(ends[0]), click(ends[1]))
        else:
            if start == "soma":
                first, second = sorted(ends, key=lambda rc: float(soma.gap_um[rc]))
            else:
                first, second = sorted(ends, key=lambda rc: auto._brightness(profile, rc), reverse=start == "brighter")
            best = click(first)
            if not best["ok"]:
                best = auto._better(best, click(second))
        if not best["ok"]:
            out["failed"] += 1
            continue
        filt = dict(best["shape"], length_um=best["measures"]["length_um"],
                    branchiness=float(tr.skeleton.sum()) * settings.pixconv / max(best["measures"]["arc_um"], 1e-9))
        if fitted:
            best = dict(refit(tr, ends) or best)
        if fitted2:
            filt["contrast"] = auto.trace_contrast(best, profile, smooth(), reference)
        best["filter"] = filt
        pixels = best["pixels"]
        if known.any() and sum(known[y - 1, x - 1] for x, y in pixels) > auto.OVERLAP * len(pixels):
            out["known"] += 1
            continue
        if soma is not None:
            gap = soma.gap_at(*pixels[0])
            best["soma_gap_um"] = round(gap, 2) if np.isfinite(gap) else None   # None: no somata found
        out["candidates"].append(best)
    if stats is not None:
        stats.update(cache.get("stats", {}))
    return out


# --- method "learned" ------------------------------------------------------------


@dataclass
class Blob:
    """learned.Blob with the masks cropped; r and c say where."""
    threshold_initial: float
    threshold: float
    selected: np.ndarray
    skeleton: np.ndarray
    r: int
    c: int


def _blob(prep: aa.PreparedImage, rc: tuple[int, int], threshold: float, settings: aa.Settings, cache: dict) -> Blob:
    click = (rc[1] + 1.0, rc[0] + 1.0)
    initial = _initial(prep, threshold, cache)
    crop, level, _, _, _ = _selected(prep, [click, click], initial, settings, cache)
    return Blob(initial, level, crop.mask, crop.skeleton(), crop.r, crop.c)


def _components(prep: aa.PreparedImage, profile: np.ndarray, reference: float, threshold: float,
                settings: aa.Settings, cache: dict, soma: Somata | None) -> tuple[list[dict[str, Any]], int]:
    """learned.components."""
    level = _initial(prep, threshold, cache)
    L, boxes = _labels(prep, level, settings, cache)
    sizes = np.bincount(L.ravel())
    labels = [k for k in range(1, len(boxes) + 1) if boxes[k - 1] is not None and sizes[k]]
    order = sorted(labels, key=lambda k: -sizes[k])[:learned.TOP_COMPONENTS]
    px = settings.pixconv
    seen: set[tuple] = set()
    out = []
    for rank, label in enumerate(order):
        box = boxes[label - 1]
        comp = L[box] == label
        local = np.unravel_index(int(np.argmax(np.where(comp, prep.D[box], -1.0))), comp.shape)
        bright = (box[0].start + int(local[0]), box[1].start + int(local[1]))
        tr = _blob(prep, bright, threshold, settings, cache)
        rows, cols = np.nonzero(tr.selected)
        rows, cols = rows + tr.r, cols + tr.c
        key = (tr.threshold, rows.size, int(rows[0]), int(cols[0]))
        if key in seen:
            continue
        seen.add(key)
        nb = learned._neighbours(tr.skeleton)
        f = {
            "comp_area_um2": rows.size * px * px,
            "comp_skeleton_um": float(tr.skeleton.sum()) * px,
            "comp_ends": int((nb == 1).sum()),
            "comp_branch_points": int((nb >= 3).sum()),
            "comp_elongation": learned._elongation(rows, cols),
            "comp_rethreshold": tr.threshold / tr.threshold_initial if tr.threshold_initial else 1.0,
            "comp_max_rel": float(profile[rows, cols].max()) / reference,
            "comp_mean_rel": float(profile[rows, cols].astype(np.float64).mean()) / reference,
            "comp_rank": rank,
            "comp_soma_gap_um": float(soma.gap_um[rows, cols].min()) if soma is not None else math.nan,
            "comp_on_soma": float(soma.mask[rows, cols].mean()) if soma is not None else math.nan,
        }
        out.append({"blob": tr, "features": f})
    return out, len(labels)


def _seeds(blob: Blob, shape_: tuple[int, int]) -> list[tuple[int, int]]:
    """learned.seeds in whole-image coordinates, the border being the image's."""
    skel = blob.skeleton
    nb = learned._neighbours(skel)
    H, W = shape_
    here = lambda p: (p[0] + blob.r, p[1] + blob.c)
    ok = lambda p: learned.BORDER <= p[0] < H - learned.BORDER and learned.BORDER <= p[1] < W - learned.BORDER
    ends = [tuple(map(int, p)) for p in np.argwhere(skel & (nb == 1))]
    rest = [tuple(map(int, p)) for p in np.argwhere(skel)]
    starts = ends or rest[:1]
    out = [here(p) for p in ends if ok(here(p))]
    for p, d in sorted(learned._geodesic(skel, starts).items(), key=lambda kv: (kv[1], kv[0])):
        if d and d % learned.SEED_STEP_PX == 0 and ok(here(p)):
            out.append(here(p))
    return out


def _candidates(prep: aa.PreparedImage, raw: np.ndarray | None, threshold: float, settings: aa.Settings,
                soma: Somata | None, prefilter: tuple[learned.Forest, float], cache: dict) -> tuple[list[dict[str, Any]], dict]:
    """learned.candidates."""
    from app.analysis.service import bright_level

    profile = raw if raw is not None else prep.pic
    if profile.ndim == 3:
        profile = profile[:, :, 0]
    reference = bright_level(profile)
    comps, n_components = _components(prep, profile, reference, threshold, settings, cache, soma)
    smooth3 = ndi.uniform_filter(profile.astype(np.float64), 3)
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    counts = {"components": n_components, "blobs": len(comps), "seeds": 0, "failed": 0, "skipped": 0}
    seeded = [True] * len(comps)
    if comps:
        model, cut = prefilter
        Xc = np.array([[c["features"][k] for k in model.features] for c in comps], np.float64)
        seeded = (model.predict(Xc) >= cut).tolist()
        counts["skipped"] = seeded.count(False)
    for i, comp in enumerate(comps):
        if not seeded[i]:
            continue
        for seed in _seeds(comp["blob"], prep.pic.shape):
            counts["seeds"] += 1
            found = run_click(prep, profile, (seed[1] + 1.0, seed[0] + 1.0), None, threshold, settings, cache,
                              outline=False, bright_ref=reference)
            if not found["ok"]:
                counts["failed"] += 1
                continue
            key = tuple(map(tuple, found["pixels"]))
            if key in seen:
                continue
            seen.add(key)
            found["seed"] = [seed[1] + 1, seed[0] + 1]
            found["blob"] = i
            found["features"] = learned.trace_features(found, comp, seed, profile, smooth3, reference, soma,
                                                       n_components, settings)
            out.append(found)
    return out, counts


def detect_learned(prep: aa.PreparedImage, raw: np.ndarray | None, threshold: float = 0.01,
                   settings: aa.Settings = aa.DEFAULT, exclude: list[list[list[int]]] | None = None,
                   soma: Somata | None = None, stats: dict | None = None) -> dict[str, Any]:
    """learned.detect."""
    m = learned.models()
    meta = m["meta"]
    plain = "" if soma is not None else "_plain"
    cache: dict = {}
    cands, counts = _candidates(prep, raw, threshold, settings, soma,
                                (m["component" + plain], meta.get("component_keep", learned.COMPONENT_KEEP)), cache)
    if stats is not None:
        stats.update(cache.get("stats", {}))
    out: dict[str, Any] = {"candidates": [], "components": counts["components"], "merged": 0, "known": 0,
                           "failed": counts["failed"]}
    if soma is not None:
        out["somata"] = soma.outlines
    if not cands:
        return out
    score = m["ais" + plain].predict(learned.feature_matrix(cands, m["ais" + plain].features))
    shape_ = prep.pic.shape
    keep = meta.get("keep", learned.KEEP_SCORE)
    known = np.zeros(len(cands), bool)
    accepted = [p for trace_ in exclude or [] for p in trace_]
    if accepted:
        on = learned.on_fractions([c["pixels"] for c in cands], [accepted], shape_, learned.EXCLUDE_REACH)
        known = on.toarray().ravel() > learned.OVERLAP
        out["known"] = len(learned.pick(cands, np.where(known, score, -1.0), shape_, keep))
    for i in learned.pick(cands, np.where(known, -1.0, score), shape_, keep):
        c = {k: v for k, v in cands[i].items() if k not in ("features", "blob")}
        c["filter"] = {"score": round(float(score[i]), 4), "length_um": c["measures"]["length_um"]}
        if soma is not None:
            gap = soma.gap_at(*c["pixels"][0])
            c["soma_gap_um"] = round(gap, 2) if np.isfinite(gap) else None
        out["candidates"].append(c)
    return out
