"""Method settings: validation, and the ais_auto.m edits that carry them to MATLAB."""
from __future__ import annotations

import numpy as np
import pytest

from app.analysis import ais_auto as aa
from app.analysis import mlcompat as ml
from app.analysis.matlab import ORIGINAL_CODE, apply_patches


def test_defaults_are_the_originals():
    s = aa.Settings()
    assert (s.pixconv, s.f, s.kernel, s.sigma, s.strel) == (0.161, 0.33, 20, 2, 3)
    assert (s.min_pixels, s.max_path, s.max_passes, s.spline_p, s.window_um) == (70, 300, 10, 0.3, 1.5)
    assert s.slide_d == 10 and s.patches() == [] and s.changed() == {}
    assert aa.Settings.from_dict(None) == s == aa.Settings.from_dict({})


@pytest.mark.parametrize("bad", [
    {"smooth": "average"}, {"kernel": 2.5}, {"kernel": 0}, {"f": 1.5}, {"sigma": "2"},
    {"strel": True}, {"nope": 1}, {"pixconv": 0},
])
def test_bad_settings_are_refused(bad):
    with pytest.raises(ValueError):
        aa.Settings.from_dict(bad)


def test_every_constant_patch_matches_the_original():
    s = aa.Settings(kernel=15, sigma=2.5, strel=5, min_pixels=50, max_path=400, max_passes=5,
                    spline_p=0.5, window_um=2.0, pixconv=0.2, f=0.4)
    text = (ORIGINAL_CODE / "ais_auto.m").read_text()
    patched = apply_patches(text, s.patches())
    for line in ("pixconv=0.2;", "f = 0.4;", "fspecial(smooth,[15 15],2.5)", "numPixels<50",
                 "length(Xais)>400", "loop2>5", "csaps(t,xy,0.5,ts)", "width = (2/(pixconv))"):
        assert line in patched
    assert patched.count("strel('square',5)") == 2
    assert len(patched.splitlines()) == len(text.splitlines())


def test_matlab_number_text_round_trips():
    for x in (0.161, 0.1 + 0.2, 1e-5, 2.0, 7):
        assert float(aa._m(x)) == x


def test_log_kernel_sums_to_zero():
    h = ml.fspecial_log((20, 20), 2)
    assert h.shape == (20, 20) and abs(h.sum()) < 1e-15


def test_square3_wrappers_match_general_k():
    rng = np.random.default_rng(0)
    m = rng.random((30, 25)) > 0.5
    assert np.array_equal(ml.imopen_square3(m), ml.imopen_square(m, 3))
    assert np.array_equal(ml.imclose_square3(m), ml.imclose_square(m, 3))


def test_probe_log_kernel_and_morphology(probe):
    if "h_log" not in probe:
        pytest.skip("probe_primitives.mat predates the settings probes; delete it and rerun scripts/parity.sh")
    assert np.abs(ml.fspecial_log((20, 20), 2) - probe["h_log"]).max() < 1e-17
    for k in probe["strel_ks"].ravel():
        k = int(k)
        for j in range(1, 6):
            m = probe[f"morph_in_{j}"].astype(bool)
            assert np.array_equal(ml.imopen_square(m, k), probe[f"open_k{k}_{j}"].astype(bool)), (k, j)
            assert np.array_equal(ml.imclose_square(m, k), probe[f"close_k{k}_{j}"].astype(bool)), (k, j)
