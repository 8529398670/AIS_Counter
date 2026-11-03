"""Auto mode "learned": every AIS on an image, picked the way the people who
hand-clicked example-data-2 (3,277 AIS on 600 images, batches C2 and C4-C7)
picked
them.

Like every auto mode, each AIS found is exactly what one click gives
(service.run_click), so its length is the original's. What is learnt is
where to click and which of the results a person would have kept:

1. Components. Threshold and segment as the original does; for each of
   the TOP_COMPONENTS largest, the re-thresholded blob and its skeleton that
   a click anywhere on it gets (blob(): ais_auto.trace up to its walk, so a
   blob whose walk from one pixel would hit the border is not lost). Blobs
   that come out the same are one. A small model
   ("component", on COMPONENT_FEATURES) leaves out the blobs no person would
   click anything on (scored under the model's component_keep), which saves
   most of the clicking below.
2. Seeds. A click's trace starts at the skeleton pixel nearest it, so the
   seeds are skeleton pixels: every end, and every SEED_STEP_PX along the
   skeleton between them (a person often clicks where the AIS starts, partway
   along a blob). Every seed is clicked, and seeds whose traces come out the
   same are one candidate.
3. Score. A gradient-boosted tree model ("ais", learned_model.json) gives
   each candidate the chance that a person's click gives it: that it lies
   on an AIS a person clicked and measures within 2 um of what they
   measured. Judging the click and the AIS together matters: scored only on
   whether it is an AIS, a long trace running on past the AIS wins over the
   one a person would have made. From FEATURES: its measures and intensity
   profile, its width, brightness and contrast against the background around
   it, its blob's size and shape, how near a soma it starts and ends (CZI
   mode), and how near the border it is. Without somata (a TIFF pair) the
   models "ais_plain" and "component_plain" are used instead, trained the
   same way without the SOMA_FEATURES.
4. Pick. Highest score first; a candidate lying on one already picked is
   left out.

Every candidate has "filter": {"score", "length_um"}; the client keeps those
with score at least Settings > Auto mode's lowest score. The models are
trained by scripts/train_learned.py (scikit-learn, not needed here: the trees
are evaluated with numpy, by Forest).
"""
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage as ndi
from scipy import sparse

from app.analysis import ais_auto as aa
from app.analysis import mlcompat as ml
from app.analysis.soma import Somata

MODEL_PATH = Path(__file__).with_name("learned_model.json")
TOP_COMPONENTS = 40     # largest components looked at; every clicked AIS was in its image's 20 largest
SEED_STEP_PX = 10       # skeleton px between seeds
REACH = 3               # px around a picked trace that a candidate on it may lie in
OVERLAP = 0.5           # this much of a trace on another's is the same AIS
KEEP_SCORE = 0.02       # candidates scored lower are not sent at all
EXCLUDE_REACH = 2       # px around an accepted trace that still counts as on it (detect.py's)
COMPONENT_KEEP = 0.02   # blobs the pre-filter scores lower are not seeded
BORDER = 1              # a skeleton this close to the edge cannot be traced (ais_auto.trace)

COMPONENT_FEATURES = (
    "comp_area_um2", "comp_skeleton_um", "comp_ends", "comp_branch_points", "comp_elongation",
    "comp_rethreshold", "comp_max_rel", "comp_mean_rel", "comp_rank", "comp_soma_gap_um", "comp_on_soma",
)
TRACE_FEATURES = (
    "length_um", "arc_um", "start_um", "end_um", "max_um", "length_frac", "start_frac", "end_frac",
    "starts_in_ais", "reaches_end", "passes", "width_um", "brightness", "contrast",
    "peak_rel", "trace_start_rel", "trace_end_rel", "outside_rel", "tortuosity", "branchiness",
    "gap_first_um", "gap_last_um", "gap_ais_start_um", "gap_min_um", "border_um", "seed_offset_um",
    "image_ref", "image_components",
)
FEATURES = COMPONENT_FEATURES + TRACE_FEATURES
SOMA_FEATURES = ("comp_soma_gap_um", "comp_on_soma", "gap_first_um", "gap_last_um", "gap_ais_start_um", "gap_min_um")
CONTRAST_BOX = 20        # px around the AIS searched for its background
CONTRAST_RING = (6, 12)  # px from the AIS that are its background


# --- trees -----------------------------------------------------------------------


