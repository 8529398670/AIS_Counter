"""Batches and accepted AIS for the Process screen, shared by every signed-in
user so a link to a folder and image works for the whole team.

A batch is one opened folder: its TIFFs grouped into images by cell (the
original's "<cell>.tif" + "<cell>.tif - Processed method 2.5.tif"; a .czi is
a cell on its own, role "czi", see app/analysis/service.py), each file
known by the sha-256 of its bytes -- the id the shared file store
(app/analysis/service.py) keeps it under. A batch opened by path (Open path)
also records where each file lives, so the server can fetch one nobody has
opened yet. Images whose files are byte-identical to an earlier image's are
marked dup_of that image.

An admin can split a batch among people by share (assign): each gets a
contiguous run of its images, duplicates left out, recorded per image in
the batch's assignment. Changing the split leaves finished images with
whoever had them and deals out only the rest. Progress is then counted per
person as well as for the whole batch.

Names can be blinded as they are added (randomize), the way the lab's
RandomNames.bat did: each image's cell becomes "<n>-<n>-<n>" (0..32767 each,
like %RANDOM%), a Zen "_c2_ORG" ending kept, and every file of the image
renamed to match, so pairs still pair. What a file was called before is kept
on it (original) for admins: the routes strip it for everyone else, and
translation() writes it out as the .bat's __Translation.txt. A folder blinded
before it got here brings the .bat's __Translation.txt along (or one is loaded
later, apply_translation): its names are kept on the files and images the
same way (name_images), as if this app had blinded them.

Each add (a folder or files picked, a server folder) is recorded in the
batch's adds, and its images carry its add_id, so the Images dialog can show
them folder by folder. Which images are included is the team's (excluded,
image keys): left out of stepping through, assigning, progress and exports.
New duplicates start excluded; a batch from before excluded existed counts
its duplicates as excluded.

A result is one accepted AIS: the measures, clicks and trace the trace route
returned, numbered n per image here (max + 1) so two people accepting on the
same image at once cannot both get the same number. Deleting one renumbers
the rest of that image 1..k; editing one keeps its number.

Records are plain dicts in the store, returned as they are; the routes decide
what reaches the browser.

A backup (backup_batch, import_batch) is a batch and its results as data, to
get a lost batch back or hand one to another server. It keeps blinded names,
so only admins get one; the page adds it to a ZIP export, with the image files
if asked (static/js/ais_export.js). Importing always makes a new batch.

The Batches screen files batches in folders, which nest: a folder has a
parent_id (None at the top), a batch a folder_id (missing or None at the
top). They are the team's, changed by admins only (the routes see to that).
Deleting a folder loses nothing: what was in it moves up to its parent. The
batches' priority order stays one order for every batch; a folder shows its
batches in that order.
"""
from __future__ import annotations

import hashlib
import math
import re
import secrets
import threading
import time
from collections import Counter
from typing import Any, Callable

from app.analysis import zstack
from app.core.db import (BUCKET_AIS_BATCHES, BUCKET_AIS_FOLDERS, BUCKET_AIS_MEASUREMENTS, BUCKET_AIS_RESULTS,
                         BUCKET_META, Record, Store)
from app.models import to_iso, utc_now

PROCESSED_SUFFIX = ".tif - Processed method 2.5.tif"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TIFF_RE = re.compile(r"\.tiff?$", re.IGNORECASE)
CZI_RE = re.compile(r"\.czi$", re.IGNORECASE)
MAX_FILES = 5000
MAX_TEXT = 1000
ROLES = ("processed", "raw", "czi", "stack")
SOURCES = ("upload", "path")    # "mixed" once a batch has had both
MAX_SHARES = 100
# A cell already blinded the RandomNames.bat way, and the ending Zen's Image
# Export adds (kept when a cell is blinded).
RANDOM_RE = re.compile(r"^\d{1,5}-\d{1,5}-\d{1,5}(?!\d)")
ZEN_SUFFIX_RE = re.compile(r"_c\d+_ORG$", re.IGNORECASE)
MAX_DATE = 40
MAX_TRANSLATION = 1_000_000     # characters of one __Translation.txt
MAX_TRANSLATIONS = 500          # of them in one add (one per folder)
BACKUP_FORMAT = "ais-batch-backup"
BACKUP_VERSION = 1
IMPORTED_SUFFIX = " (imported)"

# The Measure tool's AIS start -> soma distance (static/js/ais_measure.js):
# µm and px, then its two ends (AIS start, soma) in MATLAB axes like click_x.
SOMA_NUMBERS = ("soma_um", "soma_px", "soma_ais_x", "soma_ais_y", "soma_x", "soma_y")
# What an accepted row may carry, and the type each value must have.
RESULT_NUMBERS = ("length_um", "start_um", "end_um", "mid_um", "max_um", "arc_um", "threshold_initial",
                  "threshold", "click_x", "click_y", "click2_x", "click2_y", "profile_points",
                  # the method settings it was measured with (app/analysis/ais_auto.Settings)
                  "pixconv", "f", "kernel", "sigma", "strel", "min_pixels", "max_path", "max_passes",
                  "spline_p", "window_um",
                  # how wide and bright the measured AIS is (app/analysis/service.shape)
                  "width_um", "brightness",
                  # how far its start is from the soma, measured by hand (set_soma)
                  *SOMA_NUMBERS)
# origin: "auto" for one auto mode found, empty for a click.
RESULT_TEXTS = ("length_str", "source", "notes", "file", "sha", "smooth", "origin")
# A line the Measure tool recorded on an image, AIS or not: its ends in MATLAB
# axes, its length, and the pixel size that length was worked out with.
MEASUREMENT_NUMBERS = ("a_x", "a_y", "b_x", "b_y", "length_px", "length_um", "pixconv")
# Its type (clean_type): what kind of thing it measures, picked in the
# Measure tool from the team's list (measure_types, kept in the meta bucket).
DEFAULT_TYPES = ("Soma distance", "AIS length", "Node of Ranvier")
MEASURE_TYPES_KEY = "measure_types"
MAX_TYPE = 100
MAX_TYPES = 50
# What a row measured on a Z-stack adds (app/analysis/zlength.py). Kept apart
# from RESULT_NUMBERS so a row on an ordinary image stays exactly as it was:
# these are written only when present. z_clipped is 0 or 1.
Z_NUMBERS = ("length_3d_um", "length_xy_um", "z_start", "z_end", "z_span_um", "z_step_um", "z_confidence", "z_clipped")
# The auto mode settings a row auto mode saved was found with (static/js/
# ais_auto.js autoFields): its checking (each / end / all), method and start
# end, then the method's filters in Settings' units (µm, %, ratio; 0 is off).
# Like Z_NUMBERS, written only when present, so a clicked row is unchanged;
# an edit keeps them, as it keeps origin.
AUTO_TEXTS = ("auto_method", "auto_review", "auto_start")
AUTO_NUMBERS = ("auto_min_length", "auto_min_length_shown", "auto_min_brightness", "auto_min_contrast",
                "auto_min_width", "auto_max_soma_gap", "auto_max_branchiness", "auto_min_score")


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
        # When the file was last changed and (a server folder only) made, as ISO text.
        for k in ("modified", "created"):
            if f.get(k) is not None:
                if not isinstance(f[k], str) or len(f[k]) > MAX_DATE:
                    raise BatchError(f"{k} must be a date")
                item[k] = f[k]
        out.append(item)
    return out


def _folder(f: dict[str, Any]) -> str:
    """The folder a file is in, inside what was picked."""
    parts = f["rel"].replace("\\", "/").split("/")
    return "/".join(parts[1:-1]) if len(parts) > 2 else ""


