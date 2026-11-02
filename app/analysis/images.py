"""Reading the TIFFs ais_auto.m reads, pairing them, and drawing a preview.

The original opens two files per cell: `<cell>.tif - Processed method 2.5.tif`
(the ImageJ-processed image it segments and traces) and `<cell>.tif` (the raw
image it samples the intensity profile from). imread takes the first page
and, for colour, the first channel; tifffile gives the same uint16 pixels.
"""
from __future__ import annotations

import io
import struct
import zlib

import numpy as np
import tifffile

PROCESSED_SUFFIX = ".tif - Processed method 2.5.tif"


class ImageError(ValueError):
    pass


def read_tiff(data: bytes) -> np.ndarray:
    """The first page of a TIFF as a 2-D array, like imread(file)(:,:,1)."""
    try:
        with tifffile.TiffFile(io.BytesIO(data)) as tif:
            arr = tif.pages[0].asarray()
    except Exception as exc:  # tifffile raises many types for bad input
        raise ImageError("not a readable TIFF") from exc
    if arr.ndim == 3:
        arr = arr[:, :, 0] if arr.shape[2] <= 4 else arr[0]
    if arr.ndim != 2 or arr.dtype not in (np.uint8, np.uint16):
        raise ImageError("expected a single-channel 8- or 16-bit image")
    if min(arr.shape) < 3:
        raise ImageError("image too small")
    return np.ascontiguousarray(arr)


def tiff_bytes(arr: np.ndarray) -> bytes:
    """arr as a one-page TIFF, which imread reads back as the same pixels."""
    buf = io.BytesIO()
    tifffile.imwrite(buf, arr)
    return buf.getvalue()


def role_and_cell(filename: str) -> tuple[str, str]:
    """("processed" | "raw", cell name) from a filename: the processed file is
    the raw file's name plus " - Processed method 2.5.tif"."""
    name = filename.rsplit("/", 1)[-1]
    if name.endswith(PROCESSED_SUFFIX):
        return "processed", name[: -len(PROCESSED_SUFFIX)]
    if name.lower().endswith((".tif", ".tiff")):
        return "raw", name.rsplit(".", 1)[0]
    raise ImageError("expected a .tif file")


def preview_png(arr: np.ndarray, percentiles: tuple[float, float] | None = None) -> bytes:
    """8-bit greyscale PNG scaled min..max, as imagesc with colormap(gray);
    or between two percentiles, clipped (a channel view, as napari shows it)."""
    a = arr.astype(np.float64)
    lo, hi = (a.min(), a.max()) if percentiles is None else np.percentile(a, percentiles)
    a = np.clip(a, lo, hi)
    scaled = np.zeros(a.shape, np.uint8) if hi == lo else np.floor((a - lo) / (hi - lo) * 255 + 0.5).astype(np.uint8)
    h, w = scaled.shape
    raw = b"".join(b"\x00" + scaled[r].tobytes() for r in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


THUMB_SIDE = 256


def thumbnail_png(arr: np.ndarray, side: int = THUMB_SIDE) -> bytes:
    """A small min..max preview: every k-th pixel, k chosen so the long side
    is about `side`."""
    step = max(1, int(np.ceil(max(arr.shape) / side)))
    return preview_png(arr[::step, ::step])
