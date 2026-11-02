"""ImageJ's "Processed method 2.5": the processed image CZI mode traces on.

A port of original-code/AISCleanUpWORKS.ijm, the Fiji macro that made every
`<cell>.tif - Processed method 2.5.tif` from the ZEN `_ORG.tif` export
(docs/workflow.md). Per image:

    Duplicate; Subtract Background rolling=50        subtract_background
    Gaussian Blur sigma=2                            gaussian_blur
    8-bit (scaled to the display range)              to_8bit
    Auto Local Threshold Phansalkar radius=25 white  phansalkar
    Gaussian Blur sigma=2; Convert to Mask           gaussian_blur, convert_to_mask
    Analyze Particles size=0-10 add; roiManager Fill (changes nothing, below)
    Create Selection; on the original Clear Outside  processed

Each step copies ImageJ 1.54's code (BackgroundSubtracter, GaussianBlur,
TypeConverter, ContrastEnhancer, RankFilters, ImageProcessor ISODATA2 and
Landini's Auto_Local_Threshold 1.11), float32 arithmetic in the same order
where it decides a rounding.

The particle step looks like a hole fill, but it leaves the mask as it is:
the lab's 154 processed files in example-data/005 and 006 are exactly the
mask before it (holes and all), and so is Fiji 1.54p running the unmodified
macro. So it is left out here.

scripts/preprocess_check.py compares this, stage by stage, with Fiji running
the macro (tests/imagej/method25_stages.ijm): identical at every stage on all
154 images, and the final image identical to the lab's file on all of them.
"""
from __future__ import annotations

import math

import numpy as np

BALL_RADIUS = 50
BLUR_SIGMA = 2.0
LOCAL_RADIUS = 25
F32 = np.float32


# --- Process > Subtract Background (rolling ball, BackgroundSubtracter) ----

def _rolling_ball(radius: float) -> tuple[np.ndarray, int]:
    """RollingBall: the ball patch (heights) and the shrink factor."""
    if radius <= 10:
        shrink, trim = 1, 24
    elif radius <= 30:
        shrink, trim = 2, 24
    elif radius <= 100:
        shrink, trim = 4, 32
    else:
        shrink, trim = 8, 40
    small = max(radius / shrink, 1.0)
    xtrim = int(trim * small) // 100
    half = int(math.floor(small - xtrim + 0.5))         # Math.round
    d = np.arange(-half, half + 1, dtype=np.float64)
    temp = small * small - d[None, :] ** 2 - d[:, None] ** 2
    ball = np.where(temp > 0, np.sqrt(np.maximum(temp, 0)), 0).astype(F32)
    return ball, shrink


def _mean3(a: np.ndarray, axis: int) -> np.ndarray:
    """filter3 MEAN along one axis: edge pixels duplicated."""
    p = np.moveaxis(a, axis, 0)
    prev = np.concatenate([p[:1], p[:-1]])
    nxt = np.concatenate([p[1:], p[-1:]])
    out = (prev + p + nxt) * F32(0.333333333)
    return np.moveaxis(out, 0, axis)


