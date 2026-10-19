"""Strict CPU-only native-entry/controller inventory contract regression."""
import argparse,hashlib,json,sys,unittest
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).absolute().parent
sys.path.insert(0,str(HERE))
import test_payload_only_inventory as tests
import verify_freeze
EXPECTED=12

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    freeze=verify_freeze.verify();suite=unittest.defaultTestLoader.loadTestsFromModule(tests);discovered=suite.countTestCases()
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    passed=result.wasSuccessful() and discovered==result.testsRun==EXPECTED and not result.skipped
    value={'schema':'rust-duty-payload-only-inventory-regression/v1','source_test_only':True,
        'native_execution_performed':False,'animation_proof':False,'private_asset_used':False,
        'actual_python_version':sys.version,'actual_python_implementation':sys.implementation.name,
        'actual_executable_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        'source_freeze':freeze,'predecessor_admission_sha256':tests.original_admission_sha(),
        'observed_admission_sha256':hashlib.sha256((HERE/'admission.py').read_bytes()).hexdigest(),
        'tests_run':result.testsRun,'expected_tests':EXPECTED,'tests_discovered':discovered,
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':passed,
        'production_native_entry_inventory_and_stage_receipt_path_exercised':True,
        'synthetic_preconditions':['Windows host/process provenance','Blender/source numerical production'],
        'request_context_and_receipt_hash_checks_exercised':True}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as stream:json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({key:value[key] for key in ('schema','tests_run','failures','errors','skipped','passed')}))
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
