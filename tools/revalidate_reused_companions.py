#!/usr/bin/env python3
r"""Revalidate five immutable, previously downloaded companion ZIPs. No networking.

Example (all paths explicit; output must not exist and its parent must exist):
  python tools/revalidate_reused_companions.py --source-root . \
    --expected-source-commit FULL_CURRENT_SHA --jump-source /input/halcyon_jump.blend \
    --lock tools/source_bound_companion_reuse_lock.json \
    --origin-metadata /input/origin.json --output /evidence/revalidated \
    --artifact reload=/input/reload.zip --artifact walk=/input/walk.zip \
    --artifact ads=/input/ads.zip --artifact directional=/input/directional.zip \
    --artifact jump=/input/jump.zip

origin.json must contain schema "rust-duty-companion-origin/v1", an "origin"
object exactly equal to the lock's origin, and an "artifacts" list containing
exactly each lock artifact's artifact_id, name, run_id, head_sha, zip_sha256,
size_bytes and url. Supply metadata obtained from the authorized original
artifact retrieval; this tool neither fetches nor independently authenticates
GitHub metadata. The reviewed ZIP digests are the content trust anchor.

Source files require exact committed bytes (configure LF checkout on Windows).
The output/root is a validation tree, not a packaged game. Existing validators
run in separate fresh processes against copied, hash-checked tools. Historical
reports remain byte-identical. A successful receipt is not fresh source-oracle
parity, fresh asset generation, or native renderer evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

KINDS = ('reload', 'walk', 'ads', 'directional', 'jump')
ARTIFACT_KEYS = ('artifact_id', 'name', 'run_id', 'head_sha', 'zip_sha256', 'size_bytes', 'url')
SHA256 = re.compile(r'[0-9a-f]{64}')
SHA1 = re.compile(r'[0-9a-f]{40}')
MANDATORY_SOURCE_PATHS = set('''assets/locomotion/manifest.json assets/locomotion/README.md
assets/locomotion/asset.vra assets/locomotion/asset.vrm assets/locomotion/asset.vrs.gz
assets/animations.cfg docs/ANIMATION_SLOTS.md assets/source/reload/source.json
assets/source/reload/current.blend assets/authoring/locomotion/locomotion.blend
assets/authoring/ads/ads.blend assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend
assets/authoring/locomotion/export_config.json assets/authoring/ads/export_config.json
assets/authoring/locomotion_directional/runtime_export_config.json assets/authoring/jump/export_config.json
assets/authoring/locomotion_directional/r5/source_integrity.json
tools/check_generated_assets.py tools/package_game.py tools/build_blender_assets.py
tools/merge_walk_clip.py tools/vrview.py tools/vrskin.py tools/vrpack.py'''.split())
JUMP_PATH = 'assets/authoring/jump/halcyon_jump.blend'
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'{p}{n}' for p in ('COM', 'LPT') for n in range(1, 10))}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative_path(name):
    require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_./-]+', name),
            f'unsafe relative path: {name!r}')
    parts = name.split('/')
    require(all(p and p not in ('.', '..') and not p.endswith('.')
                and p.split('.')[0].upper() not in RESERVED for p in parts),
            f'unsafe relative path: {name!r}')
    return Path(*parts)


def no_links(path, *, file=False):
    """Reject symlinks, Windows junctions/reparse points, and non-regular files."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, 'st_file_attributes', 0) & 0x400,
                f'link/reparse point forbidden: {part}')
    require(path.is_file() if file else path.is_dir(), f'missing regular {"file" if file else "directory"}: {path}')
    if file:
        require(stat.S_ISREG(path.stat().st_mode), f'non-regular input: {path}')
    return path


