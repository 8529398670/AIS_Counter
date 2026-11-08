"""Measurements grouped by treatment, across one batch or several, for the
export's By treatment sheet and the Compare export (static/js/compare.js).

One batch is one culture. Its included images each carry a treatment
(app/models/ais.py set_treatments; "" when none was saved) and give values for
several measures, never mixed:

- "ais_length": each accepted AIS's length_um;
- "ais_soma": each accepted AIS's distance to its soma (the Measure tool's AIS
  modes, soma_um), where one was measured;
- "type:<name>": each line the Measure tool recorded with that type ("type:"
  for lines with none). A "Soma distance" line stays apart from ais_soma.

Treatments match across batches ignoring case and surrounding spaces; the
spelling first met is the one shown. Spellings that differ otherwise ("TM+KCl
WO" and "TM+KCl+WO") stay apart: whether they are one treatment is the
admin's call, made in the Treatments dialog (its "matched" guesses).

compare() tests the treatments against each other, per measure. First come
three ANOVA blocks, one per unit -- culture means (one per batch per
treatment, needing 2 cultures per treatment), image means (one per image)
and individual values (every AIS or line) -- each a one-way ANOVA over every
treatment followed by every pair compared three ways: Tukey HSD, Welch
t-tests with Holm's correction, and Dunnett against the control (_control).
The main block (rows flagged main) is culture means when it can be worked
out, else image means, else individual values; image means and individual
values are not independent cultures, so their p-values run low. After them
come the other tests on culture means, paired (only the cultures that have
every treatment) and unpaired, and a KS test of the individual values'
cumulative distributions. With two batches or more it also draws a box plot
of the culture means (brackets: their Tukey HSD) and the cumulative
distributions as SVG text per measure.
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
TYPE_PREFIX = "type:"
# The names a measure has in the plots when the page sends none.
DEFAULT_LABELS = {AIS_LENGTH: "AIS length", AIS_SOMA: "AIS to soma"}


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
            mine = [(AIS_LENGTH, r.get("length_um")) for r in rows.get(im["key"], [])]
            mine += [(AIS_SOMA, r.get("soma_um")) for r in rows.get(im["key"], [])]
            mine += [(TYPE_PREFIX + (m.get("type") or ""), m.get("length_um")) for m in lines.get(im["key"], [])]
            mine = [(measure, float(v)) for measure, v in mine if _number(v)]
            lengths = [v for measure, v in mine if measure == AIS_LENGTH]
            somas = [v for measure, v in mine if measure == AIS_SOMA]
            images.append({"batch_id": batch_id, "batch": batch["name"], "image": im["key"],
                           "original": batches.original_cell(im), "treatment": treatment,
                           "ais": len(lengths), "mean_length": describe(lengths)["mean"],
                           "soma": len(somas), "mean_soma": describe(somas)["mean"]})
            values += [{"batch_id": batch_id, "batch": batch["name"], "image": im["key"],
                        "original": batches.original_cell(im), "treatment": treatment,
                        "measure": measure, "value": v} for measure, v in mine]
    return {"images": images, "values": values}


def _measures(values: list[dict[str, Any]]) -> list[str]:
    """AIS length, AIS to soma, then the line types by name."""
    found = {v["measure"] for v in values}
    fixed = [m for m in (AIS_LENGTH, AIS_SOMA) if m in found]
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


def image_means(values: list[dict[str, Any]], measure: str) -> dict[str, list[float]]:
    """{treatment: [mean of each image's values]} of one measure."""
    sums: dict[str, dict[tuple[int, str], list[float]]] = {}
    for v in values:
        if v["measure"] == measure and v["treatment"]:
            sums.setdefault(v["treatment"], {}).setdefault((v["batch_id"], v["image"]), []).append(v["value"])
    return {t: [float(np.mean(vs)) for vs in by.values()] for t, by in sums.items()}


def culture_means(values: list[dict[str, Any]], measure: str) -> dict[int, dict[str, float]]:
    """{batch id: {treatment: mean}} of one measure: a culture's mean per treatment."""
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
    "image means": "one mean per image; images are not independent cultures, so p runs low",
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


def tests_for(values: list[dict[str, Any]], measure: str, names: dict[int, str],
              units: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
    """Every test of one measure's treatments: {rows (the three ANOVA
    blocks, main first, then the others), dropped (the cultures left out of
    the paired tests: missing a treatment), brackets (the culture means'
    Tukey HSD p per pair, for the box plot)}. units: the ANOVA blocks to
    pick the main one from (every unit when empty); all three are worked
    out regardless, for the box plot's brackets."""
    means = culture_means(values, measure)
    treatments = sorted({t for by in means.values() for t in by}, key=str.casefold)
    k = len(treatments)
    if k < 2:
        return {"rows": [], "dropped": [], "brackets": {}}
    by_culture = {t: [by[t] for by in means.values() if t in by] for t in treatments}
    by_image = image_means(values, measure)
    by_value = {t: [v["value"] for v in values if v["measure"] == measure and v["treatment"] == t] for t in treatments}
    blocks_in = [("culture means", by_culture), ("image means", by_image), ("individual values", by_value)]
    candidates = [(d, g) for d, g in blocks_in if not units or d in units] or blocks_in
    main = next((d for d, g in candidates if all(len(g[t]) >= 2 for t in treatments)), candidates[-1][0])
    blocks = {d: _anova_block(measure, d, g, d == main) for d, g in blocks_in}
    anova_rows = blocks[main] + [r for d, _ in blocks_in if d != main for r in blocks[d]]
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

# Categorical series colours in a fixed order (light surface), for the
# cumulative distributions; each also gets its own dash, so a line is told
# apart without its colour.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
DASHES = ("", "6 3", "2 3", "8 3 2 3", "1 2", "10 4", "4 2 1 2", "12 3 3 3")
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
FONT = "font-family=\"Helvetica, Arial, sans-serif\""
BRACKET_STEP = 26   # px between stacked significance brackets


def _ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    """Round tick values covering lo..hi."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    step = 10 ** math.floor(math.log10(raw))
    step *= next(m for m in (1, 2, 2.5, 5, 10) if m * step >= raw)
    start = math.floor(lo / step) * step
    return [round(start + i * step, 10) for i in range(int(math.ceil((hi - start) / step)) + 1)]


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


def _wrap(text: str, width: float) -> list[str]:
    """Greedy word wrap of a label to lines no wider than width (a single
    longer word keeps a line of its own)."""
    lines: list[str] = []
    for word in text.split():
        if lines and _text_px(lines[-1] + " " + word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


def box_plot(measure_name: str, treatments: list[str], means: dict[int, dict[str, float]], names: dict[int, str],
             brackets: dict[tuple[str, str], float | None], cultures: int) -> str:
    """Culture means per treatment: a box (quartiles, whiskers to the
    extremes), a dot per culture and a thin line joining one culture's dots,
    with brackets over the pairs the culture means' Tukey HSD found to differ."""
    k = len(treatments)
    # Each treatment gets a slot wide enough for its longest word; names wrap
    # onto extra lines so neighbouring labels never overlap.
    words = [w for t in treatments for w in t.split()]
    slot = max(90, math.ceil(max((_text_px(w) for w in words), default=0) + 14))
    wrapped = {t: _wrap(t, slot - 10) for t in treatments}
    lines = max((len(v) for v in wrapped.values()), default=1)
    left, right, top, bottom = 64, 24, 48, 84 + 15 * (lines - 1)
    order = {t: i for i, t in enumerate(treatments)}
    # Shortest spans lowest, so brackets nest instead of crossing labels.
    significant = sorted(((a, b, p) for (a, b), p in brackets.items() if p is not None and p < 0.05),
                         key=lambda s: (abs(order[s[1]] - order[s[0]]), order[s[0]]))
    top += BRACKET_STEP * len(significant)
    width = max(left + right + slot * max(k, 2), 380)
    plot_h = 300
    height = top + plot_h + bottom
    every = [v for by in means.values() for v in by.values()]
    lo, hi = (min(every), max(every)) if every else (0.0, 1.0)
    ticks = _ticks(min(0.0, lo), hi)
    y0, y1 = ticks[0], ticks[-1]
    y = lambda v: top + plot_h - (v - y0) / (y1 - y0) * plot_h   # noqa: E731
    x = {t: left + slot * (i + 0.5) for i, t in enumerate(treatments)}
    body = [f'<text x="{left}" y="22" font-size="15" fill="{INK}" font-weight="bold">{escape(measure_name)}: culture means</text>']
    for t in ticks:
        body.append(f'<line x1="{left}" x2="{width - right}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end" fill="{MUTED}">{_fmt(t)}</text>')
    body.append(f'<text transform="translate(16 {top + plot_h / 2:.0f}) rotate(-90)" text-anchor="middle" fill="{MUTED}">µm</text>')
    for b, by in means.items():
        pts = [(x[t], y(by[t])) for t in treatments if t in by]
        if len(pts) > 1:
            body.append('<polyline fill="none" stroke="#b9b8b2" stroke-width="1" points="'
                        + " ".join(f"{px:.1f},{py:.1f}" for px, py in pts) + '"/>')
    for t in treatments:
        vs = np.array([by[t] for by in means.values() if t in by])
        cx = x[t]
        if vs.size:
            q1, med, q3 = np.percentile(vs, [25, 50, 75])
            body.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(vs.min()):.1f}" y2="{y(vs.max()):.1f}" stroke="{MUTED}" stroke-width="1.5"/>')
            body.append(f'<rect x="{cx - 22:.1f}" y="{y(q3):.1f}" width="44" height="{max(y(q1) - y(q3), 1):.1f}" '
                        f'fill="#eef3fb" stroke="{MUTED}" stroke-width="1.5" rx="2"/>')
            body.append(f'<line x1="{cx - 22:.1f}" x2="{cx + 22:.1f}" y1="{y(med):.1f}" y2="{y(med):.1f}" stroke="{INK}" stroke-width="2"/>')
            for b, by in means.items():
                if t in by:
                    body.append(f'<circle cx="{cx:.1f}" cy="{y(by[t]):.1f}" r="4" fill="{SERIES[0]}" stroke="{SURFACE}" '
                                f'stroke-width="1.5"><title>{escape(names[b])}: {by[t]:.3f} µm</title></circle>')
        label = "".join(f'<tspan x="{cx:.1f}" dy="{0 if i == 0 else 15}">{escape(line)}</tspan>'
                        for i, line in enumerate(wrapped[t]))
        body.append(f'<text x="{cx:.1f}" y="{top + plot_h + 18}" text-anchor="middle" fill="{INK}">{label}</text>')
        body.append(f'<text x="{cx:.1f}" y="{top + plot_h + 34 + 15 * (lines - 1)}" text-anchor="middle" fill="{MUTED}" font-size="11">'
                    f'n = {int(vs.size)}</text>')
    for i, (a, b, p) in enumerate(significant):
        by_ = top - 10 - BRACKET_STEP * i
        body.append(f'<path d="M{x[a]:.1f},{by_ + 6:.1f} V{by_:.1f} H{x[b]:.1f} V{by_ + 6:.1f}" fill="none" stroke="{INK}"/>')
        body.append(f'<text x="{(x[a] + x[b]) / 2:.1f}" y="{by_ - 3:.1f}" text-anchor="middle" fill="{INK}">{stars(p)}</text>')
    notes = (f"One-way ANOVA and Tukey HSD on the means of {cultures} culture{'s' if cultures != 1 else ''};",
             "brackets: Tukey-adjusted p &lt; 0.05." if significant else "no pair differs at p &lt; 0.05.")
    for i, note in enumerate(notes):
        body.append(f'<text x="{left}" y="{height - 26 + 14 * i}" fill="{MUTED}" font-size="11">{note}</text>')
    return _svg(width, height, body, f"{measure_name}: culture means")


def cdf_plot(measure_name: str, treatments: list[str], each: dict[str, list[float]]) -> str:
    """The cumulative distribution of every value per treatment: a step line
    each, in a fixed colour and dash, with a legend."""
    left, right, top, bottom = 64, 24, 48, 56
    plot_w, plot_h = 520, 300
    legend_h = 18 * len(treatments)
    width, height = left + plot_w + right, top + plot_h + bottom + legend_h
    every = [v for vs in each.values() for v in vs]
    lo, hi = (min(every), max(every)) if every else (0.0, 1.0)
    ticks = _ticks(min(0.0, lo), hi)
    x0, x1 = ticks[0], ticks[-1]
    x = lambda v: left + (v - x0) / (x1 - x0) * plot_w   # noqa: E731
    y = lambda f: top + plot_h - f * plot_h   # noqa: E731
    body = [f'<text x="{left}" y="22" font-size="15" fill="{INK}" font-weight="bold">{escape(measure_name)}: cumulative distribution</text>']
    for f in (0, 0.25, 0.5, 0.75, 1):
        body.append(f'<line x1="{left}" x2="{left + plot_w}" y1="{y(f):.1f}" y2="{y(f):.1f}" stroke="{GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y(f) + 4:.1f}" text-anchor="end" fill="{MUTED}">{_fmt(f)}</text>')
    for t in ticks:
        body.append(f'<text x="{x(t):.1f}" y="{top + plot_h + 18}" text-anchor="middle" fill="{MUTED}">{_fmt(t)}</text>')
    body.append(f'<text x="{left + plot_w / 2:.0f}" y="{top + plot_h + 38}" text-anchor="middle" fill="{MUTED}">µm</text>')
    body.append(f'<text transform="translate(16 {top + plot_h / 2:.0f}) rotate(-90)" text-anchor="middle" fill="{MUTED}">'
                'Cumulative fraction</text>')
    for i, t in enumerate(treatments):
        vs = sorted(each.get(t, []))
        if not vs:
            continue
        colour, dash = SERIES[i % len(SERIES)], DASHES[i % len(DASHES)]
        pts = [f"{x(vs[0]):.1f},{y(0):.1f}"]
        for j, v in enumerate(vs):
            pts.append(f"{x(v):.1f},{y(j / len(vs)):.1f}")
            pts.append(f"{x(v):.1f},{y((j + 1) / len(vs)):.1f}")
        dashed = f' stroke-dasharray="{dash}"' if dash else ""
        body.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2"{dashed} points="{" ".join(pts)}"/>')
        ly = top + plot_h + bottom + 18 * i
        body.append(f'<line x1="{left}" x2="{left + 28}" y1="{ly:.0f}" y2="{ly:.0f}" stroke="{colour}" stroke-width="2"{dashed}/>')
        body.append(f'<text x="{left + 36}" y="{ly + 4:.0f}" fill="{INK}">{escape(t)} (n = {len(vs)})</text>')
    return _svg(width, height, body, f"{measure_name}: cumulative distribution")


# --- all of it -------------------------------------------------------------------


TESTS = ("anova", "tukey", "welch", "dunnett", "paired", "unpaired", "ks")
BLOCK_TESTS = ("anova", "tukey", "welch", "dunnett")   # the ANOVA blocks' tests, run per unit
UNITS = ("culture means", "image means", "individual values")


def _choice(value: Any, known: tuple[str, ...], what: str) -> tuple[str, ...]:
    """A list of known keys (None: all of them), in known's order."""
    if value is None:
        return known
    if not isinstance(value, list) or not all(isinstance(v, str) and v in known for v in value):
        raise CompareError(f"{what} must be a list of: {', '.join(known)}")
    return tuple(k for k in known if k in value)


def _chosen(row: dict[str, Any], tests: tuple[str, ...], units: tuple[str, ...]) -> bool:
    if row["family"] not in tests:
        return False
    return row["family"] not in BLOCK_TESTS or row["design"] in units


def compare(store: Store, batch_ids: Any, labels: Any = None, tests: Any = None, units: Any = None) -> dict[str, Any]:
    """The batches' values grouped by treatment: {measures, treatments,
    images, values, groups, pooled, stats, dropped, plots}. With one batch
    the stats are the ANOVA blocks and the KS tests (the culture means'
    block saying it needs 2 cultures), with no plots; the box plot and the
    cumulative distributions need two batches or more. labels: {measure:
    name} for the plots' titles. tests (TESTS) and units (UNITS): which
    stats rows to keep, every one when None; units narrows the ANOVA
    blocks only (paired and unpaired are on culture means, KS on individual
    values). The plots do not depend on them."""
    if not isinstance(batch_ids, list) or not batch_ids or len(batch_ids) > 200 or \
            not all(isinstance(b, int) and not isinstance(b, bool) for b in batch_ids):
        raise CompareError("batch_ids must be a list of batch ids")
    tests = _choice(tests, TESTS, "tests")
    units = _choice(units, UNITS, "units")
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
        tested = tests_for(values, measure, batch_names, units)
        rows = [r for r in tested["rows"] if _chosen(r, tests, units)]
        if not several:
            # One culture: the paired and unpaired culture-mean tests have nothing to work on.
            out["stats"] += [r for r in rows if r["design"] not in ("paired", "unpaired")]
            continue
        out["stats"] += rows
        if "paired" in tests:
            out["dropped"] += [{"measure": measure, "batch": b} for b in tested["dropped"]]
        name = names.get(measure) if isinstance(names.get(measure), str) else None
        name = name or DEFAULT_LABELS.get(measure) or measure[len(TYPE_PREFIX):] or "(no type)"
        means = culture_means(values, measure)
        treatments = sorted({t for by in means.values() for t in by}, key=str.casefold)
        if not treatments:
            continue
        each = {t: [v["value"] for v in values if v["measure"] == measure and v["treatment"] == t] for t in treatments}
        out["plots"].append({"measure": measure, "kind": "box",
                             "svg": box_plot(name, treatments, means, batch_names, tested["brackets"], len(means))})
        out["plots"].append({"measure": measure, "kind": "cdf", "svg": cdf_plot(name, treatments, each)})
    return out
