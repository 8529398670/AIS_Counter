"""Measurements grouped by treatment, across one batch or several, for the
export's By treatment sheet and the Compare export (static/js/compare.js).

One batch is one culture. Its included images each carry a treatment
(app/models/ais.py set_treatments; "" when none was saved) and give values for
several measures, never mixed:

- "ais_length": each accepted AIS's length_um;
- "ais_soma": each accepted AIS's distance to its soma (the Measure tool's AIS
  modes, soma_um; 3D on a Z-stack), where one was measured;
- "ais_area_blob" / "ais_area_width": its area two ways (app/analysis/area.py);
- "ais_length_3d": on a Z-stack, its length through the slices;
- "ais_volume_voxel" / "ais_volume_tube": on a Z-stack, its volume two ways;
- "type:<name>": each line the Measure tool recorded with that type ("type:"
  for lines with none). A "Soma distance" line stays apart from ais_soma.

Treatments match across batches ignoring case and surrounding spaces; the
spelling first met is the one shown. Spellings that differ otherwise ("TM+KCl
WO" and "TM+KCl+WO") stay apart: whether they are one treatment is the
admin's call, made in the Treatments dialog (its "matched" guesses).

Nothing is averaged per image: every AIS (or line) of a treatment within a
culture counts the same, and a culture's mean for a treatment is the mean of
all of them. Across batches, each culture is one n.

compare() tests the treatments against each other, per measure. First come
two ANOVA blocks, one per unit -- culture means (one per batch per
treatment, needing 2 cultures per treatment) and individual values (every
AIS or line, pooled within its treatment) -- each a one-way ANOVA over every
treatment followed by every pair compared three ways: Tukey HSD, Welch
t-tests with Holm's correction, and Dunnett against the control (_control).
Then a two-way ANOVA per unit (Type III, so unequal groups are fine), its
factors picked per export: drug x add-on (from the names: the first drug,
and what was added to it) or treatment x culture; each followed by its
simple effects, Holm-corrected t-tests on the two-way error.
The main block (rows flagged main) is culture means when it can be worked
out (two cultures or more per treatment), else individual values (one
culture: its AIS); across cultures, individual values are not independent,
so their p-values run low. After them
come the other tests on culture means, paired (only the cultures that have
every treatment) and unpaired, and a KS test of the individual values'
cumulative distributions. With two batches or more it also draws, as SVG
text per measure, a box plot of every value per treatment with each
culture's mean marked (brackets: the culture means' Tukey HSD on the planned
pairs, layout()) and the cumulative frequency of every value.
"""
from __future__ import annotations

import itertools
import math
import re
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
from scipy import stats as sps

from app.core.db import Store
from app.models import ais as batches

AIS_LENGTH = "ais_length"
AIS_SOMA = "ais_soma"
# Each measure with the row field it comes from, in the order they are shown.
ROW_MEASURES = ((AIS_LENGTH, "length_um"), (AIS_SOMA, "soma_um"), ("ais_area_blob", "area_blob_um2"),
                ("ais_area_width", "area_width_um2"), ("ais_length_3d", "length_3d_um"),
                ("ais_volume_voxel", "volume_voxel_um3"), ("ais_volume_tube", "volume_tube_um3"))
TYPE_PREFIX = "type:"
# The names a measure has in the plots when the page sends none.
DEFAULT_LABELS = {AIS_LENGTH: "AIS length", AIS_SOMA: "AIS to soma", "ais_area_blob": "AIS area (blob)",
                  "ais_area_width": "AIS area (widths)", "ais_length_3d": "AIS length 3D",
                  "ais_volume_voxel": "AIS volume (voxels)", "ais_volume_tube": "AIS volume (tube)"}


class CompareError(ValueError):
    """A request compare() refuses, worded for the person making it."""


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _round(v: float | None, places: int = 4) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), places)


def _p(v: float | None) -> float | None:
    """A p-value to 4 significant figures, so a tiny one reads 3.2e-12, not 0."""
    return None if v is None or not math.isfinite(v) else float(f"{float(v):.4g}")


def describe(values: list[float]) -> dict[str, Any]:
    """n, mean, median, SD (sample) and SEM; blanks where there are too few."""
    v = np.asarray(values, dtype=float)
    n = int(v.size)
    if not n:
        return {"n": 0, "mean": None, "median": None, "sd": None, "sem": None}
    sd = float(v.std(ddof=1)) if n > 1 else None
    return {"n": n, "mean": _round(float(v.mean())), "median": _round(float(np.median(v))),
            "sd": _round(sd), "sem": _round(sd / math.sqrt(n)) if sd is not None else None}


# --- the values ------------------------------------------------------------------


def collect(store: Store, batch_ids: list[int]) -> dict[str, Any]:
    """Per included image of the batches, its names, treatment and values,
    and every value on its own: {images, values}."""
    images: list[dict[str, Any]] = []
    values: list[dict[str, Any]] = []
    spelling: dict[str, str] = {}
    for batch_id in batch_ids:
        batch = batches.get_batch(store, batch_id)
        if batch is None:
            raise CompareError("no such batch")
        included = batches.included_keys(batch)
        rows: dict[str, list[dict[str, Any]]] = {}
        for row in batches.list_results(store, batch_id):
            rows.setdefault(row["image"], []).append(row)
        lines: dict[str, list[dict[str, Any]]] = {}
        for line in batches.list_measurements(store, batch_id):
            lines.setdefault(line["image"], []).append(line)
        for im in batch["images"]:
            if im["key"] not in included:
                continue
            given = im.get("treatment", "").strip()
            treatment = spelling.setdefault(given.casefold(), given) if given else ""
            mine = [(measure, r.get(field)) for measure, field in ROW_MEASURES for r in rows.get(im["key"], [])]
            mine += [(TYPE_PREFIX + (m.get("type") or ""), m.get("length_um")) for m in lines.get(im["key"], [])]
            mine = [(measure, float(v)) for measure, v in mine if _number(v)]
            lengths = [v for measure, v in mine if measure == AIS_LENGTH]
            somas = [v for measure, v in mine if measure == AIS_SOMA]
            images.append({"batch_id": batch_id, "batch": batch["name"], "image": im["key"],
                           "original": batches.original_cell(im), "treatment": treatment,
                           "ais": len(lengths), "soma": len(somas)})
            values += [{"batch_id": batch_id, "batch": batch["name"], "image": im["key"],
                        "original": batches.original_cell(im), "treatment": treatment,
                        "measure": measure, "value": v} for measure, v in mine]
    return {"images": images, "values": values}


def _measures(values: list[dict[str, Any]]) -> list[str]:
    """The AIS measures (ROW_MEASURES' order), then the line types by name."""
    found = {v["measure"] for v in values}
    fixed = [m for m, _ in ROW_MEASURES if m in found]
    return fixed + sorted(found - set(fixed), key=str.casefold)


def _treatments(values: list[dict[str, Any]]) -> list[str]:
    """The treatments by name, those without one left out."""
    return sorted({v["treatment"] for v in values if v["treatment"]}, key=str.casefold)


