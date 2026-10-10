"""Read-only G1 entry report. No network, tuning, bot import or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from research.g1_entry_comparison import summarize, render_text

PROTOCOL = Path(__file__).with_name('G1_ENTRY_COMPARISON_PROTOCOL.md')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--state',type=Path,default=Path(__file__).resolve().parents[1]/'.price_target_state.json')
    source.add_argument('--replay-dir', type=Path, help='Old snapshot + verified 1m cache, NEVER forward OOS')
    parser.add_argument('--as-of', help='Timezone-qualified cutoff for reproducible forward reports')
    parser.add_argument('--format', choices=('json', 'text'), default='json')
    args=parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        if args.replay_dir:
            from research.g1_entry_replay import replay
            events, metadata = replay(args.replay_dir)
            report = summarize(events, as_of=metadata['as_of_utc'], mode='retrospective')
            report['provenance'] = metadata
        elif not args.state.exists():
            report = summarize([], as_of=args.as_of)
            report['input_status'] = 'state_missing'
        else:
            raw = args.state.read_bytes()
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('events'), dict):
                raise ValueError('invalid_state_shape')
            report = summarize(data['events'].values(), as_of=args.as_of)
            report['provenance'] = dict(input_sha256=hashlib.sha256(raw).hexdigest(), network_used=False)
        report['protocol_sha256'] = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
        print(render_text(report) if args.format == 'text' else json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        # Never echo JSON decoder excerpts, records, local paths or secrets.
        print('Rapor okunamadı: dosya biçimini, hash kanıtını ve zaman alanlarını kontrol edin.', file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
