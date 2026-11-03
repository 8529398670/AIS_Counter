"""Auto mode: every AIS on an image, without clicks.

The original needs one click near the start of each AIS. Here the clicks are
chosen for it, and each one goes through the unchanged port (ais_auto.py via
service.run_click), so a found AIS is exactly what clicking at its seed gives:

1. Threshold and segment as the original does; every component left is a
   candidate, largest first.
2. Click the component's brightest pixel once, to get the re-thresholded
   component and its skeleton. Components that re-thresholding merged into
   one already found are skipped.
3. The skeleton's two far ends (its geodesic diameter) are the possible
   starts. start picks between them: "both" traces from each and keeps the
   one that measures, then the longer trace; "brighter" / "dimmer" try that
   end of the raw image first and the other only if it fails; "soma" (CZI
   mode) tries the end nearer a soma first, as an AIS leaves its soma.
   "fitted" picks the end and the seed the way a person clicks (below), and
   "fitted2" does too, with two changes (below).
4. A candidate that does not measure, or whose length is longer than its own
   trace (the original's ais_end fallback, see ais_auto.measure), is left
   out and counted as failed.
   Each candidate carries "filter": the length, brightness and width of
   that measure and its component's branchiness (skeleton length over
   trace length; 1 is one unbranched line), which methods Fitted and
   Fitted 2 judge it by (static/js/ais_auto.js passesFitted; Classic's
   filters judge the reported measures and shape, as always). "fitted2"
   adds the shown AIS's contrast to it.
5. A candidate lying mostly on an AIS already accepted on this image
   (exclude) is dropped, so running auto again adds only what is new.
6. With somata (soma.py, CZI mode), each candidate carries soma_gap_um, how
   far its start is from the nearest soma, for the client to filter by.

"fitted" (Settings > Auto mode's trial method "Fitted"; the classic starts
above are untouched by it): which components measure, and their
"filter", are as for "soma" on a CZI and "both" on a TIFF. The trace shown
starts where a person would click instead: at the end that is clearly
brighter (by RATIO_END), else the one nearer a soma (a TIFF: the brighter
one), and FIT_SLOPE * c + FIT_OFFSET_UM along the skeleton from it, where c
is how far the smoothed raw intensity takes to rise FIT_RISE of the way from
its lowest to its highest. A person clicks a few um into an AIS, and the
original measures from the click. If that click does not measure, the end's
own trace, then the other end's, stand in. Against the same 86 AIS this
takes the length error from 4.3 um to 1.9 um (mean, absolute).

"fitted2" (method "Fitted 2", a second trial; "fitted" and the classic
starts are untouched by it) is "fitted" learnt again from 76 images, with
the AIS fitted missed added by hand (tests/autodata/batch12_test.json and
batch12_auto.json):
- A bright AIS that fills its whole blob measures up to about 10% longer
  than its arc, and step 4 left it out. Here such a measure is left out
  only if its profile does not come back down (reaches_end) or it is more
  than GATE_EXCESS longer than its trace.
- "filter" also has "contrast" (trace_contrast): how much brighter the AIS
  is than the background just around it, as a fraction of the image's
  bright level. A clear AIS in an image with a few very bright spots is
  dim by brightness but not by contrast.

"learned" (method "Learned") is its own detector, app/analysis/learned.py,
learnt from 3,277 hand-clicked AIS; detect() only hands it over, and
nothing above applies to it.

All clicks on one image share a cache (ais_auto.trace), so each threshold is
segmented and each component thinned once.
"""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from scipy import ndimage as ndi

from app.analysis import ais_auto as aa
from app.analysis import mlcompat as ml
from app.analysis.soma import Somata

STARTS = ("both", "brighter", "dimmer", "soma", "fitted", "fitted2", "learned")
MAX_COMPONENTS = 200
OVERLAP = 0.5      # a component or trace this much inside earlier ones is a repeat
EXCLUDE_REACH = 2  # px around an accepted trace that still counts as on it
# "fitted" (scripts/auto_eval.py, fitted on tests/autodata/batch12.json)
RATIO_END = 1.3    # an end this many times brighter than the other is the start
FIT_RISE = 0.33    # c: where the profile from the start end has risen this much
FIT_SLOPE = 0.5    # the click goes FIT_SLOPE * c + FIT_OFFSET_UM along the skeleton
FIT_OFFSET_UM = 2.0
FIT_WINDOW = 19    # px of skeleton the profile is smoothed over
# "fitted2" (scripts/auto_eval.py, on all three tests/autodata files)
GATE_EXCESS = 0.10       # a measure whose profile ends may be this much longer than its trace
CONTRAST_BOX = 20        # px around the AIS searched for its background
CONTRAST_RING = (6, 12)  # px from the AIS that are its background


