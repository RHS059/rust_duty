"""Early CPU-only real-reader gate. Requires the already pinned NumPy install."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import test_rigid_json_cap as tests
import verify_freeze


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    freeze = verify_freeze.verify()
    suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = (result.wasSuccessful() and discovered == result.testsRun == 19
              and not result.skipped)
    value = {
        'schema': 'rust-duty-rigid-json-reader-regression/v1',
        'source_test_only': True,
        'native_execution_performed': False,
        'animation_proof': False,
        'private_asset_used': False,
        'actual_python_version': sys.version,
        'actual_python_implementation': sys.implementation.name,
        'actual_executable_sha256': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        'source_freeze': freeze,
        'predecessor_native_stages_sha256': tests.original_native_stages_sha(),
        'observed_native_stages_sha256': hashlib.sha256((HERE / 'native_stages.py').read_bytes()).hexdigest(),
        'default_metadata_read_bytes': 2 * 1024**2,
        'rigid_frame1_read_bytes': 32 * 1024**2,
        'unchanged_rigid_frame1_write_bytes': 32 * 1024**2,
        'tests_run': result.testsRun,
        'expected_tests': 19,
        'tests_discovered': discovered,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'passed': passed,
    }
    if passed:
        # Measure the synthetic output through the same real stage and writer.
        case = tests.RigidJsonBoundary('test_actual_large_roundtrip_focus_and_chunk')
        case.setUp()
        try:
            case.geometry(24000)
            path, _ = case.produce()
            value['synthetic_witness'] = {
                'actors': 3, 'vertices_per_actor': 24000, 'polygons_per_actor': 8000,
                'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        finally:
            case.tearDown()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({key: value[key] for key in ('schema', 'tests_run', 'failures', 'errors', 'skipped', 'passed')}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
