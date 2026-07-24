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
    "realized_performance": bot.realized_performance,
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
    rows = list(bot.RECENT_SIGNALS)
    assert rows[0]["suppressed"] is True
    assert rows[0]["suppression_reason"] == "scan_push_cap"
    assert rows[1]["push_allowed"] is True
    assert rows[2]["suppression_reason"] == "confidence_below_threshold"
    assert all(r.get("event_id") and r.get("schema_version") == 2 for r in rows)
    ok("guven esigi + push bayragi")


def test_overflow_summary_fanout():
    old_enabled = bot.ENABLE_TELEGRAM
    old_subscribers = bot.TELEGRAM_SUBSCRIBERS
    old_email = bot.ENABLE_EMAIL
    old_sender = bot._telegram_send_text
    sent = []
    bot.ENABLE_TELEGRAM = True
    bot.ENABLE_EMAIL = False
    bot.TELEGRAM_SUBSCRIBERS = ["111", "222"]
    bot._telegram_send_text = lambda text, chat_id=None: sent.append(chat_id)
    try:
        bot._send_overflow_summary([{
            "strategy": "S1", "symbol": "BTCUSDT", "price": 1,
            "horizon_hours": 24,
        }])
    finally:
        bot.ENABLE_TELEGRAM = old_enabled
        bot.ENABLE_EMAIL = old_email
        bot.TELEGRAM_SUBSCRIBERS = old_subscribers
        bot._telegram_send_text = old_sender
    assert sent == ["111", "222"]
    ok("tasma ozeti tum Telegram abonelerine fanout")


def test_state_persistence(tmpdir):
    bot.STATE_FILE = Path(tmpdir) / "state.json"
    bot.RECENT_SIGNALS.clear()
    st = bot.ScanState()
    st.prev_cond[("S1", "BTCUSDT")] = True
    st.last_fire[("S3", "ETHUSDT")] = 123.0
    bot.RECENT_SIGNALS.appendleft({
        "strategy": "S1", "symbol": "BTCUSDT", "direction": "LONG",
        "bar_time": "2026-07-19T12:00:00+00:00",
        "notified_at": "2026-07-19T12:00:01+00:00",
        "price": 100.0, "horizon_hours": 24,
    })
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
    now = bot.time.time()
    bot.LAST_SPOT_AT.update({"PEPEUSDT": now, "BTCUSDT": now})

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
    # Yazma basarisizsa saat kilidi kurulmamali; sonraki dongu tekrar deneyebilsin.
    bot.ARCHIVE_DIR = Path(tmpdir) / "olmayan" / "alt"
    bot._last_archive_hour = None
    bot.archive_market_state()
    assert bot._last_archive_hour is None
    ok("piyasa arsivi (1000x olcek + saat kilidi)")


def test_daily_summary_includes_perf():
    sent = []
    bot._telegram_send_text = lambda text, chat_id=None: sent.append(text)
    bot.ENABLE_TELEGRAM = True
    bot.DAILY_SUMMARY_HOUR_UTC = 0
    bot._last_summary_day = None
    bot.realized_performance = lambda max_signals=30, fetch_missing=True: {
        "n_total": 4, "fetch_errors": 0,
        "strategies": {"S1": {"n": 4, "median_pct": 1.2, "mean_pct": 1.0,
                              "winrate_pct": 75, "bt_median_pct": 0.93,
                              "bt_winrate_pct": 62}}}
    try:
        bot._maybe_daily_summary()
        assert sent and "Gunluk ozet" in sent[0]
        assert "karne" in sent[0] and "+1.20%" in sent[0]
    finally:
        bot.realized_performance = ORIG["realized_performance"]
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
    bot.LAST_SPOT_AT["BBBUSDT"] = bot.time.time()
    d = bot.build_dashboard_data()
    rows = {r["symbol"]: r for r in d["signals"]}
    assert rows["AAAUSDT"]["status"] == "OLGUN"
    assert rows["AAAUSDT"]["pnl_pct"] == 2.5       # cache'ten gerceklesen
    assert rows["BBBUSDT"]["status"] == "AKTIF"
    assert abs(rows["BBBUSDT"]["pnl_pct"] - 5.0) < 0.01   # 210/200-1
    assert rows["BBBUSDT"]["price_stale"] is False
    assert rows["BBBUSDT"]["remaining_h"] is not None
    s1 = next(s for s in d["strategies"] if s["name"] == "S1")
    assert s1["live_n"] == 1 and s1["live_med"] == 2.5
    assert s1["bt_med"] == 0.67 and "test" in s1["bt_scope"]
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
    bot.LAST_SPOT_AT["BBBUSDT"] = (
        bot.time.time() - (bot.PRICE_STALE_AFTER_MINUTES * 60 + 1))
    stale = {r["symbol"]: r for r in bot.build_dashboard_data()["signals"]}
    assert stale["BBBUSDT"]["price_stale"] is True
    assert stale["BBBUSDT"]["pnl_pct"] is None
    ok("pano verisi + docs/why + sablon (LAN & Pages fetch)")


