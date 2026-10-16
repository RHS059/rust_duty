"""CPU-only tests. No bpy import, Blender process, network or private fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_r15_source_delta as d
import run_prone_r15_source_proof as runner


def key(frame, value, interpolation="BEZIER"):
    value = d.f32(value)
    return {"co": [float(frame), value], "co_ui": [float(frame), value],
            "handle_left": [float(frame) - .25, d.f32(value - .1)],
            "handle_right": [float(frame) + .25, d.f32(value + .1)],
            "interpolation": interpolation, "handle_left_type": "FREE", "handle_right_type": "FREE",
            "type": "KEYFRAME", "easing": "AUTO", "amplitude": .0, "back": .0, "period": .0,
            "select_control_point": True, "select_left_handle": False, "select_right_handle": False}


def curve(path='pose.bones["righthand_prop"].location', index=0):
    return {"path": path, "index": index, "extrapolation": "CONSTANT", "mute": False, "lock": False,
            "hide": False, "select": True, "color_mode": "AUTO_RAINBOW", "color": [0., 0., 0.],
            "auto_smoothing": "NONE", "group": "righthand_prop", "modifiers": [], "samples": [],
            "keys": [key(1, .4), key(5, .8), key(9, .6)]}


def record():
    return {**d.empty_action(), "curves": [curve(), curve('pose.bones["inherited_private_control"].location', 1)]}


DEFAULTS = {"location": [5.0, 8.0, -2.0], "rotation_euler": [.2, .3, .4]}


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.base = record(); self.target = copy.deepcopy(self.base)
        self.target["curves"][0]["keys"] = [key(1, .4), key(3, .7, "LINEAR"), key(5, .9, "LINEAR")]

    def make(self):
        return d.build_action_delta(self.base, self.target, DEFAULTS, "rig")

    def test_roundtrip_sparse_replace_add_remove(self):
        patch = self.make()
        self.assertEqual(d.apply_action_delta(self.base, patch, DEFAULTS), self.target)
        ops = patch["curves"][0]["keys"]
        self.assertEqual({v["op"] for v in ops}, {"remove", "replace", "add"})
        self.assertNotIn(1, [v["frame"] for v in ops])
        self.assertEqual(patch["curves"][1]["op"], "reference")
        self.assertNotIn("path", patch["curves"][1])
        self.assertNotIn("inherited_private_control", json.dumps(patch))
        self.assertEqual(self.base, record())

    def test_signed_zero_from_nonzero_delta_roundtrip_exact_hash(self):
        self.target = copy.deepcopy(self.base)
        changed = key(5, 0.0)
        changed["co"][1] = changed["co_ui"][1] = -0.0
        changed["handle_left"][1] = -0.0
        self.target["curves"][0]["keys"][1] = changed
        patch = self.make()
        flags = patch["curves"][0]["keys"][0]["zero_signs"]
        self.assertIn(["co", 1, -1], flags)
        self.assertIn(["handle_left", 1, -1], flags)
        result = d.apply_action_delta(self.base, json.loads(json.dumps(patch)), DEFAULTS)
        self.assertEqual(d.digest(result), d.digest(self.target))

    def test_only_zero_sign_change_is_not_lost_as_reference(self):
        self.base["curves"][0]["keys"][0] = key(1, 0.0)
        self.target = copy.deepcopy(self.base)
        self.target["curves"][0]["keys"][0]["co"][1] = -0.0
        self.target["curves"][0]["keys"][0]["co_ui"][1] = -0.0
        self.assertEqual(self.base, self.target)  # Ordinary Python equality is insufficient.
        self.assertFalse(d.exact_equal(self.base, self.target))
        patch = self.make()
        self.assertEqual(patch["curves"][0]["op"], "edit_curve")
        self.assertEqual(patch["curves"][0]["keys"][0]["op"], "replace")
        self.assertEqual(d.digest(d.apply_action_delta(self.base, patch, DEFAULTS)), d.digest(self.target))

    def test_new_camera_curve_zero_sign_is_preserved(self):
        target = d.empty_action(); target["curves"] = [curve("location", 0)]
        target["curves"][0]["keys"] = [key(1, -0.0)]
        patch = d.build_action_delta(d.empty_action(), target, DEFAULTS, "camera")
        result = d.apply_action_delta(d.empty_action(), patch, DEFAULTS)
        self.assertEqual(d.digest(result), d.digest(target))

    def test_zero_sign_cannot_zero_a_nonzero_value(self):
        patch = self.make()
        operation = next(op for op in patch["curves"][0]["keys"] if op["op"] == "replace")
        operation["zero_signs"] = [["co", 1, -1]]
        with self.assertRaisesRegex(ValueError, "cannot change nonzero"):
            d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_redacted_curve_diagnostic_identifies_field_without_values(self):
        patch = self.make()
        operation = next(op for op in patch["curves"][0]["keys"] if op["op"] == "replace")
        operation["settings"]["period"] = 1234567.0
        with self.assertRaises(ValueError) as caught:
            d.apply_action_delta(self.base, patch, DEFAULTS, diagnostic_target=self.target)
        message = str(caught.exception)
        self.assertIn("role=rig", message)
        self.assertIn(".period", message)
        self.assertNotIn("1234567", message)
        self.assertIn("values redacted", message)

    def test_signed_zero_difference_diagnostic(self):
        self.assertIn("[1]", d.first_difference([0.0, -0.0], [0.0, 0.0]))
        self.assertNotIn("-0.0", d.first_difference([0.0, -0.0], [0.0, 0.0]))

    def test_legacy_fingerprint_uses_exact_order_handles_interpolation(self):
        before = d.fingerprint(self.base)
        for edit in (lambda r: r["curves"].reverse(),
                     lambda r: r["curves"][0]["keys"][0]["handle_left"].__setitem__(1, 99.0),
                     lambda r: r["curves"][0]["keys"][0].__setitem__("interpolation", "LINEAR")):
            other = copy.deepcopy(self.base); edit(other)
            self.assertNotEqual(before, d.fingerprint(other))

    def test_complete_hash_includes_handle_types_and_curve_settings(self):
        other = copy.deepcopy(self.base)
        other["curves"][0]["keys"][0]["handle_left_type"] = "AUTO"
        self.assertEqual(d.fingerprint(other), d.fingerprint(self.base))
        self.assertNotEqual(d.complete_fingerprint(other), d.complete_fingerprint(self.base))

    def test_new_curve_uses_private_object_default_as_local_origin(self):
        camera = d.empty_action(); camera["curves"] = [curve("location")]
        camera["curves"][0]["keys"] = [key(1, 5.5), key(9, 4.5)]
        patch = d.build_action_delta(d.empty_action(), camera, DEFAULTS, "camera")
        self.assertEqual(patch["curves"][0]["keys"][0]["delta"]["co"], [0., .5])
        self.assertEqual(d.apply_action_delta(d.empty_action(), patch, DEFAULTS), camera)
        changed = copy.deepcopy(DEFAULTS); changed["location"][0] += .1
        with self.assertRaises(ValueError): d.apply_action_delta(d.empty_action(), patch, changed)

    def test_added_rig_comotion_curve_appends_without_reordering(self):
        self.target["curves"].append(curve("rotation_euler", 2))
        patch = self.make()
        self.assertEqual(patch["curves"][-1]["op"], "add_curve")
        self.assertEqual(d.apply_action_delta(self.base, patch, DEFAULTS), self.target)

    def test_forbidden_curve_changes_rejected(self):
        self.target["curves"][1]["keys"][0]["co"][1] = 2.0
        self.target["curves"][1]["keys"][0]["co_ui"][1] = 2.0
        with self.assertRaisesRegex(ValueError, "allowlist"): self.make()

    def test_new_private_bone_curve_rejected(self):
        self.target["curves"].append(curve('pose.bones["clavicle_l"].location'))
        with self.assertRaisesRegex(ValueError, "co-motion"): self.make()

    def test_foreign_axis_rejected(self):
        self.target["curves"].append(curve("location", 3))
        with self.assertRaisesRegex(ValueError, "axis"): self.make()

    def test_modified_baseline_rejected(self):
        patch = self.make(); self.base["curves"][0]["mute"] = True
        with self.assertRaisesRegex(ValueError, "baseline"): d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_duplicate_operations_rejected(self):
        patch = self.make(); patch["curves"][0]["keys"].append(patch["curves"][0]["keys"][0])
        with self.assertRaisesRegex(ValueError, "duplicate key"): d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_omitted_inherited_curve_rejected(self):
        patch = self.make(); patch["curves"].pop()
        with self.assertRaisesRegex(ValueError, "omitted"): d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_reference_cannot_smuggle_private_payload(self):
        patch = self.make(); patch["curves"][1]["keys"] = self.base["curves"][1]["keys"]
        with self.assertRaisesRegex(ValueError, "embeds"): d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_unknown_top_level_field_rejected(self):
        patch = self.make(); patch["mesh_vertices"] = [0., 0., 0.]
        with self.assertRaisesRegex(ValueError, "unexpected"): d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_non_finite_and_non_grid_inputs_rejected(self):
        for frame in (float("nan"), 3.00001, 70.0):
            target = copy.deepcopy(self.target)
            target["curves"][0]["keys"][1]["co"][0] = frame
            target["curves"][0]["keys"][1]["co_ui"][0] = frame
            with self.assertRaises(ValueError): d.build_action_delta(self.base, target, DEFAULTS, "rig")

    def test_removal_requires_correct_precondition(self):
        patch = self.make(); patch["curves"][0]["keys"][0]["before_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "precondition"): d.apply_action_delta(self.base, patch, DEFAULTS)

    def test_modifiers_and_sampled_curves_fail_closed(self):
        for field in ("modifiers", "samples"):
            target = copy.deepcopy(self.target); target["curves"][0][field] = [{"unreviewed": True}]
            with self.assertRaisesRegex(ValueError, "modifiers/samples"):
                d.build_action_delta(self.base, target, DEFAULTS, "rig")

    def test_random_float32_corrections_roundtrip_exact_hash(self):
        random.seed(20261016)
        for _ in range(50):
            target = copy.deepcopy(self.base)
            target["curves"][0]["keys"] = [key(1 + i / 8, random.uniform(-2., 2.), "LINEAR") for i in range(65)]
            patch = d.build_action_delta(self.base, target, DEFAULTS, "rig")
            actual = d.apply_action_delta(self.base, json.loads(json.dumps(patch)), DEFAULTS)
            self.assertEqual(d.digest(actual), d.digest(target))

    def test_canonical_probe_clock_matches_pinned_1944_hash(self):
        self.assertEqual(len(d.probe_times()), 1944)
        self.assertTrue(all(35 + i / 128 in d.probe_times() for i in range(1281)))
        retained = Path(__file__).resolve().parents[3] / "recovery/prone-r15-author-plan/probe-times.json"
        if retained.is_file(): self.assertEqual(d.probe_times(), json.loads(retained.read_text()))

    def test_fresh_writes_never_overwrite_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipt.json"; d.write_fresh_json(path, {"ok": True})
            with self.assertRaises(FileExistsError): d.write_fresh_json(path, {"ok": False})
            self.assertEqual(d.load_json(path), {"ok": True})
            path.write_text('{"x": NaN}')
            with self.assertRaises(ValueError): d.load_json(path)
            path.write_text('{"x": 1, "x": 2}')
            with self.assertRaisesRegex(ValueError, "duplicate"): d.load_json(path)


class NativePreparationTests(unittest.TestCase):
    def test_native_command_is_serialized_headless_and_scripts_disabled(self):
        command = runner.native_command("/example/blender", ["extract", "--base", "private.blend"])
        self.assertIn("--background", command); self.assertIn("--disable-autoexec", command)
        self.assertIn("--factory-startup", command); self.assertIn("--python-exit-code", command)
        self.assertEqual(command[command.index("--threads") + 1], "1")
        self.assertNotIn("--render-frame", command)

    def test_existing_lock_not_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "owner.lock"; lock.write_text("owner")
            with self.assertRaises(FileExistsError):
                with runner.exclusive_lock(lock): self.fail("entered occupied lock")
            self.assertEqual(lock.read_text(), "owner")

    def test_owned_lock_released_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "owner.lock"
            with self.assertRaises(RuntimeError):
                with runner.exclusive_lock(lock): raise RuntimeError("test")
            self.assertFalse(lock.exists())

    def test_preparation_does_not_import_bpy(self):
        self.assertNotIn("bpy", sys.modules)



def evidence_fixture():
    h = "a" * 64
    static = {k: h for k in d.STATIC_CATEGORIES}
    producer = {"prone_r15_source_delta.py": h, "prone_r15_source_native.py": h}
    complete = {"rig": "b" * 64, "camera": "c" * 64}
    recipe = {"schema": d.SCHEMA, "base_sha256": d.BASE_SHA, "approved_source_sha256": d.APPROVED_SHA,
              "base_action": d.BASE_ACTION, "rig_action": d.RIG_ACTION, "camera_action": d.CAMERA_ACTION,
              "reset_action": d.RESET_ACTION, "reset_fingerprint": d.RESET_FINGERPRINT,
              "clock": {"frames": 69, "fps": 60}, "static_hashes": static, "base_actions_sha256": h,
              "producer_sha256": producer,
              "scope": "original authored key deltas; existing private base supplied separately; no geometry or inherited curve payload",
              "actions": {role: {"role": role, "target_fingerprint": target,
                                  "base_fingerprint": d.BASE_FINGERPRINT if role == "rig" else d.fingerprint(d.empty_action()),
                                  "target_complete_sha256": complete[role]}
                          for role, target in (("rig", d.RIG_FINGERPRINT), ("camera", d.CAMERA_FINGERPRINT))}}
    replay = {"schema": "rust-duty-prone-r15-source-replay/v1", "passed": True, "fresh_reopen_passed": True,
              "saved_default_bindings_unchanged": True, "source_byte_identity_with_approved": False,
              "generated_source_sha256": "d" * 64, "approved_source_sha256": d.APPROVED_SHA,
              "base_sha256": d.BASE_SHA, "prior_actions_preserved": 112,
              "created_actions": [d.RIG_ACTION, d.CAMERA_ACTION], "rig_action_fingerprint": d.RIG_FINGERPRINT,
              "camera_action_fingerprint": d.CAMERA_FINGERPRINT, "complete_action_fingerprints": complete,
              "blender_version": d.BLENDER_VERSION, "static_hashes": static, "producer_sha256": producer,
              "delta_sha256": "e" * 64}
    rows = [{"frame": f, "bones_world_sha256": h, "rig_world_sha256": h, "camera_world_sha256": h,
             "actors_world_sha256": h, "skins": [{"name": name, "vertices": 50, "sha256": h}
                                                 for name in ("skin-a", "skin-b", "skin-c")]}
            for f in d.probe_times()]
    approved = {"schema": "rust-duty-prone-r15-paired-witness/v1", "kind": "approved", "source_sha256": d.APPROVED_SHA,
                "approved_source_sha256": d.APPROVED_SHA,
                "action_fingerprints": {d.RIG_ACTION: d.RIG_FINGERPRINT, d.CAMERA_ACTION: d.CAMERA_FINGERPRINT},
                "complete_action_fingerprints": complete, "static_hashes": static, "producer_sha256": producer,
                "blender_version": d.BLENDER_VERSION, "source_saved": False, "rendered": False,
                "motion": {"sample_count": 1944, "rows": rows, "times_sha256": d.digest(d.probe_times()),
                           "bone_count": 148, "bone_order_sha256": h,
                           "actors": ["hk416_weapon", "hk416_magazine", "hk416_magazine_outgoing"],
                           "canonical_reset_action": d.RESET_ACTION,
                           "numeric_contract": "strict little-endian float64 bytes; no quantization; same Blender 4.3.2 evaluation"}}
    regenerated = copy.deepcopy(approved)
    regenerated["kind"] = "regenerated"; regenerated["source_sha256"] = replay["generated_source_sha256"]
    return approved, regenerated, replay, recipe


class WitnessComparisonTests(unittest.TestCase):
    def setUp(self): self.evidence = evidence_fixture()

    def compare(self): return runner.compare_witnesses(*self.evidence)

    def test_complete_pair_evidence_passes_with_distinct_identity(self):
        result = self.compare()
        self.assertTrue(result["evaluated_pair_equivalence_proved"])
        self.assertFalse(result["source_byte_identity_with_approved"])
        self.assertFalse(result["runtime_equivalence_proved"])
        self.assertNotEqual(result["generated_source_sha256"], result["approved_source_sha256"])

    def test_original_sha_cannot_label_regenerated_bytes(self):
        self.evidence[1]["source_sha256"] = d.APPROVED_SHA
        self.evidence[2]["generated_source_sha256"] = d.APPROVED_SHA
        with self.assertRaisesRegex(ValueError, "identity"): self.compare()

    def test_camera_difference_fails(self):
        self.evidence[1]["motion"]["rows"][700]["camera_world_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "paired-motion"): self.compare()

    def test_skin_difference_fails(self):
        self.evidence[1]["motion"]["rows"][50]["skins"][2]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "paired-motion"): self.compare()

    def test_half_tick_omission_fails(self):
        self.evidence[1]["motion"]["rows"].pop(700)
        with self.assertRaisesRegex(ValueError, "incomplete"): self.compare()

    def test_swapped_sample_times_fail(self):
        rows = self.evidence[1]["motion"]["rows"]
        rows[100], rows[101] = rows[101], rows[100]
        with self.assertRaisesRegex(ValueError, "times"): self.compare()

    def test_hand_pose_only_witness_fails(self):
        for witness in self.evidence[:2]: witness["motion"]["bone_count"] = 2
        with self.assertRaisesRegex(ValueError, "bone or actor"): self.compare()

    def test_bone_order_difference_fails(self):
        self.evidence[1]["motion"]["bone_order_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "paired-motion"): self.compare()

    def test_full_curve_semantic_difference_fails(self):
        self.evidence[1]["complete_action_fingerprints"]["rig"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "complete witness"): self.compare()

    def test_unverified_reopen_fails(self):
        self.evidence[2]["fresh_reopen_passed"] = False
        with self.assertRaisesRegex(ValueError, "fresh source"): self.compare()

    def test_missing_nonaction_category_fails(self):
        self.evidence[3]["static_hashes"].pop("drivers")
        with self.assertRaisesRegex(ValueError, "static preservation"): self.compare()

    def test_altered_producer_fails(self):
        self.evidence[1]["producer_sha256"]["prone_r15_source_native.py"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "producer code"): self.compare()

    def test_rounded_hash_contract_cannot_pass_as_exact(self):
        for witness in self.evidence[:2]: witness["motion"]["numeric_contract"] = "rounded 1e-5"
        with self.assertRaisesRegex(ValueError, "relaxed"): self.compare()

    def test_malformed_hash_fails(self):
        self.evidence[1]["motion"]["rows"][0]["rig_world_sha256"] = "z" * 64
        with self.assertRaisesRegex(ValueError, "malformed"): self.compare()

    def test_readonly_flag_required(self):
        self.evidence[1]["source_saved"] = True
        with self.assertRaisesRegex(ValueError, "read-only"): self.compare()


if __name__ == "__main__": unittest.main()

