"""Cevrimdisi test paketi — ag/anahtar GEREKMEZ, ~5 saniyede biter.

Her degisiklikten sonra calistir:  python tests/offline_tests.py
Botun kritik davranislarini dogrular; hepsi gecmeden push etme.
"""

import base64
import json
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import signal_bot as bot  # noqa: E402
import qc_export as qc  # noqa: E402

# testler modulu monkeypatch'ler; orijinalleri sakla ki sonraki testler
# oncekilerin sahtelerini cagirmasin
ORIG = {
    "send_tg": bot.send_telegram_message,
    "tg_text": bot._telegram_send_text,
    "realized_performance": bot.realized_performance,
    "handle_cmd": bot.handle_telegram_command,
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
    # S2 kosulu aktif oldugunda scan_symbol perpetual ticker fiyatini da okur.
    # Bu test tamamen offline olmali; aksi halde gercek Binance agina sizar.
    bot.fetch_futures_price = lambda symbol: 100.0
    bot.scan_symbol("TESTUSDT", st, snapshot=True)
    assert not st.prev_cond and not st.last_fire
    bot.scan_symbol("TESTUSDT", st, snapshot=False)
    assert st.prev_cond
    ok("snapshot izolasyonu / canli state")


def test_notify_gating_and_push_flag():
    pushed = []
    def delivered(s):
        pushed.append(("tg", s["strategy"]))
        return True
    bot.send_telegram_message = delivered
    bot.RECENT_SIGNALS.clear()
    base = {"direction": "LONG", "strength": "NORMAL", "price": 1,
            "bar_time": "2026-07-19T12:00:00+00:00", "note": "n",
            "horizon_hours": 24, "symbol": "X"}
    bot.notify({**base, "strategy": "S2", "confidence": "DUSUK"})
    bot.notify({**base, "strategy": "S1", "confidence": "YUKSEK"})
    bot.notify({**base, "strategy": "S1", "confidence": "YUKSEK"}, push=False)
    assert len(bot.RECENT_SIGNALS) == 3          # hepsi tamponda
    assert pushed == [("tg", "S1")]                    # yalniz 1 push
    rows = list(bot.RECENT_SIGNALS)
    assert rows[0]["suppressed"] is True
    assert rows[0]["suppression_reason"] == "scan_push_cap"
    assert rows[1]["push_allowed"] is True
    assert rows[2]["suppression_reason"] == "confidence_below_threshold"
    assert all(r.get("event_id") and r.get("schema_version") == 2 for r in rows)
    assert len(bot.PRICE_TARGET_STATE["events"]) == 1, \
        "yalniz gercekten teslim edilen S1 hedef takibine girmeli"
    ok("guven esigi + push bayragi")


def test_coin_price_target_tracking(tmpdir):
    """TP2/TP3 coinin fiyat degisimidir; dedupe, zamanlama ve hata izolasyonu."""
    old_file = bot.PRICE_TARGET_STATE_FILE
    old_state = bot.PRICE_TARGET_STATE
    old_enabled = bot.PRICE_TARGET_TRACKING_ENABLED
    old_levels = bot.PRICE_TARGET_LEVELS_PCT
    old_fetch = bot.fetch_price_target_klines
    try:
        bot.PRICE_TARGET_STATE_FILE = Path(tmpdir) / "price-targets.json"
        bot.PRICE_TARGET_STATE = bot._empty_price_target_state()
        bot.PRICE_TARGET_TRACKING_ENABLED = True
        bot.PRICE_TARGET_LEVELS_PCT = (2.0, 3.0, 5.0, 10.0)
        record = {
            "event_id": "a" * 32, "strategy": "S1", "symbol": "BTCUSDT",
            "direction": "LONG", "price": 100.0, "horizon_hours": 24,
            "notified_at": "2026-08-01T12:01:00+00:00",
            "push_allowed": True, "performance_market": "spot",
        }
        profile = bot._register_price_targets(record)
        assert profile and profile["basis"] == "signal_notification_price"
        assert [t["level_pct"] for t in profile["targets"]] == [2, 3, 5, 10]
        assert all(abs(got - want) < 1e-9 for got, want in zip(
            [t["price"] for t in profile["targets"]],
            [102.0, 103.0, 105.0, 110.0]))
        # 12:01 bildirimi: 12:00-12:05 mumu sayilmaz; ilk tam mum 12:05'tir.
        event = bot.PRICE_TARGET_STATE["events"][record["event_id"]]
        assert event["next_start_ms"] == 1785585900000
        assert bot._register_price_targets(record) is not None
        assert len(bot.PRICE_TARGET_STATE["events"]) == 1

        start = event["next_start_ms"]
        gap_event = json.loads(json.dumps(event))
        assert bot._apply_price_target_bars(gap_event, [{
            "open_time": start + 300_000, "high": 110.0, "low": 90.0,
            "close_time": start + 599_999,
        }], start + 600_000) == []
        assert gap_event["next_start_ms"] == start, \
            "eksik fiyat yolu hedef/miss olarak uydurulmamali"
        first_hits = bot._apply_price_target_bars(event, [{
            "open_time": start, "high": 102.2, "low": 98.7,
            "close_time": start + 299_999,
        }], start + 300_000)
        assert first_hits == ["2"]
        assert event["targets"]["2"]["hit_at"]
        assert event["targets"]["3"]["hit_at"] is None
        assert event["max_favorable_pct"] == 2.2
        assert event["max_adverse_pct"] == -1.3
        assert event["targets"]["2"]["max_adverse_before_hit_pct"] == -1.3
        assert event["targets"]["2"]["minutes_to_hit_upper"] == 5.0
        assert bot._apply_price_target_bars(event, [], start + 300_000) == []

        second_hits = bot._apply_price_target_bars(event, [{
            "open_time": start + 300_000, "high": 103.1, "low": 99.5,
            "close_time": start + 599_999,
        }], start + 600_000)
        assert second_hits == ["3"] and event["status"] == "active"
        third_hits = bot._apply_price_target_bars(event, [{
            "open_time": start + 600_000, "high": 110.1, "low": 99.0,
            "close_time": start + 899_999,
        }], start + 900_000)
        assert third_hits == ["5", "10"]
        # Aktif olaylarda erken kazanan / geç kalan sansürü oranı şişirmemeli.
        pending_summary = bot.price_target_summary()
        assert pending_summary["S1"]["2"]["resolved"] == 0
        assert pending_summary["S1"]["2"]["pending_hit"] == 1
        event["status"] = "expired"
        summary = bot.price_target_summary()
        assert summary["S1"]["2"]["hit_rate_pct"] == 100.0
        assert summary["S1"]["3"]["resolved"] == 1
        assert summary["S1"]["5"]["median_adverse_before_hit_pct"] == -1.3
        assert bot.price_path_summary()["S1"]["median_mfe_pct"] == 10.1
        assert bot.price_target_for_event(record["event_id"])["targets"][1][
            "status"] == "HIT"

        missed = {**record, "event_id": "d" * 32, "symbol": "SOLUSDT"}
        bot._register_price_targets(missed)
        bot.PRICE_TARGET_STATE["events"][missed["event_id"]][
            "status"] = "expired"
        summary = bot.price_target_summary()
        assert summary["S1"]["2"]["hit"] == 1
        assert summary["S1"]["2"]["missed"] == 1
        assert summary["S1"]["2"]["hit_rate_pct"] == 50.0

        suppressed = {**record, "event_id": "b" * 32,
                      "push_allowed": False}
        assert bot._register_price_targets(suppressed) is None
        preview = {**record, "event_id": "e" * 32, "symbol": "XRPUSDT"}
        assert bot._register_price_targets(preview, persist=False) is not None
        assert preview["event_id"] not in bot.PRICE_TARGET_STATE["events"]

        # Piyasa/API hatasi ana taramaya yayilmaz.
        failing = {**record, "event_id": "c" * 32, "symbol": "ETHUSDT",
                   "notified_at": "2026-08-01T13:01:00+00:00"}
        bot._register_price_targets(failing)
        bot.fetch_price_target_klines = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("offline hata"))
        result = bot.update_price_target_tracking(
            bot.datetime.fromisoformat("2026-08-01T13:20:00+00:00"))
        assert result["errors"] == 1
        assert "offline hata" in bot.PRICE_TARGET_STATE["events"][
            failing["event_id"]]["last_error"]
        ok("coin fiyati TP2/3/5/10 (sansur + MFE/MAE + hata izolasyonu)")
    finally:
        bot.PRICE_TARGET_STATE_FILE = old_file
        bot.PRICE_TARGET_STATE = old_state
        bot.PRICE_TARGET_TRACKING_ENABLED = old_enabled
        bot.PRICE_TARGET_LEVELS_PCT = old_levels
        bot.fetch_price_target_klines = old_fetch


