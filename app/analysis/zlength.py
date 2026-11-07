"""AIS length across a Z-stack (docs/z-stack.md).

Which method measures it is a Settings choice, METHODS below. Only "Trace, then
lift to Z" is built; the other two are templates, listed but not selectable
until their function is written and `ready` flipped.

Trace, then lift (`lift`): tracing stays 2D. The tracer runs unchanged on the
stack's max projection, and its AIS section is then followed through the
slices:

    sample   a 3x3 mean on every slice, along the trace only
    level    each slice over its own bright level, as end slices are dim
    path     Viterbi over z: the brightest route that does not jump slices
             without reason, so a fibre crossing at another depth can't take over
    refine   a centroid of the slices around the route, below one slice
    smooth   a spline, far stiffer than XY's (Z_SMOOTHING)
    measure  arc length along the tracer's spline, with z added

Compare length_3d_um with length_xy_um, measured the same way along the same
section. length_um is not comparable: it counts the rounded pixels a trace
crosses, which reads above true length on a diagonal.

Nothing here has been checked against a real AIS measured by hand in 3D: there
is no such ground truth yet. tests/test_zlength.py checks known synthetic paths.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from app.analysis import mlcompat as ml

# What one slice of jump costs, against a slice's brightness scaled 0 to 1.
JUMP_PENALTY = 0.05
# csaps p along the section, points 1..n. XY's 0.3 follows the slice-to-slice
# staircase and adds length that isn't there: +0.10 to +0.22 µm on a synthetic
# ramp, against +0.01 µm at this value.
Z_SMOOTHING = 3e-4
MIN_POINTS = 5
# A near-empty slice is levelled as if this share of the typical slice's level,
# so noise is not scaled up into something to follow.
LEVEL_FLOOR = 0.25
LEVEL_PERCENTILE = 99.9


def slice_levels(stack: np.ndarray) -> np.ndarray:
    """Each slice's bright level, from every 4th pixel: this is a scale, not a
    measure, and all of them would cost a float copy of the slice."""
    levels = np.array([np.percentile(plane[::4, ::4], LEVEL_PERCENTILE) for plane in stack], np.float64)
    return np.maximum(levels, max(LEVEL_FLOOR * float(np.median(levels)), 1.0))


def _section(answer: dict[str, Any]) -> tuple[int, int]:
    """The AIS as first and last index into pixels. ais_start is 0 when the
    trace starts inside it, and ais_end can run past the end (ais_auto.measure
    falls back to a coordinate), so both are clamped as service.shape does."""
    n = len(answer["pixels"])
    return max(int(answer["profile"]["ais_start"]), 1) - 1, min(int(answer["profile"]["ais_end"]), n) - 1


def _sample(stack: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """The 3x3 mean around each pixel on every slice, (slices, points). Only
    these points: a whole-stack filter is 127 MB a click at this image size."""
    _, height, width = stack.shape
    x, y = pixels[:, 0] - 1, pixels[:, 1] - 1       # MATLAB axes, 1-based
    out = np.zeros((stack.shape[0], len(pixels)))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out += stack[:, np.clip(y + dy, 0, height - 1), np.clip(x + dx, 0, width - 1)]
    return out / 9


def _route(brightness: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """The index of the slice at each point, the route with the most brightness
    less JUMP_PENALTY per slice moved (Viterbi)."""
    jump = JUMP_PENALTY * np.abs(zs[:, None] - zs[None, :])
    score = brightness[:, 0].copy()
    came_from = np.zeros(brightness.shape, np.intp)
    for i in range(1, brightness.shape[1]):
        options = score[None, :] - jump
        came_from[:, i] = options.argmax(axis=1)
        score = options.max(axis=1) + brightness[:, i]
    route = np.zeros(brightness.shape[1], np.intp)
    route[-1] = score.argmax()
    for i in range(brightness.shape[1] - 1, 0, -1):
        route[i - 1] = came_from[route[i], i]
    return route


def _centroid(brightness: np.ndarray, route: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """The z at each point below slice resolution: the middle of the brightness
    on the route's slice and the ones either side."""
    out = zs[route].astype(np.float64)
    floor = brightness.min(axis=0)
    for i, k in enumerate(route):
        near = slice(max(k - 1, 0), k + 2)
        weight = brightness[near, i] - floor[i]
        if weight.sum() > 0:
            out[i] = (weight * zs[near]).sum() / weight.sum()
    return out


