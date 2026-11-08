"""The Batches screen's nested folders (app/models/ais.py) and their routes."""
from __future__ import annotations

import hashlib
import json

import pytest

from app.core import db
from app.models import ais, users
from tests.test_matlab_routes import Harness

P = ".tif - Processed method 2.5.tif"


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


def batch(store, name, folder_id=None):
    sha = hashlib.sha256(name.encode()).hexdigest()
    record = ais.create_batch(store, name, "upload", [{"name": "a" + P, "rel": name + "/a" + P, "sha": sha, "size": 1}],
                              user_id=1)
    if folder_id is not None:
        ais.move_batches(store, [record["id"]], folder_id)
    return record


def tree(store):
    return [(f["name"], f["parent_id"]) for f in ais.list_folders(store)]


def folder_of(store):
    return {b["name"]: b["folder_id"] for b in ais.list_batches(store)}


def test_folders_nest_and_new_ones_go_first(store):
    year = ais.create_folder(store, "2026", None, 1)
    old = ais.create_folder(store, "2025", None, 1)
    c4 = ais.create_folder(store, " C4 ", year["id"], 1)
    assert c4["name"] == "C4" and c4["parent_id"] == year["id"]
    assert tree(store) == [("2025", None), ("2026", None), ("C4", year["id"])]
    assert ais.rename_folder(store, old["id"], "Old")["name"] == "Old"
    assert ais.rename_folder(store, 999, "x") is None
    with pytest.raises(ais.BatchError):
        ais.create_folder(store, "", None, 1)
    with pytest.raises(ais.BatchError):
        ais.create_folder(store, "x", 999, 1)


def test_batches_without_a_folder_sit_at_the_top_and_can_be_filed(store):
    a, b = batch(store, "A"), batch(store, "B")
    assert "folder_id" not in ais.get_batch(store, a["id"])
    f = ais.create_folder(store, "F", None, 1)
    assert ais.move_batches(store, [a["id"], 12345], f["id"]) == 1
    assert folder_of(store) == {"A": f["id"], "B": None}
    assert ais.move_batches(store, [a["id"]], None) == 1
    assert folder_of(store) == {"A": None, "B": None}
    with pytest.raises(ais.BatchError):
        ais.move_batches(store, [b["id"]], 999)
    with pytest.raises(ais.BatchError):
        ais.move_batches(store, [], f["id"])
    made = ais.new_batch(store, "C", "upload", 1, folder_id=f["id"])
    assert made["folder_id"] == f["id"]
    with pytest.raises(ais.BatchError):
        ais.new_batch(store, "D", "upload", 1, folder_id=999)


def test_a_folder_cannot_go_inside_itself_or_too_deep(store):
    a = ais.create_folder(store, "a", None, 1)
    b = ais.create_folder(store, "b", a["id"], 1)
    c = ais.create_folder(store, "c", b["id"], 1)
    for into in (a["id"], b["id"], c["id"]):
        with pytest.raises(ais.BatchError):
            ais.move_folder(store, a["id"], into)
    assert ais.move_folder(store, c["id"], None)["parent_id"] is None
    assert ais.move_folder(store, 999, None) is None
    chain = [ais.create_folder(store, "0", None, 1)]
    for n in range(1, ais.MAX_FOLDER_DEPTH):
        chain.append(ais.create_folder(store, str(n), chain[-1]["id"], 1))
    with pytest.raises(ais.BatchError):
        ais.create_folder(store, "too deep", chain[-1]["id"], 1)
    with pytest.raises(ais.BatchError):
        ais.move_folder(store, a["id"], chain[-2]["id"])   # a has b under it: one too many


def test_deleting_a_folder_moves_what_was_in_it_up(store):
    top = ais.create_folder(store, "top", None, 1)
    mid = ais.create_folder(store, "mid", top["id"], 1)
    low = ais.create_folder(store, "low", mid["id"], 1)
    batch(store, "in mid", mid["id"])
    batch(store, "in low", low["id"])
    assert ais.delete_folder(store, mid["id"])["name"] == "mid"
    assert tree(store) == [("top", None), ("low", top["id"])]
    assert folder_of(store) == {"in mid": top["id"], "in low": low["id"]}
    ais.delete_folder(store, top["id"])
    assert tree(store) == [("low", None)]
    assert folder_of(store) == {"in mid": None, "in low": low["id"]}
    assert ais.delete_folder(store, top["id"]) is None
    assert len(ais.list_batches(store)) == 2


