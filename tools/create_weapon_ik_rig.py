#!/usr/bin/env python3
"""Build and validate an original, asset-free Blender weapon/hand IK fixture.

Run with Blender 4.3: blender -b --python tools/create_weapon_ik_rig.py --
No files are read except an optional explicit calibration JSON. Every mesh,
armature, action and driver is generated here; no licensed rig is required.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

WEAPON_BONE = "weapon"
TARGETS = {"l": "left_hand_weapon_ik", "r": "right_hand_weapon_ik"}
PROPERTIES = {side: name + "_influence" for side, name in TARGETS.items()}
SAMPLE_FRAMES = (1, 12, 24, 36, 48)


def default_calibration():
    """Original runtime wrist frames: metres, +X right, +Y up, -Z forward."""
    return {
        "coordinate_system": "+X right, +Y up, -Z weapon forward; metres",
        "quaternion_order": "xyzw",
        "left_hand_weapon_ik": {
            "translation": [-0.068, -0.112, -0.205],
            "rotation_xyzw": [0.70147073, 0.089098096, -0.089098096, 0.70147073],
        },
        "right_hand_weapon_ik": {
            "translation": [0.062053986, -0.108130604, 0.14318079],
            "rotation_xyzw": [0.07290045, 0.7246968, -0.012056069, -0.6850947],
        },
    }


def calibration_matrix(entry):
    values = entry["translation"] + entry["rotation_xyzw"]
    if len(values) != 7 or not all(math.isfinite(v) for v in values):
        raise ValueError("Each calibration needs finite translation[3] and rotation_xyzw[4]")
    x, y, z, w = entry["rotation_xyzw"]
    q = Quaternion((w, x, y, z))
    if q.magnitude < 1e-8:
        raise ValueError("Zero-length calibration quaternion")
    q.normalize()
    return Matrix.Translation(entry["translation"]) @ q.to_matrix().to_4x4()


def activate_edit(obj):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")


def new_armature(name):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.show_in_front = True
    obj.data.display_type = "OCTAHEDRAL"
    obj.data.show_names = True
    return obj


def create_weapon_armature(calibration):
    """Create actual parented target bones, with identity `weapon` rest frame."""
    rig = new_armature("WeaponRig")
    activate_edit(rig)
    root = rig.data.edit_bones.new(WEAPON_BONE)
    root.head, root.tail = (0, 0, 0), (0, 0.10, 0)
    for target in TARGETS.values():
        child = rig.data.edit_bones.new(target)
        child.parent = root
        child.use_connect = False
        child.length = 0.055
        child.matrix = calibration_matrix(calibration[target])
    bpy.ops.object.mode_set(mode="OBJECT")
    for target in TARGETS.values():
        rig.pose.bones[target]["purpose"] = "Weapon-local default wrist frame; not a palm contact point"
    return rig


def create_synthetic_arms(calibration):
    rig = new_armature("SyntheticArms")
    activate_edit(rig)
    root = rig.data.edit_bones.new("arms_root")
    root.head, root.tail = (0, -0.28, 0.44), (0, -0.18, 0.44)
    for side, sign in (("l", -1), ("r", 1)):
        wrist = Vector(calibration[TARGETS[side]]["translation"])
        shoulder = Vector((sign * 0.25, -0.10, 0.43))
        elbow = Vector((sign * 0.33, -0.24, 0.14))
        upper = rig.data.edit_bones.new("upperarm_" + side)
        upper.head, upper.tail, upper.parent = shoulder, elbow, root
        lower = rig.data.edit_bones.new("lowerarm_" + side)
        lower.head, lower.tail, lower.parent = elbow, wrist, upper
        lower.use_connect = True
        hand = rig.data.edit_bones.new("hand_" + side)
        hand.parent = lower
        hand.use_connect = True
        hand.length = 0.065
        hand.matrix = calibration_matrix(calibration[TARGETS[side]])
        pole = rig.data.edit_bones.new("elbow_pole_" + side)
        pole.head = Vector((sign * 0.55, -0.43, 0.05))
        pole.tail = pole.head + Vector((0, 0.05, 0))
        pole.parent = root
        pole.use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def create_controls():
    control = bpy.data.objects.new("WeaponIKControls", None)
    bpy.context.collection.objects.link(control)
    control.empty_display_type = "PLAIN_AXES"
    control.empty_display_size = 0.08
    control.location = (0, 0.16, 0)
    for prop in PROPERTIES.values():
        control[prop] = 1.0
        control.id_properties_ui(prop).update(min=0.0, max=1.0, default=1.0,
            description="0: keep keyed base animation; 1: follow weapon wrist target")
    return control


def drive_influence(constraint, controls, side):
    curve = constraint.driver_add("influence")
    driver = curve.driver
    driver.type = "SCRIPTED"
    driver.expression = "min(max(grip, 0.0), 1.0)"
    variable = driver.variables.new()
    variable.name, variable.type = "grip", "SINGLE_PROP"
    variable.targets[0].id = controls
    variable.targets[0].data_path = '["' + PROPERTIES[side] + '"]'


def attach_hand_layer(arms, weapon, controls):
    """Keep all existing FK channels and add a controllable IK/rotation layer.

    Synthetic chain names are UE-style upperarm/lowerarm/hand with _l/_r.
    Object/rest transforms must be rigid with unit positive scale for the
    fixture's world-matrix equality tests. Calibrate target wrist frames first.
    """
    for side in TARGETS:
        lower = arms.pose.bones["lowerarm_" + side]
        if any(c.name.startswith(TARGETS[side])
               for bone in (lower, arms.pose.bones["hand_" + side])
               for c in bone.constraints):
            raise ValueError("Weapon hand layer already exists for side " + side)
        lower.ik_stretch = 0.0
        arms.pose.bones["upperarm_" + side].ik_stretch = 0.0
        ik = lower.constraints.new("IK")
        ik.name = TARGETS[side] + "_position"
        ik.target, ik.subtarget = weapon, TARGETS[side]
        ik.chain_count, ik.use_tail, ik.use_stretch = 2, True, False
        ik.iterations = 500
        ik.pole_target, ik.pole_subtarget = arms, "elbow_pole_" + side
        drive_influence(ik, controls, side)
        rotation = arms.pose.bones["hand_" + side].constraints.new("COPY_ROTATION")
        rotation.name = TARGETS[side] + "_rotation"
        rotation.target, rotation.subtarget = weapon, TARGETS[side]
        rotation.owner_space = rotation.target_space = "WORLD"
        rotation.mix_mode = "REPLACE"
        drive_influence(rotation, controls, side)


def key_demo_animation(arms, weapon, controls):
    # Base action is deliberately nontrivial and remains on the armature.
    # The left wrist visibly departs while its weapon influence is zero.
    for frame, amount in ((1, 0.0), (12, 0.35), (24, 1.0), (36, 0.65), (48, 0.0)):
        for side, sign in (("l", -1), ("r", 1)):
            for bone, axis, angle in (("upperarm", (0, 1, 0), sign * 0.65 * amount),
                                     ("lowerarm", (1, 0, 0), -0.4 * amount),
                                     ("hand", (0, 0, 1), sign * 0.3 * amount)):
                pose = arms.pose.bones[bone + "_" + side]
                pose.rotation_mode = "QUATERNION"
                pose.rotation_quaternion = Quaternion(axis, angle)
                pose.keyframe_insert("rotation_quaternion", frame=frame, group=bone + "_" + side)
        root = weapon.pose.bones[WEAPON_BONE]
        root.rotation_mode = "QUATERNION"
        root.rotation_quaternion = Quaternion(Vector((0.3, 1, 0.25)).normalized(), 0.18 * amount)
        root.location = (0.015 * amount, 0.018 * amount, -0.008 * amount)
        root.keyframe_insert("rotation_quaternion", frame=frame, group=WEAPON_BONE)
        root.keyframe_insert("location", frame=frame, group=WEAPON_BONE)
    arms.animation_data.action.name = "BaseArmMotion_preserved"
    weapon.animation_data.action.name = "WeaponMotion"
    for frame, left, right in ((1, 1, 1), (12, 1, 1), (18, 0, 1), (32, 0, 1),
                                (40, 1, 1), (48, 1, 1)):
        for side, value in (("l", left), ("r", right)):
            controls[PROPERTIES[side]] = float(value)
            controls.keyframe_insert(data_path='["' + PROPERTIES[side] + '"]', frame=frame)
    controls.animation_data.action.name = "WeaponGripInfluences"
    for action in (arms.animation_data.action, weapon.animation_data.action, controls.animation_data.action):
        for curve in action.fcurves:
            for key in curve.keyframe_points:
                key.interpolation = "LINEAR"
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, 48
    bpy.context.scene.render.fps = 24


def action_signature(action):
    return [(curve.data_path, curve.array_index,
             [(float(k.co.x), float(k.co.y)) for k in curve.keyframe_points])
            for curve in action.fcurves]


def world_bone(rig, name):
    evaluated = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return evaluated.matrix_world @ evaluated.pose.bones[name].matrix


def update_controls(controls, left, right):
    controls[PROPERTIES["l"]], controls[PROPERTIES["r"]] = left, right
    controls.update_tag()
    bpy.context.view_layer.update()


def matrix_error(a, b):
    return max(abs(a[row][col] - b[row][col]) for row in range(4) for col in range(4))


def validate_fixture(arms, weapon, controls):
    before = action_signature(arms.animation_data.action)
    assert weapon.data.bones[WEAPON_BONE].parent is None
    for target in TARGETS.values():
        assert weapon.data.bones[target].parent.name == WEAPON_BONE
        assert not weapon.data.bones[target].use_connect
    constraints = [c for p in arms.pose.bones for c in p.constraints]
    assert len(constraints) == 4
    assert len(arms.animation_data.drivers) == 4
    control_action = controls.animation_data.action
    controls.animation_data.action = None
    report = {"passed": False, "blender_version": bpy.app.version_string,
              "provenance": "Entirely generated original dummy geometry and animation; no external assets",
              "target_parentage": {name: weapon.data.bones[name].parent.name for name in TARGETS.values()},
              "base_action": arms.animation_data.action.name, "base_action_fcurves": len(before),
              "samples": []}
    base_positions = []
    try:
        for frame in SAMPLE_FRAMES:
            bpy.context.scene.frame_set(frame)
            for constraint in constraints:
                constraint.mute = True
            bpy.context.view_layer.update()
            baseline = {side: world_bone(arms, "hand_" + side).copy() for side in TARGETS}
            base_positions.append(list(baseline["l"].translation))
            for constraint in constraints:
                constraint.mute = False
            update_controls(controls, 0.0, 0.0)
            zero = {side: world_bone(arms, "hand_" + side).copy() for side in TARGETS}
            zero_error = max(matrix_error(zero[side], baseline[side]) for side in TARGETS)
            assert zero_error < 2e-5, (frame, "base not preserved", zero_error)
            update_controls(controls, 1.0, 1.0)
            target_error, target_positions = {}, {}
            for side in TARGETS:
                result, target = world_bone(arms, "hand_" + side), world_bone(weapon, TARGETS[side])
                hierarchy_expected = world_bone(weapon, WEAPON_BONE) @ weapon.data.bones[TARGETS[side]].matrix_local
                hierarchy_error = matrix_error(target, hierarchy_expected)
                assert hierarchy_error < 2e-5, (frame, side, "weapon-local hierarchy", hierarchy_error)
                translation_error = (result.translation - target.translation).length
                rotation_error = result.to_quaternion().rotation_difference(target.to_quaternion()).angle
                target_error[side] = {"translation_m": translation_error, "rotation_radians": rotation_error,
                                      "matrix_max_abs": matrix_error(result, target),
                                      "weapon_parent_composition_max_abs": hierarchy_error}
                target_positions[side] = {"hand_world_matrix": [list(row) for row in result],
                                           "target_world_matrix": [list(row) for row in target]}
                assert translation_error < 2e-4, (frame, side, "target position", translation_error)
                assert rotation_error < 2e-3, (frame, side, "target rotation", rotation_error)
            update_controls(controls, 0.0, 1.0)
            independent_left_error = matrix_error(world_bone(arms, "hand_l"), baseline["l"])
            right_error = (world_bone(arms, "hand_r").translation - world_bone(weapon, TARGETS["r"]).translation).length
            assert independent_left_error < 2e-5 and right_error < 2e-4
            update_controls(controls, 0.5, 1.0)
            partial = world_bone(arms, "hand_l")
            partial_gap = (partial.translation - world_bone(weapon, TARGETS["l"]).translation).length
            assert all(math.isfinite(value) for row in partial for value in row)
            assert abs(arms.pose.bones["lowerarm_l"].constraints[0].influence - 0.5) < 1e-6
            if frame == 24:
                assert matrix_error(partial, baseline["l"]) > 1e-4
                assert partial_gap > 1e-4
            report["samples"].append({"frame": frame, "influence_zero_base_matrix_max_abs": zero_error,
                                     "influence_one_target_errors": target_error,
                                     "independent_left_release_matrix_error": independent_left_error,
                                     "half_influence_left_target_gap_m": partial_gap,
                                     "evaluated_world_matrices": target_positions})
        assert action_signature(arms.animation_data.action) == before, "Base action was modified"
        motion_span = max((Vector(p) - Vector(base_positions[0])).length for p in base_positions)
        assert motion_span > 0.04, "Base action must actually move the wrist"
        report["base_action_unchanged"] = True
        report["base_left_wrist_motion_span_m"] = motion_span
    finally:
        controls.animation_data.action = control_action
        for constraint in constraints:
            constraint.mute = False
        bpy.context.scene.frame_set(24)
        bpy.context.view_layer.update()
    gap = (world_bone(arms, "hand_l").translation - world_bone(weapon, TARGETS["l"]).translation).length
    assert controls[PROPERTIES["l"]] == 0.0 and gap > 0.04, ("Released hand should leave target", gap)
    report["animated_left_release_frame"] = 24
    report["animated_left_release_gap_m"] = gap
    report["passed"] = True
    return report


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1)
    node.inputs["Roughness"].default_value = 0.65
    return mat


def weighted_bar(name, rig, bone_name, radius, mat):
    bone = rig.data.bones[bone_name]
    direction = (bone.tail_local - bone.head_local).normalized()
    u = direction.cross(Vector((0, 0, 1)))
    if u.length < 0.1:
        u = direction.cross(Vector((1, 0, 0)))
    u.normalize()
    v = direction.cross(u).normalized()
    vertices = [tuple(p + radius * (u * math.cos(a * math.tau / 12) + v * math.sin(a * math.tau / 12)))
                for p in (bone.head_local, bone.tail_local) for a in range(12)]
    faces = [(a, (a + 1) % 12, (a + 1) % 12 + 12, a + 12) for a in range(12)]
    faces += [tuple(range(11, -1, -1)), tuple(range(12, 24))]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    group = obj.vertex_groups.new(name=bone_name)
    group.add(list(range(len(vertices))), 1.0, "REPLACE")
    modifier = obj.modifiers.new("Original synthetic skin", "ARMATURE")
    modifier.object = rig
    return obj


def dummy_weapon(rig, mat):
    # A plain asymmetric rectangular prop, deliberately not a copied weapon.
    vertices = [(x, y, z) for x in (-0.03, 0.03) for y in (-0.02, 0.02) for z in (-0.27, 0.22)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new("OriginalDummyProp")
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new("OriginalDummyProp", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    group = obj.vertex_groups.new(name=WEAPON_BONE)
    group.add(list(range(8)), 1.0, "REPLACE")
    modifier = obj.modifiers.new("Weapon bone deformation", "ARMATURE")
    modifier.object = rig


def setup_preview(arms, weapon):
    left, right = material("LeftArm_orange", (0.9, 0.28, 0.08)), material("RightArm_blue", (0.06, 0.38, 0.9))
    green = material("WeaponTargets_green", (0.08, 0.8, 0.27))
    for side, mat in (("l", left), ("r", right)):
        for bone, radius in (("upperarm", 0.029), ("lowerarm", 0.024), ("hand", 0.033)):
            weighted_bar(bone + "_" + side + "_dummy", arms, bone + "_" + side, radius, mat)
        weighted_bar(TARGETS[side] + "_marker", weapon, TARGETS[side], 0.012, green)
    dummy_weapon(weapon, material("DummyProp_gray", (0.19, 0.22, 0.27)))
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 12
    scene.cycles.use_denoising = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    scene.render.resolution_x, scene.render.resolution_y = 960, 720
    scene.render.resolution_percentage = 100
    scene.world = bpy.data.worlds.new("FixtureWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.12, 0.14, 0.18, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6
    camera_data = bpy.data.cameras.new("PreviewCamera")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (1.05, 0.75, 1.35)
    camera.rotation_euler = (Vector((0, -0.1, 0.12)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera_data.type, camera_data.ortho_scale = "ORTHO", 1.28
    scene.camera = camera
    light_data = bpy.data.lights.new("PreviewLight", "AREA")
    light_data.energy, light_data.size = 150, 2
    light = bpy.data.objects.new("PreviewLight", light_data)
    bpy.context.collection.objects.link(light)
    light.location = (0.4, 0.8, 1.2)
    light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "fixtures" / "weapon_ik")
    parser.add_argument("--calibration", type=Path, help="Optional explicit wrist-frame JSON")
    parser.add_argument("--render", action="store_true", help="Render attached/released/reattached dummy previews")
    options = parser.parse_args(args)
    output = options.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    calibration = json.loads(options.calibration.read_text()) if options.calibration else default_calibration()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    weapon = create_weapon_armature(calibration)
    arms = create_synthetic_arms(calibration)
    controls = create_controls()
    key_demo_animation(arms, weapon, controls)
    action_before = action_signature(arms.animation_data.action)
    attach_hand_layer(arms, weapon, controls)
    assert action_signature(arms.animation_data.action) == action_before
    report = validate_fixture(arms, weapon, controls)
    setup_preview(arms, weapon)
    (output / "calibration.json").write_text(json.dumps(calibration, indent=2) + "\n")
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    hierarchy = {"WeaponRig": {bone.name: bone.parent.name if bone.parent else None for bone in weapon.data.bones},
                 "SyntheticArms": {bone.name: bone.parent.name if bone.parent else None for bone in arms.data.bones},
                 "influence_properties": PROPERTIES}
    (output / "hierarchy.json").write_text(json.dumps(hierarchy, indent=2) + "\n")
    bpy.context.scene["fixture_provenance"] = "Original synthetic helper; no third-party geometry, textures or animation"
    bpy.context.scene["usage"] = "WeaponIKControls: left/right hand influence 0 preserves base motion, 1 follows target. Frames 18-32 release left hand."
    bpy.context.scene.frame_set(1)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "weapon_ik_demo.blend"))
    if options.render:
        for frame, label in ((1, "attached"), (24, "left_released"), (48, "reattached")):
            bpy.context.scene.frame_set(frame)
            bpy.context.scene.render.filepath = str(output / (label + ".png"))
            bpy.ops.render.render(write_still=True)
    print("WEAPON_IK_FIXTURE_PASS " + json.dumps({"output": str(output), "samples": len(report["samples"]),
          "base_action_unchanged": report["base_action_unchanged"], "left_release_gap_m": report["animated_left_release_gap_m"]}))


if __name__ == "__main__":
    main()
