"""`python -m app view` -- open .czi and .tif images in napari, every channel
as its own layer.

    python -m app view IMAGE        that image; PageUp/PageDown step through
                                    the other images in its folder
    python -m app view FOLDER       every image in the folder, first one shown
    python -m app view A.czi B.tif  just those, in that order

Run it through scripts/view.sh (or view.bat), which first installs
app/requirements-view.txt into .venv: napari and Qt are not in
app/requirements.txt, because the server's Alpine image has no wheels for Qt.

Each channel is a layer named after the channel, blended additively in the
color ZEN gave it (a .czi records one per channel), so the composite looks
like it does in ZEN, and the layer list's eye icons show or hide each one.
Contrast starts at the 0.1-99.9th percentile of each channel. A .czi is shown
in microns, with a scale bar; a .tif in pixels, since the resolution tags in
ours are not a real pixel size.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

SUFFIXES = {".czi", ".tif", ".tiff"}

# For channels with no recorded color, in order: ZEN's usual defaults.
FALLBACK_COLORS = ["#00ff33", "#ff0000", "#0040ff", "#ff00ff", "#ffff00", "#00ffff"]


def images_in(folder):
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in SUFFIXES and not p.name.startswith("."))


def collect(arguments):
    """The images to page through, and which of them to show first."""
    paths = [Path(a).expanduser().resolve() for a in arguments]
    for index, path in enumerate(paths):
        # A path copied from a shell ("A\ B.czi") and then quoted as well keeps
        # its backslashes; drop them when that is the file that exists.
        unescaped = Path(re.sub(r"\\(.)", r"\1", str(path)))
        if not path.exists() and unescaped.exists():
            path = paths[index] = unescaped
        if not path.exists():
            raise ValueError(f"no such file or folder: {path}")
    if len(paths) == 1 and paths[0].is_file():
        siblings = images_in(paths[0].parent)
        return siblings, siblings.index(paths[0]) if paths[0] in siblings else 0
    images = []
    for path in paths:
        images.extend(images_in(path) if path.is_dir() else [path])
    if not images:
        raise ValueError("no .czi or .tif images in " + ", ".join(str(p) for p in paths))
    return images, 0


def czi_colors(image):
    """Each channel's display color from ZEN's metadata ('#FF00FF33' is ARGB), or None."""
    metadata = image.metadata
    if not hasattr(metadata, "findall"):
        return {}
    colors = {}
    for channel in metadata.findall(".//DisplaySetting/Channels/Channel"):
        color = (channel.findtext("Color") or "").lstrip("#")
        if len(color) == 8:
            colors[channel.get("Name")] = "#" + color[2:].lower()
    return colors


def load(path):
    """Layers for one image: (data, add_image keyword arguments) per channel."""
    from bioio import BioImage

    image = BioImage(path)
    is_czi = path.suffix.lower() == ".czi"
    scale = None
    if is_czi:
        sizes = image.physical_pixel_sizes
        if sizes.Y and sizes.X:
            scale = (sizes.Y, sizes.X)

    layers = []
    for scene in image.scenes:
        image.set_scene(scene)
        prefix = f"{scene} · " if len(image.scenes) > 1 else ""
        dims = image.dims
        if "S" in dims.order and dims.S > 1:
            # An RGB tif: one layer, shown as the color image it is.
            data = np.squeeze(image.get_image_data("TZYXS"))
            layers.append((data, dict(name=prefix + path.name, rgb=True)))
            continue
        colors = czi_colors(image) if is_czi else {}
        for index, name in enumerate(image.channel_names):
            # T and Z drop out when there is only one; napari gives the rest sliders.
            data = np.squeeze(image.get_image_data("TZYX", C=index))
            low, high = np.percentile(data, (0.1, 99.9)) if data.size else (0, 1)
            if high <= low:
                high = low + 1
            color = colors.get(str(name)) or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
            if not is_czi:
                # A tif's channels are only "Channel:0:0", "Channel:0:1", ...
                name = f"channel {index + 1}"
                if image.dims.C == 1:
                    color = "#ffffff"
            layers.append((data, dict(
                name=prefix + str(name),
                colormap=_colormap(color),
                blending="additive",
                contrast_limits=(float(low), float(high)),
                scale=(1,) * (data.ndim - 2) + scale if scale else None,
                units=("pixel",) * (data.ndim - 2) + ("um", "um") if scale else None,
            )))
    return layers, scale is not None


def _colormap(color):
    from napari.utils.colormaps import Colormap

    return Colormap(["#000000", color], name=f"zen{color}")


def run(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app view",
        description="Open .czi / .tif images in napari, one layer per channel. "
        "PageUp/PageDown (or [ and ]) step through the images.",
    )
    parser.add_argument("paths", nargs="+", metavar="IMAGE_OR_FOLDER")
    images, start = collect(parser.parse_args(arguments).paths)

    import bioio  # noqa: F401 -- missing, it should fail here, not on the first image
    import napari

    viewer = napari.Viewer()
    state = {"index": start}

    def show(index):
        index %= len(images)
        state["index"] = index
        path = images[index]
        try:
            layers, in_microns = load(path)
        except Exception as error:  # an unreadable file should not end the session
            viewer.status = f"Could not read {path.name}: {error}"
            print(f"Could not read {path}: {error}", file=sys.stderr)
            return
        viewer.layers.clear()
        for data, options in layers:
            viewer.add_image(data, **options)
        # The layers carry the unit; the bar reads it from them.
        viewer.canvas.overlays.scale_bar.visible = in_microns
        viewer.reset_view()
        viewer.title = f"{path.name}  ({index + 1}/{len(images)})  —  {path.parent}"

    for key, step in (("PageDown", 1), ("]", 1), ("PageUp", -1), ("[", -1)):
        viewer.bind_key(key, lambda _viewer, step=step: show(state["index"] + step), overwrite=True)

    show(start)
    napari.run()
