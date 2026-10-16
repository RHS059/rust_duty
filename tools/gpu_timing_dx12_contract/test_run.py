import json
import unittest
from run import scenario_result


class ReceiptTests(unittest.TestCase):
    def receipt(self, *, code=0, timeout=False, status='passed', backend='Dx12', name='disabled'):
        process = {'timed_out': timeout, 'exit_code': code}
        events = [
            {'event': 'scenario_start', 'name': name},
            {'event': 'instance', 'configured_backends': 'DX12', 'force_fallback_adapter': True, 'validation_requested': True},
            {'event': 'adapter', 'backend': backend, 'device_type': 'Cpu', 'name': 'test fixture', 'vendor': 0,
             'device': 0, 'driver': '', 'driver_info': '', 'available_features': '', 'requested_features': '',
             'requested_timestamp_pair': False, 'adapter_supports_timestamp_pair': True},
            {'event': 'device', 'enabled_features': '', 'enabled_timestamp_pair': False},
            {'event': 'sample', 'session': '1', 'attempt': '1', 'status': 'disabled',
             'start_ticks': None, 'end_ticks': None, 'timestamp_period_ns': None, 'elapsed_ns': None},
            {'event': 'scenario_result', 'name': name, 'status': status},
        ]
        return process, events

    def parse(self, process, events):
        return scenario_result('disabled', process, '\n'.join(json.dumps(e) for e in events))['status']

    def test_valid_control_passes(self):
        self.assertEqual(self.parse(*self.receipt()), 'passed')

    def test_timeout_cannot_pass_with_a_success_receipt(self):
        self.assertEqual(self.parse(*self.receipt(timeout=True)), 'failed')

    def test_wrong_backend_cannot_pass(self):
        self.assertEqual(self.parse(*self.receipt(backend='Vulkan')), 'failed')

    def test_wrong_scenario_cannot_pass(self):
        self.assertEqual(self.parse(*self.receipt(name='other')), 'failed')

    def test_exit_mismatch_cannot_pass(self):
        self.assertEqual(self.parse(*self.receipt(code=1)), 'failed')

    def test_missing_or_duplicate_terminal_cannot_pass(self):
        process, events = self.receipt()
        self.assertEqual(self.parse(process, events[:-1]), 'failed')
        self.assertEqual(self.parse(process, events + [events[-1]]), 'failed')

    def test_unsupported_remains_unsupported(self):
        self.assertEqual(self.parse(*self.receipt(code=2, status='unsupported')), 'unsupported')

    def test_missing_device_or_sample_cannot_pass(self):
        for kind in ('device', 'sample'):
            process, events = self.receipt()
            self.assertEqual(self.parse(process, [e for e in events if e['event'] != kind]), 'failed')

    def test_miskeyed_or_duplicated_sample_cannot_pass(self):
        process, events = self.receipt()
        self.assertEqual(self.parse(process, events + [events[4]]), 'failed')
        events[4]['attempt'] = '2'
        self.assertEqual(self.parse(process, events), 'failed')

    def test_unavailable_numeric_value_cannot_pass(self):
        process, events = self.receipt()
        events[4]['elapsed_ns'] = 0
        self.assertEqual(self.parse(process, events), 'failed')

    def test_late_error_after_terminal_cannot_pass(self):
        for kind in ('uncaptured_error', 'device_lost', 'poll_deadline'):
            process, events = self.receipt()
            self.assertEqual(self.parse(process, events + [{'event': kind}]), 'failed')

    def test_cpu_adapter_and_supervision_are_required(self):
        process, events = self.receipt()
        events[2]['device_type'] = 'DiscreteGpu'
        self.assertEqual(self.parse(process, events), 'failed')
        process, events = self.receipt()
        process['supervision_errors'] = ['taskkill failed']
        self.assertEqual(self.parse(process, events), 'failed')


if __name__ == '__main__':
    unittest.main()
