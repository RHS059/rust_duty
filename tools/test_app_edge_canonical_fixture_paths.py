"""Canonical invented receipt paths; no Rust, native launch, or asset evidence."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest

from test_app_edge_receipts import ReceiptFixture
from test_app_edge_native_receipts import NativeFixture
import verify_app_edges as verifier


@contextmanager
def aliased_root():
    """A real equivalent spelling on Linux/Windows, without symlink privileges.

    Resolving also handles the host's actual TEMP short-name/junction/case
    aliases. Do not replace TEMP, mock resolve(), or normalize receipt strings
    in the verifier: those strings must still match the exact recorded command.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        hop = root / 'parent-hop'
        hop.mkdir()
        alias = hop / '..'
        assert str(alias) != str(root) and alias.resolve() == root
        yield root, alias


class CanonicalFixturePathTests(unittest.TestCase):
    def test_actual_temp_root_records_resolved_rust_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReceiptFixture(Path(directory))
            root = Path(directory).resolve()
            print('SYNTHETIC_PATH_DIAGNOSTIC ' + json.dumps(dict(
                raw_temp_root=directory, resolved_temp_root=str(root),
                raw_cwd=str(Path(directory) / 'source'),
                recorded_cwd=fixture.receipt['checks'][0]['cwd'],
                expected_cwd=str((root / 'source').resolve())), sort_keys=True))
            self.assertEqual(str(fixture.root), str(root))
            self.assertEqual(fixture.config['root'], str(root))
            self.assertEqual(fixture.config['rust_target_dir'], str(root / 'never-used-target'))
            for entry in [*fixture.receipt['checks'], fixture.build]:
                self.assertEqual(entry['cwd'], str((root / 'source').resolve()))
                self.assertEqual(entry['environment']['CARGO_TARGET_DIR'], str(root / 'never-used-target'))
            fixture.verify()

    def test_alias_root_rust_fixture_uses_canonical_paths_and_parses(self):
        with aliased_root() as (root, alias):
            fixture = ReceiptFixture(alias)
            self.assertEqual(str(fixture.root), str(root))
            self.assertEqual(fixture.config['root'], str(root))
            self.assertEqual(fixture.config['rust_target_dir'], str(root / 'never-used-target'))
            for entry in [*fixture.receipt['checks'], fixture.build]:
                self.assertEqual(entry['cwd'], str((root / 'source').resolve()))
            config, verified_root, *_ = fixture.verify()
            self.assertEqual(config['run_id'], 'invented-cpu-fixture')
            self.assertEqual(str(verified_root), str(root))

    def test_alias_root_native_fixture_uses_canonical_contract_output_and_argv(self):
        with aliased_root() as (root, alias):
            fixture = NativeFixture(alias)
            self.assertEqual(str(fixture.contract), str(root / 'contract.json'))
            self.assertEqual(str(fixture.folder), str(root / 'invented-run'))
            for entry in fixture.run['cases']:
                case = entry['case']
                self.assertEqual(entry['command'], verifier.invocation(
                    fixture.c, root / 'never-executed.txt', root / 'manifest.cfg',
                    root / 'settings.cfg', root / 'invented-run' / case, case, fixture.pin))
            self.assertEqual(fixture.verify()['native_png_witnesses_verified'], 12)

    def test_exact_rust_cwd_rejects_equivalent_unresolved_spelling_for_every_command(self):
        with aliased_root() as (root, alias):
            fixture = ReceiptFixture(root)
            fixture.verify()
            wrong = str(alias / 'source')
            self.assertEqual(Path(wrong).resolve(), (root / 'source').resolve())
            for index, entry in enumerate([*fixture.receipt['checks'], fixture.build]):
                original = entry['cwd']
                self.assertNotEqual(original, wrong)
                with self.subTest(index=index):
                    entry['cwd'] = wrong
                    with self.assertRaisesRegex(verifier.Rejected, 'wrong exact Rust command/cwd'):
                        fixture.verify()
                entry['cwd'] = original
            fixture.verify()

    def test_exact_rust_cwd_rejects_wrong_directory_and_case_for_every_command(self):
        with aliased_root() as (root, _):
            fixture = ReceiptFixture(root)
            fixture.verify()
            for index, entry in enumerate([*fixture.receipt['checks'], fixture.build]):
                original = entry['cwd']
                # Even equivalent Windows case spellings are not exact receipts.
                for wrong in (str(root), original.swapcase()):
                    self.assertNotEqual(original, wrong)
                    with self.subTest(index=index, wrong=wrong):
                        entry['cwd'] = wrong
                        with self.assertRaisesRegex(verifier.Rejected, 'wrong exact Rust command/cwd'):
                            fixture.verify()
                entry['cwd'] = original
            fixture.verify()

    def test_exact_rust_argv_rejects_changed_reordered_and_extra_arguments(self):
        with aliased_root() as (root, _):
            fixture = ReceiptFixture(root)
            fixture.verify()
            for index, entry in enumerate([*fixture.receipt['checks'], fixture.build]):
                original = entry['command']
                reason = 'unexpected native build command' if entry is fixture.build else 'wrong exact Rust command/cwd'
                for wrong in ([*original, '--extra'], ['wrong', *original[1:]],
                              [original[1], original[0], *original[2:]]):
                    with self.subTest(index=index, wrong=wrong):
                        entry['command'] = wrong
                        with self.assertRaisesRegex(verifier.Rejected, reason):
                            fixture.verify()
                entry['command'] = original
            fixture.verify()

    def test_exact_native_argv_rejects_equivalent_alias_in_every_path_argument(self):
        with aliased_root() as (root, alias):
            fixture = NativeFixture(root)
            fixture.verify()
            for entry in fixture.run['cases']:
                original = entry['command']
                for index, argument in enumerate(original):
                    if index == 0:
                        prefix, value = '', argument
                    elif argument.startswith(('--animation-manifest=', '--settings=', '--app-edge-output=')):
                        prefix, value = argument.split('=', 1)
                        prefix += '='
                    else:
                        continue
                    equivalent = alias / Path(value).relative_to(root).as_posix()
                    self.assertEqual(equivalent.resolve(), Path(value).resolve())
                    self.assertNotEqual(str(equivalent), value)
                    wrong = list(original)
                    wrong[index] = prefix + str(equivalent)
                    with self.subTest(case=entry['case'], index=index):
                        entry['command'] = wrong
                        with self.assertRaisesRegex(verifier.Rejected, 'wrong actual command'):
                            fixture.verify()
                    entry['command'] = original
            fixture.verify()

    def test_exact_native_argv_rejects_changed_reordered_and_extra_arguments(self):
        with aliased_root() as (root, _):
            fixture = NativeFixture(root)
            fixture.verify()
            for entry in fixture.run['cases']:
                original = entry['command']
                for wrong in ([*original, '--extra'], ['wrong', *original[1:]],
                              [original[0], original[2], original[1], *original[3:]]):
                    with self.subTest(case=entry['case'], wrong=wrong):
                        entry['command'] = wrong
                        with self.assertRaisesRegex(verifier.Rejected, 'wrong actual command'):
                            fixture.verify()
                entry['command'] = original
            fixture.verify()


if __name__ == '__main__':
    unittest.main(verbosity=2)
