"""Chronological replay with an untouched final third; no parameter search."""
from collections import Counter
import json
import statistics
from datetime import datetime, timezone
from engine import DAY,HOUR,HASH,RULES,Regime,candidate,evaluate_limit


def summary(rows):
    measured=[r for r in rows if r['net_ex_funding_pct'] is not None]
    values=[r['net_ex_funding_pct'] for r in measured]
    return dict(n_signals=len(rows), n_measured=len(values),
        statuses=dict(Counter(r['status'] for r in rows)),
        mean_net_ex_funding_pct=statistics.mean(values) if values else None,
        median_net_ex_funding_pct=statistics.median(values) if values else None,
        positive_pct=100*sum(v>0 for v in values)/len(values) if values else None,
        worst_pct=min(values) if values else None,
        best_pct=max(values) if values else None,
        distinct_coins=len({r['coin'] for r in measured}))


def replay(store, assets, oi=None):
    btc_daily=store.candles('perp','BTC','1d')
    btc_hourly=store.candles('perp','BTC','1h')
    regime=Regime(btc_daily)
    trades=[]
    coverage=[]
    for asset in assets:
        market,coin=asset['market'],asset['coin']
        daily=market=='spot'
        interval='1d' if daily else '1h'
        rows=store.candles(market,coin,interval)
        benchmark=btc_daily if daily else btc_hourly
        btc={r['end']:r['c'] for r in benchmark}
        coverage.append(dict(market=market,coin=coin,display=asset['display'],bars=len(rows),
                             first_ms=rows[0]['t'] if rows else None,
                             last_ms=rows[-1]['end'] if rows else None))
        cooldown=0
        for i in range(59 if daily else 199,len(rows)):
            if rows[i]['end'] < cooldown:
                continue
            signal=candidate(rows[max(0,i-199):i+1],btc,regime,market,asset['display'],coin)
            if not signal:
                continue
            cooldown=signal['close_ms']+(28*DAY if daily else 48*HOUR)
            proxy=oi.change(asset,signal['close_ms'],daily) if oi else None
            for hours in signal['horizons_hours']:
                result=evaluate_limit(signal,rows[i+1:],hours)
                trades.append(dict(**result, strategy=signal['strategy'],market=market,
                    coin=coin,display=asset['display'],signal_ms=signal['close_ms'],hours=hours,
                    external_oi_change=proxy,rule_hash=HASH))
    groups={}
    for strategy in ('HL-S','HL-D'):
        source=[r for r in trades if r['strategy']==strategy]
        # Shared calendar split per strategy, not a different split per coin.
        series=[c for c in coverage if c['market']==('spot' if strategy=='HL-D' else 'perp') and c['first_ms'] is not None]
        if not series:
            continue
        start=min(c['first_ms'] for c in series)
        end=max(c['last_ms'] for c in series)
        split=int(start+(end-start)*2/3)
        for hours in ([24,48] if strategy=='HL-S' else [336,672]):
            selected=[r for r in source if r['hours']==hours]
            train=[r for r in selected if r['signal_ms']<split and (r['exit_ms'] or r['entry_ms'])<split]
            test=[r for r in selected if r['signal_ms']>=split]
            groups[f'{strategy}_{hours}h']={'split_ms':split,'development':summary(train),
                'heldout':summary(test), 'external_oi_up_heldout':summary([
                    r for r in test if r['external_oi_change'] is not None and r['external_oi_change']>=.01]),
                'external_oi_available_heldout':sum(r['external_oi_change'] is not None for r in test),
                'promotion':'NOT_VALIDATED',
                'reason':'current_universe_selection_bias; hypothetical_limits; forward_validation_required'}
    regime_counts=Counter(regime.at(r['end']) for r in btc_hourly)
    return dict(schema='hl-research-report-v1',rules=RULES,rule_hash=HASH,
        generated_at=datetime.now(timezone.utc).isoformat(), btc_hourly_regime=dict(regime_counts),
        provenance='Hyperliquid candles; optional historical Coinalyze OI labeled by venue',
        coverage=coverage,results=groups,trades=trades,
        limitations=['No guaranteed return or next-meme prediction.',
            'Current liquid universe is retrospective selection, not historical membership.',
            'Historical spread/depth unavailable: replay cannot reproduce the live book gate.',
            'Returns are per-signal unleveraged scenarios, not a portfolio equity curve.',
            'OI availability time is bar close plus one bar; actual publication latency unknown.',
            'External OI joins use exact ticker names, not verified token identities; exploratory context only.',
            'Perp outcomes exclude historical funding; not full net PnL.',
            'Limit penetration is a scenario; queue position and actual fills unknown.',
            'No optimization; two horizons per strategy and OI sensitivity all disclosed.'])


def markdown(report):
    def value(x):
        return '—' if x is None else f'{x:.2f}%'
    lines=['# Hyperliquid geçmiş veri raporu', '',
        f"Üretim (UTC): {report['generated_at']}",
        f"Motor kimliği: `{report['rule_hash']}`", '',
        '**Durum: NOT_VALIDATED — kârlılık kanıtlanmadı.**', '',
        '| Kural / ufuk | Bölüm | Aday | Ölçülen | Pozitif | Ortalama* | Medyan* | Coin |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for key,group in report['results'].items():
        for name in ('development','heldout','external_oi_up_heldout'):
            s=group[name]
            lines.append(f"| {key} | {name} | {s['n_signals']} | {s['n_measured']} | "
                f"{value(s['positive_pct'])} | {value(s['mean_net_ex_funding_pct'])} | "
                f"{value(s['median_net_ex_funding_pct'])} | {s['distinct_coins']} |")
    lines+=['','*Perpetual için funding hariç; spot için ücret/kayma sonrası varsayımsal sonuç. '
            'Satırlar portföy getirisi değildir. İki ufuk aynı adayları yeniden ölçer.', '',
            '## Kapsam', '',
            f"Piyasa serisi: {len(report['coverage'])}; toplam mum: "
            f"{sum(c['bars'] for c in report['coverage'])}.",
            'BTC saatlik rejim dağılımı: '+json.dumps(report.get('btc_hourly_regime',{})), '',
            'Ayrıntılı sonuç durumları, OI kapsaması ve işlem satırları `research.json` içindedir.', '',
            '## Sınırlar','']
    lines.extend('- '+s for s in report['limitations'])
    return '\n'.join(lines)+'\n'
