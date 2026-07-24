"""Cevrimdisi test paketi — ag/anahtar GEREKMEZ, ~5 saniyede biter.

Her degisiklikten sonra calistir:  python tests/offline_tests.py
Botun kritik davranislarini dogrular; hepsi gecmeden push etme.
"""

import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import signal_bot as bot  # noqa: E402

# testler modulu monkeypatch'ler; orijinalleri sakla ki sonraki testler
# oncekilerin sahtelerini cagirmasin
ORIG = {
    "send_tg": bot.send_telegram_message,
    "tg_text": bot._telegram_send_text,
}

PASS = 0


def ok(name):
    global PASS
    PASS += 1
    print(f"  ok  {name}")


def test_confidence():
    assert bot.signal_confidence("S1+S4")[0] == "COK YUKSEK"
    assert bot.signal_confidence("S1")[0] == "YUKSEK"
    assert bot.signal_confidence("S3")[0] == "ORTA"
    assert bot.signal_confidence("S2")[0] == "DUSUK"
    ok("guven kademeleri")


def test_zero_division_guards():
    z = bot.calc_volume_zscore([10.0])
    assert math.isnan(z[0])
    assert bot.realized_sigma1h([100.0, 101.0]) is None
    assert bot.calc_rsi([1.0] * 5) == [math.nan] * 5 or all(
        math.isnan(x) for x in bot.calc_rsi([1.0] * 5))
    ok("sifir-bolme korumalari")


def test_snapshot_isolation():
    st = bot.ScanState()
    bot.fetch_klines = lambda symbol, limit=250: [
        {"open_time": i * 3600000, "open": 100, "high": 101, "low": 99,
         "close": 100, "volume": 10} for i in range(250)]
    bot.fetch_funding = lambda symbol, limit=3: [
        {"time": i, "rate": -0.001} for i in range(3)]
    bot.scan_symbol("TESTUSDT", st, snapshot=True)
    assert not st.prev_cond and not st.last_fire
    bot.scan_symbol("TESTUSDT", st, snapshot=False)
    assert st.prev_cond
    ok("snapshot izolasyonu / canli state")


def test_notify_gating_and_push_flag():
    pushed = []
    bot.send_telegram_message = lambda s: pushed.append(("tg", s["strategy"]))
    bot.send_email_notification = lambda s: pushed.append(("em", s["strategy"]))
    bot.RECENT_SIGNALS.clear()
    base = {"direction": "LONG", "strength": "NORMAL", "price": 1,
            "bar_time": "2026-07-19T12:00:00+00:00", "note": "n",
            "horizon_hours": 24, "symbol": "X"}
    bot.notify({**base, "strategy": "S2", "confidence": "DUSUK"})
    bot.notify({**base, "strategy": "S1", "confidence": "YUKSEK"})
    bot.notify({**base, "strategy": "S1", "confidence": "YUKSEK"}, push=False)
    assert len(bot.RECENT_SIGNALS) == 3          # hepsi tamponda
    assert pushed == [("tg", "S1"), ("em", "S1")]  # yalniz 1 push
    ok("guven esigi + push bayragi")


def test_state_persistence(tmpdir):
    bot.STATE_FILE = Path(tmpdir) / "state.json"
    bot.RECENT_SIGNALS.clear()
    st = bot.ScanState()
    st.prev_cond[("S1", "BTCUSDT")] = True
    st.last_fire[("S3", "ETHUSDT")] = 123.0
    bot.RECENT_SIGNALS.appendleft({"strategy": "S1", "symbol": "BTCUSDT",
                                   "notified_at": "2026-07-19T12:00:00+00:00"})
    st.save()
    bot.RECENT_SIGNALS.clear()
    st2 = bot.ScanState.load()
    assert st2.prev_cond[("S1", "BTCUSDT")] is True
    assert st2.last_fire[("S3", "ETHUSDT")] == 123.0
    assert len(bot.RECENT_SIGNALS) == 1
    ok("durum kaliciligi (save/load)")


