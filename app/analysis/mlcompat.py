"""MATLAB primitives used by ais_auto.m, reproduced to match MATLAB R2026b.

Each function copies the exact semantics the original relies on, including
border padding, strict-vs-inclusive comparisons, tie-breaking and the order of
floating-point operations where that order decides a result. Where MATLAB runs
compiled code we cannot read (imfilter, bwdist, mldivide), the behaviour was
pinned down empirically against MATLAB dumps (tests/matlab/probe_primitives.m,
checked by tests/test_mlcompat.py).

Arrays are numpy, 0-based, row-major in memory. "Linear index" below always
means MATLAB's column-major order, since that is what decides ties.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import linalg
from scipy import ndimage as ndi

from app.analysis._gauss20 import GAUSS20_SIGMA2

EPS = np.finfo(np.float64).eps


class MatlabError(Exception):
    """The original MATLAB code would have stopped with an error here."""


# --- intensity -------------------------------------------------------------

def mat2gray(a: np.ndarray) -> np.ndarray:
    """mat2gray(A): imlincomb(1/(max-min), A, -min/(max-min)), clipped to [0, 1].

    The A*delta + offset order (not (A-min)/range) is what MATLAB computes,
    and the two differ in the last bit for about half the pixels.
    """
    lo, hi = float(a.min()), float(a.max())
    if hi == lo:
        return a.astype(np.float64)
    delta = 1.0 / (hi - lo)
    out = a.astype(np.float64) * delta + (-lo * delta)
    return np.maximum(0.0, np.minimum(out, 1.0))


def im2double(a: np.ndarray) -> np.ndarray:
    if a.dtype == np.uint16:
        return a.astype(np.float64) / 65535.0
    if a.dtype == np.uint8:
        return a.astype(np.float64) / 255.0
    return a.astype(np.float64)


def fspecial_gaussian(size: tuple[int, int], sigma: float) -> np.ndarray:
    """fspecial('gaussian', size, sigma). The [20 20], 2 kernel the original
    uses is returned as MATLAB's bit-exact constant."""
    if tuple(size) == (20, 20) and sigma == 2:
        return GAUSS20_SIGMA2.copy()
    sr, sc = (size[0] - 1) / 2, (size[1] - 1) / 2
    x, y = np.meshgrid(np.arange(-sc, sc + 1), np.arange(-sr, sr + 1))
    h = np.exp(-(x * x + y * y) / (2 * sigma * sigma))
    h[h < EPS * h.max()] = 0
    s = h.sum()
    return h / s if s != 0 else h


def fspecial_log(size: tuple[int, int], sigma: float) -> np.ndarray:
    """fspecial('log', size, sigma): the normalised Gaussian times the
    Laplacian factor, then shifted to sum to zero (fspecial.m, case 'log')."""
    sr, sc = (size[0] - 1) / 2, (size[1] - 1) / 2
    std2 = sigma ** 2
    x, y = np.meshgrid(np.arange(-sc, sc + 1), np.arange(-sr, sr + 1))
    h = np.exp(-(x * x + y * y) / (2 * std2))
    h[h < EPS * h.max()] = 0
    s = h.sum()
    if s != 0:
        h = h / s
    h1 = h * (x * x + y * y - 2 * std2) / (std2 ** 2)
    return h1 - h1.sum() / (size[0] * size[1])


# The smoothing types fspecial accepts with the original's (type, [k k], sigma)
# call; every other type errors in MATLAB ("Too many arguments").
FSPECIAL = {"gaussian": fspecial_gaussian, "log": fspecial_log}


