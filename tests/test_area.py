"""AIS area and volume (app/analysis/area.py) on shapes whose answer is known."""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.analysis import area

PX = 0.2


def bar(rows=10, cols=60, at=(20, 20), shape=(50, 100)):
    """A blob rows x cols, its box's top-left 0-based at, and a trace along
    its middle row, 1-based [x, y]."""
    sel = np.zeros(shape, bool)
    r0, c0 = at
    sel[r0:r0 + rows, c0:c0 + cols] = True
    y = r0 + rows // 2 + 1
    return sel, [[x, y] for x in range(c0 + 1, c0 + cols + 1)]


def test_a_bar_s_area_is_its_pixels_and_its_widths_times_length():
    sel, pixels = bar()
    out = area.areas(sel, 0, 0, pixels, 1, len(pixels), PX)
    assert out["area_blob_um2"] == pytest.approx(10 * 60 * PX * PX)
    # widths: twice the distance to the edge (about the 10 rows), over 59 steps of one pixel
    assert out["area_width_um2"] == pytest.approx(10 * 59 * PX * PX, rel=0.15)
    assert len(out["widths_um"]) == len(pixels)


def test_only_the_measured_section_counts():
    sel, pixels = bar()
    whole = area.areas(sel, 0, 0, pixels, 1, 60, PX)
    half = area.areas(sel, 0, 0, pixels, 1, 30, PX)
    assert half["area_blob_um2"] == pytest.approx(whole["area_blob_um2"] / 2, rel=0.05)
    assert half["area_width_um2"] == pytest.approx(whole["area_width_um2"] / 2, rel=0.1)
    assert len(half["widths_um"]) == 30


def test_a_blob_in_a_box_offset_on_the_image_is_found_as_well():
    sel, pixels = bar(at=(0, 0), shape=(10, 60))
    out = area.areas(sel, 20, 20, [[x + 20, y + 20] for x, y in pixels], 1, 60, PX)
    assert out["area_blob_um2"] == pytest.approx(10 * 60 * PX * PX)


def tube_stack(slices=7, lit=(2, 3, 4), rows=10, cols=60):
    """A bar bright in the slices lit only, on a dim noisy background."""
    rng = np.random.default_rng(0)
    stack = rng.normal(10, 1, (slices, 50, 100))
    for s in lit:
        stack[s, 20:20 + rows, 20:20 + cols] += 200
    return stack


def test_volume_by_voxels_counts_the_lit_slices_and_as_a_tube_uses_the_widths():
    sel, pixels = bar()
    widths = [2.0] * len(pixels)               # µm: 10 px at 0.2
    answer = {"pixels": pixels, "shape": {"widths_um": widths}}
    z_path = [3.0] * len(pixels)               # flat at slice 3
    stack = tube_stack()
    levels = np.full(stack.shape[0], 210.0)
    out = area.volumes(stack, levels, answer, z_path, PX, 0.5)
    assert out["volume_voxel_um3"] == pytest.approx(3 * 10 * 60 * PX * PX * 0.5, rel=0.1)
    assert out["volume_tube_um3"] == pytest.approx(math.pi * 1.0 ** 2 * 59 * PX, rel=0.01)


def test_a_rising_path_makes_the_tube_longer():
    sel, pixels = bar()
    answer = {"pixels": pixels, "shape": {"widths_um": [2.0] * len(pixels)}}
    flat = area.volumes(tube_stack(), np.full(7, 210.0), answer, [3.0] * 60, PX, 0.5)
    rising = area.volumes(tube_stack(), np.full(7, 210.0), answer, list(np.linspace(1, 5, 60)), PX, 0.5)
    assert rising["volume_tube_um3"] > flat["volume_tube_um3"]


def test_no_volume_without_a_lifted_section():
    sel, pixels = bar()
    answer = {"pixels": pixels, "shape": {"widths_um": [2.0]}}
    assert area.volumes(tube_stack(), np.full(7, 210.0), answer, [None] * 60, PX, 0.5) is None
