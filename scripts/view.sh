#!/usr/bin/env bash
# Open .czi and .tif images in napari, every channel as its own layer.
#
#   scripts/view.sh IMAGE           that image; PageUp/PageDown (or [ and ])
#                                   step through the others in its folder
#   scripts/view.sh FOLDER          every .czi/.tif in it, first one shown
#   scripts/view.sh A.czi B.tif     just those
#
# The same .venv as run.sh, plus app/requirements-view.txt (napari, Qt and
# the .czi reader), installed here on first use; then `python -m app view`.
# See app/view.py for what is shown.
set -euo pipefail

if [ $# -eq 0 ]; then
  sed -n '2,7s/^# \{0,1\}//p' "$0"
  exit 2
fi

# Relative paths are relative to where this was run, not the project root.
paths=()
for path in "$@"; do
  case "$path" in
    /*) paths+=( "$path" ) ;;
    *)  paths+=( "$( pwd )/${path}" ) ;;
  esac
done

cd "$( dirname "${BASH_SOURCE[0]}" )/.."
source scripts/lib.sh
ensure_venv

# As in ensure_venv: the requirements being newer than the stamp means install again.
VIEW_STAMP="${VENV}/.requirements-view.stamp"
if [ ! -f "$VIEW_STAMP" ] || [ app/requirements-view.txt -nt "$VIEW_STAMP" ]; then
  echo "Installing app/requirements-view.txt (napari) into .venv (first time takes a minute)..."
  if ! "$PYTHON" -m pip install --quiet -r app/requirements-view.txt; then
    echo "" >&2
    echo "ERROR: installing app/requirements-view.txt failed (above)." >&2
    exit 1
  fi
  touch "$VIEW_STAMP"
fi

exec "$PYTHON" -m app view "${paths[@]}"
