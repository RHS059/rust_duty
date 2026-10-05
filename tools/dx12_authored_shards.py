#!/usr/bin/env python3
"""Fail-closed shared provenance and file contracts for authored Windows shards.

These helpers inspect bytes only. They neither render nor assert native Windows
execution; the shard and aggregate entry points own that platform check.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

import run_dx12_authored as authored
import run_windows_gl_reference_probe as gl_probe
from verify_capture_telemetry import read_record


SCENARIOS = tuple(case.name for case in authored.CASES) + ('lighting-orientation',)
PROFILES = {
    name: dict(zip(('expected_frames', 'capture_timeout_seconds',
                    'run_timeout_seconds', 'step_timeout_minutes',
                    'job_timeout_minutes'), values))
    for name, values in (
        ('jump-gameplay', (403, 2100, 3300, 60, 75)),
        ('reload-gameplay', (214, 1200, 2400, 45, 60)),
        ('walk-gameplay', (223, 1500, 2700, 50, 65)),
        ('ads-gameplay', (553, 3000, 4200, 75, 90)),
        ('ads-offset', (553, 3000, 4200, 75, 90)),
        ('layered-30', (337, 2100, 3300, 60, 75)),
        ('layered-60', (673, 3900, 5100, 90, 105)),
        ('reload-return', (391, 1800, 3000, 55, 70)),
        ('lighting-orientation', (None, 900, 1800, 35, 50)),
    )
}
_CONTEXT_FIELDS = frozenset(('source_commit', 'run_id', 'run_attempt'))
_HASH_FIELDS = frozenset(('executable_sha256', 'renderer_contract_sha256',
                          'cargo_manifest_sha256', 'cargo_lock_sha256', 'gl_reference_sha256'))
_ASSET_FIELD = 'runtime_and_manifest_sha256'
_BINDING_FIELDS = _CONTEXT_FIELDS | _HASH_FIELDS | {_ASSET_FIELD}
_ASSET_SUFFIXES = frozenset(('.vra', '.vrs', '.vrm', '.json', '.cfg'))
_RESERVED_WINDOWS_NAMES = frozenset(('con', 'prn', 'aux', 'nul',
                                     *(f'com{i}' for i in '123456789¹²³'),
                                     *(f'lpt{i}' for i in '123456789¹²³')))


def _exact_keys(value, required, label):
    if type(value) is not dict or set(value) != set(required):
        raise ValueError(f'{label}: expected exactly {sorted(required)!r}')


def _validate_context(value):
    _exact_keys(value, _CONTEXT_FIELDS, 'GitHub context')
    commit = value['source_commit']
    if type(commit) is not str or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('source_commit must be an exact lowercase 40-hex GitHub SHA')
    for name in ('run_id', 'run_attempt'):
        if type(value[name]) is not str or not re.fullmatch(r'[1-9][0-9]*', value[name]):
            raise ValueError(f'{name} must be a positive decimal GitHub string')
    return value


def context():
    """Read the actual CI identity, with no local or default identity fallback."""
    return _validate_context({
        'source_commit': os.environ.get('GITHUB_SHA'),
        'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
    })


def _safe_key(key):
    # Use a portable relative POSIX spelling on both producer and consumer.
    # Windows device names, drive/ADS syntax and normalization aliases must not
    # acquire different meanings after download on another operating system.
    if type(key) is not str or not key or any(ord(char) < 32 or ord(char) == 127 or 0xd800 <= ord(char) <= 0xdfff for char in key):
        raise ValueError('inventory keys must be nonempty safe relative paths')
    if any(char in key for char in '\\<>:"|?*'):
        raise ValueError(f'unsafe relative path: {key!r}')
    for part in key.split('/'):
        if (part in ('', '.', '..') or part.endswith(('.', ' '))
                or part.split('.', 1)[0].casefold() in _RESERVED_WINDOWS_NAMES):
            raise ValueError(f'unsafe relative path: {key!r}')
    return key


def _validate_hash_map(value, label, *, require_settings=False):
    if type(value) is not dict:
        raise ValueError(f'{label} must be a path/hash object')
    if require_settings and (not value or 'settings.cfg' not in value):
        raise ValueError(f'{label} must contain settings.cfg')
    seen = {}
    for key, digest in value.items():
        _safe_key(key)
        parts = key.split('/')
        for length in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:length])
            kind = 'file' if length == len(parts) else 'directory'
            previous = seen.get(prefix.casefold())
            if previous is not None and previous != (prefix, kind):
                raise ValueError(f'{label} contains path aliases or file/directory conflicts')
            seen[prefix.casefold()] = (prefix, kind)
        if type(digest) is not str or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(f'{label}: invalid SHA-256 for {key!r}')
    return value


def _typed_equal(left, right):
    """JSON equality that never equates False with 0 or 1.0 with 1."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return (left.keys() == right.keys()
                and all(_typed_equal(left[key], right[key]) for key in left))
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def _binding_shape(binding):
    _exact_keys(binding, _BINDING_FIELDS, 'binding')
    _validate_context({name: binding[name] for name in _CONTEXT_FIELDS})
    for name in _HASH_FIELDS:
        digest = binding[name]
        if type(digest) is not str or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError(f'binding: invalid {name}')
    _validate_hash_map(binding[_ASSET_FIELD], _ASSET_FIELD, require_settings=True)
    return binding


