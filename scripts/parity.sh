#!/usr/bin/env bash
# Generate MATLAB golden data for the parity tests, then compare the Python port.
#
#   scripts/parity.sh NAME [--images N] [--per-image K] [--seed S]
#
# Writes tests/golden/NAME.json (clicks) and tests/golden/NAME/ (MATLAB output;
# re-running resumes where it stopped), then prints python -m tests.parity NAME.
# Needs MATLAB with the Image Processing and Curve Fitting toolboxes and the
# local example-data/ pairs.
set -euo pipefail
cd "$(dirname "$0")/.."
MATLAB="${MATLAB:-/Applications/MATLAB_R2026b.app/bin/matlab}"
name="$1"; shift
py=.venv/bin/python
$py tests/matlab/make_headless.py >/dev/null
[ -f "tests/golden/$name.json" ] || $py tests/matlab/make_jobs.py "tests/golden/$name.json" "$@"
[ -f tests/golden/probe_primitives.mat ] || "$MATLAB" -batch "addpath('tests/matlab'); probe_primitives('$PWD/example-data/006-both-tiff/5701-635-29860_b0c0x0-1388y0-1040_ORG','tests/golden/probe_primitives.mat')"
"$MATLAB" -batch "addpath('tests/matlab'); run_golden('tests/golden/$name.json','tests/golden/$name')"
$py -m tests.parity "$name"
