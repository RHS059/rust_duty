"""Bounded source-only CI report; deliberate missing native inputs do not skip it."""
import argparse,json,sys,unittest
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).absolute().parent
sys.path.insert(0,str(ROOT))
import verify_freeze
import workflow_core as w
import orchestrate

def inspect_source_closure():
    # These are explicitly inspected source identities, not final execution
    # acceptance. No baseline/delta/native inputs or process launch is used.
    declared=w.strict_json(ROOT/'DEPENDENCIES.json')['frozen_inspected_interfaces']
    layout=w.strict_json(ROOT/'controller-layout.template.json');base=ROOT.parent
    config={'roots':{k:str(base/v) for k,v in layout['roots'].items()},'authored_bridge':str(base/layout['authored_bridge'])}
    packages=orchestrate.load_packages(config,{'native_producer_pins_sha256':declared['native_v8'],'runtime_consumer_pins_sha256':declared['consumer_v9']})
    packages.source.portable.cache_free_execution_package(packages.source.core.package)
    return {'source_closure_checked':True,'native_execution_admitted':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--event-commit',required=True);p.add_argument('--summary',required=True);a=p.parse_args()
    identity=verify_freeze.verify(ROOT);closure=inspect_source_closure()
    suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='test_*.py');count=suite.countTestCases()
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    value={'schema':'rust-duty-onehand-pr-source-tests/v2','event_commit':a.event_commit,'observed_orchestration_pins_sha256':identity['pins_sha256'],'source_test_only':True,**closure,'tests_run':result.testsRun,'tests_discovered':count,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'source_tests_passed':result.wasSuccessful(),'native_execution_performed':False,'animation_proof':False,'private_assets_uploaded':False}
    out=Path(a.summary);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8') as f:json.dump(value,f,sort_keys=True)
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
