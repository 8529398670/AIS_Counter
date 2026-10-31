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
   end of the raw image first and the other only if it fails.
4. A candidate that does not measure, or whose length is longer than its own
   trace (the original's ais_end fallback, see ais_auto.measure), is left
   out and counted as failed.
5. A candidate lying mostly on an AIS already accepted on this image
   (exclude) is dropped, so running auto again adds only what is new.

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

STARTS = ("both", "brighter", "dimmer")
MAX_COMPONENTS = 200
OVERLAP = 0.5      # a component or trace this much inside earlier ones is a repeat
EXCLUDE_REACH = 2  # px around an accepted trace that still counts as on it


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
           exclude: list[list[list[int]]] | None = None) -> dict[str, Any]:
    """{candidates, components, merged, known, failed}. Each candidate is
    run_click's JSON for its seed (see service.run_click), without the
    component outline and skeleton, plus "seed" [x, y]. exclude is the traces
    already accepted on the image, each a list of 1-based [x, y] pixels."""
    from app.analysis.service import bright_level, run_click

    if start not in STARTS:
        raise ValueError("start must be one of " + ", ".join(STARTS))
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

    def click(rc: tuple[int, int]) -> dict[str, Any]:
        found = run_click(prep, raw, (rc[1] + 1.0, rc[0] + 1.0), None, threshold, settings, cache,
                          outline=False, bright_ref=reference)
        m = found.get("measures")
        if found["ok"] and m["length_um"] > m["arc_um"] + settings.pixconv:
            found.update({"ok": False, "error": "length longer than the trace"})
        return found | {"seed": [rc[1] + 1, rc[0] + 1]}

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
            first, second = sorted(ends, key=lambda rc: _brightness(profile, rc), reverse=start == "brighter")
            best = click(first)
            if not best["ok"]:
                best = _better(best, click(second))
        if not best["ok"]:
            out["failed"] += 1
            continue
        pixels = best["pixels"]
        if known.any() and sum(known[y - 1, x - 1] for x, y in pixels) > OVERLAP * len(pixels):
            out["known"] += 1
            continue
        out["candidates"].append(best)
    return out
