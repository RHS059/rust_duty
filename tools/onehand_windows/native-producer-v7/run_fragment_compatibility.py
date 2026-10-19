"""Early stdlib-only actual-interpreter regression; never opens a native app."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
sys.path.insert(0, str(HERE))
import pinned_code
import test_fragment_ast
import verify_freeze

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    freeze = verify_freeze.verify()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_fragment_ast)
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    records = test_fragment_ast.data()['fragments']
    fragments = {}
    for name, rec in records.items():
        tree = ast.parse(rec['source'])
        raw_dump = ast.dump(tree, include_attributes=False)
        normalized_dump = pinned_code.audited_ast_dump(tree)
        fragments[name] = {
            'source_sha256': test_fragment_ast.sha(rec['source']),
            'unmodified_runtime_ast_sha256': test_fragment_ast.sha(raw_dump),
            'original_ast_sha256': rec['original_ast_sha256'],
            'audited_ast_sha256': test_fragment_ast.sha(normalized_dump),
            'original_check_passed': test_fragment_ast.sha(raw_dump) == rec['original_ast_sha256'],
            'audited_check_passed': test_fragment_ast.sha(normalized_dump) == rec['original_ast_sha256'],
        }
    passed = (result.wasSuccessful() and discovered == result.testsRun == 23 and len(result.skipped) == 0
              and len(fragments) == 34 and all(rec['audited_check_passed'] for rec in fragments.values()))
    value = {
        'schema': 'rust-duty-fragment-interpreter-regression/v1',
        'source_test_only': True,
        'native_execution_performed': False,
        'animation_proof': False,
        'actual_python_version': sys.version,
        'actual_python_implementation': sys.implementation.name,
        'actual_executable_sha256': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        'source_freeze': freeze,
        'audited_fragments_sha256': test_fragment_ast.FROZEN_SHA,
        'runtime_definition_fields': {name: list(getattr(ast, name)._fields) for name in ('FunctionDef', 'ClassDef')},
        'tests_run': result.testsRun,
        'expected_tests': 23,
        'tests_discovered': discovered,
        'audited_fragment_count': len(fragments),
        'all_audited_checks_passed': all(rec['audited_check_passed'] for rec in fragments.values()),
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'fragments': fragments,
        'passed': passed,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as output:
        json.dump(value, output, sort_keys=True, indent=2, allow_nan=False)
        output.write('\n')
    print(json.dumps({key: value[key] for key in ('schema', 'actual_python_version', 'tests_run', 'failures', 'errors', 'skipped', 'passed')}))
    return 0 if passed else 1

if __name__ == '__main__':
    raise SystemExit(main())