def test_overflow_summary_fanout():
    old_enabled = bot.ENABLE_TELEGRAM
    old_subscribers = bot.TELEGRAM_SUBSCRIBERS
    old_sender = bot._telegram_send_text
    sent = []
    bot.ENABLE_TELEGRAM = True
    bot.TELEGRAM_SUBSCRIBERS = ["111", "222"]
    bot._telegram_send_text = lambda text, chat_id=None: sent.append(chat_id)
    try:
        bot._send_overflow_summary([{
            "strategy": "S1", "symbol": "BTCUSDT", "price": 1,
            "horizon_hours": 24,
        }])
    finally:
        bot.ENABLE_TELEGRAM = old_enabled
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
        if "premiumIndex" in url:
            return R([{"symbol": "1000PEPEUSDT", "markPrice": "0.002",
                       "indexPrice": "0.00199", "lastFundingRate": "-0.0002",
                       "nextFundingTime": 1700000000000, "time": 1699999999000},
                      {"symbol": "BTCUSDT", "markPrice": "60055",
                       "indexPrice": "60000", "lastFundingRate": "0.0001",
                       "nextFundingTime": 1700000000000, "time": 1699999999000}])
        if "openInterest" in url:
            return R({"openInterest": "12345.6", "time": 1699999999000})
        if "globalLongShortAccountRatio" in url:
            return R([{"longShortRatio": "0.75", "longAccount": "0.4286",
                       "shortAccount": "0.5714", "timestamp": 1699999800000}])
        if "takerlongshortRatio" in url:
            return R([{"buySellRatio": "1.25", "buyVol": "125",
                       "sellVol": "100", "timestamp": 1699999800000}])
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
    assert pepe["global_ls_ratio"] == 0.75
    assert pepe["taker_buy_sell_ratio"] == 1.25
    assert pepe["funding_rate_snapshot"] == -0.0002
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
    assert rows["AAAUSDT"]["gross_pnl_pct"] == 2.5
    assert rows["AAAUSDT"]["pnl_pct"] == 2.38      # 12bp sonrasi NET
    assert rows["BBBUSDT"]["status"] == "AKTIF"
    assert abs(rows["BBBUSDT"]["gross_pnl_pct"] - 5.0) < 0.01
    assert abs(rows["BBBUSDT"]["pnl_pct"] - 4.88) < 0.01
    assert rows["BBBUSDT"]["price_stale"] is False
    assert rows["BBBUSDT"]["remaining_h"] is not None
    s1 = next(s for s in d["strategies"] if s["name"] == "S1")
    assert s1["live_n"] == 1 and s1["live_med"] == 2.38
    assert s1["live_cohorts"][0]["sample_warning"] == "small_sample"
    assert s1["bt_med"] == 0.67 and "test" in s1["bt_scope"]
    assert d["status"]["interval_min"] == bot.SCAN_INTERVAL_MINUTES
    # zenginlestirilmis alanlar: docs (tiklanabilir strateji) + why (neden geldi)
    assert "S1" in d["docs"] and "Nasil" in d["docs"]["S1"]["how"] or \
        "calisir" in d["docs"]["S1"]["how"] or d["docs"]["S1"]["how"]
    assert d["docs"]["S1+S4"]["title"]
    assert "S5" in d["docs"] and "backtest YOK" in d["docs"]["S5"]["stats"]
    aktif_row = rows["BBBUSDT"]
    assert "Log-hacim z-skoru" in aktif_row["why"]      # S3 aciklamasi
    assert "RSI(14)" in rows["AAAUSDT"]["why"]           # S1 aciklamasi
    # şablon + iki fetch modu + filtrelenebilir kalite yüzeyi
    assert "{{DATA_URL}}" in bot.DASHBOARD_HTML_TEMPLATE
    assert '"/api/dashboard"' in bot.dashboard_html()
    assert '"./data.json"' in bot.dashboard_html("./data.json")
    page = bot.dashboard_html()
    assert "Benim başarı kriterim" in page and 'id="fSearch"' in page
    assert 'id="fTarget"' in page and "TP2/3/5/10" in page
    assert "Aktif olaylar hedef oranının paydasına girmez" in page
    bot.LAST_SPOT_AT["BBBUSDT"] = (
        bot.time.time() - (bot.PRICE_STALE_AFTER_MINUTES * 60 + 1))
    stale = {r["symbol"]: r for r in bot.build_dashboard_data()["signals"]}
    assert stale["BBBUSDT"]["price_stale"] is True
    assert stale["BBBUSDT"]["pnl_pct"] is None
    ok("pano verisi + docs/why + sablon (LAN & Pages fetch)")