def validate_binding(binding, expected_context=None):
    """Require a complete typed binding to the caller's actual source/run/attempt."""
    _binding_shape(binding)
    expected = context() if expected_context is None else _validate_context(expected_context)
    if not _typed_equal({name: binding[name] for name in _CONTEXT_FIELDS}, expected):
        raise ValueError('binding differs from the expected GitHub source/run/attempt')
    return binding


def compare_binding(a, b):
    """Compare complete, valid bindings without inventing a third CI context."""
    _binding_shape(a)
    _binding_shape(b)
    if not _typed_equal(a, b):
        raise ValueError('source/run/attempt, binaries or common inputs differ')
    return a


def _checked_stat(path, expected_kind):
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f'missing or unreadable {expected_kind}: {path}') from error
    reparse = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & reparse:
        raise ValueError(f'symlink or reparse point is not allowed: {path}')
    expected = stat.S_ISDIR if expected_kind == 'directory' else stat.S_ISREG
    if not expected(info.st_mode):
        raise ValueError(f'expected a regular {expected_kind}: {path}')
    return info


def _checked_root(folder):
    folder = Path(folder)
    _checked_stat(folder, 'directory')
    return folder, folder.resolve(strict=True)


def _walk_files(folder):
    """Walk without following links, checking all entries (also excluded files)."""
    folder, resolved = _checked_root(folder)
    seen = set()

    def visit(directory):
        _checked_stat(directory, 'directory')
        if not directory.resolve(strict=True).is_relative_to(resolved):
            raise ValueError('inventory directory escapes its root')
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError as error:
            raise ValueError(f'unreadable inventory directory: {directory}') from error
        for path in entries:
            key = _safe_key(path.relative_to(folder).as_posix())
            if key.casefold() in seen:
                raise ValueError('inventory contains case-insensitive path aliases')
            seen.add(key.casefold())
            info = path.lstat()
            # Test links before any is_file/is_dir operation that can follow one.
            if (stat.S_ISLNK(info.st_mode)
                    or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
                raise ValueError(f'symlink or reparse point is not allowed: {path}')
            if not path.resolve(strict=True).is_relative_to(resolved):
                raise ValueError('inventory path escapes its root')
            if stat.S_ISDIR(info.st_mode):
                yield from visit(path)
            elif stat.S_ISREG(info.st_mode):
                yield key, path
            else:
                raise ValueError(f'special file is not allowed: {path}')

    yield from visit(folder)


def _stat_identity(info, *, cross_api=False):
    """Keep file identity and timestamps, respecting Windows stat semantics.

    CPython 3.12+ path stat/lstat retain creation time in st_ctime_ns, while
    fstat exposes metadata-change time (cpython#157671). They are different
    clocks, not evidence of a replacement. Compare birthtime across those APIs
    when Windows supplies it, but retain ctime in both same-API race checks.
    POSIX cross-API comparisons keep their original ctime guard unchanged.
    """
    common = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    birth = getattr(info, 'st_birthtime_ns', None)
    if cross_api and sys.platform == 'win32' and birth is not None:
        return (*common, birth)
    return (*common, info.st_ctime_ns, birth)


def _read_regular(path, *, canonical_lf=False):
    """Hash a regular file and reject replacement or mutation during the read."""
    path = Path(path)
    before = _checked_stat(path, 'file')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or _stat_identity(before, cross_api=True) != _stat_identity(opened, cross_api=True)):
                raise ValueError(f'file changed before hashing: {path}')
            if canonical_lf:
                # Match Python universal-newline reading without changing any
                # other bytes, whitespace, encoding or trailing newline.
                data = stream.read().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
                digest = hashlib.sha256(data).hexdigest()
            else:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            # Keep the handle open while checking the current pathname. Each
            # API is compared to its own earlier observation; no ctime is lost.
            current = _checked_stat(path, 'file')
            after = os.fstat(stream.fileno())
    except OSError as error:
        raise ValueError(f'cannot hash regular file: {path}') from error
    if (_stat_identity(opened) != _stat_identity(after)
            or _stat_identity(before) != _stat_identity(current)
            or _stat_identity(after, cross_api=True) != _stat_identity(current, cross_api=True)):
        raise ValueError(f'file changed while hashing: {path}')
    return digest


