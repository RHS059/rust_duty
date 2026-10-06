"""Synthetic guard tests only; no fixture can establish native execution/review."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_graphics_cpu_contract as runner


class SourceAndProviderTests(unittest.TestCase):
    def test_exact_source_delta_rejects_extra_missing_and_unchanged_members(self):
        baseline = {name: b'old:' + name.encode() for name in runner.CHANGED - runner.ADDED}
        baseline['Cargo.lock'] = b'unchanged'
        candidate = {name: b'new:' + name.encode() for name in runner.CHANGED}
        candidate['Cargo.lock'] = b'unchanged'
        runner.source_pair(baseline, candidate)
        for mutate in (lambda c: c.update({'Cargo.lock': b'changed'}),
                       lambda c: c.update({'src/extra.rs': b'extra'}),
                       lambda c: c.pop('src/graphics_device.rs'),
                       lambda c: c.update({'src/main.rs': baseline['src/main.rs']})):
            altered = dict(candidate); mutate(altered)
            with self.assertRaises(ValueError): runner.source_pair(baseline, altered)

    def test_current_checkout_cannot_silently_test_the_old_pin(self):
        expected = {'src/a.rs': b'current'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'src').mkdir()
            (root / 'src/a.rs').write_bytes(b'current')
            runner.current_checkout(root, expected)
            (root / 'src/a.rs').write_bytes(b'stale')
            with self.assertRaisesRegex(ValueError, 'declared ebf'): runner.current_checkout(root, expected)
            (root / 'src/a.rs').write_bytes(b'current')
            (root / 'src/extra.rs').write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError, 'extra'): runner.current_checkout(root, expected)

    def test_exact_fixture_repair_retains_current_and_compiled_source_identities(self):
        name = 'src/asset_path.rs'
        repaired = (Path(__file__).resolve().parents[1] / name).read_bytes()
        original = runner.finite_source._asset_path_test_base(repaired)
        pins = runner.finite_source.ASSET_PATH_TEST_FIX
        expected = {name: original}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / name; path.parent.mkdir()
            path.write_bytes(original)
            unchanged = runner.current_checkout(root, expected)
            self.assertEqual(unchanged, {'files': {name: pins['before']}, 'test_only_equivalences': {}})
            path.write_bytes(repaired)
            actual = runner.current_checkout(root, expected)
            self.assertEqual(actual, {'files': {name: pins['after']}, 'test_only_equivalences': {
                name: {'current_checkout': pins['after'], 'compiled_source': pins['before']}}})
            retained = root / 'retained'
            runner.archive_input(root, retained, actual['test_only_equivalences'])
            self.assertEqual((retained / name).read_bytes(), repaired)
            self.assertEqual(expected[name], original)
            self.assertNotEqual(repaired, original)

    def test_fixture_repair_mapping_rejects_mutated_or_renamed_source(self):
        name = 'src/asset_path.rs'
        repaired = (Path(__file__).resolve().parents[1] / name).read_bytes()
        original = runner.finite_source._asset_path_test_base(repaired)
        mutations = (
            repaired.replace(b'return WeaponSource::Procedural;', b'return WeaponSource::Embedded;'),
            repaired.replace(b'#[cfg(test)]', b'#[cfg(not(test))]'),
            repaired.replace(b'NEXT_TEMP_ID', b'OTHER_TEMP_ID'),
            repaired.replace(b'fn locomotion_pack_is_discovered', b'fn changed_locomotion_pack_is_discovered'),
            repaired.replace(b'\n', b'\r\n'),
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / name; path.parent.mkdir()
            for changed in mutations:
                self.assertNotEqual(changed, repaired)
                path.write_bytes(changed)
                with self.subTest(source=runner.shared.digest(changed)), self.assertRaisesRegex(ValueError, 'declared ebf'):
                    runner.current_checkout(root, {name: original})
            path.write_bytes(repaired)
            with self.assertRaisesRegex(ValueError, 'declared ebf'):
                runner.current_checkout(root, {name: original + b'changed'})
            other = 'src/other.rs'; path.rename(root / other)
            with self.assertRaisesRegex(ValueError, 'declared ebf'):
                runner.current_checkout(root, {other: original})

    def test_provider_is_exact_and_cannot_substitute_artifact_or_run(self):
        value = {'id': runner.BASELINE_ARTIFACT, 'name': 'pass-submission-full-attempt-1',
                 'size_in_bytes': 15858877, 'digest': 'sha256:' + runner.BASELINE_ARCHIVE_SHA256, 'expired': False,
                 'workflow_run': {'id': runner.BASELINE_RUN, 'head_sha': '4c116be39e426f38f65772ae83ce539891a54e55',
                    'head_branch': 'main', 'repository_id': 1398577887, 'head_repository_id': 1398577887}}
        runner.baseline_provider(value)
        for key, changed in [('id', 1), ('expired', True), ('expired', 0), ('digest', 'sha256:' + '0'*64),
                             ('size_in_bytes', 1), ('name', 'other')]:
            altered = deepcopy(value); altered[key] = changed
            with self.assertRaises(ValueError): runner.baseline_provider(altered)
        for key in value['workflow_run']:
            altered = deepcopy(value); altered['workflow_run'][key] = 'changed'
            with self.assertRaises(ValueError): runner.baseline_provider(altered)

    def test_baseline_review_requires_independent_digest_before_other_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); review = root / 'review.json'; review.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'review anchor'):
                runner.verified_baseline(root, review, {})

    def test_historical_runner_uses_pinned_candidate_not_current_checkout(self):
        shared = runner.shared
        candidate = {name: b'new' for name in shared.ALLOWED}
        baseline = {name: b'old' for name in shared.ALLOWED}
        pins = {name: shared.digest(raw) for name, raw in candidate.items()}
        with patch.object(shared, 'pinned_source', return_value=candidate) as source, patch.object(shared, 'CANDIDATE_HASHES', pins):
            self.assertEqual(shared.historical_candidate_sources(Path('repository'), baseline), candidate)
            source.assert_called_once_with(Path('repository'), shared.CANDIDATE)
            altered = dict(candidate); altered['unreviewed'] = b'new'
            source.return_value = altered
            with self.assertRaisesRegex(ValueError, 'inventories'):
                shared.historical_candidate_sources(Path('repository'), baseline)


class NativeControlGuardTests(unittest.TestCase):
    def report(self):
        return {'schema': 'rust-duty-graphics-cpu-contract/v1', 'mode': 'windowed-saved', 'status': 'passed',
                'source_commit': runner.CANDIDATE_SOURCE, 'source_sha': 'a'*64, 'compiled_source_sha256': 'a'*64,
                'platform': 'windows', 'pid': 1, 'build_label': 'synthetic', 'build_version': 'synthetic', 'build_number': 'synthetic'}

    def test_native_report_is_bound_to_compiled_source_and_original_success(self):
        value = self.report(); runner.control_report(value, 'windowed-saved', 'a'*64)
        for field, altered in [('status', 'failed'), ('platform', 'linux'), ('compiled_source_sha256', 'b'*64),
                                ('source_sha', 'b'*64), ('source_commit', runner.BASELINE_SOURCE), ('pid', True),
                                ('mode', 'seed'), ('build_number', ''), ('error', 'failure')]:
            wrong = dict(value); wrong[field] = altered
            with self.assertRaises(ValueError): runner.control_report(wrong, 'windowed-saved', 'a'*64)

    def test_device_evidence_requires_actual_count_compiler_and_stable_device(self):
        narrow = {'device_type': 'Cpu', 'vendor_id': 5140, 'device_id': 140,
                  'driver': 'synthetic', 'driver_info': '', 'present_mode': None, 'force_fallback_requested': True}
        rich = {**narrow, 'name': 'Microsoft Basic Render Driver', 'backend': 'Dx12'}
        def log(n=narrow, r=rich):
            return ('renderer device_evidence=' + json.dumps(n) + '\nrenderer graphics_device_evidence=' + json.dumps(r)
                    + '\nrenderer dx12_shader_compiler=Fxc\n')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native.log'; path.write_text(log())
            self.assertEqual(runner.actual_devices(path, 1, narrow), [rich])
            for data in [log()*2, log().replace('=Fxc', '=Dxc'), log(r={**rich, 'driver': 'other'}),
                         log(r={**rich, 'device_type': 'DiscreteGpu'}), log(r={**rich, 'backend': 'Vulkan'})]:
                path.write_text(data)
                with self.assertRaises(ValueError): runner.actual_devices(path, 1, narrow)

    def test_preference_bytes_must_match_unchanged_retained_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'preference.json'
            raw = b'{"schema":"rust-duty-graphics-device/v1","adapter":{"name":"synthetic"}}'
            path.write_bytes(raw)
            value = {'length': len(raw), 'bytes': list(raw), 'utf8': raw.decode()}
            self.assertEqual(runner.preference_evidence(value, path), {'name': 'synthetic'})
            path.write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, 'bytes differ'): runner.preference_evidence(value, path)

    def test_pixels_need_fixed_colors_and_opaque_display_alpha(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native.png'
            image = Image.new('RGBA', (320, 180), (0, 0, 0, 255))
            for x, rgba in [(24, (255,0,0,255)), (80, (0,255,0,255)), (136, (0,0,255,255))]: image.putpixel((x,24), rgba)
            image.save(path); runner.synthetic_pixels(path, (320, 180))
            image.putpixel((24,24), (0,255,0,255)); image.save(path)
            with self.assertRaisesRegex(ValueError, 'expectation'): runner.synthetic_pixels(path)
            image.putpixel((24,24), (255,0,0,255)); image.putpixel((0,0), (0,0,0,0)); image.save(path)
            with self.assertRaisesRegex(ValueError, 'nonopaque'): runner.synthetic_pixels(path)

    def test_json_duplicate_and_nonfinite_cannot_hide_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            for text in ['{"status":"failed","status":"passed"}', '{"x":NaN}']:
                path.write_text(text)
                with self.assertRaises(ValueError): runner.read_json(path)

if __name__ == '__main__':
    unittest.main()
