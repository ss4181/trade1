"""Local, deterministic linear-perp risk arithmetic; NOT a hold/close predictor.

Reads only a manually supplied JSON file. No exchange, API key, notifications,
public export, inferred quantity or fake account PnL.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path


def assess(position):
    def price(name, required=False):
        x = position.get(name)
        if x is None and not required:
            return None
        if isinstance(x, bool):
            raise ValueError('invalid_price')
        v = float(x)
        if not math.isfinite(v) or v <= 0:
            raise ValueError('invalid_price')
        return v
    if position.get('direction') not in {'LONG', 'SHORT'}:
        raise ValueError('invalid_direction')
    if position.get('margin_mode') not in {'cross', 'isolated'}:
        raise ValueError('invalid_margin_mode')
    symbol = position.get('symbol')
    if not isinstance(symbol, str) or not symbol.isalnum():
        raise ValueError('invalid_symbol')
    entry, mark = price('entry_price', True), price('mark_price', True)
    stop, target, liquidation = (price(k) for k in ('stop_price', 'target_price', 'liquidation_price'))
    long = position['direction'] == 'LONG'
    sign = 1 if long else -1
    warnings = []
    if stop is None:
        warnings.append('NO_STOP_PRICE_RECORDED')
    elif (mark <= stop if long else mark >= stop):
        warnings.append('USER_STOP_LEVEL_BREACHED_EXECUTION_UNCONFIRMED')
    target_return = sign*(target/entry-1)*100 if target else None
    if target_return is not None and target_return <= 0:
        warnings.append('TARGET_IS_NOT_A_PROFIT_FROM_ENTRY')
    if liquidation is None:
        warnings.append('LIQUIDATION_PRICE_UNKNOWN_NOT_ZERO_RISK')
    elif (mark <= liquidation if long else mark >= liquidation):
        warnings.append('MARK_AT_OR_BEYOND_REPORTED_LIQUIDATION')
    if position['margin_mode'] == 'cross':
        warnings.append('CROSS_MARGIN_ACCOUNT_RISK_NOT_MODELED')
    quote_at = position.get('mark_observed_at')
    if quote_at is None:
        warnings.append('QUOTE_TIME_UNKNOWN_NOT_LIVE')
    else:
        stamp = datetime.fromisoformat(quote_at.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('quote_timezone_required')
        age = (datetime.now(timezone.utc)-stamp).total_seconds()
        if age < 0 or age > 60:
            warnings.append('QUOTE_STALE_OR_FUTURE_NOT_LIVE')
    return dict(symbol=symbol, direction=position['direction'], margin_mode=position['margin_mode'],
        entry_price=entry, mark_price=mark, price_return_pct=sign*(mark/entry-1)*100,
        price_change_needed_to_entry_pct=(entry/mark-1)*100,
        target_price_return_from_entry_pct=target_return,
        liquidation_distance_pct=sign*(mark-liquidation)/mark*100 if liquidation else None,
        warnings=warnings, action='MANUAL_REVIEW_NOT_A_CLOSE_OR_HOLD_FORECAST',
        recovery_probability=None, account_roi=None, dollar_pnl=None, funding='not_modeled',
        fees='not_modeled', source='manual_snapshot_not_exchange_verified')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--file', type=Path, required=True)
    args = ap.parse_args()
    try:
        rows = json.loads(args.file.read_bytes())
        if not isinstance(rows, list):
            raise ValueError('positions_must_be_list')
        print(json.dumps([assess(r) for r in rows], ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, TypeError, KeyError, OSError, OverflowError, AttributeError):
        # Never print malformed input excerpts, account data or exception strings.
        print('Pozisyon verisi okunamadı: fiyat, yön, margin modu ve zaman alanlarını kontrol et.')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
