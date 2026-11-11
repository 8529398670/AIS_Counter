"""Auto mode's choices, filters and saved rows on the server: what the browser
does in static/js/ais_auto.js and static/js/ais.js, for a run an agent starts
(app/analysis/auto_runner.py, the MCP tools in app/routes/mcp_tools_ais.py).

A straight port, not a new auto mode: each function names its JS twin, and
tests/test_auto_params.py runs both on the same candidates and checks they
give the same rows. Change one and the other must follow. The browser's
settings live in its localStorage, so the server cannot read them; a run
gets these defaults (static/js/settings.js) unless it names its own.
"""
from __future__ import annotations

import math
from typing import Any

from app.analysis import ais_auto as aa
from app.analysis import zlength

# static/js/settings.js general.defaults: the ones auto mode reads.
DEFAULTS: dict[str, Any] = {
    "min_length": 0, "z_method": "trace_lift",
    "auto_method": "fitted", "auto_start": "soma", "auto_min_length": 5, "auto_min_brightness": 30,
    "auto_min_width": 2.4, "auto_max_soma_gap": 10,
    "fitted_min_length": 13, "fitted_min_brightness": 55, "fitted_max_branchiness": 1.02,
    "fitted2_min_length": 13, "fitted2_min_contrast": 30, "fitted2_min_brightness": 0, "fitted2_max_branchiness": 1.02,
    "learned_min_score": 25, "learned_min_length": 0,
    "auto_skip_done": True,
}
# settings.js general.ranges and choices, for the same fields.
RANGES: dict[str, tuple[float, float]] = {
    "min_length": (0, 1000), "auto_min_length": (0, 1000), "auto_min_brightness": (0, 100),
    "auto_min_width": (0, 20), "auto_max_soma_gap": (0, 100),
    "fitted_min_length": (0, 1000), "fitted_min_brightness": (0, 100), "fitted_max_branchiness": (0, 10),
    "fitted2_min_length": (0, 1000), "fitted2_min_contrast": (0, 100), "fitted2_min_brightness": (0, 100),
    "fitted2_max_branchiness": (0, 10), "learned_min_score": (0, 100), "learned_min_length": (0, 1000),
}
METHODS = ("classic", "fitted", "fitted2", "learned")
STARTS = ("soma", "both", "brighter", "dimmer")
# settings.js methods[0].defaults: threshold, and what methodSettings() sends.
THRESHOLD = 0.01
METHOD_SETTINGS: dict[str, Any] = {
    "smooth": "gaussian", "pixconv": 0.161, "f": 0.33, "kernel": 20, "sigma": 2, "strel": 3, "min_pixels": 70,
    "max_path": 300, "max_passes": 10, "spline_p": 0.3, "window_um": 1.5,
}
# AisExport.settingCols (static/js/ais_export.js).
SETTING_COLS = ("smooth", "pixconv", "f", "kernel", "sigma", "strel", "min_pixels", "max_path", "max_passes",
                "spline_p", "window_um")
# What a run's auto_review records: an agent's run saves without anyone
# looking, as "all" does in the browser.
REVIEW = "all"


class ParamError(ValueError):
    """A choice a run cannot use, worded for whoever asked."""


