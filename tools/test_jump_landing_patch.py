"""Pure synthetic coverage for the real in-memory r8 Action mutation helper.

No Blender, asset files, renderer, encoder, subprocess, or network is needed.
Synthetic full-record digests replace the production pins only inside fixtures;
these tests do not establish that the real Blender source has been executed.
"""

import ast
import copy
import hashlib
import inspect
import json
from unittest import TestCase, main, mock

import jump_landing_patch as patch


BEFORE = {
    5.0: ((5.0, 0.047564517706632614),
          (4.666666507720947, 0.04718858748674393),
          (5.333333492279053, 0.0479404479265213)),
    6.0: ((6.0, 0.06944283097982407),
          (5.666666507720947, 0.06229608505964279),
          (6.333333492279053, 0.07658957690000534)),
}
APPROVED = {
    5.0: ((5.0, 0.05365120619535446),
          (4.666666507720947, 0.04917992651462555),
          (5.333333492279053, 0.058122482150793076)),
    6.0: ((6.0, 0.07077010720968246),
          (5.666666507720947, 0.06451913714408875),
          (6.333333492279053, 0.07702107727527618)),
}


class Vector(list):
    @property
    def y(self):
        return self[1]

    @y.setter
    def y(self, value):
        self[1] = value


class Key:
    def __init__(self, coordinates):
        self.co = Vector(coordinates[0])
        self.handle_left = coordinates[1]
        self.handle_right = coordinates[2]
        self.handle_left_type = "FREE"
        self.handle_right_type = "FREE"
        self.interpolation = "BEZIER"
        self.easing = "AUTO"
        self.amplitude = 0.8
        self.back = 1.7015800476074219
        self.period = 4.099999904632568

    @property
    def handle_left(self):
        return self._left

    @handle_left.setter
    def handle_left(self, value):
        self._left = Vector(value)

    @property
    def handle_right(self):
        return self._right

    @handle_right.setter
    def handle_right(self, value):
        self._right = Vector(value)


class Curve:
    def __init__(self, path, index, keys):
        self.data_path = path
        self.array_index = index
        self.extrapolation = "CONSTANT"
        self.mute = False
        self.keyframe_points = keys
        self.update_calls = 0

    def update(self):
        self.update_calls += 1


class Action:
    def __init__(self, name, curves, owner):
        self.name = name
        self.fcurves = curves
        self.owner = owner
        self.use_fake_user = False
        self.copy_calls = 0

    def copy(self):
        self.copy_calls += 1
        candidate = Action(self.name + ".001", copy.deepcopy(self.fcurves), self.owner)
        self.owner.append(candidate)
        return candidate


class Actions(list):
    def __getitem__(self, item):
        if isinstance(item, str):
            for action in self:
                if action.name == item:
                    return action
            raise KeyError(item)
        return super().__getitem__(item)


