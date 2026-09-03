"""archive_backup.py — .env kopyalanmaz, yalniz arsiv glob'lari."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import archive_backup as backup  # noqa: E402
import signal_bot as bot  # noqa: E402


class ArchiveBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "market_archive_2026-09.jsonl").write_text(
            json.dumps({"t": "2026-09-01T00:00:00+00:00"}) + "\n",
            encoding="utf-8")
        (self.root / "liquidation_archive_2026-09.jsonl").write_text(
            "{}\n", encoding="utf-8")
        (self.root / "shadow_events_2026-09.jsonl").write_text(
            "{}\n", encoding="utf-8")
        (self.root / ".env").write_text("TELEGRAM_BOT_TOKEN=secret\n",
                                        encoding="utf-8")
        (self.root / "signals.log").write_text("{}\n", encoding="utf-8")
        (self.root / ".bot_state.json").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_collects_archives_and_skips_env(self) -> None:
        files = backup.collect_files(self.root, include_state=False)
        names = {path.name for path in files}
        self.assertIn("market_archive_2026-09.jsonl", names)
        self.assertIn("liquidation_archive_2026-09.jsonl", names)
        self.assertIn("shadow_events_2026-09.jsonl", names)
        self.assertNotIn(".env", names)
        self.assertNotIn("signals.log", names)

    def test_include_state_still_skips_env(self) -> None:
        files = backup.collect_files(self.root, include_state=True)
        names = {path.name for path in files}
        self.assertIn("signals.log", names)
        self.assertIn(".bot_state.json", names)
        self.assertNotIn(".env", names)

    def test_copy_writes_dest_without_env(self) -> None:
        dest = self.root / "usb"
        files = backup.collect_files(self.root, include_state=False)
        backup.copy_files(files, dest, dry_run=False)
        copied = {path.name for path in dest.iterdir()}
        self.assertTrue(copied)
        self.assertNotIn(".env", copied)
        self.assertTrue((dest / "market_archive_2026-09.jsonl").is_file())

    def test_unchanged_files_are_not_copied_again(self) -> None:
        dest = self.root / "shared" / "trade1-backup"
        first = backup.backup_once(self.root, dest)
        second = backup.backup_once(self.root, dest)
        self.assertEqual(first["copied"], 3)
        self.assertEqual(second["copied"], 0)
        self.assertEqual(second["skipped"], 3)

    def test_changed_archive_replaces_destination(self) -> None:
        dest = self.root / "shared" / "trade1-backup"
        backup.backup_once(self.root, dest)
        source = self.root / "market_archive_2026-09.jsonl"
        source.write_text('{"new":true}\n', encoding="utf-8")
        # Coarse timestamp filesystems can preserve the same second. Force an
        # observable mtime while keeping this test deterministic.
        future = source.stat().st_mtime + 2
        os.utime(source, (future, future))
        result = backup.backup_once(self.root, dest)
        self.assertEqual(result["copied"], 1)
        self.assertEqual((dest / source.name).read_text(encoding="utf-8"),
                         '{"new":true}\n')

    def test_state_source_is_separate_and_secrets_are_excluded(self) -> None:
        archive_root = self.root / "archive"
        archive_root.mkdir()
        (archive_root / "market_archive_2026-09.jsonl").write_text(
            "{}\n", encoding="utf-8")
        dest = self.root / "shared" / "trade1-backup"
        result = backup.backup_once(
            archive_root, dest, include_state=True, state_source=self.root)
        self.assertEqual(result["files_total"], 3)
        copied = {path.name for path in dest.iterdir()}
        self.assertIn("signals.log", copied)
        self.assertIn(".bot_state.json", copied)
        self.assertNotIn(".env", copied)
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in dest.iterdir() if path.is_file())
        self.assertNotIn("TELEGRAM_BOT_TOKEN", combined)
        self.assertNotIn("secret", combined)

    def test_source_directory_cannot_be_the_destination(self) -> None:
        with self.assertRaises(SystemExit):
            backup.backup_once(self.root, self.root)


class DailyBackupScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.dest = self.root / "dest"
        self.archive.mkdir()
        (self.archive / "market_archive_2026-09.jsonl").write_text(
            "{}\n", encoding="utf-8")
        self.state_file = self.root / ".archive_backup_state.json"
        self.now = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)
        self.patchers = [
            mock.patch.object(bot, "ARCHIVE_BACKUP_ENABLED", True),
            mock.patch.object(bot, "ARCHIVE_BACKUP_INTERVAL_HOURS", 24.0),
            mock.patch.object(bot, "ARCHIVE_BACKUP_RETRY_HOURS", 1.0),
            mock.patch.object(bot, "ARCHIVE_BACKUP_INCLUDE_STATE", False),
            mock.patch.object(bot, "ARCHIVE_BACKUP_NOTIFY_FAILURE", True),
            mock.patch.object(bot, "ARCHIVE_BACKUP_STATE_FILE", self.state_file),
            mock.patch.object(bot, "ARCHIVE_DIR", self.archive),
            mock.patch.object(bot, "ARCHIVE_BACKUP_DIR", self.dest),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmp.cleanup()

    def _write_state(self, **values) -> None:
        self.state_file.write_text(json.dumps(values), encoding="utf-8")

    def test_first_run_due_then_waits_24_hours(self) -> None:
        self.assertTrue(bot._archive_backup_due(self.now))
        result = bot._perform_archive_backup(self.now, notify_failure=False)
        self.assertIsNone(result["last_error"])
        self.assertTrue((self.dest / "market_archive_2026-09.jsonl").is_file())
        self.assertFalse(bot._archive_backup_due(self.now + timedelta(hours=23)))
        self.assertTrue(bot._archive_backup_due(self.now + timedelta(hours=24)))

    def test_failed_run_retries_after_one_hour_without_raising(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        with mock.patch.object(bot, "ARCHIVE_DIR", empty), \
                mock.patch.object(bot, "_telegram_send_text") as telegram:
            result = bot._perform_archive_backup(self.now)
            self.assertIn("yedeklenecek", result["last_error"])
            telegram.assert_called_once()
            self.assertFalse(bot._archive_backup_due(
                self.now + timedelta(minutes=59)))
            self.assertTrue(bot._archive_backup_due(
                self.now + timedelta(hours=1)))

    def test_status_does_not_contain_file_contents_or_secrets(self) -> None:
        (self.archive / ".env").write_text(
            "TELEGRAM_BOT_TOKEN=do-not-copy\n", encoding="utf-8")
        bot._perform_archive_backup(self.now, notify_failure=False)
        status_text = json.dumps(bot.archive_backup_status())
        self.assertNotIn("TELEGRAM_BOT_TOKEN", status_text)
        self.assertNotIn("do-not-copy", status_text)
        self.assertFalse((self.dest / ".env").exists())


if __name__ == "__main__":
    unittest.main()