def digest(path):
    path = no_links(path, file=True)
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def check_digest(path, expected):
    got = digest(path)
    require(got == {k: expected[k] for k in ('bytes', 'sha256')}, f'byte/hash mismatch: {path}')
    return got


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result
    path = no_links(path, file=True)
    require(path.stat().st_size <= 1024 * 1024, 'JSON input exceeds 1 MiB')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def validate_lock(lock):
    require(lock['schema'] == 'rust-duty-source-bound-companion-reuse-lock/v1', 'unsupported lock schema')
    require(len(lock['artifacts']) == 5 and {a['kind'] for a in lock['artifacts']} == set(KINDS),
            'lock must contain exactly five packs')
    require(SHA1.fullmatch(lock['eligible_assets_tree']), 'invalid assets tree identity')
    origin = lock['origin']
    require(origin['repository'] == 'RHS059/rust_duty' and type(origin['run_id']) is int
            and origin['run_id'] > 0 and type(origin['run_attempt']) is int and origin['run_attempt'] > 0
            and SHA1.fullmatch(origin['head_sha']) and SHA1.fullmatch(origin['tested_merge']), 'invalid origin')
    paths = set()
    for row in lock['source_files']:
        path = relative_path(row['path']).as_posix()
        require(path.casefold() not in paths, 'duplicate source path')
        paths.add(path.casefold())
        require(type(row['bytes']) is int and row['bytes'] > 0
                and SHA256.fullmatch(row['sha256']) and SHA1.fullmatch(row['git_blob']), 'invalid source identity')
    require({p.casefold() for p in MANDATORY_SOURCE_PATHS} <= paths, 'missing mandatory source/config/validator inputs')
    jump = lock['jump_source']
    relative_path(jump['path'])
    require(jump['path'] == JUMP_PATH and jump['repository'] == origin['repository']
            and jump['path'].casefold() not in paths and SHA1.fullmatch(jump['commit'])
            and SHA256.fullmatch(jump['sha256']) and type(jump['bytes']) is int and jump['bytes'] > 0,
            'invalid external Jump identity')
    for a in lock['artifacts']:
        require(type(a['artifact_id']) is int and a['artifact_id'] > 0 and type(a['size_bytes']) is int
                and 0 < a['size_bytes'] <= 128 * 1024**2 and SHA256.fullmatch(a['zip_sha256'])
                and a['run_id'] == origin['run_id'] and a['head_sha'] == origin['head_sha']
                and a['name'] == f"generated-{a['kind']}-runtime"
                and a['url'] == f"https://github.com/{origin['repository']}/actions/runs/{origin['run_id']}/artifacts/{a['artifact_id']}",
                'artifact origin mismatch in lock')
        members = [relative_path(m).as_posix() for m in a['members']]
        require(members and len({m.casefold() for m in members}) == len(members), 'invalid member inventory')
    require(len({a['artifact_id'] for a in lock['artifacts']}) == 5, 'duplicate artifact ID')
    limits = lock['limits']
    caps = {'max_zip_bytes': 128 * 1024**2, 'max_member_bytes': 128 * 1024**2,
            'max_uncompressed_bytes_per_zip': 512 * 1024**2, 'max_entries_per_zip': 128,
            'max_compression_ratio': 1000}
    require(set(limits) == set(caps) and all(type(limits[k]) is int and 0 < limits[k] <= v
                                          for k, v in caps.items()), 'invalid ZIP limits')


def validate_metadata(metadata, lock):
    require(set(metadata) == {'schema', 'origin', 'artifacts'}
            and metadata['schema'] == 'rust-duty-companion-origin/v1'
            and json.dumps(metadata['origin'], sort_keys=True) == json.dumps(lock['origin'], sort_keys=True),
            'origin metadata mismatch')
    expected = [{k: a[k] for k in ARTIFACT_KEYS} for a in lock['artifacts']]
    require(isinstance(metadata['artifacts'], list) and len(metadata['artifacts']) == 5
            and json.dumps(sorted(metadata['artifacts'], key=lambda x: x['artifact_id']), sort_keys=True)
            == json.dumps(sorted(expected, key=lambda x: x['artifact_id']), sort_keys=True),
            'artifact metadata mismatch')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, timeout=30).strip()


