"""What the routes call: store uploaded TIFFs, and turn one click into the
original's trace and measures as JSON.

Files are content-addressed per user under <storage>/ais/<user id>/<sha256>.tif,
so re-uploading the same image is free and one user cannot open another's by
guessing a hash. The click-independent part of the pipeline (mat2gray and the
Gaussian smoothing) is cached in memory for the last few images, which makes
every click after the first on an image take a fraction of a second.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from app.analysis import ais_auto as aa
from app.analysis import mlcompat as ml
from app.analysis.images import ImageError, preview_png, read_tiff

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CACHE_SIZE = 6


class Library:
    def __init__(self, storage_dir: Path) -> None:
        self.root = storage_dir / "ais"
        self._lock = threading.Lock()
        self._prepared: OrderedDict[tuple[int, str], aa.PreparedImage] = OrderedDict()
        self._arrays: OrderedDict[tuple[int, str], np.ndarray] = OrderedDict()

    def _path(self, user_id: int, sha: str) -> Path:
        if not SHA_RE.match(sha):
            raise ImageError("unknown image")
        return self.root / str(int(user_id)) / f"{sha}.tif"

    def add(self, user_id: int, data: bytes) -> dict[str, Any]:
        arr = read_tiff(data)
        sha = hashlib.sha256(data).hexdigest()
        path = self._path(user_id, sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        return {"sha256": sha, "width": int(arr.shape[1]), "height": int(arr.shape[0]), "dtype": str(arr.dtype)}

    def array(self, user_id: int, sha: str) -> np.ndarray:
        key = (user_id, sha)
        with self._lock:
            if key in self._arrays:
                self._arrays.move_to_end(key)
                return self._arrays[key]
        path = self._path(user_id, sha)
        if not path.exists():
            raise ImageError("unknown image")
        arr = read_tiff(path.read_bytes())
        with self._lock:
            self._arrays[key] = arr
            while len(self._arrays) > CACHE_SIZE * 2:
                self._arrays.popitem(last=False)
        return arr

    def prepared(self, user_id: int, sha: str) -> aa.PreparedImage:
        key = (user_id, sha)
        with self._lock:
            if key in self._prepared:
                self._prepared.move_to_end(key)
                return self._prepared[key]
        prep = aa.PreparedImage.from_array(self.array(user_id, sha))
        with self._lock:
            self._prepared[key] = prep
            while len(self._prepared) > CACHE_SIZE:
                self._prepared.popitem(last=False)
        return prep

    def preview(self, user_id: int, sha: str) -> bytes:
        return preview_png(self.array(user_id, sha))

    def trace(self, user_id: int, processed: str, raw: str | None,
              click: tuple[float, float], click2: tuple[float, float] | None,
              threshold: float) -> dict[str, Any]:
        prep = self.prepared(user_id, processed)
        raw_arr = self.array(user_id, raw) if raw else None
        if raw_arr is not None and raw_arr.shape != prep.pic.shape:
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
