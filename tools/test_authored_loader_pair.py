"""Independent synthetic source, reader and retained-byte guards for PR51.

No native executable, authored asset or compiler is run here. Git is used
only for temporary source-witness fixtures; profile processes are mocked.
"""
import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import performance_matrix as matrix
import run_cpu_image_preservation as image
import run_authored_loader_pair as loader
import run_windows_cpu_profile as profile
import test_performance_matrix as matrix_tests
import test_geometry_profile_pair as geometry_tests


RECEIPT = 'a' * 64
IDENTITY = [0x3f800000 if i in (0, 5, 10, 15) else 0 for i in range(16)]


def f32_bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def corner_bytes(alpha=255):
    corners = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.)) * 2
    return b''.join(struct.pack('<3f2f4B4f', *point, 0., 0., 128, 64, 32, alpha, 0., 0., 1., 0.)
                    for point in corners)


def report_fixture(native=True, stored_vertices=6):
    cases = []
    for name in loader.CASE_NAMES:
        alpha = 255
        if name.startswith('manifest-'):
            steps = int(name.split('-')[-1])
            metadata = {'route': 'load_manifest/committed_step/draw', 'fixed_steps': steps,
                        'warning':'Authored WIP: empty reload, fire, mantle clips unavailable; reload pose crossfades',
                        'simulation_time_bits': struct.unpack('<Q', struct.pack('<d', steps * struct.unpack('<f', struct.pack('<f', 1. / 120.))[0]))[0]}
        elif name.startswith('rigid-alpha-'):
            value = (0.5, 0.25, 0.5)[int(name[-1])]
            metadata = {'route': 'draw_authored_parts', 'alpha': value}
            alpha = int(value * 255. + 0.5)
        else:
            fraction = (0., 0.5, 0.9, 0.)[int(name[-1])]
            metadata = {'route': 'load/draw', 'clip': name.rsplit('-', 1)[0] + '_clip',
                        'duration_bits': f32_bits(2.), 'time_bits': f32_bits(2. * fraction),
                        'fraction_tenths': (0, 5, 9, 0)[int(name[-1])], 'cant_bits': 0}
        command = {'model_bits': IDENTITY.copy(), 'blend': 'Alpha', 'texture': {
            'width': 2, 'height': 2, 'filter': 'Linear', 'wrap_x': 'Repeat', 'wrap_y': 'Repeat',
            'rgba_sha256': 'b' * 64}, 'stored_vertices': stored_vertices, 'indices': 6,
            'expanded_sha256': image.controls.digest(corner_bytes(alpha))}
        cases.append({'name': name, 'metadata': metadata, 'commands': [command]})
    counts = {name: {kind: [{'old_vertices': 6, 'deduplicated_vertices': 3, 'indices': 6}]
                    for kind in ('skin', 'rigid')} for name in ('ready', 'walk', 'ads', 'reload')}
    return {'schema': loader.SCHEMA, 'source_receipt_sha256': RECEIPT,
            'native_images': native, 'camera': {'extent': loader.EXTENT.copy(),
            'view_projection_bits': IDENTITY.copy(), 'derivation': 'synthetic common camera'},
            'cases': cases, 'source_counts': counts,
            'scope': 'synthetic report only; no native execution'}


def write_outputs(root, report):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    matrix.write_json(root / 'report.json', report)
    matrix.write_json(root / 'camera.json', report['camera'])
    pixels = Image.new('RGBA', tuple(loader.EXTENT), (8, 16, 24, 255))
    for i in range(128):
        pixels.putpixel((i, 0), (32 + i % 8, 64, 96, 255))
    for case in report['cases']:
        alpha = int(case['metadata'].get('alpha', 1.) * 255. + 0.5)
        (root / (case['name'] + '.corners.bin')).write_bytes(corner_bytes(alpha))
        if report['native_images']:
            pixels.save(root / (case['name'] + '.png'))
    return root


