#!/usr/bin/env bash
# Back up AIS Counter into a restic repository, on a schedule or by hand.
#
#   ./backup.sh init                  make the password file and the repository
#   ./backup.sh [run]                 take a snapshot now, then forget old ones
#   ./backup.sh list                  the snapshots
#   ./backup.sh restore [ID|latest]   put a snapshot back into this deployment
#   ./backup.sh export DIR            the whole repository as one .tar in DIR,
#                                     to copy to Dropbox, a USB drive, ...
#   ./backup.sh schedule daily|off    run it every day (macOS: launchd; Linux:
#                                     prints the crontab line)
#
#   --docker / --local                say where the server runs instead of
#                                     letting the script work it out
#   --yes                             restore without asking first
#
# Each snapshot is what `manage backup` puts in a .tar.gz -- the database,
# config.yaml and storage (every image) -- kept as a folder so restic stores
# only what changed since the last one. The database in it is re-encrypted
# under a key made for that snapshot alone and packed beside it, so a
# snapshot, or an export of the whole repository, never holds the live
# server's secret.key and cannot be used to read or sign in to it. What
# guards the snapshots is the restic password: lose it and they are gone,
# leak it with the repository and they are readable.
#
# Settings are the restic: section of config/config.yaml (repo, password_file,
# keep_*, schedule_hour). Needs restic on PATH (brew install restic), and
# either this checkout's .venv or the Docker image.
#
# Where the server runs: Docker when the container named in docker.container
# exists (running or stopped), otherwise this checkout outside Docker
# (scripts/run.sh, data in server.app_dir).
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )"
PROJECT="$( pwd )"

COMMAND="run"
MODE=""
ASSUME_YES=false
ARGS=()
for argument in "$@"; do
  case "$argument" in
    --docker) MODE="docker" ;;
    --local)  MODE="local" ;;
    --yes)    ASSUME_YES=true ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "ERROR: unknown option $argument (see ./backup.sh --help)" >&2; exit 1 ;;
    *) ARGS+=( "$argument" ) ;;
  esac
done
if [ "${#ARGS[@]}" -gt 0 ]; then
  COMMAND="${ARGS[0]}"
  ARGS=( "${ARGS[@]:1}" )
fi

CONFIG_FILE="${PROJECT}/config/config.yaml"
SECRET_FILE="${PROJECT}/config/secret.key"
RUN_DIR="${PROJECT}/.run"
STAGE_NAME="restic-staging"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "[backup] $*"; }

# --- configuration ------------------------------------------------------------

# config_shell SECTION: config.yaml's section as shell assignments, read by
# the app itself (so the defaults and validation are the server's): this
# checkout's .venv when there is one, else the Docker image.
config_shell() {
  if [ -x "${PROJECT}/.venv/bin/python" ]; then
    "${PROJECT}/.venv/bin/python" -m app config shell "$1"
    return
  fi
  command -v docker >/dev/null 2>&1 || die "neither .venv nor docker is here to read config.yaml with -- run scripts/run.sh or docker/build.sh once"
  local image="${docker_image:-ais-counter}:latest"
  docker image inspect "$image" >/dev/null 2>&1 || die "no .venv and no image $image -- run scripts/run.sh or docker/build.sh once"
  local mount=()
  [ -f "$CONFIG_FILE" ] && mount=( -v "${CONFIG_FILE}:/app/config/config.yaml:ro" )
  docker run --rm --network none --read-only --cap-drop ALL --user "$( id -u ):$( id -g )" \
    ${mount[@]+"${mount[@]}"} "$image" config shell "$1"
}

