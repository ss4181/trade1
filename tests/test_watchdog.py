"""Bekci testleri — ag YOK, gercek Telegram cagrisi YOK."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import watchdog  # noqa: E402


def _data(last_scan) -> str:
    payload = {"status": {"last_scan": last_scan}} if last_scan is not None \
        else {"status": {}}
    return json.dumps(payload)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.data = self.dir / "data.json"
        self.state = self.dir / "state.json"
        self.sent = []
        self._orig_send = watchdog.send_telegram
        watchdog.send_telegram = lambda text: (self.sent.append(text) or True)
        self._orig_argv = sys.argv

    def tearDown(self):
        watchdog.send_telegram = self._orig_send
        sys.argv = self._orig_argv
        self.tmp.cleanup()

    def run_watchdog(self):
        sys.argv = ["watchdog.py", "--data", str(self.data),
                    "--state", str(self.state)]
        return watchdog.main()

    def test_taze_tarama_sessiz_kalir(self):
        fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
        self.data.write_text(_data(fresh.isoformat()), encoding="utf-8")
        self.assertEqual(self.run_watchdog(), 0)
        self.assertEqual(self.sent, [], "saglikli durumda mesaj gitmemeli")

    def test_bayat_tarama_uyarir(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=3)
        self.data.write_text(_data(stale.isoformat()), encoding="utf-8")
        self.run_watchdog()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("tarama yapmadı", self.sent[0])
        # durum kaydedilmeli ki spam olmasin
        self.assertIn("alerted_at", json.loads(self.state.read_text()))

    def test_ayni_arizada_spam_yapmaz(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=3)
        self.data.write_text(_data(stale.isoformat()), encoding="utf-8")
        self.run_watchdog()
        self.run_watchdog()
        self.run_watchdog()
        self.assertEqual(len(self.sent), 1,
                         "yeniden-uyari penceresi dolmadan tekrar etmemeli")

    def test_realert_penceresi_dolunca_tekrar_uyarir(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=12)
        self.data.write_text(_data(stale.isoformat()), encoding="utf-8")
        self.run_watchdog()
        old = datetime.now(timezone.utc) - timedelta(
            hours=watchdog.REALERT_HOURS + 1)
        self.state.write_text(json.dumps({"alerted_at": old.isoformat()}),
                              encoding="utf-8")
        self.run_watchdog()
        self.assertEqual(len(self.sent), 2)

    def test_toparlayinca_haber_verir_ve_durumu_temizler(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=3)
        self.data.write_text(_data(stale.isoformat()), encoding="utf-8")
        self.run_watchdog()
        fresh = datetime.now(timezone.utc) - timedelta(minutes=2)
        self.data.write_text(_data(fresh.isoformat()), encoding="utf-8")
        self.run_watchdog()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("toparladı", self.sent[1])
        self.assertEqual(json.loads(self.state.read_text()), {},
                         "toparlayinca durum temizlenmeli")

    def test_veri_yoksa_yanlis_alarm_uretmez(self):
        self.data.write_text(_data(None), encoding="utf-8")
        self.assertEqual(self.run_watchdog(), 0)
        self.assertEqual(self.sent, [])
        # dosya hic yoksa da sessiz
        self.data.unlink()
        self.assertEqual(self.run_watchdog(), 0)
        self.assertEqual(self.sent, [])

    def test_naive_zaman_damgasi_utc_kabul_edilir(self):
        naive = (datetime.now(timezone.utc)
                 - timedelta(minutes=5)).replace(tzinfo=None)
        self.data.write_text(_data(naive.isoformat()), encoding="utf-8")
        self.run_watchdog()
        self.assertEqual(self.sent, [], "naive damga UTC sayilip taze olmali")

    def test_token_redakte_edilir(self):
        watchdog.TELEGRAM_BOT_TOKEN = "123:GIZLI"
        try:
            self.assertNotIn("GIZLI", watchdog._redact("bot123:GIZLI/send"))
        finally:
            watchdog.TELEGRAM_BOT_TOKEN = ""


if __name__ == "__main__":
    unittest.main(verbosity=2)
