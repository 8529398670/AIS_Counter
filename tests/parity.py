"""Compare the Python port against MATLAB golden runs, stage by stage.

A golden set is tests/golden/<name>.json (jobs from make_jobs.py) plus
tests/golden/<name>/ (run_golden.m output). For each job this reports the
first stage at which Python and MATLAB disagree, or "ok".

    python -m tests.parity [name ...]       # summary over golden sets
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import scipy.io as sio
import tifffile

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(ROOT))

from app.analysis import ais_auto as aa  # noqa: E402
from app.analysis.mlcompat import MatlabError  # noqa: E402

SUFFIX = ".tif - Processed method 2.5.tif"


@lru_cache(maxsize=4)
def prepared(base: str) -> aa.PreparedImage:
    return aa.PreparedImage.from_array(tifffile.imread(base + SUFFIX))


@lru_cache(maxsize=4)
def raw_image(base: str) -> np.ndarray:
    return tifffile.imread(base + ".tif")


def golden_sets() -> list[str]:
    return sorted(p.stem for p in GOLDEN.glob("*.json") if (GOLDEN / p.stem).is_dir())


def load_jobs(name: str) -> list[dict]:
    out = []
    for job in json.loads((GOLDEN / f"{name}.json").read_text()):
        res = GOLDEN / name / f"{job['id']}.json"
        if res.exists():
            job["result"] = json.loads(res.read_text())
            job["dir"] = GOLDEN / name
            out.append(job)
    return out


def _vec(a) -> np.ndarray:
    return np.atleast_1d(np.asarray(a, dtype=np.float64).squeeze())


def _cells(a) -> list[np.ndarray]:
    a = np.atleast_1d(a.squeeze())
    return [_vec(x) for x in a.ravel()]


def compare(job: dict) -> tuple[str, str]:
    """(stage, detail); stage "ok" when everything matches."""
    base, res, d = job["base"], job["result"], job["dir"]
    clicks = [tuple(c) for c in np.atleast_2d(job["clicks"])]
    prep = prepared(base)
    tr_file = d / f"{job['id']}_trace.mat"
    fin_file = d / f"{job['id']}_final.mat"

    try:
        tr = aa.trace(prep, clicks[0], clicks[1] if len(clicks) > 1 else None)
    except MatlabError as e:
        if not res["ok"] and not tr_file.exists():
            return "ok", f"both error before the trace: {res['error_msg']} | {e}"
        return "trace-error", f"python: {e}; matlab ok={res['ok']} {res['error_msg']}"

    if not tr_file.exists():
        return "trace-missing", f"matlab errored before the trace: {res['error_msg']} (line {res.get('error_line')})"
    m = sio.loadmat(str(tr_file))

    th = _vec(m["dbg_th"])
    py_th = [tr.threshold_initial] + ([tr.threshold] if tr.rethresholded else [])
    if len(th) != len(py_th) or not np.array_equal(th, py_th):
        return "threshold", f"matlab {th.tolist()} python {py_th}"
    sels = np.atleast_1d(m["dbg_sel"].squeeze())
    if not np.array_equal(sels[-1].astype(bool), tr.selected):
        return "select", f"{int(sels[-1].sum())} vs {int(tr.selected.sum())} px"
    if not np.array_equal(m["ais_skeleton"].astype(bool), tr.skeleton):
        return "skeleton", f"{int(m['ais_skeleton'].sum())} vs {int(tr.skeleton.sum())} px"
    if (int(m["I_skel"][0, 0]), int(m["J_skel"][0, 0])) != tr.start:
        return "start", f"matlab {(int(m['I_skel'][0, 0]), int(m['J_skel'][0, 0]))} python {tr.start}"
    XL, YL = _cells(m["XaisL"]), _cells(m["YaisL"])
    if len(XL) != len(tr.passes):
        return "passes", f"matlab {len(XL)} passes, python {len(tr.passes)}"
    for k, (xs, ys, p) in enumerate(zip(XL, YL, tr.passes)):
        if not (np.array_equal(xs, [r for r, _ in p]) and np.array_equal(ys, [c for _, c in p])):
            return "pass-path", f"pass {k + 1}: lengths {len(xs)} vs {len(p)}"
    if not (np.array_equal(_vec(m["Xais"]), [r for r, _ in tr.path])
            and np.array_equal(_vec(m["Yais"]), [c for _, c in tr.path])):
        return "path", "chosen path differs"

    try:
        ms = aa.measure(tr.path, raw_image(base))
    except MatlabError as e:
        if not res["ok"]:
            return "ok", f"both error in the profile: {res['error_msg']} | {e}"
        return "measure-error", f"python: {e}"
    if not res["ok"]:
        return "measure-noerror", f"matlab errored: {res['error_msg']} (line {res.get('error_line')})"
    f = sio.loadmat(str(fin_file))
    xysm = f["xysm"]
    if xysm.shape != ms.xysm.shape or np.abs(xysm - ms.xysm).max() > 1e-9:
        return "spline", f"max diff {np.abs(xysm - ms.xysm).max() if xysm.shape == ms.xysm.shape else xysm.shape}"
    if not (np.array_equal(_vec(f["x_pix"]), ms.x_pix) and np.array_equal(_vec(f["y_pix"]), ms.y_pix)):
        return "pixels", f"{_vec(f['x_pix']).size} vs {ms.x_pix.size} unique pixels"
    if not np.array_equal(_vec(f["lv_smooth"]), ms.lv_smooth):
        return "lv_smooth", f"max diff {np.abs(_vec(f['lv_smooth']) - ms.lv_smooth).max()}"
    if np.abs(_vec(f["norm_lv"]) - ms.norm_lv).max() > 1e-9:
        return "norm_lv", f"max diff {np.abs(_vec(f['norm_lv']) - ms.norm_lv).max()}"
    for name in ("max_i", "ais_start", "ais_end"):
        if float(f[name][0, 0]) != getattr(ms, name):
            return name, f"matlab {float(f[name][0, 0])} python {getattr(ms, name)}"
    if str(f["lngth_str"][0]) != ms.lngth_str:
        return "lngth", f"matlab {f['lngth_str'][0]} python {ms.lngth_str}"
    exact = "bit-exact" if float(f["lngth"][0, 0]) == ms.lngth else f"diff {float(f['lngth'][0, 0]) - ms.lngth}"
    bits = "lv_ss bit-exact" if np.array_equal(_vec(f["lv_ss"]), ms.lv_ss) else "lv_ss ulp-diff"
    return "ok", f"lngth {ms.lngth_str} ({exact}, {bits})"


def main(names: list[str]) -> int:
    from collections import Counter
    total = Counter()
    bad = []
    for name in names or golden_sets():
        for job in load_jobs(name):
            stage, detail = compare(job)
            total[stage] += 1
            if stage != "ok":
                bad.append((job["id"], stage, detail))
    for row in bad:
        print("MISMATCH", *row)
    print(dict(total))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
