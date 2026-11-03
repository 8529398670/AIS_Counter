"""Train auto mode "learned" (app/analysis/learned.py) on hand-clicked batches.

    .venv/bin/python scripts/train_learned.py extract [GT.json ...] [--out DIR]
    .venv/bin/python scripts/train_learned.py cv [--out DIR]
    .venv/bin/python scripts/train_learned.py fit [--out DIR]

Needs scikit-learn (pip install -r requirements-train.txt), which the app
does not.

extract: every candidate learned.candidates finds on every image of the
ground-truth files (default tests/autodata/c2.json and c4-c7.json, from
scripts/export_csv_ground_truth.py), with its features and how it lies on
the hand-clicked AIS and on the other candidates, one DIR/<batch>/<key>.npz
per image (default DIR .run/learned).

cv: leave one batch out. Model "ais" learns which candidates are good: on
a clicked AIS and within GOOD_UM of its length, what a person's click
gives. The component pre-filter (model "component", on
learned.COMPONENT_FEATURES: has this blob a good candidate?) drops the
candidates of the components it scores under --component-keep, as
learned.candidates does before clicking them. Each batch is found by models
trained on the others, picked as learned.detect picks, and scored as scripts/auto_eval.py
scores (one to one, more than half a candidate's pixels within 3 px of a
clicked trace): precision, recall, F1 and the length error, per batch and
pooled, over a range of lowest scores. The lowest score with the best pooled F1 is
reported as the default.

--plain scores the models without the soma features (learned.SOMA_FEATURES),
which a TIFF pair gets.

fit: the models on every batch, written to app/analysis/learned_model.json,
both with the soma features and without (plain),
with the lowest score cv chose (--min-score, else cv's).
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy import sparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import auto_eval as ae  # noqa: E402
from app.analysis import ais_auto as aa  # noqa: E402
from app.analysis import learned  # noqa: E402
from app.analysis import preprocess  # noqa: E402
from app.analysis import soma as somata  # noqa: E402

DEFAULT_GT = [ROOT / "tests" / "autodata" / f"c{i}.json" for i in (2, 4, 5, 6, 7)]
DEFAULT_OUT = ROOT / ".run" / "learned"
CHECK = ROOT / "tests" / "autodata" / "learned_check.json"   # rows and what scikit-learn made of them
GOOD_UM = 2.0            # a candidate within this of the clicked length measures it as a person did
SCORES = np.round(np.arange(0.05, 0.96, 0.05), 2)
PARAMS = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 40,
          "l2_regularization": 1.0, "random_state": 0}


# --- extract -----------------------------------------------------------------------


def human_fractions(pixels: list[list[list[int]]], image: dict[str, Any]) -> sparse.coo_matrix:
    """[i, j]: the fraction of pixels[i] on clicked AIS j as
    scripts/auto_eval.py judges it (ae.on of ae.near_masks), where above zero."""
    masks = ae.near_masks(image)
    dense = np.array([[ae.on(m, p) for m in masks] for p in pixels]).reshape(len(pixels), len(masks))
    return sparse.coo_matrix(dense)


def _extract_one(job: tuple[dict[str, Any], Path]) -> str:
    image, path = job
    if path.exists():
        return f"{path.stem} (kept)"
    t = time.time()
    raw = image["raw"]
    prep = aa.PreparedImage.from_array(preprocess.processed(raw))
    soma = somata.find(image["amca"], image["pixel_um"])
    cands, counts = learned.candidates(prep, raw, 0.01, aa.DEFAULT, soma)
    seconds = time.time() - t
    shape = raw.shape[:2]
    pix = [c["pixels"] for c in cands]
    truth = [a["pixels"] for a in image["ais"]]
    # learned.pick's overlaps (both ways are read from it), and how each
    # candidate lies on the clicked AIS.
    pair = learned.on_fractions(pix, pix, shape, learned.REACH).tocoo() if cands else sparse.coo_matrix((0, 0))
    hum = human_fractions(pix, image) if cands and truth else sparse.coo_matrix((len(cands), len(truth)))
    np.savez_compressed(
        path,
        X=learned.feature_matrix(cands).astype(np.float32),
        length=np.array([c["measures"]["length_um"] for c in cands], np.float32),
        component=np.array([c["blob"] for c in cands], np.int16),
        seed=np.array([c["seed"] for c in cands], np.int16).reshape(len(cands), 2),
        pair_i=pair.row.astype(np.int32), pair_j=pair.col.astype(np.int32), pair_f=pair.data.astype(np.float32),
        hum_i=hum.row.astype(np.int32), hum_j=hum.col.astype(np.int32), hum_f=hum.data.astype(np.float32),
        truth_length=np.array([a["length_um"] for a in image["ais"]], np.float32),
        counts=np.array([counts["components"], counts["blobs"], counts["seeds"], counts["failed"]]),
        seconds=seconds,
    )
    return f"{path.stem}: {len(cands)} candidates from {counts['seeds']} seeds, {seconds:.0f} s"


def extract(gt_paths: list[Path], out: Path, jobs: int) -> None:
    for gt in gt_paths:
        folder = out / gt.stem
        folder.mkdir(parents=True, exist_ok=True)
        images = ae.load(gt)
        with multiprocessing.Pool(jobs) as pool:
            for line in pool.imap_unordered(_extract_one, [(im, folder / f"{im['key']}.npz") for im in images]):
                print(gt.stem, line, flush=True)
        (folder / "features.json").write_text(json.dumps(list(learned.FEATURES)))


# --- the cache ----------------------------------------------------------------------


class Image:
    """One image's extracted candidates."""

    def __init__(self, path: Path):
        z = np.load(path)
        self.key = path.stem
        self.X = z["X"].astype(np.float64)
        self.length = z["length"].astype(np.float64)
        self.truth_length = z["truth_length"].astype(np.float64)
        self.seconds = float(z["seconds"])
        self.comp = z["component"].astype(np.int64)
        n, t = len(self.X), len(self.truth_length)
        self.pair = sparse.coo_matrix((z["pair_f"], (z["pair_i"], z["pair_j"])), shape=(n, n)).tocsr()
        self.hum = sparse.coo_matrix((z["hum_f"], (z["hum_i"], z["hum_j"])), shape=(n, t)).toarray()
        # Each candidate's clicked AIS (the one most of it lies on), or -1,
        # and how far its length is from that one's.
        self.gt, self.err = np.full(n, -1), np.full(n, np.nan)
        if n and t:
            best = self.hum.argmax(axis=1)
            on = self.hum.max(axis=1) > ae.OVERLAP
            self.gt = np.where(on, best, -1)
            self.err = np.where(on, np.abs(self.length - self.truth_length[best]), np.nan)


