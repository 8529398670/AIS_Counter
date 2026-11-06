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


# --- blinded names, adds and the team's inclusion --------------------------------


def test_randomize_blinds_cells_keeps_pairs_and_zen_endings_and_skips_blinded_ones(store):
    batch = ais.new_batch(store, "f", "upload", 1)
    added = ais.add_files(store, batch["id"], "upload", files(
        ("f/DOSE A_c2_ORG.tif", "a raw"), ("f/DOSE A_c2_ORG" + P, "a proc"),
        ("f/DOSE B.czi", "b"),
        ("f/19891-24785-20711.czi", "c"),
    ), randomize_names=True, user_id=1, name="f")
    by_original = {im.get("original_key", im["key"]): im for im in added["images"]}
    pair, czi, kept = by_original["DOSE A_c2_ORG"], by_original["DOSE B"], by_original["19891-24785-20711"]
    assert ais.RANDOM_RE.match(pair["cell"]) and pair["cell"].endswith("_c2_ORG")
    assert pair["files"]["raw"]["name"] == pair["cell"] + ".tif"
    assert pair["files"]["processed"]["name"] == pair["cell"] + P
    assert pair["files"]["processed"]["rel"] == "f/" + pair["cell"] + P
    assert pair["files"]["raw"]["original"] == {"name": "DOSE A_c2_ORG.tif", "rel": "f/DOSE A_c2_ORG.tif"}
    assert ais.RANDOM_RE.match(czi["key"]) and czi["original_cell"] == "DOSE B"
    assert "original_key" not in kept and "original" not in kept["files"]["czi"]
    assert all(0 <= int(n) < 32768 for n in czi["cell"].split("-"))
    # In the order of the new names, so the old order gives nothing away.
    assert [im["key"] for im in added["images"]] == sorted(im["key"] for im in added["images"])

    text = ais.translation(added)
    assert text.startswith("Original Name/Random Name\r\n-------------------------\r\n")
    assert f"DOSE B.czi/{czi['cell']}.czi\r\n" in text and "19891" not in text.split("\r\n", 2)[2].split("/")[0]


def test_randomize_keeps_new_names_unique(store, monkeypatch):
    draws = iter([1, 2, 3, 1, 2, 3, 4, 5, 6])
    monkeypatch.setattr(ais.secrets, "randbelow", lambda n: next(draws))
    batch = ais.create_batch(store, "f", "upload", files(("f/a.czi", "a"), ("f/b.czi", "b")), 1, randomize_names=True)
    assert sorted(im["key"] for im in batch["images"]) == ["1-2-3", "4-5-6"]


def test_each_add_is_recorded_with_its_images(store):
    batch = ais.new_batch(store, "f", "upload", 1)
    ais.add_files(store, batch["id"], "upload", files(("one/a.czi", "a")), user_id=1, name="one")
    later = ais.add_files(store, batch["id"], "path", [
        {"name": "b.czi", "rel": "two/b.czi", "sha": sha("b"), "size": 2, "path": "/two/b.czi",
         "modified": "2024-01-02T00:00:00+00:00", "created": "2024-01-01T00:00:00+00:00"},
    ], "/two", user_id=2, name="two")
    assert [(a["id"], a["name"], a["source"], a["added_by"], a["count"], a["randomized"]) for a in later["adds"]] == [
        (1, "one", "upload", 1, 1, False), (2, "two", "path", 2, 1, False)]
    assert [im["add_id"] for im in later["images"]] == [1, 2]
    assert later["images"][1]["files"]["czi"]["modified"] == "2024-01-02T00:00:00+00:00"
    listed = ais.list_batches(store)[0]
    assert [a["name"] for a in listed["adds"]] == ["one", "two"] and listed["earlier"] == 0
    with pytest.raises(ais.BatchError):
        ais.add_files(store, batch["id"], "upload", [{"name": "c.czi", "sha": sha("c"), "modified": 5}])


