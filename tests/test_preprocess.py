"""The port of the "method 2.5" ImageJ macro (app/analysis/preprocess.py)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from app.analysis import preprocess

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = " - Processed method 2.5.tif"


def test_keeps_raw_values_on_bright_lines_and_zeroes_the_background():
    H, W = 200, 300
    yy, xx = np.mgrid[0:H, 0:W]
    rng = np.random.default_rng(0)
    raw = 2000 + 8 * xx + rng.normal(0, 40, (H, W))           # uneven background
    raw += 9000 * np.exp(-((yy - 100) ** 2) / 4) * (xx > 50) * (xx < 250)
    raw = raw.astype(np.uint16)
    out = preprocess.processed(raw)
    kept = out > 0
    assert out.dtype == raw.dtype
    assert np.array_equal(out[kept], raw[kept])
    assert kept[100, 60:240].mean() > 0.95                     # the line
    assert kept[150:, :].mean() < 0.02                         # the background


def test_gaussian_kernel_is_imagejs():
    # kRadius = ceil(sigma sqrt(-2 ln accuracy)) + 1: 10 for 16-bit, 9 for 8-bit.
    for accuracy, radius in ((0.0002, 10), (0.002, 9)):
        kern, sums = preprocess.gaussian_kernel(2.0, accuracy, 1000)
        assert len(kern) == radius
        assert math.isclose(float(kern[0]) + 2 * float(kern[1:].sum()), 1.0, abs_tol=1e-6)
        assert np.all(np.diff(kern) < 0) and abs(float(sums[-1])) < 1e-6
    # A constant line stays constant: the edges are padded with edge pixels.
    line = np.full((1, 40), 1000, np.uint16)
    assert np.all(preprocess.gaussian_blur(line) == 1000)


def test_rolling_ball_removes_a_ramp_and_keeps_a_spot():
    H, W = 120, 160
    yy, xx = np.mgrid[0:H, 0:W]
    raw = (3000 + 20 * xx + 5000 * ((yy - 60) ** 2 + (xx - 80) ** 2 < 9)).astype(np.uint16)
    out = preprocess.subtract_background(raw)
    assert out[60, 80] > 4000                                 # the spot
    assert np.percentile(out, 90) < 100                       # the ramp


def test_circular_kernel_matches_rankfilters():
    rows = preprocess.circle_rows(25)
    assert len(rows) == 51 and rows[25] == (0, 25) and rows[0] == (-25, 1)
    assert sum(2 * dx + 1 for _, dx in rows) == 1969            # its nPoints


def test_phansalkar_marks_a_bright_line_white():
    img = np.full((80, 80), 10, np.uint8)
    img[40, 10:70] = 200
    out = preprocess.phansalkar(img)
    assert set(np.unique(out)) == {0, 255}
    assert np.all(out[40, 12:68] == 255) and np.all(out[:30] == 0)


def test_convert_to_mask_takes_the_side_away_from_the_mode():
    img = np.zeros((50, 50), np.uint8)
    img[20:30, 20:30] = 200
    img[22:28, 22:28] = 120
    # IsoData leaves out bins 0 and 255: 120 and 200 split at 160.
    assert preprocess.isodata_level(np.bincount(img.ravel(), minlength=256)) == 160
    masked = preprocess.convert_to_mask(img)
    assert masked[21, 21] and not masked[25, 25] and not masked[0, 0]
    inverted = preprocess.convert_to_mask(255 - img)          # mode at 255: the dark side
    assert inverted[21, 21] and not inverted[25, 25] and not inverted[0, 0]


def _pairs(limit: int) -> list[Path]:
    out = []
    for folder in ("005-both-tiff", "006-both-tiff"):
        out += sorted((ROOT / "example-data" / folder).glob("*_ORG.tif"))[:limit]
    return [p for p in out if p.with_name(p.name + SUFFIX).exists()]


@pytest.mark.parametrize("raw_path", _pairs(2) or [None])
def test_matches_the_labs_processed_files(raw_path):
    """Byte for byte what the macro wrote (scripts/preprocess_check.py runs
    every pair, and every stage against Fiji)."""
    if raw_path is None:
        pytest.skip("needs the local example-data/005 or 006 TIFF pairs")
    import tifffile

    raw = tifffile.imread(raw_path)
    real = tifffile.imread(raw_path.with_name(raw_path.name + SUFFIX))
    assert np.array_equal(preprocess.processed(raw), real)
