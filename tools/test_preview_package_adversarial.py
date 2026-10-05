"""Preview-boundary regressions using synthetic evidence, never native proof.

Reuse the existing valid preview fixture without inheriting/re-running its tests.
Only packaging and build stamping are mocked; stage() and its evidence checks
remain real. Generic parser/path tests live with their existing owners.
"""

import io
import os
from unittest import TestCase
from unittest.mock import patch

import stage_dx12_preview as preview
import test_dx12_preview as fixtures


class AdversarialPreviewTests(TestCase):
    def setUp(self):
        self.fixture = fixtures.Dx12PreviewTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f'host cannot create test symlinks: {error}')

    def assert_not_staged(self):
        self.assertFalse(self.fixture.output.exists())
        self.fixture.packager.assert_not_called()
        self.fixture.stamper.assert_not_called()

    def test_cli_malformed_reports_fail_before_packaging(self):
        fixture = self.fixture
        args = ['--root', str(fixture.root), '--smoke-evidence', str(fixture.evidence),
                '--output', str(fixture.output)]
        for name in ('invocation.json', 'summary.json'):
            path = fixture.evidence / name
            original = path.read_bytes()
            for invalid in (b'{invalid json}', b'[]', b'{"passed":true,"passed":true}', b'\xff'):
                with self.subTest(name=name, invalid=invalid):
                    path.write_bytes(invalid)
                    stderr = io.StringIO()
                    try:
                        with patch.dict(os.environ, fixture.env, clear=True), patch('sys.stderr', stderr):
                            with self.assertRaises(SystemExit) as error:
                                preview.main(args)
                        self.assertEqual(error.exception.code, 1)
                        self.assertIn('DX12 preview staging failed:', stderr.getvalue())
                        self.assertIn(name, stderr.getvalue())
                        self.assert_not_staged()
                    finally:
                        path.write_bytes(original)

    def test_symlinked_evidence_directory_is_rejected_before_packaging(self):
        fixture = self.fixture
        link = fixture.root / 'evidence-link'
        self.symlink(link, fixture.evidence, directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinked smoke evidence'):
            preview.stage(fixture.root, 'target/release/vector-range.exe',
                          link, fixture.output, fixture.env)
        self.assert_not_staged()

    def test_symlinked_reports_and_logs_cannot_borrow_valid_evidence(self):
        fixture = self.fixture
        for name in ('invocation.json', 'summary.json', 'stdout.log', 'stderr.log'):
            with self.subTest(name=name):
                path = fixture.evidence / name
                original = path.read_bytes()
                target = fixture.root / f'borrowed-{name}'
                target.write_bytes(original)
                path.unlink()
                try:
                    self.symlink(path, target)
                    with self.assertRaisesRegex(ValueError, 'symlink in distribution path'):
                        fixture.run_stage()
                    self.assert_not_staged()
                finally:
                    path.unlink(missing_ok=True)
                    path.write_bytes(original)

    def test_source_binary_changed_after_copy_fails_atomically(self):
        fixture = self.fixture

        def mutate_source_after_copy(*args, **kwargs):
            fixture.fake_package(*args, **kwargs)
            # The staged copy still matches the tested hash; only the source
            # changed after its initial validation. Exercise the second check.
            fixture.binary.write_bytes(b'changed source executable after copy')

        fixture.packager.side_effect = mutate_source_after_copy
        with self.assertRaisesRegex(ValueError, 'differs from the tested binary'):
            fixture.run_stage()
        fixture.packager.assert_called_once()
        fixture.stamper.assert_not_called()
        self.assertFalse(fixture.output.exists())
        self.assertEqual(list(fixture.output.parent.glob('.stage-dx12-preview-*')), [])


if __name__ == '__main__':
    import unittest
    unittest.main()