def inventory_files(folder, exclude=('summary.json',)):
    """Bind every regular file; only the root summary may exclude its self-hash."""
    if type(exclude) not in (tuple, list) or tuple(exclude) not in ((), ('summary.json',)):
        raise ValueError('only the root summary.json may be excluded from an inventory')
    result = {key: _read_regular(path) for key, path in _walk_files(folder) if key not in exclude}
    return _validate_hash_map(result, 'files inventory')


def verify_files(folder, recorded, *, exclude=('summary.json',)):
    """Reject changed, added or missing files, including unrecorded raw evidence."""
    _validate_hash_map(recorded, 'files inventory')
    actual = inventory_files(folder, exclude=exclude)
    if 'summary.json' in recorded and 'summary.json' in exclude:
        raise ValueError('root summary.json cannot include its own inventory hash')
    if not _typed_equal(recorded, actual):
        missing = sorted(set(recorded) - set(actual))
        unexpected = sorted(set(actual) - set(recorded))
        changed = sorted(key for key in set(recorded) & set(actual) if recorded[key] != actual[key])
        raise ValueError(f'files inventory mismatch: missing={missing!r}, unexpected={unexpected!r}, changed={changed!r}')
    return actual


def _common_inputs(root):
    # Validate the tree before calling the existing source verifier: that helper
    # uses rglob/is_file and must not be allowed to follow an untrusted link.
    paths = [(f'assets/{key}', path) for key, path in _walk_files(root / 'assets')
             if path.suffix in _ASSET_SUFFIXES]
    _checked_stat(root / 'settings.cfg', 'file')
    evidence = authored.asset_evidence(root)
    if type(evidence) is not dict or _ASSET_FIELD not in evidence:
        raise ValueError('asset_evidence did not provide its source-validated common input map')
    recorded = _validate_hash_map(evidence[_ASSET_FIELD], _ASSET_FIELD, require_settings=True)
    actual = {key: _read_regular(path) for key, path in paths}
    actual['settings.cfg'] = _read_regular(root / 'settings.cfg')
    if not _typed_equal(recorded, actual):
        raise ValueError('source-validated common input inventory is inconsistent with current files')
    return dict(recorded)


GL_RUNTIME_PATH = Path('evidence/gl-runtime')
GL_LOCK_PATH = Path('tools/windows_gl_reference_lock.json')
GL_ENVIRONMENT = {'GALLIUM_DRIVER': 'llvmpipe', 'LIBGL_ALWAYS_SOFTWARE': 'true'}


