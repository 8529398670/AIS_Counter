"""Write the AIS accepted on a batch's images as a ground-truth file for
scripts/auto_eval.py and tests/test_auto_eval.py.

    .venv/bin/python scripts/export_ground_truth.py BATCH_ID OUT.json [--skip K] [--images N]

Reads the app's database (read-only) through config/config.yaml. Only the
N images after the first K are written (default: every image after them with
at least one accepted AIS), each with its file path relative to the project
and every accepted row's trace, clicks and length. The labels are meant to be exhaustive: an
AIS auto mode finds there that is not in the file counts as a wrong pick.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import config, db  # noqa: E402

ROW_KEYS = ("length_um", "start_um", "end_um", "click_x", "click_y", "click2_x", "click2_y", "threshold", "origin")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batch", type=int)
    ap.add_argument("out")
    ap.add_argument("--skip", type=int, default=0, help="leave out the batch's first K images")
    ap.add_argument("--images", type=int, default=0, help="only N images (after the skipped ones)")
    args = ap.parse_args()

    cfg = config.load()
    store = db.Store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
    batch = store.get(db.BUCKET_AIS_BATCHES, args.batch)
    if batch is None:
        sys.exit(f"no batch {args.batch}")
    rows = [r for _, r in store.all(db.BUCKET_AIS_RESULTS) if r.get("batch_id") == args.batch]
    images = batch["images"][args.skip:]
    images = images[:args.images] if args.images else images
    out = []
    for image in images:
        mine = sorted((r for r in rows if r.get("image") == image["key"]), key=lambda r: r["n"])
        if not mine and not args.images:
            continue
        file = next(iter(image["files"].values()))
        path = Path(file["path"])
        out.append({
            "key": image["key"],
            "file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            "sha": file["sha"],
            "ais": [{k: r.get(k) for k in ROW_KEYS} | {"pixels": r["pixels"]} for r in mine],
        })
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"batch": batch["name"], "images": out}, separators=(",", ":")))
    print(f"{len(out)} images, {sum(len(i['ais']) for i in out)} AIS -> {args.out}")


if __name__ == "__main__":
    main()
