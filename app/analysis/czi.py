"""Reading the .czi files ZEN saves, for CZI mode.

A CZI holds every channel of a cell: "Alexa Fluor 488" (the AIS, the same
pixels as the exported `<cell>_ORG.tif`, which is the 12-bit camera data
times 16) and "AMCA" (somata and dendrites, app/analysis/soma.py).

Only what ours are is read: uncompressed 8- or 16-bit greyscale, one scene,
one Z and T, tiles (M) placed by their X/Y start. Anything else is refused
rather than half-read. The format (ZISRAW): 32-byte segment headers ("ZISRAW..."
id, allocated and used size); the file header points at the directory, whose
entries say where each subblock is and which channel and tile it holds; the
metadata segment is XML with the channel names and the pixel size.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np

from app.analysis.images import ImageError

# The channel the AIS is stained in and the one soma.py reads, by the names
# ZEN records.
AIS_CHANNEL = "Alexa Fluor 488"
SOMA_CHANNEL = "AMCA"

MAGIC = b"ZISRAWFILE"
SEGMENT_HEADER = 32
PIXEL_TYPES = {0: np.uint8, 1: np.uint16}   # Gray8, Gray16
SINGLE = ("Z", "T", "S", "B", "H", "R", "I", "V")  # dimensions that must be size 1
# For channels with no recorded color, in order: ZEN's usual defaults.
FALLBACK_COLORS = ("#00ff33", "#ff0000", "#0040ff", "#ff00ff", "#ffff00", "#00ffff")


@dataclass
class Czi:
    channels: dict[str, np.ndarray]   # name -> 2-D image, in the file's channel order
    pixel_um: float | None            # microns per pixel, from the metadata
    bits: int | None = None           # significant bits per pixel (12 for ours)
    colors: dict[str, str] = field(default_factory=dict)   # name -> "#rrggbb", ZEN's display color

    def channel(self, name: str) -> np.ndarray:
        if name not in self.channels:
            raise ImageError(f"the .czi file has no {name!r} channel (it has {', '.join(map(repr, self.channels))})")
        return self.channels[name]

    def as_tiff(self, name: str) -> np.ndarray:
        """The channel as ZEN exports it to TIFF: scaled up to fill 16 bits
        (12-bit data times 16), so it is the same image as `<cell>_ORG.tif`."""
        plane = self.channel(name)
        if plane.dtype == np.uint16 and self.bits and 8 < self.bits < 16:
            return plane << np.uint16(16 - self.bits)
        return plane


def is_czi(data: bytes) -> bool:
    return data[:len(MAGIC)] == MAGIC


def _segment(data: bytes, offset: int, kind: bytes) -> int:
    """Where the segment at offset starts its data, checking it is kind."""
    if offset < 0 or offset + SEGMENT_HEADER > len(data):
        raise ImageError("damaged .czi file")
    if data[offset:offset + 16].rstrip(b"\0") != kind:
        raise ImageError("damaged .czi file")
    return offset + SEGMENT_HEADER


def _entries(data: bytes, offset: int) -> list[dict]:
    """The directory's subblock entries (DirectoryEntryDV)."""
    pos = _segment(data, offset, b"ZISRAWDIRECTORY")
    (count,) = struct.unpack_from("<i", data, pos)
    pos += 128
    out = []
    for _ in range(count):
        if data[pos:pos + 2] != b"DV":
            raise ImageError("damaged .czi file")
        pixel_type, file_pos, _part, compression, pyramid = struct.unpack_from("<iqiiB", data, pos + 2)
        (ndims,) = struct.unpack_from("<i", data, pos + 28)
        pos += 32
        dims = {}
        for _ in range(ndims):
            name, start, size, _coord, stored = struct.unpack_from("<4siifi", data, pos)
            dims[name.rstrip(b"\0").decode("ascii", "replace")] = (start, size, stored)
            pos += 20
        out.append({"pixel_type": pixel_type, "pos": file_pos, "compression": compression,
                    "pyramid": pyramid, "dims": dims})
    return out


def _metadata(data: bytes, offset: int) -> ET.Element | None:
    if not offset:
        return None
    pos = _segment(data, offset, b"ZISRAWMETADATA")
    (size,) = struct.unpack_from("<i", data, pos)
    try:
        return ET.fromstring(data[pos + 256:pos + 256 + size])
    except ET.ParseError:
        return None


