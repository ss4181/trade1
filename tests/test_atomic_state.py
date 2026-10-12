from pathlib import Path
from unittest.mock import patch
import unittest

from atomic_state import replace_state


class AtomicStateTests(unittest.TestCase):
    def error(self, winerror=None):
        exc = PermissionError("synthetic_locked_file")
        if winerror is not None:
            exc.winerror = winerror
        return exc

    def test_transient_windows_lock_retries_atomically(self):
        with patch.object(Path, "replace", side_effect=[self.error(32), self.error(5), None]) as replace, patch("atomic_state.time.sleep") as sleep:
            replace_state(Path("temporary"), Path("target"))
        self.assertEqual(replace.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_permanent_error_is_not_swallowed(self):
        with patch.object(Path, "replace", side_effect=self.error(5)) as replace, patch("atomic_state.time.sleep"):
            with self.assertRaises(PermissionError):
                replace_state(Path("temporary"), Path("target"))
        self.assertEqual(replace.call_count, 6)

    def test_nonwindows_or_other_error_is_not_retried(self):
        for exc in (self.error(), OSError("disk_full")):
            with patch.object(Path, "replace", side_effect=exc) as replace, patch("atomic_state.time.sleep") as sleep:
                with self.assertRaises(type(exc)):
                    replace_state(Path("temporary"), Path("target"))
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
