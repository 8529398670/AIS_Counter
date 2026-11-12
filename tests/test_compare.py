"""Treatments (app/models/ais.py) and grouping, testing and plotting by them
(app/analysis/compare.py), through the model and the routes."""
from __future__ import annotations

import hashlib
import json
import xml.dom.minidom

import numpy as np
import pytest
from scipy import stats as sps

from app.analysis import compare
from app.core import db
from app.models import ais, users
from tests.test_matlab_routes import Harness

P = ".tif - Processed method 2.5.tif"
LINE = {"a_x": 1, "a_y": 1, "b_x": 2, "b_y": 2, "length_px": 1.0, "length_um": 5.0, "pixconv": 0.161}


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


def files(*rels):
    return [{"name": r.split("/")[-1], "rel": r, "sha": hashlib.sha256(r.encode()).hexdigest(), "size": 1} for r in rels]


def culture(store, name, lengths, randomize=True):
    """A batch with one image per (treatment, coverslip), blinded, its
    treatments saved from the guesses, and an AIS per length given:
    lengths = {treatment: [length, ...]} (each on its own coverslip)."""
    rels = [f"{name}/BB50 {t} {chr(65 + i)}{P}" for t, vs in lengths.items() for i in range(len(vs))]
    batch = ais.create_batch(store, name, "upload", files(*rels), 1, randomize_names=randomize)
    ais.set_treatments(store, batch["id"], {r["key"]: r["guess"] for r in ais.treatments(batch)})
    batch = ais.get_batch(store, batch["id"])
    by_original = {ais.original_cell(im): im["key"] for im in batch["images"]}
    for t, vs in lengths.items():
        for i, v in enumerate(vs):
            ais.add_result(store, batch["id"], by_original[f"BB50 {t} {chr(65 + i)}"], {"length_um": v, "pixels": [[1, 1]]}, 1)
    return batch


# --- guessing and keeping treatments ------------------------------------------------


@pytest.mark.parametrize("name,guess", [
    ("BB50 DMSO+Ethanol A-02", "DMSO+Ethanol"), ("BB50 DMSO+Ethanol B", "DMSO+Ethanol"),
    ("BB50 TM+Ethanol BB", "TM+Ethanol"), ("BB50 TM+MDL C", "TM+MDL"), ("BB50 DMSO A", "DMSO"),
    ("DMSO A", "DMSO"), ("BB50 DMSO+FK506 A_c2_ORG", "DMSO+FK506"), ("BB50 KCl 10 mM A-3", "KCl 10 mM"),
    ("10458-19683-22698", ""), ("Slide7zstack_26_IP-ApoTome-03", ""), ("Control", ""),
])
def test_a_treatment_is_guessed_from_the_original_name(name, guess):
    assert ais.guess_treatment(name) == guess


@pytest.mark.parametrize("a,b", [
    ("DMSO 24Hr KCl 3Hr", "dmso 24hr kcl 3hr"), ("DMSO 24Hr + KCl 3Hr", "DMSO 24 hrs KCl 3 hours"),
    ("TM+KCl+WO", "TM + KCl WO"), ("TM 3hrs+3hrs", "tm 3h 3h"), ("DMSO 30 mins", "DMSO 30min"),
])
def test_spellings_of_one_treatment_share_a_key(a, b):
    assert ais.treatment_key(a) == ais.treatment_key(b)


@pytest.mark.parametrize("a,b", [("TM", "TM+KCl"), ("TM 3h", "TM 30min"), ("DMSO 24h", "DMSO 2h")])
def test_different_treatments_keep_different_keys(a, b):
    assert ais.treatment_key(a) != ais.treatment_key(b)


C2 = ["C2 D1 DMSO 3hrs A", "C2 D1 DMSO 3hrs B-02", "C2 D2 TM 3hrs A-02", "C2 D6 TM+NaCl WO A-02",
      "C2 D6 TM+NaCl WO C", "C2 D6 TM+NaCL WO D-02", "C2 D78 TM 18hrs B", "10458-19683-22698"]


def test_a_batch_drops_its_dish_tags_and_merges_spellings():
    assert ais.guess_treatments(C2) == ["DMSO 3hrs", "DMSO 3hrs", "TM 3hrs", "TM+NaCl WO",
                                        "TM+NaCl WO", "TM+NaCl WO", "TM 18hrs", ""]


def test_a_leading_tag_that_says_more_than_the_rest_stays():
    # Two dishes with one treatment, or one tag with two: the tag is not a dish number.
    assert ais.guess_treatments(["P1 FK506 1h A", "P1 GW501 1h A"]) == ["FK506 1h", "GW501 1h"]
    assert ais.guess_treatments(["C2 D1 TM A", "C2 D2 TM B"]) == ["D1 TM", "D2 TM"]
    assert ais.guess_treatments(["C2 D1 TM A", "C2 D1 DMSO B"]) == ["D1 TM", "D1 DMSO"]
    assert ais.guess_treatments(["C2 D1 TM A", "C2 D1 TM B"]) == ["D1 TM", "D1 TM"]