def test_folders_keep_an_order_per_parent(store):
    a = ais.create_folder(store, "a", None, 1)
    b = ais.create_folder(store, "b", None, 1)
    c = ais.create_folder(store, "c", None, 1)
    inner = ais.create_folder(store, "inner", a["id"], 1)
    ais.order_folders(store, None, [a["id"]])
    assert [n for n, p in tree(store) if p is None] == ["a", "c", "b"]
    assert tree(store)[-1] == ("inner", a["id"])
    ais.order_folders(store, a["id"], [inner["id"]])
    with pytest.raises(ais.BatchError):
        ais.order_folders(store, None, [a["id"], a["id"]])
    with pytest.raises(ais.BatchError):
        ais.order_folders(store, None, "x")
    # Moved in, it goes last.
    ais.move_folder(store, b["id"], a["id"])
    assert [n for n, p in tree(store) if p == a["id"]] == ["inner", "b"]
    assert c["id"]


# --- the routes ----------------------------------------------------------------------


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def call(h, method, path, who, **body):
    response = h.get(method, path, session=who, body=body if method == "POST" else None)
    return response.status, json.loads(response.data) if response.data else None


def test_everyone_sees_folders_and_only_admins_change_them(h):
    admin, ann = h.user("Root", role=users.ROLE_ADMIN), h.user("Ann")
    b = batch(h.store, "B")
    assert call(h, "POST", "/api/ais/folders", ann, name="x", parent_id=None)[0] == 403
    status, f = call(h, "POST", "/api/ais/folders", admin, name="2026", parent_id=None)
    assert status == 200 and f["name"] == "2026"
    status, sub = call(h, "POST", "/api/ais/folders", admin, name="C4", parent_id=f["id"])
    assert status == 200
    assert call(h, "POST", "/api/ais/folders", admin, name="x", parent_id=999)[0] == 400
    for path, body in ((f"/api/ais/folders/{f['id']}/rename", {"name": "y"}),
                       (f"/api/ais/folders/{sub['id']}/move", {"parent_id": None}),
                       (f"/api/ais/folders/{f['id']}/delete", {}),
                       ("/api/ais/folders/order", {"parent_id": None, "ids": [f["id"]]}),
                       ("/api/ais/batches/move", {"ids": [b["id"]], "folder_id": f["id"]})):
        assert call(h, "POST", path, ann, **body)[0] == 403
    assert call(h, "POST", "/api/ais/batches/move", admin, ids=[b["id"]], folder_id=sub["id"]) == (200, {"moved": 1})
    status, listed = call(h, "GET", "/api/ais/batches", ann)
    assert status == 200 and [x["name"] for x in listed["folders"]] == ["2026", "C4"]
    assert listed["batches"][0]["folder_id"] == sub["id"]
    assert call(h, "GET", "/api/ais/folders", ann)[1]["folders"] == listed["folders"]
    assert call(h, "POST", f"/api/ais/folders/{f['id']}/rename", admin, name="Y")[1]["name"] == "Y"
    assert call(h, "POST", f"/api/ais/folders/{f['id']}/move", admin, parent_id=sub["id"])[0] == 400
    assert call(h, "POST", "/api/ais/folders/999/rename", admin, name="Y")[0] == 404
    assert call(h, "POST", f"/api/ais/folders/{sub['id']}/delete", admin) == (200, {"ok": True})
    assert call(h, "POST", f"/api/ais/folders/{sub['id']}/delete", admin)[0] == 404
    assert call(h, "GET", "/api/ais/batches", ann)[1]["batches"][0]["folder_id"] == f["id"]
    # A batch made while a folder shows lands in it, for anyone who can make one.
    status, made = call(h, "POST", "/api/ais/batches", ann, name="New", folder_id=f["id"])
    assert status == 200 and made["folder_id"] == f["id"]
    assert call(h, "POST", "/api/ais/batches", ann, name="New", folder_id=999)[0] == 400
