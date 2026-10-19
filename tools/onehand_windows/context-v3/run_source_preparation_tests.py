"""Run available recovered source checks with explicit, non-passing omissions.

The original 132-test historical suite is NOT complete in this restored scope.
Missing original fixtures are recorded, never regenerated or replaced by mocks.
"""
import json
from pathlib import Path
import sys
import unittest
import test_candidate_context as context
import test_metadata_projection as metadata
import test_windows_addon_profile as profile
import test_reconstruction_and_preservation as reconstruction

OMITTED = {
    'test_candidate_context.ContextTests.test_transport_readonly_verifier_pin_and_missing_evidence':
        'Historical process-v1 PINS and owned_process.py are absent from the immutable published tree.',
    'test_candidate_context.AssemblerIntegrationTests.test_explicit_generated_identity_with_unchanged_small_stream':
        'Exact original test_assemble_runtime.py fixture is absent from the immutable published tree.',
}
MISSING_DYNAMIC_SUITE = {'suite': 'test_assemble_runtime.StreamAssemblyTests', 'historical_tests': 73,
    'source_sha256': '5b6dce136fac5d681b96d87be74c703ded58dfee2de20fe9c615aeb720b97159',
    'reason': 'Exact original fixture is unavailable; no synthetic replacement is used.'}


def run():
    loader = unittest.TestLoader(); suite = unittest.TestSuite()
    classes = (context.ContextTests, context.AddonTests, context.AssemblerIntegrationTests,
               metadata.MetadataProjectionTests, profile.WindowsAddonProfileTests,
               reconstruction.ReconstructionAndPreservationTests)
    for cls in classes:
        for test in loader.loadTestsFromTestCase(cls):
            if test.id() not in OMITTED: suite.addTest(test)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {'schema': 'rust-duty-context-source-preparation-tests/v1',
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': len(result.skipped), 'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        'available_tests_passed': result.wasSuccessful(), 'complete_historical_suite_rerun': False,
        'explicit_omissions': OMITTED, 'missing_dynamic_suite': MISSING_DYNAMIC_SUITE,
        'native_execution': False, 'animation_proof': False}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == '__main__':
    result = run()
    sys.exit(0 if result['available_tests_passed'] else 1)