def _stack_image(folder: str, cell: str, slices: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    """A Z-stack as one image: one file, standing for its slices (zstack.py)."""
    name = cell + zstack.SUFFIX
    head, sep, _ = slices[0]["rel"].replace("\\", "/").rpartition("/")
    file = {"name": name, "rel": head + sep + name, "sha": zstack.sha(zstack.manifest(slices, options)),
            "size": sum(s["size"] for s in slices), "slices": slices}
    return {"key": f"{folder}/{cell}" if folder else cell, "cell": cell, "dir": folder, "files": {"stack": file},
            "z_stack": {"count": len(slices)} | options}


def _take_stacks(files: list[dict[str, Any]], options: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(Z-stacks as images, the files left over). A stack is two or more
    slices of a cell in one folder with the same channel ending; a lone slice
    stays an ordinary image."""
    found: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for f in files:
        parsed = None if f["name"].startswith(".") else zstack.parse(f["name"])
        if parsed:
            cell, z, tail = parsed
            found.setdefault((_folder(f), cell, tail), []).append(f | {"z": z})
    stacks = {k: sorted(v, key=lambda s: s["z"]) for k, v in found.items() if len(v) >= zstack.MIN_SLICES}
    tails: dict[tuple[str, str], int] = {}
    for folder, cell, _ in stacks:
        tails[folder, cell] = tails.get((folder, cell), 0) + 1
    images, used = [], set()
    for (folder, cell, tail), slices in stacks.items():
        zs = [s["z"] for s in slices]
        if len(set(zs)) != len(zs):
            raise BatchError(f"{cell} has two slices with the same z")
        used |= {s["rel"] for s in slices}
        images.append(_stack_image(folder, f"{cell}_{tail}" if tail and tails[folder, cell] > 1 else cell, slices, options))
    return images, [f for f in files if f["rel"] not in used]


def group(files: list[dict[str, Any]], stack: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Files -> images, sorted by folder and cell. A cell is keyed by its
    folder inside the batch too, so same-named files in two subfolders stay two
    images. dup_of is the index of the first image with the same bytes. With
    stack (zstack.clean_options), Z-stack slices make one image each stack."""
    stacks, files = _take_stacks(files, stack) if stack else ([], files)
    images: dict[str, dict[str, Any]] = {}
    for f in files:
        name = f["name"]
        if name.startswith("."):
            continue
        if name.endswith(PROCESSED_SUFFIX):
            cell, role = re.sub(r"\.tif$", "", name[: -len(PROCESSED_SUFFIX)], flags=re.IGNORECASE), "processed"
        elif TIFF_RE.search(name):
            cell, role = TIFF_RE.sub("", name), "raw"
        elif CZI_RE.search(name):
            cell, role = CZI_RE.sub("", name), "czi"
        else:
            continue
        folder = _folder(f)
        key = f"{folder}/{cell}" if folder else cell
        image = images.setdefault(key, {"key": key, "cell": cell, "dir": folder, "files": {}})
        image["files"][role] = f
    ordered = sorted([*images.values(), *stacks], key=lambda im: (im["dir"].lower(), im["cell"].lower(), im["key"]))
    seen: dict[tuple[str, ...], int] = {}
    for i, image in enumerate(ordered):
        signature = _signature(image)
        if signature in seen:
            image["dup_of"] = seen[signature]
        else:
            seen[signature] = i
    return ordered


def is_random(cell: str) -> bool:
    return bool(RANDOM_RE.match(cell))


def randomize(images: list[dict[str, Any]], taken: set[str]) -> list[dict[str, Any]]:
    """Grouped images (group) with every cell not already blinded renamed
    "<n>-<n>-<n>" plus any Zen ending, unique against taken (which grows),
    and each file's name and rel to match; what they were is kept as
    original (files) and original_cell / original_key (images)."""
    out = []
    for image in images:
        if is_random(image["cell"]):
            taken.add(image["key"])
            out.append(image)
        else:
            out.append(_blind_image(image, taken))
    # In the order of the new names, so the old order gives nothing away.
    return sorted(out, key=lambda im: (im["dir"].lower(), im["cell"].lower(), im["key"]))


def _blind_image(image: dict[str, Any], taken: set[str]) -> dict[str, Any]:
    """The image under a new "<n>-<n>-<n>" name (plus any Zen ending),
    unique against taken (which grows), its files renamed to match. The
    first time, what it was called is kept as original; an image blinded
    before keeps that and lists the name it leaves behind as earlier."""
    cell = image["cell"]
    ending = ZEN_SUFFIX_RE.search(cell)
    suffix = ending.group(0) if ending else ""
    # A stack's folder is usually named after it, so it goes too. Its slices
    # keep their names at rest and are hidden when sent (routes/ais.py).
    stack = "stack" in image["files"]
    folder = "" if stack else image["dir"]
    while True:
        new = "-".join(str(secrets.randbelow(32768)) for _ in range(3)) + suffix
        key = f"{folder}/{new}" if folder else new
        if key not in taken:
            break
    taken.add(key)
    blinded = "original_cell" in image
    files = {}
    for role, f in image["files"].items():
        # A file's name starts with its cell (group cuts the ending off).
        name = new + f["name"][len(cell):]
        head, sep, _ = f["rel"].replace("\\", "/").rpartition("/")
        kept = ({"earlier": f.get("earlier", []) + [f["name"]]} if blinded
                else {"original": {"name": f["name"], "rel": f["rel"]}})
        files[role] = f | {"name": name, "rel": name if stack else head + sep + name} | kept
    out = image | {"key": key, "cell": new, "dir": folder, "files": files}
    if blinded:
        out["earlier_keys"] = image.get("earlier_keys", []) + [image["key"]]
    else:
        out |= {"original_cell": cell, "original_key": image["key"]}
        if stack:
            out["original_dir"] = image["dir"]
    return out


def real_files(image: dict[str, Any]) -> list[dict[str, Any]]:
    """The image's files on disk: a stack's slices stand in for its file."""
    return [part for f in image["files"].values() for part in f.get("slices", [f])]


def excluded_keys(batch: Record) -> set[str]:
    """The images left out for everyone; a batch from before this was kept
    leaves its duplicates out, as the Process screen did."""
    if "excluded" in batch:
        return set(batch["excluded"])
    return {im["key"] for im in batch["images"] if "dup_of" in im}


def included_keys(batch: Record) -> set[str]:
    return {im["key"] for im in batch["images"]} - excluded_keys(batch)


def translation(batch: Record) -> str:
    """The batch's blinded names as RandomNames.bat wrote them: a
    __Translation.txt of "original/random" lines, one per renamed file."""
    lines = ["Original Name/Random Name", "-------------------------"]
    earlier = []
    for image in batch["images"]:
        for f in image["files"].values():
            if "original" in f:
                # Stacks of two slides can share a cell, and "/" would split the line.
                folder = image.get("original_dir", "").replace("/", "__")
                lines.append(f"{folder + '__' if folder else ''}{f['original']['name']}/{f['name']}")
            earlier += [f"{old}/{f['name']}" for old in f.get("earlier", [])]
    # Names given before a folder was randomized again, so exports made
    # under them can still be read.
    if earlier:
        lines += ["", "Earlier Random Name/Random Name", "-------------------------------"] + earlier
    return "\r\n".join(lines) + "\r\n"


def parse_translation(text: Any) -> dict[str, str]:
    """A __Translation.txt (RandomNames.bat or .sh, or translation()) as
    random name -> original name: its "original/random" lines, the header
    skipped, up to the first blank line after them (translation() lists the
    earlier random names after one)."""
    if not isinstance(text, str) or len(text) > MAX_TRANSLATION:
        raise BatchError("translation must be text")
    names: dict[str, str] = {}
    for line in text.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line:
            if names:
                break
            continue
        if line == "Original Name/Random Name" or set(line) == {"-"}:
            continue
        original, sep, random = line.partition("/")
        if sep and original.strip() and random.strip():
            names[random.strip()] = original.strip()
    if not names:
        raise BatchError("the translation has no original/random names")
    return names


def clean_translations(value: Any) -> list[tuple[str, dict[str, str]]]:
    """The __Translation.txt files that came with an add, [{dir, text}] with
    dir the folder they were in (as an image's dir), parsed."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_TRANSLATIONS:
        raise BatchError(f"translations must be a list of at most {MAX_TRANSLATIONS}")
    out = []
    for t in value:
        if not isinstance(t, dict):
            raise BatchError("each translation must be an object")
        folder = _text(t.get("dir", ""), "dir", empty=True).replace("\\", "/").strip("/")
        out.append((folder, parse_translation(t.get("text"))))
    return out


def _name_image(image: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """The image with the original names a translation gives its files, kept
    as randomize keeps them (original, original_cell, original_key). The same
    image when it has originals already or none of its files is named."""
    if "original_cell" in image:
        return image
    cell = image["cell"]
    files = {}
    cells = {}
    for role, f in image["files"].items():
        old = names.get(f["name"])
        if old is None:
            files[role] = f
            continue
        head, sep, _ = f["rel"].replace("\\", "/").rpartition("/")
        files[role] = f | {"original": {"name": old, "rel": head + sep + old}}
        # A file's name is its cell and an ending (group): the original's
        # cell is the original name without that ending.
        ending = f["name"][len(cell):]
        cells[role] = (old[: -len(ending)] if ending and old.lower().endswith(ending.lower())
                       else re.sub(r"\.[^.]*$", "", old))
    if not cells:
        return image
    original = next(cells[role] for role in ("czi", "raw", "processed", "stack") if role in cells)
    return image | {"files": files, "original_cell": original,
                    "original_key": f"{image['dir']}/{original}" if image["dir"] else original}


def name_images(images: list[dict[str, Any]], translations: list[tuple[str, dict[str, str]]]) -> list[dict[str, Any]]:
    """Grouped images with the names translations (clean_translations) give
    them. A translation is for its folder and the folders inside it, the
    nearest one first, as RandomNames.bat works one folder at a time."""
    if not translations:
        return images
    ordered = sorted(translations, key=lambda t: len(t[0]))
    out = []
    for image in images:
        d = image["dir"]
        names: dict[str, str] = {}
        for folder, given in ordered:
            if not folder or d == folder or d.startswith(folder + "/"):
                names |= given
        out.append(_name_image(image, names) if names else image)
    return out


def unnamed(batch: Record) -> int:
    """Images with a random name and nothing saying what they were called:
    blinded somewhere else, their __Translation.txt not loaded."""
    return sum(1 for im in batch["images"] if is_random(im["cell"]) and "original_cell" not in im)


def apply_translation(store: Store, batch_id: int, text: Any) -> tuple[Record, int, int] | None:
    """A __Translation.txt for a batch already here: every image not named
    yet whose files it names, wherever in the batch. Keys stay, so nothing
    that names an image moves. Returns (batch, images named, images still
    unnamed), None when the batch is gone."""
    names = parse_translation(text)
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            return None
        named = 0
        for i, image in enumerate(batch["images"]):
            new = _name_image(image, names)
            if new is not image:
                batch["images"][i] = new
                named += 1
        if named:
            for a in batch.get("adds", []):
                if any(im.get("add_id") == a["id"] and "original_cell" in im for im in batch["images"]):
                    a["randomized"] = True
            _stamp(batch)
            tx.put(BUCKET_AIS_BATCHES, batch_id, batch)
    return batch, named, unnamed(batch)


def rerandomize(store: Store, batch_id: int, add_id: Any) -> tuple[Record, int, int] | None:
    """New random names for every image of one add (add_id, or "earlier"
    for images from before adds were kept), blinding any that were not.
    Everything that names an image by its key follows: accepted AIS (image,
    cell, file), done marks, the team's exclusions and the assignment.
    Returns (batch, images renamed, how many of them had AIS or a done
    mark), None when the batch is gone."""
    if add_id != "earlier" and (not isinstance(add_id, int) or isinstance(add_id, bool)):
        raise BatchError("add_id must be a folder's id or earlier")
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            return None
        adds = batch.get("adds", [])
        if add_id != "earlier" and not any(a["id"] == add_id for a in adds):
            raise BatchError("no such folder in this batch")
        want = None if add_id == "earlier" else add_id
        picked = [i for i, im in enumerate(batch["images"]) if im.get("add_id") == want]
        if not picked:
            raise BatchError("no images in this folder")
        excluded = excluded_keys(batch)
        taken = {im["key"] for im in batch["images"]}
        keys: dict[str, tuple[str, str]] = {}
        files: dict[str, str] = {}
        for i in picked:
            old = batch["images"][i]
            new = _blind_image(old, taken)
            batch["images"][i] = new
            keys[old["key"]] = (new["key"], new["cell"])
            for role, f in old["files"].items():
                files[f["name"]] = new["files"][role]["name"]
                files[f["rel"]] = new["files"][role]["rel"]

        def rekey(k: str) -> str:
            return keys[k][0] if k in keys else k

        measured = {k for k in batch["skipped"] if k in keys}
        batch["skipped"] = [rekey(k) for k in batch["skipped"]]
        moved = {rekey(k) for k in excluded}
        batch["excluded"] = [im["key"] for im in batch["images"] if im["key"] in moved]
        if batch.get("assignment"):
            batch["assignment"]["images"] = {rekey(k): u for k, u in batch["assignment"]["images"].items()}
        for _, row in tx.all(BUCKET_AIS_RESULTS):
            if row["batch_id"] == batch_id and row["image"] in keys:
                measured.add(row["image"])
                key, cell = keys[row["image"]]
                tx.put(BUCKET_AIS_RESULTS, row["id"], row | {"image": key, "cell": cell,
                                                             "file": files.get(row.get("file", ""), row.get("file", ""))})
        for key, line in tx.all(BUCKET_AIS_MEASUREMENTS):
            if line["batch_id"] == batch_id and line["image"] in keys:
                tx.put(BUCKET_AIS_MEASUREMENTS, key, line | {"image": keys[line["image"]][0]})
        for a in adds:
            if a["id"] == add_id:
                a["randomized"] = True
                a["rerandomized_at"] = to_iso(utc_now())
                if any("z_stack" in batch["images"][i] for i in picked):
                    _hide_add(a, batch)
        _stamp(batch)
        tx.put(BUCKET_AIS_BATCHES, batch_id, batch)
    return batch, len(picked), len(measured)


def _hide_add(add: dict[str, Any], record: Record) -> None:
    """An add of blinded stacks under the batch's own name, and with no path:
    what was picked is usually a stack's folder, so both say what it is. What
    they were stays for admins (routes/ais.py strips it for everyone else)."""
    if "original_name" not in add:
        add |= {"original_name": add["name"], "original_path": add["path"]}
    if record.get("path") and record["path"] == add["path"]:
        record["path"] = None
    add |= {"name": record["name"], "path": None}


def _add(record: Record, images: list[dict[str, Any]], source: str, path: str | None,
         user_id: int | None, name: str | None) -> None:
    """images (grouped, maybe blinded) into the batch record as one add:
    recorded in adds, each image tagged with its add_id, new duplicates
    excluded."""
    adds = record.setdefault("adds", [])
    add_id = max((a["id"] for a in adds), default=0) + 1
    excluded = list(record.get("excluded", sorted(excluded_keys(record))))
    before = len(record["images"])
    record["images"] = merge(record["images"], [im | {"add_id": add_id} for im in images])
    added = record["images"][before:]
    excluded += [im["key"] for im in added if "dup_of" in im]
    record["excluded"] = excluded
    adds.append({"id": add_id, "name": (name or "").strip()[:200] or record["name"], "source": source,
                 "path": path, "added_at": to_iso(utc_now()), "added_by": user_id,
                 "randomized": any("original_cell" in im for im in added),
                 "count": len(added)})
    if any("z_stack" in im and "original_cell" in im for im in added):
        _hide_add(adds[-1], record)


# --- treatments ------------------------------------------------------------------
#
# What each image's culture was treated with ("DMSO+FK506"), kept on the image
# as treatment so exports can group by it (app/analysis/compare.py). It gives
# away what blinding hides, so like the original names only admins see it.
# guess_treatment reads it off the original name the lab's way,
# "<prep> <treatment> <coverslip>[-NN]" (BB50 DMSO+FK506 A-02);
# guess_treatments then looks at the whole batch and drops a per-dish tag
# ("C2 D6 TM+NaCl WO C-02" -> "TM+NaCl WO"). That is the guess "as written".
# The "matched" guess also gives spellings that only differ the treatment_key
# way one spelling, preferring one already saved in any batch, so batches
# line up. The admin picks either per batch (static/js/treatments.js), checks
# the result and saves it (set_treatments). Exports match saved treatments
# ignoring only case, so what is saved decides what groups together.

TRAILING_NUMBER_RE = re.compile(r"[-_ ]\d{1,3}$")
COVERSLIP_RE = re.compile(r"^[A-Z]{1,2}$")
PREP_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_.-]+$")


def guess_treatment(name: str) -> str:
    """The treatment in an original cell name: what is left once the Zen
    ending, a trailing -NN, the coverslip letter(s) at the end and the prep
    id at the start (letters and digits, like BB50) are taken off. "" when
    nothing is left or the name is not words with spaces between."""
    name = ZEN_SUFFIX_RE.sub("", name.rsplit("/", 1)[-1]).strip()
    name = TRAILING_NUMBER_RE.sub("", name).strip()
    words = name.split()
    if len(words) < 2:
        return ""
    if COVERSLIP_RE.match(words[-1]):
        words = words[:-1]
    if len(words) > 1 and PREP_RE.match(words[0]):
        words = words[1:]
    return " ".join(words) if words and words != name.split() else ""


HOURS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b")
MINUTES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)\b")
DISH_TAG_RE = re.compile(r"^[A-Za-z]{1,3}\d+$")


def treatment_key(name: str) -> str:
    """What two spellings of one treatment share: no case, "+" and "," as
    spaces, single spaces, and 3hrs / 3 Hr / 3hours as 3h (minutes as 3min).
    "DMSO 24Hr + KCl 3Hr" and "dmso 24hr KCl 3hr" are both "dmso 24h kcl 3h"."""
    key = re.sub(r"[+,]", " ", name.casefold())
    key = MINUTES_RE.sub(r"\1min", HOURS_RE.sub(r"\1h", key))
    return " ".join(key.split())


def _drop_dish_tag(guesses: list[str]) -> list[str]:
    """The guesses without a leading per-dish tag (D6, D78): only when every
    guess starts with one followed by more words, there are two tags or
    more, and tags and the rest pair off one to one, so the tag says nothing
    the rest does not (a drug like FK506 in front of differing rests stays)."""
    words = [g.split() for g in guesses if g]
    if not words or any(len(w) < 2 or not DISH_TAG_RE.match(w[0]) for w in words):
        return guesses
    rest_of: dict[str, str] = {}
    tag_of: dict[str, str] = {}
    for w in words:
        tag, rest = w[0].casefold(), treatment_key(" ".join(w[1:]))
        if rest_of.setdefault(tag, rest) != rest or tag_of.setdefault(rest, tag) != tag:
            return guesses
    if len(rest_of) < 2:
        return guesses
    return [g.split(None, 1)[1] if g else "" for g in guesses]


def guess_treatments(names: list[str], known: Any = (), matched: bool = True) -> list[str]:
    """guess_treatment for every name of one batch with a per-dish tag
    dropped (_drop_dish_tag): as written when not matched. Matched, each
    group of guesses with one treatment_key is spelled the way most of them
    are, or the way a known (saved) treatment with that key mostly is."""
    guesses = _drop_dish_tag([guess_treatment(n) for n in names])
    if not matched:
        return guesses
    seen: dict[str, Counter[str]] = {}
    for g in guesses:
        if g:
            seen.setdefault(treatment_key(g), Counter())[g] += 1
    saved: dict[str, Counter[str]] = {}
    for k in known:
        if k.strip():
            saved.setdefault(treatment_key(k), Counter())[k.strip()] += 1
    spelling = {key: (saved.get(key) or counts).most_common(1)[0][0] for key, counts in seen.items()}
    return [spelling[treatment_key(g)] if g else "" for g in guesses]


def saved_treatments(store: Store) -> list[str]:
    """Every treatment saved on an image, in every batch (one per image)."""
    return [im["treatment"] for _, b in store.all(BUCKET_AIS_BATCHES) for im in b["images"] if im.get("treatment")]


def original_cell(image: dict[str, Any]) -> str:
    """What an image was called before it was blinded (its cell if it never was)."""
    return image.get("original_cell") or image["cell"]


def treatments(batch: Record, known: Any = ()) -> list[dict[str, Any]]:
    """Per image, for the admins' review: its key, original name, the folder
    it came from (what was picked, then any subfolder), saved treatment (""
    if none), the guesses (guess_treatments: "guess" matched, preferring the
    known spellings, and "guess_written" as written), the matched guess's
    treatment_key (for lining batches up in the dialog), and whether it is
    included."""
    left_out = excluded_keys(batch)
    picked = {a["id"]: a.get("original_name") or a["name"] for a in batch.get("adds", [])}
    def folder(im: dict[str, Any]) -> str:
        sub = im.get("original_dir", im["dir"])
        return "/".join(p for p in (picked.get(im.get("add_id"), ""), sub) if p)
    names = [original_cell(im) for im in batch["images"]]
    matched = guess_treatments(names, known)
    written = guess_treatments(names, matched=False)
    return [{"key": im["key"], "original": name, "folder": folder(im), "treatment": im.get("treatment", ""),
             "guess": guess, "guess_written": as_written, "guess_key": treatment_key(guess),
             "included": im["key"] not in left_out}
            for im, name, guess, as_written in zip(batch["images"], names, matched, written)]


def treatment_counts(batch: Record, included: set[str]) -> dict[str, Any]:
    """The batch's saved treatments over its included images, for its card
    (admins only): {treatments: [[name, n], ...] most images first, matched
    ignoring case as the exports do and named the way most are spelled,
    untreated: how many included images have none}."""
    groups: dict[str, Counter[str]] = {}
    untreated = 0
    for im in batch["images"]:
        if im["key"] not in included:
            continue
        given = im.get("treatment", "").strip()
        if given:
            groups.setdefault(given.casefold(), Counter())[given] += 1
        else:
            untreated += 1
    named = [[c.most_common(1)[0][0], sum(c.values())] for c in groups.values()]
    return {"treatments": sorted(named, key=lambda t: (-t[1], t[0].casefold())), "untreated": untreated}


def review_treatments(store: Store, batch: Record) -> list[dict[str, Any]]:
    """treatments() with the guesses spelled like those saved in any batch."""
    return treatments(batch, saved_treatments(store))


def set_treatments(store: Store, batch_id: int, given: Any) -> Record | None:
    """{key: treatment} for images of the batch: each trimmed, "" taking it
    off. None when the batch is gone."""
    if not isinstance(given, dict) or len(given) > MAX_FILES:
        raise BatchError("treatments must be an object of image keys")
    clean = {}
    for key, value in given.items():
        if not isinstance(value, str) or len(value.strip()) > MAX_TYPE:
            raise BatchError("a treatment must be text")
        clean[key] = value.strip()
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            return None
        keys = {im["key"] for im in batch["images"]}
        if not set(clean) <= keys:
            raise BatchError("no such image in this batch")
        images = []
        for im in batch["images"]:
            if im["key"] in clean:
                im = {k: v for k, v in im.items() if k != "treatment"}
                if clean[im["key"]]:
                    im["treatment"] = clean[im["key"]]
            images.append(im)
        batch["images"] = images
        _stamp(batch)
        tx.put(BUCKET_AIS_BATCHES, batch_id, batch)
    return batch


def set_included(store: Store, batch_id: int, keys: Any, included: Any) -> Record | None:
    """Include (or leave out) these images, for everyone. None when the
    batch is gone."""
    if (not isinstance(keys, list) or len(keys) > MAX_FILES
            or not all(isinstance(k, str) for k in keys)):
        raise BatchError("keys must be a list of image keys")
    if not isinstance(included, bool):
        raise BatchError("included must be true or false")

    def mutate(record: Record) -> None:
        known = {im["key"] for im in record["images"]}
        out = excluded_keys(record)
        for k in keys:
            if k in known:
                if included:
                    out.discard(k)
                else:
                    out.add(k)
        record["excluded"] = [im["key"] for im in record["images"] if im["key"] in out]
        _stamp(record)

    return store.update_value(BUCKET_AIS_BATCHES, batch_id, mutate)


# --- batches -------------------------------------------------------------------


def _stamp(record: Record) -> None:
    record["updated_at"] = to_iso(utc_now())


def new_batch(store: Store, name: str, source: str, user_id: int, path: str | None = None,
              folder_id: Any = None) -> Record:
    """An empty batch, in folder_id (None: at the top); images come with add_files."""
    if source not in SOURCES:
        raise BatchError("unknown source")
    folder_id = _folder_ref(store, folder_id)
    batch_id = store.next_sequence(BUCKET_AIS_BATCHES)
    now = to_iso(utc_now())
    top = min((_position(b) for _, b in store.all(BUCKET_AIS_BATCHES)), default=0)
    record = {
        "id": batch_id,
        "name": clean_name(name),
        "source": source,
        "path": path,
        "created_by": user_id,
        "created_at": now,
        "updated_at": now,
        "position": top - 1,
        "archived_at": None,
        "skipped": [],
        "images": [],
        "adds": [],
        "excluded": [],
    }
    if folder_id is not None:
        record["folder_id"] = folder_id
    store.put(BUCKET_AIS_BATCHES, batch_id, record)
    return record


def clean_name(name: Any) -> str:
    name = _text(name.strip() if isinstance(name, str) else name, "name")
    if len(name) > 200:
        raise BatchError("name must be at most 200 characters")
    return name


def merge(existing: list[dict[str, Any]], added: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """added (from group) after existing: existing keys and indices stay put,
    a key already taken gets " (2)", " (3)", ..., and dup_of points at the
    first image, old or new, with the same bytes."""
    taken = {im["key"] for im in existing}
    out = list(existing)
    seen: dict[tuple[str, ...], int] = {}
    for i, image in enumerate(existing):
        seen.setdefault(_signature(image), i)
    for image in added:
        image = {k: v for k, v in image.items() if k != "dup_of"}
        key, n = image["key"], 2
        while key in taken:
            key, n = f"{image['key']} ({n})", n + 1
        taken.add(key)
        image["key"] = key
        signature = _signature(image)
        if signature in seen:
            image["dup_of"] = seen[signature]
        else:
            seen[signature] = len(out)
        out.append(image)
    return out


def _signature(image: dict[str, Any]) -> tuple[str, ...]:
    return tuple(image["files"].get(role, {}).get("sha", "") for role in ROLES)


def _stack_options(stack: Any) -> dict[str, Any] | None:
    if stack is None:
        return None
    try:
        return zstack.clean_options(stack)
    except ValueError as exc:
        raise BatchError(str(exc)) from exc


def add_files(store: Store, batch_id: int, source: str, files: Any, path: str | None = None, *,
              randomize_names: bool = False, user_id: int | None = None, name: str | None = None,
              translations: Any = None, stack: Any = None) -> Record | None:
    """More files into a batch: a folder or files picked later, named by the
    __Translation.txt files that came with them (clean_translations), blinded
    with randomize_names, recorded as one add called name. With stack
    (zstack.clean_options), Z-stack slices become one image each stack. None
    when the batch is gone. A batch fed from both the browser and a server
    folder becomes source "mixed"."""
    if source not in SOURCES:
        raise BatchError("unknown source")
    images = group(clean_files(files), _stack_options(stack))
    if not images:
        raise BatchError("no TIFF or CZI files")
    images = name_images(images, clean_translations(translations))

    def mutate(record: Record) -> None:
        if record["images"] and record["source"] != source:
            record["source"] = "mixed"
        elif not record["images"]:
            record["source"] = source
        if path and not record.get("path"):
            record["path"] = path
        added = randomize(images, {im["key"] for im in record["images"]}) if randomize_names else images
        _add(record, added, source, path, user_id, name)
        _stamp(record)

    return store.update_value(BUCKET_AIS_BATCHES, batch_id, mutate)


def create_batch(store: Store, name: str, source: str, files: list[dict[str, Any]], user_id: int,
                 path: str | None = None, *, randomize_names: bool = False, translations: Any = None,
                 stack: Any = None) -> Record:
    """A batch with its files in one go (Open folder, Open path), named by
    the __Translation.txt files that came with them."""
    if source not in SOURCES:
        raise BatchError("unknown source")
    images = group(clean_files(files), _stack_options(stack))
    if not images:
        raise BatchError("no TIFF or CZI files")
    images = name_images(images, clean_translations(translations))
    record = new_batch(store, name, source, user_id, path)
    _add(record, randomize(images, set()) if randomize_names else images, source, path, user_id, name)
    store.put(BUCKET_AIS_BATCHES, record["id"], record)
    return record


def rename_batch(store: Store, batch_id: int, name: Any) -> Record | None:
    """New name for the batch and for its accepted rows' batch_name."""
    clean = clean_name(name)
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            return None
        batch["name"] = clean
        _stamp(batch)
        tx.put(BUCKET_AIS_BATCHES, batch_id, batch)
        for key, row in tx.all(BUCKET_AIS_RESULTS):
            if row["batch_id"] == batch_id:
                tx.put(BUCKET_AIS_RESULTS, key, row | {"batch_name": clean})
        for key, line in tx.all(BUCKET_AIS_MEASUREMENTS):
            if line["batch_id"] == batch_id:
                tx.put(BUCKET_AIS_MEASUREMENTS, key, line | {"batch_name": clean})
    return batch


def _position(batch: Record) -> int:
    """Where the batch sits in the team's priority order, lowest first;
    batches from before the order existed sit newest first."""
    position = batch.get("position")
    return position if isinstance(position, int) else -batch["id"]


def archive_batch(store: Store, batch_id: int, archived: bool) -> Record | None:
    """Archive (or bring back) a batch: kept with its results, only hidden."""
    def mutate(record: Record) -> None:
        record["archived_at"] = to_iso(utc_now()) if archived else None
        _stamp(record)

    return store.update_value(BUCKET_AIS_BATCHES, batch_id, mutate)


def order_batches(store: Store, ids: Any) -> None:
    """The team's priority order: ids first, in that order, then every batch
    not listed, in the order it had."""
    if (not isinstance(ids, list) or len(ids) > 10000
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids)):
        raise BatchError("ids must be a list of batch ids")
    if len(set(ids)) != len(ids):
        raise BatchError("ids must not repeat")
    with store.transaction() as tx:
        current = sorted((b for _, b in tx.all(BUCKET_AIS_BATCHES)), key=lambda b: (_position(b), -b["id"]))
        rank = {batch_id: n for n, batch_id in enumerate(ids)}
        ordered = sorted(current, key=lambda b: (0, rank[b["id"]]) if b["id"] in rank else (1, 0))
        for position, batch in enumerate(ordered):
            if batch.get("position") != position:
                tx.put(BUCKET_AIS_BATCHES, batch["id"], batch | {"position": position})


def get_batch(store: Store, batch_id: int) -> Record | None:
    return store.get(BUCKET_AIS_BATCHES, batch_id)


# --- folders -------------------------------------------------------------------

MAX_FOLDERS = 2000
MAX_FOLDER_DEPTH = 12   # folders inside folders, the top one counting 1


def _is_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _folder_ref(store: Store | Any, folder_id: Any) -> int | None:
    """folder_id checked: None (the top) or a folder that exists. store may be
    a transaction."""
    if folder_id is None:
        return None
    if not _is_id(folder_id) or store.get(BUCKET_AIS_FOLDERS, folder_id) is None:
        raise BatchError("no such folder")
    return folder_id


def _parents(folders: list[Record]) -> dict[int, int | None]:
    return {f["id"]: f.get("parent_id") for f in folders}


def _depth(parents: dict[int, int | None], folder_id: int | None) -> int:
    """How many folders deep folder_id is (0 for the top)."""
    n = 0
    while folder_id is not None and n <= len(parents):
        folder_id, n = parents.get(folder_id), n + 1
    return n


def _height(parents: dict[int, int | None], folder_id: int) -> int:
    """How many folders deep folder_id goes, itself counting 1."""
    children = [f for f, p in parents.items() if p == folder_id]
    return 1 + max((_height(parents, c) for c in children), default=0)


def _folder_position(folder: Record) -> int:
    position = folder.get("position")
    return position if isinstance(position, int) else 0


def list_folders(store: Store) -> list[Record]:
    """Every folder, each parent's in their order."""
    folders = [f for _, f in store.all(BUCKET_AIS_FOLDERS)]
    return sorted(folders, key=lambda f: (f.get("parent_id") or 0, _folder_position(f), f["id"]))


def create_folder(store: Store, name: Any, parent_id: Any, user_id: int) -> Record:
    """A new folder, first in its parent (None: at the top)."""
    clean = clean_name(name)
    with store.transaction() as tx:
        parent_id = _folder_ref(tx, parent_id)
        folders = [f for _, f in tx.all(BUCKET_AIS_FOLDERS)]
        if len(folders) >= MAX_FOLDERS:
            raise BatchError(f"at most {MAX_FOLDERS} folders")
        if _depth(_parents(folders), parent_id) + 1 > MAX_FOLDER_DEPTH:
            raise BatchError(f"folders go at most {MAX_FOLDER_DEPTH} deep")
        siblings = [f for f in folders if f.get("parent_id") == parent_id]
        now = to_iso(utc_now())
        folder_id = tx.next_sequence(BUCKET_AIS_FOLDERS)
        record = {"id": folder_id, "name": clean, "parent_id": parent_id,
                  "position": min((_folder_position(f) for f in siblings), default=0) - 1,
                  "created_by": user_id, "created_at": now, "updated_at": now}
        tx.put(BUCKET_AIS_FOLDERS, folder_id, record)
    return record


def rename_folder(store: Store, folder_id: int, name: Any) -> Record | None:
    clean = clean_name(name)

    def mutate(record: Record) -> None:
        record["name"] = clean
        _stamp(record)

    return store.update_value(BUCKET_AIS_FOLDERS, folder_id, mutate)


def move_folder(store: Store, folder_id: int, parent_id: Any) -> Record | None:
    """Into another folder (None: the top), last there; not into itself or
    anything inside it. None when the folder is gone."""
    with store.transaction() as tx:
        folder = tx.get(BUCKET_AIS_FOLDERS, folder_id)
        if folder is None:
            return None
        parent_id = _folder_ref(tx, parent_id)
        folders = [f for _, f in tx.all(BUCKET_AIS_FOLDERS)]
        parents = _parents(folders)
        at = parent_id
        while at is not None:
            if at == folder_id:
                raise BatchError("a folder cannot go inside itself")
            at = parents.get(at)
        if _depth(parents, parent_id) + _height(parents, folder_id) > MAX_FOLDER_DEPTH:
            raise BatchError(f"folders go at most {MAX_FOLDER_DEPTH} deep")
        if folder.get("parent_id") != parent_id:
            siblings = [f for f in folders if f.get("parent_id") == parent_id]
            folder["parent_id"] = parent_id
            folder["position"] = max((_folder_position(f) for f in siblings), default=0) + 1
            _stamp(folder)
            tx.put(BUCKET_AIS_FOLDERS, folder_id, folder)
    return folder


def order_folders(store: Store, parent_id: Any, ids: Any) -> None:
    """The order of one folder's folders (None: the top's): ids first, then
    the rest as they were."""
    if not isinstance(ids, list) or len(ids) > MAX_FOLDERS or not all(_is_id(i) for i in ids):
        raise BatchError("ids must be a list of folder ids")
    if len(set(ids)) != len(ids):
        raise BatchError("ids must not repeat")
    with store.transaction() as tx:
        parent_id = _folder_ref(tx, parent_id)
        current = sorted((f for _, f in tx.all(BUCKET_AIS_FOLDERS) if f.get("parent_id") == parent_id),
                         key=lambda f: (_folder_position(f), f["id"]))
        rank = {folder_id: n for n, folder_id in enumerate(ids)}
        ordered = sorted(current, key=lambda f: (0, rank[f["id"]]) if f["id"] in rank else (1, 0))
        for position, folder in enumerate(ordered):
            if folder.get("position") != position:
                tx.put(BUCKET_AIS_FOLDERS, folder["id"], folder | {"position": position})


def delete_folder(store: Store, folder_id: int) -> Record | None:
    """The folder gone, its folders and batches moved up into its parent
    (after what is there). Returns the folder that was deleted, None when it
    was gone already."""
    with store.transaction() as tx:
        folder = tx.get(BUCKET_AIS_FOLDERS, folder_id)
        if folder is None:
            return None
        parent_id = folder.get("parent_id")
        folders = [f for _, f in tx.all(BUCKET_AIS_FOLDERS)]
        end = max((_folder_position(f) for f in folders if f.get("parent_id") == parent_id), default=0)
        children = sorted((f for f in folders if f.get("parent_id") == folder_id),
                          key=lambda f: (_folder_position(f), f["id"]))
        for n, child in enumerate(children, 1):
            tx.put(BUCKET_AIS_FOLDERS, child["id"], child | {"parent_id": parent_id, "position": end + n})
        for key, batch in tx.all(BUCKET_AIS_BATCHES):
            if batch.get("folder_id") == folder_id:
                tx.put(BUCKET_AIS_BATCHES, key, batch | {"folder_id": parent_id})
        tx.delete(BUCKET_AIS_FOLDERS, folder_id)
    return folder


def move_batches(store: Store, ids: Any, folder_id: Any) -> int:
    """Batches ids into folder_id (None: the top). Returns how many moved;
    ids no longer there are skipped."""
    if not isinstance(ids, list) or not ids or len(ids) > 10000 or not all(_is_id(i) for i in ids):
        raise BatchError("ids must be a list of batch ids")
    moved = 0
    with store.transaction() as tx:
        folder_id = _folder_ref(tx, folder_id)
        for batch_id in set(ids):
            batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
            if batch is None:
                continue
            moved += 1
            if batch.get("folder_id") != folder_id:
                tx.put(BUCKET_AIS_BATCHES, batch_id, batch | {"folder_id": folder_id})
    return moved


def _rows_by_image(store: Store) -> dict[int, dict[str, list[Record]]]:
    """Every accepted AIS, grouped by batch and then image."""
    out: dict[int, dict[str, list[Record]]] = {}
    for _, row in store.all(BUCKET_AIS_RESULTS):
        out.setdefault(row["batch_id"], {}).setdefault(row["image"], []).append(row)
    return out


def _complete(batch: Record, by_image: dict[str, Any]) -> set[str]:
    """Images with an accepted AIS or a done mark."""
    return (set(by_image) | set(batch["skipped"])) & {im["key"] for im in batch["images"]}


def _included_complete(batch: Record, by_image: dict[str, Any]) -> set[str]:
    return _complete(batch, by_image) & included_keys(batch)


def list_batches(store: Store, viewer_id: int | None = None,
                 has: Callable[[dict[str, Any]], bool] | None = None) -> list[Record]:
    """In the team's priority order (new batches on top), without the image
    lists, archived ones too (archived_at): name, counts and progress, per
    assignee too, and the viewer's own part (mine) when they have one. With
    has (can the server show this file?), stored counts the uploads."""
    rows = _rows_by_image(store)
    out = []
    for _, batch in store.all(BUCKET_AIS_BATCHES):
        by_image = rows.get(batch["id"], {})
        assignees = progress(batch, by_image)
        mine = next((a for a in assignees if a["user_id"] == viewer_id), None)
        files = [f for im in batch["images"] for f in real_files(im)]
        included = included_keys(batch)
        item = ({k: batch[k] for k in ("id", "name", "source", "path", "created_by", "created_at")}
                | {"updated_at": batch.get("updated_at", batch["created_at"]),
                   "archived_at": batch.get("archived_at"), "position": _position(batch),
                   "folder_id": batch.get("folder_id"),
                   "images": len(batch["images"]), "included": len(included),
                   "completed": len(_included_complete(batch, by_image)),
                   "adds": list(batch.get("adds", [])),
                   "earlier": sum(1 for im in batch["images"] if "add_id" not in im),
                   "randomized": any("original_cell" in im for im in batch["images"]),
                   "unnamed": unnamed(batch),
                   "duplicates": sum(1 for im in batch["images"] if "dup_of" in im),
                   "ais": sum(len(v) for v in by_image.values()),
                   "auto": sum(1 for v in by_image.values() for r in v if r.get("origin") == "auto"),
                   "files": len(files),
                   "assignees": assignees, "mine": mine}
                | treatment_counts(batch, included))
        if has is not None:
            item["stored"] = sum(1 for f in files if has(f))
        out.append(item)
    return sorted(out, key=lambda b: (b["position"], -b["id"]))


def image_status(batch: Record, rows: list[Record], has: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    """Per image, for the Batches screen's detail list: files on the server,
    accepted AIS, done mark, duplicate and assignee."""
    by_image: dict[str, list[Record]] = {}
    for row in rows:
        by_image.setdefault(row["image"], []).append(row)
    skipped = set(batch["skipped"])
    excluded = excluded_keys(batch)
    out = []
    for image in batch["images"]:
        files = real_files(image)
        accepted = by_image.get(image["key"], [])
        item = {"key": image["key"], "cell": image["cell"], "dir": image["dir"],
                "files": len(files), "stored": sum(1 for f in files if has(f)),
                "ais": len(accepted), "auto": sum(1 for r in accepted if r.get("origin") == "auto"),
                "done": image["key"] in skipped, "dup_of": image.get("dup_of"),
                "assignee": assignee_of(batch, image["key"]),
                "included": image["key"] not in excluded, "add_id": image.get("add_id")}
        if "original_key" in image:
            item["original_key"] = image["original_key"]
        out.append(item)
    return out


def set_done(store: Store, batch_id: int, key: str, done: bool) -> Record | None:
    """Mark (or unmark) an image done by hand -- shared progress."""
    def mutate(record: Record) -> None:
        if key not in {im["key"] for im in record["images"]}:
            raise BatchError("no such image in this batch")
        skipped = [k for k in record["skipped"] if k != key]
        if done:
            skipped.append(key)
        record["skipped"] = skipped
        _stamp(record)

    return store.update_value(BUCKET_AIS_BATCHES, batch_id, mutate)


RESET_SCOPES = ("all", "auto")


def reset_batch(store: Store, batch_id: int, scope: str) -> tuple[Record, int] | None:
    """An admin's fresh start on a batch, to run it again: scope "all" deletes
    every accepted AIS, recorded measurement and done mark, "auto" only the
    AIS auto mode saved (the rest renumbered 1..k per image) and the done
    marks of the images they were on. Images and the assignment stay. Returns
    (batch, AIS deleted)."""
    if scope not in RESET_SCOPES:
        raise BatchError("scope must be all or auto")
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if record is None:
            return None
        rows = [r for _, r in tx.all(BUCKET_AIS_RESULTS) if r["batch_id"] == batch_id]
        gone = [r for r in rows if scope == "all" or r.get("origin") == "auto"]
        for r in gone:
            tx.delete(BUCKET_AIS_RESULTS, r["id"])
        if scope == "all":
            record["skipped"] = []
            tx.delete_where(BUCKET_AIS_MEASUREMENTS, lambda _key, line: line["batch_id"] == batch_id)
        else:
            touched = {r["image"] for r in gone}
            record["skipped"] = [k for k in record["skipped"] if k not in touched]
            gone_ids = {r["id"] for r in gone}
            by_image: dict[str, list[Record]] = {}
            for r in rows:
                if r["id"] not in gone_ids:
                    by_image.setdefault(r["image"], []).append(r)
            for rest in by_image.values():
                for n, r in enumerate(sorted(rest, key=lambda r: (r["n"], r["id"])), 1):
                    if r["n"] != n:
                        tx.put(BUCKET_AIS_RESULTS, r["id"], r | {"n": n})
        _stamp(record)
        tx.put(BUCKET_AIS_BATCHES, batch_id, record)
    return record, len(gone)


def delete_batch(store: Store, batch_id: int) -> None:
    with store.transaction() as tx:
        tx.delete(BUCKET_AIS_BATCHES, batch_id)
        tx.delete_where(BUCKET_AIS_RESULTS, lambda _key, row: row["batch_id"] == batch_id)
        tx.delete_where(BUCKET_AIS_MEASUREMENTS, lambda _key, line: line["batch_id"] == batch_id)


# --- assignments ---------------------------------------------------------------


def split_counts(n: int, weights: list[float]) -> list[int]:
    """n split in proportion to weights, rounded by largest remainder so the
    parts sum to exactly n (ties go to the earlier one)."""
    total = sum(weights)
    if n <= 0 or total <= 0:
        return [0] * len(weights)
    exact = [n * w / total for w in weights]
    counts = [math.floor(x) for x in exact]
    by_remainder = sorted(range(len(weights)), key=lambda i: (-(exact[i] - counts[i]), i))
    for i in by_remainder[: n - sum(counts)]:
        counts[i] += 1
    return counts


def clean_shares(shares: Any) -> list[dict[str, Any]]:
    """[{user_id, percent}], each person once, percents scaled to sum 100."""
    if not isinstance(shares, list) or len(shares) > MAX_SHARES:
        raise BatchError(f"shares must be a list of up to {MAX_SHARES}")
    out, seen = [], set()
    for share in shares:
        if not isinstance(share, dict):
            raise BatchError("each share must be an object")
        user_id, percent = share.get("user_id"), share.get("percent")
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id in seen:
            raise BatchError("each share needs a different user_id")
        if (not isinstance(percent, (int, float)) or isinstance(percent, bool)
                or not math.isfinite(percent) or percent <= 0):
            raise BatchError("percent must be a number above 0")
        seen.add(user_id)
        out.append({"user_id": user_id, "percent": float(percent)})
    total = sum(s["percent"] for s in out)
    return [s | {"percent": round(100 * s["percent"] / total, 2)} for s in out]


def deal(batch: Record, shares: list[dict[str, Any]], complete: set[str]) -> dict[str, int]:
    """Image key -> user id for a new split. Finished images keep an assignee
    who is still in it; finished ones nobody (left) holds stay out of it. The
    unfinished are dealt in batch order, a contiguous run each, so that every
    share ends up as close to its percent as the finished ones allow."""
    ids = [s["user_id"] for s in shares]
    current = (batch.get("assignment") or {}).get("images", {})
    excluded = excluded_keys(batch)
    eligible = [im["key"] for im in batch["images"] if im["key"] not in excluded]
    kept = {k: current[k] for k in eligible if k in complete and current.get(k) in ids}
    unfinished = [k for k in eligible if k not in complete]
    targets = split_counts(len(kept) + len(unfinished), [s["percent"] for s in shares])
    held = [sum(1 for u in kept.values() if u == user_id) for user_id in ids]
    # Someone already past their share takes no more, so the rest is rescaled.
    counts = split_counts(len(unfinished), [max(0, t - h) for t, h in zip(targets, held)])
    out = dict(kept)
    it = iter(unfinished)
    for user_id, count in zip(ids, counts):
        for _ in range(count):
            out[next(it)] = user_id
    return out


def assign(store: Store, batch_id: int, shares: Any, user_id: int) -> Record | None:
    """Split the batch among people by share; an empty list clears the
    assignment. None when the batch is gone."""
    clean = clean_shares(shares)
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            return None
        if clean:
            by_image: dict[str, Any] = {}
            for _, row in tx.all(BUCKET_AIS_RESULTS):
                if row["batch_id"] == batch_id:
                    by_image[row["image"]] = True
            batch["assignment"] = {"shares": clean, "images": deal(batch, clean, _complete(batch, by_image)),
                                   "by": user_id, "at": to_iso(utc_now())}
        else:
            batch.pop("assignment", None)
        _stamp(batch)
        tx.put(BUCKET_AIS_BATCHES, batch_id, batch)
    return batch


def assignee_of(batch: Record, key: str) -> int | None:
    return (batch.get("assignment") or {}).get("images", {}).get(key)


def progress(batch: Record, by_image: dict[str, list[Record]]) -> list[dict[str, Any]]:
    """Per share: images assigned, how many are complete, AIS accepted on them
    (by anyone), and when one was last accepted or edited."""
    assignment = batch.get("assignment")
    if not assignment:
        return []
    complete = _complete(batch, by_image)
    included = included_keys(batch)
    out = []
    for share in assignment["shares"]:
        keys = [k for k, u in assignment["images"].items() if u == share["user_id"] and k in included]
        rows = [r for k in keys for r in by_image.get(k, [])]
        stamps = [t for r in rows for t in (r["accepted_at"], r.get("edited_at")) if t]
        out.append({"user_id": share["user_id"], "percent": share["percent"], "images": len(keys),
                    "completed": sum(1 for k in keys if k in complete), "ais": len(rows),
                    "last_at": max(stamps, default=None)})
    return out


def local_path_for(store: Store, sha: str) -> str | None:
    """Where an Open-path batch found the file with this sha, if any."""
    for _, batch in store.all(BUCKET_AIS_BATCHES):
        if batch["source"] not in ("path", "mixed"):
            continue
        for image in batch["images"]:
            for f in real_files(image):
                if f["sha"] == sha and f.get("path"):
                    return f["path"]
    return None


def stack_for(store: Store, sha: str) -> dict[str, Any] | None:
    """The manifest of the Z-stack with this sha, from the batch record that
    holds it, for Library to keep a copy of."""
    for _, batch in store.all(BUCKET_AIS_BATCHES):
        for image in batch["images"]:
            f = image["files"].get("stack")
            if f and f["sha"] == sha:
                return zstack.manifest(f["slices"], image["z_stack"])
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
    return out | _clean_z(row, len(pixels)) | _clean_auto(row)


def _clean_auto(row: dict[str, Any]) -> dict[str, Any]:
    """A row's auto mode settings, only those it has: nothing on a click."""
    out: dict[str, Any] = {}
    for k in AUTO_TEXTS:
        v = row.get(k)
        if v is not None and v != "":
            out[k] = _text(v, k)
    for k in AUTO_NUMBERS:
        v = row.get(k)
        if v is not None:
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise BatchError(f"{k} must be a number")
            out[k] = v
    return out


def _clean_z(row: dict[str, Any], pixels: int) -> dict[str, Any]:
    """A row's Z-stack measures, only those it has: nothing on a row measured
    on an ordinary image. z_path is the z of each of pixels, None outside the
    AIS, so a length can be worked out again if the z step was wrong."""
    out: dict[str, Any] = {}
    for k in Z_NUMBERS:
        v = row.get(k)
        if v is not None:
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise BatchError(f"{k} must be a number")
            out[k] = v
    if row.get("z_method"):
        out["z_method"] = _text(row["z_method"], "z_method")
    path = row.get("z_path")
    if path is not None:
        if (not isinstance(path, list) or len(path) != pixels
                or not all(z is None or (isinstance(z, (int, float)) and not isinstance(z, bool) and math.isfinite(z))
                           for z in path)):
            raise BatchError("z_path must give a z for each pixel")
        out["z_path"] = path
    return out


class RevConflict(Exception):
    """An edit based on a revision someone else has since moved past. current
    is the record as it is now, for the caller to show."""

    def __init__(self, current: Record) -> None:
        super().__init__("someone else changed this since you last saw it")
        self.current = current


_CLIENT_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


def clean_client_id(value: Any) -> str | None:
    """The browser's own name for a row it created (a UUID), so a create sent
    again after a dropped connection finds the first one instead of adding a
    second. None when not given."""
    if value is None:
        return None
    if not isinstance(value, str) or not _CLIENT_ID.fullmatch(value):
        raise BatchError("client_id must be a short id")
    return value


def _check_rev(record: Record, expect: int | None) -> None:
    """expect is the rev the caller last saw; None skips the check."""
    if expect is not None and record.get("rev", 0) != expect:
        raise RevConflict(record)


def _kept_sync(record: Any) -> dict[str, Any]:
    """A backed-up row's client_id and rev, when it has them, so it comes back
    as it was."""
    out: dict[str, Any] = {}
    if record.get("client_id") is not None:
        out["client_id"] = clean_client_id(record["client_id"])
    if record.get("rev") is not None:
        out["rev"] = _whole(record["rev"], "rev")
    return out


def add_result(store: Store, batch_id: int, image_key: str, row: Any, user_id: int,
               client_id: Any = None) -> Record:
    clean = clean_row(row)
    client_id = clean_client_id(client_id)
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            raise BatchError("no such batch")
        image = next((im for im in batch["images"] if im["key"] == image_key), None)
        if image is None:
            raise BatchError("no such image in this batch")
        rows = [r for _, r in tx.all(BUCKET_AIS_RESULTS) if r["batch_id"] == batch_id and r["image"] == image_key]
        if client_id is not None:
            sent = next((r for r in rows if r.get("client_id") == client_id), None)
            if sent is not None:
                return sent
        same = [r["n"] for r in rows]
        result_id = tx.next_sequence(BUCKET_AIS_RESULTS)
        record = clean | ({"client_id": client_id} if client_id else {}) | {
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


def update_result(store: Store, result_id: int, row: Any, user_id: int, expect: int | None = None) -> Record | None:
    """Replace an accepted AIS's measures and trace (an edit), keeping which
    image it is on, its number, origin and who accepted it. None when it is
    gone; RevConflict when expect is not its rev."""
    clean = clean_row(row)
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_RESULTS, result_id)
        if record is None:
            return None
        _check_rev(record, expect)
        kept = {k: record[k] for k in ("id", "batch_id", "batch_name", "image", "cell", "n", "created_by", "accepted_at")}
        if "client_id" in record:
            kept["client_id"] = record["client_id"]
        # How auto mode found it stays with it: the edit is a new trace, not a new find.
        clean = {k: v for k, v in clean.items() if k not in AUTO_TEXTS + AUTO_NUMBERS}
        kept |= {k: record[k] for k in AUTO_TEXTS + AUTO_NUMBERS if k in record}
        record = clean | kept | {"origin": record.get("origin", ""), "edited_at": to_iso(utc_now()), "edited_by": user_id,
                                 "rev": record.get("rev", 0) + 1}
        tx.put(BUCKET_AIS_RESULTS, result_id, record)
    return record


def set_soma(store: Store, result_id: int, soma: Any, user_id: int, expect: int | None = None) -> Record | None:
    """Set an accepted AIS's distance to its soma ({soma_um, ...} with every
    SOMA_NUMBERS field a number), or clear it (None), leaving its trace alone.
    None when it is gone. An edit (update_result) drops it: the start may move."""
    if soma is None:
        values: dict[str, Any] = dict.fromkeys(SOMA_NUMBERS)
    elif isinstance(soma, dict):
        values = {}
        for k in SOMA_NUMBERS:
            v = soma.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v != v or v < 0:
                raise BatchError(f"{k} must be a number")
            values[k] = v
    else:
        raise BatchError("soma must be an object or null")
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_RESULTS, result_id)
        if record is None:
            return None
        _check_rev(record, expect)
        record = record | values | {"soma_at": to_iso(utc_now()) if soma is not None else None,
                                    "soma_by": user_id if soma is not None else None,
                                    "rev": record.get("rev", 0) + 1}
        tx.put(BUCKET_AIS_RESULTS, result_id, record)
    return record


def delete_result(store: Store, result_id: int, expect: int | None = None) -> list[dict[str, int]]:
    """Delete one, and renumber the rest of its image 1..k in their order.
    Returns the new numbers, [{id, n}], of the rows that changed."""
    changed = []
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_RESULTS, result_id)
        if record is None:
            return []
        _check_rev(record, expect)
        tx.delete(BUCKET_AIS_RESULTS, result_id)
        rest = sorted((r for _, r in tx.all(BUCKET_AIS_RESULTS)
                       if r["batch_id"] == record["batch_id"] and r["image"] == record["image"]),
                      key=lambda r: (r["n"], r["id"]))
        for n, r in enumerate(rest, 1):
            if r["n"] != n:
                tx.put(BUCKET_AIS_RESULTS, r["id"], r | {"n": n})
                changed.append({"id": r["id"], "n": n})
    return changed