def _far_end(skel: np.ndarray, start: tuple[int, int]) -> tuple[int, int]:
    """The skeleton pixel the most 8-connected steps from start."""
    H, W = skel.shape
    seen = {start}
    queue = deque([start])
    last = start
    while queue:
        last = queue.popleft()
        r, c = last
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                p = (r + dr, c + dc)
                if 0 <= p[0] < H and 0 <= p[1] < W and skel[p] and p not in seen:
                    seen.add(p)
                    queue.append(p)
    return last


def skeleton_ends(skel: np.ndarray, near: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    """The two ends of the skeleton's longest walk, 0-based (row, col), found
    from the skeleton pixel nearest near (0-based (row, col))."""
    first = ml.bwdist_nearest(skel, *near)
    a = _far_end(skel, first)
    return a, _far_end(skel, a)


def skeleton_path(skel: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """The shortest 8-connected walk on the skeleton from a to b, both
    0-based (row, col) and included; [] if they are not connected."""
    H, W = skel.shape
    prev = {a: None}
    queue = deque([a])
    while queue:
        p = queue.popleft()
        if p == b:
            break
        r, c = p
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                q = (r + dr, c + dc)
                if 0 <= q[0] < H and 0 <= q[1] < W and skel[q] and q not in prev:
                    prev[q] = p
                    queue.append(q)
    if b not in prev:
        return []
    out = [b]
    while prev[out[-1]] is not None:
        out.append(prev[out[-1]])
    return out[::-1]


def fitted_seed(path: list[tuple[int, int]], smooth3: np.ndarray, pixconv: float) -> tuple[int, int]:
    """Where along path (from its start end) "fitted" clicks; smooth3 is the
    raw image's 3x3 mean."""
    P = np.array(path)
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(P.astype(np.float64), axis=0).T))] * pixconv
    p = ndi.uniform_filter1d(smooth3[P[:, 0], P[:, 1]], FIT_WINDOW, mode="nearest")
    lo, hi = p.min(), p.max()
    c = s[int(np.argmax(p >= lo + FIT_RISE * (hi - lo)))]
    i = int(np.argmin(np.abs(s - max(0.0, FIT_SLOPE * c + FIT_OFFSET_UM))))
    return int(P[i, 0]), int(P[i, 1])


def reaches_end(found: dict[str, Any]) -> bool:
    """Its profile falls below f after its peak, so ais_end is a real end and
    not the original's fallback to the trace's last pixel."""
    if not found["ok"]:
        return False
    prof = found["profile"]
    norm = np.asarray(prof["norm_lv"])
    return bool(np.any(norm[int(prof["max_i"]):] > prof["f"]))


def trace_contrast(found: dict[str, Any], raw: np.ndarray, smooth3: np.ndarray, reference: float) -> float:
    """"fitted2": the AIS part of found's trace (its profile's ais_start to
    ais_end), its mean in smooth3 (raw's 3x3 mean) less the median of raw
    CONTRAST_RING px around it, over reference (service.bright_level)."""
    P = np.asarray(found["pixels"])
    prof = found["profile"]
    a = max(int(round(prof["ais_start"])), 1)
    b = min(int(round(prof["ais_end"])), len(P))
    S = P[a - 1:b] if b - a >= 1 else P
    rows, cols = S[:, 1] - 1, S[:, 0] - 1
    level = float(smooth3[rows, cols].mean())
    H, W = raw.shape
    r0, r1 = max(int(rows.min()) - CONTRAST_BOX, 0), min(int(rows.max()) + CONTRAST_BOX, H - 1)
    c0, c1 = max(int(cols.min()) - CONTRAST_BOX, 0), min(int(cols.max()) + CONTRAST_BOX, W - 1)
    on = np.zeros((r1 - r0 + 1, c1 - c0 + 1), bool)
    on[rows - r0, cols - c0] = True
    d = ndi.distance_transform_edt(~on)
    ring = (d >= CONTRAST_RING[0]) & (d <= CONTRAST_RING[1])
    if not ring.any():
        ring = d >= 1
    bg = float(np.median(raw[r0:r1 + 1, c0:c1 + 1][ring].astype(np.float64)))
    return (level - bg) / reference


def _brightness(raw: np.ndarray, rc: tuple[int, int]) -> float:
    r, c = rc
    return float(raw[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].astype(np.float64).mean())


