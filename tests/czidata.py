"""Small .czi files written here, so the CZI tests need no example data:
just what app/analysis/czi.py reads (file header, metadata XML, one
uncompressed subblock per channel and tile, the directory)."""
from __future__ import annotations

import struct

import numpy as np


def _segment(kind: bytes, body: bytes) -> bytes:
    return kind.ljust(16, b"\0") + struct.pack("<qq", len(body), len(body)) + body


def _entry(pixel_type: int, pos: int, dims: list[tuple[str, int, int]], compression: int = 0) -> bytes:
    out = b"DV" + struct.pack("<iqiiB5si", pixel_type, pos, 0, compression, 0, b"\0" * 5, len(dims))
    for name, start, size in dims:
        out += struct.pack("<4siifi", name.encode().ljust(4, b"\0"), start, size, float(start), size)
    return out


def write_czi(channels: dict[str, np.ndarray], pixel_um: float = 0.16125, bits: int = 12,
              tiles: int = 1, extra: tuple[str, int] | None = None, compression: int = 0,
              colors: dict[str, str] | None = None) -> bytes:
    """A CZI of these 2-D uint16 channels, each cut into `tiles` horizontal
    strips (stored last strip first). extra: one more dimension (name, size)
    on every subblock, e.g. ("Z", 2) for a file that should be refused.
    colors: name -> "#rrggbb", written as ZEN's display settings (ARGB)."""
    names = "".join(f'<Channel Id="Channel:{i}" Name="{n}"/>' for i, n in enumerate(channels))
    xml = ("<ImageDocument><Metadata><Information><Image>"
           f"<ComponentBitCount>{bits}</ComponentBitCount><Dimensions><Channels>{names}</Channels></Dimensions>"
           "</Image></Information>"
           + ("<DisplaySetting><Channels>" + "".join(
               f'<Channel Name="{n}"><Color>#FF{c.lstrip("#").upper()}</Color></Channel>'
               for n, c in (colors or {}).items()) + "</Channels></DisplaySetting>" if colors else "")
           + "<Scaling><Items>"
           f'<Distance Id="X"><Value>{pixel_um * 1e-6}</Value></Distance>'
           "</Items></Scaling></Metadata></ImageDocument>").encode()
    header_size = 32 + 512
    metadata = _segment(b"ZISRAWMETADATA", struct.pack("<ii", len(xml), 0) + b"\0" * 248 + xml)
    pos = header_size + len(metadata)
    blocks, entries = b"", []
    for c, plane in enumerate(channels.values()):
        H, W = plane.shape
        cuts = np.linspace(0, H, tiles + 1).astype(int)
        for y0, y1 in reversed(list(zip(cuts[:-1], cuts[1:]))):
            dims = [("X", 0, W), ("Y", int(y0), int(y1 - y0)), ("C", c, 1)] + ([(extra[0], 0, extra[1])] if extra else [])
            entry = _entry(1, pos, dims, compression)
            data = np.ascontiguousarray(plane[y0:y1], "<u2").tobytes()
            head = struct.pack("<iiq", 0, 0, len(data)) + entry
            seg = _segment(b"ZISRAWSUBBLOCK", head.ljust(256, b"\0") + data)
            blocks += seg
            entries.append(entry)
            pos += len(seg)
    directory = _segment(b"ZISRAWDIRECTORY", struct.pack("<i", len(entries)) + b"\0" * 124 + b"".join(entries))
    file_header = struct.pack("<iiii16s16siqqiq", 1, 0, 0, 0, b"\0" * 16, b"\0" * 16, 0, pos, header_size, 0, 0)
    return _segment(b"ZISRAWFILE", file_header.ljust(512, b"\0")) + metadata + blocks + directory
