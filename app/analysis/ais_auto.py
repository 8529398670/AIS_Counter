"""A line-for-line port of original-code/ais_auto.m.

Given the processed image, one click (optionally a second click for the
re-threshold iteration) and the raw image, this reproduces the original's
trace and AIS measures exactly, including its quirks: the threshold rescaled by
the clicked component's max, the first-neighbour branch walk, the Cartesian
branch deletion, the 300-pixel cap, the duplicated centre in the sliding mean,
and the coordinate fallback for ais_end. Comments cite the .m line numbers.

Coordinates follow MATLAB where the original exposes them: clicks are axes
coordinates (pixel centres at 1..n, x = column), and the path, x_pix and y_pix
are 1-based. Internally arrays are numpy 0-based.

Where MATLAB would stop with an error, MatlabError is raised with what the
original would have hit, so callers can report "no length" the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.analysis import mlcompat as ml
from app.analysis.mlcompat import MatlabError

PIXCONV = 0.161     # microns per pixel (line 5)
F = 0.33            # fraction of the normalised peak for start/end (line 6)
MIN_PIXELS = 70     # components smaller than this are dropped (line 87)
MAX_PATH = 300      # tracing stops once the path is longer than this (line 192)
MAX_PASSES = 10     # branch passes stop once loop2 > 10 (line 233)
SPLINE_P = 0.3      # csaps smoothing parameter (line 272)
SLIDE_D = int(ml.round_half_away(1.5 / PIXCONV)) + 1   # 10 (line 403)


@dataclass
class PreparedImage:
    """Everything about the processed image that does not depend on a click."""
    pic: np.ndarray            # Ch{1}, uint16
    smooth: np.ndarray         # Chais_smooth
    D: np.ndarray              # im2double(Ch{1})
    max_all: float

    @classmethod
    def from_array(cls, pic: np.ndarray, smooth: str = "gaussian") -> "PreparedImage":
        if pic.ndim == 3:
            pic = pic[:, :, 0]                                       # line 15
        if smooth != "gaussian":
            raise ValueError("only the 'gaussian' smoothing of the original is supported")
        chais = ml.mat2gray(pic)                                     # line 33
        sm = ml.imfilter_zero_same(chais, ml.fspecial_gaussian((20, 20), 2))  # line 37
        D = ml.im2double(pic)                                        # line 125
        return cls(pic=pic, smooth=sm, D=D, max_all=float(D.max()))  # line 126


@dataclass
class Trace:
    threshold_initial: float
    threshold: float                  # the threshold the final component used
    rethresholded: bool
    max_ais: float
    max_all: float
    clicks: list[tuple[int, int]]     # rounded (Xcell, Ycell) per iteration
    selected: np.ndarray              # final ais_select (bool mask)
    skeleton: np.ndarray              # ais_skeleton
    start: tuple[int, int]            # (I_skel, J_skel), 1-based (row, col)
    passes: list[list[tuple[int, int]]]   # XaisL/YaisL: each pass's path, 1-based (row, col)
    longest: int                      # 0-based index into passes
    path: list[tuple[int, int]]       # the chosen path, 1-based (row, col)


@dataclass
class Measures:
    xysm: np.ndarray          # 2 x M spline samples (x; y), 1-based axes coords
    arc_um: float             # spline length in um (ax_um(end))
    x_pix: np.ndarray         # unique rounded spline pixels, 1-based
    y_pix: np.ndarray
    lv_smooth: np.ndarray
    lv_ss: np.ndarray
    norm_lv: np.ndarray
    max_i: int                # 1-based
    ais_start: float          # index (0 when the profile never drops below F)
    ais_end: float            # index, or x_pix(end) when nothing passes F after the max
    debut: float
    fin: float
    mid: float
    maxi: float
    lngth: float
    lngth_str: str            # num2str(lngth, 6), what the original copied to the clipboard
    notes: list[str] = field(default_factory=list)


def _click_to_pixel(x: float, y: float, shape: tuple[int, int]) -> tuple[int, int]:
    X, Y = int(ml.round_half_away(x)), int(ml.round_half_away(y))   # lines 100-101
    if not (1 <= Y <= shape[0] and 1 <= X <= shape[1]):
        raise MatlabError("Index in position 1 exceeds array bounds (click outside the image)")
    return X, Y


def _select(L: np.ndarray, X: int, Y: int) -> np.ndarray:
    """Lines 105-115: the clicked component, or the one nearest the click."""
    I = L[Y - 1, X - 1]
    if I == 0:
        bw = L > 0
        if not bw.any():
            raise MatlabError("Index in position 1 is invalid (no components above 70 px)")
        r, c = ml.bwdist_nearest(bw, Y - 1, X - 1)
        I = L[r, c]
    return L == I


def segment(prep: PreparedImage, threshold: float) -> np.ndarray:
    """Lines 56-89 + 105: threshold, open, close, drop small components."""
    bw = ml.im2bw(prep.smooth, threshold)
    closed = ml.imclose_square3(ml.imopen_square3(bw))
    return ml.components8(closed, MIN_PIXELS)


def trace(prep: PreparedImage, click: tuple[float, float],
          click2: tuple[float, float] | None = None,
          threshold: float = 0.01) -> Trace:
    """Lines 47-246. click is (x, y) in MATLAB axes coordinates. click2 is the
    click the original asks for after re-thresholding; None repeats click."""
    threshold_initial = threshold
    if threshold == 0:
        threshold = ml.graythresh(prep.smooth)                        # line 48
        threshold_initial = threshold
    queue = [click, click2 if click2 is not None else click]
    clicks: list[tuple[int, int]] = []
    loop = 0
    max_ais = prep.max_all
    while True:                                                       # line 55
        L = segment(prep, threshold)
        X, Y = _click_to_pixel(*queue[loop], prep.pic.shape)
        clicks.append((X, Y))
        sel = _select(L, X, Y)
        if loop == 0:                                                 # line 124
            max_ais = float((sel * prep.D).max())
            if prep.max_all == max_ais:
                break
            threshold = (max_ais / prep.max_all) * threshold          # line 133
            loop = 1
        else:
            break

    skel = ml.bwmorph_thin(sel)                                       # line 142
    X, Y = clicks[-1]
    r0, c0 = ml.bwdist_nearest(skel, Y - 1, X - 1)                    # lines 166-168
    H, W = skel.shape

    traceq = skel.copy()
    traceq[r0, c0] = False                                            # lines 173-176
    work = traceq.copy()
    passes: list[list[tuple[int, int]]] = []
    loop2 = 0
    while True:                                                       # line 183
        loop2 += 1
        path = [(r0, c0)]
        branch = None                                                 # MATLAB's q
        while work.any():                                             # line 186
            r, c = path[-1]
            if r < 1 or c < 1 or r + 1 >= H or c + 1 >= W:
                raise MatlabError("Index in position 1 exceeds array bounds (skeleton touches the image border)")
            win = work[r - 1:r + 2, c - 1:c + 2]
            nb = [(r - 1 + i, c - 1 + j) for j in range(3) for i in range(3) if win[i, j]]  # find(temp), column-major
            if len(path) > MAX_PATH:
                work[:] = False
            elif len(nb) > 1:
                branch = nb[0]                                        # line 195
                path.append(branch)
                work[branch] = False
            elif len(nb) == 1:
                path.append(nb[0])
                work[nb[0]] = False
            else:
                work[:] = False
        passes.append(path)
        again = False
        if branch is not None:                                        # line 218
            qdel = path.index(branch)
            rows = sorted({p[0] for p in path[qdel:]})
            cols = sorted({p[1] for p in path[qdel:]})
            traceq[np.ix_(rows, cols)] = False                        # line 223: rows x cols, not pairs
            work = traceq.copy()
            work[r0, c0] = False
            again = True
        if loop2 > MAX_PASSES:
            again = False
        if not again:
            break

    lengths = [len(p) for p in passes]
    longest = lengths.index(max(lengths))                             # line 244: first of the longest
    one = lambda p: [(r + 1, c + 1) for r, c in p]
    return Trace(
        threshold_initial=threshold_initial, threshold=threshold, rethresholded=loop == 1,
        max_ais=max_ais, max_all=prep.max_all, clicks=clicks, selected=sel, skeleton=skel,
        start=(r0 + 1, c0 + 1), passes=[one(p) for p in passes], longest=longest,
        path=one(passes[longest]),
    )


def measure(path: list[tuple[int, int]], raw: np.ndarray) -> Measures:
    """Lines 266-455: spline through the path, intensity profile from the raw
    image, AIS start/end/max/length. path is 1-based (row, col)."""
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    N = len(path)
    xy = np.array([[c for _, c in path], [r for r, _ in path]], np.float64)   # line 266: [Yais; Xais]
    if N < 2:
        raise MatlabError("SPLINES:CHCKXYWP:XdontmatchY (single-pixel trace)")
    ts = np.append(ml.colon(1, 0.1, N), N)                            # line 271
    xysm = ml.csaps(np.arange(1, N + 1, dtype=np.float64), xy, SPLINE_P, ts)
    seg = np.sqrt((xysm[0, 1:] - xysm[0, :-1]) ** 2 + (xysm[1, 1:] - xysm[1, :-1]) ** 2)
    ax_um = np.cumsum(np.concatenate([[0.0], seg])) * PIXCONV         # lines 273-277
    xys = ml.round_half_away(xysm)                                    # line 278

    seen: set[tuple[float, float]] = set()
    keep = []
    for k in range(xys.shape[1]):                                     # lines 293-305
        key = (xys[0, k], xys[1, k])
        if key not in seen:
            seen.add(key)
            keep.append(k)
    x_pix = xys[0, keep]
    y_pix = xys[1, keep]
    n = x_pix.size

    H, W = raw.shape
    xi = x_pix.astype(np.int64) - 1
    yi = y_pix.astype(np.int64) - 1
    if xi.min() < 1 or yi.min() < 1 or xi.max() + 1 >= W or yi.max() + 1 >= H:
        raise MatlabError("Index in position 1 exceeds array bounds (profile 3x3 leaves the raw image)")
    rawd = raw.astype(np.float64)
    tot = np.zeros(n)
    for dr, dc in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
        tot = tot + rawd[yi + dr, xi + dc]
    lv_smooth = tot / 9                                               # line 395

    d = SLIDE_D
    if n < 2 * d:
        raise MatlabError(f"Index exceeds the number of array elements ({n} profile points; the sliding mean needs {2 * d})")
    lv_ss = np.zeros(n)
    for i in range(1, n + 1):                                         # lines 401-415, 1-based i
        if i < d + 1:
            win = np.concatenate([lv_smooth[0:i], lv_smooth[i - 1:i + d]])
        elif i > n - (d + 1):
            win = np.concatenate([lv_smooth[i - d - 1:i], lv_smooth[i - 1:n]])
        else:
            win = np.concatenate([lv_smooth[i - d - 1:i], lv_smooth[i - 1:i + d]])
        lv_ss[i - 1] = _matlab_mean(win)

    lo, hi = lv_ss.min(), lv_ss.max()
    norm_lv = (lv_ss - lo) / (hi - lo)                                # line 421
    peak = np.flatnonzero(norm_lv == 1)
    if peak.size == 0:
        raise MatlabError("Index exceeds the number of array elements (flat profile)")
    max_i = int(peak[0]) + 1                                          # line 436
    idx = np.arange(1, n + 1)
    notes = []
    after = np.flatnonzero((idx > max_i) & (norm_lv > F))
    if after.size:
        ais_end = float(after[-1] + 1)                                # line 438: the LAST one
    else:
        ais_end = float(x_pix[-1])                                    # line 442: a coordinate, not an index
        notes.append("profile never exceeds f after its peak; the original uses x_pix(end) as ais_end")
    before = np.flatnonzero((idx < max_i) & (norm_lv < F))
    if before.size:
        ais_start = float(before[-1] + 1)
    else:
        ais_start = 0.0
        notes.append("profile never drops below f before its peak; ais_start is 0")
    debut = ais_start * PIXCONV
    fin = ais_end * PIXCONV
    lngth = fin - debut
    return Measures(
        xysm=xysm, arc_um=float(ax_um[-1]), x_pix=x_pix, y_pix=y_pix, lv_smooth=lv_smooth,
        lv_ss=lv_ss, norm_lv=norm_lv, max_i=max_i, ais_start=ais_start, ais_end=ais_end,
        debut=debut, fin=fin, mid=(debut + fin) / 2, maxi=max_i * PIXCONV, lngth=lngth,
        lngth_str=ml.num2str(lngth, 6), notes=notes,
    )


def _matlab_mean(v: np.ndarray) -> float:
    """mean() of a short row vector: a left-to-right sum, then divide."""
    s = 0.0
    for x in v:
        s += x
    return s / v.size
