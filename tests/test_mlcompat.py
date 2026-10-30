"""Each MATLAB primitive against MATLAB R2026b's own output."""
from __future__ import annotations

import numpy as np

from app.analysis import mlcompat as ml


def test_mat2gray_bit_exact(probe):
    assert np.array_equal(ml.mat2gray(probe["pic"]), probe["Chais"])


def test_gauss_kernel(probe):
    h = ml.fspecial_gaussian((20, 20), 2)
    assert np.array_equal(h, probe["h"])
    x = np.arange(-9.5, 10.5)
    X, Y = np.meshgrid(x, x)
    formula = np.exp(-(X * X + Y * Y) / 8)
    assert np.allclose(h, formula / formula.sum(), rtol=1e-14, atol=0)


def test_imfilter_and_masks(probe):
    s = ml.imfilter_zero_same(probe["Chais"], probe["h"])
    assert np.abs(s - probe["Chais_smooth"]).max() < 1e-13
    for k, th in enumerate(probe["th_list"][0], 1):
        bw = ml.im2bw(s, float(th))
        assert np.array_equal(bw, probe[f"bw_{k}"].astype(bool))
        o = ml.imopen_square3(bw)
        assert np.array_equal(o, probe[f"open_{k}"].astype(bool))
        assert np.array_equal(ml.imclose_square3(o), probe[f"close_{k}"].astype(bool))


def test_graythresh(probe):
    assert ml.graythresh(probe["Chais_smooth"]) == probe["otsu"][0, 0]


def test_morphology_random_with_borders(probe):
    for k in range(1, 21):
        m = probe[f"morph_in_{k}"].astype(bool)
        assert np.array_equal(ml.imopen_square3(m), probe[f"morph_open_{k}"].astype(bool)), k
        assert np.array_equal(ml.imclose_square3(m), probe[f"morph_close_{k}"].astype(bool)), k


def test_bwdist_index_ties(probe):
    for k in range(1, int(probe["bwd_n"][0, 0]) + 1):
        m = probe[f"bwd_in_{k}"].astype(bool)
        idx = probe[f"bwd_idx_{k}"].astype(np.int64) - 1
        H = m.shape[0]
        for r in range(m.shape[0]):
            for c in range(m.shape[1]):
                rr, cc = ml.bwdist_nearest(m, r, c)
                assert cc * H + rr == idx[r, c], (k, r, c)


def test_thin_luts(probe):
    assert np.array_equal(ml.LUT_THIN1, probe["lutthin1"].ravel().astype(bool))
    assert np.array_equal(ml.LUT_THIN2, probe["lutthin2"].ravel().astype(bool))


def test_thin_random_blobs(probe):
    for k in range(1, 31):
        out = ml.bwmorph_thin(probe[f"thin_in_{k}"].astype(bool))
        assert np.array_equal(out, probe[f"thin_out_{k}"].astype(bool)), k


def test_colon_and_csaps(probe):
    for k, N in enumerate(probe["Ns"][0], 1):
        N = int(N)
        ts = np.append(ml.colon(1, 0.1, N), N)
        assert np.array_equal(ts, probe[f"ts_{k}"].ravel()), N
        xy = probe[f"xy_{k}"].astype(np.float64)
        got = ml.csaps(np.arange(1, N + 1), xy, 0.3, ts)
        want = probe[f"xysm_{k}"]
        assert np.abs(got - want).max() < 1e-9, N
        assert np.array_equal(ml.round_half_away(got), ml.round_half_away(want)), N


def test_num2str6(probe):
    strs = [s[0] for s in probe["fmt_strs"][0]]
    assert [ml.num2str(float(v), 6) for v in probe["fmt_vals"][0]] == strs


def test_round_half_away():
    assert list(ml.round_half_away([0.5, 1.5, 2.5, -0.5, -2.5, 0.49999999999999994])) == [1, 2, 3, -1, -3, 0]