# --- recorded measurements -----------------------------------------------------


def clean_measurement(line: Any) -> dict[str, Any]:
    """What a client sends for a recorded line: every MEASUREMENT_NUMBERS field
    a number, and an optional label and type."""
    if not isinstance(line, dict):
        raise BatchError("measurement must be an object")
    out: dict[str, Any] = {}
    for k in MEASUREMENT_NUMBERS:
        v = line.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0:
            raise BatchError(f"{k} must be a number")
        out[k] = v
    out["label"] = _text(line.get("label", ""), "label", empty=True)
    out["type"] = clean_type(line.get("type", ""), empty=True)
    return out


def clean_type(value: Any, empty: bool = False) -> str:
    """A measurement type ("Soma distance", ...): short text, trimmed."""
    if not isinstance(value, str) or len(value.strip()) > MAX_TYPE or (not empty and not value.strip()):
        raise BatchError("type must be text")
    return value.strip()


def measure_types(store: Store) -> list[str]:
    """The team's list of measurement types for the Measure tool's picker:
    what an admin saved, or DEFAULT_TYPES until then."""
    saved = store.get(BUCKET_META, MEASURE_TYPES_KEY)
    return list(saved["types"]) if saved else list(DEFAULT_TYPES)


def set_measure_types(store: Store, types: Any) -> list[str]:
    """Save the team's list: 1..MAX_TYPES distinct names, in the order given.
    Lines already tagged with a type taken off the list keep it."""
    if not isinstance(types, list) or not 1 <= len(types) <= MAX_TYPES:
        raise BatchError(f"types must be a list of 1 to {MAX_TYPES}")
    out: list[str] = []
    for t in types:
        t = clean_type(t)
        if t.casefold() not in {o.casefold() for o in out}:
            out.append(t)
    store.put(BUCKET_META, MEASURE_TYPES_KEY, {"types": out})
    return out


