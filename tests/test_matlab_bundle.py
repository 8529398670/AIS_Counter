"""The MATLAB replay zip (app/analysis/matlab_bundle.py). MATLAB itself is never
started here: a stub on the PATH records what run.sh would have run."""
from __future__ import annotations

import io
import os
import stat
import subprocess
import time
import zipfile

import pytest

from app.analysis import matlab, matlab_bundle
from app.analysis.ais_auto import Settings

CLICKS = [(972.5, 910.25), (970.0, 911.0)]


def job(mode="replay", cell="cell A", settings=Settings()):
    return matlab.Run(mode, "p" * 64, None, cell, 0.02, CLICKS if mode == "replay" else None, settings)


def members(data: bytes) -> dict[str, zipfile.ZipInfo]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {info.filename.split("/", 1)[1]: info for info in archive.infolist()}


def read(data: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return next(archive.read(i) for i in archive.infolist() if i.filename.endswith("/" + name))


def extract(data: bytes, into) -> "os.PathLike":
    """As unzip does, permissions included (ZipFile.extractall drops them)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(into)
        for info in archive.infolist():
            (into / info.filename).chmod(info.external_attr >> 16 & 0o777)
        return into / archive.namelist()[0].split("/")[0]


COMMON = {"cell_A.tif", "cell_A.tif - Processed method 2.5.tif", "ais_replay_start.m", "run.sh", "run.bat",
          "matlab_path.txt", "README.txt"}


@pytest.mark.parametrize("mode,settings,extra", [
    ("replay", Settings(), {"ais_auto_replay.m", "ais_replay_click.m"}),
    ("run", Settings(), {"ais_auto.m"}),
    ("open", Settings(), {"ais_auto.m"}),
    ("run", Settings(pixconv=0.2), {"ais_auto_settings.m"}),
    ("open", Settings(pixconv=0.2), {"ais_auto_settings.m"}),
])
def test_every_mode_carries_the_files_it_calls(mode, settings, extra):
    name, data = matlab_bundle.build(job(mode, settings=settings), b"P", b"R")
    assert name == f"cell_A-matlab-{mode}.zip"
    assert set(members(data)) == COMMON | extra


def test_the_pair_keeps_the_original_names():
    _, data = matlab_bundle.build(job(), b"P", b"R")
    assert read(data, "cell_A.tif - Processed method 2.5.tif") == b"P"
    assert read(data, "cell_A.tif") == b"R"


def test_a_single_image_is_both_files():
    _, data = matlab_bundle.build(job(), b"P", None)
    assert read(data, "cell_A.tif") == b"P"


def test_the_start_script_calls_with_a_slash_and_no_host_path():
    script = read(matlab_bundle.build(job(), b"P", None)[1], "ais_replay_start.m").decode()
    # ais_auto.m:357-361 scans back for a '/'; a bare name runs off the string.
    assert "ais_auto_replay('./cell_A', 0.02, 'gaussian', 0);" in script
    assert "AIS_REPLAY_CLICKS = [972.5 910.25; 970.0 911.0];" in script
    assert "diary('cell_A_matlab.log');" in script
    assert "addpath" not in script and str(matlab.ORIGINAL_CODE) not in script


def test_open_edits_the_copy_in_the_folder():
    script = read(matlab_bundle.build(job("open"), b"P", None)[1], "ais_replay_start.m").decode()
    assert "edit('ais_auto.m');" in script and "clipboard('copy', 'ais_auto(''./cell_A''" in script


def test_scripts_have_the_line_endings_their_shells_need():
    _, data = matlab_bundle.build(job(), b"P", None)
    assert b"\r" not in read(data, "run.sh")
    bat = read(data, "run.bat")
    assert bat.count(b"\n") == bat.count(b"\r\n") > 10


def test_entries_extract_readable_and_run_sh_executable():
    entries = members(matlab_bundle.build(job(), b"P", None)[1])
    assert all(i.create_system == 3 and i.compress_type == zipfile.ZIP_DEFLATED for i in entries.values())
    assert stat.S_IMODE(entries["run.sh"].external_attr >> 16) == 0o755
    assert stat.S_IMODE(entries["README.txt"].external_attr >> 16) == 0o644


def test_the_saved_path_is_data_with_no_newline():
    _, data = matlab_bundle.build(job(), b"P", None, "/opt/it's/matlab")
    assert read(data, "matlab_path.txt") == b"/opt/it's/matlab"
    assert b"it's" not in read(data, "run.sh") and b"it's" not in read(data, "run.bat")


@pytest.mark.parametrize("cell,safe", [
    ("β-IV spectrin", "_-IV_spectrin"),
    ("CON", "cell_CON"),
    ("nul.tif", "cell_nul.tif"),
    ("../../etc/passwd", "_.._etc_passwd"),
    ("..", "cell"),
    ("", "cell"),
    ("a'b\";disp(1)\n", "a_b__disp_1__"),
    ("x" * 500, "x" * 64),
])
def test_cell_names_cannot_escape(cell, safe):
    assert matlab.safe_cell(cell) == safe
    name, data = matlab_bundle.build(job(cell=cell), b"P", None)
    name.encode("latin-1")   # Content-Disposition
    assert f"'./{safe}'" in read(data, "ais_replay_start.m").decode()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert all(".." not in n.split("/") and not n.startswith("/") for n in archive.namelist())


def test_run_sh_parses():
    _, data = matlab_bundle.build(job(), b"P", None)
    subprocess.run(["sh", "-n"], input=read(data, "run.sh"), check=True)


def stub(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n{ pwd; echo "$AIS_REPLAY_DIR"; printf "%s\\n" "$@"; } > "$AIS_REPLAY_DIR/ran.txt"\n')
    path.chmod(0o755)
    return path


def run_sh(folder, env_path):
    env = {"PATH": f"{env_path}:/usr/bin:/bin", "HOME": str(folder)}
    return subprocess.run(["sh", str(folder / "run.sh")], env=env, capture_output=True, text=True, cwd="/")


def ran(folder):
    for _ in range(100):
        if (folder / "ran.txt").exists() and (folder / "ran.txt").read_text().endswith("\n"):
            return (folder / "ran.txt").read_text().splitlines()
        time.sleep(0.02)
    raise AssertionError("the stub never ran")


def test_run_sh_uses_the_saved_path_from_any_folder(tmp_path):
    saved = stub(tmp_path / "my matlab" / "matlab")
    folder = extract(matlab_bundle.build(job(), b"P", None, str(saved))[1], tmp_path / "it's here")
    assert run_sh(folder, tmp_path).returncode == 0
    lines = ran(folder)
    assert lines[1] == str(folder.resolve())
    assert lines[2:] == ["-desktop", "-r", matlab_bundle.LAUNCH]


def test_run_sh_takes_a_folder_as_its_bin_matlab(tmp_path):
    stub(tmp_path / "MATLAB_R2024b.app" / "bin" / "matlab")
    folder = extract(matlab_bundle.build(job(), b"P", None, str(tmp_path / "MATLAB_R2024b.app"))[1], tmp_path / "x")
    assert run_sh(folder, tmp_path / "empty").returncode == 0
    assert ran(folder)[2] == "-desktop"


def test_run_sh_falls_through_a_path_from_another_computer(tmp_path):
    folder = extract(matlab_bundle.build(job(), b"P", None, r"C:\Program Files\MATLAB\R2024b\bin\matlab.exe")[1], tmp_path / "x")
    # Under $HOME, the search's last place, so it beats any real install: this
    # must never start the MATLAB on the machine running the tests.
    stub(folder / "MATLAB" / "R2099a" / "bin" / "matlab")
    assert run_sh(folder, tmp_path / "empty").returncode == 0
    assert ran(folder)[2] == "-desktop"


def test_run_sh_takes_the_newest_install(tmp_path):
    folder = extract(matlab_bundle.build(job(), b"P", None)[1], tmp_path / "x")
    old, new = folder / "MATLAB" / "R2098a" / "bin" / "matlab", folder / "MATLAB" / "R2099a" / "bin" / "matlab"
    old.parent.mkdir(parents=True)
    old.write_text("#!/bin/sh\nexit 1\n")
    old.chmod(0o755)
    stub(new)
    assert run_sh(folder, tmp_path / "empty").returncode == 0
    assert ran(folder)[2] == "-desktop"


def test_run_sh_says_so_when_there_is_no_matlab(tmp_path):
    folder = extract(matlab_bundle.build(job(), b"P", None)[1], tmp_path / "x")
    if any(os.path.exists(p) for p in ("/usr/bin/matlab", "/bin/matlab")) or list(__import__("glob").glob("/Applications/MATLAB_R*.app")):
        pytest.skip("a real MATLAB is installed here, and run.sh must not start it")
    done = run_sh(folder, tmp_path / "empty")
    assert done.returncode == 1 and "MATLAB was not found" in done.stderr
