"""What the page's outbox relies on when it sends edits made while offline:
a create sent twice is one row, and an edit based on an old rev is a 409."""
from __future__ import annotations

import json

import pytest

from app.models import ais
from tests.test_batches import LINE, P, files, row
from tests.test_matlab_routes import Harness


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def post(h, path, who, **body):
    response = h.get("POST", path, session=who, body=body)
    return response.status, json.loads(response.data)


def batch_for(h, who):
    return ais.create_batch(h.store, "f", "upload", files(("f/a" + P, "a")), who.id)


def test_a_result_sent_twice_is_saved_once(h):
    ann = h.user()
    batch = batch_for(h, ann)
    body = {"batch_id": batch["id"], "image": "a", "row": row(), "client_id": "c0ffee00-0001"}
    status, first = post(h, "/api/ais/results", ann, **body)
    assert status == 200, first
    status, again = post(h, "/api/ais/results", ann, **body)
    assert (status, again["id"], again["n"]) == (200, first["id"], 1)
    assert len(ais.list_results(h.store, batch["id"])) == 1
    status, plain = post(h, "/api/ais/results", ann, batch_id=batch["id"], image="a", row=row())
    assert (status, plain["n"]) == (200, 2)
    status, bad = post(h, "/api/ais/results", ann, **body | {"client_id": 5})
    assert status == 400


def test_a_stale_expect_is_a_409_with_the_row_as_it_is(h):
    ann = h.user()
    batch = batch_for(h, ann)
    _, first = post(h, "/api/ais/results", ann, batch_id=batch["id"], image="a", row=row(), client_id="c0ffee00-0002")
    path = f"/api/ais/results/{first['id']}"
    status, edited = post(h, path + "/update", ann, row=row(2.0), expect=0)
    assert (status, edited["rev"]) == (200, 1)
    status, refused = post(h, path + "/update", ann, row=row(3.0), expect=0)
    assert status == 409 and refused["current"]["length_um"] == 2.0
    soma = {k: 1.0 for k in ais.SOMA_NUMBERS}
    assert post(h, path + "/soma", ann, soma=soma, expect=0)[0] == 409
    assert post(h, path + "/soma", ann, soma=soma, expect=1)[1]["rev"] == 2
    assert post(h, path + "/update", ann, row=row(), expect="1")[0] == 400
    assert post(h, path + "/delete", ann, expect=1)[0] == 409
    assert post(h, path + "/delete", ann, expect=2)[0] == 200
    assert post(h, path + "/delete", ann, expect=2)[0] == 404


def test_measurements_take_client_id_and_expect_too(h):
    ann = h.user()
    batch = batch_for(h, ann)
    body = {"batch_id": batch["id"], "image": "a", "measurement": LINE, "client_id": "c0ffee00-0003"}
    _, line = post(h, "/api/ais/measurements", ann, **body)
    assert post(h, "/api/ais/measurements", ann, **body)[1]["id"] == line["id"]
    path = f"/api/ais/measurements/{line['id']}"
    assert post(h, path + "/update", ann, measurement=LINE, expect=0)[1]["rev"] == 1
    assert post(h, path + "/update", ann, measurement=LINE, expect=0)[0] == 409
    assert post(h, path + "/delete", ann, expect=0)[0] == 409
    assert post(h, path + "/delete", ann)[0] == 200


def test_without_expect_an_edit_works_as_before(h):
    ann = h.user()
    batch = batch_for(h, ann)
    _, first = post(h, "/api/ais/results", ann, batch_id=batch["id"], image="a", row=row())
    for _ in range(2):
        assert post(h, f"/api/ais/results/{first['id']}/update", ann, row=row(2.0))[0] == 200