def add_measurement(store: Store, batch_id: int, image_key: str, line: Any, user_id: int,
                    client_id: Any = None) -> Record:
    """A recorded line on an image, numbered after the image's others. It has
    no bearing on the image's AIS or whether the image counts as done. The
    same client_id again returns the line already made."""
    clean = clean_measurement(line)
    client_id = clean_client_id(client_id)
    with store.transaction() as tx:
        batch = tx.get(BUCKET_AIS_BATCHES, batch_id)
        if batch is None:
            raise BatchError("no such batch")
        if not any(im["key"] == image_key for im in batch["images"]):
            raise BatchError("no such image in this batch")
        lines = [m for _, m in tx.all(BUCKET_AIS_MEASUREMENTS) if m["batch_id"] == batch_id and m["image"] == image_key]
        if client_id is not None:
            sent = next((m for m in lines if m.get("client_id") == client_id), None)
            if sent is not None:
                return sent
        same = [m["n"] for m in lines]
        line_id = tx.next_sequence(BUCKET_AIS_MEASUREMENTS)
        record = clean | ({"client_id": client_id} if client_id else {}) | {
            "id": line_id,
            "batch_id": batch_id,
            "batch_name": batch["name"],
            "image": image_key,
            "n": max(same, default=0) + 1,
            "created_by": user_id,
            "created_at": to_iso(utc_now()),
        }
        tx.put(BUCKET_AIS_MEASUREMENTS, line_id, record)
    return record


