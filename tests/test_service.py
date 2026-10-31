"""The JSON one click produces, on a synthetic image (no example data needed)."""
from __future__ import annotations

import numpy as np

from app.analysis import ais_auto as aa
from app.analysis.service import run_click


def synthetic() -> tuple[np.ndarray, np.ndarray]:
    """A dim curved 'axon' with a bright segment, plus a brighter blob
    elsewhere so the clicked component does not hold the image max."""
    H, W = 200, 260
    yy, xx = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W))
    for t in np.linspace(0, 1, 400):
        cx, cy = 40 + 160 * t, 100 + 30 * np.sin(3 * t)
        amp = 3000 + 9000 * np.exp(-((t - 0.4) / 0.15) ** 2)
        img += amp * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / 8) / 40
    img += 40000 * np.exp(-((xx - 220) ** 2 + (yy - 30) ** 2) / 30)
    pic = np.clip(img, 0, 65535).astype(np.uint16)
    return pic, pic.copy()


def test_click_returns_trace_and_length():
    pic, raw = synthetic()
    prep = aa.PreparedImage.from_array(pic)
    out = run_click(prep, raw, (38.0, 101.0), None, 0.01)
    assert out["rethresholded"] is True
    assert out["threshold"] < out["threshold_initial"] == 0.01
    assert out["ok"], out["error"]
    assert len(out["path"]) > 20
    assert out["measures"]["length_str"] == f"{out['measures']['length_um']:.6g}"
    assert out["shape"]["width_um"] > 0 and out["shape"]["brightness"] > 0
    assert out["clicks"] == [[38, 101], [38, 101]]


def test_click_without_raw_stops_after_trace():
    pic, _ = synthetic()
    out = run_click(aa.PreparedImage.from_array(pic), None, (38.0, 101.0), None, 0.01)
    assert not out["ok"] and out["path"] and "raw" in out["error"]


def test_single_image_is_traced_and_profiled_from_itself(tmp_path):
    from app.analysis.service import SINGLE_NOTE, Library

    pic, raw = synthetic()
    lib = Library(tmp_path)
    sha = lib.add(_tiff_bytes(pic))["sha256"]
    out = lib.trace(sha, None, (38.0, 101.0), None, 0.01)
    assert out["ok"], out["error"]
    assert out["notes"][0] == SINGLE_NOTE
    # The synthetic raw is a copy of the processed image, so the pair gives the same length.
    paired = run_click(aa.PreparedImage.from_array(pic), raw, (38.0, 101.0), None, 0.01)
    assert out["measures"]["length_um"] == paired["measures"]["length_um"]


def _tiff_bytes(arr) -> bytes:
    import io

    import tifffile

    buf = io.BytesIO()
    tifffile.imwrite(buf, arr)
    return buf.getvalue()


def test_store_is_shared_and_finds_legacy_and_local_files(tmp_path):
    import hashlib

    from app.analysis.images import ImageError
    from app.analysis.service import Library

    pic, _ = synthetic()
    data = _tiff_bytes(pic)
    sha = hashlib.sha256(data).hexdigest()
    lib = Library(tmp_path / "s")
    assert not lib.has(sha)
    # a file an older version stored per user moves into the shared store
    legacy = tmp_path / "s" / "ais" / "7" / f"{sha}.tif"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(data)
    assert lib.file_path(sha) == tmp_path / "s" / "ais" / "files" / f"{sha}.tif" and not legacy.exists()
    # an Open-path file is copied in on demand, only if its bytes still match
    other = _tiff_bytes(pic + 1)
    other_sha = hashlib.sha256(other).hexdigest()
    (tmp_path / "on-disk.tif").write_bytes(other)
    lib2 = Library(tmp_path / "t", resolver=lambda s: str(tmp_path / "on-disk.tif") if s == other_sha else None)
    assert lib2.file_path(other_sha).read_bytes() == other
    (tmp_path / "changed.tif").write_bytes(data)
    lib3 = Library(tmp_path / "u", resolver=lambda s: str(tmp_path / "changed.tif"))
    try:
        lib3.file_path(other_sha)
        raise AssertionError("a changed file must not be accepted")
    except ImageError:
        pass
    assert lib.thumbnail(sha).startswith(b"\x89PNG")
