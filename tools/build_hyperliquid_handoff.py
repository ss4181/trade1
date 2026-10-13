"""Build a private, offline reference ZIP. Never reads env/account/runtime state.

Optional public-market JSONL archives require a fully verified backup. Large
historical Binance datasets stay external; their paths are documented, not
silently claimed as bundled. This is not a live trading implementation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VERSION = 'trade1-hl-handoff-v1'
ARCHIVES = ('market_archive_*.jsonl', 'liquidation_archive_*.jsonl',
    'shadow_market_*.jsonl', 'shadow_events_*.jsonl', 'g2_market_*.jsonl',
    'g2_events_*.jsonl', 'execution_shadow_bars_*.jsonl',
    'g1_alignment_observations_*.jsonl', 'g1_alignment_bars_*.jsonl')
SECRET_KEYS = {'token', 'api_key', 'apikey', 'private_key', 'privatekey',
    'password', 'mnemonic', 'seed_phrase', 'telegram_bot_token', 'github_token',
    'resend_api_key', 'secret', 'chat_id', 'chat_ids', 'recipients', 'subscribers'}
SECRET_LITERAL = re.compile(
    r'(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}'
    r'|\d{7,12}:[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)')
EXCLUDED_ROOT = {'binance_testnet.py', 'testnet_pilot.py', 'testnet_risk.py'}


def safe_json(value):
    if isinstance(value, dict):
        for key, child in value.items():
            norm = str(key).lower().replace('-', '_')
            if (norm in SECRET_KEYS or norm.endswith(('_api_key', '_private_key', '_password'))):
                if child not in (None, '', False):
                    raise ValueError('private_field_not_allowed')
            safe_json(child)
    elif isinstance(value, list):
        for child in value:
            safe_json(child)
    elif isinstance(value, str) and SECRET_LITERAL.search(value):
        raise ValueError('secret_literal_not_allowed')


def safe_text(data, *, json_input=False):
    text = data.decode('utf-8-sig')
    if SECRET_LITERAL.search(text):
        raise ValueError('secret_literal_not_allowed')
    if json_input:
        safe_json(json.loads(text))


def sources(repo):
    """Allowlist code/docs; no directory-wide copy, glob of dotfiles or .env."""
    files = set()
    for p in repo.iterdir():
        if p.is_file() and not p.name.startswith('.') and p.suffix in {'.py', '.md', '.html', '.txt'}:
            if p.name not in EXCLUDED_ROOT:
                files.add(p)
    for dirname, extensions in [('research', {'.py', '.md', '.pine'}),
                                ('tests', {'.py', '.js'}), ('termux', {'.sh'}),
                                ('tools', {'.py'})]:
        # Research/data is deliberately never traversed by this code allowlist.
        folder = repo/dirname
        paths = folder.glob('*') if dirname == 'research' else folder.rglob('*')
        files.update(p for p in paths if p.is_file() and p.suffix in extensions
                     and '__pycache__' not in p.parts and p.name != 'test_testnet_pilot.py')
    files.update(p for p in (repo/'handoff'/'hyperliquid').glob('*.md'))
    example = repo/'.env.example'
    if example.is_file():
        files.add(example)
    return sorted(files, key=lambda p:p.relative_to(repo).as_posix())


def git_meta(repo):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], encoding='utf-8', stderr=subprocess.DEVNULL).strip()
    try:
        return git('rev-parse', 'HEAD'), set(git('ls-files').splitlines())
    except (OSError, subprocess.CalledProcessError):
        return None, set()


def build_bundle(repo, output, *, archive_dir=None, include_evidence=True):
    repo, output = Path(repo).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('output_exists_no_overwrite')
    # Outputs must not be inside the immutable backup/source evidence tree.
    if archive_dir and (Path(archive_dir).resolve() == output.parent.resolve()
                       or Path(archive_dir).resolve() in output.resolve().parents):
        raise ValueError('output_inside_backup')
    entries = sources(repo)
    if include_evidence:
        evidence = repo/'research'/'data'/'g1-diagnostic-2026-10-13'
        entries += sorted(p for p in evidence.rglob('*.json') if p.is_file())
    archive_paths, backup_raw, expected = [], None, {}
    if archive_dir:
        from backup_verify import verify_backup
        archive_dir = Path(archive_dir).resolve()
        verified = verify_backup(archive_dir)
        if not verified.get('ok'):
            raise ValueError('backup_unverified_or_stale')
        backup_raw = (archive_dir/'backup_manifest.json').read_bytes()
        expected = json.loads(backup_raw)['files']
        for name in sorted(expected):
            if Path(name).name != name or not any(fnmatch.fnmatchcase(name, g) for g in ARCHIVES):
                continue
            archive_paths.append(archive_dir/name)
        if not archive_paths:
            raise ValueError('no_market_archives')
    commit, tracked = git_meta(repo)
    manifest = dict(schema_version=VERSION, generated_at_utc=datetime.now(timezone.utc).isoformat(),
        source_commit=commit, execution='REFERENCE_ONLY_NO_ORDERS', live_enabled=False,
        network_used=False, source_tree='working_tree_snapshot_with_per_file_hashes',
        historical_bulk_data_included=False, forward_archives_included=bool(archive_paths),
        backup_manifest_sha256=hashlib.sha256(backup_raw).hexdigest() if backup_raw else None,
        private_runtime_state_included=False, files={})
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name+'.partial')
    # Exclusive temporary creation: never overwrite another running build.
    try:
        stream = temp.open('xb')
    except FileExistsError:
        raise ValueError('partial_output_exists_no_overwrite') from None
    final_created = False
    try:
        with stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in entries:
                if path.is_symlink() or repo not in path.resolve().parents:
                    raise ValueError('unsafe_source_path')
                rel = path.relative_to(repo).as_posix()
                data = path.read_bytes()
                safe_text(data, json_input=path.suffix == '.json')
                target = rel if rel.startswith('handoff/hyperliquid/') else 'reference/trade1/'+rel
                z.writestr(target, data)
                # Track modified tracked files explicitly, without exposing env.
                status = 'untracked_draft'
                if rel in tracked:
                    base = subprocess.check_output(['git', '-C', str(repo), 'show', 'HEAD:'+rel])
                    status = 'committed' if base.replace(b'\r\n', b'\n') == data.replace(b'\r\n', b'\n') else 'modified_draft'
                manifest['files'][target] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    source_status=status if path.suffix != '.json' else 'private_diagnostic_evidence')
            for path in archive_paths:
                if path.is_symlink() or path.resolve().parent != archive_dir:
                    raise ValueError('unsafe_archive_path')
                name = path.name
                digest, count = hashlib.sha256(), 0
                with path.open('rb') as f, z.open('reference-data/binance-forward/'+name, 'w', force_zip64=True) as target:
                    for line in f:
                        if line.strip():
                            safe_text(line, json_input=True)
                        digest.update(line)
                        count += len(line)
                        target.write(line)
                if digest.hexdigest() != expected[name]['sha256'] or count != expected[name]['bytes']:
                    raise ValueError('archive_changed_during_copy')
                manifest['files']['reference-data/binance-forward/'+name] = dict(
                    bytes=count, sha256=digest.hexdigest(), source_status='verified_private_market_archive')
            if backup_raw is not None and (archive_dir/'backup_manifest.json').read_bytes() != backup_raw:
                raise ValueError('backup_manifest_changed')
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
        # No replacement of existing files, including a racing other process.
        with output.open('xb') as final, temp.open('rb') as partial:
            final_created = True
            import shutil
            shutil.copyfileobj(partial, final)
        temp.unlink()
    except Exception:
        if final_created and output.exists():
            output.unlink()  # Only this run's failed output, never an existing file.
        if temp.exists():
            temp.unlink()  # Only this newly-created partial ZIP, never the source.
        raise
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--archive-dir', type=Path)
    args = ap.parse_args()
    try:
        manifest = build_bundle(ROOT, args.output, archive_dir=args.archive_dir)
        print(json.dumps(dict(ok=True, file_count=len(manifest['files']),
            forward_archives_included=manifest['forward_archives_included'], network_used=False)))
    except (OSError, ValueError, subprocess.CalledProcessError, UnicodeError):
        print('Paket oluşturulamadı: hedef/sır/JSON veya yedek bütünlüğü kontrolü başarısız; kaynaklar değiştirilmedi.')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
