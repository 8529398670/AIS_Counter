"""Reading TIFFs: tifffile first, Pillow for what it has no codec for.

The dev venv has imagecodecs by way of the viewer's packages; Docker and a
fresh run.sh venv do not. So the fallback is tested in a subprocess that can't
import it, and tifffile's own answer is what it must match.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from app.analysis import images
from app.analysis.images import ImageError, decode_tiff, read_planes, read_tiff

ROOT = Path(__file__).resolve().parents[1]
RNG = np.random.default_rng(4)
RGB = RNG.integers(0, 255, (40, 60, 3), dtype=np.uint8)


def lzw(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    tifffile.imwrite(buf, arr, compression="lzw", photometric="rgb" if arr.ndim == 3 else "minisblack")
    return buf.getvalue()


def without_imagecodecs(tmp_path: Path, data: bytes, call: str) -> dict:
    """{"ok": <call's array as a list>} or {"error": <ImageError's text>}, from
    a Python with no imagecodecs."""
    file = tmp_path / "in.tif"
    file.write_bytes(data)
    script = f"""
import json, sys
sys.modules["imagecodecs"] = None
from app.analysis import images
data = open({str(file)!r}, "rb").read()
try:
    arr = images.{call}(data)
except images.ImageError as exc:
    print(json.dumps({{"error": str(exc)}}))
else:
    print(json.dumps({{"ok": arr.tolist(), "dtype": str(arr.dtype)}}))
"""
    done = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_a_colour_lzw_reads_the_same_with_and_without_imagecodecs(tmp_path):
    data = lzw(RGB)
    got = without_imagecodecs(tmp_path, data, "read_planes")
    assert got["dtype"] == "uint8"
    assert np.array_equal(np.array(got["ok"]), read_planes(data))
    assert np.array_equal(np.array(got["ok"]), RGB)


def test_read_tiff_still_gives_the_first_plane_of_a_colour_lzw(tmp_path):
    got = without_imagecodecs(tmp_path, lzw(RGB), "read_tiff")
    assert np.array_equal(np.array(got["ok"]), RGB[:, :, 0])


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_a_grey_lzw_keeps_its_bit_depth(tmp_path, dtype):
    grey = RNG.integers(0, np.iinfo(dtype).max, (40, 60), dtype=dtype)
    got = without_imagecodecs(tmp_path, lzw(grey), "read_tiff")
    assert got["dtype"] == np.dtype(dtype).name
    assert np.array_equal(np.array(got["ok"]), grey)


def test_a_16_bit_colour_lzw_is_refused_rather_than_cut_to_8_bits(tmp_path):
    arr = RNG.integers(0, 65535, (40, 60, 3), dtype=np.uint16)
    assert "error" in without_imagecodecs(tmp_path, lzw(arr), "read_planes")


def test_pillow_is_not_a_way_in_for_other_formats():
    buf = io.BytesIO()
    Image.fromarray(RGB).save(buf, "PNG")
    with pytest.raises(ImageError, match="not a readable TIFF"):
        decode_tiff(buf.getvalue())


def test_a_page_too_large_to_decode_is_refused_before_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "MAX_SAMPLES", 10)
    with tifffile.TiffFile(io.BytesIO(lzw(RGB))) as tif:
        with pytest.raises(ImageError, match="too large"):
            images._with_pillow(lzw(RGB), tif.pages[0])


def test_an_uncompressed_file_that_fails_is_not_retried():
    data = bytearray(images.tiff_bytes(RGB[:, :, 0]))
    with pytest.raises(ImageError, match="not a readable TIFF"):
        read_tiff(bytes(data[:40]))


def test_grey_is_one_plane():
    arr = RGB[:, :, 0]
    assert read_planes(images.tiff_bytes(arr)).shape == (40, 60, 1)


def test_planes_are_last_however_the_file_stored_them():
    buf = io.BytesIO()
    tifffile.imwrite(buf, np.moveaxis(RGB, -1, 0), photometric="rgb", planarconfig="separate")
    assert np.array_equal(read_planes(buf.getvalue()), RGB)


def test_read_planes_refuses_a_float_image():
    buf = io.BytesIO()
    tifffile.imwrite(buf, RGB[:, :, 0].astype(np.float32))
    with pytest.raises(ImageError):
        read_planes(buf.getvalue())
