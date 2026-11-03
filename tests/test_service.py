"""The JSON one click produces, on a synthetic image (no example data needed)."""
from __future__ import annotations

import struct

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

    from app.analysis.service import Library, NotStored

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
    except NotStored:
        pass
    assert lib.thumbnail(sha).startswith(b"\x89PNG")


def test_preview_is_kept_after_the_first_request(tmp_path):
    from app.analysis.service import Library

    pic, _ = synthetic()
    lib = Library(tmp_path / "s")
    sha = lib.add(_tiff_bytes(pic))["sha256"]
    first = lib.preview(sha)
    assert first.startswith(b"\x89PNG")
    # the second comes from memory, even with the file gone from disk
    lib.file_path(sha).unlink()
    lib._arrays.clear()
    assert lib.preview(sha) is first


def test_a_czi_is_traced_on_its_processed_ais_channel_and_finds_somata(tmp_path):
    import pytest

    from app.analysis import preprocess
    from app.analysis.images import ImageError
    from app.analysis.service import Library
    from tests.czidata import write_czi

    ais_channel = (synthetic()[0] >> 4).astype(np.uint16)     # 12-bit, as the camera gives
    H, W = ais_channel.shape
    yy, xx = np.mgrid[0:H, 0:W]
    amca = (800 + 1500 * np.exp(-((yy - 100) ** 2 + (xx - 30) ** 2) / (2 * 25.0 ** 2))).astype(np.uint16)
    library = Library(tmp_path)
    info = library.add(write_czi({"Alexa Fluor 488": ais_channel, "AMCA": amca}))
    sha = info["sha256"]
    assert info["czi"] and (tmp_path / "ais" / "files" / f"{sha}.czi").exists()
    assert library.is_czi(sha) and library.has(sha)
    assert np.array_equal(library.array(sha), ais_channel * 16)
    assert np.array_equal(library.prepared(sha).pic, aa.PreparedImage.from_array(preprocess.processed(ais_channel * 16)).pic)
    assert library.soma(sha).mask[100, 30]
    clicked = library.trace(sha, None, (38.0, 101.0), None, 0.01)
    assert clicked["ok"] and "single image" not in " ".join(clicked["notes"])
    found = library.detect(sha, None, 0.01, start="soma")
    assert "somata" in found and all("soma_gap_um" in c for c in found["candidates"])

    # The channel buttons: each channel with its color, as a PNG of the image's
    # size; the main view is the processed image that is traced.
    from app.analysis.images import preview_png

    assert [(c["index"], c["name"]) for c in library.channels(sha)] == [(0, "Alexa Fluor 488"), (1, "AMCA")]
    png = library.channel_png(sha, 1)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (W, H)
    assert library.preview(sha) == preview_png(preprocess.processed(ais_channel * 16))
    with pytest.raises(ImageError):
        library.channel_png(sha, 2)

    # MATLAB gets the pair it is traced from, as TIFFs: processed and raw.
    from app.analysis.images import read_tiff

    processed_tiff, raw_tiff = library.matlab_pair(sha, None)
    assert np.array_equal(read_tiff(processed_tiff), preprocess.processed(ais_channel * 16))
    assert np.array_equal(read_tiff(raw_tiff), ais_channel * 16)

    tiff = library.add(_tiff(synthetic()[0]))["sha256"]
    assert library.matlab_pair(tiff, None) == (_tiff(synthetic()[0]), None)
    assert not library.is_czi(tiff) and library.soma(tiff) is None
    assert library.channels(tiff) == []
    with pytest.raises(ImageError, match="czi"):
        library.detect(tiff, None, 0.01, start="soma")

    # Another staining: the AIS in 594 is traced, and with no soma stain
    # there are no somata, so only the Soma start is refused.
    other = library.add(write_czi({"Alexa Fluor 594": ais_channel}))["sha256"]
    assert np.array_equal(library.array(other), ais_channel * 16)
    assert library.soma(other) is None
    assert library.detect(other, None, 0.01)["candidates"]
    with pytest.raises(ImageError, match="soma channel"):
        library.detect(other, None, 0.01, start="soma")

    # Only a file the server does not have is NotStored (the page calls it
    # "not uploaded"); one it has but cannot read is a plain ImageError.
    from app.analysis.service import NotStored

    with pytest.raises(NotStored):
        library.preview("0" * 64)


