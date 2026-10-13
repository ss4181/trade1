import json
import unittest
from position_risk import assess


class PositionRiskTests(unittest.TestCase):
    def position(self, **extra):
        return dict(symbol='COINUSDT', direction='LONG', entry_price=100,
                    mark_price=80, margin_mode='cross', **extra)

    def test_long_loss_and_recovery_not_roi_or_probability(self):
        r = assess(self.position())
        self.assertAlmostEqual(r['price_return_pct'], -20)
        self.assertAlmostEqual(r['price_change_needed_to_entry_pct'], 25)
        self.assertIsNone(r['account_roi'])
        self.assertIsNone(r['dollar_pnl'])
        self.assertIsNone(r['recovery_probability'])

    def test_target_below_entry_not_profit(self):
        r = assess(self.position(target_price=99))
        self.assertIn('TARGET_IS_NOT_A_PROFIT_FROM_ENTRY', r['warnings'])
        self.assertAlmostEqual(r['target_price_return_from_entry_pct'], -1)

    def test_unknown_liquidation_not_safe_and_cross_account_not_modeled(self):
        r = assess(self.position())
        self.assertIsNone(r['liquidation_distance_pct'])
        self.assertIn('CROSS_MARGIN_ACCOUNT_RISK_NOT_MODELED', r['warnings'])
        self.assertIn('NO_STOP_PRICE_RECORDED', r['warnings'])

    def test_stop_breach_does_not_claim_execution(self):
        r = assess(self.position(stop_price=90, liquidation_price=70))
        self.assertIn('USER_STOP_LEVEL_BREACHED_EXECUTION_UNCONFIRMED', r['warnings'])
        self.assertEqual(r['action'], 'MANUAL_REVIEW_NOT_A_CLOSE_OR_HOLD_FORECAST')

    def test_short_math(self):
        p = self.position()
        p.update(direction='SHORT', mark_price=120, target_price=90)
        r = assess(p)
        self.assertAlmostEqual(r['price_return_pct'], -20)
        self.assertAlmostEqual(r['price_change_needed_to_entry_pct'], -100/6)

    def test_nonfinite_and_zero_rejected(self):
        for value in (0, float('nan'), float('inf'), True):
            p = self.position()
            p['mark_price'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): assess(p)

    def test_secret_and_unknown_fields_never_echoed(self):
        p = self.position(api_key='DO_NOT_ECHO', roi=-123, quantity=999)
        self.assertNotIn('DO_NOT_ECHO', json.dumps(assess(p)))


if __name__ == '__main__': unittest.main()
