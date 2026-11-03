"""Folders on this machine's disk, for the Process screen's "Open path".

A browser never learns where a picked file lives, so an uploaded folder cannot
be shown in Finder or copied as a path. When the server runs on the same
machine (loopback, outside the container: Config.local_folders_enabled) it can
read the folder itself, which gives exact paths, Finder reveal and opening a
TIFF (or .czi) in its default app. Only those are ever read, opened or revealed.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.analysis.images import ImageError

TIFF_SUFFIXES = (".tif", ".tiff", ".czi")   # the images: TIFFs and CZI mode's .czi
CHOOSE_TIMEOUT_SECONDS = 600
MAX_FILES = 5000                            # as many as a batch takes (app/models/ais.py)


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
        raise ImageError("not a TIFF or .czi file")
    return path


def listing(raw: Any) -> dict[str, Any]:
    """The folder's subfolders and images, hidden entries skipped."""
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


def images_under(base: Path, limit: int = MAX_FILES) -> list[Path]:
    """Every image in the folder and its subfolders, hidden entries skipped,
    sorted, at most limit of them."""
    found: list[Path] = []
    for root, dirs, names in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names, key=str.lower):
            if not name.startswith(".") and name.lower().endswith(TIFF_SUFFIXES):
                found.append(Path(root) / name)
                if len(found) >= limit:
                    return found
    return found


def _dates(path: Path) -> dict[str, str]:
    """When the file was last changed and, where the system keeps it
    (macOS, Windows), made: ISO text in UTC."""
    try:
        st = path.stat()
    except OSError:
        return {}
    def iso(t: float) -> str:
        return datetime.fromtimestamp(t, timezone.utc).isoformat()

    out = {"modified": iso(st.st_mtime)}
    born = getattr(st, "st_birthtime", None)
    if born is None and os.name == "nt":
        born = st.st_ctime
    if born:
        out["created"] = iso(born)
    return out


def hashed_files(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    """The folder's images, subfolders too, with the sha-256 of each, for an
    Open-path batch: (folder, [{name, rel, sha, size, path}]). rel starts with
    the folder's own name, as a browser's folder pick does, so subfolders
    group the same way (app/models/ais.group)."""
    base = folder(raw)
    files = []
    for path in images_under(base):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        rel = "/".join((base.name or str(base), *path.relative_to(base).parts))
        item = {"name": path.name, "rel": rel, "sha": hashlib.sha256(data).hexdigest(),
                "size": len(data), "path": str(path)}
        item.update(_dates(path))
        files.append(item)
    return str(base), files


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
