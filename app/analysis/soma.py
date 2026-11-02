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
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

STEP_UM = 0.3          # working pixel size
SMOOTH_PX = 2.0
OPEN_UM = 1.9          # radius: dendrites are narrower than twice this
BACKGROUND_UM = 13.0
K = 1.25
BRIDGE_UM = 1.0        # radius of the opening that cuts thin bridges
MIN_AREA_UM2 = 40.0


@dataclass
class Somata:
    mask: np.ndarray                 # bool, full size: inside a soma
    gap_um: np.ndarray               # float32, full size: microns to the nearest soma (0 inside)
    outlines: list[list[list[int]]]  # per soma, its edge pixels as 1-based [x, y]

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
    return Somata(mask, gap, outlines)
