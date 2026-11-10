"""Data migrations: a database built before versions existed upgrades, a failed
step changes nothing and is tried again, a newer database is refused, and a
new one skips the steps entirely."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core import db, encryption, server_lock


def split_name(tx: db.Transaction) -> None:
    for key, record in tx.all(db.BUCKET_USERS):
        first, _, last = record.pop("name").partition(" ")
        record.update(first=first, last=last)
        tx.put(db.BUCKET_USERS, key, record)


SPLIT = db.Migration("split name", split_name)


def never(tx: db.Transaction) -> None:
    raise AssertionError("this step must not run")


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "app.db"
        self.key = encryption.generate_key_hex()

    def open(self, steps: list[db.Migration], lock: Path | None = None) -> db.Store:
        return db.open_store(self.path, self.key, True, lock, steps)

    def old_database(self) -> None:
        self.open([]).put(db.BUCKET_USERS, 1, {"name": "Ada Lovelace"})

    def kept(self) -> list[Path]:
        return sorted(self.path.parent.glob("app.db.before-migration-*"))

    def test_an_old_database_upgrades_and_is_kept(self) -> None:
        self.old_database()
        store = self.open([SPLIT])
        self.assertEqual(store.schema_version(), 1)
        self.assertEqual(store.get(db.BUCKET_USERS, 1), {"first": "Ada", "last": "Lovelace"})
        kept = self.kept()
        self.assertEqual(len(kept), 1)
        self.assertIn("-v0-", kept[0].name)
        self.assertEqual(kept[0].stat().st_mode & 0o777, 0o600)
        db.check_file(kept[0], self.key, True)
        self.assertEqual(db.Store(kept[0], self.key, True).get(db.BUCKET_USERS, 1), {"name": "Ada Lovelace"})

        self.open([db.Migration("split name", never)])
        self.assertEqual(len(self.kept()), 1, "a copy was kept with nothing to do")

    def test_a_failed_step_changes_nothing_and_is_tried_again(self) -> None:
        self.old_database()

        def broken(tx: db.Transaction) -> None:
            tx.put(db.BUCKET_USERS, 2, {"name": "Should not survive"})
            raise ValueError("something went wrong")

        with self.assertRaisesRegex(RuntimeError, "breaks half way"):
            self.open([SPLIT, db.Migration("breaks half way", broken), db.Migration("never reached", never)])
        store = self.open([SPLIT])
        self.assertEqual(store.schema_version(), 1)
        self.assertIsNone(store.get(db.BUCKET_USERS, 2))

    def test_a_newer_database_is_refused(self) -> None:
        self.open([SPLIT, SPLIT])
        with self.assertRaisesRegex(RuntimeError, "newer"):
            self.open([SPLIT])

    def test_a_new_database_is_stamped_without_running_anything(self) -> None:
        store = self.open([db.Migration("must not run", never)])
        self.assertEqual(store.schema_version(), 1)
        self.assertEqual(self.kept(), [])

    def test_shipped_migrations_leave_other_records_alone(self) -> None:
        """A database from before versions existed reads as 0. The shipped
        steps only touch saved themes, so a record without any opens as it
        always did. (The template's version of this test expects no steps.)"""
        self.old_database()
        store = db.open_store(self.path, self.key, True)
        self.assertEqual(store.schema_version(), db.latest_schema_version())
        self.assertEqual(store.get(db.BUCKET_USERS, 1), {"name": "Ada Lovelace"})

    def test_saved_themes_are_reset_to_the_built_ins(self) -> None:
        old = self.open([])
        old.put(db.BUCKET_META, "theme_defaults", {"themes": [{"id": "light"}]})
        old.put(db.BUCKET_USERS, 1, {"name": "Ada", "themes": [{"id": "wsu_dark"}], "theme_id": "wsu_dark"})
        old.put(db.BUCKET_USERS, 2, {"name": "Bob", "theme_id": "dark"})
        old.put(db.BUCKET_USERS, 3, {"name": "Cy", "theme_id": ""})
        store = db.open_store(self.path, self.key, True)
        self.assertIsNone(store.get(db.BUCKET_META, "theme_defaults"))
        self.assertEqual(store.get(db.BUCKET_USERS, 1), {"name": "Ada", "theme_id": ""})
        self.assertEqual(store.get(db.BUCKET_USERS, 2), {"name": "Bob", "theme_id": ""})
        self.assertEqual(store.get(db.BUCKET_USERS, 3), {"name": "Cy", "theme_id": ""})
        self.assertEqual(len(self.kept()), 1)

    def test_manage_does_not_migrate_under_a_running_server(self) -> None:
        self.old_database()
        lock_path = self.path.parent / "server.lock"
        lock = server_lock.acquire(lock_path)
        self.addCleanup(lock.release)
        with self.assertRaisesRegex(RuntimeError, "restart the server"):
            self.open([SPLIT], lock=lock_path)
        self.assertEqual(self.open([]).schema_version(), 0)

    def test_a_snapshot_keeps_the_version(self) -> None:
        store = self.open([SPLIT])
        copy = self.path.with_name("copy.db")
        store.snapshot(copy)
        self.assertEqual(db.Store(copy, self.key, True).schema_version(), 1)


if __name__ == "__main__":
    unittest.main()
