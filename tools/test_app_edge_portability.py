"""Run all invented receipt regressions from a standalone checkout layout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class CheckoutLayoutTests(unittest.TestCase):
    def test_receipts_run_without_external_review_or_source_directories(self):
        here=Path(__file__).resolve().parent
        names=('test_app_edge_receipts.py','test_app_edge_native_receipts.py',
            'app_edge_review_fixture.py','app_edge_contract.py',
            'app_edge_synthetic_fixture.py','verify_app_edges.py',
            'verify_capture_frame_witness.py','verify_render_capture.py')
        # Isolated Python excludes ambient PYTHONPATH and imports only the
        # relocated checkout plus installed standard/Pillow dependencies.
        script="""import json,sys,unittest
sys.path.insert(0,sys.argv[1])
suite=unittest.defaultTestLoader.discover(sys.argv[1],pattern='test_app_edge*receipts.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
print(json.dumps(dict(tests=result.testsRun,failures=len(result.failures),
    errors=len(result.errors),skips=len(result.skipped))))
sys.exit(not result.wasSuccessful())
"""
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);checkout=root/'standalone-checkout';tools=checkout/'tools'
            tools.mkdir(parents=True)
            for name in names:shutil.copyfile(here/name,tools/name)
            unrelated=root/'unrelated-working-directory';unrelated.mkdir()
            for cwd in (checkout,unrelated):
                with self.subTest(cwd=cwd.name):
                    result=subprocess.run([sys.executable,'-I','-B','-c',script,str(tools)],
                        cwd=cwd,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),
                        capture_output=True,text=True,timeout=30,check=False)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    report=json.loads(result.stdout.strip().splitlines()[-1])
                    self.assertGreaterEqual(report.pop('tests'),16)
                    self.assertEqual(report,dict(failures=0,errors=0,skips=0))
            self.assertFalse((root/'source').exists())
            self.assertFalse((root/'app-edge-review-v1').exists())


if __name__=='__main__':unittest.main(verbosity=2)
