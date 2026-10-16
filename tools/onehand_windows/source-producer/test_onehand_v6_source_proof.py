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


def synthetic_recipe():
    from onehand_v6_source_native import CODE_FILES
    h = "a" * 64
    prior = {f"original_{i:02}": {"legacy": h, "complete": h, "metadata": h, "auxiliary": h} for i in range(86)}
    prior[d.BASE_ACTION] = {"legacy": d.BASE_FINGERPRINT, "complete": h, "metadata": h, "auxiliary": h}
    prior[d.RESET_ACTION] = {"legacy": d.RESET_FINGERPRINT, "complete": h, "metadata": h, "auxiliary": h}
    static = {key: h for key in d.STATIC_CATEGORIES}
    target_static = {**static, "pose_channel_defaults": "b" * 64}
    return {"schema": d.SCHEMA, "base_sha256": d.BASE_SHA, "approved_source_sha256": d.APPROVED_SHA,
            "base_action": d.BASE_ACTION, "rig_action": d.RIG_ACTION, "camera_action": None,
            "reset_action": d.RESET_ACTION, "reset_fingerprint": d.RESET_FINGERPRINT,
            "clock": {"frames": [1, 96], "fps": [60, 1], "grid_sha256": d.GRID_SHA, "sample_count": 4240},
            "base_static_hashes": static, "approved_static_hashes": target_static, "inherited_actions": prior,
            "action": {"role": "rig", "base_fingerprint": d.BASE_FINGERPRINT, "target_fingerprint": d.RIG_FINGERPRINT,
                       "target_complete_sha256": h, "base_complete_sha256": h, "settings": {},
                       "curves": [{"op": "reference", "base_index": 0, "before_sha256": h}]},
            "metadata": {"after_sha256": h, "before_sha256": h, "properties": {}, "use_fake_user": None}, "action_auxiliary_sha256": h,
            "producer_sha256": {name: d.sha(Path(__file__).with_name(name)) for name in CODE_FILES}, "pose_corrections_sha256": d.POSE_CORRECTIONS_SHA,
            "scope": "Original final Action deltas and 12 original scalar corrections; inherited content by hash reference only."}


def synthetic_replay(recipe):
    return {"schema": "rust-duty-onehand-v6-source-replay/v1", "passed": True, "fresh_reopen_passed": True,
            "base_sha256": d.BASE_SHA, "approved_source_sha256": d.APPROVED_SHA, "delta_sha256": "d" * 64,
            "generated_source_sha256": "c" * 64, "prior_actions_preserved": 88, "result_action_count": 89,
            "created_actions": [d.RIG_ACTION], "original_scalar_corrections_applied": 12,
            "unchanged_driven_outputs_recomputed": 4, "action_hashes": runner.expected_action_hashes(recipe),
            "static_hashes": recipe["approved_static_hashes"], "producer_sha256": recipe["producer_sha256"],
            "blender_version": d.BLENDER_VERSION, "source_byte_identity_with_approved": False,
            "rendered": False, "runtime_equivalence_proved": False, "evaluated_equivalence_proved": False,
            "limits": ["Independent exact 4240-time witness comparison remains required.",
                       "The regenerated private BLEND is never a source-only publication artifact."]}


def synthetic_witness(recipe, replay, kind, chunk=16):
    from onehand_v6_source_native import ACTORS, SKINS, GEOMETRY, NUMERIC_CONTRACT
    h = "e" * 64; start, stop = d.chunk_bounds(chunk); times = d.probe_times()
    meshes = [{"name": name, "role": "skin" if name in SKINS else "rigid",
               "vertices": (3412 if name == SKINS[0] else 3411) if name in SKINS else 12,
               "local_positions_sha256": h, "world_positions_sha256": h, "topology_sha256": h} for name in GEOMETRY]
    motion = {"chunk_index": chunk, "index_range_half_open": [start, stop], "sample_count": stop - start,
              "grid_sha256": d.GRID_SHA, "numeric_contract": NUMERIC_CONTRACT,
              "bone_count": 148, "bone_order_sha256": h, "object_order_sha256": h, "hierarchy_sha256": h,
              "rest_world_sha256": h, "actors": list(ACTORS), "skins": list(SKINS),
              "canonical_reset_action": d.RESET_ACTION, "frame1_geometry": copy.deepcopy(meshes),
              "static_rig_world_sha256": h, "static_camera_world_sha256": h, "static_projection_sha256": h,
              "rows": [{"sample_index": i, "frame": times[i], "bones_world_sha256": h, "rig_world_sha256": h,
                        "camera_world_sha256": h, "projection_sha256": h, "actors_world_sha256": h,
                        "all_objects_world_sha256": h, "geometry": copy.deepcopy(meshes)} for i in range(start, stop)]}
    return {"schema": "rust-duty-onehand-v6-source-witness-chunk/v1", "kind": kind,
            "source_sha256": d.APPROVED_SHA if kind == "approved" else replay["generated_source_sha256"],
            "approved_source_sha256": d.APPROVED_SHA, "delta_sha256": replay["delta_sha256"],
            "action_hashes": runner.expected_action_hashes(recipe), "inherited_actions_sha256": d.digest(recipe["inherited_actions"]),
            "static_hashes": recipe["approved_static_hashes"], "producer_sha256": recipe["producer_sha256"],
            "blender_version": d.BLENDER_VERSION, "motion": motion, "source_saved": False,
            "source_bytes_unchanged": True, "rendered": False, "runtime_equivalence_proved": False}


