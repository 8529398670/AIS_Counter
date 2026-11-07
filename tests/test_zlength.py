"""Following a trace through a Z-stack, on stacks with a known path."""
from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage as ndi

from app.analysis import zlength

PIXEL_UM = 0.161
Z_STEP = 0.5
SIZE = 96


def path(n=80, x0=8.0, y0=20.0, slope=0.5):
    """A straight diagonal in MATLAB axes: float spline, rounded pixels."""
    t = np.arange(n, dtype=np.float64)
    spline = np.stack([x0 + t, y0 + slope * t], axis=1)
    return spline, np.round(spline).astype(int)


def answer(spline, pixels, start=1, end=None):
    return {"pixels": pixels.tolist(), "spline": spline.tolist(),
            "profile": {"ais_start": start, "ais_end": len(pixels) if end is None else end}}


def stack_with(spline, z_of, slices, brightness=200.0, background=4.0, seed=1):
    """A fibre along spline, at z_of(point index) in slice units (0-based),
    blurred in xy and z as a microscope would."""
    volume = np.zeros((slices, SIZE, SIZE), np.float64)
    for i, (x, y) in enumerate(spline):
        volume[int(round(z_of(i))), int(round(y)) - 1, int(round(x)) - 1] = brightness * 30
    volume = ndi.gaussian_filter(volume, (0.9, 1.4, 1.4)) + background
    noise = np.random.default_rng(seed).normal(0, 1.0, volume.shape)
    return np.clip(volume + noise, 0, 255).astype(np.uint8)


def measure(stack, data, zs=None, z_step=Z_STEP):
    zs = list(range(1, len(stack) + 1)) if zs is None else zs
    return zlength.lift(stack, zlength.slice_levels(stack), zs, data, PIXEL_UM, z_step)


def xy_length(spline):
    return float(np.hypot(*np.diff(spline, axis=0).T).sum()) * PIXEL_UM


def test_a_flat_fibre_is_as_long_in_3d_as_in_xy():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 4, 9)
    got = measure(stack, answer(spline, pixels))
    assert got["length_xy_um"] == pytest.approx(xy_length(spline), rel=0.01)
    assert got["length_3d_um"] == pytest.approx(got["length_xy_um"], rel=0.01)
    assert got["z_start"] == pytest.approx(5, abs=0.3) and got["z_end"] == pytest.approx(5, abs=0.3)


@pytest.mark.parametrize("rise", [2, 4, 6])
def test_a_rising_fibre_reads_its_true_3d_length(rise):
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 1 + rise * i / 79, 9)
    got = measure(stack, answer(spline, pixels))
    want = float(np.hypot(xy_length(spline), rise * Z_STEP))
    assert got["length_3d_um"] == pytest.approx(want, rel=0.02)
    assert got["z_span_um"] == pytest.approx(rise * Z_STEP, abs=0.4)
    assert got["z_end"] > got["z_start"]


def test_length_follows_the_z_step():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 1 + 6 * i / 79, 9)
    data = answer(spline, pixels)
    for z_step in (0.5, 2.0):
        want = float(np.hypot(xy_length(spline), 6 * z_step))
        assert measure(stack, data, z_step=z_step)["length_3d_um"] == pytest.approx(want, rel=0.02)


def test_a_missing_slice_keeps_its_spacing():
    spline, pixels = path()
    whole = stack_with(spline, lambda i: 1 + 6 * i / 79, 9)
    kept = [0, 1, 2, 3, 5, 6, 7, 8]
    with_gap = measure(whole[kept], answer(spline, pixels), zs=[k + 1 for k in kept])
    assert with_gap["z_end"] == pytest.approx(measure(whole, answer(spline, pixels))["z_end"], abs=0.5)
    closed_up = measure(whole[kept], answer(spline, pixels))
    assert with_gap["z_span_um"] > closed_up["z_span_um"]


def test_a_brighter_fibre_crossing_at_another_depth_does_not_take_over():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 2, 9).astype(np.float64)
    other = np.zeros(stack.shape)
    other[7, :, int(spline[40, 0]) - 1] = 255 * 8
    stack = np.clip(stack + ndi.gaussian_filter(other, (0.9, 1.4, 1.4)), 0, 255).astype(np.uint8)
    got = measure(stack, answer(spline, pixels))
    assert np.nanmax(np.array(got["z_path"], float)) < 4.6
    assert got["length_3d_um"] == pytest.approx(got["length_xy_um"], rel=0.02)


