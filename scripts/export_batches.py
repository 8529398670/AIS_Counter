"""Copy the files of one or more batches out of the server's file store into a
folder, under their original names.

    .venv/bin/python scripts/export_batches.py                 list the batches
    .venv/bin/python scripts/export_batches.py C4 C5           by name (or id)
    .venv/bin/python scripts/export_batches.py --all [--archived]
    ... --out DIR                                               default ./exports

Reads the app's database (read-only) through config/config.yaml. Uploaded
files are stored once, by content (<storage>/ais/files/<sha256>.tif or .czi);
this puts each batch back together as DIR/<id>-<name>/, with the subfolders
the batch was opened with. A file already there with the right size is left
alone, so a re-run only copies what is missing. An Open-path batch's files
that were never fetched into the store are copied from the path the batch
recorded, if it is still there.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import config, db  # noqa: E402


def real_files(image: dict) -> list[dict]:
    """The image's files on disk: a Z-stack's slices stand in for its file."""
    return [part for f in image["files"].values() for part in f.get("slices", [f])]


def source(storage: Path, f: dict) -> Path | None:
    """Where this machine holds the file's bytes, or None."""
    files = storage / "ais" / "files"
    for ext in ("tif", "czi"):
        if (files / f"{f['sha']}.{ext}").exists():
            return files / f"{f['sha']}.{ext}"
    # Per-user folders from older versions; the server moves these on first use.
    legacy = next((storage / "ais").glob(f"[0-9]*/{f['sha']}.tif"), None)
    if legacy:
        return legacy
    if f.get("path") and Path(f["path"]).is_file():
        return Path(f["path"])
    return None


def target(folder: Path, rel: str) -> Path | None:
    """Where a file goes: its path inside the opened folder (the first part of
    rel is that folder's own name, as in app/models/ais.group). None for a rel
    that would land outside the batch's folder."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    parts = parts[1:] if len(parts) > 1 else parts
    if not parts or any(p in (".", "..") for p in parts):
        return None
    return folder.joinpath(*parts)


def folder_name(batch: dict) -> str:
    name = re.sub(r"[^\w.() -]+", "_", batch["name"]).strip(" .") or "batch"
    return f"{batch['id']}-{name}"


def export(batch: dict, storage: Path, out: Path) -> tuple[int, int, list[str]]:
    """(copied, already there, missing rels)"""
    folder = out / folder_name(batch)
    copied = kept = 0
    missing = []
    seen = set()
    for image in batch["images"]:
        for f in real_files(image):
            if f["rel"] in seen:
                continue
            seen.add(f["rel"])
            dest, src = target(folder, f["rel"]), source(storage, f)
            if dest is None or src is None:
                missing.append(f["rel"])
                continue
            if dest.is_file() and dest.stat().st_size == f["size"]:
                kept += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied, kept, missing


def pick(batches: list[dict], wanted: list[str]) -> list[dict]:
    """Batches by id or name (case-insensitive); exits on one that matches
    none, or a name two batches share."""
    chosen = []
    for w in wanted:
        hits = [b for b in batches if str(b["id"]) == w] or [b for b in batches if b["name"].lower() == w.lower()]
        if not hits:
            sys.exit(f"no batch {w!r} (run with no arguments to list them)")
        if len(hits) > 1:
            sys.exit(f"{len(hits)} batches are named {w!r}: use the id ({', '.join(str(b['id']) for b in hits)})")
        chosen += [b for b in hits if b not in chosen]
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batches", nargs="*", help="batch names or ids; none lists them")
    ap.add_argument("-o", "--out", default="exports", help="folder to export into (default: ./exports)")
    ap.add_argument("--all", action="store_true", help="every batch that is not archived")
    ap.add_argument("--archived", action="store_true", help="with --all, archived batches too")
    args = ap.parse_args()

    cfg = config.load()
    store = db.Store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
    batches = sorted((b for _, b in store.all(db.BUCKET_AIS_BATCHES)), key=lambda b: b["id"])

    if not args.batches and not args.all:
        print(f"{'id':>4}  {'files':>5}  {'stored':>6}  name")
        for b in batches:
            files = {f["rel"]: f for im in b["images"] for f in real_files(im)}.values()
            stored = sum(1 for f in files if source(cfg.storage_dir, f))
            flag = "  (archived)" if b.get("archived_at") else ""
            print(f"{b['id']:>4}  {len(files):>5}  {stored:>6}  {b['name']}{flag}")
        print("\nexport with: scripts/export_batches.py NAME ... [--out DIR]  (or --all)")
        return

    chosen = [b for b in batches if args.archived or not b.get("archived_at")] if args.all \
        else pick(batches, args.batches)

    out = Path(args.out).expanduser()
    failed = False
    for b in chosen:
        copied, kept, missing = export(b, cfg.storage_dir, out)
        print(f"{folder_name(b)}: {copied} copied, {kept} already there"
              + (f", {len(missing)} missing" if missing else ""))
        for rel in missing:
            print(f"  missing: {rel}")
        failed |= bool(missing)
    print(f"-> {out.resolve()}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