def canonical_digest(action):
    """Independent whole-record path checks the production streaming digest."""
    return hashlib.sha256(json.dumps(patch.action_record(action), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def make_actions():
    actions = Actions()
    keys = [Key(((4.0, 0.01), (3.5, 0.0), (4.5, 0.02))),
            Key(BEFORE[5.0]), Key(BEFORE[6.0]),
            Key(((7.0, 0.09), (6.5, 0.08), (7.5, 0.10)))]
    curves = [Curve(patch.CURVE_PATH, patch.CURVE_INDEX, keys),
              Curve('pose.bones["righthand_prop"].location', 0,
                    [Key(((1.0, 0.0), (0.0, 0.0), (2.0, 0.0)))])]
    actions.append(Action(patch.SOURCE_ACTION, curves, actions))
    actions.append(Action("jump_takeoff_r7", copy.deepcopy(curves[1:]), actions))
    actions.append(Action("jump_air_r7", copy.deepcopy(curves[1:]), actions))
    return actions


class JumpLandingPatchTests(TestCase):
    def setUp(self):
        self.actions = make_actions()
        self.source = self.actions[patch.SOURCE_ACTION]
        self.source_hash = canonical_digest(self.source)
        expected = Action("expected", copy.deepcopy(self.source.fcurves), None)
        for key in expected.fcurves[0].keyframe_points:
            if key.co[0] in APPROVED:
                co, left, right = APPROVED[key.co[0]]
                key.co = Vector(co)
                key.handle_left, key.handle_right = left, right
        self.candidate_hash = canonical_digest(expected)
        self.pins = mock.patch.multiple(
            patch, ORIGINAL_ACTION_COUNT=3, ACTION_CURVE_COUNT=2,
            SOURCE_ACTION_SHA256=self.source_hash,
            CANDIDATE_ACTION_SHA256=self.candidate_hash,
        )
        self.pins.start()
        self.addCleanup(self.pins.stop)

    def apply(self):
        return patch.apply_patch(self.actions, patch.SOURCE_SHA256)

    def test_real_mutation_matches_exact_approved_recipe_and_preserves_originals(self):
        originals = [(action, action.name, canonical_digest(action)) for action in self.actions]
        source_record = patch.action_record(self.source)
        result = self.apply()
        self.assertEqual(result, patch.PATCH_PROVENANCE)
        self.assertIsNot(result, patch.PATCH_PROVENANCE)
        self.assertEqual(result, json.loads(json.dumps(result)))
        self.assertEqual(len(self.actions), 4)
        candidate = self.actions[patch.CANDIDATE_ACTION]
        self.assertIsNot(candidate, self.source)
        self.assertTrue(candidate.use_fake_user)
        self.assertFalse(self.source.use_fake_user)
        self.assertEqual(candidate.fcurves[0].update_calls, 1)
        self.assertEqual(self.source.fcurves[0].update_calls, 0)
        self.assertEqual(canonical_digest(candidate), self.candidate_hash)
        for action, name, original_hash in originals:
            self.assertIs(self.actions[name], action)
            self.assertEqual(canonical_digest(action), original_hash)
        differences = []
        for old_curve, new_curve in zip(source_record, patch.action_record(candidate)):
            for old_key, new_key in zip(old_curve["points"], new_curve["points"]):
                if old_key != new_key:
                    differences.append((new_curve["path"], new_curve["index"], new_key["co"][0]))
                    self.assertEqual(set(key for key in old_key if old_key[key] != new_key[key]),
                                     {"co", "left", "right"})
        self.assertEqual(differences, [(patch.CURVE_PATH, 1, 5.0), (patch.CURVE_PATH, 1, 6.0)])
        for key in candidate.fcurves[0].keyframe_points:
            if key.co[0] in APPROVED:
                self.assertEqual((tuple(key.co), tuple(key.handle_left), tuple(key.handle_right)),
                                 APPROVED[key.co[0]])
        result["source_sha256"] = "caller edit"
        self.assertEqual(patch.PATCH_PROVENANCE["source_sha256"], patch.SOURCE_SHA256)

    def test_streaming_hash_matches_exact_canonical_json_including_curve_order(self):
        self.assertEqual(patch.action_sha256(self.source), canonical_digest(self.source))
        self.source.fcurves.reverse()
        self.assertEqual(patch.action_sha256(self.source), canonical_digest(self.source))
        self.assertNotEqual(patch.action_sha256(self.source), self.source_hash)
        self.assertEqual(patch.action_sha256(Action("empty", [], None)),
                         hashlib.sha256(b"[]").hexdigest())

    def test_canonical_record_schema_matches_review_serializer(self):
        self.assertEqual(patch.curve_record(self.source.fcurves[1]), {
            "path": 'pose.bones["righthand_prop"].location',
            "index": 0,
            "extrapolation": "CONSTANT",
            "mute": False,
            "points": [{
                "co": [1.0, 0.0],
                "left": [0.0, 0.0],
                "right": [2.0, 0.0],
                "left_type": "FREE",
                "right_type": "FREE",
                "interpolation": "BEZIER",
                "easing": "AUTO",
                "amplitude": 0.8,
                "back": 1.7015800476074219,
                "period": 4.099999904632568,
            }],
        })

    def test_production_pins_and_provenance_are_explicit(self):
        provenance = patch.PATCH_PROVENANCE
        self.assertEqual(provenance["source_sha256"],
                         "a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b")
        self.assertEqual(provenance["approved_candidate_sha256"],
                         "db30e98a8d63cb4e9075ec2930cd5d34d385780ab374e1d6386f42d1e0fe7b3b")
        self.assertEqual(provenance["source_action_sha256"],
                         "c492d72146c1d23e054599137e40c936c1bb2b2766862d858af8316f092d6bda")
        self.assertEqual(provenance["candidate_action_sha256"],
                         "6e8daff6b1e0d81780336733cc397c965d65c2a9b5eb908cbeb5346a51965d56")
        self.assertEqual(provenance["original_action_count"], 103)
        self.assertEqual(provenance["action_curve_count"], 775)
        self.assertEqual(provenance["changed_keys"], "5,6")
        self.assertTrue(all(isinstance(value, (str, int, bool, float, type(None)))
                            for value in provenance.values()))

    def test_source_pin_failures_happen_before_copy(self):
        for wrong_hash in (None, "", "a" * 64, patch.SOURCE_SHA256.upper(),
                           patch.APPROVED_CANDIDATE_SHA256):
            with self.subTest(wrong_hash=wrong_hash):
                with self.assertRaisesRegex(patch.PatchValidationError, "Pinned source"):
                    patch.apply_patch(self.actions, wrong_hash)
        self.assertEqual(self.source.copy_calls, 0)
        self.assertEqual(len(self.actions), 3)

    def test_preexisting_candidate_is_never_reused_or_overwritten(self):
        existing = Action(patch.CANDIDATE_ACTION, [], self.actions)
        self.actions.append(existing)
        with self.assertRaisesRegex(patch.PatchValidationError, "already exists"):
            self.apply()
        self.assertIs(self.actions[-1], existing)
        self.assertEqual(self.source.copy_calls, 0)

    def test_second_application_fails_closed(self):
        self.apply()
        with self.assertRaisesRegex(patch.PatchValidationError, "already exists"):
            self.apply()
        self.assertEqual(self.source.copy_calls, 1)
        self.assertEqual(len(self.actions), 4)

    def test_wrong_original_action_count(self):
        self.actions.pop()
        with self.assertRaisesRegex(patch.PatchValidationError, "Original Action count"):
            self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_duplicate_original_action_names(self):
        self.actions[-1].name = self.actions[-2].name
        with self.assertRaisesRegex(patch.PatchValidationError, "unique names"):
            self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_missing_source_action(self):
        self.source.name = "unexpected"
        with self.assertRaisesRegex(patch.PatchValidationError, "Missing pinned"):
            self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_wrong_curve_count(self):
        self.source.fcurves.pop()
        with self.assertRaisesRegex(patch.PatchValidationError, "curve count"):
            self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_wrong_full_source_action_hash(self):
        self.source.fcurves[1].mute = True
        with self.assertRaisesRegex(patch.PatchValidationError, "Source full Action"):
            self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_key_before_mismatch_is_a_separate_preflight_guard(self):
        self.source.fcurves[0].keyframe_points[2].handle_left.y += 0.01
        with mock.patch.object(patch, "SOURCE_ACTION_SHA256", canonical_digest(self.source)):
            with self.assertRaisesRegex(patch.PatchValidationError, "before-record mismatch"):
                self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_missing_and_duplicate_target_keys_are_rejected(self):
        keys = self.source.fcurves[0].keyframe_points
        keys[1].co[0] = 5.01
        with mock.patch.object(patch, "SOURCE_ACTION_SHA256", canonical_digest(self.source)):
            with self.assertRaisesRegex(patch.PatchValidationError, "exactly one landing key"):
                self.apply()
        keys[1].co[0] = 5.0
        keys.append(copy.deepcopy(keys[1]))
        with mock.patch.object(patch, "SOURCE_ACTION_SHA256", canonical_digest(self.source)):
            with self.assertRaisesRegex(patch.PatchValidationError, "exactly one landing key"):
                self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_missing_and_duplicate_target_curves_are_rejected(self):
        self.source.fcurves[0].array_index = 2
        with mock.patch.object(patch, "SOURCE_ACTION_SHA256", canonical_digest(self.source)):
            with self.assertRaisesRegex(patch.PatchValidationError, "exactly one landing rotation"):
                self.apply()
        self.source.fcurves[0].array_index = 1
        self.source.fcurves[1] = copy.deepcopy(self.source.fcurves[0])
        with mock.patch.object(patch, "SOURCE_ACTION_SHA256", canonical_digest(self.source)):
            with self.assertRaisesRegex(patch.PatchValidationError, "exactly one landing rotation"):
                self.apply()
        self.assertEqual(self.source.copy_calls, 0)

    def test_recipe_validates_both_keys_before_any_mutation(self):
        self.source.fcurves[0].keyframe_points[2].co.y += 0.01
        before = canonical_digest(self.source)
        with self.assertRaisesRegex(patch.PatchValidationError, "before-record mismatch"):
            patch._apply_key_recipe(self.source)
        self.assertEqual(canonical_digest(self.source), before)
        self.assertEqual(self.source.fcurves[0].update_calls, 0)

    def test_wrong_candidate_hash_rejects_and_removes_derived_copy(self):
        with mock.patch.object(patch, "CANDIDATE_ACTION_SHA256", "0" * 64):
            with self.assertRaisesRegex(patch.PatchValidationError, "Candidate full Action"):
                self.apply()
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(canonical_digest(self.source), self.source_hash)

    def test_update_must_preserve_exact_approved_key_values(self):
        def corrupt_update(curve):
            curve.keyframe_points[1].handle_right.y += 0.01
        with mock.patch.object(Curve, "update", corrupt_update):
            with self.assertRaisesRegex(patch.PatchValidationError, "differs from approved recipe"):
                self.apply()
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(canonical_digest(self.source), self.source_hash)

    def test_neighboring_key_changes_during_update_fail_full_hash(self):
        def corrupt_boundary(curve):
            curve.keyframe_points[0].handle_right.y += 0.01
        with mock.patch.object(Curve, "update", corrupt_boundary):
            with self.assertRaisesRegex(patch.PatchValidationError, "Candidate full Action"):
                self.apply()
        self.assertEqual(len(self.actions), 3)
        self.assertEqual(canonical_digest(self.source), self.source_hash)

    def test_original_action_mutation_is_detected_even_with_correct_candidate(self):
        def corrupt_original(curve):
            self.actions["jump_air_r7"].fcurves[0].mute = True
        with mock.patch.object(Curve, "update", corrupt_original):
            with self.assertRaisesRegex(patch.PatchValidationError, "Original Action changed: jump_air_r7"):
                self.apply()
        self.assertEqual(len(self.actions), 3)

    def test_original_action_identity_replacement_is_detected(self):
        def replace_original(curve):
            old = self.actions[-2]
            self.actions[-2] = Action(old.name, copy.deepcopy(old.fcurves), self.actions)
        with mock.patch.object(Curve, "update", replace_original):
            with self.assertRaisesRegex(patch.PatchValidationError, "Original Action changed"):
                self.apply()
        self.assertEqual(len(self.actions), 3)

    def test_copy_cannot_return_original_or_leave_it_removed(self):
        with mock.patch.object(self.source, "copy", return_value=self.source):
            with self.assertRaisesRegex(patch.PatchValidationError, "reused an original"):
                self.apply()
        self.assertIs(self.actions[patch.SOURCE_ACTION], self.source)
        self.assertEqual(len(self.actions), 3)

    def test_copy_must_match_source_and_register_one_action(self):
        real_copy = self.source.copy
        def wrong_copy():
            candidate = real_copy()
            candidate.fcurves[1].mute = True
            return candidate
        with mock.patch.object(self.source, "copy", side_effect=wrong_copy):
            with self.assertRaisesRegex(patch.PatchValidationError, "copy does not match"):
                self.apply()
        self.assertEqual(len(self.actions), 3)
        detached = Action("detached", copy.deepcopy(self.source.fcurves), self.actions)
        with mock.patch.object(self.source, "copy", return_value=detached):
            with self.assertRaisesRegex(patch.PatchValidationError, "exactly one datablock"):
                self.apply()
        self.assertEqual(len(self.actions), 3)

    def test_runtime_helper_has_no_asserts_or_file_network_render_operations(self):
        tree = ast.parse(inspect.getsource(patch))
        self.assertFalse(any(isinstance(node, ast.Assert) for node in ast.walk(tree)))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                   for alias in node.names}
        self.assertEqual(imports, {"hashlib", "json"})
        self.assertFalse(any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)))
        forbidden = {"open", "read", "write", "read_bytes", "write_bytes", "read_text", "write_text",
                     "save", "save_as_mainfile", "render", "system", "popen", "exec", "eval",
                     "urlopen", "request", "connect", "__import__"}
        calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
                 for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, (ast.Name, ast.Attribute))}
        self.assertFalse(calls & forbidden)
        with mock.patch("builtins.open", side_effect=AssertionError("No file access")):
            self.apply()


if __name__ == "__main__":
    main()