def test_ref_lines():
    ref = bot.build_ref_levels("S1+S4", 62931.99, 0.006)
    ref["exit_by"] = "2026-07-20 13:00 UTC"
    sig = {"strategy": "S1+S4", "symbol": "BTCUSDT", "direction": "LONG",
           "strength": "STRONG", "confidence": "COK YUKSEK",
           "confidence_note": "test p=0.006", "price": 62931.99,
           "bar_time": "2026-07-19T12:00:00+00:00", "rsi": 21.4,
           "note": "x", "horizon_hours": 24, "ref": ref}
    lines = bot._ref_lines(sig)
    joined = "\n".join(lines)
    for must in ("Guven: COK YUKSEK", "son: 2026-07-20 13:00 UTC",
                 "Dokunma olasiliklari", "medyan"):
        assert must in joined, must
    assert "Referans" in bot._email_html(sig)
    ok("bildirim referans satirlari")


def test_command_security():
    bot.ENABLE_TELEGRAM = True
    bot.TELEGRAM_BOT_TOKEN = "X"
    bot.TELEGRAM_CHAT_ID = "111"
    bot.TELEGRAM_SUBSCRIBERS = ["111", "222"]
    bot.TELEGRAM_OPEN = False
    handled, replies = [], []
    bot.handle_telegram_command = lambda text, chat_id: handled.append(
        (text, chat_id))
    bot._telegram_send_text = lambda text, chat_id=None: replies.append(chat_id)

    class R:
        def __init__(s, d): s._d = d
        def raise_for_status(s): pass
        def json(s): return s._d
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return R({"result": [
                {"update_id": 1, "message": {"text": "/check",
                                             "chat": {"id": 111}}},
                {"update_id": 2, "message": {"text": "/check",
                                             "chat": {"id": 999}}},
                {"update_id": 3, "message": {"text": "/myid",
                                             "chat": {"id": 999}}},
                {"update_id": 4, "message": {"text": "/status",
                                             "chat": {"id": 222}}},
            ]})
        raise KeyboardInterrupt

    bot.requests.get = fake_get
    try:
        bot.telegram_command_loop()
    except KeyboardInterrupt:
        pass
    assert [c for _, c in handled] == ["111", "222"]   # yabanci komut islenmedi
    assert replies == ["999"]                          # yabanci sadece /myid aldi
    ok("telegram izin listesi guvenligi")


def test_disabled_strategies_and_header():
    # S2 kapaliyken: S2 kosulu saglansa bile sinyal uretilmemeli, funding
    # API'sine hic gidilmemeli
    called = {"funding": 0}

    def fake_funding(symbol, limit=3):
        called["funding"] += 1
        return [{"time": i, "rate": -0.01} for i in range(3)]  # derin negatif

    bot.fetch_funding = fake_funding
    bot.fetch_klines = lambda symbol, limit=250: [
        {"open_time": i * 3600000, "open": 100, "high": 101, "low": 99,
         "close": 100, "volume": 10} for i in range(250)]
    bot.DISABLED_STRATEGIES = {"S2"}
    st = bot.ScanState()
    bot.scan_symbol("XUSDT", st, snapshot=True)
    sigs = bot.scan_symbol("XUSDT", st, snapshot=True)
    assert called["funding"] == 0, "S2 kapaliyken funding cekilmemeli"
    assert not any(s["strategy"] == "S2" for s in sigs)
    bot.DISABLED_STRATEGIES = set()
    sigs2 = bot.scan_symbol("XUSDT", st, snapshot=True)
    assert any(s["strategy"] == "S2" for s in sigs2), "acikken S2 uretilmeli"
    # telegram basliginda guven kademesi gorunmeli
    captured = {}

    class FR:
        def raise_for_status(self): pass
    bot.ENABLE_TELEGRAM = True
    bot.TELEGRAM_BOT_TOKEN = "X"
    bot.TELEGRAM_CHAT_ID = "1"
    bot.TELEGRAM_SUBSCRIBERS = ["1"]
    bot.send_telegram_message = ORIG["send_tg"]     # onceki sahteyi kaldir
    bot._telegram_send_text = ORIG["tg_text"]
    bot.requests.post = (lambda url, json=None, timeout=None:
                         captured.update(json) or FR())
    bot.send_telegram_message({"strategy": "S1", "symbol": "BTCUSDT",
                               "direction": "LONG", "strength": "NORMAL",
                               "confidence": "YUKSEK", "price": 1,
                               "bar_time": "t", "note": "n",
                               "horizon_hours": 24})
    assert "Guven: YUKSEK" in captured["text"].splitlines()[0]
    ok("strateji kapatma anahtari + baslikta guven")