class LoaderSourcePairTests(unittest.TestCase):
    def setUp(self):
        self.old = {name: ('old ' + name).encode() for name in image.LOADER_BASELINE}
        self.production = {'Cargo.toml': b'common manifest', image.ARENA_PATH: b'current packed serializer',
                           image.UPLOAD_POLICY_PATH: b'pub const REUSE_ENABLED: bool = true;\n',
                           **{name: ('new ' + name).encode() for name in self.old}}
        for item in (patch.object(image, 'PRODUCTION_MANIFEST', matrix.canonical_hash(image.hashes(self.production))),
                     patch.object(image, 'LOADER_BASELINE', image.hashes(self.old))):
            item.start()
            self.addCleanup(item.stop)

    def test_exact_two_loader_delta_preserves_serializer_reuse_and_inputs(self):
        before = copy.deepcopy((self.production, self.old))
        variants = image.loader_production_pair(self.production, self.old)
        self.assertEqual((self.production, self.old), before)
        self.assertEqual(variants['candidate'], self.production)
        self.assertEqual({n for n in self.production if variants['baseline'][n] != variants['candidate'][n]},
                         set(self.old))
        for name in (image.ARENA_PATH, image.UPLOAD_POLICY_PATH, 'Cargo.toml'):
            self.assertEqual(variants['baseline'][name], variants['candidate'][name])
        variants['candidate']['Cargo.toml'] = b'local change'
        self.assertEqual((self.production, self.old), before)
        metadata = image.experiment_metadata('authored-dedup')
        self.assertEqual(metadata['baseline_loader_origin'], image.LOADER_BASELINE_COMMIT)
        self.assertEqual(metadata['baseline_loader_sha256'], image.hashes(self.old))
        self.assertEqual(metadata['overlay_paths'], sorted(self.old))
        self.assertEqual(metadata['upload_policies'], dict.fromkeys(('baseline', 'candidate'), 'bounded_reuse_v1'))
        self.assertFalse(metadata['baseline_is_four_file_counterfactual'])

    def test_closed_candidate_inventory_rejects_missing_extra_and_mutated_inputs(self):
        for mutated in ({**self.production, image.ARENA_PATH: b'other serializer'},
                        {**self.production, 'src/extra.rs': b'unknown'},
                        {n: v for n, v in self.production.items() if n != 'Cargo.toml'}):
            with self.subTest(mutated=mutated), self.assertRaisesRegex(ValueError, 'compile inventory'):
                image.loader_production_pair(mutated, self.old)

    def test_historical_loader_overlay_is_exact_and_cannot_include_another_experiment(self):
        key = next(iter(self.old))
        for mutated in ({}, {key: self.old[key]}, {**self.old, key: b'wrong baseline'},
                        {**self.old, image.ARENA_PATH: b'old serializer'},
                        {**self.old, image.UPLOAD_POLICY_PATH: image.UPLOAD_POLICY_DISABLED}):
            with self.subTest(mutated=mutated), self.assertRaisesRegex(ValueError, 'baseline loaders'):
                image.loader_production_pair(self.production, mutated)

    def test_rebound_candidate_still_requires_both_changed_loaders_and_enabled_policy(self):
        key = next(iter(self.old))
        for replacement in (None, b'', image.UPLOAD_POLICY_DISABLED, image.UPLOAD_POLICY_ENABLED * 2,
                            image.UPLOAD_POLICY_ENABLED + image.UPLOAD_POLICY_DISABLED):
            changed = self.production.copy()
            if replacement is None:
                changed.pop(image.UPLOAD_POLICY_PATH)
            else:
                changed[image.UPLOAD_POLICY_PATH] = replacement
            with self.subTest(policy=replacement), patch.object(image, 'PRODUCTION_MANIFEST',
                    matrix.canonical_hash(image.hashes(changed))), self.assertRaisesRegex(ValueError, 'enabled upload reuse'):
                image.loader_production_pair(changed, self.old)
        for changed in ({**self.production, key: self.old[key]},
                        {n: v for n, v in self.production.items() if n != key}):
            with self.subTest(changed=changed), patch.object(image, 'PRODUCTION_MANIFEST',
                    matrix.canonical_hash(image.hashes(changed))), self.assertRaisesRegex(ValueError, 'exactly both loader'):
                image.loader_production_pair(changed, self.old)