def test_exact_strategy_performance_and_median(tmpdir):
    log = Path(tmpdir) / "perf-signals.log"
    now = bot.datetime.now(bot.timezone.utc)
    signals = []
    values = [
        ("S1", "AUSDT", 1.0, "spot"),
        ("S1", "BUSDT", 3.0, "spot"),
        ("S1+S4", "CUSDT", 5.0, "spot"),
        ("S2", "DUSDT", -2.0, "um_perp"),
    ]
    cache = {}
    for i, (strategy, symbol, ret, market) in enumerate(values):
        sig = {
            "strategy": strategy, "symbol": symbol, "direction": "LONG",
            "bar_time": (now - bot.timedelta(hours=100 + i)).isoformat(),
            "horizon_hours": 24, "performance_market": market,
        }
        signals.append(sig)
        cache[bot._perf_key(sig)] = {
            "return_pct": ret, "entry": 100.0, "exit": 100.0 + ret,
            "market": market,
        }
    log.write_text("\n".join(json.dumps(s) for s in signals) + "\n",
                   encoding="utf-8")
    bot.SIGNAL_LOG = str(log)
    bot.PERF_CACHE_FILE = Path(tmpdir) / "perf-cache-v2.json"
    bot.PERF_CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    perf = bot.realized_performance(max_signals=10)
    assert set(perf["strategies"]) == {"S1", "S1+S4", "S2"}
    assert perf["strategies"]["S1"]["median_pct"] == 2.0
    assert perf["strategies"]["S1+S4"]["n"] == 1
    assert perf["strategies"]["S2"]["performance_market"] == "um_perp"
    # Cache yokken S2 mutlaka USD-M perp fetcher'ini kullanmali.
    s2 = {
        "strategy": "S2", "symbol": "EUSDT", "direction": "LONG",
        "bar_time": (now - bot.timedelta(hours=100)).isoformat(),
        "horizon_hours": 72, "performance_market": "um_perp",
    }
    log.write_text(json.dumps(s2) + "\n", encoding="utf-8")
    bot.PERF_CACHE_FILE = Path(tmpdir) / "empty-perf-cache.json"
    bot.PERF_CACHE_FILE.write_text("{}", encoding="utf-8")
    old_spot, old_fut = bot.fetch_klines_at, bot.fetch_futures_klines_at
    called = []
    bars = [{"open_time": i, "open": 100.0, "close": 101.0}
            for i in range(74)]
    bot.fetch_klines_at = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("S2 spot fetcher kullanmamalı"))
    bot.fetch_futures_klines_at = lambda *a, **k: called.append("um") or bars
    try:
        fetched = bot.realized_performance(max_signals=10)
    finally:
        bot.fetch_klines_at, bot.fetch_futures_klines_at = old_spot, old_fut
    assert called == ["um"] and "S2" in fetched["strategies"]
    ok("tam strateji performansi + gercek medyan + piyasa ayrimi")


def test_spot_rate_limit_backoff():
    calls = []

    class R:
        def __init__(self, status, data):
            self.status_code = status
            self.headers = {"Retry-After": "0"}
            self._data = data

        def raise_for_status(self):
            if self.status_code >= 400:
                err = bot.requests.HTTPError(f"HTTP {self.status_code}")
                err.response = self
                raise err

        def json(self):
            return self._data

    responses = [R(429, {}), R(200, {"ok": True})]

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return responses.pop(0)

    old_get = bot.requests.get
    bot.requests.get = fake_get
    bot._spot_host_idx = 0
    old_retries = bot.SPOT_MAX_RETRIES
    bot.SPOT_MAX_RETRIES = 2
    try:
        result = bot._spot_get("/api/v3/test")
    finally:
        bot.SPOT_MAX_RETRIES = old_retries
        bot.requests.get = old_get
    assert result.json()["ok"] is True
    assert len(calls) == 2 and calls[0].split("/api")[0] == calls[1].split("/api")[0]
    ok("spot 429 backoff (host atlamadan)")


