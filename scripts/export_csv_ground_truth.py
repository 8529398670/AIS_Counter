"""Write a batch's hand-clicked AIS, from its exported results.csv, as a
ground-truth file for scripts/auto_eval.py and scripts/train_learned.py.

    .venv/bin/python scripts/export_csv_ground_truth.py CSV CZI_DIR OUT.json

CSV is the Export screen's results.csv for the batch (example-data-2/C4_human_clicked/results.csv),
CZI_DIR the folder of its .czi images. Every image in CZI_DIR is written,
those with no row too (an image marked done with no AIS on it is a
true negative), so the file is exhaustive like export_ground_truth.py's.

Rows carry their click but not their trace: the trace is what a click there
gives (service.run_click, at the row's threshold_initial: "threshold" is
where the original's re-thresholding ended), and auto_eval.load
rebuilds it. Before writing, every row is clicked again here and its length
must come out as the CSV has it.
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import ais_auto as aa  # noqa: E402
from app.analysis import preprocess  # noqa: E402
from app.analysis.czi import read_czi  # noqa: E402
from app.analysis.service import bright_level, run_click  # noqa: E402

ROW_KEYS = ("length_um", "start_um", "end_um", "click_x", "click_y", "click2_x", "click2_y", "threshold_initial",
            "threshold")
TOLERANCE_UM = 1e-3


def _row(r: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ROW_KEYS:
        v = r.get(k, "")
        out[k] = None if v == "" else (int(float(v)) if k.startswith("click") else float(v))
    out["origin"] = r.get("origin") or ""
    return out


def _check(job: tuple[Path, list[dict[str, Any]]]) -> list[str]:
    """Each row clicked again: what does not come out as the CSV has it."""
    path, rows = job
    if not rows:
        return []
    czi = read_czi(path.read_bytes())
    raw = np.ascontiguousarray(czi.as_tiff(czi.ais_name))
    prep = aa.PreparedImage.from_array(preprocess.processed(raw))
    cache: dict = {}
    ref = bright_level(raw)
    bad = []
    for i, r in enumerate(rows):
        click2 = None if r["click2_x"] in (None, r["click_x"]) and r["click2_y"] in (None, r["click_y"]) \
            else (float(r["click2_x"]), float(r["click2_y"]))
        out = run_click(prep, raw, (float(r["click_x"]), float(r["click_y"])), click2, r["threshold_initial"] or 0.01,
                        aa.DEFAULT, cache, outline=False, bright_ref=ref)
        got = out["measures"]["length_um"] if out["ok"] else None
        if got is None or abs(got - r["length_um"]) > TOLERANCE_UM:
            bad.append(f"{path.stem} #{i + 1}: csv {r['length_um']}, clicked {got}")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv")
    ap.add_argument("czi_dir")
    ap.add_argument("out")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = ap.parse_args()

    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    batch = ""
    with open(args.csv, newline="") as f:
        for r in csv.DictReader(f):
            batch = batch or r.get("batch_name", "")
            rows[r["image"]].append(r)
    folder = Path(args.czi_dir)
    paths = sorted(folder.glob("*.czi"))
    missing = set(rows) - {p.stem for p in paths}
    if missing:
        sys.exit(f"rows for images not in {folder}: {', '.join(sorted(missing))}")
    images = []
    for path in paths:
        mine = sorted(rows.get(path.stem, []), key=lambda r: int(r["n"]))
        images.append({"key": path.stem,
                       "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                       "ais": [_row(r) for r in mine]})
    with multiprocessing.Pool(args.jobs) as pool:
        bad = [b for one in pool.map(_check, [(ROOT / i["file"], i["ais"]) for i in images]) for b in one]
    if bad:
        sys.exit("lengths that do not come out again:\n  " + "\n  ".join(bad))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"batch": batch, "images": images}, separators=(",", ":")))
    print(f"{len(images)} images, {sum(len(i['ais']) for i in images)} AIS, every length as clicked -> {args.out}")


if __name__ == "__main__":
    main()
