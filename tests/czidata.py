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


def write_czi_stack(channels: dict[str, np.ndarray], pixel_um: float = 0.10238, z_um: float | None = 0.77,
                    bits: int = 12, tiles: int = 1, shuffle: bool = False, drop: int | None = None,
                    extra: tuple[str, int, int] | None = None) -> bytes:
    """A Z-stack CZI: each channel (Z, Y, X), or (Z, H, Y, X) for an ApoTome
    stack's grid phases, one subblock per channel, slice, phase and tile,
    each of size 1 in Z and H as ZEN writes them. shuffle: subblocks out of
    order; drop: leave out that subblock (a damaged stack); extra: (name,
    start, size) on every subblock, e.g. ("T", 0, 2) to be refused."""
    arrays = {n: (a[:, None] if a.ndim == 3 else a) for n, a in channels.items()}
    first = next(iter(arrays.values()))
    Z, H = first.shape[:2]
    names = "".join(f'<Channel Id="Channel:{i}" Name="{n}"/>' for i, n in enumerate(arrays))
    scaling = f'<Distance Id="X"><Value>{pixel_um * 1e-6}</Value></Distance>' \
        + (f'<Distance Id="Z"><Value>{z_um * 1e-6}</Value></Distance>' if z_um else "")
    apotome = f"<ApoTomePhaseSetup IsActivated=\"true\"><PhaseCount>{H}</PhaseCount></ApoTomePhaseSetup>" if H > 1 else ""
    xml = ("<ImageDocument><Metadata><Information><Image>"
           f"<ComponentBitCount>{bits}</ComponentBitCount><SizeZ>{Z}</SizeZ>"
           f"<Dimensions><Channels>{names}</Channels></Dimensions></Image></Information>"
           f"<Experiment>{apotome}</Experiment><Scaling><Items>{scaling}</Items></Scaling>"
           "</Metadata></ImageDocument>").encode()
    header_size = 32 + 512
    metadata = _segment(b"ZISRAWMETADATA", struct.pack("<ii", len(xml), 0) + b"\0" * 248 + xml)
    pieces = []
    for c, volume in enumerate(arrays.values()):
        Y, W = volume.shape[2:]
        cuts = np.linspace(0, Y, tiles + 1).astype(int)
        for z in range(Z):
            for h in range(H):
                for y0, y1 in zip(cuts[:-1], cuts[1:]):
                    dims = [("X", -694, W), ("Y", int(y0) - 520, int(y1 - y0)), ("C", c, 1), ("Z", z, 1)] \
                        + ([("H", h, 1)] if H > 1 else []) + ([extra] if extra else [])
                    pieces.append((dims, np.ascontiguousarray(volume[z, h, y0:y1], "<u2").tobytes()))
    if shuffle:
        pieces = [pieces[i] for i in np.random.default_rng(3).permutation(len(pieces))]
    if drop is not None:
        pieces.pop(drop)
    pos = header_size + len(metadata)
    blocks, entries = b"", []
    for dims, data in pieces:
        entry = _entry(1, pos, dims)
        head = struct.pack("<iiq", 0, 0, len(data)) + entry
        seg = _segment(b"ZISRAWSUBBLOCK", head.ljust(256, b"\0") + data)
        blocks += seg
        entries.append(entry)
        pos += len(seg)
    directory = _segment(b"ZISRAWDIRECTORY", struct.pack("<i", len(entries)) + b"\0" * 124 + b"".join(entries))
    file_header = struct.pack("<iiii16s16siqqiq", 1, 0, 0, 0, b"\0" * 16, b"\0" * 16, 0, pos, header_size, 0, 0)
    return _segment(b"ZISRAWFILE", file_header.ljust(512, b"\0")) + metadata + blocks + directory


def apotome_phases(amplitude: np.ndarray, mean: np.ndarray, phases: int = 5, shift: float = 0.4) -> np.ndarray:
    """Grid images of one slice, (phases, Y, X): mean + amplitude * cos of
    the grid, moved 1/phases of its period each time, as ApoTome takes them."""
    k = np.arange(phases)[:, None, None]
    return np.rint(mean + amplitude * np.cos(2 * np.pi * k / phases + shift)).astype(np.uint16)
