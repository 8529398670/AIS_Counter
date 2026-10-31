# AIS Counter

Measures axon initial segment (AIS) start, end, length and peak position from
fluorescence microscopy images. This is a Python web-app reimplementation of the
MATLAB tool in [original-code/ais_auto.m](original-code/ais_auto.m), to be
improved on once it matches the original.

The web server is a Starlette app (link-based login, encrypted SQLite storage,
API keys, an MCP endpoint) scaffolded from the `python-webserver` template. The
Python side handles auth, storage and analysis; the UI lives in `static/`.

## Layout

```
app/            Python server (python -m app): auth, storage, routes, admin CLI
static/         browser UI: index.html, js/, css/, vendored Bootstrap
config/         config.yaml (gitignored, holds the secret key), defaults, language.yaml
scripts/        run.sh / login.sh (and .bat on Windows)
docker/         Dockerfile + run.sh (no compose)
original-code/  the MATLAB original being ported
example-data/   sample .czi / .tif images (gitignored, local only)
```

## Running

```bash
scripts/run.sh            # creates .venv, (re)starts the server, prints its URL
scripts/login.sh          # a fresh login link for the owner account
scripts/run.sh manage list-users
docker/run.sh             # build + run the hardened container
```

On a fresh clone, `cp config/config.example.yaml config/config.yaml` and set a
`secret_key` (or let `docker/run.sh` generate one). State lives in
`~/.config/ais-counter/`. `server.secure_cookies` is `false` for plain-http
localhost; set it to `true` behind https.

## Process

The **Process** screen (the default after signing in) is our
reimplementation of the original `ais_auto.m`. It opens a folder of TIFF pairs:
`<cell>.tif` (raw, sampled for the intensity profile) and
`<cell>.tif - Processed method 2.5.tif` (segmented and traced). One click near
the start of an AIS gives the original's trace and length. **Enter** accepts,
**N** rejects, **D** marks an image done.

- **Opening.** *Open folder* / *Open files* upload from the browser. *Open
  path* (admins, and only when the server listens on loopback outside Docker:
  `server.local_folders`) reads a folder straight off this machine, so the
  current file can be shown in Finder, opened in its default app, and copied
  as an exact path.
- **Batches, shared.** Each opened folder is a batch on the server
  (`app/models/ais.py`): its images, done marks and accepted AIS are shared
  by every signed-in user. The URL follows along
  (`#ais/<id>-<folder>/<image>`), so a link opens the same image, with its
  traces, for anyone; **Batches** lists them all. A browser-picked folder is
  hashed first (sha-256) and uploads in the background; files live once, by
  content, in `<app dir>/storage/ais/files/`.
- **Assignments.** Admins can split a batch among people (the people
  button in **Batches**): one slider per person, reset to an even split
  whenever someone is added or removed, always totalling 100 %. Each person
  gets a contiguous run of the images, duplicates left out. Their batch then
  opens on just their images (the Images dialog's *Mine*; the rest stay
  reachable), and they can edit or delete any AIS on those images. Changing
  the split later leaves finished images with whoever had them and deals
  out only the unfinished ones. **Batches** shows each person's progress
  (images complete, AIS, last activity) and refreshes every 5 s while open;
  *Assigned to me* filters it to your own.
- **Images dialog.** Opens after every import; previews, All / None, click,
  Ctrl/⌘-click, Shift-click, double-click to open. Byte-identical files are
  flagged *duplicate of #k* and hidden (and left out) by default.
- **Tracing.** After a click, the arrow keys walk the point 1 px (Shift: 5 px)
  and re-trace each time; Enter keeps the latest. PageUp/PageDown (and ←/→
  when nothing is pending) switch images. An image is complete once an AIS on
  it is accepted or it is marked done (D).
