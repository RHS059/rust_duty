"""Offline adversarial controls; synthetic fixtures are never native evidence."""
from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import warnings
import zipfile

import yaml

import revalidate_ebf_authored_packet as adapter
import build_ads_source_packet as fixed_producer
import finite_ads_profile_binding as finite_profile
from test_build_ads_source_packet import COMPILER, COMPILER_SHA
from test_dx12_authored_shards import make_gl_runtime


NOW = datetime(2026, 10, 6, 19, tzinfo=timezone.utc)
VERIFIER = {'source_commit': 'a' * 40, 'run_id': '999888777', 'run_attempt': '1'}


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if isinstance(raw, bytes) else (json.dumps(raw) + '\n').encode())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def catalog():
    run = deepcopy(adapter.PINS['attempt'])
    run['repository'] = {'full_name': adapter.REPOSITORY, 'id': adapter.REPOSITORY_ID}
    run['head_repository'] = deepcopy(run['repository'])
    artifacts = [{**deepcopy(row), 'expired': False} for row in adapter.PINS['artifacts'].values()]
    jobs = [deepcopy(row) for row in adapter.PINS['jobs'].values()]
    return {'attempt': run, 'artifacts': artifacts, 'complete': True, 'total_count': len(artifacts),
            'jobs': jobs, 'jobs_complete': True, 'jobs_total_count': len(jobs),
            'jobs_context': dict(adapter.CAPTURE)}


