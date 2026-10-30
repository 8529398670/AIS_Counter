"""The JSON one click produces, on a synthetic image (no example data needed)."""
from __future__ import annotations

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
    assert out["clicks"] == [[38, 101], [38, 101]]


def test_click_without_raw_stops_after_trace():
    pic, _ = synthetic()
    out = run_click(aa.PreparedImage.from_array(pic), None, (38.0, 101.0), None, 0.01)
    assert not out["ok"] and out["path"] and "raw" in out["error"]
