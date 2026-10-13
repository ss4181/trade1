"""Offline report of the separate alignment cohort; no bot/secret/network access."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from g1_alignment_shadow import summarize


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--state', type=Path, default=Path(__file__).resolve().parents[1]/'.g1_alignment_state.json')
    args = ap.parse_args()
    if not args.state.exists():
        print(json.dumps(dict(input_status='state_missing', validated=False, network_used=False)))
        return 0
    try:
        report = summarize(json.loads(args.state.read_bytes()), int(time.time()*1000))
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        print('Hizalama raporu okunamadı; canlı state değiştirilmedi.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