def _number(name: str, value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ParamError(f"{name} must be a number")
    low, high = RANGES[name]
    if not low <= value <= high:
        raise ParamError(f"{name} must be {low:g}-{high:g}")
    return value


def general(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """DEFAULTS with the caller's choices, each checked as Settings checks it.
    An unknown name is refused rather than ignored."""
    values = dict(DEFAULTS)
    for name, value in (overrides or {}).items():
        if name in RANGES:
            values[name] = _number(name, value)
        elif name == "auto_method":
            if value not in METHODS:
                raise ParamError("auto_method must be one of " + ", ".join(METHODS))
            values[name] = value
        elif name == "auto_start":
            if value not in STARTS:
                raise ParamError("auto_start must be one of " + ", ".join(STARTS))
            values[name] = value
        elif name == "z_method":
            try:
                values[name] = zlength.method(value).id
            except ValueError as exc:
                raise ParamError(str(exc)) from None
        elif name == "auto_skip_done":
            if not isinstance(value, bool):
                raise ParamError("auto_skip_done must be true or false")
            values[name] = value
        else:
            raise ParamError(f"unknown setting {name!r}")
    return values


def method_settings(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """METHOD_SETTINGS with the caller's, checked by ais_auto.Settings (which
    refuses unknown names and values out of range)."""
    values = METHOD_SETTINGS | dict(overrides or {})
    try:
        aa.Settings.from_dict(values)
    except ValueError as exc:
        raise ParamError(str(exc)) from None
    return values


def _or0(value: Any) -> Any:
    """JS `x || 0`."""
    return value or 0


def filters(g: dict[str, Any]) -> dict[str, Any]:
    """AisAuto.filters(): the start end and filters a run uses, from the
    general settings g (general())."""
    method = g["auto_method"]
    if method == "fitted":
        return {"method": "fitted", "start": "fitted", "min": _or0(g["fitted_min_length"]),
                "minShown": _or0(g["min_length"]), "brightness": _or0(g["fitted_min_brightness"]) / 100,
                "branchiness": _or0(g["fitted_max_branchiness"])}
    if method == "fitted2":
        return {"method": "fitted2", "start": "fitted2", "min": _or0(g["fitted2_min_length"]),
                "minShown": _or0(g["min_length"]), "contrast": _or0(g["fitted2_min_contrast"]) / 100,
                "brightness": _or0(g["fitted2_min_brightness"]) / 100,
                "branchiness": _or0(g["fitted2_max_branchiness"])}
    if method == "learned":
        return {"method": "learned", "start": "learned", "min": _or0(g["learned_min_length"]),
                "minShown": _or0(g["min_length"]), "score": _or0(g["learned_min_score"]) / 100}
    return {"method": "classic", "start": g["auto_start"],
            "min": max(_or0(g["min_length"]), _or0(g["auto_min_length"])),
            "brightness": _or0(g["auto_min_brightness"]) / 100, "width": _or0(g["auto_min_width"]),
            "somaGap": _or0(g["auto_max_soma_gap"])}


def _lt(a: Any, b: Any) -> bool:
    """JS a < b for the numbers (or null/undefined) a candidate carries:
    null is 0, undefined is NaN (never less, never more)."""
    return _js_num(a) < _js_num(b)


def _gt(a: Any, b: Any) -> bool:
    return _js_num(a) > _js_num(b)


_MISSING = object()


def _js_num(value: Any) -> float:
    if value is _MISSING:
        return math.nan
    if value is None:
        return 0.0
    return float(value)


def _get(d: Any, key: str) -> Any:
    return d.get(key, _MISSING) if isinstance(d, dict) else _MISSING


def passes(c: dict[str, Any], p: dict[str, Any]) -> bool:
    """AisAuto.passes, passesFitted and passesLearned."""
    method = p.get("method")
    if method in ("fitted", "fitted2"):
        f = c.get("filter") or {}
        shown = _get(c.get("measures"), "length_um")
        if p.get("minShown") and _lt(shown, p["minShown"]):
            return False
        if p.get("min") and (_lt(_get(f, "length_um"), p["min"]) or _lt(shown, p["min"])):
            return False
        if p.get("contrast") and _lt(_get(f, "contrast"), p["contrast"]):
            return False
        if p.get("brightness") and _lt(_get(f, "brightness"), p["brightness"]):
            return False
        if p.get("branchiness") and _gt(_get(f, "branchiness"), p["branchiness"]):
            return False
        return True
    if method == "learned":
        length = _get(c.get("measures"), "length_um")
        if p.get("minShown") and _lt(length, p["minShown"]):
            return False
        if p.get("min") and _lt(length, p["min"]):
            return False
        score = _get(c["filter"], "score") if c.get("filter") else 0
        return not (p.get("score") and _lt(score, p["score"]))
    m = c.get("measures")
    shape = c.get("shape") or {}
    if p.get("min") and _lt(_get(m, "length_um"), p["min"]):
        return False
    if p.get("brightness") and _lt(_get(shape, "brightness"), p["brightness"]):
        return False
    if p.get("width") and _lt(_get(shape, "width_um"), p["width"]):
        return False
    gap = c.get("soma_gap_um")
    if p.get("somaGap") and gap is not None and _gt(gap, p["somaGap"]):
        return False
    return True


# --- an image of a batch, as ais.js sees it ----------------------------------


def traced(files: dict[str, Any]) -> str:
    """Ais.traced: the role that is thresholded and traced."""
    if files.get("stack"):
        return "stack"
    if files.get("czi"):
        return "czi"
    return "processed" if files.get("processed") else "raw"


def kind(files: dict[str, Any]) -> str:
    """Ais.kind."""
    if files.get("stack"):
        return "stack"
    if files.get("czi"):
        return "czi"
    if files.get("processed") and files.get("raw"):
        return "pair"
    return "processed only" if files.get("processed") else "raw only"


def has_soma(image: dict[str, Any]) -> bool:
    """AisAuto.hasSoma: whether the image may have somata -- any but a
    Z-stack, as any channel showing cell bodies gives them (soma.best); the
    server starts from both ends when none does."""
    return not (image.get("files") or {}).get("stack")


def start_for(image_kind: str, start: str, soma: bool = True) -> str:
    """AisAuto.startFor: "soma" on an image that can have no somata (a
    Z-stack; soma: has_soma) is "both"."""
    return "both" if start == "soma" and (image_kind == "stack" or not soma) else start


def _js_round(x: float) -> float:
    """Math.round: halves go up, not to even."""
    return math.floor(x + 0.5)


def _pct(v: float) -> float:
    out = _js_round(v * 10000) / 100
    return int(out) if out == int(out) else out


def _num(v: Any) -> Any:
    """A JS number as JSON writes it: 5.0 is 5."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def auto_fields(p: dict[str, Any], review: str, image_kind: str, soma: bool = False) -> dict[str, Any]:
    """AisAuto.autoFields."""
    out: dict[str, Any] = {"auto_method": p["method"], "auto_review": review,
                           "auto_start": start_for(image_kind, p["start"], soma)}
    out["auto_min_length"] = _num(p.get("min") or 0)
    if "minShown" in p:
        out["auto_min_length_shown"] = _num(p["minShown"] or 0)
    if "brightness" in p:
        out["auto_min_brightness"] = _pct(p["brightness"] or 0)
    if "contrast" in p:
        out["auto_min_contrast"] = _pct(p["contrast"] or 0)
    if "width" in p:
        out["auto_min_width"] = _num(p["width"] or 0)
    if "somaGap" in p:
        out["auto_max_soma_gap"] = _num(p["somaGap"] or 0)
    if "branchiness" in p:
        out["auto_max_branchiness"] = _num(p["branchiness"] or 0)
    if "score" in p:
        out["auto_min_score"] = _pct(p["score"] or 0)
    return out


def row_for(files: dict[str, Any], r: dict[str, Any], origin: str, source: str,
            sha: str | None = None) -> dict[str, Any]:
    """Ais.rowFor: the row the server keeps for an accepted trace r on an
    image with these files. source is kind(files), which the browser puts on
    a candidate (AisAuto.find) or a click's result. sha is the image traced
    when that is not its file's own: a channel view's (Ais.sha)."""
    m = r["measures"]
    f = files[traced(files)]
    # Not the path of a blinded file: it has the original name in it.
    file = ("" if f.get("original") else f.get("path")) or f.get("rel") or f.get("name")
    clicks = r["clicks"]
    shape = r.get("shape")
    row: dict[str, Any] = {
        "file": file, "sha": sha or f.get("sha"),
        "length_um": m.get("length_um"), "length_str": m.get("length_str"), "start_um": m.get("start_um"),
        "end_um": m.get("end_um"), "mid_um": m.get("mid_um"), "max_um": m.get("max_um"), "arc_um": m.get("arc_um"),
        "threshold_initial": r.get("threshold_initial"), "threshold": r.get("threshold"),
        "click_x": clicks[0][0], "click_y": clicks[0][1], "click2_x": clicks[-1][0], "click2_y": clicks[-1][1],
        "profile_points": len(r["pixels"]), "source": source, "smooth": r["settings"].get("smooth"),
        "notes": "; ".join(r.get("notes") or []), "pixels": r["pixels"], "origin": origin,
        "width_um": shape.get("width_um") if shape else None,
        "brightness": shape.get("brightness") if shape else None,
    }
    for key in SETTING_COLS:
        if key != "smooth":
            row[key] = r["settings"].get(key)
    return row | (r.get("z") or {})


def auto_row(files: dict[str, Any], c: dict[str, Any], p: dict[str, Any], review: str = REVIEW,
             soma: bool = False, sha: str | None = None) -> dict[str, Any]:
    """What saveAll saves for a kept candidate: rowFor(..., "auto") and
    autoFields (soma: has_soma; sha: row_for's)."""
    source = kind(files)
    return row_for(files, c, "auto", source, sha) | auto_fields(p, review, source, soma)
