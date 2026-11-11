"""The Batches screen's trash (app/models/ais.py): deleting a batch or folder,
or resetting a batch, puts what went in the trash, and restoring puts it back
exactly; old entries are purged; only the right people may restore."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.core import db
from app.core.db import BUCKET_AIS_TRASH
from app.models import ais, to_iso, users, utc_now
from tests.test_batches import LINE, P, files, row
from tests.test_matlab_routes import Harness


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


def snapshot(store, batch_id):
    return (ais.get_batch(store, batch_id),
            sorted((r["id"], r["image"], r["n"]) for r in ais.list_results(store, batch_id)),
            sorted(m["id"] for m in ais.list_measurements(store, batch_id)))


def worked_batch(store, name="f"):
    batch = ais.create_batch(store, name, "upload", files(("f/a" + P, name + "a"), ("f/b" + P, name + "b")), 1)
    ais.add_result(store, batch["id"], "a", row(), 1)
    ais.add_result(store, batch["id"], "a", row() | {"origin": "auto"}, 1)
    ais.add_result(store, batch["id"], "b", row(), 1)
    ais.add_measurement(store, batch["id"], "a", LINE, 1)
    ais.set_done(store, batch["id"], "a", True)
    return ais.get_batch(store, batch["id"])


def test_a_deleted_batch_comes_back_with_its_ais_and_lines(store):
    batch = worked_batch(store)
    before = snapshot(store, batch["id"])
    trash_id = ais.delete_batch(store, batch["id"], 7)
    assert ais.get_batch(store, batch["id"]) is None and ais.list_results(store, batch["id"]) == []
    [entry] = ais.list_trash(store)
    assert entry["kind"] == "batch" and entry["name"] == "f" and entry["deleted_by"] == 7
    assert (entry["results"], entry["measurements"], entry["images"]) == (3, 1, 2)
    assert ais.restore_trash(store, trash_id)["id"] == trash_id
    assert snapshot(store, batch["id"]) == before
    assert ais.list_trash(store) == []
    assert ais.restore_trash(store, trash_id) is None
    assert ais.delete_batch(store, 999) is None


def test_a_batch_whose_folder_went_comes_back_at_the_top(store):
    folder = ais.create_folder(store, "x", None, 1)
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    ais.move_batches(store, [batch["id"]], folder["id"])
    trash_id = ais.delete_batch(store, batch["id"], 1)
    ais.delete_folder(store, folder["id"], 1)
    ais.restore_trash(store, trash_id)
    assert ais.get_batch(store, batch["id"])["folder_id"] is None


def test_a_deleted_folder_takes_back_what_it_held(store):
    top = ais.create_folder(store, "top", None, 1)
    mid = ais.create_folder(store, "mid", top["id"], 1)
    low = ais.create_folder(store, "low", mid["id"], 1)
    held = ais.create_batch(store, "held", "upload", files(("f/a" + P, "a")), 1)
    moved = ais.create_batch(store, "moved", "upload", files(("f/b" + P, "b")), 1)
    ais.move_batches(store, [held["id"], moved["id"]], mid["id"])
    trash_id = ais.delete_folder(store, mid["id"], 1)["trash_id"]
    # Filed somewhere else since: stays there.
    ais.move_batches(store, [moved["id"]], None)
    ais.restore_trash(store, trash_id)
    folders = {f["id"]: f for f in ais.list_folders(store)}
    assert folders[mid["id"]]["parent_id"] == top["id"]
    assert folders[low["id"]]["parent_id"] == mid["id"]
    assert ais.get_batch(store, held["id"])["folder_id"] == mid["id"]
    assert ais.get_batch(store, moved["id"])["folder_id"] is None


def test_a_reset_comes_back_with_the_numbers_it_had(store):
    batch = worked_batch(store)
    before = snapshot(store, batch["id"])
    _, deleted, trash_id = ais.reset_batch(store, batch["id"], "auto", 1)
    assert deleted == 1
    ais.restore_trash(store, trash_id)
    assert snapshot(store, batch["id"])[1:] == before[1:]
    assert ais.get_batch(store, batch["id"])["skipped"] == ["a"]

    _, deleted, trash_id = ais.reset_batch(store, batch["id"], "all", 1)
    assert deleted == 3 and ais.list_measurements(store, batch["id"]) == []
    ais.restore_trash(store, trash_id)
    assert snapshot(store, batch["id"])[1:] == before[1:]
    assert ais.get_batch(store, batch["id"])["skipped"] == ["a"]


def test_a_reset_with_nothing_to_take_puts_nothing_in_the_trash(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    assert ais.reset_batch(store, batch["id"], "all", 1)[2] is None
    assert ais.list_trash(store) == []


def test_a_reset_of_a_deleted_batch_cannot_come_back_first(store):
    batch = worked_batch(store)
    reset_id = ais.reset_batch(store, batch["id"], "auto", 1)[2]
    batch_id = ais.delete_batch(store, batch["id"], 1)
    with pytest.raises(ais.BatchError):
        ais.restore_trash(store, reset_id)
    ais.restore_trash(store, batch_id)
    ais.restore_trash(store, reset_id)
    assert len(ais.list_results(store, batch["id"])) == 3


def test_old_entries_are_purged_and_purge_deletes_for_good(store):
    old = ais.delete_batch(store, worked_batch(store, "old")["id"], 1)
    new = ais.delete_batch(store, worked_batch(store, "new")["id"], 1)
    store.update_value(BUCKET_AIS_TRASH, old, lambda e: e.update(
        deleted_at=to_iso(utc_now() - timedelta(days=ais.TRASH_DAYS, seconds=1))))
    assert ais.purge_old_trash(store) == 1
    assert [e["id"] for e in ais.list_trash(store)] == [new]
    assert ais.purge_trash(store, new) and not ais.purge_trash(store, new)
    assert ais.list_trash(store) == []


# --- the routes ----------------------------------------------------------------------


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def call(h, method, path, who, **body):
    response = h.get(method, path, session=who, body=body if method == "POST" else None)
    return response.status, json.loads(response.data) if response.data else None


def test_who_may_restore_and_purge(h):
    admin, ann, bob = h.user("Root", role=users.ROLE_ADMIN), h.user("Ann"), h.user("Bob")
    batch = ais.create_batch(h.store, "B", "upload", files(("f/a" + P, "a")), ann.id)
    status, out = call(h, "POST", f"/api/ais/batches/{batch['id']}/delete", ann)
    assert status == 200 and out["trash_id"]
    status, listed = call(h, "GET", "/api/ais/trash", bob)
    assert status == 200 and listed["days"] == ais.TRASH_DAYS
    [entry] = listed["entries"]
    assert entry["deleted_by_name"] == "Ann" and entry["can_restore"] is False
    assert call(h, "GET", "/api/ais/trash", ann)[1]["entries"][0]["can_restore"] is True
    assert call(h, "POST", f"/api/ais/trash/{out['trash_id']}/restore", bob)[0] == 403
    assert call(h, "POST", f"/api/ais/trash/{out['trash_id']}/purge", ann)[0] == 403
    assert call(h, "POST", f"/api/ais/trash/{out['trash_id']}/restore", ann)[0] == 200
    assert ais.get_batch(h.store, batch["id"])["name"] == "B"
    assert call(h, "POST", f"/api/ais/trash/{out['trash_id']}/restore", ann)[0] == 404

    folder = ais.create_folder(h.store, "F", None, admin.id)
    status, out = call(h, "POST", f"/api/ais/folders/{folder['id']}/delete", admin)
    assert status == 200
    assert call(h, "POST", f"/api/ais/trash/{out['trash_id']}/restore", ann)[0] == 403
    assert call(h, "POST", f"/api/ais/trash/{out['trash_id']}/purge", admin)[0] == 200
    assert call(h, "GET", "/api/ais/trash", admin)[1]["entries"] == []
