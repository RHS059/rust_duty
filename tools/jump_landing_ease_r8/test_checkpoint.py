"""Asset-free checks of the actual original math, entry guard and frozen scope."""
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

if __package__:
    from . import run_authoring
else:
    import run_authoring

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / 'correction.json').read_text())
PROVENANCE = json.loads((HERE / 'provenance.json').read_text())
AUTHOR = (HERE / 'refine_jump_landing.py').read_text()
AUTHOR_TREE = ast.parse(AUTHOR)


class CorrectionScope(unittest.TestCase):
    def test_original_author_script_is_byte_preserved(self):
        self.assertEqual(hashlib.sha256((HERE / 'refine_jump_landing.py').read_bytes()).hexdigest(), PROVENANCE['original_authoring_script']['sha256'])
        self.assertEqual(PROVENANCE['original_authoring_script']['sha256'], 'fd5e7933660705765a686e0b745b16160b331dc0b4b8795114d5edf99e9152ee')

    def test_one_curve_and_exact_two_keys(self):
        self.assertEqual(PLAN['changed_curves'], [dict(path='pose.bones["righthand_prop"].rotation_euler', index=1, changed_frames=[5.0, 6.0])])
        self.assertEqual([row['frame'] for row in PLAN['changes']], [5, 6])
        self.assertEqual([row['native_frame'] for row in PLAN['changes']], [4071, 4072])
        for row in PLAN['changes']:
            for field in ('co', 'left', 'right'):
                self.assertEqual(row['before'][field][0], row['after'][field][0])

    def test_frozen_coordinate_values_and_small_adjustments(self):
        self.assertEqual([row['after']['co'][1] for row in PLAN['changes']], [0.05365120619535446, 0.07077010720968246])
        for row in PLAN['changes']:
            delta = math.degrees(row['after']['co'][1] - row['before']['co'][1])
            self.assertAlmostEqual(delta, row['rotation_y_delta_degrees'], places=5)
            self.assertLess(abs(delta), 1.0)

    def test_endpoints_and_landing_playback_mapping(self):
        self.assertEqual(PLAN['preserved_boundary_frames'], [4, 7])
        self.assertEqual(PLAN['preserved_trough_frame'], 12)
        self.assertEqual(PLAN['preserved_endpoint_frame'], 29)
        self.assertEqual(PLAN['action_frames_inclusive'], [1, 29])
        self.assertEqual(PLAN['reference_native_frames_inclusive'], [4067, 4095])
        self.assertEqual(PLAN['fps'], [60, 1])
        self.assertTrue(PLAN['all_frames_in_playback'])
        self.assertEqual(PLAN['closure_only_frames'], 0)

    def test_exact_source_and_candidate_identity(self):
        self.assertEqual(PLAN['source_sha256'], 'a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b')
        self.assertEqual(PLAN['candidate_sha256'], 'db30e98a8d63cb4e9075ec2930cd5d34d385780ab374e1d6386f42d1e0fe7b3b')
        self.assertEqual((PLAN['source_action'], PLAN['candidate_action']), ('jump_land_r7', 'jump_land_r8_ease_candidate'))

    def test_historical_invariants_are_explicit(self):
        report = json.loads((HERE / 'evidence/author-checks.json').read_text())
        self.assertEqual(report['sample_count'], 173)
        preservation = report['preservation']
        self.assertEqual(preservation['original_action_count'], 103)
        for key in ('all_original_actions_same_complete_curve_hash', 'other_774_candidate_curves_identical',
                    'root_translation_curves_identical', 'takeoff_air_actions_untouched',
                    'trough_f12_and_closure_f29_world_matrices_unchanged'):
            self.assertIs(preservation[key], True)
        for key in ('max_local_translation_delta', 'max_world_root_translation_delta', 'max_world_root_delta_outside_open_4_7'):
            self.assertEqual(preservation[key], 0)
        self.assertFalse(report['artistic_approval'])
        self.assertFalse(report['fbx_or_runtime_integration'])

    def test_original_author_and_reopen_do_not_render_or_upload(self):
        for name in ('refine_jump_landing.py', 'reopen_verify.py', 'run_authoring.py'):
            tree = ast.parse((HERE / name).read_text())
            calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
            self.assertFalse(any(call.startswith('bpy.ops.render.') for call in calls))
            self.assertFalse(any(call.startswith(('requests.', 'urllib.', 'httpx.')) for call in calls))
        self.assertIn('assert out.resolve()!=source.resolve()', AUTHOR)
        self.assertIn("assert not out.exists(),'Refuse to overwrite an existing candidate'", AUTHOR)
        self.assertEqual(AUTHOR.count('bpy.ops.wm.save_as_mainfile('), 1)

    def test_reopen_computation_functions_are_unchanged(self):
        source = (HERE / 'reopen_verify.py').read_text()
        actual = {node.name: hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest()
                  for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(actual, PROVENANCE['original_reopen_function_sha256'])

    def test_no_machine_specific_paths_or_assets_in_checkpoint(self):
        for path in HERE.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            self.assertNotIn(path.suffix, ('.blend', '.png', '.jpg', '.mp4', '.fbx', '.zip'))
            text = path.read_text()
            self.assertNotIn('/work' + 'space/', text)
            self.assertNotIn('/Us' + 'ers/', text)


class OriginalHermiteMath(unittest.TestCase):
    def setUp(self):
        # Compile only the actual pure target function, never the Blender module.
        node = next(node for node in AUTHOR_TREE.body if isinstance(node, ast.FunctionDef) and node.name == 'target')
        boundary = PLAN['target_boundary']
        namespace = dict(y0=boundary['angle4'], y1=boundary['angle7'], m0=boundary['slope4'], m1=boundary['slope7'])
        exec(compile(ast.Module(body=[copy.deepcopy(node)], type_ignores=[]), '<original target function>', 'exec'), namespace)
        self.target = namespace['target']
        self.boundary = boundary

    def test_both_original_endpoint_values_and_tangents(self):
        # Hermite tangent scaling can round by one floating-point ULP.
        for frame in (4, 7):
            actual = self.target(frame)
            expected = (self.boundary[f'angle{frame}'], self.boundary[f'slope{frame}'])
            for value, boundary in zip(actual, expected):
                self.assertAlmostEqual(value, boundary, places=12)

    def test_middle_targets_match_author_receipt(self):
        for row in PLAN['changes']:
            angle, slope = self.target(row['frame'])
            self.assertAlmostEqual(angle, row['target_angle'], places=11)
            self.assertAlmostEqual(slope, row['target_slope'], places=11)

    def test_reported_derivative_matches_numerical_slope(self):
        for frame in (4.1, 4.5, 5, 5.5, 6, 6.9):
            delta = 1e-5
            numeric = (self.target(frame + delta)[0] - self.target(frame - delta)[0]) / (2 * delta)
            self.assertAlmostEqual(numeric, self.target(frame)[1], places=8)


class EntryGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        self.output = self.root / 'new-output'
        self.source = self.inputs / 'synthetic-source.bin'
        self.source.write_bytes(b'Original synthetic fixture; not a private Blender asset.')
        self.script = self.root / 'synthetic-author.py'
        self.script.write_text('raise RuntimeError("This fixture must not execute")\n')
        self.provenance = dict(inputs=[dict(filename=self.source.name, sha256=run_authoring.sha(self.source))],
                               original_authoring_script=dict(path=self.script.name, sha256=run_authoring.sha(self.script)))
        patch = mock.patch.object(run_authoring, 'HERE', self.root)
        patch.start()
        self.addCleanup(patch.stop)

    def test_valid_control_returns_canonical_paths_without_writing(self):
        actual = run_authoring.validate_inputs(self.inputs, self.output, self.provenance)
        self.assertEqual(actual, (self.inputs.resolve(), self.output.resolve(), self.script))
        self.assertFalse(self.output.exists())

    def test_changed_input_is_rejected(self):
        self.source.write_bytes(b'Changed fixture')
        with self.assertRaisesRegex(ValueError, 'changed pinned input'):
            run_authoring.validate_inputs(self.inputs, self.output, self.provenance)

    def test_missing_input_is_rejected(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            run_authoring.validate_inputs(self.inputs, self.output, self.provenance)

    def test_changed_author_script_is_rejected(self):
        self.script.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'script hash mismatch'):
            run_authoring.validate_inputs(self.inputs, self.output, self.provenance)

    def test_existing_output_directory_or_file_is_rejected(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            run_authoring.validate_inputs(self.inputs, self.output, self.provenance)
        self.output.rmdir()
        self.output.write_text('existing evidence')
        with self.assertRaises(FileExistsError):
            run_authoring.validate_inputs(self.inputs, self.output, self.provenance)

    def test_optimized_python_is_rejected(self):
        code = 'import run_authoring; run_authoring.validate_inputs("inputs", "output", {})'
        result = subprocess.run([sys.executable, '-O', '-c', code], cwd=HERE, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires Python assertions', result.stderr)

    def test_output_created_after_validation_cannot_be_claimed(self):
        (self.root / 'provenance.json').write_text(json.dumps(self.provenance))
        validate = run_authoring.validate_inputs

        def concurrent_output(*args):
            result = validate(*args)
            self.output.mkdir()
            (self.output / 'prior-evidence.txt').write_text('preserve')
            return result

        open_source = mock.Mock()
        fake_bpy = SimpleNamespace(app=SimpleNamespace(version_string='4.3.2', background=True),
                                   ops=SimpleNamespace(wm=SimpleNamespace(open_mainfile=open_source)))
        with mock.patch.object(run_authoring, 'validate_inputs', side_effect=concurrent_output), \
                mock.patch.dict(sys.modules, {'bpy': fake_bpy}):
            with self.assertRaises(FileExistsError):
                run_authoring.main(['--inputs', str(self.inputs), '--output', str(self.output)])
        open_source.assert_not_called()
        self.assertEqual((self.output / 'prior-evidence.txt').read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
