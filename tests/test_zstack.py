"""Telling Z-stack slices from other files, and a stack's manifest."""
from __future__ import annotations

import pytest

from app.analysis import zstack

OPTIONS = {"plane": 1, "z_step_um": 0.5, "pixel_um": 0.161}
A, B = "a" * 64, "b" * 64


@pytest.mark.parametrize(("name", "parsed"), [
    ("IP-ApoTome-04_z01c1+2.tif", ("IP-ApoTome-04", 1, "c1+2")),
    ("IP-ApoTome-03_z9c1+2.tif", ("IP-ApoTome-03", 9, "c1+2")),
    ("cell_Z12.TIFF", ("cell", 12, "")),
    ("two_z1_z2.tif", ("two_z1", 2, "")),
    ("a_z003c2.tif", ("a", 3, "c2")),
])
def test_a_slice_gives_its_cell_z_and_ending(name, parsed):
    assert zstack.parse(name) == parsed


@pytest.mark.parametrize("name", [
    "8127-12522-26915_b0c0x0-1388y0-1040_ORG.tif",
    "cell.tif",
    "cell_z1.czi",
    "cell_z.tif",
    "cell_z12345.tif",
    "_z1.tif",
    "cell_z1.tif - Processed method 2.5.tif",
    "cell_z1.tif\n",
    "cell_z١.tif",     # an Arabic digit: \d would take it
])
def test_other_names_are_not_slices(name):
    assert zstack.parse(name) is None


def test_options_keep_what_a_stack_needs():
    assert zstack.clean_options(OPTIONS | {"more": 1}) == OPTIONS


@pytest.mark.parametrize("change", [
    {"plane": 4}, {"plane": -1}, {"plane": None}, {"plane": True}, {"plane": "0"},
    {"z_step_um": 0}, {"z_step_um": -1}, {"z_step_um": None}, {"z_step_um": True}, {"z_step_um": float("nan")},
    {"z_step_um": float("inf")}, {"z_step_um": 101},
    {"pixel_um": 0}, {"pixel_um": "0.161"},
])
def test_options_are_refused_when_they_can_not_be_right(change):
    with pytest.raises(ValueError):
        zstack.clean_options(OPTIONS | change)


def test_a_manifest_is_in_z_order_whatever_order_it_got():
    slices = [{"z": 10, "sha": B, "name": "x"}, {"z": 2, "sha": A}]
    assert [s["z"] for s in zstack.manifest(slices, OPTIONS)["slices"]] == [2, 10]
    assert set(zstack.manifest(slices, OPTIONS)["slices"][0]) == {"z", "sha"}


def test_the_sha_follows_the_stack_and_not_its_order_or_number_types():
    slices = [{"z": 1, "sha": A}, {"z": 2, "sha": B}]
    sha = zstack.sha(zstack.manifest(slices, OPTIONS))
    assert sha == zstack.sha(zstack.manifest(slices[::-1], OPTIONS))
    assert sha == zstack.sha(zstack.manifest(slices, OPTIONS | {"z_step_um": 0.5}))
    whole = OPTIONS | {"z_step_um": 1}
    assert zstack.sha(zstack.manifest(slices, whole)) == zstack.sha(zstack.manifest(slices, whole | {"z_step_um": 1.0}))
    for other in (OPTIONS | {"plane": 0}, OPTIONS | {"z_step_um": 0.6}, OPTIONS | {"pixel_um": 0.2}):
        assert zstack.sha(zstack.manifest(slices, other)) != sha


def test_a_manifest_names_no_files():
    slices = [{"z": 1, "sha": A, "name": "secret.tif", "rel": "secret/secret.tif"}]
    assert b"secret" not in zstack.canonical(zstack.manifest(slices, OPTIONS))