def verify_source(root, expected_commit, jump_path, lock):
    root = no_links(root)
    require(SHA1.fullmatch(expected_commit), 'expected source commit must be full lowercase SHA')
    require(git(root, 'rev-parse', 'HEAD') == expected_commit, 'current checkout commit mismatch')
    require(git(root, 'rev-parse', 'HEAD:assets') == lock['eligible_assets_tree'], 'current assets tree mismatch')
    for row in lock['source_files']:
        require(git(root, 'rev-parse', f"HEAD:{row['path']}") == row['git_blob'],
                f"current source Git identity mismatch: {row['path']}")
        check_digest(root / relative_path(row['path']), row)
    check_digest(jump_path, lock['jump_source'])


def extract_archive(archive, record, target, limits):
    """Hash and inspect before writing; never use ZipFile.extract/extractall."""
    require(not target.exists() and not target.is_symlink(), f'existing pack destination: {target}')
    archive = no_links(archive, file=True)
    require(record['size_bytes'] <= limits['max_zip_bytes'], 'ZIP exceeds size limit')
    check_digest(archive, {'bytes': record['size_bytes'], 'sha256': record['zip_sha256']})
    expected = set(record['members'])
    inventory = {}
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        require(len(entries) <= limits['max_entries_per_zip'], 'too many ZIP entries')
        seen, files, total = set(), set(), 0
        for item in entries:
            require(item.orig_filename == item.filename, 'NUL/aliased ZIP filename forbidden')
            name = item.filename[:-1] if item.is_dir() else item.filename
            relative_path(name)
            require(name.casefold() not in seen, 'duplicate/case-colliding ZIP entry')
            seen.add(name.casefold())
            mode = stat.S_IFMT(item.external_attr >> 16)
            require(mode in ((0, stat.S_IFDIR) if item.is_dir() else (0, stat.S_IFREG)), 'ZIP link/special file forbidden')
            require(not item.external_attr & 0x400 and not item.flag_bits & 1, 'ZIP reparse/encrypted entry forbidden')
            require(item.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'unsupported ZIP compression')
            if item.is_dir():
                require(item.file_size == 0 and any(p.startswith(name + '/') for p in expected), 'unexpected ZIP directory')
                continue
            require(0 < item.file_size <= limits['max_member_bytes'], 'ZIP member size limit')
            require(item.file_size <= max(1, item.compress_size) * limits['max_compression_ratio'], 'ZIP compression ratio limit')
            files.add(name)
            total += item.file_size
        require(total <= limits['max_uncompressed_bytes_per_zip'], 'ZIP total size limit')
        require(files == expected, f"incomplete/unexpected {record['kind']} ZIP inventory")
        target.mkdir(parents=True)
        for item in entries:
            if item.is_dir():
                continue
            destination = target / relative_path(item.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            remaining, h = item.file_size, hashlib.sha256()
            with bundle.open(item) as source, destination.open('xb') as out:
                while remaining:
                    chunk = source.read(min(remaining, 1024 * 1024))
                    require(chunk, 'truncated ZIP member')
                    out.write(chunk)
                    h.update(chunk)
                    remaining -= len(chunk)
                require(source.read(1) == b'', 'oversized ZIP member')
            inventory[item.filename] = {'bytes': item.file_size, 'sha256': h.hexdigest()}
    check_digest(archive, {'bytes': record['size_bytes'], 'sha256': record['zip_sha256']})
    return inventory


def snapshot(root):
    result = {}
    for path in sorted(root.rglob('*')):
        no_links(path, file=not path.is_dir())
        if path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def run_validators(root, reports):
    reports.mkdir()
    commands = [[sys.executable, '-E', '-s', '-B', str(root / 'tools/check_generated_assets.py'),
                 '--kind', kind, '--root', str(root), '--directory', f'assets/{kind}'] for kind in KINDS]
    commands.append([sys.executable, '-E', '-s', '-B', str(root / 'tools/package_game.py'),
                     'verify', '--root', str(root), '--require-generated'])
    results = []
    for label, command in zip((*KINDS, 'all-generated'), commands):
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=300)
        (reports / f'{label}.stdout.txt').write_text(result.stdout, encoding='utf-8')
        (reports / f'{label}.stderr.txt').write_text(result.stderr, encoding='utf-8')
        require(result.returncode == 0, f'validator failed: {label}: {result.stderr[-4000:]}')
        # The exit code is mandatory; parse output so truncated/non-JSON success fails too.
        report = json.loads(result.stdout)
        require(isinstance(report, dict) and report, f'empty validator report: {label}')
        results.append({'name': label, 'command': command, 'returncode': result.returncode, 'report': report})
    return results


