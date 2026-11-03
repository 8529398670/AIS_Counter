"""Reading .czi files (app/analysis/czi.py), on files written by
tests/czidata.py, and on the example data when it is there."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.analysis.czi import is_czi, read_channels, read_czi
from app.analysis.images import ImageError
from tests.czidata import write_czi

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "example-data/002-czi/11849-1137-974.czi"
EXPORTED = ROOT / "example-data/006-both-tiff/11849-1137-974_b0c0x0-1388y0-1040_ORG.tif"


def planes(H=30, W=40):
    rng = np.random.default_rng(1)
    return {"Alexa Fluor 488": rng.integers(0, 4096, (H, W), dtype=np.uint16),
            "AMCA": rng.integers(0, 4096, (H, W), dtype=np.uint16)}


@pytest.mark.parametrize("tiles", [1, 3])
def test_channels_names_and_pixel_size_read_back(tiles):
    want = planes()
    data = write_czi(want, pixel_um=0.2, tiles=tiles)
    assert is_czi(data)
    got = read_czi(data)
    assert list(got.channels) == ["Alexa Fluor 488", "AMCA"]
    for name in want:
        assert np.array_equal(got.channels[name], want[name])
    assert got.pixel_um == pytest.approx(0.2)
    assert got.bits == 12


def test_display_colors_come_from_zen_or_fall_back():
    got = read_czi(write_czi(planes(), colors={"AMCA": "#000eff"}))
    assert got.colors == {"Alexa Fluor 488": "#00ff33", "AMCA": "#000eff"}   # 488: the first fallback


def test_as_tiff_fills_16_bits_like_the_zen_export():
    want = planes()
    got = read_czi(write_czi(want, bits=12)).as_tiff("Alexa Fluor 488")
    assert np.array_equal(got, want["Alexa Fluor 488"] * 16)
    assert np.array_equal(read_czi(write_czi(want, bits=16)).as_tiff("AMCA"), want["AMCA"])


@pytest.mark.parametrize("kwargs, message", [
    ({"extra": ("Z", 2)}, "single-plane"),
    ({"compression": 1}, "compressed"),
])
def test_files_it_cannot_read_are_refused(kwargs, message):
    with pytest.raises(ImageError, match=message):
        read_czi(write_czi(planes(), **kwargs))


def test_not_a_czi_and_a_missing_channel_are_refused():
    with pytest.raises(ImageError):
        read_czi(b"II*\0" + b"\0" * 100)
    with pytest.raises(ImageError, match="no 'DAPI' channel"):
        read_czi(write_czi(planes())).channel("DAPI")


def test_the_ais_and_soma_channels_are_whatever_the_cell_was_stained_in():
    ais, soma = planes().values()
    usual = read_czi(write_czi({"AMCA": soma, "Alexa Fluor 488": ais}))
    assert (usual.ais_name, usual.soma_name) == ("Alexa Fluor 488", "AMCA")
    other = read_czi(write_czi({"Alexa Fluor 594": ais, "DAPI": soma}))
    assert (other.ais_name, other.soma_name) == ("Alexa Fluor 594", "DAPI")
    alone = read_czi(write_czi({"Alexa Fluor 594": ais}))
    assert (alone.ais_name, alone.soma_name) == ("Alexa Fluor 594", None)


@pytest.mark.skipif(not (EXAMPLE.exists() and EXPORTED.exists()), reason="needs example-data/")
def test_the_ais_channel_is_the_exported_raw_tiff():
    import tifffile

    image = read_czi(EXAMPLE.read_bytes())
    assert np.array_equal(image.as_tiff("Alexa Fluor 488"), tifffile.imread(EXPORTED))
    assert image.pixel_um == pytest.approx(0.16125)


@pytest.mark.skipif(not EXAMPLE.exists(), reason="needs example-data/")
def test_matches_bioio():
    bioio = pytest.importorskip("bioio")
    pytest.importorskip("bioio_czi")
    reference = bioio.BioImage(EXAMPLE)
    image = read_czi(EXAMPLE.read_bytes())
    assert list(image.channels) == [str(n) for n in reference.channel_names]
    for c, name in enumerate(image.channels):
        assert np.array_equal(image.channels[name], reference.get_image_data("YX", C=c, T=0, Z=0))


def test_channel_names_and_colors_read_without_the_pixels():
    data = write_czi(planes(), colors={"AMCA": "#000eff"})
    got = read_czi(data)
    assert read_channels(data) == got.colors
    assert list(read_channels(data)) == list(got.channels)