class LoaderReportTests(unittest.TestCase):
    def test_complete_native_and_prepare_reports_bind_exact_source_and_revisits(self):
        for native in (True, False):
            value = report_fixture(native)
            self.assertIs(loader.validate_report(value, RECEIPT, native), value)
        old, new = report_fixture(), report_fixture(stored_vertices=3)
        new['source_receipt_sha256'] = 'c' * 64
        loader.validate_report(new, 'c' * 64)
        actual = loader.compare_reports(old, new)
        self.assertEqual(actual, {'baseline_stored_vertices': 132, 'candidate_stored_vertices': 66,
                                'reduced_vertices': 66, 'ordered_expanded_commands_equal': True, 'cases': 22})

    def test_source_mode_case_order_missing_duplicate_and_revisit_tampering_rejected(self):
        mutations = []
        for key, value in (('schema', 'other'), ('source_receipt_sha256', 'c' * 64), ('native_images', 1)):
            x = report_fixture();x[key] = value;mutations.append(x)
        for cases in (list(reversed(loader.CASE_NAMES)), loader.CASE_NAMES[:-1],
                      loader.CASE_NAMES[:-1] + [loader.CASE_NAMES[0]]):
            x = report_fixture();x['cases'] = [copy.deepcopy(x['cases'][loader.CASE_NAMES.index(n)]) for n in cases];mutations.append(x)
        x = report_fixture();x['cases'][3]['commands'][0]['expanded_sha256'] = 'd' * 64;mutations.append(x)
        for ordinal, x in enumerate(mutations):
            with self.subTest(mutation=ordinal), self.assertRaises(ValueError):
                loader.validate_report(x, RECEIPT)

    def test_invalid_counts_matrices_textures_and_blends_rejected(self):
        replacements = [('stored_vertices', True), ('stored_vertices', 0), ('stored_vertices', 7),
                        ('indices', 5), ('indices', 5001), ('expanded_sha256', 'A' * 64),
                        ('blend', 'Opaque'), ('model_bits', [0] * 15),
                        ('model_bits', [True] + IDENTITY[1:]), ('model_bits', [0x7fc00001] + IDENTITY[1:]),
                        ('model_bits', [0x7f800000] + IDENTITY[1:]),
                        ('texture', {'width': 2, 'height': 2}), ('texture', {**report_fixture()['cases'][0]['commands'][0]['texture'], 'wrap_y': 'Clamp'})]
        for key, value in replacements:
            x = report_fixture();x['cases'][0]['commands'][0][key] = value
            # Keep revisit honest so the specific malformed command is exercised.
            x['cases'][3]['commands'] = copy.deepcopy(x['cases'][0]['commands'])
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                loader.validate_report(x, RECEIPT)
        for value in ([0x7fc00001] + IDENTITY[1:], [0x7f800000] + IDENTITY[1:], [True] + IDENTITY[1:]):
            x = report_fixture();x['camera']['view_projection_bits'] = value
            with self.subTest(camera=value), self.assertRaises(ValueError):
                loader.validate_report(x, RECEIPT)

    def test_metadata_rejects_nonfinite_negative_and_contradictory_times_and_boolean_aliases(self):
        mutations = []
        for key in ('duration_bits', 'time_bits'):
            for value in (0x7fc00001, 0x7f800000, 0xbf800000):
                mutations.append((0, key, value))
        mutations += [(0, 'fraction_tenths', False), (0, 'cant_bits', False),
                      (0, 'time_bits', f32_bits(0.5)), (1, 'time_bits', f32_bits(1.5)),
                      (16, 'fixed_steps', False), (16, 'simulation_time_bits', 0x7ff0000000000000),
                      (16, 'simulation_time_bits', 0xbff0000000000000)]
        for index, key, value in mutations:
            x = report_fixture();x['cases'][index]['metadata'][key] = value
            with self.subTest(case=index, field=key, value=value), self.assertRaises(ValueError):
                loader.validate_report(x, RECEIPT)

    def test_each_clip_keeps_one_duration_and_name_and_manifest_time_matches_steps(self):
        mutations = []
        for field, value in (('clip', 'other_clip'), ('duration_bits', f32_bits(4.))):
            x = report_fixture();x['cases'][1]['metadata'][field] = value
            if field == 'duration_bits':x['cases'][1]['metadata']['time_bits'] = f32_bits(2.)
            mutations.append(x)
        x = report_fixture();x['cases'][16]['metadata']['simulation_time_bits'] = struct.unpack('<Q', struct.pack('<d', 1.))[0];mutations.append(x)
        x = report_fixture();x['cases'][17]['metadata']['simulation_time_bits'] = 0;mutations.append(x)
        for ordinal, x in enumerate(mutations):
            with self.subTest(mutation=ordinal), self.assertRaises(ValueError):
                loader.validate_report(x, RECEIPT)

    def test_expected_manifest_wip_notice_is_retained_bounded_and_stable(self):
        loader.validate_report(report_fixture(), RECEIPT)
        for value in (None, '', 'unexpected', 'Authored WIP: ' + 'x'*512,
                      'Authored WIP: changed during idle controller steps'):
            x=report_fixture();x['cases'][17]['metadata']['warning']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                loader.validate_report(x,RECEIPT)

    def test_source_oracle_requires_original_duplicates_and_consistent_integer_counts(self):
        for update in ({'old_vertices': 2}, {'deduplicated_vertices': 7}, {'indices': 5}, {'old_vertices': True}):
            x = report_fixture();x['source_counts']['ready']['skin'][0].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                loader.validate_report(x, RECEIPT)
        x = report_fixture()
        for groups in x['source_counts'].values():
            for rows in groups.values():
                for row in rows:row['deduplicated_vertices'] = row['old_vertices']
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            loader.validate_report(x, RECEIPT)

    def test_compare_rejects_changed_expanded_order_material_pose_camera_or_source_oracle(self):
        for field, value in (('expanded_sha256', 'd' * 64), ('indices', 3), ('blend', 'Opaque'),
                             ('model_bits', [0x40000000] + IDENTITY[1:]), ('texture', None)):
            old, new = report_fixture(), report_fixture(stored_vertices=3)
            new['cases'][0]['commands'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'ordered expanded'):
                loader.compare_reports(old, new)
        for kind in ('camera', 'source_counts', 'metadata', 'unchanged', 'increased'):
            old, new = report_fixture(), report_fixture(stored_vertices=3)
            if kind == 'camera':new['camera']['view_projection_bits'][0] = 0x40000000
            elif kind == 'source_counts':new['source_counts']['ready']['skin'][0]['old_vertices'] = 5
            elif kind == 'metadata':new['cases'][1]['metadata']['clip'] = 'other'
            elif kind == 'unchanged':new = copy.deepcopy(old)
            else:new['cases'][0]['commands'][0]['stored_vertices'] = 7
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                loader.compare_reports(old, new)


