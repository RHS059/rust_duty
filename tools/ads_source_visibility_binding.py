#!/usr/bin/env python3
"""Bind conditional ADS source output to an independently validated capture.

This module does not establish native execution or prove the arithmetic/raster
assumptions. The caller verifies the original closed shard inventory, process
receipts, runtime/executable and unchanged existing validators. Only its
ads-offset coverage/structure exception may consult the returned source rows.

The portable packet deliberately wraps, rather than edits, the original source
receipt. ``files`` maps every original before/after inventory key to a regular
file beneath the packet directory. ``recorded_root`` resolves the receipt's
relative keys against its original execution root; no path is guessed or read
from that old location. Native and verifier identities remain separate.
The caller supplies the independently retained original receipt SHA-256. The
packet cannot supply its own trust anchor or refresh output hashes undetected.
"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import tomllib
import zlib

import dx12_authored_shards as shared
from run_dx12_authored_shard import role_witness_identity
import verify_capture_telemetry as telemetry


SCHEMA = 'rust-duty-ads-source-packet/v1'
ROLES = ('windows-legacy', 'dx12')
BACKENDS = {'windows-legacy': ('opengl', 'OpenGl', 'gl'), 'dx12': ('dx12', 'Dx12', 'dx12')}
FRAME_COUNT = 553
COMPANIONS = tuple(f'assets/{family}/asset.{ext}'
                   for family in ('locomotion', 'walk', 'ads', 'directional', 'jump', 'reload')
                   for ext in ('vra', 'vrs', 'vrm'))
INPUTS = set(COMPANIONS) | {'assets/animations.cfg', 'settings.cfg', 'ads-offset.cfg'}
MANIFEST_ASSETS = {'locomotion.asset': 'locomotion/asset.vra',
                   'reload.tactical.asset': 'reload/asset.vra',
                   'regular_walk.asset': 'directional/asset.vra',
                   'ads.asset': 'ads/asset.vra', 'jump.asset': 'jump/asset.vra'}
BACKEND_PROFILES = {
    'windows-legacy': 'opengl: Projection*Model*position; gamma17',
    'dx12': 'dx12: CPU (remap*Projection)*Model upload then shader MVP*position; gamma24',
}
PROFILE_FIELDS = {
    'numeric_profile': 'conditional normal-finite or exact-zero operations, no underflow/flush-to-zero/overflow, relative operation error <=2^-23, equivalent-or-tighter FMA; GL two matrix/vector stages or expanded16terms gamma17; DX12 two CPU four-term matrix products then GPU four-term dot gamma24; outward host allowance',
    'raster_profile': 'single sample at pixel center; at least 8 subpixel bits, displacement <=1/256 pixel; no culling; opaque depth winner; no alpha discard; x/y clipping produces coverage identical to the interval-bounded unclipped triangle inside the viewport (both interior and possible support)',
    'fragment_profile': 'RGB result differs from exact convex vertex/texture interpolation and multiplication by <=3 byte levels per channel; source texture alpha is overwritten to 255 as in adapter',
}
HEADER_FIELDS = json.loads('''{"schema":"rust-duty-source-visibility-certificate-diagnostic/v2",
    "scenario":"ads-offset","expected_frames":553,"extent":[960,540],
    "capture_hz":"60000/1001 as f32","profile":"m4a1","weapon_id":"hk416a5",
    "initial_ammo":12,"horizontal_fov_degrees":76,"near":0.01,"far":5.0,
    "fixed_dt_bits":"3c088889","acceptance_verdict":null}''', parse_float=telemetry._parse_float)
OFFSET_SUFFIX = '\nviewmodel_x = 0.20\nviewmodel_y = -0.20\nviewmodel_z = 0.20\n'
GAMEPLAY_STRINGS = {'segment', 'route', 'clip'}
GAMEPLAY_BOOLEANS = {'ads_requested', 'grounded', 'sprinting', 'mantling', 'renderer_failed'}
GAMEPLAY_INTEGERS = {'direction', 'ammo', 'reserve', 'shots'}
GAMEPLAY_NUMBERS = {'simulation_time', 'simulation_ads', 'speed', 'reload_left',
                    'reload_credit_at', 'reload_ready_at', 'walk_weight', 'run_weight', 'walk_min_rate'}
GAMEPLAY_NULLABLE_NUMBERS = {'native_clip_seconds', 'clip_duration', 'walk_seconds'}
GAMEPLAY_KEYS = (GAMEPLAY_STRINGS | GAMEPLAY_BOOLEANS | GAMEPLAY_INTEGERS
                 | GAMEPLAY_NUMBERS | GAMEPLAY_NULLABLE_NUMBERS)
TIME_KEYS = {'elapsed_seconds', 'normalized_phase', 'visual_duration_seconds',
             'simulation_ready_seconds', 'sampling_hz'}
ORACLE_TARGET = 'x86_64-pc-windows-msvc'
ORACLE_FEATURES = ['legacy-macroquad', 'wgpu-runtime']
ORACLE_ENVIRONMENT = {'RUSTFLAGS': None, 'CARGO_ENCODED_RUSTFLAGS': None, 'RUSTC_WRAPPER': None}
ORACLE_RELEASE_PROFILE = {'lto': 'thin', 'codegen-units': 1, 'strip': True}
ORACLE_EXAMPLES = ('source_visibility_certificate', 'source_visibility_certificate_telemetry',
                   'source_visibility_certificate_complete')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _parse(raw, label):
    try:
        value = json.loads(raw, parse_float=telemetry._parse_float,
                           parse_constant=telemetry._reject_constant,
                           object_pairs_hook=telemetry._unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError(f'{label}: {error}') from error
    _require(type(value) is dict and bool(value), f'{label}: expected nonempty JSON object')
    return value


def _digest(path):
    digest = shared._read_regular(path)
    return {'bytes': shared._checked_stat(path, 'file').st_size, 'sha256': digest}


def _digest_shape(value, label):
    shared._exact_keys(value, {'bytes', 'sha256'}, label)
    _require(type(value['bytes']) is int and value['bytes'] >= 0, f'{label}: invalid byte length')
    _require(type(value['sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['sha256']),
             f'{label}: invalid digest')


def _native_telemetry_shape(gameplay, timing, label):
    """Require the complete capture.rs ADS records, including otherwise unused fields.

    Rust Display emits whole-valued floats as integer JSON tokens. Other float
    tokens are parsed as Decimal by the unchanged strict telemetry reader. A
    bool is never a number, even though Python's bool subclasses int.
    """
    shared._exact_keys(gameplay, GAMEPLAY_KEYS, f'{label}/native_gameplay')
    shared._exact_keys(timing, TIME_KEYS, f'{label}/native_time')
    for field in GAMEPLAY_STRINGS:
        _require(type(gameplay[field]) is str, f'{label}/native_gameplay/{field}: expected string')
    for field in GAMEPLAY_BOOLEANS:
        _require(type(gameplay[field]) is bool, f'{label}/native_gameplay/{field}: expected boolean')
    for field in GAMEPLAY_INTEGERS:
        value = gameplay[field]
        _require(type(value) is int and (value in (-1, 0, 1) if field == 'direction' else value >= 0),
                 f'{label}/native_gameplay/{field}: expected capture integer')
    for field in GAMEPLAY_NUMBERS | GAMEPLAY_NULLABLE_NUMBERS:
        value = gameplay[field]
        if field in GAMEPLAY_NULLABLE_NUMBERS and value is None:
            continue
        _require(type(value) is int or (type(value) is Decimal and value.is_finite()),
                 f'{label}/native_gameplay/{field}: expected finite number')
    for field, value in timing.items():
        _require(type(value) is int or (type(value) is Decimal and value.is_finite()),
                 f'{label}/native_time/{field}: expected finite number')


def _recorded_path(value, root=None):
    """Resolve explicitly recorded Windows paths without using the local host."""
    _require(type(value) is str and bool(value), 'missing recorded Windows source path')
    path = PureWindowsPath(value)
    if path.drive:
        _require(re.fullmatch('[A-Za-z]:', path.drive) and path.is_absolute(),
                 'recorded source path must use an absolute Windows drive')
        relative = '/'.join(path.parts[1:])
        if relative:
            shared._safe_key(relative)
        return path.as_posix().casefold()
    _require(not path.root and root is not None, 'recorded source root must be an absolute Windows drive path')
    relative = value.replace('\\', '/')
    shared._safe_key(relative)
    return root.rstrip('/') + '/' + relative.casefold()


def _oracle_process(record, root, label):
    shared._exact_keys(record, {'command', 'cwd', 'exit_code', 'environment'}, label)
    _require(type(record['exit_code']) is int and record['exit_code'] == 0, f'{label}: unsuccessful process')
    _require(type(record['command']) is list and record['command']
             and all(type(part) is str and part for part in record['command']), f'{label}: malformed command')
    _require(_recorded_path(record['cwd']) == root, f'{label}: process cwd differs from oracle root')
    telemetry._compare(record['environment'], ORACLE_ENVIRONMENT, f'{label}: default compiler environment')
    return record['command']


def _oracle_build(command, example, recorded_root, recorded_paths, implementation):
    _require(PureWindowsPath(command[0]).name.casefold() in ('cargo', 'cargo.exe')
             and len(command) > 1 and command[1] == 'build', 'oracle build must use cargo build')
    switches, options = set(), {}
    index = 2
    while index < len(command):
        argument = command[index]
        if argument in ('--locked', '--release', '--no-default-features'):
            _require(argument not in switches, 'duplicate oracle build switch')
            switches.add(argument)
        else:
            option, separator, value = argument.partition('=')
            _require(option in ('--target', '--features', '--example', '--manifest-path')
                     and option not in options, 'unsupported or duplicate oracle build option')
            if not separator:
                index += 1
                _require(index < len(command), 'missing oracle build option value')
                value = command[index]
            _require(bool(value), 'empty oracle build option value')
            options[option] = value
        index += 1
    _require(switches == {'--locked', '--release', '--no-default-features'}, 'oracle build requires locked release without default features')
    _require(options.get('--target') == ORACLE_TARGET and options.get('--example') == example,
             'oracle build target/example differs')
    features = options.get('--features', '').split(',')
    _require(sorted(features) in (ORACLE_FEATURES, ['vector-range/' + feature for feature in ORACLE_FEATURES]),
             'oracle build must use exactly the native production features')
    if '--manifest-path' in options:
        _require(recorded_paths.get(_recorded_path(options['--manifest-path'], recorded_root)) == implementation['cargo.toml'],
                 'oracle build manifest differs from hash-bound Cargo.toml')


class BoundSourcePacket:
    """Read-only evidence binding; success is not a migration acceptance verdict."""

    def __init__(self):
        self.rows_by_role = {}
        self.headers_by_role = {}
        self.capture_binding = None
        self.source_base_commit = None
        self._snapshots = {}
        self._roots = {}
        self._frames = {}

    def _remember(self, path):
        path = Path(path).absolute()
        value = _digest(path)
        if path in self._snapshots:
            telemetry._compare(self._snapshots[path], value, f'{path}: late mutation')
        else:
            self._snapshots[path] = value
        return value

    def _read(self, path):
        before = self._remember(path)
        raw = Path(path).read_bytes()
        _require({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} == before,
                 f'{path}: changed during read')
        self._remember(path)
        return raw

    def _json(self, path):
        return _parse(self._read(path), path)

    def _portable(self, root, relative):
        shared._safe_key(relative)
        path = root
        for part in relative.split('/')[:-1]:
            path /= part
            shared._checked_stat(path, 'directory')
        path = root / relative
        shared._checked_stat(path, 'file')
        _require(path.resolve().is_relative_to(root.resolve()), 'packet file escapes root')
        return path

    def verify_frame_binding(self, path, role, index):
        """Recheck exact selected image and its full telemetry after binding."""
        _require(role in ROLES and type(index) is int and 0 <= index < FRAME_COUNT,
                 'invalid role/frame index')
        path = Path(path).absolute()
        _require(path == self._frames[role][index], 'frame path differs from bound capture')
        for suffix in ('', '.json', '.gameplay.json', '.time.json'):
            self._remember(Path(str(path) + suffix))
        row = self.rows_by_role[role][index]
        _native_telemetry_shape(row['native_gameplay'], row['native_time'], f'{role}/{index}')
        for suffix, key in (('.gameplay.json', 'native_gameplay'), ('.time.json', 'native_time')):
            telemetry._compare(row[key], self._json(Path(str(path) + suffix)),
                               f'{role}/{index}/{key}')
        return row

    def verify_unchanged(self):
        """Call after all validators/comparators, immediately before the verdict."""
        for root, names in self._roots.items():
            actual = {key for key, _ in shared._walk_files(root)} - {'verification.json'}
            _require(actual == names, f'{root}: bound file set changed')
        for path in tuple(self._snapshots):
            self._remember(path)


def bind_source_packet(packet_path, *, native_binding, original_invocations,
                       native_frame_dirs, native_offset_settings, expected_receipt_sha256,
                       expected_compiler_sha256):
    """Rehash the portable receipt and compare both complete native replays.

    ``native_binding`` and ``original_invocations`` come from the caller's
    independent original-shard validation, never from this packet. The offset
    path is the preserved original shard's ads-offset.cfg. The expected receipt
    digest must be retained outside this packet from the caller's independently
    verified source run; hashing the supplied receipt now and passing that value
    is not provenance. The compiler digest comes from the captured native build,
    independently of this packet. Matching it does not prove shader arithmetic
    guarantees. All original receipt flags are non-authoritative.
    """
    result = BoundSourcePacket()
    packet_path = Path(packet_path).absolute()
    root, _ = shared._checked_root(packet_path.parent)
    packet = result._json(packet_path)
    shared._exact_keys(packet, {'schema', 'capture_binding', 'original_invocations',
                               'receipt', 'recorded_root', 'files', 'source_outputs', 'input_files'}, 'source packet')
    _require(packet['schema'] == SCHEMA, 'unsupported source packet schema')
    shared.compare_binding(native_binding, packet['capture_binding'])
    result.capture_binding = deepcopy(native_binding)
    for value, label in ((original_invocations, 'original invocations'),
                         (packet['original_invocations'], 'packet invocations'),
                         (native_frame_dirs, 'native frame directories'),
                         (packet['source_outputs'], 'source outputs')):
        shared._exact_keys(value, ROLES, label)
    telemetry._compare(original_invocations, packet['original_invocations'], 'original native invocation')
    _require(type(expected_receipt_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_receipt_sha256),
             'expected source receipt SHA-256 must be independently supplied')
    receipt_path = result._portable(root, packet['receipt'])
    _require(result._remember(receipt_path)['sha256'] == expected_receipt_sha256,
             'source receipt differs from independently retained SHA-256')
    receipt = result._json(receipt_path)
    _require(receipt.get('schema') == 'rust-duty-source-visibility-certificates-binding/v1',
             'unsupported source receipt')
    commit = receipt.get('source_base_commit')
    _require(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit), 'invalid source replay commit')
    _require(commit == native_binding['source_commit'], 'source replay production commit differs from native capture')
    result.source_base_commit = commit
    before = receipt.get('inputs_and_implementation_before')
    after = receipt.get('inputs_and_implementation_after')
    _require(type(before) is dict and before, 'source before inventory missing')
    telemetry._compare(before, after, 'source implementation/input/executable before and after')
    files = packet['files']
    shared._exact_keys(files, before, 'portable file mapping')
    recorded_root = _recorded_path(packet['recorded_root'])
    actual_files, recorded_paths, implementation = {}, {}, {}
    for key, expected in before.items():
        _require(type(key) is str and key, 'invalid source inventory key')
        _digest_shape(expected, key)
        recorded = _recorded_path(key, recorded_root)
        _require(recorded not in recorded_paths, 'aliased recorded source path')
        path = result._portable(root, files[key])
        _require(path not in actual_files.values(), 'aliased portable source file')
        telemetry._compare(expected, result._remember(path), f'{key}: source bytes')
        actual_files[key] = path
        recorded_paths[recorded] = key
        if recorded.startswith(recorded_root + '/'):
            implementation[recorded[len(recorded_root) + 1:]] = key
    required_implementation = {'Cargo.toml', 'Cargo.lock', 'src/authored_viewmodel.rs',
                               'src/weapon_model.rs'}
    _require({name.casefold() for name in required_implementation} <= set(implementation)
             and ('run_bound_certificates.py' in implementation or 'tools/build_ads_source_packet.py' in implementation),
             'source implementation inventory incomplete')
    cargo = tomllib.loads(result._read(actual_files[implementation['cargo.toml']]).decode('utf-8'))
    release = cargo.get('profile', {}).get('release')
    telemetry._compare(release, ORACLE_RELEASE_PROFILE, 'oracle Cargo release profile')
    oracle = receipt.get('oracle_execution')
    shared._exact_keys(oracle, {'schema', 'platform', 'machine', 'host', 'target', 'profile',
                               'features', 'rustc_vv', 'build_receipt', 'execution_receipts', 'executable'},
                       'native Windows source oracle')
    for key, expected in {'schema': 'rust-duty-native-source-oracle/v1', 'platform': 'win32',
                          'host': ORACLE_TARGET, 'target': ORACLE_TARGET, 'profile': 'release',
                          'features': ORACLE_FEATURES}.items():
        telemetry._compare(oracle[key], expected, f'oracle {key}')
    _require(oracle['machine'] in ('AMD64', 'x86_64'), 'oracle must execute on native AMD64/x86_64 Windows')
    for key in ('rustc_vv', 'build_receipt', 'executable'):
        _require(type(oracle[key]) is str and oracle[key] in actual_files,
                 f'oracle {key} must name actual before/after hash-bound bytes')
    _require(type(expected_compiler_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_compiler_sha256),
             'expected captured compiler SHA-256 must be independently supplied')
    compiler_path = actual_files[oracle['rustc_vv']]
    _require(result._remember(compiler_path)['sha256'] == expected_compiler_sha256,
             'oracle compiler bytes differ from independently captured compiler SHA-256')
    compiler_lines = result._read(compiler_path).decode('utf-8').splitlines()
    _require(bool(compiler_lines) and compiler_lines[0].startswith('rustc ')
             and [line for line in compiler_lines if line.startswith('host:')] == ['host: ' + ORACLE_TARGET],
             'oracle rustc -Vv must identify the native Windows host')
    build_command = _oracle_process(result._json(actual_files[oracle['build_receipt']]), recorded_root, 'oracle build')
    shared._exact_keys(oracle['execution_receipts'], ('opengl', 'dx12'), 'oracle execution receipts')
    inputs = packet['input_files']
    shared._exact_keys(inputs, INPUTS, 'consumed inputs')
    _require(all(type(key) is str and key in files for key in inputs.values()), 'missing consumed input bytes')
    _require(len(set(inputs.values())) == len(INPUTS), 'consumed input aliases')
    native_hashes = native_binding['runtime_and_manifest_sha256']
    for name in INPUTS - {'ads-offset.cfg'}:
        _require(name in native_hashes, f'native input absent: {name}')
        _require(before[inputs[name]]['sha256'] == native_hashes[name], f'native/source input mismatch: {name}')
    offset_digest = result._remember(Path(native_offset_settings))
    telemetry._compare(before[inputs['ads-offset.cfg']], offset_digest, 'original native offset settings')
    base = result._read(actual_files[inputs['settings.cfg']]).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    offset = result._read(actual_files[inputs['ads-offset.cfg']]).decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    _require(offset == base + OFFSET_SUFFIX, 'offset settings differ from original exact base-plus-offset transform')
    manifest_values = {}
    for line in result._read(actual_files[inputs['assets/animations.cfg']]).decode('utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            _require('=' in line, 'malformed animation manifest')
            key, value = (part.strip() for part in line.split('=', 1))
            _require(key not in manifest_values, 'duplicate animation manifest key')
            manifest_values[key] = value
    _require({k: v for k, v in manifest_values.items() if k.endswith('.asset')} == MANIFEST_ASSETS
             and manifest_values.get('reload.empty') == 'unavailable', 'unsupported manifest dependency mapping')
    telemetry._compare(receipt.get('reviewed_manifest_dependency_mapping'), MANIFEST_ASSETS, 'source manifest mapping')
    reports = receipt.get('backend_reports')
    shared._exact_keys(reports, ('opengl', 'dx12'), 'source backend reports')
    catalog = {}
    for family in ('locomotion', 'reload'):
        name = f'assets/{family}/asset.vra'
        key = inputs[name]
        recorded = next(path for path, entry in recorded_paths.items() if entry == key)
        checksums = [zlib.crc32(result._read(actual_files[inputs[f'assets/{family}/asset.{ext}']]))
                     for ext in ('vrs', 'vrm')]
        catalog[recorded] = checksums
    source_executable = None
    for role in ROLES:
        backend, native_backend, renderer = BACKENDS[role]
        invocation = original_invocations[role]
        _require(type(invocation) is dict and type(invocation.get('cwd')) is str and invocation['cwd'],
                 f'{role}: malformed original invocation')
        command = invocation.get('command')
        _require(type(command) is list and command and all(type(arg) is str and arg for arg in command),
                 f'{role}: malformed original command')
        required_flags = [f'--renderer={renderer}', '--no-update', '--reference-viewport',
                          '--capture-sequence=gameplay-ads',
                          f'--capture-frame-witness={role_witness_identity(native_binding, "ads-offset", role)}']
        for flag in required_flags:
            _require(command.count(flag) == 1, f'{role}: wrong original capture flag {flag}')
        for prefix in ('--animation-manifest=', '--settings=', '--output=', '--renderer=',
                       '--capture-sequence=', '--capture-frame-witness='):
            _require(sum(arg.startswith(prefix) for arg in command) == 1, f'{role}: ambiguous {prefix}')
        _require(not any(arg.startswith('--capture-hz') for arg in command), f'{role}: unexpected capture rate')
        _require(command.count('--force-fallback-adapter') == (1 if role == 'dx12' else 0),
                 f'{role}: incorrect adapter invocation')
        report = reports[backend]
        _require(type(report) is dict and type(report.get('exit_code')) is int and report['exit_code'] == 0,
                 f'{role}: unsuccessful source replay')
        source_command = report.get('command')
        _require(type(source_command) is list and len(source_command) == 5
                 and all(type(part) is str for part in source_command), 'malformed source replay command')
        executable_path = _recorded_path(source_command[0])
        _require(executable_path in recorded_paths, 'source replay executable has no before/after hash')
        _require(recorded_paths[executable_path] == oracle['executable'], 'source executable differs from native oracle executable')
        example = PureWindowsPath(source_command[0]).name.removesuffix('.exe')
        _require(example in ORACLE_EXAMPLES
                 and f'examples/{example}.rs' in implementation,
                 'source replay executable must name its hash-bound known example')
        _oracle_build(build_command, example, recorded_root, recorded_paths, implementation)
        execution_command = _oracle_process(oracle['execution_receipts'][backend], recorded_root, f'oracle {backend}')
        telemetry._compare(source_command, execution_command, f'oracle {backend}: original execution command')
        if source_executable is None:
            source_executable = executable_path
        _require(executable_path == source_executable, 'source backends used different executables')
        _require(recorded_paths.get(_recorded_path(source_command[1])) == inputs['assets/animations.cfg']
                 and recorded_paths.get(_recorded_path(source_command[2])) == inputs['ads-offset.cfg']
                 and source_command[3] == backend, f'{role}: source invocation/input mismatch')
        output = result._portable(root, packet['source_outputs'][role])
        _require(_recorded_path(source_command[4]) == _recorded_path(packet['source_outputs'][role], recorded_root),
                 f'{role}: source output invocation path mismatch')
        _digest_shape(report.get('output'), f'{role}: source output')
        telemetry._compare(report['output'], result._remember(output), f'{role}: source output bytes')
        records = [_parse(line, f'{output}:{index + 1}') for index, line in enumerate(result._read(output).splitlines())]
        _require(len(records) == FRAME_COUNT + 1, f'{role}: source must enumerate all 553 frames')
        header, rows = records[0], records[1:]
        telemetry._compare(report.get('header'), header, f'{role}: source header receipt')
        for key, expected in {**HEADER_FIELDS, **PROFILE_FIELDS, 'backend_profile': BACKEND_PROFILES[role]}.items():
            telemetry._compare(expected, header.get(key), f'{role}: source header {key}')
        sources = header.get('sources')
        _require(type(sources) is list and len(sources) == len(catalog), 'source companion catalog incomplete')
        _require({_recorded_path(entry.get('vra')) for entry in sources if type(entry) is dict} == set(catalog),
                 'source companion catalog differs')
        for entry in sources:
            telemetry._compare(entry.get('companion_crc32'), catalog[_recorded_path(entry['vra'])], 'source companion CRC')
        folder, _ = shared._checked_root(Path(native_frame_dirs[role]).absolute())
        expected = {f'{index:04}.png{suffix}' for index in range(FRAME_COUNT)
                    for suffix in ('', '.json', '.gameplay.json', '.time.json')}
        actual = {key for key, _ in shared._walk_files(folder)}
        _require(actual - {'verification.json'} == expected, f'{role}: incomplete or unexpected native frame files')
        result._roots[folder] = expected
        result._frames[role] = [folder / f'{index:04}.png' for index in range(FRAME_COUNT)]
        result.rows_by_role[role] = rows
        result.headers_by_role[role] = header
        for index, row in enumerate(rows):
            _require(type(row.get('frame')) is int and row['frame'] == index, f'{role}: source frame order differs')
            catalog_path = _recorded_path(row.get('companion_catalog_vra'))
            _require(catalog_path in catalog, f'{role}/{index}: unknown companion catalog')
            telemetry._compare(row.get('companion_crc32'), catalog[catalog_path], 'frame companion CRC')
            for key in ('native_gameplay', 'native_time'):
                _require(type(row.get(key)) is dict and row[key], f'{role}/{index}: missing complete {key}')
            image = result._frames[role][index]
            metadata = result._json(Path(str(image) + '.json'))
            _require(metadata.get('backend') == native_backend and metadata.get('requested') == renderer,
                     f'{role}/{index}: native backend mismatch')
            _require(type(metadata.get('width')) is int and type(metadata.get('height')) is int
                     and (metadata['width'], metadata['height']) == (960, 540), f'{role}/{index}: native extent mismatch')
            result.verify_frame_binding(image, role, index)
    result.verify_unchanged()
    return result
