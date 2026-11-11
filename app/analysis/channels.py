"""Channel roles: which colour channel of an image is the AIS, which the
soma/dendrite stain, and what the others are called.

The person adding images says this per channel layout (the channels a file
has, by name), and each image keeps it as `image["channels"]`:

    {"role": "czi" | "raw" | "processed" | "stack",   # the file it applies to
     "layout": {"kind": "czi" | "tiff", "names": [...]},
     "roles": [{"role": "ais" | "soma" | "other", "label": "..."}, ...],
     "sha": "<view sha>"}                             # only when not the default

When the choice is what the app would have guessed anyway (default_picks), the
image is traced from its file's own sha as before, so nothing changes for it.
Otherwise the traced file is reached through a view: a small manifest naming
the file and the channels to read, whose sha-256 stands in for the file's sha
the way a Z-stack's does (zstack.py). Every cache and result keyed by sha then
follows the choice, and a different choice is a different sha.

A Z-stack needs no view: its manifest already says which plane is the AIS.

Standard library only, as app/models/ais.py imports it.
"""
from __future__ import annotations

from typing import Any

from app.analysis import zstack

FORMAT = "ais-view"
SUFFIX = ".view"
ROLES = ("ais", "soma", "other")
KINDS = ("czi", "tiff")
MAX_CHANNELS = 16
MAX_NAME = 200
MAX_LABEL = 60

# The channel the AIS is usually stained in, by the name ZEN records, and the
# stains soma.py can read, in order of preference (matched within the name).
AIS_CHANNEL = "Alexa Fluor 488"
SOMA_STAINS = ("AMCA", "DAPI", "Hoechst")
# A colour TIFF's planes, as ZEN's merged export writes them.
RGB_NAMES = ("Red", "Green", "Blue")


class ChannelError(ValueError):
    pass


def tiff_names(count: int, rgb: bool) -> list[str]:
    """What a TIFF's planes are called: Red/Green/Blue for colour, else by number."""
    return [RGB_NAMES[i] if rgb and i < len(RGB_NAMES) else f"Channel {i + 1}" for i in range(count)]


def soma_index(names: list[str]) -> int | None:
    """The channel soma.py reads: the first SOMA_STAINS stain there is."""
    for stain in SOMA_STAINS:
        for i, name in enumerate(names):
            if stain.lower() in name.lower():
                return i
    return None


def ais_index(names: list[str]) -> int:
    """The channel the AIS is traced in: Alexa Fluor 488 when there is one,
    else the first channel that is not the soma's, else the first."""
    if AIS_CHANNEL in names:
        return names.index(AIS_CHANNEL)
    soma = soma_index(names)
    return next((i for i in range(len(names)) if i != soma), 0)


def default_picks(layout: dict[str, Any]) -> tuple[int, int | None]:
    """(AIS, soma) as the app guesses them without being told: by name for a
    .czi, the first plane (and no soma) for a TIFF, as imread(file)(:,:,1)."""
    if layout["kind"] == "czi":
        return ais_index(layout["names"]), soma_index(layout["names"])
    return 0, None


def default_roles(layout: dict[str, Any]) -> list[dict[str, str]]:
    ais, soma = default_picks(layout)
    return [{"role": "ais", "label": ""} if i == ais else {"role": "soma", "label": ""} if i == soma
            else {"role": "other", "label": name} for i, name in enumerate(layout["names"])]


def picks(roles: list[dict[str, str]]) -> tuple[int, int | None]:
    """(AIS, soma) channel indexes of clean roles."""
    ais = next(i for i, r in enumerate(roles) if r["role"] == "ais")
    return ais, next((i for i, r in enumerate(roles) if r["role"] == "soma"), None)


def _text(value: Any, label: str, most: int) -> str:
    if not isinstance(value, str) or len(value) > most:
        raise ChannelError(f"{label} must be text of at most {most} characters")
    return value.strip()


