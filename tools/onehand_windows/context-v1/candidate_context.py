"""Versioned explicit Windows candidate identity. No native process or proof is run.

All trusted digests come from the caller's reviewed context, never a receipt's
self-declaration. This adapter checks consistency, not cryptographic host
attestation. It deliberately cannot label authored matching as evaluated parity.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import struct
import sys

SCHEMA = 'rust-duty-windows-candidate-context/v1'
MODE = 'fresh-Windows-production'
APPROVED_SHA = 'b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77'
BASE_SHA = '6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79'
DELTA_SHA = '7be513e2c9fa5d0ff1c00684c542a73354d49fd561fd406a08dad8e05c219a9d'
CANONICAL_SHA = 'd02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab'
GRID_SHA = 'a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f'
SOURCE_PINS_SHA = '0c7e6e1ef7a2f0c3637e7eb800d0fc7a1bd196c69bdb3c377db76680e0663a5f'
BRIDGE_SHA = '3453dcd587a5869a061420f8bf702a4c7968336876a4ec0a7e371767c9d213de'
ACTION = 'aella_mantle_onehand_r6_camera_reconstructed_v6'
FOCUS = tuple(55.65625 + i / 512 for i in range(9))
GIB = 1024**3

# Declarative constants only. This is not a replacement numerical implementation.
INVARIANTS = {
    'native_first_frame': 1, 'native_last_frame': 96, 'native_fps': 60,
    'source_samples': 4240, 'source_grid_sha256': GRID_SHA,
    'subdivisions': 256, 'runtime_keys': 24321, 'ticks_per_second': 15360,
    'block_count': 12, 'block_ticks': 2048, 'maximum_stored_keys': 2051,
    'frame_bytes': 3007, 'source_bones': 148, 'runtime_bones': 72,
    'actors': 3, 'skins': 3, 'skin_vertices': 10234,
    'skin_vertex_observations': 43392160, 'runtime_chunks': 67,
    'matrix_position_strict_max': 1e-4, 'projection_strict_max': 1e-5,
    'focus_frames': list(FOCUS), 'focus_offkeys': 4, 'focus_counts_toward_grid': False,
    'max_transforms': 2000000, 'max_file_bytes': 128 * 1024**2,
    'rss_bytes': 3 * GIB, 'initial_available_bytes': 3 * GIB + 512 * 1024**2,
    'disk_floor_bytes': GIB, 'sample_seconds': 0.2, 'stage_seconds': 1800,
}
INPUT_ROLES = {'baseline', 'original_delta', 'canonical', 'source_grid',
               'reference_replay', 'reference_index', 'reference_equivalence'}
OUTPUT_INPUT_ROLES = {'generated_source', 'target_replay', 'authored_admission',
                     'host_binding', 'prerequisites', 'actual_fbx', 'geometry', 'vrs', 'vrm'}
BLOCK_ROLES = {f'block_{i:02d}_{kind}' for i in range(12) for kind in ('receipt', 'frames')}
ALL_FILES = INPUT_ROLES | OUTPUT_INPUT_ROLES | BLOCK_ROLES
ROOT_ROLES = {'source_package', 'assembler_package', 'tools', 'blender_bundle', 'reference', 'process_adapter', 'native_window', 'native_dense'}


class ContextError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ContextError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(value, label='digest'):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None,
            label + ' must be lowercase SHA256')
    return value


def identifier(value, label):
    require(type(value) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,95}', value) is not None,
            label + ' must be a bounded ordinary identifier')
    return value


def exact_keys(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), label + ': missing or unknown fields')


def exact(actual, expected, label):
    # Prevent true/false from impersonating counts and clocks.
    require(type(actual) is type(expected) and actual == expected, label + ' differs')


def strict_json(path, cap=2 * 1024**2):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON field: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ContextError('nonfinite JSON number: ' + value)
    with ordinary(path, existing=True).open('rb') as stream:
        raw = stream.read(cap + 1)
    require(len(raw) <= cap, 'JSON byte cap exceeded')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad)
    except (ValueError, UnicodeError) as error:
        raise ContextError('invalid strict JSON: ' + str(error)) from error


def ordinary(value, *, existing=False):
    require(isinstance(value, (str, Path)) and '\0' not in str(value), 'invalid role path')
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'absolute ordinary path required')
    for component in path.parts[1:]:
        require(':' not in component and component == component.rstrip(' .')
                and not re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', component),
                'ambiguous Windows path component')
    # Do not resolve first: that would erase evidence of a symlink or junction.
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'symlink/reparse path is forbidden: ' + str(part))
    if existing:
        require(path.exists(), 'required role path is absent: ' + str(path))
    return path


def file_sha(path):
    path = ordinary(path, existing=True)
    value = hashlib.sha256()
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), 'ordinary regular file required')
        for block in iter(lambda: stream.read(64 * 1024), b''):
            value.update(block)
        after = os.fstat(stream.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'file changed during hashing')
    return value.hexdigest()


@dataclass(frozen=True)
class FilePin:
    role: str
    path: Path
    sha256: str

    @classmethod
    def parse(cls, role, value):
        exact_keys(value, ('path', 'sha256'), role)
        return cls(role, ordinary(value['path']), sha(value['sha256'], role))

    def verify(self):
        require(file_sha(self.path) == self.sha256, 'pinned bytes differ: ' + self.role)
        return self.path

    def record(self):
        return {'path': str(self.path), 'sha256': self.sha256}


@dataclass(frozen=True)
class HostBuildBinding:
    runner_id: str
    run_id: str
    system: str
    release: str
    version: str
    machine: str
    build_sha256: str

    @classmethod
    def parse(cls, value):
        exact_keys(value, cls.__dataclass_fields__, 'host')
        for key in ('runner_id', 'run_id'):
            identifier(value[key], key)
        exact(value['system'], 'Windows', 'target host system')
        require(value['machine'] in ('AMD64', 'x86_64'), 'x64 Windows target required')
        for key in ('release', 'version'):
            require(type(value[key]) is str and 0 < len(value[key]) <= 128 and '\0' not in value[key],
                    'observed Windows release/version required')
        sha(value['build_sha256'], 'build binding')
        return cls(**value)

    @property
    def expected_host(self):
        return {name: getattr(self, name) for name in ('system', 'release', 'version', 'machine')}

    def record(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def require_current_host(self):
        require(sys.platform == 'win32' and platform.system() == 'Windows' and struct.calcsize('P') == 8,
                'actual 64-bit Windows Python host required; fixture/context is not execution')
        actual = {'system': platform.system(), 'release': platform.release(),
                  'version': platform.version(), 'machine': platform.machine()}
        require(actual == self.expected_host, 'current host differs from pinned host binding')


@dataclass(frozen=True)
class ProofContext:
    candidate_id: str
    session_id: str
    private_root: Path
    roots: tuple[tuple[str, Path], ...]
    files: tuple[FilePin, ...]
    host: HostBuildBinding
    action_hashes: tuple[tuple[str, str], ...]
    static_state_sha256: str

    @classmethod
    def parse(cls, value):
        exact_keys(value, ('schema', 'mode', 'candidate_id', 'session_id', 'private_root',
                          'roots', 'files', 'host', 'lineage', 'invariants'), 'context')
        exact(value['schema'], SCHEMA, 'context schema')
        exact(value['mode'], MODE, 'candidate mode')
        exact_keys(value['invariants'], INVARIANTS, 'invariants')
        for key, expected in INVARIANTS.items():
            exact(value['invariants'][key], expected, 'invariant ' + key)
        exact_keys(value['roots'], ROOT_ROLES, 'root roles')
        exact_keys(value['files'], ALL_FILES, 'file roles')
        lineage = value['lineage']
        exact_keys(lineage, ('approved_source_sha256', 'source_package_pins_sha256',
                            'action_hashes', 'static_state_sha256'), 'lineage')
        exact(lineage['approved_source_sha256'], APPROVED_SHA, 'approved lineage')
        exact(lineage['source_package_pins_sha256'], SOURCE_PINS_SHA, 'source package lineage')
        exact_keys(lineage['action_hashes'], ('legacy', 'complete', 'metadata', 'auxiliary'), 'Action hashes')
        result = cls(identifier(value['candidate_id'], 'candidate'), identifier(value['session_id'], 'session'),
                     ordinary(value['private_root']),
                     tuple(sorted((role, ordinary(path)) for role, path in value['roots'].items())),
                     tuple(FilePin.parse(role, value['files'][role]) for role in sorted(ALL_FILES)),
                     HostBuildBinding.parse(value['host']),
                     tuple(sorted((key, sha(val, 'Action ' + key)) for key, val in lineage['action_hashes'].items())),
                     sha(lineage['static_state_sha256'], 'static state'))
        result.validate_roles()
        return result

    @property
    def candidate_root(self):
        return self.private_root / self.session_id / 'candidates' / self.candidate_id

    @property
    def owner_lock(self):
        return self.private_root / self.session_id / 'native-owner.lock'

    @property
    def runtime_output(self):
        return self.candidate_root / 'runtime' / 'asset.vra'

    def pin(self, role):
        return next(pin for pin in self.files if pin.role == role)

    def root(self, role):
        return dict(self.roots)[role]

    def validate_roles(self):
        paths = [pin.path for pin in self.files]
        folded = [str(path).casefold() for path in paths]
        require(len(set(folded)) == len(paths), 'file role paths alias')
        existing = [(p, p.stat()) for p in paths if p.exists()]
        identities = [(s.st_dev, s.st_ino) for _, s in existing]
        require(len(set(identities)) == len(identities), 'hardlinked role paths alias')
        root_paths = [path for _, path in self.roots]
        require(len({str(p).casefold() for p in root_paths}) == len(root_paths), 'root roles alias')
        for root in root_paths:
            require(not root.is_relative_to(self.private_root) and not self.private_root.is_relative_to(root),
                    'private evidence root overlaps protected root')
        for pin in self.files:
            ordinary(pin.path)
            if pin.role in OUTPUT_INPUT_ROLES | BLOCK_ROLES:
                require(pin.path.is_relative_to(self.candidate_root), 'foreign candidate/session role: ' + pin.role)
            else:
                require(not pin.path.is_relative_to(self.private_root), 'protected input placed in private evidence root')
        for role in ('reference_replay', 'reference_index', 'reference_equivalence'):
            require(self.pin(role).path.is_relative_to(self.root('reference')), 'reference role outside hash-only reference root')
        fixed = {'baseline': BASE_SHA, 'original_delta': DELTA_SHA, 'canonical': CANONICAL_SHA, 'source_grid': GRID_SHA}
        for role, expected in fixed.items():
            exact(self.pin(role).sha256, expected, role + ' immutable identity')
        require(self.pin('generated_source').sha256 not in (APPROVED_SHA, BASE_SHA),
                'generated source cannot launder approved/baseline identity')
        for i in range(12):
            receipt, frames = self.pin(f'block_{i:02d}_receipt'), self.pin(f'block_{i:02d}_frames')
            require(frames.path == receipt.path.parent / 'frames.bin', 'block frames must accompany their receipt')
        require(self.runtime_output not in paths and not self.runtime_output.exists(), 'fresh runtime output required')
        ordinary(self.owner_lock)
        ordinary(self.runtime_output)
        return self

    @property
    def binding(self):
        # Stable before generated receipts exist: no receipt/context hash cycle.
        return {'schema': 'rust-duty-windows-candidate-binding/v1', 'mode': MODE,
                'candidate_id': self.candidate_id, 'session_id': self.session_id,
                'runner_id': self.host.runner_id, 'run_id': self.host.run_id,
                'approved_source_sha256': APPROVED_SHA,
                'generated_source_sha256': self.pin('generated_source').sha256,
                'actual_fbx_sha256': self.pin('actual_fbx').sha256,
                'canonical_sha256': CANONICAL_SHA, 'source_grid_sha256': GRID_SHA,
                'authored_admission_sha256': self.pin('authored_admission').sha256,
                'host_build_sha256': self.host.build_sha256}

    @property
    def binding_sha256(self):
        return digest(self.binding)

    def record(self):
        return {'schema': SCHEMA, 'mode': MODE, 'candidate_id': self.candidate_id,
                'session_id': self.session_id, 'private_root': str(self.private_root),
                'roots': {name: str(path) for name, path in self.roots},
                'files': {pin.role: pin.record() for pin in self.files}, 'host': self.host.record(),
                'lineage': {'approved_source_sha256': APPROVED_SHA, 'source_package_pins_sha256': SOURCE_PINS_SHA,
                            'action_hashes': dict(self.action_hashes), 'static_state_sha256': self.static_state_sha256},
                'invariants': json.loads(canonical(INVARIANTS))}

    @property
    def context_sha256(self):
        return digest(self.record())

    def process_binding(self, environment):
        """Keywords for owned_process.HostBinding; does not launch or admit a host."""
        return {'runner_id': self.host.runner_id, 'run_id': self.host.run_id,
                'build_sha256': self.host.build_sha256, 'context_sha256': self.context_sha256,
                'expected_host': self.host.expected_host, 'environment': dict(environment),
                'owner_lock': str(self.owner_lock)}

    def verify_files(self):
        self.validate_roles()
        for pin in self.files:
            pin.verify()
        grid = strict_json(self.pin('source_grid').path)
        require(type(grid) is list and len(grid) == 4240 and all(type(x) in (int, float) and math.isfinite(x) for x in grid),
                'exact original 4240-time grid required')
        require(all(a < b for a, b in zip(grid, grid[1:])) and grid[0] == 1 and grid[-1] == 96,
                'source grid order/endpoints differ')
        require(file_sha(self.root('source_package') / 'PINS.json') == SOURCE_PINS_SHA, 'source package manifest differs')
        package_pins = strict_json(self.root('source_package') / 'PINS.json')
        require(type(package_pins) is dict and package_pins, 'source package pin inventory required')
        for name, expected in package_pins.items():
            require(Path(name).name == name and name not in ('.', '..'), 'unsafe source package pin name')
            require(file_sha(self.root('source_package') / name) == sha(expected), 'source package file differs: ' + name)
        index = strict_json(self.pin('reference_index').path)
        exact_keys(index, (f'{kind}-{i:03}.json' for i in range(17) for kind in ('approved', 'regenerated')),
                   'complete hash-only reference witnesses')
        for name, expected in index.items():
            require(file_sha(self.root('reference') / name) == sha(expected), 'hash-only reference witness differs: ' + name)
        require(self.pin('host_binding').sha256 == self.host.build_sha256, 'host binding pin differs')
        return self

    def validate_authored_receipt(self, data):
        fixed = {'schema': 'rust-duty-onehand-authored-input-bridge/v1', 'authored_input_admitted': True,
                 'source_relation': 'exact-base-and-original-delta; exact recorded Action/static state',
                 'approved_source_sha256': APPROVED_SHA, 'generated_source_sha256': self.pin('generated_source').sha256,
                 'baseline_sha256': BASE_SHA, 'delta_sha256': DELTA_SHA, 'canonical_sha256': CANONICAL_SHA,
                 'source_package_pins_sha256': SOURCE_PINS_SHA, 'bridge_sha256': BRIDGE_SHA,
                 'reference_replay_sha256': self.pin('reference_replay').sha256,
                 'reference_witness_index_sha256': self.pin('reference_index').sha256,
                 'reference_source_equivalence_sha256': self.pin('reference_equivalence').sha256,
                 'target_replay_sha256': self.pin('target_replay').sha256,
                 'action_hashes': dict(self.action_hashes), 'static_state_sha256': self.static_state_sha256,
                 'prior_actions_preserved': 88, 'result_action_count': 89,
                 'original_scalar_corrections': 12, 'unchanged_driven_outputs': 4,
                 'reference_samples': 4240, 'reference_chunk_pairs': 17,
                 'required_next_gate': 'Explicit distinct-source runtime contract and actual Windows all-grid/offkey proof'}
        false = ('source_byte_identity_with_approved', 'target_evaluated_source_equivalence_proved',
                 'cross_platform_float64_equality_proved', 'windows_execution_proved',
                 'runtime_equivalence_proved', 'activation_authorized', 'private_assets_copied_or_uploaded')
        fixed.update({name: False for name in false})
        exact_keys(data, (*fixed, 'reference_generated_source_sha256', 'limits'), 'authored receipt')
        for name, expected in fixed.items():
            exact(data[name], expected, 'authored ' + name)
        sha(data['reference_generated_source_sha256'], 'reference generated identity')
        exact(data['limits'], [
            'Admission is conditional on authentic externally pinned native replay/reference evidence.',
            'Receipts do not cryptographically attest the host or prove a native process ran.',
            'Only preservation categories covered by the frozen source producer are asserted.',
            'No cross-platform evaluated numeric equality follows from matching authored data.',
            'Do not substitute this generated source into an approved-source receipt.',
            'No current Linux FBX/VRA equivalence or art acceptance is inferred.'], 'authored limits')
        return data