def commit_fixture(root):
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Loader Guard Test',
                    '-c', 'user.email=loader-guard@example.invalid', '-c', 'commit.gpgsign=false',
                    'commit', '-qm', 'Synthetic committed loader fixture'], check=True, capture_output=True)


class HistoricalLoaderWitnessTests(unittest.TestCase):
    # Reuse the existing narrow synthetic Git protocol, without running its tests twice.
    setUp = matrix_tests.SourceWitnessTests.setUp
    tearDown = matrix_tests.SourceWitnessTests.tearDown

    def test_dirty_and_committed_loader_changes_cannot_hide_in_17_file_witness(self):
        original_source = matrix.source_identity(self.repository)
        self.assertEqual(len(original_source['runtime_files_sha256']), 17)
        for name in matrix.LOADER_BASELINE:
            path = self.repository / name
            original = path.read_bytes()
            path.write_bytes(original + b'// unexpected loader change\n')
            with self.subTest(path=name, state='dirty'), self.assertRaisesRegex(ValueError, 'Uncommitted authored loader'):
                matrix.source_identity(self.repository)
            commit_fixture(self.repository)
            with self.subTest(path=name, state='committed'), self.assertRaisesRegex(ValueError, 'cannot fall back'):
                matrix.source_identity(self.repository)
            path.write_bytes(original)
            commit_fixture(self.repository)
            self.assertEqual(matrix.source_identity(self.repository)['runtime_files_sha256'],
                             original_source['runtime_files_sha256'])
        # Historical retained artifacts remain their original narrow inventory.
        restored = matrix.artifact_source(self.witness, self.digest)
        self.assertEqual(restored['runtime_files_sha256'], original_source['runtime_files_sha256'])
        self.assertTrue(set(matrix.LOADER_BASELINE).isdisjoint(restored['runtime_files_sha256']))

    def test_missing_or_unsafe_loader_cannot_fall_back_to_historical_pin(self):
        for name in matrix.LOADER_BASELINE:
            path = self.repository / name
            original = path.read_bytes()
            path.unlink()
            with self.subTest(path=name, state='missing'), self.assertRaisesRegex(ValueError, 'Missing/unsafe authored loader'):
                matrix.source_identity(self.repository)
            path.write_bytes(original)
            actual = Path.is_symlink
            with patch.object(Path, 'is_symlink', lambda p: p == path or actual(p)), \
                    self.subTest(path=name, state='unsafe'), self.assertRaisesRegex(ValueError, 'Missing/unsafe authored loader'):
                matrix.source_identity(self.repository)