def test_guesses_take_the_spelling_already_saved():
    names = ["C7 DMSO 24Hr + KCl 3Hr A", "C7 TM 24Hr B", "C7 TM 24hr C"]
    assert ais.guess_treatments(names) == ["DMSO 24Hr + KCl 3Hr", "TM 24Hr", "TM 24Hr"]
    known = ["DMSO 24hr KCl 3hr", "DMSO 24hr KCl 3hr", "DMSO 24Hr KCl 3Hr", "TM 24h"]
    assert ais.guess_treatments(names, known) == ["DMSO 24hr KCl 3hr", "TM 24h", "TM 24h"]


def test_as_written_keeps_each_spelling_but_still_drops_dish_tags():
    assert ais.guess_treatments(C2, ["dmso 3h"], matched=False) == [
        "DMSO 3hrs", "DMSO 3hrs", "TM 3hrs", "TM+NaCl WO", "TM+NaCl WO", "TM+NaCL WO", "TM 18hrs", ""]


def test_the_review_gives_both_guesses_and_spells_matched_like_other_batches(store):
    culture(store, "C1", {"DMSO 24hr": [1]})
    other = ais.create_batch(store, "C7", "upload", files(f"C7/BB50 DMSO 24 Hr A{P}"), 1, randomize_names=True)
    [row] = ais.review_treatments(store, other)
    assert (row["guess"], row["guess_written"], row["guess_key"]) == ("DMSO 24hr", "DMSO 24 Hr", "dmso 24h")
    assert [r["guess"] for r in ais.treatments(other)] == ["DMSO 24 Hr"]


def test_treatments_are_saved_per_image_trimmed_and_cleared_with_blank(store):
    batch = culture(store, "C1", {"DMSO": [1], "TTX": [2]})
    rows = ais.treatments(batch)
    assert {(r["original"], r["folder"], r["treatment"], r["guess"]) for r in rows} == \
        {("BB50 DMSO A", "C1", "DMSO", "DMSO"), ("BB50 TTX A", "C1", "TTX", "TTX")}
    first, second = rows[0]["key"], rows[1]["key"]
    after = ais.set_treatments(store, batch["id"], {first: "  Vehicle ", second: ""})
    assert {im["key"]: im.get("treatment") for im in after["images"]} == {first: "Vehicle", second: None}
    with pytest.raises(ais.BatchError):
        ais.set_treatments(store, batch["id"], {"nope": "x"})
    with pytest.raises(ais.BatchError):
        ais.set_treatments(store, batch["id"], {first: 4})
    with pytest.raises(ais.BatchError):
        ais.set_treatments(store, batch["id"], [first])
    assert ais.set_treatments(store, batch["id"] + 99, {}) is None


def test_each_image_says_which_folder_it_came_from(store):
    picked = files(f"exp/DMSO/a{P}", f"exp/TTX/b{P}", f"exp/c{P}")
    batch = ais.create_batch(store, "Culture 3", "upload", picked, 1, randomize_names=True)
    rows = {r["original"]: r["folder"] for r in ais.treatments(batch)}
    assert rows == {"a": "Culture 3/DMSO", "b": "Culture 3/TTX", "c": "Culture 3"}


def test_a_treatment_survives_rerandomizing_and_a_backup(store):
    batch = culture(store, "C1", {"DMSO": [1]})
    again, _, _ = ais.rerandomize(store, batch["id"], 1)
    assert again["images"][0]["treatment"] == "DMSO"
    backup = json.loads(json.dumps(ais.backup_batch(store, batch["id"])))
    backup |= {"format": ais.BACKUP_FORMAT, "version": ais.BACKUP_VERSION, "users": {"1": "Ada"}}
    restored = ais.import_batch(store, backup, {1: "Ada"}, 1)
    assert restored["images"][0]["treatment"] == "DMSO"


# --- grouping ------------------------------------------------------------------------


def test_values_are_grouped_by_treatment_and_measures_never_mix(store):
    batch = culture(store, "C1", {"DMSO": [10, 20], "TTX": [5]}, randomize=False)
    rows = ais.list_results(store, batch["id"])
    ais.set_soma(store, rows[0]["id"], {"soma_um": 3.0, "soma_px": 18.6, "soma_ais_x": 1, "soma_ais_y": 1, "soma_x": 2, "soma_y": 2}, 1)
    ais.add_measurement(store, batch["id"], rows[0]["image"], LINE | {"type": "Soma distance", "length_um": 7.0}, 1)
    ais.add_measurement(store, batch["id"], rows[0]["image"], LINE, 1)
    out = compare.compare(store, [batch["id"]])
    assert out["measures"] == ["ais_length", "ais_soma", "type:", "type:Soma distance"]
    assert out["treatments"] == ["DMSO", "TTX"]
    groups = {(g["treatment"], g["measure"]): (g["n"], g["mean"]) for g in out["groups"]}
    assert groups[("DMSO", "ais_length")] == (2, 15.0) and groups[("TTX", "ais_length")] == (1, 5.0)
    assert groups[("DMSO", "ais_soma")] == (1, 3.0) and groups[("DMSO", "type:Soma distance")] == (1, 7.0)
    # One batch, TTX with one value: every ANOVA block says why it could not run; no plots.
    length = [r for r in out["stats"] if r["measure"] == "ais_length" and r["family"] not in ("ks", "twoway")]
    assert [(r["design"], r["test"]) for r in length] == [
        ("individual values", "one-way ANOVA"), ("culture means", "one-way ANOVA")]
    assert all(r["p"] is None for r in length) and out["plots"] == []
    names = {im["original"]: (im["treatment"], im["ais"]) for im in out["images"]}
    assert names["BB50 DMSO A"][0] == "DMSO" and names["BB50 TTX A"] == ("TTX", 1)
    assert all("mean_length" not in im and "mean_soma" not in im for im in out["images"])   # no means per image


