"""Verify in MATLAB (app/analysis/matlab.py): staging, the three modes, and the
replay copy of ais_auto.m. MATLAB itself is never started here."""
from __future__ import annotations

import io

import numpy as np
import pytest
import tifffile

from app.analysis import matlab
from app.analysis.ais_auto import Settings
from app.analysis.images import ImageError


def _tiff(path, value=0):
    buf = io.BytesIO()
    tifffile.imwrite(buf, np.full((10, 12), value, np.uint16))
    path.write_bytes(buf.getvalue())


def test_stage_copies_the_pair_under_the_original_names(tmp_path):
    _tiff(tmp_path / "p.tif", 1)
    _tiff(tmp_path / "r.tif", 2)
    stem = matlab.stage(tmp_path / "runs", "cell A", (tmp_path / "p.tif").read_bytes(), (tmp_path / "r.tif").read_bytes())
    assert stem.name == "cell_A"
    assert (stem.parent / "cell_A.tif - Processed method 2.5.tif").read_bytes() == (tmp_path / "p.tif").read_bytes()
    assert (stem.parent / "cell_A.tif").read_bytes() == (tmp_path / "r.tif").read_bytes()


def test_stage_uses_a_single_file_for_both(tmp_path):
    _tiff(tmp_path / "p.tif")
    stem = matlab.stage(tmp_path / "runs", "c", (tmp_path / "p.tif").read_bytes(), None)
    assert (stem.parent / "c.tif").read_bytes() == (tmp_path / "p.tif").read_bytes()


def test_stage_keeps_only_recent_runs(tmp_path):
    runs = tmp_path / "runs"
    for k in range(25):
        (runs / f"20260101-0000{k:02d}-old").mkdir(parents=True)
    _tiff(tmp_path / "p.tif")
    matlab.stage(runs, "c", (tmp_path / "p.tif").read_bytes(), None)
    left = sorted(p.name for p in runs.iterdir())
    assert len(left) == matlab.KEEP_RUNS and left[-1].endswith("-c")


@pytest.fixture
def popen(monkeypatch):
    seen = {}

    def fake(args, **kw):
        seen["args"], seen["cwd"] = args, kw["cwd"]

    monkeypatch.setattr(matlab.subprocess, "Popen", fake)
    return seen


@pytest.mark.parametrize("mode", matlab.MODES)
def test_every_mode_keeps_the_desktop_open(tmp_path, popen, mode):
    stem = tmp_path / "it's" / "cell"
    stem.parent.mkdir()
    matlab.launch("/x/matlab", mode, stem, 0.02, [(10.5, 20.0)])
    assert popen["args"][:3] == ["/x/matlab", "-desktop", "-r"]
    assert popen["cwd"] == str(stem.parent)
    assert f"addpath('{matlab.ORIGINAL_CODE}')" in popen["args"][3]


def test_run_calls_the_original(tmp_path, popen):
    stem = tmp_path / "it's" / "cell"
    stem.parent.mkdir()
    matlab.launch("/x/matlab", "run", stem, 0.02)
    assert "ais_auto('" + str(stem).replace("'", "''") + "', 0.02, 'gaussian', 0)" in popen["args"][3]


def test_open_only_opens_the_editor_and_offers_the_call(tmp_path, popen):
    stem = tmp_path / "cell"
    matlab.launch("/x/matlab", "open", stem, 0.01)
    cmd = popen["args"][3]
    assert f"edit('{matlab.ORIGINAL_CODE / 'ais_auto.m'}')" in cmd
    assert "clipboard('copy', 'ais_auto(''" in cmd
    # the call is only printed and copied, never run
    assert "; ais_auto(" not in cmd


def test_replay_writes_a_patched_copy_and_the_clicks(tmp_path, popen):
    stem = tmp_path / "cell"
    matlab.launch("/x/matlab", "replay", stem, 0.01, [(972.5, 910.25), (970.0, 911.0)])
    cmd = popen["args"][3]
    assert "AIS_REPLAY_CLICKS = [972.5 910.25; 970.0 911.0]" in cmd
    assert "ais_auto_replay('" in cmd
    replay = (tmp_path / "ais_auto_replay.m").read_text()
    original = (matlab.ORIGINAL_CODE / "ais_auto.m").read_text()
    # exactly the three patched lines differ; the final key press stays real
    changed = [(a, b) for a, b in zip(original.splitlines(), replay.splitlines()) if a != b]
    assert len(changed) == 3 and len(original.splitlines()) == len(replay.splitlines())
    assert "[~,~,S]=ginput(1);" in replay
    assert (tmp_path / "ais_replay_click.m").exists()


def test_replay_needs_clicks(tmp_path, popen):
    with pytest.raises(ImageError):
        matlab.launch("/x/matlab", "replay", tmp_path / "cell", 0.01, None)


def test_find_matlab_respects_the_config(tmp_path):
    assert matlab.find_matlab(str(tmp_path / "missing")) is None
    exe = tmp_path / "matlab"
    exe.write_text("")
    assert matlab.find_matlab(str(exe)) == str(exe)


def test_changed_constants_run_a_patched_copy(tmp_path, popen):
    stem = tmp_path / "cell"
    settings = Settings(pixconv=0.2, strel=5, smooth="log")
    matlab.launch("/x/matlab", "run", stem, 0.01, None, settings)
    assert "ais_auto_settings('" in popen["args"][3] and ", 0.01, 'log', 0)" in popen["args"][3]
    copy = (tmp_path / "ais_auto_settings.m").read_text()
    assert "pixconv=0.2;" in copy and copy.count("strel('square',5)") == 2
    assert "%   pixconv = 0.2 (original 0.161)" in copy
    assert "function [out] = ais_auto_settings(cell," in copy


def test_open_with_changed_constants_opens_the_copy(tmp_path, popen):
    stem = tmp_path / "cell"
    matlab.launch("/x/matlab", "open", stem, 0.01, None, Settings(f=0.5))
    assert f"edit('{tmp_path / 'ais_auto_settings.m'}')" in popen["args"][3]


def test_smooth_alone_needs_no_copy(tmp_path, popen):
    stem = tmp_path / "cell"
    matlab.launch("/x/matlab", "run", stem, 0.01, None, Settings(smooth="log"))
    assert "ais_auto('" in popen["args"][3] and not (tmp_path / "ais_auto_settings.m").exists()


def test_replay_with_changed_constants(tmp_path, popen):
    stem = tmp_path / "cell"
    matlab.launch("/x/matlab", "replay", stem, 0.01, [(5.0, 6.0)], Settings(max_path=150))
    replay = (tmp_path / "ais_auto_replay.m").read_text()
    assert "length(Xais)>150" in replay and "ais_replay_click()" in replay
