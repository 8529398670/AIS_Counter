#!/usr/bin/env bash
# A second, throwaway server for trying changes while your own keeps running:
# this checkout's code, its own venv, port, cookie and a snapshot of your data.
#
#   scripts/test_server.sh setup      create .test-venv and .test-server/ (config,
#                                     key and a snapshot of your data); again to
#                                     update the venv, keeping the snapshot
#   scripts/test_server.sh refresh    take a fresh snapshot of your data
#   scripts/test_server.sh run        run it (foreground) on TEST_PORT
#   scripts/test_server.sh login      a login link for user 1 on it
#   scripts/test_server.sh pytest ... run the tests in .test-venv
#
# .test-server/config/config.yaml is a copy of config/config.yaml with its own
# port, cookie name and app_dir (.test-server/data), and the static files read
# from this checkout. The snapshot is the database (SQLite's backup, safe while
# your server runs) and storage (a copy-on-write clone on APFS, so it costs no
# space until something changes). Nothing here touches your own data.
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )/.."
ROOT="$PWD"
VENV="$ROOT/.test-venv"
HERE="$ROOT/.test-server"
TEST_PORT="${TEST_PORT:-24015}"

live_app_dir() {
  ( cd "$ROOT" && .venv/bin/python -m app manage paths 2>/dev/null || python3 -m app manage paths ) | awk '$1 == "app" && $2 == "dir" { print $3 }'
}

make_venv() {
  local python
  python="$( command -v python3.15 || command -v python3 )"
  [ -x "$VENV/bin/python" ] || "$python" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r "$ROOT/requirements-dev.txt"
}

make_config() {
  mkdir -p "$HERE/config"
  [ -f "$ROOT/config/config.yaml" ] || { echo "no config/config.yaml to copy" >&2; exit 1; }
  sed -E \
    -e "s/^(  port: ).*/\1$TEST_PORT/" \
    -e 's#^(  app_dir: ).*#\1./data#' \
    -e 's#^(  static_dir: ).*#\1../static#' \
    -e 's/^(  cookie_name: ).*/\1ais-counter-test_session/' \
    "$ROOT/config/config.yaml" > "$HERE/config/config.yaml"
  install -m 600 "$ROOT/config/secret.key" "$HERE/config/secret.key"
}

snapshot() {
  local live
  live="$( live_app_dir )"
  [ -n "$live" ] && [ -f "$live/app.db" ] || { echo "can't find your app dir (manage paths)" >&2; exit 1; }
  rm -rf "$HERE/data"
  mkdir -p "$HERE/data"
  "$VENV/bin/python" - "$live/app.db" "$HERE/data/app.db" <<'EOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
EOF
  chmod 600 "$HERE/data/app.db"
  if [ -d "$live/storage" ]; then
    cp -cR "$live/storage" "$HERE/data/storage" 2>/dev/null || cp -R "$live/storage" "$HERE/data/storage"
  fi
  echo "snapshot of $live in $HERE/data"
}

in_test_dir() {
  cd "$HERE"
  PYTHONPATH="$ROOT" exec "$VENV/bin/python" "$@"
}

case "${1:-}" in
  setup)
    make_venv
    make_config
    [ -f "$HERE/data/app.db" ] || snapshot
    echo "ready: scripts/test_server.sh run  (http://localhost:$TEST_PORT)"
    ;;
  refresh) snapshot ;;
  run) in_test_dir -m app ;;
  login) in_test_dir -m app manage reissue-login --user-id 1 ;;
  pytest) shift; cd "$ROOT"; exec "$VENV/bin/python" -m pytest "$@" ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
