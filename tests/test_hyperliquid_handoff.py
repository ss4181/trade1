import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools.build_hyperliquid_handoff import build_bundle, safe_json


class HandoffTests(unittest.TestCase):
    def make(self, root):
        (root/'research').mkdir()
        (root/'research'/'PROTOCOL.md').write_text('research only')
        (root/'strategy_engine.py').write_text('VALUE=1')
        (root/'.env').write_text('DO_NOT_INCLUDE=private')
        (root/'.subscribers.json').write_text('[123]')
        (root/'.manual_positions.json').write_text('[{}]')
        (root/'signals.log').write_text('private user state')

    def test_no_secrets_state_or_pnl_and_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make(root)
            with patch('tools.build_hyperliquid_handoff.git_meta', return_value=(None,set())):
                m = build_bundle(root, root/'out.zip', include_evidence=False)
            with zipfile.ZipFile(root/'out.zip') as z:
                self.assertNotIn('.env', z.namelist())
                self.assertFalse(any('subscribers' in s or 'positions' in s or 'signals.log' in s for s in z.namelist()))
                for name, info in m['files'].items():
                    self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(),info['sha256'])
                self.assertFalse(m['live_enabled'])
                self.assertFalse(m['network_used'])

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make(root)
            (root/'out.zip').write_bytes(b'user file')
            with self.assertRaises(ValueError): build_bundle(root,root/'out.zip')
            self.assertEqual((root/'out.zip').read_bytes(), b'user file')

    def test_private_json_fields_rejected(self):
        for key in ('api_key','telegram_bot_token','private_key','recipients'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                safe_json({'nested':{key:'do not share'}})

    def test_other_build_partial_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.make(root)
            (root/'out.zip.partial').write_bytes(b'other build')
            with self.assertRaises(ValueError): build_bundle(root,root/'out.zip')
            self.assertEqual((root/'out.zip.partial').read_bytes(), b'other build')

    def test_missing_manifest_rejected_no_archive_copy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.make(root)
            archive=root/'backup'
            archive.mkdir()
            (archive/'market_archive_2026-10.jsonl').write_text('{}\n')
            with self.assertRaises(ValueError): build_bundle(root,root/'out.zip',archive_dir=archive)
            self.assertFalse((root/'out.zip').exists())

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.make(root)
            with patch.object(Path,'is_symlink',return_value=True):
                with self.assertRaises(ValueError): build_bundle(root,root/'out.zip')

    def test_verified_market_archive_only(self):
        from datetime import datetime,timezone
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            self.make(root)
            archive=root/'backup'
            archive.mkdir()
            files={'market_archive_2026-10.jsonl':b'{"symbol":"BTCUSDT","oi":1}\n',
                   '.subscribers.json':b'[123]'}
            for name,data in files.items(): (archive/name).write_bytes(data)
            manifest=dict(schema_version='trade1-backup-v1',created_at_utc=datetime.now(timezone.utc).isoformat(),
                files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in files.items()})
            (archive/'backup_manifest.json').write_text(json.dumps(manifest))
            with patch('tools.build_hyperliquid_handoff.git_meta',return_value=(None,set())):
                m=build_bundle(root,root/'out.zip',archive_dir=archive)
            self.assertTrue(m['forward_archives_included'])
            with zipfile.ZipFile(root/'out.zip') as z:
                self.assertIn('reference-data/binance-forward/market_archive_2026-10.jsonl', z.namelist())
                self.assertFalse(any('subscribers' in s for s in z.namelist()))


if __name__=='__main__': unittest.main()