def test_market_archiver(tmpdir):
    bot.ARCHIVE_DIR = Path(tmpdir)
    bot.ARCHIVE_MARKET_DATA = True
    bot._last_archive_hour = None
    bot.SYMBOLS = ["PEPEUSDT", "BTCUSDT"]
    bot.PERP_MAP = {"PEPEUSDT": "1000PEPEUSDT"}
    bot.LAST_SPOT_CLOSE.update({"PEPEUSDT": 0.000002, "BTCUSDT": 60000.0})

    class R:
        def __init__(s, d): s._d = d
        def raise_for_status(s): pass
        def json(s): return s._d

    def fake_get(url, params=None, timeout=None):
        if "ticker/price" in url:
            return R([{"symbol": "1000PEPEUSDT", "price": "0.002002"},
                      {"symbol": "BTCUSDT", "price": "60060"}])
        if "openInterest" in url:
            return R({"openInterest": "12345.6"})
        raise AssertionError(url)

    bot.requests.get = fake_get
    bot.time.sleep = lambda s: None
    bot.archive_market_state()
    files = list(Path(tmpdir).glob("market_archive_*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(l) for l in files[0].read_text(
        encoding="utf-8").splitlines()]
    assert len(rows) == 2
    pepe = next(r for r in rows if r["sym"] == "PEPEUSDT")
    # 1000'lik kontrat olcegi: 0.002002/(0.000002*1000)-1 = +0.001
    assert abs(pepe["basis"] - 0.001) < 1e-6
    assert pepe["oi"] == 12345.6
    # ayni saat icinde ikinci cagri yazmamali
    bot.archive_market_state()
    assert len(files[0].read_text(encoding="utf-8").splitlines()) == 2
    ok("piyasa arsivi (1000x olcek + saat kilidi)")


def test_daily_summary_includes_perf():
    sent = []
    bot._telegram_send_text = lambda text, chat_id=None: sent.append(text)
    bot.ENABLE_TELEGRAM = True
    bot.DAILY_SUMMARY_HOUR_UTC = 0
    bot._last_summary_day = None
    bot.realized_performance = lambda max_signals=30: {
        "n_total": 4, "fetch_errors": 0,
        "strategies": {"S1": {"n": 4, "median_pct": 1.2, "mean_pct": 1.0,
                              "winrate_pct": 75, "bt_median_pct": 0.93,
                              "bt_winrate_pct": 62}}}
    bot._maybe_daily_summary()
    assert sent and "Gunluk ozet" in sent[0]
    assert "karne" in sent[0] and "+1.20%" in sent[0]
    ok("gunluk ozette olgun sinyal karnesi")