class WitnessTests(unittest.TestCase):
    def setUp(self):
        self.recipe = synthetic_recipe(); self.replay = synthetic_replay(self.recipe)
        self.a = synthetic_witness(self.recipe, self.replay, "approved")
        self.b = synthetic_witness(self.recipe, self.replay, "regenerated")

    def compare(self):
        runner.validate_replay(self.recipe, self.replay, "d" * 64)
        return runner.compare_chunks(self.a, self.b, self.recipe, self.replay, 16)

    def test_exact_hash_only_pair_passes(self):
        self.compare()
        self.assertNotIn("bpy", sys.modules)
        self.assertLess(len(json.dumps(self.a).encode()), 1024 * 1024)

    def test_distinct_serialized_identity_is_required(self):
        self.replay["generated_source_sha256"] = d.APPROVED_SHA
        with self.assertRaisesRegex(ValueError, "serialized"): self.compare()

    def test_all_eighty_eight_original_actions_must_be_preserved(self):
        self.recipe["inherited_actions"].pop("original_00")
        with self.assertRaisesRegex(ValueError, "88"): self.compare()

    def test_exactly_one_new_action_required(self):
        self.replay["result_action_count"] = 95
        with self.assertRaisesRegex(ValueError, "one final"): self.compare()

    def test_correction_metadata_cannot_be_silently_dropped(self):
        self.replay["original_scalar_corrections_applied"] = 0
        with self.assertRaisesRegex(ValueError, "lineage"): self.compare()

    def test_a_single_coordinate_hash_difference_fails(self):
        self.b["motion"]["rows"][0]["geometry"][0]["world_positions_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "exact evaluated"): self.compare()

    def test_inherited_static_rest_change_fails(self):
        self.b["static_hashes"] = {**self.b["static_hashes"], "armatures": "f" * 64}
        with self.assertRaisesRegex(ValueError, "static"): self.compare()

    def test_missing_row_duplicate_time_and_ulp_time_fail(self):
        for mode in ("missing", "duplicate", "ulp"):
            self.setUp()
            if mode == "missing": self.b["motion"]["rows"].pop()
            elif mode == "duplicate": self.b["motion"]["rows"][1]["frame"] = self.b["motion"]["rows"][0]["frame"]
            else: self.b["motion"]["rows"][0]["frame"] += 1e-12
            with self.assertRaises(ValueError): self.compare()

    def test_actor_geometry_and_topology_are_measured_not_name_only(self):
        self.b["motion"]["rows"][0]["geometry"][-1]["topology_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "topology"): self.compare()

    def test_missing_rigid_actor_fails(self):
        self.b["motion"]["rows"][0]["geometry"].pop()
        with self.assertRaisesRegex(ValueError, "geometry coverage"): self.compare()

    def test_camera_world_or_projection_animation_fails(self):
        for key in ("camera_world_sha256", "projection_sha256"):
            self.setUp(); self.b["motion"]["rows"][0][key] = "f" * 64
            with self.assertRaisesRegex(ValueError, "contract drift"): self.compare()

    def test_hash_witness_rejects_raw_vertices(self):
        self.b["motion"]["rows"][0]["geometry"][0]["vertices_xyz"] = [[1, 2, 3]]
        with self.assertRaisesRegex(ValueError, "raw or unexpected"): self.compare()

    def test_relaxed_numeric_contract_fails(self):
        self.b["motion"]["numeric_contract"] = "float tolerance 1e-5"
        with self.assertRaisesRegex(ValueError, "numeric"): self.compare()

    def test_cross_platform_version_or_code_mismatch_fails(self):
        self.b["blender_version"] = "4.4.0"
        with self.assertRaisesRegex(ValueError, "producer"): self.compare()

    def test_runtime_or_render_claim_is_forbidden(self):
        self.b["runtime_equivalence_proved"] = True
        with self.assertRaisesRegex(ValueError, "no runtime claim"): self.compare()

    def test_replay_rejects_extra_raw_asset_payload(self):
        self.replay["private_asset_payload"] = [[1, 2, 3]]
        with self.assertRaisesRegex(ValueError, "unexpected replay"): self.compare()

    def test_recipe_rejects_raw_payload_nested_in_action(self):
        self.recipe["action"]["mesh_vertices"] = [[1, 2, 3]]
        with self.assertRaisesRegex(ValueError, "unexpected Action"): self.compare()

    def test_recipe_rejects_raw_payload_nested_in_metadata(self):
        self.recipe["metadata"]["rest_world_matrices"] = [[1, 2, 3]]
        with self.assertRaisesRegex(ValueError, "unexpected metadata"): self.compare()

    def test_replay_cannot_preclaim_evaluated_equivalence(self):
        self.replay["evaluated_equivalence_proved"] = True
        with self.assertRaisesRegex(ValueError, "preclaim"): self.compare()

    def test_metadata_value_cannot_smuggle_arrays(self):
        self.recipe["metadata"]["properties"] = {"mesh": {"before_sha256": None, "value": [1, 2, 3]}}
        with self.assertRaisesRegex(ValueError, "scalar/text"): self.compare()

    def test_actual_full_4240_aggregate_requires_all_34_chunk_files(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            d.write_fresh_json(root / "delta.json", self.recipe)
            delta_sha = d.sha(root / "delta.json")
            self.replay["delta_sha256"] = delta_sha
            d.write_fresh_json(root / "replay.json", self.replay)
            index = {}
            for i in range(17):
                for kind in ("approved", "regenerated"):
                    name = f"{kind}-{i:03}.json"
                    witness = synthetic_witness(self.recipe, self.replay, kind, i)
                    d.write_fresh_json(root / name, witness)
                    index[name] = d.sha(root / name)
            d.write_fresh_json(root / "index.json", index)
            args = SimpleNamespace(delta=root / "delta.json", delta_sha256=delta_sha,
                replay_receipt=root / "replay.json", replay_receipt_sha256=d.sha(root / "replay.json"),
                witness_index=root / "index.json", witness_index_sha256=d.sha(root / "index.json"),
                directory=root, output=root / "equivalence.json")
            runner.compare_directory(args)
            result = d.load_json(args.output)
            self.assertEqual(result["sample_count"], 4240)
            self.assertEqual(result["chunk_count"], 17)
            self.assertFalse(result["runtime_equivalence_proved"])
            (root / "regenerated-008.json").unlink()
            args.output = root / "not-created.json"
            with self.assertRaises(FileNotFoundError): runner.compare_directory(args)
            self.assertFalse(args.output.exists())


class CompletionIntegrityTests(unittest.TestCase):
    """End-to-end planner completion tests with synthetic, sealed 34-file evidence."""
    @classmethod
    def setUpClass(cls):
        from types import SimpleNamespace
        cls.temp = tempfile.TemporaryDirectory(prefix="completion-tests-", dir=Path(__file__).parent)
        cls.root = Path(cls.temp.name).resolve()
        cls.fixture = cls.root / "fixture"; cls.fixture.mkdir()
        cls.recipe = synthetic_recipe()
        d.write_fresh_json(cls.fixture / "original-delta.json", cls.recipe)
        delta_sha = d.sha(cls.fixture / "original-delta.json")
        replay = synthetic_replay(cls.recipe); replay["delta_sha256"] = delta_sha
        (cls.fixture / "regenerated-onehand-v6.blend").write_bytes(b"SYNTHETIC SOURCE IDENTITY ONLY")
        replay["generated_source_sha256"] = d.sha(cls.fixture / "regenerated-onehand-v6.blend")
        d.write_fresh_json(cls.fixture / "replay-receipt.json", replay)
        index = {}
        for i in range(17):
            for kind in ("approved", "regenerated"):
                name = f"{kind}-{i:03}.json"
                d.write_fresh_json(cls.fixture / name, synthetic_witness(cls.recipe, replay, kind, i))
                index[name] = d.sha(cls.fixture / name)
        d.write_fresh_json(cls.fixture / "witness-index.json", index)
        args = cls.evidence_args(cls.fixture)
        d.write_fresh_json(args.output, runner.build_equivalence_result(args))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def evidence_args(root):
        from types import SimpleNamespace
        return SimpleNamespace(delta=root / "original-delta.json", delta_sha256=d.sha(root / "original-delta.json"),
            replay_receipt=root / "replay-receipt.json", replay_receipt_sha256=d.sha(root / "replay-receipt.json"),
            witness_index=root / "witness-index.json", witness_index_sha256=d.sha(root / "witness-index.json"),
            directory=root, output=root / "source-equivalence.json")

    def setUp(self):
        import shutil
        self.work = self.root / self._testMethodName
        shutil.copytree(self.fixture, self.work)

    def write(self, name, value):
        (self.work / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def next(self):
        from types import SimpleNamespace
        import owner_commands as owner
        real_sha = d.sha
        base = Path("/synthetic/base.blend"); approved = Path("/synthetic/approved.blend")
        def source_hash(path):
            if Path(path) == base: return d.BASE_SHA
            if Path(path) == approved: return d.APPROVED_SHA
            return real_sha(path)
        args = SimpleNamespace(pins_sha256="a" * 64, blender="/synthetic/blender", lock=self.work / "owner.lock",
                               output_directory=self.work)
        with patch.object(owner, "verify_pins"), patch.object(owner, "BASE", base), patch.object(owner, "APPROVED", approved), \
             patch.object(d, "sha", side_effect=source_hash):
            return owner.next_command(args)

    def test_valid_completion_revalidates_without_writes(self):
        before = {p.name: (p.stat().st_mtime_ns, d.sha(p)) for p in self.work.iterdir()}
        self.assertEqual(self.next()["stage"], "complete")
        self.assertEqual(before, {p.name: (p.stat().st_mtime_ns, d.sha(p)) for p in self.work.iterdir()})

    def test_minimal_four_field_completion_is_rejected(self):
        proof = d.load_json(self.work / "source-equivalence.json")
        self.write("source-equivalence.json", {k: proof[k] for k in
                   ("passed", "generated_source_sha256", "sample_count", "delta_sha256")})
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.next()

    def test_stale_replay_receipt_identity_is_rejected(self):
        path = self.work / "replay-receipt.json"
        # Same semantic replay, different bytes: the saved proof's replay pin is stale.
        path.write_text(json.dumps(d.load_json(path), separators=(",", ":")))
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.next()

    def test_stale_witness_index_identity_is_rejected(self):
        path = self.work / "witness-index.json"
        path.write_text(json.dumps(d.load_json(path), separators=(",", ":")))
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.next()

    def mutate_paired_motion(self, reseal):
        index = d.load_json(self.work / "witness-index.json")
        for kind in ("approved", "regenerated"):
            name = f"{kind}-008.json"; witness = d.load_json(self.work / name)
            witness["motion"]["rows"][0]["geometry"][0]["world_positions_sha256"] = "f" * 64
            self.write(name, witness)
            if reseal: index[name] = d.sha(self.work / name)
        if reseal: self.write("witness-index.json", index)

    def test_coherently_replaced_pair_with_stale_seal_is_rejected(self):
        self.mutate_paired_motion(reseal=False)
        with self.assertRaisesRegex(ValueError, "pinned evidence differs"): self.next()

    def test_replaced_pair_and_new_seal_cannot_reuse_old_proof(self):
        self.mutate_paired_motion(reseal=True)
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.next()

    def test_stale_producer_under_new_package_is_rejected(self):
        recipe = d.load_json(self.work / "original-delta.json")
        recipe["producer_sha256"]["onehand_v6_source_native.py"] = "f" * 64
        self.write("original-delta.json", recipe)
        with self.assertRaisesRegex(ValueError, "current package code"): self.next()

    def test_extra_completion_payload_is_rejected(self):
        proof = d.load_json(self.work / "source-equivalence.json")
        proof["private_asset_payload"] = [[1., 2., 3.]]
        self.write("source-equivalence.json", proof)
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.next()


if __name__ == "__main__":
    unittest.main()
