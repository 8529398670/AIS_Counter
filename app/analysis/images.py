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
from PIL import Image

PROCESSED_SUFFIX = ".tif - Processed method 2.5.tif"
# The most a compressed page may decode to through Pillow: ample for a camera
# frame, and short of what would fill a 256 MB container. Pillow's own limit
# (about 179 megapixels) is too high to protect it.
MAX_SAMPLES = 64_000_000


class ImageError(ValueError):
    pass


def decode_tiff(data: bytes) -> np.ndarray:
    """The first page's pixels, as tifffile gives them. tifffile needs
    imagecodecs for LZW, which has no Alpine wheel, so a compressed page it
    can't decode goes through Pillow instead."""
    try:
        with tifffile.TiffFile(io.BytesIO(data)) as tif:
            page = tif.pages[0]
            try:
                return page.asarray()
            except Exception:
                if page.compression == tifffile.COMPRESSION.NONE:
                    raise
                return _with_pillow(data, page)
    except ImageError:
        raise
    except Exception as exc:  # tifffile raises many types for bad input
        raise ImageError("not a readable TIFF") from exc


def _with_pillow(data: bytes, page: tifffile.TiffPage) -> np.ndarray:
    """The page through Pillow, refused where it would not be the same pixels:
    it turns 16-bit colour into 8-bit without saying so."""
    if page.imagewidth * page.imagelength * page.samplesperpixel > MAX_SAMPLES:
        raise ImageError("image too large")
    with Image.open(io.BytesIO(data), formats=("TIFF",)) as image:
        arr = np.asarray(image)
    native = arr.dtype.newbyteorder("=")
    if native != page.dtype.newbyteorder("="):
        raise ImageError("expected a single-channel 8- or 16-bit image")
    return arr.astype(native, copy=False)


def read_tiff(data: bytes) -> np.ndarray:
    """The first page of a TIFF as a 2-D array, like imread(file)(:,:,1)."""
    arr = decode_tiff(data)
    if arr.ndim == 3:
        arr = arr[:, :, 0] if arr.shape[2] <= 4 else arr[0]
    if arr.ndim != 2 or arr.dtype not in (np.uint8, np.uint16):
        raise ImageError("expected a single-channel 8- or 16-bit image")
    if min(arr.shape) < 3:
        raise ImageError("image too small")
    return np.ascontiguousarray(arr)


def read_planes(data: bytes) -> np.ndarray:
    """The first page of a TIFF as (height, width, planes): one plane for grey,
    one for each channel of colour. A Z-stack slice is read this way, as its
    AIS stain may be any plane of the merged export."""
    arr = decode_tiff(data)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    elif arr.ndim == 3 and arr.shape[2] > 4:
        arr = np.moveaxis(arr, 0, -1)   # stored plane by plane
    if arr.ndim != 3 or arr.shape[2] > 4 or arr.dtype not in (np.uint8, np.uint16):
        raise ImageError("expected an 8- or 16-bit image of up to four planes")
    if min(arr.shape[:2]) < 3:
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
    return _png(scaled)


def scaled_png(arr: np.ndarray, lo: float, hi: float) -> bytes:
    """8-bit greyscale PNG between lo and hi, clipped: a Z-stack's slices on one
    scale, so a dim end slice looks dim rather than flaring."""
    a = np.clip(arr.astype(np.float64), lo, hi)
    return _png(np.zeros(a.shape, np.uint8) if hi <= lo else np.floor((a - lo) / (hi - lo) * 255 + 0.5).astype(np.uint8))


def composite_png(planes: list[np.ndarray], colors: list[str], percentiles: tuple[float, float]) -> bytes:
    """Channels merged as ZEN shows them, an RGB PNG: each between its two
    percentiles, clipped, in its "#rrggbb" color, added up."""
    rgb = np.zeros((*planes[0].shape, 3))
    for plane, color in zip(planes, colors):
        a = plane.astype(np.float64)
        lo, hi = np.percentile(a, percentiles)
        if hi > lo:
            shade = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], np.float64)
            rgb += (np.clip(a, lo, hi) - lo)[..., None] / (hi - lo) * shade
    return _png(np.floor(np.clip(rgb, 0, 255) + 0.5).astype(np.uint8))


def _png(scaled: np.ndarray) -> bytes:
    """A PNG of 8-bit pixels: greyscale (h, w) or RGB (h, w, 3)."""
    h, w = scaled.shape[:2]
    raw = b"".join(b"\x00" + scaled[r].tobytes() for r in range(h))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2 if scaled.ndim == 3 else 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


THUMB_SIDE = 256


def thumbnail_png(arr: np.ndarray, side: int = THUMB_SIDE) -> bytes:
    """A small min..max preview: every k-th pixel, k chosen so the long side
    is about `side`."""
    step = max(1, int(np.ceil(max(arr.shape) / side)))
    return preview_png(arr[::step, ::step])