def test_dashboard_data(tmpdir):
    log = Path(tmpdir) / "sig.log"
    old_t = (bot.datetime.now(bot.timezone.utc)
             - bot.timedelta(hours=40)).isoformat()
    new_t = (bot.datetime.now(bot.timezone.utc)
             - bot.timedelta(hours=2)).isoformat()
    olgun = {"strategy": "S1", "symbol": "AAAUSDT", "direction": "LONG",
             "strength": "NORMAL", "confidence": "YUKSEK", "bar_time": old_t,
             "price": 100.0, "note": "x", "horizon_hours": 24,
             "ref": {"entry_ref": 100.0}}
    aktif = {"strategy": "S3", "symbol": "BBBUSDT", "direction": "LONG",
             "strength": "NORMAL", "confidence": "ORTA", "bar_time": new_t,
             "price": 200.0, "note": "y", "horizon_hours": 4,
             "ref": {"entry_ref": 200.0}}
    log.write_text(json.dumps(olgun) + "\n" + json.dumps(aktif) + "\n",
                   encoding="utf-8")
    bot.SIGNAL_LOG = str(log)                      # mutlak yol: parent'i ezer
    bot.PERF_CACHE_FILE = Path(tmpdir) / "pc.json"
    bot.PERF_CACHE_FILE.write_text(
        json.dumps({bot._perf_key(olgun): 2.5}), encoding="utf-8")
    bot.LAST_SPOT_CLOSE.update({"BBBUSDT": 210.0})
    d = bot.build_dashboard_data()
    rows = {r["symbol"]: r for r in d["signals"]}
    assert rows["AAAUSDT"]["status"] == "OLGUN"
    assert rows["AAAUSDT"]["pnl_pct"] == 2.5       # cache'ten gerceklesen
    assert rows["BBBUSDT"]["status"] == "AKTIF"
    assert abs(rows["BBBUSDT"]["pnl_pct"] - 5.0) < 0.01   # 210/200-1
    assert rows["BBBUSDT"]["remaining_h"] is not None
    s1 = next(s for s in d["strategies"] if s["name"] == "S1")
    assert s1["live_n"] == 1 and s1["live_med"] == 2.5
    assert d["status"]["interval_min"] == bot.SCAN_INTERVAL_MINUTES
    # zenginlestirilmis alanlar: docs (tiklanabilir strateji) + why (neden geldi)
    assert "S1" in d["docs"] and "Nasil" in d["docs"]["S1"]["how"] or \
        "calisir" in d["docs"]["S1"]["how"] or d["docs"]["S1"]["how"]
    assert d["docs"]["S1+S4"]["title"]
    aktif_row = rows["BBBUSDT"]
    assert "Log-hacim z-skoru" in aktif_row["why"]      # S3 aciklamasi
    assert "RSI(14)" in rows["AAAUSDT"]["why"]           # S1 aciklamasi
    # sablon + iki fetch modu
    assert "{{DATA_URL}}" in bot.DASHBOARD_HTML_TEMPLATE
    assert '"/api/dashboard"' in bot.dashboard_html()
    assert '"./data.json"' in bot.dashboard_html("./data.json")
    ok("pano verisi + docs/why + sablon (LAN & Pages fetch)")


def test_extended_universe_rules():
    # genis-evren sembolu: S2/S3 CALISMAMALI, S1 ORTA guvenle gelmeli
    called = {"funding": 0}
    bot.fetch_funding = lambda symbol, limit=3: called.__setitem__(
        "funding", called["funding"] + 1) or [
        {"time": i, "rate": -0.01} for i in range(3)]
    # dusen kapanislar -> RSI ~0; hacim sabit -> z ~0 (S4 upgrade olmaz)
    closes = [1000 - i for i in range(250)]
    bot.fetch_klines = lambda symbol, limit=250: [
        {"open_time": i * 3600000, "open": closes[i] + 0.5, "high": closes[i] + 1,
         "low": closes[i] - 1, "close": closes[i], "volume": 10}
        for i in range(250)]
    orig_div = bot.bullish_divergence
    bot.bullish_divergence = lambda c, l, r, i: True
    bot.DISABLED_STRATEGIES = set()
    try:
        ext_sym = next(iter(bot.EXTENDED_SET))
        sigs = bot.scan_symbol(ext_sym, bot.ScanState(), snapshot=True)
        assert called["funding"] == 0, "genis evrende funding cekilmemeli"
        strats = {s["strategy"] for s in sigs}
        assert "S2" not in strats and "S3" not in strats
        s1 = next(s for s in sigs if s["strategy"].startswith("S1"))
        assert s1["confidence"] == "ORTA" and "genis evren" in s1["confidence_note"]
        # ayni kosullar CEKIRDEK sembolde: S1 YUKSEK olmali
        sigs2 = bot.scan_symbol("BTCUSDT", bot.ScanState(), snapshot=True)
        s1c = next(s for s in sigs2 if s["strategy"].startswith("S1"))
        assert s1c["confidence"] == "YUKSEK"
        # evren bilesimi (onceki testler SYMBOLS'u mutasyona ugratabilir;
        # kaynak sabitlerden dogrula)
        assert len(bot.DEFAULT_SYMBOLS.split(",")) == 30
        assert len(bot.EXTENDED_SET) == 59
    finally:
        bot.bullish_divergence = orig_div
    ok("genis evren kurallari (S1-yalniz, kademeli guven, 89 sembol)")


