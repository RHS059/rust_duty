"""Original synthetic public-API regression tests; no Windows execution."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_dx12_authored as producer
import summarize_dx12_progress as progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.summary = {'schema': progress.SUMMARY_SCHEMA, 'status': 'running', 'passed': False,
                        'acceptance_complete': False, 'budget_exhausted': False,
                        'current_check': 'next/capture', 'elapsed_seconds': 4.2,
                        'run_timeout_seconds': 60, 'checks': [
                            {'name': 'fixture/capture', 'passed': True, 'elapsed_seconds': 0.1, 'result': {}},
                            {'name': 'fixture/finite-images', 'passed': True, 'elapsed_seconds': 0.2,
                             'result': {'frames': 3}}]}
        self.write_summary()

    def write_summary(self):
        producer.write_json(self.root / 'summary.json', self.summary)

    def process(self, name, **fields):
        row = {'schema': progress.PROCESS_SCHEMA, 'status': 'running', 'pid': 123, 'exit_code': None,
               'elapsed_seconds': 4.0, 'timeout_seconds': 10, 'png_files': 2,
               'stdout_bytes': 0, 'stderr_bytes': 0, 'output_path': 'synthetic/output', **fields}
        path = self.root / 'logs' / name / 'process.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        producer.write_json(path, row)
        return row

    def test_two_checks_frames_and_new_report_preserve_inputs(self):
        before = (self.root / 'summary.json').read_bytes()
        report = self.root / 'new-report.json'
        result = progress.summarize_dx12_progress(self.root, report)
        self.assertEqual(result['frame_count'], 3)
        self.assertEqual(result['checks'][1]['result']['frames'], 3)
        self.assertEqual(json.loads(report.read_text()), result)
        self.assertEqual((self.root / 'summary.json').read_bytes(), before)
        self.assertFalse(result['acceptance_complete'])

    def test_current_process_is_retained_before_its_check_is_appended(self):
        row = self.process('next')
        result = progress.summarize_dx12_progress(self.root)
        self.assertEqual(result['current_check'], 'next/capture')
        self.assertEqual(result['active_process']['pid'], row['pid'])
        self.assertEqual(result['active_process']['png_files'], 2)
        self.assertEqual(result['frame_count'], 3)  # Live PNG progress is separate.
        self.assertEqual(len(result['checks']), 2)

    def test_real_producer_process_record_is_read_without_rewriting_check(self):
        self.summary['current_check'] = 'fixture/capture'
        self.write_summary()
        with contextlib.redirect_stdout(io.StringIO()):
            producer.execute([sys.executable, '-c', 'print("synthetic")'], self.root,
                             self.root / 'logs/fixture', 10)
        result = progress.summarize_dx12_progress(self.root)
        self.assertEqual(result['active_process']['status'], 'passed')
        self.assertGreater(result['active_process']['stdout_bytes'], 0)
        self.assertEqual(result['checks'][0]['elapsed_seconds'], 0.1)

    def test_actual_process_name_mappings(self):
        for check, log in [('orientation-renderer-contract', 'renderer-contract'),
                           ('lighting/ready_front', 'lighting-ready_front'),
                           ('jump-gameplay/existing-validator', 'jump-gameplay-validator'),
                           ('ads-placement-existing-validator', 'ads-placement-validator'),
                           ('layered-rates-existing-validator', 'layered-rates-validator')]:
            with self.subTest(check=check):
                self.summary['current_check'] = check
                self.write_summary()
                self.process(log, status='timed_out', error='synthetic timeout')
                active = progress.summarize_dx12_progress(self.root)['active_process']
                self.assertEqual(active['log_name'], log)
                self.assertEqual(active['error'], 'synthetic timeout')

    def test_check_failure_is_not_replaced_by_successful_process(self):
        self.summary['checks'].append({'name': 'fixture/existing-validator', 'passed': False,
                                       'error': 'actual validation failed', 'elapsed_seconds': 1})
        self.write_summary()
        self.process('fixture-validator', status='passed', exit_code=0)
        result = progress.summarize_dx12_progress(self.root)
        self.assertEqual(result['checks'][-1]['status'], 'failed')
        self.assertEqual(result['checks'][-1]['error'], 'actual validation failed')

    def test_missing_summary_is_incomplete_even_with_successful_process(self):
        (self.root / 'summary.json').unlink()
        self.process('fixture', status='passed', exit_code=0)
        result = progress.summarize_dx12_progress(self.root)
        self.assertEqual(result['status'], 'incomplete')
        self.assertTrue(result['issues'])
        self.assertEqual(len(result['processes']), 1)

    def test_invalid_shapes_truthy_flags_and_nonfinite_json_are_rejected(self):
        original = json.loads(json.dumps(self.summary))
        mutations = [('checks', ['bad']), ('checks', {}), ('passed', 1),
                     ('elapsed_seconds', -1), ('current_check', False), ('status', 'unknown')]
        for field, value in mutations:
            with self.subTest(field=field):
                self.summary = {**original, field: value}
                self.write_summary()
                with self.assertRaises(ValueError):
                    progress.summarize_dx12_progress(self.root)
        self.summary = original
        for value in ('false', 1, [], {}):
            self.summary['checks'][0]['passed'] = value
            self.write_summary()
            with self.subTest(value=value), self.assertRaises(ValueError):
                progress.summarize_dx12_progress(self.root)
        for raw in ('{', '[]', '{"checks":[],"checks":[]}', '{"x":NaN}', '{"x":1e9999}'):
            (self.root / 'summary.json').write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                progress.summarize_dx12_progress(self.root)

    def test_frame_counts_and_process_counters_require_real_integers(self):
        for value in (True, -1, 3.0, '3'):
            self.summary['checks'][1]['result']['frames'] = value
            self.write_summary()
            with self.subTest(frames=value), self.assertRaises(ValueError):
                progress.summarize_dx12_progress(self.root)
        self.summary['checks'][1]['result']['frames'] = 3
        self.write_summary()
        self.process('next', png_files=True)
        with self.assertRaises(ValueError):
            progress.summarize_dx12_progress(self.root)

    def test_existing_report_and_input_summary_are_never_overwritten(self):
        sentinel = self.root / 'report.json'
        sentinel.write_bytes(b'keep this exactly')
        for path in (sentinel, self.root / 'summary.json'):
            before = path.read_bytes()
            with self.subTest(path=path), self.assertRaises(FileExistsError):
                progress.summarize_dx12_progress(self.root, path)
            self.assertEqual(path.read_bytes(), before)

    def test_symlink_inputs_and_dangling_report_are_rejected(self):
        link = self.root / 'report-link'
        try:
            link.symlink_to(self.root / 'absent')
        except OSError as error:
            self.skipTest(str(error))
        original_link = link.readlink()
        with self.assertRaises(FileExistsError):
            progress.summarize_dx12_progress(self.root, link)
        self.assertFalse((self.root / 'absent').exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), original_link)
        source = self.root / 'summary.json'
        target = self.root / 'original.json'
        source.rename(target)
        source.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            progress.summarize_dx12_progress(self.root)

    def test_contradictory_pass_does_not_hide_incomplete_check(self):
        self.summary.update(status='passed', passed=True, current_check=None)
        self.summary['checks'][0]['passed'] = None
        self.write_summary()
        with self.assertRaisesRegex(ValueError, 'contradictory'):
            progress.summarize_dx12_progress(self.root)

    def test_passed_snapshot_requires_matching_clean_process_evidence(self):
        self.summary.update(status='passed', passed=True, current_check=None)
        self.write_summary()
        self.assertEqual(progress.summarize_dx12_progress(self.root)['status'], 'incomplete')
        self.process('fixture', status='passed', exit_code=0)
        result = progress.summarize_dx12_progress(self.root)
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['acceptance_complete'])
        self.process('fixture', status='passed', exit_code=3)
        with self.assertRaisesRegex(ValueError, 'clean exit'):
            progress.summarize_dx12_progress(self.root)

    def test_public_cli_errors_and_real_authored_failure_report(self):
        game, contract = self.root / 'game.exe', self.root / 'contract.exe'
        for path in (game, contract):
            path.write_bytes(b'synthetic not executed')
        (self.root / 'settings.cfg').write_text('# synthetic\n')
        legacy = self.root / 'legacy'
        legacy.mkdir()
        evidence = self.root / 'produced'
        with patch.object(producer, 'asset_evidence', return_value={}), \
                patch.object(producer, 'execute', side_effect=ValueError('synthetic launch failure')), \
                contextlib.redirect_stdout(io.StringIO()):
            produced = producer.run(game, contract, self.root, evidence, legacy, 10)
            self.assertEqual(progress.main([str(evidence)]), 0)
        result = progress.summarize_dx12_progress(evidence, self.root / 'produced-report.json')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(result['checks']), len(produced['checks']))
        self.assertIn('synthetic launch failure', result['checks'][1]['error'])
        (self.root / 'summary.json').write_text('{')
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(progress.main([str(self.root)]), 1)
        self.assertIn('summary failed', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
