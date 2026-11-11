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


def lines(seed=0):
    """AIS-like thin bright lines on a dim, slightly noisy background: no cell bodies."""
    H, W = 500, 700
    rng = np.random.default_rng(seed)
    img = np.full((H, W), 800.0)
    for k in range(20, W, 45):
        img[100:400, k:k + 6] += 1500
    return (img + rng.normal(0, 30, (H, W))).astype(np.uint16)


def noise(seed=1):
    return (1000 + np.random.default_rng(seed).normal(0, 100, (500, 700))).astype(np.uint16)


def test_cell_bodies_score_and_lines_noise_and_flat_do_not():
    img, _ = amca()
    assert soma.quality(soma.find(img, PX), img, PX) > 0
    for plane in (lines(), noise(), np.full((500, 700), 1000, np.uint16)):
        assert soma.quality(soma.find(plane, PX), plane, PX) == 0


def test_an_ais_thick_end_is_not_a_cell_body():
    """A lone tapered AIS (as tests/test_pairing.tapered) shows no somata."""
    H, W = 200, 300
    yy, xx = np.mgrid[1:H + 1, 1:W + 1].astype(np.float64)
    frac = np.clip((xx - 50) / 150, 0, 1)
    sigma = 4.0 - 2.5 * frac
    img = (100 + 1000 * ((xx >= 50) & (xx <= 200)) * np.exp(-((yy - 100) ** 2) / (2 * sigma ** 2))).astype(np.uint16)
    assert soma.best([img], PX, ais=0) is None


def test_best_takes_the_channel_that_shows_cell_bodies():
    img, centres = amca()
    index, found = soma.best([lines(), noise(), img], PX, ais=0)
    assert index == 2 and all(found.mask[r, c] for r, c in centres)
    assert soma.best([lines(), noise()], PX, ais=0) is None


def test_a_soma_channel_that_shows_too_little_gives_way_to_another():
    img, centres = amca()
    assert soma.best([lines(), img, noise()], PX, ais=0, first=1)[0] == 1       # it shows them: kept
    index, found = soma.best([lines(), noise(), img], PX, ais=0, first=1)       # it does not: the next
    assert index == 2 and all(found.mask[r, c] for r, c in centres)
    assert soma.best([lines(), noise()], PX, ais=0, first=1)[0] == 1          # none does: still the chosen


def test_best_takes_the_ais_channel_only_when_no_other_shows_any():
    img, _ = amca()
    assert soma.best([img, img.copy()], PX, ais=0)[0] == 1
    assert soma.best([img, noise()], PX, ais=0)[0] == 0


def test_a_dim_noisy_channel_is_not_taken_for_somata():
    """Smoothed noise can make a few blobs stand out against its own small
    range; none stands out against the pixel noise."""
    for seed in range(3):
        plane = np.random.default_rng(seed).normal(300, 20, (1040, 1388)).clip(0).astype(np.uint16)
        assert soma.quality(soma.find(plane, PX), plane, PX) == 0