def gl_reference_digest(reference):
    return hashlib.sha256(json.dumps(reference, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def make_gl_reference(runtime, manifest=None, *, game_sha256=None):
    """Verify the staged official lock, exact DLL/license closure and receipt.

    The PowerShell stager already validates pinned package hashes and PE imports.
    This byte-only recheck runs before use and after artifact transport. No DLLs
    are loaded here; actual llvmpipe identity is a separate native capture gate.
    """
    runtime = Path(runtime)
    files = inventory_files(runtime, exclude=())
    lock_path = runtime / 'windows_gl_reference_lock.json'
    if manifest is not None and _read_regular(manifest) != _read_regular(lock_path):
        raise ValueError('staged GL lock differs from current source lock')
    lock = read_record(lock_path)
    gl_probe.validate_runtime(runtime, lock_path)
    if lock.get('architecture') != 'x86_64' or lock.get('runtime_environment') != GL_ENVIRONMENT:
        raise ValueError('reference must be pinned x86_64 llvmpipe')
    expected = {'windows_gl_reference_lock.json', 'staging-receipt.json'}
    for entry in lock['dlls']:
        name = _safe_key(entry['dll'])
        if '/' in name or not name.lower().endswith('.dll'):
            raise ValueError('unsafe reference DLL name')
        expected.add(name)
    if not isinstance(lock.get('packages'), list) or not lock['packages']:
        raise ValueError('reference requires pinned package licenses')
    for package in lock['packages']:
        if not package.get('licenses'):
            raise ValueError('reference package lacks pinned licenses')
        for entry in package['licenses']:
            prefix = 'ucrt64/share/licenses/'
            member = entry['member']
            if not isinstance(member, str) or not member.startswith(prefix):
                raise ValueError('reference license outside pinned tree')
            name = 'licenses/' + _safe_key(member[len(prefix):])
            if name in expected:
                raise ValueError('duplicate reference member')
            expected.add(name)
            path = runtime / name
            if (type(entry.get('size')) is not int or entry['size'] <= 0
                    or _checked_stat(path, 'file').st_size != entry['size']
                    or _read_regular(path) != entry['sha256']):
                raise ValueError('reference license differs from pin')
    if game_sha256 is not None:
        if files.pop('vector-range.exe', None) != game_sha256:
            raise ValueError('app-local game differs from the single compiled binary')
    if set(files) != expected:
        raise ValueError('reference file inventory differs from pinned DLL/license closure')
    return {'schema': 'rust-duty-authored-app-local-gl/v1',
            'manifest_sha256': _read_regular(lock_path), 'files': files,
            'environment': dict(GL_ENVIRONMENT), 'expected_adapter_prefix': 'llvmpipe',
            'loaded_modules_verified': False,
            'scope': 'Pinned app-local Mesa bytes; actual renderer identity checked separately.'}


def verify_gl_reference(runtime, reference, *, game_sha256=None):
    actual = make_gl_reference(runtime, game_sha256=game_sha256)
    if not _typed_equal(reference, actual):
        raise ValueError('app-local GL reference bytes/provenance changed')
    return actual


def make_input_manifest(executable, fixture, root):
    """Bind the one dual-runtime build and immutable source-validated inputs."""
    ci = context()
    root, _ = _checked_root(root)
    reference = make_gl_reference(root / GL_RUNTIME_PATH, root / GL_LOCK_PATH)
    binding = {
        **ci,
        'gl_reference_sha256': gl_reference_digest(reference),
        'executable_sha256': _read_regular(executable),
        'renderer_contract_sha256': _read_regular(fixture),
        'cargo_manifest_sha256': _read_regular(root / 'Cargo.toml', canonical_lf=True),
        'cargo_lock_sha256': _read_regular(root / 'Cargo.lock', canonical_lf=True),
        _ASSET_FIELD: _common_inputs(root),
    }
    validate_binding(binding, ci)
    return {
        'schema': 'rust-duty-dx12-authored-inputs/v1',
        'platform': 'win32',
        'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
        'binding': binding,
        'gl_reference': reference,
        'expected_scenarios': list(SCENARIOS),
    }


def verify_input_manifest(manifest, executable, fixture, root):
    """Recompute and strictly compare the entire input contract, not a subset."""
    if type(manifest) is not dict:
        raise ValueError('input manifest must be an object')
    expected = make_input_manifest(executable, fixture, root)
    if not _typed_equal(manifest, expected):
        raise ValueError('input manifest schema, build, context or input bytes do not match')
    return expected['binding']


def capture_paths(scenario):
    """Return only the real role-relative capture roots for this scenario."""
    if type(scenario) is not str:
        raise ValueError('scenario must be an exact authored scenario name')
    if scenario == 'lighting-orientation':
        return {'dx12': 'captures/dx12/lighting', 'orientation': 'renderer-contract'}
    for case in authored.CASES:
        if scenario == case.name:
            return {'windows-legacy': f'captures/windows-legacy/{case.baseline}',
                    'dx12': f'captures/dx12/{case.name}'}
    raise ValueError(f'unknown authored scenario: {scenario!r}')