def list_measurements(store: Store, batch_id: int | None = None) -> list[Record]:
    """Oldest first, like the order they were recorded in."""
    return [line for _, line in store.all(BUCKET_AIS_MEASUREMENTS) if batch_id is None or line["batch_id"] == batch_id]


def get_measurement(store: Store, line_id: int) -> Record | None:
    return store.get(BUCKET_AIS_MEASUREMENTS, line_id)


def update_measurement(store: Store, line_id: int, line: Any, user_id: int, expect: int | None = None) -> Record | None:
    """New ends, length or label for a recorded line, keeping which image it
    is on, its number and who recorded it. None when it is gone."""
    clean = clean_measurement(line)
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_MEASUREMENTS, line_id)
        if record is None:
            return None
        _check_rev(record, expect)
        record = record | clean | {"edited_at": to_iso(utc_now()), "edited_by": user_id, "rev": record.get("rev", 0) + 1}
        tx.put(BUCKET_AIS_MEASUREMENTS, line_id, record)
    return record


def delete_measurement(store: Store, line_id: int, expect: int | None = None) -> list[dict[str, int]]:
    """Delete one, and renumber the rest of its image 1..k in their order.
    Returns the new numbers, [{id, n}], of the lines that changed."""
    changed = []
    with store.transaction() as tx:
        record = tx.get(BUCKET_AIS_MEASUREMENTS, line_id)
        if record is None:
            return []
        _check_rev(record, expect)
        tx.delete(BUCKET_AIS_MEASUREMENTS, line_id)
        rest = sorted((m for _, m in tx.all(BUCKET_AIS_MEASUREMENTS)
                       if m["batch_id"] == record["batch_id"] and m["image"] == record["image"]),
                      key=lambda m: (m["n"], m["id"]))
        for n, m in enumerate(rest, 1):
            if m["n"] != n:
                tx.put(BUCKET_AIS_MEASUREMENTS, m["id"], m | {"n": n})
                changed.append({"id": m["id"], "n": n})
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


