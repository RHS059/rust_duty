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
import onehand_v6_source_delta as d
import run_onehand_v6_source_proof as runner


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

    def test_forbidden_curve_changes_rejected(self):
        self.target["curves"][1]["keys"][0]["co"][1] = 2.0
        self.target["curves"][1]["keys"][0]["co_ui"][1] = 2.0
        with self.assertRaisesRegex(ValueError, "allowlist"): self.make()

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
        for frame in (float("nan"), 3.00001, 97.0):
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

    def test_fresh_writes_never_overwrite_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "receipt.json"; d.write_fresh_json(path, {"ok": True})
            with self.assertRaises(FileExistsError): d.write_fresh_json(path, {"ok": False})
            self.assertEqual(d.load_json(path), {"ok": True})
            path.write_text('{"x": NaN}')
            with self.assertRaises(ValueError): d.load_json(path)
            path.write_text('{"x": 1, "x": 2}')
            with self.assertRaisesRegex(ValueError, "duplicate"): d.load_json(path)

class OnehandScopeTests(unittest.TestCase):
    def test_actual_v3_ancestry_right_elbow_pole_delta_is_allowed(self):
        for side in ("r", "l"):
            base = {**d.empty_action(), "curves": [curve('pose.bones["elbow_pole_' + side + '"].location')]}
            target = copy.deepcopy(base); target["curves"][0]["keys"][0] = key(1, .7)
            if side == "r":
                patch = d.build_action_delta(base, target, {}, "rig")
                self.assertTrue(d.exact_equal(d.apply_action_delta(base, patch, {}), target))
            else:
                with self.assertRaisesRegex(ValueError, "allowlist"):
                    d.build_action_delta(base, target, {}, "rig")


    def test_curve_reordering_fails_before_native_installation(self):
        base = record(); target = copy.deepcopy(base); target["curves"].reverse()
        with self.assertRaisesRegex(ValueError, "ordering"):
            d.build_action_delta(base, target, {}, "rig")


    def test_exact_pinned_grid_has_4240_unique_times_and_17_bounded_chunks(self):
        times = d.probe_times()
        self.assertEqual(len(times), 4240)
        self.assertEqual([times[0], times[-1]], [1, 96])
        self.assertEqual(d.sha(Path(__file__).with_name("dense-times.json")), d.GRID_SHA)
        self.assertEqual([i for c in range(17) for i in range(*d.chunk_bounds(c))], list(range(4240)))
        self.assertEqual(d.chunk_bounds(16), (4096, 4240))
        for index in (-1, 17, True, 1.5):
            with self.assertRaises(ValueError): d.chunk_bounds(index)

    def test_grid_bytes_cannot_be_substituted_by_approximately_equal_clock(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "times.json"
            times = d.probe_times(); times[1] += 1e-12
            path.write_text(json.dumps(times))
            with self.assertRaisesRegex(ValueError, "bytes differ"): d.probe_times(path)

    def test_camera_and_object_comotion_are_forbidden(self):
        for role, path in (("camera", "location"), ("rig", "location"), ("rig", "rotation_euler")):
            base = {**d.empty_action(), "curves": [curve(path)]}
            target = copy.deepcopy(base); target["curves"][0]["keys"][0] = key(1, .7)
            with self.assertRaises(ValueError): d.build_action_delta(base, target, {}, role)

    def test_added_curves_are_forbidden_even_on_allowed_control(self):
        target = {**d.empty_action(), "curves": [curve()]}
        with self.assertRaisesRegex(ValueError, "additions/removals/ordering"):
            d.build_action_delta(d.empty_action(), target, {}, "rig")

    def test_custom_controller_scalar_requires_axis_zero(self):
        path = 'pose.bones["righthand_prop_lefthand"]["wrist_flex"]'
        for axis in (0, 1):
            base = {**d.empty_action(), "curves": [curve(path, axis)]}
            target = copy.deepcopy(base); target["curves"][0]["keys"][0] = key(1, .7)
            if axis == 0:
                patch = d.build_action_delta(base, target, {}, "rig")
                self.assertTrue(d.exact_equal(d.apply_action_delta(base, patch, {}), target))
            else:
                with self.assertRaisesRegex(ValueError, "allowlist"): d.build_action_delta(base, target, {}, "rig")

    def test_pose_correction_scope_is_twelve_delta_and_four_recompute_only(self):
        rows = d.pose_corrections()
        self.assertEqual(len(rows), 16)
        self.assertEqual(sum("delta" in r for r in rows), 12)
        self.assertTrue(all("baseline" not in r and "candidate" not in r and "value" not in r for r in rows))
        self.assertTrue(all("delta" not in r for r in rows if r["mode"] == "unchanged_driver_recompute"))

    def test_pose_correction_guard_roundtrips_and_rejects_wrong_base(self):
        before = .5; after = d.f32(before + 2 ** -24)
        row = {"mode": "original_scalar_delta", "delta": 2 ** -24,
               "before_sha256": d.digest(before), "after_sha256": d.digest(after)}
        self.assertEqual(d.corrected_scalar(before, row), after)
        with self.assertRaisesRegex(ValueError, "baseline hash"): d.corrected_scalar(.6, row)
        row["after_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "reconstruction"): d.corrected_scalar(before, row)

    def test_driven_output_assignment_and_large_corrections_are_forbidden(self):
        row = {"mode": "unchanged_driver_recompute"}
        with self.assertRaisesRegex(ValueError, "never be assigned"): d.corrected_scalar(.5, row)
        row = {"mode": "original_scalar_delta", "before_sha256": d.digest(.5), "delta": .1}
        with self.assertRaisesRegex(ValueError, "scope"): d.corrected_scalar(.5, row)

    def test_mask_excludes_only_the_sixteen_declared_paths(self):
        poses = {"Arms": {"other": {"scale": [1., 1., 1.]}}}
        for row in d.pose_corrections():
            obj, bone, field, component = row["path"]
            record = poses[obj].setdefault(bone, {})
            record.setdefault(field, {} if field == "custom_properties" else [1., 1., 1.])
            record[field][component] = .5
        masked = d.mask_pose_exceptions(poses)
        self.assertEqual(masked["Arms"]["other"], poses["Arms"]["other"])
        self.assertNotEqual(d.digest(masked), d.digest(poses))
        self.assertEqual(sum(str(masked).count(x) for x in ("original_scalar_delta", "unchanged_driver_recompute")), 16)

    def test_metadata_deltas_omit_inherited_values(self):
        base = {"use_fake_user": True, "properties": {"unchanged": "PRIVATE_INHERITED", "status": "old"}}
        target = {"use_fake_user": True, "properties": {"unchanged": "PRIVATE_INHERITED", "status": "authored", "new": 42}}
        patch = d.metadata_delta(base, target)
        self.assertNotIn("PRIVATE_INHERITED", json.dumps(patch))
        self.assertNotIn("unchanged", patch["properties"])
        self.assertTrue(d.exact_equal(d.apply_metadata_delta(base, patch), target))

    def test_metadata_cannot_smuggle_geometry_or_remove_inherited_properties(self):
        base = {"use_fake_user": True, "properties": {"unchanged": 1}}
        for properties in ({}, {"unchanged": 1, "mesh": [1., 2., 3.]}, {"unchanged": 1, "large": "x" * 4097}):
            with self.assertRaises(ValueError): d.metadata_delta(base, {"use_fake_user": True, "properties": properties})

    def test_native_command_is_serial_headless_no_render_no_autoexec(self):
        command = runner.native_command("/usr/bin/blender", ["witness", "--chunk-index", "0"])
        self.assertIn("--disable-autoexec", command)
        self.assertIn("--factory-startup", command)
        self.assertEqual(command[command.index("--threads") + 1], "1")
        self.assertNotIn("--render-anim", command)
        self.assertNotIn("bpy", sys.modules)

    def test_existing_lock_is_not_removed_or_stolen(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "owner.lock"; lock.write_text("already held")
            with self.assertRaises(FileExistsError):
                with runner.exclusive_lock(lock): pass
            self.assertEqual(lock.read_text(), "already held")


