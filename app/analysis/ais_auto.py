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

Settings holds the original's smooth argument and the constants it hard-codes.
The defaults are the original's values; any other value has a matching edit of
ais_auto.m (Settings.patches) so MATLAB can be run with the same settings.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

import numpy as np

from app.analysis import mlcompat as ml
from app.analysis.mlcompat import MatlabError



@dataclass(frozen=True)
class Settings:
    smooth: str = "gaussian"   # fspecial type, the smooth argument (line 37)
    kernel: int = 20           # fspecial size, [kernel kernel] (line 37)
    sigma: float = 2.0         # fspecial sigma (line 37)
    strel: int = 3             # strel('square', strel) for open and close (lines 70-71)
    min_pixels: int = 70       # components smaller than this are dropped (line 87)
    max_path: int = 300        # tracing stops once the path is longer than this (line 192)
    max_passes: int = 10       # branch passes stop once loop2 > max_passes (line 233)
    spline_p: float = 0.3      # csaps smoothing parameter (line 272)
    window_um: float = 1.5     # sliding-mean half width in microns (line 402)
    pixconv: float = 0.161     # microns per pixel (line 5)
    f: float = 0.33            # fraction of the normalised peak for start/end (line 6)

    # field -> (type, lowest, highest); ranges keep MATLAB's calls valid.
    RANGES = {
        "kernel": (int, 1, 201), "sigma": (float, 0.01, 100.0), "strel": (int, 1, 25),
        "min_pixels": (int, 0, 10_000_000), "max_path": (int, 1, 100_000),
        "max_passes": (int, 1, 1000), "spline_p": (float, 0.0, 1.0),
        "window_um": (float, 0.001, 1000.0), "pixconv": (float, 0.0001, 1000.0),
        "f": (float, 0.0, 1.0),
    }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Settings":
        """Settings from client JSON; missing fields keep the original's
        values. ValueError names the first bad field."""
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValueError("settings must be an object")
        known = {f.name for f in fields(cls)}
        values = {}
        for key, value in data.items():
            if key not in known:
                raise ValueError(f"unknown setting {key}")
            if key == "smooth":
                if value not in ml.FSPECIAL:
                    raise ValueError("smooth must be one of " + ", ".join(ml.FSPECIAL))
                values[key] = value
                continue
            kind, lo, hi = cls.RANGES[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
            if kind is int and value != int(value):
                raise ValueError(f"{key} must be a whole number")
            if not lo <= value <= hi:
                raise ValueError(f"{key} must be between {lo} and {hi}")
            values[key] = kind(value)
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)

    def changed(self) -> dict:
        """The fields that differ from the original's values."""
        default = Settings()
        return {k: v for k, v in asdict(self).items() if getattr(default, k) != v}

    @property
    def slide_d(self) -> int:
        """d = round(width) + 1, width = window_um / pixconv (lines 402-403)."""
        return int(ml.round_half_away(self.window_um / self.pixconv)) + 1

    def patches(self) -> list[tuple[str, str, int]]:
        """(text in ais_auto.m, replacement, times it occurs) for every
        constant that differs from the original's value. smooth is not here:
        it is the call's own argument."""
        d, out = Settings(), []

        def add(old: str, new: str, count: int = 1) -> None:
            out.append((old, new, count))

        if self.pixconv != d.pixconv:
            add("pixconv=0.161;", f"pixconv={_m(self.pixconv)};")
        if self.f != d.f:
            add("f = 0.33;", f"f = {_m(self.f)};")
            add("yline(0.33,", f"yline({_m(self.f)},")
        if (self.kernel, self.sigma) != (d.kernel, d.sigma):
            add("fspecial(smooth,[20 20],2)", f"fspecial(smooth,[{self.kernel} {self.kernel}],{_m(self.sigma)})")
        if self.strel != d.strel:
            add("strel('square',3)", f"strel('square',{self.strel})", 2)
        if self.min_pixels != d.min_pixels:
            add("numPixels<70", f"numPixels<{self.min_pixels}")
        if self.max_path != d.max_path:
            add("length(Xais)>300", f"length(Xais)>{self.max_path}")
        if self.max_passes != d.max_passes:
            add("loop2>10", f"loop2>{self.max_passes}")
        if self.spline_p != d.spline_p:
            add("csaps(t,xy,0.3,ts)", f"csaps(t,xy,{_m(self.spline_p)},ts)")
        if self.window_um != d.window_um:
            add("width = (1.5/(pixconv))", f"width = ({_m(self.window_um)}/(pixconv))")
        return out