def _interpolation(length: int, small_length: int, shrink: int) -> tuple[np.ndarray, np.ndarray]:
    """makeInterpolationArrays: index of the left small pixel and its weight."""
    i = np.arange(length)
    index = np.trunc((i - shrink // 2) / shrink).astype(np.int64)    # Java int division
    index = np.minimum(index, small_length - 2)
    distance = (i.astype(F32) + F32(0.5)) / F32(shrink) - (index.astype(F32) + F32(0.5))
    return index, F32(1) - distance


def background(raw: np.ndarray, radius: float = BALL_RADIUS) -> np.ndarray:
    """rollingBallFloatBackground with presmoothing: the background, float32."""
    ball, shrink = _rolling_ball(radius)
    fp = _mean3(_mean3(raw.astype(F32), 1), 0)
    H, W = fp.shape
    sh, sw = -(-H // shrink), -(-W // shrink)
    padded = np.full((sh * shrink, sw * shrink), np.inf, F32)
    padded[:H, :W] = fp
    small = padded.reshape(sh, shrink, sw, shrink).min(axis=(1, 3))
    # rollBall: the ball's height at every centre (also up to R outside the
    # image), the lowest it can sit under the in-image points it covers; then
    # every pixel is raised to the highest ball surface over it.
    R = ball.shape[0] // 2
    P = np.full((sh + 4 * R, sw + 4 * R), np.inf, F32)
    P[2 * R:2 * R + sh, 2 * R:2 * R + sw] = small
    Z = np.full((sh + 2 * R, sw + 2 * R), np.inf, F32)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            np.minimum(Z, P[R + dy:R + dy + sh + 2 * R, R + dx:R + dx + sw + 2 * R] - ball[dy + R, dx + R], out=Z)
    rolled = np.full((sh, sw), -np.finfo(F32).max, F32)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            np.maximum(rolled, Z[R - dy:R - dy + sh, R - dx:R - dx + sw] + ball[dy + R, dx + R], out=rolled)
    if shrink == 1:
        return rolled
    xi, xw = _interpolation(W, sw, shrink)
    yi, yw = _interpolation(H, sh, shrink)
    rows = rolled[:, xi] * xw + rolled[:, xi + 1] * (F32(1) - xw)
    return rows[yi] * yw[:, None] + rows[yi + 1] * (F32(1) - yw)[:, None]


def subtract_background(raw: np.ndarray, radius: float = BALL_RADIUS) -> np.ndarray:
    """Subtract Background... rolling=radius on a 16-bit image."""
    value = raw.astype(F32) - background(raw, radius) + F32(0.5)
    return np.clip(value, 0, 65535).astype(np.uint16)


# --- Process > Filters > Gaussian Blur (GaussianBlur) ----------------------

def gaussian_kernel(sigma: float, accuracy: float, max_radius: int) -> tuple[np.ndarray, np.ndarray]:
    """makeGaussianKernel: one side of the kernel, and the running sum of
    what lies beyond each point (both float32)."""
    k_radius = int(math.ceil(sigma * math.sqrt(-2 * math.log(accuracy)))) + 1
    max_radius = max(max_radius, 50)
    k_radius = min(k_radius, max_radius)
    kern = np.array([np.float32(math.exp(-0.5 * i * i / sigma / sigma)) for i in range(k_radius)], F32)
    if k_radius < max_radius and k_radius > 3:            # edge correction
        sqrt_slope = float("inf")
        r = k_radius
        while r > k_radius // 2:
            r -= 1
            a = math.sqrt(float(kern[r])) / (k_radius - r)
            if a < sqrt_slope:
                sqrt_slope = a
            else:
                break
        for r1 in range(r + 2, k_radius):
            kern[r1] = F32((k_radius - r1) * (k_radius - r1) * sqrt_slope * sqrt_slope)
    if k_radius < max_radius:
        total = float(kern[0]) + sum(2 * float(v) for v in kern[1:])
    else:
        total = sigma * math.sqrt(2 * math.pi)
    rsum = 0.5 + 0.5 * float(kern[0]) / total
    sums = np.empty(k_radius, F32)
    for i in range(k_radius):
        v = float(kern[i]) / total
        kern[i] = F32(v)
        rsum -= v
        sums[i] = F32(rsum)
    return kern, sums


def blur_lines(a: np.ndarray, sigma: float, accuracy: float) -> np.ndarray:
    """blur1Direction along the last axis (sigma small enough not to
    downscale): convolveLine, out-of-line pixels taken as the edge pixels."""
    a = a.astype(F32)
    n = a.shape[-1]
    kern, sums = gaussian_kernel(sigma, accuracy, n)
    kr = len(kern)
    i = np.arange(n)
    first_part = i < min(kr, n)
    last_part = i >= max(min(kr, n), n - kr)
    left = np.where(first_part | (last_part & (i < kr)), sums[np.minimum(i, kr - 1)], F32(0))
    right_on = (first_part & (i + kr > n)) | (last_part & (i + kr >= n))
    right = np.where(right_on, sums[np.clip(n - i - 1, 0, kr - 1)], F32(0))
    out = a * kern[0]
    out = out + left * a[..., :1]
    out = out + right * a[..., -1:]
    zero = np.zeros(a.shape[:-1] + (kr,), F32)
    padded = np.concatenate([zero, a, zero], axis=-1)
    for k in range(1, kr):
        out = out + kern[k] * (padded[..., kr - k:kr - k + n] + padded[..., kr + k:kr + k + n])
    return out


def gaussian_blur(img: np.ndarray, sigma: float = BLUR_SIGMA) -> np.ndarray:
    """Gaussian Blur... sigma on an 8- or 16-bit image, rounded back."""
    accuracy = 0.002 if img.dtype == np.uint8 else 0.0002
    out = blur_lines(blur_lines(img, sigma, accuracy).T, sigma, accuracy).T    # x, then y
    top = 255 if img.dtype == np.uint8 else 65535
    return np.clip(out + F32(0.5), 0, top).astype(img.dtype)


# --- Image > Type > 8-bit (TypeConverter, ScaleConversions) ----------------

def to_8bit(img: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """A 16-bit image to 8-bit, display range lo..hi to 0..255."""
    scale = 256.0 / (hi - lo + 1)
    value = np.maximum(img.astype(np.int64) - lo, 0)
    return np.minimum((value * scale + 0.5).astype(np.int64), 255).astype(np.uint8)


# --- Auto Local Threshold, Phansalkar (Landini, Auto_Local_Threshold) ------

def _normalize(img8: np.ndarray) -> np.ndarray:
    """ContrastEnhancer.stretchHistogram(imp, 0) with normalize on 8-bit."""
    lo, hi = int(img8.min()), int(img8.max())
    if hi <= lo:
        return img8
    i = np.arange(256)
    lut = np.where(i <= lo, 0, np.where(i >= hi, 255, ((i - lo) / (hi - lo) * 255).astype(np.int64)))
    return lut[img8].astype(np.uint8)


def circle_rows(radius: float) -> list[tuple[int, int]]:
    """RankFilters.makeLineRadii: (dy, half width) for each kernel row."""
    r2 = int(radius * radius) + 1
    k = int(math.sqrt(r2 + 1e-10))
    return [(dy, k if dy == 0 else int(math.sqrt(r2 - dy * dy + 1e-10))) for dy in range(-k, k + 1)]


def local_mean_var(img: np.ndarray, radius: float) -> tuple[np.ndarray, np.ndarray]:
    """RankFilters MEAN and VARIANCE over the circular kernel, edge pixels
    repeated outside the image; sums in double, results float32."""
    rows = circle_rows(radius)
    k = len(rows) // 2
    H, W = img.shape
    v = np.pad(img.astype(np.float64), k, mode="edge")
    c1 = np.concatenate([np.zeros((v.shape[0], 1)), np.cumsum(v, axis=1)], axis=1)
    c2 = np.concatenate([np.zeros((v.shape[0], 1)), np.cumsum(v * v, axis=1)], axis=1)
    s1 = np.zeros((H, W))
    s2 = np.zeros((H, W))
    n = 0
    for dy, dx in rows:
        y = slice(k + dy, k + dy + H)
        s1 += c1[y, k + dx + 1:k + dx + 1 + W] - c1[y, k - dx:k - dx + W]
        s2 += c2[y, k + dx + 1:k + dx + 1 + W] - c2[y, k - dx:k - dx + W]
        n += 2 * dx + 1
    mean = (s1 / n).astype(F32)
    var = np.maximum(((s2 - s1 * s1 / n) / n).astype(F32), F32(0))
    return mean, var


def phansalkar(img8: np.ndarray, radius: float = LOCAL_RADIUS, k: float = 0.25, r: float = 0.5,
               p: float = 2.0, q: float = 10.0) -> np.ndarray:
    """Phansalkar's local threshold, objects white: 255 where
    ori > mean * (1 + p exp(-q mean) + k (sd / r - 1)), on the image
    stretched to 0..255 and scaled to 0..1."""
    ori = _normalize(img8).astype(F32) * F32(1.0 / 255)
    mean, var = local_mean_var(ori, radius)
    sd = np.sqrt(var).astype(np.float64)
    m = mean.astype(np.float64)
    t = m * (1.0 + p * np.exp(-q * m) + k * ((sd / r) - 1.0))
    return np.where(ori.astype(np.float64) > t, 255, 0).astype(np.uint8)


# --- Process > Binary > Convert to Mask (Thresholder, ISODATA2) ------------

def isodata_level(histogram: np.ndarray) -> int:
    """ImageProcessor.getAutoThreshold(int[]): ImageJ's iterative IsoData."""
    h = histogram.astype(np.int64).copy()
    top = len(h) - 1
    h[0] = 0
    h[top] = 0
    nonzero = np.flatnonzero(h)
    lo = int(nonzero[0]) if len(nonzero) else top
    hi = int(nonzero[-1]) if len(nonzero) else 0
    if lo >= hi:
        return len(h) // 2
    moving = lo
    inc_values = np.arange(len(h), dtype=np.float64) * h
    while True:
        s1 = inc_values[lo:moving + 1].sum()
        s2 = float(h[lo:moving + 1].sum())
        s3 = inc_values[moving + 1:hi + 1].sum()
        s4 = float(h[moving + 1:hi + 1].sum())
        result = (s1 / s2 + s3 / s4) / 2.0
        moving += 1
        if not ((moving + 1) <= result and moving < hi - 1):
            break
    return int(math.floor(result + 0.5))


def convert_to_mask(img8: np.ndarray) -> np.ndarray:
    """Convert to Mask on an 8-bit image with no threshold set: the
    "Default" (ISODATA2) threshold, objects on the side away from the
    histogram's mode, as a boolean mask."""
    hist = np.bincount(img8.ravel(), minlength=256).astype(np.int64)
    mode = int(np.argmax(hist))
    second = int(np.max(np.delete(hist, mode)))
    h = hist.copy()
    if hist[mode] > second * 2 and second != 0:
        h[mode] = int(second * 1.5)
    level = isodata_level(h)
    smooth = blur_lines(hist.astype(F32)[None, :], 2.0, 0.01)[0]
    smooth_mode = int(np.argmax(smooth))
    lo_px, hi_px = int(img8.min()), int(img8.max())
    if float(smooth.max()) / (float(smooth.sum(dtype=F32)) / 256.0) > 1.5 and (hi_px - smooth_mode) > (smooth_mode - lo_px):
        return img8 >= level
    return img8 <= level


# --- the macro -------------------------------------------------------------

def stages(raw: np.ndarray) -> dict[str, np.ndarray]:
    """Every intermediate, named as tests/imagej/method25_stages.ijm saves
    Fiji's (masks as 0/255; there is no 7, the particle fill)."""
    raw = raw.astype(np.uint16)
    out: dict[str, np.ndarray] = {}
    out["1-background"] = sub = subtract_background(raw)
    out["2-blur"] = blurred = gaussian_blur(sub)
    out["3-8bit"] = img8 = to_8bit(blurred, int(sub.min()), int(sub.max()))
    out["4-phansalkar"] = local = phansalkar(img8)
    out["5-blur"] = soft = gaussian_blur(local)
    out["6-mask"] = convert_to_mask(soft).astype(np.uint8) * 255
    out["8-final"] = np.where(out["6-mask"] > 0, raw, 0).astype(np.uint16)
    return out


def mask(raw: np.ndarray) -> np.ndarray:
    """Which pixels the processed image keeps."""
    return stages(raw)["6-mask"] > 0


def processed(raw: np.ndarray) -> np.ndarray:
    """raw where mask() is on, 0 elsewhere, in raw's dtype."""
    return np.where(mask(raw), raw, 0).astype(raw.dtype)
