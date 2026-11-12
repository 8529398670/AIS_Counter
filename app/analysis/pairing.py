"""Which end of an accepted AIS starts at its soma, and which soma: the
Measure tool's first guess for its two ends (static/js/ais_measure.js), and
the start of a fully automatic AIS -> soma distance one day.

1. The thicker end. An AIS tapers away from its soma, so at each end the
   trace's first / last END_UM are measured across: at each point, a
   profile perpendicular to the trace on the (smoothed) AIS image, its full
   width at half maximum above the profile's floor. The end's width is the
   median. An end at least THICK_RATIO wider than the other is the start.
2. The soma in front. Out of a start end the AIS points away from the trace
   (outward: the end minus the trace point DIR_UM inward); its soma lies
   that way. Every soma outline point q costs d * (1 + K_ANGLE * (1 - cos)),
   d its distance and cos the angle between q - start and that direction:
   straight ahead costs d, beside it 3d, behind it 5d. Within TOUCH_UM the
   angle is noise, so such a point counts as ahead. The cheapest point is B.
3. Ends of about the same width: the end whose best soma costs less.

4. B on an ellipse. A soma outline is ragged, and often touching cells run
   together, so each soma is a body (soma.py: an outline, or with split
   one piece per hotspot) and an ellipse: the largest that fits inside it,
   as round and as large as the user's soma shape allows (SomaShape); a
   body too small for it is no soma. B is where the line from the
   ellipse's centre toward A meets it; the gap is 0 when A is inside.

"confident" says the guess needs no one to check it: a clear width winner
whose soma is also the better one, and the next soma costs at least
MARGIN times as much. Nothing acts on it yet but the Measure tool's hint.

Points are 1-based [x, y], like soma.Somata.outlines and a trace's pixels.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import ndimage as ndi

from app.analysis.soma import Bodies

SMOOTH_PX = 1.0     # the AIS image's smoothing before profiles: speckle, not structure
END_UM = 2.0        # how much of each end is measured across
MIN_END_PX = 3      # ... and at least this many trace points
TANGENT_PX = 2      # the trace's local direction: from the point this far back to this far on
HALF_UM = 3.0       # a profile's reach either side of the trace (an AIS is ~1-2 um wide)
STEP_PX = 0.25      # a profile's sampling step
THICK_RATIO = 1.2   # an end this much wider than the other is the start
DIR_UM = 3.0        # outward: from the trace point this far in to the end
K_ANGLE = 2.0       # how much an angled soma costs over one straight ahead
TOUCH_UM = 1.0      # nearer than this, any soma counts as ahead
MARGIN = 1.5        # confident: the next soma costs at least this much more
CENTRES = 6           # a soma ellipse's centres tried: this many of the piece's deepest points, and its hotspot
ANGLE_STEP_DEG = 7.5  # ... its long axis's angles tried
RATIOS = 8            # ... and its widths tried, from the roundness allowed to a circle


def smoothed(ais: np.ndarray) -> np.ndarray:
    """The AIS image as end_widths reads it (once per image)."""
    if ais.ndim == 3:
        ais = ais[:, :, 0]
    return ndi.gaussian_filter(ais.astype(np.float64), SMOOTH_PX)


def _fwhm(profile: np.ndarray, centre: int) -> float | None:
    """The profile's width at half its peak (near centre) over its floor, in
    samples, crossings interpolated; None when there is no peak."""
    reach = max(1, int(round(1.0 / STEP_PX)))    # the peak: within a pixel of the trace
    lo, hi = max(0, centre - reach), min(len(profile), centre + reach + 1)
    top = lo + int(np.argmax(profile[lo:hi]))
    floor = float(profile.min())
    peak = float(profile[top])
    if peak - floor <= 1e-9 * max(1.0, abs(peak)):
        return None
    half = floor + (peak - floor) / 2
    left = top
    while left > 0 and profile[left - 1] >= half:
        left -= 1
    right = top
    while right < len(profile) - 1 and profile[right + 1] >= half:
        right += 1
    a = float(left)
    if left > 0:
        a -= (profile[left] - half) / (profile[left] - profile[left - 1])
    b = float(right)
    if right < len(profile) - 1:
        b += (profile[right] - half) / (profile[right] - profile[right + 1])
    return b - a


def _end_width(smooth: np.ndarray, P: np.ndarray, pixel_um: float) -> float:
    """The width (um) of the trace's start: the median FWHM across its first
    END_UM. P: float [x, y] points, 1-based, the end first."""
    n = len(P)
    count = min(n, max(MIN_END_PX, int(round(END_UM / pixel_um))))
    half = HALF_UM / pixel_um
    t = np.arange(-half, half + STEP_PX / 2, STEP_PX)
    centre = int(np.argmin(np.abs(t)))
    widths = []
    for i in range(count):
        tangent = P[min(i + TANGENT_PX, n - 1)] - P[max(i - TANGENT_PX, 0)]
        norm = math.hypot(tangent[0], tangent[1])
        if norm == 0:
            continue
        nx, ny = -tangent[1] / norm, tangent[0] / norm
        xs, ys = P[i, 0] + t * nx, P[i, 1] + t * ny
        profile = ndi.map_coordinates(smooth, [ys - 1, xs - 1], order=1, mode="nearest")
        w = _fwhm(profile, centre)
        if w is not None:
            widths.append(w * STEP_PX)
    return float(np.median(widths) * pixel_um) if widths else math.nan


def end_widths(smooth: np.ndarray, pixels: list[list[int]], pixel_um: float) -> tuple[float, float]:
    """(first end's width, last end's width) in um; NaN where it can't be
    measured. smooth: smoothed(ais)."""
    P = np.asarray(pixels, np.float64).reshape(-1, 2)
    if len(P) < 2:
        return math.nan, math.nan
    return _end_width(smooth, P, pixel_um), _end_width(smooth, P[::-1], pixel_um)


def outward(pixels: list[list[int]], end: str, pixel_um: float) -> np.ndarray | None:
    """The unit [x, y] direction the AIS points out of its end ("first" |
    "last"): from the trace point DIR_UM in to the end. None for a dot."""
    P = np.asarray(pixels, np.float64).reshape(-1, 2)
    if end == "last":
        P = P[::-1]
    if len(P) < 2:
        return None
    k = min(len(P) - 1, max(1, int(round(DIR_UM / pixel_um))))
    v = P[0] - P[k]
    norm = math.hypot(v[0], v[1])
    return v / norm if norm else None


def best_soma(outlines: list[list[list[int]]], a: list[float], direction: np.ndarray | None,
              pixel_um: float) -> dict[str, Any] | None:
    """The soma outline point B for an AIS starting at a and pointing along
    direction (None: every way alike): {b, soma (its index), gap_um,
    angle_deg, score, margin (the next soma's score over this one's)}. None
    when there are no somata."""
    a = np.asarray(a, np.float64)
    per = []   # (score, point index, d, cos) per soma
    for outline in outlines:
        Q = np.asarray(outline, np.float64).reshape(-1, 2)
        if not len(Q):
            per.append(None)
            continue
        V = Q - a
        span = np.hypot(V[:, 0], V[:, 1])
        d = span * pixel_um
        if direction is None:
            cos = np.ones(len(Q))
        else:
            with np.errstate(invalid="ignore", divide="ignore"):
                cos = (V @ direction) / span
        cos = np.where((d < TOUCH_UM) | ~np.isfinite(cos), 1.0, cos)
        score = d * (1 + K_ANGLE * (1 - cos))
        i = int(np.argmin(score))
        per.append((float(score[i]), Q[i], float(d[i]), float(cos[i])))
    found = sorted((s for s in enumerate(per) if s[1] is not None), key=lambda s: s[1][0])
    if not found:
        return None
    k, (score, q, d, cos) = found[0]
    nxt = found[1][1][0] if len(found) > 1 else math.inf
    margin = nxt / score if score > 0 else (math.inf if nxt > 0 else 1.0)
    return {"b": [int(q[0]), int(q[1])], "soma": k, "gap_um": d,
            "angle_deg": math.degrees(math.acos(max(-1.0, min(1.0, cos)))), "score": score, "margin": margin}


def _num(v: float | None, digits: int = 3) -> float | None:
    return None if v is None or not math.isfinite(v) else round(v, digits)


def _choose(widths: tuple[float, float], ends: dict[str, tuple]) -> tuple[str, str, bool]:
    """(end, by, thick): the thicker end; ends alike, the one whose soma costs
    less; else the trace's start."""
    w0, w1 = widths
    if math.isfinite(w0) and math.isfinite(w1) and min(w0, w1) > 0 and max(w0, w1) / min(w0, w1) >= THICK_RATIO:
        return ("first" if w0 > w1 else "last"), "width", True
    if ends["first"][1] and ends["last"][1]:
        return ("first" if ends["first"][1]["score"] <= ends["last"][1]["score"] else "last"), "soma", False
    return "first", "default", False


