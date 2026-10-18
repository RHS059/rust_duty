#!/usr/bin/env python3
"""Post-terminal, read-only diagnostics. Never imports or admits an addon.

Only the fresh, fixed hash-only report is written. There are no subprocess,
Blender, network, environment mutation, normalization acceptance, or pin-update
routes. A completed observation is not a passed native proof. The workflow's
original failure remains in force, and its summary is never modified.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import zipfile

MIB = 1024 ** 2
MEMBER_CAP = MIB
ADDON_TOTAL_CAP = 4 * MIB  # Installed and ZIP-member payloads combined.
JSON_CAP = 256 * 1024
REPORT_CAP = 32 * 1024
ARCHIVE_BYTES = 405138423
ARCHIVE_SHA = '933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6'
CONTEXT_PINS_SHA = '8702d486bc36a649924c3d844ea5eab445600f93995ec8367ea02d94e250c48a'
ADDON_PINS_SHA = '710ac9f97ba798dda2b4091232215bf0d973a03a07703448d184b420f5addb4f'
PROBE_SOURCE_SHA = '618eeef21e353a43e90855c2914c32b89d6c66e6b51a902b49825dfb958e57b1'
ORCHESTRATION_PINS_SHA = '946f4ed23f90ceb6886252c9c636ff2bfb37f4e0ae43e6bd6fad27ad8050eb26'
KNOWN_FAILURE_SHA = '8fbf4ddff747b03e580219fa0d2a3a80fb9b4c0664fdb437c1542514944ad737'
ARCHIVE_NAME = 'blender-4.3.2-windows-x64.zip'
BUNDLE_NAME = 'blender-4.3.2-windows-x64'
VENDOR = 'https://download.blender.org/release/Blender4.3/'
NAMES = frozenset(('__init__.py', 'data_types.py', 'encode_bin.py',
                   'export_fbx_bin.py', 'fbx2json.py', 'fbx_utils.py',
                   'fbx_utils_threading.py', 'import_fbx.py', 'json2fbx.py',
                   'parse_fbx.py'))
ERROR_TYPES = frozenset(('ContextError', 'ValueError', 'RuntimeError',
                        'AdapterError', 'AssertionError', 'OSError',
                        'FileNotFoundError', 'PermissionError', 'KeyError',
                        'TypeError', 'OverflowError', 'MemoryError'))


class ObservationError(ValueError):
    """Messages are fixed public error codes, never input text or paths."""


def require(condition, code):
    if not condition:
        raise ObservationError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def hash_value(value):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value),
            'invalid_sha256')
    return value


def component(value):
    require(type(value) is str and 0 < len(value) <= 255 and value not in ('.', '..') and
            value == value.rstrip(' .') and
            not any(ord(c) < 32 or c in ':\\/' for c in value) and
            not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value),
            'ambiguous_path_component')


def ordinary(value, *, existing=True, directory=False):
    require(isinstance(value, (str, Path)), 'invalid_path_type')
    p = Path(value)
    require(p.is_absolute() and '..' not in p.parts, 'absolute_path_required')
    if os.name == 'nt':
        require(re.fullmatch(r'[A-Za-z]:\\', p.anchor), 'local_drive_required')
    for part in p.parts[1:]:
        component(part)
    parents = list(reversed(p.parents))
    for part in parents + [p]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            require(not existing and part == p, 'required_path_missing')
            continue
        require(not stat.S_ISLNK(info.st_mode) and
                not (getattr(info, 'st_file_attributes', 0) & 0x400),
                'redirected_path')
        if part in parents or directory:
            require(stat.S_ISDIR(info.st_mode), 'directory_required')
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    'ordinary_single_link_file_required')
    return p


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def path_handle_identity(info):
    """Compare shared fields without mixing Windows timestamp domains.

    CPython 3.12.10 win32_xstat copies CreationTime into path st_ctime,
    whereas _Py_fstat_noraise exposes handle ChangeTime there. Both expose
    CreationTime explicitly as st_birthtime_ns. Keep full identity() for
    same-API before/after checks, including handle ChangeTime mutation.
    """
    if sys.platform != 'win32':
        return identity(info)
    birthtime = getattr(info, 'st_birthtime_ns', None)
    require(type(birthtime) is int and type(info.st_dev) is int and
            type(info.st_ino) is int and info.st_ino > 0,
            'windows_file_identity_unavailable')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            birthtime, info.st_nlink)


@contextlib.contextmanager
def open_read(path, cap, *, exact_size=None):
    p = ordinary(path)
    before = p.lstat()
    require(0 <= before.st_size <= cap and
            (exact_size is None or before.st_size == exact_size), 'file_size_bound')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(p, flags)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        require(stat.S_ISREG(opened.st_mode) and
                path_handle_identity(before) == path_handle_identity(opened),
                'input_changed_before_read')
        yield stream
        require(identity(opened) == identity(os.fstat(stream.fileno())),
                'input_changed_during_read')
    ordinary(p)
    require(identity(before) == identity(p.lstat()), 'input_changed_after_read')


def read_bytes(path, cap):
    with open_read(path, cap) as stream:
        raw = stream.read(cap + 1)
        require(len(raw) <= cap, 'file_size_bound')
    return raw


def file_hash(path, cap, *, exact_size=None):
    h = hashlib.sha256()
    size = 0
    with open_read(path, cap, exact_size=exact_size) as stream:
        while block := stream.read(MIB):
            size += len(block)
            require(size <= cap, 'file_size_bound')
            h.update(block)
    return h.hexdigest(), size


def strict_json(path, cap=JSON_CAP, expected=None):
    raw = read_bytes(path, cap)
    if expected is not None:
        require(sha(raw) == hash_value(expected), 'input_pin_mismatch')

    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate_json_key')
            value[key] = item
        return value

    def bad(_):
        raise ObservationError('nonfinite_json')

    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad)
    require(type(value) is dict, 'json_object_required')
    return value, sha(raw), len(raw)


def exact_keys(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'json_fields_differ')


def same_path(value, expected, *, directory=False):
    p = ordinary(value, directory=directory)
    require(p == expected, 'path_binding_differs')
    return p


def read_config(work, config_path, expected, run_id, attempt):
    require(type(run_id) is str and re.fullmatch(r'[1-9][0-9]{0,19}', run_id) and
            type(attempt) is str and re.fullmatch(r'[1-9][0-9]{0,9}', attempt),
            'run_identity_invalid')
    work = ordinary(work, directory=True)
    same_path(config_path, work / 'controller.json')
    config, config_sha, _ = strict_json(config_path, MIB, expected)
    exact_keys(config, ('byte_checkout', 'candidate_id', 'session_id', 'runner_id',
                       'run_id', 'private_root', 'evidence_root', 'roots', 'inputs',
                       'authored_bridge', 'blender_install_receipt', 'native_environment',
                       'runtime_environment', 'rust'))
    session = 'run-' + run_id + '-attempt-' + attempt
    require(config['candidate_id'] == 'onehand-v6-windows' and
            config['session_id'] == config['run_id'] == session,
            'candidate_identity_differs')
    require(type(config['runner_id']) is str and
            re.fullmatch(r'runner-[0-9a-f]{24}', config['runner_id']),
            'runner_identity_differs')
    private = same_path(config['private_root'], work / 'proof' / 'private', directory=True)
    evidence = same_path(config['evidence_root'], work / 'proof' / 'public-evidence', directory=True)
    candidate = ordinary(private / session / 'candidates' / config['candidate_id'], directory=True)
    require(type(config['roots']) is dict, 'roots_object_required')
    bundle = same_path(config['roots']['blender_bundle'],
                       work / 'blender-official' / BUNDLE_NAME, directory=True)
    context = ordinary(config['roots']['context_package'], directory=True)
    require(context == work / 'admission' / 'full-materialized' / 'context-v3',
            'context_root_outside_materialized')
    receipt = same_path(config['blender_install_receipt'], work / 'blender-install.json')
    owner = private / session / 'native-owner.lock'
    ordinary(owner, existing=False)
    require(not owner.exists(), 'native_owner_still_present')
    return config, config_sha, candidate, evidence, bundle, context, receipt


def original_outcome(evidence):
    value, digest, _ = strict_json(evidence / 'summary.json', 128 * 1024)
    require(value.get('schema') == 'rust-duty-onehand-windows-public-summary/v2' and
            type(value.get('passed')) is bool, 'native_summary_contract_differs')
    if value['passed']:
        require(value.get('error_type') is None and value.get('error_sha256') is None,
                'native_summary_error_conflict')
    else:
        require(value.get('error_type') in ERROR_TYPES, 'native_error_type_unavailable')
        hash_value(value.get('error_sha256'))
    # Its canonical config hash covers mutated in-memory config. Do not compare
    # that field to the separately verified, retained controller.json raw SHA.
    return {'summary_sha256': digest, 'passed': value['passed'],
            'error_type': value['error_type'], 'error_sha256': value['error_sha256']}


PROFILE_ID = 'blender-4.3.2-windows-x64-official-crlf-v1'
PROFILE_DISTRIBUTION = {'filename': ARCHIVE_NAME, 'bytes': ARCHIVE_BYTES, 'sha256': ARCHIVE_SHA}
PROFILE_HASH_DOMAINS = {
    'files': 'sha256(raw-file-bytes)',
    'raw_functions_sha256': 'sha256(utf8(raw-AST-function-slice-with-original-line-endings))',
    'loaded_functions_sha256': 'sha256(utf8(inspect.getsource(function)))'}
PROFILE_OBSERVATION = {
    'run_id': '39107154529', 'job_id': '117615400667',
    'head_sha': '01e3d821d197799a342b7738b84e835b11197f24',
    'artifact_bytes': 5181,
    'artifact_sha256': '2e23f39ca4a7f42f27338e34a51970237bdf04242e9770b346876ef36ed5e9c0',
    'report_bytes': 9422,
    'report_sha256': '5ee21d576be9af34c7b4095352aca1b4fde329eca23b79b6f12a189edc9d800a',
    'vendor_checksum_file_sha256': 'eee745a32c28b3e6ae90d246474dacfde6d2e05291c118b153d8ef72cff45c7f'}


def addon_pins(context):
    package, _, _ = strict_json(context / 'PINS.json', expected=CONTEXT_PINS_SHA)
    require(package.get('OFFICIAL_ADDON_PINS.json') == ADDON_PINS_SHA,
            'context_addon_binding_differs')
    value, _, _ = strict_json(context / 'OFFICIAL_ADDON_PINS.json', expected=ADDON_PINS_SHA)
    exact_keys(value, ('schema', 'profile_id', 'blender_version', 'distribution',
                       'observation', 'hash_domains', 'files', 'file_metadata',
                       'raw_functions_sha256', 'loaded_functions_sha256'))
    require(value['schema'] == 'rust-duty-windows-official-fbx-pins/v2' and
            value['profile_id'] == PROFILE_ID and value['blender_version'] == [4, 3, 2] and
            type(value['files']) is dict and set(value['files']) == NAMES,
            'addon_pin_contract_differs')
    for key, expected in (('distribution', PROFILE_DISTRIBUTION),
                          ('observation', PROFILE_OBSERVATION),
                          ('hash_domains', PROFILE_HASH_DOMAINS)):
        require(type(value[key]) is dict and canonical(value[key]) == canonical(expected),
                'addon_profile_provenance_differs')
    exact_keys(value['file_metadata'], NAMES)
    for name, digest in value['files'].items():
        hash_value(digest)
        metadata = value['file_metadata'][name]
        exact_keys(metadata, ('bytes', 'crlf_count', 'bare_lf_count', 'bare_cr_count'))
        require(all(type(n) is int for n in metadata.values()) and
                0 < metadata['bytes'] <= MEMBER_CAP and
                0 < 2 * metadata['crlf_count'] <= metadata['bytes'] and
                metadata['bare_lf_count'] == metadata['bare_cr_count'] == 0,
                'addon_profile_newline_metadata_differs')
    # Validate both declared domains separately; do not derive or compare them,
    # import functions, normalize installed bytes, or convert this into admission.
    for domain in ('raw_functions_sha256', 'loaded_functions_sha256'):
        exact_keys(value[domain], ('import_fbx.py',))
        exact_keys(value[domain]['import_fbx.py'],
                   ('blen_read_animations', 'blen_store_keyframes_multi'))
        for digest in value[domain]['import_fbx.py'].values():
            hash_value(digest)
    return value['files']


def verify_install(work, receipt_path, bundle):
    value, receipt_sha, _ = strict_json(receipt_path)
    exact_keys(value, ('schema', 'version', 'vendor_checksum_url', 'archive_url',
                       'vendor_sha256', 'archive_sha256', 'archive_bytes', 'archive_path',
                       'bundle_root', 'executable_sha256', 'vendor_checksum_verified',
                       'vendor_checksum_file'))
    fixed = {'schema': 'rust-duty-onehand-official-blender-install/v1', 'version': '4.3.2',
             'vendor_checksum_url': VENDOR + 'blender-4.3.2.sha256',
             'archive_url': VENDOR + ARCHIVE_NAME, 'vendor_sha256': ARCHIVE_SHA,
             'archive_sha256': ARCHIVE_SHA, 'archive_bytes': ARCHIVE_BYTES,
             'vendor_checksum_verified': True}
    for key, expected in fixed.items():
        require(type(value[key]) is type(expected) and value[key] == expected,
                'official_installer_contract_differs')
    same_path(value['bundle_root'], bundle, directory=True)
    archive = same_path(value['archive_path'], work / 'blender-official.zip')
    exact_keys(value['vendor_checksum_file'], ('path', 'sha256'))
    checksum = same_path(value['vendor_checksum_file']['path'],
                         work / 'blender-official.vendor.sha256')
    vendor_raw = read_bytes(checksum, 64 * 1024)
    require(sha(vendor_raw) == hash_value(value['vendor_checksum_file']['sha256']),
            'vendor_checksum_pin_differs')
    matches = [m.group(1).lower() for line in vendor_raw.decode('ascii').splitlines()
               if (m := re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?' +
                                    re.escape(ARCHIVE_NAME), line))]
    require(matches == [ARCHIVE_SHA], 'vendor_checksum_row_differs')
    actual, _ = file_hash(archive, ARCHIVE_BYTES, exact_size=ARCHIVE_BYTES)
    require(actual == ARCHIVE_SHA, 'official_archive_pin_differs')
    binary_sha, binary_bytes = file_hash(bundle / 'blender.exe', 512 * MIB)
    require(binary_sha == hash_value(value['executable_sha256']), 'installed_binary_pin_differs')
    return archive, binary_sha, {'installer_receipt_sha256': receipt_sha,
                                'vendor_checksum_file_sha256': sha(vendor_raw),
                                'official_archive_sha256': actual,
                                'official_archive_bytes': ARCHIVE_BYTES,
                                'blender_binary_sha256': binary_sha,
                                'blender_binary_bytes': binary_bytes,
                                'blender_version': [4, 3, 2]}


def probe_observation(candidate, bundle, binary_sha):
    path = candidate / 'blender-observed.json'
    ordinary(path, existing=False)
    if not path.exists():
        return None
    value, digest, _ = strict_json(path)
    exact_keys(value, ('schema', 'blender_version', 'blender_build_hash', 'blender_binary',
                       'blender_binary_sha256', 'python_runtime', 'python_runtime_sha256',
                       'fbx_addon_file', 'background', 'autoexec_disabled', 'source_saved', 'rendered'))
    require(value['schema'] == 'rust-duty-official-blender-host-observation/v1' and
            value['blender_version'] == [4, 3, 2] and
            value['blender_binary_sha256'] == binary_sha and
            value['background'] is True and value['autoexec_disabled'] is True and
            value['source_saved'] is False and value['rendered'] is False,
            'probe_contract_differs')
    same_path(value['blender_binary'], bundle / 'blender.exe')
    require(type(value['blender_build_hash']) is str and
            re.fullmatch(r'[0-9a-f]{7,64}', value['blender_build_hash']),
            'probe_build_identity_invalid')
    addon = ordinary(value['fbx_addon_file'])
    require(addon.is_relative_to(bundle) and addon.name == '__init__.py' and
            addon.parent.name == 'io_scene_fbx', 'probe_addon_escape')
    return addon.parent, {'observed_probe_sha256': digest,
                          'blender_build_id_sha256': sha(value['blender_build_hash'].encode('ascii'))}


def retained_process(candidate, config, bundle, binary_sha):
    """Bounded provenance checks, deliberately not a second process admission.

    No logs/streams are read. A terminal's self-hash is not a signature, and it
    does not seal the probe file. These limitations are explicit in the report.
    """
    context_path = candidate / 'contexts' / 'blender-host-observation-command.json'
    process = candidate / 'process' / 'blender-host-observation'
    paths = (context_path, process / 'terminal.json', process / 'terminal.sha256.json')
    # Missing intermediate directories are allowed only for the unavailable
    # path: check the existing prefix without following redirections.
    for path in paths:
        check = path
        while not check.exists() and not check.is_symlink():
            check = check.parent
        ordinary(check, directory=check.is_dir())
    if not all(p.exists() for p in paths):
        return None
    command, command_sha, _ = strict_json(context_path)
    terminal, terminal_sha, terminal_bytes = strict_json(paths[1])
    seal, seal_sha, _ = strict_json(paths[2])
    require(seal.get('path') == 'terminal.json' and seal.get('sha256') == terminal_sha and
            type(seal.get('bytes')) is int and seal['bytes'] == terminal_bytes,
            'process_terminal_seal_differs')
    source_root = ordinary(config['roots']['context_package'], directory=True).parent / 'orchestration'
    source_pins, _, _ = strict_json(source_root / 'PINS.json', expected=ORCHESTRATION_PINS_SHA)
    require(source_pins.get('probe_blender.py') == PROBE_SOURCE_SHA,
            'probe_source_binding_differs')
    probe_source = source_root / 'probe_blender.py'
    require(file_hash(probe_source, MIB)[0] == PROBE_SOURCE_SHA, 'probe_source_pin_differs')
    argv = [str(bundle / 'blender.exe'), '--background', '--factory-startup',
            '--disable-autoexec', '--threads', '1', '--python-exit-code', '1',
            '--python', str(probe_source), '--', str(candidate / 'blender-observed.json')]
    require(command.get('schema') == 'rust-duty-onehand-controller-command/v1' and
            command.get('label') == 'blender-host-observation' and command.get('argv') == argv and
            command.get('cwd') == str(candidate), 'probe_command_context_differs')
    require(command.get('executable', {}).get('path') == str(bundle / 'blender.exe') and
            command['executable'].get('sha256') == binary_sha,
            'probe_command_executable_differs')
    environment = config['native_environment']
    require(type(environment) is dict and len(environment) <= 256 and
            all(type(k) is str and type(v) is str for k, v in environment.items()) and
            len(canonical(environment)) <= 64 * 1024,
            'native_environment_contract_differs')
    require(command.get('environment_sha256') == sha(canonical(environment)),
            'command_environment_binding_differs')
    require(terminal.get('schema') == 'rust-duty-owned-process/v1' and
            terminal.get('command') == argv and terminal.get('cwd') == str(candidate) and
            terminal.get('state') == 'completed' and terminal.get('completed') is True and
            type(terminal.get('exit_code')) is int and terminal['exit_code'] == 0 and
            terminal.get('windows_job_empty_verified') is True and
            terminal.get('cleanup_complete') is True and terminal.get('consumer_complete') is True and
            terminal.get('timed_out') is False and terminal.get('resource_stop_reason') is None,
            'probe_terminal_not_complete')
    host = terminal.get('host_binding', {})
    require(host.get('context_sha256') == sha(canonical(command)) and
            host.get('run_id') == config['run_id'] and host.get('runner_id') == config['runner_id'] and
            host.get('owner_lock') == str(candidate.parent.parent / 'native-owner.lock') and
            host.get('observed_host', {}).get('system') == 'Windows' and
            host.get('environment_sha256') == sha(canonical(environment) + b'\n') and
            host.get('environment_keys') == sorted(environment), 'probe_terminal_binding_differs')
    return {'probe_command_context_sha256': command_sha, 'probe_terminal_sha256': terminal_sha,
            'probe_terminal_seal_sha256': seal_sha, 'probe_source_sha256': PROBE_SOURCE_SHA}


def newline_stats(raw):
    require(type(raw) is bytes and len(raw) <= MEMBER_CAP, 'member_size_bound')
    crlf = raw.count(b'\r\n')
    return {'bytes': len(raw), 'raw_sha256': sha(raw), 'crlf_count': crlf,
            'bare_lf_count': raw.count(b'\n') - crlf,
            'bare_cr_count': raw.count(b'\r') - crlf,
            'diagnostic_crlf_to_lf_sha256': sha(raw.replace(b'\r\n', b'\n'))}


def zip_name(name):
    require(type(name) is str and 0 < len(name) <= 4096 and '\\' not in name and '\x00' not in name,
            'unsafe_zip_name')
    stripped = name[:-1] if name.endswith('/') else name
    parts = stripped.split('/')
    for part in parts:
        component(part)
    require(not PurePosixPath(name).is_absolute(), 'unsafe_zip_name')
    return stripped.casefold()


def bounded_zip_directory(stream):
    """Bound the central directory before zipfile can allocate its index."""
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - 65557))
    tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    require(offset >= 0 and len(tail) - offset >= 22, 'zip_end_record_missing')
    end = struct.unpack('<4s4H2LH', tail[offset:offset + 22])
    _, disk, start_disk, disk_entries, entries, central_bytes, central_offset, comment = end
    require(disk == start_disk == 0 and disk_entries == entries and entries <= 50000 and
            entries != 65535 and central_bytes <= 16 * MIB and
            central_offset + central_bytes == size - len(tail) + offset and
            offset + 22 + comment == len(tail), 'zip_directory_bounds')
    stream.seek(0)


def member_rows(archive, bundle, addon, pins):
    """Read only the ten observed addon files and their corresponding ZIP entries."""
    require(addon.is_relative_to(bundle), 'addon_root_escape')
    prefix = BUNDLE_NAME + '/' + addon.relative_to(bundle).as_posix() + '/'
    rows = []
    total = 0
    # The exact archive was already hashed. Rehash the same open handle before
    # parsing the directory, rejecting replacement between those two stages.
    with open_read(archive, ARCHIVE_BYTES, exact_size=ARCHIVE_BYTES) as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(MIB), b''):
            h.update(block)
        require(h.hexdigest() == ARCHIVE_SHA, 'official_archive_pin_differs')
        bounded_zip_directory(stream)
        with zipfile.ZipFile(stream, 'r') as zf:
            entries = zf.infolist()
            require(len(entries) <= 50000, 'zip_entry_count_bound')
            unique = set()
            by_name = {}
            for info in entries:
                require(info.orig_filename == info.filename, 'unsafe_zip_name')
                key = zip_name(info.filename)
                require(key not in unique, 'duplicate_zip_name')
                unique.add(key)
                by_name[info.filename] = info
            selected = []
            for name in sorted(pins):
                require(name in NAMES, 'unallowlisted_addon_name')
                info = by_name.get(prefix + name)
                require(info is not None and not info.is_dir(), 'archive_member_missing')
                mode = (info.external_attr >> 16) & 0xFFFF
                require(stat.S_IFMT(mode) in (0, stat.S_IFREG) and not (info.flag_bits & 1) and
                        not (info.external_attr & 0x400),
                        'nonordinary_archive_member')
                require(0 <= info.file_size <= MEMBER_CAP and
                        0 <= info.compress_size <= MEMBER_CAP + 65536, 'member_size_bound')
                path = ordinary(addon / name)
                size = path.stat().st_size
                require(0 <= size <= MEMBER_CAP, 'member_size_bound')
                total += size + info.file_size
                require(total <= ADDON_TOTAL_CAP, 'addon_total_size_bound')
                selected.append((name, path, info))
            for name, path, info in selected:
                installed = read_bytes(path, MEMBER_CAP)
                with zf.open(info, 'r') as member:
                    archived = member.read(MEMBER_CAP + 1)
                    require(len(archived) == info.file_size and len(archived) <= MEMBER_CAP,
                            'archive_member_size_differs')
                expected = hash_value(pins[name])
                installed_stats, archived_stats = newline_stats(installed), newline_stats(archived)
                rows.append({'relative_filename': name, 'expected_raw_sha256': expected,
                             'installed': installed_stats, 'archive': archived_stats,
                             'archive_equals_installed': archived == installed,
                             'installed_raw_matches_expected': installed_stats['raw_sha256'] == expected,
                             'archive_raw_matches_expected': archived_stats['raw_sha256'] == expected})
    return rows, total


def write_report(path, report):
    raw = canonical(report) + b'\n'
    require(len(raw) <= REPORT_CAP, 'report_size_bound')
    p = ordinary(path, existing=False)
    require(not p.exists(), 'report_already_exists')
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(p, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    ordinary(p)


def observe(work, config_path, config_sha, run_id, attempt):
    work = ordinary(work, directory=True)
    config, raw_sha, candidate, evidence, bundle, context, receipt = read_config(
        work, config_path, config_sha, run_id, attempt)
    output = evidence / 'official-addon-observation.json'
    ordinary(output, existing=False)
    require(not output.exists(), 'report_already_exists')
    outcome = original_outcome(evidence)
    pins = addon_pins(context)
    archive, binary_sha, provenance = verify_install(work, receipt, bundle)
    report = {'schema': 'rust-duty-official-addon-observation/v1',
              'diagnostic_only': True, 'native_admission': False, 'animation_proof': False,
              'normalized_hash_acceptance': False, 'native_outcome_modified': False,
              'original_native_outcome': outcome, 'controller_config_raw_sha256': raw_sha,
              'context_pins_sha256': CONTEXT_PINS_SHA, 'addon_pins_sha256': ADDON_PINS_SHA,
              'probe_bytes_previously_sealed': False, 'full_process_admission_repeated': False,
              'provenance': provenance, 'files': [], 'addon_payload_bytes_read': 0}
    probe = probe_observation(candidate, bundle, binary_sha)
    process = retained_process(candidate, config, bundle, binary_sha)
    if probe is None or process is None:
        report['status'] = 'observation_unavailable'
        report['reason'] = 'original_probe_missing' if probe is None else 'retained_process_context_missing'
    else:
        addon, probe_hashes = probe
        report['provenance'].update(probe_hashes, **process)
        report['files'], report['addon_payload_bytes_read'] = member_rows(archive, bundle, addon, pins)
        report['status'] = 'observed_diagnostic_only'
    # Retain the exact original failure even when normalized hashes happen to
    # match or the observation succeeds. No proof/capture flags are upgraded.
    write_report(output, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-root', 'config', 'config-sha256', 'run-id', 'run-attempt'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        report = observe(args.work_root, args.config, args.config_sha256, args.run_id, args.run_attempt)
    except Exception as exc:
        # Untrusted file/parser/OS exceptions can contain sensitive input. Keep
        # public output constant; never print exception text, tracebacks or paths.
        print(json.dumps({'observation_complete': False,
                          'observation_error_sha256': sha(str(exc).encode('utf-8'))}))
        return 1
    print(json.dumps({'observation_complete': report['status'] == 'observed_diagnostic_only',
                      'diagnostic_only': True, 'native_admission': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
