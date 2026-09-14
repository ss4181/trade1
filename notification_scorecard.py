"""Last five delivered alerts, with unresolved/missing outcomes kept in view."""
from datetime import datetime,timezone
import html


def stamp(value):
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt.astimezone(timezone.utc).timestamp() if dt.tzinfo else None
    except (ValueError,TypeError):return None


def summarize(signal,delivered,events,target_pct=2.):
    strategy=str(signal.get("strategy") or "?")
    current_id=signal.get("event_id")
    cutoff=stamp(signal.get("notified_at"))
    selected={}
    for row in delivered:
        t=stamp(row.get("delivered_at"))
        eid=row.get("event_id")
        if (row.get("strategy")==strategy and row.get("delivery_confirmed") is True
                and eid and eid!=current_id and t is not None and (cutoff is None or t<cutoff)):
            selected[eid]=(t,row)
    recent=sorted(selected.items(),key=lambda x:(-x[1][0],x[0]))[:5]
    counts={"success":0,"failed":0,"pending":0,"unknown":0}
    details=[]
    for eid,(_,row) in recent:
        event=events.get(eid)
        status="unknown"
        # Choose the last five first. Old/incompatible records stay unknown;
        # do not replace them with older winners from a convenient cohort.
        if event and all(event.get(k)==signal.get(k) for k in ("config_version","direction")):
            if strategy=="G2" and event.get("measurement_version")=="g2-scheduled-bracket-v1":
                raw=(event.get("g2_bracket") or {}).get("status")
                status=("success" if raw=="TP" else "failed" if raw in ("SL","AMBIGUOUS_SL","TIMEOUT")
                        else "pending" if raw=="PENDING" else "unknown")
            elif strategy!="G2" and event.get("measurement_version")=="signal-reference-touch-v1":
                target=(event.get("targets") or {}).get(f"{target_pct:g}")
                if target:
                    status=("success" if target.get("hit_at") else "failed" if event.get("status")=="expired"
                            else "pending" if event.get("status")=="active" else "unknown")
        counts[status]+=1
        details.append({"event_id":eid,"status":status})
    return {"strategy":strategy,"n":len(recent),**counts,"target_pct":3. if strategy=="G2" else target_pct,
            "definition":"scheduled_binance_TP3_before_SL2" if strategy=="G2" else "notification_reference_target_touch",
            "as_of":signal.get("notified_at"),"events":details}


def format_html(score):
    if not score:return "📊 <b>Son 5 bildirim:</b> geçmiş ölçümü okunamadı."
    name=html.escape(str(score['strategy']))
    definition="TP%3 / SL%2 sırası" if score['strategy']=="G2" else f"%{score['target_pct']:g} hedef dokunması"
    if not score['n']:return f"📊 <b>Son 5 {name}:</b> henüz teslim edilmiş geçmiş yok · {definition}."
    resolved=score['success']+score['failed']
    ratio=f" · sonuçlanan {score['success']}/{resolved}" if resolved else ""
    return (f"📊 <b>Son 5 {name} ({score['n']} kayıt):</b> {score['success']} başarılı · "
            f"{score['failed']} başarısız · {score['pending']} bekliyor · {score['unknown']} ölçülemedi{ratio}\n"
            f"<i>{definition}; brüt fiyat ölçümü, gerçek işlem kârı değil.</i>")
