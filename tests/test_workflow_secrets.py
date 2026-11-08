"""Cloud workflows keep secrets on the steps that use them — offline text checks."""
from pathlib import Path
import unittest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def split_workflow(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    head, body = text.split("\n    steps:\n", 1)
    return head, ["      - name:" + block for block in body.split("      - name:")[1:]]


def secret_steps(steps):
    return [block.split("\n", 1)[0].replace("      - name:", "").strip()
            for block in steps if "secrets." in block]


class WorkflowSecretTests(unittest.TestCase):
    def test_cloud_scanner_exposes_secrets_only_to_steps_that_need_them(self):
        head, steps = split_workflow("trade1-cloud.yml")
        self.assertNotIn("secrets.", head)
        self.assertEqual(secret_steps(steps), ["Send Telegram connection test",
                                               "Report successful scan to Serhan Lab",
                                               "Report failed scan to Serhan Lab"])

    def test_watchdog_exposes_secrets_only_to_its_check(self):
        head, steps = split_workflow("trade1-watchdog.yml")
        self.assertNotIn("secrets.", head)
        self.assertEqual(secret_steps(steps), ["Tabletin son taramasini kontrol et"])

    def test_cloud_cache_excludes_recipients_and_message_queue(self):
        _, steps = split_workflow("trade1-cloud.yml")
        cache = next(block for block in steps if "actions/cache@" in block)
        self.assertNotIn(".subscribers.json", cache)
        self.assertNotIn(".notification_outbox.json", cache)


if __name__ == "__main__":
    unittest.main()
