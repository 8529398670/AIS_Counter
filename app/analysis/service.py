"""What the routes call: store uploaded TIFFs and CZIs, and turn one click
into the original's trace and measures as JSON.

Files are content-addressed under <storage>/ais/files/<sha256>.tif (or .czi),
one store
shared by every user: batches are shared (app/models/ais.py), so anyone who
can open a batch can see its images, and a sha is only ever learnt from a
batch. Re-uploading the same image is free. A file that is not there yet is
looked for in the per-user folders older versions used, then at the path an
Open-path batch recorded for it (`resolver`), and copied in. The
click-independent part of the pipeline (mat2gray and the smoothing) is cached
in memory for the last few images and smoothing settings, which makes every
click after the first on an image take a fraction of a second.

A .czi is one whole cell (CZI mode): its AIS channel (Czi.ais_name, usually
"Alexa Fluor 488") is the raw image (the same pixels as the exported
<cell>_ORG.tif), traced on a processed version of it (preprocess.py, a port
of the "Processed method 2.5" Fiji macro) and profiled from the raw, like a
TIFF pair; its soma channel (Czi.soma_name, usually "AMCA") gives the somata
auto mode starts from (soma.py), if it has one.

A Z-stack (zstack.py) is many stored slices under one sha that isn't a file. It
behaves like a .czi with no soma channel: the max projection of its AIS plane is
the raw image, traced on a processed version of it, and each trace is then
followed through the slices (zlength.py). Its manifest comes from the batch that
holds it (`stacks`); the copy kept beside the files is only a cache.

A view (channels.py) is a stored file read with other channels than the app
would pick: its AIS channel is the image, its soma channel (if any) gives the
somata. Its sha isn't a file either; it is found the same way as a stack's,
and stands for its file wherever the file itself is wanted (file_path).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import mmap
import os
import re
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy import ndimage as ndi

from app.analysis import ais_auto as aa
from app.analysis import detect as auto
from app.analysis import fast
from app.analysis import mlcompat as ml
from app.analysis import pairing
from app.analysis import preprocess
from app.analysis import soma as somata
from app.analysis import channels as views
from app.analysis import zlength, zstack
from app.analysis.czi import is_czi, read_channels, read_czi
from app.analysis.images import (ImageError, composite_png, preview_png, read_planes, read_tiff, scaled_png,
                                 thumbnail_png, tiff_bytes, tiff_names)

class NotStored(ImageError):
    """The server does not have the file (yet), as opposed to having one it
    cannot read."""


SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CACHE_SIZE = 6
STACK_CACHE_SIZE = 2    # a whole stack each: the container has 256 MB
CHANNEL_PERCENTILES = (0.1, 99.9)
SINGLE_NOTE = "single image: traced and profiled from the same file (the original profiles the raw <cell>.tif)"
UNLIFTED_NOTE = "could not follow this trace through the slices: no 3D length"


class Library:
    def __init__(self, storage_dir: Path, resolver: Callable[[str], str | None] | None = None,
                 stacks: Callable[[str], dict[str, Any] | None] | None = None) -> None:
        self.root = storage_dir / "ais"
        self.files = self.root / "files"
        # sha -> a path on this machine holding those bytes (Open-path batches).
        self.resolver = resolver
        # sha -> a Z-stack's or a view's manifest, from the batch that holds it.
        self.stacks = stacks
        self._manifests: dict[str, dict[str, Any]] = {}
        self._stacks: OrderedDict[str, np.ndarray] = OrderedDict()
        self._levels: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        self._prepared: OrderedDict[tuple, aa.PreparedImage] = OrderedDict()
        self._arrays: OrderedDict[str, np.ndarray] = OrderedDict()
        self._bright: dict[str, float] = {}
        self._somata: OrderedDict[str, somata.Somata | None] = OrderedDict()
        self._previews: OrderedDict[str, bytes] = OrderedDict()
        self._channels: dict[str, list[dict[str, Any]]] = {}

    def _path(self, sha: str, czi: bool = False) -> Path:
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise ImageError("unknown image")
        return self.files / f"{sha}.{'czi' if czi else 'tif'}"

    def _store(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # A temp of its own: requests for an image not stored yet (its view,
        # channels and thumbnail) all fetch it in at once, and with a shared
        # temp one would rewrite the file another had just put in place.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.stem}.", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def add(self, data: bytes) -> dict[str, Any]:
        czi = is_czi(data)
        arr = _read(data)
        sha = hashlib.sha256(data).hexdigest()
        path = self._path(sha, czi)
        if not path.exists():
            self._store(path, data)
        return {"sha256": sha, "width": int(arr.shape[1]), "height": int(arr.shape[0]), "dtype": str(arr.dtype),
                "czi": czi}

    def has(self, sha: str) -> bool:
        return self._path(sha).exists() or self._path(sha, czi=True).exists()

    def is_czi(self, sha: str) -> bool:
        return not self.is_stack(sha) and self.file_path(sha).suffix == ".czi"

    def is_stack(self, sha: str) -> bool:
        return self._manifest(sha) is not None

    def _preprocessed(self, sha: str) -> bool:
        """Whether its traced image is made here, by preprocess.py."""
        return self.is_stack(sha) or self.is_czi(sha)

    def _virtual(self, sha: str) -> dict[str, Any] | None:
        """A Z-stack's or a view's manifest; None for a file. Kept beside the
        files as a cache, and always checked against its sha."""
        with self._lock:
            if sha in self._manifests:
                return self._manifests[sha]
        # Before anything else, so a stored image never costs a look through
        # the batches.
        if self._path(sha).exists() or self._path(sha, czi=True).exists():
            return None
        found = None
        for suffix in (zstack.SUFFIX, views.SUFFIX):
            try:
                found = json.loads((self.files / f"{sha}{suffix}").read_bytes())
            except (OSError, ValueError):
                continue
            if isinstance(found, dict) and zstack.sha(found) == sha:
                break
            found = None
        if found is None:
            found = self.stacks(sha) if self.stacks else None
            if not isinstance(found, dict) or zstack.sha(found) != sha:
                return None
            suffix = views.SUFFIX if views.is_view(found) else zstack.SUFFIX
            self._store(self.files / f"{sha}{suffix}", zstack.canonical(found))
        with self._lock:
            self._manifests[sha] = found
        return found

    def _manifest(self, sha: str) -> dict[str, Any] | None:
        """A Z-stack's manifest; None for anything else."""
        found = self._virtual(sha)
        return found if found is not None and found.get("format") == zstack.FORMAT else None

    def _view(self, sha: str) -> dict[str, Any] | None:
        """A view's manifest (channels.py); None for anything else."""
        found = self._virtual(sha)
        return found if views.is_view(found) else None

    def layout(self, sha: str) -> dict[str, Any]:
        """A stored file's channels as channels.py lays them out: {kind, names}."""
        if self.is_czi(sha):
            return {"kind": "czi", "names": [c["name"] for c in self.channels(sha)]}
        with self.file_path(sha).open("rb") as file:
            return {"kind": "tiff", "names": tiff_names(file)}

    def require(self, sha: str) -> None:
        """NotStored unless the file, or every slice of a Z-stack, is here."""
        manifest = self._manifest(sha)
        for part in manifest["slices"] if manifest else [{"sha": sha}]:
            self.file_path(part["sha"])

    def stack(self, sha: str) -> np.ndarray:
        """A Z-stack's AIS plane as (slices, height, width). What a stack is
        made from is decided here alone, so a .czi's own Z planes can come in
        later without the rest changing."""
        with self._lock:
            if sha in self._stacks:
                self._stacks.move_to_end(sha)
                return self._stacks[sha]
        manifest = self._manifest(sha)
        if manifest is None:
            raise ImageError("not a Z-stack")
        planes = []
        for part in manifest["slices"]:
            arr = read_planes(self.file_path(part["sha"]).read_bytes())
            if arr.shape[2] > 1 and manifest["plane"] >= arr.shape[2]:
                raise ImageError("a slice has no such channel")
            planes.append(arr[:, :, 0 if arr.shape[2] == 1 else manifest["plane"]])
        if len({(p.shape, p.dtype) for p in planes}) != 1:
            raise ImageError("the slices of a stack differ in size")
        stack = np.stack(planes)
        with self._lock:
            self._stacks[sha] = stack
            while len(self._stacks) > STACK_CACHE_SIZE:
                self._stacks.popitem(last=False)
        return stack

    def slice_png(self, sha: str, index: int) -> bytes:
        """One slice of a Z-stack, on the scale of the whole stack."""
        stack = self.stack(sha)
        if not 0 <= index < len(stack):
            raise ImageError("no such slice")
        lo, hi = np.percentile(self.array(sha), CHANNEL_PERCENTILES)
        return scaled_png(stack[index], float(lo), float(hi))

    def _calibrated(self, sha: str, settings: aa.Settings) -> aa.Settings:
        """settings with a Z-stack's own pixel size, which beats any in Settings."""
        manifest = self._manifest(sha)
        return settings if manifest is None else dataclasses.replace(settings, pixconv=manifest["pixel_um"])

    def _lifted(self, sha: str, answer: dict[str, Any], z_method: str | None) -> dict[str, Any]:
        """answer (run_click's) with, on a Z-stack, its 3D measures as z: None
        and a note when the trace can't be followed. The click still counts."""
        manifest = self._manifest(sha)
        if manifest is None or not answer.get("ok"):
            return answer
        chosen = zlength.method(z_method)
        stack = self.stack(sha)
        with self._lock:
            levels = self._levels.get(sha)
        if levels is None:
            levels = zlength.slice_levels(stack)
            with self._lock:
                self._levels[sha] = levels
        try:
            found = chosen.run(stack, levels, [s["z"] for s in manifest["slices"]], answer,
                               manifest["pixel_um"], manifest["z_step_um"])
        except (ValueError, IndexError, ArithmeticError, ml.MatlabError):
            found = None
        answer["z"] = None if found is None else found | {"z_method": chosen.id}
        if found is None:
            answer.setdefault("notes", []).append(UNLIFTED_NOTE)
        return answer

    def file_path(self, sha: str) -> Path:
        """The stored file, fetched in if it is known elsewhere (see the
        module docstring); ImageError when it is nowhere. A view's is its
        file's."""
        for czi in (False, True):
            path = self._path(sha, czi)
            if path.exists():
                return path
        view = self._view(sha)
        if view is not None:
            return self.file_path(view["source"])
        for czi in (False, True):
            path = self._path(sha, czi)
            if path.exists():
                return path
        path = self._path(sha)
        for legacy in self.root.glob(f"[0-9]*/{sha}.tif"):
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                legacy.replace(path)
            except FileNotFoundError:
                # Another request moved it in first.
                if not path.exists():
                    raise
            return path
        source = self.resolver(sha) if self.resolver else None
        if source:
            try:
                data = Path(source).read_bytes()
            except OSError:
                data = b""
            # Only if the file there still has the same bytes.
            if data and hashlib.sha256(data).hexdigest() == sha:
                path = self._path(sha, is_czi(data))
                self._store(path, data)
                return path
        raise NotStored("image not uploaded yet")

    def array(self, sha: str) -> np.ndarray:
        """The image itself: a TIFF's first page, a CZI's AIS channel."""
        with self._lock:
            if sha in self._arrays:
                self._arrays.move_to_end(sha)
                return self._arrays[sha]
        view = self._view(sha)
        if self.is_stack(sha):
            arr = self.stack(sha).max(axis=0)
        else:
            arr = _read(self.file_path(sha).read_bytes(), view["ais"] if view else None)
        with self._lock:
            self._arrays[sha] = arr
            while len(self._arrays) > CACHE_SIZE * 2:
                self._arrays.popitem(last=False)
        return arr

    def prepared(self, sha: str, settings: aa.Settings = aa.DEFAULT) -> aa.PreparedImage:
        """The traced image, prepared: a CZI's processed version of its AIS
        channel, else the file as it is."""
        key = (sha, settings.smooth, settings.kernel, settings.sigma)
        with self._lock:
            if key in self._prepared:
                self._prepared.move_to_end(key)
                return self._prepared[key]
        arr = self.array(sha)
        prep = aa.PreparedImage.from_array(preprocess.processed(arr) if self._preprocessed(sha) else arr, settings)
        with self._lock:
            self._prepared[key] = prep
            while len(self._prepared) > CACHE_SIZE:
                self._prepared.popitem(last=False)
        return prep

    def soma(self, sha: str) -> somata.Somata | None:
        """A CZI's somata (soma.py), kept per image, from its soma channel: the
        one a view names, else Czi.soma_name. A TIFF has some only through a
        view that names a soma plane. None when there is no soma channel."""
        view = self._view(sha)
        if not self.is_czi(sha) and (view is None or view["soma"] is None):
            return None
        with self._lock:
            if sha in self._somata:
                self._somata.move_to_end(sha)
                return self._somata[sha]
        data = self.file_path(sha).read_bytes()
        if is_czi(data):
            image = read_czi(data)
            names = list(image.channels)
            index = view["soma"] if view else views.soma_index(names)
            if index is not None and not 0 <= index < len(names):
                raise ImageError("the .czi file has no such channel")
            plane, pixel_um = (None if index is None else image.channels[names[index]]), image.pixel_um
        else:
            planes = read_planes(data)
            if view["soma"] >= planes.shape[2]:
                raise ImageError("the TIFF has no such channel")
            plane, pixel_um = planes[:, :, view["soma"]], None
        found = somata.find(plane, pixel_um or aa.DEFAULT.pixconv) if plane is not None else None
        with self._lock:
            self._somata[sha] = found
            while len(self._somata) > CACHE_SIZE:
                self._somata.popitem(last=False)
        return found

    def pair(self, sha: str, traces: list[list[list[int]]], pixel_um: float, split: bool = True,
             shape: pairing.SomaShape | None = None,
             sections: list[tuple[int, int] | None] | None = None) -> dict[str, Any]:
        """The Measure tool's guesses for the traces on the image and its
        soma ellipses (pairing.pair_image): each trace's start end (the
        thicker) and the soma in front of it, from the image's AIS plane and
        its somata, if it has a soma channel; split: one soma per hotspot;
        shape: the soma size and roundness allowed; sections: each trace's
        measured AIS (pairing.pair_image)."""
        smooth = pairing.smoothed(self.array(sha))
        found = self.soma(sha)
        return pairing.pair_image(smooth, found.bodies(split) if found else None, traces, pixel_um, shape, sections)

    def bright_ref(self, sha: str) -> float:
        """The image's bright level (see bright_level), kept per image."""
        with self._lock:
            if sha in self._bright:
                return self._bright[sha]
        level = bright_level(self.array(sha))
        with self._lock:
            self._bright[sha] = level
        return level

    def preview(self, sha: str) -> bytes:
        """The traced image: a CZI's processed AIS channel, else the file.
        Kept for the last few images: an export asks for every one of them,
        and a CZI's is a whole preprocess run."""
        with self._lock:
            if sha in self._previews:
                self._previews.move_to_end(sha)
                return self._previews[sha]
        arr = self.array(sha)
        png = preview_png(preprocess.processed(arr) if self._preprocessed(sha) else arr)
        with self._lock:
            self._previews[sha] = png
            while len(self._previews) > CACHE_SIZE * 4:
                self._previews.popitem(last=False)
        return png

    def channels(self, sha: str) -> list[dict[str, Any]]:
        """A CZI's channels, [{index, name, color}], for the channel buttons
        and the Export dialog; [] for a TIFF. Kept: a sha's bytes never change,
        and the dialog asks for every file of a batch."""
        with self._lock:
            if sha in self._channels:
                return self._channels[sha]
        if not self.is_czi(sha):
            return []
        with self.file_path(sha).open("rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            found = read_channels(data)
        out = [{"index": i, "name": name, "color": color} for i, (name, color) in enumerate(found.items())]
        with self._lock:
            self._channels[sha] = out
        return out

    def channel_png(self, sha: str, index: int) -> bytes:
        """One CZI channel, greyscale between its 0.1th and 99.9th percentile."""
        if not self.is_czi(sha):
            raise ImageError("only a .czi has channels")
        planes = list(read_czi(self.file_path(sha).read_bytes()).channels.values())
        if not 0 <= index < len(planes):
            raise ImageError("no such channel")
        return preview_png(planes[index], CHANNEL_PERCENTILES)

    def composite_png(self, sha: str) -> bytes:
        """A CZI's channels merged in their display colors, its PNG for an
        export; a Z-stack's projection, as it holds one plane."""
        if self.is_stack(sha):
            return preview_png(self.array(sha), CHANNEL_PERCENTILES)
        if not self.is_czi(sha):
            raise ImageError("only a .czi has channels")
        image = read_czi(self.file_path(sha).read_bytes())
        return composite_png(list(image.channels.values()), [image.colors[n] for n in image.channels], CHANNEL_PERCENTILES)

    def channel_tiff(self, sha: str, index: int) -> bytes:
        """One CZI channel's data as it is (16-bit), as a TIFF."""
        if not self.is_czi(sha):
            raise ImageError("only a .czi has channels")
        planes = list(read_czi(self.file_path(sha).read_bytes()).channels.values())
        if not 0 <= index < len(planes):
            raise ImageError("no such channel")
        return tiff_bytes(planes[index])

    def processed_tiff(self, sha: str) -> bytes:
        """A CZI's or Z-stack's processed AIS channel (what is traced) as a TIFF."""
        if not self._preprocessed(sha):
            raise ImageError("only a .czi is processed here")
        return tiff_bytes(preprocess.processed(self.array(sha)))

    def matlab_pair(self, processed: str, raw: str | None) -> tuple[bytes, bytes | None]:
        """The TIFFs ais_auto.m reads for this cell (app/analysis/matlab.py):
        the files themselves, or for a CZI the pair trace() uses -- its
        processed AIS channel and the AIS channel as ZEN exports it."""
        if not raw and self._preprocessed(processed):
            arr = self.array(processed)
            return tiff_bytes(preprocess.processed(arr)), tiff_bytes(arr)
        return self._tiff_of(processed), self._tiff_of(raw) if raw else None

    def _tiff_of(self, sha: str) -> bytes:
        """The TIFF ais_auto.m reads for sha: the file, or a view's AIS plane
        alone (it reads plane 1)."""
        return tiff_bytes(self.array(sha)) if self._view(sha) else self.file_path(sha).read_bytes()

    def thumbnail(self, sha: str) -> bytes:
        return thumbnail_png(self.array(sha))

    def trace(self, processed: str, raw: str | None,
              click: tuple[float, float], click2: tuple[float, float] | None,
              threshold: float, settings: aa.Settings = aa.DEFAULT, z_method: str | None = None) -> dict[str, Any]:
        settings = self._calibrated(processed, settings)
        prep = self.prepared(processed, settings)
        if not raw and self._preprocessed(processed):
            return self._lifted(processed, run_click(prep, self.array(processed), click, click2, threshold, settings,
                                                     bright_ref=self.bright_ref(processed)), z_method)
        if not raw:
            # Only one file for this cell: profile the image that was traced.
            out = run_click(prep, prep.pic, click, click2, threshold, settings, bright_ref=self.bright_ref(processed))
            out.setdefault("notes", []).insert(0, SINGLE_NOTE)
            return out
        raw_arr = self.array(raw)
        if raw_arr.shape[:2] != prep.pic.shape:
            raise ImageError("raw and processed images differ in size")
        return run_click(prep, raw_arr, click, click2, threshold, settings, bright_ref=self.bright_ref(raw))

    def detect(self, processed: str, raw: str | None, threshold: float,
               settings: aa.Settings = aa.DEFAULT, start: str = "both",
               exclude: list[list[list[int]]] | None = None, z_method: str | None = None) -> dict[str, Any]:
        """Auto mode: every AIS on the image (app/analysis/detect.py). On a
        CZI, with the somata it found (start "soma" needs them)."""
        settings = self._calibrated(processed, settings)
        prep = self.prepared(processed, settings)
        if not raw and self.is_stack(processed) and start != "soma":
            out = auto.detect(prep, self.array(processed), threshold, settings, start, exclude)
            out["candidates"] = [self._lifted(processed, c, z_method) for c in out["candidates"]]
            return out
        if not raw and self.is_czi(processed):
            soma = self.soma(processed)
            if start == "soma" and soma is None:
                raise ImageError("start \"soma\" needs a soma channel (AMCA, DAPI or Hoechst), and this .czi has none")
            return auto.detect(prep, self.array(processed), threshold, settings, start, exclude, soma=soma)
        # A TIFF has somata only through a view naming its soma plane.
        soma = self.soma(raw or processed)
        if start == "soma" and soma is None:
            raise ImageError("start \"soma\" needs a .czi image (its AMCA channel) or a soma channel chosen")
        if not raw:
            out = auto.detect(prep, prep.pic, threshold, settings, start, exclude, soma=soma)
            for candidate in out["candidates"]:
                candidate.setdefault("notes", []).insert(0, SINGLE_NOTE)
            return out
        raw_arr = self.array(raw)
        if raw_arr.shape[:2] != prep.pic.shape:
            raise ImageError("raw and processed images differ in size")
        return auto.detect(prep, raw_arr, threshold, settings, start, exclude, soma=soma)

    def trace_fast(self, processed: str, raw: str | None,
                   click: tuple[float, float], click2: tuple[float, float] | None,
                   threshold: float, settings: aa.Settings = aa.DEFAULT, z_method: str | None = None) -> dict[str, Any]:
        """trace on Settings' Method "ais_auto.m (fast)" (fast.py): the same
        answer, from crops."""
        settings = self._calibrated(processed, settings)
        prep = self.prepared(processed, settings)
        if not raw and self._preprocessed(processed):
            return self._lifted(processed, fast.run_click(prep, self.array(processed), click, click2, threshold, settings,
                                                          bright_ref=self.bright_ref(processed)), z_method)
        if not raw:
            out = fast.run_click(prep, prep.pic, click, click2, threshold, settings, bright_ref=self.bright_ref(processed))
            out.setdefault("notes", []).insert(0, SINGLE_NOTE)
            return out
        raw_arr = self.array(raw)
        if raw_arr.shape[:2] != prep.pic.shape:
            raise ImageError("raw and processed images differ in size")
        return fast.run_click(prep, raw_arr, click, click2, threshold, settings, bright_ref=self.bright_ref(raw))

    def detect_fast(self, processed: str, raw: str | None, threshold: float,
                    settings: aa.Settings = aa.DEFAULT, start: str = "both",
                    exclude: list[list[list[int]]] | None = None, z_method: str | None = None) -> dict[str, Any]:
        """detect on Settings' Method "ais_auto.m (fast)" (fast.py)."""
        settings = self._calibrated(processed, settings)
        prep = self.prepared(processed, settings)
        if not raw and self.is_stack(processed) and start != "soma":
            out = fast.detect(prep, self.array(processed), threshold, settings, start, exclude)
            out["candidates"] = [self._lifted(processed, c, z_method) for c in out["candidates"]]
            return out
        if not raw and self.is_czi(processed):
            soma = self.soma(processed)
            if start == "soma" and soma is None:
                raise ImageError("start \"soma\" needs a soma channel (AMCA, DAPI or Hoechst), and this .czi has none")
            return fast.detect(prep, self.array(processed), threshold, settings, start, exclude, soma=soma)
        # A TIFF has somata only through a view naming its soma plane.
        soma = self.soma(raw or processed)
        if start == "soma" and soma is None:
            raise ImageError("start \"soma\" needs a .czi image (its AMCA channel) or a soma channel chosen")
        if not raw:
            out = fast.detect(prep, prep.pic, threshold, settings, start, exclude, soma=soma)
            for candidate in out["candidates"]:
                candidate.setdefault("notes", []).insert(0, SINGLE_NOTE)
            return out
        raw_arr = self.array(raw)
        if raw_arr.shape[:2] != prep.pic.shape:
            raise ImageError("raw and processed images differ in size")
        return fast.detect(prep, raw_arr, threshold, settings, start, exclude, soma=soma)


def _read(data: bytes, plane: int | None = None) -> np.ndarray:
    """The image a file holds: a TIFF's first page, a CZI's AIS channel as
    ZEN exports it to TIFF. With plane (a view's AIS channel), that channel
    of the CZI or plane of the TIFF instead."""
    if is_czi(data):
        image = read_czi(data)
        names = list(image.channels)
        if plane is not None and not 0 <= plane < len(names):
            raise ImageError("the .czi file has no such channel")
        return np.ascontiguousarray(image.as_tiff(image.ais_name if plane is None else names[plane]))
    if plane is None:
        return read_tiff(data)
    planes = read_planes(data)
    if plane >= planes.shape[2]:
        raise ImageError("the TIFF has no such channel")
    return np.ascontiguousarray(planes[:, :, plane])


def bright_level(raw: np.ndarray) -> float:
    """What a trace's brightness is a fraction of: the profile image's 99.9th
    percentile, a bright AIS rather than one hot pixel."""
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    return float(np.percentile(raw, 99.9)) or 1.0


def shape(sel: np.ndarray, raw: np.ndarray, pixels: list[list[int]], ais_start: float, ais_end: float,
          pixconv: float, bright_ref: float) -> dict[str, float]:
    """How wide and bright the measured AIS (profile points ais_start..ais_end)
    is, which auto mode filters specks by. width_um: the median of twice the
    distance to the blob's edge (from the 3x3 around each point, as the spline
    can run beside the blob); brightness: the mean raw intensity there over
    bright_ref."""
    n = len(pixels)
    a, b = max(int(ais_start), 1), min(int(ais_end), n)
    section = np.array(pixels[a - 1:b] if b - a >= 1 else pixels)
    rows, cols = np.flatnonzero(sel.any(axis=1)), np.flatnonzero(sel.any(axis=0))
    r0, c0 = rows[0], cols[0]
    crop = np.pad(sel[r0:rows[-1] + 1, c0:cols[-1] + 1], 1)
    near = ndi.maximum_filter(ndi.distance_transform_edt(crop), size=3)
    r = np.clip(section[:, 1] - 1 - r0 + 1, 0, crop.shape[0] - 1)
    c = np.clip(section[:, 0] - 1 - c0 + 1, 0, crop.shape[1] - 1)
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    level = raw[section[:, 1] - 1, section[:, 0] - 1].astype(np.float64).mean()
    return {"width_um": float(np.median(2 * near[r, c]) * pixconv), "brightness": float(level / bright_ref)}


def _xy(points) -> list[list[int]]:
    """1-based (row, col) pairs -> [x, y] (column, row) for the client."""
    return [[int(c), int(r)] for r, c in points]


def run_click(prep: aa.PreparedImage, raw: np.ndarray | None,
              click: tuple[float, float], click2: tuple[float, float] | None,
              threshold: float, settings: aa.Settings = aa.DEFAULT,
              cache: dict | None = None, outline: bool = True, bright_ref: float | None = None) -> dict[str, Any]:
    """The JSON for one click. Coordinates in and out are MATLAB axes
    coordinates: x = column, y = row, pixel centres at 1..n. cache: see
    ais_auto.trace. outline=False leaves out the component's edge and the
    skeleton, which auto mode does not draw. bright_ref: raw's bright_level,
    when the caller already has it."""
    out: dict[str, Any] = {"ok": False, "stage": "trace", "error": None,
                           "settings": settings.to_dict(), "settings_changed": settings.changed()}
    try:
        tr = aa.trace(prep, click, click2, threshold, settings, cache)
    except ml.MatlabError as exc:
        out["error"] = str(exc)
        return out
    sel = tr.selected
    rows, cols = np.nonzero(sel)
    out.update({
        "threshold_initial": tr.threshold_initial,
        "threshold": tr.threshold,
        "rethresholded": tr.rethresholded,
        "clicks": [list(c) for c in tr.clicks],
        "component": {
            "pixels": int(rows.size),
            "bbox": [int(cols.min()) + 1, int(rows.min()) + 1, int(cols.max()) + 1, int(rows.max()) + 1],
        },
        "start": [tr.start[1], tr.start[0]],
        "passes": len(tr.passes),
        "path": _xy(tr.path),
    })
    if outline:
        out["component"]["edge"] = _xy(np.argwhere(sel & ~ml.imerode_square3(sel)) + 1)
        out["skeleton"] = _xy(np.argwhere(tr.skeleton) + 1)
    if raw is None:
        out.update({"stage": "measure", "error": "no raw image: the original reads the profile from <cell>.tif"})
        return out
    out["stage"] = "measure"
    try:
        ms = aa.measure(tr.path, raw, settings)
    except ml.MatlabError as exc:
        out["error"] = str(exc)
        return out
    out.update({
        "ok": True,
        "stage": "done",
        "spline": np.round(ms.xysm.T, 3).tolist(),
        "pixels": [[int(x), int(y)] for x, y in zip(ms.x_pix, ms.y_pix)],
        "profile": {"lv_ss": ms.lv_ss.tolist(), "norm_lv": ms.norm_lv.tolist(), "max_i": ms.max_i,
                    "ais_start": ms.ais_start, "ais_end": ms.ais_end, "f": settings.f, "pixconv": settings.pixconv},
        "measures": {"start_um": ms.debut, "end_um": ms.fin, "mid_um": ms.mid, "max_um": ms.maxi,
                     "length_um": ms.lngth, "length_str": ms.lngth_str, "arc_um": ms.arc_um},
        "notes": ms.notes,
    })
    out["shape"] = shape(sel, raw, out["pixels"], ms.ais_start, ms.ais_end, settings.pixconv,
                         bright_ref if bright_ref is not None else bright_level(raw))
    return out
