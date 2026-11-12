"""How much AIS there is: its area on an image, and its volume in a Z-stack.

Two ways each, side by side, so they can be compared on real AIS:

Area (µm², the measured AIS: profile points ais_start..ais_end)
- area_blob_um2: the traced blob's pixels whose nearest trace point is in
  the measured section, times the pixel's area. Follows the outline as
  thresholded, taper and bulges included; a short branch off the AIS that
  is nearer the section than anything else counts too.
- area_width_um2: the width at each section point (twice the distance to the
  blob's edge, as width_um's median) times the length that point stands for
  along the trace, summed. Follows taper; smoother than counting pixels.

Volume (µm³, Z-stacks only: zlength.lift's route through the slices)
- volume_voxel_um3: in each slice, the pixels near the section (within its
  widest half-width and a pixel) at least halfway from the slice's
  background to the AIS's peak at the nearest section point, times pixel
  area times z step. What the slices show; out-of-focus light in the slices
  above and below an AIS can count, so it reads high where z is blurred.
- volume_tube_um3: the AIS as a tube of round cross-section, pi (w/2)^2 at
  each section point times the 3D length that point stands for. Not touched
  by z blur, but it assumes the cross-section is round.

Nothing here has been checked against AIS measured by hand.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage as ndi

RING_PX = 3           # volume_voxel: the background ring beyond the footprint, px
HALF = 0.5            # volume_voxel: a voxel counts from halfway between background and peak


def _section(n: int, ais_start: float, ais_end: float) -> tuple[int, int]:
    """First and last index of the measured AIS into n trace points, clamped
    as service.shape does (the whole trace when the section is a point)."""
    a, b = max(int(ais_start), 1), min(int(ais_end), n)
    return (a - 1, b - 1) if b - a >= 1 else (0, n - 1)


def _weights(points: np.ndarray) -> np.ndarray:
    """The length each point stands for along a path: half of each segment
    on either side of it (an end point gets half its one segment)."""
    if len(points) < 2:
        return np.zeros(len(points))
    seg = np.sqrt(((points[1:] - points[:-1]) ** 2).sum(axis=1))
    out = np.zeros(len(points))
    out[:-1] += seg / 2
    out[1:] += seg / 2
    return out


def areas(sel: np.ndarray, top: int, left: int, pixels: list[list[int]], ais_start: float, ais_end: float,
          pixconv: float) -> dict[str, Any]:
    """{area_blob_um2, area_width_um2, widths_um}: the measured AIS's area two
    ways, and its width at each section point (for volume_tube). sel: the
    traced blob, its box starting at 0-based (top, left) of the image;
    pixels: the trace, 1-based [x, y]."""
    n = len(pixels)
    first, last = _section(n, ais_start, ais_end)
    rows, cols = np.flatnonzero(sel.any(axis=1)), np.flatnonzero(sel.any(axis=0))
    if not rows.size:
        return {"area_blob_um2": None, "area_width_um2": None, "widths_um": []}
    r0, c0 = rows[0], cols[0]
    crop = np.pad(sel[r0:rows[-1] + 1, c0:cols[-1] + 1], 1)
    P = np.asarray(pixels, np.intp).reshape(-1, 2)
    rr = np.clip(P[:, 1] - 1 - (r0 + top) + 1, 0, crop.shape[0] - 1)
    cc = np.clip(P[:, 0] - 1 - (c0 + left) + 1, 0, crop.shape[1] - 1)
    # Widths as service.shape: the 3x3 around each point, as the spline can run beside the blob.
    near = ndi.maximum_filter(ndi.distance_transform_edt(crop), size=3)
    widths = 2 * near[rr[first:last + 1], cc[first:last + 1]] * pixconv
    step = _weights(P[first:last + 1].astype(np.float64)) * pixconv
    # Each blob pixel goes to its nearest trace point.
    label = np.zeros(crop.shape, np.int32)
    label[rr, cc] = np.arange(1, n + 1)
    _, (ir, ic) = ndi.distance_transform_edt(label == 0, return_indices=True)
    owner = label[ir, ic] - 1
    blob = int(np.count_nonzero(crop & (owner >= first) & (owner <= last)))
    return {"area_blob_um2": round(blob * pixconv * pixconv, 4),
            "area_width_um2": round(float((widths * step).sum()), 4),
            "widths_um": [round(float(w), 4) for w in widths]}


def volumes(stack: np.ndarray, levels: np.ndarray, answer: dict[str, Any], z_path: list[float | None],
            pixel_um: float, z_step_um: float) -> dict[str, float] | None:
    """{volume_voxel_um3, volume_tube_um3} of a lifted trace (see the module
    docstring). stack: (slices, height, width) of the AIS plane; levels: each
    slice's bright level (zlength.slice_levels); answer: run_click's, with
    shape.widths_um; z_path: zlength.lift's z per trace point (slice
    numbers, None outside the section). None when it can't be said."""
    pixels = np.asarray(answer["pixels"], np.intp).reshape(-1, 2)
    idx = [i for i, z in enumerate(z_path) if z is not None]
    widths = np.asarray((answer.get("shape") or {}).get("widths_um") or [], np.float64)
    if len(idx) < 2 or len(widths) != len(idx):
        return None
    sec = pixels[idx]
    zs = np.asarray([z_path[i] for i in idx], np.float64)
    # Tube: pi r^2 along the 3D path.
    path3 = np.column_stack([sec[:, 0] * pixel_um, sec[:, 1] * pixel_um, zs * z_step_um])
    tube = float((math.pi * (widths / 2) ** 2 * _weights(path3)).sum())
    # Voxels: a footprint around the section, each pixel owned by its nearest section point.
    S, H, W = stack.shape
    reach = int(math.ceil(float(widths.max()) / 2 / pixel_um)) + 1
    x0, x1 = max(int(sec[:, 0].min()) - 1 - reach - RING_PX, 0), min(int(sec[:, 0].max()) + reach + RING_PX, W)
    y0, y1 = max(int(sec[:, 1].min()) - 1 - reach - RING_PX, 0), min(int(sec[:, 1].max()) + reach + RING_PX, H)
    label = np.zeros((y1 - y0, x1 - x0), np.int32)
    label[sec[:, 1] - 1 - y0, sec[:, 0] - 1 - x0] = np.arange(1, len(sec) + 1)
    dist, (ir, ic) = ndi.distance_transform_edt(label == 0, return_indices=True)
    owner = label[ir, ic] - 1
    foot = dist <= reach
    ring = (dist > reach) & (dist <= reach + RING_PX)
    if not ring.any():
        return None
    box = stack[:, y0:y1, x0:x1].astype(np.float64) / levels[:, None, None]
    background = np.median(box[:, ring], axis=1)                       # per slice
    on_path = box[:, sec[:, 1] - 1 - y0, sec[:, 0] - 1 - x0]           # (slices, points)
    peak = on_path.max(axis=0)
    floor = background.mean()
    cut = background[:, None] + HALF * np.maximum(peak - floor, 0)[None, :]   # (slices, points)
    fy, fx = np.nonzero(foot)
    owners = owner[fy, fx]
    lit = box[:, fy, fx] >= cut[:, owners]
    lit &= (peak[owners] > floor)[None, :]
    voxel = float(np.count_nonzero(lit)) * pixel_um * pixel_um * z_step_um
    if not (math.isfinite(voxel) and math.isfinite(tube)):
        return None
    return {"volume_voxel_um3": round(voxel, 4), "volume_tube_um3": round(tube, 4)}