def test_left_out_images_and_unmatched_case_are_handled(store):
    a = culture(store, "C1", {"DMSO": [10], "TTX": [5]})
    b = culture(store, "C2", {"DMSO": [12], "TTX": [6]})
    key = next(r["key"] for r in ais.treatments(b) if r["treatment"] == "DMSO")
    ais.set_treatments(store, b["id"], {key: " dmso "})
    out = compare.compare(store, [a["id"], b["id"]])
    assert out["treatments"] == ["DMSO", "TTX"]
    ais.set_included(store, a["id"], [im["key"] for im in a["images"]], False)
    assert {im["batch"] for im in compare.compare(store, [a["id"], b["id"]])["images"]} == {"C2"}


def test_spellings_that_differ_beyond_case_stay_apart_in_compare(store):
    # Whether TM+KCl+WO and TM+KCl WO are one treatment is the admin's call, saved as one spelling or two.
    a = culture(store, "C2", {"TM+KCl WO": [10], "TM": [5]})
    b = culture(store, "C3", {"TM+KCl+WO": [12], "tm": [6]})
    assert compare.compare(store, [a["id"], b["id"]])["treatments"] == ["TM", "TM+KCl WO", "TM+KCl+WO"]


def test_compare_refuses_what_is_not_a_list_of_batches(store):
    for bad in ([], "1", [True], None):
        with pytest.raises(compare.CompareError):
            compare.compare(store, bad)
    with pytest.raises(compare.CompareError):
        compare.compare(store, [999])


# --- the tests -----------------------------------------------------------------------


def test_holm_adjusts_in_order_and_keeps_blanks():
    # Sorted 0.01, 0.03, 0.04 -> 3 x 0.01, 2 x 0.03, max(that, 1 x 0.04).
    adjusted = compare.holm([0.01, None, 0.04, 0.03])
    assert adjusted[1] is None and adjusted[0] == pytest.approx(0.03)
    assert adjusted[3] == pytest.approx(0.06) and adjusted[2] == pytest.approx(0.06)


def test_rm_anova_with_two_treatments_is_the_paired_t_test_squared():
    data = np.array([[10.0, 8.0], [12.0, 9.5], [11.0, 10.0], [14.0, 11.0]])
    f, p, df_t, df_e = compare.rm_anova(data)
    t = sps.ttest_rel(data[:, 0], data[:, 1])
    assert f == pytest.approx(t.statistic ** 2) and p == pytest.approx(t.pvalue)
    assert (df_t, df_e) == (1, 3)
    assert compare.rm_anova(data[:1]) is None


def test_rm_anova_matches_its_sums_of_squares():
    # Three subjects, three conditions, worked by hand:
    # grand 5; SS treatment 3 * (1 + 0 + 1) = 6; SS subjects 3 * (1 + 0 + 1) = 6;
    # SS total 16; SS error 4; F = (6 / 2) / (4 / 4) = 3.
    data = np.array([[2.0, 4.0, 6.0], [4.0, 5.0, 6.0], [6.0, 6.0, 6.0]])
    f, p, df_t, df_e = compare.rm_anova(data)
    assert (df_t, df_e) == (2, 4) and f == pytest.approx(3.0) and p == pytest.approx(sps.f.sf(3.0, 2, 4))


def test_the_tests_run_on_culture_means_paired_and_unpaired(store):
    means = {"DMSO": [40.0, 42.0, 41.0], "TTX": [30.0, 33.0, 31.5], "KCl": [35.0, 36.0, 36.5]}
    ids = [culture(store, f"C{c}", {t: [vs[c] - 1, vs[c] + 1] for t, vs in means.items()})["id"] for c in range(3)]
    out = compare.compare(store, ids)
    rows = {(r["measure"], r["design"], r["test"], r["groups"]): r for r in out["stats"]}
    order = ["DMSO", "KCl", "TTX"]
    data = np.array([[means[t][c] for t in order] for c in range(3)])
    friedman = sps.friedmanchisquare(*data.T)
    assert rows[("ais_length", "paired", "Friedman", "all")]["p"] == pytest.approx(friedman.pvalue, rel=1e-3)
    pair = rows[("ais_length", "paired", "paired t-test (Holm)", "DMSO vs TTX")]
    assert pair["p"] == pytest.approx(sps.ttest_rel(data[:, 0], data[:, 2]).pvalue, rel=1e-3)
    assert pair["p_holm"] >= pair["p"]
    kw = rows[("ais_length", "unpaired", "Kruskal-Wallis", "all")]
    assert kw["p"] == pytest.approx(sps.kruskal(*data.T).pvalue, rel=1e-3) and kw["n"] == 9
    ks = rows[("ais_length", "individual values", "Kolmogorov-Smirnov (Holm)", "DMSO vs KCl")]
    assert ks["n"] == 12 and ks["note"] == "individual values, not culture means"
    assert out["dropped"] == []
    pooled = {p["treatment"]: p for p in out["pooled"]}
    assert pooled["DMSO"]["cultures"] == 3 and pooled["DMSO"]["culture_mean"] == pytest.approx(41.0)
    kinds = [(p["measure"], p["kind"]) for p in out["plots"]]
    assert kinds == [("ais_length", "box"), ("ais_length", "cdf")]
    for plot in out["plots"]:
        xml.dom.minidom.parseString(plot["svg"])