class Forest:
    """A scikit-learn HistGradientBoosting model's trees (exported by
    scripts/train_learned.py), evaluated with numpy. raw() is the summed
    tree output (a classifier's log-odds), predict() a classifier's
    probability or a regressor's value."""

    def __init__(self, spec: dict[str, Any]):
        self.kind = spec["kind"]
        self.features = list(spec["features"])
        self.baseline = float(spec["baseline"])
        self.trees = [{k: np.asarray(v) for k, v in tree.items()} for tree in spec["trees"]]

    def raw(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, np.float64)
        out = np.full(len(X), self.baseline)
        rows = np.arange(len(X))
        for t in self.trees:
            node = np.zeros(len(X), np.int64)
            while True:
                inner = ~t["leaf"][node]
                if not inner.any():
                    break
                n = node[inner]
                x = X[rows[inner], t["feature"][n]]
                left = np.where(np.isnan(x), t["missing_left"][n], x <= t["threshold"][n])
                node[inner] = np.where(left, t["left"][n], t["right"][n])
            out += t["value"][node]
        return out

    def predict(self, X: np.ndarray) -> np.ndarray:
        raw = self.raw(X)
        return 1.0 / (1.0 + np.exp(-raw)) if self.kind == "classifier" else raw


@lru_cache(maxsize=1)
def models() -> dict[str, Any]:
    """{"ais", "component", "ais_plain", "component_plain": Forest, "meta":
    {...}} from MODEL_PATH."""
    spec = json.loads(MODEL_PATH.read_text())
    return {k: Forest(v) for k, v in spec.items() if k != "meta"} | {"meta": spec.get("meta", {})}


# --- components and seeds --------------------------------------------------------------


def _neighbours(skel: np.ndarray) -> np.ndarray:
    """Per skeleton pixel, how many of its 8 neighbours are skeleton."""
    k = np.ones((3, 3), np.int32)
    k[1, 1] = 0
    return ndi.convolve(skel.astype(np.int32), k, mode="constant") * skel


