"""Somata from an AMCA-like image (app/analysis/soma.py)."""
from __future__ import annotations

import numpy as np

from app.analysis import soma

PX = 0.16125


def amca():
    """Three soma-sized blobs in a mesh of thin, equally bright 'dendrites'."""
    H, W = 500, 700
    yy, xx = np.mgrid[0:H, 0:W]
    img = np.full((H, W), 800.0)
    centres = [(120, 150), (300, 450), (380, 160)]
    for r, c in centres:
        img += 1200 * np.exp(-(((yy - r) ** 2 + (xx - c) ** 2) / (2 * 30.0 ** 2)) ** 2)
    for k in range(0, W, 60):                      # vertical dendrites, ~1 um wide
        img[:, k:k + 6] += 1100
    for k in range(30, H, 70):
        img[k:k + 6, :] += 1100
    return img.astype(np.uint16), centres


def test_finds_the_somata_and_not_the_dendrites():
    img, centres = amca()
    found = soma.find(img, PX)
    assert len(found.outlines) == len(centres)
    for r, c in centres:
        assert found.mask[r, c] and found.gap_um[r, c] == 0
    assert not found.mask[30:36, 600:].any()       # a dendrite far from any soma
    assert found.gap_at(600, 33) > 10              # 1-based x, y


def test_outlines_are_on_the_mask_edge():
    img, _ = amca()
    found = soma.find(img, PX)
    for outline in found.outlines:
        assert outline and all(found.mask[y - 1, x - 1] for x, y in outline)


def test_an_image_without_somata_has_none():
    found = soma.find(np.full((200, 200), 1000, np.uint16), PX)
    assert found.outlines == [] and not found.mask.any() and np.isinf(found.gap_um).all()