def imfilter_zero_same(a: np.ndarray, h: np.ndarray) -> np.ndarray:
    """imfilter(A, h) with the defaults: correlation, zero padding, 'same'.

    The kernel centre is floor((size+1)/2) (1-based), so an even 20-tap kernel
    reaches 9 pixels back and 10 forward. Rank-1 kernels are applied as two
    1-D passes from the SVD factors, as MATLAB does. MATLAB's own summation
    order is not reproducible bit for bit (results differ by ~1e-15), which
    leaves every thresholded mask identical.
    """
    kh, kw = h.shape
    cr, cc = (kh + 1) // 2 - 1, (kw + 1) // 2 - 1
    H, W = a.shape
    pad = np.zeros((H + kh - 1, W + kw - 1))
    pad[cr:cr + H, cc:cc + W] = a
    u, s, vt = np.linalg.svd(h)
    if np.sum(s > max(h.shape) * s.max() * EPS) == 1:
        hcol, hrow = u[:, 0] * math.sqrt(s[0]), vt[0] * math.sqrt(s[0])
        tmp = np.zeros((H, W + kw - 1))
        for i in range(kh):
            tmp += hcol[i] * pad[i:i + H, :]
        out = np.zeros((H, W))
        for j in range(kw):
            out += hrow[j] * tmp[:, j:j + W]
        return out
    out = np.zeros((H, W))
    for j in range(kw):
        for i in range(kh):
            out += h[i, j] * pad[i:i + H, j:j + W]
    return out


def graythresh(img: np.ndarray) -> float:
    """graythresh(I) for a double image: Otsu on im2uint8's 256-bin histogram."""
    u8 = round_half_away(np.clip(img, 0, 1) * 255).astype(np.int64)
    counts = np.bincount(u8.ravel(), minlength=256).astype(np.float64)
    p = counts / counts.sum()
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(1, 257))
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b2 = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    finite = sigma_b2[np.isfinite(sigma_b2)]
    if finite.size == 0:
        return 0.0
    maxval = finite.max()
    idx = np.mean(np.flatnonzero(sigma_b2 == maxval) + 1)
    return float((idx - 1) / 255)


def im2bw(img: np.ndarray, level: float) -> np.ndarray:
    """im2bw on a double image is a strict comparison: I > level."""
    if not 0 <= level <= 1:
        raise MatlabError("images:im2bw:outOfRangeThreshLuminanceLevel")
    return img > level


# --- binary morphology -----------------------------------------------------