class CurrentLoaderWitnessTests(unittest.TestCase):
    def checkout(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), 'config', 'core.autocrlf', 'false'], check=True, capture_output=True)
        current = Path(matrix.__file__).resolve().parents[1]
        for name in matrix.LOADER_SOURCE_PATHS:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((current / name).read_bytes())
        commit_fixture(root)
        return root

    def test_actual_37_file_current_bytes_and_retained_witness_roundtrip(self):
        root = self.checkout()
        source = matrix.source_identity(root)
        self.assertEqual(len(source['runtime_files_sha256']), 37)
        self.assertEqual(set(source['runtime_files_sha256']), set(matrix.LOADER_SOURCE_PATHS))
        self.assertEqual(matrix.canonical_hash(source['runtime_files_sha256']), matrix.AUDITED_AUTHORED_DEDUP_MANIFEST)
        self.assertEqual(matrix.audited_inventory(matrix.AUDITED_AUTHORED_DEDUP_MANIFEST), matrix.LOADER_SOURCE_PATHS)
        output = root / 'witness'
        digest = matrix.export_witness(root, output)
        with patch.object(matrix.subprocess, 'check_output', side_effect=AssertionError('artifact replay cannot use Git')):
            self.assertEqual(matrix.artifact_source(output, digest), source)
        value = matrix.json_read(output / 'SOURCE_WITNESS.json')
        name = next(iter(matrix.LOADER_BASELINE))
        (output / name).write_bytes((output / name).read_bytes() + b'// changed retained loader\n')
        value['source']['runtime_files_sha256'][name] = matrix.sha256(output / name)
        value['audited_runtime_manifest_sha256'] = matrix.canonical_hash(value['source']['runtime_files_sha256'])
        (output / 'SOURCE_WITNESS.json').write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            matrix.artifact_source(output, matrix.sha256(output / 'SOURCE_WITNESS.json'))