def test_only_the_ais_section_is_measured():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 4, 9)
    got = measure(stack, answer(spline, pixels, 21, 60))
    assert got["length_xy_um"] == pytest.approx(xy_length(spline[20:60]), rel=0.02)
    z = got["z_path"]
    assert len(z) == len(pixels)
    assert z[19] is None and z[20] is not None and z[59] is not None and z[60] is None


def test_a_trace_starting_inside_the_ais_is_not_cut_at_the_wrong_end():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 4, 9)
    got = measure(stack, answer(spline, pixels, 0, 40))
    assert got["length_xy_um"] == pytest.approx(xy_length(spline[:40]), rel=0.02)
    assert got["z_path"][0] is not None


def test_an_end_past_the_last_pixel_is_held_to_it():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 4, 9)
    got = measure(stack, answer(spline, pixels, 1, 5000))
    assert got["length_xy_um"] == pytest.approx(xy_length(spline), rel=0.01)


def test_a_section_too_short_to_say_gives_nothing():
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 4, 9)
    assert measure(stack, answer(spline, pixels, 5, 8)) is None


def test_a_fibre_leaving_the_stack_says_so():
    spline, pixels = path()
    assert measure(stack_with(spline, lambda i: 8 * i / 79, 9), answer(spline, pixels))["z_clipped"] == 1
    assert measure(stack_with(spline, lambda i: 3 + 2 * i / 79, 9), answer(spline, pixels))["z_clipped"] == 0


def test_a_dim_end_slice_still_counts():
    """Ends of a stack fall off in brightness; a fibre there is still there."""
    spline, pixels = path()
    stack = stack_with(spline, lambda i: 7, 8).astype(np.float64)
    stack[7] *= 0.4
    rng = np.random.default_rng(2)
    bright = rng.integers(0, 90, stack.shape).astype(np.float64)
    bright[7] *= 0.4
    stack = np.clip(stack + bright * (rng.random(stack.shape) > 0.995), 0, 255).astype(np.uint8)
    assert measure(stack, answer(spline, pixels))["z_clipped"] == 1


def test_near_empty_slices_are_not_scaled_up():
    stack = np.zeros((4, 40, 40), np.uint8)
    stack[0] = 200
    stack[1] = 180
    stack[2] = 160
    stack[3] = 1
    levels = zlength.slice_levels(stack)
    assert levels[3] == pytest.approx(0.25 * np.median(levels[:4]))
    assert (levels > 0).all()


def test_an_all_black_stack_has_levels_it_can_divide_by():
    assert (zlength.slice_levels(np.zeros((3, 20, 20), np.uint8)) >= 1).all()


def test_all_its_numbers_are_finite_and_rounded():
    spline, pixels = path()
    got = measure(stack_with(spline, lambda i: 4, 9), answer(spline, pixels))
    for k in ("length_3d_um", "length_xy_um", "z_start", "z_end", "z_span_um", "z_confidence"):
        assert np.isfinite(got[k]) and got[k] == round(got[k], 3)
    assert 0 <= got["z_confidence"] <= 1
    assert got["z_step_um"] == Z_STEP


def test_a_flat_black_stack_gives_numbers_or_nothing_never_nan():
    spline, pixels = path()
    got = measure(np.zeros((5, SIZE, SIZE), np.uint8), answer(spline, pixels))
    assert got is None or all(np.isfinite(v) for k, v in got.items() if k != "z_path")


def test_only_the_built_method_can_be_chosen():
    assert zlength.method().id == zlength.DEFAULT_METHOD == "trace_lift"
    assert zlength.method("trace_lift").run is zlength.lift
    with pytest.raises(ValueError, match="not built yet"):
        zlength.method("end_clicks")
    with pytest.raises(ValueError, match="not built yet"):
        zlength.method("volume_trace")
    with pytest.raises(ValueError, match="unknown"):
        zlength.method("nothing")


def test_the_three_methods_are_listed():
    assert [(m.id, m.ready) for m in zlength.METHODS] == [("trace_lift", True), ("end_clicks", False), ("volume_trace", False)]
