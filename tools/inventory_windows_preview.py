#!/usr/bin/env python3
"""Read a Windows WIP preview ZIP without extracting or executing its contents."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import zipfile


REQUIRED_FILES = (
    'vector-range.exe', 'PLAYTEST_DX12.cmd', 'DX12_PREVIEW.json', 'BUILD_IDENTITY.json',
    'DX12_PREVIEW_README.txt', 'LICENSE', 'THIRD_PARTY_LICENSES.txt',
    'updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt', 'ui/theme.css',
    'ui/examples/high-contrast.css', 'ui/examples/large-type.css',
    'docs/UI_THEME.md', 'docs/UI_THEME_EXAMPLES.md', 'assets/animations.cfg',
)
LAUNCHER = '@echo off\ncd /d "%~dp0"\n"%~dp0vector-range.exe" --renderer=dx12 --no-update\nexit /b %ERRORLEVEL%\n'
MAX_TOTAL_BYTES = 4 * 1024**3
MAX_ENTRIES = 20_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalize_zip_member(name):
    """Reject ambiguous Windows extraction names; never perform extraction."""
    require(isinstance(name, str) and bool(name), 'empty ZIP path')
    require(not name.startswith(('/', '\\')) and '\\' not in name and ':' not in name,
            f'unsafe absolute, drive, stream or backslash path: {name!r}')
    require(not any(ord(char) < 32 or ord(char) == 127 for char in name), 'control character in ZIP path')
    parts = name.removesuffix('/').split('/')
    devices = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
    for part in parts:
        require(part not in ('', '.', '..') and not part.endswith((' ', '.')), f'unsafe ZIP component: {part!r}')
        require(not any(c in part for c in '<>"|?*'), f'invalid Windows ZIP component: {part!r}')
        require(part.split('.', 1)[0].upper() not in devices, f'reserved Windows ZIP component: {part!r}')
    return '/'.join(parts)


def _unique(pairs):
    row = {}
    for key, value in pairs:
        require(key not in row, f'duplicate JSON field: {key}')
        row[key] = value
    return row


def _constant(value):
    raise ValueError(f'non-finite JSON number: {value}')


def _json(data, name):
    require(len(data) <= 1024 * 1024, f'{name} exceeds 1 MiB')
    value = json.loads(data.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_constant)
    require(isinstance(value, dict) and bool(value), f'{name} must be a nonempty object')
    json.dumps(value, allow_nan=False)  # Also rejects exponent overflow in any field.
    return value


def _hash(value, name):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value), f'{name} must be SHA-256')
    return value


def _identity(preview, identity, executable, notices_hash):
    require(preview.get('schema') == 'rust-duty-dx12-wip-preview/v1', 'wrong preview schema')
    require(identity.get('schema') == 'rust-duty-build-identity/v1', 'wrong build identity schema')
    require(identity.get('target') == 'x86_64-pc-windows-msvc', 'wrong Windows build target')
    record = identity.get('executable')
    require(isinstance(record, dict), 'missing executable identity')
    require(record.get('name') == 'vector-range.exe' and type(record.get('size')) is int
            and record['size'] == executable['bytes'], 'executable name/size mismatch')
    for source in (preview, record):
        key = 'executable_sha256' if source is preview else 'sha256'
        require(_hash(source.get(key), key) == executable['sha256'], 'executable SHA256 mismatch')
    before, after = preview.get('source'), identity.get('source')
    require(isinstance(before, dict) and isinstance(after, dict) and before == after, 'preview/build source mismatch')
    require(isinstance(before.get('commit'), str) and re.fullmatch('[0-9a-f]{40}', before['commit']), 'invalid source commit')
    for name in ('run_id', 'run_number', 'run_attempt'):
        require(type(before.get(name)) is int and 0 < before[name] < 2**64, f'invalid source {name}')
    require(isinstance(before.get('branch'), str) and before['branch'].strip()
            and '\n' not in before['branch'], 'invalid source branch')
    require(before.get('workflow') == '.github/workflows/build.yml', 'unexpected source workflow')
    repository = identity.get('repository')
    require(isinstance(repository, str) and re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository), 'invalid repository')
    require(before.get('run_url') == f'https://github.com/{repository}/actions/runs/{before["run_id"]}', 'source run URL mismatch')
    version = identity.get('version')
    require(isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version), 'invalid build version')
    number = f'{before["run_id"]}.{before["run_attempt"]}'
    require(identity.get('build_number') == number and identity.get('display_version') == f'{version}+build.{number}'
            and preview.get('display_version') == identity['display_version'], 'build display identity mismatch')
    require(type(identity.get('sequence')) is int and identity['sequence'] > 0, 'invalid build sequence')
    require(preview.get('status') == 'WIP preview; M4 approval pending' and preview.get('default_renderer') == 'legacy',
            'preview must remain WIP with legacy default')
    require(preview.get('human_launch') == ['vector-range.exe', '--renderer=dx12', '--no-update'], 'unsafe declared human launcher')
    require(preview.get('enabled_features') == ['audio', 'legacy-macroquad', 'wgpu-runtime']
            and preview.get('dx12_shader_compiler') == 'Fxc', 'unexpected preview feature/compiler contract')
    require(preview.get('cargo_build_command') == ['cargo', 'build', '--locked', '--release', '--features',
                                                  'wgpu-runtime', '--bin', 'vector-range'], 'unexpected preview build command')
    notices = preview.get('game_dependency_notices')
    require(isinstance(notices, dict), 'missing notice provenance')
    require(_hash(notices.get('notice_sha256'), 'notice_sha256') == notices_hash, 'game notice SHA256 mismatch')
    _hash(notices.get('inventory_sha256'), 'inventory_sha256')
    smoke = preview.get('smoke')
    require(isinstance(smoke, dict) and smoke.get('backend') == 'Dx12'
            and smoke.get('adapter') == 'Microsoft Basic Render Driver'
            and type(smoke.get('frames')) is int and smoke['frames'] == 127, 'invalid smoke provenance')
    require(smoke.get('run_url') == before['run_url']
            and smoke.get('evidence_artifact') == f'dx12-warp-smoke-attempt-{before["run_attempt"]}', 'smoke run identity mismatch')
    for field in ('invocation_sha256', 'summary_sha256'):
        _hash(smoke.get(field), field)


def validate_zip_archive(zip_path, strict=False):
    """Inventory structure, CRCs and internal provenance consistency, never native acceptance."""
    try:
        path = Path(zip_path)
        require(not path.is_symlink(), 'ZIP input must not be a symlink')
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            require(0 < len(infos) <= MAX_ENTRIES, 'ZIP must have 1..20000 entries')
            require(sum(i.file_size for i in infos) <= MAX_TOTAL_BYTES, 'ZIP expands beyond 4 GiB inventory limit')
            members, folded = {}, set()
            for info in infos:
                name = normalize_zip_member(info.orig_filename)
                require(name.casefold() not in folded, f'duplicate/case-colliding ZIP path: {name}')
                folded.add(name.casefold())
                mode = (info.external_attr >> 16) & 0xffff
                require(not stat.S_ISLNK(mode), f'symlink ZIP entry: {name}')
                file_type = stat.S_IFMT(mode)
                require(file_type in (0, stat.S_IFREG, stat.S_IFDIR), f'nonregular ZIP entry: {name}')
                require(not file_type or (file_type == stat.S_IFDIR) == info.is_dir(), f'ambiguous directory entry: {name}')
                require(not info.is_dir() or info.file_size == 0, f'nonempty directory entry: {name}')
                require(not info.flag_bits & 1, f'encrypted ZIP entry: {name}')
                members[name] = info
            files = {name for name, info in members.items() if not info.is_dir()}
            file_keys = {name.casefold() for name in files}
            for name in members:
                require(not any('/'.join(name.split('/')[:i]).casefold() in file_keys
                                for i in range(1, len(name.split('/')))), f'file/directory conflict: {name}')
            prefix = ''
            if 'vector-range.exe' not in files:
                candidates = [name.split('/')[0] for name in files
                              if len(name.split('/')) == 2 and name.endswith('/vector-range.exe')]
                require(len(candidates) == 1, 'missing executable or ambiguous containing directory')
                prefix = candidates[0] + '/'
                require(all(name == prefix[:-1] or name.startswith(prefix) for name in members),
                        'archive contains files outside the package root')
            relative = {name[len(prefix):]: info for name, info in members.items()
                        if not info.is_dir() and (not prefix or name.startswith(prefix))}
            missing = sorted(set(REQUIRED_FILES) - relative.keys())
            require(not missing, f'missing required files: {missing}')
            for name in REQUIRED_FILES:
                require(relative[name].file_size > 0, f'empty required file: {name}')
            entries, saved = [], {}
            # Full streaming read triggers CRC validation for every member,
            # including entries using a data descriptor. Never extract anything.
            for name, info in members.items():
                digest, size = hashlib.sha256(), 0
                rel = name[len(prefix):] if prefix else name
                keep = rel in ('DX12_PREVIEW.json', 'BUILD_IDENTITY.json', 'PLAYTEST_DX12.cmd')
                require(not keep or info.file_size <= 1024 * 1024, f'{rel} exceeds 1 MiB')
                chunks = []
                with archive.open(info) as stream:
                    while chunk := stream.read(64 * 1024):
                        size += len(chunk)
                        require(size <= info.file_size and size <= MAX_TOTAL_BYTES, 'ZIP size exceeds declared bound')
                        digest.update(chunk)
                        if keep:
                            chunks.append(chunk)
                        if rel == 'vector-range.exe' and size == len(chunk):
                            require(chunk.startswith(b'MZ'), 'game executable has no Windows MZ signature')
                require(size == info.file_size, 'ZIP uncompressed size mismatch')
                if keep:
                    saved[rel] = b''.join(chunks)
                if not info.is_dir():
                    entries.append({'path': rel, 'bytes': size, 'sha256': digest.hexdigest()})
            by_name = {row['path']: row for row in entries}
            preview = _json(saved['DX12_PREVIEW.json'], 'DX12_PREVIEW.json')
            identity = _json(saved['BUILD_IDENTITY.json'], 'BUILD_IDENTITY.json')
            _identity(preview, identity, by_name['vector-range.exe'], by_name['THIRD_PARTY_LICENSES.txt']['sha256'])
            require(saved['PLAYTEST_DX12.cmd'].decode('utf-8').replace('\r\n', '\n') == LAUNCHER,
                    'launcher differs from the shipped DX12/no-update launcher')
            result = {'schema': 'rust-duty-windows-preview-inventory/v1', 'valid': True,
                      'package_root': prefix, 'files': sorted(relative), 'entries': sorted(entries, key=lambda r: r['path']),
                      'uncompressed_bytes': sum(row['bytes'] for row in entries),
                      'executable_sha256': by_name['vector-range.exe']['sha256'],
                      'source': preview['source'], 'display_version': preview['display_version'],
                      'status': preview['status'],
                      'scope': 'ZIP structure, CRC and internal provenance consistency only. No executable was run; smoke captures, licensing completeness, human visuals and native Windows behavior were not revalidated.'}
            if strict:
                result['details'] = {'all_member_crcs_checked': True, 'required_files_present': True,
                                     'provenance_consistent': True, 'launcher_matches_producer': True}
            return result
    except (OSError, ValueError, UnicodeError, RuntimeError, zipfile.BadZipFile, NotImplementedError, RecursionError) as error:
        return {'schema': 'rust-duty-windows-preview-inventory/v1', 'valid': False, 'error': str(error)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip-path', type=Path, required=True)
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--report', type=Path, help='Write a new report, never overwrite')
    args = parser.parse_args(argv)
    result = validate_zip_archive(args.zip_path, args.strict)
    text = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.report is not None:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open('x', encoding='utf-8') as output:
                output.write(text)
        except OSError as error:
            print(f'Cannot save inventory report: {error}', file=sys.stderr)
            return 1
    print(text, end='')
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