def test_a_culture_missing_a_treatment_is_left_out_of_the_paired_tests(store):
    a = culture(store, "C1", {"DMSO": [10], "TTX": [5]})
    b = culture(store, "C2", {"DMSO": [12], "TTX": [6]})
    c = culture(store, "C3", {"DMSO": [11]})
    out = compare.compare(store, [a["id"], b["id"], c["id"]])
    assert out["dropped"] == [{"measure": "ais_length", "batch": "C3"}]
    paired = next(r for r in out["stats"] if r["test"] == "paired t-test")
    assert paired["n"] == 2
    unpaired = next(r for r in out["stats"] if r["test"] == "Welch t-test")
    assert unpaired["n"] == 5


def test_too_few_cultures_say_so_instead_of_a_p_value(store):
    a = culture(store, "C1", {"DMSO": [10], "TTX": [5]})
    b = culture(store, "C2", {"DMSO": [12]})
    out = compare.compare(store, [a["id"], b["id"]])
    paired = next(r for r in out["stats"] if r["test"] == "paired t-test")
    assert paired["p"] is None and paired["note"] == "needs 2 cultures with every treatment"
    welch = next(r for r in out["stats"] if r["test"] == "Welch t-test")
    assert welch["p"] is None and welch["note"] == "needs 2 cultures per treatment"


# --- choosing the stats (the Compare dialog) ----------------------------------------


def _three_cultures(store):
    means = {"DMSO": [40.0, 42.0, 41.0], "TTX": [30.0, 33.0, 31.5], "KCl": [35.0, 36.0, 36.5]}
    return [culture(store, f"C{c}", {t: [vs[c] - 1, vs[c] + 1] for t, vs in means.items()})["id"] for c in range(3)]


def test_every_row_says_its_family_and_no_choice_keeps_every_test(store):
    ids = _three_cultures(store)
    everything = compare.compare(store, ids)
    assert {r["family"] for r in everything["stats"]} == set(compare.TESTS)
    chosen = compare.compare(store, ids, tests=list(compare.TESTS), units=list(compare.UNITS))
    assert chosen["stats"] == everything["stats"]


def test_the_anova_blocks_alone_leave_out_paired_unpaired_and_ks(store):
    a = culture(store, "C1", {"DMSO": [10, 11], "TTX": [5, 6]})
    b = culture(store, "C2", {"DMSO": [12, 13], "TTX": [6, 7]})
    c = culture(store, "C3", {"DMSO": [11, 12]})
    out = compare.compare(store, [a["id"], b["id"], c["id"]], tests=["anova", "tukey", "welch", "dunnett"])
    assert {r["family"] for r in out["stats"]} == {"anova", "tukey", "welch", "dunnett"}
    assert {r["design"] for r in out["stats"]} == set(compare.UNITS)
    assert out["dropped"] == []
    everything = compare.compare(store, [a["id"], b["id"], c["id"]])
    assert [p["svg"] for p in out["plots"]] == [p["svg"] for p in everything["plots"]]


def test_units_narrow_the_blocks_and_main_moves_to_a_chosen_one(store):
    ids = _three_cultures(store)
    out = compare.compare(store, ids, tests=["anova", "tukey"], units=["individual values"])
    assert {r["design"] for r in out["stats"]} == {"individual values"}
    assert all(r["main"] for r in out["stats"])
    # "image means" is no longer a unit: asked for, it is left out, not refused.
    old = compare.compare(store, ids, tests=["anova"], units=["image means", "culture means"])
    assert {r["design"] for r in old["stats"]} == {"culture means"}
    ks = compare.compare(store, ids, tests=["ks"], units=["culture means"])
    assert {r["test"] for r in ks["stats"]} == {"Kolmogorov-Smirnov (Holm)"}
    assert compare.compare(store, ids, tests=[])["stats"] == []


@pytest.mark.parametrize("tests, units", [("anova", None), (["nope"], None), (None, ["cultures"]), (["anova"], [])])
def test_a_bad_choice_of_stats_is_refused(store, tests, units):
    ids = _three_cultures(store)
    with pytest.raises(compare.CompareError):
        compare.compare(store, ids, tests=tests, units=units)


