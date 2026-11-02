"""How close app/analysis/preprocess.py comes to ImageJ's "Processed method 2.5".

    .venv/bin/python scripts/preprocess_check.py FOLDER... [--limit N] [--detect] [--stages DIR]

For every `<cell>.tif` with its `<cell>.tif - Processed method 2.5.tif` in the
folders: the Dice overlap of the kept pixels (1 is the same mask) and how many
pixels differ. With --detect, auto mode too, on the real processed image and
on ours (start "both", AIS of 5 um or more): how many each finds, how many
match (traces overlapping by half), and how much the matched lengths differ.

With --stages DIR, every intermediate is compared with Fiji's, as written by

    fiji --headless -batch tests/imagej/method25_stages.ijm "FOLDER|DIR|0"

(DIR/<cell>.tif/1-background.tif ...): pixels that differ at each stage, so
the first stage that departs from ImageJ is named.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis import ais_auto as aa  # noqa: E402
from app.analysis import detect as auto  # noqa: E402
from app.analysis import mlcompat as ml  # noqa: E402
from app.analysis import preprocess  # noqa: E402

SUFFIX = " - Processed method 2.5.tif"
MIN_LENGTH_UM = 5.0


def pairs(folders: list[str]) -> list[tuple[Path, Path]]:
    out = []
    for folder in folders:
        for processed in sorted(Path(folder).glob("*" + SUFFIX)):
            raw = processed.with_name(processed.name[: -len(SUFFIX)])
            if raw.exists():
                out.append((raw, processed))
    return out


def dice(a: np.ndarray, b: np.ndarray) -> float:
    return 2 * float((a & b).sum()) / max(int(a.sum() + b.sum()), 1)


def found(processed: np.ndarray, raw: np.ndarray) -> list[dict]:
    out = auto.detect(aa.PreparedImage.from_array(processed), raw)
    return [c for c in out["candidates"] if c["measures"]["length_um"] >= MIN_LENGTH_UM]


def matches(real: list[dict], ours: list[dict], shape: tuple[int, int]) -> list[tuple[float, float]]:
    """(real length, our length) for each real AIS one of ours lies on."""
    out = []
    taken: set[int] = set()
    for r in real:
        near = np.zeros(shape, bool)
        for x, y in r["pixels"]:
            near[y - 1, x - 1] = True
        near = ml.imdilate_square(near, 7)
        for k, o in enumerate(ours):
            if k not in taken and sum(near[y - 1, x - 1] for x, y in o["pixels"]) > 0.5 * len(o["pixels"]):
                taken.add(k)
                out.append((r["measures"]["length_um"], o["measures"]["length_um"]))
                break
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--limit", type=int, default=0, help="only the first N pairs")
    parser.add_argument("--detect", action="store_true", help="compare auto mode too (seconds per image)")
    parser.add_argument("--stages", metavar="DIR", help="Fiji's intermediates (tests/imagej/method25_stages.ijm)")
    args = parser.parse_args()
    todo = pairs(args.folders)[: args.limit or None]
    if not todo:
        sys.exit("no TIFF pairs found")
    scores, totals = [], [0, 0, 0]
    diffs: list[float] = []
    stage_diffs: dict[str, int] = {}
    for raw_path, processed_path in todo:
        raw = tifffile.imread(raw_path)
        real = tifffile.imread(processed_path)
        steps = preprocess.stages(raw)
        ours = steps["8-final"]
        score = dice(real > 0, ours > 0)
        scores.append(score)
        line = f"{raw_path.name[:40]:40s}  dice {score:.4f}  differ {int((real != ours).sum()):5d} px"
        if args.stages:
            fiji = Path(args.stages) / raw_path.name
            off = {k: int((tifffile.imread(fiji / f"{k}.tif") != v).sum()) for k, v in steps.items()}
            for k, n in off.items():
                stage_diffs[k] = stage_diffs.get(k, 0) + n
            first = next((k for k, n in off.items() if n), None)
            line += "  fiji: " + (f"{first} differs ({off[first]} px)" if first else "identical")
        if args.detect:
            a, b = found(real, raw), found(ours, raw)
            matched = matches(a, b, raw.shape)
            totals[0] += len(a)
            totals[1] += len(b)
            totals[2] += len(matched)
            diffs += [abs(x - y) for x, y in matched]
            line += f"  AIS real {len(a):3d}  ours {len(b):3d}  matched {len(matched):3d}"
        print(line, flush=True)
    print(f"\n{len(todo)} pairs: mean dice {np.mean(scores):.4f} (min {np.min(scores):.4f})")
    if args.stages:
        print("pixels differing from Fiji, all images: "
              + ", ".join(f"{k} {n}" for k, n in stage_diffs.items()))
    if args.detect:
        print(f"auto mode: real {totals[0]} AIS, ours {totals[1]}, matched {totals[2]}"
              + (f", median length difference {np.median(diffs):.2f} um" if diffs else ""))


if __name__ == "__main__":
    main()