class SelectionTests(unittest.TestCase):
    def select(self, value):
        return adapter.select_artifacts(value, now=NOW)

    def test_current_pin_keeps_fixed_8f_identity_untouched(self):
        original = dict(fixed_producer.CAPTURE_CONTEXT)
        self.assertEqual(adapter.CAPTURE, {'source_commit': 'ebf4bcb7f489766e3c7ec188c35db9bb4146c62b',
                                          'run_id': '37490373763', 'run_attempt': '1'})
        self.assertNotEqual(adapter.CAPTURE, original)
        self.select(catalog())
        self.assertEqual(fixed_producer.CAPTURE_CONTEXT, original)
        self.assertEqual(original['source_commit'], '8f571464be706d0abde862e124582a188f633baf')

    def test_exact_current_packet_selects_all_nine_shards_and_seven_linux_inputs(self):
        original = catalog()
        before = deepcopy(original)
        selected = self.select(original)
        self.assertEqual(set(selected), set(adapter.PINS['artifacts']))
        self.assertEqual(len(selected), 23)
        self.assertEqual(len({row['id'] for row in selected.values()}), 23)
        self.assertEqual({key.removeprefix('shards/') for key in selected if key.startswith('shards/')},
                         set(adapter.shared.SCENARIOS))
        self.assertEqual(len([key for key in selected if key.startswith('legacy/')]), 7)
        self.assertEqual(original, before)
        self.assertEqual(original['attempt']['conclusion'], 'failure')

    def test_capture_metadata_every_pinned_field_is_required_and_exact(self):
        for field, pinned in adapter.PINS['attempt'].items():
            for wrong in (None, str(pinned) + '-changed'):
                with self.subTest(field=field, wrong=wrong):
                    value = catalog()
                    value['attempt'][field] = wrong
                    with self.assertRaises(ValueError):
                        self.select(value)

    def test_repository_and_fork_head_are_checked_by_name_and_numeric_identity(self):
        for key in ('repository', 'head_repository'):
            for field, wrong in (('full_name', 'someone/rust_duty'), ('id', 1),
                                 ('id', float(adapter.REPOSITORY_ID))):
                with self.subTest(key=key, field=field, wrong=wrong):
                    value = catalog()
                    value['attempt'][key][field] = wrong
                    with self.assertRaises(ValueError):
                        self.select(value)

    def test_original_failure_cannot_be_relabelled_successful(self):
        value = catalog()
        value['attempt']['conclusion'] = 'success'
        with self.assertRaises(ValueError):
            self.select(value)
        value = catalog()
        value['jobs'][1]['conclusion'] = 'success'
        with self.assertRaises(ValueError):
            self.select(value)

    def test_artifact_identity_digest_size_dates_and_origin_are_exact(self):
        for index in (0, 1, 8, 22):
            for field, wrong in (('id', 1), ('id', True), ('id', float(catalog()['artifacts'][index]['id'])),
                                 ('name', 'different-artifact'), ('digest', 'sha256:' + '0' * 64),
                                 ('size_in_bytes', 1), ('size_in_bytes', True),
                                 ('created_at', '2026-10-06T01:00:00Z'),
                                 ('updated_at', '2026-10-06T01:00:00Z'),
                                 ('expires_at', '2026-10-20T01:00:00Z'), ('expired', True), ('expired', 0)):
                value = catalog()
                value['artifacts'][index][field] = wrong
                with self.subTest(index=index, field=field, wrong=wrong), self.assertRaises(ValueError):
                    self.select(value)
            for field, wrong in (('id', 1), ('head_sha', 'b' * 40), ('head_branch', 'other'),
                                 ('repository_id', 1), ('head_repository_id', 1)):
                value = catalog()
                value['artifacts'][index]['workflow_run'][field] = wrong
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    self.select(value)

    def test_expiration_is_checked_against_the_clock_not_only_the_api_flag(self):
        with self.assertRaises(ValueError):
            adapter.select_artifacts(catalog(), now=datetime(2026, 10, 14, tzinfo=timezone.utc))

    def test_listing_completeness_counts_and_aliases_fail_closed(self):
        mutations = [lambda c: c.update(complete=False), lambda c: c.update(complete=1),
                     lambda c: c.update(total_count=c['total_count'] + 1),
                     lambda c: c.update(total_count=float(c['total_count'])),
                     lambda c: c['artifacts'].pop(),
                     lambda c: c['artifacts'].append(deepcopy(c['artifacts'][0])),
                     lambda c: c['artifacts'][1].update(id=c['artifacts'][0]['id'])]
        for index, mutate in enumerate(mutations):
            value = catalog()
            mutate(value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.select(value)

    def test_unrelated_artifact_is_allowed_but_extra_authored_shard_is_not_discarded(self):
        value = catalog()
        extra = {**deepcopy(value['artifacts'][0]), 'id': 999, 'name': 'unrelated-report'}
        value['artifacts'].append(extra)
        value['total_count'] += 1
        self.assertEqual(set(self.select(value)), set(adapter.PINS['artifacts']))
        extra['name'] = 'dx12-authored-shard-unknown-evidence-attempt-1'
        with self.assertRaises(ValueError):
            self.select(value)

    def test_unrelated_records_cannot_alias_selected_names_or_ids(self):
        for field in ('id', 'name'):
            value = catalog()
            extra = {**deepcopy(value['artifacts'][0]), 'id': 999, 'name': 'unrelated-report'}
            extra[field] = value['artifacts'][0][field]
            value['artifacts'].append(extra)
            value['total_count'] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.select(value)

    def test_job_context_completeness_identity_and_exact_steps_are_preserved(self):
        mutations = [lambda c: c.update(jobs_complete=False), lambda c: c.update(jobs_complete=1),
                     lambda c: c.update(jobs_total_count=c['jobs_total_count'] + 1),
                     lambda c: c.update(jobs_context={**adapter.CAPTURE, 'run_attempt': '2'}),
                     lambda c: c['jobs'].pop(),
                     lambda c: c['jobs'].append(deepcopy(c['jobs'][0]))]
        for index, mutate in enumerate(mutations):
            value = catalog()
            mutate(value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.select(value)
        for index in (0, 1):
            for field in adapter.PINS['jobs'][('inputs', 'aggregate')[index]]:
                value = catalog()
                value['jobs'][index][field] = None
                with self.subTest(job=index, field=field), self.assertRaises(ValueError):
                    self.select(value)
            value = catalog()
            value['jobs'][index]['steps'][0]['conclusion'] = 'failure'
            with self.subTest(job=index, field='step conclusion'), self.assertRaises(ValueError):
                self.select(value)


class ProductionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.capture = self.base / 'capture'
        self.verifier = self.base / 'verifier'
        self.names = ('Cargo.toml', 'Cargo.lock', 'src/main.rs', 'src/asset_path.rs',
                      'src/gpu_telemetry/windows.rs', 'assets/weapons/hk416a5.vrm')
        for root in (self.capture, self.verifier):
            for name in self.names:
                write(root / name, b'original synthetic bytes\n')

    def compare(self):
        def inventory(root):
            return {name: root / name for name in self.names if (root / name).is_file()}
        with patch.object(adapter.producer, 'production_files', side_effect=inventory), \
             patch.object(adapter.subprocess, 'run', side_effect=AssertionError('native execution forbidden')):
            return adapter.compare_production(self.capture, self.verifier)

    def test_exact_source_and_allowlisted_text_newlines_leave_original_bytes_unchanged(self):
        before = {(root.name, name): (root / name).read_bytes()
                  for root in (self.capture, self.verifier) for name in self.names}
        self.compare()
        for name in ('Cargo.toml', 'Cargo.lock', 'src/main.rs'):
            write(self.verifier / name, b'original synthetic bytes\r\n')
        self.compare()
        self.assertEqual({name: (self.capture / name).read_bytes() for name in self.names},
                         {name: before[('capture', name)] for name in self.names})

    def test_changed_source_or_binary_newlines_are_rejected(self):
        for name in self.names:
            original = (self.verifier / name).read_bytes()
            write(self.verifier / name, original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.compare()
            write(self.verifier / name, original)
        write(self.verifier / 'assets/weapons/hk416a5.vrm', b'original synthetic bytes\r\n')
        with self.assertRaises(ValueError):
            self.compare()

    def test_missing_production_file_cannot_be_silently_dropped(self):
        (self.verifier / self.names[0]).unlink()
        with self.assertRaises(ValueError):
            self.compare()

    def test_extra_production_file_cannot_be_silently_dropped(self):
        self.names += ('src/unreviewed.rs',)
        write(self.verifier / self.names[-1], b'new module')
        with self.assertRaises(ValueError):
            self.compare()

    def test_only_exact_reviewed_asset_path_test_fix_is_equivalent(self):
        name = 'src/asset_path.rs'
        repaired = (Path(__file__).resolve().parents[1] / name).read_bytes().replace(b'\r\n', b'\n')
        original = finite_profile._asset_path_test_base(repaired)
        self.assertNotEqual(original, repaired)
        write(self.capture / name, original)
        write(self.verifier / name, repaired)
        self.compare()
        write(self.verifier / name, repaired + b'\n// unreviewed test change\n')
        with self.assertRaises(ValueError):
            self.compare()

    def test_source_symlink_is_not_a_production_equivalence(self):
        path = self.verifier / 'src/main.rs'
        path.unlink()
        try:
            path.symlink_to(self.capture / 'src/main.rs')
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.compare()


class MaterializationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source, self.verifier, self.inputs, self.output = [self.base / name for name in
                                                               ('source', 'verifier', 'inputs', 'output')]
        for path in (self.source, self.verifier, self.inputs):
            path.mkdir()
        self.native_files = {'settings.cfg': b'viewmodel_offset_x=0\r\n',
            'assets/animations.cfg': b'normal_ready=synthetic\r\n',
            'assets/reload/asset.vra': b'synthetic runtime\x00\r\n',
            'assets/authoring/locomotion_directional/review/review.json': b'{"synthetic": true}\r\n'}
        for name, raw in self.native_files.items():
            write(self.source / name, raw.replace(b'\r\n', b'\n') if Path(name).suffix in ('.json', '.cfg') else raw)
        write(self.source / 'Cargo.toml', b'[package]\nname="synthetic"\n')
        write(self.source / 'Cargo.lock', b'version=4\n')
        write(self.verifier / 'tools/verify_synthetic.py', b'# Synthetic validator, never executed\n')
        reference = make_gl_runtime(self.inputs, manifest=self.verifier / adapter.shared.GL_LOCK_PATH)
        self.binaries = {'target/release/vector-range.exe': b'synthetic game, never executed',
                         'target/release/examples/renderer_contract.exe': b'synthetic contract, never executed'}
        for name, raw in self.binaries.items():
            write(self.inputs / name, raw)
        native = {**adapter.CAPTURE, 'gl_reference_sha256': adapter.shared.gl_reference_digest(reference),
            'executable_sha256': sha(self.binaries['target/release/vector-range.exe']),
            'renderer_contract_sha256': sha(self.binaries['target/release/examples/renderer_contract.exe']),
            'cargo_manifest_sha256': adapter.shared._read_regular(self.source / 'Cargo.toml'),
            'cargo_lock_sha256': adapter.shared._read_regular(self.source / 'Cargo.lock'),
            'runtime_and_manifest_sha256': {name: sha(raw) for name, raw in self.native_files.items()}}
        self.manifest = {'schema': 'rust-duty-dx12-authored-inputs/v1', 'platform': 'win32',
            'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
            'binding': native, 'gl_reference': reference, 'expected_scenarios': list(adapter.shared.SCENARIOS)}
        self.manifest_path = self.inputs / 'evidence/authored-inputs/input-manifest.json'
        write(self.manifest_path, self.manifest)

    def materialize(self):
        with patch.object(adapter.subprocess, 'run', side_effect=AssertionError('native execution forbidden')), \
             patch.object(adapter.subprocess, 'check_output', side_effect=AssertionError('no subprocess expected')):
            return adapter.materialize_root(self.source, self.verifier, self.inputs, self.output, self.manifest)

    def test_full_original_manifest_bytes_and_gl_lock_are_reconstructed_without_mutating_inputs(self):
        snapshots = {root: adapter.shared.inventory_files(root, exclude=()) for root in (self.source, self.inputs)}
        write(self.verifier / adapter.shared.GL_LOCK_PATH, b'new verifier GL pin cannot replace original')
        result = self.materialize()
        self.assertEqual(set(result['runtime_and_manifest_files']), set(self.native_files))
        for name, raw in self.native_files.items():
            self.assertEqual((self.output / name).read_bytes(), raw)
        for name, raw in self.binaries.items():
            self.assertEqual((self.output / name).read_bytes(), raw)
        self.assertEqual((self.output / adapter.shared.GL_LOCK_PATH).read_bytes(),
                         (self.inputs / adapter.shared.GL_RUNTIME_PATH / adapter.shared.GL_LOCK_PATH.name).read_bytes())
        for root, inventory in snapshots.items():
            self.assertEqual(adapter.shared.inventory_files(root, exclude=()), inventory)
        self.assertEqual(adapter.aggregate.validated_manifest(self.manifest_path, self.output,
                         expected_context=adapter.CAPTURE), self.manifest['binding'])

    def test_missing_or_mismatched_metadata_outside_ads_leaf_is_not_dropped(self):
        name = 'assets/authoring/locomotion_directional/review/review.json'
        path = self.source / name
        for raw in (None, b'{ "synthetic" : true }\n'):
            if raw is None:
                path.unlink()
            else:
                write(path, raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.materialize()
            self.assertFalse((self.output / name).exists())
            if self.output.exists():
                shutil.rmtree(self.output)

    def test_binary_runtime_newlines_cannot_be_normalized(self):
        name = 'assets/reload/asset.vra'
        write(self.source / name, self.native_files[name].replace(b'\r\n', b'\n'))
        with self.assertRaises(ValueError):
            self.materialize()

    def test_changed_executables_and_gl_runtime_are_rejected(self):
        for name in (*self.binaries, 'evidence/gl-runtime/opengl32.dll'):
            path = self.inputs / name
            original = path.read_bytes()
            write(path, b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.materialize()
            write(path, original)
            if self.output.exists():
                shutil.rmtree(self.output)

    def test_wrong_cargo_or_capture_identity_is_rejected(self):
        for name in ('Cargo.toml', 'Cargo.lock'):
            path = self.source / name
            original = path.read_bytes()
            write(path, original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.materialize()
            write(path, original)
            if self.output.exists():
                shutil.rmtree(self.output)
        self.manifest['binding'].update(fixed_producer.CAPTURE_CONTEXT)
        with self.assertRaises(ValueError):
            self.materialize()

    def test_case_aliased_or_symlinked_runtime_inputs_fail_before_staging(self):
        alias = self.source / 'assets/ANIMATIONS.cfg'
        write(alias, b'case alias')
        with self.assertRaises(ValueError):
            self.materialize()
        self.assertFalse(self.output.exists())
        alias.unlink()
        path = self.source / 'assets/reload/asset.vra'
        outside = self.base / 'outside.vra'
        path.rename(outside)
        try:
            path.symlink_to(outside)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.materialize()
        self.assertFalse(self.output.exists())

    def test_symlinked_metadata_parent_fails_before_staging(self):
        path = self.source / 'assets/authoring/locomotion_directional/review'
        outside = self.base / 'outside-review'
        path.rename(outside)
        try:
            path.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.materialize()
        self.assertFalse(self.output.exists())

    def test_original_root_beneath_symlinked_ancestor_is_rejected_before_staging(self):
        outside = self.base / 'outside-source'
        outside.mkdir()
        self.source.rename(outside / 'source')
        alias = self.base / 'source-alias'
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        self.source = alias / 'source'
        with self.assertRaises(ValueError):
            self.materialize()
        self.assertFalse(self.output.exists())

    def test_materialized_root_cannot_be_existing_or_overlap_original_inputs(self):
        for output in (self.source / 'new-output', self.inputs / 'new-output', self.verifier / 'new-output', self.base):
            self.output = output
            with self.subTest(output=str(output)), self.assertRaises(ValueError):
                self.materialize()

    def test_candidate_mutation_during_staging_is_detected(self):
        original_write = adapter.write_bytes
        first = next(iter(self.native_files))
        def write_and_change_source(path, raw):
            original_write(path, raw)
            if path == self.output / first:
                write(self.source / first, b'changed after staging')
        with patch.object(adapter, 'write_bytes', side_effect=write_and_change_source):
            with self.assertRaisesRegex(ValueError, 'candidate changed'):
                self.materialize()

    def test_symlinked_output_parent_fails_before_writing_outside_the_requested_tree(self):
        outside = self.base / 'outside'
        outside.mkdir()
        alias = self.base / 'alias'
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        self.output = alias / 'materialized'
        with self.assertRaises(ValueError):
            self.materialize()
        self.assertEqual(list(outside.iterdir()), [])


class DownloadInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inventories = {}
        for destination in adapter.PINS['artifacts']:
            write(self.root / destination / 'original.bin', ('synthetic original ' + destination).encode())
            self.inventories[destination] = adapter.shared.inventory_files(self.root / destination, exclude=())

    def verify(self):
        return adapter.verify_downloads(self.root, self.inventories)

    def test_all_23_exact_immutable_download_inventories_verify(self):
        before = deepcopy(self.inventories)
        self.verify()
        self.assertEqual(self.inventories, before)

    def test_missing_extra_or_empty_artifact_inventory_cannot_be_accepted(self):
        original = deepcopy(self.inventories)
        variants = [dict(list(original.items())[1:]), {**original, 'unrequested': {'original.bin': 'a' * 64}},
                    {**original, 'source': {}}]
        for index, inventories in enumerate(variants):
            self.inventories = inventories
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.verify()

    def test_postdownload_byte_mutation_deletion_and_addition_fail(self):
        for destination in ('inputs', 'source', 'shards/ads-offset', 'legacy/layered'):
            path = self.root / destination / 'original.bin'
            original = path.read_bytes()
            write(path, original + b'changed')
            with self.subTest(destination=destination, mutation='bytes'), self.assertRaises(ValueError):
                self.verify()
            path.unlink()
            with self.subTest(destination=destination, mutation='missing'), self.assertRaises(ValueError):
                self.verify()
            write(path, original)
            extra = path.parent / 'added.bin'
            write(extra, b'added')
            with self.subTest(destination=destination, mutation='extra'), self.assertRaises(ValueError):
                self.verify()
            extra.unlink()

    def test_postdownload_file_symlink_and_case_alias_fail(self):
        path = self.root / 'source/original.bin'
        alias = path.with_name('ORIGINAL.bin')
        write(alias, path.read_bytes())
        with self.assertRaises(ValueError):
            self.verify()
        alias.unlink()
        outside = self.root / 'outside.bin'
        path.rename(outside)
        try:
            path.symlink_to(outside)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.verify()

    def test_postdownload_symlinked_artifact_ancestor_cannot_reuse_matching_bytes(self):
        shards = self.root / 'shards'
        outside = self.root / 'outside-shards'
        shards.rename(outside)
        try:
            shards.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.verify()


class CallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': adapter.REPOSITORY,
                            'GITHUB_REPOSITORY_ID': str(adapter.REPOSITORY_ID),
                            'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                            'GITHUB_WORKFLOW_REF': adapter.REPOSITORY +
                                '/.github/workflows/revalidate-ebf-authored-packet.yml@refs/heads/main',
                            'GITHUB_WORKFLOW_SHA': VERIFIER['source_commit'],
                            'GITHUB_SHA': VERIFIER['source_commit'], 'GITHUB_RUN_ID': VERIFIER['run_id'],
                            'GITHUB_RUN_ATTEMPT': VERIFIER['run_attempt']}

    def current(self, *, head=None, dirty=b''):
        def git_output(command, **kwargs):
            self.assertEqual(command[:3], ['git', '-C', str(self.root)])
            if command[3:5] == ['rev-parse', 'HEAD']:
                output = head or self.environment['GITHUB_SHA']
            elif command[3] == 'status':
                output = dirty.decode()
            else:
                self.fail(f'unexpected subprocess: {command}')
            return output if kwargs.get('text') else output.encode()
        with patch.dict(os.environ, self.environment, clear=True), \
             patch.object(adapter.subprocess, 'check_output', side_effect=git_output), \
             patch.object(adapter.subprocess, 'run', side_effect=AssertionError('native execution forbidden')):
            before = dict(os.environ)
            result = adapter.current_verifier(self.root)
            self.assertEqual(dict(os.environ), before)
            return result

    def test_new_workflow_retains_actual_caller_identity_without_environment_spoofing(self):
        self.current()
        self.environment['GITHUB_EVENT_NAME'] = 'push'
        self.current()

    def test_caller_context_cannot_claim_original_capture(self):
        self.environment.update(GITHUB_SHA=adapter.CAPTURE['source_commit'],
                                GITHUB_WORKFLOW_SHA=adapter.CAPTURE['source_commit'],
                                GITHUB_RUN_ID=adapter.CAPTURE['run_id'],
                                GITHUB_RUN_ATTEMPT=adapter.CAPTURE['run_attempt'])
        with self.assertRaises(ValueError):
            self.current()

    def test_every_actual_caller_field_is_required_and_wrong_values_are_rejected(self):
        original = dict(self.environment)
        for field in original:
            self.environment = {key: value for key, value in original.items() if key != field}
            with self.subTest(field=field, mutation='missing'), self.assertRaises(ValueError):
                self.current()
        for field, wrong in (('GITHUB_ACTIONS', 'false'), ('GITHUB_REPOSITORY', 'fork/rust_duty'),
                             ('GITHUB_REPOSITORY_ID', '1'), ('GITHUB_REF', 'refs/heads/feature'),
                             ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_WORKFLOW_REF', 'other'),
                             ('GITHUB_WORKFLOW_SHA', 'b' * 40), ('GITHUB_SHA', 'moving-ref'),
                             ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '0')):
            self.environment = {**original, field: wrong}
            with self.subTest(field=field, mutation=wrong), self.assertRaises(ValueError):
                self.current()

    def test_modified_verifier_checkout_and_wrong_head_fail(self):
        for kwargs in ({'head': 'b' * 40}, {'dirty': b' M tools/validator.py\n'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.current(**kwargs)


class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.inputs = self.log(COMPILER.decode().splitlines() + [
            'Cache key: authored-dual-release-v1-Windows-X64-' + COMPILER_SHA + '-' + 'c' * 64 +
            '-' + adapter.CAPTURE['source_commit'], 'PRECOMPILED_ORACLE_RECEIPT_SHA256=' + 'd' * 64])
        self.aggregate = self.log(['INDEPENDENT_SOURCE_RECEIPT_SHA256=' + 'e' * 64,
            'ValueError: unreviewed production file added',
            'ads-offset: required successful check missing: windows-legacy/finite-images'])

    @staticmethod
    def log(lines):
        return ''.join('2026-10-06T18:00:00.123Z ' + line + '\r\n' for line in lines).encode()

    def recover(self, inputs=None, aggregate=None, *, refresh_fixture_hashes=False):
        supplied_inputs = self.inputs if inputs is None else inputs
        supplied_aggregate = self.aggregate if aggregate is None else aggregate
        # Parser controls need synthetic independent pins. Production pins are
        # unchanged, and separate tests prove these synthetic logs cannot pass
        # without that explicitly scoped fixture patch.
        pins = deepcopy(adapter.PINS)
        pins['logs'] = {key: {'bytes': len(raw), 'sha256': sha(raw)} for key, raw in (
            ('inputs', supplied_inputs if refresh_fixture_hashes else self.inputs),
            ('aggregate', supplied_aggregate if refresh_fixture_hashes else self.aggregate))}
        with patch.object(adapter, 'PINS', pins), \
             patch.object(adapter.subprocess, 'run', side_effect=AssertionError('native execution forbidden')):
            return adapter.recover_anchors(supplied_inputs, supplied_aggregate)

    def test_independent_logs_bind_exact_compiler_capture_and_both_receipts(self):
        result = self.recover()
        self.assertEqual(result['capture_context'], adapter.CAPTURE)
        self.assertEqual(result['rustc_sha256'], COMPILER_SHA)
        self.assertEqual(result['toolchain'], '1.90.0-x86_64-pc-windows-msvc')
        self.assertEqual(result['rustc_verbose_lines'], COMPILER.decode().splitlines())
        self.assertEqual(result['precompiled_receipt_sha256'], 'd' * 64)
        self.assertEqual(result['source_receipt_sha256'], 'e' * 64)

    def test_synthetic_logs_cannot_replace_pinned_original_job_bytes(self):
        with self.assertRaises(ValueError):
            adapter.recover_anchors(self.inputs, self.aggregate)

    def test_even_semantically_equivalent_log_newlines_do_not_refresh_anchor(self):
        for key, raw in (('inputs', self.inputs), ('aggregate', self.aggregate)):
            for changed in (raw.replace(b'\r\n', b'\n'), raw + b'\r\n', raw[:-1]):
                with self.subTest(key=key, digest=sha(changed)), self.assertRaises(ValueError):
                    self.recover(**{key: changed})

    def test_receipt_anchor_must_be_a_unique_standalone_canonical_line(self):
        for key, prefix, original in (('inputs', 'PRECOMPILED_ORACLE_RECEIPT_SHA256', self.inputs),
                                      ('aggregate', 'INDEPENDENT_SOURCE_RECEIPT_SHA256', self.aggregate)):
            current = ('d' if key == 'inputs' else 'e') * 64
            anchor = prefix + '=' + current
            for changed in (original + self.log([anchor]),
                            original.replace(anchor.encode(), ('print("' + anchor + '")').encode()),
                            original.replace(current.encode(), current.upper().encode()),
                            original.replace(current.encode(), (current + '0').encode()),
                            original.replace(anchor.encode(), b'')):
                with self.subTest(key=key, digest=sha(changed)), self.assertRaises(ValueError):
                    self.recover(**{key: changed}, refresh_fixture_hashes=True)

    def test_cache_fingerprint_cannot_anchor_another_capture_or_ambiguous_compiler(self):
        variants = [self.inputs.replace(adapter.CAPTURE['source_commit'].encode(), b'1' * 40),
                    self.inputs + self.inputs.replace(COMPILER_SHA.encode(), b'f' * 64),
                    self.inputs.replace(b'binary: rustc', b'binary: tampered'),
                    self.inputs.replace(COMPILER_SHA.encode(), b'f' * 64)]
        for raw in variants:
            with self.subTest(digest=sha(raw)), self.assertRaises(ValueError):
                self.recover(inputs=raw, refresh_fixture_hashes=True)

    def test_nonwindows_or_unstable_compiler_cannot_establish_native_math_anchor(self):
        for compiler in (COMPILER.replace(b'x86_64-pc-windows-msvc', b'x86_64-unknown-linux-gnu'),
                         COMPILER.replace(b'1.90.0', b'1.90.0-nightly')):
            raw = self.inputs.replace(COMPILER_SHA.encode(), sha(compiler).encode())
            original_block = self.log(COMPILER.decode().splitlines())
            raw = raw.replace(original_block, self.log(compiler.decode().splitlines()))
            with self.subTest(compiler=compiler), self.assertRaises(ValueError):
                self.recover(inputs=raw, refresh_fixture_hashes=True)

    def test_original_source_and_aggregate_failures_cannot_be_erased(self):
        for marker in (b'ValueError: unreviewed production file added',
                       b'ads-offset: required successful check missing: windows-legacy/finite-images'):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.recover(aggregate=self.aggregate.replace(marker, b'success'), refresh_fixture_hashes=True)


class PrecompiledPacketTests(unittest.TestCase):
    """Exercise adapter bindings only; the unchanged leaf validates native data."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.capture = self.base / 'capture'
        self.packet_root = self.base / 'packet'
        self.packet_path = self.packet_root / 'source-packet.json'
        self.manifest_path = self.base / 'native-input-manifest.json'
        self.production_names = ('Cargo.toml', 'Cargo.lock', 'src/lib.rs')
        self.implementation_names = (*self.production_names, 'examples/source_visibility_certificate.rs',
                                     'tools/build_ads_source_packet.py', 'tools/prepare_ads_source_oracle.py')
        self.extra_names = ('tools/current_ads_source_oracle.py', 'tools/collect_ads_offset_evidence.py',
                            'tools/finite_ads_profile_binding.py')
        names = set(self.implementation_names) | set(self.extra_names) | (adapter.binding.INPUTS - {'ads-offset.cfg'})
        for name in names:
            write(self.capture / name, ('synthetic original ' + name + '\n').encode())
        write(self.capture / 'Cargo.toml', b'[package]\nname="synthetic"\nversion="0.0.0"\n'
              b'[profile.release]\nlto="thin"\ncodegen-units=1\nstrip=true\n')
        reference = {'fixture': 'This is synthetic metadata, not a native GL runtime.'}
        native = {**adapter.CAPTURE, **{key: 'a' * 64 for key in adapter.shared._HASH_FIELDS},
                  'runtime_and_manifest_sha256': {name: adapter.shared._read_regular(self.capture / name)
                      for name in adapter.binding.INPUTS - {'ads-offset.cfg'}}}
        native.update(cargo_manifest_sha256=adapter.shared._read_regular(self.capture / 'Cargo.toml'),
                      cargo_lock_sha256=adapter.shared._read_regular(self.capture / 'Cargo.lock'),
                      gl_reference_sha256=adapter.shared.gl_reference_digest(reference))
        self.manifest = {'schema': 'rust-duty-dx12-authored-inputs/v1', 'platform': 'win32',
                         'build_selection': {'default_enabled': False, 'features': adapter.producer.FEATURES},
                         'binding': native, 'gl_reference': reference,
                         'expected_scenarios': list(adapter.shared.SCENARIOS)}
        write(self.manifest_path, self.manifest)
        recorded = 'C:/original/repo'
        self.build = {'command': adapter.prepared.build_command('C:/toolchain/cargo.exe'), 'cwd': recorded,
                      'exit_code': 0, 'environment': dict(adapter.binding.ORACLE_ENVIRONMENT)}
        self.files = {name: 'inventory/' + name for name in names}
        for name in names:
            write(self.packet_root / self.files[name], (self.capture / name).read_bytes())
        for name, raw in {'source_visibility_certificate.exe': b'SYNTHETIC NEVER EXECUTED',
                          'rustc-Vv.txt': COMPILER, 'build-receipt.json': self.build,
                          'native-input-manifest.json': self.manifest_path.read_bytes(),
                          'ads-offset.cfg': b'synthetic offset\n'}.items():
            key = adapter.ORACLE_PREFIX + name
            self.files[key] = 'inventory/' + key
            write(self.packet_root / self.files[key], raw)
        implementation = adapter.producer.inventory({name: self.capture / name for name in self.implementation_names})
        self.preparation = {'schema': adapter.prepared.SCHEMA, 'capture_context': dict(adapter.CAPTURE),
            'capture_binding': deepcopy(native), 'input_manifest_sha256': sha(self.manifest_path.read_bytes()),
            'platform': 'win32', 'machine': 'AMD64', 'host': adapter.producer.TARGET,
            'target': adapter.producer.TARGET, 'profile': 'release', 'features': adapter.producer.FEATURES,
            'recorded_root': recorded, 'executable': f'target/{adapter.producer.TARGET}/release/examples/{adapter.producer.EXAMPLE}.exe',
            'compiler_sha256': COMPILER_SHA, 'toolchain': '1.90.0-x86_64-pc-windows-msvc',
            'active_toolchain_alias': 'stable-x86_64-pc-windows-msvc',
            'implementation_before': implementation, 'implementation_after': deepcopy(implementation),
            'files': {name: adapter.producer.digest(self.packet_root / self.files[adapter.ORACLE_PREFIX +
                ('native-input-manifest.json' if name == 'input-manifest.json' else name)])
                for name in adapter.prepared.FILES}}
        self.prep_key = adapter.ORACLE_PREFIX + 'precompiled-receipt.json'
        self.files[self.prep_key] = 'inventory/' + self.prep_key
        write(self.packet_root / self.files[self.prep_key], self.preparation)
        before = adapter.producer.inventory({name: self.packet_root / relative for name, relative in self.files.items()})
        reports, outputs = {}, {}
        for role in adapter.binding.ROLES:
            backend = adapter.binding.BACKENDS[role][0]
            outputs[role] = adapter.ORACLE_PREFIX + f'frames-{backend}.jsonl'
            write(self.packet_root / outputs[role], b'{"synthetic": true}\n')
            reports[backend] = {'output': adapter.producer.digest(self.packet_root / outputs[role])}
        oracle = {'schema': 'rust-duty-native-source-oracle/v1', 'platform': 'win32', 'machine': 'AMD64',
                  'host': adapter.producer.TARGET, 'target': adapter.producer.TARGET,
                  'profile': 'release', 'features': adapter.producer.FEATURES,
                  'rustc_vv': adapter.ORACLE_PREFIX + 'rustc-Vv.txt',
                  'build_receipt': adapter.ORACLE_PREFIX + 'build-receipt.json',
                  'executable': adapter.ORACLE_PREFIX + 'source_visibility_certificate.exe',
                  'execution_receipts': {}}
        self.anchors = {'capture_context': dict(adapter.CAPTURE), 'rustc_sha256': COMPILER_SHA,
                        'toolchain': self.preparation['toolchain'], 'rustc_verbose_lines': COMPILER.decode().splitlines(),
                        'cache_lock_sha256': sha(bytes.fromhex(native['cargo_lock_sha256'])),
                        'precompiled_receipt_sha256': before[self.prep_key]['sha256']}
        self.receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                        'source_base_commit': adapter.CAPTURE['source_commit'],
                        'source_execution_context': dict(adapter.CAPTURE), 'capture_context': dict(adapter.CAPTURE),
                        'capture_rustc_sha256': COMPILER_SHA, 'toolchain': self.preparation['toolchain'],
                        'precompiled_receipt_sha256': self.anchors['precompiled_receipt_sha256'],
                        'inputs_and_implementation_before': before, 'inputs_and_implementation_after': deepcopy(before),
                        'backend_reports': reports, 'reviewed_manifest_dependency_mapping': adapter.binding.MANIFEST_ASSETS,
                        'oracle_execution': oracle, 'acceptance_verdict': None}
        self.packet = {'schema': adapter.binding.SCHEMA, 'capture_binding': deepcopy(native), 'original_invocations': {},
                       'receipt': 'source-receipt.json', 'recorded_root': recorded, 'files': self.files,
                       'source_outputs': outputs, 'input_files': {name: adapter.ORACLE_PREFIX + name
                           if name == 'ads-offset.cfg' else name for name in adapter.binding.INPUTS}}
        self.seal_source()

    def seal_source(self, *, refresh_anchor=True):
        write(self.packet_root / 'source-receipt.json', self.receipt)
        write(self.packet_path, self.packet)
        if refresh_anchor:
            self.anchors['source_receipt_sha256'] = sha((self.packet_root / 'source-receipt.json').read_bytes())

    def seal_preparation(self):
        path = self.packet_root / self.files[self.prep_key]
        write(path, self.preparation)
        identity = adapter.producer.digest(path)
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][self.prep_key] = identity
        self.anchors['precompiled_receipt_sha256'] = identity['sha256']
        self.receipt['precompiled_receipt_sha256'] = identity['sha256']
        self.seal_source()

    def bind(self):
        def production(root):
            self.assertEqual(root, self.capture)
            return {name: root / name for name in self.production_names}
        with patch.object(adapter.producer, 'production_files', side_effect=production), \
             patch.object(adapter.subprocess, 'run', side_effect=AssertionError('native execution forbidden')), \
             patch.object(adapter.subprocess, 'check_output', side_effect=AssertionError('no subprocess expected')):
            return adapter.bind_precompiled(self.packet_path, self.manifest_path, self.capture, self.anchors)

    def test_original_packet_binds_read_only_without_replay_or_changing_caller_environment(self):
        before = adapter.shared.inventory_files(self.packet_root, exclude=())
        environment = dict(os.environ)
        ledger = self.bind()
        ledger.verify_unchanged()
        self.assertEqual(adapter.shared.inventory_files(self.packet_root, exclude=()), before)
        self.assertEqual(dict(os.environ), environment)

    def test_supplied_anchor_context_receipts_compiler_and_cache_lock_cannot_be_substituted(self):
        original = deepcopy(self.anchors)
        for field in ('source_receipt_sha256', 'precompiled_receipt_sha256', 'rustc_sha256', 'cache_lock_sha256'):
            self.anchors = {**original, field: 'f' * 64}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.bind()
        self.anchors = {**original, 'capture_context': VERIFIER}
        with self.assertRaises(ValueError):
            self.bind()

    def test_source_receipt_cannot_refresh_its_own_anchor(self):
        self.receipt['acceptance_verdict'] = True
        self.seal_source(refresh_anchor=False)
        with self.assertRaises(ValueError):
            self.bind()

    def test_cache_key_uses_github_hashfiles_digest_not_raw_lock_sha(self):
        raw_digest = adapter.shared._read_regular(self.capture / 'Cargo.lock')
        self.assertEqual(self.anchors['cache_lock_sha256'], sha(bytes.fromhex(raw_digest)))
        self.anchors['cache_lock_sha256'] = raw_digest
        with self.assertRaises(ValueError):
            self.bind()

    def test_source_capture_execution_and_production_identities_stay_original(self):
        original = deepcopy(self.receipt)
        for field, wrong in (('source_base_commit', VERIFIER['source_commit']), ('source_execution_context', VERIFIER),
                             ('capture_context', VERIFIER), ('capture_rustc_sha256', 'f' * 64),
                             ('acceptance_verdict', True), ('toolchain', 'stable')):
            self.receipt = {**deepcopy(original), field: wrong}
            self.seal_source()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.bind()

    def test_precompiled_context_target_profile_features_and_manifest_are_bound(self):
        original = deepcopy(self.preparation)
        for field, wrong in (('capture_context', VERIFIER), ('platform', 'linux'), ('host', 'x86_64-unknown-linux-gnu'),
                             ('target', 'x86_64-unknown-linux-gnu'), ('profile', 'debug'), ('features', []),
                             ('machine', 'arm64'), ('compiler_sha256', 'f' * 64), ('toolchain', 'stable'),
                             ('input_manifest_sha256', 'f' * 64), ('recorded_root', 'C:/other/repo'),
                             ('active_toolchain_alias', 'untrusted/alias'), ('executable', 'other.exe')):
            self.preparation = {**deepcopy(original), field: wrong}
            self.seal_preparation()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.bind()

    def test_replay_compiler_build_and_executable_mappings_cannot_be_swapped(self):
        original = deepcopy(self.receipt)
        for field, wrong in (('rustc_vv', adapter.ORACLE_PREFIX + 'build-receipt.json'),
                             ('build_receipt', adapter.ORACLE_PREFIX + 'rustc-Vv.txt'),
                             ('executable', 'other.exe'), ('machine', 'arm64'), ('features', [])):
            self.receipt = deepcopy(original)
            self.receipt['oracle_execution'][field] = wrong
            self.seal_source()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.bind()

    def test_fixed_8f_receipts_cannot_be_relabelled_as_current_ebf(self):
        original = deepcopy(self.receipt)
        for field in ('source_execution_context', 'capture_context'):
            self.receipt = {**deepcopy(original), field: dict(fixed_producer.CAPTURE_CONTEXT)}
            self.seal_source()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.bind()
        self.receipt = deepcopy(original)
        self.preparation['capture_context'] = dict(fixed_producer.CAPTURE_CONTEXT)
        self.seal_preparation()
        with self.assertRaises(ValueError):
            self.bind()

    def test_changed_packet_file_fails_even_when_its_name_is_unchanged(self):
        for name in self.files:
            path = self.packet_root / self.files[name]
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.bind()
            path.write_bytes(original)

    def test_refreshing_a_packet_implementation_hash_cannot_replace_capture_source(self):
        name = 'src/lib.rs'
        path = self.packet_root / self.files[name]
        path.write_bytes(b'changed implementation')
        for field in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[field][name] = adapter.producer.digest(path)
        self.seal_source()
        with self.assertRaises(ValueError):
            self.bind()

    def test_preparation_and_replay_inventories_must_agree_before_and_after(self):
        self.preparation['implementation_after']['src/lib.rs']['sha256'] = 'f' * 64
        self.seal_preparation()
        with self.assertRaises(ValueError):
            self.bind()
        self.preparation['implementation_after'] = deepcopy(self.preparation['implementation_before'])
        self.seal_preparation()
        self.receipt['inputs_and_implementation_after']['src/lib.rs']['sha256'] = 'f' * 64
        self.seal_source()
        with self.assertRaises(ValueError):
            self.bind()

    def test_packet_mapping_cannot_escape_alias_or_omit_original_files(self):
        original = deepcopy(self.packet)
        name = 'src/lib.rs'
        for mutate in (lambda p: p['files'].update({name: '../escape'}),
                       lambda p: p['files'].update({name: p['files']['Cargo.toml']}),
                       lambda p: p['files'].pop(name),
                       lambda p: p['input_files'].update({'ads-offset.cfg': 'settings.cfg'}),
                       lambda p: p['source_outputs'].update({'dx12': p['source_outputs']['windows-legacy']})):
            self.packet = deepcopy(original)
            mutate(self.packet)
            self.seal_source()
            with self.assertRaises(ValueError):
                self.bind()

    def test_closed_packet_rejects_unrecorded_and_missing_outputs(self):
        extra = self.packet_root / 'unrecorded.txt'
        write(extra, b'unrecorded')
        with self.assertRaises(ValueError):
            self.bind()
        extra.unlink()
        output = self.packet_root / self.packet['source_outputs']['dx12']
        output.unlink()
        with self.assertRaises(ValueError):
            self.bind()

    def test_bound_packet_rechecks_late_byte_mutations_and_inventory_additions(self):
        for relative in ('source-packet.json', 'source-receipt.json', self.files[self.prep_key],
                         self.packet['source_outputs']['dx12']):
            ledger = self.bind()
            path = self.packet_root / relative
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                ledger.verify_unchanged()
            path.write_bytes(original)
        ledger = self.bind()
        write(self.packet_root / 'added-after-binding', b'changed closed set')
        with self.assertRaises(ValueError):
            ledger.verify_unchanged()

    def test_bound_manifest_and_original_source_are_rechecked_after_binding(self):
        for path in (self.manifest_path, self.capture / 'src/lib.rs'):
            ledger = self.bind()
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.subTest(path=str(path)), self.assertRaises(ValueError):
                ledger.verify_unchanged()
            path.write_bytes(original)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archive = self.root / 'original.zip'
        self.destination = self.root / 'decoded'

    def make_archive(self, entries=(('summary.json', b'{}\r\n'), ('frames/image.png', b'original image bytes')),
                     *, mode=stat.S_IFREG, compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(self.archive, 'w') as stream:
            for name, raw in entries:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (mode | 0o644) << 16
                info.compress_type = compression
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    stream.writestr(info, raw)
        raw = self.archive.read_bytes()
        return {'size_in_bytes': len(raw), 'digest': 'sha256:' + sha(raw)}

    def extract(self, metadata):
        with patch.object(adapter.subprocess, 'run', side_effect=AssertionError('native execution forbidden')):
            return adapter.extract_archive(self.archive, self.destination, metadata)

    def test_exact_archive_retains_native_crlf_and_original_zip(self):
        metadata = self.make_archive()
        original = self.archive.read_bytes()
        self.extract(metadata)
        self.assertEqual((self.destination / 'summary.json').read_bytes(), b'{}\r\n')
        self.assertEqual((self.destination / 'frames/image.png').read_bytes(), b'original image bytes')
        self.assertEqual(self.archive.read_bytes(), original)

    def test_archive_digest_and_length_fail_before_creating_destination(self):
        for field, wrong in (('digest', 'sha256:' + '0' * 64), ('size_in_bytes', 1)):
            metadata = self.make_archive()
            metadata[field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.extract(metadata)
            self.assertFalse(self.destination.exists())

    def test_path_escape_absolute_windows_and_alias_spellings_are_rejected(self):
        for name in ('../escape', '/absolute', 'C:/escape', 'frames\\escape.png', './same.json',
                     'frames/../escape', 'frames//escape', 'CON', 'frames/name.', 'frames/name:stream'):
            metadata = self.make_archive(((name, b'unsafe'),))
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract(metadata)
            self.assertFalse(self.destination.exists())
        self.assertFalse((self.root / 'escape').exists())

    def test_duplicate_case_alias_and_file_parent_collisions_are_rejected(self):
        for entries in ((('same.json', b'a'), ('same.json', b'b')),
                        (('same.json', b'a'), ('SAME.json', b'b')),
                        (('frames', b'a'), ('frames/image.png', b'b')),
                        (('Frames/one.png', b'a'), ('frames/two.png', b'b'))):
            metadata = self.make_archive(entries)
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.extract(metadata)
            self.assertFalse(self.destination.exists())

    def test_symlink_and_nonregular_members_are_rejected_before_extraction(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR):
            metadata = self.make_archive((('unsafe', b'../outside'),), mode=mode)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.extract(metadata)
            self.assertFalse(self.destination.exists())

    def test_unsupported_compression_is_rejected(self):
        metadata = self.make_archive(compression=zipfile.ZIP_BZIP2)
        with self.assertRaises(ValueError):
            self.extract(metadata)
        self.assertFalse(self.destination.exists())

    def test_archive_symlink_is_rejected(self):
        metadata = self.make_archive()
        source = self.root / 'real.zip'
        self.archive.rename(source)
        try:
            self.archive.symlink_to(source)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaises(ValueError):
            self.extract(metadata)
        self.assertFalse(self.destination.exists())

    def test_existing_destination_is_never_overwritten(self):
        metadata = self.make_archive()
        write(self.destination / 'summary.json', b'preserved original')
        with self.assertRaises(ValueError):
            self.extract(metadata)
        self.assertEqual((self.destination / 'summary.json').read_bytes(), b'preserved original')

    def test_header_entry_count_member_size_total_size_and_encryption_are_bounded(self):
        metadata = self.make_archive()
        original = zipfile.ZipFile.infolist
        def malicious_listing(bundle, mutation):
            entries = deepcopy(original(bundle))
            if mutation == 'member':
                entries[0].file_size = 256 * 1024**2 + 1
            elif mutation == 'encrypted':
                entries[0].flag_bits |= 1
            elif mutation == 'count':
                entries *= 50001
            elif mutation == 'total':
                entries = [deepcopy(entries[0]) for _ in range(33)]
                for index, entry in enumerate(entries):
                    entry.filename = f'file-{index}'
                    entry.file_size = 256 * 1024**2
            return entries
        for mutation in ('member', 'encrypted', 'count', 'total'):
            with patch.object(zipfile.ZipFile, 'infolist', autospec=True,
                              side_effect=lambda bundle, mode=mutation: malicious_listing(bundle, mode)):
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    self.extract(metadata)
            self.assertFalse(self.destination.exists())

    def test_symlinked_destination_parent_is_rejected_before_any_output_is_written(self):
        metadata = self.make_archive()
        outside = self.root / 'outside'
        outside.mkdir()
        alias = self.root / 'alias'
        try:
            alias.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(str(error))
        self.destination = alias / 'decoded'
        with self.assertRaises(ValueError):
            self.extract(metadata)
        self.assertEqual(list(outside.iterdir()), [])


class OrchestrationTests(unittest.TestCase):
    """Stub expensive validators but exercise the real acceptance caller."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.capture, self.verifier, self.downloads = [self.base / name for name in ('capture', 'verifier', 'downloads')]
        for path in (self.capture, self.verifier, self.downloads):
            path.mkdir()
        self.anchors = {'capture_context': dict(adapter.CAPTURE), 'source_receipt_sha256': 'd' * 64,
                        'rustc_sha256': COMPILER_SHA, 'precompiled_receipt_sha256': 'e' * 64}
        write(self.downloads / 'artifact-catalog.json', {'synthetic': True})
        write(self.downloads / 'independent-anchors.json', self.anchors)
        write(self.downloads / 'download-inventories.json', {'synthetic': True})
        self.logs = {'inputs': b'original synthetic input job\r\n', 'aggregate': b'original synthetic failed aggregate\r\n'}
        for key, raw in self.logs.items():
            write(self.downloads / 'logs' / f'{key}.log', raw)
        self.original_summaries = {}
        for scenario in adapter.shared.SCENARIOS:
            raw = (json.dumps({'scenario': scenario, 'passed': scenario != 'ads-offset'}) + '\r\n').encode()
            self.original_summaries[scenario] = raw
            write(self.downloads / 'shards' / scenario / 'summary.json', raw)
        self.source_root = self.downloads / 'source/current-ads-source'
        write(self.source_root / 'producer-summary.json', {
            'passed': False, 'capture_context': adapter.CAPTURE, 'verifier_context': adapter.CAPTURE,
            'phase': 'bind-finite-ads-profile', 'needs_supplement': True,
            'source_receipt_sha256': self.anchors['source_receipt_sha256'],
            'bounded_ads_profile_established': False, 'failure': 'ValueError: unreviewed production file added'})
        write(self.downloads / 'source/current-ads-source-receipt.sha256', b'd' * 64 + b'\n')
        class_bytes = Path(__file__).with_name('finite_ads_gpu_cpu_class.json').read_bytes()
        self.assertEqual(sha(class_bytes), adapter.CLASS_SHA256)
        write(self.verifier / 'tools/finite_ads_gpu_cpu_class.json', class_bytes)
        self.expected_checks = adapter.aggregate.expected_checks(ads_source_supplement=True)
        self.leaf_result = {'passed': True, 'bounded_ads_profile_established': True, 'conditional_diagnostic': False}
        self.aggregate_result = {'passed': True, 'status': 'passed', 'expected_checks': self.expected_checks,
                                 'checks': [{'name': name, 'passed': True} for name in self.expected_checks]}
        self.sequence = []
        self.serial = 0

    def run_adapter(self, *, leaf_result=None, aggregate_result=None, late_mutation=False):
        self.serial += 1
        self.evidence = self.base / f'evidence-{self.serial}'
        native = self.base / f'native-{self.serial}'
        self.sequence = []
        def leaf_call(**kwargs):
            self.sequence.append('leaf')
            return deepcopy(self.leaf_result if leaf_result is None else leaf_result)
        def aggregate_call(*args, **kwargs):
            self.sequence.append('aggregate')
            return deepcopy(self.aggregate_result if aggregate_result is None else aggregate_result)
        def python_process(command, **kwargs):
            self.sequence.append('materialize')
            self.assertEqual(command, [sys.executable, str(self.capture / 'tools/package_game.py'), 'materialize',
                '--root', str(self.capture), '--include-walk', '--include-ads', '--include-directional',
                '--include-jump', '--require-generated'])
            return Mock(returncode=0)
        ledger = Mock()
        if late_mutation:
            ledger.verify_unchanged.side_effect = ValueError('original packet changed after validators')
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'GITHUB_SHA': VERIFIER['source_commit'],
                'GITHUB_RUN_ID': VERIFIER['run_id'], 'GITHUB_RUN_ATTEMPT': VERIFIER['run_attempt']}, clear=True))
            self.current = stack.enter_context(patch.object(adapter, 'current_verifier', return_value=dict(VERIFIER)))
            self.checkout = stack.enter_context(patch.object(adapter, 'check_checkout'))
            stack.enter_context(patch.object(adapter, 'select_artifacts', return_value=deepcopy(adapter.PINS['artifacts'])))
            stack.enter_context(patch.object(adapter, 'recover_anchors', return_value=deepcopy(self.anchors)))
            self.download_guard = stack.enter_context(patch.object(adapter, 'verify_downloads'))
            stack.enter_context(patch.object(adapter, 'compare_production', return_value={}))
            stack.enter_context(patch.object(adapter.leaf, 'manifest_binding', return_value={'binding': adapter.CAPTURE}))
            self.bind_call = stack.enter_context(patch.object(adapter, 'bind_precompiled', return_value=ledger))
            for name in ('stage_generated_inputs', 'recover_native_text_bytes', 'validate_consumed_inputs'):
                stack.enter_context(patch.object(adapter.producer, name))
            stack.enter_context(patch.object(adapter, 'materialize_root', return_value={'synthetic': True}))
            stack.enter_context(patch.object(adapter.recovery, 'verify_historical'))
            stack.enter_context(patch.object(adapter.subprocess, 'run', side_effect=python_process))
            self.leaf_call = stack.enter_context(patch.object(adapter.leaf, 'run', side_effect=leaf_call))
            self.aggregate_call = stack.enter_context(patch.object(adapter.aggregate, 'run', side_effect=aggregate_call))
            result = adapter.run(capture_root=self.capture, verifier_root=self.verifier, downloads=self.downloads,
                                 evidence=self.evidence, native_root=native)
        self.ledger = ledger
        self.native = native
        return result

    def test_passing_leaf_requires_full_aggregate_and_retains_all_original_failed_bytes(self):
        result = self.run_adapter()
        self.assertTrue(result['passed'], result.get('failure'))
        self.assertFalse(result['acceptance_complete'])
        self.assertTrue(result['leaf_passed'])
        self.assertTrue(result['aggregate_passed'])
        self.assertTrue(result['original_failures_preserved'])
        self.assertEqual(result['native_processes_run'], 0)
        self.assertEqual(result['capture_context'], adapter.CAPTURE)
        self.assertEqual(result['source_execution_context'], adapter.CAPTURE)
        self.assertEqual(result['verifier_context'], VERIFIER)
        self.assertEqual(self.sequence, ['materialize', 'leaf', 'aggregate'])
        self.assertEqual(self.aggregate_call.call_count, 1)
        self.assertEqual(self.download_guard.call_count, 2)
        self.assertEqual(self.current.call_count, 2)
        self.checkout.assert_called_once_with(self.capture, adapter.CAPTURE['source_commit'])
        self.ledger.verify_unchanged.assert_called_once_with()
        for scenario, raw in self.original_summaries.items():
            self.assertEqual((self.evidence / 'original-verdicts' / f'{scenario}-summary.json').read_bytes(), raw)
        for key, raw in self.logs.items():
            self.assertEqual((self.evidence / 'original-verdicts' / f'{key}-job.log').read_bytes(), raw)

    def test_actual_source_artifact_lca_packet_and_distinct_verifier_are_forwarded(self):
        result = self.run_adapter()
        self.assertTrue(result['passed'], result.get('failure'))
        packet = self.source_root / 'packet/source-packet.json'
        manifest = self.downloads / 'inputs/evidence/authored-inputs/input-manifest.json'
        self.bind_call.assert_called_once_with(packet, manifest, self.capture, self.anchors)
        kwargs = self.leaf_call.call_args.kwargs
        self.assertEqual(kwargs['source_packet'], packet)
        self.assertEqual(kwargs['capture_context'], adapter.CAPTURE)
        self.assertEqual(kwargs['verifier_context'], VERIFIER)
        self.assertEqual(kwargs['reviewed_class'], self.verifier / 'tools/finite_ads_gpu_cpu_class.json')
        self.assertEqual(kwargs['expected_class_sha256'], adapter.CLASS_SHA256)
        self.assertNotIn('conditional_diagnostic', kwargs)
        args = self.aggregate_call.call_args.args
        self.assertEqual(args, (self.native, self.downloads / 'shards', self.downloads / 'legacy',
                               self.evidence / 'aggregate', manifest))
        supplement = self.aggregate_call.call_args.kwargs['ads_source_supplement']
        self.assertEqual(supplement['source_packet'], str(packet))
        self.assertEqual(supplement['capture_context'], adapter.CAPTURE)
        self.assertEqual(supplement['leaf_verifier_context'], VERIFIER)
        self.assertEqual(supplement['verifier_context'], VERIFIER)
        self.assertEqual(supplement['expected_class_sha256'], adapter.CLASS_SHA256)

    def test_failed_incomplete_or_conditional_leaf_cannot_reach_aggregate(self):
        for field, value in (('passed', False), ('passed', 1), ('bounded_ads_profile_established', False),
                             ('conditional_diagnostic', True), ('conditional_diagnostic', None)):
            result = self.run_adapter(leaf_result={**self.leaf_result, field: value})
            with self.subTest(field=field, value=value):
                self.assertFalse(result['passed'])
                self.assertIn('ADS leaf failed', result['failure'])
                self.aggregate_call.assert_not_called()

    def test_failed_missing_reordered_or_false_aggregate_checks_never_pass(self):
        variants = [{**self.aggregate_result, 'passed': False}, {**self.aggregate_result, 'passed': 1},
                    {**self.aggregate_result, 'status': 'failed'},
                    {**self.aggregate_result, 'checks': self.aggregate_result['checks'][:-1]},
                    {**self.aggregate_result, 'checks': list(reversed(self.aggregate_result['checks']))},
                    {**self.aggregate_result, 'expected_checks': self.expected_checks[:-1]},
                    {**self.aggregate_result, 'checks': [{**row, 'passed': False} for row in self.aggregate_result['checks']]},
                    {**self.aggregate_result, 'checks': [{**row, 'passed': 1} for row in self.aggregate_result['checks']]}]
        for index, aggregate_result in enumerate(variants):
            result = self.run_adapter(aggregate_result=aggregate_result)
            with self.subTest(index=index):
                self.assertFalse(result['passed'])
                self.assertIn('mandatory', result['failure'])
                self.assertNotIn('aggregate_passed', result)
                self.aggregate_call.assert_called_once()
                self.assertEqual(json.loads((self.evidence / 'summary.json').read_text())['passed'], False)

    def test_late_packet_mutation_prevents_promoting_successful_validator_results(self):
        result = self.run_adapter(late_mutation=True)
        self.assertFalse(result['passed'])
        self.assertIn('changed after validators', result['failure'])
        self.assertEqual(self.sequence, ['materialize', 'leaf', 'aggregate'])

    def test_wrong_current_reviewed_class_never_reaches_leaf_or_aggregate(self):
        write(self.verifier / 'tools/finite_ads_gpu_cpu_class.json', b'{"changed": true}\n')
        result = self.run_adapter()
        self.assertFalse(result['passed'])
        self.assertIn('reviewed GPU/CPU class changed', result['failure'])
        self.leaf_call.assert_not_called()
        self.aggregate_call.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parents[1] / adapter.WORKFLOW
        self.text = self.path.read_text()
        self.workflow = yaml.safe_load(self.text)
        self.job = self.workflow['jobs']['revalidate-completed-packet']
        self.steps = self.job['steps']

    def test_only_explicit_dispatch_and_four_narrow_main_paths_trigger_work(self):
        trigger = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(set(trigger), {'push', 'workflow_dispatch'})
        self.assertEqual(trigger['push']['branches'], ['main'])
        self.assertEqual(set(trigger['push']['paths']), {adapter.WORKFLOW, 'tools/revalidate_ebf_authored_packet.py',
            'tools/test_revalidate_ebf_authored_packet.py', 'tools/ebf_authored_packet_pins.json'})
        self.assertEqual(self.job['if'], "github.repository == 'RHS059/rust_duty' && github.ref == 'refs/heads/main'")

    def test_read_only_permissions_linux_and_distinct_exact_checkouts(self):
        self.assertEqual(self.workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        self.assertNotIn('permissions', self.job)
        self.assertEqual(self.job['runs-on'], 'ubuntu-latest')
        checkouts = [step['with'] for step in self.steps if step.get('uses', '').startswith('actions/checkout@')]
        self.assertEqual(len(checkouts), 2)
        self.assertEqual(checkouts[0], {'ref': '${{ github.sha }}', 'path': 'verifier', 'persist-credentials': False})
        self.assertEqual(checkouts[1], {'ref': adapter.CAPTURE['source_commit'], 'path': 'capture-source',
                                      'persist-credentials': False})

    def test_shell_commands_are_python_only_and_do_not_spoof_caller_or_launch_native_tools(self):
        for step in self.steps:
            if 'run' in step:
                self.assertTrue(step['run'].startswith('python '), step['run'])
                self.assertNotRegex(step['run'], r'(?i)\b(?:cargo|rustup|rustc)\b|\.exe\b|--conditional-diagnostic')
                self.assertNotIn('current_ads_source_oracle.py', step['run'])
                self.assertNotIn('build_ads_source_packet.py', step['run'])
                self.assertNotIn('run_dx12_authored_shard.py', step['run'])
            self.assertFalse({'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKFLOW_SHA'} & set(step.get('env', {})))
        self.assertFalse({'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'} & set(self.job.get('env', {})))
        self.assertNotRegex(self.text, r'(?m)^\s*continue-on-error:')
        self.assertNotIn('secrets.', self.text)

    def test_fetch_and_mandatory_run_use_distinct_original_verifier_and_evidence_roots(self):
        commands = [step['run'] for step in self.steps if 'run' in step]
        fetch = next(command for command in commands if 'revalidate_ebf_authored_packet.py fetch' in command)
        run = next(command for command in commands if 'revalidate_ebf_authored_packet.py run' in command)
        self.assertEqual(fetch.split(), ['python', 'verifier/tools/revalidate_ebf_authored_packet.py', 'fetch',
                                        '--verifier-root', 'verifier', '--downloads', 'downloaded'])
        self.assertEqual(run.split(), ['python', 'verifier/tools/revalidate_ebf_authored_packet.py', 'run',
                                      '--verifier-root', 'verifier', '--capture-root', 'capture-source',
                                      '--downloads', 'downloaded', '--native-root', 'native-inputs', '--evidence', 'evidence'])
        self.assertLess(commands.index(fetch), commands.index(run))
        uploads = [step for step in self.steps if step.get('uses', '').startswith('actions/upload-artifact@')]
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]['if'], 'always()')
        self.assertEqual(set(uploads[0]['with']['path'].splitlines()), {'evidence/', 'downloaded/*.json', 'downloaded/logs/'})


if __name__ == '__main__':
    unittest.main()
