"""Synthetic inputs and process mocks only; never proof of native Windows output."""

import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_dx12_authored as authored


class AuthoredDx12Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        image = Image.new('RGBA', (960, 540), (36, 48, 61, 255))
        ImageDraw.Draw(image).rectangle((200, 100, 700, 420), fill=(120, 90, 60, 255))
        output = io.BytesIO()
        image.save(output, format='PNG')
        cls.png = output.getvalue()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Resolve on BOTH sides of assertions: Windows may expose RUNNER~1.
        self.root = Path(temporary.name).resolve()
        self.captures = self.root / 'candidate'
        self.baseline = self.root / 'legacy'
        self.sequence(self.captures)
        self.sequence(self.baseline, 'OpenGl')
        authored.write_json(self.baseline / 'verification.json', {'schema': 'synthetic', 'passed': True, 'frames': 3})

    def sequence(self, folder, backend='Dx12'):
        folder.mkdir(parents=True)
        for index in range(3):
            image = folder / f'{index:04}.png'
            image.write_bytes(self.png)
            authored.write_json(Path(f'{image}.json'), {
                'backend': backend, 'adapter': authored.WARP if backend == 'Dx12' else 'Mesa software',
                'requested': 'dx12' if backend == 'Dx12' else 'gl', 'width': 960, 'height': 540})
            authored.write_json(Path(f'{image}.time.json'), {
                'elapsed_seconds': index / 60, 'sampling_hz': 60})
            authored.write_json(Path(f'{image}.gameplay.json'), {
                'simulation_time': index / 60, 'route': 'ready' if index == 0 else 'ads.hold',
                'run_weight': 0, 'speed': 0, 'simulation_ads': 0 if index == 0 else 1,
                'renderer_failed': False, 'nested': {'ammo': 12, 'vector': [1.0, 2.0]}})

    def edit(self, suffix, field, value, index=1, folder=None):
        path = (folder or self.captures) / f'{index:04}.png{suffix}'
        row = json.loads(path.read_text())
        row[field] = value
        authored.write_json(path, row)

    def logs(self, identity=None, compiler=authored.FXC_LOG):
        folder = self.root / 'process'
        folder.mkdir(exist_ok=True)
        identity = identity or f'renderer requested=dx12 backend=Dx12 adapter={authored.WARP}'
        (folder / 'stdout.log').write_text('startup\n', encoding='utf-8')
        (folder / 'stderr.log').write_text(identity + '\n' + compiler + '\n', encoding='utf-8')
        return folder

    def test_all_frame_finite_and_image_control(self):
        result = authored.validate_sequence(self.captures)
        self.assertEqual(result['frames'], 3)
        self.assertTrue(result['all_images_checked'])
        self.assertGreater(result['minimum_foreground_coverage'], 0.01)

    def test_missing_every_required_file_fails(self):
        for suffix in ('', '.json', '.time.json', '.gameplay.json'):
            path = self.captures / f'0001.png{suffix}'
            data = path.read_bytes()
            path.unlink()
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                authored.validate_sequence(self.captures)
            path.write_bytes(data)

    def test_orphan_sidecars_and_unexpected_files_fail(self):
        for name in ('9999.png.gameplay.json', 'random.txt'):
            path = self.captures / name
            path.write_text('{"extra":true}')
            with self.subTest(name=name), self.assertRaises(ValueError):
                authored.validate_sequence(self.captures)
            path.unlink()

    def test_wrong_backend_request_adapter_and_extent_fail(self):
        original = (self.captures / '0001.png.json').read_bytes()
        for field, value in [('backend', 'OpenGl'), ('backend', 'Vulkan'), ('requested', 'auto'),
                             ('adapter', 'NVIDIA'), ('adapter', ''), ('adapter', None),
                             ('width', 1), ('width', 960.0), ('height', True)]:
            self.edit('.json', field, value)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                authored.validate_sequence(self.captures)
            (self.captures / '0001.png.json').write_bytes(original)

    def test_bad_json_nonfinite_and_duplicate_fields_fail(self):
        path = self.captures / '0001.png.gameplay.json'
        for value in ('{}', '{', '{"x":NaN}', '{"x":1e9999}', '{"x":1,"x":1}'):
            path.write_text(value, encoding='utf-8')
            with self.subTest(value=value), self.assertRaises(ValueError):
                authored.validate_sequence(self.captures)

    def test_non_sampled_uniform_or_broken_png_fails(self):
        path = self.captures / '0001.png'
        Image.new('RGBA', (960, 540), (36, 48, 61, 255)).save(path)
        with self.assertRaisesRegex(ValueError, 'uniform'):
            authored.validate_sequence(self.captures)
        path.write_bytes(self.png[:-1])
        with self.assertRaisesRegex(ValueError, 'truncated PNG'):
            authored.validate_sequence(self.captures)

    def test_no_symlink_subtree_is_silently_ignored(self):
        link = self.captures / 'linked'
        try:
            link.symlink_to(self.baseline, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'host cannot create test symlinks: {error}')
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            authored.validate_sequence(self.captures)

    def test_strict_same_sequence_telemetry_control(self):
        result = authored.compare_sequence(self.baseline, self.captures)
        self.assertEqual(result['gameplay_files'], 3)
        self.assertEqual(result['time_files'], 3)
        self.assertTrue(result['passed'])

    def test_strict_parity_rejects_any_gameplay_or_time_difference(self):
        for suffix, field, value in [('.gameplay.json', 'simulation_time', 0.000000001),
                                     ('.time.json', 'sampling_hz', 30),
                                     ('.gameplay.json', 'renderer_failed', True),
                                     ('.gameplay.json', 'nested', {'ammo': 12, 'vector': [1, 2.0]})]:
            path = self.captures / f'0001.png{suffix}'
            original = path.read_bytes()
            self.edit(suffix, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                authored.compare_sequence(self.baseline, self.captures)
            path.write_bytes(original)

    def test_parity_preserves_sub_float_decimal_difference(self):
        for folder, value in ((self.captures, '0.1000000000000000001'), (self.baseline, '0.1')):
            (folder / '0000.png.time.json').write_text('{"elapsed_seconds":' + value + '}')
        with self.assertRaisesRegex(ValueError, 'value differs'):
            authored.compare_sequence(self.baseline, self.captures)

    def test_baseline_must_be_legacy_with_complete_sidecars(self):
        self.edit('.json', 'backend', 'Dx12', folder=self.baseline)
        with self.assertRaisesRegex(ValueError, 'backend'):
            authored.compare_sequence(self.baseline, self.captures)
        self.edit('.json', 'backend', 'OpenGl', folder=self.baseline)
        (self.baseline / '0000.png.time.json').unlink()
        with self.assertRaises(ValueError):
            authored.compare_sequence(self.baseline, self.captures)

    def test_actual_backend_and_exact_fxc_log_control(self):
        report = authored.renderer_logs(self.logs())
        self.assertEqual(report['shader_compiler'], [authored.FXC_LOG])

    def test_fxc_is_required_not_auto_dxc_or_case_insensitive(self):
        for compiler in ('', 'renderer dx12_shader_compiler=Auto', 'renderer dx12_shader_compiler=Dxc',
                         'renderer dx12_shader_compiler=fxc', authored.FXC_LOG + ' suffix',
                         authored.FXC_LOG + '\nrenderer dx12_shader_compiler=Auto'):
            with self.subTest(compiler=compiler), self.assertRaisesRegex(ValueError, 'expected exact'):
                authored.renderer_logs(self.logs(compiler=compiler))

    def test_requested_flag_does_not_substitute_for_actual_backend(self):
        for identity in ('flags --renderer=dx12', 'renderer requested=dx12 backend=Vulkan adapter=WARP',
                         'renderer requested=dx12 backend=Dx12 adapter=NVIDIA'):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'actual DX12'):
                authored.renderer_logs(self.logs(identity=identity))

    def test_eight_exact_native_replay_commands_and_sampling_rates(self):
        expected = [('gameplay-jump', 60), ('gameplay-reload', None), ('gameplay-walk', None),
                    ('gameplay-ads', None), ('gameplay-ads', None), ('gameplay-layered', 30),
                    ('gameplay-layered', 60), ('gameplay-return', 60)]
        self.assertEqual([(case.sequence, case.hz) for case in authored.CASES], expected)
        for case in authored.CASES:
            command = authored.game_command(self.root / 'game.exe', self.root, self.root / 'out', case, self.root / 'offset.cfg')
            for flag in ('--renderer=dx12', '--force-fallback-adapter', '--no-update', '--reference-viewport'):
                self.assertEqual(command.count(flag), 1)
            self.assertNotIn('--procedural-weapon', command)
            self.assertIn(f'--animation-manifest={self.root / "assets/animations.cfg"}', command)
            rates = [arg for arg in command if arg.startswith('--capture-hz=')]
            self.assertEqual(rates, [] if case.hz is None else [f'--capture-hz={case.hz}'])
            self.assertEqual(any(arg.startswith('--settings=') for arg in command), case.name == 'ads-offset')

    def test_twelve_lighting_commands_preserve_existing_contract(self):
        commands = list(authored.lighting_commands(self.root / 'game.exe', self.root, self.root / 'lighting'))
        self.assertEqual(len(commands), 12)
        self.assertEqual(len({name for name, _ in commands}), 12)
        for name, command in commands:
            for flag in ('--renderer=dx12', '--force-fallback-adapter', '--no-update', '--capture-lighting'):
                self.assertIn(flag, command)
            self.assertIn('--viewmodel-time=0' if name.startswith('ready') else '--viewmodel-time=1.4', command)
            self.assertIn('--viewmodel-clip=normal_ready' if name.startswith('ready') else '--viewmodel-clip=reload_current_wip', command)

    def lighting_fixture(self):
        folder = self.root / 'lighting-fixture'
        folder.mkdir()
        # Independent closed-form expected cardinal/pitched basis vectors.
        scale = math.sqrt(0.98)
        x, y, z = -0.3 / scale, 0.8 / scale, 0.5 / scale
        sine, cosine = math.sin(math.radians(35)), math.cos(math.radians(35))
        directions = [('front', -90, 0, [x, y, z], 100),
                      ('right', 0, 0, [z, y, -x], 110),
                      ('back', 90, 0, [-x, y, -z], 140),
                      ('left', 180, 0, [-z, y, x], 130),
                      ('up', -90, 35, [x, y * cosine + z * sine, -y * sine + z * cosine], 180),
                      ('down', -90, -35, [x, y * cosine - z * sine, y * sine + z * cosine], 80)]
        for pose in ('ready', 'reload'):
            for name, yaw, pitch, view, shade in directions:
                image = folder / f'{pose}_{name}.png'
                native = Image.new('RGBA', (960, 540), authored.BACKGROUND)
                ImageDraw.Draw(native).rectangle((250, 220, 930, 539), fill=(shade, shade, shade, 255))
                native.save(image)
                metadata = {'requested': 'dx12', 'backend': 'Dx12', 'adapter': authored.WARP,
                            'width': 960, 'height': 540}
                authored.write_json(Path(f'{image}.json'), metadata)
                world = Image.new('RGBA', (96, 64), authored.WORLD_BACKGROUND)
                ImageDraw.Draw(world).rectangle((20, 20, 70, 60), fill=(80, 100, 120, 255))
                world.save(Path(f'{image}.world.png'))
                authored.write_json(Path(f'{image}.world.png.json'), {**metadata, 'width': 96, 'height': 64})
                authored.write_json(Path(f'{image}.lighting.json'), {
                    'schema': 'rust-duty-lighting-capture/v1', 'yaw_degrees': yaw,
                    'pitch_degrees': pitch, 'simulation_time': 0, 'ambient': 0.28, 'diffuse': 0.72,
                    'world_light': [x, y, z], 'view_light': view})
        return folder

    def test_actual_lighting_entry_accepts_complete_synthetic_control(self):
        report = authored.validate_lighting(self.lighting_fixture())
        self.assertTrue(report['existing_validator']['passed'])
        self.assertEqual(report['world_images_checked'], 12)
        self.assertEqual(report['viewmodel_images_checked'], 12)

    def test_actual_lighting_entry_rejects_truncated_extra_or_wrong_type_vectors(self):
        folder = self.lighting_fixture()
        paths = sorted(folder.glob('*.lighting.json'))
        originals = {path: json.loads(path.read_text()) for path in paths}
        for field in ('world_light', 'view_light'):
            for value in ('truncated', 'extra', 'string', 'object', 'null'):
                for path, original in originals.items():
                    replacement = {'truncated': original[field][:1], 'extra': original[field] + [0],
                                   'string': '0,0,1', 'object': {'x': 0, 'y': 0, 'z': 1}, 'null': None}[value]
                    authored.write_json(path, {**original, field: replacement})
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field + ' must contain exactly three'):
                    authored.validate_lighting(folder)
                for path, original in originals.items():
                    authored.write_json(path, original)

    def test_actual_lighting_entry_rejects_wrong_component_types(self):
        folder = self.lighting_fixture()
        path = folder / 'ready_front.png.lighting.json'
        original = json.loads(path.read_text())
        for field in ('world_light', 'view_light'):
            for invalid in (True, False, '0.3', None, [], {}):
                vector = original[field].copy()
                vector[1] = invalid
                authored.write_json(path, {**original, field: vector})
                with self.subTest(field=field, invalid=invalid), self.assertRaisesRegex(ValueError, field + ' components must be finite JSON numbers'):
                    authored.validate_lighting(folder)
                authored.write_json(path, original)

    def test_actual_lighting_entry_checks_all_twelve_records(self):
        folder = self.lighting_fixture()
        for path in sorted(folder.glob('*.lighting.json')):
            original = json.loads(path.read_text())
            authored.write_json(path, {**original, 'view_light': original['view_light'][:1]})
            with self.subTest(file=path.name), self.assertRaisesRegex(ValueError, 'view_light must contain exactly three'):
                authored.validate_lighting(folder)
            authored.write_json(path, original)

    def test_actual_lighting_entry_rejects_wrong_schema_and_scalar_types(self):
        folder = self.lighting_fixture()
        path = folder / 'ready_front.png.lighting.json'
        original = json.loads(path.read_text())
        for field in ('yaw_degrees', 'pitch_degrees', 'simulation_time', 'ambient', 'diffuse'):
            for invalid in (True, '0', None, []):
                authored.write_json(path, {**original, field: invalid})
                with self.subTest(field=field, invalid=invalid), self.assertRaisesRegex(ValueError, field + ' must be a finite JSON number'):
                    authored.validate_lighting(folder)
                authored.write_json(path, original)
        for invalid in ({**original, 'schema': 'invented'}, {**original, 'extra': 1},
                        {key: value for key, value in original.items() if key != 'view_light'}):
            authored.write_json(path, invalid)
            with self.assertRaisesRegex(ValueError, 'lighting schema'):
                authored.validate_lighting(folder)
            authored.write_json(path, original)

    def test_execute_retains_invocation_and_nonzero_error(self):
        logs = self.root / 'failure-logs'
        with self.assertRaisesRegex(ValueError, 'process exited 7'):
            authored.execute([sys.executable, '-c', 'print("actual subprocess"); raise SystemExit(7)'],
                             self.root, logs, 20)
        self.assertIn('actual subprocess', (logs / 'stdout.log').read_text())
        invocation = json.loads((logs / 'invocation.json').read_text())
        self.assertEqual(invocation['cwd'], str(self.root))
        self.assertEqual(invocation['timeout_seconds'], 20)

    def test_actual_existing_validator_rejects_truncated_control(self):
        # Exercise the existing real validator CLI, not a mock that says passed.
        script = Path(authored.__file__).parent / 'verify_gameplay_ads_capture.py'
        with self.assertRaisesRegex(ValueError, 'process exited'):
            authored.execute([sys.executable, str(script), str(self.captures)], self.root,
                             self.root / 'truncated-validator', 20)
        self.assertIn('missing or truncated', (self.root / 'truncated-validator/stderr.log').read_text())

    def test_timeout_is_not_a_success(self):
        with patch.object(authored.subprocess, 'Popen', side_effect=subprocess.TimeoutExpired(['game'], 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                authored.execute(['game'], self.root, self.root / 'timeout', 1)
        self.assertTrue((self.root / 'timeout/invocation.json').is_file())

    def binaries(self):
        game, fixture = self.root / 'game.exe', self.root / 'fixture.exe'
        game.write_bytes(b'synthetic executable placeholder')
        fixture.write_bytes(b'synthetic fixture placeholder')
        (self.root / 'settings.cfg').write_text('fov = 90\n')
        return game, fixture

    def test_existing_output_and_bad_timeout_refused_before_launch(self):
        game, fixture = self.binaries()
        for timeout in (0, -1, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, 'timeout'):
                authored.run(game, fixture, self.root, self.root / 'out', self.baseline, timeout)
        with patch.object(authored, 'execute') as execute:
            with self.assertRaises(FileExistsError):
                authored.run(game, fixture, self.root, self.captures, self.baseline, 10)
            execute.assert_not_called()

    def test_source_validation_failure_blocks_all_capture_commands(self):
        game, fixture = self.binaries()
        with patch.object(authored, 'asset_evidence', side_effect=ValueError('source hash mismatch')), \
                patch.object(authored, 'execute') as execute:
            result = authored.run(game, fixture, self.root, self.root / 'out', self.baseline, 10)
        self.assertFalse(result['passed'])
        self.assertIn('source hash mismatch', result['checks'][0]['error'])
        execute.assert_not_called()

    def test_failed_native_launch_still_attempts_other_cases_and_lighting(self):
        game, fixture = self.binaries()
        with patch.object(authored, 'asset_evidence', return_value={'synthetic': True}), \
                patch.object(authored, 'execute', side_effect=ValueError('synthetic launch failure')) as execute:
            result = authored.run(game, fixture, self.root, self.root / 'out', self.baseline, 10)
        self.assertFalse(result['passed'])
        self.assertFalse(result['acceptance_complete'])
        self.assertEqual(result['automated_landmark_gate'], 'open')
        # Fixture, all eight authored sequences and all twelve lighting poses.
        self.assertEqual(execute.call_count, 21)
        self.assertEqual(json.loads((self.root / 'out/summary.json').read_text())['passed'], False)

    def test_mocked_orchestration_runs_every_validator_and_parity(self):
        game, fixture = self.binaries()
        with patch.object(authored, 'asset_evidence', return_value={'synthetic': True}), \
                patch.object(authored, 'execute', return_value={'synthetic': True}) as execute, \
                patch.object(authored, 'validate_orientation', return_value={}), \
                patch.object(authored, 'validate_sequence', return_value={}), \
                patch.object(authored, 'compare_sequence', return_value={}) as compare, \
                patch.object(authored, 'validate_lighting', return_value={}), \
                patch.object(authored, 'review_guides', return_value={'automated_landmark_gate': 'open'}):
            report = authored.run(game, fixture, self.root, self.root / 'out', self.baseline, 10)
        self.assertTrue(report['passed'])  # Mocked orchestration, NOT native execution proof.
        self.assertFalse(report['acceptance_complete'])
        self.assertEqual(compare.call_count, 8)
        commands = [call.args[0] for call in execute.call_args_list]
        scripts = [Path(command[1]).name for command in commands if command[0] == sys.executable]
        self.assertEqual(scripts.count('verify_gameplay_ads_capture.py'), 2)
        for validator in ('verify_jump_capture.py', 'verify_gameplay_capture.py',
                          'verify_gameplay_walk_capture.py', 'verify_reload_return_capture.py',
                          'verify_ads_placement_capture.py', 'verify_layered_locomotion_capture.py'):
            self.assertEqual(scripts.count(validator), 1)
        self.assertFalse(any('--allow-legacy-walk' in command for command in commands))
        self.assertIn('viewmodel_x = 0.20', (self.root / 'out/ads-offset.cfg').read_text())

    def test_guide_preserves_raw_pixels_and_never_claims_measurement(self):
        before = authored.sha256(self.captures / '0000.png')
        report = authored.review_guides(self.captures, self.baseline, self.root / 'review', Path(authored.__file__).resolve().parents[1])
        self.assertEqual(report['automated_landmark_gate'], 'open')
        self.assertEqual(len(report['records']), 4)
        historical = report['historical_projection_context']
        self.assertFalse(historical['current_runtime_geometry_match_verified'])
        self.assertIn('not current DX12 measured pixels', historical['evidence_type'])
        self.assertEqual(len(historical['records']), 2)
        self.assertEqual(authored.sha256(self.captures / '0000.png'), before)
        for row in report['records']:
            self.assertIsNone(row['measured_center'])
            self.assertIsNone(row['projected_center'])
            self.assertEqual(row['tolerance_px'], 4)
            self.assertEqual(row['raw_sha256'], authored.sha256(self.root / 'review' / row['raw']))
            self.assertEqual(row['calibrated_center'], [480, 270] if row['pose'] == 'ads' else [526, 280])
            raw = (self.root / 'review' / row['raw']).read_bytes()
            self.assertEqual(raw, self.png)
            with Image.open(self.root / 'review' / row['guide']) as guide:
                self.assertEqual(guide.size, (960, 540))
                x, y = row['calibrated_center']
                self.assertEqual(guide.getpixel((x - 4, y)), (255, 207, 64))

    def test_review_preserves_each_exact_source_sidecar_and_hash(self):
        source_root = Path(authored.__file__).resolve().parents[1]
        for label, folder in (('dx12', self.captures), ('legacy', self.baseline)):
            for index in range(3):
                path = folder / f'{index:04}.png.json'
                data = json.loads(path.read_text())
                data['source_identity_probe'] = f'{label}-{index}'
                # Deliberate whitespace/order/newline differences would be lost
                # by rebuilding metadata from parsed fields after copying PNGs.
                path.write_bytes(('  ' + json.dumps(data, indent=3, sort_keys=True) + '\r\n').encode())
        output = self.root / 'review-sidecars'
        report = authored.review_guides(self.captures, self.baseline, output, source_root)
        for row in report['records']:
            source = self.captures if row['backend'] == 'dx12' else self.baseline
            original = source / f'{row["source_frame"]}.json'
            copied = output / row['raw_sidecar']
            self.assertEqual(row['source_sidecar'], original.name)
            self.assertEqual(row['raw_sidecar'], row['raw'] + '.json')
            self.assertEqual(copied.read_bytes(), original.read_bytes())
            self.assertEqual(row['raw_sidecar_sha256'], authored.sha256(original))
            self.assertEqual(row['raw_sidecar_sha256'], authored.sha256(copied))
            self.assertEqual(row['actual_backend'], 'Dx12' if row['backend'] == 'dx12' else 'OpenGl')
            self.assertEqual(row['source_role'], 'dx12-under-review' if row['backend'] == 'dx12' else 'legacy-comparison-only')
            self.assertFalse((output / (row['guide'] + '.json')).exists())
        self.assertEqual(json.loads((output / 'landmark-review.json').read_text()), report)

    def test_review_rejects_cross_backend_sidecar_substitution(self):
        source_root = Path(authored.__file__).resolve().parents[1]
        candidate = self.captures / '0000.png.json'
        legacy = self.baseline / '0000.png.json'
        candidate_bytes, legacy_bytes = candidate.read_bytes(), legacy.read_bytes()
        for label, target, substituted in (('legacy-as-dx12', candidate, legacy_bytes),
                                            ('dx12-as-legacy', legacy, candidate_bytes)):
            target.write_bytes(substituted)
            output = self.root / label
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, 'renderer identity'):
                authored.review_guides(self.captures, self.baseline, output, source_root)
            self.assertFalse((output / 'landmark-review.json').exists())
            candidate.write_bytes(candidate_bytes)
            legacy.write_bytes(legacy_bytes)

    def test_review_requires_selected_frame_sidecar_not_another_available_one(self):
        source_root = Path(authored.__file__).resolve().parents[1]
        for index, source in enumerate((self.captures, self.baseline)):
            missing = source / '0001.png.json'  # Selected ADS frame; 0002 remains available.
            original = missing.read_bytes()
            missing.unlink()
            output = self.root / f'missing-source-{index}'
            with self.subTest(source=source.name), self.assertRaisesRegex(ValueError, '0001.png.json'):
                authored.review_guides(self.captures, self.baseline, output, source_root)
            self.assertFalse((output / 'landmark-review.json').exists())
            missing.write_bytes(original)

    def test_review_rejects_wrong_source_adapter_request_and_extent(self):
        source_root = Path(authored.__file__).resolve().parents[1]
        path = self.captures / '0000.png.json'
        original = json.loads(path.read_text())
        cases = [('adapter', 'NVIDIA'), ('requested', 'auto'), ('width', 1920), ('height', 540.0)]
        for index, (field, invalid) in enumerate(cases):
            authored.write_json(path, {**original, field: invalid})
            output = self.root / f'invalid-source-{index}'
            with self.subTest(field=field), self.assertRaises(ValueError):
                authored.review_guides(self.captures, self.baseline, output, source_root)
            self.assertFalse((output / 'landmark-review.json').exists())
            authored.write_json(path, original)

    def test_review_needs_real_stationary_held_ads_telemetry(self):
        for index in (1, 2):
            self.edit('.gameplay.json', 'speed', 2, index=index)
        with self.assertRaisesRegex(ValueError, 'fully held ADS'):
            authored.review_guides(self.captures, self.baseline, self.root / 'review', Path(authored.__file__).resolve().parents[1])

    def orientation(self, folder=None):
        folder = folder or self.root / 'orientation'
        folder.mkdir()
        for name, size in (('quadrant.png', (96, 64)), ('readback-width-65.png', (65, 49))):
            image = Image.new('RGBA', size)
            for x in range(size[0]):
                for y in range(size[1]):
                    color = {(True, True): (255, 0, 0, 255), (False, True): (0, 255, 0, 255),
                             (True, False): (0, 0, 255, 255), (False, False): (255, 255, 0, 255)}[x < size[0] / 2, y < size[1] / 2]
                    image.putpixel((x, y), color)
            image.save(folder / name)
            authored.write_json(folder / f'{name}.json', {
                'requested': 'dx12', 'backend': 'Dx12', 'adapter': authored.WARP,
                'width': size[0], 'height': size[1]})
        authored.write_json(folder / 'renderer-contract-report.json', {
            'status': 'passed', 'native_execution': True, 'platform': 'windows',
            'requested': 'dx12', 'backend': 'Dx12', 'adapter': authored.WARP,
            'force_fallback_adapter': True})
        return folder

    def test_orientation_control_and_flip_discrimination(self):
        folder = self.orientation()
        self.assertEqual(len(authored.validate_orientation(folder)['orientation']), 2)
        with Image.open(folder / 'quadrant.png') as image:
            image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(folder / 'quadrant.png')
        with self.assertRaisesRegex(ValueError, 'orientation'):
            authored.validate_orientation(folder)

    def test_orientation_report_cannot_be_non_native_or_another_adapter(self):
        folder = self.orientation()
        path = folder / 'renderer-contract-report.json'
        original = path.read_bytes()
        for field, value in [('native_execution', False), ('platform', 'linux'),
                             ('force_fallback_adapter', False), ('adapter', 'NVIDIA'),
                             ('adapter', None), ('adapter', 123), ('adapter', False),
                             ('adapter', []), ('adapter', {})]:
            data = json.loads(original)
            data[field] = value
            authored.write_json(path, data)
            with self.subTest(field=field), self.assertRaises(ValueError):
                authored.validate_orientation(folder)
            path.write_bytes(original)

    def test_malformed_orientation_is_recorded_and_later_captures_are_attempted(self):
        game, fixture = self.binaries()
        output = self.root / 'malformed-orientation-run'

        def fake_execute(command, *args, **kwargs):
            if command[0] == str(fixture.resolve()):
                folder = self.orientation(output / 'renderer-contract')
                path = folder / 'renderer-contract-report.json'
                record = json.loads(path.read_text())
                record['adapter'] = None
                authored.write_json(path, record)
            return {'synthetic_process': True}

        with patch.object(authored, 'asset_evidence', return_value={'synthetic': True}), \
                patch.object(authored, 'execute', side_effect=fake_execute) as execute:
            report = authored.run(game, fixture, self.root, output, self.baseline, 10)
        orientation = next(row for row in report['checks'] if row['name'] == 'orientation-renderer-contract')
        self.assertFalse(orientation['passed'])
        self.assertIn('not a passing native Windows DX12 WARP run', orientation['error'])
        self.assertFalse(report['passed'])
        game_commands = [call.args[0] for call in execute.call_args_list if call.args[0][0] == str(game.resolve())]
        self.assertEqual(len(game_commands), 20)
        self.assertEqual(sum(any(arg.startswith('--capture-sequence=') for arg in command) for command in game_commands), 8)
        self.assertEqual(sum('--capture-lighting' in command for command in game_commands), 12)
        saved = json.loads((output / 'summary.json').read_text())
        self.assertEqual(saved['checks'], report['checks'])

    def test_cli_cannot_report_a_native_run_on_non_windows(self):
        with patch.object(authored.sys, 'platform', 'linux'), patch.object(authored, 'run') as run:
            result = authored.main(['--executable', 'missing', '--renderer-contract', 'missing',
                                    '--legacy', 'missing', '--evidence', 'missing'])
        self.assertEqual(result, 1)
        run.assert_not_called()

    def test_workflow_fetches_only_same_run_and_attempt_inputs(self):
        workflow = (Path(authored.__file__).resolve().parents[1] / '.github/workflows/wgpu-dx12-authored.yml').read_text()
        for name in ('reload', 'walk', 'ads', 'directional', 'jump'):
            self.assertIn(f'name: generated-{name}-runtime', workflow)
        self.assertEqual(workflow.count('evidence-attempt-${{ github.run_attempt }}'), 8)
        for forbidden in ('\n          run-id:', '\n          repository:', '\n          github-token:', 'continue-on-error:'):
            self.assertNotIn(forbidden, workflow)
        self.assertIn('--features wgpu-runtime', workflow)
        self.assertIn('--bin vector-range --example renderer_contract', workflow)
        self.assertIn('--include-jump --require-generated', workflow)


if __name__ == '__main__':
    unittest.main()