def test_github_publish():
    calls = []

    class R:
        def __init__(s, code=200, js=None):
            s.status_code = code
            s._js = js or {}
        def raise_for_status(s):
            if s.status_code >= 400:
                raise bot.requests.HTTPError(f"HTTP {s.status_code}")
        def json(s): return s._js
    bot.GITHUB_TOKEN = "ghsecret"
    bot.GITHUB_REPO = "u/r"
    bot.PUBLISH_ENABLED = True
    bot._last_publish = 0.0
    bot._gh_sha = None
    bot.build_dashboard_data = lambda: {"ok": 1}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(("GET", url))
        if url.endswith("/git/ref/heads/gh-pages"):
            return R(404)                   # pages branch yok -> olustur
        if url.endswith("/repos/u/r"):
            return R(200, {"default_branch": "main"})
        if url.endswith("/git/ref/heads/main"):
            return R(200, {"object": {"sha": "mainsha"}})
        return R(404)                       # contents: dosya yok
    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append(("POST", url, json.get("ref")))
        return R(201, {})
    def fake_put(url, json=None, timeout=None, headers=None):
        calls.append(("PUT", url, json.get("branch")))
        assert "ghsecret" in headers["Authorization"]
        assert "content" in json and "message" in json
        return R(200, {"content": {"sha": "newsha"}})
    bot.requests.get = fake_get
    bot.requests.post = fake_post
    bot.requests.put = fake_put
    bot.publish_to_github(force=True)
    # branch olusturma cagrisi yapildi mi
    assert any(c[0] == "POST" and c[2] == "refs/heads/gh-pages" for c in calls)
    puts = [c for c in calls if c[0] == "PUT"]
    # ilk yayinda hem index.html hem data.json yazilmali, dogru branch'e
    paths = {c[1].rsplit("/", 1)[-1] for c in puts}
    assert "index.html" in paths and "data.json" in paths
    assert all(c[2] == "gh-pages" for c in puts)
    assert bot._gh_sha == "newsha"
    # token loglarda sizmamali
    assert bot._redact("hata ghsecret var") == "hata ***TOKEN*** var"
    ok("github pages yayini (index+data, dogru branch, token redakte)")


def test_perf_formatting():
    txt = bot._format_performance({"n_total": 0})
    assert "olgunlasmis" in txt
    txt = bot._format_performance({
        "n_total": 5, "fetch_errors": 0,
        "strategies": {"S1": {"n": 5, "median_pct": 1.1, "mean_pct": 1.5,
                              "winrate_pct": 60, "bt_median_pct": 0.93,
                              "bt_winrate_pct": 62}}})
    assert "S1" in txt and "backtest medyan" in txt
    ok("performans bicimlendirme")


def main():
    with tempfile.TemporaryDirectory() as td:
        test_confidence()
        test_zero_division_guards()
        test_snapshot_isolation()
        test_notify_gating_and_push_flag()
        test_state_persistence(td)
        test_ref_lines()
        test_disabled_strategies_and_header()
        test_command_security()
        test_market_archiver(td)
        test_daily_summary_includes_perf()
        test_dashboard_data(td)
        test_extended_universe_rules()
        test_github_publish()
        test_perf_formatting()
    print(f"\nHEPSI GECTI ({PASS} test)")


if __name__ == "__main__":
    main()