# --- soma ellipses -------------------------------------------------------------

def body_outlines(bodies: Bodies) -> list[list[list[float]]]:
    """Per body, its piece's edge points as full-size 1-based [x, y]."""
    labels, step = bodies.labels, bodies.step
    out = []
    for k, box in enumerate(ndi.find_objects(labels, max_label=len(bodies.hotspots)), 1):
        if box is None:
            out.append([])
            continue
        piece = labels[box] == k
        rows, cols = np.nonzero(piece & ~ndi.binary_erosion(piece, border_value=0))
        out.append([[float((c + box[1].start) * step + 1), float((r + box[0].start) * step + 1)]
                    for r, c in zip(rows, cols)])
    return out


@dataclass
class SomaShape:
    """What counts as a soma, as the user sets it (the Soma size controls):
    its longest diameter (um) from min_um to max_um, and its roundness, the
    narrowest it may be across as a share of that (1: a circle)."""
    min_um: float = 6.0
    max_um: float = 40.0
    roundness: float = 0.6


def fit_ellipse(bodies: Bodies, k: int, shape: SomaShape, pixel_um: float) -> dict[str, float] | None:
    """Body k's ellipse, full-size px: the largest (by area) that lies inside
    its piece, no rounder than shape lets it be thin and no longer than
    shape.max_um. None when even that is shorter than shape.min_um: not a
    soma. {cx, cy, a (the long half-axis), b, angle_deg (of the long axis)}.

    For a centre c and a long axis at angle t, an ellipse with b = r a
    holds no pixel outside the piece while a is under the smallest
    sqrt(u^2 + (v / r)^2) over those pixels (u, v: their offsets from c
    along and across t), so every angle and r is a minimum over the pixels
    just outside. Centres tried: the deepest points of the piece (its
    distance-transform peaks) and its hotspot."""
    labels, step = bodies.labels, bodies.step
    mine = labels == k + 1
    if not mine.any():
        return None
    box = ndi.find_objects(mine.astype(np.int8))[0]
    r0, c0 = box[0].start - 1, box[1].start - 1
    piece = np.pad(labels[box] == k + 1, 1)
    outside = ndi.binary_dilation(piece, np.ones((3, 3), bool)) & ~piece
    full = lambda rows, cols: np.stack([(cols + c0) * step + 1.0, (rows + r0) * step + 1.0], axis=1)
    Q = full(*np.nonzero(outside))
    depth = ndi.distance_transform_edt(piece)
    peaks = (depth == ndi.maximum_filter(depth, size=5)) & piece & (depth >= 0.6 * depth.max())
    rows, cols = np.nonzero(peaks)
    order = np.argsort(-depth[rows, cols])[:CENTRES]
    centres = list(full(rows[order], cols[order])) + [np.asarray(bodies.hotspots[k], np.float64)]
    angles = np.radians(np.arange(0, 180, ANGLE_STEP_DEG))
    ratios = np.unique(np.linspace(min(max(shape.roundness, 0.05), 1.0), 1.0, RATIOS))
    cos, sin = np.cos(angles)[:, None], np.sin(angles)[:, None]
    longest = shape.max_um / 2 / pixel_um
    best = None
    for c in centres:
        D = Q - c
        u = D[:, 0][None, :] * cos + D[:, 1][None, :] * sin           # angles x pixels
        v = -D[:, 0][None, :] * sin + D[:, 1][None, :] * cos
        a = np.sqrt((u[:, :, None] ** 2 + (v[:, :, None] / ratios) ** 2).min(axis=1)) - step / 2
        a = np.clip(a, 0, longest)                                     # angles x ratios
        area = ratios * a * a
        i, j = np.unravel_index(int(np.argmax(area)), area.shape)
        if best is None or area[i, j] > best[0]:
            best = (float(area[i, j]), c, float(a[i, j]), float(ratios[j]), float(angles[i]))
    _, c, a, ratio, angle = best
    if 2 * a * pixel_um < shape.min_um:
        return None
    return {"cx": float(c[0]), "cy": float(c[1]), "a": a, "b": a * ratio, "angle_deg": math.degrees(angle)}


