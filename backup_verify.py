"""Read-only PC receipt/integrity check; optional restore rehearsal in a NEW folder."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from archive_backup import ARCHIVE_GLOBS, STATE_NAMES


def allowed_name(name):
    return (isinstance(name, str) and Path(name).name == name
            and "/" not in name and "\\" not in name
            and (name in STATE_NAMES or any(fnmatch.fnmatchcase(name, p) for p in ARCHIVE_GLOBS)))


def verify_backup(directory, *, max_age_hours=36, now=None):
    root = Path(directory).resolve()
    now = now or datetime.now(timezone.utc)
    result = {"ok": False, "verified_at_utc": now.isoformat(), "files_verified": 0,
              "bytes_verified": 0, "errors": [], "scope": "pc_local_receipt"}
    try:
        manifest = json.loads((root / "backup_manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "trade1-backup-v1":
            raise ValueError("unsupported_manifest")
        stamp = datetime.fromisoformat(manifest["created_at_utc"])
        age = (now - stamp).total_seconds() / 3600
        result["age_hours"] = round(age, 2)
        if age < -0.1 or age > max_age_hours:
            result["errors"].append("backup_stale_or_future")
        entries = manifest["files"]
        if not isinstance(entries, dict) or not entries:
            raise ValueError("empty_manifest")
        if not any(allowed_name(n) and n.endswith(".jsonl") for n in entries):
            result["errors"].append("no_research_archive")
        for name, expected in entries.items():
            if not allowed_name(name):
                result["errors"].append("unsafe_manifest_path")
                continue
            path = root / name
            if path.is_symlink() or path.resolve().parent != root:
                result["errors"].append("unsafe_backup_symlink")
                continue
            try:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if digest != expected["sha256"] or path.stat().st_size != expected["bytes"]:
                    result["errors"].append(f"checksum_mismatch:{name}")
                    continue
                with path.open(encoding="utf-8") as stream:
                    if name.endswith(".jsonl") or name == "signals.log":
                        for line in stream:
                            if line.strip():
                                json.loads(line)
                    else:
                        json.load(stream)
                result["files_verified"] += 1
                result["bytes_verified"] += path.stat().st_size
            except (OSError, ValueError, KeyError, TypeError):
                result["errors"].append(f"unreadable_or_invalid:{name}")
        free = shutil.disk_usage(root).free
        result["free_bytes"] = free
        if free < max(1024**3, result["bytes_verified"] * 2):
            result["errors"].append("pc_disk_space_low")
        result["ok"] = not result["errors"]
    except (OSError, ValueError, KeyError, TypeError):
        result["errors"].append("manifest_missing_or_invalid")
    return result


def restore_rehearsal(directory, destination):
    report = verify_backup(directory)
    if not report["ok"]:
        raise ValueError("backup_not_verified")
    root, dest = Path(directory).resolve(), Path(destination).resolve()
    if dest.exists():
        raise ValueError("restore_destination_must_not_exist")
    manifest = json.loads((root / "backup_manifest.json").read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=False)
    for name in manifest["files"]:
        shutil.copy2(root / name, dest / name)
    shutil.copy2(root / "backup_manifest.json", dest / "backup_manifest.json")
    return verify_backup(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--restore-to", help="Must be a new, non-existing directory; never starts the bot")
    parser.add_argument("--status-file", help="Optional private PC status JSON")
    args = parser.parse_args()
    result = (restore_rehearsal(args.directory, args.restore_to) if args.restore_to
              else verify_backup(args.directory))
    payload = json.dumps(result, indent=2)
    if args.status_file:
        target = Path(args.status_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(target)
    print(payload)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
