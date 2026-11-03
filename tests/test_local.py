"""Open path: folders on this machine (app/analysis/local.py) and the switch
that keeps it to loopback, non-container, admin-session use."""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import io
import json
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile
from starlette.requests import Request

from app.analysis import local
from app.analysis.images import ImageError, thumbnail_png
from app.core import config
from app.routes import ais


def _tiff(path, shape=(40, 60)):
    buf = io.BytesIO()
    tifffile.imwrite(buf, (np.arange(shape[0] * shape[1]) % 65535).reshape(shape).astype(np.uint16))
    path.write_bytes(buf.getvalue())


def test_listing_keeps_tiffs_and_folders(tmp_path):
    _tiff(tmp_path / "b.tif")
    _tiff(tmp_path / "a.tif - Processed method 2.5.tif")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".hidden.tif").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    out = local.listing(str(tmp_path))
    assert out["path"] == str(tmp_path.resolve())
    assert out["dirs"] == ["sub"]
    assert [f["name"] for f in out["files"]] == ["a.tif - Processed method 2.5.tif", "b.tif"]


@pytest.mark.parametrize("bad", ["relative/path", "", None, 5])
def test_listing_needs_an_absolute_folder(bad):
    with pytest.raises(ImageError):
        local.listing(bad)


def test_listing_refuses_a_file(tmp_path):
    _tiff(tmp_path / "a.tif")
    with pytest.raises(ImageError):
        local.listing(str(tmp_path / "a.tif"))


def test_thumbnail_is_a_small_png():
    png = thumbnail_png(np.zeros((1040, 1388), np.uint16))
    assert png.startswith(b"\x89PNG")
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    assert max(width, height) <= 256


def test_hashed_files_gives_each_tiff_its_sha(tmp_path):
    _tiff(tmp_path / "a.tif")
    (tmp_path / "x.txt").write_text("no")
    folder, files = local.hashed_files(str(tmp_path))
    assert folder == str(tmp_path.resolve())
    assert [f["name"] for f in files] == ["a.tif"]
    assert files[0]["sha"] == hashlib.sha256((tmp_path / "a.tif").read_bytes()).hexdigest()
    assert files[0]["path"] == str(tmp_path.resolve() / "a.tif")
    # When it was last changed (and made, where the system keeps that), as ISO text.
    modified = datetime.fromisoformat(files[0]["modified"])
    assert abs(modified.timestamp() - (tmp_path / "a.tif").stat().st_mtime) < 1


def test_hashed_files_reads_subfolders_with_the_folder_name_first(tmp_path):
    top = tmp_path / "exp"
    (top / "s1").mkdir(parents=True)
    (top / ".hidden").mkdir()
    _tiff(top / "a.tif")
    _tiff(top / "s1" / "b.tif")
    _tiff(top / ".hidden" / "c.tif")
    folder, files = local.hashed_files(str(top))
    assert [(f["name"], f["rel"]) for f in files] == [("a.tif", "exp/a.tif"), ("b.tif", "exp/s1/b.tif")]
    assert files[1]["path"] == str(top.resolve() / "s1" / "b.tif")


def test_reveal_and_open_only_touch_tiffs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(local.subprocess, "run", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(local, "platform", lambda: "mac")
    (tmp_path / "script.sh").write_text("echo hi")
    for fn in (local.reveal, local.open_file):
        with pytest.raises(ImageError):
            fn(str(tmp_path / "script.sh"))
    assert calls == []
    _tiff(tmp_path / "a.tif")
    local.reveal(str(tmp_path / "a.tif"))
    local.open_file(str(tmp_path / "a.tif"))
    target = str((tmp_path / "a.tif").resolve())
    assert calls == [["open", "-R", target], ["open", target]]


@pytest.mark.parametrize("host, wanted", [("127.0.0.1", True), ("localhost", True), ("0.0.0.0", False), ("192.168.1.5", False)])
def test_local_folders_only_on_loopback(host, wanted):
    file = config.defaults()
    file = dataclasses.replace(file, server=dataclasses.replace(file.server, host=host))
    assert config.local_folders_allowed(file) is wanted
    off = dataclasses.replace(file, server=dataclasses.replace(file.server, host=host, local_folders=False))
    assert config.local_folders_allowed(off) is False


def _request(method: str, query: bytes = b"", body: dict | None = None) -> Request:
    payload = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    app = SimpleNamespace(state=SimpleNamespace(config=SimpleNamespace(local_folders_enabled=False)))
    scope = {"type": "http", "method": method, "path": "/", "query_string": query, "headers": [], "app": app}
    return Request(scope, receive)


def test_routes_refuse_when_switched_off(tmp_path):
    _tiff(tmp_path / "a.tif")
    for handler in (ais.local_list, ais.batch_path, ais.batch_add_path, ais.local_reveal, ais.local_open, ais.local_choose, ais.local_matlab):
        response = asyncio.run(handler(_request("POST", body={"path": str(tmp_path / "a.tif")})))
        assert response.status_code == 403