class LoaderOutputTests(unittest.TestCase):
    def test_original_corner_bytes_camera_and_native_images_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            report = report_fixture()
            root = write_outputs(Path(folder) / 'original', report)
            before = image.controls.source_manifest(root)
            evidence = loader.validate_outputs(root, loader.validate_report(report, RECEIPT))
            self.assertEqual(len(evidence), 22)
            self.assertTrue(all(row['foreground_pixels'] == 128 for row in evidence.values()))
            self.assertEqual(loader.compare_images(evidence, copy.deepcopy(evidence)), {'exact_rgba_pairs': 22, 'zero_tolerance': True})
            self.assertEqual(image.controls.source_manifest(root), before)

    def test_missing_extra_changed_or_appended_corner_bytes_and_camera_rejected(self):
        for mutation in ('missing', 'extra', 'changed', 'appended', 'camera', 'report'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                report = report_fixture(False);root = write_outputs(Path(folder) / 'original', report)
                path = root / 'ready-0.corners.bin'
                if mutation == 'missing':path.unlink()
                elif mutation == 'extra':(root / 'unreported.bin').write_bytes(b'extra')
                elif mutation == 'changed':path.write_bytes(b'X' + path.read_bytes()[1:])
                elif mutation == 'appended':path.write_bytes(path.read_bytes() + b'x')
                elif mutation == 'camera':(root / 'camera.json').write_text(json.dumps({'substituted': True}))
                else:
                    changed = copy.deepcopy(report);changed['scope'] = 'mutated after validation'
                    (root / 'report.json').write_text(json.dumps(changed))
                with self.assertRaises(ValueError):loader.validate_outputs(root, report)

    def test_multiple_ordered_command_hashes_bind_their_exact_byte_ranges(self):
        with tempfile.TemporaryDirectory() as folder:
            report = report_fixture(False)
            root = write_outputs(Path(folder) / 'original', report)
            for case in report['cases']:
                second = copy.deepcopy(case['commands'][0])
                second['texture'] = None
                second['expanded_sha256'] = image.controls.digest(corner_bytes(17))
                case['commands'].append(second)
                path = root / (case['name'] + '.corners.bin')
                path.write_bytes(path.read_bytes() + corner_bytes(17))
            (root / 'report.json').write_text(json.dumps(report))
            self.assertEqual(loader.validate_outputs(root, loader.validate_report(report, RECEIPT, False)), {})
            path = root / 'ready-0.corners.bin'
            raw = path.read_bytes()
            for mutated in (raw[:-1] + bytes([raw[-1] ^ 1]), raw[len(raw)//2:] + raw[:len(raw)//2]):
                path.write_bytes(mutated)
                with self.assertRaisesRegex(ValueError, 'corner bytes'):
                    loader.validate_outputs(root, report)

    def test_native_image_format_opacity_empty_size_and_material_variation_are_required(self):
        for mutation in ('rgb', 'extent', 'alpha', 'empty', 'tiny', 'flat'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                report = report_fixture();root = write_outputs(Path(folder) / 'original', report)
                path = root / 'ready-0.png'
                pixels = Image.open(path).copy()
                if mutation == 'rgb':pixels = pixels.convert('RGB')
                elif mutation == 'extent':pixels = pixels.resize((480, 270))
                elif mutation == 'alpha':pixels.putpixel((0, 0), (32, 64, 96, 254))
                else:
                    pixels = Image.new('RGBA', tuple(loader.EXTENT), (8, 16, 24, 255))
                    for i in range(99 if mutation == 'tiny' else 128 if mutation == 'flat' else 0):
                        pixels.putpixel((i, 0), (32 + (0 if mutation == 'flat' else i % 8), 64, 96, 255))
                pixels.save(path)
                with self.assertRaises(ValueError):loader.validate_outputs(root, report)

    def test_exact_image_evidence_cannot_hide_changed_rgba_coverage_or_missing_case(self):
        original = {name: {'rgba_sha256': 'd' * 64, 'foreground_pixels': 128} for name in loader.CASE_NAMES}
        for mutation in ('rgba', 'coverage', 'missing'):
            changed = copy.deepcopy(original)
            if mutation == 'missing':changed.pop(loader.CASE_NAMES[-1])
            else:changed['ready-0']['rgba_sha256' if mutation == 'rgba' else 'foreground_pixels'] = 'e' * 64 if mutation == 'rgba' else 129
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):loader.compare_images(original, changed)


class LoaderProfileFlowTests(unittest.TestCase):
    flow = geometry_tests.GeometryProfilePairTests.flow

    def test_explicit_loader_selection_preserves_historical_profile_defaults(self):
        for mode, experiment in (('compare-loaders', 'authored-dedup'),
                                 ('compare-serialization', 'arena-serialization'),
                                 ('compare-uploads', 'geometry-reuse')):
            with self.subTest(mode=mode), patch.object(profile, 'compare_uploads') as compare:
                self.assertEqual(profile.main([mode, '--root', '.', '--output', 'synthetic']), 0)
                compare.assert_called_once_with(Path('.'), Path('synthetic'), experiment)
        self.assertEqual(profile.compare_uploads.__defaults__, ('geometry-reuse',))

    def test_two_fresh_builds_and_abba_change_only_loaders_with_reuse_and_serializer_retained(self):
        self.flow(experiment='authored-dedup')
        output = self.last['output']
        self.assertEqual(self.last['events'], [('build', 'baseline'), ('build', 'candidate'),
                         ('sample', 'baseline'), ('sample', 'candidate'), ('sample', 'candidate'), ('sample', 'baseline')])
        variants = {label: image.controls.source_manifest(output / ('sources/' + label + '-source'))
                    for label in ('baseline', 'candidate')}
        self.assertEqual({name for name in variants['baseline']
                          if variants['baseline'][name] != variants['candidate'][name]}, set(image.LOADER_BASELINE))
        for name in (image.ARENA_PATH, image.UPLOAD_POLICY_PATH):
            self.assertEqual(variants['baseline'][name], variants['candidate'][name])
        summary = matrix.json_read(output / 'pair-summary.json')
        self.assertTrue(summary['passed'])
        self.assertEqual(summary['experiment'], 'authored-dedup')
        self.assertEqual(summary['diagnostic_runs_complete'], 4)
        self.assertIsNone(summary['performance_improvement'])
        self.assertFalse(summary['target_1080p60_proven'])
        self.assertTrue(all(row['measurements']['upload_policy'] == 'bounded_reuse_v1' for row in summary['runs']))
        self.assertEqual(matrix.json_read(output / 'pair-inputs.json')['experiment'], 'authored-dedup')
        for label in ('baseline', 'candidate'):
            source = output / ('sources/' + label + '-source.json')
            receipt = matrix.json_read(source)
            build = matrix.json_read(output / (label + '-build/build.json'))
            self.assertEqual(build['source_receipt_sha256'], matrix.sha256(source))
            self.assertEqual(build['compiled_files_sha256'], receipt['files_sha256'])
            self.assertEqual(receipt['overlay_paths'], sorted(image.LOADER_BASELINE))
            self.assertEqual(receipt['upload_policies'], dict.fromkeys(('baseline', 'candidate'), 'bounded_reuse_v1'))

    def test_new_profile_selection_retains_source_policy_and_previous_capture_guards(self):
        for mutation in ('policy', 'compiled_source', 'prior_pdb', 'source_receipt', 'assets',
                         'prior_record', 'prior_report', 'device', 'final_checks'):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.flow(mutation=mutation, experiment='authored-dedup')
            self.assertTrue((self.last['output'] / 'pair-failure.json').is_file())
            self.assertFalse((self.last['output'] / 'pair-summary.json').exists())


if __name__ == '__main__':
    unittest.main()
