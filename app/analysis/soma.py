"""Cell bodies from a CZI's AMCA channel, for CZI mode's auto detection.

AMCA here is a somatodendritic (MAP2-like) stain: bright blurry somata
10-20 um across inside a dense mesh of 1-2 um dendrites. An AIS is MAP2
negative and leaves its soma at the edge, so the soma nearest a trace's end
says which end the AIS starts from (detect.py, start "soma").

1. Smooth (sigma 2 px) and work at about 0.3 um per pixel, which keeps a
   soma and makes the next step fast.
2. A grey opening with a disk of radius OPEN_UM erases what is narrower than
   it: the dendrites go, the somata stay.
3. Subtract the broad background (a Gaussian of BACKGROUND_UM), so dim and
   bright corners are judged alike.
4. Keep what is above the mean + K standard deviations, open away thin
   bridges, fill holes, and drop pieces under MIN_AREA_UM2.

Tuned on example-data/001-003-czi. Thresholds are deliberately loose: a
missed soma costs more (a real AIS filtered out) than an extra one.

Bodies (the Measure tool's somata, app/analysis/pairing.py) are what the
outlines hold, at the same working size: each outline's hotspot, the
brightest point of the soma channel smoothed to soma scale (HOTSPOT_UM). An
outline is often touching cells run together, so "split" bodies take every
local hotspot at least HOTSPOT_SEP_UM from a brighter one and share the
outline out among them (each pixel climbing the smoothed image to its peak); a piece under
MIN_PIECE_UM2, or longer than MAX_ASPECT times its width (a thick
dendrite's trunk), gives its hotspot up. "Whole" bodies are one per outline.

Any channel may show somata, not only a soma stain (best): the soma stain
is tried first, and when it shows too little the others are, too. each channel's
outlines are judged (quality) by how many look like a cell body -- MIN_AREA_UM2
to MAX_AREA_UM2, at least MIN_WIDTH_UM wide (an AIS's thick end is not), no
longer than MAX_ASPECT times their width, and brighter than
a RING_UM ring around them by MIN_CONTRAST of the channel's range and by
MIN_SNR times its pixel noise -- and the
channel with the most convincing ones is used. A channel where most outlines
are not cell-body-like (noise, texture, AIS segments) shows none.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage as ndi

STEP_UM = 0.3          # working pixel size
SMOOTH_PX = 2.0
OPEN_UM = 1.9          # radius: dendrites are narrower than twice this
BACKGROUND_UM = 13.0
K = 1.25
BRIDGE_UM = 1.0        # radius of the opening that cuts thin bridges
MIN_AREA_UM2 = 40.0
HOTSPOT_UM = 2.5       # smoothing for hotspots: a MAP2 ring or a nucleolus blurs to one centre
HOTSPOT_SEP_UM = 8.0   # split: hotspots nearer than this are one cell (a soma is 10-20 um across)
MIN_PIECE_UM2 = 40.0   # split: a smaller piece is not a cell of its own (as MIN_AREA_UM2)
MAX_ASPECT = 3.0       # split: a piece longer than this times its width is a dendrite trunk (somata here: 1.5-2)
MAX_AREA_UM2 = 1200.0  # quality: larger is not one cell body, nor a few run together
MIN_WIDTH_UM = 6.0     # quality: narrower is not a cell body (an AIS is 1-2 um wide)
RING_UM = 3.0          # quality: the ring around an outline its contrast is judged against
MIN_CONTRAST = 0.08    # quality: inside minus ring, as a fraction of the channel's 1-99.9 percentile range
MIN_SNR = 1.0          # quality: ... and at least this times the pixel noise (real somata: 2-10; plain noise: 0.1)


@dataclass
class Bodies:
    labels: np.ndarray          # int32 at the working size: 0 outside, k + 1 in body k
    hotspots: list[list[float]] # per body, its hotspot as a full-size 1-based [x, y]
    step: int                   # full-size pixels per working pixel
    depths: list[float] | None = None   # Z-stacks: each body's depth in slice numbers (depths)


@dataclass
class Somata:
    mask: np.ndarray                 # bool, full size: inside a soma
    gap_um: np.ndarray               # float32, full size: microns to the nearest soma (0 inside)
    outlines: list[list[list[int]]]  # per soma, its edge pixels as 1-based [x, y]
    split: Bodies | None = None      # the bodies: one per hotspot ...
    whole: Bodies | None = None      # ... or one per outline (None: made by hand, no bodies)

    def bodies(self, split: bool) -> Bodies | None:
        return self.split if split else self.whole

    def gap_at(self, x: int, y: int) -> float:
        """gap_um at a 1-based [x, y] pixel."""
        return float(self.gap_um[y - 1, x - 1])


def _disk(radius: float) -> np.ndarray:
    r = max(1, int(round(radius)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return xx * xx + yy * yy <= r * r


def find(amca: np.ndarray, pixel_um: float) -> Somata:
    """The somata in an AMCA image with pixel_um microns per pixel."""
    step = max(1, int(round(STEP_UM / pixel_um)))
    um = pixel_um * step
    small = ndi.gaussian_filter(amca.astype(np.float64), SMOOTH_PX)[::step, ::step]
    opened = ndi.grey_opening(small, footprint=_disk(OPEN_UM / um))
    signal = opened - ndi.gaussian_filter(opened, BACKGROUND_UM / um)
    on = signal > signal.mean() + K * signal.std()
    on = ndi.binary_fill_holes(ndi.binary_opening(on, structure=_disk(BRIDGE_UM / um)))
    labels, n = ndi.label(on)
    if n:
        area = ndi.sum(on, labels, range(1, n + 1)) * um * um
        on = np.isin(labels, 1 + np.flatnonzero(area >= MIN_AREA_UM2))
    H, W = amca.shape
    mask = np.repeat(np.repeat(on, step, axis=0), step, axis=1)[:H, :W]
    if mask.shape != (H, W):   # step does not divide the size: pad the last row / column
        mask = np.pad(mask, ((0, H - mask.shape[0]), (0, W - mask.shape[1])), mode="edge")
    if mask.any():
        gap = (ndi.distance_transform_edt(~mask) * pixel_um).astype(np.float32)
    else:
        gap = np.full((H, W), np.inf, np.float32)
    edge = mask & ~ndi.binary_erosion(mask, border_value=0)
    labels, n = ndi.label(mask)
    outlines = []
    for k, box in enumerate(ndi.find_objects(labels), 1):
        rows, cols = np.nonzero(edge[box] & (labels[box] == k))
        outlines.append([[int(c) + box[1].start + 1, int(r) + box[0].start + 1] for r, c in zip(rows, cols)])
    hot = ndi.gaussian_filter(small, HOTSPOT_UM / um)
    return Somata(mask, gap, outlines, _bodies(on, hot, step, um, True), _bodies(on, hot, step, um, False))


def _bodies(on: np.ndarray, hot: np.ndarray, step: int, um: float, split: bool) -> Bodies:
    """The bodies in the working-size mask on, from hot (the smoothed soma
    channel at that size)."""
    regions, n = ndi.label(on)
    out = np.zeros(on.shape, np.int32)
    seeds: list[tuple[int, int]] = []
    if split and n:
        r = max(1, int(round(HOTSPOT_SEP_UM / um)))
        peaks = (hot == ndi.maximum_filter(hot, size=2 * r + 1)) & on   # a square: separable, so fast
    for k, box in enumerate(ndi.find_objects(regions), 1):
        region = regions[box] == k
        local = np.where(region, hot[box], -np.inf)
        top = np.unravel_index(int(np.argmax(local)), local.shape)
        found = [top]
        if split:
            # One seed per plateau, brightest first; the region's top always.
            plateaus, m = ndi.label(peaks[box] & region)
            for p in ndi.center_of_mass(plateaus, plateaus, range(1, m + 1)) if m else []:
                q = (int(round(p[0])), int(round(p[1])))
                if region[q] and all(abs(q[0] - f[0]) + abs(q[1] - f[1]) > 1 for f in found):
                    found.append(q)
            found.sort(key=lambda q: -local[q])
            found = _keep_pieces(region, local, found, MIN_PIECE_UM2 / (um * um))
        pieces = _share(region, local, found)
        for i, q in enumerate(found):
            seeds.append((q[0] + box[0].start, q[1] + box[1].start))
            out[box][pieces == i + 1] = len(seeds)
    hotspots = [[float(c * step + 1), float(r * step + 1)] for r, c in seeds]
    return Bodies(out, hotspots, step)


def _share(region: np.ndarray, local: np.ndarray, seeds: list[tuple[int, int]]) -> np.ndarray:
    """region shared out among seeds (labels 1..): each pixel climbs local
    to its brightest neighbour until it can climb no more, and goes to the
    seed nearest that top. (A watershed hands a shallow saddle's far side to
    whichever seed floods first; touching somata are mostly shallow
    saddles.)"""
    if len(seeds) == 1:
        return region.astype(np.int32)
    H, W = region.shape
    padded = np.pad(local, 1, constant_values=-np.inf)
    rows, cols = np.mgrid[0:H, 0:W]
    up = rows * W + cols
    top = local.copy()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                there = padded[1 + dr:1 + dr + H, 1 + dc:1 + dc + W]
                better = there > top
                up = np.where(better, np.clip(rows + dr, 0, H - 1) * W + np.clip(cols + dc, 0, W - 1), up)
                top = np.where(better, there, top)
    up = up.ravel()
    for _ in range(int(math.ceil(math.log2(H * W))) + 1):
        up = up[up]
    inside = region.ravel()
    tops = np.unique(up[inside])
    ty, tx = np.divmod(tops, W)
    S = np.asarray(seeds)
    owner = np.argmin((ty[:, None] - S[:, 0]) ** 2 + (tx[:, None] - S[:, 1]) ** 2, axis=1) + 1
    out = np.zeros(H * W, np.int32)
    out[inside] = owner[np.searchsorted(tops, up[inside])]
    return out.reshape(H, W)


def _keep_pieces(region: np.ndarray, local: np.ndarray, seeds: list[tuple[int, int]],
                 min_px: float) -> list[tuple[int, int]]:
    """seeds without those whose piece is too long for a soma (MAX_ASPECT,
    judged once, on the first share: a trunk given up makes its neighbour
    longer, not less a soma), then without those whose piece is under
    min_px, dimmest first, one at a time (a dropped seed's piece goes to its
    neighbours). The brightest always stays."""
    if len(seeds) > 1:
        pieces = _share(region, local, seeds)
        seeds = [q for i, q in enumerate(seeds) if i == 0 or not _long(pieces == i + 1)]
    while len(seeds) > 1:
        pieces = _share(region, local, seeds)
        small = [i for i in range(1, len(seeds)) if np.count_nonzero(pieces == i + 1) < min_px]
        if not small:
            break
        seeds = [q for i, q in enumerate(seeds) if i != small[-1]]
    return seeds


def depths(volume: np.ndarray, bodies: Bodies, zs: list[float]) -> list[float]:
    """Each body's depth in a Z-stack: volume (slices, height, width) of the
    plane the somata were found in; zs each slice's number. The centre of the
    body's brightness through the slices, above its dimmest slice, squared so
    the in-focus slices lead."""
    small = volume[:, ::bodies.step, ::bodies.step].astype(np.float64)
    h, w = min(small.shape[1], bodies.labels.shape[0]), min(small.shape[2], bodies.labels.shape[1])
    labels = bodies.labels[:h, :w]
    z = np.asarray(zs, np.float64)
    out = []
    for k in range(1, len(bodies.hotspots) + 1):
        inside = labels == k
        if not inside.any():
            out.append(float(np.median(z)))
            continue
        means = small[:, :h, :w][:, inside].mean(axis=1)
        weight = (means - means.min()) ** 2
        out.append(float((z * weight).sum() / weight.sum()) if weight.sum() > 0 else float(z[int(np.argmax(means))]))
    return [round(v, 3) for v in out]


def _width(piece: np.ndarray) -> float:
    """A piece's width in pixels: that of the ellipse with its spread."""
    rows, cols = np.nonzero(piece)
    if len(rows) < 3:
        return 0.0
    D = np.stack([rows - rows.mean(), cols - cols.mean()], axis=1)
    return 4.0 * math.sqrt(max(float(np.linalg.eigvalsh(D.T @ D / len(D))[0]), 0.0))


