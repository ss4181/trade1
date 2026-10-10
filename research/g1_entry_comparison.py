"""Pure reporting for frozen G1 entries. Missing is not zero; replay is not OOS."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import random
import statistics as st

from g1_entry import CONFIG_VERSION, MEASUREMENT, MINUTE, PATH_VERSION

PLANS = ('immediate', 'wait_5m', 'wait_15m', 'confirm_5m', 'confirm_15m')
TERMINAL = ('TP', 'SL', 'SL_GAP', 'AMBIGUOUS_SL', 'TIMEOUT')
UNIVERSE = 'all_active_usdm_perpetuals'


def utc(value):
    value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('timezone_required')
    return value.astimezone(timezone.utc)


def ms(value):
    return int(utc(value).timestamp()*1000)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    p = (len(values)-1)*q
    a, b = math.floor(p), math.ceil(p)
    return values[a] + (values[b]-values[a])*(p-a)


def distribution(values):
    return dict(n=len(values), mean=st.mean(values) if values else None,
                median=st.median(values) if values else None,
                q10=quantile(values, .1), q90=quantile(values, .9))


def week(event):
    d = utc(event['started_at']).date()
    return (d-timedelta(days=d.weekday())).isoformat()


def cohort_filter(events, as_of, mode):
    counts, candidates = Counter(), defaultdict(list)
    for e in events:
        reason = None
        if not isinstance(e, dict) or e.get('strategy') != 'G1':
            counts['not_g1'] += 1
            continue
        if (e.get('measurement_version') != MEASUREMENT or
                (mode == 'forward' and e.get('config_version') != CONFIG_VERSION)):
            reason = 'different_measurement_or_config'
        elif mode == 'forward' and e.get('entry_study_origin') == 'retrospective_proxy':
            reason = 'retrospective_not_forward'
        elif (e.get('market') != 'um_perp' or e.get('direction') != 'LONG' or
              e.get('universe') != UNIVERSE):
            reason = 'different_market_direction_or_universe'
        elif e.get('delivery_evidence') != 'confirmed':
            reason = 'delivery_unconfirmed'
        elif (not isinstance(e.get('event_id'), str) or not e['event_id'].isalnum()
              or not isinstance(e.get('symbol'), str) or not e['symbol'].isalnum()
              or not e['symbol'].endswith('USDT')):
            reason = 'invalid_identifier'
        else:
            try:
                start, end = utc(e['started_at']), utc(e['expires_at'])
                expected = ((ms(e['started_at'])+MINUTE-1)//MINUTE)*MINUTE
                if (start > as_of or (end-start).total_seconds() != 4*3600
                        or e.get('tracking_start_ms') != expected):
                    reason = 'invalid_time_or_horizon'
            except (KeyError, ValueError, TypeError, OverflowError):
                reason = 'invalid_time_or_horizon'
        if reason:
            counts[reason] += 1
        else:
            candidates[e['event_id']].append(e)
    cohort = []
    for group in candidates.values():
        # Never silently choose the more profitable duplicate.
        encoded = {json.dumps(e, sort_keys=True, separators=(',', ':')) for e in group}
        if len(encoded) > 1:
            counts['conflicting_duplicate_records'] += len(group)
        else:
            counts['identical_duplicate_records'] += len(group)-1
            cohort.append(group[0])
    return sorted(cohort, key=lambda e: (utc(e['started_at']), e['event_id'])), dict(counts)


def complete(event):
    end = ms(event['expires_at'])//MINUTE*MINUTE
    next_ms = event.get('next_start_ms')
    return event.get('status') == 'expired' and number(next_ms) and next_ms >= end


def window(event, wait):
    shadow = event.get('entry_shadow') or {}
    if not isinstance(shadow, dict):
        return None
    history = shadow.get('minutes') or []
    if not isinstance(history, list) or len(history) < wait:
        return None
    rows = history[:wait]
    for i, b in enumerate(rows):
        if not isinstance(b, dict) or b.get('open_time') != event['tracking_start_ms']+i*MINUTE:
            return None
        if not all(number(b.get(k)) for k in ('open', 'high', 'low', 'close')):
            return None
        if not 0 < b['low'] <= min(b['open'], b['close']) <= max(b['open'], b['close']) <= b['high']:
            return None
    return rows


def outcome(event, key):
    if not complete(event):
        return None
    shadow = event.get('entry_shadow') or {}
    if not isinstance(shadow, dict) or not isinstance(shadow.get('plans'), dict):
        return None
    plan = shadow['plans'].get(key)
    if not isinstance(plan, dict) or plan.get('tp_pct') != 3 or plan.get('sl_pct') != 2:
        return None
    wait = 0 if key == 'immediate' else int(key.split('_')[1][:-1])
    if key.startswith('confirm'):
        w = window(event, wait)
        if w is None:
            return None
        if w[-1]['close'] <= w[0]['open']:
            return plan if plan.get('status') == 'no_entry' else None
    if plan.get('status') not in TERMINAL or not number(plan.get('gross_pct')):
        return None
    if (plan.get('entry_time_ms') != event['tracking_start_ms']+wait*MINUTE or
            not number(plan.get('entry_price')) or plan['entry_price'] <= 0):
        return None
    gross, status = plan['gross_pct'], plan['status']
    if ((status == 'TP' and abs(gross-3) > 1e-7) or
            (status in ('SL', 'AMBIGUOUS_SL') and abs(gross+2) > 1e-7) or
            (status == 'SL_GAP' and gross > -2+1e-7)):
        return None
    return plan


def net(plan, cost):
    return 0. if plan['status'] == 'no_entry' else plan['gross_pct']-cost/100


def regime(event):
    label = event.get('market_regime')
    if label not in ('BULL', 'BEAR', 'TRANSITION'):
        return 'UNKNOWN'
    try:
        age = (utc(event['started_at'])-utc(event['market_regime_data_close_at'])).total_seconds()
    except (KeyError, ValueError, TypeError, OverflowError):
        return 'UNKNOWN'
    return label if 0 <= age <= 72*3600 else 'UNKNOWN'


def paired_ci(pairs):
    weeks = defaultdict(list)
    for e, delta in pairs:
        weeks[week(e)].append(delta)
    if len(weeks) < 4:
        return dict(n_weeks=len(weeks), low=None, high=None, warning='fewer_than_4_weeks')
    blocks = [weeks[k] for k in sorted(weeks)]
    rng = random.Random(731)
    samples = []
    for _ in range(2000):
        selected = rng.choices(blocks, k=len(blocks))
        samples.append(sum(map(sum, selected))/sum(map(len, selected)))
    return dict(n_weeks=len(weeks), low=quantile(samples, .025), high=quantile(samples, .975),
                warning='exploratory_not_multiple_comparison_adjusted')


def plan_summary(events, key):
    observed = [(e, outcome(e, key)) for e in events]
    counts = Counter(p['status'] if p else 'unavailable' for _, p in observed)
    entered = [(e, p) for e, p in observed if p and p['status'] != 'no_entry']
    n = len(entered)
    costs = {}
    for cost in (20, 40):
        returns = [net(p, cost) for _, p in entered]
        costs[str(cost)] = dict(per_entered_trade=distribution(returns),
            per_observed_opportunity=distribution([net(p, cost) for _, p in observed if p]),
            positive_net_trade_pct=100*sum(r > 0 for r in returns)/n if n else None)
    paths = [p['path'] for _, p in entered if isinstance(p.get('path'), dict)
             and p['path'].get('version') == PATH_VERSION and p['path'].get('complete_from_entry') is True
             and all(number(p['path'].get(k)) for k in ('mae_full_bar_pct', 'mfe_full_bar_pct'))]
    by_regime = {}
    for label in ('BULL', 'BEAR', 'TRANSITION', 'UNKNOWN'):
        group = [(e, p) for e, p in observed if regime(e) == label]
        by_regime[label] = dict(n_opportunities=len(group), n_observed=sum(p is not None for _, p in group),
            net40_per_observed_opportunity=distribution([net(p, 40) for _, p in group if p]))
    pairs, compared, price_delta, delays = [], Counter(), [], []
    for e, p in observed:
        base = outcome(e, 'immediate')
        if p is None or base is None:
            compared['unavailable_pair'] += 1
            continue
        pairs.append((e, net(p, 40)-net(base, 40)))
        if p['status'] == 'no_entry':
            compared['no_entry_with_profitable_immediate' if net(base, 40) > 0 else
                     'no_entry_with_losing_immediate' if net(base, 40) < 0 else 'no_entry_with_flat_immediate'] += 1
        else:
            price_delta.append((p['entry_price']/base['entry_price']-1)*100)
            delays.append((p['entry_time_ms']-ms(e['started_at']))/MINUTE)
    no_entry_counterfactual = Counter()
    if key.startswith('confirm'):
        for e, p in observed:
            if p and p['status'] == 'no_entry':
                cf = outcome(e, key.replace('confirm', 'wait'))
                no_entry_counterfactual['unavailable' if cf is None else
                    'missed_net_winner' if net(cf, 40) > 0 else
                    'avoided_net_loser' if net(cf, 40) < 0 else 'flat'] += 1
    windows = []
    if key != 'immediate':
        wait = int(key.split('_')[1][:-1])
        for e in events:
            w = window(e, wait)
            if w:
                ref = w[0]['open']
                windows.append(dict(touch=max(b['high'] for b in w) >= ref*1.03,
                    mae=min(0., (min(b['low'] for b in w)/ref-1)*100),
                    mfe=max(0., (max(b['high'] for b in w)/ref-1)*100)))
    return dict(counts=dict(counts), n_entered=n, n_opportunities=len(events),
        n_observed_opportunities=sum(p is not None for _, p in observed),
        tp_first_lower_pct=100*counts['TP']/n if n else None,
        tp_first_upper_pct=100*(counts['TP']+counts['AMBIGUOUS_SL'])/n if n else None,
        costs_ex_funding=costs,
        mean_net40_per_observed_opportunity_ex_funding_pct=costs['40']['per_observed_opportunity']['mean'],
        path=dict(n_available=len(paths), n_unavailable=n-len(paths),
            mae_full_exit_bar_pct=distribution([p['mae_full_bar_pct'] for p in paths]),
            mfe_full_exit_bar_pct=distribution([p['mfe_full_bar_pct'] for p in paths])),
        paired_vs_immediate=dict(n=len(pairs), counts=dict(compared),
            net40_delta_pct=distribution([delta for _, delta in pairs]), weekly_cluster_ci95=paired_ci(pairs),
            entry_price_change_pct=distribution(price_delta), minutes_from_delivery=distribution(delays)),
        no_entry_vs_same_time_wait=dict(no_entry_counterfactual),
        waiting_window=dict(n_observed=len(windows), tp3_touched_before_entry_count=sum(w['touch'] for w in windows),
            mae_pct=distribution([w['mae'] for w in windows]), mfe_pct=distribution([w['mfe'] for w in windows])),
        by_regime=by_regime)


def summarize(events, *, as_of=None, mode='forward'):
    if mode not in ('forward', 'retrospective'):
        raise ValueError('invalid_mode')
    now = utc(as_of) if as_of else datetime.now(timezone.utc)
    cohort, excluded = cohort_filter(events, now, mode)
    matured = [e for e in cohort if utc(e['expires_at']) <= now]
    times = [utc(e['started_at']) for e in cohort]
    span = (times[-1]-times[0]).total_seconds()/86400 if times else 0.
    days = len({utc(e['started_at']).date() for e in matured})
    full = [e for e in matured if all(outcome(e, p) is not None for p in PLANS)]
    full_days = len({utc(e['started_at']).date() for e in full})
    full_span = (utc(full[-1]['started_at'])-utc(full[0]['started_at'])).total_seconds()/86400 if full else 0.
    gate = mode == 'forward' and full_span >= 90 and len(full) >= 30 and full_days >= 28
    return dict(schema_version='g1-entry-shadow-report-v2', as_of_utc=now.isoformat(), mode=mode,
        n_total=len(cohort), n_matured=len(matured), n_pending=len(cohort)-len(matured),
        n_complete_all_plans=len(full), n_matured_incomplete=len(matured)-len(full),
        complete_event_days=full_days, complete_span_days=round(full_span, 3),
        excluded=excluded, event_days=days, span_days=round(span, 3), readiness_gate=gate,
        first_event_utc=times[0].isoformat() if times else None, last_event_utc=times[-1].isoformat() if times else None,
        concentration=dict(symbol_counts=dict(sorted(Counter(e['symbol'] for e in matured).items())),
            utc_day_counts=dict(sorted(Counter(utc(e['started_at']).date().isoformat() for e in matured).items())),
            utc_week_counts=dict(sorted(Counter(week(e) for e in matured).items()))),
        validated=False, funding='not_modeled', live_filter_enabled=False, decision='NO_LIVE_CHANGE',
        sample_warning='sample_gate_only_not_validation' if gate else 'insufficient_forward_evidence',
        plans={key: plan_summary(matured, key) for key in PLANS})


def render_text(r):
    def fmt(v):
        return '—' if v is None else f'{v:.3f}'
    lines = ['G1 GİRİŞ KARŞILAŞTIRMASI — İŞLEM DEĞİL / CANLI FİLTRE DEĞİL',
        'Kaynak: '+('İLERİ GÖZLEM' if r['mode'] == 'forward' else 'ESKİ VERİ TEKRARI — OOS DEĞİL'),
        f"Toplam {r['n_total']} · olgun {r['n_matured']} · bekleyen {r['n_pending']} · beş planı tam {r['n_complete_all_plans']}",
        f"Olay günü {r['event_days']} · zaman aralığı {r['span_days']} gün · olgun/eksik {r['n_matured_incomplete']}",
        '', '| Plan | Giriş | Girilmedi | Eksik | TP alt–üst % | Net20/fırsat % | Net40/fırsat % |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for key, p in r['plans'].items():
        c = p['counts']
        lines.append(f"| {key} | {p['n_entered']} | {c.get('no_entry', 0)} | {c.get('unavailable', 0)} | "
            f"{fmt(p['tp_first_lower_pct'])}–{fmt(p['tp_first_upper_pct'])} | "
            f"{fmt(p['costs_ex_funding']['20']['per_observed_opportunity']['mean'])} | "
            f"{fmt(p['costs_ex_funding']['40']['per_observed_opportunity']['mean'])} |")
    for key in PLANS[1:]:
        p = r['plans'][key]
        paired = p['paired_vs_immediate']; ci = paired['weekly_cluster_ci95']
        lines.extend(['', f"{key}: eşlenmiş N={paired['n']}; immediate'a göre net40 farkı {fmt(paired['net40_delta_pct']['mean'])} puan; "
            f"hafta-blok %95 aralık [{fmt(ci['low'])}, {fmt(ci['high'])}] ({ci['n_weeks']} hafta).",
            f"Giriş fiyatı farkı medyan {fmt(paired['entry_price_change_pct']['median'])}%; negatif daha ucuz LONG referansı.",
            f"Giriş–çıkış mum-aralığı MAE medyan {fmt(p['path']['mae_full_exit_bar_pct']['median'])}%; "
            f"MFE medyan {fmt(p['path']['mfe_full_exit_bar_pct']['median'])}%; ölçülen N={p['path']['n_available']}."])
        if key.startswith('confirm'):
            cf = p['no_entry_vs_same_time_wait']
            lines.append(f"Teyit yokken aynı saatte koşulsuz girişe göre: kaçırılan net kazanç {cf.get('missed_net_winner', 0)}, "
                f"atlanan net kayıp {cf.get('avoided_net_loser', 0)}, bilinmeyen {cf.get('unavailable', 0)}.")
    lines.extend(['', 'TP3 / SL2, ortak 4h; aynı mumda stop önce. Fırsat ortalaması portföy getirisi değildir.',
        'No-entry sıfır; eksik veri sıfır/kayıp değildir. Funding hesaplanmadı. Kısmi ilk/son dakika yok.',
        'MAE/MFE çıkış mumunun TAM aralığını içerir; gerçek işlem içi düşüş/tepe değildir.',
        'Rejim, maliyet dağılımları, bekleme dokunmaları ve yoğunlaşma JSON raporundadır.',
        'Karar: Canlı değişiklik yok. 90 gün / 30 tam olay / 28 olay günü dahi tek başına doğrulama değildir.'])
    return '\n'.join(lines)
