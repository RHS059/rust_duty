import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import summarize_telemetry_session as m

class SessionInventoryTests(unittest.TestCase):
    def test_frame_trace_has_a_separate_bounded_production_sized_budget(self):
        data = json.loads((self.root / 'frames.json').read_text())
        data['records'] = [{'kind':'successful_present_return','at_ns':i,'eligible':True,
                            'interval_ns':16666667,'ineligibility_reason':None} for i in range(10000)]
        self.write('frames.json', data)
        self.assertGreater((self.root / 'frames.json').stat().st_size, m.JSON_LIMIT)
        self.assertFalse(m.analyze_session(self.root)['acceptance_proven'])
        with patch.object(m, 'FRAME_JSON_LIMIT', 128):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                m.analyze_session(self.root)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('IDENTITY.json', {'schema':'rust-duty-local-playtest-session/v1', 'runtime_observed':{'backend':'Dx12','adapter':'test','requested':'dx12'}})
        self.write('CSV_STATUS.json', {'schema':'rust-duty-local-csv-status/v1','state':'stopped','error':None})
        self.write('frames.json', {'schema':'rust_duty_frame_performance_v1','measurement':m.MEASUREMENT,'status':{'state':'complete','error':None},'identity':{'runtime_observed':{'actual_backend':'Dx12'}}})
        (self.root/'gameplay.csv').write_text(','.join(m.CSV_HEADER)+'\n'+','.join(['0']*15)+'\n',encoding='utf-8')
        (self.root/'OBSERVATIONS.txt').write_text('Local observations',encoding='utf-8')
    def write(self, name, value):
        (self.root/name).write_text(json.dumps(value),encoding='utf-8')
    def test_complete_identity_and_no_acceptance(self):
        result=m.analyze_session(self.root)
        self.assertEqual(result['inventory_state'],'complete')
        self.assertEqual(result['csv_data_rows'],1)
        self.assertEqual(result['identity']['runtime_observed']['backend'],'Dx12')
        self.assertIs(result['acceptance_proven'],False)
    def test_missing_status_or_trace_is_incomplete(self):
        for name in ('CSV_STATUS.json','frames.json'):
            with self.subTest(name=name):
                path=self.root/name; saved=path.read_bytes(); path.unlink()
                self.assertEqual(m.analyze_session(self.root)['inventory_state'],'incomplete')
                path.write_bytes(saved)
    def test_incomplete_states_preserved(self):
        for state in ('incomplete','interrupted'):
            self.write('CSV_STATUS.json',{'schema':'rust-duty-local-csv-status/v1','state':state,'error':'write failed'})
            result=m.analyze_session(self.root)
            self.assertEqual(result['csv_status']['state'],state)
            self.assertEqual(result['inventory_state'],'incomplete')
    def test_backend_mismatch_uses_trace_identity(self):
        data=json.loads((self.root/'frames.json').read_text());data['identity']['runtime_observed']['actual_backend']='Gl';self.write('frames.json',data)
        self.assertTrue(any('Backend mismatch' in x for x in m.analyze_session(self.root)['warnings']))
    def test_invalid_json_values_and_schemas(self):
        for text in ('{}','[]','null','{"schema":"rust-duty-local-playtest-session/v1","x":1,"x":2}',
                     '{"schema":"rust-duty-local-playtest-session/v1","x":NaN}',
                     '{"schema":"rust-duty-local-playtest-session/v1","x":1e999}','{partial'):
            with self.subTest(text=text):
                (self.root/'IDENTITY.json').write_text(text)
                with self.assertRaises(ValueError):m.analyze_session(self.root)
    def test_size_limit(self):
        (self.root/'IDENTITY.json').write_bytes(b' '*(m.JSON_LIMIT+1))
        with self.assertRaises(ValueError):m.analyze_session(self.root)
    def test_symlink_inputs_including_dangling(self):
        for name in ('frames.json','OBSERVATIONS.txt'):
            path=self.root/name;saved=path.read_bytes();path.unlink();path.symlink_to(self.root/'missing')
            with self.assertRaises(ValueError):m.analyze_session(self.root)
            path.unlink();path.write_bytes(saved)
    def test_symlink_directory(self):
        alias=self.root/'alias';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):m.analyze_session(alias)
    def test_bad_csv_headers_width_and_empty(self):
        for value in ('','bad,header\n',' ,'.join(m.CSV_HEADER)+'\n',','.join(m.CSV_HEADER)+'\n1,2\n'):
            (self.root/'gameplay.csv').write_text(value)
            with self.assertRaises(ValueError):m.analyze_session(self.root)
    def test_csv_row_cap(self):
        with patch.object(m,'ROW_LIMIT',0):
            with self.assertRaises(ValueError):m.analyze_session(self.root)
    def test_wrong_measurement_or_status(self):
        original=json.loads((self.root/'frames.json').read_text())
        for key,value in [('measurement','wrong'),('status',{'state':True}),('status',{'state':'complete','error':17})]:
            data=dict(original);data[key]=value;self.write('frames.json',data)
            with self.assertRaises(ValueError):m.analyze_session(self.root)
    def test_cli_read_only_and_exit_codes(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(m.main([str(self.root)]),0)
        self.assertFalse(json.loads(output.getvalue())['acceptance_proven'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})
        (self.root/'gameplay.csv').write_text('bad\n')
        with contextlib.redirect_stderr(io.StringIO()):self.assertEqual(m.main([str(self.root)]),2)

if __name__ == '__main__':unittest.main()