def _long(piece: np.ndarray) -> bool:
    """Longer than MAX_ASPECT times its width: a dendrite's trunk."""
    rows, cols = np.nonzero(piece)
    if len(rows) < 3:
        return False
    D = np.stack([rows - rows.mean(), cols - cols.mean()], axis=1)
    small, large = np.linalg.eigvalsh(D.T @ D / len(D))
    return bool(large > MAX_ASPECT ** 2 * max(small, 1e-9))


def quality(found: Somata, plane: np.ndarray, pixel_um: float) -> float:
    """How surely found (find(plane, pixel_um)) shows cell bodies: the number
    of soma-like outlines times their median contrast; 0 when there are none,
    or when they are fewer than the outlines that are not."""
    if found.whole is None or not found.outlines:
        return 0.0
    step = found.whole.step
    um = pixel_um * step
    small = ndi.gaussian_filter(plane.astype(np.float64), SMOOTH_PX)[::step, ::step]
    labels = found.whole.labels
    lo, hi = np.percentile(small, (1, 99.9))
    span = max(float(hi - lo), 1e-9)
    detail = plane.astype(np.float64) - ndi.gaussian_filter(plane.astype(np.float64), 1.0)
    noise = max(1.4826 * float(np.median(np.abs(detail - np.median(detail)))), 1e-9)   # the pixel noise (robust sd)
    ring = _disk(RING_UM / um)
    r = ring.shape[0] // 2 + 1
    good: list[float] = []
    count = 0
    for k, box in enumerate(ndi.find_objects(labels), 1):
        if box is None:
            continue
        count += 1
        big = tuple(slice(max(0, b.start - r), b.stop + r) for b in box)
        region = labels[big] == k
        area = np.count_nonzero(region) * um * um
        if not MIN_AREA_UM2 <= area <= MAX_AREA_UM2 or _long(region) or _width(region) * um < MIN_WIDTH_UM:
            continue
        around = ndi.binary_dilation(region, structure=ring) & (labels[big] == 0)
        if not around.any():
            continue
        step_up = float(np.median(small[big][region]) - np.median(small[big][around]))
        contrast = step_up / span
        if contrast >= MIN_CONTRAST and step_up >= MIN_SNR * noise:
            good.append(float(contrast))
    if not good or 2 * len(good) < count:
        return 0.0
    return len(good) * float(np.median(good))


def best(planes: list[np.ndarray], pixel_um: float, ais: int | None = None,
         first: int | None = None) -> tuple[int, Somata] | None:
    """The channel of planes that shows somata most surely, with its somata:
    first (the soma channel chosen or named) when it shows them well enough
    (quality > 0), else the best other one; the AIS channel (ais) only when
    no other shows any; first's own, however few, when none does. None when
    there is no first and no channel shows any."""
    chosen = None
    if first is not None and 0 <= first < len(planes):
        chosen = first, find(planes[first], pixel_um)
        if quality(chosen[1], planes[first], pixel_um) > 0:
            return chosen
    scored: list[tuple[float, int, Somata]] = []
    for i, plane in enumerate(planes):
        if i in (ais, first):
            continue
        found = find(plane, pixel_um)
        score = quality(found, plane, pixel_um)
        if score > 0:
            scored.append((score, -i, found))
    if scored:
        _, i, found = max(scored, key=lambda t: (t[0], t[1]))
        return -i, found
    if ais is not None and ais != first and 0 <= ais < len(planes):
        found = find(planes[ais], pixel_um)
        if quality(found, planes[ais], pixel_um) > 0:
            return ais, found
    return chosen