def group_table(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per batch x treatment x measure: n, mean, median, SD, SEM."""
    groups: dict[tuple[int, str, str, str], list[float]] = {}
    for v in values:
        groups.setdefault((v["batch_id"], v["batch"], v["treatment"], v["measure"]), []).append(v["value"])
    return [{"batch_id": b, "batch": name, "treatment": t, "measure": m} | describe(vs)
            for (b, name, t, m), vs in groups.items()]


def culture_means(values: list[dict[str, Any]], measure: str) -> dict[int, dict[str, float]]:
    """{batch id: {treatment: mean}} of one measure: a culture's mean per
    treatment, of every value in it alike (no image means in between)."""
    sums: dict[int, dict[str, list[float]]] = {}
    for v in values:
        if v["measure"] == measure and v["treatment"]:
            sums.setdefault(v["batch_id"], {}).setdefault(v["treatment"], []).append(v["value"])
    return {b: {t: float(np.mean(vs)) for t, vs in by.items()} for b, by in sums.items()}


def pooled_table(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per treatment x measure: every value pooled (n, mean, SD, SEM)
    and the culture means (how many cultures, their mean, SD and SEM)."""
    out = []
    for measure in _measures(values):
        means = culture_means(values, measure)
        for t in _treatments(values):
            pooled = describe([v["value"] for v in values if v["measure"] == measure and v["treatment"] == t])
            if not pooled["n"]:
                continue
            cm = describe([by[t] for by in means.values() if t in by])
            out.append({"treatment": t, "measure": measure, "n": pooled["n"], "mean": pooled["mean"],
                        "sd": pooled["sd"], "sem": pooled["sem"], "cultures": cm["n"], "culture_mean": cm["mean"],
                        "culture_sd": cm["sd"], "culture_sem": cm["sem"]})
    return out


# --- the tests -------------------------------------------------------------------


def holm(ps: list[float | None]) -> list[float | None]:
    """Holm-Bonferroni adjusted p-values, in the order given; None stays None."""
    known = sorted((p, i) for i, p in enumerate(ps) if p is not None)
    m = len(known)
    out: list[float | None] = [None] * len(ps)
    running = 0.0
    for rank, (p, i) in enumerate(known):
        running = max(running, min(1.0, (m - rank) * p))
        out[i] = running
    return out


def rm_anova(data: np.ndarray) -> tuple[float, float, int, int] | None:
    """One-way repeated-measures ANOVA on cultures (rows) x treatments
    (columns): (F, p, df treatment, df error); None when it cannot be
    worked out (fewer than 2 cultures or 2 treatments, or no error left)."""
    n, k = data.shape
    if n < 2 or k < 2:
        return None
    grand = data.mean()
    ss_treat = n * float(((data.mean(axis=0) - grand) ** 2).sum())
    ss_subj = k * float(((data.mean(axis=1) - grand) ** 2).sum())
    ss_error = float(((data - grand) ** 2).sum()) - ss_treat - ss_subj
    df_t, df_e = k - 1, (n - 1) * (k - 1)
    if ss_error <= 1e-12 * max(1.0, ss_treat):
        return None
    f = (ss_treat / df_t) / (ss_error / df_e)
    return f, float(sps.f.sf(f, df_t, df_e)), df_t, df_e


def _row(measure: str, design: str, test: str, groups: str, n: int, statistic: Any = None, p: Any = None,
         note: str = "", main: bool = False, family: str = "") -> dict[str, Any]:
    ok = statistic is not None and p is not None and math.isfinite(statistic) and math.isfinite(p)
    return {"measure": measure, "design": design, "test": test, "groups": groups, "n": n,
            "statistic": _round(statistic) if ok else None, "p": _p(p) if ok else None,
            "p_holm": None, "note": note if ok or note else "could not be worked out", "main": main,
            "family": family}


CONTROL_RE = re.compile(r"\b(dmso|vehicle|control|ctrl|untreated)\b", re.IGNORECASE)


def _control(treatments: list[str]) -> str:
    """The treatment Dunnett compares the others with: one with a control
    word in it (DMSO, vehicle, control, ctrl, untreated), the fewest words
    first, then by name ("DMSO 24Hr" before "DMSO 24Hr KCl 3Hr"); the first
    by name when none has one."""
    named = sorted(treatments, key=str.casefold)
    controls = [t for t in named if CONTROL_RE.search(t)]
    return min(controls, key=lambda t: len(t.split())) if controls else named[0]


UNIT_NOTES = {
    "culture means": "one mean per culture (batch) per treatment",
    "individual values": "every value; not independent cultures, so p runs low",
}


def _anova_block(measure: str, design: str, groups: dict[str, list[float]], main: bool,
                 refused: str = "") -> list[dict[str, Any]]:
    """One unit's ANOVA rows: a one-way ANOVA over every treatment, then
    every pair by Tukey HSD, by Welch t-tests (Holm) and each treatment
    against the control by Dunnett. Tukey and Dunnett p are adjusted
    already. refused (or fewer than 2 values in a treatment): one row
    saying why, nothing tested."""
    treatments = sorted(groups, key=str.casefold)
    data = [np.asarray(groups[t], dtype=float) for t in treatments]
    sizes = [len(d) for d in data]
    total = sum(sizes)
    unit = UNIT_NOTES[design]
    refused = refused or ("" if all(n >= 2 for n in sizes) else f"needs 2 {design} per treatment")
    if refused:
        return [_row(measure, design, "one-way ANOVA", "all", total, note=refused, main=main, family="anova")]
    k = len(treatments)
    f, p = _try(sps.f_oneway, *data)
    rows = [_row(measure, design, "one-way ANOVA", "all", total, f, p,
                 f"F({k - 1}, {total - k}); {unit}" if f is not None else "", main, "anova")]
    pairs = list(itertools.combinations(range(k), 2))
    name = lambda i, j: f"{treatments[i]} vs {treatments[j]}"  # noqa: E731
    try:
        tukey = sps.tukey_hsd(*data)
    except (ValueError, ZeroDivisionError, FloatingPointError):
        tukey = None
    rows += [_row(measure, design, "Tukey HSD", name(i, j), sizes[i] + sizes[j],
                  *((float(tukey.statistic[i, j]), float(tukey.pvalue[i, j])) if tukey is not None else (None, None)),
                  "p adjusted for every pair", main, "tukey") for i, j in pairs]
    rows += _pairwise([_row(measure, design, "Welch t-test (Holm)", name(i, j), sizes[i] + sizes[j],
                            *_try(sps.ttest_ind, data[i], data[j], equal_var=False), "", main, "welch") for i, j in pairs])
    control = _control(treatments)
    c = treatments.index(control)
    others = [i for i in range(k) if i != c]
    try:
        # Seeded: its p comes from a random integration, and an export should not change on a re-run.
        dunnett = sps.dunnett(*[data[i] for i in others], control=data[c], rng=0)
    except (ValueError, ZeroDivisionError, FloatingPointError):
        dunnett = None
    rows += [_row(measure, design, "Dunnett vs control", f"{treatments[i]} vs {control}", sizes[i] + sizes[c],
                  *((float(dunnett.statistic[n]), float(dunnett.pvalue[n])) if dunnett is not None else (None, None)),
                  f"control: {control}; p adjusted", main, "dunnett") for n, i in enumerate(others)]
    return rows


def _try(fn: Any, *args: Any, **kwargs: Any) -> tuple[float | None, float | None]:
    """A scipy test's (statistic, p), or (None, None) when it refuses the data."""
    try:
        result = fn(*args, **kwargs)
    except (ValueError, ZeroDivisionError, FloatingPointError):
        return None, None
    s, p = float(result[0]), float(result[1])
    return (s, p) if math.isfinite(s) and math.isfinite(p) else (None, None)


def _pairwise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    adjusted = holm([r["p"] for r in rows])
    return [r | {"p_holm": _p(a) if a is not None else None} for r, a in zip(rows, adjusted)]


# --- the two-way ANOVA -----------------------------------------------------------

DRUG_ADDON, TREATMENT_CULTURE = "drug x add-on", "treatment x culture"
DESIGNS = (DRUG_ADDON, TREATMENT_CULTURE)


def _effect_columns(level: np.ndarray, count: int) -> np.ndarray:
    """Sum-to-zero (effect) coding: count - 1 columns, the last level -1 in each."""
    cols = np.zeros((level.size, count - 1))
    for i in range(count - 1):
        cols[:, i] = (level == i).astype(float) - (level == count - 1).astype(float)
    return cols


def _design_matrix(a: np.ndarray, b: np.ndarray, na: int, nb: int,
                   interaction: bool) -> tuple[np.ndarray, dict[str, slice]]:
    """Intercept, A, B (and A x B) in effect coding, and each term's columns."""
    ca, cb = _effect_columns(a, na), _effect_columns(b, nb)
    parts = [np.ones((a.size, 1)), ca, cb]
    if interaction:
        parts.append(np.column_stack([ca[:, i] * cb[:, j] for i in range(na - 1) for j in range(nb - 1)])
                     if na > 1 and nb > 1 else np.zeros((a.size, 0)))
    X = np.hstack(parts)
    terms = {"a": slice(1, na), "b": slice(na, na + nb - 1)}
    if interaction:
        terms["ab"] = slice(na + nb - 1, X.shape[1])
    return X, terms


def _rss(X: np.ndarray, y: np.ndarray) -> float:
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    return float(((y - X @ beta) ** 2).sum())


def two_way_anova(y: Any, a: Any, b: Any, na: int, nb: int, interaction: bool = True) -> dict[str, Any] | str:
    """Two-way ANOVA with Type III sums of squares (effect coding), so
    unequal group sizes are fine. y: the values; a, b: each value's level
    index (0..na-1, 0..nb-1). Returns {terms: {a, b, ab?: (SS, df, F, p)},
    mse, df, beta, cov (the coefficients' covariance), interaction}, or a
    reason it cannot be worked out: a level or (with interaction) a cell
    with no values, or no residual degrees of freedom left."""
    y, a, b = np.asarray(y, dtype=float), np.asarray(a, dtype=int), np.asarray(b, dtype=int)
    if na < 2 or nb < 2:
        return "needs 2 levels of each factor"
    if interaction and any(not np.any((a == i) & (b == j)) for i in range(na) for j in range(nb)):
        return "needs a value in every combination of the two factors"
    if any(not np.any(a == i) for i in range(na)) or any(not np.any(b == j) for j in range(nb)):
        return "needs a value at every level of each factor"
    X, terms = _design_matrix(a, b, na, nb, interaction)
    if np.linalg.matrix_rank(X) < X.shape[1]:
        return "the groups do not make a full grid"
    df_e = y.size - X.shape[1]
    if df_e < 1:
        return "no degrees of freedom left for the error"
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    rss = float(((y - X @ beta) ** 2).sum())
    mse = rss / df_e
    if mse <= 1e-12 * max(1.0, float(np.var(y))):
        return "no variation within the groups"
    out: dict[str, tuple[float, int, float, float]] = {}
    for name, cols in terms.items():
        keep = [c for c in range(X.shape[1]) if not (cols.start <= c < cols.stop)]
        ss = max(_rss(X[:, keep], y) - rss, 0.0)
        df = cols.stop - cols.start
        f = (ss / df) / mse
        out[name] = (ss, df, f, float(sps.f.sf(f, df, df_e)))
    return {"terms": out, "mse": mse, "df": df_e, "beta": beta,
            "cov": mse * np.linalg.inv(X.T @ X), "interaction": interaction, "na": na, "nb": nb}


def _cell_row(fit: dict[str, Any], i: int, j: int) -> np.ndarray:
    """The design row of level i of A and level j of B: its fitted mean is row @ beta."""
    X, _ = _design_matrix(np.array([i]), np.array([j]), fit["na"], fit["nb"], fit["interaction"])
    return X[0]


def _contrast(fit: dict[str, Any], c: np.ndarray) -> tuple[float | None, float | None]:
    """A t-test of c @ beta = 0 on the fit's error: (t, two-sided p)."""
    se = math.sqrt(float(c @ fit["cov"] @ c))
    if se <= 0:
        return None, None
    t = float(c @ fit["beta"]) / se
    return t, float(2 * sps.t.sf(abs(t), fit["df"]))


def _drug_addon(treatments: list[str]) -> tuple[dict[str, tuple[str, str]], list[str], list[str]] | str:
    """Each treatment's (drug, add-on) from its name (drugs()): the first
    drug and the ones added after it ("none" when bare), with the levels in
    the plots' order (layout(): the control's drug first, then none, NaCl,
    KCl). A reason instead when two treatments land in one cell."""
    cell: dict[str, tuple[str, str]] = {}
    seen: dict[tuple[str, str], str] = {}
    spelled: dict[str, str] = {}
    for t in layout(treatments)["order"]:
        parsed = drugs(t) or [t]
        drug = spelled.setdefault(parsed[0].casefold(), parsed[0])
        addon = "+".join(parsed[1:])
        addon = spelled.setdefault("+" + addon.casefold(), addon) if addon else "none"
        if (drug.casefold(), addon.casefold()) in seen:
            return f"{seen[(drug.casefold(), addon.casefold())]} and {t} are the same drug and add-on"
        seen[(drug.casefold(), addon.casefold())] = t
        cell[t] = (drug, addon)
    drugs_ = list(dict.fromkeys(d for d, _ in cell.values()))
    addons = list(dict.fromkeys(a for _, a in cell.values()))
    addons.sort(key=lambda a: a != "none")
    return cell, drugs_, addons


def _two_way_block(measure: str, unit: str, data: list[tuple[str, int, float]], design: str,
                   names: dict[int, str], main: bool) -> list[dict[str, Any]]:
    """One unit's two-way ANOVA rows (family "twoway"): the two factors and
    their interaction, then the simple effects, Holm-corrected together, as
    t-tests on the model's error. data: (treatment, batch id, value).
    drug x add-on: every add-on pair within each drug and every drug pair at
    each add-on. treatment x culture: every treatment pair, adjusted for
    culture; on culture means there is one value per cell, so no
    interaction."""
    unit_note = UNIT_NOTES[unit]
    total = len(data)
    treatments = sorted({t for t, _, _ in data}, key=str.casefold)

    def refused(why: str) -> list[dict[str, Any]]:
        return [_row(measure, unit, "two-way ANOVA", "all", total, note=why, main=main, family="twoway")]

    if design == DRUG_ADDON:
        split = _drug_addon(treatments)
        if isinstance(split, str):
            return refused(split)
        cell, a_levels, b_levels = split
        a_name, b_name = "drug", "add-on"
        a_of = {t: a_levels.index(cell[t][0]) for t in treatments}
        b_of = {t: b_levels.index(cell[t][1]) for t in treatments}
        a = [a_of[t] for t, _, _ in data]
        b = [b_of[t] for t, _, _ in data]
        interaction = True
    else:
        lay = layout(treatments)["order"]
        cultures = sorted({c for _, c, _ in data}, key=lambda c: _natural(names.get(c, str(c))))
        a_levels, b_levels = lay, [names.get(c, str(c)) for c in cultures]
        a_name, b_name = "treatment", "culture"
        a = [lay.index(t) for t, _, _ in data]
        b = [cultures.index(c) for _, c, _ in data]
        # One culture mean per culture per treatment leaves nothing for an interaction.
        interaction = unit != "culture means"
    fit = two_way_anova([v for _, _, v in data], a, b, len(a_levels), len(b_levels), interaction)
    if isinstance(fit, str):
        return refused(fit)
    rows = []
    label = {"a": a_name, "b": b_name, "ab": f"{a_name} × {b_name}"}
    for key, (_, df, f, p) in fit["terms"].items():
        extra = "" if interaction else "; no interaction (one value per culture per treatment)"
        rows.append(_row(measure, unit, f"two-way ANOVA: {label[key]}", "all", total, f, p,
                         f"F({df}, {fit['df']}); Type III; {unit_note}{extra}", main, "twoway"))
    sizes = {t: sum(1 for u, _, _ in data if u == t) for t in treatments}
    simple = []
    if design == DRUG_ADDON:
        named = {(a_of[t], b_of[t]): t for t in treatments}
        for i, drug in enumerate(a_levels):
            for j, k in itertools.combinations(range(len(b_levels)), 2):
                simple.append(((i, j), (i, k), f"within {drug}"))
        for j, addon in enumerate(b_levels):
            for i, k in itertools.combinations(range(len(a_levels)), 2):
                simple.append(((i, j), (k, j), f"at {addon}"))
        for one, two, where in simple:
            t1, t2 = named[one], named[two]
            stat, p = _contrast(fit, _cell_row(fit, *one) - _cell_row(fit, *two))
            rows.append(_row(measure, unit, "simple effect (Holm)", f"{t1} vs {t2}", sizes[t1] + sizes[t2],
                             stat, p, f"{where}; t on the two-way error, df {fit['df']}", main, "twoway"))
    else:
        nb = len(b_levels)
        marginal = [sum(_cell_row(fit, i, j) for j in range(nb)) / nb for i in range(len(a_levels))]
        for i, k in itertools.combinations(range(len(a_levels)), 2):
            stat, p = _contrast(fit, marginal[i] - marginal[k])
            rows.append(_row(measure, unit, "simple effect (Holm)", f"{a_levels[i]} vs {a_levels[k]}",
                             sizes[a_levels[i]] + sizes[a_levels[k]], stat, p,
                             f"adjusted for culture; t on the two-way error, df {fit['df']}", main, "twoway"))
    terms = [r for r in rows if r["test"] != "simple effect (Holm)"]
    return terms + _pairwise([r for r in rows if r["test"] == "simple effect (Holm)"])


def _two_way_data(values: list[dict[str, Any]], measure: str, unit: str) -> list[tuple[str, int, float]]:
    """(treatment, batch id, value) per culture mean or value of one measure."""
    mine = [v for v in values if v["measure"] == measure and v["treatment"]]
    if unit == "individual values":
        return [(v["treatment"], v["batch_id"], v["value"]) for v in mine]
    sums: dict[tuple, list[float]] = {}
    for v in mine:
        sums.setdefault((v["treatment"], v["batch_id"]), []).append(v["value"])
    return [(k[0], k[1], float(np.mean(vs))) for k, vs in sums.items()]


def tests_for(values: list[dict[str, Any]], measure: str, names: dict[int, str],
              units: tuple[str, ...] | list[str] = (), design: str = DRUG_ADDON) -> dict[str, Any]:
    """Every test of one measure's treatments: {rows (the two ANOVA
    blocks, main first, then the others), dropped (the cultures left out of
    the paired tests: missing a treatment), brackets (the culture means'
    Tukey HSD p per pair, for the box plot)}. units: the ANOVA blocks to
    pick the main one from (every unit when empty); both are worked
    out regardless, for the box plot's brackets. After the one-way blocks
    come the two-way ANOVA blocks, one per unit, in the same order
    (_two_way_block; design: DESIGNS)."""
    means = culture_means(values, measure)
    treatments = sorted({t for by in means.values() for t in by}, key=str.casefold)
    k = len(treatments)
    if k < 2:
        return {"rows": [], "dropped": [], "brackets": {}}
    by_culture = {t: [by[t] for by in means.values() if t in by] for t in treatments}
    by_value = {t: [v["value"] for v in values if v["measure"] == measure and v["treatment"] == t] for t in treatments}
    blocks_in = [("culture means", by_culture), ("individual values", by_value)]
    candidates = [(d, g) for d, g in blocks_in if not units or d in units] or blocks_in
    main = next((d for d, g in candidates if all(len(g[t]) >= 2 for t in treatments)), candidates[-1][0])
    blocks = {d: _anova_block(measure, d, g, d == main) for d, g in blocks_in}
    anova_rows = blocks[main] + [r for d, _ in blocks_in if d != main for r in blocks[d]]
    two_way = {d: _two_way_block(measure, d, _two_way_data(values, measure, d), design, names, d == main)
               for d, _ in blocks_in}
    anova_rows += two_way[main] + [r for d, _ in blocks_in if d != main for r in two_way[d]]
    brackets: dict[tuple[str, str], float | None] = {}
    for r in blocks["culture means"]:
        if r["test"] == "Tukey HSD":
            a, b = r["groups"].split(" vs ", 1)
            brackets[(a, b)] = r["p"]
    rows: list[dict[str, Any]] = []
    complete = [b for b in means if all(t in means[b] for t in treatments)]
    dropped = [names[b] for b in means if b not in complete]
    paired = np.array([[means[b][t] for t in treatments] for b in complete]) if complete else np.zeros((0, k))
    n = len(complete)
    note = "" if n >= 2 else "needs 2 cultures with every treatment"
    pairs = list(itertools.combinations(range(k), 2))
    if k == 2:
        a, b = (paired[:, 0], paired[:, 1]) if n else ([], [])
        rows.append(_row(measure, "paired", "paired t-test", "all", n, *(_try(sps.ttest_rel, a, b) if n >= 2 else (None, None)), note, family="paired"))
        rows.append(_row(measure, "paired", "Wilcoxon signed-rank", "all", n,
                         *(_try(sps.wilcoxon, a, b) if n >= 2 else (None, None)), note, family="paired"))
    else:
        anova = rm_anova(paired) if n >= 2 else None
        rows.append(_row(measure, "paired", "repeated-measures ANOVA", "all", n, *(anova[:2] if anova else (None, None)),
                         note or (f"F({anova[2]}, {anova[3]})" if anova else ""), family="paired"))
        rows.append(_row(measure, "paired", "Friedman", "all", n,
                         *(_try(sps.friedmanchisquare, *paired.T) if n >= 2 else (None, None)), note, family="paired"))
        pair_rows = [_row(measure, "paired", "paired t-test (Holm)", f"{treatments[i]} vs {treatments[j]}", n,
                          *(_try(sps.ttest_rel, paired[:, i], paired[:, j]) if n >= 2 else (None, None)), note, family="paired")
                     for i, j in pairs]
        rows += _pairwise(pair_rows)
    groups = [[by[t] for by in means.values() if t in by] for t in treatments]
    sizes = [len(g) for g in groups]
    enough = all(s >= 2 for s in sizes)
    unote = "" if enough else "needs 2 cultures per treatment"
    total = sum(sizes)
    if k == 2:
        rows.append(_row(measure, "unpaired", "Welch t-test", "all", total,
                         *(_try(sps.ttest_ind, groups[0], groups[1], equal_var=False) if enough else (None, None)), unote, family="unpaired"))
        rows.append(_row(measure, "unpaired", "Mann-Whitney U", "all", total,
                         *(_try(sps.mannwhitneyu, groups[0], groups[1]) if enough else (None, None)), unote, family="unpaired"))
    else:
        rows.append(_row(measure, "unpaired", "one-way ANOVA", "all", total,
                         *(_try(sps.f_oneway, *groups) if enough else (None, None)), unote, family="unpaired"))
        rows.append(_row(measure, "unpaired", "Kruskal-Wallis", "all", total,
                         *(_try(sps.kruskal, *groups) if enough else (None, None)), unote, family="unpaired"))
        rows += _pairwise([_row(measure, "unpaired", "Welch t-test (Holm)", f"{treatments[i]} vs {treatments[j]}",
                                sizes[i] + sizes[j],
                                *(_try(sps.ttest_ind, groups[i], groups[j], equal_var=False) if enough else (None, None)),
                                unote, family="unpaired") for i, j in pairs])
    each = {t: [v["value"] for v in values if v["measure"] == measure and v["treatment"] == t] for t in treatments}
    rows += _pairwise([_row(measure, "individual values", "Kolmogorov-Smirnov (Holm)", f"{treatments[i]} vs {treatments[j]}",
                            len(each[treatments[i]]) + len(each[treatments[j]]),
                            *_try(sps.ks_2samp, each[treatments[i]], each[treatments[j]]),
                            "individual values, not culture means", family="ks") for i, j in pairs])
    return {"rows": anova_rows + rows, "dropped": dropped, "brackets": brackets}


# --- the plots -------------------------------------------------------------------

INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#ffffff"
MEDIAN = "#ff7f0e"
FONT = "font-family=\"Helvetica, Arial, sans-serif\""
# Shades per family of treatments (one first drug each): the bare treatment,
# then its add-ons in order. The control family is blue, the next red.
FAMILY_SHADES = (("#3a8fd9", "#5dade2", "#1abc9c", "#2471a3"), ("#e74c3c", "#ec7063", "#f39c12", "#b03a2e"),
                 ("#27ae60", "#7dcea0", "#16a085", "#1e8449"), ("#8e44ad", "#bb8fce", "#d35400", "#6c3483"))
# Add-ons in this order within a family: NaCl is KCl's osmolarity control.
ADDON_ORDER = ("nacl", "kcl")
TIME_RE = re.compile(r"^\d+(\.\d+)?\s*(h|hr|hrs|hour|hours|min|mins|d|days?)$", re.IGNORECASE)
UNIT_WORDS = {"mm", "um", "µm", "nm", "mg", "ml", "%", "hr", "hrs", "h", "min", "hours"}


def drugs(treatment: str) -> list[str]:
    """The drugs in a treatment's name, in the order added: times, doses and
    units dropped ("DMSO 24Hr KCl 3Hr" and "DMSO+KCl 24hrs+3hrs" -> DMSO, KCl)."""
    tokens = [t for t in re.split(r"[\s+]+", treatment) if t]
    return [t for t in tokens if not TIME_RE.match(t) and not t[0].isdigit() and t.casefold() not in UNIT_WORDS]


def layout(treatments: list[str]) -> dict[str, Any]:
    """How the plots show the treatments: {order, short, colour, planned}.
    Treatments are grouped into families by their first drug (the first drug
    stays on when a second is added), the control's family first; in a
    family the bare treatment first, then NaCl, KCl, then the rest by name.
    short: the first drug alone, or its initial + the add-ons ("D+NaCl"),
    the full names when that would be ambiguous. colour: a shade of the
    family's colour. planned: the pairs worth a bracket -- in a family, bare
    vs each add-on and NaCl vs each other add-on; across families, the
    control's family vs each other at the same add-ons; every pair when
    that leaves none."""
    parsed = {t: drugs(t) or [t] for t in treatments}
    first = {t: d[0].casefold() for t, d in parsed.items()}
    addon = {t: tuple(x.casefold() for x in d[1:]) for t, d in parsed.items()}
    control = first[_control(treatments)] if treatments else ""
    families = sorted(set(first.values()), key=lambda f: (f != control, f))

    def addon_key(t: str) -> tuple:
        a = addon[t]
        return (len(a) > 0, ADDON_ORDER.index(a[0]) if a and a[0] in ADDON_ORDER else len(ADDON_ORDER), a, t.casefold())

    order: list[str] = []
    colour: dict[str, str] = {}
    for f, family in enumerate(families):
        members = sorted((t for t in treatments if first[t] == family), key=addon_key)
        shades = FAMILY_SHADES[f % len(FAMILY_SHADES)]
        for i, t in enumerate(members):
            colour[t] = shades[i % len(shades)]
        order += members
    lead = {t: parsed[t][0] for t in treatments}
    initials = {f: next(lead[t] for t in treatments if first[t] == f)[0].upper() for f in families}
    unique_initials = len(set(initials.values())) == len(initials)
    short = {t: "+".join([initials[first[t]] if unique_initials else lead[t]] + parsed[t][1:]) if addon[t] else lead[t]
             for t in treatments}
    if len(set(short.values())) != len(short):
        short = {t: t for t in treatments}
    planned: list[tuple[str, str]] = []
    for family in families:
        members = [t for t in order if first[t] == family]
        bare = next((t for t in members if not addon[t]), None)
        nacl = next((t for t in members if addon[t] == ("nacl",)), None)
        for t in members:
            if bare and t != bare:
                planned.append((bare, t))
            if nacl and addon[t] and t != nacl:
                planned.append((nacl, t))
    for t in order:
        if first[t] != control:
            continue
        for u in order:
            if first[u] != control and addon[u] == addon[t]:
                planned.append((t, u))
    if not planned:
        planned = list(itertools.combinations(order, 2))
    return {"order": order, "short": short, "colour": colour, "planned": list(dict.fromkeys(planned))}


def title_case(text: str) -> str:
    """"AIS length" -> "AIS Length": each word capitalised but short joining
    words, and words already holding a capital left alone."""
    small = {"to", "of", "and", "or", "vs", "in", "on", "per"}
    words = text.split(" ")
    return " ".join(w if (i and w in small) or any(c.isupper() for c in w) else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))


