"""Bounded Blender-only extraction, replay and hash-only motion proof.

Never import/execute this file to launch Blender: use the separately reviewed
owner's serialized native job. No rendering, network or asset publication.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_r15_source_delta as delta

FIELDS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
ACTORS = ("hk416_weapon", "hk416_magazine", "hk416_magazine_outgoing")


def atom(value):
    import bpy
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bpy.types.ID):
        return {"id_type": type(value).__name__, "name": value.name}
    if hasattr(value, "to_dict"):
        return {k: atom(v) for k, v in value.to_dict().items()}
    try:
        return [atom(x) for x in value]
    except TypeError:
        return str(value)


def props(obj):
    """Same writable RNA selection as the retained preservation checker."""
    result = {}
    for field in obj.bl_rna.properties:
        name = field.identifier
        if name == "rna_type" or field.type == "COLLECTION" or field.is_readonly:
            continue
        try:
            result[name] = atom(getattr(obj, name))
        except (AttributeError, TypeError, ValueError):
            pass
    return result


def custom(obj):
    return {k: atom(v) for k, v in obj.items() if k != "_RNA_UI"}


def matrix(value):
    return [list(row) for row in value]


def action_record(action):
    curves = []
    for curve in action.fcurves:
        curves.append({"path": curve.data_path, "index": curve.array_index,
                       **{k: atom(getattr(curve, k)) for k in delta.CURVE_SETTINGS if k != "group"},
                       "group": curve.group.name if curve.group else None,
                       "modifiers": [props(m) for m in curve.modifiers],
                       "samples": [list(point.co) for point in curve.sampled_points],
                       "keys": [props(key) for key in curve.keyframe_points]})
    result = {"curves": curves, **{k: getattr(action, k) for k in delta.ACTION_SETTINGS}}
    delta.validate_record(result)
    return result


def action_hashes(bpy):
    return {a.name: {"legacy": delta.fingerprint(action_record(a)),
                     "complete": delta.digest(action_record(a)),
                     "metadata": delta.digest({"use_fake_user": a.use_fake_user, "properties": custom(a)})}
            for a in bpy.data.actions}


def non_action_hashes(bpy):
    """Only hashes leave memory; includes existing audited preservation categories.

    No category is normalized away to force equality. New Actions are the sole
    allowed saved-state edit; active Actions/NLA, defaults and scene stay intact.
    """
    mesh_records = {}
    for mesh in bpy.data.meshes:
        record = {"vertices": [list(v.co) for v in mesh.vertices],
                  "edges": [list(e.vertices) for e in mesh.edges],
                  "polygons": [{"vertices": list(p.vertices), "material_index": p.material_index,
                                "use_smooth": p.use_smooth} for p in mesh.polygons],
                  "uv": {layer.name: [list(v.uv) for v in layer.data] for layer in mesh.uv_layers},
                  "materials": [m.name if m else None for m in mesh.materials],
                  "custom_properties": custom(mesh)}
        mesh_records[mesh.name] = delta.digest(record)
    armatures = {}
    for armature in bpy.data.armatures:
        armatures[armature.name] = delta.digest([
            {"name": b.name, "parent": b.parent.name if b.parent else None,
             "rest_matrix": matrix(b.matrix_local), "use_deform": b.use_deform,
             "use_connect": b.use_connect, "inherit_scale": b.inherit_scale,
             "head": list(b.head_local), "tail": list(b.tail_local), "props": props(b), "custom": custom(b)}
            for b in armature.bones])
    objects, defaults, pose_defaults, drivers, nla = {}, {}, {}, {}, {}
    for obj in bpy.data.objects:
        record = {"type": obj.type, "data": obj.data.name if obj.data else None,
                  "parent": obj.parent.name if obj.parent else None, "parent_type": obj.parent_type,
                  "parent_bone": obj.parent_bone, "matrix_parent_inverse": matrix(obj.matrix_parent_inverse),
                  "modifiers": [{"type": m.type, "props": props(m)} for m in obj.modifiers],
                  "constraints": [{"type": c.type, "props": props(c)} for c in obj.constraints],
                  "vertex_groups": [g.name for g in obj.vertex_groups], "properties": custom(obj)}
        if obj.type == "MESH":
            record["weights"] = [[(g.group, g.weight) for g in v.groups] for v in obj.data.vertices]
        if obj.pose:
            record["pose_constraints"] = {b.name: [{"type": c.type, "props": props(c)} for c in b.constraints]
                                            for b in obj.pose.bones}
            pose_defaults[obj.name] = {b.name: {"rotation_mode": b.rotation_mode,
                                               **{k: list(getattr(b, k)) for k in FIELDS},
                                               "custom_properties": custom(b)} for b in obj.pose.bones}
        objects[obj.name] = delta.digest(record)
        defaults[obj.name] = {"rotation_mode": obj.rotation_mode, **{k: list(getattr(obj, k)) for k in FIELDS}}
        data = obj.animation_data
        if data:
            drivers[obj.name] = [{"path": c.data_path, "index": c.array_index,
                                  "fcurve": props(c), "driver": props(c.driver),
                                  "variables": [{"props": props(v), "targets": [props(t) for t in v.targets]}
                                                for v in c.driver.variables],
                                  "modifiers": [props(m) for m in c.modifiers],
                                  "keys": [props(k) for k in c.keyframe_points]} for c in data.drivers]
            nla[obj.name] = {"props": props(data),
                            "tracks": [{"props": props(t), "strips": [props(s) for s in t.strips]}
                                       for t in data.nla_tracks]}
    materials = {}
    for material in bpy.data.materials:
        value = {"props": props(material), "custom": custom(material)}
        if material.node_tree:
            value["nodes"] = [{"name": n.name, "type": n.bl_idname, "props": props(n),
                               "inputs": [(s.name, atom(s.default_value)) for s in n.inputs if hasattr(s, "default_value")]}
                              for n in material.node_tree.nodes]
            value["links"] = [(link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name)
                              for link in material.node_tree.links]
        materials[material.name] = delta.digest(value)
    scenes = {scene.name: {**{k: getattr(scene, k) for k in
                                      ("frame_current", "frame_subframe", "frame_start", "frame_end", "frame_step")},
                           "camera": scene.camera.name if scene.camera else None,
                           "fps": scene.render.fps, "fps_base": scene.render.fps_base,
                           "resolution": [scene.render.resolution_x, scene.render.resolution_y,
                                          scene.render.resolution_percentage]}
              for scene in bpy.data.scenes}
    records = {"meshes": mesh_records, "armatures": armatures, "objects_and_bindings": objects,
               "object_defaults": defaults, "pose_channel_defaults": pose_defaults, "drivers": drivers, "nla": nla,
               "materials": materials, "cameras": {c.name: props(c) for c in bpy.data.cameras}, "scene": scenes,
               "packed_images": {i.name: hashlib.sha256(bytes(i.packed_file.data)).hexdigest()
                                 for i in bpy.data.images if i.packed_file},
               "embedded_text": {t.name: hashlib.sha256(t.as_string().encode()).hexdigest() for t in bpy.data.texts},
               "collections": {c.name: {"objects": sorted(o.name for o in c.objects),
                                         "children": sorted(ch.name for ch in c.children)} for c in bpy.data.collections}}
    return {category: delta.digest(value) for category, value in records.items()}


def native_preflight(bpy):
    delta.require(bpy.app.background and bpy.app.version_string == delta.BLENDER_VERSION,
                  "requires background Blender 4.3.2")
    delta.require(not bpy.context.preferences.filepaths.use_scripts_auto_execute,
                  "requires --factory-startup --disable-autoexec")


def open_pinned(bpy, path, expected):
    delta.require(delta.sha(path) == expected, "input BLEND SHA-256 mismatch")
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    native_preflight(bpy)
    delta.require(delta.sha(path) == expected, "input changed while opening")


def defaults_of(bpy, name):
    obj = bpy.data.objects[name]
    return {field: list(getattr(obj, field)) for field in delta.OBJECT_PATHS}


def producer_hashes():
    here = Path(__file__).resolve().parent
    return {name: delta.sha(here / name) for name in ("prone_r15_source_delta.py", "prone_r15_source_native.py")}


def validate_recipe(recipe):
    delta.require(set(recipe) == {"schema", "base_sha256", "approved_source_sha256", "base_action", "rig_action",
                                  "camera_action", "reset_action", "reset_fingerprint", "clock", "static_hashes",
                                  "base_actions_sha256", "actions", "producer_sha256", "scope"}, "unexpected recipe field")
    expected = {"schema": delta.SCHEMA, "base_sha256": delta.BASE_SHA,
                "approved_source_sha256": delta.APPROVED_SHA, "base_action": delta.BASE_ACTION,
                "rig_action": delta.RIG_ACTION, "camera_action": delta.CAMERA_ACTION,
                "reset_action": delta.RESET_ACTION, "reset_fingerprint": delta.RESET_FINGERPRINT,
                "clock": {"frames": 69, "fps": 60},
                "scope": "original authored key deltas; existing private base supplied separately; no geometry or inherited curve payload"}
    for key, value in expected.items():
        delta.require(recipe[key] == value, "recipe identity mismatch: " + key)
    delta.require(set(recipe["actions"]) == {"rig", "camera"}, "recipe requires explicit pair")
    delta.require(set(recipe["static_hashes"]) == delta.STATIC_CATEGORIES
                  and all(delta.is_sha256(v) for v in recipe["static_hashes"].values()), "incomplete static preservation categories")
    delta.require(set(recipe["producer_sha256"]) == {"prone_r15_source_delta.py", "prone_r15_source_native.py"}
                  and all(delta.is_sha256(v) for v in recipe["producer_sha256"].values()), "invalid producer identity")
    for role, fingerprint in (("rig", delta.RIG_FINGERPRINT), ("camera", delta.CAMERA_FINGERPRINT)):
        delta.require(recipe["actions"][role]["role"] == role
                      and recipe["actions"][role]["target_fingerprint"] == fingerprint, "target pair differs")
    delta.require(recipe["actions"]["rig"]["base_fingerprint"] == delta.BASE_FINGERPRINT,
                  "recipe rig baseline differs")


def extract(bpy, args):
    base, approved = args.base.resolve(), args.approved.resolve()
    delta.require(base != approved, "base and approved paths alias")
    delta.require(not args.output.exists(), "refuse to overwrite recipe")
    open_pinned(bpy, base, delta.BASE_SHA)
    prior = action_hashes(bpy)
    delta.require(len(prior) == 112, "unexpected r5 Action count")
    delta.require(prior[delta.RESET_ACTION]["legacy"] == delta.RESET_FINGERPRINT, "reset Action differs")
    base_record = action_record(bpy.data.actions[delta.BASE_ACTION])
    delta.require(delta.fingerprint(base_record) == delta.BASE_FINGERPRINT, "r5 Action differs")
    static = non_action_hashes(bpy)
    defaults = {"rig": defaults_of(bpy, delta.RIG_OBJECT), "camera": defaults_of(bpy, delta.CAMERA_OBJECT)}
    open_pinned(bpy, approved, delta.APPROVED_SHA)
    current = action_hashes(bpy)
    delta.require(all(current.get(name) == value for name, value in prior.items()), "approved source changed inherited Actions")
    delta.require(non_action_hashes(bpy) == static, "approved source has non-Action changes")
    print("PRONE_R15_INPUT_PRESERVATION_PASSED", len(prior), "inherited Actions;", len(static), "non-Action categories", flush=True)
    targets = {"rig": action_record(bpy.data.actions[delta.RIG_ACTION]),
               "camera": action_record(bpy.data.actions[delta.CAMERA_ACTION])}
    delta.require(delta.fingerprint(targets["rig"]) == delta.RIG_FINGERPRINT, "approved rig Action differs")
    delta.require(delta.fingerprint(targets["camera"]) == delta.CAMERA_FINGERPRINT, "approved camera Action differs")
    actions = {role: delta.build_action_delta(base_record if role == "rig" else delta.empty_action(),
                                              targets[role], defaults[role], role) for role in targets}
    recipe = {"schema": delta.SCHEMA, "base_sha256": delta.BASE_SHA, "approved_source_sha256": delta.APPROVED_SHA,
              "base_action": delta.BASE_ACTION, "rig_action": delta.RIG_ACTION, "camera_action": delta.CAMERA_ACTION,
              "reset_action": delta.RESET_ACTION, "reset_fingerprint": delta.RESET_FINGERPRINT,
              "clock": {"frames": 69, "fps": 60}, "static_hashes": static, "base_actions_sha256": delta.digest(prior),
              "actions": actions, "producer_sha256": producer_hashes(),
              "scope": "original authored key deltas; existing private base supplied separately; no geometry or inherited curve payload"}
    validate_recipe(recipe)
    delta.require(delta.sha(base) == delta.BASE_SHA and delta.sha(approved) == delta.APPROVED_SHA,
                  "extraction altered input bytes")
    delta.write_fresh_json(args.output, recipe)
    print("PRONE_R15_DELTA_EXTRACTED", delta.sha(args.output), flush=True)


def install_keys(curve, rows):
    curve.keyframe_points.clear()
    curve.keyframe_points.add(len(rows))
    for key, row in zip(curve.keyframe_points, rows):
        key.handle_left_type = "FREE"; key.handle_right_type = "FREE"
        key.co = row["co"]
        for field in delta.KEY_SETTINGS - {"handle_left_type", "handle_right_type"}:
            if field in row:
                setattr(key, field, row[field])
        key.handle_left = row["handle_left"]; key.handle_right = row["handle_right"]
    curve.update()
    for key, row in zip(curve.keyframe_points, rows):
        key.handle_left_type = row["handle_left_type"]; key.handle_right_type = row["handle_right_type"]
    curve.update()
    # Preserve final stored handles exactly; auto-handle recomputation is checked
    # again after saving/reopening. A mismatch is a failure, never approximated.
    for key, row in zip(curve.keyframe_points, rows):
        key.co = row["co"]
        key.handle_left = row["handle_left"]; key.handle_right = row["handle_right"]


def install_action(bpy, prior, desired, name):
    delta.require(name not in bpy.data.actions, "target Action already exists")
    action = prior.copy() if prior is not None else bpy.data.actions.new(name)
    action.name = name; action.use_fake_user = True
    existing = {} if prior is None else {delta.curve_id(c): c for c in action_record(prior)["curves"]}
    for row in desired["curves"]:
        curve = action.fcurves.find(row["path"], index=row["index"])
        if delta.curve_id(row) in existing and delta.exact_equal(existing[delta.curve_id(row)], row):
            continue
        if curve is None:
            kwargs = {"index": row["index"]}
            if row["group"]:
                kwargs["action_group"] = row["group"]
            curve = action.fcurves.new(row["path"], **kwargs)
        for field in delta.CURVE_SETTINGS - {"group"}:
            setattr(curve, field, row[field])
        if row["group"]:
            curve.group = action.groups.get(row["group"]) or action.groups.new(row["group"])
        else:
            curve.group = None
        install_keys(curve, row["keys"])
    for field in ("frame_start", "frame_end", "use_frame_range", "use_cyclic"):
        if not delta.exact_equal(getattr(action, field), desired[field]):
            setattr(action, field, desired[field])
    actual = action_record(action)
    delta.require(delta.exact_equal(actual, desired), "native Action reconstruction differs, including ordering/handles: "
                  + delta.first_difference(desired, actual))
    return action


def replay(bpy, args):
    base, output = args.base.resolve(), args.output.resolve()
    delta.require(output.suffix.lower() == ".blend" and output != base, "output must be a distinct BLEND")
    delta.require(not output.exists() and not args.receipt.exists(), "refuse to overwrite reconstruction/evidence")
    delta.require(delta.sha(args.delta) == args.delta_sha256, "delta input SHA-256 mismatch")
    recipe = delta.load_json(args.delta); validate_recipe(recipe)
    open_pinned(bpy, base, delta.BASE_SHA)
    prior = action_hashes(bpy); static = non_action_hashes(bpy)
    delta.require(len(prior) == 112 and delta.digest(prior) == recipe["base_actions_sha256"], "baseline Action set differs")
    delta.require(static == recipe["static_hashes"], "baseline non-Action data differs")
    base_action = bpy.data.actions[delta.BASE_ACTION]
    for role, original, name, obj in (("rig", base_action, delta.RIG_ACTION, delta.RIG_OBJECT),
                                       ("camera", None, delta.CAMERA_ACTION, delta.CAMERA_OBJECT)):
        baseline = action_record(original) if original else delta.empty_action()
        desired = delta.apply_action_delta(baseline, recipe["actions"][role], defaults_of(bpy, obj))
        install_action(bpy, original, desired, name)
    check_replayed(bpy, recipe, prior, static)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True, check_existing=False)
    generated = delta.sha(output)
    delta.require(generated not in (delta.BASE_SHA, delta.APPROVED_SHA), "generated serialized identity unexpectedly aliases input")
    open_pinned(bpy, output, generated)
    check_replayed(bpy, recipe, prior, static)
    delta.require(delta.sha(base) == delta.BASE_SHA and delta.sha(args.delta) == args.delta_sha256,
                  "replay inputs changed")
    receipt = {"schema": "rust-duty-prone-r15-source-replay/v1", "passed": True,
               "base_sha256": delta.BASE_SHA, "approved_source_sha256": delta.APPROVED_SHA,
               "generated_source_sha256": generated, "delta_sha256": args.delta_sha256,
               "rig_action_fingerprint": delta.RIG_FINGERPRINT, "camera_action_fingerprint": delta.CAMERA_FINGERPRINT,
               "prior_actions_preserved": len(prior), "created_actions": [delta.RIG_ACTION, delta.CAMERA_ACTION],
               "complete_action_fingerprints": {role: recipe["actions"][role]["target_complete_sha256"] for role in ("rig", "camera")},
               "static_hashes": static, "fresh_reopen_passed": True, "blender_version": bpy.app.version_string,
               "producer_sha256": producer_hashes(), "evaluated_equivalence_proved": False,
               "source_byte_identity_with_approved": False, "runtime_equivalence_proved": False,
               "saved_default_bindings_unchanged": True, "rendered": False,
               "limits": ["Motion equivalence requires the independent 1,944-time paired witness.",
                          "This generated private BLEND is never a source-only publication artifact."]}
    delta.write_fresh_json(args.receipt, receipt)
    print("PRONE_R15_SOURCE_REPLAYED", generated, delta.sha(args.receipt), flush=True)


def check_replayed(bpy, recipe, prior, static):
    current = action_hashes(bpy)
    delta.require(set(current) - set(prior) == {delta.RIG_ACTION, delta.CAMERA_ACTION}, "unexpected saved Actions")
    delta.require(all(current.get(name) == value for name, value in prior.items()), "inherited Action changed")
    delta.require(non_action_hashes(bpy) == static, "non-Action saved state changed")
    for role, name in (("rig", delta.RIG_ACTION), ("camera", delta.CAMERA_ACTION)):
        delta.require(current[name]["legacy"] == recipe["actions"][role]["target_fingerprint"]
                      and current[name]["complete"] == recipe["actions"][role]["target_complete_sha256"],
                      "fresh target Action differs")


def motion_witness(bpy):
    """Strict float64-byte hash comparison; no rounded or visually inferred pass.

    Values exist only in memory. This detects platform numeric differences too;
    a cross-platform mismatch requires diagnosis, never an automatic tolerance.
    """
    import numpy as np
    rig = bpy.data.objects[delta.RIG_OBJECT]; camera = bpy.data.objects[delta.CAMERA_OBJECT]
    scene = bpy.context.scene
    delta.require(scene.camera == camera and (scene.render.fps, scene.render.fps_base) == (60, 1.0),
                  "paired camera or clock differs")
    delta.require(delta.fingerprint(action_record(bpy.data.actions[delta.RESET_ACTION])) == delta.RESET_FINGERPRINT,
                  "canonical reset differs")
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data.use_nla = False
            for track in obj.animation_data.nla_tracks:
                track.mute = True; track.is_solo = False
    rig.animation_data.action = bpy.data.actions[delta.RESET_ACTION]
    if camera.animation_data:
        camera.animation_data.action = None
    scene.frame_set(1); rig.update_tag(); camera.update_tag(); bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()
    objects = {o.name: {k: tuple(getattr(o, k)) for k in FIELDS} for o in bpy.data.objects}
    poses = {b.name: ({k: tuple(getattr(b, k)) for k in FIELDS}, custom(b)) for b in rig.pose.bones}
    skins = sorted([o for o in bpy.data.objects if o.type == "MESH" and
                    any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers)], key=lambda o: o.name)
    delta.require(len(skins) == 3 and len(rig.pose.bones) == 148, "evaluated source topology scope differs")
    camera.animation_data_create(); camera.animation_data.use_nla = False
    def exact_hash(values):
        array = np.asarray(values, dtype="<f8")
        delta.require(bool(np.isfinite(array).all()), "non-finite evaluated motion")
        return hashlib.sha256(array.tobytes(order="C")).hexdigest()
    rows = []
    for index, frame in enumerate(delta.probe_times()):
        rig.animation_data.action = None; camera.animation_data.action = None
        for obj in bpy.data.objects:
            for field, value in objects[obj.name].items():
                setattr(obj, field, value)
        for bone in rig.pose.bones:
            for field, value in poses[bone.name][0].items():
                setattr(bone, field, value)
            for field, value in poses[bone.name][1].items():
                bone[field] = value
        rig.animation_data.action = bpy.data.actions[delta.RIG_ACTION]
        camera.animation_data.action = bpy.data.actions[delta.CAMERA_ACTION]
        scene.frame_set(math.floor(frame), subframe=frame % 1)
        rig.update_tag(); camera.update_tag(); bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get(); depsgraph.update()
        bone_values = [matrix(rig.matrix_world @ b.matrix) for b in rig.pose.bones]
        actor_values = [matrix(bpy.data.objects[name].matrix_world) for name in ACTORS]
        skin_hashes = []
        for obj in skins:
            evaluated = obj.evaluated_get(depsgraph); mesh = evaluated.to_mesh()
            try:
                points = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
                mesh.vertices.foreach_get("co", points); points = points.reshape((-1, 3))
                transform = np.asarray(evaluated.matrix_world, dtype=np.float64)
                world = points @ transform[:3, :3].T + transform[:3, 3]
                skin_hashes.append({"name": obj.name, "vertices": len(points), "sha256": exact_hash(world)})
            finally:
                evaluated.to_mesh_clear()
        rows.append({"frame": frame, "bones_world_sha256": exact_hash(bone_values),
                     "rig_world_sha256": exact_hash(matrix(rig.matrix_world)),
                     "camera_world_sha256": exact_hash(matrix(camera.matrix_world)),
                     "actors_world_sha256": exact_hash(actor_values), "skins": skin_hashes})
        if index % 128 == 0:
            print("PRONE_R15_PAIR_WITNESS", index, "/1944", flush=True)
    return {"sample_count": len(rows), "times_sha256": delta.digest(delta.probe_times()),
            "numeric_contract": "strict little-endian float64 bytes; no quantization; same Blender 4.3.2 evaluation",
            "bone_count": len(rig.pose.bones), "bone_order_sha256": delta.digest([b.name for b in rig.pose.bones]), "actors": list(ACTORS),
            "canonical_reset_action": delta.RESET_ACTION, "rows": rows}


def witness(bpy, args):
    delta.require(not args.output.exists(), "refuse to overwrite witness")
    source = args.source.resolve()
    if args.kind == "approved":
        delta.require(args.source_sha256 == delta.APPROVED_SHA, "approved witness requires pinned approved bytes")
    else:
        delta.require(args.replay_receipt is not None and args.replay_receipt_sha256 is not None,
                      "regenerated witness requires a pinned fresh-reopen receipt")
        delta.require(delta.sha(args.replay_receipt) == args.replay_receipt_sha256, "replay receipt differs")
        replay_receipt = delta.load_json(args.replay_receipt)
        delta.require(replay_receipt["passed"] is True and replay_receipt["fresh_reopen_passed"] is True
                      and replay_receipt["generated_source_sha256"] == args.source_sha256, "source does not match replay receipt")
    open_pinned(bpy, source, args.source_sha256)
    fingerprints = {name: delta.fingerprint(action_record(bpy.data.actions[name]))
                    for name in (delta.RIG_ACTION, delta.CAMERA_ACTION)}
    delta.require(fingerprints == {delta.RIG_ACTION: delta.RIG_FINGERPRINT,
                                  delta.CAMERA_ACTION: delta.CAMERA_FINGERPRINT}, "witness pair differs")
    static = non_action_hashes(bpy)
    result = {"schema": "rust-duty-prone-r15-paired-witness/v1", "kind": args.kind,
              "source_sha256": args.source_sha256, "approved_source_sha256": delta.APPROVED_SHA,
              "action_fingerprints": fingerprints,
              "complete_action_fingerprints": {role: delta.digest(action_record(bpy.data.actions[name]))
                                               for role, name in (("rig", delta.RIG_ACTION), ("camera", delta.CAMERA_ACTION))},
              "static_hashes": static,
              "blender_version": bpy.app.version_string, "producer_sha256": producer_hashes(),
              "motion": motion_witness(bpy), "source_saved": False, "rendered": False}
    delta.require(delta.sha(source) == args.source_sha256, "witness altered source bytes")
    delta.write_fresh_json(args.output, result)
    print("PRONE_R15_PAIR_WITNESS_COMPLETE", delta.sha(args.output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract")
    extract_parser.add_argument("--base", type=Path, required=True)
    extract_parser.add_argument("--approved", type=Path, required=True)
    extract_parser.add_argument("--output", type=Path, required=True)
    replay_parser = commands.add_parser("replay")
    for name in ("base", "delta", "output", "receipt"):
        replay_parser.add_argument("--" + name, type=Path, required=True)
    replay_parser.add_argument("--delta-sha256", required=True)
    witness_parser = commands.add_parser("witness")
    witness_parser.add_argument("--source", type=Path, required=True)
    witness_parser.add_argument("--source-sha256", required=True)
    witness_parser.add_argument("--kind", choices=("approved", "regenerated"), required=True)
    witness_parser.add_argument("--replay-receipt", type=Path)
    witness_parser.add_argument("--replay-receipt-sha256")
    witness_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    import bpy
    native_preflight(bpy)
    {"extract": extract, "replay": replay, "witness": witness}[args.command](bpy, args)


if __name__ == "__main__":
    main()