- **Auto.** Finds every AIS on every image of the batch without clicks,
  with the method and settings on the Settings screen
  (`app/analysis/detect.py`, `static/js/ais_auto.js`). Every blob the
  threshold leaves is traced from one end of its skeleton, so a found AIS is
  exactly what a click at that point gives. *Settings > Auto mode* picks:
  - **Confirm each image.** Stops on every image with the candidates in
    pink, numbered as they will be saved. Click one to untick it, Enter
    saves the ticked ones and marks the image done, N skips it.
  - **Review at the end.** Saves everything found, then goes back over the
    images to delete wrong ones and add missed ones; Enter marks the image
    done. The **Review** button picks this up later.
  - **Accept everything.** Saves it all without stopping.

  In every mode, a click away from the candidates traces one by hand as
  usual, and Esc stops. Other settings:
  - **Where a trace starts:** both ends (keep the better trace), the
    brighter end, or the dimmer end.
  - **Shortest, dimmest and thinnest AIS auto keeps:** 5 µm, 30 % and
    2.4 µm by default. Brightness is the measured AIS's mean raw intensity as
    a % of the image's 99.9th percentile. Width is the median of twice the
    distance to the blob's edge. Background specks are dim and thin, so
    these drop most of them; each candidate shows both numbers.
  - **Skip images already done.**

  Rows have `origin` = `auto` in the table and CSV, which also has
  `width_um` and `brightness` for every row. AIS already accepted on
  an image are not found again. An image takes about 9 s, and the next
  image is worked on while you check the current one.
- **Edit and Delete.** Tools at the top of the image (T / E / X) act on
  any trace, saved or pink.
  - **Delete:** locks on to the trace under the pointer, and a click
    removes it. Deleting renumbers the rest of the image 1..k.
  - **Edit:** click a trace, then walk its start with the arrow keys or
    click a new start. Enter updates it (a saved AIS keeps its number) and
    Esc cancels.
- **Verify in MATLAB** (admins on this machine). Per image: *Open original*
  (MATLAB with `ais_auto.m` in the Editor and the exact call on the
  clipboard — run it yourself) or *Run original*. After a web click, *Replay in
  MATLAB* runs the original with exactly those click(s) (a copy with only the
  zoom pause and the click `ginput` replaced; the final key is still yours).
  MATLAB starts with `-desktop`, so it stays open with the results. Files are
  copied into `<app dir>/storage/ais-matlab/` first (last 20 runs kept), the
  command window is logged there, and `server.matlab` picks the MATLAB.
- **Viewer.** Wheel or +/− zooms, drag or middle-drag pans, 1 is 100 %. The
  lock (L) freezes pan and zoom and keeps that view on every image; Reset (0),
  under the lock, fits the image (and becomes the locked view when locked).
- **Settings.** *Minimum AIS length* (µm, 0 = off) skips a trace that comes
  out shorter: it is shown with a note but cannot be accepted. *Trace line
  thickness* sets how thick traces and markers are drawn, on screen and in the
  exported PNGs. Both are kept in this browser.
- **About.** What each overlay colour is, the numbers and keys, the MATLAB
  requirements, and the full [ais_auto.m report](docs/ais_auto_report.md)
  rendered in the app (`/api/about/report`).
- **Results.** The table lists the newest first, for this batch or all.
  *Export* gives the CSV, or a ZIP with the CSV and one full-resolution PNG
  per image with its accepted traces drawn and numbered.

A cell with only one of the two files still works: that file is traced and
the profile is read from it too. The result carries a note and the CSV's
`source` column says `processed only` or `raw only`, since the original always
profiled the raw image.

`app/analysis/` is a line-for-line port of `ais_auto.m` as it was called,
`ais_auto(path, 0.01, 'gaussian', 0)`:

- `mlcompat.py` holds the MATLAB primitives: mat2gray, the 20×20 Gaussian,
  imfilter, im2bw, imopen/imclose, bwdist ties, bwmorph thin, colon and csaps.
- `ais_auto.py` holds the threshold loop, branch tracing, spline, profile and
  measures.

The re-threshold step asked for a second click in MATLAB. With *Second
click: Auto* (the default) the first click is reused, which equals clicking
the same pixel twice. *Manual* restores the two-click behaviour.

### Parity with MATLAB

```bash
scripts/parity.sh set1 --images 10 --per-image 30   # MATLAB golden run + compare
.venv/bin/pytest tests/                              # primitives + every golden click
```

The parity run needs MATLAB R2026b (Image Processing + Curve Fitting toolboxes)
and the local `example-data/`.

- `tests/matlab/make_headless.py` patches the original mechanically: ginput
  and the clipboard go, intermediates are dumped.
- `run_golden.m` replays the clicks.
- `tests/parity.py` names the first stage where Python and MATLAB differ.

## Roadmap

1. Improvements beyond the original: `.czi` input, batch mode, configurable
   pixel size and thresholds, results stored server-side.
