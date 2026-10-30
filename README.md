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

## AIS tracing

The **AIS tracing** screen (the default after signing in) opens a folder of
TIFF pairs: `<cell>.tif` (raw, sampled for the intensity profile) and
`<cell>.tif - Processed method 2.5.tif` (segmented and traced). One click near
the start of an AIS gives the original's trace and length. **Enter** accepts,
**N** rejects, and accepted rows export as CSV.

`app/analysis/` is a line-for-line port of `ais_auto.m` as it was called,
`ais_auto(path, 0.01, 'gaussian', 0)`:

- `mlcompat.py` holds the MATLAB primitives: mat2gray, the 20×20 Gaussian,
  imfilter, im2bw, imopen/imclose, bwdist ties, bwmorph thin, colon and csaps.
- `ais_auto.py` holds the threshold loop, branch tracing, spline, profile and
  measures.

The re-threshold step asked for a second click in MATLAB. Here the first
click is reused, which equals clicking the same pixel twice. The *Separate
second click* switch restores the two-click behaviour.

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
