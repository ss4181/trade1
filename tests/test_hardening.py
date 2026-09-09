"""Backup/sync and Telegram regressions. Synthetic private data; no network."""
import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive_backup as backup
import backup_verify as verifier
from notification_delivery import DeliveryOutbox


class BackupHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.file = self.source / "market_archive_2026-09.jsonl"
        self.file.write_bytes(b'{"n":1}\n')
        self.dest = self.root / "backup"
        self.manifest = self.dest / "backup_manifest.json"
        with redirect_stdout(io.StringIO()):
            backup.backup_once(self.source, self.dest)

    def tearDown(self):
        self.tmp.cleanup()

    def copy(self):
        with redirect_stdout(io.StringIO()):
            return backup.backup_once(self.source, self.dest)

    def test_same_metadata_edit_changes_sync_timestamp_and_does_not_recopy(self):
        old_source = self.file.stat()
        target = self.dest / self.file.name
        old_target = target.stat()
        self.file.write_bytes(b'{"n":2}\n')
        os.utime(self.file, ns=(old_source.st_atime_ns, old_source.st_mtime_ns))
        self.assertEqual(self.copy()["copied"], 1)
        self.assertGreaterEqual(target.stat().st_mtime_ns - old_target.st_mtime_ns, 2_000_000_000)
        self.assertEqual(self.file.stat().st_mtime_ns, old_source.st_mtime_ns)
        self.assertTrue(verifier.verify_backup(self.dest)["ok"])
        self.assertEqual(self.copy()["copied"], 0)

    def test_target_corruption_is_repaired_with_new_timestamp(self):
        target = self.dest / self.file.name
        original = target.stat()
        target.write_bytes(b'{"n":9}\n')
        os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(self.copy()["copied"], 1)
        self.assertGreater(target.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(self.copy()["skipped"], 1)

    def test_mtime_only_change_is_not_a_content_change(self):
        info = self.file.stat()
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
        self.assertEqual(self.copy()["copied"], 0)

    def test_target_symlink_guard_does_not_read_or_overwrite(self):
        original = Path.is_symlink
        target = self.dest / self.file.name
        with patch.object(Path, "is_symlink", lambda p: p == target or original(p)):
            with self.assertRaisesRegex(OSError, "unsafe_backup_target"):
                self.copy()
        self.assertEqual(target.read_bytes(), b'{"n":1}\n')

    def test_dry_run_does_not_write_files_or_manifest(self):
        fresh = self.root / "dry"
        with redirect_stdout(io.StringIO()):
            backup.backup_once(self.source, fresh, dry_run=True)
        self.assertFalse(fresh.exists())

    def test_failed_copy_preserves_previous_backup_and_cleans_temp(self):
        original = (self.dest / self.file.name).read_bytes()
        manifest = self.manifest.read_bytes()
        self.file.write_bytes(b'{"n":2}\n')
        with patch.object(backup.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.copy()
        self.assertEqual((self.dest / self.file.name).read_bytes(), original)
        self.assertEqual(self.manifest.read_bytes(), manifest)
        self.assertEqual(list(self.dest.glob("*.tmp")), [])

    def test_invalid_manifest_shapes_fail_closed(self):
        original = json.loads(self.manifest.read_text())
        for payload in ([], None, {}, {**original, "files": []},
                        {**original, "files": {self.file.name: None}},
                        {**original, "files": {self.file.name: {"bytes": True, "sha256": "x"}}},
                        {**original, "created_at_utc": "2026-09-09T00:00:00"}):
            with self.subTest(payload=type(payload).__name__):
                self.manifest.write_text(json.dumps(payload))
                self.assertFalse(verifier.verify_backup(self.dest)["ok"])

    def test_duplicate_manifest_keys_fail_closed(self):
        raw = self.manifest.read_text()
        self.manifest.write_text(raw.replace('"files":', '"files": {}, "files":', 1))
        self.assertFalse(verifier.verify_backup(self.dest)["ok"])

    def test_matching_hash_does_not_make_invalid_json_valid(self):
        for payload in (b'{"x":NaN}\n', b'{"x":1,"x":2}\n', b'\xff\n'):
            with self.subTest(payload=repr(payload)):
                target = self.dest / self.file.name
                target.write_bytes(payload)
                manifest = json.loads(self.manifest.read_text())
                manifest["files"][self.file.name] = {
                    "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                self.manifest.write_text(json.dumps(manifest))
                result = verifier.verify_backup(self.dest)
                self.assertIn(f"unreadable_or_invalid:{self.file.name}", result["errors"])

    def test_missing_file_is_not_success(self):
        (self.dest / self.file.name).unlink()
        self.assertFalse(verifier.verify_backup(self.dest)["ok"])

    def test_manifest_change_during_verification_is_rejected(self):
        real = verifier._json
        def changing_json(payload):
            parsed = real(payload)
            if payload == '{"n":1}\n':
                self.manifest.write_text(self.manifest.read_text() + " ")
            return parsed
        with patch.object(verifier, "_json", changing_json):
            result = verifier.verify_backup(self.dest)
        self.assertIn("manifest_changed_during_verification", result["errors"])

    def test_restore_uses_frozen_manifest_not_replaced_source_manifest(self):
        snapshot = verifier._inspect_backup(self.dest)
        corrupted = json.loads(self.manifest.read_text())
        corrupted["files"]["../.env"] = {"bytes": 1, "sha256": "0"*64}
        self.manifest.write_text(json.dumps(corrupted))
        original = verifier._inspect_backup
        def inspect(directory, **kwargs):
            return snapshot if Path(directory) == self.dest else original(directory, **kwargs)
        with patch.object(verifier, "_inspect_backup", inspect):
            result = verifier.restore_rehearsal(self.dest, self.root / "restored")
        self.assertTrue(result["ok"])
        self.assertEqual((self.root / "restored" / "backup_manifest.json").read_bytes(), snapshot[1])

    def test_restore_preserves_existing_dest_and_rejects_nested_dest(self):
        existing = self.root / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(ValueError, "must_not_exist"):
            verifier.restore_rehearsal(self.dest, existing)
        with self.assertRaisesRegex(ValueError, "inside_backup"):
            verifier.restore_rehearsal(self.dest, self.dest / "nested")
        self.assertEqual(marker.read_text(), "keep")
        self.assertFalse((self.dest / "nested").exists())

    def test_status_file_cannot_overwrite_the_backup(self):
        before = self.manifest.read_bytes()
        output = io.StringIO()
        with redirect_stdout(output):
            rc = verifier.main([str(self.dest), "--status-file", str(self.manifest)])
        self.assertEqual(rc, 1)
        self.assertIn("status_write_failed", json.loads(output.getvalue())["errors"])
        self.assertEqual(before, self.manifest.read_bytes())

    def test_cli_failure_has_no_payload_or_traceback(self):
        self.manifest.write_text("PRIVATE_SECRET invalid json")
        output = io.StringIO()
        with redirect_stdout(output):
            rc = verifier.main([str(self.dest), "--restore-to", str(self.root / "new")])
        self.assertEqual(rc, 1)
        self.assertNotIn("PRIVATE_SECRET", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["ok"])


class DeliveryHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "outbox.json"
        self.box = DeliveryOutbox(self.path)
        self.now = datetime(2026, 9, 9, tzinfo=timezone.utc)
        self.box.enqueue({"event_id": "event"}, ["private-chat"], self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def test_concurrent_retry_never_sends_to_an_inflight_recipient(self):
        started, finish = threading.Event(), threading.Event()
        errors = []
        calls = []
        def slow_sender(cid, record):
            calls.append(cid)
            started.set()
            return finish.wait(5)
        def work():
            try:
                self.box.deliver("event", slow_sender, self.now)
            except Exception as exc:
                errors.append(type(exc).__name__)
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        try:
            self.assertTrue(started.wait(3))
            sender = Mock(return_value=True)
            self.box.deliver("event", sender, self.now + timedelta(minutes=2))
            sender.assert_not_called()
        finally:
            finish.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(calls, ["private-chat"])
        self.assertEqual(self.box.get_public("event")["delivery_status"], "delivered")

    def test_crash_interrupted_sending_can_retry_after_restart(self):
        data = json.loads(self.path.read_text())
        data["events"]["event"]["recipients"]["private-chat"].update(
            status="sending", attempts=1, next_attempt_at=(self.now+timedelta(minutes=1)).isoformat())
        self.path.write_text(json.dumps(data))
        restarted = DeliveryOutbox(self.path)
        sender = Mock(return_value=True)
        restarted.deliver("event", sender, self.now+timedelta(minutes=2))
        sender.assert_called_once()
        self.assertEqual(restarted.get_public("event")["delivery_status"], "delivered")

    def test_final_failed_attempt_is_immediately_terminal(self):
        box = DeliveryOutbox(self.path, max_attempts=1)
        result = box.deliver("event", lambda *_: False, self.now)
        self.assertEqual(result["delivery_status"], "failed")
        self.assertEqual(box.pending_ids(), [])

    def test_corrupt_queue_is_not_silently_replaced(self):
        for payload in ([], {"schema_version": 99, "events": {}},
                        {"schema_version": 1, "events": {"event": {"record": "PRIVATE_SECRET"}}}):
            with self.subTest(payload=type(payload).__name__):
                raw = json.dumps(payload)
                self.path.write_text(raw)
                box = DeliveryOutbox(self.path)
                with self.assertRaisesRegex(ValueError, "^invalid_delivery_state$"):
                    box.enqueue({"event_id": "next"}, ["other"], self.now)
                self.assertEqual(self.path.read_text(), raw)

    def test_partial_delivery_public_view_has_no_recipient_ids(self):
        path = Path(self.tmp.name) / "partial.json"
        box = DeliveryOutbox(path)
        box.enqueue({"event_id": "e"}, ["private-one", "private-two"], self.now)
        result = box.deliver("e", lambda cid, record: cid == "private-one", self.now)
        self.assertEqual(result["delivery_status"], "partial")
        self.assertNotIn("private-", json.dumps(result))

    def test_corrupt_delivery_evidence_cannot_count_as_confirmed(self):
        data = json.loads(self.path.read_text())
        data["events"]["event"]["first_delivered_at"] = self.now.isoformat()
        self.path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "invalid_delivery_state"):
            DeliveryOutbox(self.path).confirmed_records()


if __name__ == "__main__":
    unittest.main()
