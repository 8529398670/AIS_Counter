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


def test_a_czi_is_a_cell_of_its_own(store):
    batch = ais.create_batch(store, "f", "upload", files(
        ("f/x.czi", "x czi"), ("f/y.CZI", "x czi"), ("f/z.tif", "z raw"),
    ), user_id=1)
    keys = [(im["key"], sorted(im["files"]), im.get("dup_of")) for im in batch["images"]]
    assert keys == [("x", ["czi"], None), ("y", ["czi"], 0), ("z", ["raw"], None)]


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
    # Deleting renumbers the rest of that image (only): "a" is 1..k again.
    assert ais.delete_result(store, first["id"]) == [{"id": second["id"], "n": 1}]
    assert ais.add_result(store, batch["id"], "a", row(), 1)["n"] == 2
    assert ais.get_result(store, other["id"])["n"] == 1
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


def test_origin_is_kept(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    auto = ais.add_result(store, batch["id"], "a", row() | {"origin": "auto"}, 1)
    clicked = ais.add_result(store, batch["id"], "a", row(), 1)
    assert (auto["origin"], clicked["origin"]) == ("auto", "")


def test_delete_closes_the_gap_and_update_keeps_the_number(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    rows = [ais.add_result(store, batch["id"], "a", row(float(k)) | {"origin": "auto"}, 1) for k in range(4)]
    ais.delete_result(store, rows[1]["id"])
    assert [r["n"] for r in ais.list_results(store, batch["id"])] == [1, 2, 3]
    edited = ais.update_result(store, rows[3]["id"], row(9.0), 2)
    assert (edited["n"], edited["origin"], edited["created_by"], edited["length_um"]) == (3, "auto", 1, 9.0)
    assert edited["edited_by"] == 2 and edited["edited_at"]
    assert ais.update_result(store, 999, row(), 1) is None


SOMA = {"soma_um": 4.83, "soma_px": 30.0, "soma_ais_x": 10, "soma_ais_y": 12, "soma_x": 34, "soma_y": 30}


def test_soma_distance_is_set_cleared_and_dropped_by_an_edit(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    first = ais.add_result(store, batch["id"], "a", row(), 1)
    assert first["soma_um"] is None
    measured = ais.set_soma(store, first["id"], SOMA, 2)
    assert {k: measured[k] for k in SOMA} == SOMA
    assert (measured["n"], measured["pixels"], measured["length_um"], measured["soma_by"]) == (1, [[1, 2], [2, 3]], 1.5, 2)
    assert measured["soma_at"]
    cleared = ais.set_soma(store, first["id"], None, 2)
    assert all(cleared[k] is None for k in SOMA) and cleared["soma_at"] is None
    ais.set_soma(store, first["id"], SOMA, 2)
    edited = ais.update_result(store, first["id"], row(2.0), 2)
    assert all(edited[k] is None for k in SOMA) and "soma_at" not in edited
    assert ais.set_soma(store, 999, SOMA, 1) is None


@pytest.mark.parametrize("soma", [SOMA | {"soma_um": "4"}, SOMA | {"soma_x": True}, SOMA | {"soma_px": -1},
                                  {"soma_um": 4.0}, [1, 2]])
def test_soma_distance_must_be_numbers(store, soma):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    first = ais.add_result(store, batch["id"], "a", row(), 1)
    with pytest.raises(ais.BatchError):
        ais.set_soma(store, first["id"], soma, 1)


def test_split_counts_sum_to_n():
    assert ais.split_counts(10, [1, 1, 1]) == [4, 3, 3]
    assert ais.split_counts(30, [66.67, 33.33]) == [20, 10]
    assert ais.split_counts(0, [50, 50]) == [0, 0]
    for n in range(40):
        assert sum(ais.split_counts(n, [17, 33, 50])) == n


def cells(n):
    return files(*[(f"f/c{i:02d}" + P, f"c{i}") for i in range(n)])


def owners(batch):
    images = batch["assignment"]["images"]
    return [images.get(im["key"]) for im in batch["images"]]


def test_assign_deals_contiguous_runs_and_skips_duplicates(store):
    batch = ais.create_batch(store, "f", "upload", cells(6) + files(("f/zz" + P, "c0")), 1)
    batch = ais.assign(store, batch["id"], [{"user_id": 7, "percent": 2}, {"user_id": 8, "percent": 1}], 1)
    assert [s["percent"] for s in batch["assignment"]["shares"]] == [66.67, 33.33]
    assert owners(batch) == [7, 7, 7, 7, 8, 8, None]     # zz is a duplicate of c00
    assert ais.assignee_of(batch, "c04") == 8 and ais.assignee_of(batch, "zz") is None


def test_resplit_keeps_finished_images_with_their_assignee(store):
    batch = ais.create_batch(store, "f", "upload", cells(10), 1)
    ais.assign(store, batch["id"], [{"user_id": 7, "percent": 50}, {"user_id": 8, "percent": 50}], 1)
    for key in ("c05", "c06", "c07"):                     # 8 finishes three of theirs
        ais.add_result(store, batch["id"], key, row(), 8)
    ais.set_done(store, batch["id"], "c00", True)         # and 7 one
    batch = ais.assign(store, batch["id"], [{"user_id": 7, "percent": 20}, {"user_id": 8, "percent": 80}], 1)
    assert owners(batch)[0] == 7 and owners(batch)[5:8] == [8, 8, 8]
    assert owners(batch).count(7) == 2 and owners(batch).count(8) == 8
    # Someone removed: their finished images are left unassigned.
    batch = ais.assign(store, batch["id"], [{"user_id": 7, "percent": 1}], 1)
    assert owners(batch)[5:8] == [None, None, None] and owners(batch).count(7) == 7
    assert ais.assign(store, batch["id"], [], 1).get("assignment") is None


def test_progress_per_assignee(store):
    batch = ais.create_batch(store, "f", "upload", cells(4), 1)
    ais.assign(store, batch["id"], [{"user_id": 7, "percent": 1}, {"user_id": 8, "percent": 1}], 1)
    ais.add_result(store, batch["id"], "c00", row(), 7)
    ais.add_result(store, batch["id"], "c00", row(), 7)
    ais.set_done(store, batch["id"], "c03", True)
    listed = ais.list_batches(store, viewer_id=7)[0]
    by_user = {a["user_id"]: a for a in listed["assignees"]}
    assert (by_user[7]["images"], by_user[7]["completed"], by_user[7]["ais"]) == (2, 1, 2)
    assert (by_user[8]["images"], by_user[8]["completed"], by_user[8]["ais"]) == (2, 1, 0)
    assert by_user[7]["last_at"] and by_user[8]["last_at"] is None
    assert listed["mine"] == by_user[7] and ais.list_batches(store, viewer_id=9)[0]["mine"] is None
    assert listed["completed"] == 2


def test_bad_shares_are_refused(store):
    batch = ais.create_batch(store, "f", "upload", cells(2), 1)
    for shares in ("x", [{"user_id": 7, "percent": 0}], [{"user_id": 7, "percent": 1}, {"user_id": 7, "percent": 1}],
                   [{"user_id": "7", "percent": 1}]):
        with pytest.raises(ais.BatchError):
            ais.assign(store, batch["id"], shares, 1)
    assert ais.assign(store, 999, [], 1) is None


def test_a_batch_can_start_empty_and_take_images_later(store):
    batch = ais.new_batch(store, "  plan  ", "upload", 1)
    assert batch["name"] == "plan" and batch["images"] == []
    assert ais.list_batches(store)[0]["images"] == 0
    with pytest.raises(ais.BatchError):
        ais.add_files(store, batch["id"], "upload", [])
    assert ais.add_files(store, 999, "upload", files(("f/a" + P, "a"))) is None

    added = ais.add_files(store, batch["id"], "upload", files(("f/a" + P, "a"), ("f/b.czi", "b")))
    assert [im["key"] for im in added["images"]] == ["a", "b"]
    again = ais.add_files(store, batch["id"], "path", [
        f | {"path": "/x/" + f["name"]} for f in files(("g/a" + P, "a"), ("g/c.czi", "c"))])
    # a taken already: the new one is "a (2)", and has the first a's bytes.
    assert [(im["key"], im.get("dup_of")) for im in again["images"]] == [
        ("a", None), ("b", None), ("a (2)", 0), ("c", None)]
    assert again["source"] == "mixed"
    assert ais.get_batch(store, batch["id"])["images"] == again["images"]


def test_rename_follows_into_results_and_stamps(store):
    batch = ais.create_batch(store, "old", "upload", files(("f/a" + P, "a")), 1)
    other = ais.create_batch(store, "other", "upload", files(("f/a" + P, "a")), 1)
    ais.add_result(store, batch["id"], "a", row(), 1)
    ais.add_result(store, other["id"], "a", row(), 1)
    renamed = ais.rename_batch(store, batch["id"], "new")
    assert renamed["name"] == "new" and renamed["updated_at"] >= batch["created_at"]
    assert {r["batch_id"]: r["batch_name"] for r in ais.list_results(store)} == {batch["id"]: "new", other["id"]: "other"}
    assert ais.rename_batch(store, 999, "x") is None
    with pytest.raises(ais.BatchError):
        ais.rename_batch(store, batch["id"], "   ")


def test_new_batches_go_on_top_and_the_order_is_shared(store):
    a, b, c = (ais.new_batch(store, name, "upload", 1)["id"] for name in "abc")
    order = lambda: [x["id"] for x in ais.list_batches(store)]
    assert order() == [c, b, a]
    ais.order_batches(store, [a, c, b])
    assert order() == [a, c, b]
    # Unlisted batches follow the listed ones, keeping their order.
    ais.order_batches(store, [b])
    assert order() == [b, a, c]
    d = ais.new_batch(store, "d", "upload", 1)["id"]
    assert order() == [d, b, a, c]
    for bad in ([a, a], ["x"], [True], "nope"):
        with pytest.raises(ais.BatchError):
            ais.order_batches(store, bad)


def test_batches_from_before_the_order_sit_newest_first(store):
    old = [ais.new_batch(store, name, "upload", 1) for name in "ab"]
    for batch in old:
        store.put(db.BUCKET_AIS_BATCHES, batch["id"], {k: v for k, v in batch.items() if k != "position"})
    assert [x["id"] for x in ais.list_batches(store)] == [old[1]["id"], old[0]["id"]]
    fresh = ais.new_batch(store, "c", "upload", 1)["id"]
    assert ais.list_batches(store)[0]["id"] == fresh


def test_archive_and_unarchive_keep_the_results(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    ais.add_result(store, batch["id"], "a", row(), 1)
    archived = ais.archive_batch(store, batch["id"], True)
    assert archived["archived_at"] and ais.list_batches(store)[0]["archived_at"] == archived["archived_at"]
    assert len(ais.list_results(store, batch["id"])) == 1
    assert ais.archive_batch(store, batch["id"], False)["archived_at"] is None
    assert ais.list_batches(store)[0]["archived_at"] is None
    assert ais.archive_batch(store, 999, True) is None


def test_list_and_status_count_uploads_and_states(store):
    batch = ais.create_batch(store, "f", "upload", files(
        ("f/a.tif", "a raw"), ("f/a" + P, "a proc"), ("f/b" + P, "b"), ("f/c" + P, "c")), 1)
    ais.add_result(store, batch["id"], "a", row() | {"origin": "auto"}, 1)
    ais.set_done(store, batch["id"], "b", True)
    on_server = {sha("a raw"), sha("b")}
    has = lambda f: f["sha"] in on_server
    listed = ais.list_batches(store, 1, has)[0]
    assert (listed["files"], listed["stored"], listed["ais"], listed["completed"]) == (4, 2, 1, 2)
    assert "stored" not in ais.list_batches(store)[0]
    status = ais.image_status(ais.get_batch(store, batch["id"]), ais.list_results(store, batch["id"]), has)
    assert [(s["key"], s["files"], s["stored"], s["ais"], s["auto"], s["done"]) for s in status] == [
        ("a", 2, 1, 1, 1, False), ("b", 1, 1, 0, 0, True), ("c", 1, 0, 0, 0, False)]


def test_activity_reports_age_out():
    now = [100.0]
    live = ais.Activity(ttl=60, clock=lambda: now[0])
    live.report(3, 1, {"kind": "auto", "state": "running", "done": 2, "total": 9})
    live.report(3, 1, {"kind": "auto", "state": "running", "done": 3, "total": 9})   # replaces
    live.report(4, 2, {"kind": "auto", "state": "stopped", "done": 1, "total": 2})
    assert [(a["user_id"], a["done"]) for a in live.current()[3]] == [(1, 3)]
    now[0] += 61
    assert live.current() == {}
    for bad in ({"kind": "x", "state": "running", "done": 0, "total": 1},
                {"kind": "auto", "state": "running", "done": 2, "total": 1},
                {"kind": "auto", "state": "running", "done": True, "total": 1}):
        with pytest.raises(ais.BatchError):
            live.report(3, 1, bad)


def test_reset_deletes_all_or_only_auto_and_keeps_images_and_assignment(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a"), ("f/b" + P, "b"), ("f/c" + P, "c")), 1)
    bid = batch["id"]
    ais.assign(store, bid, [{"user_id": 1, "percent": 100}], 1)
    ais.add_result(store, bid, "a", row() | {"origin": "auto"}, 1)
    clicked = ais.add_result(store, bid, "a", row(), 1)
    ais.add_result(store, bid, "b", row(), 1)
    ais.set_done(store, bid, "a", True)
    ais.set_done(store, bid, "c", True)
    with pytest.raises(ais.BatchError):
        ais.reset_batch(store, bid, "some")
    assert ais.reset_batch(store, 999, "all") is None

    after, deleted = ais.reset_batch(store, bid, "auto")
    assert deleted == 1
    left = ais.list_results(store, bid)
    assert sorted((r["image"], r["n"], r["origin"]) for r in left) == [("a", 1, ""), ("b", 1, "")]
    assert next(r for r in left if r["id"] == clicked["id"])["n"] == 1
    assert after["skipped"] == ["c"]   # only the image that had auto AIS is un-marked

    after, deleted = ais.reset_batch(store, bid, "all")
    assert deleted == 2 and ais.list_results(store, bid) == []
    assert after["skipped"] == [] and len(after["images"]) == 3 and after["assignment"]
    assert ais.list_batches(store)[0]["completed"] == 0
