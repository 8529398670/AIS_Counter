"""Reading the .czi files ZEN saves, for CZI mode.

A CZI holds every channel of a cell: usually "Alexa Fluor 488" (the AIS, the
same pixels as the exported `<cell>_ORG.tif`, which is the 12-bit camera data
times 16) and "AMCA" (somata and dendrites, app/analysis/soma.py). Other
stainings are taken as they come: the soma channel is the blue stain
(SOMA_STAINS), the AIS channel 488 if there is one, else the first other
channel (Czi.ais_name).

Only what ours are is read: uncompressed 8- or 16-bit greyscale, one scene,
one T, tiles (M) placed by their X/Y start. Anything else is refused rather
than half-read. read_czi reads one Z; a Z-stack (Z > 1, docs/z-stack.md) is
read by read_header and read_stack instead. The format (ZISRAW): 32-byte
segment headers ("ZISRAW..." id, allocated and used size); the file header
points at the directory, whose entries say where each subblock is and which
channel, slice, phase and tile it holds; the metadata segment is XML with the
channel names and the pixel size and z step.

An ApoTome Z-stack holds the raw grid images, not ZEN's processed ones: H
phases (5 on ours) of each slice and channel, the grid shifted by 1/H of its
period each time. read_stack makes the optical section from them as
|sum_k P_k exp(-2 pi i k / H)| * 2 / H, the amplitude of the grid's modulation,
which only in-focus light has. On the two sample stacks that correlates
r = 0.99 (Alexa Fluor 488) and 0.94 (594) with ZEN's own IP-ApoTome export;
ZEN also corrects grid phase and bleaching, so it is close to, not the same
as, ZEN's. Widefield is the phases' mean: in-focus and out-of-focus light.
"""
from __future__ import annotations

import math
import struct
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from app.analysis.channels import AIS_CHANNEL, SOMA_STAINS, ais_index, soma_index  # noqa: F401
from app.analysis.images import ImageError

MAGIC = b"ZISRAWFILE"
SEGMENT_HEADER = 32
PIXEL_TYPES = {0: np.uint8, 1: np.uint16}   # Gray8, Gray16
SINGLE = ("Z", "T", "S", "B", "H", "R", "I", "V")  # dimensions that must be size 1
STACKED = ("Z", "H")   # of those, what a Z-stack's subblocks differ in: slice and ApoTome phase
APOTOME = ("sectioned", "widefield")
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

    @property
    def soma_name(self) -> str | None:
        """The channel soma.py reads: the first SOMA_STAINS stain there is;
        None when the cell has none (channels.soma_index)."""
        names = list(self.channels)
        found = soma_index(names)
        return None if found is None else names[found]

    @property
    def ais_name(self) -> str:
        """The channel the AIS is traced in: Alexa Fluor 488 when there is
        one, else the first channel that is not the soma's (an AIS stained in
        594, say), else the only channel (channels.ais_index)."""
        names = list(self.channels)
        return names[ais_index(names)]

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


def _z_um(meta: ET.Element | None) -> float | None:
    """The z step in microns, from the metadata's Z scaling; None without one."""
    if meta is None:
        return None
    for item in meta.findall(".//Scaling/Items/Distance"):
        if item.get("Id") == "Z":
            try:
                found = float(item.findtext("Value")) * 1e6   # metres
            except (TypeError, ValueError):
                return None
            return found if math.isfinite(found) and found > 0 else None
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


def _scan(data: bytes) -> tuple[list[dict], ET.Element | None]:
    """The directory entries and the metadata, each entry checked for what
    every reader here needs (uncompressed greyscale, whole X and Y)."""
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
    return entries, meta


def _placed(entries: list[dict]) -> None:
    for e in entries:
        x, y = e["dims"].get("X"), e["dims"].get("Y")
        if not x or not y or x[1] != x[2] or y[1] != y[2]:
            raise ImageError("damaged .czi file")


def _distinct(entries: list[dict], name: str) -> list[int]:
    return sorted({e["dims"].get(name, (0, 1, 1))[0] for e in entries})


def _contents(data: bytes) -> tuple[list[dict], ET.Element | None]:
    """The checked directory entries and the metadata of a single-plane CZI;
    ImageError for anything this does not read (see the module docstring)."""
    entries, meta = _scan(data)
    for e in entries:
        if any(e["dims"].get(d, (0, 1, 1))[1] != 1 for d in SINGLE):
            raise ImageError("only single-plane .czi files are supported (one scene, Z and time point)")
        if any(e["dims"].get(d, (0, 1, 1))[0] != entries[0]["dims"].get(d, (0, 1, 1))[0] for d in SINGLE):
            slices = len(_distinct(entries, "Z"))
            if slices > 1 and _stacked(entries):
                raise ImageError(f"this .czi is a Z-stack ({slices} slices); add it again to read it as one")
            raise ImageError("only single-plane .czi files are supported (one scene, Z and time point)")
        x, y = e["dims"].get("X"), e["dims"].get("Y")
        if not x or not y or x[1] != x[2] or y[1] != y[2]:
            raise ImageError("damaged .czi file")
    return entries, meta


