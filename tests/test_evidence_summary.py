import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.evidence_summary import summarize, block_mean_interval


def row(event_id="e", **kwargs):
    item = {"event_id": event_id, "observed_at_ms": 1_735_689_600_000,
            "strategy": "S1", "direction": "LONG", "universe": "core30",
            "config_version": "v", "engine_config_hash": "enginehash",
            "evidence_source": "forward_confirmed_delivery",
            "outcome": {"status": "measured", "performance_market": "spot",
                        "measurement_version": "paper-barriers-v1", "execution_spec_hash": "spec",
                        "net_return_pct": 1.88, "net_ex_funding_return_pct": 1.88,
                        "tp_before_sl_lower": True, "tp_before_sl_upper": True}}
    item.update(kwargs)
    return item


class EvidenceTests(unittest.TestCase):
    def test_deduplicate_and_conflicting_outcomes_do_not_pick_winner(self):
        r = row()
        report = summarize([r, copy.deepcopy(r)])
        self.assertEqual(report["cohorts"][0]["n_total"], 1)
        other = copy.deepcopy(r)
        other["outcome"]["net_return_pct"] = -1.62
        report = summarize([r, other])
        self.assertEqual(report["cohorts"], [])
        self.assertEqual(report["rejected_counts"]["conflicting_duplicate"], 2)

    def test_never_pool_versions_universes_markets_or_targets(self):
        records = [row(str(i)) for i in range(6)]
        records[1]["universe"] = "extended59"
        records[2]["config_version"] = "v2"
        records[3]["engine_config_hash"] = "different"
        records[4]["outcome"]["execution_spec_hash"] = "tp3"
        records[5]["outcome"].update(performance_market="um_perp", net_return_pct=None)
        report = summarize(records)
        self.assertEqual(len(report["cohorts"]), 6)
        perp = next(c for c in report["cohorts"] if c["performance_market"] == "um_perp")
        self.assertIsNone(perp["net_win_rate_pct"])
        self.assertEqual(perp["n_full_net"], 0)
        self.assertEqual(perp["mean_net_ex_funding_pct"], 1.88)

    def test_pending_unknown_and_small_sample_remain_visible(self):
        r = row()
        del r["config_version"]
        other = row("p", config_version=None)
        other["outcome"].update(status="pending", net_return_pct=None,
                                net_ex_funding_return_pct=None,
                                tp_before_sl_lower=None, tp_before_sl_upper=None)
        c = summarize([r, other])["cohorts"][0]
        self.assertEqual(c["n_total"], 2)
        self.assertEqual(c["n_measured"], 1)
        self.assertEqual(c["n_pending"], 1)
        self.assertEqual(c["config_version"], "UNKNOWN")
        self.assertIn("small_sample", c["warnings"])
        self.assertIn("legacy_or_missing_provenance", c["warnings"])
        self.assertIsNone(c["mean_net_interval"])

    def test_deterministic_cluster_blocks_and_no_secret_passthrough(self):
        records = [row(str(i), observed_at_ms=1_735_689_600_000 + i*86_400_000,
                       token="SECRET_FIXTURE_NEVER_EXPORT", chat_id="PRIVATE_CHAT",
                       note="PRIVATE_NOTE") for i in range(35)]
        a = summarize(records, bootstrap_iterations=100)
        b = summarize(list(reversed(records)), bootstrap_iterations=100)
        self.assertEqual(a, b)
        rendered = json.dumps(a)
        self.assertNotIn("SECRET_FIXTURE", rendered)
        self.assertNotIn("PRIVATE_", rendered)
        interval = a["cohorts"][0]["mean_net_interval"]
        self.assertAlmostEqual(interval["low_pct"], 1.88)
        self.assertAlmostEqual(interval["high_pct"], 1.88)
        # 100 simultaneous correlated events do not make 100 independent days.
        self.assertIsNone(block_mean_interval([(1, 1.0)]*100, iterations=100))


if __name__ == "__main__":
    unittest.main()
