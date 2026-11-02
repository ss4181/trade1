"""Report provenance: unavailable is not zero or evidence of a missing archive."""
import copy
import json
import unittest
from datetime import datetime, timezone

import research_report_delivery as delivery


class ResearchReportStateTests(unittest.TestCase):
    def test_missing_snapshot_is_unknown_not_empty_archive(self):
        report = delivery.public_state({})
        self.assertIsNone(report['last_archive']['rows'])
        self.assertIsNone(report['last_archive']['symbols'])
        self.assertFalse(report['archive_snapshot_available'])
        self.assertEqual(report['last_status'], 'not_run')

    def test_legacy_week_is_not_a_confirmed_delivery_or_scheduled_replay(self):
        state={'last_week':'2026-W42'}
        before=copy.deepcopy(state)
        report=delivery.public_state(state)
        self.assertEqual(report['last_status'],'legacy_unverified')
        self.assertEqual(report['delivery_evidence'],'legacy_period_only')
        self.assertIsNone(report['last_sent_at_utc'])
        self.assertIsNone(report['last_archive']['rows'])
        self.assertFalse(delivery.weekly_due(state,'2026-W42',datetime(2026,10,15,tzinfo=timezone.utc)))
        self.assertEqual(state,before)

    def test_old_monthly_ack_does_not_fabricate_archive_snapshot(self):
        report=delivery.public_state({'last_status':'sent','last_sent_at_utc':'2026-09-30T20:13:10Z'})
        self.assertEqual(report['last_status'],'sent')
        self.assertEqual(report['delivery_evidence'],'telegram_api_ack')
        self.assertIsNone(report['last_archive']['rows'])
        self.assertFalse(report['archive_snapshot_available'])

    def test_genuine_empty_snapshot_preserves_zero(self):
        report=delivery.public_state({'last_status':'warning','archive_snapshot':{'rows':0,'symbols':0}})
        self.assertEqual(report['last_archive']['rows'],0)
        self.assertTrue(report['archive_snapshot_available'])

    def test_known_snapshot_and_ack_remain_valid(self):
        report=delivery.public_state({'last_status':'sent','last_sent_at_utc':'2026-10-12T09:00:00+03:00',
            'archive_snapshot':{'rows':120,'symbols':4,'last_record_at_utc':'2026-10-12T08:00:00+03:00'}})
        self.assertEqual(report['last_archive']['rows'],120)
        self.assertEqual(report['last_archive']['symbols'],4)
        self.assertEqual(report['last_archive']['last_record_at_utc'],'2026-10-12T05:00:00+00:00')
        self.assertEqual(report['delivery_evidence'],'telegram_api_ack')

    def test_invalid_legacy_week_not_publicly_copied(self):
        for week in ('SECRET_TOKEN','2026-W00','2026-W99','0000-W10',True):
            with self.subTest(week=week):
                report=delivery.public_state({'last_week':week})
                self.assertIsNone(report['legacy_week'])
                self.assertEqual(report['delivery_evidence'],'not_confirmed')

    def test_invalid_counts_are_unknown_instead_of_invented_numbers(self):
        for value in (-1,True,'5',float('nan'),float('inf')):
            with self.subTest(value=value):
                report=delivery.public_state({'archive_snapshot':{'rows':value,'symbols':value}})
                self.assertIsNone(report['last_archive']['rows'])
                self.assertFalse(report['archive_snapshot_available'])
                json.dumps(report,allow_nan=False)

    def test_arbitrary_metadata_and_secrets_are_excluded(self):
        state={'last_week':'2026-W42','token':'PRIVATE','path':'PRIVATE',
               'archive_snapshot':{'rows':1,'symbols':1,'token':'PRIVATE'}}
        self.assertNotIn('PRIVATE',json.dumps(delivery.public_state(state)))


if __name__=='__main__':unittest.main()