# --- backups -------------------------------------------------------------------


def backup_batch(store: Store, batch_id: int) -> Record | None:
    """Everything needed to rebuild a batch elsewhere: its record and results
    as they are, without where its files live on this machine (a path means
    nothing on another server, and has the original name in it) or its
    assignment (who works on what is this server's). None when it is gone."""
    batch = get_batch(store, batch_id)
    if batch is None:
        return None
    def pathless(f: dict[str, Any]) -> dict[str, Any]:
        return {k: [pathless(s) for s in v] if k == "slices" else v for k, v in f.items() if k != "path"}

    images = [im | {"files": {role: pathless(f) for role, f in im["files"].items()}} for im in batch["images"]]
    kept = {k: v for k, v in batch.items() if k != "assignment"}
    return {"batch": kept | {"path": None, "images": images, "excluded": sorted(excluded_keys(batch)),
                             "adds": [{k: v for k, v in a.items() if k != "original_path"} | {"path": None}
                                      for a in batch.get("adds", [])]},
            "results": list_results(store, batch_id),
            "measurements": list_measurements(store, batch_id)}


def backup_user_ids(backup: Record) -> set[int]:
    """Who a backup names, so it carries those people's names and no others."""
    batch = backup["batch"]
    ids = {batch.get("created_by")} | {a.get("added_by") for a in batch["adds"]}
    for row in backup["results"]:
        ids |= {row.get("created_by"), row.get("edited_by"), row.get("soma_by")}
    for line in backup.get("measurements", []):
        ids |= {line.get("created_by"), line.get("edited_by")}
    return {i for i in ids if i is not None}


