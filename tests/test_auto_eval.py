"""Auto mode against the AIS someone accepted by hand (scripts/auto_eval.py):
methods fitted's and fitted2's starts and filter defaults (detect.py
"fitted" / "fitted2", static/js/settings.js) must keep what they scored when
they were fitted, and classic what it always did. Needs example-data/."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import auto_eval  # noqa: E402

GT = ROOT / "tests" / "autodata" / "batch12.json"
NEEDS = pytest.mark.skipif(not (ROOT / "example-data" / "002-czi").exists(), reason="needs example-data/002-czi")


@NEEDS
def test_fitted_defaults_find_what_was_accepted_and_measure_it_alike():
    images = auto_eval.load(GT)
    total = auto_eval.evaluate(images, "fitted", False, "fitted", os.cpu_count() or 1)["total"]
    assert total["precision"] >= 0.78 and total["recall"] >= 0.9
    assert total["len_mae"] <= 2.0
    assert (total["tp"], total["found"]) == (81, 97)      # as before fitted2


@NEEDS
def test_fitted2_defaults_find_a_little_more_than_fitted():
    images = auto_eval.load(GT)
    total = auto_eval.evaluate(images, "fitted2", False, "fitted2", os.cpu_count() or 1)["total"]
    assert (total["tp"], total["found"]) == (82, 101)
    assert total["len_mae"] <= 2.0


@NEEDS
def test_classic_scores_as_it_did_before_fitted():
    images = auto_eval.load(GT)
    total = auto_eval.evaluate(images, "soma", False, "classic", os.cpu_count() or 1)["total"]
    assert (total["tp"], total["found"]) == (81, 122)


def test_match_is_one_to_one_by_overlap():
    import numpy as np
    masks = [np.zeros((5, 5), bool), np.zeros((5, 5), bool)]
    masks[0][0, :] = True
    masks[1][2, :] = True
    whole = {"pixels": [[x, 1] for x in range(1, 6)]}
    partly = {"pixels": [[1, 1], [2, 1], [3, 1], [4, 5], [5, 5]]}   # 3 of 5 on the first
    other = {"pixels": [[x, 3] for x in range(1, 6)]}
    assert auto_eval.match([partly, whole, other], masks) == [None, 0, 1]
    assert auto_eval.match([partly], masks) == [0]
