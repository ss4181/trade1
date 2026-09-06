"""Run all offline suites in a temporary copy without .env, live state or network."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="trade1-tests-") as directory:
        copy = Path(directory)
        files = list(root.glob("*.py")) + [root / "dashboard.html"]
        files += list((root / "tests").rglob("*.py"))
        files += list((root / "research").glob("*.py"))
        for source in files:
            target = copy / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG",
            "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH"}}
        env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   ENABLE_TELEGRAM="false", PUBLISH_QC_ENABLED="false",
                   TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="", GITHUB_TOKEN="")
        suites = sorted(p for p in (copy / "tests").glob("*.py")
                        if p.name != "run_isolated.py")
        suites.append(copy / "research" / "test_methodology.py")
        failed = 0
        for suite in suites:
            code = ("import socket,runpy,sys; "
                    "socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('offline_test_network_blocked')); "
                    f"sys.path[:0]=[{str(copy)!r},{str(suite.parent)!r}]; "
                    f"sys.argv=[{str(suite)!r}]; runpy.run_path(sys.argv[0],run_name='__main__')")
            run = subprocess.run([sys.executable, "-B", "-c", code], cwd=copy,
                                 env=env, capture_output=True, text=True,
                                 encoding="utf-8", timeout=180)
            print(f"{'PASS' if run.returncode == 0 else 'FAIL'} {suite.name}", flush=True)
            if run.returncode:
                failed += 1
                print((run.stdout + run.stderr)[-12000:], flush=True)
            else:
                for line in run.stderr.splitlines():
                    if line.startswith(("Ran ", "OK")):
                        print(line, flush=True)
        print(f"Suites: {len(suites)}; failures: {failed}; live files/network untouched")
        return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
