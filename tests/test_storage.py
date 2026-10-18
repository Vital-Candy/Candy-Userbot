import tempfile
import unittest
from pathlib import Path

from storage.database import Database
from storage.labels import LabelStore
from storage.permissions import PermissionLevel, PermissionStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Database(Path(self.temp.name) / "test.sqlite3")
        db.open()
        self.db = db
        self.labels = LabelStore(db)
        self.permissions = PermissionStore(db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_label_crud_and_account_isolation(self):
        label = self.labels.create(
            account_id=1, chat_id=10, message_id=20, name="Download", creator_id=1
        )
        self.assertEqual(label.name, "download")
        self.assertEqual(len(self.labels.list_for_message(account_id=1, chat_id=10, message_id=20)), 1)
        self.assertEqual(self.labels.list_for_message(account_id=2, chat_id=10, message_id=20), [])
        self.assertTrue(self.labels.delete(account_id=1, chat_id=10, message_id=20, name="download"))
        self.assertFalse(self.labels.delete(account_id=1, chat_id=10, message_id=20, name="download"))

    def test_duplicate_label_is_rejected(self):
        self.labels.create(account_id=1, chat_id=10, message_id=20, name="x")
        with self.assertRaises(Exception):
            self.labels.create(account_id=1, chat_id=10, message_id=20, name="X")

    def test_permissions(self):
        self.permissions.grant(
            account_id=1,
            subject_id=42,
            permission=PermissionLevel.TRUSTED,
            granted_by=1,
        )
        self.assertTrue(self.permissions.has(account_id=1, subject_id=42, permission="trusted"))
        self.assertFalse(self.permissions.has(account_id=2, subject_id=42, permission="trusted"))
        self.assertTrue(self.permissions.revoke(account_id=1, subject_id=42, permission="trusted"))
        self.assertFalse(self.permissions.has(account_id=1, subject_id=42, permission="trusted"))


if __name__ == "__main__":
    unittest.main()
