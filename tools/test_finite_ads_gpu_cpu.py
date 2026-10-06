"""Disabled class controls. Synthetic fixtures never grant native review."""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import finite_ads_profile_binding as f
import test_finite_ads_profile_binding as original_tests

encoded = original_tests.encoded


class CoherentVariantTests(original_tests.ProfileTests):
    """Repeat the original packet boundary controls with one coherent variant."""
    def setUp(self):
        super().setUp()
        names = list(f.GPU_CPU_VARIANTS['baseline']['production'])
        self.files = {label: {name: ((('' if label == 'baseline' else 'candidate/') + name + '\n').encode()
                    if name != 'src/graphics_device.rs' or label == 'candidate' else None)
                    for name in names} for label in ('baseline', 'candidate')}
        variants = {}
        for label, files in self.files.items():
            production = {name: f._identity(raw) if raw is not None else None for name, raw in files.items()}
            files['src/render/mod.rs'] += f.preparation.MOD_SUFFIX
            variants[label] = {'production': production, 'reviewed_additions': {
                'src/render/mod.rs': f._identity(files['src/render/mod.rs'])}}
        self.addCleanup(patch.stopall)
        patch.object(f, 'GPU_CPU_VARIANTS', variants).start()
        plan = b'reviewed batching plan\n'
        pair = {'src/render/frame.rs': variants['baseline']['production']['src/render/frame.rs'],
                'src/render/plan.rs': f._identity(plan)}
        patch.object(f, 'PASS_BATCHING_PAIRS', {'baseline': {name: f._identity(b'prebatch/' + name.encode())
                                                          for name in pair}, 'candidate': pair}).start()
        for name, identity in variants['baseline']['production'].items():
            if identity is not None:
                self.descriptor['equivalence']['production'][name] = identity
        self.add_file('src/render/plan.rs', plan)
        self.descriptor['equivalence']['production']['src/render/plan.rs'] = f.PASS_BATCHING_PAIRS['baseline']['src/render/plan.rs']
        self.descriptor['equivalence']['reviewed_additions'] = deepcopy(variants['baseline']['reviewed_additions'])
        self.descriptor['_pass_batching'] = {'comparison': {}, 'sha256': 'a' * 64}
        self.descriptor['_gpu_cpu'] = {'synthetic_guard_fixture_only': True}
        self.select('candidate')

    def remove(self, name):
        self.packet['files'].pop(name, None)
        for key in ('inputs_and_implementation_before', 'inputs_and_implementation_after'):
            self.receipt[key].pop(name, None)

    def select(self, label):
        for name, raw in self.files[label].items():
            if raw is None:
                self.remove(name)
            else:
                self.add_file(name, raw)
        self.save()

    def test_pending_descriptor_and_self_refreshed_hash_rejected(self):
        self.descriptor.pop('_pass_batching')
        self.descriptor.pop('_gpu_cpu')
        super().test_pending_descriptor_and_self_refreshed_hash_rejected()

    def test_only_exact_verified_root_mapping_and_source_line_endings(self):
        for role in f.source.ROLES:
            self.bound.headers_by_role[role]['sources'][0]['vra'] = 'D:/later/source/assets/locomotion/asset.vra'
            for row in self.bound.rows_by_role[role]:
                row['companion_catalog_vra'] = 'D:/later/source/assets/locomotion/asset.vra'
        self.packet['recorded_root'] = 'D:/later/source'
        for name, raw in self.files['candidate'].items():
            self.add_file(name, raw.replace(b'\n', b'\r\n'))
        self.save(); self.bind_class()
        self.bound.rows_by_role['dx12'][0]['companion_catalog_vra'] = 'D:/outside/assets/locomotion/asset.vra'
        with self.assertRaisesRegex(ValueError, 'escapes verified'):
            self.bind_class()

    def test_lone_carriage_return_and_compiler_change_rejected(self):
        name = 'src/render/device.rs'
        self.add_file(name, self.files['candidate'][name] + b'\r')
        self.save()
        with self.assertRaisesRegex(ValueError, 'CRLF/LF'):
            self.bind_class()
        self.add_file(name, self.files['candidate'][name])
        self.add_file('compiler.txt', b'changed compiler')
        self.save()
        with self.assertRaisesRegex(ValueError, 'actual compiler bytes'):
            self.bind_class()

    def test_complete_variants_bind_and_all_4094_mixed_subsets_reject(self):
        for label in self.files:
            self.select(label); self.bind_class()
        names = list(self.files['baseline'])
        for bits in itertools.product((0, 1), repeat=len(names)):
            files = {name: self.files['candidate' if bit else 'baseline'][name]
                     for name, bit in zip(names, bits)}
            files = {name: raw for name, raw in files.items() if raw is not None}
            if all(bit == bits[0] for bit in bits):
                self.assertIsNotNone(f._gpu_cpu_variant(files.__getitem__, self.descriptor, set(files)))
            else:
                with self.assertRaisesRegex(ValueError, 'mixed or unreviewed'):
                    f._gpu_cpu_variant(files.__getitem__, self.descriptor, set(files))

    def test_missing_changed_member_and_added_or_missing_selector_reject(self):
        for name in self.files['candidate']:
            self.select('candidate'); self.remove(name); self.save()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.bind_class()
        self.select('baseline')
        self.add_file('src/graphics_device.rs', self.files['candidate']['src/graphics_device.rs'])
        self.save()
        with self.assertRaisesRegex(ValueError, 'mixed or unreviewed'):
            self.bind_class()

    def test_individually_refreshed_source_inventory_never_extends_variant(self):
        for name in self.files['candidate']:
            self.select('candidate')
            self.add_file(name, self.files['candidate'][name] + b'// candidate rewrite\n')
            self.save()
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.bind_class()

    def test_old_classes_do_not_accept_new_source_and_new_class_requires_batching_plan(self):
        self.descriptor.pop('_gpu_cpu')
        with self.assertRaisesRegex(ValueError, 'unreviewed production file'):
            self.bind_class()
        self.descriptor.pop('_pass_batching')
        with self.assertRaisesRegex(ValueError, 'unreviewed production file'):
            self.bind_class()
        self.descriptor['_gpu_cpu'] = {'synthetic_guard_fixture_only': True}
        self.add_file('src/render/plan.rs', b'prebatch/src/render/plan.rs')
        self.save()
        with self.assertRaisesRegex(ValueError, 'unreviewed additive/source'):
            self.bind_class()

    def test_mod_suffix_is_exact_optional_addition_not_a_second_production_hash(self):
        name = 'src/render/mod.rs'
        for label in self.files:
            self.select(label)
            self.bind_class()
            canonical = f._production_bytes(name, self.files[label][name])
            self.assertNotEqual(f._identity(canonical), f._identity(self.files[label][name]))
            self.add_file(name, canonical); self.save(); self.bind_class()
            for raw in (canonical + f.preparation.MOD_SUFFIX.replace(b'diagnostic', b'changed'),
                        canonical + f.preparation.MOD_SUFFIX * 2):
                self.add_file(name, raw); self.save()
                with self.assertRaises(ValueError):
                    self.bind_class()


class DisabledDescriptorTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).with_name('finite_ads_gpu_cpu_class.pending.json').absolute()
        self.descriptor = json.loads(self.path.read_bytes())

    def bind(self, path):
        return f.bind_finite_ads_profile(source_packet=None, source_packet_path=path,
            reviewed_class=path, expected_class_sha256=f._identity(path.read_bytes())['sha256'],
            native_runtime_logs={})

    def test_pending_descriptor_exact_source_and_parent_anchors_remain_disabled(self):
        self.assertIsNone(self.descriptor['native_comparison'])
        self.assertEqual(self.descriptor['source_variants'], f.GPU_CPU_VARIANTS)
        self.assertEqual(len(f.GPU_CPU_VARIANTS['candidate']['production']), 12)
        self.assertIsNone(f.GPU_CPU_VARIANTS['baseline']['production']['src/graphics_device.rs'])
        with self.assertRaisesRegex(ValueError, 'review pending'):
            self.bind(self.path)
        for filename, expected in [('finite_ads_reviewed_class.json', f.ORIGINAL_CLASS_SHA256),
                                   ('finite_ads_pass_batching_class.json', f.PASS_BATCHING_CLASS_SHA256),
                                   ('finite_ads_pass_batching_evidence/native-review.json', f.PASS_BATCHING_NATIVE_REVIEW_SHA256)]:
            self.assertEqual(hashlib.sha256((self.path.parent / filename).read_bytes()).hexdigest(), expected)

    def test_flipping_status_or_self_anchoring_receipt_never_activates(self):
        descriptor = deepcopy(self.descriptor); descriptor['status'] = 'reviewed'
        descriptor['native_comparison'] = {'path': 'synthetic.json', **f._identity(b'{}')}
        with patch.object(f, 'GPU_CPU_NATIVE_REVIEW_SHA256', None):
            with self.assertRaisesRegex(ValueError, 'native review anchor unavailable'):
                f._read_gpu_cpu_class(f.source.BoundSourcePacket(), self.path, descriptor)
        with self.assertRaisesRegex(ValueError, 'native comparison anchor'):
            f._read_gpu_cpu_class(f.source.BoundSourcePacket(), self.path, descriptor)

    def test_source_mapping_and_parent_anchor_are_not_caller_controlled(self):
        for change, pattern in [('source', 'coherent'), ('parent', 'batching class anchor'),
                                ('verdict', 'descriptor verdict')]:
            descriptor = deepcopy(self.descriptor); descriptor['status'] = 'reviewed'
            if change == 'source':
                descriptor['source_variants']['candidate']['production']['src/app.rs']['sha256'] = '0' * 64
            elif change == 'parent':
                descriptor['batching_class']['sha256'] = '0' * 64
            else:
                descriptor['acceptance_verdict'] = 'passed'
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, pattern):
                f._read_gpu_cpu_class(f.source.BoundSourcePacket(), self.path, descriptor)

    def test_reserved_markers_reject_before_every_schema_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'external.json'
            for schema, marker in itertools.product((f.SCHEMA, f.PASS_BATCHING_SCHEMA, f.GPU_CPU_SCHEMA, 'unknown'),
                                                     ('_pass_batching', '_gpu_cpu')):
                external = deepcopy(self.descriptor)
                external.update(schema=schema, status='reviewed')
                external[marker] = {'comparison': {}, 'sha256': 'a' * 64}
                path.write_bytes(encoded(external))
                with self.subTest(schema=schema, marker=marker), patch.object(f, '_packet_class') as packet:
                    with self.assertRaisesRegex(ValueError, 'reserved internal'):
                        self.bind(path)
                    packet.assert_not_called()
                # The same prohibition applies to each digest-bound nested reference.
                with self.assertRaisesRegex(ValueError, 'reserved internal'):
                    f._read_class_reference(f.source.BoundSourcePacket(), path,
                        {'path': path.name, **f._identity(path.read_bytes())},
                        f._identity(path.read_bytes())['sha256'], 'nested synthetic descriptor')

    def test_original_schema_cannot_select_new_class(self):
        original = json.loads(self.path.with_name('finite_ads_reviewed_class.json').read_bytes())
        original['class_id'] = f.GPU_CPU_CLASS
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'external.json'; path.write_bytes(encoded(original))
            with patch.object(f, '_packet_class') as packet, self.assertRaisesRegex(ValueError, 'unknown reviewed'):
                self.bind(path)
            packet.assert_not_called()

    def test_mod_canonical_and_overlay_identities_are_distinct(self):
        for label, sizes in [('baseline', (713, 872)), ('candidate', (724, 883))]:
            variant = f.GPU_CPU_VARIANTS[label]
            self.assertEqual(variant['production']['src/render/mod.rs']['bytes'], sizes[0])
            self.assertEqual(variant['reviewed_additions']['src/render/mod.rs']['bytes'], sizes[1])
            self.assertEqual(sizes[1] - sizes[0], len(f.preparation.MOD_SUFFIX))


if __name__ == '__main__':
    unittest.main()
