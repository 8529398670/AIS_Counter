"""AIS length across a Z-stack (docs/z-stack.md).

Which method measures it is a Settings choice, METHODS below. "Trace, then
lift to Z" and "Trace, lift to Z, ends from the slices" are built; the other
two are templates, listed but not selectable until their function is written
and `ready` flipped.

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

Ends from the slices (`lift_ends`): a route through the slices along the
whole trace, which may climb no steeper than MAX_SLOPE (_steady_route), then
the AIS start and end found again from the intensity along it (levelled per
slice, at each point's z) instead of the projection's, with the original's
own rules (_bounds). Light from another depth past an end is then off the
route and no longer moves the end. The section between the new ends is measured as
lift measures its. It adds z_ais_start and z_ais_end, the new ends as profile
points like ais_start and ais_end, and z_profile, for drawing.

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

from app.analysis import ais_auto as aa
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
# How steeply lift_ends' route may climb: z over xy distance. 1 is 45°.
MAX_SLOPE = 1.0


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


def _bounds(lv_smooth: np.ndarray, d: int, f: float) -> tuple[np.ndarray, int, float, float] | None:
    """(norm_lv, max_i, ais_start, ais_end) of a profile by ais_auto.measure's
    rules (lines 401-442): a sliding mean of half-width d, scaled 0 to 1; the
    AIS ends at the last point above f after the peak and starts after the
    last point below f before it, as 1-based profile points (ais_start 0 when
    there is none; ais_end the last point, where the original falls back to a
    coordinate). A copy, so ais_auto stays the MATLAB port it is. None when
    the profile is too short or flat."""
    n = lv_smooth.size
    if n < 2 * d:
        return None
    lv_ss = np.zeros(n)
    for i in range(1, n + 1):
        if i < d + 1:
            win = np.concatenate([lv_smooth[0:i], lv_smooth[i - 1:i + d]])
        elif i > n - (d + 1):
            win = np.concatenate([lv_smooth[i - d - 1:i], lv_smooth[i - 1:n]])
        else:
            win = np.concatenate([lv_smooth[i - d - 1:i], lv_smooth[i - 1:i + d]])
        lv_ss[i - 1] = aa._matlab_mean(win)
    lo, hi = lv_ss.min(), lv_ss.max()
    if not hi > lo:
        return None
    norm_lv = (lv_ss - lo) / (hi - lo)
    max_i = int(np.flatnonzero(norm_lv == norm_lv.max())[0]) + 1
    idx = np.arange(1, n + 1)
    after = np.flatnonzero((idx > max_i) & (norm_lv > f))
    before = np.flatnonzero((idx < max_i) & (norm_lv < f))
    return norm_lv, max_i, float(after[-1] + 1) if after.size else float(n), float(before[-1] + 1) if before.size else 0.0


def _steady_route(brightness: np.ndarray, zs: np.ndarray, points_per_slice: float) -> np.ndarray:
    """_route for lift_ends, over the whole trace: the trace is cut into runs
    of points_per_slice points, and the route moves at most one slice from
    run to run, so it climbs no steeper than MAX_SLOPE. lift's route may
    jump anywhere at a small cost, which is right within an AIS but lets a
    patch alone in its slice (levelled as bright as the AIS) draw it off past
    the end, exactly where the ends are being found."""
    k = max(int(round(points_per_slice)), 1)
    n = brightness.shape[1]
    runs = [slice(i, min(i + k, n)) for i in range(0, n, k)]
    mean = np.stack([brightness[:, r].mean(axis=1) for r in runs], axis=1)   # (slices, runs)
    count, steps = mean.shape
    score = mean[:, 0].copy()
    came_from = np.zeros(mean.shape, np.intp)
    for j in range(1, steps):
        new = np.full(count, -np.inf)
        for s in range(count):
            for prev in (s - 1, s, s + 1):
                if 0 <= prev < count:
                    value = score[prev] - JUMP_PENALTY * abs(zs[s] - zs[prev])
                    if value > new[s]:
                        new[s], came_from[s, j] = value, prev
        score = new + mean[:, j]
    at = np.zeros(steps, np.intp)
    at[-1] = score.argmax()
    for j in range(steps - 1, 0, -1):
        at[j - 1] = came_from[at[j], j]
    route = np.zeros(n, np.intp)
    for r, s in zip(runs, at):
        route[r] = s
    return route


def lift_ends(stack: np.ndarray, levels: np.ndarray, zs: Any, answer: dict[str, Any],
              pixel_um: float, z_step_um: float) -> dict[str, Any] | None:
    """lift, with the AIS's ends found from the slices (module docstring),
    and the same numbers. None when the trace or its new section is too
    short, or its 3D profile flat."""
    pixels = np.asarray(answer["pixels"], np.intp).reshape(-1, 2)
    n = len(pixels)
    if n < MIN_POINTS:
        return None
    zs = np.asarray(zs, np.float64)
    levelled = _sample(stack, pixels) / levels[:, None]
    brightness = levelled / max(float(levelled.max()), 1e-9)
    route = _steady_route(brightness, zs, z_step_um / pixel_um / MAX_SLOPE)
    t = np.arange(1.0, n + 1)
    z = ml.csaps(t, _centroid(brightness, route, zs)[None, :], Z_SMOOTHING, t)[0]
    profile = np.array([np.interp(z[i], zs, levelled[:, i]) for i in range(n)])
    settings = aa.Settings.from_dict(answer.get("settings"))
    found = _bounds(profile, settings.slide_d, settings.f)
    if found is None:
        return None
    norm_lv, max_i, ais_end, ais_start = found
    moved = answer | {"profile": dict(answer["profile"]) | {"ais_start": ais_start, "ais_end": ais_end}}
    first, last = _section(moved)
    if last - first + 1 < MIN_POINTS:
        return None
    # Measured as lift measures its section, along this route: lift's own
    # route on the new section could still take a patch at its very end.
    section = pixels[first:last + 1]
    bright = brightness[:, first:last + 1] / max(float(brightness[:, first:last + 1].max()), 1e-9)
    steady = route[first:last + 1]
    ts = np.arange(1.0, len(section) + 1)
    zz = ml.csaps(ts, _centroid(bright, steady, zs)[None, :], Z_SMOOTHING, ts)[0]
    xy = _on_spline(section, np.asarray(answer["spline"], np.float64)) * pixel_um
    peak = bright[steady, np.arange(len(section))]
    contrast = float(np.median((peak - np.median(bright, axis=0)) / np.maximum(peak, 1e-9)))
    numbers = {"length_3d_um": _arc(xy[:, 0], xy[:, 1], zz * z_step_um), "length_xy_um": _arc(xy[:, 0], xy[:, 1]),
               "z_start": float(zz[0]), "z_end": float(zz[-1]), "z_span_um": float(zz.max() - zz.min()) * z_step_um,
               "z_confidence": min(max(contrast, 0.0), 1.0)}
    if not all(math.isfinite(v) for v in numbers.values()):
        return None
    path: list[float | None] = [None] * n
    path[first:last + 1] = [round(float(v), 2) for v in zz]
    ends = {0, len(zs) - 1}
    out = ({k: round(v, 3) for k, v in numbers.items()}
           | {"z_step_um": z_step_um, "z_clipped": int(int(steady[0]) in ends or int(steady[-1]) in ends), "z_path": path})
    return out | {"z_ais_start": ais_start, "z_ais_end": ais_end,
                  "z_profile": {"norm_lv": [round(float(v), 4) for v in norm_lv], "max_i": max_i,
                                "ais_start": ais_start, "ais_end": ais_end}}


def section_widths(answer: dict[str, Any], z_path: list[float | None]) -> dict[str, Any]:
    """answer with its shape's widths (one per point of the projection's
    section) laid along the section z_path covers, each point taking the
    width of the nearest point the projection measured, for area.volumes:
    the blob was only measured over the projection's section. An estimate."""
    widths = list((answer.get("shape") or {}).get("widths_um") or [])
    idx = [i for i, v in enumerate(z_path) if v is not None]
    if not widths or not idx:
        return answer
    first, _ = _section(answer)
    laid = [widths[min(max(i - first, 0), len(widths) - 1)] for i in idx]
    return answer | {"shape": dict(answer["shape"]) | {"widths_um": laid}}


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
    own_section: bool = False   # finds its own AIS ends, not the projection's


# Settings' Z method list (static/js/settings.js) follows this.
METHODS = (
    Method("trace_lift", "Trace, then lift to Z", True, lift),
    Method("lift_ends", "Trace, lift to Z, ends from the slices", True, lift_ends, own_section=True),
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