def _tiff(arr: np.ndarray) -> bytes:
    import io

    import tifffile

    buffer = io.BytesIO()
    tifffile.imwrite(buffer, arr)
    return buffer.getvalue()


def test_a_czi_exports_its_channels_and_processed_image_as_tiffs(tmp_path):
    import io

    import pytest
    import tifffile

    from app.analysis import preprocess
    from app.analysis.czi import read_czi
    from app.analysis.images import ImageError
    from app.analysis.service import Library
    from tests.czidata import write_czi

    ais_channel = (synthetic()[0] >> 4).astype(np.uint16)
    data = write_czi({"Alexa Fluor 488": ais_channel, "AMCA": ais_channel[::-1].copy()})
    library = Library(tmp_path)
    sha = library.add(data)["sha256"]
    planes = list(read_czi(data).channels.values())
    for i, plane in enumerate(planes):
        out = tifffile.imread(io.BytesIO(library.channel_tiff(sha, i)))
        assert out.dtype == np.uint16 and np.array_equal(out, plane)
    assert np.array_equal(tifffile.imread(io.BytesIO(library.processed_tiff(sha))), preprocess.processed(library.array(sha)))
    with pytest.raises(ImageError):
        library.channel_tiff(sha, len(planes))
    tiff = library.add(library.channel_tiff(sha, 0))["sha256"]
    with pytest.raises(ImageError):
        library.processed_tiff(tiff)


def _rgb(png: bytes) -> np.ndarray:
    """The pixels of an RGB PNG as composite_png writes it."""
    import zlib

    w, h = struct.unpack(">II", png[16:24])
    assert png[24:26] == bytes([8, 2])   # 8-bit RGB
    size = struct.unpack(">I", png[33:37])[0]
    rows = np.frombuffer(zlib.decompress(png[41:41 + size]), np.uint8).reshape(h, 1 + 3 * w)
    return rows[:, 1:].reshape(h, w, 3)


def test_a_composite_shows_each_channel_in_its_color():
    from app.analysis.images import composite_png

    green = np.zeros((20, 30), np.uint16)
    blue = np.zeros((20, 30), np.uint16)
    green[:10] = 4000
    blue[:, :15] = 4000
    pixels = _rgb(composite_png([green, blue], ["#00ff00", "#0000ff"], (0.1, 99.9)))
    assert pixels.shape == (20, 30, 3)
    assert pixels[0, 29].tolist() == [0, 255, 0]      # green only
    assert pixels[19, 0].tolist() == [0, 0, 255]      # blue only
    assert pixels[0, 0].tolist() == [0, 255, 255]     # both add up
    assert pixels[19, 29].tolist() == [0, 0, 0]
    # A flat channel adds nothing rather than dividing by zero.
    assert not _rgb(composite_png([np.ones((5, 5), np.uint16)], ["#ffffff"], (0.1, 99.9))).any()


def test_a_library_composites_a_czi_and_keeps_its_channel_list(tmp_path):
    import pytest

    from app.analysis.images import ImageError
    from app.analysis.service import Library
    from tests.czidata import write_czi

    rng = np.random.default_rng(2)
    planes = {name: rng.integers(0, 4096, (24, 32), dtype=np.uint16) for name in ("Alexa Fluor 488", "AMCA")}
    library = Library(tmp_path)
    sha = library.add(write_czi(planes))["sha256"]
    assert _rgb(library.composite_png(sha)).shape == (24, 32, 3)
    found = library.channels(sha)
    assert [c["name"] for c in found] == list(planes)
    library.file_path(sha).unlink()
    assert library.channels(sha) == found   # a sha's channels never change
    tiff = library.add(_tiff(synthetic()[0]))["sha256"]
    with pytest.raises(ImageError):
        library.composite_png(tiff)
