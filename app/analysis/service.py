"""What the routes call: store uploaded TIFFs, and turn one click into the
original's trace and measures as JSON.

Files are content-addressed under <storage>/ais/files/<sha256>.tif, one store
shared by every user: batches are shared (app/models/ais.py), so anyone who
can open a batch can see its images, and a sha is only ever learnt from a
batch. Re-uploading the same image is free. A file that is not there yet is
looked for in the per-user folders older versions used, then at the path an
Open-path batch recorded for it (`resolver`), and copied in. The
click-independent part of the pipeline (mat2gray and the Gaussian smoothing)
is cached in memory for the last few images, which makes every click after
the first on an image take a fraction of a second.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.analysis import ais_auto as aa
from app.analysis import mlcompat as ml
from app.analysis.images import ImageError, preview_png, read_tiff, thumbnail_png

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CACHE_SIZE = 6
SINGLE_NOTE = "single image: traced and profiled from the same file (the original profiles the raw <cell>.tif)"


class Library:
    def __init__(self, storage_dir: Path, resolver: Callable[[str], str | None] | None = None) -> None:
        self.root = storage_dir / "ais"
        self.files = self.root / "files"
        # sha -> a path on this machine holding those bytes (Open-path batches).
        self.resolver = resolver
        self._lock = threading.Lock()
        self._prepared: OrderedDict[str, aa.PreparedImage] = OrderedDict()
        self._arrays: OrderedDict[str, np.ndarray] = OrderedDict()

    def _path(self, sha: str) -> Path:
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise ImageError("unknown image")
        return self.files / f"{sha}.tif"

    def _store(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)

    def add(self, data: bytes) -> dict[str, Any]:
        arr = read_tiff(data)
        sha = hashlib.sha256(data).hexdigest()
        path = self._path(sha)
        if not path.exists():
            self._store(path, data)
        return {"sha256": sha, "width": int(arr.shape[1]), "height": int(arr.shape[0]), "dtype": str(arr.dtype)}

    def has(self, sha: str) -> bool:
        return self._path(sha).exists()

    def file_path(self, sha: str) -> Path:
        """The stored TIFF, fetched in if it is known elsewhere (see the
        module docstring); ImageError when it is nowhere."""
        path = self._path(sha)
        if path.exists():
            return path
        for legacy in self.root.glob(f"[0-9]*/{sha}.tif"):
            path.parent.mkdir(parents=True, exist_ok=True)
            legacy.replace(path)
            return path
        source = self.resolver(sha) if self.resolver else None
        if source:
            try:
                data = Path(source).read_bytes()
            except OSError:
                data = b""
            # Only if the file there still has the same bytes.
            if data and hashlib.sha256(data).hexdigest() == sha:
                self._store(path, data)
                return path
        raise ImageError("image not uploaded yet")

    def array(self, sha: str) -> np.ndarray:
        with self._lock:
            if sha in self._arrays:
                self._arrays.move_to_end(sha)
                return self._arrays[sha]
        arr = read_tiff(self.file_path(sha).read_bytes())
        with self._lock:
            self._arrays[sha] = arr
            while len(self._arrays) > CACHE_SIZE * 2:
                self._arrays.popitem(last=False)
        return arr

    def prepared(self, sha: str) -> aa.PreparedImage:
        with self._lock:
            if sha in self._prepared:
                self._prepared.move_to_end(sha)
                return self._prepared[sha]
        prep = aa.PreparedImage.from_array(self.array(sha))
        with self._lock:
            self._prepared[sha] = prep
            while len(self._prepared) > CACHE_SIZE:
                self._prepared.popitem(last=False)
        return prep

    def preview(self, sha: str) -> bytes:
        return preview_png(self.array(sha))

    def thumbnail(self, sha: str) -> bytes:
        return thumbnail_png(self.array(sha))

    def trace(self, processed: str, raw: str | None,
              click: tuple[float, float], click2: tuple[float, float] | None,
              threshold: float) -> dict[str, Any]:
        prep = self.prepared(processed)
        if not raw:
            # Only one file for this cell: profile the image that was traced.
            out = run_click(prep, prep.pic, click, click2, threshold)
            out.setdefault("notes", []).insert(0, SINGLE_NOTE)
            return out
        raw_arr = self.array(raw)
        if raw_arr.shape[:2] != prep.pic.shape:
            raise ImageError("raw and processed images differ in size")
        return run_click(prep, raw_arr, click, click2, threshold)


def _xy(points) -> list[list[int]]:
    """1-based (row, col) pairs -> [x, y] (column, row) for the client."""
    return [[int(c), int(r)] for r, c in points]


def run_click(prep: aa.PreparedImage, raw: np.ndarray | None,
              click: tuple[float, float], click2: tuple[float, float] | None,
              threshold: float) -> dict[str, Any]:
    """The JSON for one click. Coordinates in and out are MATLAB axes
    coordinates: x = column, y = row, pixel centres at 1..n."""
    out: dict[str, Any] = {"ok": False, "stage": "trace", "error": None}
    try:
        tr = aa.trace(prep, click, click2, threshold)
    except ml.MatlabError as exc:
        out["error"] = str(exc)
        return out
    sel = tr.selected
    edge = sel & ~ml.imerode_square3(sel)
    rows, cols = np.nonzero(sel)
    out.update({
        "threshold_initial": tr.threshold_initial,
        "threshold": tr.threshold,
        "rethresholded": tr.rethresholded,
        "clicks": [list(c) for c in tr.clicks],
        "component": {
            "pixels": int(sel.sum()),
            "bbox": [int(cols.min()) + 1, int(rows.min()) + 1, int(cols.max()) + 1, int(rows.max()) + 1],
            "edge": _xy(np.argwhere(edge) + 1),
        },
        "skeleton": _xy(np.argwhere(tr.skeleton) + 1),
        "start": [tr.start[1], tr.start[0]],
        "passes": len(tr.passes),
        "path": _xy(tr.path),
    })
    if raw is None:
        out.update({"stage": "measure", "error": "no raw image: the original reads the profile from <cell>.tif"})
        return out
    out["stage"] = "measure"
    try:
        ms = aa.measure(tr.path, raw)
    except ml.MatlabError as exc:
        out["error"] = str(exc)
        return out
    out.update({
        "ok": True,
        "stage": "done",
        "spline": np.round(ms.xysm.T, 3).tolist(),
        "pixels": [[int(x), int(y)] for x, y in zip(ms.x_pix, ms.y_pix)],
        "profile": {"lv_ss": ms.lv_ss.tolist(), "norm_lv": ms.norm_lv.tolist(), "max_i": ms.max_i,
                    "ais_start": ms.ais_start, "ais_end": ms.ais_end, "f": aa.F, "pixconv": aa.PIXCONV},
        "measures": {"start_um": ms.debut, "end_um": ms.fin, "mid_um": ms.mid, "max_um": ms.maxi,
                     "length_um": ms.lngth, "length_str": ms.lngth_str, "arc_um": ms.arc_um},
        "notes": ms.notes,
    })
    return out
