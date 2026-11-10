"""The batch report and the comparison as JSON: what the Batches screen's
exports put in report.xlsx and comparison.xlsx (static/js/ais_export.js
sheets, static/js/compare.js), for an agent or a script that wants the
numbers without unzipping a ZIP or reading a workbook.

Same rows and numbers as the workbook (tests/test_report.py runs the JS on
the same input and checks), shaped for a program rather than a person:

- each sheet is {"columns": [...], "rows": [{column: value}]}, with the
  workbook's columns in its order;
- dates are ISO 8601 (UTC), not the browser's local format;
- an image's state is its key (done, auto, waiting, ...), not its label;
- a line with no type has type null, and a group with no treatment has
  treatment null, where the workbook writes "(no type)", "(no treatment)";
- measures are their ids (ais_length, ais_soma, type:<name>).
"""
from __future__ import annotations

import math
from typing import Any

from app.analysis import auto_params as ap
from app.analysis import compare

# AisExport.cols, zCols, autoCols, measureCols (static/js/ais_export.js).
COLS = ("batch_name", "batch_id", "image", "n", "file", "source", "length_um", "start_um", "end_um", "mid_um",
        "max_um", "arc_um", "threshold_initial", "threshold", "click_x", "click_y", "click2_x", "click2_y",
        "profile_points", "smooth", "pixconv", "f", "kernel", "sigma", "strel", "min_pixels", "max_path",
        "max_passes", "spline_p", "window_um", "width_um", "brightness", "soma_um", "soma_px", "soma_ais_x",
        "soma_ais_y", "soma_x", "soma_y", "origin", "accepted_at", "edited_at", "notes")
Z_COLS = ("length_3d_um", "length_xy_um", "z_start", "z_end", "z_span_um", "z_step_um", "z_confidence", "z_clipped",
          "z_method")
AUTO_COLS = ("auto_method", "auto_review", "auto_start", "auto_min_length", "auto_min_length_shown",
             "auto_min_brightness", "auto_min_contrast", "auto_min_width", "auto_max_soma_gap", "auto_max_branchiness",
             "auto_min_score")
MEASURE_COLS = ("batch_name", "batch_id", "image", "n", "type", "label", "length_um", "length_px", "a_x", "a_y",
                "b_x", "b_y", "pixconv", "created_at", "edited_at")
SUMMARY_COLS = ("batch", "batch_id", "opened_by", "created", "archived", "images", "completed", "duplicates", "ais",
                "mean_um", "median_um", "sd_um", "min_um", "max_um", "ais_per_image")
IMAGE_COLS = ("batch", "image", "state", "ais", "mean_um", "median_um", "assignee")
ASSIGNEE_COLS = ("batch", "person", "images", "completed", "percent", "ais", "last_activity")
TYPE_COLS = ("batch", "image", "type", "count", "mean_type_um", "median_type_um", "sd_type_um")
# compare.js imageSheets, pooledSheet, statsSheet and sheets.
NAMES_COLS = ("batch", "image", "original", "treatment", "ais", "mean_length", "soma", "mean_soma")
GROUP_COLS = ("batch", "treatment", "measure", "n", "mean", "median", "sd", "sem")
CULTURE_COLS = ("batch", "treatment", "measure", "n", "mean", "sd", "sem")
POOLED_COLS = ("treatment", "measure", "n", "mean", "sd", "sem", "cultures", "culture_mean", "culture_sd",
               "culture_sem")
STATS_COLS = ("measure", "main", "design", "test", "groups", "n", "statistic", "p", "p_holm", "stars", "note")
VALUE_COLS = ("batch", "image", "original", "treatment", "measure", "value")
SHEETS = ("summary", "images", "assignees", "ais", "measurements", "measurement_types",
          "original_names", "by_treatment", "statistics")


def _round3(x: float) -> float:
    return ap._js_round(x * 1000) / 1000