def _natural(name: str) -> list:
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", name)]


def culture_span(names: list[str]) -> str:
    """"C4–C7" for more than two cultures, else their names joined."""
    ordered = sorted(names, key=_natural)
    return f"{ordered[0]}–{ordered[-1]}" if len(ordered) > 2 else ", ".join(ordered)


def _ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round tick values covering lo..hi."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    step = 10 ** math.floor(math.log10(raw))
    step *= next(m for m in (1, 2, 2.5, 5, 10) if m * step >= raw)
    start = math.floor(lo / step) * step
    return [round(start + i * step, 10) for i in range(int(math.ceil((hi - start) / step - 1e-9)) + 1)]


def _fmt(v: float) -> str:
    return f"{v:g}"


def stars(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


def _svg(width: int, height: int, body: list[str], title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'{FONT} font-size="12"><title>{escape(title)}</title><rect width="100%" height="100%" fill="{SURFACE}"/>'
            + "".join(body) + "</svg>")


def _text_px(text: str, size: float = 12) -> float:
    """Rough rendered width of Helvetica text: capitals and digits run wider."""
    return sum(0.72 if c.isupper() else 0.28 if c in " .,:;il|" else 0.56 for c in text) * size


def _wrap(text: str, width: float, size: float = 12) -> list[str]:
    """Greedy word wrap of a label to lines no wider than width (a single
    longer word keeps a line of its own)."""
    lines: list[str] = []
    for word in text.split():
        if lines and _text_px(lines[-1] + " " + word, size) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


MARKERS = ("circle", "square", "triangle", "diamond", "triangle-down", "pentagon", "hexagon", "star")


def marker(shape: str, cx: float, cy: float, r: float, fill: str = INK, stroke: str = SURFACE,
           tip: str = "") -> str:
    """A matplotlib-like marker centred on (cx, cy), about 2r across."""
    def poly(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{cx + px * r:.1f},{cy + py * r:.1f}" for px, py in points)

    def regular(n: int, turn: float = -90) -> list[tuple[float, float]]:
        return [(math.cos(math.radians(turn + 360 * i / n)), math.sin(math.radians(turn + 360 * i / n))) for i in range(n)]

    paint = f'fill="{fill}" stroke="{stroke}" stroke-width="1"'
    title = f"<title>{escape(tip)}</title>" if tip else ""
    if shape == "circle":
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" {paint}>{title}</circle>'
    if shape == "square":
        s = r * 0.9
        return f'<rect x="{cx - s:.1f}" y="{cy - s:.1f}" width="{2 * s:.1f}" height="{2 * s:.1f}" {paint}>{title}</rect>'
    points = {"triangle": [(0, -1.1), (1, 0.75), (-1, 0.75)], "triangle-down": [(0, 1.1), (1, -0.75), (-1, -0.75)],
              "diamond": [(0, -1.25), (1, 0), (0, 1.25), (-1, 0)], "pentagon": regular(5), "hexagon": regular(6),
              "star": [(p[0] * (1.2 if i % 2 == 0 else 0.5), p[1] * (1.2 if i % 2 == 0 else 0.5))
                       for i, p in enumerate(regular(10))]}[shape]
    return f'<polygon points="{poly(points)}" {paint}>{title}</polygon>'


def _axes(left: float, top: float, w: float, h: float) -> str:
    return f'<rect x="{left}" y="{top}" width="{w}" height="{h}" fill="none" stroke="{INK}" stroke-width="1"/>'


def _box_stats(vs: np.ndarray) -> tuple[float, float, float, float, float]:
    """Quartiles and whiskers to the furthest value within 1.5 IQR."""
    q1, med, q3 = np.percentile(vs, [25, 50, 75])
    iqr = q3 - q1
    lo = float(vs[vs >= q1 - 1.5 * iqr].min())
    hi = float(vs[vs <= q3 + 1.5 * iqr].max())
    return lo, float(q1), float(med), float(q3), hi


def _find(brackets: dict[tuple[str, str], float | None], a: str, b: str) -> float | None:
    return brackets.get((a, b), brackets.get((b, a)))


def box_plot(measure_name: str, each: dict[str, list[float]], means: dict[int, dict[str, float]],
             names: dict[int, str], brackets: dict[tuple[str, str], float | None], lay: dict[str, Any]) -> str:
    """Every value per treatment: a box (quartiles, whiskers to 1.5 IQR) in
    the treatment's colour over its values as faint jittered dots, each
    culture's mean as a black marker of that culture's shape, and brackets
    over the planned pairs the culture means' Tukey HSD finds to differ ("ns
    (Tukey)" when none does)."""
    order = [t for t in lay["order"] if each.get(t)]
    short, colour = lay["short"], lay["colour"]
    k = len(order)
    cultures = sorted(means, key=lambda b: _natural(names[b]))
    shape = {b: MARKERS[i % len(MARKERS)] for i, b in enumerate(cultures)}
    width, plot_h = max(1000, 70 + 30 + 130 * k), 470
    slot = (width - 70 - 30) / max(k, 1)
    wrapped = {t: _wrap(short[t], slot - 10, 14) for t in order}
    lines = max((len(v) for v in wrapped.values()), default=1)
    left, right, top = 70, 30, 50
    plot_w = width - left - right
    height = top + plot_h + 40 + 17 * (lines - 1) + 30
    x = {t: left + slot * (i + 0.5) for i, t in enumerate(order)}
    stats = {t: _box_stats(np.asarray(each[t], dtype=float)) for t in order}
    significant = [(a, b, p) for a, b in lay["planned"] if a in x and b in x
                   for p in [_find(brackets, a, b)] if p is not None and p < 0.05]
    significant.sort(key=lambda s: (abs(order.index(s[1]) - order.index(s[0])), order.index(min(s[:2], key=order.index))))
    every = [v for t in order for v in each[t]]
    # The axis stops at the 99.5th percentile (or the whiskers and means, if
    # higher), so a lone far value does not squash the boxes; the note says
    # how many values lie above it.
    data_hi = max([float(np.percentile(every, 99.5))] + [v for by in means.values() for v in by.values()]) if every else 1.0
    whisk_hi = max((s[4] for s in stats.values()), default=data_hi)
    data_hi = max(data_hi, whisk_hi)
    span = max(data_hi, 1e-9)
    step = 0.07 * span
    base = whisk_hi + 0.02 * span
    top_needed = base + step * len(significant) + (0.03 * span if significant else 0)
    ticks = _ticks(0.0, max(data_hi, top_needed))
    y0, y1 = ticks[0], ticks[-1]
    y = lambda v: top + plot_h - (v - y0) / (y1 - y0) * plot_h   # noqa: E731
    body = [f'<text x="{left + plot_w / 2:.0f}" y="32" text-anchor="middle" font-size="18" font-weight="bold" fill="{INK}">'
            f'{escape(measure_name)} by Treatment ({escape(culture_span([names[b] for b in cultures]))})</text>']
    for t in ticks:
        body.append(f'<line x1="{left - 5}" x2="{left}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{INK}"/>')
        body.append(f'<text x="{left - 8}" y="{y(t) + 4.5:.1f}" text-anchor="end" font-size="13" fill="{INK}">{_fmt(t)}</text>')
    body.append(f'<text transform="translate(22 {top + plot_h / 2:.0f}) rotate(-90)" text-anchor="middle" font-size="15" '
                f'fill="{INK}">{escape(measure_name)} (µm)</text>')
    rng = np.random.default_rng(0)
    above = 0
    for t in order:
        cx = x[t]
        half = min(0.25 * slot, 60)
        for v in each[t]:
            jx = cx + rng.uniform(-0.6, 0.6) * half
            if v > y1:
                above += 1
                continue
            body.append(f'<circle cx="{jx:.1f}" cy="{y(v):.1f}" r="1.9" fill="{colour[t]}" fill-opacity="0.3"/>')
        lo, q1, med, q3, hi = stats[t]
        cap = half * 0.5
        body.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(q3):.1f}" y2="{y(hi):.1f}" stroke="{INK}" stroke-width="1.2"/>')
        body.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(q1):.1f}" y2="{y(lo):.1f}" stroke="{INK}" stroke-width="1.2"/>')
        for w in (lo, hi):
            body.append(f'<line x1="{cx - cap:.1f}" x2="{cx + cap:.1f}" y1="{y(w):.1f}" y2="{y(w):.1f}" stroke="{INK}" stroke-width="1.2"/>')
        body.append(f'<rect x="{cx - half:.1f}" y="{y(q3):.1f}" width="{2 * half:.1f}" height="{max(y(q1) - y(q3), 1):.1f}" '
                    f'fill="{colour[t]}" fill-opacity="0.65" stroke="#333333" stroke-opacity="0.8" stroke-width="1.2"/>')
        body.append(f'<line x1="{cx - half:.1f}" x2="{cx + half:.1f}" y1="{y(med):.1f}" y2="{y(med):.1f}" stroke="{MEDIAN}" stroke-width="1.6"/>')
        for b in cultures:
            if t in means[b]:
                body.append(marker(shape[b], cx, y(means[b][t]), 6, tip=f"{names[b]}: {means[b][t]:.3f} µm"))
        label = "".join(f'<tspan x="{cx:.1f}" dy="{0 if i == 0 else 17}">{escape(line)}</tspan>'
                        for i, line in enumerate(wrapped[t]))
        body.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{top + plot_h}" y2="{top + plot_h + 5}" stroke="{INK}"/>')
        body.append(f'<text x="{cx:.1f}" y="{top + plot_h + 22}" text-anchor="middle" font-size="14" fill="{INK}">{label}</text>')
        body.append(f'<text x="{cx:.1f}" y="{top + plot_h + 38 + 17 * (lines - 1)}" text-anchor="middle" font-size="11" '
                    f'fill="{MUTED}">n = {len(each[t])}</text>')
    for i, (a, b, p) in enumerate(significant):
        level = y(base + step * (i + 1))
        body.append(f'<path d="M{x[a]:.1f},{level + 8:.1f} V{level:.1f} H{x[b]:.1f} V{level + 8:.1f}" fill="none" stroke="{INK}" stroke-width="1.2"/>')
        body.append(f'<text x="{(x[a] + x[b]) / 2:.1f}" y="{level - 4:.1f}" text-anchor="middle" font-size="15" fill="{INK}">{stars(p)}</text>')
    if not significant:
        known = any(_find(brackets, a, b) is not None for a, b in lay["planned"])
        badge = "ns (Tukey)" if known else "Tukey: n/a"
        bw = _text_px(badge, 14) + 16
        bx, by = left + plot_w - bw - 12, top + 12
        body.append(f'<rect x="{bx:.1f}" y="{by}" width="{bw:.1f}" height="26" rx="5" fill="#dddddd" stroke="{INK}"/>')
        body.append(f'<text x="{bx + bw / 2:.1f}" y="{by + 18}" text-anchor="middle" font-size="14" fill="{INK}">{badge}</text>')
    if cultures:
        lw = max(_text_px(names[b], 12) for b in cultures) + 44
        lw = max(lw, _text_px("Culture", 13) + 16)
        lx, ly = left + 8, top + 8
        body.append(f'<rect x="{lx}" y="{ly}" width="{lw:.1f}" height="{28 + 22 * len(cultures)}" rx="4" fill="{SURFACE}" '
                    f'fill-opacity="0.85" stroke="#cccccc"/>')
        body.append(f'<text x="{lx + lw / 2:.1f}" y="{ly + 19}" text-anchor="middle" font-size="13" fill="{INK}">Culture</text>')
        for i, b in enumerate(cultures):
            my = ly + 38 + 22 * i
            body.append(marker(shape[b], lx + 18, my, 5.5, stroke=INK))
            body.append(f'<text x="{lx + 34}" y="{my + 4}" font-size="12" fill="{INK}">{escape(names[b])}</text>')
    body.append(_axes(left, top, plot_w, plot_h))
    note = ("Boxes and dots: every value. Markers: culture means. Brackets: Tukey HSD on the culture means "
            "(planned pairs), * p &lt; 0.05, ** p &lt; 0.01, *** p &lt; 0.001.")
    if above:
        note += f" {above} value{'s' if above != 1 else ''} above {_fmt(y1)} µm not shown."
    body.append(f'<text x="{left}" y="{height - 10}" font-size="11" fill="{MUTED}">{note}</text>')
    return _svg(width, height, body, f"{measure_name} by treatment")


