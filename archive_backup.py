"""Git'e girmeyen arsiv dosyalarini harici bir klasore güvenle kopyalar.

Bot bu modülü tablette günlük worker olarak çağırır; CLI ile elle de çalışır.
Hedef public GitHub, Pages veya .env olamaz — yalniz senin verdigin dizin.

Kopyalananlar (varsayilan):
  market_archive_YYYY-MM.jsonl
  liquidation_archive_YYYY-MM.jsonl
  shadow_market_YYYY-MM.jsonl
  shadow_events_YYYY-MM.jsonl

--include-state ile (token icermez):
  bot/deney/performance/hedef/arastirma durumlari, .subscribers.json,
  .forward_oi_report_state.json ve signals.log

ASLA kopyalanmaz: .env, GITHUB_TOKEN, herhangi bir gizli dosya.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ARCHIVE_GLOBS = (
    "market_archive_*.jsonl",
    "liquidation_archive_*.jsonl",
    "shadow_market_*.jsonl",
    "shadow_events_*.jsonl",
)

STATE_NAMES = (
    ".bot_state.json",
    ".experiment_state.json",
    ".perf_cache.json",
    ".price_target_state.json",
    ".research_monitor_state.json",
    ".subscribers.json",
    ".forward_oi_report_state.json",
    "signals.log",
)

FORBIDDEN_NAMES = {".env", ".env.local"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _source_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("ARCHIVE_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return _repo_root()


def collect_files(source: Path, include_state: bool) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in ARCHIVE_GLOBS:
        for path in sorted(source.glob(pattern)):
            if not path.is_file() or path.name in FORBIDDEN_NAMES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    if include_state:
        for name in STATE_NAMES:
            path = source / name
            if path.is_file() and path.name not in FORBIDDEN_NAMES:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(path)
    return found


def collect_state_files(source: Path) -> list[Path]:
    """Bot durum dosyalarını açık beyaz listeyle seç; `.env` asla seçilmez."""
    source = source.resolve()
    return [source / name for name in STATE_NAMES
            if (source / name).is_file() and name not in FORBIDDEN_NAMES]


def _unchanged(source: Path, target: Path) -> bool:
    if not target.is_file():
        return False
    src_stat = source.stat()
    dst_stat = target.stat()
    return (src_stat.st_size == dst_stat.st_size
            and src_stat.st_mtime_ns == dst_stat.st_mtime_ns)


def _atomic_copy(source: Path, target: Path) -> None:
    """Aktif JSONL büyürken yarım hedef bırakmadan kararlı bir snapshot al."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        # Kaynak kopyalama sırasında büyürse bir kez daha kopyala. İkinci
        # snapshot da geçerli bir dosya önekidir; hedefe yalnız atomik geçer.
        for _attempt in range(2):
            before = source.stat()
            shutil.copy2(source, temp_path)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) == (
                    after.st_size, after.st_mtime_ns):
                break
        os.replace(temp_path, target)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def copy_files(files: list[Path], dest: Path, *, dry_run: bool) -> dict:
    dest = dest.expanduser().resolve()
    if dest.name in FORBIDDEN_NAMES:
        raise SystemExit("hedef .env olamaz")
    resolved_sources = {path.resolve() for path in files}
    if any((dest / path.name).resolve() == path.resolve() for path in files):
        raise SystemExit("yedek hedefi kaynak klasorle ayni olamaz")
    copied = 0
    bytes_ = 0
    skipped = 0
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
    for src in files:
        target = dest / src.name
        size = src.stat().st_size
        if target.resolve() in resolved_sources and target.resolve() != src.resolve():
            raise SystemExit("yedek hedefi baska bir kaynak dosyanin ustune gelemez")
        if _unchanged(src, target):
            print(f"AYNI {src.name}  {size} bayt")
            skipped += 1
            continue
        if dry_run:
            print(f"DRY  {src.name}  {size} bayt -> {target}")
            copied += 1
            bytes_ += size
            continue
        _atomic_copy(src, target)
        print(f"OK   {src.name}  {size} bayt")
        copied += 1
        bytes_ += size
    return {"files_total": len(files), "copied": copied, "bytes": bytes_,
            "skipped": skipped, "dest": str(dest)}


def backup_once(source: Path, dest: Path, *, include_state: bool = False,
                state_source: Path | None = None,
                dry_run: bool = False) -> dict:
    """Tek yedek turu; sır içermeyen, test edilebilir ana API."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"kaynak yok: {source}")
    files = collect_files(source, include_state=False)
    if include_state:
        state_root = (state_source or source).expanduser().resolve()
        known = {item.resolve() for item in files}
        files.extend(path for path in collect_state_files(state_root)
                     if path.resolve() not in known)
    return copy_files(files, dest, dry_run=dry_run)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Arsiv JSONL dosyalarini harici klasore kopyala")
    ap.add_argument("dest", help="hedef klasor (ornegin USB veya ~/backups/trade1)")
    ap.add_argument("--source", default=None,
                    help="kaynak dizin (varsayilan: ARCHIVE_DIR veya repo koku)")
    ap.add_argument("--include-state", action="store_true",
                    help="bot durum dosyalarini ve signals.log'u da kopyala")
    ap.add_argument("--dry-run", action="store_true",
                    help="kopyalama; yalniz listele")
    args = ap.parse_args(argv)

    source = _source_dir(args.source)
    if not source.is_dir():
        print(f"kaynak yok: {source}", file=sys.stderr)
        return 1
    try:
        summary = backup_once(
            source, Path(args.dest), include_state=args.include_state,
            state_source=_repo_root(), dry_run=args.dry_run)
    except (OSError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not summary["files_total"]:
        print(f"kopyalanacak arsiv yok: {source}")
        return 0
    print(f"{summary['copied']} kopya, {summary['skipped']} degismemis, "
          f"{summary['bytes']} bayt -> {summary['dest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
