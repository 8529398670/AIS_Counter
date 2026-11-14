"""Z-stacks: one image made of many per-slice TIFFs, or of one .czi with many
slices (docs/z-stack.md).

ZEN's Image Export writes a stack as a folder of `<cell>_z01c1+2.tif` files. A
batch keeps them as one image with one virtual file, whose sha is the sha-256
of a manifest: the slices in order, the plane their AIS stain is in, and the
calibration, which none of these files carry. Whatever takes "a sha" (tracing,
previews) then gets the stack's max projection back.

A Z-stack .czi is one file holding every slice, so its manifest names that
file (source) instead of a sha per slice, the channel the AIS is in (plane),
how its ApoTome phases are made into slices (apotome, None without phases),
and the calibration the file records (or what replaced it). Its slices are
numbered from 1, as ZEN numbers its exported `z01` files.

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
PLANES = (0, 1, 2, 3)   # read_planes reads up to four: red, green, blue, the fourth
MAX_UM = 100.0
CZI = "czi"             # z_stack["source"] of a stack that is one .czi
APOTOME = ("sectioned", "widefield")
MAX_CZI_CHANNELS = 16   # channels.MAX_CHANNELS (channels.py imports this module)
MAX_CZI_SLICES = 10_000
MAX_PHASES = 16


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
        raise ValueError("plane must be a channel from 0 to 3 (red, green, blue, fourth)")
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


def _whole(value: Any, label: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f"{label} must be a whole number from {low} to {high}")
    return value


def _maybe_um(value: Any, label: str) -> float | None:
    return None if value is None else _micrometres(value, label)


def clean_czi_header(value: Any) -> dict[str, Any]:
    """What a Z-stack .czi says of itself, as the client (or local.py) read it
    from the file: {slices, phases, z_step_um, pixel_um}, calibration None
    when the file has none."""
    if not isinstance(value, dict):
        raise ValueError("zstack must be an object")
    return {"slices": _whole(value.get("slices"), "slices", MIN_SLICES, MAX_CZI_SLICES),
            "phases": _whole(value.get("phases", 1), "phases", 1, MAX_PHASES),
            "z_step_um": _maybe_um(value.get("z_step_um"), "z step"),
            "pixel_um": _maybe_um(value.get("pixel_um"), "pixel size")}


def clean_czi_choice(value: Any) -> dict[str, Any]:
    """What the person adding Z-stack .czi files chose: {apotome}, how ApoTome
    phases become slices, "sectioned" unless said."""
    if value is None:
        return {"apotome": APOTOME[0]}
    if not isinstance(value, dict):
        raise ValueError("czi_stack must be an object")
    apotome = value.get("apotome", APOTOME[0])
    if apotome not in APOTOME:
        raise ValueError("apotome must be sectioned or widefield")
    return {"apotome": apotome}


def _clean_czi_options(value: dict[str, Any]) -> dict[str, Any]:
    phases = _whole(value.get("phases", 1), "phases", 1, MAX_PHASES)
    apotome = value.get("apotome")
    if (apotome is None) != (phases == 1) or (apotome is not None and apotome not in APOTOME):
        raise ValueError("apotome must be sectioned or widefield for an ApoTome stack, else none")
    return {"source": CZI, "count": _whole(value.get("count"), "count", MIN_SLICES, MAX_CZI_SLICES),
            "phases": phases, "apotome": apotome,
            "plane": _whole(value.get("plane"), "plane", 0, MAX_CZI_CHANNELS - 1),
            "z_step_um": _micrometres(value.get("z_step_um"), "z step"),
            "pixel_um": _micrometres(value.get("pixel_um"), "pixel size")}


def is_czi(z_stack: dict[str, Any] | None) -> bool:
    """Whether an image's z_stack is a Z-stack .czi's."""
    return bool(z_stack) and z_stack.get("source") == CZI


def from_czi(data: dict[str, Any] | None) -> bool:
    """Whether a manifest is a Z-stack .czi's (it names its file)."""
    return bool(data) and "source" in data


def clean_stored(value: Any) -> dict[str, Any]:
    """A stored image's z_stack checked, either kind: clean_options with the
    slice count for TIFF slices, every field for a .czi."""
    if isinstance(value, dict) and value.get("source") == CZI:
        return _clean_czi_options(value)
    return clean_options(value)


def czi_manifest(source: str, options: dict[str, Any]) -> dict[str, Any]:
    """A Z-stack .czi as data: the file, the channel, how its phases are
    made into slices, and its calibration (floats, as in manifest)."""
    return {"format": FORMAT, "source": source, "plane": options["plane"], "apotome": options["apotome"],
            "z_step_um": float(options["z_step_um"]), "pixel_um": float(options["pixel_um"]),
            "slices": [{"z": z} for z in range(1, options["count"] + 1)]}


def manifest_of(stack_file: dict[str, Any], z_stack: dict[str, Any]) -> dict[str, Any]:
    """The manifest of an image's stack file (files["stack"]) with its z_stack:
    the one place either kind's is made, so every sha agrees."""
    if z_stack.get("source") == CZI:
        return czi_manifest(stack_file["slices"][0]["sha"], z_stack)
    return manifest(stack_file["slices"], z_stack)


def parts(data: dict[str, Any]) -> list[str]:
    """The real files a manifest is made of: its .czi, else its slices."""
    return [data["source"]] if "source" in data else [s["sha"] for s in data["slices"]]