def test_scan_isolates_non_network_symbol_errors():
    old_scan, old_symbols = bot.scan_symbol, bot.SYMBOLS
    bot.SYMBOLS = ["BADUSDT", "GOODUSDT"]

    def fake_scan(symbol, state):
        if symbol == "BADUSDT":
            raise ValueError("bozuk API semasi")
        return []

    bot.scan_symbol = fake_scan
    try:
        count = bot.scan_all(bot.ScanState())
    finally:
        bot.scan_symbol, bot.SYMBOLS = old_scan, old_symbols
    assert count == 0 and bot.LAST_SCAN_ERRORS == 1
    assert any("BADUSDT" in e for e in bot.ERROR_SAMPLES)
    ok("sembol-bazli beklenmeyen hata izolasyonu")


def test_scan_rejects_total_market_outage():
    old_scan, old_symbols = bot.scan_symbol, bot.SYMBOLS
    bot.SYMBOLS = ["AUSDT", "BUSDT", "CUSDT"]
    bot.scan_symbol = lambda symbol, state: (_ for _ in ()).throw(
        bot.requests.ConnectionError("piyasa yok"))
    try:
        try:
            bot.scan_all(bot.ScanState())
            raise AssertionError("tam veri kesintisi basarili sayilmamali")
        except RuntimeError as e:
            assert "yetersiz piyasa veri kapsami" in str(e)
        assert bot.LAST_SCAN_ERRORS == 3
        assert bot.LAST_SCAN_SUCCEEDED_SYMBOLS == 0
        assert bot.LAST_SCAN_ERROR_RATIO == 1.0
    finally:
        bot.scan_symbol, bot.SYMBOLS = old_scan, old_symbols
    ok("tam piyasa kesintisi basarisiz tarama")


def test_true_price_time_and_s2_perp_market():
    old_klines = bot.fetch_klines
    old_funding = bot.fetch_funding
    old_price = bot.fetch_futures_price
    base_ms = 1_720_000_000_000
    bot.fetch_klines = lambda symbol, limit=250: [
        {"open_time": base_ms + i * 3_600_000, "open": 100.0,
         "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0}
        for i in range(250)
    ]
    bot.fetch_funding = lambda symbol, limit=3: [
        {"time": base_ms + i * 8 * 3_600_000, "rate": -0.001}
        for i in range(3)
    ]
    bot.fetch_futures_price = lambda symbol: 123.45
    try:
        signals = bot.scan_symbol("BTCUSDT", bot.ScanState(), snapshot=True)
    finally:
        bot.fetch_klines = old_klines
        bot.fetch_funding = old_funding
        bot.fetch_futures_price = old_price
    expected_close = (base_ms + 249 * 3_600_000 + 3_600_000) / 1000
    assert bot.LAST_SPOT_AT["BTCUSDT"] == expected_close
    s2 = next(sig for sig in signals if sig["strategy"] == "S2")
    assert s2["signal_market"] == "um_perp"
    assert s2["performance_market"] == "um_perp"
    assert s2["price"] == 123.45 and s2["price_source"] == "futures_ticker"
    ok("gercek mum zamani + S2 perp fiyat temeli")


def test_instance_file_lock(tmpdir):
    old_path = bot.INSTANCE_LOCK_PATH
    bot.INSTANCE_LOCK_PATH = Path(tmpdir) / "instance.lock"
    first = second = None
    try:
        first = bot._acquire_instance_file_lock()
        second = bot._acquire_instance_file_lock()
        assert first is not None
        assert second is None
    finally:
        bot._release_instance_file_lock(second)
        bot._release_instance_file_lock(first)
        bot.INSTANCE_LOCK_PATH = old_path
    ok("tek-instance dosya kilidi")


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
    orig_futures_price = bot.fetch_futures_price
    bot.fetch_futures_price = lambda symbol: 100.0
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
        assert s1["confidence_note"] in bot._signal_why(s1)
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
        bot.fetch_futures_price = orig_futures_price
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
        bot.SIGNAL_LOG = str(Path(td) / "signals.log")
        test_confidence()
        test_zero_division_guards()
        test_snapshot_isolation()
        test_notify_gating_and_push_flag()
        test_overflow_summary_fanout()
        test_state_persistence(td)
        test_ref_lines()
        test_disabled_strategies_and_header()
        test_command_security()
        test_market_archiver(td)
        test_daily_summary_includes_perf()
        test_dashboard_data(td)
        test_exact_strategy_performance_and_median(td)
        test_spot_rate_limit_backoff()
        test_scan_isolates_non_network_symbol_errors()
        test_scan_rejects_total_market_outage()
        test_true_price_time_and_s2_perp_market()
        test_instance_file_lock(td)
        test_extended_universe_rules()
        test_github_publish()
        test_perf_formatting()
    print(f"\nHEPSI GECTI ({PASS} test)")


if __name__ == "__main__":
    main()