def test_exact_strategy_performance_and_median(tmpdir):
    log = Path(tmpdir) / "perf-signals.log"
    now = bot.datetime.now(bot.timezone.utc)
    # realized_performance evren filtresi uygular; onceki testler SYMBOLS'u
    # mutasyona ugratabildigi icin bu testin evrenini ACIKCA kur.
    bot.SYMBOLS = [s.strip() for s in bot.DEFAULT_SYMBOLS.split(",") if s.strip()]
    signals = []
    values = [
        # Semboller YAPILANDIRILMIS evrenden olmali: realized_performance
        # artik evren disi kayitlari olcume katmiyor (Ek F filtresi).
        ("S1", "BTCUSDT", 1.0, "spot"),
        ("S1", "ETHUSDT", 3.0, "spot"),
        ("S1+S4", "SOLUSDT", 5.0, "spot"),
        ("S2", "XRPUSDT", -2.0, "um_perp"),
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
    s1_cohort = next(c for c in perf["cohorts"] if c["strategy"] == "S1")
    assert s1_cohort["universe"] == "core30"
    assert s1_cohort["config_version"] == "legacy"
    assert s1_cohort["net_median_pct"] == 1.88
    assert s1_cohort["sample_warning"] == "small_sample"
    s2_cohort = next(c for c in perf["cohorts"] if c["strategy"] == "S2")
    assert s2_cohort["performance_market"] == "um_perp"
    assert s2_cohort["funding_cost_status"] == "not_modeled"
    # Cache yokken S2 mutlaka USD-M perp fetcher'ini kullanmali.
    s2 = {
        "strategy": "S2", "symbol": "ADAUSDT", "direction": "LONG",
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


def test_s3_shadow_market_regime():
    """Rejim etiketi kapanmis 1d mumdan gelir ama S3 kosulunu filtrelemez."""
    old = (bot._spot_get, bot.fetch_klines, bot.fetch_funding,
           bot.fetch_futures_price, bot.bullish_divergence,
           set(bot.DISABLED_STRATEGIES), dict(bot.MARKET_REGIME),
           bot._last_market_regime_refresh)

    class R:
        def json(self):
            now_ms = int(bot.time.time() * 1000)
            day = 86_400_000
            return [
                [now_ms - (202 - i) * day, "0", "0", "0", str(100 + i),
                 "0", now_ms - (201 - i) * day]
                for i in range(201)
            ]

    try:
        bot._spot_get = lambda *a, **k: R()
        bot._last_market_regime_refresh = 0.0
        assert bot.refresh_market_regime_if_due(force=True) is True
        assert bot.MARKET_REGIME["label"] == "BULL"

        bot.fetch_klines = lambda symbol, limit=250: [
            {"open_time": i * 3_600_000,
             "open": 99.0 if i == 249 else 100.0,
             "high": 102.0, "low": 98.0, "close": 101.0 if i == 249 else 100.0,
             "volume": 1e100 if i == 249 else 10.0}
            for i in range(250)
        ]
        bot.fetch_funding = lambda *a, **k: []
        bot.fetch_futures_price = lambda symbol: 100.0
        bot.bullish_divergence = lambda *a, **k: False
        bot.DISABLED_STRATEGIES = set()
        sigs = bot.scan_symbol("BTCUSDT", bot.ScanState(), snapshot=True)
        s3 = next(s for s in sigs if s["strategy"] == "S3")
        assert s3["market_regime"] == "BULL"
        assert s3["market_regime_source"] == "btc_1d_close_vs_sma200_shadow"
        assert any(label.startswith("Piyasa rejimi")
                   for label, _ in bot._signal_detail_rows(s3))
    finally:
        (bot._spot_get, bot.fetch_klines, bot.fetch_funding,
         bot.fetch_futures_price, bot.bullish_divergence,
         bot.DISABLED_STRATEGIES, regime, bot._last_market_regime_refresh) = old
        bot.MARKET_REGIME.clear()
        bot.MARKET_REGIME.update(regime)
    ok("S3 shadow piyasa rejimi (kapali 1d mum; filtre yok)")


def test_join_approval_flow(tmpdir):
    """/katil -> sahip /onayla akisi + yetki sinirlari."""
    old = (bot.SUBSCRIBERS_FILE, list(bot.TELEGRAM_SUBSCRIBERS),
           dict(bot.DYNAMIC_SUBSCRIBERS), dict(bot.PENDING_JOINS),
           bot.TELEGRAM_CHAT_ID, list(bot.TELEGRAM_ALLOWED),
           bot._telegram_send_text, bot.ENABLE_TELEGRAM, bot.TELEGRAM_OPEN)
    sent = []
    try:
        # onceki testler handle_telegram_command'i sahteyle degistirmis olabilir
        bot.handle_telegram_command = ORIG["handle_cmd"]
        bot.SUBSCRIBERS_FILE = Path(tmpdir) / "subs.json"
        bot.TELEGRAM_CHAT_ID = "111"
        bot.TELEGRAM_ALLOWED = ["222"]         # env tabani (silinemez)
        bot.TELEGRAM_SUBSCRIBERS = ["111", "222"]
        bot.DYNAMIC_SUBSCRIBERS = {}
        bot.PENDING_JOINS = {"999": "Ahmet @ahmet"}
        bot.ENABLE_TELEGRAM = True
        bot.TELEGRAM_OPEN = False
        bot._telegram_send_text = lambda text, chat_id=None: sent.append(
            (chat_id, text))

        # 1) ARKADAS (222) onaylayamaz — yetki yukseltme engeli
        bot.handle_telegram_command("/onayla 999", "222")
        assert "yalniz bot sahibine" in sent[-1][1]
        assert "999" not in bot.TELEGRAM_SUBSCRIBERS

        # 2) SAHIP (111) onaylar -> abone olur, dosyaya yazilir, ikisi bilgilenir
        sent.clear()
        bot.handle_telegram_command("/onayla 999", "111")
        assert "999" in bot.TELEGRAM_SUBSCRIBERS
        assert bot.SUBSCRIBERS_FILE.exists()
        assert json.loads(bot.SUBSCRIBERS_FILE.read_text(
            encoding="utf-8"))["subscribers"]["999"].startswith("Ahmet")
        assert {c for c, _ in sent} == {"111", "999"}   # sahibe + yeni uyeye
        assert "999" not in bot.PENDING_JOINS           # bekleyenden dustu
        assert bot._chat_allowed("999") is True         # komut da verebilir

        # 3) Yeniden baslatmada dosyadan geri yuklenir
        bot.TELEGRAM_SUBSCRIBERS = ["111", "222"]
        bot.DYNAMIC_SUBSCRIBERS = {}
        bot._load_subscribers()
        assert "999" in bot.TELEGRAM_SUBSCRIBERS

        # 4) Kaldirma: dinamik olan gider, env/sahip KORUNUR
        assert bot.remove_subscriber("999") is True
        assert bot.remove_subscriber("222") is False    # env tabani
        assert bot.remove_subscriber("111") is False    # sahip
        assert "111" in bot.TELEGRAM_SUBSCRIBERS
    finally:
        (bot.SUBSCRIBERS_FILE, bot.TELEGRAM_SUBSCRIBERS,
         bot.DYNAMIC_SUBSCRIBERS, bot.PENDING_JOINS, bot.TELEGRAM_CHAT_ID,
         bot.TELEGRAM_ALLOWED, bot._telegram_send_text, bot.ENABLE_TELEGRAM,
         bot.TELEGRAM_OPEN) = old
    ok("katilim onay akisi (yetki yukseltme engelli, kalici)")


def test_buttons_and_callbacks(tmpdir):
    """Kalici menu dugmeleri + satir-ici onay dugmeleri (yetki dahil)."""
    old = (bot.SUBSCRIBERS_FILE, list(bot.TELEGRAM_SUBSCRIBERS),
           dict(bot.DYNAMIC_SUBSCRIBERS), dict(bot.PENDING_JOINS),
           bot.TELEGRAM_CHAT_ID, list(bot.TELEGRAM_ALLOWED),
           bot._telegram_send_text, bot.handle_telegram_command,
           bot.ENABLE_TELEGRAM, bot.TELEGRAM_OPEN, bot.requests.post)
    sent, answered = [], []
    try:
        bot.handle_telegram_command = ORIG["handle_cmd"]
        bot.SUBSCRIBERS_FILE = Path(tmpdir) / "subs-btn.json"
        bot.TELEGRAM_CHAT_ID = "111"
        bot.TELEGRAM_ALLOWED = []
        bot.TELEGRAM_SUBSCRIBERS = ["111", "222"]
        bot.DYNAMIC_SUBSCRIBERS = {}
        bot.PENDING_JOINS = {"999": "Ayse @ayse"}
        bot.ENABLE_TELEGRAM = True
        bot.TELEGRAM_OPEN = False
        bot._telegram_send_text = (
            lambda text, chat_id=None, reply_markup=None:
            sent.append((chat_id, text, reply_markup)) or True)
        bot._telegram_answer_callback = (
            lambda cq_id, text="": answered.append(text))

        # 1) /start kalici menu klavyesi gonderir; sahip ekstra dugme gorur
        bot.handle_telegram_command("/start", "111")
        markup = sent[-1][2]
        assert markup and markup["resize_keyboard"] is True
        flat_owner = [b for row in markup["keyboard"] for b in row]
        assert "🔎 Kontrol" in flat_owner and "👥 Aboneler" in flat_owner
        sent.clear()
        bot.handle_telegram_command("/start", "222")     # arkadas
        flat_friend = [b for row in sent[-1][2]["keyboard"] for b in row]
        assert "👥 Aboneler" not in flat_friend          # yonetim dugmesi yok

        # 2) Dugme etiketi -> komut eslemesi eksiksiz ve gecerli
        for label, cmd in bot.MENU_BUTTONS.items():
            assert cmd.startswith("/") and label.strip()

        # 3) YABANCI/arkadas dugmeye basarsa onay OLMAZ (yetki yukseltme engeli)
        bot.handle_callback_query({"id": "c1", "data": "ok:999",
                                   "from": {"id": 222},
                                   "message": {"chat": {"id": 222}}})
        assert "999" not in bot.TELEGRAM_SUBSCRIBERS
        assert "yalniz bot sahibine" in answered[-1]

        # 4) SAHIP basarsa: abone olur, iki taraf bilgilenir, yeni uyeye de
        #    menu klavyesi gider
        sent.clear(); answered.clear()
        bot.handle_callback_query({"id": "c2", "data": "ok:999",
                                   "from": {"id": 111},
                                   "message": {"chat": {"id": 111}}})
        assert "999" in bot.TELEGRAM_SUBSCRIBERS
        assert "Onaylandi" in answered[-1]
        new_member = [s for s in sent if s[0] == "999"]
        assert new_member and new_member[-1][2]["keyboard"]

        # 5) Reddet: bekleyenden dusurur, abone yapmaz
        bot.PENDING_JOINS["888"] = "Veli"
        answered.clear()
        bot.handle_callback_query({"id": "c3", "data": "no:888",
                                   "from": {"id": 111},
                                   "message": {"chat": {"id": 111}}})
        assert "888" not in bot.PENDING_JOINS
        assert "888" not in bot.TELEGRAM_SUBSCRIBERS
        assert "Reddedildi" in answered[-1]

        # 6) Bozuk callback verisi sessizce yutulur (istisna firlatmaz)
        answered.clear()
        bot.handle_callback_query({"id": "c4", "data": "saskin",
                                   "from": {"id": 111},
                                   "message": {"chat": {"id": 111}}})
        assert answered and "Gecersiz" in answered[-1]

        # 7) reply_markup gercekten API payload'ina giriyor mu
        captured = {}

        class R:
            def raise_for_status(self): pass
        bot._telegram_send_text = ORIG["tg_text"]
        bot.TELEGRAM_BOT_TOKEN = "T"
        bot.requests.post = (lambda url, json=None, timeout=None:
                             captured.update(json or {}) or R())
        bot._telegram_send_text("x", chat_id="111",
                                reply_markup=bot._menu_keyboard(True))
        assert "reply_markup" in captured and captured["reply_markup"]["keyboard"]
    finally:
        (bot.SUBSCRIBERS_FILE, bot.TELEGRAM_SUBSCRIBERS,
         bot.DYNAMIC_SUBSCRIBERS, bot.PENDING_JOINS, bot.TELEGRAM_CHAT_ID,
         bot.TELEGRAM_ALLOWED, bot._telegram_send_text,
         bot.handle_telegram_command, bot.ENABLE_TELEGRAM, bot.TELEGRAM_OPEN,
         bot.requests.post) = old
    ok("dugmeler: menu klavyesi + satir-ici onay (yetki korumali)")


def test_notify_health_visibility():
    """Gonderim basarisiz olursa panoda/health'te GORUNMELI (2026-07-26
    teshisinde sinyaller uretildi ama sessizce gonderilemedi)."""
    old = (bot._telegram_send_text, bot.requests.post, bot.ENABLE_TELEGRAM,
           bot.TELEGRAM_BOT_TOKEN, dict(bot.NOTIFY_HEALTH["telegram"]),
           bot.requests.get, bot.TELEGRAM_IDENTITY)
    try:
        bot._telegram_send_text = ORIG["tg_text"]
        bot.ENABLE_TELEGRAM = True
        bot.TELEGRAM_BOT_TOKEN = "GIZLI_TOKEN"
        bot.NOTIFY_HEALTH["telegram"] = {"ok": 0, "fail": 0, "last_ok": None,
                                         "last_error": None}

        class Bad:
            status_code = 401
            def raise_for_status(self):
                err = bot.requests.HTTPError(
                    "401 Unauthorized for bot GIZLI_TOKEN/sendMessage")
                err.response = self
                raise err

        bot.requests.post = lambda url, json=None, timeout=None: Bad()
        assert bot._telegram_send_text("x", chat_id="1") is False
        h = bot.NOTIFY_HEALTH["telegram"]
        assert h["fail"] == 1 and h["last_error"]
        assert "GIZLI_TOKEN" not in h["last_error"]     # sir redakte

        # basarili gonderimde ok sayaci ve last_ok dolar
        class Good:
            def raise_for_status(self): pass
        bot.requests.post = lambda url, json=None, timeout=None: Good()
        assert bot._telegram_send_text("y", chat_id="1") is True
        assert bot.NOTIFY_HEALTH["telegram"]["ok"] == 1
        assert bot.NOTIFY_HEALTH["telegram"]["last_ok"]

        # preflight gecersiz token'i aciktan isaretler
        class BadGet:
            def raise_for_status(self):
                raise bot.requests.HTTPError("401 Unauthorized")
        bot.requests.get = lambda url, timeout=None: BadGet()
        bot.telegram_preflight()
        assert bot.TELEGRAM_IDENTITY.startswith("GECERSIZ")

        # panoda gorunuyor mu
        st = bot.build_dashboard_data(max_rows=1)["status"]
        for key in ("telegram_enabled", "telegram_identity", "notify_health"):
            assert key in st, key
        assert st["notify_health"]["telegram"]["fail"] >= 1
    finally:
        (bot._telegram_send_text, bot.requests.post, bot.ENABLE_TELEGRAM,
         bot.TELEGRAM_BOT_TOKEN, bot.NOTIFY_HEALTH["telegram"],
         bot.requests.get, bot.TELEGRAM_IDENTITY) = old
    ok("bildirim saglik izleme (sessiz gonderim hatasi artik gorunur)")


def test_github_publish():
    calls = []
    branches = {"main"}
    files = {}

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
    bot.GITHUB_PAGES_BRANCH = "gh-pages"
    bot.GITHUB_DATA_BRANCH = "trade1-data"
    bot.PUBLISH_ENABLED = True
    bot._last_publish = 0.0
    bot._gh_sha = None
    bot.build_dashboard_data = lambda: {"ok": 1}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(("GET", url, (params or {}).get("ref")))
        if "/git/ref/heads/" in url:
            branch = url.rsplit("/", 1)[-1]
            if branch in branches:
                return R(200, {"object": {"sha": f"{branch}-sha"}})
            return R(404)
        if url.endswith("/repos/u/r"):
            return R(200, {"default_branch": "main"})
        if "/contents/" in url:
            path = url.split("/contents/", 1)[1]
            sha = files.get(((params or {}).get("ref"), path))
            return R(200, {"sha": sha}) if sha else R(404)
        return R(404)
    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append(("POST", url, json.get("ref")))
        branches.add(json["ref"].rsplit("/", 1)[-1])
        return R(201, {})
    def fake_put(url, json=None, timeout=None, headers=None):
        calls.append(("PUT", url, json.get("branch")))
        assert "ghsecret" in headers["Authorization"]
        assert "content" in json and "message" in json
        content = base64.b64decode(json["content"])
        sha = bot._git_blob_sha(content)
        files[(json["branch"], url.split("/contents/", 1)[1])] = sha
        return R(200, {"content": {"sha": sha}})
    bot.requests.get = fake_get
    bot.requests.post = fake_post
    bot.requests.put = fake_put
    bot.publish_to_github(force=True)
    # Iki branch de ilk yayinda otomatik olusturulur.
    assert any(c[0] == "POST" and c[2] == "refs/heads/gh-pages" for c in calls)
    assert any(c[0] == "POST" and c[2] == "refs/heads/trade1-data" for c in calls)
    puts = [c for c in calls if c[0] == "PUT"]
    branches_by_path = {c[1].rsplit("/", 1)[-1]: c[2] for c in puts}
    assert branches_by_path == {"index.html": "gh-pages",
                                "data.json": "trade1-data"}
    assert bot._gh_sha == files[("trade1-data", "data.json")]
    # Icerik degismediyse ikinci yayinda hicbir dosya yeniden gonderilmez.
    before = len(puts)
    bot._last_publish = 0.0
    bot.publish_to_github(force=True)
    assert len([c for c in calls if c[0] == "PUT"]) == before
    # token loglarda sizmamali
    assert bot._redact("hata ghsecret var") == "hata ***TOKEN*** var"
    ok("github pages yayini (statik/data branch ayrimi + degisiklik kontrolu)")


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


def test_observation_channel(tmpdir):
    """Gozlem kanali: S1-yalniz, GOZLEM- oneki, referans YOK, ayri kova,
    dogrulanmis istatistigi kirletmiyor, qc_export'a sizmiyor."""
    called = {"funding": 0}
    bot.fetch_funding = lambda symbol, limit=3: called.__setitem__(
        "funding", called["funding"] + 1) or [
        {"time": i, "rate": -0.01} for i in range(3)]
    closes = [1000 - i for i in range(250)]
    bot.fetch_klines = lambda symbol, limit=250: [
        {"open_time": i * 3600000, "open": closes[i] + 0.5, "high": closes[i] + 1,
         "low": closes[i] - 1, "close": closes[i], "volume": 10}
        for i in range(250)]
    orig_div = bot.bullish_divergence
    orig_push = bot.OBSERVE_PUSH
    bot.bullish_divergence = lambda c, l, r, i: True
    bot.DISABLED_STRATEGIES = set()
    try:
        sigs = bot.scan_symbol("ZZZFAKEUSDT", bot.ScanState(),
                               snapshot=True, observe=True)
        assert called["funding"] == 0, "gozlem kanalinda funding cekilmemeli"
        strats = {s["strategy"] for s in sigs}
        assert strats and strats <= bot.OBSERVE_STRATEGIES, \
            f"gozlem sinyalleri yalniz S5/S6 olmali: {strats}"
        # dogrulanmis adlarla ASLA karismamali (perf kovasi ayri kalsin)
        assert not (strats & {"S1", "S1+S4", "S2", "S3"})
        sig = sigs[0]
        assert sig["confidence"] == "GOZLEM" and sig["observe"] is True
        assert sig["universe"] == "observe"
        # backtest referanslari GOSTERILMEMELI (cekirdek-30 dagilimi gecersiz)
        assert "ref" not in sig and bot._ref_lines(sig) == []
        assert bot._observe_lines(sig) and "DOGRULANMAMIS" in bot._observe_lines(sig)[0]
        # pano "neden geldi": uyari basta, S1 aciklamasi yine de gelmeli
        why = bot._signal_why(sig)
        assert why.startswith("S5/S6") and "DOGRULANMAMIS" in why, why
        assert "RSI(14)" in why, "S1 aciklamasi da gelmeli: " + why
        # GOZLEM kademesi her push esiginin altinda
        assert bot.CONF_RANK["GOZLEM"] < min(
            v for k, v in bot.CONF_RANK.items() if k != "GOZLEM")

        # push kapisi CONF_RANK'a degil OBSERVE_PUSH'a bagli
        bot.OBSERVE_PUSH = True
        rec = bot._delivery_record(sig, push=True)
        assert rec["push_allowed"] is True, "OBSERVE_PUSH acikken gitmeli"
        bot.OBSERVE_PUSH = False
        rec = bot._delivery_record(sig, push=True)
        assert rec["push_allowed"] is False
        assert rec["suppression_reason"] == "observe_channel_silent"
        # dogrulanmis sinyal esikten etkilenmeye devam etmeli
        low = {"strategy": "S2", "confidence": "DUSUK"}
        assert bot._delivery_record(low, push=True)["push_allowed"] is False

        # /performans: gozlem AYRI blokta, S1 satiriyla karismaz
        txt = bot._format_performance({
            "n_total": 8, "fetch_errors": 0,
            "strategies": {
                "S1": {"n": 5, "median_pct": 1.1, "mean_pct": 1.5,
                       "winrate_pct": 60, "bt_median_pct": 0.93,
                       "bt_winrate_pct": 62},
                "S6": {"n": 3, "median_pct": -9.0, "mean_pct": -8.0,
                       "winrate_pct": 33}}})
        assert "Gozlem kanali" in txt and "DOGRULANMAMIS" in txt
        assert txt.index("<b>S1</b>") < txt.index("Gozlem kanali"), \
            "gozlem satirlari dogrulanmis bloktan SONRA gelmeli"
        assert "backtest medyan" in txt.split("Gozlem kanali")[0]
        assert "backtest medyan" not in txt.split("Gozlem kanali")[1], \
            "gozlem satirinda karsilastirilacak backtest OLMAMALI"

        # olcum: evren disi olmasina ragmen gozlem kaydi kovaya girmeli
        log = Path(tmpdir) / "observe.log"
        old_log, old_cache = bot.SIGNAL_LOG, bot.PERF_CACHE_FILE
        bar = (bot.datetime.now(bot.timezone.utc)
               - bot.timedelta(hours=48)).replace(microsecond=0)
        try:
            bot.SIGNAL_LOG = str(log)
            bot.PERF_CACHE_FILE = Path(tmpdir) / ".observe_cache.json"
            rows = []
            for strat, sym, obs in (("S6", "ZZZFAKEUSDT", True),
                                    ("S1", "QQQFAKEUSDT", False)):
                r = {"strategy": strat, "symbol": sym, "direction": "LONG",
                     "bar_time": bar.isoformat(), "horizon_hours": 24,
                     "price": 100.0}
                if obs:
                    r["observe"] = True
                rows.append(json.dumps(r))
            log.write_text("\n".join(rows) + "\n", encoding="utf-8")
            bot.fetch_klines_at = lambda symbol, start_ms, limit: [
                {"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0}
                for _ in range(limit)]
            perf = bot.realized_performance()
            assert "S6" in perf["strategies"], perf
            assert "S1" not in perf["strategies"], \
                "evren disi dogrulanmis kayit hala karantinada olmali"
            assert perf["excluded_out_of_universe"] == 1
        finally:
            bot.SIGNAL_LOG, bot.PERF_CACHE_FILE = old_log, old_cache

        # gozlem evreni state'te KALICI olmali: --once (bulut, 5dk'da bir)
        # her turda fetch_universe()'u tekrar cagirirsa gunde ~864 agir
        # API cagrisi olur ve paylasimli IP yasaklanir.
        old_state, old_syms, old_ref = (bot.STATE_FILE, bot.OBSERVE_SYMBOLS,
                                        bot._last_observe_refresh)
        try:
            bot.STATE_FILE = Path(tmpdir) / ".observe_state.json"
            bot.OBSERVE_SYMBOLS = ["ZZZFAKEUSDT", "QQQFAKEUSDT"]
            bot._last_observe_refresh = 1234567.0
            bot.ScanState().save()
            bot.OBSERVE_SYMBOLS, bot._last_observe_refresh = [], 0.0
            bot.ScanState.load()
            assert bot.OBSERVE_SYMBOLS == ["ZZZFAKEUSDT", "QQQFAKEUSDT"], \
                bot.OBSERVE_SYMBOLS
            assert bot._last_observe_refresh == 1234567.0
            # taze liste varken yenileme AGIR cagriyi YAPMAMALI
            called = {"n": 0}
            orig_fetch = bot.fetch_observe_universe
            bot.fetch_observe_universe = lambda: (
                called.__setitem__("n", called["n"] + 1) or ([], {}))
            try:
                bot._last_observe_refresh = bot.time.time()
                bot.refresh_observe_universe_if_due()
                assert called["n"] == 0, "taze listede yeniden indirme olmamali"
                bot._last_observe_refresh = 0.0
                bot.refresh_observe_universe_if_due()
                assert called["n"] == 1, "bayat listede yenilenmeli"
            finally:
                bot.fetch_observe_universe = orig_fetch

            # AYAR degisirse onbellek gecersiz olmali; yoksa OBSERVE_TOP_N'i
            # degistirmek 24 saat boyunca hicbir sey yapmaz (2026-08-04).
            old_n = bot.OBSERVE_TOP_N
            try:
                bot.OBSERVE_SYMBOLS = ["AUSDT", "BUSDT"]
                bot._last_observe_refresh = bot.time.time()
                bot.ScanState().save()
                bot.OBSERVE_TOP_N = old_n + 7        # ayar degisti
                bot.ScanState.load()
                assert bot._last_observe_refresh == 0.0, \
                    "ayar degisince liste bayat sayilmali"
                # ayar ayniysa taze kalmali
                bot._last_observe_refresh = bot.time.time()
                bot.ScanState().save()
                bot.ScanState.load()
                assert bot._last_observe_refresh > 0.0, \
                    "ayar aynidayken gereksiz yenileme olmamali"
            finally:
                bot.OBSERVE_TOP_N = old_n
        finally:
            (bot.STATE_FILE, bot.OBSERVE_SYMBOLS,
             bot._last_observe_refresh) = old_state, old_syms, old_ref

        # qc_export: gozlem kayitlari arastirma paketine SIZMAMALI
        # Uc kapinin her biri tek basina tutmali: isim, eski onek, observe
        # bayragi. Biri unutulursa gozlem kaydi arastirma paketine sizar.
        for rec in ({"strategy": "S6", "observe": True},
                    {"strategy": "S5"},                 # yalniz isim
                    {"strategy": "GOZLEM-S1"},          # eski kayitlar
                    {"strategy": "S1", "observe": True}):  # yalniz bayrak
            events, rejected = qc._parse_events(
                [json.dumps({**rec, "symbol": "ZZZFAKEUSDT",
                             "direction": "LONG", "price": 1.0,
                             "bar_time": bar.isoformat(),
                             "horizon_hours": 24})],
                configured_symbols={"ZZZFAKEUSDT"}, core_symbols=set(),
                extended_symbols=set(), config_version="t",
                confidence_rank=bot.CONF_RANK, min_confidence="ORTA")
            assert events == [] and len(rejected) == 1, rec
            assert rejected[0]["rejection_reason"] == "observation_channel", rec
    finally:
        bot.bullish_divergence = orig_div
        bot.OBSERVE_PUSH = orig_push
    ok("gozlem kanali (S1-yalniz, ayri kova, referans yok, qc sizintisi yok)")


def main():
    with tempfile.TemporaryDirectory() as td:
        bot.SIGNAL_LOG = str(Path(td) / "signals.log")
        bot.PRICE_TARGET_STATE_FILE = Path(td) / "price-target-state.json"
        bot.PRICE_TARGET_STATE = bot._empty_price_target_state()
        test_confidence()
        test_zero_division_guards()
        test_snapshot_isolation()
        test_notify_gating_and_push_flag()
        test_coin_price_target_tracking(td)
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
        test_s3_shadow_market_regime()
        test_observation_channel(td)
        test_join_approval_flow(td)
        test_buttons_and_callbacks(td)
        test_notify_health_visibility()
        test_github_publish()
        test_perf_formatting()
    print(f"\nHEPSI GECTI ({PASS} test)")


if __name__ == "__main__":
    main()
