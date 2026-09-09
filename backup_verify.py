"""Read-only PC integrity check; optional restore into a NEW private folder."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from archive_backup import ARCHIVE_GLOBS, STATE_NAMES


def allowed_name(name):
    return (isinstance(name, str) and Path(name).name == name
            and "/" not in name and "\\" not in name and ":" not in name
            and (name in STATE_NAMES or any(fnmatch.fnmatchcase(name, p) for p in ARCHIVE_GLOBS)))


def _invalid_constant(_value):
    raise ValueError("non_finite_json")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _json(payload):
    return json.loads(payload, parse_constant=_invalid_constant, object_pairs_hook=_unique_pairs)


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _regular_file(path, root):
    return (not path.is_symlink() and path.resolve().parent == root
            and stat.S_ISREG(path.stat().st_mode))


def _inspect_backup(directory, *, max_age_hours=36, now=None):
    root = Path(directory).expanduser().resolve()
    now = now or datetime.now(timezone.utc)
    result = {"ok": False, "verified_at_utc": now.isoformat(), "files_verified": 0,
              "bytes_verified": 0, "errors": [], "scope": "pc_local_receipt"}
    raw = None
    try:
        path = root / "backup_manifest.json"
        if not _regular_file(path, root):
            raise ValueError("unsafe_manifest_file")
        raw = path.read_bytes()
        manifest = _json(raw.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "trade1-backup-v1":
            raise ValueError("unsupported_manifest")
        stamp = datetime.fromisoformat(manifest["created_at_utc"])
        if stamp.tzinfo is None or now.tzinfo is None:
            raise ValueError("timezone_required")
        if not math.isfinite(max_age_hours) or max_age_hours <= 0:
            raise ValueError("invalid_max_age")
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
            if (not isinstance(expected, dict) or type(expected.get("bytes")) is not int
                    or expected["bytes"] < 0 or not isinstance(expected.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"])):
                result["errors"].append("invalid_manifest_entry")
                continue
            path = root / name
            try:
                if not _regular_file(path, root):
                    result["errors"].append("unsafe_backup_symlink_or_file")
                    continue
                digest, byte_count = hashlib.sha256(), 0
                valid_json = True
                # Hash and parse the SAME bytes in one pass. Archive memory use
                # is limited to one JSONL line; rejected data is never printed.
                with path.open("rb") as stream:
                    before = os.fstat(stream.fileno())
                    if name.endswith(".jsonl") or name == "signals.log":
                        for line in stream:
                            digest.update(line)
                            byte_count += len(line)
                            try:
                                if line.strip():
                                    _json(line.decode("utf-8"))
                            except ValueError:
                                valid_json = False
                    else:
                        payload = stream.read()
                        byte_count = len(payload)
                        digest.update(payload)
                        try:
                            _json(payload.decode("utf-8"))
                        except ValueError:
                            valid_json = False
                    after = os.fstat(stream.fileno())
                if (_signature(before) != _signature(after)
                        or _signature(after) != _signature(path.stat())):
                    result["errors"].append(f"file_changed_during_verification:{name}")
                    continue
                if digest.hexdigest() != expected["sha256"] or byte_count != expected["bytes"]:
                    result["errors"].append(f"checksum_mismatch:{name}")
                    continue
                if not valid_json:
                    result["errors"].append(f"unreadable_or_invalid:{name}")
                    continue
                result["files_verified"] += 1
                result["bytes_verified"] += byte_count
            except (OSError, ValueError, TypeError):
                result["errors"].append(f"unreadable_or_invalid:{name}")
        if (root / "backup_manifest.json").read_bytes() != raw:
            result["errors"].append("manifest_changed_during_verification")
        free = shutil.disk_usage(root).free
        result["free_bytes"] = free
        if free < max(1024**3, result["bytes_verified"] * 2):
            result["errors"].append("pc_disk_space_low")
        result["ok"] = not result["errors"]
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        result["errors"].append("manifest_missing_or_invalid")
    return result, raw


def verify_backup(directory, *, max_age_hours=36, now=None):
    return _inspect_backup(directory, max_age_hours=max_age_hours, now=now)[0]


def restore_rehearsal(directory, destination):
    report, raw = _inspect_backup(directory)
    if not report["ok"]:
        raise ValueError("backup_not_verified")
    root = Path(directory).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    if dest.exists():
        raise ValueError("restore_destination_must_not_exist")
    if dest.is_relative_to(root):
        raise ValueError("restore_destination_inside_backup")
    # Freeze the verified manifest; a second read could change the file list
    # midway through a new Syncthing publication.
    manifest = _json(raw.decode("utf-8"))
    dest.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(dest).free < report["bytes_verified"] + 1024**3:
        raise OSError("restore_disk_space_low")
    for name in manifest["files"]:
        if not _regular_file(root / name, root):
            raise ValueError("restore_source_changed")
        shutil.copy2(root / name, dest / name)
    (dest / "backup_manifest.json").write_bytes(raw)
    return verify_backup(dest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--restore-to", help="Must be a new, non-existing directory; never starts the bot")
    parser.add_argument("--status-file", help="Optional private PC status JSON outside the backup")
    args = parser.parse_args(argv)
    try:
        result = (restore_rehearsal(args.directory, args.restore_to) if args.restore_to
                  else verify_backup(args.directory))
    except (OSError, ValueError):
        result = {"ok": False, "scope": "pc_local_receipt", "errors": ["restore_failed"]}
    if args.status_file:
        temporary = None
        try:
            target = Path(args.status_file).expanduser().resolve()
            if target.is_relative_to(Path(args.directory).expanduser().resolve()):
                raise ValueError("status_inside_backup")
            if args.restore_to and target.is_relative_to(Path(args.restore_to).expanduser().resolve()):
                raise ValueError("status_inside_restore")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".pc_backup_status.", suffix=".tmp", dir=target.parent)
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
            temporary.replace(target)
        except (OSError, ValueError):
            result["ok"] = False
            result["errors"].append("status_write_failed")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
