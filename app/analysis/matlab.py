"""Checking a result in MATLAB itself, with the original ais_auto.m.

ais_auto(cell, ...) reads <cell>.tif - Processed method 2.5.tif and <cell>.tif
and writes <cell>_xy.txt beside them, so both files are copied into a fresh
folder under the app's storage first: the user's data folder is never written
to, uploaded images work too, and a cell with one file gets it under both
names -- what the web port does for a single image. A .czi is written out as
the pair the web port traces: its processed AIS channel (preprocess.py) and
the AIS channel as ZEN exports it to TIFF (Library.matlab_pair).

Three ways to run it, all in MATLAB's desktop (-desktop: without it a MATLAB
started with no terminal reads commands from stdin, hits end-of-file when
ais_auto returns, and quits -- taking the result figures with it):

  open    the original, untouched: ais_auto.m in the Editor, the current
          folder set, and the exact call printed and on the clipboard to run
          by hand.
  run     the same call, run for you; zoom, click and the final key are yours.
  replay  the web screen's own click(s): a copy of ais_auto.m with two
          mechanical changes (the zoom pause becomes a 1 s pause; ginput(1) for
          the click becomes ais_replay_click, which plays back the web clicks
          and marks each with an orange +). The final key press is still
          yours, after the spline is drawn. Every other line is the original's.

The smooth setting is the call's own argument. Any other setting that differs
from the original's constants (ais_auto.Settings.patches) is written into a
copy, ais_auto_settings.m (or the replay copy), in the run folder, with a
header listing what changed; with the original's constants open and run use
ais_auto.m itself.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from app.analysis.ais_auto import DEFAULT, Settings
from app.analysis.images import ImageError
from app.analysis.local import platform

ORIGINAL_CODE = Path(__file__).resolve().parents[2] / "original-code"
PROCESSED_SUFFIX = ".tif - Processed method 2.5.tif"
KEEP_RUNS = 20
MODES = ("open", "run", "replay")

# (original text, replacement): each must occur exactly once in ais_auto.m, so
# a change to the original fails loudly instead of replaying something else.
REPLAY_PATCHES = [
    ("function [out] = ais_auto(cell,threshold,smooth,chosen)",
     "function [out] = ais_auto_replay(cell,threshold,smooth,chosen)"),
    ("    zoom ON;pause;zoom OFF;\n",
     "    pause(1);   % replay: the original waits here for you to zoom and press a key\n"),
    ("    [Xcell,Ycell]=ginput(1);",
     "    [Xcell,Ycell]=ais_replay_click();   % replay: the web click(s) instead of ginput(1)"),
]

REPLAY_CLICK = """function [x, y] = ais_replay_click()
% Stand-in for ginput(1) in ais_auto_replay: pops the next web click (MATLAB
% axes coordinates) and marks it on the figure. With one click left it
% repeats, which is "clicked the same spot again" for the re-threshold pass.
global AIS_REPLAY_CLICKS
x = AIS_REPLAY_CLICKS(1,1);
y = AIS_REPLAY_CLICKS(1,2);
if size(AIS_REPLAY_CLICKS,1) > 1
    AIS_REPLAY_CLICKS(1,:) = [];
end
plot(x, y, '+', 'Color', [1 0.6 0], 'MarkerSize', 18, 'LineWidth', 2);
drawnow;
pause(1);
end
"""


def find_matlab(configured: str) -> str | None:
    """server.matlab when set, else the newest /Applications/MATLAB_R*.app,
    else `matlab` on the PATH."""
    if configured:
        return configured if Path(configured).is_file() else None
    if platform() == "mac":
        apps = sorted(Path("/Applications").glob("MATLAB_R*.app"), key=lambda p: p.name)
        for app in reversed(apps):
            binary = app / "bin" / "matlab"
            if binary.is_file():
                return str(binary)
    return shutil.which("matlab")


def _str(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def apply_patches(text: str, patches) -> str:
    """Each (old, new[, count]) must occur exactly count (default 1) times."""
    for old, new, *count in patches:
        want = count[0] if count else 1
        if text.count(old) != want:
            raise ImageError(f"ais_auto.m has changed: cannot apply a patch ({old.strip()[:40]!r})")
        text = text.replace(old, new)
    return text


def settings_header(settings: Settings) -> str:
    changed = settings.changed()
    changed.pop("smooth", None)
    lines = ["% Built by AIS Counter from original-code/ais_auto.m with these constants changed",
             "% (every other line is the original's):"]
    lines += [f"%   {k} = {v!r} (original {getattr(DEFAULT, k)!r})" for k, v in changed.items()]
    return "\n".join(lines) + "\n"


def settings_source(settings: Settings = DEFAULT, name: str = "ais_auto_settings") -> str:
    """ais_auto.m with the settings' constants written in, as function name."""
    text = (ORIGINAL_CODE / "ais_auto.m").read_text()
    text = apply_patches(text, [("function [out] = ais_auto(cell,", f"function [out] = {name}(cell,")])
    text = apply_patches(text, settings.patches())
    return settings_header(settings) + text if settings.patches() else text


