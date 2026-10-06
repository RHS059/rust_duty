"""CPU-only recovery controls; synthetic files are never native capture evidence."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import recover_ads_source_aggregate as recovery
import test_build_ads_source_packet as producer_fixture
from test_dx12_authored_shards import make_gl_runtime

CAPTURE = dict(recovery.CAPTURE)
VERIFIER = {'source_commit': 'a' * 40, 'run_id': '98765', 'run_attempt': '2'}
ENV = {'GITHUB_SHA': VERIFIER['source_commit'], 'GITHUB_RUN_ID': VERIFIER['run_id'],
       'GITHUB_RUN_ATTEMPT': VERIFIER['run_attempt']}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else (json.dumps(data) + '\n').encode())


def catalog():
    value = producer_fixture.catalog()
    value['attempt'].update(name=recovery.WORKFLOW_NAME, conclusion='failure')
    prototype = deepcopy(value['artifacts'][0])
    value['artifacts'] = [{**deepcopy(prototype), 'id': index + 1, 'name': name}
                          for index, name in enumerate(recovery.artifact_names('1').values())]
    return value


class SelectionTests(unittest.TestCase):
    def test_exact_22_includes_all_nine_original_shards_and_seven_linux_inputs(self):
        value = recovery.select_artifacts(catalog(), CAPTURE)
        self.assertEqual(len(value), 22)
        self.assertEqual(len({item['id'] for item in value.values()}), 22)
        names = {item['name'] for item in value.values()}
        self.assertEqual({name for name in names if name.startswith('dx12-authored-shard-')},
                         {f'dx12-authored-shard-{scenario}-evidence-attempt-1' for scenario in recovery.shared.SCENARIOS})
        self.assertEqual(len([key for key in value if key.startswith('linux_')]), 7)
        self.assertTrue(all(name.endswith('-attempt-1') for name in names))

    def test_extra_artifact_guard_rejects_missing_duplicate_denied_expired_aliased_and_wrong_origin(self):
        for key in ('shard_layered_60', 'linux_layered'):
            base = catalog()
            index = list(recovery.artifact_names('1')).index(key)
            mutations = [lambda c: c['artifacts'].pop(index),
                         lambda c: c['artifacts'].append(deepcopy(c['artifacts'][index])),
                         lambda c: c['artifacts'][index].update(expired=True),
                         lambda c: c['artifacts'][index].update(id=c['artifacts'][0]['id']),
                         lambda c: c['artifacts'][index].update(size_in_bytes=0),
                         lambda c: c['artifacts'][index].update(size_in_bytes=5 * 1024**3),
                         lambda c: c['artifacts'][index].update(created_at='2026-10-05T23:59:59Z'),
                         lambda c: c['artifacts'][index].update(created_at='2026-10-06T04:00:01Z'),
                         lambda c: c.update(complete=False)]
            for field, wrong in (('id', 1), ('head_sha', 'b' * 40), ('repository_id', 10), ('head_repository_id', 10)):
                mutations.append(lambda c, f=field, v=wrong: c['artifacts'][index]['workflow_run'].update({f: v}))
            for denied in recovery.producer.DENIED_ARTIFACT_IDS:
                mutations.append(lambda c, v=denied: c['artifacts'][index].update(id=v))
            for serial, mutate in enumerate(mutations):
                value = deepcopy(base)
                mutate(value)
                with self.subTest(key=key, serial=serial), self.assertRaises(ValueError):
                    recovery.select_artifacts(value, CAPTURE)

    def test_capture_identity_workflow_and_original_failure_are_not_relabelled(self):
        for field, wrong in (('name', 'Other workflow'), ('conclusion', 'success'), ('path', '.github/workflows/other.yml'),
                             ('head_branch', 'patch'), ('head_sha', 'b' * 40), ('run_attempt', 2), ('status', 'in_progress')):
            value = catalog()
            value['attempt'][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                recovery.select_artifacts(value, CAPTURE)
        with self.assertRaises(ValueError):
            recovery.select_artifacts(catalog(), VERIFIER)
        with self.assertRaises(ValueError):
            recovery.select_artifacts(catalog(), CAPTURE, 'other/rust_duty')

    def test_cli_emits_nothing_when_any_required_artifact_is_denied(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = catalog()
            value['artifacts'][-1]['id'] = next(iter(recovery.producer.DENIED_ARTIFACT_IDS))
            write(root / 'catalog.json', value)
            arguments = ['select-artifacts', '--catalog', str(root / 'catalog.json'),
                         '--capture-source', CAPTURE['source_commit'], '--capture-run-id', CAPTURE['run_id'],
                         '--capture-run-attempt', CAPTURE['run_attempt']]
            with patch.dict(os.environ, {'GITHUB_OUTPUT': str(root / 'outputs')}, clear=True):
                self.assertEqual(recovery.main(arguments), 1)
            self.assertFalse((root / 'outputs').exists())


class MaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source, self.verifier, self.inputs, self.root = [self.base / name for name in ('source', 'verifier', 'inputs', 'root')]
        for path in (self.source, self.verifier, self.inputs):
            path.mkdir()
        self.native_files = {
            'settings.cfg': b'viewmodel_offset_x=0\r\n',
            'assets/animations.cfg': b'normal_ready=synthetic\r\n',
            'assets/reload/asset.vra': b'synthetic runtime\x00\r\n',
            # Metadata beyond the ADS leaf's input subset must remain bound.
            'assets/authoring/locomotion_directional/review/review.json': b'{"native": true}\r\n',
        }
        for name, raw in self.native_files.items():
            write(self.source / name, raw.replace(b'\r\n', b'\n') if Path(name).suffix in ('.json', '.cfg') else raw)
        write(self.source / 'Cargo.toml', b'[package]\nname="synthetic"\n')
        write(self.source / 'Cargo.lock', b'version=4\n')
        write(self.verifier / 'tools/verify_synthetic.py', b'# Synthetic verifier; never a game\n')
        self.reference = make_gl_runtime(self.inputs, manifest=self.verifier / recovery.shared.GL_LOCK_PATH)
        self.binaries = {'target/release/vector-range.exe': b'synthetic game, never executed',
                         'target/release/examples/renderer_contract.exe': b'synthetic contract, never executed'}
        for name, raw in self.binaries.items():
            write(self.inputs / name, raw)
        self.native = {**CAPTURE, 'gl_reference_sha256': recovery.shared.gl_reference_digest(self.reference),
                       'executable_sha256': sha(self.binaries['target/release/vector-range.exe']),
                       'renderer_contract_sha256': sha(self.binaries['target/release/examples/renderer_contract.exe']),
                       'cargo_manifest_sha256': recovery.shared._read_regular(self.source / 'Cargo.toml'),
                       'cargo_lock_sha256': recovery.shared._read_regular(self.source / 'Cargo.lock'),
                       'runtime_and_manifest_sha256': {key: sha(value) for key, value in self.native_files.items()}}
        self.manifest = {'schema': 'rust-duty-dx12-authored-inputs/v1', 'platform': 'win32',
                         'build_selection': {'default_enabled': False, 'features': ['legacy-macroquad', 'wgpu-runtime']},
                         'binding': self.native, 'gl_reference': self.reference,
                         'expected_scenarios': list(recovery.shared.SCENARIOS)}
        write(self.inputs / 'evidence/authored-inputs/input-manifest.json', self.manifest)

    def materialize(self):
        return recovery.materialize_root(self.source, self.verifier, self.inputs, self.root, self.manifest)

    def test_full_native_root_passes_original_aggregate_manifest_api_with_exact_text_bytes(self):
        original = recovery.shared.inventory_files(self.source, exclude=())
        # A later verifier GL pin must not replace the original runtime lock.
        write(self.verifier / recovery.shared.GL_LOCK_PATH, b'changed verifier pin')
        result = self.materialize()
        self.assertEqual(set(result['runtime_and_manifest_files']), set(self.native_files))
        for name, raw in self.native_files.items():
            self.assertEqual((self.root / name).read_bytes(), raw)
        self.assertEqual(result['runtime_and_manifest_files']['assets/animations.cfg']['transformation'], 'crlf')
        self.assertEqual(recovery.shared.inventory_files(self.source, exclude=()), original)
        native = recovery.aggregate.validated_manifest(self.inputs / 'evidence/authored-inputs/input-manifest.json',
                                                        self.root, expected_context=CAPTURE)
        self.assertEqual(native, self.native)
        self.assertEqual((self.root / recovery.shared.GL_LOCK_PATH).read_bytes(),
                         (self.inputs / recovery.shared.GL_RUNTIME_PATH / recovery.shared.GL_LOCK_PATH.name).read_bytes())
        self.assertEqual((self.root / 'target/release/vector-range.exe').read_bytes(), self.binaries['target/release/vector-range.exe'])

    def test_metadata_outside_leaf_is_required_and_semantic_json_equality_is_insufficient(self):
        key = 'assets/authoring/locomotion_directional/review/review.json'
        write(self.source / key, b'{ "native" : true }\n')
        with self.assertRaisesRegex(ValueError, 'exact native input bytes'):
            self.materialize()
        self.assertFalse((self.root / key).exists())

    def test_missing_metadata_is_not_silently_dropped(self):
        (self.source / 'assets/authoring/locomotion_directional/review/review.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing original input-root file'):
            self.materialize()

    def test_binary_newline_normalization_is_forbidden(self):
        write(self.source / 'assets/reload/asset.vra', self.native_files['assets/reload/asset.vra'].replace(b'\r\n', b'\n'))
        with self.assertRaisesRegex(ValueError, 'exact native input bytes'):
            self.materialize()

    def test_original_executable_and_gl_runtime_bytes_are_checked(self):
        for path in ('target/release/vector-range.exe', 'evidence/gl-runtime/opengl32.dll'):
            with self.subTest(path=path):
                raw = (self.inputs / path).read_bytes()
                write(self.inputs / path, b'changed')
                with self.assertRaises(ValueError):
                    self.materialize()
                shutil.rmtree(self.root)
                write(self.inputs / path, raw)

    def test_symlinked_metadata_parent_is_rejected_before_reconstruction(self):
        folder = self.source / 'assets/authoring/locomotion_directional/review'
        renamed = self.base / 'outside'
        folder.rename(renamed)
        try:
            folder.symlink_to(renamed, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')
        with self.assertRaisesRegex(ValueError, 'symlink or reparse'):
            self.materialize()

    def test_unexpected_path_cannot_escape_full_root(self):
        self.native['runtime_and_manifest_sha256']['../escape.cfg'] = sha(b'bad')
        with self.assertRaisesRegex(ValueError, 'unsafe relative'):
            self.materialize()
        self.assertFalse((self.base / 'escape.cfg').exists())

    def test_existing_or_nested_destination_cannot_mutate_original_inputs(self):
        self.root.mkdir()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.materialize()
        self.root = self.source / 'reconstructed'
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            self.materialize()


class PrepareTests(unittest.TestCase):
    def setUp(self):
        MaterializationTests.setUp(self)
        self.downloads = self.base / 'downloads'
        self.downloads.mkdir()
        self.inputs.rename(self.downloads / 'inputs')
        self.inputs = self.downloads / 'inputs'
        self.catalog = catalog()
        write(self.downloads / 'artifact-catalog.json', self.catalog)
        for scenario in recovery.shared.SCENARIOS:
            folder = self.downloads / {'ads-gameplay': 'gameplay', 'ads-offset': 'offset'}.get(scenario, f'shards/{scenario}')
            # These tiny intake fixtures test preservation only. The real
            # aggregate separately validates the entire native shard contract.
            write(folder / 'summary.json', {'scenario': scenario, 'passed': scenario != 'ads-offset',
                                           'status': 'failed' if scenario == 'ads-offset' else 'passed'})
            write(folder / 'capture-marker.txt', b'original sealed capture marker')
        for name in recovery.HISTORICAL:
            write(self.downloads / f'legacy/{name}/diagnostic.json', {'original': name})
        historical = {'schema': 'rust-duty-dx12-authored-historical/v1', **CAPTURE,
                      'files': recovery.shared.inventory_files(self.downloads / 'legacy', exclude=())}
        write(self.inputs / 'evidence/authored-inputs/historical-manifest.json', historical)
        log = producer_fixture.COMPILER + (f'authored-dual-release-v1-Windows-X64-{producer_fixture.COMPILER_SHA}-'
                                          + '1' * 64 + '-' + CAPTURE['source_commit'] + '\n').encode()
        compiler = recovery.producer.recover_compiler(log, CAPTURE)
        compiler['original_job'] = recovery.producer.select_compiler_job(self.catalog, CAPTURE)
        write(self.downloads / 'compiler-recovery/original-authored-inputs.log', log)
        write(self.downloads / 'compiler-recovery/compiler-recovery.json', compiler)
        self.args = SimpleNamespace(capture_source=CAPTURE['source_commit'], capture_run_id=CAPTURE['run_id'],
                                    capture_run_attempt=CAPTURE['run_attempt'], capture_root=self.source,
                                    verifier_root=self.verifier, downloads=self.downloads,
                                    evidence=self.base / 'recovery-evidence', root=self.root,
                                    shards=self.base / 'aggregate-shards', leaf_summary=self.base / 'leaf/summary.json',
                                    source_packet=self.base / 'packet/source-packet.json',
                                    receipt_anchor=self.base / 'receipt.sha256', request=self.base / 'request.json',
                                    reviewed_class=self.base / 'profile/class.json', expected_class_sha256='a' * 64)
        write(self.args.receipt_anchor, b'd' * 64 + b'\n')
        write(self.args.leaf_summary, {'passed': True, 'bounded_ads_profile_established': True,
                                      'conditional_diagnostic': False, 'capture_context': CAPTURE, 'verifier_context': VERIFIER,
                                      'source_receipt_sha256': 'd' * 64, 'capture_rustc_sha256': producer_fixture.COMPILER_SHA})

    def prepare(self):
        def git_output(command, **kwargs):
            if command[-1] == '--untracked-files=no':
                return b''
            self.assertEqual(command[:2], ['git', '-C'])
            self.assertEqual(command[3:], ['rev-parse', 'HEAD'])
            return CAPTURE['source_commit'] if command[2] == str(self.source) else VERIFIER['source_commit']
        with patch.dict(os.environ, ENV, clear=True), patch.object(recovery.subprocess, 'check_output', side_effect=git_output), \
             patch.object(recovery.subprocess, 'run', side_effect=AssertionError('A recovery must not build or execute native code')):
            return recovery.prepare(self.args)

    def test_complete_prepare_preserves_nine_original_summaries_and_separate_failed_capture(self):
        report = self.prepare()
        self.assertTrue(report['passed'])
        self.assertEqual(report['original_workflow']['conclusion'], 'failure')
        self.assertEqual(report['native_processes_run'], 0)
        saved = report['original_shard_summaries']
        self.assertEqual(set(saved), set(recovery.shared.SCENARIOS))
        self.assertEqual(len({row['artifact_id'] for row in saved.values()}), 9)
        for scenario, row in saved.items():
            path = self.args.evidence / row['retained_path']
            self.assertEqual(recovery.producer.digest(path), {'bytes': row['bytes'], 'sha256': row['sha256']})
            self.assertEqual(json.loads(path.read_text())['passed'], scenario != 'ads-offset')
        request = json.loads(self.args.request.read_text())
        self.assertEqual(request['capture_context'], CAPTURE)
        self.assertEqual(request['verifier_context'], VERIFIER)
        self.assertEqual(request['capture_rustc_sha256'], producer_fixture.COMPILER_SHA)
        self.assertEqual(set(path.name for path in self.args.shards.iterdir()), set(recovery.shared.SCENARIOS))
        self.assertFalse((self.downloads / 'gameplay').exists())
        self.assertFalse((self.downloads / 'offset').exists())
        self.assertFalse((self.args.evidence / 'historical-verified').exists())

    def test_all_nine_summaries_are_sealed_before_any_relocation_can_fail(self):
        with patch.object(recovery, 'stage_shard', side_effect=ValueError('same-volume relocation failed')):
            with self.assertRaisesRegex(ValueError, 'same-volume relocation failed'):
                self.prepare()
        originals = list((self.args.evidence / 'original-verdicts').glob('*-summary.json'))
        self.assertEqual(len(originals), 9)
        self.assertEqual(len(json.loads((self.args.evidence / 'original-shard-summaries.json').read_text())), 9)
        self.assertTrue((self.downloads / 'gameplay/summary.json').is_file())
        self.assertTrue((self.downloads / 'offset/summary.json').is_file())
        self.assertFalse(self.args.request.exists())

    def test_changed_summary_cannot_be_relocated_under_earlier_summary_hash(self):
        source = self.downloads / 'gameplay'
        original_hash = recovery.producer.digest(source / 'summary.json')['sha256']
        write(source / 'summary.json', {'changed': True})
        target = self.base / 'relocated'
        with self.assertRaisesRegex(ValueError, 'summary changed before relocation'):
            recovery.stage_shard(source, target, original_hash)
        self.assertTrue(source.is_dir())
        self.assertFalse(target.exists())

    def test_missing_historical_file_fails_and_retains_all_original_verdicts(self):
        (self.downloads / 'legacy/layered/diagnostic.json').unlink()
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            self.prepare()
        report = json.loads((self.args.evidence / 'summary.json').read_text())
        self.assertFalse(report['passed'])
        self.assertEqual(len(report['original_shard_summaries']), 9)
        self.assertFalse(self.args.request.exists())

    def test_compiler_anchor_changed_after_recovery_fails_without_a_request(self):
        path = self.downloads / 'compiler-recovery/compiler-recovery.json'
        compiler = json.loads(path.read_text())
        compiler['rustc_sha256'] = 'f' * 64
        write(path, compiler)
        with self.assertRaisesRegex(ValueError, 'compiler recovery metadata changed'):
            self.prepare()
        self.assertFalse(self.args.request.exists())
        self.assertFalse(json.loads((self.args.evidence / 'summary.json').read_text())['passed'])


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.summary = self.root / 'leaf/summary.json'
        self.packet = self.root / 'packet/source-packet.json'
        self.anchor = self.root / 'independent.sha256'
        self.compiler = {'capture_context': CAPTURE, 'rustc_sha256': 'c' * 64}
        self.record = {'passed': True, 'bounded_ads_profile_established': True, 'conditional_diagnostic': False, 'capture_context': CAPTURE, 'verifier_context': VERIFIER,
                       'source_receipt_sha256': 'd' * 64, 'capture_rustc_sha256': 'c' * 64}
        write(self.summary, self.record)
        write(self.anchor, b'd' * 64 + b'\n')

    def request(self):
        with patch.dict(os.environ, ENV, clear=True):
            return recovery.make_request(self.summary, self.packet, self.anchor, self.compiler, CAPTURE, VERIFIER,
                                         reviewed_class=self.root / 'class.json', expected_class_sha256='a' * 64)

    def test_request_has_exact_reviewed_api_fields_and_separate_capture_identity(self):
        request = self.request()
        self.assertEqual(set(request), {'leaf_summary', 'source_packet', 'source_receipt_sha256',
                                       'capture_rustc_sha256', 'capture_context', 'leaf_verifier_context', 'verifier_context',
                                       'reviewed_class', 'expected_class_sha256'})
        self.assertEqual(request['capture_context'], CAPTURE)
        self.assertEqual(request['verifier_context'], VERIFIER)
        self.assertEqual(request['leaf_verifier_context'], VERIFIER)
        self.assertNotEqual(CAPTURE, VERIFIER)

    def test_failed_leaf_or_changed_independent_anchors_are_not_accepted(self):
        for field, value in (('passed', False), ('bounded_ads_profile_established', False),
                             ('conditional_diagnostic', True), ('source_receipt_sha256', 'e' * 64),
                             ('capture_rustc_sha256', 'e' * 64), ('verifier_context', CAPTURE),
                             ('capture_context', VERIFIER)):
            write(self.summary, {**self.record, field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.request()

    def test_actual_github_identity_must_agree_without_environment_spoofing(self):
        with patch.dict(os.environ, {**ENV, 'GITHUB_SHA': 'f' * 40}, clear=True), self.assertRaises(ValueError):
            recovery.make_request(self.summary, self.packet, self.anchor, self.compiler, CAPTURE, VERIFIER,
                                         reviewed_class=self.root / 'class.json', expected_class_sha256='a' * 64)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).resolve().parents[1] / '.github/workflows/revalidate-ads-source.yml'
        cls.workflow = yaml.safe_load(cls.path.read_text())
        cls.steps = cls.workflow['jobs']['windows-source-oracle']['steps']

    def test_22_download_ids_match_selection_and_exact_directory_layout(self):
        downloads = [step for step in self.steps if step.get('uses') == 'actions/download-artifact@v4']
        self.assertEqual(len(downloads), 22)
        actual = {step['with']['artifact-ids']: step['with']['path'] for step in downloads}
        expected = {f'${{{{ steps.artifacts.outputs.{key} }}}}': 'downloaded/' + key
                    for key in recovery.producer.artifact_names('1')}
        expected.update({f'${{{{ steps.artifacts.outputs.shard_{name.replace("-", "_")} }}}}': f'downloaded/shards/{name}'
                         for name in recovery.shared.SCENARIOS if name not in recovery.leaf.SCENARIOS})
        expected.update({f'${{{{ steps.artifacts.outputs.linux_{name.replace("-", "_")} }}}}': f'downloaded/legacy/{name}'
                         for name in recovery.HISTORICAL})
        self.assertEqual(actual, expected)
        for step in downloads:
            self.assertEqual(step['if'], "steps.eligibility.outputs.eligible == 'true'")
            self.assertEqual(step['with']['run-id'], '${{ env.CAPTURE_RUN_ID }}')
            self.assertEqual(step['with']['repository'], recovery.REPOSITORY)
            self.assertNotIn('name', step['with'])
            self.assertNotIn('pattern', step['with'])

    def test_aggregate_uses_existing_leaf_and_original_full_input_and_historical_manifests(self):
        commands = [step.get('run', '') for step in self.steps]
        leaf = next(i for i, command in enumerate(commands) if 'tools/revalidate_ads_offset.py' in command)
        prepare = next(i for i, command in enumerate(commands) if 'tools/recover_ads_source_aggregate.py prepare' in command)
        aggregate = next(i for i, command in enumerate(commands) if 'tools/aggregate_dx12_authored.py --root' in command)
        self.assertLess(leaf, prepare)
        self.assertLess(prepare, aggregate)
        self.assertIn('--leaf-summary evidence/revalidation/summary.json', commands[prepare])
        self.assertIn('--receipt-anchor evidence/independent-source-receipt.sha256', commands[prepare])
        self.assertIn('--source-packet evidence/source-oracle/packet/source-packet.json', commands[prepare])
        for command in (commands[leaf], commands[prepare]):
            self.assertIn('--reviewed-class verifier/tools/finite_ads_reviewed_class.json', command)
            self.assertIn('--expected-class-sha256 96dfb631be9d59f6cf35d87e4f3c17a4a4303d74787bb773a8c47672efb53331', command)
            self.assertNotIn('--conditional-diagnostic', command)
        for required in ('--input-manifest downloaded/inputs/evidence/authored-inputs/input-manifest.json',
                         '--historical-manifest downloaded/inputs/evidence/authored-inputs/historical-manifest.json',
                         '--ads-source-supplement evidence/aggregate-source-supplement.json', '--legacy-linux downloaded/legacy'):
            self.assertIn(required, commands[aggregate])
        self.assertEqual(len([command for command in commands if 'build_ads_source_packet.py build' in command]), 1)
        self.assertNotIn('continue-on-error', self.path.read_text())
        self.assertFalse(any('GITHUB_SHA' in step.get('env', {}) for step in self.steps))
        self.assertNotIn('run_dx12_authored_shard.py run', self.path.read_text())

    def test_failure_diagnostics_preserve_original_and_supplemental_results(self):
        uploads = [step for step in self.steps if step.get('uses') == 'actions/upload-artifact@v4']
        self.assertTrue(all(step.get('if') == 'always()' for step in uploads))
        paths = uploads[1]['with']['path']
        for expected in ('evidence/aggregate/summary.json', 'evidence/aggregate/original-verdicts/',
                         'evidence/aggregate-recovery/summary.json', 'evidence/revalidation/original-verdicts/',
                         'evidence/aggregate-recovery/original-verdicts/', 'evidence/aggregate-recovery/original-shard-summaries.json',
                         'downloaded/shards/**/summary.json', 'downloaded/inputs/evidence/authored-inputs/historical-manifest.json'):
            self.assertIn(expected, paths)


if __name__ == '__main__':
    unittest.main()