# --- the ANOVA blocks ---------------------------------------------------------------


def test_the_control_is_the_shortest_name_with_a_control_word():
    assert compare._control(["TM 24Hr", "DMSO 24Hr KCl 3Hr", "DMSO 24Hr", "TM 24Hr KCl 3Hr"]) == "DMSO 24Hr"
    assert compare._control(["TM+KCl", "Vehicle", "TM"]) == "Vehicle"
    assert compare._control(["TTX", "APV"]) == "APV"


def test_an_anova_block_matches_scipy_and_compares_every_pair_three_ways():
    groups = {"DMSO": [10.0, 11, 12, 10.5], "TM": [14.0, 15, 13.5, 16], "TTX": [10.0, 9, 11, 10.2]}
    rows = compare._anova_block("ais_length", "individual values", groups, True)
    assert all(r["main"] and r["design"] == "individual values" for r in rows)
    data = [groups[t] for t in ("DMSO", "TM", "TTX")]
    anova = rows[0]
    assert anova["test"] == "one-way ANOVA" and anova["p"] == pytest.approx(sps.f_oneway(*data).pvalue, rel=1e-3)
    tukey = {r["groups"]: r["p"] for r in rows if r["test"] == "Tukey HSD"}
    assert tukey["DMSO vs TM"] == pytest.approx(sps.tukey_hsd(*data).pvalue[0, 1], rel=1e-3)
    assert set(tukey) == {"DMSO vs TM", "DMSO vs TTX", "TM vs TTX"}
    holm = [r for r in rows if r["test"] == "Welch t-test (Holm)"]
    assert len(holm) == 3 and all(r["p_holm"] >= r["p"] for r in holm)
    dunnett = {r["groups"]: r["p"] for r in rows if r["test"] == "Dunnett vs control"}
    expected = sps.dunnett(groups["TM"], groups["TTX"], control=groups["DMSO"], rng=0).pvalue
    assert dunnett == {"TM vs DMSO": pytest.approx(expected[0], rel=1e-3),
                       "TTX vs DMSO": pytest.approx(expected[1], rel=1e-3)}
    assert compare._anova_block("ais_length", "individual values", groups, True) == rows   # the same on a re-run


def test_two_treatments_still_get_an_anova_which_is_the_t_test_squared():
    groups = {"DMSO": [10.0, 11, 12], "TM": [14.0, 15, 13.5]}
    anova = compare._anova_block("ais_length", "individual values", groups, False)[0]
    t = sps.ttest_ind(groups["DMSO"], groups["TM"])
    assert anova["statistic"] == pytest.approx(t.statistic ** 2, rel=1e-4)
    assert anova["p"] == pytest.approx(t.pvalue, rel=1e-3)


def test_a_culture_mean_weighs_every_ais_alike_not_each_image(store):
    """Image A: three AIS of 10; image B: one of 20. The culture's DMSO mean
    is 12.5 (every AIS alike), not 15 (the mean of the image means)."""
    batch = culture(store, "C1", {"DMSO": [10, 20], "TM": [5]})
    a = next(r["image"] for r in ais.list_results(store, batch["id"]) if r["length_um"] == 10)
    for _ in range(2):
        ais.add_result(store, batch["id"], a, {"length_um": 10, "pixels": [[1, 1]]}, 1)
    values = compare.collect(store, [batch["id"]])["values"]
    assert compare.culture_means(values, "ais_length")[batch["id"]]["DMSO"] == 12.5
    group = next(g for g in compare.compare(store, [batch["id"]])["groups"] if g["treatment"] == "DMSO")
    assert (group["n"], group["mean"]) == (4, 12.5)


def test_one_batch_is_tested_on_its_ais_and_several_on_culture_means(store):
    one = culture(store, "C1", {"DMSO": [10, 11, 12], "TM": [15, 16, 14]})
    out = compare.compare(store, [one["id"]])
    main = [r for r in out["stats"] if r["main"]]
    assert {r["design"] for r in main} == {"individual values"} and main[0]["test"] == "one-way ANOVA"
    assert out["stats"][0] is main[0] and main[0]["p"] < 0.05
    culture_row = next(r for r in out["stats"] if r["design"] == "culture means")
    assert culture_row["p"] is None and "needs 2" in culture_row["note"]
    assert not any(r["design"] in ("paired", "unpaired") for r in out["stats"]) and out["plots"] == []
    two = culture(store, "C2", {"DMSO": [10, 12], "TM": [16, 15]})
    out = compare.compare(store, [one["id"], two["id"]])
    main = [r for r in out["stats"] if r["main"] and r["measure"] == "ais_length"]
    assert {r["design"] for r in main} == {"culture means"}
    tukey = next(r for r in main if r["test"] == "Tukey HSD")
    assert tukey["groups"] == "DMSO vs TM"
    assert "Tukey" in next(p["svg"] for p in out["plots"] if p["kind"] == "box")


# --- the plots -----------------------------------------------------------------------