def _stacked(entries: list[dict]) -> bool:
    """Whether the entries differ only in slice and phase (STACKED), each
    subblock one of each, as a Z-stack's do."""
    first = entries[0]["dims"]
    for e in entries:
        for d in SINGLE:
            start, size, _ = e["dims"].get(d, (0, 1, 1))
            if size != 1 or (d not in STACKED and start != first.get(d, (0, 1, 1))[0]):
                return False
    return True


def _stack_contents(data: bytes) -> tuple[list[dict], ET.Element | None]:
    """A single-plane CZI's or a Z-stack's entries and metadata: like
    _contents, but slices and phases may differ."""
    entries, meta = _scan(data)
    if not _stacked(entries):
        raise ImageError("only Z-stacks and single-plane .czi files are supported (one scene and time point)")
    _placed(entries)
    return entries, meta


def _groups(entries: list[dict]) -> dict[tuple[int, int, int], list[dict]]:
    """Entries by (C, Z, H) start, every combination there with the same
    tiles; ImageError when one is missing, so no slice is read half-empty."""
    groups: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    for e in entries:
        groups[tuple(e["dims"].get(d, (0, 1, 1))[0] for d in ("C", "Z", "H"))].append(e)
    want = {(c, z, h) for c in _distinct(entries, "C") for z in _distinct(entries, "Z") for h in _distinct(entries, "H")}
    if set(groups) != want:
        raise ImageError("the .czi Z-stack is missing slices or phases")
    layouts = {tuple(sorted((e["dims"]["X"][0], e["dims"]["Y"][0], e["dims"]["X"][1], e["dims"]["Y"][1])
                            for e in group)) for group in groups.values()}
    if len(layouts) != 1:
        raise ImageError("the .czi Z-stack's slices are tiled differently")
    return groups


def _tile(data: bytes, e: dict, dtype: type) -> int:
    """Where a subblock's pixels start, checking they are all there."""
    pos = _segment(data, e["pos"], b"ZISRAWSUBBLOCK")
    meta_size, _attach, size = struct.unpack_from("<iiq", data, pos)
    (ndims,) = struct.unpack_from("<i", data, pos + 16 + 28)
    start = pos + max(256, 16 + 32 + 20 * ndims) + meta_size
    w, h = e["dims"]["X"][1], e["dims"]["Y"][1]
    if PIXEL_TYPES[e["pixel_type"]] is not dtype or size != w * h * np.dtype(dtype).itemsize \
            or start + size > len(data):
        raise ImageError("damaged .czi file")
    return start


def _starts(entries: list[dict]) -> list[int]:
    """The channels' C coordinates, in the file's order."""
    return sorted({e["dims"].get("C", (0, 1, 1))[0] for e in entries})


def read_channels(data: bytes) -> dict[str, str]:
    """A CZI's channels as name -> "#rrggbb", in the file's order, from its
    directory and metadata alone: no pixels are read, so data can be a mmap.
    A Z-stack's too."""
    entries, meta = _stack_contents(data)
    names = _names(meta, len(_starts(entries)))
    return _colors(meta, names)


def read_czi(data: bytes) -> Czi:
    """Every channel of a CZI as a 2-D array; ImageError for anything this
    does not read (see the module docstring)."""
    entries, meta = _contents(data)
    x0 = min(e["dims"]["X"][0] for e in entries)
    y0 = min(e["dims"]["Y"][0] for e in entries)
    width = max(e["dims"]["X"][0] + e["dims"]["X"][1] for e in entries) - x0
    height = max(e["dims"]["Y"][0] + e["dims"]["Y"][1] for e in entries) - y0
    starts = _starts(entries)
    dtype = PIXEL_TYPES[entries[0]["pixel_type"]]
    planes = {c: np.zeros((height, width), dtype) for c in starts}
    for e in entries:
        start = _tile(data, e, dtype)
        (w0, w, _), (h0, h, _) = e["dims"]["X"], e["dims"]["Y"]
        tile = np.frombuffer(data, dtype, w * h, start).reshape(h, w)
        planes[e["dims"].get("C", (0, 1, 1))[0]][h0 - y0:h0 - y0 + h, w0 - x0:w0 - x0 + w] = tile
    names = _names(meta, len(starts))
    return Czi({name: planes[c] for name, c in zip(names, starts)}, _pixel_um(meta), _bits(meta),
               _colors(meta, names))


