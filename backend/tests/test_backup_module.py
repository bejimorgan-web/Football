import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import backup, storage
from app.settings import BackupSettings


class BackupModuleTest(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parent / ".tmp-backup-test"
        if self.temp_root.exists():
            shutil.rmtree(self.temp_root, ignore_errors=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.data_dir = self.temp_root / "data"
        self.assets_dir = self.data_dir / "assets"
        self.backups_dir = self.temp_root / "backups"
        patches = [
            patch.object(storage, "DATA_DIR", self.data_dir),
            patch.object(storage, "ASSETS_DIR", self.assets_dir),
            patch.object(storage, "CONFIG_PATH", self.data_dir / "config.json"),
            patch.object(storage, "METADATA_PATH", self.data_dir / "football_metadata.json"),
            patch.object(storage, "APPROVED_STREAMS_PATH", self.data_dir / "approved_streams.json"),
            patch.object(storage, "USERS_PATH", self.data_dir / "users.json"),
            patch.object(storage, "VIEWERS_PATH", self.data_dir / "viewers.json"),
            patch.object(storage, "SESSIONS_PATH", self.data_dir / "sessions.json"),
            patch.object(storage, "SECURITY_LOGS_PATH", self.data_dir / "security_logs.json"),
            patch.object(storage, "TENANTS_PATH", self.data_dir / "tenants.json"),
            patch.object(backup, "DATA_DIR", self.data_dir),
            patch.object(backup, "BACKEND_DIR", self.temp_root),
            patch.object(backup, "DEFAULT_BACKUP_DIR", self.backups_dir),
            patch.object(backup, "BACKUP_LOGS_PATH", self.data_dir / "backup_logs.json"),
        ]
        self._patches = patches
        for item in self._patches:
            item.start()
        storage.ensure_storage_files()
        (self.data_dir / "users.json").write_text(json.dumps([{"tenant_id": "default", "device_id": "one"}]), encoding="utf-8")

    def tearDown(self):
        for item in reversed(self._patches):
            item.stop()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_create_and_restore_backup(self):
        settings = BackupSettings(path=str(self.backups_dir), retention=3)
        created = backup.create_backup(settings)
        self.assertEqual(created["status"], "ok")
        archive_path = Path(created["archive_path"])
        self.assertTrue(archive_path.exists())

        (self.data_dir / "users.json").write_text("[]", encoding="utf-8")
        restored = backup.restore_backup(str(archive_path))
        self.assertEqual(restored["status"], "ok")
        contents = json.loads((self.data_dir / "users.json").read_text(encoding="utf-8"))
        self.assertEqual(contents[0]["device_id"], "one")


if __name__ == "__main__":
    unittest.main()
