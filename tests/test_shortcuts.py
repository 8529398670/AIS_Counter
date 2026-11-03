"""Keyboard shortcuts kept on the account (app/models/users.py)."""
from __future__ import annotations

import pytest

from app.core import db
from app.models import users


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


@pytest.mark.parametrize("good", [
    {},
    {"ais.reject": []},
    {"ais.zoom_in": ["+", "="], "ais.redo": ["Mod+Shift+Z", "Mod+Y"]},
    {"ais.nudge_left": ["Alt+ArrowLeft", "Alt+Shift+A"], "measure.switch_end": ["Tab"]},
    {"ais.undo": ["Mod++", "Space", "F12", "ö"]},
    {"newer.build_action": ["Q"]},
])
def test_good_shortcuts_are_accepted(good):
    assert users.valid_shortcuts(good)


@pytest.mark.parametrize("bad", [
    None, [], "ais.undo=Z",
    {"ais.undo": "Z"},
    {"ais.undo": ["A", "B", "C", "D", "E"]},
    {"Ais.Undo": ["Z"]}, {"ais..undo": ["Z"]}, {"": ["Z"]}, {"a" * 65: ["Z"]},
    {"ais.undo": [""]}, {"ais.undo": [" "]}, {"ais.undo": ["Ctrl+Z"]}, {"ais.undo": ["Shift+Mod+Z"]},
    {"ais.undo": ["Arrow-Left"]}, {"ais.undo": ["X" * 41]}, {"ais.undo": [1]},
    {f"a.n{i}": ["Z"] for i in range(201)},
])
def test_bad_shortcuts_are_refused(bad):
    assert not users.valid_shortcuts(bad)


def test_shortcuts_are_kept_on_the_account(store):
    user = users.create_user(store, "Ada", users.ROLE_USER)
    assert users.get_user(store, user.id).shortcuts == {}
    assert users.set_shortcuts(store, user.id, {"ais.tool_trace": ["Q"]})
    assert users.get_user(store, user.id).shortcuts == {"ais.tool_trace": ["Q"]}
    assert users.set_shortcuts(store, user.id, {})
    assert users.get_user(store, user.id).shortcuts == {}
    assert not users.set_shortcuts(store, user.id + 1, {})


def test_an_account_saved_before_shortcuts_loads(store):
    user = users.create_user(store, "Ada", users.ROLE_USER)
    record = user.to_record()
    del record["shortcuts"]
    assert users.User.from_record(record).shortcuts == {}
