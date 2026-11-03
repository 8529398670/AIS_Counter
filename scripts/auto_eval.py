"""How well auto mode (app/analysis/detect.py) finds the AIS someone accepted.

    .venv/bin/python scripts/auto_eval.py [GROUND_TRUTH.json] [--method M] [--plain] [--start S] [--filters F]
    .venv/bin/python scripts/auto_eval.py [GROUND_TRUTH.json] --dump DIR

The ground truth is scripts/export_ground_truth.py's file (default
tests/autodata/batch12.json): every AIS accepted on each image, taken as the
complete set. A candidate matches an accepted AIS when more than half its
pixels lie within REACH px of that AIS's trace, one to one. Per image and in
total: precision, recall, F1, and the length error on matches.

--method is Settings > Auto mode's method with its default start and filter
values (static/js/settings.js): "classic" (start soma, its filters),
"fitted" or "fitted2" (that start, its filters), or "learned" (start
learned, kept from the lowest score its model was shipped with, which
--min-score overrides). --start and --filters (a set from
FILTERS, "off" for none) override either. --plain runs as for a TIFF pair (no
somata, no AMCA): start soma becomes both, as the client does.

--dump DIR writes, per image, what trying other rules needs without running
detection again: DIR/<key>.npz (raw AIS channel, AMCA, soma mask and gap)
and DIR/<key>.json, every component with the run_click result from each of
its skeleton's two ends (pixels, measures, shape, profile), its outline mask
bbox and the accepted AIS each end's trace matches, and "fitted": every
candidate start "fitted" finds, unfiltered, with the accepted AIS it matches.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis import ais_auto as aa  # noqa: E402
from app.analysis import detect as auto  # noqa: E402
from app.analysis import mlcompat as ml  # noqa: E402
from app.analysis import preprocess  # noqa: E402
from app.analysis import soma as somata  # noqa: E402
from app.analysis.czi import read_czi  # noqa: E402
from app.analysis.service import bright_level, run_click  # noqa: E402

DEFAULT_GT = ROOT / "tests" / "autodata" / "batch12.json"
REACH = 3      # px around an accepted trace that a candidate may lie in
# The client's filter defaults per method (static/js/settings.js): min
# length (um), min brightness (fraction), min width (um), max soma gap (um),
# max branchiness, min contrast (fraction); 0 is off.
FILTERS = {
    "off": ("classic", (0, 0, 0, 0, 0, 0)),
    "classic": ("classic", (5, 0.30, 2.4, 10, 0, 0)),
    "fitted": ("fitted", (13, 0.55, 0, 0, 1.02, 0)),
    "fitted2": ("fitted2", (13, 0, 0, 0, 1.02, 0.30)),
}
METHODS = {"classic": "soma", "fitted": "fitted", "fitted2": "fitted2", "learned": "learned"}   # method -> its start
OVERLAP = 0.5
LEARNED_MIN_SCORE: float | None = None   # --min-score


def load(gt_path: Path) -> list[dict[str, Any]]:
    """The ground truth's images, each with "raw" (the AIS channel as ZEN
    exports it), "amca" and "pixel_um" read from its .czi. An AIS without
    "pixels" (scripts/export_csv_ground_truth.py's files) gets the trace a
    click at its click gives."""
    images = json.loads(gt_path.read_text())["images"]
    for image in images:
        path = Path(image["file"])
        czi = read_czi((path if path.is_absolute() else ROOT / path).read_bytes())
        image["raw"] = np.ascontiguousarray(czi.as_tiff(czi.ais_name))
        image["amca"] = czi.channel(czi.soma_name or "AMCA")
        image["pixel_um"] = czi.pixel_um or aa.DEFAULT.pixconv
        if any("pixels" not in ais for ais in image["ais"]):
            _retrace(image)
    return images


def _retrace(image: dict[str, Any]) -> None:
    prep = aa.PreparedImage.from_array(preprocess.processed(image["raw"]))
    cache: dict = {}
    ref = bright_level(image["raw"])
    for ais in image["ais"]:
        if "pixels" not in ais:
            click = (float(ais["click_x"]), float(ais["click_y"]))
            two = ais.get("click2_x") is not None and (ais["click2_x"], ais["click2_y"]) != (ais["click_x"], ais["click_y"])
            click2 = (float(ais["click2_x"]), float(ais["click2_y"])) if two else None
            out = run_click(prep, image["raw"], click, click2, ais.get("threshold_initial") or 0.01, aa.DEFAULT, cache,
                            outline=False, bright_ref=ref)
            ais["pixels"] = out["pixels"]


def near_masks(image: dict[str, Any]) -> list[np.ndarray]:
    """Each accepted AIS's trace, grown by REACH."""
    out = []
    for ais in image["ais"]:
        m = np.zeros(image["raw"].shape[:2], bool)
        for x, y in ais["pixels"]:
            m[y - 1, x - 1] = True
        out.append(ndi.binary_dilation(m, iterations=REACH))
    return out


def on(mask: np.ndarray, pixels: list[list[int]]) -> float:
    return float(np.mean([mask[y - 1, x - 1] for x, y in pixels])) if pixels else 0.0


def match(candidates: list[dict[str, Any]], masks: list[np.ndarray]) -> list[int | None]:
    """Per candidate, the index of the accepted AIS it matches, or None.
    Greedy by overlap, best first, one to one."""
    pairs = sorted(((on(m, c["pixels"]), i, j) for i, c in enumerate(candidates) for j, m in enumerate(masks)),
                   reverse=True)
    out: list[int | None] = [None] * len(candidates)
    used = set()
    for frac, i, j in pairs:
        if frac <= OVERLAP:
            break
        if out[i] is None and j not in used:
            out[i] = j
            used.add(j)
    return out


def summary(tp: int, found: int, truth: int, errors: list[float]) -> dict[str, float]:
    p = tp / found if found else 0.0
    r = tp / truth if truth else 0.0
    e = np.array(errors) if errors else np.zeros(1)
    return {"tp": tp, "found": found, "truth": truth, "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "len_mae": float(np.abs(e).mean()), "len_bias": float(e.mean()),
            "len_within_2um": float(np.mean(np.abs(e) <= 2.0)) if errors else 0.0}


def _found(job: tuple[dict[str, Any], str, bool]) -> list[dict[str, Any]]:
    """Auto mode's candidates on one image."""
    image, start, plain = job
    raw = image["raw"]
    prep = aa.PreparedImage.from_array(preprocess.processed(raw))
    soma = None if plain else somata.find(image["amca"], image["pixel_um"])
    return auto.detect(prep, raw, 0.01, aa.DEFAULT, start, [], soma=soma)["candidates"]


def learned_min_score() -> float:
    """Method learned's lowest score: its model's, unless --min-score."""
    from app.analysis import learned
    return LEARNED_MIN_SCORE if LEARNED_MIN_SCORE is not None else learned.models()["meta"]["min_score"]


def passes(c: dict[str, Any], filters: str) -> bool:
    """static/js/ais_auto.js passes() (classic), passesFitted() and
    passesLearned(), with the general minimum length off."""
    if filters == "learned":
        return c["filter"]["score"] >= learned_min_score()
    method, (length, bright, width, gap, branch, contrast) = FILTERS[filters]
    f = c["filter"] if method != "classic" else dict(c["shape"], length_um=c["measures"]["length_um"])
    if length and f["length_um"] < length:
        return False
    if bright and f["brightness"] < bright:
        return False
    if width and f["width_um"] < width:
        return False
    if gap and c.get("soma_gap_um") is not None and c["soma_gap_um"] > gap:
        return False
    if contrast and f.get("contrast") is not None and f["contrast"] < contrast:
        return False
    return not (branch and f.get("branchiness", 0) > branch)


def evaluate(images: list[dict[str, Any]], start: str, plain: bool, filters: str = "off",
             jobs: int = 1) -> dict[str, Any]:
    per, tp, found, truth, errors = {}, 0, 0, 0, []
    with multiprocessing.Pool(jobs) as pool:
        all_found = pool.map(_found, [(image, start, plain) for image in images])
    for image, cands in zip(images, all_found):
        cands = [c for c in cands if passes(c, filters)]
        hits = match(cands, near_masks(image))
        errs = [c["measures"]["length_um"] - image["ais"][j]["length_um"] for c, j in zip(cands, hits) if j is not None]
        n = sum(j is not None for j in hits)
        per[image["key"]] = summary(n, len(cands), len(image["ais"]), errs)
        tp, found, truth = tp + n, found + len(cands), truth + len(image["ais"])
        errors += errs
    return {"images": per, "total": summary(tp, found, truth, errors)}


def dump(images: list[dict[str, Any]], folder: Path, jobs: int = 1) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with multiprocessing.Pool(jobs) as pool:
        pool.map(_dump_one, [(image, folder) for image in images])


def _dump_one(job: tuple[dict[str, Any], Path]) -> None:
    image, folder = job
    raw = image["raw"]
    prep = aa.PreparedImage.from_array(preprocess.processed(raw))
    soma = somata.find(image["amca"], image["pixel_um"])
    np.savez_compressed(folder / f"{image['key']}.npz", raw=raw, processed=prep.pic, amca=image["amca"],
                        soma_mask=soma.mask, soma_gap=soma.gap_um, pixel_um=image["pixel_um"])
    masks = near_masks(image)
    cache: dict = {}
    ref = bright_level(raw)
    L = aa.segment(prep, 0.01)
    cache[("L", 0.01)] = L
    boxes = ndi.find_objects(L)
    sizes = np.bincount(L.ravel())
    labels = sorted((k for k in range(1, len(boxes) + 1) if boxes[k - 1] is not None and sizes[k]),
                    key=lambda k: -sizes[k])[:auto.MAX_COMPONENTS]
    claimed = np.zeros(raw.shape, bool)
    comps = []
    for label in labels:
        box = boxes[label - 1]
        comp = L[box] == label
        if (comp & claimed[box]).sum() > auto.OVERLAP * comp.sum():
            continue
        local = np.unravel_index(int(np.argmax(np.where(comp, prep.D[box], -1.0))), comp.shape)
        bright = (box[0].start + int(local[0]), box[1].start + int(local[1]))
        try:
            tr = aa.trace(prep, (bright[1] + 1.0, bright[0] + 1.0), None, 0.01, aa.DEFAULT, cache)
        except ml.MatlabError:
            continue
        if (tr.selected & claimed).sum() > auto.OVERLAP * tr.selected.sum():
            continue
        claimed |= tr.selected
        claimed[box] |= comp
        ends = auto.skeleton_ends(tr.skeleton, (tr.start[0] - 1, tr.start[1] - 1))
        rows, cols = np.nonzero(tr.selected)
        entry = {"label": int(label), "area": int(rows.size),
                 "bbox": [int(cols.min()) + 1, int(rows.min()) + 1, int(cols.max()) + 1, int(rows.max()) + 1],
                 "skeleton_pixels": int(tr.skeleton.sum()),
                 "selected": [[int(c) + 1, int(r) + 1] for r, c in zip(rows, cols)],
                 "ends": []}
        for rc in ends:
            found = run_click(prep, raw, (rc[1] + 1.0, rc[0] + 1.0), None, 0.01, aa.DEFAULT, cache,
                              outline=False, bright_ref=ref)
            keep = {k: found.get(k) for k in ("ok", "error", "pixels", "measures", "shape", "profile", "path", "notes")}
            keep["seed"] = [rc[1] + 1, rc[0] + 1]
            keep["soma_gap_um"] = float(soma.gap_um[rc]) if np.isfinite(soma.gap_um[rc]) else None
            if found["ok"]:
                best = max(range(len(masks)), key=lambda j: on(masks[j], found["pixels"]), default=None)
                keep["gt"] = best if best is not None and on(masks[best], found["pixels"]) > OVERLAP else None
            entry["ends"].append(keep)
        comps.append(entry)
    fitted = auto.detect(prep, raw, 0.01, aa.DEFAULT, "fitted", [], soma=soma)["candidates"]
    keep = ("pixels", "seed", "measures", "shape", "filter", "soma_gap_um", "notes")
    fitted = [{k: c.get(k) for k in keep} | {"gt": j} for c, j in zip(fitted, match(fitted, masks))]
    (folder / f"{image['key']}.json").write_text(json.dumps(
        {"key": image["key"], "ais": image["ais"], "components": comps, "fitted": fitted}, separators=(",", ":")))
    print(image["key"], len(comps), "components", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gt", nargs="?", default=str(DEFAULT_GT))
    ap.add_argument("--method", default="classic", choices=METHODS)
    ap.add_argument("--start", choices=auto.STARTS, help="instead of the method's")
    ap.add_argument("--plain", action="store_true", help="no somata or AMCA, as for a TIFF pair")
    ap.add_argument("--filters", choices=list(FILTERS) + ["learned"], help="instead of the method's")
    ap.add_argument("--min-score", type=float, help="method learned's lowest score (0-1), instead of its model's")
    ap.add_argument("--dump", metavar="DIR")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="images worked on at once")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()
    global LEARNED_MIN_SCORE
    LEARNED_MIN_SCORE = args.min_score
    images = load(Path(args.gt))
    if args.dump:
        dump(images, Path(args.dump), args.jobs)
        return
    start = args.start or METHODS[args.method]
    start = "both" if args.plain and start == "soma" else start
    result = evaluate(images, start, args.plain, args.filters or args.method, args.jobs)
    if args.json:
        print(json.dumps(result, indent=1))
        return
    head = f"{'image':<22}{'truth':>6}{'found':>6}{'tp':>5}{'prec':>7}{'rec':>6}{'f1':>6}{'MAE':>7}{'bias':>7}{'<=2um':>7}"
    print(head)
    for key, s in list(result["images"].items()) + [("TOTAL", result["total"])]:
        print(f"{key:<22}{s['truth']:>6}{s['found']:>6}{s['tp']:>5}{s['precision']:>7.2f}{s['recall']:>6.2f}"
              f"{s['f1']:>6.2f}{s['len_mae']:>7.2f}{s['len_bias']:>7.2f}{s['len_within_2um']:>7.2f}")


if __name__ == "__main__":
    main()
