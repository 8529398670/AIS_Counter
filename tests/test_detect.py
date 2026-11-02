"""Auto mode (app/analysis/detect.py) on synthetic images."""
from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage as ndi

from app.analysis import ais_auto as aa
from app.analysis.detect import detect, fitted_seed, reaches_end, skeleton_ends, skeleton_path, trace_contrast
from app.analysis.service import run_click
from app.analysis.soma import Somata


def rods(slope: float = 0.0, scale=(1.0, 1.0), spread=(8.0, 8.0)) -> np.ndarray:
    """Two separate straight 'AIS', each brightest in its middle (plus
    slope along x), and a brighter blob, so each component re-thresholds.
    scale and spread set each rod's brightness and (squared) width."""
    H, W = 200, 300
    yy, xx = np.mgrid[0:H, 0:W]
    img = np.zeros((H, W))
    for y0, k, s2 in zip((60, 140), scale, spread):
        for t in np.linspace(0, 1, 300):
            cx = 50 + 180 * t
            amp = (3000 + 9000 * np.exp(-((t - 0.5) / 0.2) ** 2)) * (1 + slope * t) * k
            img += amp * np.exp(-((xx - cx) ** 2 + (yy - y0) ** 2) / s2) / 40
    img += 40000 * np.exp(-((xx - 280) ** 2 + (yy - 15) ** 2) / 30)
    return np.clip(img, 0, 65535).astype(np.uint16)


def test_finds_each_rod_once_and_matches_a_click_at_its_seed():
    pic = rods()
    prep = aa.PreparedImage.from_array(pic)
    out = detect(prep, pic)
    rows = sorted(c["seed"][1] for c in out["candidates"] if len(c["path"]) > 100)
    assert len(rows) == 2 and abs(rows[0] - 60) <= 3 and abs(rows[1] - 140) <= 3
    # A candidate is exactly what clicking its seed gives.
    c = out["candidates"][0]
    clicked = run_click(prep, pic, tuple(float(v) for v in c["seed"]), None, 0.01)
    assert clicked["measures"] == c["measures"] and clicked["path"] == c["path"]
    assert "skeleton" not in c and "edge" not in c["component"]


def test_already_accepted_traces_are_not_found_again():
    pic = rods()
    prep = aa.PreparedImage.from_array(pic)
    first = detect(prep, pic)
    long_ones = [c for c in first["candidates"] if len(c["path"]) > 100]
    again = detect(prep, pic, exclude=[long_ones[0]["pixels"]])
    assert again["known"] >= 1
    assert len([c for c in again["candidates"] if len(c["path"]) > 100]) == len(long_ones) - 1


def test_brighter_and_dimmer_start_at_opposite_ends():
    pic = rods(slope=2.0)          # brighter towards larger x
    prep = aa.PreparedImage.from_array(pic)
    bright = [c for c in detect(prep, pic, start="brighter")["candidates"] if len(c["path"]) > 100]
    dim = [c for c in detect(prep, pic, start="dimmer")["candidates"] if len(c["path"]) > 100]
    assert bright and dim
    assert all(c["seed"][0] > 150 for c in bright)
    assert all(c["seed"][0] < 150 for c in dim)


def test_skeleton_ends_are_the_far_ends_of_a_line():
    skel = np.zeros((20, 40), bool)
    skel[10, 5:35] = True
    skel[5:10, 20] = True          # a short side branch
    ends = sorted(skeleton_ends(skel, (10, 20)))
    assert ends == [(10, 5), (10, 34)]


def test_candidates_say_how_wide_and_bright_they_are():
    # The lower rod is half as bright and thinner.
    pic = rods(scale=(1.0, 0.6), spread=(8.0, 4.0))
    found = [c for c in detect(aa.PreparedImage.from_array(pic), pic)["candidates"] if len(c["path"]) > 100]
    top, low = sorted(found, key=lambda c: c["seed"][1])
    assert 0 < low["shape"]["brightness"] < 0.75 * top["shape"]["brightness"] <= 1
    assert 0 < low["shape"]["width_um"] < top["shape"]["width_um"]


def _soma_at(shape, col: int) -> Somata:
    """A soma straddling both rods at column col (0-based)."""
    mask = np.zeros(shape, bool)
    mask[:, max(col - 15, 0):col + 15] = True
    gap = (ndi.distance_transform_edt(~mask) * aa.DEFAULT.pixconv).astype(np.float32)
    return Somata(mask, gap, [[[col + 1, 1]]])


def test_soma_start_traces_from_the_end_nearer_a_soma():
    pic = rods()
    prep = aa.PreparedImage.from_array(pic)
    for col, near in ((20, lambda x: x < 150), (260, lambda x: x > 150)):
        out = detect(prep, pic, start="soma", soma=_soma_at(pic.shape, col))
        found = [c for c in out["candidates"] if len(c["path"]) > 100]
        assert found and all(near(c["seed"][0]) and near(c["pixels"][0][0]) for c in found)
        assert all(c["soma_gap_um"] < 5 for c in found)
        assert out["somata"] == [[[col + 1, 1]]]


