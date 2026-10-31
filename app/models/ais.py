"""Batches and accepted AIS for the Process screen, shared by every signed-in
user so a link to a folder and image works for the whole team.

A batch is one opened folder: its TIFFs grouped into images by cell (the
original's "<cell>.tif" + "<cell>.tif - Processed method 2.5.tif"), each file
known by the sha-256 of its bytes -- the id the shared file store
(app/analysis/service.py) keeps it under. A batch opened by path (Open path)
also records where each file lives, so the server can fetch one nobody has
opened yet. Images whose files are byte-identical to an earlier image's are
marked dup_of that image.

A result is one accepted AIS: the measures, clicks and trace the trace route
returned, numbered n per image here (max + 1) so two people accepting on the
same image at once cannot both get the same number. Deleting one renumbers
the rest of that image 1..k; editing one keeps its number.

Records are plain dicts in the store, returned as they are; the routes decide
what reaches the browser.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.core.db import BUCKET_AIS_BATCHES, BUCKET_AIS_RESULTS, Record, Store
from app.models import to_iso, utc_now

PROCESSED_SUFFIX = ".tif - Processed method 2.5.tif"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TIFF_RE = re.compile(r"\.tiff?$", re.IGNORECASE)
MAX_FILES = 5000
MAX_TEXT = 1000
SOURCES = ("upload", "path")

# What an accepted row may carry, and the type each value must have.
RESULT_NUMBERS = ("length_um", "start_um", "end_um", "mid_um", "max_um", "arc_um", "threshold_initial",
                  "threshold", "click_x", "click_y", "click2_x", "click2_y", "profile_points",
                  # the method settings it was measured with (app/analysis/ais_auto.Settings)
                  "pixconv", "f", "kernel", "sigma", "strel", "min_pixels", "max_path", "max_passes",
                  "spline_p", "window_um",
                  # how wide and bright the measured AIS is (app/analysis/service.shape)
                  "width_um", "brightness")
# origin: "auto" for one auto mode found, empty for a click.
RESULT_TEXTS = ("length_str", "source", "notes", "file", "sha", "smooth", "origin")


class BatchError(ValueError):
    """A request the model refuses, worded for the person making it."""


# --- grouping ------------------------------------------------------------------


def _text(value: Any, label: str, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT or (not empty and not value):
        raise BatchError(f"{label} must be text")
    return value


def clean_files(files: Any) -> list[dict[str, Any]]:
    """The file list a client (or the server, for Open path) sends:
    [{name, rel, sha, size, path?}], checked."""
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise BatchError(f"files must be a list of 1 to {MAX_FILES}")
    out = []
    for f in files:
        if not isinstance(f, dict):
            raise BatchError("each file must be an object")
        name = _text(f.get("name"), "name")
        if "/" in name or "\\" in name:
            raise BatchError("name must be a file name")
        rel = _text(f.get("rel", name), "rel")
        sha = f.get("sha")
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise BatchError("sha must be a sha-256 hex digest")
        size = f.get("size", 0)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BatchError("size must be a whole number")
        item = {"name": name, "rel": rel, "sha": sha, "size": size}
        if f.get("path") is not None:
            item["path"] = _text(f["path"], "path")
        out.append(item)
    return out


def group(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Files -> images, sorted by folder and cell. A cell is keyed by its
    folder inside the batch too, so same-named files in two subfolders stay two
    images. dup_of is the index of the first image with the same bytes."""
    images: dict[str, dict[str, Any]] = {}
    for f in files:
        name = f["name"]
        if name.startswith("."):
            continue
        if name.endswith(PROCESSED_SUFFIX):
            cell, role = re.sub(r"\.tif$", "", name[: -len(PROCESSED_SUFFIX)], flags=re.IGNORECASE), "processed"
        elif TIFF_RE.search(name):
            cell, role = TIFF_RE.sub("", name), "raw"
        else:
            continue
        parts = f["rel"].replace("\\", "/").split("/")
        folder = "/".join(parts[1:-1]) if len(parts) > 2 else ""
        key = f"{folder}/{cell}" if folder else cell
        image = images.setdefault(key, {"key": key, "cell": cell, "dir": folder, "files": {}})
        image["files"][role] = f
    ordered = sorted(images.values(), key=lambda im: (im["dir"].lower(), im["cell"].lower(), im["key"]))
    seen: dict[tuple[str, str], int] = {}
    for i, image in enumerate(ordered):
        files_ = image["files"]
        signature = (files_.get("processed", {}).get("sha", ""), files_.get("raw", {}).get("sha", ""))
        if signature in seen:
            image["dup_of"] = seen[signature]
        else:
            seen[signature] = i
    return ordered


