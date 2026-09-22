"""Connection reuse and candle publication safety, without external traffic."""
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import Mock, patch
import requests
import signal_bot as bot
from market_http import MarketHttp


class ScanSpeedTests(unittest.TestCase):
    def test_buffered_sessions_reuse_and_keep_headers_per_request(self):
        session=Mock()
        client=MarketHttp(session_factory=lambda:session)
        client.get("https://example.test/one",headers={"X-MBX-APIKEY":"test"})
        client.get("https://example.test/two",params={"symbol":"BTCUSDT"})
        self.assertEqual(client.snapshot()["sessions_created"],1)
        self.assertEqual(client.snapshot()["session_reuses"],1)
        self.assertNotIn("headers",session.get.call_args.kwargs)
        self.assertEqual(session.cookies.clear.call_count,2)
        client.close()
        session.close.assert_called_once()

    def test_parallel_requests_never_share_session_and_idle_pool_is_bounded(self):
        barrier=threading.Barrier(3)
        sessions=[]
        def factory():
            session=Mock()
            session.get.side_effect=lambda *a,**k:barrier.wait(timeout=3)
            sessions.append(session)
            return session
        client=MarketHttp(max_idle=1,session_factory=factory)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _:client.get("https://example.test/"),range(3)))
        self.assertEqual(len(sessions),3)
        self.assertEqual(sum(s.close.call_count for s in sessions),2)
        self.assertEqual(client.snapshot()["idle_sessions"],1)
        client.close()

    def test_transport_failure_discards_connection_without_extra_retry(self):
        session=Mock()
        session.get.side_effect=requests.ConnectionError("offline")
        client=MarketHttp(session_factory=lambda:session)
        with self.assertRaises(requests.ConnectionError): client.get("https://example.test/")
        session.get.assert_called_once()
        session.close.assert_called_once()
        self.assertEqual(client.snapshot()["idle_sessions"],0)

    def test_rate_limit_still_honors_caller_retry_after(self):
        fail=Mock(status_code=429,headers={"Retry-After":"0"})
        fail.raise_for_status.side_effect=requests.HTTPError(response=fail)
        ok=Mock(status_code=200)
        with patch.object(bot,"_market_get",side_effect=[fail,ok]) as get, \
             patch.object(bot,"_spot_blocked_until",0),patch.object(bot,"SPOT_MAX_RETRIES",2), \
             patch.object(bot.time,"sleep"):
            self.assertIs(bot._spot_get("/api/v3/klines"),ok)
        self.assertEqual(get.call_count,2)

    def raw(self, latest, forming=True):
        rows=[[i*3600000,"100","102","99","101","20",(i+1)*3600000-1]
              for i in range(latest-248,latest+1)]
        if forming:
            i=latest+1
            rows.append([i*3600000,"100","99999","1","99999","999999",(i+1)*3600000-1])
        return rows

    def test_closed_window_same_with_or_without_forming_bar(self):
        response=Mock()
        outputs=[]
        with patch.object(bot,"_spot_get",return_value=response),patch.object(bot.time,"time",return_value=1000*3600+5):
            for forming in (True,False):
                response.json.return_value=self.raw(999,forming)
                outputs.append(bot.fetch_klines("BTCUSDT"))
        self.assertEqual(outputs[0],outputs[1])
        self.assertEqual(len(outputs[0]),249)
        self.assertEqual(outputs[0][-1]["close"],101.)

    def test_lagging_bar_retried_and_stale_failure_cannot_mutate_strategy_state(self):
        response=Mock()
        response.json.side_effect=[self.raw(998,False),self.raw(999)]
        with patch.object(bot,"_spot_get",return_value=response) as get, \
             patch.object(bot.time,"time",return_value=1000*3600+5),patch.object(bot.time,"sleep") as sleep:
            self.assertEqual(bot.fetch_klines("BTCUSDT")[-1]["open_time"],999*3600000)
            self.assertEqual(get.call_count,2)
            sleep.assert_called_once_with(1.)
            response.json.side_effect=None
            response.json.return_value=self.raw(998,False)
            state=bot.ScanState()
            with self.assertRaises(bot.StaleCandleError):bot.scan_symbol("BTCUSDT",state)
            self.assertEqual(state.prev_cond,{})
            self.assertEqual(state.last_fire,{})

    def test_five_second_slot_does_not_skip_hour_boundary(self):
        with patch.object(bot,"SCAN_CLOSE_DELAY_SECONDS",5),patch.object(bot,"SCAN_INTERVAL_MINUTES",5):
            self.assertEqual(bot._seconds_until_next_scan(3600),5)
            self.assertEqual(bot._seconds_until_next_scan(3604),1)
            self.assertEqual(bot._seconds_until_next_scan(3605),300)


if __name__=="__main__":unittest.main()
