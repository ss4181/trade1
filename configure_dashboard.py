"""Set dashboard publication cadence without displaying or changing credentials."""
import argparse
from pathlib import Path
import re


def configure(path, minutes):
    if type(minutes) is not int or not 5 <= minutes <= 60:
        raise ValueError("minutes_must_be_between_5_and_60")
    path = Path(path)
    content = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = [line for line in content.splitlines()
             if not re.match(r"^\s*(?:export\s+)?PUBLISH_INTERVAL_MIN\s*=", line)]
    lines.append(f"PUBLISH_INTERVAL_MIN={minutes}")
    tmp = path.with_name(".env.dashboard.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args()
    configure(Path(__file__).with_name(".env"), args.minutes)
    print(f"Pano yayın aralığı kaydedildi: {args.minutes} dakika.")
    print(f"Bu terminalde: export PUBLISH_INTERVAL_MIN={args.minutes}")
    print("Uygulamak için botu yeniden başlat.")
