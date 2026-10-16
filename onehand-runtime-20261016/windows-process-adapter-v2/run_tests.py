"""Original bounded test runner; only synthetic Python process tests are launched."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import unittest
sys.dont_write_bytecode=True

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--require-windows',action='store_true')
    parser.add_argument('--verify-pins',action='store_true')
    parser.add_argument('--summary',type=Path,required=True)
    args=parser.parse_args()
    if args.require_windows and os.name!='nt':
        raise SystemExit('actual Windows required; non-Windows skipped tests are not a pass')
    if args.summary.exists(): raise SystemExit('summary already exists; refuse overwrite')
    if args.verify_pins:
        pins=json.loads((HERE/'PINS.json').read_text())
        for name,record in pins['files'].items():
            if Path(name).name!=name: raise SystemExit('pins must use local basenames')
            data=(HERE/name).read_bytes()
            if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
                raise SystemExit('frozen source mismatch: '+name)
    suite=unittest.defaultTestLoader.discover(str(HERE),pattern='test_*.py')
    start=time.monotonic(); result=unittest.TextTestRunner(verbosity=2).run(suite)
    windows_skips=[test.id() for test,reason in result.skipped if 'test_windows_native.' in test.id()]
    native_count=unittest.defaultTestLoader.loadTestsFromName('test_windows_native.NativeWindowsSmoke').countTestCases()
    smoke=platform.system()=='Windows' and native_count==4 and not windows_skips and result.wasSuccessful()
    summary={'schema':'rust-duty-owned-process-tests/v1','host':platform.platform(),'python':sys.version,
        'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':[{'test':test.id(),'reason':reason} for test,reason in result.skipped],
        'duration_seconds':time.monotonic()-start,'all_executed_tests_passed':result.wasSuccessful(),
        'actual_windows_transport_smoke_passed':smoke,'actual_windows_animation_proof':False,
        'blender_game_or_assets_executed':False,'source_revision':os.environ.get('GITHUB_SHA'),
        'native_windows_tests_defined':native_count,'pins_verified':args.verify_pins}
    data=(json.dumps(summary,indent=2,allow_nan=False)+'\n').encode()
    if len(data)>32768: raise SystemExit('summary bound exceeded')
    with args.summary.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    if not result.wasSuccessful() or (args.require_windows and not smoke): raise SystemExit(1)

if __name__=='__main__': main()
