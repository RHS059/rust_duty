"""Offline controls for the fixed CI baseline download; no GitHub writes."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import download_preflight_baseline as fetcher


class PreflightBaselineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / 'baseline'
        self.calls = []
        self.stream = io.StringIO()

    def run_download(self, outcomes):
        outcomes = iter(outcomes)

        def run(command, **options):
            directory = Path(command[command.index('--dir') + 1])
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(directory.parent, self.output)
            self.assertTrue(all(not previous.exists() for previous in self.calls))
            self.calls.append(directory)
            self.assertEqual(command, ['gh', 'release', 'download', 'v0.1.9',
                '--repo', 'RHS059/rust_duty', '--dir', str(directory),
                '--pattern', 'rust-duty-0.1.9-x86_64-pc-windows-msvc.rdb',
                '--pattern', 'update-x86_64-pc-windows-msvc.json'])
            # No new token handling, shell, alternate source or clobber option.
            self.assertEqual(options, {'capture_output': True, 'text': True,
                'encoding': 'utf-8', 'errors': 'replace', 'check': False, 'timeout': 300})
            error, files = next(outcomes)
            for name, contents in files.items():
                (directory / name).write_bytes(contents)
            return subprocess.CompletedProcess(command, 1 if error else 0,
                stdout='sensitive stdout must not be printed', stderr=error)

        with patch.object(fetcher.subprocess, 'run', side_effect=run), \
             patch.object(fetcher.time, 'sleep') as sleep, redirect_stdout(self.stream):
            code = fetcher.main(['--output', str(self.output)])
        return code, sleep

    @staticmethod
    def complete():
        return {'rust-duty-0.1.9-x86_64-pc-windows-msvc.rdb': b'complete bundle',
                'update-x86_64-pc-windows-msvc.json': b'complete manifest'}

    def test_first_attempt_succeeds_and_only_complete_assets_remain(self):
        code, sleep = self.run_download([('', self.complete())])
        self.assertEqual(code, 0)
        sleep.assert_not_called()
        self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, self.complete())
        self.assertNotIn('sensitive stdout', self.stream.getvalue())

    def test_transient_failures_retry_same_source_with_fresh_files(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                self.calls = []
                code, sleep = self.run_download([
                    (f'HTTP {status}: failure (https://private.invalid/?token=secret)',
                     {name: b'partial' for name in self.complete()}),
                    ('', self.complete())])
                self.assertEqual(code, 0)
                self.assertEqual(len(self.calls), 2)
                sleep.assert_called_once_with(2)
                self.assertEqual({p.name: p.read_bytes() for p in self.output.iterdir()}, self.complete())
                self.assertNotIn('https://', self.stream.getvalue())
                self.assertNotIn('secret', self.stream.getvalue())
                for path in self.output.iterdir():
                    path.unlink()

    def test_retry_budget_is_four_attempts_and_failed_downloads_are_cleaned(self):
        partial = {name: b'partial' for name in self.complete()}
        code, sleep = self.run_download([('HTTP 500: server failure', partial)] * 4)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 4)
        self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (4,), (8,)])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertIn('retries exhausted', self.stream.getvalue())

    def test_permanent_and_unclassified_errors_never_retry(self):
        errors = [f'HTTP {status}: rejected' for status in (400, 401, 403, 404, 408, 429, 501, 505)]
        errors += ['HTTP 500: first failure\nHTTP 403: access denied',
                   'connection reset by peer', 'unexpected EOF', 'no assets match the pattern',
                   'TLS certificate verification failed']
        for error in errors:
            with self.subTest(error=error):
                self.calls = []
                code, sleep = self.run_download([(error, self.complete())])
                self.assertEqual(code, 1)
                self.assertEqual(len(self.calls), 1)
                sleep.assert_not_called()
                self.assertEqual(list(self.output.iterdir()), [])

    def test_access_denial_after_transient_failure_stops_immediately(self):
        code, sleep = self.run_download([('HTTP 502: Bad Gateway', {}),
                                        ('gh: Forbidden (HTTP 403)', {})])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 2)
        sleep.assert_called_once_with(2)

    def test_success_without_both_nonempty_assets_fails_without_retry(self):
        cases = [{}, {'rust-duty-0.1.9-x86_64-pc-windows-msvc.rdb': b'one asset'},
                 {name: b'' for name in self.complete()}]
        for files in cases:
            with self.subTest(files=files):
                self.calls = []
                code, sleep = self.run_download([('', files)])
                self.assertEqual(code, 1)
                sleep.assert_not_called()
                self.assertEqual(list(self.output.iterdir()), [])

    def test_existing_files_are_not_removed_or_overwritten(self):
        self.output.mkdir()
        existing = self.output / 'existing-user-file'
        existing.write_bytes(b'preserve')
        with patch.object(fetcher.subprocess, 'run') as run, redirect_stdout(self.stream):
            code = fetcher.main(['--output', str(self.output)])
        self.assertEqual(code, 1)
        run.assert_not_called()
        self.assertEqual(existing.read_bytes(), b'preserve')

    def test_local_process_failure_is_sanitized_and_not_retried(self):
        with patch.object(fetcher.subprocess, 'run', side_effect=OSError(
                'https://private.invalid/?token=secret')) as run, \
             patch.object(fetcher.time, 'sleep') as sleep, redirect_stdout(self.stream):
            code = fetcher.main(['--output', str(self.output)])
        self.assertEqual(code, 1)
        run.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertNotIn('https://', self.stream.getvalue())
        self.assertNotIn('secret', self.stream.getvalue())

    def test_timed_out_process_stops_without_retry_or_raw_diagnostics(self):
        error = subprocess.TimeoutExpired(['gh'], 300, output='secret',
                                          stderr='HTTP 500 https://private.invalid/?token=secret')
        with patch.object(fetcher.subprocess, 'run', side_effect=error) as run, \
             patch.object(fetcher.time, 'sleep') as sleep, redirect_stdout(self.stream):
            code = fetcher.main(['--output', str(self.output)])
        self.assertEqual(code, 1)
        run.assert_called_once()
        sleep.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertNotIn('secret', self.stream.getvalue())

    def test_workflow_keeps_fixed_download_before_existing_verification(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/build.yml').read_text()
        step = workflow.split('      - name: Prepare real Windows 0.1.9 to 0.1.11 update preflight\n')[1]
        step = step.split('      - name:', 1)[0]
        self.assertIn('          GH_TOKEN: ${{ github.token }}', step)
        self.assertIn('          mkdir -p preflight/baseline\n'
                      '          python tools/download_preflight_baseline.py --output preflight/baseline\n'
                      '          python tools/release_update.py verify --manifest preflight/baseline/', step)
        self.assertIn('--assets-dir preflight/baseline --bundle-only --version 0.1.9 '
                      '--target x86_64-pc-windows-msvc', step)
        self.assertIn('--previous preflight/baseline/rust-duty-0.1.9-x86_64-pc-windows-msvc.rdb '
                      '--previous-version 0.1.9', step)
        self.assertIn('--assets-dir preflight/candidate --version 0.1.11 --target x86_64-pc-windows-msvc', step)


if __name__ == '__main__':
    unittest.main()
