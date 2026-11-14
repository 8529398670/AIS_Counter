"""Reading .czi files (app/analysis/czi.py), on files written by
tests/czidata.py, and on the example data when it is there."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.analysis.czi import is_czi, read_channels, read_czi, read_header, read_stack
from app.analysis.images import ImageError
from tests.czidata import apotome_phases, write_czi, write_czi_stack

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "example-data/002-czi/11849-1137-974.czi"
EXPORTED = ROOT / "example-data/006-both-tiff/11849-1137-974_b0c0x0-1388y0-1040_ORG.tif"
STACK = ROOT / "example-data-4/Slide7zstackExperiment-27.czi"
STACK_TIFF = ROOT / "example-data-3/Slide7zstack_27_IP-ApoTome-04/IP-ApoTome-04_z06c1+2.tif"


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


# Z-stacks (docs/z-stack.md)

def volume(Z=4, H=12, W=16, seed=2):
    return np.random.default_rng(seed).integers(0, 4096, (Z, H, W), dtype=np.uint16)


@pytest.mark.parametrize("tiles, shuffle", [(1, False), (3, True)])
def test_a_stack_reads_back_in_z_order_on_the_tiff_scale(tiles, shuffle):
    ais, other = volume(), volume(seed=5)
    data = write_czi_stack({"Alexa Fluor 594": other, "Alexa Fluor 488": ais}, tiles=tiles, shuffle=shuffle)
    assert np.array_equal(read_stack(data, 1, None), ais * 16)
    assert np.array_equal(read_stack(data, 0, None, [2, 0]), other[[2, 0]] * 16)
    header = read_header(data)
    assert (header.names, header.slices, header.phases, header.width, header.height, header.bits) == \
        (["Alexa Fluor 594", "Alexa Fluor 488"], 4, 1, 16, 12, 12)
    assert header.pixel_um == pytest.approx(0.10238) and header.z_step_um == pytest.approx(0.77)
    assert list(read_channels(data)) == header.names


def test_apotome_phases_give_the_section_or_the_widefield_image():
    rng = np.random.default_rng(4)
    amplitude = rng.integers(0, 600, (3, 10, 14)).astype(float)
    mean = rng.integers(800, 2000, (3, 10, 14)).astype(float)
    phases = np.stack([apotome_phases(amplitude[z], mean[z]) for z in range(3)])   # (Z, H, Y, X)
    data = write_czi_stack({"Alexa Fluor 488": phases}, shuffle=True)
    assert read_header(data).phases == 5
    sectioned = read_stack(data, 0, "sectioned").astype(float)
    widefield = read_stack(data, 0, "widefield").astype(float)
    assert np.abs(sectioned - amplitude * 16).max() <= 2 * 16    # the grid's amplitude, rounding aside
    assert np.abs(widefield - mean * 16).max() <= 16
    with pytest.raises(ImageError, match="sectioned or widefield"):
        read_stack(data, 0, None)
    with pytest.raises(ImageError, match="no ApoTome"):
        read_stack(write_czi_stack({"Alexa Fluor 488": volume()}), 0, "sectioned")


def test_a_stack_without_z_scaling_has_no_z_step():
    assert read_header(write_czi_stack({"Alexa Fluor 488": volume()}, z_um=None)).z_step_um is None


def test_a_stack_read_as_one_plane_says_what_it_is():
    data = write_czi_stack({"Alexa Fluor 488": volume()})
    with pytest.raises(ImageError, match=r"Z-stack \(4 slices\)"):
        read_czi(data)


@pytest.mark.parametrize("kwargs, message", [
    ({"drop": 3}, "missing slices"),
    ({"extra": ("T", 0, 2)}, "one scene and time point"),
])
def test_stacks_it_cannot_read_are_refused(kwargs, message):
    data = write_czi_stack({"Alexa Fluor 594": volume(seed=1), "Alexa Fluor 488": volume()}, **kwargs)
    with pytest.raises(ImageError, match=message):
        read_header(data)
    with pytest.raises(ImageError, match=message):
        read_stack(data, 0, None)


def test_a_single_plane_czi_has_a_header_too():
    header = read_header(write_czi(planes(), tiles=3))
    assert (header.slices, header.phases, header.z_step_um) == (1, 1, None)


@pytest.mark.skipif(not (STACK.exists() and STACK_TIFF.exists()), reason="needs example-data-4/ and example-data-3/")
def test_the_sample_stack_sections_like_zen():
    import mmap

    from PIL import Image

    with STACK.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        header = read_header(data)
        assert (header.slices, header.phases, header.names) == (11, 5, ["Alexa Fluor 594", "Alexa Fluor 488"])
        assert header.pixel_um == pytest.approx(0.10238, abs=1e-5) and header.z_step_um == pytest.approx(0.77)
        section = read_stack(data, 1, "sectioned", [5])[0].astype(float)
    green = np.asarray(Image.open(STACK_TIFF))[..., 1].astype(float)
    assert np.corrcoef(section.ravel(), green.ravel())[0, 1] >= 0.98
