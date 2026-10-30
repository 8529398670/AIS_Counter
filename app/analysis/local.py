"""Folders on this machine's disk, for the Original screen's "Open path".

A browser never learns where a picked file lives, so an uploaded folder cannot
be shown in Finder or copied as a path. When the server runs on the same
machine (loopback, outside the container: Config.local_folders_enabled) it can
read the folder itself, which gives exact paths, Finder reveal and opening a
TIFF in its default app. Only TIFFs are ever read, opened or revealed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.analysis.images import ImageError

TIFF_SUFFIXES = (".tif", ".tiff")
CHOOSE_TIMEOUT_SECONDS = 600


def platform() -> str:
    if sys.platform == "darwin":
        return "mac"
    return "windows" if sys.platform.startswith("win") else "linux"


def _absolute(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ImageError("path must be a string")
    path = Path(os.path.expanduser(raw.strip()))
    if not path.is_absolute():
        raise ImageError("path must be absolute")
    return path.resolve()


def folder(raw: Any) -> Path:
    path = _absolute(raw)
    if not path.is_dir():
        raise ImageError("not a folder")
    return path


def tiff(raw: Any) -> Path:
    path = _absolute(raw)
    if path.suffix.lower() not in TIFF_SUFFIXES or not path.is_file():
        raise ImageError("not a TIFF file")
    return path


def listing(raw: Any) -> dict[str, Any]:
    """The folder's subfolders and TIFFs, hidden entries skipped."""
    path = folder(raw)
    dirs: list[str] = []
    files: list[dict[str, Any]] = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except OSError as exc:
        raise ImageError(f"cannot read folder: {exc.strerror}") from None
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                dirs.append(entry.name)
            elif entry.is_file() and entry.name.lower().endswith(TIFF_SUFFIXES):
                files.append({"name": entry.name, "size": entry.stat().st_size})
        except OSError:
            continue
    parent = str(path.parent) if path.parent != path else None
    return {"path": str(path), "parent": parent, "dirs": dirs, "files": files}


def read(raw: Any) -> bytes:
    return tiff(raw).read_bytes()


def hashed_files(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    """The folder's TIFFs with the sha-256 of each, for an Open-path batch:
    (folder, [{name, rel, sha, size, path}])."""
    found = listing(raw)
    base = Path(found["path"])
    files = []
    for f in found["files"]:
        path = base / f["name"]
        try:
            data = path.read_bytes()
        except OSError:
            continue
        files.append({"name": f["name"], "rel": f["name"], "sha": hashlib.sha256(data).hexdigest(),
                      "size": len(data), "path": str(path)})
    return found["path"], files


def reveal(raw: Any) -> None:
    """Show the file selected in Finder / Explorer (its folder on Linux)."""
    path = str(tiff(raw))
    kind = platform()
    if kind == "mac":
        subprocess.run(["open", "-R", path], check=False, timeout=10)
    elif kind == "windows":
        subprocess.run(["explorer", f"/select,{path}"], check=False, timeout=10)
    else:
        subprocess.run(["xdg-open", str(Path(path).parent)], check=False, timeout=10)


def open_file(raw: Any) -> None:
    """Open the TIFF in its default app (ImageJ, Preview, ...)."""
    path = str(tiff(raw))
    kind = platform()
    if kind == "mac":
        subprocess.run(["open", path], check=False, timeout=10)
    elif kind == "windows":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", path], check=False, timeout=10)


def choose() -> str | None:
    """macOS only: the native folder chooser. None when cancelled."""
    if platform() != "mac":
        raise ImageError("the folder chooser is only available on macOS")
    try:
        done = subprocess.run(["osascript", "-e", "POSIX path of (choose folder)"],
                              capture_output=True, text=True, timeout=CHOOSE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None
    path = done.stdout.strip()
    return path or None
