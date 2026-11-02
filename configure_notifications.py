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
ALL_ALERTS = "all-alerts-2026-09-14"
# Same profile with only the G2 Telegram push off; G2 scanning/archive keep running.
G2_MUTED = "all-alerts-g2-muted-2026-11-02"
PROFILES = {ALL_ALERTS: OVERRIDES, G2_MUTED: {**OVERRIDES, "G2_PUSH":"false"}}
PATH = Path(__file__).with_name(".notification_preferences.json")


def load(path=PATH):
    if not path.exists():return {}
    value=json.loads(path.read_text(encoding="utf-8"))
    profile=value.get("profile") if isinstance(value,dict) else None
    if profile not in PROFILES or value!={"version":1,"profile":profile,"overrides":PROFILES[profile]}:
        raise ValueError("invalid_notification_preferences")
    return dict(PROFILES[profile])


def enable(path=PATH, profile=ALL_ALERTS):
    value={"version":1,"profile":profile,"overrides":PROFILES[profile]}
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)
    return load(path)


def mute_g2(path=PATH):
    # Without a profile the bot reads .env; creating one here would silently
    # turn on every other alert channel too.
    if not load(path):
        raise ValueError("no_notification_profile_set_G2_PUSH_false_in_env")
    return enable(path, G2_MUTED)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--enable-all",action="store_true")
    group.add_argument("--mute-g2",action="store_true",
                       help="mevcut tum-bildirimler profilinde yalniz G2 Telegram bildirimini kapatir")
    args=parser.parse_args()
    if args.mute_g2:
        try:
            settings=mute_g2()
        except ValueError as exc:
            parser.exit(1,f"{exc}\n")
    else:
        settings=enable() if args.enable_all else load()
    profile=next((name for name,overrides in PROFILES.items() if overrides==settings),"existing-env-settings")
    print(json.dumps({"profile":profile,
                      "restart_required":args.enable_all or args.mute_g2,"settings":settings},ensure_ascii=False,indent=2))