# host_path VALUE: ~ expanded, relative resolved against the project.
host_path() {
  case "$1" in
    "~")   echo "$HOME" ;;
    "~/"*) echo "${HOME}/${1#\~/}" ;;
    /*)    echo "$1" ;;
    *)     echo "${PROJECT}/${1#./}" ;;
  esac
}

load_config() {
  local assignments
  assignments="$( config_shell docker )" || die "config.yaml did not validate (above)"
  eval "$assignments"
  assignments="$( config_shell restic )" || die "config.yaml did not validate (above)"
  eval "$assignments"

  # A backend repository (sftp:host:/path, s3:..., rclone:remote:path) is
  # passed to restic as written; anything else is a folder on this machine.
  case "$restic_repo" in
    /*|~*|.*) REPO="$( host_path "$restic_repo" )"; REPO_LOCAL=true ;;
    *:*)      REPO="$restic_repo"; REPO_LOCAL=false ;;
    *)        REPO="$( host_path "$restic_repo" )"; REPO_LOCAL=true ;;
  esac
  PASSWORD_FILE="$( host_path "$restic_password_file" )"
  # Groups this deployment's snapshots in the repository, and stays the same
  # when the Mac's hostname changes.
  SNAPSHOT_HOST="$docker_container"

  case "$docker_data_dir" in
    /*) DATA_DIR="$docker_data_dir" ;;
    *)  DATA_DIR="${PROJECT}/${docker_data_dir#./}" ;;
  esac
  DATA_DIR="${DATA_DIR%/}"
}

need_restic() {
  command -v restic >/dev/null 2>&1 || die "restic is not on PATH -- brew install restic (or your package manager), then re-run"
}

restic_cmd() {
  restic --repo "$REPO" --password-file "$PASSWORD_FILE" "$@"
}

need_repo() {
  need_restic
  [ -f "$PASSWORD_FILE" ] || die "no password file at ${PASSWORD_FILE} -- run ./backup.sh init first"
  restic_cmd cat config >/dev/null 2>&1 || die "no restic repository at ${REPO} (or the password does not open it) -- run ./backup.sh init"
}

detect_mode() {
  [ -n "$MODE" ] && return
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 \
     && [ -n "$( docker ps -aq --filter "name=^${docker_container}\$" )" ]; then
    MODE="docker"
  else
    MODE="local"
  fi
}

container_running() {
  [ -n "$( docker ps -q --filter "name=^${docker_container}\$" )" ]
}

# in_container COMMAND...: run python -m app ... against the Docker
# deployment: in the container when it runs, else in a throwaway one with the
# same mounts (as docker/restore.sh does).
in_container() {
  if container_running; then
    docker exec "$docker_container" python -m app "$@"
  else
    docker run --rm --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges:true \
      --tmpfs "/tmp:rw,noexec,nosuid,size=1m" \
      -v "${DATA_DIR}:/app/data" \
      -v "${CONFIG_FILE}:/app/config/config.yaml:ro" \
      -v "${SECRET_FILE}:/app/config/secret.key:ro" \
      "${docker_image}:latest" "$@"
  fi
}

# One backup.sh at a time per checkout, so a scheduled run and an export or
# restore never overlap. mkdir is atomic; a lock left by a killed run names
# its pid and is taken over once that process is gone.
LOCK_DIR="${RUN_DIR}/backup.lock"
take_lock() {
  mkdir -p "$RUN_DIR"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    local holder
    holder="$( cat "${LOCK_DIR}/pid" 2>/dev/null || true )"
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      die "another ./backup.sh is running (pid ${holder})"
    fi
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" || die "could not take ${LOCK_DIR}"
  fi
  echo $$ > "${LOCK_DIR}/pid"
}

CLEANUP=()
on_exit() {
  local item
  for item in ${CLEANUP[@]+"${CLEANUP[@]}"}; do eval "$item" || true; done
  rm -rf "$LOCK_DIR"
}
trap on_exit EXIT

# --- init ---------------------------------------------------------------------

command_init() {
  need_restic
  if [ -f "$PASSWORD_FILE" ]; then
    say "password file already there: ${PASSWORD_FILE}"
  else
    mkdir -p "$( dirname "$PASSWORD_FILE" )"
    ( umask 077 && head -c 32 /dev/urandom | base64 | tr -d '\n=' > "$PASSWORD_FILE" && echo >> "$PASSWORD_FILE" )
    chmod 600 "$PASSWORD_FILE"
    say "wrote a new password to ${PASSWORD_FILE} (mode 0600)"
  fi
  if restic_cmd cat config >/dev/null 2>&1; then
    say "repository already there: ${REPO}"
  else
    if [ "$REPO_LOCAL" = "true" ]; then
      mkdir -p "$( dirname "$REPO" )"
    fi
    restic_cmd init
  fi
  cat <<NOTE

Keep a copy of the password somewhere that is not this machine and not
beside the repository (a password manager). Without it no snapshot can be
read; with it and the repository, every snapshot can.

  password  ${PASSWORD_FILE}
  repo      ${REPO}

Next: ./backup.sh            take the first snapshot
      ./backup.sh schedule daily
NOTE
}

# --- run ----------------------------------------------------------------------

command_run() {
  need_repo
  detect_mode
  take_lock
  local stage output
  say "$( date '+%Y-%m-%d %H:%M:%S' ) -- backing up the ${MODE} deployment"

  if [ "$MODE" = "docker" ]; then
    [ -d "$DATA_DIR" ] || die "docker.data_dir ${DATA_DIR} does not exist"
    stage="${DATA_DIR}/${STAGE_NAME}"
    CLEANUP+=( "remove_stage_docker" )
    output="$( in_container manage backup-set --out "/app/data/${STAGE_NAME}" )" || die "backup-set failed (above)"
  else
    [ -x scripts/run.sh ] || die "scripts/run.sh is missing"
    output="$( scripts/run.sh manage backup-set )" || die "backup-set failed (above)"
    stage="$( printf '%s\n' "$output" | sed -n 's/^staged: //p' | tail -n 1 )"
    [ -n "$stage" ] || die "backup-set did not say where it wrote the set"
    CLEANUP+=( "rm -rf $( printf '%q' "$stage" )" )
  fi
  printf '%s\n' "$output" | grep -v '^staged: ' | sed 's/^/  /'

  if [ ! -r "${stage}/deployment/app.db" ]; then
    die "cannot read ${stage}/deployment/app.db as $( id -un ) -- on Linux the container's files belong to its own user; run ./backup.sh with sudo"
  fi

  # Relative paths from inside the set, so every snapshot has the same two
  # entries whichever folder it was staged in. --ignore-ctime: storage is
  # hard links made fresh each run, which bumps ctime on files that have not
  # changed; size, mtime and inode still catch a real change.
  ( cd "$stage" && restic_cmd backup --host "$SNAPSHOT_HOST" --tag ais-counter --ignore-ctime deployment README.txt ) \
    || die "restic backup failed (above); nothing was forgotten"

  local keep=()
  [ "$restic_keep_daily" -gt 0 ] && keep+=( --keep-daily "$restic_keep_daily" )
  [ "$restic_keep_weekly" -gt 0 ] && keep+=( --keep-weekly "$restic_keep_weekly" )
  [ "$restic_keep_monthly" -gt 0 ] && keep+=( --keep-monthly "$restic_keep_monthly" )
  restic_cmd forget --host "$SNAPSHOT_HOST" --tag ais-counter "${keep[@]}" --prune \
    || die "restic forget failed (above); the snapshot itself was saved"
  say "done"
}

remove_stage_docker() {
  local stage="${DATA_DIR}/${STAGE_NAME}"
  [ -e "$stage" ] || return 0
  rm -rf "$stage" 2>/dev/null && return 0
  # Files the container's user owns (Linux): let a container remove them.
  docker run --rm --network none --cap-drop ALL -v "${DATA_DIR}:/app/data" \
    --entrypoint sh "${docker_image}:latest" -c "rm -rf /app/data/${STAGE_NAME}" || true
}

# --- list ---------------------------------------------------------------------

command_list() {
  need_repo
  restic_cmd snapshots --host "$SNAPSHOT_HOST" --tag ais-counter
}

# --- restore ------------------------------------------------------------------

command_restore() {
  local snapshot="${ARGS[0]:-latest}"
  need_repo
  detect_mode
  take_lock

  local work
  work="$( mktemp -d "${TMPDIR:-/tmp}/ais-counter-restore.XXXXXX" )"
  chmod 700 "$work"
  CLEANUP+=( "rm -rf $( printf '%q' "$work" )" )

  say "restoring snapshot ${snapshot} from ${REPO} into a temporary folder"
  restic_cmd restore "$snapshot" --host "$SNAPSHOT_HOST" --tag ais-counter --target "${work}/files" \
    || die "restic restore failed (above); nothing was changed"
  local manifest deployment
  manifest="$( find "${work}/files" -type f -path '*/deployment/manifest.json' | head -n 1 )"
  [ -n "$manifest" ] || die "snapshot ${snapshot} holds no deployment/manifest.json -- not one ./backup.sh made"
  deployment="$( dirname "$manifest" )"
  sed -n 's/^ *"created_at": "\(.*\)",$/  made at   \1/p; s/^ *"key_fingerprint": "\(.*\)",$/  its key   \1/p' "$manifest"

  local members=( manifest.json app.db config.yaml secret.key )
  [ -d "${deployment}/storage" ] && members+=( storage )
  # COPYFILE_DISABLE: no macOS ._ files, which restore would refuse.
  ( cd "$deployment" && COPYFILE_DISABLE=1 tar -czf "${work}/restore.tar.gz" "${members[@]}" ) \
    || die "could not pack the snapshot (above); nothing was changed"

  if [ "$ASSUME_YES" != "true" ]; then
    echo ""
    echo "This replaces the ${MODE} deployment's database and storage with that snapshot."
    echo "What is there now is kept beside it (app.db.before-restore-<time>)."
    if [ "$MODE" = "docker" ]; then
      echo "The container is stopped for the restore and started again."
    else
      echo "The server must be stopped first: scripts/run.sh stop"
    fi
    printf "Type yes to go on: "
    local answer
    read -r answer
    [ "$answer" = "yes" ] || die "nothing was restored"
  fi

  if [ "$MODE" = "docker" ]; then
    docker/restore.sh "${work}/restore.tar.gz"
  else
    scripts/run.sh manage restore --from "${work}/restore.tar.gz" --yes
  fi
}