def _geodesic(skel: np.ndarray, starts: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
    """8-connected steps along skel from the nearest of starts, for every
    skeleton pixel reachable from them."""
    H, W = skel.shape
    dist = {s: 0 for s in starts}
    queue = deque(starts)
    while queue:
        p = queue.popleft()
        r, c = p
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                q = (r + dr, c + dc)
                if 0 <= q[0] < H and 0 <= q[1] < W and skel[q] and q not in dist:
                    dist[q] = dist[p] + 1
                    queue.append(q)
    return dist


def seeds(skel: np.ndarray) -> list[tuple[int, int]]:
    """A skeleton's ends, then every SEED_STEP_PX along it from them,
    0-based (row, col); pixels touching the image border are left out."""
    nb = _neighbours(skel)
    H, W = skel.shape
    ok = lambda p: BORDER <= p[0] < H - BORDER and BORDER <= p[1] < W - BORDER
    ends = [tuple(map(int, p)) for p in np.argwhere(skel & (nb == 1))]
    rest = [tuple(map(int, p)) for p in np.argwhere(skel)]
    starts = ends or rest[:1]
    out = [p for p in ends if ok(p)]
    for p, d in sorted(_geodesic(skel, starts).items(), key=lambda kv: (kv[1], kv[0])):
        if d and d % SEED_STEP_PX == 0 and ok(p):
            out.append(p)
    return out


def _elongation(rows: np.ndarray, cols: np.ndarray) -> float:
    if rows.size < 3:
        return 1.0
    ev = np.linalg.eigvalsh(np.cov(np.vstack([rows, cols]).astype(np.float64)))
    return float(math.sqrt(max(ev[-1], 1e-9) / max(ev[0], 1e-9)))


@dataclass
class Blob:
    threshold_initial: float
    threshold: float          # the threshold the blob was selected at
    selected: np.ndarray      # bool mask, full size
    skeleton: np.ndarray      # its bwmorph thin, full size


def blob(prep: aa.PreparedImage, rc: tuple[int, int], threshold: float, settings: aa.Settings,
         cache: dict) -> Blob:
    """What ais_auto.trace selects and thins for a click at the 0-based
    (row, col) rc, before it walks the skeleton: the clicked component,
    re-thresholded once as the original does. Shares trace's cache keys."""
    X, Y = rc[1] + 1, rc[0] + 1
    initial = ml.graythresh(prep.smooth) if threshold == 0 else threshold
    level = initial
    L = aa._cached(cache, ("L", level), lambda: aa.segment(prep, level, settings))
    label = aa._select(L, X, Y)
    max_ais = float(((L == label) * prep.D).max())
    if prep.max_all != max_ais:
        level = (max_ais / prep.max_all) * initial
        L = aa._cached(cache, ("L", level), lambda: aa.segment(prep, level, settings))
        label = aa._select(L, X, Y)
    sel = L == label
    skel = aa._cached(cache, ("skel", level, label), lambda: ml.bwmorph_thin(sel))
    return Blob(threshold_initial=initial, threshold=level, selected=sel, skeleton=skel)


def components(prep: aa.PreparedImage, profile: np.ndarray, reference: float, threshold: float,
               settings: aa.Settings, cache: dict, soma: Somata | None) -> tuple[list[dict[str, Any]], int]:
    """The re-thresholded blobs of the TOP_COMPONENTS largest components,
    each {"blob": Blob, "features": {...}}, and how many components there
    are in all."""
    level = ml.graythresh(prep.smooth) if threshold == 0 else threshold
    L = cache.get(("L", level))
    if L is None:
        L = cache[("L", level)] = aa.segment(prep, level, settings)
    boxes = ndi.find_objects(L)
    sizes = np.bincount(L.ravel())
    labels = [k for k in range(1, len(boxes) + 1) if boxes[k - 1] is not None and sizes[k]]
    order = sorted(labels, key=lambda k: -sizes[k])[:TOP_COMPONENTS]
    px = settings.pixconv
    seen: set[tuple] = set()
    out = []
    for rank, label in enumerate(order):
        box = boxes[label - 1]
        comp = L[box] == label
        local = np.unravel_index(int(np.argmax(np.where(comp, prep.D[box], -1.0))), comp.shape)
        bright = (box[0].start + int(local[0]), box[1].start + int(local[1]))
        tr = blob(prep, bright, threshold, settings, cache)
        rows, cols = np.nonzero(tr.selected)
        key = (tr.threshold, rows.size, int(rows[0]), int(cols[0]))
        if key in seen:
            continue
        seen.add(key)
        nb = _neighbours(tr.skeleton)
        f = {
            "comp_area_um2": rows.size * px * px,
            "comp_skeleton_um": float(tr.skeleton.sum()) * px,
            "comp_ends": int((nb == 1).sum()),
            "comp_branch_points": int((nb >= 3).sum()),
            "comp_elongation": _elongation(rows, cols),
            "comp_rethreshold": tr.threshold / tr.threshold_initial if tr.threshold_initial else 1.0,
            "comp_max_rel": float(profile[rows, cols].max()) / reference,
            "comp_mean_rel": float(profile[rows, cols].astype(np.float64).mean()) / reference,
            "comp_rank": rank,
            "comp_soma_gap_um": float(soma.gap_um[rows, cols].min()) if soma is not None else math.nan,
            "comp_on_soma": float(soma.mask[rows, cols].mean()) if soma is not None else math.nan,
        }
        out.append({"blob": tr, "features": f})
    return out, len(labels)


# --- candidates ------------------------------------------------------------------


def _contrast(P: np.ndarray, raw: np.ndarray, smooth3: np.ndarray, reference: float) -> float:
    """Mean of smooth3 on the 0-based (row, col) pixels P, less the median of
    raw CONTRAST_RING px around them, over reference."""
    rows, cols = P[:, 0], P[:, 1]
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
    return (level - float(np.median(raw[r0:r1 + 1, c0:c1 + 1][ring]))) / reference


def trace_features(found: dict[str, Any], comp: dict[str, Any], seed: tuple[int, int], raw: np.ndarray,
                   smooth3: np.ndarray, reference: float, soma: Somata | None, n_components: int,
                   settings: aa.Settings) -> dict[str, float]:
    """FEATURES for one measured candidate (run_click's JSON) on comp."""
    m, prof, shape = found["measures"], found["profile"], found["shape"]
    px = settings.pixconv
    pix = np.asarray(found["pixels"])
    P = np.stack([pix[:, 1] - 1, pix[:, 0] - 1], axis=1)      # 0-based (row, col)
    n = len(P)
    a = min(max(int(round(prof["ais_start"])), 1), n) - 1
    b = min(max(int(round(prof["ais_end"])), 1), n)
    ais = P[a:b] if b - a >= 1 else P
    lv = np.asarray(prof["lv_ss"], np.float64)
    peak = float(lv.max()) if lv.size else 0.0
    outside = np.r_[lv[:a], lv[b:]] if lv.size else lv
    arc = max(m["arc_um"], 1e-9)
    H, W = raw.shape
    chord = float(np.hypot(*(P[-1] - P[0]))) * px
    gap = (lambda rc: float(soma.gap_um[rc[0], rc[1]])) if soma is not None else (lambda rc: math.nan)
    norm = np.asarray(prof["norm_lv"])
    start = found["start"]
    f = dict(comp["features"])
    f.update({
        "length_um": m["length_um"], "arc_um": m["arc_um"], "start_um": m["start_um"], "end_um": m["end_um"],
        "max_um": m["max_um"], "length_frac": m["length_um"] / arc, "start_frac": m["start_um"] / arc,
        "end_frac": m["end_um"] / arc,
        "starts_in_ais": float(prof["ais_start"] == 0),
        "reaches_end": float(bool(np.any(norm[int(prof["max_i"]):] > prof["f"]))),
        "passes": found["passes"], "width_um": shape["width_um"], "brightness": shape["brightness"],
        "contrast": _contrast(ais, raw, smooth3, reference),
        "peak_rel": peak / reference,
        "trace_start_rel": float(lv[0]) / peak if peak else 0.0,
        "trace_end_rel": float(lv[-1]) / peak if peak else 0.0,
        "outside_rel": float(outside.mean()) / peak if outside.size and peak else 0.0,
        "tortuosity": arc / max(chord, px),
        "branchiness": comp["features"]["comp_skeleton_um"] / arc,
        "gap_first_um": gap(P[0]), "gap_last_um": gap(P[-1]), "gap_ais_start_um": gap(ais[0]),
        "gap_min_um": float(soma.gap_um[P[:, 0], P[:, 1]].min()) if soma is not None else math.nan,
        "border_um": float(min(P[:, 0].min(), P[:, 1].min(), H - 1 - P[:, 0].max(), W - 1 - P[:, 1].max())) * px,
        "seed_offset_um": float(np.hypot(start[1] - 1 - seed[0], start[0] - 1 - seed[1])) * px,
        "image_ref": math.log10(max(reference, 1.0)),
        "image_components": n_components,
    })
    return f


def candidates(prep: aa.PreparedImage, raw: np.ndarray | None, threshold: float = 0.01,
               settings: aa.Settings = aa.DEFAULT, soma: Somata | None = None,
               prefilter: tuple[Forest, float] | None = None) -> tuple[list[dict[str, Any]], dict]:
    """Every distinct measured trace a seed gives, each run_click's JSON
    (no outline) with "seed" [x, y], "blob" (index into the components) and
    "features"; and counts {components, blobs, seeds,
    failed, skipped}. prefilter: the component model and the score under
    which a blob is not seeded (None seeds every blob, as training does)."""
    from app.analysis.service import bright_level, run_click

    profile = raw if raw is not None else prep.pic
    if profile.ndim == 3:
        profile = profile[:, :, 0]
    reference = bright_level(profile)
    cache: dict = {}
    comps, n_components = components(prep, profile, reference, threshold, settings, cache, soma)
    smooth3 = ndi.uniform_filter(profile.astype(np.float64), 3)
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    counts = {"components": n_components, "blobs": len(comps), "seeds": 0, "failed": 0, "skipped": 0}
    seeded = [True] * len(comps)
    if prefilter is not None and comps:
        model, cut = prefilter
        Xc = np.array([[c["features"][k] for k in model.features] for c in comps], np.float64)
        seeded = (model.predict(Xc) >= cut).tolist()
        counts["skipped"] = seeded.count(False)
    for i, comp in enumerate(comps):
        if not seeded[i]:
            continue
        for seed in seeds(comp["blob"].skeleton):
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
            found["features"] = trace_features(found, comp, seed, profile, smooth3, reference, soma,
                                               n_components, settings)
            out.append(found)
    return out, counts


def feature_matrix(cands: list[dict[str, Any]], names: list[str] | tuple[str, ...] = FEATURES) -> np.ndarray:
    """The candidates' features names, rounded to float32 as the models were
    trained on them (a value on a split threshold must go the same way)."""
    X = np.array([[c["features"][k] for k in names] for c in cands], np.float64).reshape(len(cands), len(names))
    return X.astype(np.float32).astype(np.float64)


def _flat(pixels: list[list[int]], W: int) -> np.ndarray:
    p = np.asarray(pixels).reshape(-1, 2)
    return (p[:, 1] - 1) * W + (p[:, 0] - 1)


def _dilated(pixels: list[list[int]], shape: tuple[int, int], reach: int) -> np.ndarray:
    """The flat indexes within reach px (a square) of the 1-based [x, y]
    pixels, clipped to the image."""
    H, W = shape
    p = np.asarray(pixels).reshape(-1, 2) - 1
    d = np.arange(-reach, reach + 1)
    rr = (p[:, 1, None, None] + d[:, None]).clip(0, H - 1)
    cc = (p[:, 0, None, None] + d[None, :]).clip(0, W - 1)
    return np.unique(rr * W + cc)


def _incidence(sets: list[np.ndarray], n_pix: int) -> sparse.csr_matrix:
    rows = np.repeat(np.arange(len(sets)), [len(s) for s in sets])
    cols = np.concatenate(sets) if sets else np.zeros(0, np.int64)
    return sparse.csr_matrix((np.ones(len(cols), np.float32), (rows, cols)), shape=(len(sets), n_pix))


def on_fractions(pixels: list[list[list[int]]], others: list[list[list[int]]], shape: tuple[int, int],
                 reach: int) -> sparse.csr_matrix:
    """[i, j]: the fraction of pixels[i] within reach px of others[j], where
    it is above zero. Sparse, so nothing image-sized is kept per trace."""
    n_pix = shape[0] * shape[1]
    A = _incidence([np.unique(_flat(p, shape[1])) for p in pixels], n_pix)
    B = _incidence([_dilated(p, shape, reach) for p in others], n_pix)
    counts = (A @ B.T).tocoo()
    sizes = np.maximum(np.asarray(A.sum(axis=1)).ravel(), 1)
    return sparse.csr_matrix((counts.data / sizes[counts.row], (counts.row, counts.col)), shape=counts.shape)


def suppress(pair: sparse.csr_matrix, score: np.ndarray, keep: float) -> list[int]:
    """Step 4 on overlaps pair[i, j] (on_fractions of the candidates with
    themselves, at REACH): the indexes picked, best score first. One with
    OVERLAP of its pixels on a picked one, or the picked one's on it, is
    left out."""
    order = [int(i) for i in np.argsort(-score, kind="stable") if score[i] >= keep]
    taken = np.zeros(len(score), bool)
    PT = pair.T.tocsr()
    out = []
    for i in order:
        if taken[i]:
            continue
        out.append(i)
        # j's pixels on i: pair[j, i]; i's pixels on j: pair[i, j].
        taken[PT[i].indices[PT[i].data > OVERLAP]] = True
        taken[pair[i].indices[pair[i].data > OVERLAP]] = True
        taken[i] = True
    return out


def pick(cands: list[dict[str, Any]], score: np.ndarray, shape: tuple[int, int],
         keep: float = KEEP_SCORE) -> list[int]:
    """suppress() on the candidates' traces."""
    pix = [c["pixels"] for c in cands]
    pair = on_fractions(pix, pix, shape, REACH) if cands else sparse.csr_matrix((0, 0))
    return suppress(pair, score, keep)


def detect(prep: aa.PreparedImage, raw: np.ndarray | None, threshold: float = 0.01,
           settings: aa.Settings = aa.DEFAULT, exclude: list[list[list[int]]] | None = None,
           soma: Somata | None = None) -> dict[str, Any]:
    """detect.detect's JSON for start "learned": {candidates, components,
    merged, known, failed, somata?}, each candidate with "filter" {score,
    length_um}."""
    m = models()
    meta = m["meta"]
    plain = "" if soma is not None else "_plain"
    cands, counts = candidates(prep, raw, threshold, settings, soma,
                               (m["component" + plain], meta.get("component_keep", COMPONENT_KEEP)))
    out: dict[str, Any] = {"candidates": [], "components": counts["components"], "merged": 0, "known": 0,
                           "failed": counts["failed"]}
    if soma is not None:
        out["somata"] = soma.outlines
    if not cands:
        return out
    score = m["ais" + plain].predict(feature_matrix(cands, m["ais" + plain].features))
    shape = prep.pic.shape
    keep = meta.get("keep", KEEP_SCORE)
    # Candidates lying on an AIS already accepted are set aside first, so
    # none of them can crowd out a new AIS beside it; "known" counts the
    # AIS they would have shown.
    known = np.zeros(len(cands), bool)
    accepted = [p for trace in exclude or [] for p in trace]
    if accepted:
        on = on_fractions([c["pixels"] for c in cands], [accepted], shape, EXCLUDE_REACH)
        known = on.toarray().ravel() > OVERLAP
        out["known"] = len(pick(cands, np.where(known, score, -1.0), shape, keep))
    for i in pick(cands, np.where(known, -1.0, score), shape, keep):
        c = {k: v for k, v in cands[i].items() if k not in ("features", "blob")}
        c["filter"] = {"score": round(float(score[i]), 4), "length_um": c["measures"]["length_um"]}
        if soma is not None:
            gap = soma.gap_at(*c["pixels"][0])
            c["soma_gap_um"] = round(gap, 2) if np.isfinite(gap) else None
        out["candidates"].append(c)
    return out
