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


def touching():
    """Two soma-sized blobs about 14 um apart, run together into one outline."""
    H, W = 400, 500
    yy, xx = np.mgrid[0:H, 0:W]
    img = np.full((H, W), 800.0)
    centres = [(200, 200), (200, 290)]
    for r, c in centres:
        img += 1200 * np.exp(-((yy - r) ** 2 + (xx - c) ** 2) / (2 * 35.0 ** 2))
    return img.astype(np.uint16), centres


def test_touching_somata_are_one_body_whole_and_two_split():
    img, centres = touching()
    found = soma.find(img, PX)
    assert len(found.outlines) == 1
    assert len(found.bodies(False).hotspots) == 1
    split = found.bodies(True)
    assert len(split.hotspots) == 2
    for (r, c), (x, y) in zip(centres, sorted(split.hotspots)):
        assert abs(x - (c + 1)) <= 12 and abs(y - (r + 1)) <= 6   # the blobs pull each peak inward a little
    labels = split.labels
    assert set(np.unique(labels)) == {0, 1, 2}


def test_a_lone_soma_is_one_body_either_way():
    img, centres = amca()
    found = soma.find(img, PX)
    for split in (False, True):
        bodies = found.bodies(split)
        assert len(bodies.hotspots) == len(centres)


def test_a_dendrite_trunk_is_not_a_soma_of_its_own():
    """A soma with a thick, bright trunk leaving it: one body, split or not."""
    H, W = 400, 600
    yy, xx = np.mgrid[0:H, 0:W]
    img = np.full((H, W), 800.0)
    img += 1200 * np.exp(-((yy - 200) ** 2 + (xx - 200) ** 2) / (2 * 35.0 ** 2))
    img[185:215, 230:520] += 1100      # ~5 um wide, ~47 um long
    found = soma.find(img.astype(np.uint16), PX)
    assert len(found.outlines) == 1
    assert len(found.bodies(True).hotspots) == 1