def _better(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """"both": the one that measures, then the longer trace, then the longer AIS."""
    def key(out: dict[str, Any]) -> tuple:
        return (bool(out["ok"]), len(out.get("path") or []), (out.get("measures") or {}).get("length_um", 0))
    return b if key(b) > key(a) else a


def _mask(points: list[list[int]], shape: tuple[int, int], reach: int = 0) -> np.ndarray:
    """1-based [x, y] points as a mask, grown by reach pixels."""
    mask = np.zeros(shape, bool)
    for x, y in points:
        if 1 <= y <= shape[0] and 1 <= x <= shape[1]:
            mask[y - 1, x - 1] = True
    return ml.imdilate_square(mask, 2 * reach + 1) if reach and mask.any() else mask


def detect(prep: aa.PreparedImage, raw: np.ndarray | None, threshold: float = 0.01,
           settings: aa.Settings = aa.DEFAULT, start: str = "both",
           exclude: list[list[list[int]]] | None = None, soma: Somata | None = None) -> dict[str, Any]:
    """{candidates, components, merged, known, failed, somata?}. Each
    candidate is run_click's JSON for its seed (see service.run_click),
    without the component outline and skeleton, plus "seed" [x, y],
    "filter" {length_um, brightness, width_um, branchiness, and contrast
    for "fitted2"} (and "soma_gap_um" when soma is given). exclude is the traces already accepted
    on the image, each a list of 1-based [x, y] pixels. somata: soma's
    outlines, for drawing."""
    from app.analysis.service import bright_level, run_click

    if start not in STARTS:
        raise ValueError("start must be one of " + ", ".join(STARTS))
    if start == "learned":
        from app.analysis import learned
        return learned.detect(prep, raw, threshold, settings, exclude, soma)
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
    level = ml.graythresh(prep.smooth) if threshold == 0 else threshold
    L = aa.segment(prep, level, settings)
    cache[("L", level)] = L
    boxes = ndi.find_objects(L)
    sizes = np.bincount(L.ravel())
    labels = [k for k in range(1, len(boxes) + 1) if boxes[k - 1] is not None and sizes[k]]
    order = sorted(labels, key=lambda k: -sizes[k])[:MAX_COMPONENTS]
    shape = prep.pic.shape
    known = _mask([p for trace in exclude or [] for p in trace], shape, EXCLUDE_REACH)
    claimed = np.zeros(shape, bool)
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
                not fitted2 or not reaches_end(found)
                or m["length_um"] > (1 + GATE_EXCESS) * m["arc_um"] + settings.pixconv):
            found.update({"ok": False, "error": "length longer than the trace"})
        return found

    def refit(tr: aa.Trace, ends: tuple[tuple[int, int], tuple[int, int]]) -> dict[str, Any] | None:
        """"fitted" and "fitted2": the trace from where a person would click."""
        bright = [_brightness(profile, rc) for rc in ends]
        if soma is not None and max(bright) < RATIO_END * min(bright):
            first = 0 if soma.gap_um[ends[0]] <= soma.gap_um[ends[1]] else 1
        else:
            first = 0 if bright[0] >= bright[1] else 1
        tries = [ends[first], ends[1 - first]]
        path = skeleton_path(tr.skeleton, *tries)
        if path:
            tries.insert(0, fitted_seed(path, smooth(), settings.pixconv))
        return next((plain_click(rc) for rc in tries if reaches_end(plain_click(rc))), None)

    for label in order:
        box = boxes[label - 1]
        comp = L[box] == label
        if (comp & claimed[box]).sum() > OVERLAP * comp.sum():
            out["merged"] += 1
            continue
        local = np.unravel_index(int(np.argmax(np.where(comp, prep.D[box], -1.0))), comp.shape)
        bright = (box[0].start + int(local[0]), box[1].start + int(local[1]))
        try:
            tr = aa.trace(prep, (bright[1] + 1.0, bright[0] + 1.0), None, threshold, settings, cache)
        except ml.MatlabError:
            out["failed"] += 1
            continue
        if (tr.selected & claimed).sum() > OVERLAP * tr.selected.sum():
            out["merged"] += 1
            continue
        claimed |= tr.selected
        claimed[box] |= comp
        ends = skeleton_ends(tr.skeleton, (tr.start[0] - 1, tr.start[1] - 1))
        if start == "both":
            best = _better(click(ends[0]), click(ends[1]))
        else:
            if start == "soma":
                first, second = sorted(ends, key=lambda rc: float(soma.gap_um[rc]))
            else:
                first, second = sorted(ends, key=lambda rc: _brightness(profile, rc), reverse=start == "brighter")
            best = click(first)
            if not best["ok"]:
                best = _better(best, click(second))
        if not best["ok"]:
            out["failed"] += 1
            continue
        filt = dict(best["shape"], length_um=best["measures"]["length_um"],
                    branchiness=float(tr.skeleton.sum()) * settings.pixconv / max(best["measures"]["arc_um"], 1e-9))
        if fitted:
            best = dict(refit(tr, ends) or best)
        if fitted2:
            filt["contrast"] = trace_contrast(best, profile, smooth(), reference)
        best["filter"] = filt
        pixels = best["pixels"]
        if known.any() and sum(known[y - 1, x - 1] for x, y in pixels) > OVERLAP * len(pixels):
            out["known"] += 1
            continue
        if soma is not None:
            gap = soma.gap_at(*pixels[0])
            best["soma_gap_um"] = round(gap, 2) if np.isfinite(gap) else None   # None: no somata found
        out["candidates"].append(best)
    return out
