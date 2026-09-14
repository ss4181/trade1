"""G2 public-data research alerts and scheduled Binance TP/SL reference tracking.

No exchange account, orders, private keys or historical research dependencies.
The live Binance OI snapshot adapter is explicitly distinct from Coinalyze OI.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from shadow_experiments import append_jsonl

HOUR = 3_600_000
BAR = 300_000
VERSION = "G2-binance-oi-snapshot-forward-v1"
MEASUREMENT = "g2-scheduled-bracket-v1"
CONTRACTS = tuple((
    "1INCHUSDT AAVEUSDT ACEUSDT ADAUSDT AGLDUSDT ALGOUSDT ALICEUSDT APEUSDT APTUSDT ARBUSDT ARUSDT "
    "ATOMUSDT AVAXUSDT AXSUSDT BCHUSDT BLURUSDT BNBUSDT BOMEUSDT 1000BONKUSDT BTCUSDT CAKEUSDT "
    "CHRUSDT CHZUSDT COMPUSDT CRVUSDT DASHUSDT DOGEUSDT DOTUSDT DYDXUSDT ENAUSDT ENSUSDT ETCUSDT "
    "ETHFIUSDT ETHUSDT FETUSDT FILUSDT GALAUSDT GRTUSDT HBARUSDT HOTUSDT ICPUSDT IDUSDT INJUSDT "
    "JTOUSDT JUPUSDT LDOUSDT LINKUSDT LISTAUSDT LSKUSDT LTCUSDT 1000LUNCUSDT NEARUSDT ONEUSDT "
    "OPUSDT ORDIUSDT PENDLEUSDT 1000PEPEUSDT PYTHUSDT QTUMUSDT RENDERUSDT RIFUSDT RSRUSDT SANDUSDT "
    "SEIUSDT 1000SHIBUSDT SKLUSDT SNXUSDT SOLUSDT STRKUSDT STXUSDT SUIUSDT TAOUSDT TIAUSDT "
    "TLMUSDT TNSRUSDT TRXUSDT TUSDT UNIUSDT WIFUSDT WLDUSDT 1000XECUSDT XLMUSDT XRPUSDT ZECUSDT "
    "ZENUSDT ZILUSDT ZROUSDT").split())


def iso(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def closed_return(klines, close_ms):
    rows={int(k[0]):k for k in klines if isinstance(k,list) and len(k)>=7 and int(k[6])<close_ms}
    expected=range(close_ms-25*HOUR,close_ms,HOUR)
    if any(t not in rows or int(rows[t][6])!=t+HOUR-1 for t in expected):
        raise ValueError("G2 incomplete closed hourly grid")
    values=[float(rows[t][4]) for t in expected]
    if not all(math.isfinite(v) and v>0 for v in values):raise ValueError("G2 invalid close")
    return {"close":values[-1],"return_24h":values[-1]/values[0]-1}


def oi_change(rows,close_ms):
    def before(cutoff):
        good=[]
        for r in rows:
            t=int(r.get("timestamp",0))
            v=float(r.get("sumOpenInterest",0))
            if cutoff-15*60_000<=t<cutoff and math.isfinite(v) and v>0:good.append((t,v))
        if not good:raise ValueError("G2 missing fresh OI snapshot")
        return max(good)
    now,old=before(close_ms),before(close_ms-HOUR)
    if now[0]-old[0]!=HOUR:raise ValueError("G2 OI snapshots not one hour apart")
    return now[1]/old[1]-1,now[0],old[0]


def scan_g2(futures_get,state_path,archive_dir,now=None,contracts=CONTRACTS,on_error=None):
    now=now or datetime.now(timezone.utc)
    close_ms=int(now.timestamp()*1000)//HOUR*HOUR
    state_path=Path(state_path)
    state=json.loads(state_path.read_text()) if state_path.exists() else {"last_fire":{}}
    if state.get("completed_hour")==close_ms:return []
    if state.get("input_hour")!=close_ms:
        state.update(input_hour=close_ms,prices={})
    def save():
        state_path.parent.mkdir(parents=True,exist_ok=True)
        tmp=state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state,allow_nan=False),encoding="utf-8")
        tmp.replace(state_path)
    def fetch(path,params):
        response=futures_get(path,params)
        response.raise_for_status()
        return response.json()
    # Full frozen cross-section first; never rank only the symbols that responded.
    try:
        for symbol in contracts:
            if symbol not in state["prices"]:
                raw=fetch("/fapi/v1/klines",{"symbol":symbol,"interval":"1h","limit":25,
                          "startTime":close_ms-25*HOUR,"endTime":close_ms-1})
                state["prices"][symbol]=closed_return(raw,close_ms)
    except Exception:
        save()
        raise
    ranked=sorted(contracts,key=lambda s:(state["prices"][s]["return_24h"],s))
    signals=[]
    errors=[]
    snapshots=[]
    for rank,symbol in enumerate(ranked[:10],1):
        price=state["prices"][symbol]
        if price["return_24h"]>-.05:continue
        if close_ms-int(state["last_fire"].get(symbol,0))<24*HOUR:continue
        try:
            raw=fetch("/futures/data/openInterestHist",{"symbol":symbol,"period":"5m","limit":16,
                      "startTime":close_ms-HOUR-15*60_000,"endTime":close_ms-1})
            change,oi_at,lag_at=oi_change(raw,close_ms)
            snapshots.append({"kind":"G2_SNAPSHOT","symbol":symbol,"closed_at":iso(close_ms),
                              "rank_loser":rank,**price,"oi_change_1h":change,"oi_at":oi_at,"oi_lag_at":lag_at})
            if change<.01:continue
            signal={"strategy":"G2","symbol":symbol,"direction":"LONG","strength":"RESEARCH",
                    "confidence":"GOZLEM","confidence_note":"Araştırma adayı; Hyperliquid dolumu doğrulanmadı",
                    "bar_time":iso(close_ms-HOUR),"signal_reference_at":iso(close_ms),"detected_at":now.isoformat(),
                    "price":price["close"],"condition_price":price["close"],"horizon_hours":24,
                    "planned_entry_at":iso(close_ms+HOUR),"target_pct":3.,"stop_pct":2.,
                    "rank_loser":rank,"return_24h_pct":round(price["return_24h"]*100,3),"oi_change_1h_pct":round(change*100,3),
                    "observe":True,"experimental":True,"universe":"g2_fixed87_binance_signal_universe",
                    "signal_market":"um_perp","performance_market":"um_perp","performance_symbol":symbol,
                    "execution_venue_intent":"Hyperliquid","entry_order_intent":"limit_post_only_ALO",
                    "oi_source":"binance_closed_5m_snapshots_not_coinalyze_ohlc",
                    "price_source":"closed_binance_usdm_1h","config_version":VERSION,
                    "performance_excluded":True,"performance_exclusion_reason":"G2 uses scheduled TP3 SL2 reference tracker",
                    "note":"İlk-10 düşen, 24s düşüş ≥%5 ve 1s OI artışı ≥%1. Planlanan giriş kapanış+1s; TP3/SL2, azami24s. Binance referansı; Hyperliquid limit dolumu ölçülmedi."}
            signals.append(signal)
            state["last_fire"][symbol]=close_ms
        except Exception as exc:
            errors.append(type(exc).__name__)
            if on_error:on_error(f"G2 {symbol}: {type(exc).__name__}")
    if not errors:state["completed_hour"]=close_ms
    state["last_errors"]=errors
    save()
    append_jsonl(Path(archive_dir),"g2_market",snapshots,now)
    append_jsonl(Path(archive_dir),"g2_events",signals,now)
    return signals


def initialize_tracking(event,record,delivered_ms):
    planned=int(datetime.fromisoformat(record["planned_entry_at"].replace("Z","+00:00")).timestamp()*1000)
    event.update(measurement_version=MEASUREMENT,entry_definition="scheduled_binance_5m_open_not_hyperliquid_fill",
                 started_at=iso(planned),expires_at=iso(planned+24*HOUR),next_start_ms=planned,
                 replay_silent_before_ms=planned,targets={},
                 g2_bracket={"status":"PENDING","target_pct":3.,"stop_pct":2.,"planned_entry_ms":planned,"entry_set":False})
    if delivered_ms>planned:
        event["status"]="invalid"
        event["g2_bracket"]["status"]="UNAVAILABLE_LATE_DELIVERY"


def advance_tracking(event,bars,coverage_end_ms):
    bracket=event["g2_bracket"]
    if bracket["status"]!="PENDING":return []
    next_ms=event["next_start_ms"]
    horizon_end=bracket["planned_entry_ms"]+24*HOUR
    for bar in sorted(bars,key=lambda b:int(b["open_time"])):
        t=int(bar["open_time"])
        if t<next_ms:continue
        if t!=next_ms or t+BAR>min(coverage_end_ms,horizon_end):break
        o,h,l,c=(float(bar[k]) for k in ("open","high","low","close"))
        if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:break
        if not bracket["entry_set"]:
            event["entry_ref"]=o
            bracket["entry_set"]=True
            event["targets"]={"3":{"price":o*1.03,"hit_at":None,"max_adverse_before_hit_pct":0.,"minutes_to_hit_upper":None}}
        entry=event["entry_ref"]
        target,stop=entry*1.03,entry*.98
        event["max_adverse_pct"]=min(event.get("max_adverse_pct",0),(l/entry-1)*100)
        event["max_favorable_pct"]=max(event.get("max_favorable_pct",0),(h/entry-1)*100)
        if o<=stop:result="SL"
        elif o>=target:result="TP"
        elif l<=stop:result="AMBIGUOUS_SL" if h>=target else "SL"
        elif h>=target:result="TP"
        else:result=None
        next_ms=t+BAR
        event["next_start_ms"]=next_ms
        if result or next_ms>=horizon_end:
            bracket.update(status=result or "TIMEOUT",resolved_at=iso(next_ms))
            event["status"]="expired"
            if result=="TP":
                event["targets"]["3"].update(hit_at=iso(t),minutes_to_hit_upper=(next_ms-bracket["planned_entry_ms"])/60000,
                    max_adverse_before_hit_pct=event["max_adverse_pct"])
                return ["3"] if t>=event.get("replay_silent_before_ms",0) else []
            return []
    return []
