"""Termux update widget: stray files never block, real edits and overwrites do."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


@unittest.skipUnless(shutil.which("sh") and shutil.which("git") and os.path.isdir("/proc/self"),
                     "needs POSIX sh, git and /proc (CI/Termux)")
class UpdateWidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = {**os.environ, **ENV, "HOME": str(self.tmp / "home"), "TMPDIR": str(self.tmp)}
        self.env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + self.env["PATH"]
        seed = self.tmp / "seed"
        self.git("init", "-q", "--bare", "-b", "main", str(self.tmp / "origin.git"))
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(seed))
        shutil.copytree(ROOT / "termux" / "widget", seed / "termux" / "widget")
        (seed / "termux" / "boot-signal-bot.sh").write_text("#!/bin/sh\nsleep 20\n")
        (seed / "signal_bot.py").write_text("print(1)\n")
        (seed / "signal_watch.py").write_text('CRITICAL_POLICY = "critical-reversal-v1"\n')
        self.commit(seed, "init")
        self.repo = self.tmp / "home" / "trade1"
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.repo))
        (seed / "signal_bot.py").write_text("print(2)\n")
        self.seed = seed

    def tearDown(self):
        subprocess.run(["pkill", "-f", str(self.repo / "termux" / "boot-signal-bot.sh")],
                       capture_output=True)

    def git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **ENV}, check=True,
                       capture_output=True)

    def commit(self, repo, message):
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-qm", message, cwd=repo)
        self.git("push", "-q", "origin", "main", cwd=repo)

    def update(self):
        return subprocess.run(["sh", "termux/widget/update-restart.sh"], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, timeout=120)

    def head(self):
        return subprocess.run(["git", "log", "-1", "--format=%s"], cwd=self.repo,
                              capture_output=True, text=True).stdout.strip()

    def test_stray_untracked_files_are_listed_but_do_not_block(self):
        self.commit(self.seed, "update")
        for name in ("Sarioglu:", "bot.out.log.1", "stop-signal-bot"):
            (self.repo / name).write_text("x")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Git disi dosyalar (dokunulmadi)", result.stdout)
        self.assertIn("Guncelleme tamamlandi", result.stdout)
        self.assertEqual(self.head(), "update")
        self.assertTrue((self.repo / "Sarioglu:").exists())

    def test_untracked_file_that_update_would_add_blocks_before_stopping(self):
        (self.seed / "newfile.txt").write_text("remote\n")
        self.commit(self.seed, "add")
        (self.repo / "newfile.txt").write_text("local\n")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uzerine yazacakti", result.stderr)
        self.assertNotIn("durduruluyor", result.stdout)
        self.assertEqual((self.repo / "newfile.txt").read_text(), "local\n")
        self.assertEqual(self.head(), "init")

    def test_tracked_local_edit_still_blocks(self):
        self.commit(self.seed, "update")
        with open(self.repo / "signal_watch.py", "a") as stream:
            stream.write("# local edit\n")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("yerel degisiklik", result.stderr)
        self.assertEqual(self.head(), "init")


if __name__ == "__main__":
    unittest.main()