def _offsets(k: int) -> np.ndarray:
    """strel('square',k) offsets about its centre, floor((k+1)/2) (1-based)."""
    return np.arange(k) - ((k + 1) // 2 - 1)


def _shifted(bw: np.ndarray, offsets: np.ndarray, border: bool) -> list[np.ndarray]:
    """bw(p + (dr, dc)) for every pair of offsets, outside read as border."""
    m = int(np.abs(offsets).max()) if offsets.size else 0
    p = np.pad(bw, m, constant_values=border)
    H, W = bw.shape
    return [p[m + dr:m + dr + H, m + dc:m + dc + W] for dr in offsets for dc in offsets]


def imerode_square(bw: np.ndarray, k: int = 3) -> np.ndarray:
    """Binary erosion pads with true, so the image border does not erode."""
    return np.logical_and.reduce(_shifted(bw, _offsets(k), True))


def imdilate_square(bw: np.ndarray, k: int = 3) -> np.ndarray:
    """Dilation uses the reflected element, which matters for even k."""
    return np.logical_or.reduce(_shifted(bw, -_offsets(k), False))


def imopen_square(bw: np.ndarray, k: int = 3) -> np.ndarray:
    return imdilate_square(imerode_square(bw, k), k)


def imclose_square(bw: np.ndarray, k: int = 3) -> np.ndarray:
    """imclose zero-pads by ceil(k/2) first (imopen does not), so closing
    can open up along the image border."""
    m = (k + 1) // 2
    p = np.pad(bw, m)
    return imerode_square(imdilate_square(p, k), k)[m:-m, m:-m]


def imerode_square3(bw: np.ndarray) -> np.ndarray:
    return imerode_square(bw, 3)


def imdilate_square3(bw: np.ndarray) -> np.ndarray:
    return imdilate_square(bw, 3)


def imopen_square3(bw: np.ndarray) -> np.ndarray:
    return imopen_square(bw, 3)


def imclose_square3(bw: np.ndarray) -> np.ndarray:
    return imclose_square(bw, 3)


def components8(bw: np.ndarray, min_pixels: int = 0) -> np.ndarray:
    """bwconncomp (8-connected) with components of fewer than min_pixels
    removed, as a label matrix (0 = background). Label numbers differ from
    labelmatrix's, but ais_auto only uses them for identity."""
    lab, n = ndi.label(bw, structure=np.ones((3, 3), bool))
    if n and min_pixels:
        sizes = np.bincount(lab.ravel(), minlength=n + 1)
        small = sizes < min_pixels
        small[0] = True
        lab[small[lab]] = 0
    return lab


def bwdist_nearest(bw: np.ndarray, r: int, c: int) -> tuple[int, int]:
    """The pixel [~, IDX] = bwdist(BW) names at (r, c): the nearest true pixel
    by exact Euclidean distance, ties going to the smallest column-major
    linear index (checked on thousands of MATLAB ties)."""
    rows, cols = np.nonzero(bw)
    if rows.size == 0:
        raise MatlabError("bwdist of an empty image has no nearest pixel")
    d2 = (rows - r) ** 2 + (cols - c) ** 2
    best = np.flatnonzero(d2 == d2.min())
    lin = cols[best] * bw.shape[0] + rows[best]
    k = best[np.argmin(lin)]
    return int(rows[k]), int(cols[k])


def _thin_lut(second: bool) -> np.ndarray:
    """images.internal.lutthin1/2 (createThinningLut.m): Lam, Lee & Suen 1992."""
    lut = np.zeros(512, bool)
    for k in range(512):
        I = np.array([(k >> b) & 1 for b in range(9)], bool).reshape(3, 3, order="F")
        x = [I[1, 2], I[0, 2], I[0, 1], I[0, 0], I[1, 0], I[2, 0], I[2, 1], I[2, 2]]
        b = [not x[2 * i - 2] and (x[2 * i - 1] or x[(2 * i) % 8]) for i in range(1, 5)]
        g1 = sum(b) == 1
        n1 = sum(x[2 * i - 2] or x[2 * i - 1] for i in range(1, 5))
        n2 = sum(x[2 * i - 1] or x[(2 * i) % 8] for i in range(1, 5))
        g2 = min(n1, n2) in (2, 3)
        if second:
            g3 = not ((x[5] or x[6] or not x[3]) and x[4])
        else:
            g3 = not ((x[1] or x[2] or not x[7]) and x[0])
        lut[k] = bool(I[1, 1]) and not (g1 and g2 and g3)
    return lut


LUT_THIN1 = _thin_lut(False)
LUT_THIN2 = _thin_lut(True)
_WEIGHTS = (1 << np.arange(9)).reshape(3, 3, order="F")


def bwlookup3(bw: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """bwlookup with a 512-entry LUT; outside the image counts as false."""
    p = np.pad(bw, 1).astype(np.int32)
    H, W = bw.shape
    idx = np.zeros((H, W), np.int32)
    for i in range(3):
        for j in range(3):
            idx += _WEIGHTS[i, j] * p[i:i + H, j:j + W]
    return lut[idx]


def bwmorph_thin(bw: np.ndarray, n: float = math.inf) -> np.ndarray:
    """bwmorph(BW, 'thin', n): both sub-iterations per pass, until no change.

    Thinning never sets a pixel (the LUTs keep a false centre false), so only
    the bounding box of the true pixels, plus a pixel of margin, is worked
    on; the result is the same as thinning the whole image."""
    full = bw.astype(bool)
    rows, cols = np.flatnonzero(full.any(axis=1)), np.flatnonzero(full.any(axis=0))
    if rows.size == 0:
        return full
    r0, r1 = max(rows[0] - 1, 0), min(rows[-1] + 2, full.shape[0])
    c0, c1 = max(cols[0] - 1, 0), min(cols[-1] + 2, full.shape[1])
    result = np.zeros_like(full)
    result[r0:r1, c0:c1] = _thin(full[r0:r1, c0:c1], n)
    return result


def _thin(bw: np.ndarray, n: float) -> np.ndarray:
    out = bw
    it = 0
    while it < n:
        last = out
        out = bwlookup3(bwlookup3(out, LUT_THIN1), LUT_THIN2)
        it += 1
        if np.array_equal(last, out):
            break
    return out


# --- numbers ---------------------------------------------------------------

def round_half_away(x):
    """MATLAB round: halves go away from zero (numpy rounds them to even)."""
    x = np.asarray(x, dtype=np.float64)
    ax = np.abs(x)
    f = np.floor(ax)
    return np.copysign(f + (ax - f >= 0.5), x)


def colon(a: float, d: float, b: float) -> np.ndarray:
    """a:d:b with MATLAB's arithmetic: built from both ends so it is symmetric
    about the midpoint and lands on b exactly (Moler, "The colon operator")."""
    tol = 2.0 * EPS * max(abs(a), abs(b))
    sig = math.copysign(1.0, d)
    if a == math.floor(a) and d == 1:
        n = math.floor(b) - a
    elif a == math.floor(a) and d == math.floor(d):
        n = math.floor((b - a) / d)
    else:
        n = round_half_away((b - a) / d)
        if sig * (a + n * d - b) > tol:
            n -= 1
    n = int(n)
    if n < 0:
        return np.zeros(0)
    c = a + n * d
    if sig * (c - b) > -tol:
        c = b
    v = np.zeros(n + 1)
    k = np.arange(n // 2 + 1)
    v[k] = a + k * d
    v[n - k] = c - k * d
    if n % 2 == 0:
        v[n // 2] = (a + c) / 2
    return v


def num2str(x: float, precision: int) -> str:
    """num2str(x, precision) == sprintf('%.<precision>g', x)."""
    return f"{x:.{precision}g}"


# --- smoothing spline ------------------------------------------------------

def csaps(x: np.ndarray, y: np.ndarray, p: float, xx: np.ndarray) -> np.ndarray:
    """csaps(x, y, p, xx) for increasing, distinct x and unit weights.

    y is (d, n) like MATLAB's vector-valued input; returns (d, len(xx)). A
    line-by-line port of csaps1 (curvefit/splines/csaps.m) and ppual.
    """
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    n = x.size
    if n < 2:
        raise MatlabError("SPLINES:CHCKXYWP:toofewpoints")
    if y.shape[1] != n:
        raise MatlabError("SPLINES:CHCKXYWP:XdontmatchY")
    yi = y.T.copy()                        # n x yd
    dx = np.diff(x)
    divdif = np.diff(yi, axis=0) / dx[:, None]
    if n == 2:
        coefs = np.stack([divdif[0], yi[0]], axis=1)[None]   # 1 piece, order 2
        return _ppval(x, coefs, xx)
    odx = 1.0 / dx
    m = n - 2
    R = np.zeros((m, m))
    Qt = np.zeros((m, n))
    for i in range(m):
        R[i, i] = 2 * (dx[i + 1] + dx[i])
        if i > 0:
            R[i, i - 1] = dx[i]
        if i < m - 1:
            R[i, i + 1] = dx[i + 1]
        Qt[i, i] = odx[i]
        Qt[i, i + 1] = -(odx[i + 1] + odx[i])
        Qt[i, i + 2] = odx[i + 1]
    A = (6 * (1 - p)) * (Qt @ Qt.T) + p * R
    # A is symmetric pentadiagonal; solve in banded form (MATLAB's sparse
    # backslash also takes a banded path).
    ab = np.zeros((5, m))
    for k in range(-2, 3):
        diag = np.diagonal(A, k)
        if k >= 0:
            ab[2 - k, k:] = diag
        else:
            ab[2 - k, :m + k] = diag
    u = linalg.solve_banded((2, 2), ab, np.diff(divdif, axis=0))
    zeros = np.zeros((1, yi.shape[1]))
    yi = yi - (6 * (1 - p)) * np.diff(
        np.vstack([zeros, np.diff(np.vstack([zeros, u, zeros]), axis=0) / dx[:, None], zeros]), axis=0)
    c3 = np.vstack([zeros, p * u, zeros])
    c2 = np.diff(yi, axis=0) / dx[:, None] - dx[:, None] * (2 * c3[:-1] + c3[1:])
    # pieces x yd x order (highest power first)
    coefs = np.stack([np.diff(c3, axis=0) / dx[:, None], 3 * c3[:-1], c2, yi[:-1]], axis=2)
    return _ppval(x, coefs, xx)


def _ppval(breaks: np.ndarray, coefs: np.ndarray, xx: np.ndarray) -> np.ndarray:
    """ppual: piece j covers [breaks[j], breaks[j+1]), the last one closed;
    points outside extend the end pieces. Horner in the local variable."""
    xx = np.asarray(xx, np.float64)
    j = np.searchsorted(breaks[1:-1], xx, side="right")
    s = xx - breaks[j]
    c = coefs[j]                            # len(xx) x yd x order
    v = c[:, :, 0].copy()
    for k in range(1, c.shape[2]):
        v = v * s[:, None] + c[:, :, k]
    return v.T
