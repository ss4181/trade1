"""Enable all existing alert channels without reading or rewriting .env secrets."""
import argparse
import json
from pathlib import Path

OVERRIDES = {
    "OBSERVE_ENABLED":"true", "OBSERVE_PUSH":"true",
    "SHADOW_EXPERIMENTS_ENABLED":"true", "SHADOW_PUSH_ENABLED":"true",
    "G2_ENABLED":"true", "G2_PUSH":"true", "S2_RESEARCH_PUSH":"true",
    "NOTIFY_MIN_CONFIDENCE":"GOZLEM", "DISABLED_STRATEGIES":"",
    "PRICE_TARGET_TRACKING_ENABLED":"true", "PRICE_TARGET_NOTIFY":"true",
    "MAX_PUSH_PER_SCAN":"10000", "OBSERVE_MAX_PUSH_PER_SCAN":"10000",
    "SHADOW_MAX_PUSH_PER_RUN":"10000", "DAILY_SUMMARY_HOUR_UTC":"6",
    "RESEARCH_WEEKLY_SUMMARY_ENABLED":"true",
}
PATH = Path(__file__).with_name(".notification_preferences.json")


def load(path=PATH):
    if not path.exists():return {}
    value=json.loads(path.read_text(encoding="utf-8"))
    if value!={"version":1,"profile":"all-alerts-2026-09-14","overrides":OVERRIDES}:
        raise ValueError("invalid_notification_preferences")
    return dict(OVERRIDES)


def enable(path=PATH):
    value={"version":1,"profile":"all-alerts-2026-09-14","overrides":OVERRIDES}
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)
    return load(path)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-all",action="store_true")
    args=parser.parse_args()
    settings=enable() if args.enable_all else load()
    print(json.dumps({"profile":"all-alerts-2026-09-14" if settings else "existing-env-settings",
                      "restart_required":args.enable_all,"settings":settings},ensure_ascii=False,indent=2))
