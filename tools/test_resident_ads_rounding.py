"""Independent source/pixel protocol tests; synthetic images are not native proof."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import run_resident_ads_rounding as rounding
from test_capture_frame_witness import marker


def production_fixture():
    return {'Cargo.toml': b'synthetic closed input',
            'src/main.rs': b'synthetic original source',
            rounding.POLICY: b'pub const ENABLED: bool = true;\n',
            'src/frame_staging_policy.rs': b'pub const ENABLED: bool = true;\n'}


class ResidentAdsSourceTests(unittest.TestCase):
    def test_exact_closed_pair_changes_only_resident_boolean(self):
        production = production_fixture()
        original = copy.deepcopy(production)
        digest = rounding.matrix.canonical_hash(rounding.pair.hashes(production))
        with patch.object(rounding, 'PRODUCTION_MANIFEST', digest):
            result = rounding.source_pair(production)
        self.assertEqual(set(result), {'resident-off', 'resident-on'})
        self.assertEqual(result['resident-on'], original)
        self.assertEqual(production, original)
        self.assertEqual([p for p in original if result['resident-off'][p] != original[p]], [rounding.POLICY])
        self.assertEqual(result['resident-off'][rounding.POLICY], b'pub const ENABLED: bool = false;\n')
        self.assertEqual(result['resident-off']['src/frame_staging_policy.rs'], original['src/frame_staging_policy.rs'])
        self.assertIsNot(result['resident-on'], production)

    def test_added_removed_and_changed_compile_inputs_fail_closed(self):
        production = production_fixture()
        digest = rounding.matrix.canonical_hash(rounding.pair.hashes(production))
        variants = [{**production, 'src/extra.rs': b'extra'},
                    {p: v for p, v in production.items() if p != 'Cargo.toml'}]
        variants.extend({**production, p: v + b'changed'} for p, v in production.items())
        variants.append({**production, 'src/frame_staging_policy.rs': b'pub const ENABLED: bool = false;\n'})
        with patch.object(rounding, 'PRODUCTION_MANIFEST', digest):
            for changed in variants:
                with self.subTest(paths=list(changed)), self.assertRaisesRegex(ValueError, 'closed production'):
                    rounding.source_pair(changed)

    def test_policy_guard_is_not_replaced_by_a_matching_inventory_hash(self):
        for policy in (b'pub const ENABLED: bool = false;', b'no policy',
                       b'ENABLED: bool = true; ENABLED: bool = true;',
                       b'ENABLED: bool = true; ENABLED: bool = false;'):
            production = {**production_fixture(), rounding.POLICY: policy}
            digest = rounding.matrix.canonical_hash(rounding.pair.hashes(production))
            with self.subTest(policy=policy), patch.object(rounding, 'PRODUCTION_MANIFEST', digest), \
                    self.assertRaisesRegex(ValueError, 'candidate policy'):
                rounding.source_pair(production)

    def test_declared_native_frame_count_and_release_build_are_explicit(self):
        self.assertEqual(rounding.FRAMES, 553)
        self.assertEqual(rounding.authored.EXTENT, (960, 540))
        self.assertEqual(rounding.BUILD, ['cargo', 'build', '--locked', '--release',
                         '--no-default-features', '--features', 'wgpu-runtime', '--bin', 'vector-range'])


class ResidentAdsPixelTests(unittest.TestCase):
    def test_all_channels_count_once_per_pixel_without_a_tolerance(self):
        before = Image.new('RGBA', (3, 2), (10, 20, 30, 255))
        after = before.copy()
        after.putpixel((0, 0), (11, 18, 33, 255))
        after.putpixel((1, 0), (10, 20, 30, 0))
        self.assertEqual(rounding.pixel_metrics(before, after), {
            'differing_pixels': 2, 'maximum_channel_delta': 255,
            'absolute_channel_delta': 261, 'alpha_differing_pixels': 1})
        self.assertEqual(rounding.pixel_metrics(before, before.copy()), {
            'differing_pixels': 0, 'maximum_channel_delta': 0,
            'absolute_channel_delta': 0, 'alpha_differing_pixels': 0})

    def test_pixel_formats_and_dimensions_must_match(self):
        rgba = Image.new('RGBA', (2, 2))
        for other in (Image.new('RGB', (2, 2)), Image.new('RGBA', (3, 2))):
            with self.subTest(mode=other.mode, size=other.size), self.assertRaisesRegex(ValueError, 'formats/extents'):
                rounding.pixel_metrics(rgba, other)


class ResidentAdsSequenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.before, self.after = self.root / 'off', self.root / 'on'
        self.identities = []
        for folder, executable in ((self.before, 'a' * 64), (self.after, 'b' * 64)):
            folder.mkdir()
            identity = rounding.witness.capture_identity({
                'source_commit': '1' * 40, 'exe_sha256': executable,
                'run_id': '42', 'run_attempt': '1', 'scenario': 'ads-offset', 'backend': 'Dx12'})
            self.identities.append(identity)
            for index in range(3):
                image = Image.new('RGBA', rounding.authored.EXTENT, rounding.authored.BACKGROUND)
                if index:
                    ImageDraw.Draw(image).rectangle((200, 100, 700, 420), fill=(120, 90, 60, 255))
                image.paste(marker(index, identity).crop((0, 0, 64, 22)), (0, 0))
                image.save(folder / f'{index:04}.png')
                metadata = {'backend': 'Dx12', 'adapter': rounding.authored.WARP,
                            'requested': 'dx12', 'width': 960, 'height': 540,
                            'frame_witness': {'schema': 'rust-duty-capture-frame-witness/v1',
                                              'frame_index': index, 'capture_identity': identity},
                            'hfov_degrees': 90.0}
                for suffix, record in (('.json', metadata),
                        ('.time.json', {'elapsed_seconds': index / 60, 'sampling_hz': 60}),
                        ('.gameplay.json', {'simulation_time': index / 60, 'route': 'ready',
                         'simulation_ads': 0, 'renderer_failed': False, 'ammo': 12})):
                    rounding.matrix.write_json(folder / f'{index:04}.png{suffix}', record)

    def compare(self):
        # Keep the real readers/witness decoder and native image extent. Only
        # shrink the fixed native sequence length for inexpensive negative cases.
        with patch.object(rounding, 'FRAMES', 3):
            return rounding.compare_sequences(self.before, self.after, *self.identities)

    def inventory(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_verified_marker_only_frame_remains_a_failed_original_visibility_gate(self):
        original = self.inventory()
        result = self.compare()
        self.assertIs(result['diagnostic_completed'], True)
        self.assertIs(result['visibility_gate_passed'], False)
        self.assertNotIn('passed', result)
        self.assertEqual(result['differing_pixels'], 0)
        self.assertEqual(result['differing_frames'], 0)
        self.assertEqual(result['per_frame'][0]['scene_foreground_pixels'], [0, 0])
        for label in rounding.LABELS:
            visibility = result['visibility'][label]
            self.assertEqual([r['passed'] for r in visibility['visibility']], [False, True, True])
            self.assertIn('foreground coverage 0.002716 below 0.010000', visibility['visibility'][0]['error'])
        self.assertEqual(result['telemetry']['gameplay_files'], 3)
        self.assertEqual(result['telemetry']['time_files'], 3)
        self.assertEqual(self.inventory(), original)

    def test_pixels_just_outside_marker_are_never_masked_or_accepted_by_tolerance(self):
        path = self.after / '0001.png'
        with Image.open(path) as stored:
            image = stored.convert('RGBA')
        image.putpixel((64, 21), (37, 48, 61, 255))
        image.putpixel((0, 22), (36, 48, 255, 255))
        image.save(path)
        result = self.compare()
        self.assertEqual(result['differing_frames'], 1)
        self.assertEqual(result['differing_pixels'], 2)
        self.assertEqual(result['maximum_channel_delta'], 194)
        self.assertEqual(result['absolute_channel_delta'], 195)
        self.assertEqual(result['alpha_differing_pixels'], 0)
        self.assertIs(result['visibility_gate_passed'], False)

    def test_nonopaque_scene_pixel_still_fails_original_witness_contract(self):
        path = self.after / '0001.png'
        with Image.open(path) as stored:
            image = stored.convert('RGBA')
        image.putpixel((100, 100), (36, 48, 61, 0)); image.save(path)
        with self.assertRaisesRegex(ValueError, 'alpha must be 255 everywhere'):
            self.compare()

    def test_incomplete_native_count_is_rejected_without_test_count_override(self):
        with self.assertRaisesRegex(ValueError, '553-frame inventory'):
            rounding.validate_sequence(self.before, self.identities[0])

    def test_missing_or_extra_file_and_directory_fail_before_pixel_comparison(self):
        for suffix in ('', '.json', '.time.json', '.gameplay.json'):
            path = self.after / ('0001.png' + suffix)
            raw = path.read_bytes(); path.unlink()
            try:
                with self.subTest(missing=suffix), self.assertRaisesRegex(ValueError, 'inventory'):
                    self.compare()
            finally: path.write_bytes(raw)
        for name, directory in (('verification.json', False), ('unbound.txt', False), ('unbound-dir', True)):
            path = self.after / name
            path.mkdir() if directory else path.write_bytes(b'{}')
            try:
                with self.subTest(extra=name), self.assertRaisesRegex(ValueError, 'inventory'):
                    self.compare()
            finally: path.rmdir() if directory else path.unlink()

    def test_stale_or_wrong_identity_marker_is_checked_before_exclusion(self):
        path = self.after / '0001.png'
        original = path.read_bytes()
        for index, identity in ((0, self.identities[1]), (1, self.identities[0])):
            with Image.open(path) as stored:
                image = stored.convert('RGBA')
            image.paste(marker(index, identity).crop((0, 0, 64, 22)), (0, 0)); image.save(path)
            try:
                with self.subTest(index=index, identity=identity), \
                        patch.object(rounding, 'pixel_metrics', side_effect=AssertionError('masking reached')) as metrics, \
                        self.assertRaises(ValueError): self.compare()
                metrics.assert_not_called()
            finally: path.write_bytes(original)

    def test_wrong_backend_adapter_extent_or_witness_metadata_is_rejected(self):
        path = self.after / '0001.png.json'; raw = path.read_bytes(); record = json.loads(raw)
        for field, value in (('backend', 'OpenGl'), ('requested', 'auto'), ('adapter', 'NVIDIA'),
                             ('width', 1920), ('height', True), ('frame_witness', {})):
            try:
                path.write_bytes(json.dumps({**record, field: value}, allow_nan=False).encode('utf-8'))
                with self.subTest(field=field), self.assertRaises(ValueError): self.compare()
            finally: path.write_bytes(raw)

    def test_all_gameplay_time_and_non_identity_primary_fields_still_join_exactly(self):
        for suffix, field, value in (('.gameplay.json', 'ammo', 11), ('.time.json', 'sampling_hz', 30),
                                     ('.json', 'hfov_degrees', 91)):
            path = self.after / ('0001.png' + suffix); raw = path.read_bytes(); record = json.loads(raw)
            try:
                path.write_bytes(json.dumps({**record, field: value}, allow_nan=False).encode('utf-8'))
                with self.subTest(field=field), self.assertRaises(ValueError): self.compare()
            finally: path.write_bytes(raw)

    def test_duplicate_or_nonfinite_telemetry_is_never_diagnostic_success(self):
        path = self.after / '0001.png.time.json'; raw = path.read_bytes()
        for invalid in (b'{"elapsed_seconds":0,"elapsed_seconds":0}', b'{"elapsed_seconds":NaN}', b'{"elapsed_seconds":1e9999}'):
            try:
                path.write_bytes(invalid)
                with self.subTest(raw=invalid), self.assertRaises(ValueError): self.compare()
            finally: path.write_bytes(raw)


class ResidentAdsDeviceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.logs = Path(temporary.name)
        (self.logs / 'stdout.log').write_bytes(b'')
        self.record = {'backend': 'Dx12', 'device_type': 'Cpu', 'name': rounding.authored.WARP,
                       'force_fallback_requested': True, 'present_mode': 'Fifo',
                       'gpu_timestamps_requested': False, 'gpu_timestamp_features_enabled': False,
                       'instance_descriptor': {'schema': 'rust-duty-wgpu-instance-descriptor/v1',
                                               'wgpu_version': '30.0.1', 'flags_bits': 32,
                                               'debug': False, 'validation': False,
                                               'gpu_based_validation': False, 'validation_indirect_call': True,
                                               'application_debug_assertions': False,
                                               'environment_overrides_applied': False}}

    def write(self, raw=None):
        raw = json.dumps(self.record) if raw is None else raw
        text = f'renderer requested=dx12 backend=Dx12 adapter={rounding.authored.WARP}\n'
        text += rounding.authored.FXC_LOG + '\nrenderer graphics_device_evidence=' + raw + '\n'
        (self.logs / 'stderr.log').write_text(text, encoding='utf-8')

    def test_actual_warp_release_descriptor_is_required(self):
        self.write(); self.assertEqual(rounding.device_evidence(self.logs), self.record)
        original = copy.deepcopy(self.record)
        for field, value in (('backend', 'Vulkan'), ('device_type', 'DiscreteGpu'), ('name', 'NVIDIA'),
                             ('force_fallback_requested', False), ('present_mode', 'Immediate'),
                             ('gpu_timestamps_requested', True), ('gpu_timestamp_features_enabled', True)):
            self.record = {**original, field: value}; self.write()
            with self.subTest(field=field), self.assertRaises(ValueError): rounding.device_evidence(self.logs)
        for field, value in (('flags_bits', 0), ('application_debug_assertions', True), ('environment_overrides_applied', True)):
            self.record = {**original, 'instance_descriptor': {**original['instance_descriptor'], field: value}}; self.write()
            with self.subTest(field=field), self.assertRaises(ValueError): rounding.device_evidence(self.logs)

    def test_duplicate_device_keys_and_nonfinite_extensions_are_rejected(self):
        valid = json.dumps(self.record)
        for raw in ('{"backend":"Vulkan",' + valid[1:], '{"extra":NaN,' + valid[1:]):
            self.write(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError): rounding.device_evidence(self.logs)

    def test_instance_descriptor_types_schema_and_flag_bits_are_consistent(self):
        original = copy.deepcopy(self.record)
        for field, value in (('flags_bits', 32.0), ('debug', True), ('validation_indirect_call', False),
                             ('gpu_based_validation', 0), ('wgpu_version', '0.0.0'), ('schema', 'unknown')):
            self.record = {**original, 'instance_descriptor': {**original['instance_descriptor'], field: value}}
            self.write()
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                rounding.device_evidence(self.logs)

    def test_ambiguous_multiple_actual_device_records_are_rejected(self):
        self.write()
        with (self.logs / 'stderr.log').open('a', encoding='utf-8') as stream:
            stream.write('renderer graphics_device_evidence=' + json.dumps(self.record) + '\n')
        with self.assertRaisesRegex(ValueError, 'one actual graphics device'):
            rounding.device_evidence(self.logs)


if __name__ == '__main__':
    unittest.main()
