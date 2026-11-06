"""A MATLAB run as a zip, for a server that cannot reach the person's MATLAB:
it runs in Docker, or on another machine. What is inside is what stage() and
launch() would have put in a run folder (app/analysis/matlab.py), plus scripts
that find MATLAB on whichever computer the zip is opened on.

Nothing machine-specific is written into a script. The folder arrives through
AIS_REPLAY_DIR, so the launch line is one constant that needs no quoting
wherever the zip is extracted, and the person's saved MATLAB path is data in
matlab_path.txt that the scripts read rather than text they contain.

Built in memory: a pair is about 6 MB, and in the container /tmp is a small
tmpfs.
"""
from __future__ import annotations

import io
import time
import zipfile

from app.analysis import matlab

START = "ais_replay_start"
# The Go helper (helper/) launches with this same line.
LAUNCH = f"cd(getenv('AIS_REPLAY_DIR')); {START}"

RUN_SH = f"""#!/bin/sh
# Opens this image in MATLAB: sh run.sh
cd "$(dirname "$0")" || exit 1
AIS_REPLAY_DIR="$PWD"
export AIS_REPLAY_DIR

usable() {{ [ -f "$1" ] && [ -x "$1" ]; }}

matlab=""

# The path saved on your account; a folder (MATLAB_R2024b.app, or an install
# root) is taken to mean the bin/matlab inside it. One that is not on this
# computer falls through to the search below.
saved=""
IFS= read -r saved < matlab_path.txt || true
if [ -n "$saved" ]; then
  [ -d "$saved" ] && saved="$saved/bin/matlab"
  usable "$saved" && matlab=$saved
fi

# The newest install: each pattern expands in sorted order, so the last wins.
if [ -z "$matlab" ]; then
  for candidate in /Applications/MATLAB_R*.app/bin/matlab /usr/local/MATLAB/R*/bin/matlab \\
                   /opt/MATLAB/R*/bin/matlab "$HOME"/MATLAB/R*/bin/matlab; do
    usable "$candidate" && matlab=$candidate
  done
fi

[ -n "$matlab" ] || matlab=$(command -v matlab)

if [ -z "$matlab" ]; then
  echo "MATLAB was not found. Save its path under Account in AIS Counter and download again," >&2
  echo "or put the path on the first line of matlab_path.txt in this folder." >&2
  exit 1
fi

echo "Starting $matlab"
# -desktop: a MATLAB with no terminal otherwise quits when the run returns,
# taking the result figures with it.
nohup "$matlab" -desktop -r "{LAUNCH}" </dev/null >matlab_launch.log 2>&1 &
"""

RUN_BAT = f"""@echo off
rem Opens this image in MATLAB.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Double-clicking inside Explorer's zip view extracts this file alone.
if not exist "{START}.m" (
  echo Extract the whole zip first, then run run.bat from the extracted folder.
  pause
  exit /b 1
)
set "AIS_REPLAY_DIR=%CD%"
set "MATLAB="

rem The path saved on your account; a folder is taken to mean the bin\\matlab.exe
rem inside it. One that is not on this computer falls through to the search.
set "SAVED="
set /p SAVED=<matlab_path.txt
if not defined SAVED goto search
if exist "%SAVED%\\bin\\matlab.exe" (
  set "MATLAB=%SAVED%\\bin\\matlab.exe"
  goto launch
)
if exist "%SAVED%" if not exist "%SAVED%\\" (
  set "MATLAB=%SAVED%"
  goto launch
)

:search
rem The newest install: sorted by name, so the last one found wins.
for /f "delims=" %%d in ('dir /b /ad /on "%ProgramFiles%\\MATLAB\\R*" 2^>nul') do (
  if exist "%ProgramFiles%\\MATLAB\\%%d\\bin\\matlab.exe" set "MATLAB=%ProgramFiles%\\MATLAB\\%%d\\bin\\matlab.exe"
)
if defined MATLAB goto launch
for /f "delims=" %%m in ('where matlab 2^>nul') do if not defined MATLAB set "MATLAB=%%m"
if defined MATLAB goto launch

echo MATLAB was not found. Save its path under Account in AIS Counter and download again,
echo or put the path on the first line of matlab_path.txt in this folder.
pause
exit /b 1

:launch
echo Starting %MATLAB%
start "" "%MATLAB%" -r "{LAUNCH}"
""".replace("\n", "\r\n")

README = """{title}

Extract this zip, then:

  macOS, Linux   open a terminal in this folder and run:  sh run.sh
                 (double-clicking a .sh file only opens it in an editor)
  Windows        double-click run.bat in the extracted folder

MATLAB opens with this image and the run below it. {what}
The result, {cell}_xy.txt, is written to this folder.

Which MATLAB: the path saved under Account in AIS Counter, if it is on this
computer (it is in matlab_path.txt, which you can edit), else the newest MATLAB
installed in the usual place, else `matlab` on the PATH.

ais_auto.m needs the Image Processing and Curve Fitting toolboxes.
"""

WHAT = {
    "open": "ais_auto.m opens in the Editor, and the call to run is on the clipboard.",
    "run": "Zoom if needed, press a key in the figure, then click just outside the AIS start.",
    "replay": "Your web click(s) play back (orange +); when the trace shows, press a key (n discards).",
}


def start_script(job: matlab.Run, safe: str) -> str:
    """What MATLAB runs once it is in the folder. './' because ais_auto.m
    scans its cell argument back for a '/' (lines 357-361) and a bare name
    runs off the start of the string."""
    fn = matlab.function_name(job.mode, job.settings)
    steps = matlab.steps(job.mode, f"./{safe}", f"{fn}.m", job.threshold, job.clicks, job.settings)
    return "\n".join(line + ";" for line in [f"diary('{safe}_matlab.log')", *steps]) + "\n"


def _add(archive: zipfile.ZipFile, name: str, data: str | bytes, executable: bool = False) -> None:
    # A bare ZipInfo has mode 0000 and no compression, and says it was made on
    # whatever OS this is; unzip would then extract files nobody can read.
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    archive.writestr(info, data, compresslevel=1)


def build(job: matlab.Run, processed: bytes, raw: bytes | None, matlab_path: str = "") -> tuple[str, bytes]:
    """(file name, zip bytes). matlab_path is the asking person's own setting
    (User.matlab_path); it has no trailing newline so both scripts read it the
    same way."""
    safe = matlab.safe_cell(job.cell)
    folder = f"{safe}-matlab-{job.mode}"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        _add(archive, f"{folder}/{safe}{matlab.PROCESSED_SUFFIX}", processed)
        _add(archive, f"{folder}/{safe}.tif", raw or processed)
        for name, text in matlab.sources(job.mode, job.settings, portable=True).items():
            _add(archive, f"{folder}/{name}", text)
        _add(archive, f"{folder}/{START}.m", start_script(job, safe))
        _add(archive, f"{folder}/run.sh", RUN_SH, executable=True)
        _add(archive, f"{folder}/run.bat", RUN_BAT)
        _add(archive, f"{folder}/matlab_path.txt", matlab_path)
        _add(archive, f"{folder}/README.txt", README.format(title=folder, what=WHAT[job.mode], cell=safe))
    return f"{folder}.zip", out.getvalue()
