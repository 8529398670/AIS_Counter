"""Z-stacks: one image made of many per-slice TIFFs (docs/z-stack.md).

ZEN's Image Export writes a stack as a folder of `<cell>_z01c1+2.tif` files. A
batch keeps them as one image with one virtual file, whose sha is the sha-256
of a manifest: the slices in order, the plane their AIS stain is in, and the
calibration, which none of these files carry. Whatever takes "a sha" (tracing,
previews) then gets the stack's max projection back.

The batch record is the truth; the manifest can always be worked out from it
(app/analysis/service.py keeps a copy on disk). Standard library only, as
app/models/ais.py imports it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

# Digits are spelled out: \d also takes other scripts' digits. \Z, not $, which
# would let a trailing newline through.
SLICE_RE = re.compile(r"^(.+?)_z([0-9]{1,4})(c[0-9+]+)?\.tiff?\Z", re.IGNORECASE)
SUFFIX = ".zstack"
FORMAT = "ais-zstack"
MIN_SLICES = 2          # one match alone is an ordinary image
PLANES = (0, 1)         # red and green; blue in ZEN's merge is green's tint
MAX_UM = 100.0


def parse(name: str) -> tuple[str, int, str] | None:
    """(cell, z, channel ending) of a slice's file name, or None."""
    match = SLICE_RE.match(name)
    return (match[1], int(match[2]), (match[3] or "").lower()) if match else None


def _micrometres(value: Any, label: str) -> float:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or not 0 < value <= MAX_UM):
        raise ValueError(f"{label} must be between 0 and {MAX_UM:g} µm")
    return float(value)


def clean_options(value: Any) -> dict[str, Any]:
    """What the person adding stacks says about them, none of which the files
    do: {plane, z_step_um, pixel_um}, checked."""
    if not isinstance(value, dict):
        raise ValueError("stack must be an object")
    plane = value.get("plane")
    if plane not in PLANES or isinstance(plane, bool):
        raise ValueError("plane must be red (0) or green (1)")
    return {"plane": plane, "z_step_um": _micrometres(value.get("z_step_um"), "z step"),
            "pixel_um": _micrometres(value.get("pixel_um"), "pixel size")}


def manifest(slices: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    """The stack as data: slices (each with z and sha) in z order, and options
    (clean_options). Numbers are floats so 1 and 1.0 give the same sha."""
    return {"format": FORMAT, "plane": options["plane"],
            "z_step_um": float(options["z_step_um"]), "pixel_um": float(options["pixel_um"]),
            "slices": [{"z": s["z"], "sha": s["sha"]} for s in sorted(slices, key=lambda s: s["z"])]}


def canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def sha(data: dict[str, Any]) -> str:
    """A manifest's id, which stands in for a file's sha."""
    return hashlib.sha256(canonical(data)).hexdigest()
