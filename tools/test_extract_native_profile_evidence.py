"""Offline controls for exact-ID, unchanged, conditional-only evidence extraction."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import extract_native_profile_evidence as extraction

ROOT = Path(__file__).resolve().parents[1]


def encoded(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def provider():
    repo = {'id': 123456, 'full_name': extraction.REPOSITORY}
    return {
        'artifact': {'id': extraction.ARTIFACT_ID, 'name': extraction.ARTIFACT_NAME,
                     'size_in_bytes': extraction.ARTIFACT_BYTES, 'digest': extraction.ARTIFACT_DIGEST,
                     'expired': False, 'workflow_run': {
                         'id': int(extraction.SOURCE_CONTEXT['run_id']),
                         'repository_id': repo['id'], 'head_repository_id': repo['id'],
                         'head_sha': extraction.SOURCE_CONTEXT['source_commit'], 'head_branch': 'main'}},
        'attempt': {'id': int(extraction.SOURCE_CONTEXT['run_id']), 'run_attempt': 1,
                    'head_sha': extraction.SOURCE_CONTEXT['source_commit'], 'head_branch': 'main',
                    'path': extraction.SOURCE_WORKFLOW, 'status': 'completed', 'conclusion': 'success',
                    'repository': dict(repo), 'head_repository': dict(repo)},
    }


def fixture():
    inventory = {'oracle-output/rustc-Vv.txt': {'sha256': extraction.COMPILER_SHA256, 'bytes': 194}}
    receipt = {'schema': 'rust-duty-source-visibility-certificates-binding/v1',
               'source_base_commit': extraction.CAPTURE_CONTEXT['source_commit'],
               'source_execution_context': dict(extraction.SOURCE_CONTEXT),
               'capture_context': dict(extraction.CAPTURE_CONTEXT),
               'capture_rustc_sha256': extraction.COMPILER_SHA256,
               'inputs_and_implementation_before': inventory,
               'inputs_and_implementation_after': deepcopy(inventory),
               'backend_reports': {}, 'acceptance_verdict': None}
    packet = {'schema': 'rust-duty-ads-source-packet/v1', 'receipt': 'source-receipt.json',
              'capture_binding': dict(extraction.CAPTURE_CONTEXT),
              'source_outputs': {'windows-legacy': 'oracle-output/frames-opengl.jsonl',
                                 'dx12': 'oracle-output/frames-dx12.jsonl'},
              # References are retained as inert bytes; never used for selection.
              'files': {'private-soldier.bin': 'inventory/private-soldier.bin'}}
    selected = {extraction.PACKET + 'source-packet.json': encoded(packet)}
    for backend in ('opengl', 'dx12'):
        header = {'schema': 'rust-duty-source-visibility-certificate-diagnostic/v2',
                  'expected_frames': 553, 'acceptance_verdict': None,
                  'backend_profile': backend, **dict.fromkeys(extraction.UNPROVEN_FLAGS, False)}
        data = encoded(header) + b''.join(encoded({'frame': frame, 'conditional': True}) for frame in range(553))
        selected[extraction.PACKET + f'oracle-output/frames-{backend}.jsonl'] = data
        receipt['backend_reports'][backend] = {'exit_code': 0, 'header': header,
                                              'output': {'bytes': len(data), 'sha256': extraction.sha256(data)}}
    selected[extraction.PACKET + 'source-receipt.json'] = encoded(receipt)
    return selected


class ProviderTests(unittest.TestCase):
    def test_exact_provider_metadata_passes(self):
        result = extraction.verify_provider(provider())
        self.assertEqual(result['source_execution_context'], extraction.SOURCE_CONTEXT)
        self.assertEqual(result['artifact']['id'], 11396831337)
        self.assertIn('provider metadata', result['artifact_digest_verification'])

    def test_all_artifact_identity_mismatches_fail(self):
        mutations = {'id': 123, 'name': 'other', 'size_in_bytes': 1,
                     'digest': 'sha256:' + '0' * 64, 'expired': True}
        for key, value in mutations.items():
            with self.subTest(key=key):
                metadata = provider()
                metadata['artifact'][key] = value
                with self.assertRaisesRegex(ValueError, 'artifact metadata mismatch'):
                    extraction.verify_provider(metadata)
        metadata = provider()
        metadata['artifact']['expired'] = 0  # False-equivalent is not a provider boolean.
        with self.assertRaises(ValueError):
            extraction.verify_provider(metadata)

    def test_wrong_source_run_attempt_branch_workflow_status_fail(self):
        changes = {'id': 4, 'run_attempt': 2, 'head_sha': 'a' * 40, 'head_branch': 'feature',
                   'path': '.github/workflows/other.yml', 'status': 'in_progress', 'conclusion': 'failure'}
        for key, value in changes.items():
            with self.subTest(key=key):
                metadata = provider()
                metadata['attempt'][key] = value
                with self.assertRaisesRegex(ValueError, 'source attempt mismatch'):
                    extraction.verify_provider(metadata)

    def test_forks_and_artifact_context_mismatches_fail(self):
        for container, key, value in (
            ('repository', 'full_name', 'other/repo'), ('head_repository', 'full_name', 'other/repo'),
            ('head_repository', 'id', 987),
        ):
            metadata = provider()
            metadata['attempt'][container][key] = value
            with self.subTest(container=container, key=key), self.assertRaises(ValueError):
                extraction.verify_provider(metadata)
        for key in provider()['artifact']['workflow_run']:
            metadata = provider()
            metadata['artifact']['workflow_run'][key] = 'mismatch'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'artifact workflow context mismatch'):
                extraction.verify_provider(metadata)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.selected = fixture()
        self.caller = {'source_commit': 'a' * 40, 'run_id': '900', 'run_attempt': '1'}
        for name, data in self.selected.items():
            path = self.root / extraction.INPUT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.pins = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in self.selected.items()}
        self.addCleanup(patch.stopall)
        patch.object(extraction, 'FILES', self.pins).start()

    def package(self):
        return extraction.package(self.root, provider(), self.caller)

    def test_unchanged_closed_output_preserves_original_and_false_flags(self):
        other = self.root / extraction.INPUT / extraction.PACKET / 'inventory/private-soldier.bin'
        other.parent.mkdir()
        other.write_bytes(b'NEVER COPY INVENTORY OR ASSETS')
        outside = self.root / extraction.INPUT / 'unselected-link'
        # Unselected files are never traversed, with or without a supported link.
        try:
            outside.symlink_to(other)
        except OSError:
            outside.write_bytes(b'unselected')
        result = self.package()
        output = self.root / extraction.OUTPUT
        actual = {path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file()}
        self.assertEqual(actual, set(self.selected) | {extraction.PROVENANCE})
        for name, data in self.selected.items():
            self.assertEqual((output / name).read_bytes(), data)
            self.assertEqual((self.root / extraction.INPUT / name).read_bytes(), data)
        self.assertEqual(other.read_bytes(), b'NEVER COPY INVENTORY OR ASSETS')
        self.assertFalse(result['new_oracle_execution'])
        self.assertFalse(result['new_native_capture'])
        self.assertFalse(result['profile_native_verified'])
        self.assertIsNone(result['acceptance_verdict'])
        self.assertEqual(result['source_execution_context'], extraction.SOURCE_CONTEXT)
        self.assertEqual(result['capture_context'], extraction.CAPTURE_CONTEXT)
        self.assertLess(sum(path.stat().st_size for path in output.rglob('*') if path.is_file()), extraction.MAX_TOTAL_BYTES)

    def test_metadata_mismatch_prevents_reading_any_selected_file(self):
        metadata = provider()
        metadata['artifact']['id'] += 1
        with patch.object(extraction, 'read_regular') as read:
            with self.assertRaises(ValueError):
                extraction.package(self.root, metadata, self.caller)
            read.assert_not_called()
        self.assertFalse((self.root / extraction.OUTPUT).exists())

    def test_hash_size_and_missing_file_controls_leave_no_output(self):
        target = self.root / extraction.INPUT / next(iter(self.selected))
        original = target.read_bytes()
        for changed in (b'x' + original[1:], original + b' ', None):
            if changed is None:
                target.unlink()
            else:
                target.write_bytes(changed)
            with self.subTest(changed_size=None if changed is None else len(changed)):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.package()
                self.assertFalse((self.root / extraction.OUTPUT).exists())
            target.write_bytes(original)

    def test_symlink_and_hardlink_selected_files_are_rejected(self):
        target = self.root / extraction.INPUT / next(iter(self.selected))
        original = target.read_bytes()
        outside = self.root / 'outside.json'
        outside.write_bytes(original)
        for kind in ('symlink', 'hardlink'):
            target.unlink()
            try:
                target.symlink_to(outside) if kind == 'symlink' else os.link(outside, target)
            except OSError as error:
                if kind != 'symlink':
                    raise
                target.write_bytes(original)
                continue  # Native link support is covered by the Ubuntu workflow.
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.package()
            self.assertFalse((self.root / extraction.OUTPUT).exists())
            target.unlink()
            target.write_bytes(original)

    def test_symlink_ancestor_rejected(self):
        source = self.root / extraction.INPUT
        moved = source.with_name('moved')
        source.rename(moved)
        try:
            source.symlink_to(moved, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'symlinks unavailable: {error}')
        with self.assertRaisesRegex(ValueError, 'symlink/reparse'):
            self.package()

    def test_native_windows_root_retains_ancestor_validation(self):
        seen = []
        class WindowsPath(PureWindowsPath):
            def absolute(self):
                return self
            def lstat(self):
                seen.append(self.as_posix())
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
        path = WindowsPath('C:/Users/runner/checkout/evidence')
        with patch.object(extraction, 'Path', WindowsPath):
            self.assertEqual(extraction.safe_path(path), path)
        self.assertEqual(seen, ['C:/', 'C:/Users', 'C:/Users/runner',
                                'C:/Users/runner/checkout', 'C:/Users/runner/checkout/evidence'])

    def test_reparse_point_rejected(self):
        path = self.root / 'junction'
        original = Path.lstat
        def observed(value):
            if value == path:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original(value)
        with patch.object(Path, 'lstat', observed), self.assertRaisesRegex(ValueError, 'symlink/reparse'):
            extraction.safe_path(path / 'file')

    def test_total_bound_includes_provenance_and_leaves_no_output(self):
        original_total = sum(map(len, self.selected.values()))
        with patch.object(extraction, 'MAX_TOTAL_BYTES', original_total):
            with self.assertRaisesRegex(ValueError, 'total byte bound including provenance'):
                self.package()
        self.assertFalse((self.root / extraction.OUTPUT).exists())

    def test_existing_output_is_never_overwritten(self):
        output = self.root / extraction.OUTPUT
        output.mkdir(parents=True)
        marker = output / 'original.txt'
        marker.write_bytes(b'original')
        with self.assertRaisesRegex(ValueError, 'output must be fresh'):
            self.package()
        self.assertEqual(marker.read_bytes(), b'original')

    def test_unexpected_output_file_is_rejected(self):
        self.package()
        output = self.root / extraction.OUTPUT
        extra = output / 'unexpected.bin'
        extra.write_bytes(b'no')
        expected = dict(self.selected)
        expected[extraction.PROVENANCE] = (output / extraction.PROVENANCE).read_bytes()
        with self.assertRaisesRegex(ValueError, 'unexpected output file'):
            extraction.verify_output(output, expected)

    def test_flags_provenance_header_and_sequence_mismatches_rejected(self):
        for change in ('native-flag', 'verdict', 'execution', 'compiler', 'output', 'sequence', 'packet'):
            selected = dict(self.selected)
            receipt = json.loads(selected[extraction.PACKET + 'source-receipt.json'])
            if change == 'native-flag':
                receipt['backend_reports']['opengl']['header']['profile_native_verified'] = True
            elif change == 'verdict':
                receipt['acceptance_verdict'] = True
            elif change == 'execution':
                receipt['source_execution_context'] = extraction.CAPTURE_CONTEXT
            elif change == 'compiler':
                receipt['capture_rustc_sha256'] = 'a' * 64
            elif change == 'output':
                receipt['backend_reports']['opengl']['output']['sha256'] = 'a' * 64
            elif change == 'packet':
                packet = json.loads(selected[extraction.PACKET + 'source-packet.json'])
                packet['source_outputs']['dx12'] = 'inventory/private-soldier.bin'
                selected[extraction.PACKET + 'source-packet.json'] = encoded(packet)
            else:
                relative = extraction.PACKET + 'oracle-output/frames-opengl.jsonl'
                lines = selected[relative].splitlines()
                lines[2] = encoded({'frame': 0}).strip()
                selected[relative] = b'\n'.join(lines) + b'\n'
                receipt['backend_reports']['opengl']['output'] = {
                    'bytes': len(selected[relative]), 'sha256': extraction.sha256(selected[relative])}
            selected[extraction.PACKET + 'source-receipt.json'] = encoded(receipt)
            with self.subTest(change=change), self.assertRaises(ValueError):
                extraction.validate_documents(selected)


class WorkflowTests(unittest.TestCase):
    def test_workflow_is_single_bounded_read_only_exact_id_job(self):
        text = (ROOT / extraction.WORKFLOW).read_text()
        self.assertEqual(text.count('runs-on:'), 1)
        self.assertIn('runs-on: ubuntu-24.04', text)
        self.assertIn('contents: read\n  actions: read', text)
        self.assertIn('persist-credentials: false', text)
        self.assertIn("artifact-ids: '11396831337'", text)
        self.assertIn("run-id: '37427554951'", text)
        self.assertIn('artifact_id: 11396831337', text)
        self.assertIn('run_id: 37427554951, attempt_number: 1', text)
        self.assertIn('retries: 0', text)
        self.assertIn('github.run_attempt == 1', text)
        self.assertLess(text.index('extract_native_profile_evidence.py verify-provider'),
                        text.index('uses: actions/download-artifact@v4'))
        self.assertLess(text.index('extract_native_profile_evidence.py package'),
                        text.index('uses: actions/upload-artifact@v4'))
        for forbidden in ('workflow_dispatch:', 'workflow_run:', 'listWorkflowRunArtifacts',
                          'continue-on-error:', 'cargo ', 'rustc ', 'blender ', 'build_ads_source_packet.py',
                          '11364272946', '11385711086', '11386835833', '11386227794'):
            self.assertNotIn(forbidden, text)
        for path in (extraction.WORKFLOW, 'tools/extract_native_profile_evidence.py',
                     'tools/test_extract_native_profile_evidence.py'):
            self.assertIn("      - '" + path + "'", text)

    def test_caller_identity_and_clean_head_guard(self):
        source = 'a' * 40
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_SERVER_URL': 'https://github.com',
               'GITHUB_REPOSITORY': extraction.REPOSITORY, 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '123',
               'GITHUB_WORKFLOW_REF': f'{extraction.REPOSITORY}/{extraction.WORKFLOW}@refs/heads/main',
               'GITHUB_SHA': source, 'GITHUB_WORKFLOW_SHA': source}
        with patch.object(extraction.subprocess, 'check_output', side_effect=[source + '\n', '']):
            self.assertEqual(extraction.caller_identity(ROOT, env)['source_commit'], source)
        for key, value in (('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_RUN_ATTEMPT', '2'),
                           ('GITHUB_REF', 'refs/heads/feature'), ('GITHUB_WORKFLOW_SHA', 'b' * 40)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                extraction.caller_identity(ROOT, {**env, key: value})
        for results in ([source + '\n', ' M tools/extract_native_profile_evidence.py'], ['b' * 40, '']):
            with patch.object(extraction.subprocess, 'check_output', side_effect=results):
                with self.assertRaisesRegex(ValueError, 'clean checkout'):
                    extraction.caller_identity(ROOT, env)


if __name__ == '__main__':
    unittest.main()