def replay_source(settings: Settings = DEFAULT) -> str:
    text = settings_source(settings, "ais_auto")
    return apply_patches(text, REPLAY_PATCHES)


def stage(runs_dir: Path, cell: str, processed: bytes, raw: bytes | None) -> Path:
    """Write the pair (TIFF bytes) into runs_dir/<time>-<cell>/ under the
    original's names; returns the <cell> path stem ais_auto takes. Old runs
    beyond KEEP_RUNS go."""
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in cell) or "cell"
    runs_dir.mkdir(parents=True, exist_ok=True)
    runs = sorted(p for p in runs_dir.iterdir() if p.is_dir())   # oldest first: names start with the time
    for old in runs[:max(0, len(runs) - (KEEP_RUNS - 1))]:
        shutil.rmtree(old, ignore_errors=True)
    folder = runs_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}"
    n = 1
    while folder.exists():
        n += 1
        folder = runs_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}-{n}"
    folder.mkdir()
    stem = folder / safe
    (folder / (safe + PROCESSED_SUFFIX)).write_bytes(processed)
    (folder / (safe + ".tif")).write_bytes(raw or processed)
    return stem


def function_name(mode: str, settings: Settings) -> str:
    if mode == "replay":
        return "ais_auto_replay"
    return "ais_auto_settings" if settings.patches() else "ais_auto"


def command(mode: str, stem: Path, threshold: float, clicks: list[tuple[float, float]] | None = None,
            settings: Settings = DEFAULT) -> str:
    """What the new MATLAB session runs."""
    fn = function_name(mode, settings)
    call = f"{fn}({_str(str(stem))}, {threshold!r}, {_str(settings.smooth)}, 0)"
    source = ORIGINAL_CODE / "ais_auto.m" if fn == "ais_auto" else stem.parent / f"{fn}.m"
    # diary copies the command window into <stem>_matlab.log: with the desktop,
    # MATLAB's output goes there rather than to stdout.
    steps = [f"diary({_str(str(stem) + '_matlab.log')})", f"cd({_str(str(stem.parent))})",
             f"addpath({_str(str(ORIGINAL_CODE))})"]
    if mode == "open":
        steps += [
            f"edit({_str(str(source))})",
            f"clipboard('copy', {_str(call)})",
            (f"disp('{source.name} (the original with the changed constants listed at its top) is open in the Editor. "
             "To run it on this image, paste (it is on the clipboard):')" if fn != "ais_auto" else
             "disp('The original ais_auto.m is open in the Editor. To run it on this image, paste (it is on the clipboard):')"),
            f"disp({_str('    ' + call)})",
        ]
    elif mode == "run":
        steps += [
            "disp('ais_auto.m: zoom if needed, press a key in the figure, click just outside the AIS start; "
            "after the trace shows press a key (n discards). The results stay open here.')",
            call,
        ]
    elif mode == "replay":
        if not clicks:
            raise ImageError("replay needs the clicks")
        rows = "; ".join(f"{x!r} {y!r}" for x, y in clicks)
        steps += [
            "global AIS_REPLAY_CLICKS",
            f"AIS_REPLAY_CLICKS = [{rows}]",
            "disp('Replaying the web click(s) in ais_auto.m (orange +). After the trace shows, press a key "
            "(n discards). The results stay open here.')",
            call,
        ]
    else:
        raise ImageError("unknown MATLAB mode")
    return "; ".join(steps) + ";"


def launch(matlab: str, mode: str, stem: Path, threshold: float,
           clicks: list[tuple[float, float]] | None = None, settings: Settings = DEFAULT) -> None:
    """Start MATLAB with its desktop, detached. The session writes its command
    window to <stem>_matlab.log (diary); MATLAB's own start-up output goes to
    <stem>_launch.log."""
    cmd = command(mode, stem, threshold, clicks, settings)
    if mode == "replay":
        (stem.parent / "ais_auto_replay.m").write_text(replay_source(settings))
        (stem.parent / "ais_replay_click.m").write_text(REPLAY_CLICK)
    elif settings.patches():
        (stem.parent / "ais_auto_settings.m").write_text(settings_source(settings))
    with open(str(stem) + "_launch.log", "wb") as log:
        subprocess.Popen([matlab, "-desktop", "-r", cmd], cwd=str(stem.parent),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