C4_C7 = ["TM 24Hr KCl 3Hr", "DMSO 24Hr", "TM 24Hr", "DMSO 24Hr NaCl 3Hr", "TM 24Hr NaCl 3Hr", "DMSO 24Hr KCl 3Hr"]


def test_the_layout_groups_by_first_drug_with_the_control_first_and_short_names():
    lay = compare.layout(C4_C7)
    assert lay["order"] == ["DMSO 24Hr", "DMSO 24Hr NaCl 3Hr", "DMSO 24Hr KCl 3Hr", "TM 24Hr", "TM 24Hr NaCl 3Hr", "TM 24Hr KCl 3Hr"]
    assert [lay["short"][t] for t in lay["order"]] == ["DMSO", "D+NaCl", "D+KCl", "TM", "T+NaCl", "T+KCl"]
    assert lay["colour"]["DMSO 24Hr"] == compare.FAMILY_SHADES[0][0] and lay["colour"]["TM 24Hr"] == compare.FAMILY_SHADES[1][0]
    planned = {frozenset(p) for p in lay["planned"]}
    assert frozenset(("DMSO 24Hr", "DMSO 24Hr KCl 3Hr")) in planned           # add-on vs bare
    assert frozenset(("DMSO 24Hr NaCl 3Hr", "DMSO 24Hr KCl 3Hr")) in planned  # KCl vs its osmolarity control
    assert frozenset(("DMSO 24Hr", "TM 24Hr")) in planned                     # TM vs DMSO, same add-on
    assert frozenset(("DMSO 24Hr KCl 3Hr", "TM 24Hr KCl 3Hr")) in planned
    assert frozenset(("DMSO 24Hr", "TM 24Hr NaCl 3Hr")) not in planned and len(planned) == 9


def test_the_layout_keeps_full_names_when_short_ones_would_clash():
    assert compare.drugs("TM+KCl 3hrs+3hrs") == ["TM", "KCl"] and compare.drugs("KCl 10 mM") == ["KCl"]
    lay = compare.layout(["TTX+KCl", "TM+KCl", "TTX", "TM"])
    assert lay["short"]["TTX+KCl"] == "TTX+KCl" and lay["short"]["TM+KCl"] == "TM+KCl"
    assert compare.layout(["TTX", "APV"])["planned"] == [("APV", "TTX")]


def test_the_box_plot_marks_each_cultures_mean_and_says_ns_without_a_difference(store):
    ids = _three_cultures(store)
    out = compare.compare(store, ids)
    box = next(p["svg"] for p in out["plots"] if p["kind"] == "box")
    assert box.count(" µm</title>") == 9   # 3 cultures x 3 treatments
    assert "by Treatment (C0–C2)" in box and "Culture" in box
    lay = compare.layout(["DMSO", "TTX"])
    each = {"DMSO": [10.0, 11, 12, 13], "TTX": [10.5, 11.5, 12, 12.5]}
    means = {1: {"DMSO": 11.0, "TTX": 11.0}, 2: {"DMSO": 12.0, "TTX": 12.0}}
    flat = compare.box_plot("AIS Length", each, means, {1: "C1", 2: "C2"}, {("DMSO", "TTX"): 0.9}, lay)
    xml.dom.minidom.parseString(flat)
    assert "ns (Tukey)" in flat and "<path" not in flat
    differ = compare.box_plot("AIS Length", each, means, {1: "C1", 2: "C2"}, {("DMSO", "TTX"): 0.0004}, lay)
    assert "ns (Tukey)" not in differ and "***" in differ


def test_the_cdf_is_in_percent_with_a_dashed_median_line():
    lay = compare.layout(["DMSO", "TM"])
    svg = compare.cdf_plot("AIS Length", {"DMSO": [1.0, 2, 3], "TM": [2.0, 3, 4]}, lay)
    xml.dom.minidom.parseString(svg)
    assert "Cumulative Frequency (%)" in svg and 'stroke-dasharray="7 4"' in svg
    assert svg.count("<polyline") == 2


# --- the routes ----------------------------------------------------------------------


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def call(h, method, path, who, **body):
    response = h.get(method, path, session=who, body=body if method == "POST" else None)
    return response.status, json.loads(response.data) if response.data else None


