"""Shared batches and accepted AIS (app/models/ais.py)."""
from __future__ import annotations

import hashlib

import pytest

from app.core import db
from app.models import ais

P = ".tif - Processed method 2.5.tif"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


def files(*entries):
    return [{"name": rel.split("/")[-1], "rel": rel, "sha": sha(content), "size": 1} for rel, content in entries]


def test_files_group_into_cells_and_duplicates_are_marked(store):
    batch = ais.create_batch(store, "f", "upload", files(
        ("f/a.tif", "a raw"), ("f/a" + P, "a proc"),
        ("f/b" + P, "b proc"),
        ("f/c.tif", "a raw"), ("f/c" + P, "a proc"),        # same bytes as a
        ("f/sub/a" + P, "other"),                           # same name, other folder
        ("f/notes.txt", "x"),
    ), user_id=1)
    keys = [(im["key"], sorted(im["files"]), im.get("dup_of")) for im in batch["images"]]
    assert keys == [("a", ["processed", "raw"], None), ("b", ["processed"], None),
                    ("c", ["processed", "raw"], 0), ("sub/a", ["processed"], None)]


def test_bad_files_are_refused(store):
    with pytest.raises(ais.BatchError):
        ais.create_batch(store, "f", "upload", [{"name": "a.tif", "sha": "nope"}], 1)
    with pytest.raises(ais.BatchError):
        ais.create_batch(store, "f", "upload", files(("f/x.txt", "x")), 1)


def row(length=1.5):
    return {"length_um": length, "length_str": str(length), "click_x": 3, "click_y": 4, "pixels": [[1, 2], [2, 3]]}


def test_results_are_numbered_per_image_and_count_as_progress(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a"), ("f/b" + P, "b")), 1)
    first = ais.add_result(store, batch["id"], "a", row(), 1)
    second = ais.add_result(store, batch["id"], "a", row(2.0), 2)
    other = ais.add_result(store, batch["id"], "b", row(), 1)
    assert (first["n"], second["n"], other["n"]) == (1, 2, 1)
    assert second["created_by"] == 2 and second["cell"] == "a"
    ais.delete_result(store, first["id"])
    assert ais.add_result(store, batch["id"], "a", row(), 1)["n"] == 3
    listed = ais.list_batches(store)[0]
    assert (listed["images"], listed["completed"]) == (2, 2)


def test_rows_are_checked(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    with pytest.raises(ais.BatchError):
        ais.add_result(store, batch["id"], "a", {"pixels": [[1, "x"]]}, 1)
    with pytest.raises(ais.BatchError):
        ais.add_result(store, batch["id"], "zz", row(), 1)


def test_done_marks_and_delete_cascade(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a"), ("f/b" + P, "b")), 1)
    assert ais.set_done(store, batch["id"], "b", True)["skipped"] == ["b"]
    assert ais.list_batches(store)[0]["completed"] == 1
    assert ais.set_done(store, batch["id"], "b", False)["skipped"] == []
    with pytest.raises(ais.BatchError):
        ais.set_done(store, batch["id"], "nope", True)
    ais.add_result(store, batch["id"], "a", row(), 1)
    ais.delete_batch(store, batch["id"])
    assert ais.get_batch(store, batch["id"]) is None and ais.list_results(store) == []


def test_local_path_lookup(store):
    f = files(("a" + P, "a"))[0] | {"path": "/data/a" + P}
    ais.create_batch(store, "data", "path", [f], 1, "/data")
    assert ais.local_path_for(store, sha("a")) == "/data/a" + P
    assert ais.local_path_for(store, sha("zzz")) is None


def test_browser_rows_import_as_their_own_batch(store):
    rows = [row() | {"image": "a", "sha": sha("a")}, row(2) | {"image": "a"}, row() | {"image": "b"}]
    batch = ais.import_rows(store, rows, 1, "Imported")
    results = ais.list_results(store, batch["id"])
    assert [(r["image"], r["n"]) for r in results] == [("a", 1), ("a", 2), ("b", 1)]
    assert all("dup_of" not in im for im in batch["images"])