def test_excluded_images_are_left_out_of_counts_and_assignment_and_duplicates_start_out(store):
    batch = ais.create_batch(store, "f", "upload", files(
        ("f/a" + P, "a"), ("f/b" + P, "b"), ("f/c" + P, "c"), ("f/d" + P, "a")), 1)
    bid = batch["id"]
    assert batch["excluded"] == ["d"]                          # a duplicate of a
    ais.set_done(store, bid, "c", True)
    after = ais.set_included(store, bid, ["c", "nope"], False)
    assert after["excluded"] == ["c", "d"]
    listed = ais.list_batches(store)[0]
    assert (listed["images"], listed["included"], listed["completed"]) == (4, 2, 0)
    ais.assign(store, bid, [{"user_id": 1, "percent": 100}], 1)
    assert sorted(ais.get_batch(store, bid)["assignment"]["images"]) == ["a", "b"]
    status = {s["key"]: s["included"] for s in ais.image_status(ais.get_batch(store, bid), [], lambda f: True)}
    assert status == {"a": True, "b": True, "c": False, "d": False}
    assert ais.set_included(store, bid, ["d"], True)["excluded"] == ["c"]
    with pytest.raises(ais.BatchError):
        ais.set_included(store, bid, "c", True)
    with pytest.raises(ais.BatchError):
        ais.set_included(store, bid, ["c"], "yes")
    assert ais.set_included(store, 999, ["c"], True) is None