def _m(x: float) -> str:
    """A number as MATLAB source that parses back to the same double."""
    return repr(int(x)) if float(x).is_integer() else repr(float(x))


DEFAULT = Settings()
PIXCONV = DEFAULT.pixconv
F = DEFAULT.f
MIN_PIXELS = DEFAULT.min_pixels
MAX_PATH = DEFAULT.max_path
MAX_PASSES = DEFAULT.max_passes
SPLINE_P = DEFAULT.spline_p
SLIDE_D = DEFAULT.slide_d   # 10 (line 403)


@dataclass
class PreparedImage:
    """Everything about the processed image that does not depend on a click."""
    pic: np.ndarray            # Ch{1}, uint16
    smooth: np.ndarray         # Chais_smooth
    D: np.ndarray              # im2double(Ch{1})
    max_all: float

    @classmethod
    def from_array(cls, pic: np.ndarray, settings: Settings = DEFAULT) -> "PreparedImage":
        if pic.ndim == 3:
            pic = pic[:, :, 0]                                       # line 15
        if settings.smooth not in ml.FSPECIAL:
            raise ValueError(f"fspecial type {settings.smooth!r} is not supported")
        chais = ml.mat2gray(pic)                                     # line 33
        h = ml.FSPECIAL[settings.smooth]((settings.kernel, settings.kernel), settings.sigma)
        sm = ml.imfilter_zero_same(chais, h)                         # line 37
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


def segment(prep: PreparedImage, threshold: float, settings: Settings = DEFAULT) -> np.ndarray:
    """Lines 56-89 + 105: threshold, open, close, drop small components."""
    bw = ml.im2bw(prep.smooth, threshold)
    k = settings.strel
    closed = ml.imclose_square(ml.imopen_square(bw, k), k)
    return ml.components8(closed, settings.min_pixels)


def trace(prep: PreparedImage, click: tuple[float, float],
          click2: tuple[float, float] | None = None,
          threshold: float = 0.01, settings: Settings = DEFAULT) -> Trace:
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
        L = segment(prep, threshold, settings)
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
            if len(path) > settings.max_path:
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
        if loop2 > settings.max_passes:
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


def measure(path: list[tuple[int, int]], raw: np.ndarray, settings: Settings = DEFAULT) -> Measures:
    """Lines 266-455: spline through the path, intensity profile from the raw
    image, AIS start/end/max/length. path is 1-based (row, col)."""
    if raw.ndim == 3:
        raw = raw[:, :, 0]
    N = len(path)
    xy = np.array([[c for _, c in path], [r for r, _ in path]], np.float64)   # line 266: [Yais; Xais]
    if N < 2:
        # length(xy) of a 2x1 array is 2, so csaps fits the two coordinates as
        # a 2-point scalar series and returns one row; line 274 then indexes row 2.
        raise MatlabError("Index in position 2 exceeds array bounds (single-pixel trace)")
    ts = np.append(ml.colon(1, 0.1, N), N)                            # line 271
    xysm = ml.csaps(np.arange(1, N + 1, dtype=np.float64), xy, settings.spline_p, ts)
    seg = np.sqrt((xysm[0, 1:] - xysm[0, :-1]) ** 2 + (xysm[1, 1:] - xysm[1, :-1]) ** 2)
    pixconv, F = settings.pixconv, settings.f
    ax_um = np.cumsum(np.concatenate([[0.0], seg])) * pixconv         # lines 273-277
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

    d = settings.slide_d
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
    debut = ais_start * pixconv
    fin = ais_end * pixconv
    lngth = fin - debut
    return Measures(
        xysm=xysm, arc_um=float(ax_um[-1]), x_pix=x_pix, y_pix=y_pix, lv_smooth=lv_smooth,
        lv_ss=lv_ss, norm_lv=norm_lv, max_i=max_i, ais_start=ais_start, ais_end=ais_end,
        debut=debut, fin=fin, mid=(debut + fin) / 2, maxi=max_i * pixconv, lngth=lngth,
        lngth_str=ml.num2str(lngth, 6), notes=notes,
    )


def _matlab_mean(v: np.ndarray) -> float:
    """mean() of a short row vector: a left-to-right sum, then divide."""
    s = 0.0
    for x in v:
        s += x
    return s / v.size