def _whole(value: Any, label: str, least: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < least:
        raise BatchError(f"{label} must be a whole number")
    return value


def _date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_DATE:
        raise BatchError(f"{label} must be a date")
    return value


def _inside(rel: str) -> str:
    """A rel from a backup: relative, and staying inside its folder."""
    parts = rel.replace("\\", "/").split("/")
    if not parts[0] or ".." in parts:
        raise BatchError("rel must stay inside the batch")
    return rel


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_FILES:
        raise BatchError(f"{label} must be a list")
    return [_text(v, label) for v in value]


def _restored_file(f: Any) -> dict[str, Any]:
    if not isinstance(f, dict):
        raise BatchError("each file must be an object")
    out = clean_files([{k: v for k, v in f.items() if k != "path"}])[0]
    _inside(out["rel"])
    original = f.get("original")
    if original is not None:
        if not isinstance(original, dict):
            raise BatchError("original must be an object")
        out["original"] = {"name": _text(original.get("name"), "name"),
                           "rel": _inside(_text(original.get("rel"), "rel"))}
    if f.get("earlier") is not None:
        out["earlier"] = _strings(f["earlier"], "earlier")
    return out


def _restored_stack(f: Any, options: dict[str, Any]) -> dict[str, Any]:
    """A stack's file, its slices checked and its sha worked out again, since
    a manifest is only as good as the record it comes from."""
    out = _restored_file(f)
    slices = f.get("slices")
    if not isinstance(slices, list) or not zstack.MIN_SLICES <= len(slices) <= MAX_FILES:
        raise BatchError("a stack needs its slices")
    restored = [_restored_file(s) | {"z": _whole(s.get("z"), "z")} for s in slices]
    if len({s["z"] for s in restored}) != len(restored):
        raise BatchError("two slices share a z")
    if zstack.sha(zstack.manifest(restored, options)) != out["sha"]:
        raise BatchError("a stack does not match its slices")
    return out | {"slices": restored}


def _restored_image(image: Any, count: int) -> dict[str, Any]:
    if not isinstance(image, dict) or not isinstance(image.get("files"), dict) or not image["files"]:
        raise BatchError("each image needs its files")
    if not set(image["files"]) <= set(ROLES):
        raise BatchError("unknown file role")
    options = _stack_options(image.get("z_stack")) if "stack" in image["files"] else None
    if "stack" in image["files"] and options is None:
        raise BatchError("a stack needs its plane and calibration")
    out: dict[str, Any] = {"key": _text(image.get("key"), "key"), "cell": _text(image.get("cell"), "cell"),
                           "dir": _text(image.get("dir", ""), "dir", empty=True),
                           "files": {role: _restored_stack(f, options) if role == "stack" else _restored_file(f)
                                     for role, f in image["files"].items()}}
    if options:
        out["z_stack"] = {"count": len(out["files"]["stack"]["slices"])} | options
    if image.get("original_dir") is not None:
        out["original_dir"] = _text(image["original_dir"], "original_dir", empty=True)
    if image.get("dup_of") is not None:
        out["dup_of"] = _whole(image["dup_of"], "dup_of")
        if out["dup_of"] >= count:
            raise BatchError("dup_of must be an image of this batch")
    if image.get("add_id") is not None:
        out["add_id"] = _whole(image["add_id"], "add_id")
    for k in ("original_cell", "original_key", "treatment"):
        if image.get(k) is not None:
            out[k] = _text(image[k], k)
    if image.get("earlier_keys") is not None:
        out["earlier_keys"] = _strings(image["earlier_keys"], "earlier_keys")
    return out


def _user_map(exported: Any, local: dict[int, str]) -> dict[int, int]:
    """A backup's user ids -> this server's: the same id under the same name
    (a restore here), else the one person with that name. Whoever matches
    nobody falls to the person importing."""
    if not isinstance(exported, dict):
        raise BatchError("users must be an object")
    out: dict[int, int] = {}
    for key, name in exported.items():
        if not isinstance(key, str) or not key.isdecimal():
            raise BatchError("users must be keyed by id")
        same = [i for i, n in local.items() if n == name]
        if int(key) in same:
            out[int(key)] = int(key)
        elif len(same) == 1:
            out[int(key)] = same[0]
    return out


def import_batch(store: Store, data: Any, local_users: dict[int, str], user_id: int) -> Record:
    """A backup (backup_batch, with format, version and users) as a new batch
    at the top of the list, whatever it was called or whether it is still
    here: importing never touches an existing batch. Its images are written
    as they were, not regrouped, so keys, blinded names and which results
    belong to which image survive. Nothing in it can point at this machine:
    paths are dropped and the batch counts as uploaded. It is all checked
    first and written at once, so a bad backup leaves nothing behind."""
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise BatchError("this is not a batch backup")
    if data.get("version") != BACKUP_VERSION:
        raise BatchError("this backup is from a different version of the app")
    batch, rows = data.get("batch"), data.get("results")
    if not isinstance(batch, dict) or not isinstance(rows, list):
        raise BatchError("the backup needs its batch and results")
    images = batch.get("images")
    if not isinstance(images, list) or len(images) > MAX_FILES:
        raise BatchError(f"images must be a list of up to {MAX_FILES}")
    people = _user_map(data.get("users", {}), local_users)

    def person(value: Any) -> int:
        return people.get(value, user_id)

    restored = [_restored_image(im, len(images)) for im in images]
    keys = {im["key"] for im in restored}
    if len(keys) != len(restored):
        raise BatchError("two images share a key")
    excluded = _strings(batch.get("excluded", []), "excluded")
    skipped = _strings(batch.get("skipped", []), "skipped")
    if not set(excluded) | set(skipped) <= keys:
        raise BatchError("excluded and skipped must be images of this batch")
    adds = batch.get("adds", [])
    if not isinstance(adds, list) or len(adds) > MAX_FILES:
        raise BatchError("adds must be a list")
    clean_adds = []
    for a in adds:
        if not isinstance(a, dict):
            raise BatchError("each add must be an object")
        clean_adds.append({"id": _whole(a.get("id"), "add id"), "name": _text(a.get("name"), "add name"),
                           "source": "upload", "path": None, "added_at": _date(a.get("added_at"), "added_at"),
                           "added_by": person(a.get("added_by")), "randomized": bool(a.get("randomized")),
                           "count": _whole(a.get("count", 0), "count")})
        if a.get("original_name") is not None:
            clean_adds[-1] |= {"original_name": _text(a["original_name"], "add name"), "original_path": None}
    if {im["add_id"] for im in restored if "add_id" in im} - {a["id"] for a in clean_adds}:
        raise BatchError("an image names an add the batch does not have")

    clean_rows, numbered = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise BatchError("a result must be an object")
        image = row.get("image")
        if image not in keys:
            raise BatchError("a result names an image the batch does not have")
        n = _whole(row.get("n"), "n", least=1)
        if (image, n) in numbered:
            raise BatchError("two results of an image share a number")
        numbered.add((image, n))
        record = clean_row(row) | {"image": image, "n": n, "created_by": person(row.get("created_by")),
                                   "accepted_at": _date(row.get("accepted_at"), "accepted_at")}
        for at, by in (("edited_at", "edited_by"), ("soma_at", "soma_by")):
            if row.get(at) is not None:
                record |= {at: _date(row[at], at), by: person(row.get(by))}
        record |= _kept_sync(row)
        clean_rows.append(record)

    # Backups from before measurements were recorded have none.
    lines = data.get("measurements", [])
    if not isinstance(lines, list):
        raise BatchError("measurements must be a list")
    clean_lines, numbered = [], set()
    for line in lines:
        if not isinstance(line, dict):
            raise BatchError("a measurement must be an object")
        image = line.get("image")
        if image not in keys:
            raise BatchError("a measurement names an image the batch does not have")
        n = _whole(line.get("n"), "n", least=1)
        if (image, n) in numbered:
            raise BatchError("two measurements of an image share a number")
        numbered.add((image, n))
        record = clean_measurement(line) | {"image": image, "n": n, "created_by": person(line.get("created_by")),
                                            "created_at": _date(line.get("created_at"), "created_at")}
        if line.get("edited_at") is not None:
            record |= {"edited_at": _date(line["edited_at"], "edited_at"), "edited_by": person(line.get("edited_by"))}
        record |= _kept_sync(line)
        clean_lines.append(record)

    name = clean_name(batch.get("name"))
    created_at = _date(batch.get("created_at"), "created_at")
    cells = {im["key"]: im["cell"] for im in restored}
    now = to_iso(utc_now())
    with store.transaction() as tx:
        existing = [b for _, b in tx.all(BUCKET_AIS_BATCHES)]
        if any(b["name"] == name for b in existing):
            name = name[:200 - len(IMPORTED_SUFFIX)] + IMPORTED_SUFFIX
        batch_id = tx.next_sequence(BUCKET_AIS_BATCHES)
        record = {
            "id": batch_id,
            "name": name,
            "source": "upload",
            "path": None,
            "created_by": person(batch.get("created_by")),
            "created_at": created_at,
            "updated_at": now,
            "position": min((_position(b) for b in existing), default=0) - 1,
            "archived_at": None,
            "skipped": skipped,
            "images": restored,
            "adds": clean_adds,
            "excluded": excluded,
        }
        tx.put(BUCKET_AIS_BATCHES, batch_id, record)
        for row in clean_rows:
            result_id = tx.next_sequence(BUCKET_AIS_RESULTS)
            tx.put(BUCKET_AIS_RESULTS, result_id, row | {"id": result_id, "batch_id": batch_id, "batch_name": name,
                                                         "cell": cells[row["image"]]})
        for line in clean_lines:
            line_id = tx.next_sequence(BUCKET_AIS_MEASUREMENTS)
            tx.put(BUCKET_AIS_MEASUREMENTS, line_id, line | {"id": line_id, "batch_id": batch_id, "batch_name": name})
    return record


# --- live activity -------------------------------------------------------------


class Activity:
    """What people are running on each batch right now (auto mode's progress,
    which lives in their browser), as they last reported it. Kept in memory
    only: a report older than ttl seconds has stopped, so it drops out."""

    KINDS = ("auto",)
    STATES = ("running", "paused", "finished", "stopped")

    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] | None = None) -> None:
        self._ttl = ttl
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._reports: dict[tuple[int, int, str], dict[str, Any]] = {}

    def report(self, batch_id: int, user_id: int, body: dict[str, Any]) -> dict[str, Any]:
        kind, state, done, total = body.get("kind"), body.get("state"), body.get("done"), body.get("total")
        if kind not in self.KINDS or state not in self.STATES:
            raise BatchError("kind or state is not known")
        if (not all(isinstance(n, int) and not isinstance(n, bool) for n in (done, total))
                or not 0 <= done <= total <= MAX_FILES):
            raise BatchError("done and total must be counts")
        item = {"user_id": user_id, "kind": kind, "state": state, "done": done, "total": total,
                "at": to_iso(utc_now())}
        with self._lock:
            self._reports[(batch_id, user_id, kind)] = item | {"_t": self._clock()}
        return item

    def current(self) -> dict[int, list[dict[str, Any]]]:
        """batch id -> live reports."""
        now = self._clock()
        out: dict[int, list[dict[str, Any]]] = {}
        with self._lock:
            for key, item in list(self._reports.items()):
                if now - item["_t"] > self._ttl:
                    del self._reports[key]
                    continue
                out.setdefault(key[0], []).append({k: v for k, v in item.items() if k != "_t"})
        return out