def test_a_batch_from_before_inclusion_leaves_its_duplicates_out(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a"), ("f/b" + P, "a")), 1)
    legacy = {k: v for k, v in batch.items() if k not in ("excluded", "adds")}
    legacy["images"] = [{k: v for k, v in im.items() if k != "add_id"} for im in legacy["images"]]
    store.put(db.BUCKET_AIS_BATCHES, batch["id"], legacy)
    assert ais.excluded_keys(legacy) == {"b"}
    listed = ais.list_batches(store)[0]
    assert listed["included"] == 1 and listed["earlier"] == 2 and listed["adds"] == []
    added = ais.add_files(store, batch["id"], "upload", files(("g/c" + P, "c")), user_id=1, name="g")
    assert added["excluded"] == ["b"] and added["adds"][0]["id"] == 1


def test_originals_are_only_for_admins():
    from app.routes import ais as routes

    blinded = {"name": "1-2-3.czi", "rel": "f/1-2-3.czi", "sha": sha("x"), "path": "/f/DOSE.czi",
               "original": {"name": "DOSE.czi", "rel": "f/DOSE.czi"}}
    assert routes._unnamed_file(blinded) == {"name": "1-2-3.czi", "rel": "f/1-2-3.czi", "sha": sha("x")}
    plain = {"name": "a.czi", "rel": "f/a.czi", "sha": sha("a"), "path": "/f/a.czi"}
    assert routes._unnamed_file(plain) == plain
    assert routes._unnamed_image({"key": "1-2-3", "original_key": "DOSE", "original_cell": "DOSE"}) == {"key": "1-2-3"}


def test_rerandomize_renames_one_folder_and_everything_that_names_its_images(store):
    batch = ais.new_batch(store, "f", "upload", 1)
    bid = batch["id"]
    ais.add_files(store, bid, "upload", files(("one/DOSE A_c2_ORG.tif", "a raw"), ("one/DOSE A_c2_ORG" + P, "a proc"),
                                              ("one/DOSE B.czi", "b"), ("one/DOSE C.czi", "b")),
                  randomize_names=True, user_id=1, name="one")
    other = ais.add_files(store, bid, "upload", files(("two/plain.czi", "p")), user_id=1, name="two")
    by_original = {im.get("original_key"): im for im in other["images"]}
    pair = by_original["DOSE A_c2_ORG"]
    dup = next(im for im in other["images"] if "dup_of" in im)          # DOSE B or C, whichever sorts later
    czi = next(im for im in other["images"] if im.get("original_key") in ("DOSE B", "DOSE C") and "dup_of" not in im)
    ais.assign(store, bid, [{"user_id": 1, "percent": 100}], 1)
    row_ = ais.add_result(store, bid, pair["key"], row() | {"file": pair["files"]["processed"]["rel"]}, 1)
    ais.set_done(store, bid, czi["key"], True)
    before = ais.list_batches(store)[0]

    after, renamed, measured = ais.rerandomize(store, bid, 1)
    assert (renamed, measured) == (3, 2)
    moved = {im.get("original_key"): im for im in after["images"]}
    new_pair, new_czi, new_dup = moved["DOSE A_c2_ORG"], moved[czi["original_key"]], moved[dup["original_key"]]
    assert new_pair["key"] != pair["key"] and new_pair["cell"].endswith("_c2_ORG")
    assert new_pair["files"]["processed"]["name"] == new_pair["cell"] + P
    assert new_pair["files"]["raw"]["original"] == {"name": "DOSE A_c2_ORG.tif", "rel": "one/DOSE A_c2_ORG.tif"}
    assert new_pair["files"]["raw"]["earlier"] == [pair["files"]["raw"]["name"]]
    assert new_pair["earlier_keys"] == [pair["key"]]
    assert moved[None]["key"] == "plain"                              # the other folder is untouched
    assert [im["add_id"] for im in after["images"]] == [im["add_id"] for im in other["images"]]

    result = ais.get_result(store, row_["id"])
    assert (result["image"], result["cell"], result["n"]) == (new_pair["key"], new_pair["cell"], 1)
    assert result["file"] == new_pair["files"]["processed"]["rel"]
    assert after["skipped"] == [new_czi["key"]]
    assert after["excluded"] == [new_dup["key"]]
    assert set(after["assignment"]["images"]) == {new_pair["key"], new_czi["key"], "plain"}
    now = ais.list_batches(store)[0]
    assert {k: now[k] for k in ("images", "included", "completed", "ais")} == {k: before[k] for k in ("images", "included", "completed", "ais")}
    assert [a["randomized"] for a in now["adds"]] == [True, False]

    again, _, _ = ais.rerandomize(store, bid, 1)
    twice = next(im for im in again["images"] if im.get("original_key") == czi["original_key"])
    assert twice["files"]["czi"]["original"]["name"] == czi["original_key"] + ".czi"
    assert twice["earlier_keys"] == [czi["key"], new_czi["key"]]
    text = ais.translation(again)
    assert f"{czi['original_key']}.czi/{twice['cell']}.czi\r\n" in text
    assert "\r\n\r\nEarlier Random Name/Random Name\r\n" in text
    assert f"{czi['cell']}.czi/{twice['cell']}.czi\r\n" in text and f"{new_czi['cell']}.czi/{twice['cell']}.czi\r\n" in text


def test_rerandomize_blinds_an_unblinded_folder_and_earlier_images(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a.czi", "a"), ("f/19891-24785-20711.czi", "b")), 1)
    legacy = batch | {"adds": []}
    legacy["images"] = [{k: v for k, v in im.items() if k != "add_id"} for im in batch["images"]]
    store.put(db.BUCKET_AIS_BATCHES, batch["id"], legacy)
    after, renamed, measured = ais.rerandomize(store, batch["id"], "earlier")
    assert (renamed, measured) == (2, 0)
    originals = sorted(im["original_key"] for im in after["images"])
    assert originals == ["19891-24785-20711", "a"]
    assert all(ais.RANDOM_RE.match(im["key"]) and "earlier_keys" not in im for im in after["images"])
    assert ais.rerandomize(store, 999, 1) is None
    for bad in (7, True, "x"):
        with pytest.raises(ais.BatchError):
            ais.rerandomize(store, batch["id"], bad)


def test_earlier_random_names_are_only_for_admins():
    from app.routes import ais as routes

    f = {"name": "4-5-6.czi", "rel": "f/4-5-6.czi", "sha": sha("x"), "earlier": ["1-2-3.czi"],
         "original": {"name": "DOSE.czi", "rel": "f/DOSE.czi"}}
    assert "earlier" not in routes._unnamed_file(f)
    assert routes._unnamed_image({"key": "4-5-6", "earlier_keys": ["1-2-3"]}) == {"key": "4-5-6"}


# --- names given by a __Translation.txt from RandomNames.bat ---------------------

BAT = "Original Name/Random Name \r\n------------------------- \r\nDOSE A.czi/1-2-3.czi\r\nDOSE B.tif/4-5-6.tif\r\n"


def test_a_translation_reads_like_the_bat_wrote_it_and_like_ours():
    assert ais.parse_translation("﻿" + BAT) == {"1-2-3.czi": "DOSE A.czi", "4-5-6.tif": "DOSE B.tif"}
    ours = "Original Name/Random Name\r\n---\r\nA.czi/7-8-9.czi\r\n\r\nEarlier Random Name/Random Name\r\n---\r\n1-1-1.czi/7-8-9.czi\r\n"
    assert ais.parse_translation(ours) == {"7-8-9.czi": "A.czi"}
    for bad in ("Original Name/Random Name\n----\n", "", None, 5):
        with pytest.raises(ais.BatchError):
            ais.parse_translation(bad)


def test_an_upload_with_its_translation_keeps_the_original_names(store):
    batch = ais.create_batch(store, "f", "upload", files(
        ("f/1-2-3.czi", "a"),
        ("f/4-5-6.tif", "b raw"), ("f/4-5-6" + P, "b proc"),
        ("f/sub/1-2-3.czi", "c"),                            # same random name, another folder
        ("f/7-7-7.czi", "d"),                                # not in the translation
    ), 1, randomize_names=True, translations=[
        {"dir": "", "text": BAT}, {"dir": "sub", "text": "Original Name/Random Name\n---\nDOSE C.czi/1-2-3.czi\n"}])
    by_key = {im["key"]: im for im in batch["images"]}
    assert set(by_key) == {"1-2-3", "4-5-6", "sub/1-2-3", "7-7-7"}    # randomize kept the names
    assert (by_key["1-2-3"]["original_cell"], by_key["1-2-3"]["original_key"]) == ("DOSE A", "DOSE A")
    assert by_key["sub/1-2-3"]["original_key"] == "sub/DOSE C"
    pair = by_key["4-5-6"]
    assert pair["original_cell"] == "DOSE B"
    assert pair["files"]["raw"]["original"] == {"name": "DOSE B.tif", "rel": "f/DOSE B.tif"}
    assert "original" not in pair["files"]["processed"]               # the .bat named only the raw file
    assert "original_cell" not in by_key["7-7-7"]
    assert batch["adds"][0]["randomized"] is True
    listed = ais.list_batches(store)[0]
    assert listed["randomized"] and listed["unnamed"] == 1
    assert "DOSE A.czi/1-2-3.czi\r\n" in ais.translation(batch)
    with pytest.raises(ais.BatchError):
        ais.create_batch(store, "f", "upload", files(("f/a.czi", "a")), 1, translations="nope")


def test_a_translation_loaded_later_names_the_images_it_knows(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/1-2-3.czi", "a"), ("f/4-5-6.tif", "b"), ("f/9-9-9.czi", "c")), 1)
    bid = batch["id"]
    ais.add_result(store, bid, "1-2-3", row(), 1)
    assert ais.list_batches(store)[0]["unnamed"] == 3 and not batch["adds"][0]["randomized"]
    after, named, left = ais.apply_translation(store, bid, BAT)
    assert (named, left) == (2, 1)
    assert [im["key"] for im in after["images"]] == ["1-2-3", "4-5-6", "9-9-9"]   # keys stay
    assert {im["key"]: im.get("original_key") for im in after["images"]} == {"1-2-3": "DOSE A", "4-5-6": "DOSE B", "9-9-9": None}
    assert after["adds"][0]["randomized"] is True
    assert ais.list_results(store, bid)[0]["image"] == "1-2-3"
    # Loaded again: what was named stays as it was.
    _, again, _ = ais.apply_translation(store, bid, BAT.replace("DOSE A", "OTHER"))
    assert again == 0 and ais.get_batch(store, bid)["images"][0]["original_cell"] == "DOSE A"
    assert ais.apply_translation(store, 999, BAT) is None


def test_a_server_folder_finds_its_translations(tmp_path):
    from app.analysis import local

    (tmp_path / "sub").mkdir()
    (tmp_path / "__Translation.txt").write_text(BAT)
    (tmp_path / "sub" / "__translation.TXT").write_bytes("Original Name/Random Name\r\n---\r\nDOSÉ.czi/1-2-3.czi\r\n".encode("cp1252"))
    (tmp_path / "notes.txt").write_text("x")
    found = sorted(local.translations_under(str(tmp_path)), key=lambda t: t["dir"])
    assert [t["dir"] for t in found] == ["", "sub"]
    assert ais.parse_translation(found[1]["text"]) == {"1-2-3.czi": "DOSÉ.czi"}


def test_the_export_dialog_lists_the_channels_of_stored_included_czis(store, tmp_path):
    import numpy as np

    from app.analysis.service import Library
    from app.routes.ais import _batch_channels
    from tests.czidata import write_czi

    plane = np.arange(24 * 32, dtype=np.uint16).reshape(24, 32)
    library = Library(tmp_path)
    both = write_czi({"Alexa Fluor 488": plane, "AMCA": plane + 1})
    other = write_czi({"Alexa Fluor 594": plane, "AMCA": plane + 2})
    left_out = write_czi({"Cy5": plane})

    def entry(rel, data):
        return {"name": rel.split("/")[-1], "rel": rel, "sha": library.add(data)["sha256"], "size": len(data)}

    batch = ais.create_batch(store, "c", "upload", [
        entry("c/a.czi", both), entry("c/b.czi", other), entry("c/out.czi", left_out),
        {"name": "gone.czi", "rel": "c/gone.czi", "sha": sha("gone"), "size": 1},
        {"name": "t.tif", "rel": "c/t.tif", "sha": sha("t"), "size": 1},
    ], user_id=1)
    batch["excluded"] = ["out"]
    # A file known at a path elsewhere is not fetched in to list it.
    asked = []
    library.resolver = lambda digest: asked.append(digest)

    out = _batch_channels(library, batch)
    assert [(c["name"], c["files"]) for c in out["channels"]] == [("Alexa Fluor 488", 1), ("AMCA", 2), ("Alexa Fluor 594", 1)]
    assert (out["czis"], out["unread"]) == (3, 1)
    assert not asked


# --- backups -------------------------------------------------------------------


def backup_of(store, batch_id, names=None):
    backup = ais.backup_batch(store, batch_id)
    return {"format": ais.BACKUP_FORMAT, "version": ais.BACKUP_VERSION, "users": names or {"1": "Ann"}, **backup}


def blinded_batch(store):
    batch = ais.create_batch(store, "b", "upload", files(("f/a.tif", "a"), ("f/a" + P, "ap"), ("f/b.tif", "b")), 1,
                             randomize_names=True)
    first, second = (im["key"] for im in batch["images"])
    row = {"length_um": 3.5, "pixels": [[1, 2], [3, 4]], "origin": "auto"}
    ais.add_result(store, batch["id"], first, row, 1)
    kept = ais.add_result(store, batch["id"], first, row, 1)
    ais.update_result(store, kept["id"], row | {"length_um": 4.5}, 1)
    ais.set_soma(store, kept["id"], dict.fromkeys(ais.SOMA_NUMBERS, 2.0), 1)
    ais.set_included(store, batch["id"], [second], False)
    return ais.get_batch(store, batch["id"])


def test_a_deleted_batch_comes_back_from_its_backup_as_it_was(store):
    batch = blinded_batch(store)
    rows = ais.list_results(store, batch["id"])
    backup = backup_of(store, batch["id"])
    ais.delete_batch(store, batch["id"])

    back = ais.import_batch(store, backup, {1: "Ann"}, 1)

    assert back["id"] != batch["id"] and back["name"] == "b"
    for k in ("images", "adds", "excluded", "skipped", "created_at", "created_by"):
        assert back[k] == batch[k], k
    assert "original_cell" in back["images"][0]
    assert "original" in back["images"][0]["files"]["raw"]
    moved = ("id", "batch_id")
    again = ais.list_results(store, back["id"])
    assert [{k: v for k, v in r.items() if k not in moved} for r in again] == \
           [{k: v for k, v in r.items() if k not in moved} for r in rows]
    assert again[1]["pixels"] == [[1, 2], [3, 4]] and again[1]["n"] == 2 and again[1]["edited_by"] == 1


def test_a_backup_cannot_point_at_this_machine(store):
    batch = ais.create_batch(store, "p", "path", [f | {"path": "/secret/a.tif"} for f in files(("f/a.tif", "a"))], 1,
                             path="/secret")
    backup = backup_of(store, batch["id"])
    assert "/secret" not in str(backup)
    backup["batch"]["source"] = "path"
    backup["batch"]["path"] = "/etc"
    backup["batch"]["images"][0]["files"]["raw"]["path"] = "/etc/passwd"
    backup["batch"]["adds"][0]["path"] = "/etc"
    back = ais.import_batch(store, backup, {}, 1)
    assert back["source"] == "upload" and back["path"] is None
    assert "path" not in back["images"][0]["files"]["raw"]
    assert back["adds"][0]["path"] is None and back["adds"][0]["source"] == "upload"
    assert ais.local_path_for(store, back["images"][0]["files"]["raw"]["sha"]) == "/secret/a.tif"   # the first batch's


@pytest.mark.parametrize("rel", ["../a.tif", "f/../../a.tif", "/etc/a.tif", "f\\..\\a.tif"])
def test_a_backup_cannot_climb_out_of_its_folder(store, rel):
    batch = ais.create_batch(store, "r", "upload", files(("f/a.tif", "a")), 1)
    backup = backup_of(store, batch["id"])
    backup["batch"]["images"][0]["files"]["raw"]["rel"] = rel
    with pytest.raises(ais.BatchError):
        ais.import_batch(store, backup, {}, 1)


def test_a_bad_backup_writes_nothing(store):
    batch = blinded_batch(store)
    backup = backup_of(store, batch["id"])
    backup["results"][-1]["image"] = "nobody"
    before = len(ais.list_batches(store)), len(ais.list_results(store))
    with pytest.raises(ais.BatchError):
        ais.import_batch(store, backup, {}, 1)
    assert (len(ais.list_batches(store)), len(ais.list_results(store))) == before


@pytest.mark.parametrize("change", [{"format": "report"}, {"version": 2}, {"batch": None}, {"results": None}])
def test_only_a_backup_of_this_version_imports(store, change):
    batch = ais.create_batch(store, "v", "upload", files(("f/a.tif", "a")), 1)
    with pytest.raises(ais.BatchError):
        ais.import_batch(store, backup_of(store, batch["id"]) | change, {}, 1)


def test_importing_twice_makes_two_batches_and_touches_neither_original(store):
    batch = blinded_batch(store)
    backup = backup_of(store, batch["id"])
    one = ais.import_batch(store, backup, {1: "Ann"}, 1)
    two = ais.import_batch(store, backup, {1: "Ann"}, 1)
    assert len({batch["id"], one["id"], two["id"]}) == 3
    assert one["name"] == two["name"] == "b (imported)"
    assert ais.get_batch(store, batch["id"]) == batch
    assert two["position"] < one["position"] < batch["position"]
    assert len(ais.list_results(store, batch["id"])) == len(ais.list_results(store, two["id"])) == 2


def test_imported_work_stays_with_people_of_the_same_name(store):
    batch = ais.create_batch(store, "u", "upload", files(("f/a.tif", "a"), ("f/b.tif", "b")), 7)
    first, second = (im["key"] for im in batch["images"])
    ais.add_result(store, batch["id"], first, {}, 7)
    ais.add_result(store, batch["id"], second, {}, 8)
    backup = backup_of(store, batch["id"], {"7": "Ann", "8": "Gone"})
    back = ais.import_batch(store, backup, {3: "Ann", 4: "Admin"}, 4)
    assert back["created_by"] == 3
    assert [r["created_by"] for r in ais.list_results(store, back["id"])] == [3, 4]


def test_a_backup_leaves_the_assignment_and_names_only_who_it_mentions(store):
    batch = ais.create_batch(store, "a", "upload", files(("f/a.tif", "a")), 7)
    ais.add_result(store, batch["id"], batch["images"][0]["key"], {}, 8)
    ais.assign(store, batch["id"], [{"user_id": 9, "percent": 100}], 7)
    backup = ais.backup_batch(store, batch["id"])
    assert "assignment" not in backup["batch"]
    assert ais.backup_user_ids(backup) == {7, 8}


# --- recorded measurements -----------------------------------------------------


LINE = {"a_x": 10, "a_y": 12, "b_x": 40, "b_y": 52, "length_px": 50.0, "length_um": 8.05, "pixconv": 0.161}


def test_measurements_are_numbered_per_image_and_renumbered_on_delete(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a"), ("f/b" + P, "b")), 1)
    first = ais.add_measurement(store, batch["id"], "a", LINE, 1)
    second = ais.add_measurement(store, batch["id"], "a", LINE | {"label": "soma"}, 1)
    other = ais.add_measurement(store, batch["id"], "b", LINE, 2)
    assert [(m["image"], m["n"], m["label"]) for m in (first, second, other)] == [("a", 1, ""), ("a", 2, "soma"), ("b", 1, "")]
    assert (first["batch_name"], other["created_by"]) == ("f", 2) and first["created_at"]
    assert ais.delete_measurement(store, first["id"]) == [{"id": second["id"], "n": 1}]
    assert [m["id"] for m in ais.list_measurements(store, batch["id"])] == [second["id"], other["id"]]
    assert ais.delete_measurement(store, 999) == []


def test_a_measurement_update_keeps_its_place_and_who_recorded_it(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    line = ais.add_measurement(store, batch["id"], "a", LINE, 1)
    moved = ais.update_measurement(store, line["id"], LINE | {"b_x": 20, "label": "width"}, 2)
    assert (moved["id"], moved["n"], moved["image"], moved["created_by"], moved["created_at"]) == \
        (line["id"], 1, "a", 1, line["created_at"])
    assert (moved["b_x"], moved["label"], moved["edited_by"]) == (20, "width", 2) and moved["edited_at"]
    assert ais.update_measurement(store, 999, LINE, 1) is None


@pytest.mark.parametrize("line", [LINE | {"a_x": "4"}, LINE | {"b_y": True}, LINE | {"length_px": -1},
                                  LINE | {"length_um": float("inf")}, LINE | {"pixconv": float("nan")},
                                  LINE | {"label": 3}, LINE | {"label": "x" * 1001}, {"a_x": 1}, [1, 2]])
def test_a_measurement_must_be_numbers_and_a_label(store, line):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    with pytest.raises(ais.BatchError):
        ais.add_measurement(store, batch["id"], "a", line, 1)


def test_a_measurement_needs_a_batch_and_image_that_exist(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    with pytest.raises(ais.BatchError):
        ais.add_measurement(store, batch["id"] + 1, "a", LINE, 1)
    with pytest.raises(ais.BatchError):
        ais.add_measurement(store, batch["id"], "nope", LINE, 1)


def test_a_measurement_is_not_an_ais_and_does_not_finish_an_image(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    before = ais.list_batches(store)
    ais.add_measurement(store, batch["id"], "a", LINE, 1)
    assert ais.list_batches(store) == before
    assert ais.list_results(store, batch["id"]) == []


def test_measurements_follow_a_renamed_batch_and_go_with_a_deleted_one(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    other = ais.create_batch(store, "g", "upload", files(("f/z" + P, "z")), 1)
    ais.add_measurement(store, batch["id"], "a", LINE, 1)
    kept = ais.add_measurement(store, other["id"], "z", LINE, 1)
    ais.rename_batch(store, batch["id"], "new")
    assert ais.list_measurements(store, batch["id"])[0]["batch_name"] == "new"
    assert ais.get_measurement(store, kept["id"])["batch_name"] == "g"
    ais.delete_batch(store, batch["id"])
    assert ais.list_measurements(store) == [kept]


def test_a_full_reset_deletes_measurements_and_an_auto_reset_keeps_them(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    ais.add_measurement(store, batch["id"], "a", LINE, 1)
    assert ais.reset_batch(store, batch["id"], "auto")[1] == 0
    assert len(ais.list_measurements(store, batch["id"])) == 1
    assert ais.reset_batch(store, batch["id"], "all")[1] == 0
    assert ais.list_measurements(store, batch["id"]) == []


def test_measurements_move_with_a_rerandomized_image(store):
    batch = ais.create_batch(store, "b", "upload", files(("f/a" + P, "a")), 1, randomize_names=True)
    old = batch["images"][0]["key"]
    ais.add_measurement(store, batch["id"], old, LINE, 1)
    after, _, _ = ais.rerandomize(store, batch["id"], 1)
    new = after["images"][0]["key"]
    assert new != old and ais.list_measurements(store, batch["id"])[0]["image"] == new


def test_measurements_come_back_from_a_backup(store):
    batch = blinded_batch(store)
    key = batch["images"][0]["key"]
    line = ais.add_measurement(store, batch["id"], key, LINE | {"label": "soma"}, 1)
    ais.update_measurement(store, line["id"], LINE | {"label": "edited"}, 1)
    lines = ais.list_measurements(store, batch["id"])
    backup = backup_of(store, batch["id"])
    ais.delete_batch(store, batch["id"])

    back = ais.import_batch(store, backup, {1: "Ann"}, 1)

    moved = ("id", "batch_id")
    assert [{k: v for k, v in m.items() if k not in moved} for m in ais.list_measurements(store, back["id"])] == \
        [{k: v for k, v in m.items() if k not in moved} for m in lines]


def test_a_backup_from_before_measurements_still_imports(store):
    batch = blinded_batch(store)
    backup = backup_of(store, batch["id"])
    del backup["measurements"]
    back = ais.import_batch(store, backup, {1: "Ann"}, 1)
    assert ais.list_measurements(store, back["id"]) == []


@pytest.mark.parametrize("change", [
    "not a list", ["not an object"], [{"image": "nope", "n": 1}],
])
def test_a_backup_with_bad_measurements_is_refused_whole(store, change):
    batch = blinded_batch(store)
    backup = backup_of(store, batch["id"]) | {"measurements": change}
    count = len(ais.list_batches(store))
    with pytest.raises(ais.BatchError):
        ais.import_batch(store, backup, {1: "Ann"}, 1)
    assert len(ais.list_batches(store)) == count


def test_a_backup_names_the_people_of_its_measurements(store):
    batch = ais.create_batch(store, "f", "upload", files(("f/a" + P, "a")), 1)
    line = ais.add_measurement(store, batch["id"], "a", LINE, 7)
    ais.update_measurement(store, line["id"], LINE, 8)
    assert ais.backup_user_ids(ais.backup_batch(store, batch["id"])) == {1, 7, 8}