def test_treatments_and_compare_are_admins_only_and_hidden_from_others(h):
    admin, ann = h.user("Root", role=users.ROLE_ADMIN), h.user("Ann")
    batch = culture(h.store, "C1", {"DMSO": [10], "TTX": [5]})
    assert call(h, "GET", f"/api/ais/batches/{batch['id']}/treatments", ann)[0] == 403
    assert call(h, "POST", "/api/ais/compare", ann, batch_ids=[batch["id"]])[0] == 403
    status, out = call(h, "GET", f"/api/ais/batches/{batch['id']}/treatments", admin)
    assert status == 200 and {r["treatment"] for r in out["treatments"]} == {"DMSO", "TTX"}
    key = out["treatments"][0]["key"]
    status, out = call(h, "POST", f"/api/ais/batches/{batch['id']}/treatments", admin, treatments={key: "Vehicle"})
    assert status == 200 and any(r["treatment"] == "Vehicle" for r in out["treatments"])
    assert call(h, "POST", f"/api/ais/batches/{batch['id']}/treatments", admin, treatments={"nope": "x"})[0] == 400
    seen = call(h, "GET", f"/api/ais/batches/{batch['id']}", ann)[1]
    assert all("treatment" not in im for im in seen["images"])
    assert any("treatment" in im for im in call(h, "GET", f"/api/ais/batches/{batch['id']}", admin)[1]["images"])
    status, out = call(h, "POST", "/api/ais/compare", admin, batch_ids=[batch["id"]])
    assert status == 200 and len(out["treatments"]) == 2 and "Vehicle" in out["treatments"]
    assert call(h, "POST", "/api/ais/compare", admin, batch_ids="x")[0] == 400
    # The cards: admins see each saved treatment's count and how many have none; others nothing.
    other = next(im["key"] for im in ais.get_batch(h.store, batch["id"])["images"] if im["key"] != key)
    ais.set_treatments(h.store, batch["id"], {key: "", other: "dmso"})
    culture(h.store, "C2", {"DMSO": [1, 2], "TTX": [3]})
    rows = {b["name"]: b for b in call(h, "GET", "/api/ais/batches", admin)[1]["batches"]}
    assert (rows["C1"]["treatments"], rows["C1"]["untreated"]) == ([["dmso", 1]], 1)
    assert (rows["C2"]["treatments"], rows["C2"]["untreated"]) == ([["DMSO", 2], ["TTX", 1]], 0)
    [row] = [b for b in call(h, "GET", "/api/ais/batches", ann)[1]["batches"] if b["id"] == batch["id"]]
    assert "treatments" not in row and "untreated" not in row


def test_everyone_reads_the_measure_types_and_admins_set_them(h):
    admin, ann = h.user("Root", role=users.ROLE_ADMIN), h.user("Ann")
    assert call(h, "GET", "/api/ais/measure-types", ann) == (200, {"types": list(ais.DEFAULT_TYPES)})
    assert call(h, "POST", "/api/ais/measure-types", ann, types=["X"])[0] == 403
    assert call(h, "POST", "/api/ais/measure-types", admin, types=["Nodes", " Soma distance "]) == \
        (200, {"types": ["Nodes", "Soma distance"]})
    assert call(h, "POST", "/api/ais/measure-types", admin, types=[])[0] == 400
    assert call(h, "GET", "/api/ais/measure-types", ann)[1]["types"] == ["Nodes", "Soma distance"]


# --- the two-way ANOVA ----------------------------------------------------------------


# An unbalanced 2 x 3 design (3/5/4 and 6/2/4 values per cell), checked against
# statsmodels' anova_lm(ols("y ~ C(a, Sum) * C(b, Sum)"), typ=3).
TWO_WAY_Y = [2.040919, -2.555665, 0.418099, -0.26777, -0.152649, 0.084403, -1.719986, 0.068068, -0.265213, 3.923,
             0.825787, 0.247369, 0.418713, 0.031954, -0.355151, 0.309199, 1.181945, 0.461446, 1.957759, 0.800198,
             2.52426, 4.045821, 3.045106, 1.994771]
TWO_WAY_A = [0] * 12 + [1] * 12
TWO_WAY_B = [0] * 3 + [1] * 5 + [2] * 4 + [0] * 6 + [1] * 2 + [2] * 4


def test_two_way_anova_matches_type_iii_on_unequal_groups():
    fit = compare.two_way_anova(TWO_WAY_Y, TWO_WAY_A, TWO_WAY_B, 2, 3)
    assert fit["df"] == 18
    for key, (ss, df, f, p) in {"a": (8.809421, 1, 5.658240, 0.028650), "b": (15.814791, 2, 5.078875, 0.017827),
                                "ab": (2.373021, 2, 0.762089, 0.481169)}.items():
        got = fit["terms"][key]
        assert got[0] == pytest.approx(ss, abs=1e-5) and got[1] == df
        assert got[2] == pytest.approx(f, abs=1e-5) and got[3] == pytest.approx(p, abs=1e-5)


def test_two_way_anova_without_interaction_matches_the_additive_model():
    fit = compare.two_way_anova(TWO_WAY_Y, TWO_WAY_A, TWO_WAY_B, 2, 3, interaction=False)
    assert set(fit["terms"]) == {"a", "b"} and fit["df"] == 20
    assert fit["terms"]["a"][2] == pytest.approx(5.480719, abs=1e-5)
    assert fit["terms"]["b"][2] == pytest.approx(6.308151, abs=1e-5)


def test_two_way_anova_balanced_matches_the_textbook_sums():
    rng = np.random.default_rng(1)
    a = np.repeat(np.arange(2), 12)
    b = np.tile(np.repeat(np.arange(3), 4), 2)
    y = rng.normal(size=24) + a + (b == 2)
    fit = compare.two_way_anova(y, a, b, 2, 3)
    g = y.mean()
    ss_a = 12 * sum((y[a == i].mean() - g) ** 2 for i in range(2))
    ss_b = 8 * sum((y[b == j].mean() - g) ** 2 for j in range(3))
    assert fit["terms"]["a"][0] == pytest.approx(ss_a)
    assert fit["terms"]["b"][0] == pytest.approx(ss_b)