@dataclass
class CziHeader:
    """What a CZI is, from its directory and metadata alone (read_header)."""
    names: list[str]                  # channel names, in the file's order
    colors: dict[str, str]            # name -> "#rrggbb"
    pixel_um: float | None
    z_step_um: float | None           # None without Z scaling
    bits: int | None
    slices: int                       # Z; 1 for a single-plane CZI
    phases: int                       # H, ApoTome grid phases; 1 without
    width: int
    height: int
    dtype: str = "uint16"


def _extent(entries: list[dict]) -> tuple[int, int, int, int]:
    x0 = min(e["dims"]["X"][0] for e in entries)
    y0 = min(e["dims"]["Y"][0] for e in entries)
    width = max(e["dims"]["X"][0] + e["dims"]["X"][1] for e in entries) - x0
    height = max(e["dims"]["Y"][0] + e["dims"]["Y"][1] for e in entries) - y0
    return x0, y0, width, height


def read_header(data: bytes) -> CziHeader:
    """A CZI's channels, calibration, slices and phases; every subblock's
    header is checked but no pixels are read, so data can be a mmap of a
    300 MB stack. ImageError for anything read_czi or read_stack would refuse."""
    entries, meta = _stack_contents(data)
    if len(_distinct(entries, "Z")) > 1 or len(_distinct(entries, "H")) > 1:
        _groups(entries)
    else:
        _contents(data)
    dtype = PIXEL_TYPES[entries[0]["pixel_type"]]
    try:
        for e in entries:
            _tile(data, e, dtype)
    except struct.error:
        raise ImageError("damaged .czi file") from None
    names = _names(meta, len(_starts(entries)))
    _, _, width, height = _extent(entries)
    return CziHeader(names, _colors(meta, names), _pixel_um(meta), _z_um(meta), _bits(meta),
                     len(_distinct(entries, "Z")), len(_distinct(entries, "H")), width, height, np.dtype(dtype).name)


def read_stack(data: bytes, channel: int, apotome: str | None,
               slices: Sequence[int] | None = None) -> np.ndarray:
    """One channel of a Z-stack CZI as (slices, height, width), in z order,
    on the scale ZEN exports to TIFF (Czi.as_tiff). An ApoTome stack's
    phases are made into one image per slice: apotome "sectioned" or
    "widefield" (module docstring); apotome is None exactly when the file
    has no phases. slices: which of them (0-based), else all. Built one
    slice and phase at a time from views of data, which can be a mmap."""
    entries, meta = _stack_contents(data)
    groups = _groups(entries)
    cs, zs, hs = _distinct(entries, "C"), _distinct(entries, "Z"), _distinct(entries, "H")
    if not 0 <= channel < len(cs):
        raise ImageError("the .czi file has no such channel")
    if (len(hs) > 1) != (apotome is not None):
        raise ImageError("an ApoTome .czi needs sectioned or widefield" if len(hs) > 1
                         else "this .czi has no ApoTome phases")
    if apotome is not None and apotome not in APOTOME:
        raise ImageError("apotome must be sectioned or widefield")
    picked = range(len(zs)) if slices is None else list(slices)
    if any(not 0 <= i < len(zs) for i in picked):
        raise ImageError("no such slice")
    dtype = PIXEL_TYPES[entries[0]["pixel_type"]]
    x0, y0, width, height = _extent(entries)
    bits = _bits(meta)
    shift = 16 - bits if dtype == np.uint16 and bits and 8 < bits < 16 else 0
    top = (1 << (16 - shift)) - 1 if dtype == np.uint16 else 255

    def plane(z: int, h: int) -> np.ndarray:
        out = np.zeros((height, width), dtype)
        for e in groups[cs[channel], z, h]:
            start = _tile(data, e, dtype)
            (w0, w, _), (h0, hh, _) = e["dims"]["X"], e["dims"]["Y"]
            out[h0 - y0:h0 - y0 + hh, w0 - x0:w0 - x0 + w] = np.frombuffer(data, dtype, w * hh, start).reshape(hh, w)
        return out

    stack = np.empty((len(picked), height, width), dtype)
    n = len(hs)
    for i, index in enumerate(picked):
        z = zs[index]
        if n == 1:
            stack[i] = plane(z, hs[0])
            continue
        if apotome == "widefield":
            total = np.zeros((height, width), np.float32)
            for h in hs:
                total += plane(z, h)
            made = total / n
        else:
            re = np.zeros((height, width), np.float32)
            im = np.zeros((height, width), np.float32)
            for k, h in enumerate(hs):
                p = plane(z, h).astype(np.float32)
                re += p * np.float32(math.cos(2 * math.pi * k / n))
                im -= p * np.float32(math.sin(2 * math.pi * k / n))
            made = np.sqrt(re * re + im * im) * np.float32(2 / n)
        stack[i] = np.clip(np.rint(made), 0, top).astype(dtype)
    if shift:
        stack <<= np.uint16(shift)
    return stack