def ray_hit(e: dict[str, float], a: list[float], pixel_um: float) -> tuple[list[float], float]:
    """(B, gap um): where the line from the ellipse's centre toward a crosses
    its edge, and how far a is beyond it (0 when a is inside)."""
    c = np.array([e["cx"], e["cy"]])
    th = math.radians(e["angle_deg"])
    u, v = np.array([math.cos(th), math.sin(th)]), np.array([-math.sin(th), math.cos(th)])
    d = np.asarray(a, np.float64) - c
    r = math.hypot(d[0], d[1])
    w = d / r if r else u
    t = 1 / math.sqrt((float(w @ u) / e["a"]) ** 2 + (float(w @ v) / e["b"]) ** 2)
    B = c + t * w
    return [round(float(B[0]), 2), round(float(B[1]), 2)], max(0.0, r - t) * pixel_um


def _ellipse_json(e: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 2) for k, v in e.items()}


def pair_image(smooth: np.ndarray, bodies: Bodies | None, traces: list[list[list[int]]],
               pixel_um: float, shape: SomaShape | None = None) -> dict[str, Any]:
    """The Measure tool's guesses for every AIS on an image, and its somata:
    {pairs, bodies}. smooth: smoothed(ais); bodies: Somata.bodies(split), None
    without a soma channel.

    Each body's ellipse is the largest inside its piece that shape allows
    (fit_ellipse); a body too small for shape.min_um is no soma and drops
    out. Each trace's start end and body as pair's rules say (the body by
    best_soma on the pieces' edges). B is where the line from the ellipse's
    centre to A meets the ellipse.

    pairs: per trace {end, by, widths [first, last] um, a, b, body, soma (=
    body), gap_um, angle_deg, confident, other {end, a, b, body, gap_um} (the
    same from the other end)}; b, body and the gaps None without bodies.
    bodies: per body kept {cx, cy, a, b, angle_deg, ais (its most prominent
    AIS, by the most AIS signal along the trace: its index) | None}.
    JSON-safe."""
    shape = shape or SomaShape()
    ellipses, outlines = [], []
    if bodies is not None and bodies.hotspots:
        edges = body_outlines(bodies)
        for k in range(len(bodies.hotspots)):
            e = fit_ellipse(bodies, k, shape, pixel_um)
            if e is not None:
                if bodies.depths is not None:
                    e["z"] = bodies.depths[k]      # a Z-stack's: the soma's depth, in slice numbers
                ellipses.append(e)
                outlines.append(edges[k])
    background = float(np.median(smooth))
    guesses = []
    for pixels in traces:
        widths = end_widths(smooth, pixels, pixel_um)
        ends = {}
        for end in ("first", "last"):
            a = list(pixels[0] if end == "first" else pixels[-1])
            ends[end] = (a, best_soma(outlines, a, outward(pixels, end, pixel_um), pixel_um) if outlines else None)
        end, by, thick = _choose(widths, ends)
        P = np.asarray(pixels).reshape(-1, 2) - 1
        level = smooth[np.clip(P[:, 1], 0, smooth.shape[0] - 1), np.clip(P[:, 0], 0, smooth.shape[1] - 1)]
        guesses.append({"pixels": pixels, "widths": widths, "ends": ends, "end": end, "by": by, "thick": thick,
                        "prominence": float(np.clip(level - background, 0, None).sum())})
    # Each body's most prominent AIS.
    facing: dict[int, int] = {}
    for i, g in enumerate(guesses):
        best = g["ends"][g["end"]][1]
        if best and (best["soma"] not in facing or g["prominence"] > guesses[facing[best["soma"]]]["prominence"]):
            facing[best["soma"]] = i
    pairs = []
    for g in guesses:
        end = g["end"]
        other = "last" if end == "first" else "first"

        def at(which: str) -> dict[str, Any]:
            a, best = g["ends"][which]
            if not best:
                return {"end": which, "a": a, "b": None, "body": None, "gap_um": None}
            b, gap = ray_hit(ellipses[best["soma"]], a, pixel_um)
            return {"end": which, "a": a, "b": b, "body": best["soma"], "gap_um": _num(gap)}

        here, best, against = at(end), g["ends"][end][1], g["ends"][other][1]
        confident = bool(g["thick"] and best and (against is None or best["score"] <= against["score"])
                         and best["margin"] >= MARGIN)
        pairs.append({"end": end, "by": g["by"], "widths": [_num(g["widths"][0]), _num(g["widths"][1])],
                      "a": here["a"], "b": here["b"], "body": here["body"], "soma": here["body"],
                      "gap_um": here["gap_um"], "angle_deg": _num(best["angle_deg"], 1) if best else None,
                      "confident": confident, "other": at(other)})
    return {"pairs": pairs,
            "bodies": [_ellipse_json(e) | {"ais": facing.get(k)} for k, e in enumerate(ellipses)]}
