"""Change only the project's close delay; never print .env contents."""
import argparse
from pathlib import Path
import re


def configure(path, seconds):
    if type(seconds) is not int or not 1 <= seconds <= 90:
        raise ValueError("seconds_must_be_between_1_and_90")
    path = Path(path)
    content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = [line for line in content.splitlines()
             if not re.match(r"^\s*(?:export\s+)?SCAN_CLOSE_DELAY_SECONDS\s*=", line)]
    lines.append(f"SCAN_CLOSE_DELAY_SECONDS={seconds}")
    tmp = path.with_name(".env.scan-timing.tmp")
    tmp.write_text("\n".join(lines)+"\n", encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seconds", type=int, required=True)
    args = p.parse_args()
    configure(Path(__file__).with_name(".env"), args.seconds)
    print(f"Project close delay saved: {args.seconds} seconds.")
    print(f"Run in this Termux shell: export SCAN_CLOSE_DELAY_SECONDS={args.seconds}")
    print("Restart the bot to apply. Existing processes retain their old environment.")
