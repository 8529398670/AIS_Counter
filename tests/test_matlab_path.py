"""The MATLAB path kept on the account (app/models/users.py)."""
from __future__ import annotations

import pytest

from app.core import db
from app.models import users


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


@pytest.mark.parametrize("good", [
    "", "/Applications/MATLAB_R2024b.app", r"C:\Program Files\MATLAB\R2024b\bin\matlab.exe",
    "/home/ana/it's mine/matlab", "/Users/josé/MATLAB/bin/matlab",
])
def test_good_paths_are_accepted(good):
    assert users.valid_matlab_path(good)


@pytest.mark.parametrize("bad", [None, 1, ["/x"], 'C:\\a"&calc&"', "/x\nrm", "/x\r", "/x\x00", "/x\t", "/" * 1025])
def test_bad_paths_are_refused(bad):
    assert not users.valid_matlab_path(bad)


def test_the_path_is_kept_on_the_account(store):
    user = users.create_user(store, "Ada", users.ROLE_USER)
    assert users.get_user(store, user.id).matlab_path == ""
    assert users.set_matlab_path(store, user.id, "/x/matlab")
    assert users.get_user(store, user.id).matlab_path == "/x/matlab"
    assert not users.set_matlab_path(store, user.id + 1, "/x")


def test_an_account_saved_before_the_path_loads(store):
    record = users.create_user(store, "Ada", users.ROLE_USER).to_record()
    del record["matlab_path"]
    assert users.User.from_record(record).matlab_path == ""
