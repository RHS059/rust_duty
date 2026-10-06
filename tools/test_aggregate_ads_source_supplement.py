"""Original synthetic controls, never native Windows or visual evidence."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import aggregate_dx12_authored as aggregate
import ads_source_visibility_binding as binding
import revalidate_ads_offset as leaf
import test_ads_source_visibility_binding as packet_fixture
import test_aggregate_dx12_authored as fixture
import verify_gameplay_ads_capture as ads_validator
from test_capture_frame_witness import marker


write = fixture.write
BLOCKED = 'ValueError: blocked by a failed required capture or input check'
CAPTURE = {'source_commit': '8f571464be706d0abde862e124582a188f633baf',
           'run_id': '37415102452', 'run_attempt': '1'}
LEAF_VERIFIER = {'source_commit': 'e9eb434d4d4b127940d977c9acf18a3fe80e130e',
            'run_id': '37420000000', 'run_attempt': '1'}
VERIFIER = {'source_commit': 'b' * 40, 'run_id': '37420000001', 'run_attempt': '1'}
ENV = {'GITHUB_SHA': VERIFIER['source_commit'], 'GITHUB_RUN_ID': VERIFIER['run_id'],
       'GITHUB_RUN_ATTEMPT': VERIFIER['run_attempt']}


def gameplay(base, index):
    row = deepcopy(base)
    row.update(simulation_time=index, segment='complete_cycle', route='ready', clip='',
               native_clip_seconds=None, clip_duration=None, direction=0, simulation_ads=0,
               ads_requested=False, speed=0, walk_seconds=None, walk_weight=0, run_weight=0,
               sprinting=False, shots=int(index >= 166), ammo=30 if index >= 311 else 12,
               reserve=71 if index >= 311 else 90)
    if 31 <= index <= 50 or 151 <= index <= 165:
        row.update(route='ads.entry', segment='sprint_to_ads' if index >= 151 else 'complete_cycle',
                   run_weight=0.5 if index >= 151 else 0, direction=-1 if index < 34 else 1)
    elif 51 <= index <= 120 or 166 <= index <= 250 or 311 <= index <= 350:
        row.update(route='ads.hold', segment='fire_while_aiming' if 166 <= index <= 250 else 'complete_cycle',
                   speed=1 if 51 <= index <= 80 else 0)
    elif 121 <= index <= 140:
        row.update(route='ads.exit', direction=-1 if index < 124 else 1,
                   sprinting=True, run_weight=0.5, walk_weight=0.5, walk_seconds=index)
    elif 141 <= index <= 150:
        row.update(route='locomotion', sprinting=True, run_weight=1)
    elif 251 <= index <= 280:
        row.update(route='regular_walk')
    elif 281 <= index <= 310:
        row.update(route='reload.tactical')
    if row['route'].startswith('ads.'):
        row.update(clip='ads_' + row['route'].split('.')[1] + '_r1', native_clip_seconds=0.1,
                   clip_duration=1, simulation_ads=1 if row['route'] == 'ads.hold' else 0.5,
                   ads_requested=row['route'] != 'ads.exit')
    if row['speed']:
        row.update(walk_weight=1, walk_seconds=index)
    return row


def gl_profile(folder, native_binding):
    invocation = aggregate.read_record(folder / 'logs/windows-legacy-capture/invocation.json')
    identity = aggregate.shard_runner.role_witness_identity(native_binding, 'ads-offset', 'windows-legacy')
    output = next(arg.split('=', 1)[1] for arg in invocation['command'] if arg.startswith('--output='))
    cap = dict(schema='rust-duty-gl-precision-receipt/v1', backend='OpenGl', platform='windows',
               architecture='x86_64', capture_identity=identity, adapter='llvmpipe (synthetic unit fixture)',
               measurement_complete=True, phase='capture_before_readback', subpixel={'status': 'reported', 'bits': 8},
               shader_precision={name: {'status': 'reported', 'precision_bits': bits, 'range': [exponent, exponent]}
                   for name, bits, exponent in [('vertex_high_float', 23, 127), ('vertex_low_float', 10, 15),
                                               ('fragment_medium_float', 10, 15), ('fragment_low_float', 10, 15)]})
    target = dict(schema='rust-duty-gl-target-capture-receipt/v1', capture_identity=identity,
                  width=960, height=540, depth=True, miniquad_sample_count_parameter=0,
                  allocation='plain_non_resolving_texture_target', phase='capture_before_readback',
                  capture_path=output + '/0000.png')
    (folder / 'logs/windows-legacy-capture/stderr.log').write_text(
        'renderer gl_precision_receipt=' + json.dumps(cap) + '\nrenderer gl_target_capture_receipt='
        + json.dumps(target) + '\n')


class AggregateSupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.serial = 0
        cls.source = source = packet_fixture.BindingTests()
        source.setUp()
        cls.addClassCleanup(source.doCleanups)
        source.native.update(CAPTURE)
        source.receipt['source_base_commit'] = CAPTURE['source_commit']
        original_make_root = fixture.make_root

        def make_root(root):
            native = original_make_root(root)
            for name, key in source.inputs.items():
                if name == 'ads-offset.cfg':
                    continue
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source.root / source.files[key], path)
            source.native.update({key: value for key, value in native.items()
                                  if key not in ('source_commit', 'run_id', 'run_attempt', 'runtime_and_manifest_sha256')})
            # This original metadata input is deliberately outside the leaf's
            # 21 consumed inputs. The aggregate must continue binding it.
            key = 'assets/authoring/ads/sight_alignment.json'
            source.native['runtime_and_manifest_sha256'][key] = native['runtime_and_manifest_sha256'][key]
            manifest = json.loads((root / 'input-manifest.json').read_text())
            manifest['binding'] = source.native
            write(root / 'input-manifest.json', manifest)
            shutil.copyfile(Path(ads_validator.__file__), root / 'tools/verify_gameplay_ads_capture.py')
            return deepcopy(source.native)

        with patch.object(fixture, 'make_root', side_effect=make_root), redirect_stdout(io.StringIO()):
            cls.root, cls.incoming, cls.historical, cls.historical_manifest, cls.native = fixture.make_fixture(cls.base)
        source.packet['capture_binding'] = deepcopy(cls.native)
        for role in aggregate.ROLES:
            path = source.root / source.outputs[role]
            records = [json.loads(line) for line in path.read_text().splitlines()]
            for index, record in enumerate(records[1:]):
                row = gameplay(record['native_gameplay'], index)
                record['native_gameplay'] = row
                for scenario in leaf.SCENARIOS:
                    folder = cls.incoming / scenario / aggregate.shards.capture_paths(scenario)[role]
                    write(folder / f'{index:04}.png.gameplay.json', row)
                    write(folder / f'{index:04}.png.time.json', record['native_time'])
                    color = (90, 120, 60, 255) if scenario == 'ads-offset' and row['route'] == 'ready' else (120, 90, 60, 255)
                    image = Image.open(io.BytesIO(fixture.image_bytes(color)))
                    if scenario == 'ads-offset' and index == 0:
                        image = Image.new('RGBA', aggregate.authored.EXTENT, aggregate.authored.BACKGROUND)
                    identity = aggregate.shard_runner.role_witness_identity(cls.native, scenario, role)
                    image.paste(marker(index, identity).crop((0, 0, 64, 22)), (0, 0))
                    image.save(folder / f'{index:04}.png')
            raw = b''.join(packet_fixture.encoded(record) for record in records)
            path.write_bytes(raw)
            source.receipt['backend_reports'][binding.BACKENDS[role][0]]['output'] = packet_fixture.digest(raw)
            source.invocations[role] = json.loads((cls.incoming / 'ads-offset' / 'logs' / f'{role}-capture/invocation.json').read_text())
        source.packet['original_invocations'] = deepcopy(source.invocations)
        source.save()
        cls.receipt_sha256 = aggregate.authored.sha256(source.root / 'receipt.json')
        for scenario in leaf.SCENARIOS:
            folder = cls.incoming / scenario
            if scenario == 'ads-offset':
                shutil.copyfile(source.native_offset, folder / 'ads-offset.cfg')
                gl_profile(folder, cls.native)
            for role in aggregate.ROLES:
                frames = folder / aggregate.shards.capture_paths(scenario)[role]
                if scenario == 'ads-gameplay':
                    verdict = ads_validator.verify(frames)
                    write(folder / 'logs' / f'{role}-validator/stdout.log', verdict)
                else:
                    (frames / 'verification.json').unlink()
                    shutil.rmtree(folder / 'logs' / f'{role}-validator')
            report = json.loads((folder / 'summary.json').read_text())
            report['files'] = aggregate.shards.inventory_files(folder)
            if scenario == 'ads-offset':
                report.update(passed=False, status='failed')
                for row in report['checks']:
                    if row['name'].endswith('/finite-images'):
                        role = row['name'].split('/')[0]
                        try:
                            aggregate.shard_runner.validate_role_images(folder / report['capture_paths'][role], role, 553,
                                expected_witness_identity=aggregate.shard_runner.role_witness_identity(cls.native, scenario, role))
                        except aggregate.shard_runner.CaptureStructureError as error:
                            row.pop('result')
                            row.update(passed=False, error='CaptureError: ' + str(error))
                    elif row['name'].endswith('/existing-validator') or row['name'] == 'same-windows-strict-parity':
                        row.pop('result')
                        row.update(passed=False, error=BLOCKED)
            write(folder / 'summary.json', report)
        cls.leaf_output = cls.base / 'leaf'
        with patch.dict(os.environ, {'GITHUB_SHA': LEAF_VERIFIER['source_commit'],
                                    'GITHUB_RUN_ID': LEAF_VERIFIER['run_id'],
                                    'GITHUB_RUN_ATTEMPT': LEAF_VERIFIER['run_attempt']}), redirect_stdout(io.StringIO()):
            result = leaf.run(input_manifest=cls.root / 'input-manifest.json',
                gameplay_shard=cls.incoming / 'ads-gameplay', offset_shard=cls.incoming / 'ads-offset',
                source_packet=source.packet_path, source_receipt_sha256=cls.receipt_sha256,
                capture_rustc_sha256=source.expected_compiler_sha256, evidence=cls.leaf_output,
                capture_context=CAPTURE, verifier_context=LEAF_VERIFIER)
        if not result['passed']:
            raise AssertionError(result.get('failure'))
        cls.request = {'leaf_summary': str(cls.leaf_output / 'summary.json'), 'source_packet': str(source.packet_path),
                       'source_receipt_sha256': cls.receipt_sha256, 'capture_rustc_sha256': source.expected_compiler_sha256,
                       'capture_context': CAPTURE, 'leaf_verifier_context': LEAF_VERIFIER, 'verifier_context': VERIFIER}

    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def output(self, name):
        type(self).serial += 1
        return self.base / f'{name}-{self.serial}'

    def load(self, request=None):
        intake = aggregate.AdsSourceSupplement(request or self.request)
        destination = self.output('intake')
        destination.mkdir()
        intake.load(self.native, self.incoming, self.root / 'input-manifest.json', destination)
        return intake, destination

    def restore(self, path):
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        return json.loads(original)

    def invoke(self, name, request=True):
        output = self.output(name)
        with redirect_stdout(io.StringIO()):
            report = aggregate.run(self.root, self.incoming, self.historical, output,
                self.root / 'input-manifest.json', historical_manifest=self.historical_manifest,
                ads_source_supplement=self.request if request else None)
        return output, report

    def test_full_nine_shard_correction_runs_original_validators_and_preserves_history(self):
        originals = aggregate.shards.inventory_files(self.incoming, exclude=())
        output, report = self.invoke('corrected')
        self.assertTrue(report['passed'], [row for row in report['checks'] if not row['passed']])
        self.assertFalse(report['acceptance_complete'])
        self.assertEqual(report['capture_context'], CAPTURE)
        self.assertEqual(report['verifier_context'], VERIFIER)
        self.assertEqual(report['ads_source_supplement']['leaf_verifier_context'], LEAF_VERIFIER)
        self.assertEqual([row['name'] for row in report['checks']], aggregate.expected_checks(ads_source_supplement=True))
        self.assertNotIn('ads-offset/local-checks', report['expected_checks'])
        for role in aggregate.ROLES:
            row = next(row for row in report['checks'] if row['name'] == f'ads-offset/{role}/corrected-assembled-evidence')
            self.assertEqual(row['result']['existing_validator']['schema'], 'rust-duty-native-ads-capture/v1')
            self.assertEqual([row['frame'] for row in row['result']['source_fallback']], [0])
            for name in ('ads-placement-existing-validator', 'layered-rates-existing-validator'):
                self.assertTrue(next(row for row in report['checks'] if row['name'] == f'{role}/{name}')['passed'])
        for scenario in leaf.SCENARIOS:
            self.assertEqual((output / 'original-verdicts' / f'{scenario}-summary.json').read_bytes(),
                             (self.incoming / scenario / 'summary.json').read_bytes())
        self.assertEqual(aggregate.shards.inventory_files(self.incoming, exclude=()), originals)
        self.assertEqual(len(report['diagnostics']), len(aggregate.CASES))
        self.assertTrue(all(row['acceptance_predicate'] is False for row in report['diagnostics']))

    def test_leaf_boolean_is_insufficient_and_inventory_is_closed(self):
        path = self.leaf_output / 'summary.json'
        saved = self.restore(path)
        for mutation in ('missing_check', 'binding', 'receipt', 'compiler', 'packet'):
            changed = deepcopy(saved)
            if mutation == 'missing_check':
                changed['checks'].pop()
            elif mutation == 'binding':
                changed['capture_binding']['executable_sha256'] = 'b' * 64
            else:
                changed[{'receipt': 'source_receipt_sha256', 'compiler': 'capture_rustc_sha256',
                         'packet': 'source_packet_sha256'}[mutation]] = 'b' * 64
            write(path, changed)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.load()
        write(path, saved)
        extra = self.leaf_output / 'unrecorded.txt'
        extra.write_text('changed leaf tree')
        self.addCleanup(extra.unlink)
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            self.load()

    def test_capture_verifier_and_full_binding_mismatches_fail(self):
        for context, field, value in [('capture_context', 'source_commit', 'a' * 40),
                                       ('capture_context', 'run_id', '37415102453'),
                                       ('capture_context', 'run_attempt', '2'),
                                       ('leaf_verifier_context', 'run_id', '37420000002'),
                                       ('verifier_context', 'source_commit', 'a' * 40)]:
            request = deepcopy(self.request)
            request[context][field] = value
            with self.subTest(context=context, field=field), self.assertRaises(ValueError):
                self.load(request)
        for field in ('executable_sha256', 'renderer_contract_sha256'):
            changed = deepcopy(self.native)
            changed[field] = 'b' * 64
            intake = aggregate.AdsSourceSupplement(self.request)
            output = self.output('bad-binding')
            output.mkdir()
            with self.subTest(field=field), self.assertRaises(ValueError):
                intake.load(changed, self.incoming, self.root / 'input-manifest.json', output)

    def test_both_original_summary_hashes_are_required(self):
        for scenario in leaf.SCENARIOS:
            path = self.incoming / scenario / 'summary.json'
            old = path.read_bytes()
            path.write_bytes(old + b'\n')
            try:
                with self.subTest(scenario=scenario), self.assertRaisesRegex(ValueError, 'summary'):
                    self.load()
            finally:
                path.write_bytes(old)

    def test_original_unrelated_failures_timeouts_and_missing_checks_cannot_be_excused(self):
        report = aggregate.read_record(self.incoming / 'ads-offset/summary.json')
        mutations = [lambda saved: saved.update(budget_exhausted=True),
                     lambda saved: saved.update(fatal_error='native capture failed'),
                     lambda saved: saved.update(elapsed_seconds=saved['run_timeout_seconds']),
                     lambda saved: saved.update(status='interrupted'), lambda saved: saved['checks'].pop()]
        for name, error in [('validated-inputs', 'ValueError: corrupt input'),
                            ('dx12/capture', 'TimeoutExpired: native capture'),
                            ('dx12/finite-images', 'ValueError: nonfinite telemetry'),
                            ('dx12/existing-validator', 'ValueError: gameplay changed'),
                            ('same-windows-strict-parity', 'ValueError: metadata differs')]:
            def change(saved, name=name, error=error):
                row = next(row for row in saved['checks'] if row['name'] == name)
                row.pop('result', None)
                row.update(passed=False, error=error)
            mutations.append(change)
        for index, mutate in enumerate(mutations):
            changed = deepcopy(report)
            mutate(changed)
            with self.subTest(index=index), self.assertRaises(ValueError):
                aggregate.offset_correction_eligibility(changed)

    def test_full_root_metadata_outside_leaf_inputs_remains_required(self):
        path = self.root / 'assets/authoring/ads/sight_alignment.json'
        self.restore(path)
        path.write_text('{}\n')
        self.assertNotIn('assets/authoring/ads/sight_alignment.json', binding.INPUTS)
        with self.assertRaisesRegex(ValueError, 'source runtime/assets'):
            aggregate.validated_manifest(self.root / 'input-manifest.json', self.root, expected_context=CAPTURE)
        _, report = self.invoke('changed-root')
        self.assertFalse(report['passed'])
        rows = {row['name']: row for row in report['checks']}
        self.assertFalse(rows['validated-inputs']['passed'])
        self.assertFalse(rows['ads-source-supplement/bound-leaf']['passed'])

    def test_stale_receipt_compiler_and_native_bytes_are_rejected(self):
        for path in (self.source.root / 'receipt.json',
                     self.source.root / self.source.files[self.source.receipt['oracle_execution']['rustc_vv']],
                     self.incoming / 'ads-offset' / aggregate.shards.capture_paths('ads-offset')['dx12'] / '0001.png'):
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            try:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    intake, output = self.load()
                    intake.prepare(self.incoming / 'ads-offset', intake.original_reports['ads-offset'], output / 'assembled', self.native)
            finally:
                path.write_bytes(original)

    def test_unrelated_failure_and_partial_nine_shards_still_prevent_aggregate_pass(self):
        folder = self.incoming / 'jump-gameplay'
        moved = self.base / 'temporarily-removed-jump'
        folder.rename(moved)
        self.addCleanup(moved.rename, folder)
        with self.assertRaisesRegex(ValueError, 'exactly the nine'):
            aggregate.validate_shard_set(self.incoming)
        summary = self.incoming / 'reload-gameplay/summary.json'
        changed = self.restore(summary)
        changed.update(passed=False, status='failed')
        row = next(row for row in changed['checks'] if row['name'] == 'dx12/existing-validator')
        row.pop('result')
        row.update(passed=False, error='ValueError: unrelated reload gameplay failure')
        write(summary, changed)
        _, report = self.invoke('unrelated-failure')
        self.assertFalse(report['passed'])
        rows = {row['name']: row for row in report['checks']}
        self.assertFalse(rows['exact-nine-shards']['passed'])
        self.assertFalse(rows['reload-gameplay/local-checks']['passed'])
        # The valid offset correction can complete independently, but it
        # cannot make either unrelated original failure disappear.
        self.assertTrue(rows['ads-source-supplement/bound-leaf']['passed'])
        for role in aggregate.ROLES:
            self.assertTrue(rows[f'ads-offset/{role}/corrected-assembled-evidence']['passed'])

    def test_unsupplemented_mode_keeps_actual_same_run_context(self):
        with self.assertRaisesRegex(ValueError, 'expected GitHub'):
            aggregate.validated_manifest(self.root / 'input-manifest.json', self.root)
        with patch.dict(os.environ, {'GITHUB_SHA': CAPTURE['source_commit'], 'GITHUB_RUN_ID': CAPTURE['run_id'],
                                    'GITHUB_RUN_ATTEMPT': CAPTURE['run_attempt']}):
            native = aggregate.validated_manifest(self.root / 'input-manifest.json', self.root)
            report = aggregate.read_shard(self.incoming / 'ads-offset', 'ads-offset', native)
            with self.assertRaisesRegex(ValueError, 'required successful check missing'):
                aggregate.shard_pass(report)
        self.assertNotIn('ads-source-supplement/bound-leaf', aggregate.expected_checks())


if __name__ == '__main__':
    unittest.main()