def load_cache(out: Path) -> dict[str, list[Image]]:
    return {d.name: [Image(p) for p in sorted(d.glob("*.npz"))] for d in sorted(out.iterdir()) if d.is_dir()}


# --- models and picking ---------------------------------------------------------------


def good(im: Image) -> np.ndarray:
    """Per candidate: what a person's click gives (on a clicked AIS and
    within GOOD_UM of its length), which model "ais" learns."""
    return (im.gt >= 0) & (np.nan_to_num(im.err, nan=np.inf) <= GOOD_UM)


def features(plain: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The candidate and component features: all of them, or (plain, for a
    TIFF pair) those without the somata."""
    drop = set(learned.SOMA_FEATURES) if plain else set()
    return (tuple(f for f in learned.FEATURES if f not in drop),
            tuple(f for f in learned.COMPONENT_FEATURES if f not in drop))


def columns(names: tuple[str, ...]) -> list[int]:
    return [learned.FEATURES.index(f) for f in names]


def component_rows(im: Image, names: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per component with a candidate: its index, its features names and
    whether any of its candidates is good."""
    comps, first = np.unique(im.comp, return_index=True)
    g = good(im)
    has = np.array([bool(np.any(g[im.comp == c])) for c in comps], bool)
    return comps, im.X[np.ix_(first, columns(names))], has


def fit_models(images: list[Image], plain: bool = False) -> dict[str, Any]:
    """Models "ais" and "component" (plain: without the soma features), each
    with .names, the features it takes."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    names, comp_names = features(plain)
    X = np.vstack([im.X for im in images])[:, columns(names)]
    ais = HistGradientBoostingClassifier(**PARAMS).fit(X, np.concatenate([good(im) for im in images]))
    rows = [component_rows(im, comp_names) for im in images if len(im.X)]
    component = HistGradientBoostingClassifier(**(PARAMS | {"min_samples_leaf": 20})).fit(
        np.vstack([r[1] for r in rows]), np.concatenate([r[2] for r in rows]))
    ais.names, component.names = names, comp_names
    return {"ais": ais, "component": component}


def predict(model: Any, X: np.ndarray) -> np.ndarray:
    """model's probability for the rows of X (every feature, in learned.FEATURES order)."""
    return model.predict_proba(X[:, columns(model.names)])[:, 1] if len(X) else np.zeros(0)


def component_kept(im: Image, model: Any, cut: float) -> np.ndarray:
    """Per candidate: whether learned.candidates seeds its component at all."""
    if not len(im.X):
        return np.zeros(0, bool)
    comps, Xc, _ = component_rows(im, model.names)
    keep = set(comps[model.predict_proba(Xc)[:, 1] >= cut].tolist())
    return np.array([c in keep for c in im.comp], bool)


def pick(im: Image, score: np.ndarray, keep: float) -> list[int]:
    """learned.pick on the cached overlaps."""
    return learned.suppress(im.pair, score, keep)


def score_picks(images: list[Image], picks: list[list[int]], scores: list[np.ndarray],
                min_score: float) -> dict[str, float]:
    """scripts/auto_eval.py's scoring (auto_eval.match, one to one by
    overlap) of what is shown from min_score."""
    tp = found = truth = 0
    errors: list[float] = []
    for im, chosen, s in zip(images, picks, scores):
        shown = [i for i in chosen if s[i] >= min_score]
        pairs = sorted(((im.hum[b, j], k, j) for k, b in enumerate(shown) for j in range(len(im.truth_length))),
                       reverse=True)
        used_k, used_j = set(), set()
        for frac, k, j in pairs:
            if frac <= ae.OVERLAP:
                break
            if k not in used_k and j not in used_j:
                used_k.add(k)
                used_j.add(j)
                errors.append(im.length[shown[k]] - im.truth_length[j])
        tp += len(used_k)
        found += len(shown)
        truth += len(im.truth_length)
    return ae.summary(tp, found, truth, errors)


def cv(out: Path, keep: float, cuts: list[float], plain: bool = False) -> dict[str, Any]:
    """Leave one batch out, for each component pre-filter cut: per lowest
    score, per batch and pooled; the best lowest score; the share of
    candidates the pre-filter keeps (what the clicking costs) and the
    clicked AIS a good candidate is left for."""
    cache = load_cache(out)
    batches = list(cache)
    held: dict[str, Any] = {}
    for b in batches:
        train = [im for o in batches if o != b for im in cache[o]]
        held[b] = (cache[b], fit_models(train, plain))
        print(f"{b}: trained on {len(train)} images", flush=True)
    result: dict[str, Any] = {"cuts": {}, "keep": keep, "plain": plain,
                              "seconds_per_image": float(np.mean([im.seconds for b in batches for im in cache[b]]))}
    for cut in cuts:
        runs, kept_frac, reach = {}, {}, {}
        for b, (test, models) in held.items():
            scores = [predict(models["ais"], im.X) for im in test]
            # Candidates on components the pre-filter drops are never found.
            kept = [component_kept(im, models["component"], cut) for im in test]
            scores = [np.where(k, s, -1.0) for s, k in zip(scores, kept)]
            runs[b] = (test, [pick(im, s, keep) for im, s in zip(test, scores)], scores)
            kept_frac[b] = float(np.concatenate(kept).mean())
            reach[b] = (sum(len(set(im.gt[k & good(im)])) for im, k in zip(test, kept)),
                        sum(len(set(im.gt[good(im)])) for im in test), sum(len(im.truth_length) for im in test))
        table = {}
        for t in SCORES:
            per = {b: score_picks(*runs[b], float(t)) for b in batches}
            pooled = score_picks([im for b in batches for im in runs[b][0]], [p for b in batches for p in runs[b][1]],
                                 [s for b in batches for s in runs[b][2]], float(t))
            table[float(t)] = {"batches": per, "pooled": pooled}
        best = max(table, key=lambda t: table[t]["pooled"]["f1"])
        result["cuts"][float(cut)] = {"table": table, "best": best, "candidates_kept": kept_frac, "reachable": reach}
    return result


def print_cv(result: dict[str, Any]) -> None:
    head = f"{'score':>6} {'batch':<7}{'truth':>6}{'found':>6}{'tp':>6}{'prec':>7}{'rec':>6}{'f1':>6}{'MAE':>7}{'bias':>7}{'<=2um':>7}"
    for cut, r in result["cuts"].items():
        print(f"\ncomponent pre-filter {cut}: keeps "
              + ", ".join(f"{b} {f:.0%}" for b, f in r["candidates_kept"].items()) + " of candidates; clicked AIS "
              + "with a good candidate left: "
              + ", ".join(f"{b} {k}/{a} (of {t})" for b, (k, a, t) in r["reachable"].items()))
        print(head)
        for t, row in r["table"].items():
            for name, s in list(row["batches"].items()) + [("pooled", row["pooled"])]:
                if name != "pooled" and t != r["best"]:
                    continue
                print(f"{t:>6.2f} {name:<7}{s['truth']:>6}{s['found']:>6}{s['tp']:>6}{s['precision']:>7.2f}"
                      f"{s['recall']:>6.2f}{s['f1']:>6.2f}{s['len_mae']:>7.2f}{s['len_bias']:>7.2f}{s['len_within_2um']:>7.2f}")
        print(f"best lowest score {r['best']:.2f}")
    print(f"{result['seconds_per_image']:.1f} s per image to find the candidates of every component (extract)")


# --- export ----------------------------------------------------------------------------


def export_forest(model: Any, kind: str = "classifier") -> dict[str, Any]:
    """A HistGradientBoosting model's trees as learned.Forest reads them."""
    trees = []
    for per_iter in model._predictors:
        nodes = per_iter[0].nodes
        trees.append({
            "feature": nodes["feature_idx"].astype(int).tolist(),
            "threshold": [float(v) for v in nodes["num_threshold"]],
            "missing_left": nodes["missing_go_to_left"].astype(bool).tolist(),
            "left": nodes["left"].astype(int).tolist(),
            "right": nodes["right"].astype(int).tolist(),
            "leaf": nodes["is_leaf"].astype(bool).tolist(),
            "value": [float(v) for v in nodes["value"]],
        })
    baseline = float(np.ravel(model._baseline_prediction)[0])
    return {"kind": kind, "features": list(model.names), "baseline": baseline, "trees": trees}


def fit(out: Path, min_score: float, keep: float, cut: float, cv_result: dict[str, Any] | None) -> None:
    """Both pairs of models on every image: with somata and plain."""
    cache = load_cache(out)
    images = [im for b in cache for im in cache[b]]
    models = fit_models(images)
    plain = fit_models(images, plain=True)
    meta = {"min_score": min_score, "keep": keep, "component_keep": cut, "good_um": GOOD_UM,
            "batches": list(cache), "images": len(images), "clicked": int(sum(len(im.truth_length) for im in images)),
            "params": PARAMS}
    if cv_result:
        r = cv_result["cuts"][cut]
        meta["cv"] = {"min_score": r["best"], "pooled": r["table"][r["best"]]["pooled"],
                      "batches": r["table"][r["best"]]["batches"]}
    trained = {"ais": models["ais"], "component": models["component"],
               "ais_plain": plain["ais"], "component_plain": plain["component"]}
    spec = {k: export_forest(m) for k, m in trained.items()} | {"meta": meta}
    learned.MODEL_PATH.write_text(json.dumps(spec, separators=(",", ":")))
    # The numpy trees must give what scikit-learn gives, on rows with every
    # feature (learned.FEATURES order) ...
    X = np.vstack([im.X for im in images[:20]])
    rows = np.linspace(0, len(X) - 1, 40).astype(int)
    check: dict[str, Any] = {"X": X[rows].tolist()}
    for k, m in trained.items():
        theirs = predict(m, X)
        assert np.allclose(learned.Forest(spec[k]).predict(X[:, columns(m.names)]), theirs, atol=1e-6), k
        check[k] = theirs[rows].tolist()
    # ... and tests/test_learned.py checks the shipped file still does.
    CHECK.write_text(json.dumps(check))
    print(f"{len(images)} images -> {learned.MODEL_PATH} ({learned.MODEL_PATH.stat().st_size // 1024} KB),"
          f" lowest score {min_score}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("extract", "cv", "fit"))
    ap.add_argument("gt", nargs="*", default=[str(p) for p in DEFAULT_GT])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--keep", type=float, default=learned.KEEP_SCORE)
    ap.add_argument("--component-keep", default=str(learned.COMPONENT_KEEP),
                    help="components the pre-filter scores lower are not seeded; cv: a comma list to compare")
    ap.add_argument("--min-score", type=float, help="fit: the default lowest score, instead of cv's")
    ap.add_argument("--json", metavar="FILE", help="cv: also write the result here")
    ap.add_argument("--plain", action="store_true", help="cv: the models without the soma features (a TIFF pair)")
    args = ap.parse_args()
    out = Path(args.out)
    cuts = [float(c) for c in args.component_keep.split(",")]
    if args.command == "extract":
        extract([Path(p) for p in args.gt], out, args.jobs)
    elif args.command == "cv":
        result = cv(out, args.keep, cuts, args.plain)
        print_cv(result)
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=1))
    else:
        result = None
        if args.min_score is None:
            result = cv(out, args.keep, cuts[:1])
            print_cv(result)
        fit(out, args.min_score if args.min_score is not None else result["cuts"][cuts[0]]["best"], args.keep,
            cuts[0], result)


if __name__ == "__main__":
    main()