def revalidate(args):
    output = Path(os.path.abspath(args.output))
    require(not output.exists() and not output.is_symlink(), 'output already exists; nothing overwritten')
    no_links(output.parent)
    lock_path, metadata_path = no_links(args.lock, file=True), no_links(args.origin_metadata, file=True)
    lock, metadata = read_json(lock_path), read_json(metadata_path)
    lock_digest, metadata_digest = digest(lock_path), digest(metadata_path)
    validate_lock(lock)
    validate_metadata(metadata, lock)
    archives = {}
    for value in args.artifact:
        kind, separator, name = value.partition('=')
        require(separator and kind in KINDS and kind not in archives, 'use exactly one KIND=PATH per artifact')
        archives[kind] = no_links(Path(name), file=True)
    require(set(archives) == set(KINDS), 'all five complete original ZIPs are required, including reload')
    source_root, jump = no_links(args.source_root), no_links(args.jump_source, file=True)
    verify_source(source_root, args.expected_source_commit, jump, lock)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}.staging-', dir=output.parent) as temporary:
        work = Path(temporary)
        root = work / 'root'
        root.mkdir()
        for row in lock['source_files']:
            destination = root / relative_path(row['path'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / relative_path(row['path']), destination)
            check_digest(destination, row)
        jump_out = root / relative_path(lock['jump_source']['path'])
        jump_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(jump, jump_out)
        check_digest(jump_out, lock['jump_source'])
        inventories = {}
        for record in lock['artifacts']:
            kind = record['kind']
            inventories[kind] = extract_archive(archives[kind], record, root / 'assets' / kind, lock['limits'])
        before = snapshot(root)
        results = run_validators(root, work / 'validation')
        require(snapshot(root) == before, 'validator modified staged input bytes or inventory')
        verify_source(source_root, args.expected_source_commit, jump, lock)
        check_digest(lock_path, lock_digest)
        check_digest(metadata_path, metadata_digest)
        receipt = {'schema': 'rust-duty-reused-companion-validation/v1', 'passed': True,
                   'generation_reused': True, 'new_generation': False, 'new_asset_generation': False,
                   'historical_parity_reports_preserved': True, 'fresh_source_oracle_parity': False,
                   'native_execution': False, 'origin_metadata_authenticated_by_this_tool': False,
                   'origin': lock['origin'],
                   'current_source_commit': args.expected_source_commit,
                   'lock': lock_digest, 'origin_metadata': metadata_digest,
                   'python': sys.version, 'platform': sys.platform,
                   'source_files': lock['source_files'], 'jump_source': lock['jump_source'],
                   'artifacts': lock['artifacts'], 'artifact_members': inventories,
                   'validated_input_files': before, 'validators': results,
                   'scope': 'Current structural/source eligibility only; output/root is not a packaged game.'}
        (work / 'provenance.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        shutil.copyfile(lock_path, work / 'reuse-lock.json')
        shutil.copyfile(metadata_path, work / 'origin-metadata.json')
        # Atomically claim a new directory; POSIX rename alone can replace an
        # existing empty directory. Publish the success receipt last.
        output.mkdir()
        for item in sorted(work.iterdir(), key=lambda p: p.name == 'provenance.json'):
            item.rename(output / item.name)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('source-root', 'lock', 'origin-metadata', 'jump-source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--expected-source-commit', required=True)
    parser.add_argument('--artifact', action='append', required=True, metavar='KIND=PATH')
    args = parser.parse_args()
    try:
        receipt = revalidate(args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print(f'companion reuse rejected: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'passed': receipt['passed'], 'output': str(args.output), 'generation_reused': True,
                      'new_generation': False, 'fresh_source_oracle_parity': False}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
