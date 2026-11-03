"""Auto mode "learned" (app/analysis/learned.py) on synthetic images, and its
shipped model against what scikit-learn made of it (scripts/train_learned.py)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from app.analysis import ais_auto as aa
from app.analysis import learned
from app.analysis.detect import detect
from app.analysis.service import run_click
from tests.test_detect import rods

CHECK = Path(__file__).resolve().parent / "autodata" / "learned_check.json"


def test_forest_follows_thresholds_and_missing_values():
    # x0 <= 1 -> -1; else x1 <= 5 -> 2, else 3; a missing x0 goes right,
    # a missing x1 left.
    tree = {"feature": [0, 0, 1, 0, 0], "threshold": [1.0, 0, 5.0, 0, 0],
            "missing_left": [False, False, True, False, False],
            "left": [1, 0, 3, 0, 0], "right": [2, 0, 4, 0, 0],
            "leaf": [False, True, False, True, True], "value": [0, -1.0, 0, 2.0, 3.0]}
    forest = learned.Forest({"kind": "regressor", "features": ["a", "b"], "baseline": 0.5, "trees": [tree, tree]})
    X = np.array([[1.0, 9.0], [1.5, 5.0], [1.5, 6.0], [math.nan, 9.0], [2.0, math.nan]])
    assert forest.predict(X).tolist() == [-1.5, 4.5, 6.5, 6.5, 4.5]
    clf = learned.Forest({"kind": "classifier", "features": ["a", "b"], "baseline": 0.0, "trees": [tree]})
    assert clf.predict(X[:1])[0] == pytest.approx(1 / (1 + math.e))


def test_shipped_model_gives_what_scikit_learn_gave():
    check = json.loads(CHECK.read_text())
    m = learned.models()
    assert m["ais"].features == list(learned.FEATURES)
    assert m["component"].features == list(learned.COMPONENT_FEATURES)
    assert not set(learned.SOMA_FEATURES) & set(m["ais_plain"].features + m["component_plain"].features)
    X = np.array(check["X"], np.float64)
    for name in ("ais", "component", "ais_plain", "component_plain"):
        cols = [learned.FEATURES.index(f) for f in m[name].features]
        assert np.allclose(m[name].predict(X[:, cols]), check[name], atol=1e-6), name
    assert 0 < m["meta"]["min_score"] < 1


def test_seeds_are_the_ends_then_every_step_along():
    skel = np.zeros((5, 60), bool)
    skel[2, 5:46] = True           # 41 px: ends at 5 and 45
    out = learned.seeds(skel)
    assert out[:2] == [(2, 5), (2, 45)]
    cols = sorted(c for _, c in out[2:])
    # Every SEED_STEP_PX from the nearer end.
    assert cols == [15, 25, 35]
    edge = np.zeros((5, 60), bool)
    edge[2, 0:20] = True           # touches the border: that end cannot be clicked
    assert (2, 0) not in learned.seeds(edge)


def constant(p: float) -> learned.Forest:
    """A model that scores everything p."""
    leaf = {"feature": [0], "threshold": [0.0], "missing_left": [True], "left": [0], "right": [0],
            "leaf": [True], "value": [0.0]}
    return learned.Forest({"kind": "classifier", "features": ["comp_area_um2"], "baseline": math.log(p / (1 - p)),
                           "trees": [leaf]})


@pytest.fixture
def stub_models(monkeypatch):
    """Every blob seeded and every candidate scored alike, so these tests
    check the mechanics, not what the shipped model makes of a drawing."""
    m = {k: constant(0.5) for k in ("ais", "component", "ais_plain", "component_plain")} | {"meta": {}}
    monkeypatch.setattr(learned, "models", lambda: m)


def test_candidates_are_clicks_at_their_seeds_scored_once_each(stub_models):
    pic = rods()
    prep = aa.PreparedImage.from_array(pic)
    out = detect(prep, pic, start="learned")
    long_ones = [c for c in out["candidates"] if len(c["path"]) > 100]
    assert len(long_ones) == 2
    for c in out["candidates"]:
        assert c["filter"]["score"] == 0.5 and c["filter"]["length_um"] == c["measures"]["length_um"]
        assert "features" not in c and "blob" not in c
        clicked = run_click(prep, pic, tuple(float(v) for v in c["seed"]), None, 0.01)
        assert clicked["measures"] == c["measures"] and clicked["path"] == c["path"]
        assert {k: clicked["component"][k] for k in ("pixels", "bbox")} == c["component"]
    # No two lie on each other, either way.
    pix = [c["pixels"] for c in out["candidates"]]
    pair = learned.on_fractions(pix, pix, pic.shape, learned.REACH).toarray()
    np.fill_diagonal(pair, 0)
    assert pair.max() <= learned.OVERLAP
    again = detect(prep, pic, start="learned", exclude=[long_ones[0]["pixels"]])
    assert again["known"] >= 1
    assert len([c for c in again["candidates"] if len(c["path"]) > 100]) == 1


def test_without_somata_the_plain_models_judge(monkeypatch):
    used = []
    m = {k: constant(0.5) for k in ("ais", "component", "ais_plain", "component_plain")} | {"meta": {}}
    for k in m:
        if k != "meta":
            predict = m[k].predict
            m[k].predict = (lambda k, predict: lambda X: used.append(k) or predict(X))(k, predict)
    monkeypatch.setattr(learned, "models", lambda: m)
    pic = rods()
    detect(aa.PreparedImage.from_array(pic), pic, start="learned")
    assert set(used) == {"component_plain", "ais_plain"}


def test_blob_is_what_a_click_selects_and_thins():
    pic = rods()
    prep = aa.PreparedImage.from_array(pic)
    for rc in ((60, 140), (140, 100), (15, 280)):
        cache: dict = {}
        b = learned.blob(prep, rc, 0.01, aa.DEFAULT, cache)
        tr = aa.trace(prep, (rc[1] + 1.0, rc[0] + 1.0), None, 0.01, aa.DEFAULT, {})
        assert b.threshold == tr.threshold and b.threshold_initial == tr.threshold_initial
        assert np.array_equal(b.selected, tr.selected) and np.array_equal(b.skeleton, tr.skeleton)


def test_on_fractions_reach_is_a_square_both_ways():
    a = [[10, 10], [11, 10], [12, 10], [13, 10]]
    b = [[13, 13], [17, 13]]          # 3 px below a's end, and 4 px past it
    f = learned.on_fractions([a, b], [a, b], (30, 30), 3).toarray()
    assert f[0, 0] == f[1, 1] == 1
    assert f[1, 0] == 0.5             # (17, 13) is 4 px from a along x
    assert f[0, 1] == 1               # (10, 10) is 3 px from (13, 13) both ways: in the square
