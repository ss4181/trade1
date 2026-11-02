"""Owner /g2 command: mute/unmute G2 Telegram alerts without a terminal — offline."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import configure_notifications as settings
import signal_bot as bot


class G2CommandTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / ".notification_preferences.json"
        self.sent = []
        self.owner = True
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(bot, "NOTIFICATION_PREFERENCES_PATH", self.path))
        stack.enter_context(patch.object(bot, "G2_PUSH", True))
        stack.enter_context(patch.object(bot, "_is_owner", lambda chat_id: self.owner))
        stack.enter_context(patch.object(bot, "_telegram_send_text",
                                         lambda text, chat_id=None, **kw: self.sent.append(text)))

    def test_owner_mutes_and_unmutes_immediately_and_persistently(self):
        settings.enable(self.path)
        bot.handle_telegram_command("/g2 kapat", "1")
        self.assertFalse(bot.G2_PUSH)
        self.assertEqual(settings.load(self.path)["G2_PUSH"], "false")
        self.assertIn("SUSTURULDU", self.sent[-1])
        bot.handle_telegram_command("/g2", "1")
        self.assertIn("sessiz", self.sent[-1])
        bot.handle_telegram_command("/g2 ac", "1")
        self.assertTrue(bot.G2_PUSH)
        self.assertEqual(settings.load(self.path)["G2_PUSH"], "true")

    def test_non_owner_cannot_change(self):
        settings.enable(self.path)
        self.owner = False
        bot.handle_telegram_command("/g2 kapat", "2")
        self.assertTrue(bot.G2_PUSH)
        self.assertEqual(settings.load(self.path)["G2_PUSH"], "true")
        self.assertIn("yalniz bot sahibine", self.sent[-1])

    def test_env_only_setup_is_not_changed_silently(self):
        bot.handle_telegram_command("/g2 kapat", "1")
        self.assertTrue(bot.G2_PUSH)
        self.assertFalse(self.path.exists())
        self.assertIn(".env", self.sent[-1])

    def test_corrupt_profile_is_not_overwritten(self):
        self.path.write_text('{"profile":"x"}', encoding="utf-8")
        bot.handle_telegram_command("/g2 kapat", "1")
        self.assertTrue(bot.G2_PUSH)
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"profile":"x"}')
        self.assertIn("okunamadı", self.sent[-1])


if __name__ == "__main__":
    unittest.main()