def test_soma_start_needs_somata():
    pic = rods()
    with pytest.raises(ValueError):
        detect(aa.PreparedImage.from_array(pic), pic, start="soma")


def test_skeleton_path_walks_from_one_end_to_the_other():
    skel = np.zeros((20, 40), bool)
    skel[10, 5:35] = True
    skel[5:10, 20] = True
    path = skeleton_path(skel, (10, 5), (10, 34))
    assert path[0] == (10, 5) and path[-1] == (10, 34) and len(path) == 30
    assert skeleton_path(skel, (10, 5), (0, 0)) == []


def test_fitted_seed_goes_further_in_when_the_rise_is_later():
    path = [(10, c) for c in range(200)]
    for rise in (20, 80):
        img = np.zeros((20, 200))
        img[:, rise:] = 1000.0
        r, c = fitted_seed(path, img, 0.161)
        # 0.5 * (where it has risen a third of the way) + 2 um, in pixels
        assert r == 10 and abs(c - (0.5 * (rise - 6) + 2 / 0.161)) <= 2


def test_reaches_end_needs_the_profile_to_fall_after_its_peak():
    def found(norm, peak):
        return {"ok": True, "profile": {"norm_lv": norm, "max_i": peak, "f": 0.33}}
    assert reaches_end(found([0.1, 1.0, 0.8, 0.5], 2))
    assert not reaches_end(found([0.1, 0.5, 1.0], 3))
    assert not reaches_end({"ok": False})


def test_fitted_judges_as_both_and_traces_from_inside_the_brighter_end():
    pic = rods(slope=2.0)          # brighter towards larger x
    prep = aa.PreparedImage.from_array(pic)
    both = {c["seed"][1] // 10: c for c in detect(prep, pic, start="both")["candidates"] if len(c["path"]) > 100}
    fitted = [c for c in detect(prep, pic, start="fitted")["candidates"] if c["filter"]["length_um"] > 15]
    assert len(fitted) == len(both) == 2
    for c in fitted:
        gate = both[c["seed"][1] // 10]
        assert c["filter"]["length_um"] == gate["measures"]["length_um"]
        assert c["filter"]["brightness"] == gate["shape"]["brightness"]
        assert 0.95 < c["filter"]["branchiness"] < 1.1     # one straight rod
        assert c["seed"][0] > 150                           # in from the brighter end
        clicked = run_click(prep, pic, tuple(float(v) for v in c["seed"]), None, 0.01)
        assert clicked["measures"] == c["measures"]


def test_a_forked_blob_is_more_branched_than_a_rod():
    pic = rods().astype(np.float64)
    yy, xx = np.mgrid[0:pic.shape[0], 0:pic.shape[1]]
    for t in np.linspace(0, 1, 200):    # a branch off the upper rod
        pic += 9000 * np.exp(-((xx - (140 + 60 * t)) ** 2 + (yy - (60 + 50 * t)) ** 2) / 8.0) / 40
    pic = np.clip(pic, 0, 65535).astype(np.uint16)
    found = detect(aa.PreparedImage.from_array(pic), pic, start="fitted")["candidates"]
    upper = max((c for c in found if c["seed"][1] < 100), key=lambda c: c["filter"]["length_um"])
    lower = max((c for c in found if c["seed"][1] > 120), key=lambda c: c["filter"]["length_um"])
    assert upper["filter"]["branchiness"] > lower["filter"]["branchiness"] + 0.1


def test_contrast_is_the_ais_over_the_background_around_it():
    img = np.full((100, 120), 1000.0)
    img[49:52, 20:81] = 3000.0                       # a 3 px wide line
    found = {"pixels": [[x + 1, 51] for x in range(20, 81)], "profile": {"ais_start": 21.0, "ais_end": 41.0}}
    assert trace_contrast(found, img, ndi.uniform_filter(img, 3), 4000.0) == pytest.approx(0.5)
    # The same AIS on a brighter background stands out as much.
    img += 500.0
    assert trace_contrast(found, img, ndi.uniform_filter(img, 3), 4000.0) == pytest.approx(0.5)


def test_fitted2_traces_as_fitted_and_adds_contrast():
    pic = rods(slope=2.0)
    prep = aa.PreparedImage.from_array(pic)
    fitted = detect(prep, pic, start="fitted")["candidates"]
    fitted2 = detect(prep, pic, start="fitted2")["candidates"]
    assert len(fitted2) == len(fitted) == 2
    for a, b in zip(fitted, fitted2):
        assert "contrast" not in a["filter"]
        assert b["pixels"] == a["pixels"] and b["measures"] == a["measures"]
        f = dict(b["filter"])
        assert 0 < f.pop("contrast") < 1 and f == a["filter"]