def cdf_plot(measure_name: str, each: dict[str, list[float]], lay: dict[str, Any]) -> str:
    """The cumulative distribution of every value per treatment: a step line
    each in the treatment's colour, y in percent with a dashed 50 % line, x
    cut at a round number past the 99.5th percentile, legend inside."""
    order = [t for t in lay["order"] if each.get(t)]
    left, right, top, bottom = 80, 30, 50, 66
    plot_w, plot_h = 790, 500
    width, height = left + plot_w + right, top + plot_h + bottom
    every = np.asarray([v for t in order for v in each[t]], dtype=float)
    hi = float(np.percentile(every, 99.5)) if every.size else 1.0
    ticks = _ticks(min(0.0, float(every.min())) if every.size else 0.0, hi)
    x0, x1 = ticks[0], ticks[-1]
    x = lambda v: left + (v - x0) / (x1 - x0) * plot_w   # noqa: E731
    y = lambda f: top + plot_h - (f + 5) / 110 * plot_h   # noqa: E731   (-5..105 %)
    body = [f'<text x="{left + plot_w / 2:.0f}" y="32" text-anchor="middle" font-size="18" font-weight="bold" fill="{INK}">'
            f'Cumulative Frequency: {escape(measure_name)} by Treatment</text>',
            f'<clipPath id="plot"><rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}"/></clipPath>']
    for f in range(0, 101, 20):
        body.append(f'<line x1="{left - 5}" x2="{left}" y1="{y(f):.1f}" y2="{y(f):.1f}" stroke="{INK}"/>')
        body.append(f'<text x="{left - 8}" y="{y(f) + 4.5:.1f}" text-anchor="end" font-size="13" fill="{INK}">{f}</text>')
    for t in ticks:
        body.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top + plot_h}" y2="{top + plot_h + 5}" stroke="{INK}"/>')
        body.append(f'<text x="{x(t):.1f}" y="{top + plot_h + 21}" text-anchor="middle" font-size="13" fill="{INK}">{_fmt(t)}</text>')
    body.append(f'<text x="{left + plot_w / 2:.0f}" y="{top + plot_h + 50}" text-anchor="middle" font-size="16" fill="{INK}">'
                f'{escape(measure_name)} (µm)</text>')
    body.append(f'<text transform="translate(26 {top + plot_h / 2:.0f}) rotate(-90)" text-anchor="middle" font-size="16" '
                f'fill="{INK}">Cumulative Frequency (%)</text>')
    body.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y(50):.1f}" y2="{y(50):.1f}" stroke="#bbbbbb" '
                f'stroke-width="1.6" stroke-dasharray="7 4"/>')
    for t in order:
        vs = sorted(each[t])
        n = len(vs)
        pts = [f"{x(vs[0]):.1f},{y(0):.1f}"]
        for j, v in enumerate(vs):
            pts.append(f"{x(v):.1f},{y(100 * j / n):.1f}")
            pts.append(f"{x(v):.1f},{y(100 * (j + 1) / n):.1f}")
        pts.append(f"{x(x1) + 10:.1f},{y(100):.1f}")
        body.append(f'<polyline clip-path="url(#plot)" fill="none" stroke="{lay["colour"][t]}" stroke-width="2.4" '
                    f'stroke-linejoin="round" points="{" ".join(pts)}"><title>{escape(t)} (n = {n})</title></polyline>')
    labels = [lay["short"][t] for t in order]
    lw = max((_text_px(s, 13) for s in labels), default=0) + 56
    lh = 10 + 24 * len(order)
    lx, ly = left + plot_w - lw - 10, top + plot_h - lh - 10
    body.append(f'<rect x="{lx:.1f}" y="{ly:.1f}" width="{lw:.1f}" height="{lh}" rx="4" fill="{SURFACE}" fill-opacity="0.85" stroke="#cccccc"/>')
    for i, t in enumerate(order):
        my = ly + 17 + 24 * i
        body.append(f'<line x1="{lx + 10:.1f}" x2="{lx + 38:.1f}" y1="{my:.1f}" y2="{my:.1f}" stroke="{lay["colour"][t]}" stroke-width="2.4"/>')
        body.append(f'<text x="{lx + 46:.1f}" y="{my + 4.5:.1f}" font-size="13" fill="{INK}">{escape(lay["short"][t])}</text>')
    body.append(_axes(left, top, plot_w, plot_h))
    return _svg(width, height, body, f"{measure_name}: cumulative frequency")