def clean_layout(value: Any) -> dict[str, Any]:
    """{kind, names}, checked."""
    if not isinstance(value, dict) or value.get("kind") not in KINDS:
        raise ChannelError("a layout must say its kind (czi or tiff)")
    names = value.get("names")
    if not isinstance(names, list) or not 1 <= len(names) <= MAX_CHANNELS:
        raise ChannelError(f"a layout must name 1 to {MAX_CHANNELS} channels")
    return {"kind": value["kind"], "names": [_text(n, "a channel name", MAX_NAME) for n in names]}


def clean_roles(value: Any, count: int) -> list[dict[str, str]]:
    """One {role, label} per channel: exactly one AIS, at most one soma, and a
    label for each other channel."""
    if not isinstance(value, list) or len(value) != count:
        raise ChannelError(f"give a role for each of the {count} channels")
    out = []
    for r in value:
        if not isinstance(r, dict) or r.get("role") not in ROLES:
            raise ChannelError("a channel's role must be ais, soma or other")
        label = _text(r.get("label", ""), "a channel's label", MAX_LABEL) if r["role"] == "other" else ""
        if r["role"] == "other" and not label:
            raise ChannelError("name each channel marked other")
        out.append({"role": r["role"], "label": label})
    if sum(r["role"] == "ais" for r in out) != 1:
        raise ChannelError("mark exactly one channel as the AIS")
    if sum(r["role"] == "soma" for r in out) > 1:
        raise ChannelError("mark at most one channel as soma/dendrite")
    return out


def clean_choices(value: Any) -> list[dict[str, Any]]:
    """What the person adding images said: [{layout, roles}], one per layout."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 100:
        raise ChannelError("channels must be a list of layouts")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise ChannelError("each channel layout must be an object")
        layout = clean_layout(item.get("layout"))
        out.append({"layout": layout, "roles": clean_roles(item.get("roles"), len(layout["names"]))})
    return out


def same(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    return bool(a and b) and a["kind"] == b["kind"] and a["names"] == b["names"]


def summarize(found: list[tuple[dict[str, Any], list[str] | None]],
              roles: list[list[dict[str, str]] | None] | None = None) -> list[dict[str, Any]]:
    """Files' (layout, colors) -> one entry per layout, in the order first
    met: {layout, colors, count, roles}. roles, one per file where known, are
    the roles in use (the first met for each layout), else default_roles."""
    out: list[dict[str, Any]] = []
    for i, (layout, colors) in enumerate(found):
        here = next((o for o in out if same(o["layout"], layout)), None)
        if here is None:
            here = {"layout": layout, "colors": colors, "count": 0, "roles": None}
            out.append(here)
        here["count"] += 1
        if here["roles"] is None and roles and roles[i]:
            here["roles"] = roles[i]
    for o in out:
        o["roles"] = o["roles"] or default_roles(o["layout"])
    return out


def manifest(source: str, ais: int, soma: int | None) -> dict[str, Any]:
    """A view as data: the file and the channels read from it."""
    return {"format": FORMAT, "source": source, "ais": ais, "soma": soma}


def sha(data: dict[str, Any]) -> str:
    return zstack.sha(data)


def is_view(data: Any) -> bool:
    return (isinstance(data, dict) and data.get("format") == FORMAT and isinstance(data.get("source"), str)
            and isinstance(data.get("ais"), int) and (data.get("soma") is None or isinstance(data.get("soma"), int)))


def entry(role: str, layout: dict[str, Any], roles: list[dict[str, str]], source_sha: str | None) -> dict[str, Any]:
    """An image's `channels`, with the view sha when it needs one (see the
    module docstring). A stack never does; source_sha is None for it."""
    out = {"role": role, "layout": layout, "roles": roles}
    chosen = picks(roles)
    if source_sha and chosen != default_picks(layout):
        out["sha"] = sha(manifest(source_sha, *chosen))
    return out