# --- batches -------------------------------------------------------------------


def create_batch(store: Store, name: str, source: str, files: list[dict[str, Any]], user_id: int,
                 path: str | None = None) -> Record:
    if source not in SOURCES:
        raise BatchError("unknown source")
    images = group(clean_files(files))
    if not images:
        raise BatchError("no TIFF files")
    batch_id = store.next_sequence(BUCKET_AIS_BATCHES)
    record = {
        "id": batch_id,
        "name": _text(name, "name"),
        "source": source,
        "path": path,
        "created_by": user_id,
        "created_at": to_iso(utc_now()),
        "skipped": [],
        "images": images,
    }
    store.put(BUCKET_AIS_BATCHES, batch_id, record)
    return record


def get_batch(store: Store, batch_id: int) -> Record | None:
    return store.get(BUCKET_AIS_BATCHES, batch_id)


def list_batches(store: Store) -> list[Record]:
    """Newest first, without the image lists: name, counts and progress."""
    done_by_batch: dict[int, set[str]] = {}
    for _, row in store.all(BUCKET_AIS_RESULTS):
        done_by_batch.setdefault(row["batch_id"], set()).add(row["image"])
    out = []
    for _, batch in store.all(BUCKET_AIS_BATCHES):
        keys = {im["key"] for im in batch["images"]}
        done = (done_by_batch.get(batch["id"], set()) | set(batch["skipped"])) & keys
        out.append({k: batch[k] for k in ("id", "name", "source", "path", "created_by", "created_at")}
                   | {"images": len(keys), "completed": len(done),
                      "duplicates": sum(1 for im in batch["images"] if "dup_of" in im)})
    return sorted(out, key=lambda b: b["id"], reverse=True)


def set_done(store: Store, batch_id: int, key: str, done: bool) -> Record | None:
    """Mark (or unmark) an image done by hand -- shared progress."""
    def mutate(record: Record) -> None:
        if key not in {im["key"] for im in record["images"]}:
            raise BatchError("no such image in this batch")
        skipped = [k for k in record["skipped"] if k != key]
        if done:
            skipped.append(key)
        record["skipped"] = skipped

    return store.update_value(BUCKET_AIS_BATCHES, batch_id, mutate)


def delete_batch(store: Store, batch_id: int) -> None:
    with store.transaction() as tx:
        tx.delete(BUCKET_AIS_BATCHES, batch_id)
        tx.delete_where(BUCKET_AIS_RESULTS, lambda _key, row: row["batch_id"] == batch_id)


def local_path_for(store: Store, sha: str) -> str | None:
    """Where an Open-path batch found the file with this sha, if any."""
    for _, batch in store.all(BUCKET_AIS_BATCHES):
        if batch["source"] != "path":
            continue
        for image in batch["images"]:
            for f in image["files"].values():
                if f["sha"] == sha and f.get("path"):
                    return f["path"]
    return None


# --- results -------------------------------------------------------------------


def clean_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise BatchError("a result must be an object")
    out: dict[str, Any] = {}
    for k in RESULT_NUMBERS:
        v = row.get(k)
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool)):
            raise BatchError(f"{k} must be a number")
        out[k] = v
    for k in RESULT_TEXTS:
        v = row.get(k, "")
        out[k] = _text(v if v is not None else "", k, empty=True)
    pixels = row.get("pixels", [])
    if (not isinstance(pixels, list) or len(pixels) > 20000
            or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(c, int) and not isinstance(c, bool) for c in p)
                       for p in pixels)):
        raise BatchError("pixels must be [x, y] pairs")
    out["pixels"] = pixels
    return out