# --- export -------------------------------------------------------------------

command_export() {
  local destination="${ARGS[0]:-}"
  [ -n "$destination" ] || die "usage: ./backup.sh export DIR"
  [ "$REPO_LOCAL" = "true" ] || die "restic.repo ${REPO} is not a folder on this machine; export copies a local repository"
  need_repo
  take_lock
  mkdir -p "$destination"
  destination="$( cd "$destination" && pwd )"
  case "$destination/" in
    "$REPO"/*) die "DIR must be outside the repository" ;;
  esac

  say "checking the repository first"
  restic_cmd check || die "restic check failed (above); fix the repository before copying it anywhere"

  local name="${docker_container}-restic-$( date '+%Y%m%d-%H%M' ).tar"
  local partial="${destination}/.${name}.partial"
  CLEANUP+=( "rm -f $( printf '%q' "$partial" )" )
  ( umask 077 && COPYFILE_DISABLE=1 tar -cf "$partial" -C "$( dirname "$REPO" )" "$( basename "$REPO" )" ) \
    || die "tar failed (above)"
  mv "$partial" "${destination}/${name}"
  say "wrote ${destination}/${name} ($( du -h "${destination}/${name}" | cut -f1 ))"
  cat <<NOTE

Everything in it is encrypted with the restic password, so it is safe to put
on Dropbox and the like. To use it elsewhere:

  tar -xf ${name}
  restic --repo $( basename "$REPO" ) snapshots          (asks for the password)

or point restic.repo in config.yaml at the unpacked folder and use
./backup.sh list / restore. The password is not in it: keep that apart.
NOTE
}

# --- schedule -----------------------------------------------------------------

command_schedule() {
  local what="${ARGS[0]:-}"
  local label="com.${docker_container}.backup"
  local log="${RUN_DIR}/backup.log"
  case "$what" in
    daily|off) ;;
    *) die "usage: ./backup.sh schedule daily|off" ;;
  esac

  if [ "$( uname )" != "Darwin" ]; then
    if [ "$what" = "daily" ]; then
      echo "Add this with \`crontab -e\` (as the user that owns the data; root for Docker on Linux):"
      echo ""
      echo "0 ${restic_schedule_hour} * * * ${PROJECT}/backup.sh run >> ${log} 2>&1"
    else
      echo "Remove the backup.sh line with \`crontab -e\`."
    fi
    return
  fi

  local plist="${HOME}/Library/LaunchAgents/${label}.plist"
  launchctl bootout "gui/$( id -u )/${label}" 2>/dev/null || true
  if [ "$what" = "off" ]; then
    rm -f "$plist"
    say "daily backup off (${label} removed)"
    return
  fi

  need_repo
  mkdir -p "$( dirname "$plist" )" "$RUN_DIR"
  # PATH for restic and docker, which launchd does not give a job.
  local path_dirs="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  local restic_dir docker_dir
  restic_dir="$( dirname "$( command -v restic )" )"
  path_dirs="${restic_dir}:${path_dirs}"
  if command -v docker >/dev/null 2>&1; then
    docker_dir="$( dirname "$( command -v docker )" )"
    path_dirs="${docker_dir}:${path_dirs}"
  fi
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${PROJECT}/backup.sh</string>
    <string>run</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${path_dirs}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${restic_schedule_hour}</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${log}</string>
  <key>StandardErrorPath</key>
  <string>${log}</string>
</dict>
</plist>
PLIST
  launchctl bootstrap "gui/$( id -u )" "$plist" || die "launchctl could not load ${plist}"
  say "daily backup on: ${restic_schedule_hour}:00 every day (missed while asleep: runs on wake)"
  say "log: ${log}"
  say "run it now to test: launchctl kickstart gui/$( id -u )/${label}"
}

# --- main ---------------------------------------------------------------------

load_config
case "$COMMAND" in
  init)     command_init ;;
  run)      command_run ;;
  list)     command_list ;;
  restore)  command_restore ;;
  export)   command_export ;;
  schedule) command_schedule ;;
  *) die "unknown command ${COMMAND} (see ./backup.sh --help)" ;;
esac
