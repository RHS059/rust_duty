"""Offline adversarial restoration tests; never compile or execute retained code."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import prepare_finite_probe_inputs as prep
import extract_native_profile_evidence as extraction
from test_extract_native_profile_evidence import provider


def bridge_fixture():
    original = (b'impl AuthoredViewmodel {\n'
                b'    /// Loads CPU mesh and texture descriptors without requiring a render context.\n'
                b'}\n#[cfg(test)]\nmod tests {\n}\n')
    overlay = (b'/// Read-only evaluated source pose for independent CPU diagnostics.\nstruct Snapshot;\n' + original)
    overlay = overlay.replace(b'    /// Loads CPU', b'    /// Snapshot the same effective pose selected by `draw_checked`, before\n    // diagnostic\n    /// Loads CPU')
    last = overlay.rfind(b'\n}')
    overlay = overlay[:last] + b'\n\n    fn layered_contact_fixture() -> AuthoredViewmodel { todo!() }\n' + overlay[last:]
    prep.producer.reviewed_bridge(original, overlay)
    return original, overlay


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packet = self.root / 'packet'
        self.verifier = self.root / 'verifier'
        self.output = self.root / 'restored'
        self.metadata = self.root / 'provider.json'
        self.caller = {'source_commit': 'a' * 40, 'run_id': '123', 'run_attempt': '1'}
        self.metadata.write_bytes(prep.encoded(provider()))
        self.originals = {name: ('synthetic ' + name + '\n').encode() for name in prep.ROOT_PRODUCTION | prep.binding.INPUTS | prep.EXCLUDED}
        self.originals.update({
            'src/authored_viewmodel.rs': bridge_fixture()[1],
            'oracle-output/original-authored_viewmodel.rs': bridge_fixture()[0],
            'src/render/mesh.rs': b'impl Mesh {\n    /// Three immutable buffers\n}\n',
            'src/render/mod.rs': b'pub mod mesh;\n',
            'oracle-output/rustc-Vv.txt': b'rustc 1.99.0 (fixture)\nhost: x86_64-pc-windows-msvc\n',
            'settings.cfg': b'original settings\n',
            'ads-offset.cfg': b'original settings\n' + prep.binding.OFFSET_SUFFIX.encode(),
        })
        for i in range(137 - len(self.originals)):
            self.originals[f'src/test_source_{i}.rs'] = f'// fixture {i}\n'.encode()
        inventory = {name: prep.identity(data) for name, data in self.originals.items()}
        compiler_hash = inventory['oracle-output/rustc-Vv.txt']['sha256']
        self.addCleanup(patch.stopall)
        patch.object(extraction, 'COMPILER_SHA256', compiler_hash).start()
        self.receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
                        'source_base_commit': extraction.CAPTURE_CONTEXT['source_commit'],
                        'source_execution_context': deepcopy(extraction.SOURCE_CONTEXT),
                        'capture_context': deepcopy(extraction.CAPTURE_CONTEXT),
                        'capture_rustc_sha256': compiler_hash, 'toolchain': prep.TOOLCHAIN,
                        'inputs_and_implementation_before': inventory,
                        'inputs_and_implementation_after': deepcopy(inventory),
                        'oracle_execution': {'platform': 'win32', 'host': prep.TARGET, 'target': prep.TARGET,
                                             'profile': 'release', 'features': prep.producer.FEATURES},
                        'backend_reports': {}, 'acceptance_verdict': None}
        capture_binding = deepcopy(extraction.CAPTURE_CONTEXT)
        capture_binding['runtime_and_manifest_sha256'] = {name: inventory[name]['sha256'] for name in prep.binding.INPUTS}
        self.document = {'schema': 'rust-duty-ads-source-packet/v1', 'receipt': 'source-receipt.json',
                         'capture_binding': capture_binding,
                         'source_outputs': {'windows-legacy': 'oracle-output/frames-opengl.jsonl',
                                            'dx12': 'oracle-output/frames-dx12.jsonl'},
                         'files': {name: 'inventory/' + name for name in inventory},
                         'input_files': {name: name for name in prep.binding.INPUTS}}
        self.documents = {}
        empty = [i for i in range(553) if i not in prep.VISIBLE][:160]
        self.rows = [{'frame': i, 'classification': 'expected_empty_under_profile' if i in empty else 'potentially_visible_unresolved',
                      'acceptance_verdict': None, 'possible_support_complete': True, 'unsupported_clip_triangles': 0,
                      'possible_samples': 0 if i in empty else 1, 'required_contrast_samples': 0 if i in empty else 1,
                      'required_contrast_runs': [] if i in empty else [[12, 1]],
                      'possible_support_runs': [] if i in empty else [[12, 1]]} for i in range(553)]
        for backend, role in (('opengl', 'windows-legacy'), ('dx12', 'dx12')):
            header = {'schema': 'rust-duty-source-visibility-certificate-diagnostic/v2',
                      'expected_frames': 553, 'acceptance_verdict': None,
                      'backend_profile': prep.binding.BACKEND_PROFILES[role],
                      **dict.fromkeys(extraction.UNPROVEN_FLAGS, False)}
            data = b'\n'.join(json.dumps(row).encode() for row in [header, *self.rows]) + b'\n'
            self.documents[f'oracle-output/frames-{backend}.jsonl'] = data
            self.receipt['backend_reports'][backend] = {'exit_code': 0, 'header': header, 'output': prep.identity(data)}
        self.sync_documents()
        patch.object(extraction, 'FILES', self.pins).start()
        for name, data in self.originals.items():
            path = self.packet / 'inventory' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        for name in prep.OVERLAYS:
            if name == 'src/render/mesh.rs':
                data = self.originals[name].replace(prep.MESH_END, prep.MESH_START + b'\n    fn diagnostic() {}\n' + prep.MESH_END)
            elif name == 'src/render/mod.rs':
                data = self.originals[name] + prep.MOD_SUFFIX
            else:
                data = ('// current committed diagnostic: ' + name + '\n').encode()
            path = self.verifier / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def sync_documents(self):
        self.documents['source-receipt.json'] = prep.encoded(self.receipt)
        self.documents['source-packet.json'] = prep.encoded(self.document)
        new_pins = {}
        for name, data in self.documents.items():
            path = self.packet / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            new_pins[extraction.PACKET + name] = (len(data), prep.identity(data)['sha256'])
        if hasattr(self, 'pins'):
            # The fixture-only pin dictionary stays the object installed by patch.
            self.pins.clear()
            self.pins.update(new_pins)
        else:
            self.pins = new_pins

    def prepare(self):
        return prep.prepare(self.packet, self.metadata, self.verifier, self.output, self.caller)

    def verify(self, anchor):
        return prep.verify(self.packet, self.metadata, self.verifier, self.output, self.caller, anchor)

    def test_restores_only_128_original_files_and_six_overlays(self):
        sentinel = self.packet / 'inventory/assets/private-soldier.bin'
        sentinel.write_bytes(b'never read or copy')
        with patch.object(subprocess, 'run', side_effect=AssertionError('native execution prohibited')), \
             patch.object(subprocess, 'check_output', side_effect=AssertionError('execution prohibited')):
            anchor = self.prepare()
            report = self.verify(anchor)
        self.assertEqual(len(report['restored_original_inventory']), 128)
        self.assertEqual(set(report['diagnostic_overlays']), set(prep.OVERLAYS))
        self.assertFalse((self.output / 'source/target').exists())
        self.assertFalse((self.output / 'source/assets/private-soldier.bin').exists())
        self.assertFalse(report['profile_native_verified'])
        self.assertIsNone(report['acceptance_verdict'])
        self.assertEqual(json.loads((self.output / 'visible-frames.json').read_bytes()), list(prep.VISIBLE))
        self.assertEqual(len(json.loads((self.output / 'empty-frames.json').read_bytes())), 160)
        self.assertEqual(len(json.loads((self.output / 'fallback-frames.json').read_bytes())), 210)
        for name in ('source-packet.json', 'source-receipt.json', 'oracle-output/frames-dx12.jsonl'):
            self.assertEqual((self.packet / name).read_bytes(), (self.output / 'original' / name).read_bytes())

    def test_denied_ids_and_wrong_provider_fail_before_inventory_read(self):
        for artifact in (*prep.producer.DENIED_ARTIFACT_IDS, 1):
            metadata = provider()
            metadata['artifact']['id'] = artifact
            self.metadata.write_bytes(prep.encoded(metadata))
            with self.subTest(artifact=artifact), self.assertRaisesRegex(ValueError, 'artifact metadata'):
                self.prepare()
            self.assertFalse(self.output.exists())

    def test_pinned_packet_jsonl_or_receipt_mutation_fails(self):
        for name in self.documents:
            path = self.packet / name
            data = path.read_bytes()
            path.write_bytes(data + b' ')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'pinned original'):
                self.prepare()
            path.write_bytes(data)
        self.assertFalse(self.output.exists())

    def test_selected_source_or_companion_mutation_fails(self):
        for name in ('src/render/mesh.rs', 'assets/reload/asset.vrs', 'settings.cfg'):
            path = self.packet / 'inventory' / name
            data = path.read_bytes()
            path.write_bytes(data + b'!')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'inventory bytes changed'):
                self.prepare()
            path.write_bytes(data)
        self.assertFalse(self.output.exists())

    def test_old_executable_is_not_read_even_when_unavailable(self):
        old = self.packet / 'inventory' / f'target/{prep.TARGET}/release/examples/source_visibility_certificate.exe'
        old.unlink()
        self.prepare()

    def test_original_bridge_and_compiler_validation_are_real(self):
        original, overlay = bridge_fixture()
        self.assertEqual(prep.producer.reviewed_bridge(original, overlay), overlay)
        with self.assertRaises(ValueError):
            prep.producer.reviewed_bridge(original, overlay.replace(b'impl AuthoredViewmodel', b'impl ChangedViewmodel'))
        with self.assertRaises(ValueError):
            prep.producer.checked_compiler(b'host: wrong\n', extraction.COMPILER_SHA256)

    def test_symlink_and_hardlink_rejected(self):
        path = self.packet / 'inventory/settings.cfg'
        original = path.read_bytes()
        outside = self.root / 'other-settings'
        outside.write_bytes(original)
        for hard in (False, True):
            path.unlink()
            try:
                if hard:
                    os.link(outside, path)
                else:
                    path.symlink_to(outside)
            except OSError:
                path.write_bytes(original)
                continue
            with self.subTest(hard=hard), self.assertRaises(ValueError):
                self.prepare()
            path.unlink()
            path.write_bytes(original)

    def test_output_must_be_fresh(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.prepare()

    def test_production_overlay_changes_and_missing_markers_fail(self):
        for name in ('src/render/mesh.rs', 'src/render/mod.rs'):
            path = self.verifier / name
            data = path.read_bytes()
            for changed in (data + b'// production change\n', data.replace(b'pub mod mesh;', b'pub mod other;') if name.endswith('mod.rs') else data.replace(prep.MESH_START, b'// no marker')):
                path.write_bytes(changed)
                with self.subTest(name=name), self.assertRaises(ValueError):
                    self.prepare()
            path.write_bytes(data)

    def test_inventory_rejects_noncanonical_mapping_missing_extra_and_type(self):
        for change in ('map', 'missing', 'extra', 'bool', 'input'):
            packet, receipt = deepcopy(self.document), deepcopy(self.receipt)
            entries = receipt['inputs_and_implementation_before']
            if change == 'map': packet['files']['Cargo.lock'] = 'inventory/../Cargo.lock'
            elif change == 'missing': del packet['files']['Cargo.lock']
            elif change == 'extra': entries['assets/private-soldier.bin'] = prep.identity(b'private')
            elif change == 'bool': entries['Cargo.lock']['bytes'] = True
            elif change == 'input': del packet['input_files']['assets/reload/asset.vrs']
            receipt['inputs_and_implementation_after'] = deepcopy(entries)
            with self.subTest(change=change), self.assertRaises(ValueError):
                prep.validate_inventory(packet, receipt)

    def test_context_and_toolchain_mismatch_fail(self):
        for field, changed in (('toolchain', 'stable'), ('source_base_commit', 'b' * 40),
                               ('source_execution_context', extraction.CAPTURE_CONTEXT)):
            original = self.receipt[field]
            self.receipt[field] = changed
            self.sync_documents()
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.prepare()
            self.receipt[field] = original
        self.sync_documents()

    def test_late_original_overlay_and_restored_mutation_fail(self):
        anchor = self.prepare()
        paths = [self.packet / 'inventory/assets/reload/asset.vrs',
                 self.verifier / 'examples/finite_warp_probe.rs',
                 self.output / 'source/src/render/mesh.rs',
                 self.output / 'source/assets/reload/asset.vrs',
                 self.output / 'original/source-receipt.json']
        for path in paths:
            original = path.read_bytes()
            path.write_bytes(original + b'!')
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.verify(anchor)
            path.write_bytes(original)
        self.verify(anchor)

    def test_receipt_anchor_and_caller_are_independent(self):
        anchor = self.prepare()
        with self.assertRaises(ValueError): self.verify('0' * 64)
        with self.assertRaises(ValueError): self.verify(None)
        self.caller['run_id'] = '456'
        with self.assertRaisesRegex(ValueError, 'caller/schema'):
            self.verify(anchor)

    def test_unexpected_source_file_or_directory_fails_but_fresh_target_allowed(self):
        anchor = self.prepare()
        target = self.output / f'source/target/{prep.TARGET}/release/examples'
        target.mkdir(parents=True)
        (target / 'source_visibility_geometry_probe.exe').write_bytes(b'new build output never executed by helper')
        self.verify(anchor)
        extra = self.output / 'source/src/new-production.rs'
        extra.write_bytes(b'not allowed')
        with self.assertRaisesRegex(ValueError, 'unexpected output file'): self.verify(anchor)
        extra.unlink()
        extra_dir = self.output / 'source/.cargo'
        extra_dir.mkdir()
        with self.assertRaisesRegex(ValueError, 'unexpected output directory'): self.verify(anchor)

    def test_frame_source_rejects_bool_count_missing_nonempty_and_unsupported(self):
        raw = self.documents['oracle-output/frames-dx12.jsonl']
        rows = list(map(json.loads, raw.splitlines()))
        for key, value in (('frame', True), ('required_contrast_samples', True),
                           ('possible_support_complete', 1), ('unsupported_clip_triangles', 1),
                           ('required_contrast_runs', []), ('acceptance_verdict', True)):
            changed = deepcopy(rows)
            changed[prep.VISIBLE[0] + 1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                prep.frame_lists(b'\n'.join(json.dumps(row).encode() for row in changed))

    def test_duplicate_and_nonfinite_json_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'):
            with self.assertRaises(ValueError): prep.parse(raw)

    def test_traversal_windows_alias_and_unc_paths_rejected(self):
        for path in ('../source.rs', 'src/../file.rs', '/tmp/file.rs', 'C:/file.rs', 'src\\file.rs',
                     'src//file.rs', 'src/./file.rs', 'src/NUL.rs', 'src/file.rs.', 'src/file.rs '):
            with self.subTest(path=path), self.assertRaises(ValueError): prep.relative(path)


class CallerTests(unittest.TestCase):
    def environment(self):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_SERVER_URL': 'https://github.com',
                'GITHUB_REPOSITORY': extraction.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ATTEMPT': '1',
                'GITHUB_WORKFLOW_REF': f'{extraction.REPOSITORY}/{prep.WORKFLOW}@refs/heads/main',
                'GITHUB_SHA': 'a' * 40, 'GITHUB_WORKFLOW_SHA': 'a' * 40, 'GITHUB_RUN_ID': '999'}

    def identity(self, env, tracked=None, dirty=''):
        results = ['a' * 40, dirty, ('\0'.join(prep.OVERLAYS if tracked is None else tracked) + '\0').encode()]
        with patch.object(subprocess, 'check_output', side_effect=results):
            return prep.caller_identity(Path('/nonexistent-test-root'), env)

    def test_exact_main_push_identity_passes(self):
        self.assertEqual(self.identity(self.environment())['workflow'], prep.WORKFLOW)

    def test_wrong_workflow_context_rerun_and_conflation_fail(self):
        for key, value in (('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                           ('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_WORKFLOW_SHA', 'b' * 40),
                           ('GITHUB_REPOSITORY', 'fork/rust_duty'), ('GITHUB_RUN_ID', extraction.SOURCE_CONTEXT['run_id']),
                           ('GITHUB_WORKFLOW_REF', f'{extraction.REPOSITORY}/{extraction.WORKFLOW}@refs/heads/main')):
            env = self.environment()
            env[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.identity(env)

    def test_dirty_or_unpublished_overlay_fails(self):
        with self.assertRaises(ValueError): self.identity(self.environment(), dirty=' M src/render/mod.rs')
        with self.assertRaises(ValueError): self.identity(self.environment(), tracked=prep.OVERLAYS[:-1])


if __name__ == '__main__':
    unittest.main()
