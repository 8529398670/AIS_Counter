# `ais_auto.m`: what it does, why, and every quirk

A full reading of `original-code/ais_auto.m` and of how it was reproduced in
Python (`app/analysis/`) so that one click in the web app gives **the same
trace and the same length** as MATLAB.

## Contents

- [1. Summary](#1-summary)
- [2. How it was used](#2-how-it-was-used)
- [3. The pipeline, stage by stage](#3-the-pipeline-stage-by-stage)
- [4. Quirks in the original](#4-quirks-in-the-original)
- [5. MATLAB behaviour the port had to copy exactly](#5-matlab-behaviour-the-port-had-to-copy-exactly)
- [6. When the original crashes](#6-when-the-original-crashes)
- [7. Dead code and leftovers](#7-dead-code-and-leftovers)
- [8. How the 1-1 match was proven](#8-how-the-1-1-match-was-proven)
- [9. What we might change later (not in the port)](#9-what-we-might-change-later-not-in-the-port)
- [10. Where things live](#10-where-things-live)

---

## 1. Summary

`ais_auto` measures the **axon initial segment (AIS)** of one neuron in a
fluorescence image. The user clicks near an AIS. The script:

1. segments the image;
2. picks the blob nearest the click;
3. thins it to a one-pixel skeleton;
4. walks the skeleton into an ordered path, starting at the skeleton pixel
   nearest the click;
5. fits a smoothing spline through the path;
6. samples the intensity of the **raw** image along the spline;
7. reports where the smoothed, normalised intensity crosses 33% of its peak.

That gives the AIS start, end, peak, midpoint and length in µm. This is the
Grubb & Burrone (2010) method.

The threshold is **not global**. The first click selects a blob at the
threshold the function was called with (0.01). The threshold is then rescaled
by how bright that blob is relative to the brightest pixel in the image. The
image is re-segmented at the new threshold and the user clicks again. This
happened on 99% of test clicks (1,211 of 1,224), so in practice every AIS gets
its own threshold.

The Python port reproduces all of it, bugs included. It matches MATLAB R2026b
on **1,224 of 1,224** test clicks, and the **635 clicks that produce a length
match to the last bit**.

---

## 2. How it was used

```matlab
ais_auto('/path/to/<cell>', 0.01, 'gaussian', 0)
```

| Argument | Value used | Effect |
|---|---|---|
| `cell` | path without extension, must contain a `/` | both file names are built from it |
| `threshold` | `0.01` | starting threshold on the smoothed image (0 would mean Otsu) |
| `smooth` | `'gaussian'` | passed straight to `fspecial` |
| `chosen` | `0` | **never used** |

**Files read.** Both are single-page 16-bit greyscale, 1388×1040:

| File | Used for |
|---|---|
| `<cell>.tif - Processed method 2.5.tif` | the ImageJ-processed image: segmentation and tracing only |
| `<cell>.tif` | the raw image: the intensity profile and therefore the length |

**Interaction.**

1. Figure 1 shows the processed image.
2. The user zooms, presses a key, then clicks *"just outside the start of the
   AIS"* (`ginput`).
3. Usually the console prints *"max pixel is not in ais region. Image is
   thresholded again…"*, and the user zooms and clicks a second time.
4. Figure 8 shows the trace (blue) and spline (yellow).
5. The user presses any key to accept, or `n` to reject.

**Outputs.**

- The length is printed with `num2str(lngth,6)` and copied to the clipboard.
  That clipboard copy is how results were collected.
- `<cell>_xy.txt` holds the profile pixel coordinates.
- `out` is **never assigned** on the accept path. Calling
  `x = ais_auto(...)` would error, so it must have been called without an
  output.

---

## 3. The pipeline, stage by stage

Line numbers refer to `original-code/ais_auto.m`.

### 3.1 Normalise and smooth (lines 33–37)

```matlab
Chais        = mat2gray(Ch{1});                               % scale to 0..1
Chais_smooth = imfilter(Chais, fspecial('gaussian',[20 20],2));
```

- **Why:** smoothing merges the punctate AIS staining into one continuous
  blob before thresholding.
- **Kernel:** 20×20 with σ = 2. An even-sized kernel has no centre pixel, so
  MATLAB uses index (10,10). It reaches 9 pixels up/left and 10 down/right,
  which shifts the blur half a pixel toward the top-left.
- **Edges:** pixels beyond the image edge count as 0 (`imfilter`'s default),
  which darkens a 10-pixel band around the image border.

### 3.2 Threshold loop (lines 52–139)

Each iteration runs these steps:

| Step | Code | Detail |
|---|---|---|
| Binarise | `im2bw(Chais_smooth, threshold)` | strictly `>` threshold |
| Open | `imopen`, 3×3 square | removes specks |
| Close | `imclose`, 3×3 square | fills one-pixel gaps |
| Find blobs | `bwconncomp` | 8-connected components |
| Drop small blobs | | anything under **70 px** |
| Click | `ginput` | rounded to the nearest pixel |
| Pick blob | `L(Ycell,Xcell)` | if the click is on background, the blob holding the nearest foreground pixel (`bwdist` index) |

On the first pass only:

```matlab
max_all = max(D(:));             % brightest raw pixel in the whole image
max_ais = max(ais_select.*D);    % brightest raw pixel inside the chosen blob
if max_all ~= max_ais
    threshold = (max_ais/max_all) * threshold;   % lower the threshold
    loop = 1;                                    % segment again, click again
end
```

- **Why:** a dim AIS barely clears the threshold, so its blob is thin and
  broken. Lowering the threshold in proportion to the AIS's own brightness
  segments a dim AIS about as generously as a bright one.
- **Iteration 2** thresholds at the new value, picks the blob at the second
  click, and stops. There is never a third iteration.
- **In the test clicks:**
  - The new threshold had a median of 0.0019, about 5× lower than 0.01, and
    ranged from 0.0004 to 0.00998.
  - The chosen blob grew by a median of 1.5×. It grew more than 1.5× in 614 of
    1,224 clicks, and at most 71×: at the lower threshold the AIS often merges
    with its neighbours.

### 3.3 Skeleton (line 142)

`bwmorph(ais_select,'thin',Inf)` uses Lam, Lee & Suen's thinning (1992) until
nothing changes, leaving a one-pixel-wide, 8-connected skeleton.

### 3.4 Order the skeleton into one path (lines 166–246)

The skeleton is a set of pixels, but a profile needs an ordered line from one
end to the other. The code:

1. **Starts** at the skeleton pixel nearest the (second) click.
2. **Walks:** looks at the 8 neighbours still unvisited and steps to one of
   them, until it reaches a dead end or the path has more than 300 pixels.
3. **At a fork** (more than one unvisited neighbour) takes the first one in
   MATLAB's column-major order and remembers it as `q`.
4. **After a pass that forked**, deletes "the branch" from the skeleton and
   walks again from the start. It does this for up to 11 passes.
5. **Keeps the longest pass.**

The intent is to explore the branches one at a time and keep the longest
route. How it actually behaves is in §4.4–4.9.

Of the test clicks, 563 needed one pass and 661 needed two or more (up to 9).
In 388 clicks the longest pass was not the last one.

### 3.5 Smoothing spline and profile pixels (lines 266–308)

```matlab
t  = 1:N;                          % path index as the curve parameter
ts = [1:0.1:N, N];                 % 10 samples per path step, last one doubled
xysm = csaps(t, [col; row], 0.3, ts);
xys  = round(xysm);                % back to whole pixels
% remove repeated pixels, keeping the first  ->  x_pix, y_pix
```

The spline (smoothing parameter 0.3) irons out the skeleton's zig-zags. The
fine sampling followed by rounding and de-duplication turns the smooth curve
back into a gap-free chain of pixels. Those pixels are where the intensity is
sampled.

### 3.6 Intensity profile from the raw image (lines 385–421)

For each profile pixel:

1. Take the mean of the **3×3** neighbourhood in the raw image (`lv_smooth`).
2. Take a **sliding mean** along the profile: 10 points either side plus the
   centre, about 3.4 µm (`lv_ss`). The window is cut short near the ends.
3. Normalise to 0..1 with the profile's own min and max (`norm_lv`).

### 3.7 AIS measures (lines 436–455)

```matlab
max_i     = first index where norm_lv == 1                       % peak
ais_end   = LAST index after the peak where norm_lv > 0.33
ais_start = LAST index before the peak where norm_lv < 0.33      % 0 if none
debut = ais_start*0.161;  fin = ais_end*0.161;
lngth = fin - debut;  mid = (debut+fin)/2;  maxi = max_i*0.161;
```

The constants are `pixconv = 0.161` µm per pixel (a microscope calibration)
and `f = 0.33` (from Grubb & Burrone 2010).

---

## 4. Quirks in the original

The port keeps every one of these, because changing any of them changes the
numbers. Each says how often it mattered in the 1,224 test clicks.

Those clicks were generated, not real user clicks: a mix of clicks just off
large blobs, on blobs, and on background. Real sessions (clicking just past an
AIS tip) would hit the error paths less often.

### Thresholding and selection

**4.1 The threshold is per click and depends on the image's brightest pixel.**
The new threshold is `0.01 × max(raw inside blob) / max(raw anywhere)`.
- One hot pixel or bright cell elsewhere in the image lowers the threshold for
  every AIS in that image.
- The ratio comes from **raw** maxima (`im2double` of the unsmoothed image)
  but is applied to the **smoothed, min–max-normalised** image, which is on a
  different scale.
- *Frequency:* re-thresholding happened in 1,211 of 1,224 clicks.

**4.2 The second click decides both the blob and the trace start.** After
re-thresholding, the second click picks the blob again and sets where the
trace begins. If it lands a pixel or two from the first, the trace start can
move. The web app reuses the first click, which is exactly "clicked the same
pixel twice". The *Separate second click* switch restores the old behaviour.

**4.3 Clicking on background picks the nearest blob, ties resolved by memory
order.** `bwdist` gives the nearest foreground pixel. When two pixels are
equally near, MATLAB returns the one with the smallest column-major index
(checked on 3,764 ties). The same rule decides the trace's start pixel.

### Tracing

**4.4 At a fork, the walk always prefers left, then up.** Neighbours are
scanned in column-major order:

| Order | Neighbour |
|---|---|
| 1 | up-left |
| 2 | left |
| 3 | down-left |
| 4 | up |
| 5 | down |
| 6 | up-right |
| 7 | right |
| 8 | down-right |

It takes the first neighbour found, not the straightest or the longest.

**4.5 Branch deletion removes a rectangle, not the branch** (line 223):

```matlab
ais_traceq(Xdel, Ydel) = 0;   % Xdel = rows, Ydel = columns of the branch pixels
```

With two index *vectors*, MATLAB zeroes **every combination** of those rows
and columns. That is a whole grid covering the branch's bounding rows and
columns, not just the branch's pixels. It can delete parts of the main AIS
that share a row or column with the branch. *Frequency:* 661 of 1,224 clicks
took more than one pass.

**4.6 Only the last fork in each pass is undone.** `q` is overwritten at
every fork, so after a pass only the branch after the **last** fork is
deleted. Earlier forks in the same pass are never explored separately.

**4.7 Clicking beside the middle of an AIS traces only one half.** The start
pixel is the skeleton pixel nearest the click.
- **Click beside the middle:** the nearest skeleton pixel has a neighbour on
  each side, so the very first step counts as a fork. The walk goes one way
  (left/up first), the deletion removes that side, the next pass goes the
  other way, and the **longer half wins**. The AIS is never traced end to end
  through the click point.
- **Click past the tip:** the nearest skeleton pixel is the endpoint, so the
  walk covers the whole AIS. That is why the instructions said to click just
  past the AIS's start.
- *Frequency:* in 194 of 250 sampled clicks, the start pixel was mid-skeleton.

**4.8 Paths are capped at 301 pixels** (line 192): about 48 µm of skeleton.
Longer paths are silently truncated. *Frequency:* 6 clicks.

**4.9 At most 11 passes, and the first of equally long paths wins** (lines
233 and 244). `XaisL{[2 3]}` assigned to one variable quietly takes the first
element; this was checked in MATLAB.

### Spline and profile

**4.10 The spline is parameterised by path index, not distance.** A diagonal
step and a straight step both count as 1. With `p = 0.3` this bends the curve
slightly where the path runs diagonally.

**4.11 The profile is a staircase of pixels.** Rounding a finely sampled
curve gives a chain where most steps are horizontal or vertical (diagonal
steps were a median of 7%). A path of N skeleton pixels usually becomes more
than N profile pixels (633 of 635 measured clicks).

**4.12 The reported length counts profile points, not distance.**
- `lngth = (ais_end − ais_start) × 0.161`. Every profile point counts as
  0.161 µm, whatever direction the step goes.
- On a diagonal, the staircase uses about 2 points per √2 pixels of real
  distance.
- *Measured:* the length is a **median 17% longer than the distance along the
  spline** (10th–90th percentile 9%–25%, worst 32%), depending on the axon's
  angle.
- The comment on line 418 assumes the step is always `pixconv`; it is only
  true for horizontal or vertical axons.

**4.13 The sliding mean counts the centre point twice** (lines 404–413).
- Each window is `[lv(i-d:i) lv(i:i+d)]`, so point *i* appears twice: 22
  values, not 21.
- Near the ends the window is truncated on one side but still doubles the
  centre.
- `width = 1.5/0.161 = 9.32` gives `d = round(9.32) + 1 = 10`. The comment
  ("for d = 20, … 41") is stale.

**4.14 Normalisation uses the profile's own min and max.**
- 0 means "the dimmest point on this trace", not background.
- The 33% level is therefore relative to the trace's range, and the peak
  always normalises to exactly 1.
- A trace that starts inside the AIS has no low baseline, which feeds 4.16.

### Start, end and length

**4.15 Start and end are found asymmetrically.**
- **Start:** the closest point *before* the peak that is below 33%, i.e. the
  first crossing going backwards from the peak.
- **End:** the farthest point *after* the peak that is above 33%. If the
  profile dips below 33% and rises again, the end jumps to the later rise,
  past the first drop.

**4.16 No crossing before the peak gives start = 0** (line 448).
- The start is reported as 0 µm, and the length runs from the trace's first
  point.
- This happens when the trace begins inside the bright part (4.7, 4.14).
- *Frequency:* **306 of 635** measured clicks (48%).

**4.17 No point above 33% after the peak puts a coordinate in place of an
index** (line 442).
- `ais_end = x_pix(end)` is the **x coordinate** of the last pixel (0–1388),
  not an index into the profile, so the "length" becomes x × 0.161 − start.
- That produces meaningless values such as 206.7 µm on a 46-point trace.
- *Frequency:* **87 of 635** measured clicks (14%). The app flags these with a
  note.

**4.18 Positions are indices × 0.161, so the first profile point is at
0.161 µm,** while a start of 0 (4.16) means 0 µm. "Max" is
`max_i × 0.161`, the peak's position, not its intensity.

### Accept / reject and output

**4.19 Pressing `n` to reject crashes the function.** The `n` branch sets
`out = 0` and skips computing `x_pix`. Line 326 then uses `x_pix` and
MATLAB stops with an "unrecognised variable" error. Rejecting worked, but by
crashing.

**4.20 `<cell>_xy.txt` is written twice.**
- The first `fopen` (line 325) is never closed, so each run leaks a file
  handle.
- The second write (lines 375–380) overwrites the same file and closes it.

**4.21 The display is stretched.** `axis square` draws the 1388×1040 image in
a square, so the pixels the user clicked on were not square. Click
coordinates are still correct.

**4.22 Console noise.** `n=1` (line 249) and `d=((round(width))+1)` inside a
loop have no semicolon, so they print on every call and every profile point.

---

## 5. MATLAB behaviour the port had to copy exactly

These are not bugs in `ais_auto.m`. They are details of MATLAB's own functions
that decide the result. Each was confirmed against MATLAB output
(`tests/matlab/probe_primitives.m`, checked by `tests/test_mlcompat.py`).

| MATLAB function | Detail that matters | Port |
|---|---|---|
| `mat2gray` | computes `A*(1/range) + (−min/range)`, which differs in the last bit from `(A−min)/range` for about half the pixels | same order of operations; bit-exact |
| `fspecial('gaussian',[20 20],2)` | MATLAB's `exp`/`sum` differ from numpy's in the last bit | the kernel is stored as MATLAB's exact numbers |
| `imfilter` | zero padding, centre at (10,10) for an even kernel, applied as two 1-D passes | same; values differ by ~1e-15 (MATLAB's internal summation order), and **every thresholded mask is identical** |
| `im2bw` | strictly `>` | same |
| `imopen` | erosion treats outside the image as foreground | same |
| `imclose` | **pads the image with 2 rows/columns of zeros first**, so blobs touching the border can lose border pixels | same (found when random masks disagreed only along the border) |
| `bwconncomp` | 8-connected; label numbers are never used, only "same blob or not" | `scipy.ndimage.label` |
| `bwdist` (index output) | exact Euclidean nearest; ties go to the smallest column-major index | brute force with that tie rule; 0 mismatches on 3,764 ties |
| `bwmorph thin` | lookup tables `lutthin1`/`lutthin2`, two sub-passes, until unchanged | tables rebuilt from MATLAB's `createThinningLut.m`, identical to MATLAB's |
| `1:0.1:N` | MATLAB builds ranges from both ends so they land on N exactly | MATLAB's documented colon algorithm, bit-exact |
| `csaps` | natural cubic smoothing spline (`csaps.m` source is readable) | line-by-line port with a banded solve; within 1e-9, rounding identical |
| `round` | halves go away from zero (numpy rounds them to even) | own `round_half_away` |
| `mean` of a short vector | left-to-right sum, then divide | same; the profile `lv_ss` is bit-exact |
| `num2str(x,6)` | `%.6g` | same |
| `c{[2 3]}` into one variable | takes the first | same |

---

## 6. When the original crashes

MATLAB stops with an error in these cases, and no length is produced. The port
raises the same kind of error at the same point, and the app shows "No length"
with the reason.

| Cause | Line | MATLAB message | Test clicks |
|---|---|---|---|
| Profile has fewer than 20 points (sliding mean reads past the end) | 405 | Index exceeds the number of array elements | 499 |
| Skeleton is a single pixel (blob thinned to a point). `length(xy)` of a 2×1 array is 2, so `csaps` fits the pixel's two coordinates as a 2-point scalar series and returns one row; the arc-length loop then asks for row 2 | 274 | Index in position 2 is invalid / exceeds array bounds | 88 |
| Trace or 3×3 profile window touches the image border | 190 / 390 | Index … exceeds array bounds | 2 |
| `n` pressed to reject | 326 | unrecognised variable `x_pix` | (by design) |
| No blob of 70+ px anywhere | 113 | index invalid | 0 |

Of the 1,224 test clicks, 589 crashed in MATLAB and 635 produced a length. The
crash rate reflects the generated clicks, which often hit small specks.

---

## 7. Dead code and leftovers

| What | Lines | Note |
|---|---|---|
| `chosen` argument | 2 | never used |
| `byeye`, `nCh`, `draw`, `prof` options and the Channel 2 code | 341–352, 457–488 | single-channel only; `lv_cb`, `ais_end2` and similar are never defined |
| `folder` | 357–361 | computed (needs a `/` in `cell`) and never used |
| `saxon_um`, `mind`, `mindi` | 310–319 | O(n²) nearest-point search along the spline, never used |
| `lv_slide`, `norm_lvslide` | 405–420 | 1×1-pixel version of the profile, computed and never used |
| `v = num2str(lv_c); lv_c = str2num(v)` | 398 | converts uint16 to double by printing and re-parsing |
| `L_bw = imbinarize(L, 0.0000001)` | 109 | the comment calls it a "weird way" of writing `L > 0` |
| `% Chais_smooth=edge(Chais,smooth)` | 35 | an earlier edge-detection idea |
| ~12 figures per call | throughout | figures 2–7 are diagnostics; figure 3 shows the profile |
| `figure(1)` re-opened with the raw image | 368 | |

---

## 8. How the 1-1 match was proven

1. **Headless original.** `tests/matlab/make_headless.py` copies
   `ais_auto.m` with only the interactive parts replaced:
   - `ginput` reads from a click queue;
   - `zoom`/`pause` are removed;
   - `S = 'y'` stands in for the accept key;
   - the clipboard copy and the `_xy.txt` location are redirected;
   - the intermediate variables are saved.

   Every replacement must match exactly once, so an edit to the original makes
   the build fail.
2. **No figures.** `tests/matlab/nographics/` replaces the plotting functions
   with ones that do nothing. Hidden figures still started MATLAB's web
   renderer, which crashed with dialogs on exit. None of the plotting affects
   the analysis.
3. **Golden runs.** `scripts/parity.sh NAME` generates clicks, runs them
   through MATLAB R2026b, then runs `tests/parity.py`. That script compares,
   in order:
   - threshold(s);
   - the selected blob;
   - the skeleton;
   - the start pixel;
   - every pass's path;
   - the chosen path;
   - the spline;
   - the profile pixels;
   - the 3×3 means;
   - the normalised profile;
   - peak, start and end indices;
   - the length string.

   It reports the first stage that differs.
4. **Results.**

| Set | Clicks | Images | Matched | Lengths (all bit-exact) | Both crashed the same way |
|---|---|---|---|---|---|
| set1, random clicks | 300 | 10 | 300 | 86 | 214 |
| set2, just off large blobs | 924 | 154 | 924 | 549 | 375 |
| **Total** | **1,224** | | **1,224** | **635** | **589** |

`.venv/bin/pytest tests/` runs everything: 1,241 tests, about 10 minutes. It
includes the primitive checks and a synthetic-image test that need no example
data.

**What "exact" relies on:**

- **Smoothed values:** these differ from MATLAB by about 1e-15. A pixel would
  flip only if it sat within 1e-15 of the threshold, which happened in none of
  the 1,224 clicks.
- **Spline:** differences are within 1e-9. A point would flip only if it sat
  that close to a half-pixel when rounded.
- **Everything else** (masks, paths, pixels, indices, lengths) is identical.

---

## 9. What we might change later (not in the port)

The web app reproduces the original on purpose. Each change below would change
the numbers, so it belongs behind an explicit "improved mode", with the 1-1
mode kept for comparison with old data.

1. **Measure length as distance along the spline** (`ax_um`), not
   points × 0.161 (4.12). This removes a 9–32% overestimate that depends on
   the axon's angle.
2. **Fix the `ais_end` fallback** (4.17). When nothing is above 33% after the
   peak, use the last index, or report "no end".
3. **Delete only the branch's pixels** (4.5), and explore every fork, not just
   the last (4.6). Or replace the walk with "longest geodesic path through the
   skeleton from the start point".
4. **Trace both ways from a mid-axon click** (4.7), or snap the start to the
   nearest skeleton *endpoint*.
5. **Make re-thresholding independent of the rest of the image** (4.1), e.g.
   scale by the blob's own intensity percentile, not the global max.
6. **Use a symmetric sliding window** (4.13) and **normalise to local
   background** (4.14).
7. **Configurable constants** (pixel size, f, window, 70 px, 300 px). The
   pixel size especially matters for other microscopes.
8. **Surface the crash cases** (§6) with clear messages. The app already does
   this.

---

## 10. Where things live

| Path | What |
|---|---|
| `original-code/ais_auto.m` | the original |
| `app/analysis/ais_auto.py` | the port: `trace()` (lines 47–246) and `measure()` (lines 266–455); comments cite `.m` line numbers |
| `app/analysis/mlcompat.py` | the MATLAB functions in §5 |
| `app/analysis/_gauss20.py` | MATLAB's exact Gaussian kernel |
| `app/analysis/service.py`, `images.py` | upload storage, preview, click → JSON |
| `app/routes/ais.py`, `static/js/ais.js` | the API and the tracing screen |
| `tests/matlab/` | headless patcher, golden runner, click generator, MATLAB probes, no-op graphics |
| `tests/parity.py`, `tests/test_*.py` | stage-by-stage comparison and the test suite |
| `scripts/parity.sh` | one command: MATLAB golden run, then compare |
