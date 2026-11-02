"""The store's write path (app/core/db.py)."""
from __future__ import annotations

import threading
import time

import pytest

from app.core import db


@pytest.fixture
def store(tmp_path):
    return db.open_store(tmp_path / "app.db", "0" * 64, False)


def test_a_writer_is_not_starved_by_back_to_back_transactions(store):
    # Auto mode accepting AIS one after another, each transaction slow: a
    # delete in between used to poll SQLite's lock, miss every short gap and
    # fail with "database is locked" after the busy timeout.
    stop = threading.Event()

    def hog():
        while not stop.is_set():
            with store.transaction() as tx:
                tx.next_sequence(db.BUCKET_META)
                time.sleep(0.05)

    thread = threading.Thread(target=hog)
    thread.start()
    try:
        time.sleep(0.05)
        started = time.perf_counter()
        for _ in range(5):
            store.put(db.BUCKET_META, "k", {"v": 1})
            with store.transaction() as tx:
                tx.delete(db.BUCKET_META, "k")
        assert time.perf_counter() - started < 2
    finally:
        stop.set()
        thread.join()


def test_a_write_inside_a_transaction_on_the_same_thread_does_not_wait_on_itself(store, monkeypatch):
    monkeypatch.setattr(db, "BUSY_TIMEOUT_SECONDS", 0.2)
    with store.transaction():
        with pytest.raises(db.sqlite3.OperationalError):
            # Still SQLite's lock, so it fails after the busy timeout as
            # before -- rather than hanging on the queue.
            store.connect().execute("BEGIN IMMEDIATE")
        started = time.perf_counter()
        with pytest.raises(db.sqlite3.OperationalError):
            store.put(db.BUCKET_META, "k", {"v": 1})
        assert time.perf_counter() - started < 2
    store.put(db.BUCKET_META, "k", {"v": 1})
    assert store.get(db.BUCKET_META, "k") == {"v": 1}