# --- all of it -------------------------------------------------------------------


TESTS = ("anova", "tukey", "welch", "dunnett", "twoway", "paired", "unpaired", "ks")
BLOCK_TESTS = ("anova", "tukey", "welch", "dunnett", "twoway")   # the ANOVA blocks' tests, run per unit
UNITS = ("culture means", "individual values")
# Units there were once, still accepted and left out: nothing is averaged per image now.
RETIRED_UNITS = ("image means",)


def _choice(value: Any, known: tuple[str, ...], what: str, retired: tuple[str, ...] = ()) -> tuple[str, ...]:
    """A list of known keys (None: all of them), in known's order; retired
    keys are dropped."""
    if value is None:
        return known
    if isinstance(value, list):
        value = [v for v in value if v not in retired]
    if not isinstance(value, list) or not all(isinstance(v, str) and v in known for v in value):
        raise CompareError(f"{what} must be a list of: {', '.join(known)}")
    return tuple(k for k in known if k in value)


def _chosen(row: dict[str, Any], tests: tuple[str, ...], units: tuple[str, ...]) -> bool:
    if row["family"] not in tests:
        return False
    return row["family"] not in BLOCK_TESTS or row["design"] in units


def compare(store: Store, batch_ids: Any, labels: Any = None, tests: Any = None, units: Any = None,
            design: Any = None) -> dict[str, Any]:
    """The batches' values grouped by treatment: {measures, treatments,
    images, values, groups, pooled, stats, dropped, plots}. With one batch
    the stats are the ANOVA blocks and the KS tests (the culture means'
    block saying it needs 2 cultures), with no plots; the box plot and the
    cumulative distributions need two batches or more. labels: {measure:
    name} for the plots' titles. tests (TESTS) and units (UNITS): which
    stats rows to keep, every one when None; units narrows the ANOVA
    blocks only (paired and unpaired are on culture means, KS on individual
    values). design (DESIGNS): the two-way ANOVA's factors, drug x add-on
    when None. The plots do not depend on them."""
    if not isinstance(batch_ids, list) or not batch_ids or len(batch_ids) > 200 or \
            not all(isinstance(b, int) and not isinstance(b, bool) for b in batch_ids):
        raise CompareError("batch_ids must be a list of batch ids")
    tests = _choice(tests, TESTS, "tests")
    units = _choice(units, UNITS, "units", RETIRED_UNITS)
    design = DRUG_ADDON if design is None else design
    if design not in DESIGNS:
        raise CompareError(f"design must be one of: {', '.join(DESIGNS)}")
    if not units and any(t in BLOCK_TESTS for t in tests):
        raise CompareError("the ANOVA tests need at least one unit")
    batch_ids = list(dict.fromkeys(batch_ids))
    names = labels if isinstance(labels, dict) else {}
    found = collect(store, batch_ids)
    values = found["values"]
    out: dict[str, Any] = found | {"measures": _measures(values), "treatments": _treatments(values),
                                   "groups": group_table(values), "pooled": pooled_table(values),
                                   "stats": [], "dropped": [], "plots": []}
    several = len(batch_ids) > 1
    batch_names = {}
    for b in batch_ids:
        batch = batches.get_batch(store, b)
        batch_names[b] = batch["name"] if batch else str(b)
    for measure in out["measures"]:
        tested = tests_for(values, measure, batch_names, units, design)
        rows = [r for r in tested["rows"] if _chosen(r, tests, units)]
        if not several:
            # One culture: the paired and unpaired culture-mean tests have nothing to work on.
            out["stats"] += [r for r in rows if r["design"] not in ("paired", "unpaired")]
            continue
        out["stats"] += rows
        if "paired" in tests:
            out["dropped"] += [{"measure": measure, "batch": b} for b in tested["dropped"]]
        name = names.get(measure) if isinstance(names.get(measure), str) else None
        name = title_case(name or DEFAULT_LABELS.get(measure) or measure[len(TYPE_PREFIX):] or "(no type)")
        means = culture_means(values, measure)
        treatments = sorted({t for by in means.values() for t in by}, key=str.casefold)
        if not treatments:
            continue
        each = {t: [v["value"] for v in values if v["measure"] == measure and v["treatment"] == t] for t in treatments}
        lay = layout(treatments)
        out["plots"].append({"measure": measure, "kind": "box",
                             "svg": box_plot(name, each, means, batch_names, tested["brackets"], lay)})
        out["plots"].append({"measure": measure, "kind": "cdf", "svg": cdf_plot(name, each, lay)})
    return out