def _on_spline(pixels: np.ndarray, spline: np.ndarray) -> np.ndarray:
    """Where the tracer's spline runs at each pixel, in order along it. The
    pixels are the spline rounded, so they step; the spline doesn't."""
    nearest = ((pixels[:, None, :] - spline[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
    return spline[np.maximum.accumulate(nearest)]


def _arc(*steps: np.ndarray) -> float:
    return float(np.sqrt(sum(np.diff(s) ** 2 for s in steps)).sum())


def lift(stack: np.ndarray, levels: np.ndarray, zs: Any, answer: dict[str, Any],
         pixel_um: float, z_step_um: float) -> dict[str, Any] | None:
    """A trace's AIS through the slices of stack (slices, height, width), zs
    being each slice's own number so a missing slice keeps its spacing. answer
    is run_click's. None when the section is too short to say."""
    first, last = _section(answer)
    if last - first + 1 < MIN_POINTS:
        return None
    pixels = np.asarray(answer["pixels"], np.intp)[first:last + 1]
    zs = np.asarray(zs, np.float64)
    brightness = _sample(stack, pixels) / levels[:, None]
    brightness /= max(float(brightness.max()), 1e-9)
    route = _route(brightness, zs)
    t = np.arange(1.0, len(pixels) + 1)
    z = ml.csaps(t, _centroid(brightness, route, zs)[None, :], Z_SMOOTHING, t)[0]
    xy = _on_spline(pixels, np.asarray(answer["spline"], np.float64)) * pixel_um
    peak = brightness[route, np.arange(len(pixels))]
    contrast = float(np.median((peak - np.median(brightness, axis=0)) / np.maximum(peak, 1e-9)))
    numbers = {"length_3d_um": _arc(xy[:, 0], xy[:, 1], z * z_step_um), "length_xy_um": _arc(xy[:, 0], xy[:, 1]),
               "z_start": float(z[0]), "z_end": float(z[-1]), "z_span_um": float(z.max() - z.min()) * z_step_um,
               "z_confidence": min(max(contrast, 0.0), 1.0)}
    if not all(math.isfinite(v) for v in numbers.values()):
        return None
    path: list[float | None] = [None] * len(answer["pixels"])
    path[first:last + 1] = [round(float(v), 2) for v in z]
    ends = {0, len(zs) - 1}
    return ({k: round(v, 3) for k, v in numbers.items()}
            | {"z_step_um": z_step_um, "z_clipped": int(int(route[0]) in ends or int(route[-1]) in ends), "z_path": path})


def end_clicks(stack: np.ndarray, levels: np.ndarray, zs: Any, answer: dict[str, Any],
               pixel_um: float, z_step_um: float) -> dict[str, Any] | None:
    """TODO: "Click ends per slice". See docs/z-stack.md."""
    raise NotImplementedError("Click ends per slice is not built yet")


def volume_trace(stack: np.ndarray, levels: np.ndarray, zs: Any, answer: dict[str, Any],
                 pixel_um: float, z_step_um: float) -> dict[str, Any] | None:
    """TODO: "Full 3D tracing". See docs/z-stack.md."""
    raise NotImplementedError("Full 3D tracing is not built yet")


@dataclass(frozen=True)
class Method:
    id: str
    label: str
    ready: bool     # False: listed in Settings, not selectable
    run: Callable[..., dict[str, Any] | None]


# Settings' Z method list (static/js/settings.js) follows this.
METHODS = (
    Method("trace_lift", "Trace, then lift to Z", True, lift),
    Method("end_clicks", "Click ends per slice", False, end_clicks),
    Method("volume_trace", "Full 3D tracing", False, volume_trace),
)
DEFAULT_METHOD = METHODS[0].id


def method(value: Any = None) -> Method:
    """The method asked for; left out, the default. ValueError for one that
    doesn't exist or isn't built."""
    wanted = DEFAULT_METHOD if value is None else value
    found = next((m for m in METHODS if m.id == wanted), None)
    if found is None:
        raise ValueError("unknown z method")
    if not found.ready:
        raise ValueError(f"{found.label} is not built yet")
    return found