def add_result(store: Store, batch_id: int, image_key: str, row: Any, user_id: int) -> Record:
    clean = clean_row(row)
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            raise BatchError("no such batch")
        image = next((im for im in batch["images"] if im["key"] == image_key), None)
        if image is None:
            raise BatchError("no such image in this batch")
        same = [r["n"] for _, r in tx.all(BUCKET_AIS_RESULTS) if r["batch_id"] == batch_id and r["image"] == image_key]
        result_id = tx.next_sequence(BUCKET_AIS_RESULTS)
        record = clean | {
            "id": result_id,
            "batch_id": batch_id,
            "batch_name": batch["name"],
            "image": image_key,
            "cell": image["cell"],
            "n": max(same, default=0) + 1,
            "created_by": user_id,
            "accepted_at": to_iso(utc_now()),
        }
        tx.put(BUCKET_AIS_RESULTS, result_id, record)
    return record


def list_results(store: Store, batch_id: int | None = None) -> list[Record]:
    """Oldest first, like the order they were accepted in."""
    return [row for _, row in store.all(BUCKET_AIS_RESULTS) if batch_id is None or row["batch_id"] == batch_id]


def get_result(store: Store, result_id: int) -> Record | None:
    return store.get(BUCKET_AIS_RESULTS, result_id)


def update_result(store: Store, result_id: int, row: Any, user_id: int) -> Record | None:
    """Replace an accepted AIS's measures and trace (an edit), keeping which
    image it is on, its number, origin and who accepted it. None when it is
    gone."""
    clean = clean_row(row)
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_RESULTS, result_id)
        if record is None:
            return None
        kept = {k: record[k] for k in ("id", "batch_id", "batch_name", "image", "cell", "n", "created_by", "accepted_at")}
        record = clean | kept | {"origin": record.get("origin", ""), "edited_at": to_iso(utc_now()), "edited_by": user_id}
        tx.put(BUCKET_AIS_RESULTS, result_id, record)
    return record


def delete_result(store: Store, result_id: int) -> list[dict[str, int]]:
    """Delete one, and renumber the rest of its image 1..k in their order.
    Returns the new numbers, [{id, n}], of the rows that changed."""
    changed = []
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_RESULTS, result_id)
        if record is None:
            return []
        tx.delete(BUCKET_AIS_RESULTS, result_id)
        rest = sorted((r for _, r in tx.all(BUCKET_AIS_RESULTS)
                       if r["batch_id"] == record["batch_id"] and r["image"] == record["image"]),
                      key=lambda r: (r["n"], r["id"]))
        for n, r in enumerate(rest, 1):
            if r["n"] != n:
                tx.put(BUCKET_AIS_RESULTS, r["id"], r | {"n": n})
                changed.append({"id": r["id"], "n": n})
    return changed


def import_rows(store: Store, rows: Any, user_id: int, name: str) -> Record:
    """Rows accepted before results lived on the server (this browser's
    localStorage) become a batch of their own, one image per cell, so they
    are kept and exported like any other. Rows without a known sha still come
    across; their images just have no file to show."""
    if not isinstance(rows, list) or not rows or len(rows) > MAX_FILES:
        raise BatchError(f"rows must be a list of 1 to {MAX_FILES}")
    files: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("image"), str):
            raise BatchError("each row needs its image")
        cell = row["image"]
        sha = row.get("sha")
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            # A placeholder no file has: unique per cell, so these are not duplicates.
            sha = hashlib.sha256(("no file: " + cell).encode()).hexdigest()
        files.setdefault(cell, {"name": cell + PROCESSED_SUFFIX, "rel": cell + PROCESSED_SUFFIX, "sha": sha, "size": 0})
    batch = create_batch(store, name, "upload", list(files.values()), user_id)
    by_cell = {im["cell"]: im["key"] for im in batch["images"]}
    for row in rows:
        add_result(store, batch["id"], by_cell[row["image"]], row, user_id)
    return batch