def test_two_way_anova_refuses_an_empty_cell():
    assert compare.two_way_anova([1, 2, 3, 4], [0, 0, 1, 1], [0, 1, 0, 0], 2, 2) == \
        "needs a value in every combination of the two factors"


def test_drug_and_add_on_come_from_the_names_control_first():
    cell, drugs, addons = compare._drug_addon(["TM 24Hr KCl 3Hr", "DMSO 24Hr", "TM 24Hr", "DMSO 24Hr NaCl 3Hr",
                                               "DMSO 24Hr KCl 3Hr", "TM 24Hr NaCl 3Hr"])
    assert drugs == ["DMSO", "TM"] and addons == ["none", "NaCl", "KCl"]
    assert cell["TM 24Hr KCl 3Hr"] == ("TM", "KCl") and cell["DMSO 24Hr"] == ("DMSO", "none")
    assert "same drug and add-on" in compare._drug_addon(["DMSO 24Hr", "DMSO 48Hr", "TM"])


GRID = {"DMSO": 40.0, "DMSO+NaCl": 40.5, "DMSO+KCl": 36.0, "TM": 38.0, "TM+NaCl": 38.5, "TM+KCl": 30.0}


def _grid_cultures(store, count=3):
    # Each culture a little off in its own way per treatment, so the culture means are not purely additive.
    jitter = lambda c, i: ((c * 7 + i * 3) % 5 - 2) * 0.3   # noqa: E731
    return [culture(store, f"C{c}", {t: [m + c - 1 + jitter(c, i), m + c + 1 + jitter(c, i)]
                                     for i, (t, m) in enumerate(GRID.items())})["id"] for c in range(count)]


def test_drug_x_add_on_gives_the_factors_and_simple_effects(store):
    ids = _grid_cultures(store)
    out = compare.compare(store, ids, tests=["twoway"], units=["culture means"])
    rows = [r for r in out["stats"] if r["measure"] == compare.AIS_LENGTH]
    tests = [r["test"] for r in rows]
    assert tests[:3] == ["two-way ANOVA: drug", "two-way ANOVA: add-on", "two-way ANOVA: drug × add-on"]
    assert all(r["family"] == "twoway" and r["main"] for r in rows)
    assert rows[2]["note"].startswith("F(2, 12); Type III")
    simple = {r["groups"]: r for r in rows[3:]}
    # 3 add-on pairs within each of 2 drugs, 1 drug pair at each of 3 add-ons.
    assert len(simple) == 9 and all(r["p_holm"] is not None for r in simple.values())
    assert simple["TM+NaCl vs TM+KCl"]["note"].startswith("within TM")
    assert simple["DMSO+KCl vs TM+KCl"]["note"].startswith("at KCl")
    assert simple["TM+NaCl vs TM+KCl"]["p_holm"] < 0.05


def test_treatment_x_culture_has_no_interaction_on_culture_means(store):
    ids = _grid_cultures(store)
    out = compare.compare(store, ids, tests=["twoway"], design="treatment x culture")
    by_unit = {}
    for r in out["stats"]:
        if r["measure"] == compare.AIS_LENGTH and not r["test"].startswith("simple"):
            by_unit.setdefault(r["design"], []).append(r["test"])
    assert by_unit["culture means"] == ["two-way ANOVA: treatment", "two-way ANOVA: culture"]
    assert by_unit["individual values"][-1] == "two-way ANOVA: treatment × culture"
    # Additive on culture means: the treatment F is the repeated-measures ANOVA's.
    means = compare.culture_means(compare.collect(store, ids)["values"], compare.AIS_LENGTH)
    order = compare.layout(sorted(GRID, key=str.casefold))["order"]
    rm = compare.rm_anova(np.array([[means[b][t] for t in order] for b in ids]))
    first = next(r for r in out["stats"] if r["design"] == "culture means" and r["test"] == "two-way ANOVA: treatment")
    assert first["statistic"] == pytest.approx(rm[0], rel=1e-4)


def test_twoway_says_why_when_the_names_do_not_make_a_grid(store):
    ids = _three_cultures(store)   # DMSO, TTX, KCl: three drugs, no add-ons
    out = compare.compare(store, ids, tests=["twoway"], units=["culture means"])
    rows = [r for r in out["stats"] if r["measure"] == compare.AIS_LENGTH]
    assert [(r["test"], r["note"]) for r in rows] == [("two-way ANOVA", "needs 2 levels of each factor")]


def test_leaving_out_twoway_keeps_the_other_rows_and_a_bad_design_is_refused(store):
    ids = _three_cultures(store)
    without = compare.compare(store, ids, tests=[t for t in compare.TESTS if t != "twoway"])
    assert [r for r in compare.compare(store, ids)["stats"] if r["family"] != "twoway"] == without["stats"]
    with pytest.raises(compare.CompareError):
        compare.compare(store, ids, design="drug")