def _names(meta: ET.Element | None, count: int) -> list[str]:
    found = [] if meta is None else [
        c.get("Name") or c.get("Id") or "" for c in meta.findall(".//Information/Image/Dimensions/Channels/Channel")]
    if len(found) != count or len(set(found)) != count or not all(found):
        return [f"channel {i + 1}" for i in range(count)]
    return found


def _pixel_um(meta: ET.Element | None) -> float | None:
    if meta is None:
        return None
    for item in meta.findall(".//Scaling/Items/Distance"):
        if item.get("Id") == "X":
            try:
                return float(item.findtext("Value")) * 1e6   # metres
            except (TypeError, ValueError):
                return None
    return None


def _bits(meta: ET.Element | None) -> int | None:
    try:
        return int(meta.findtext(".//Information/Image/ComponentBitCount")) if meta is not None else None
    except (TypeError, ValueError):
        return None


def _colors(meta: ET.Element | None, names: list[str]) -> dict[str, str]:
    """Each channel's display color ("#FF00FF33" is ARGB in ZEN's metadata),
    or the next fallback."""
    found = {}
    if meta is not None:
        for channel in meta.findall(".//DisplaySetting/Channels/Channel"):
            color = (channel.findtext("Color") or "").lstrip("#")
            if len(color) == 8:
                found[channel.get("Name")] = "#" + color[2:].lower()
    return {n: found.get(n) or FALLBACK_COLORS[i % len(FALLBACK_COLORS)] for i, n in enumerate(names)}


def read_czi(data: bytes) -> Czi:
    """Every channel of a CZI as a 2-D array; ImageError for anything this
    does not read (see the module docstring)."""
    if not is_czi(data):
        raise ImageError("not a .czi file")
    try:
        pos = _segment(data, 0, MAGIC)
        directory, metadata = struct.unpack_from("<qq", data, pos + 52)
        entries = [e for e in _entries(data, directory) if e["pyramid"] == 0]
        meta = _metadata(data, metadata)
    except struct.error:
        raise ImageError("damaged .czi file") from None
    if not entries:
        raise ImageError("no images in the .czi file")
    for e in entries:
        if e["compression"] != 0:
            raise ImageError("compressed .czi files are not supported")
        if e["pixel_type"] not in PIXEL_TYPES:
            raise ImageError("expected 8- or 16-bit greyscale .czi channels")
        if any(e["dims"].get(d, (0, 1, 1))[1] != 1 for d in SINGLE):
            raise ImageError("only single-plane .czi files are supported (one scene, Z and time point)")
        if any(e["dims"].get(d, (0, 1, 1))[0] != entries[0]["dims"].get(d, (0, 1, 1))[0] for d in SINGLE):
            raise ImageError("only single-plane .czi files are supported (one scene, Z and time point)")
        x, y = e["dims"].get("X"), e["dims"].get("Y")
        if not x or not y or x[1] != x[2] or y[1] != y[2]:
            raise ImageError("damaged .czi file")
    x0 = min(e["dims"]["X"][0] for e in entries)
    y0 = min(e["dims"]["Y"][0] for e in entries)
    width = max(e["dims"]["X"][0] + e["dims"]["X"][1] for e in entries) - x0
    height = max(e["dims"]["Y"][0] + e["dims"]["Y"][1] for e in entries) - y0
    starts = sorted({e["dims"].get("C", (0, 1, 1))[0] for e in entries})
    dtype = PIXEL_TYPES[entries[0]["pixel_type"]]
    planes = {c: np.zeros((height, width), dtype) for c in starts}
    for e in entries:
        pos = _segment(data, e["pos"], b"ZISRAWSUBBLOCK")
        meta_size, _attach, size = struct.unpack_from("<iiq", data, pos)
        (ndims,) = struct.unpack_from("<i", data, pos + 16 + 28)
        start = pos + max(256, 16 + 32 + 20 * ndims) + meta_size
        (w0, w, _), (h0, h, _) = e["dims"]["X"], e["dims"]["Y"]
        if PIXEL_TYPES[e["pixel_type"]] is not dtype or size != w * h * np.dtype(dtype).itemsize \
                or start + size > len(data):
            raise ImageError("damaged .czi file")
        tile = np.frombuffer(data, dtype, w * h, start).reshape(h, w)
        planes[e["dims"].get("C", (0, 1, 1))[0]][h0 - y0:h0 - y0 + h, w0 - x0:w0 - x0 + w] = tile
    names = _names(meta, len(starts))
    return Czi({name: planes[c] for name, c in zip(names, starts)}, _pixel_um(meta), _bits(meta),
               _colors(meta, names))
