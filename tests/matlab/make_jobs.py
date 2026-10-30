"""Generate click jobs for run_golden.m from the local example-data pairs.

Clicks only need to land in interesting places (on components, just off their
edges, on background, near borders, two different clicks), so an approximate
scipy segmentation is enough to aim them; MATLAB decides what they hit.

    python tests/matlab/make_jobs.py OUT.json [--images N] [--per-image K] [--seed S]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import tifffile
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parents[2]
DATA = [ROOT / "example-data" / "005-both-tiff", ROOT / "example-data" / "006-both-tiff"]
SUFFIX = ".tif - Processed method 2.5.tif"


def pairs() -> list[Path]:
    """Bases (path without the .tif) that have both the raw and processed tif."""
    out = []
    for d in DATA:
        for p in sorted(d.glob("*" + SUFFIX)):
            base = Path(str(p)[: -len(SUFFIX)])
            if base.with_name(base.name + ".tif").exists():
                out.append(base)
    return out


def components(img: np.ndarray) -> list[np.ndarray]:
    a = img.astype(float)
    a = (a - a.min()) / (a.max() - a.min())
    ax = np.arange(20) - 9.5
    g = np.exp(-(ax[:, None] ** 2 + ax[None, :] ** 2) / 8)
    g /= g.sum()
    s = ndi.correlate(a, g, mode="constant")
    bw = s > 0.01
    sq = np.ones((3, 3), bool)
    bw = ndi.binary_closing(ndi.binary_opening(bw, sq), sq)
    lab, n = ndi.label(bw, np.ones((3, 3)))
    return [np.argwhere(lab == i) for i in range(1, n + 1) if (lab == i).sum() >= 70]


KINDS = ["on", "near", "near", "far", "two", "border"]


def jobs_for(base: Path, k: int, rng: np.random.Generator) -> list[dict]:
    img = tifffile.imread(str(base) + SUFFIX)
    h, w = img.shape
    comps = components(img)
    if not comps:
        return []
    out = []

    def add(kind: str, *clicks: tuple[float, float]) -> None:
        # MATLAB axes coords: x = column, y = row, pixel centres at 1..n.
        out.append({"id": f"{base.name[:24]}_{len(out):03d}_{kind}", "base": str(base),
                    "clicks": [[float(x), float(y)] for x, y in clicks]})

    def jitter() -> float:
        return float(rng.uniform(-0.49, 0.49))

    for _ in range(k):
        kind = rng.choice(KINDS)
        # "ais" clicks aim just off a large component, as a user would
        # (the original asks for a click just outside the start of the AIS).
        pool = [c for c in comps if len(c) >= 300] if kind == "ais" else comps
        c = (pool or comps)[rng.integers(len(pool or comps))]
        r, cc = c[rng.integers(len(c))]
        if kind == "ais":
            dr, dc = rng.integers(-4, 5, size=2)
            add("ais", (np.clip(cc + 1 + dc, 2, w - 1) + jitter(), np.clip(r + 1 + dr, 2, h - 1) + jitter()))
        elif kind == "on":
            add("on", (cc + 1 + jitter(), r + 1 + jitter()))
        elif kind == "near":
            dr, dc = rng.integers(-10, 11, size=2)
            add("near", (np.clip(cc + 1 + dc, 2, w - 1) + jitter(), np.clip(r + 1 + dr, 2, h - 1) + jitter()))
        elif kind == "far":
            add("far", (rng.integers(2, w) + jitter(), rng.integers(2, h) + jitter()))
        elif kind == "two":
            dr, dc = rng.integers(-4, 5, size=2)
            add("two", (cc + 1, r + 1), (np.clip(cc + 1 + dc, 2, w - 1), np.clip(r + 1 + dr, 2, h - 1)))
        else:
            edge = rng.integers(4)
            x, y = rng.integers(1, w + 1), rng.integers(1, h + 1)
            x, y = [(x, 1 + rng.integers(3)), (x, h - rng.integers(3)), (1 + rng.integers(3), y), (w - rng.integers(3), y)][edge]
            add("border", (float(x), float(y)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--images", type=int, default=10)
    ap.add_argument("--per-image", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--kinds", default="", help="comma list to draw click kinds from, e.g. ais,ais,two")
    a = ap.parse_args()
    if a.kinds:
        KINDS[:] = a.kinds.split(",")
    rng = np.random.default_rng(a.seed)
    bases = pairs()
    pick = sorted(rng.choice(len(bases), size=min(a.images, len(bases)), replace=False))
    jobs = [j for i in pick for j in jobs_for(bases[i], a.per_image, rng)]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(jobs, indent=1))
    print(f"{len(jobs)} jobs from {len(pick)} of {len(bases)} image pairs -> {a.out}")


if __name__ == "__main__":
    main()