def stats(values: list[Any]) -> dict[str, Any]:
    """AisExport.stats: n, mean, median, SD (sample), min and max, rounded
    to 3 decimals; None when there are none."""
    v = sorted(x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x))
    if not v:
        return {"n": 0, "mean": None, "median": None, "sd": None, "min": None, "max": None}
    mean = sum(v) / len(v)
    mid = len(v) // 2
    median = v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
    sd = math.sqrt(sum((b - mean) ** 2 for b in v) / (len(v) - 1)) if len(v) > 1 else None
    return {"n": len(v), "mean": _round3(mean), "median": _round3(median), "sd": None if sd is None else _round3(sd),
            "min": _round3(v[0]), "max": _round3(v[-1])}


def image_state(image: dict[str, Any]) -> str:
    """AisExport.imageState, most telling first."""
    if image.get("dup_of") is not None:
        return "duplicate"
    if image["stored"] < image["files"]:
        return "not_uploaded"
    if image["done"]:
        return "done"
    if image["ais"] and image["auto"] == image["ais"]:
        return "auto"
    if image["ais"]:
        return "accepted"
    return "waiting"


def cols_for(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    """AisExport.colsFor: the Z and auto columns only when a row has them."""
    cols = COLS + Z_COLS if any(r.get("z_method") for r in rows) else COLS
    if any(r.get("auto_method") for r in rows):
        cols = cols + AUTO_COLS
    return cols


def _sheet(cols: tuple[str, ...], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"columns": list(cols), "rows": [{c: row.get(c) for c in cols} for row in rows]}


def sheets(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """AisExport.sheets. items: [{batch (a list_batches row with
    created_by_name and assignee names), images (its image_status with
    assignee_name), rows (its results), measurements}]."""
    summary = []
    for item in items:
        b, images, rows = item["batch"], item.get("images") or [], item["rows"]
        s = stats([r.get("length_um") for r in rows])
        completed = b.get("completed")
        summary.append({"batch": b["name"], "batch_id": b["id"], "opened_by": b.get("created_by_name") or "",
                        "created": b.get("created_at") or "", "archived": b.get("archived_at") or "",
                        "images": len(images), "completed": completed, "duplicates": b.get("duplicates") or 0,
                        "ais": len(rows), "mean_um": s["mean"], "median_um": s["median"], "sd_um": s["sd"],
                        "min_um": s["min"], "max_um": s["max"],
                        "ais_per_image": ap._js_round(1000 * len(rows) / completed) / 1000 if completed else None})
    image_rows = []
    for item in items:
        by_image: dict[str, list[Any]] = {}
        for r in item["rows"]:
            by_image.setdefault(r["image"], []).append(r.get("length_um"))
        for image in item.get("images") or []:
            s = stats(by_image.get(image["key"], []))
            image_rows.append({"batch": item["batch"]["name"], "image": image["key"], "state": image_state(image),
                               "ais": image["ais"], "mean_um": s["mean"], "median_um": s["median"],
                               "assignee": image.get("assignee_name") or ""})
    assignees = [{"batch": item["batch"]["name"], "person": a.get("name") or "", "images": a.get("images"),
                  "completed": a.get("completed"), "percent": ap._js_round(a["percent"]) if a.get("percent") is not None
                  else None, "ais": a.get("ais"), "last_activity": a.get("last_at") or ""}
                 for item in items for a in item["batch"].get("assignees") or []]
    all_rows = [r for item in items for r in item["rows"]]
    lines = [m for item in items for m in item.get("measurements") or []]
    return {
        "summary": _sheet(SUMMARY_COLS, summary),
        "images": _sheet(IMAGE_COLS, image_rows),
        "assignees": _sheet(ASSIGNEE_COLS, assignees),
        "ais": _sheet(cols_for(all_rows), all_rows),
        "measurements": _sheet(MEASURE_COLS, lines),
        "measurement_types": _sheet(TYPE_COLS, type_rows(items)),
    }


def type_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AisExport.typeRows: the recorded lines per batch, image and type."""
    groups: dict[tuple[Any, str, str | None], dict[str, Any]] = {}
    for item in items:
        b = item["batch"]
        for line in item.get("measurements") or []:
            kind = line.get("type") or None
            key = (b["id"], line["image"], kind)
            groups.setdefault(key, {"batch": b["name"], "image": line["image"], "type": kind, "lengths": []})
            groups[key]["lengths"].append(line.get("length_um"))
    out = []
    for g in groups.values():
        s = stats(g["lengths"])
        out.append({"batch": g["batch"], "image": g["image"], "type": g["type"], "count": s["n"],
                    "mean_type_um": s["mean"], "median_type_um": s["median"], "sd_type_um": s["sd"]})
    return out


def unrandomized(items: list[dict[str, Any]], full: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """AisExport.unrandomized: images, rows and lines under their original
    names (admins). full: batch id -> the whole batch record. A row keeps
    its random key as random_image."""
    out = []
    for item in items:
        batch = full.get(item["batch"]["id"]) or {"images": []}
        keys: dict[str, str] = {}
        files: dict[str, str] = {}
        for image in batch["images"]:
            if image.get("original_key"):
                keys[image["key"]] = image["original_key"]
            for f in image["files"].values():
                original = f.get("original")
                if not original:
                    continue
                files[f.get("name")] = original.get("name")
                files[f.get("rel")] = original.get("rel")
        out.append(item | {
            "images": [im | {"key": keys.get(im["key"], im["key"])} for im in item.get("images") or []],
            "rows": [r | {"random_image": r["image"], "image": keys.get(r["image"], r["image"]),
                          "file": files.get(r.get("file")) or r.get("file")} for r in item["rows"]],
            "measurements": [m | {"image": keys.get(m["image"], m["image"])} for m in item.get("measurements") or []],
        })
    return out


# --- the comparison (compare.js) ---------------------------------------------------


def stars(p: Any) -> str:
    """Compare.stars."""
    if p is None:
        return ""
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


def _stats_sheet(out: dict[str, Any]) -> dict[str, Any]:
    """Compare.statsSheet: every test, then the paired test's left-out batches."""
    rows = [{"measure": s["measure"], "main": bool(s.get("main")), "design": s.get("design"), "test": s.get("test"),
             "groups": s.get("groups"), "n": s.get("n"), "statistic": s.get("statistic"), "p": s.get("p"),
             "p_holm": s.get("p_holm"),
             "stars": "" if s.get("p") is None else stars(s["p_holm"] if s.get("p_holm") is not None else s["p"]),
             "note": s.get("note")} for s in out["stats"]]
    rows += [{"measure": d["measure"], "main": False, "design": "paired", "test": "left out", "groups": d["batch"],
              "n": None, "statistic": None, "p": None, "p_holm": None, "stars": "",
              "note": "left out of the paired test"} for d in out["dropped"]]
    return _sheet(STATS_COLS, rows)


def compare_sheets(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """compare.js sheets and imageSheets, from compare.compare's answer."""
    return {
        "culture_means": _sheet(CULTURE_COLS, [g for g in out["groups"] if g.get("treatment")]),
        "treatment_summary": _sheet(POOLED_COLS, out["pooled"]),
        "statistics": _stats_sheet(out),
        "all_values": _sheet(VALUE_COLS, out["values"]),
        "original_names": _sheet(NAMES_COLS, out["images"]),
        "by_treatment": _sheet(GROUP_COLS, out["groups"]),
    }


def comparison(store: Any, batch_ids: Any, labels: Any = None, tests: Any = None, units: Any = None,
               plots: bool = False, design: Any = None) -> dict[str, Any]:
    """compare.compare with its sheets, and the SVG plots only when asked
    (they are most of the answer's size)."""
    out = compare.compare(store, batch_ids, labels, tests, units, design)
    result = {k: v for k, v in out.items() if k != "plots"} | {"sheets": compare_sheets(out)}
    if plots:
        result["plots"] = out["plots"]
    return result


def extra_sheets(store: Any, batch_ids: list[int]) -> dict[str, dict[str, Any]]:
    """Compare.extraSheets: a report's Original names, By treatment and
    Statistics, once its images have treatments (admins); none otherwise."""
    if not batch_ids:
        return {}
    out = compare.compare(store, batch_ids)
    if not any(im.get("treatment") for im in out["images"]):
        return {}
    sheets_ = compare_sheets(out)
    extra = {"original_names": sheets_["original_names"], "by_treatment": sheets_["by_treatment"]}
    if out["stats"]:
        extra["statistics"] = sheets_["statistics"]
    return extra
