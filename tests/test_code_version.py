"""Running code version comes from .git files read once; never a subprocess."""
from pathlib import Path
import tempfile
import unittest

import signal_bot as bot

SHA = "49b830620123456789abcdef0123456789abcdef"


class CodeVersionTests(unittest.TestCase):
    def repo(self, root):
        git = Path(root) / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        return git

    def test_loose_ref_packed_ref_and_detached_head(self):
        with tempfile.TemporaryDirectory() as root:
            git = self.repo(root)
            (git / "refs" / "heads" / "main").write_text(SHA + "\n", encoding="utf-8")
            self.assertEqual(bot._git_code_version(Path(root)), "49b8306")
            (git / "refs" / "heads" / "main").unlink()
            (git / "packed-refs").write_text(f"# pack-refs\n{SHA} refs/heads/main\n", encoding="utf-8")
            self.assertEqual(bot._git_code_version(Path(root)), "49b8306")
            (git / "HEAD").write_text(SHA.replace("4", "5", 1) + "\n", encoding="utf-8")
            self.assertEqual(bot._git_code_version(Path(root)), "59b8306")

    def test_worktree_gitdir_file(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            git = self.repo(other)
            (git / "refs" / "heads" / "main").write_text(SHA, encoding="utf-8")
            (Path(root) / ".git").write_text(f"gitdir: {git}\n", encoding="utf-8")
            self.assertEqual(bot._git_code_version(Path(root)), "49b8306")

    def test_missing_or_garbage_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(bot._git_code_version(Path(root)), "UNKNOWN")
            git = self.repo(root)
            (git / "refs" / "heads" / "main").write_text("not-a-sha", encoding="utf-8")
            self.assertEqual(bot._git_code_version(Path(root)), "UNKNOWN")
            (git / "refs" / "heads" / "main").unlink()
            self.assertEqual(bot._git_code_version(Path(root)), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
