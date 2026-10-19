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
import onehand_v6_source_delta as delta

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


def action_metadata(action):
    return {"use_fake_user": action.use_fake_user, "properties": custom(action)}


def action_auxiliary(action):
    return {"groups": [{"name": group.name, "props": props(group)} for group in action.groups],
            "markers": [props(marker) for marker in action.pose_markers], "id_root": action.id_root}


def action_hashes(bpy):
    return {a.name: {"legacy": delta.fingerprint(action_record(a)),
                     "complete": delta.digest(action_record(a)),
                     "metadata": delta.digest(action_metadata(a)), "auxiliary": delta.digest(action_auxiliary(a))}
            for a in bpy.data.actions}


def non_action_hashes(bpy):
    """Only hashes leave memory; includes existing audited preservation categories.

    The full pose-default hash is retained. A second explicitly named projection
    excludes exactly the 16 separately checked lineage scalar exceptions.
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
                                          scene.render.resolution_percentage],
                           "pixel_aspect": [scene.render.pixel_aspect_x, scene.render.pixel_aspect_y]}
              for scene in bpy.data.scenes}
    records = {"meshes": mesh_records, "armatures": armatures, "objects_and_bindings": objects,
               "object_defaults": defaults, "pose_channel_defaults": pose_defaults,
               "pose_defaults_except_lineage": delta.mask_pose_exceptions(pose_defaults), "drivers": drivers, "nla": nla,
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


CODE_FILES = ("onehand_v6_source_delta.py", "onehand_v6_source_native.py", "run_onehand_v6_source_proof.py",
              "dense-times.json", "pose-corrections.json")
SKINS = tuple("Actual arms mesh " + str(i) for i in range(3))
GEOMETRY = SKINS + ACTORS
NUMERIC_CONTRACT = "strict little-endian float64 coordinates and int64 topology bytes; no quantization; Blender 4.3.2"


def producer_hashes():
    here = Path(__file__).resolve().parent
    return {name: delta.sha(here / name) for name in CODE_FILES}


def pose_value(bpy, row):
    obj, bone, field, component = row["path"]
    pb = bpy.data.objects[obj].pose.bones[bone]
    return atom(pb[component]) if field == "custom_properties" else float(getattr(pb, field)[component])


def driven_path(row):
    obj, bone, field, component = row["path"]
    path = 'pose.bones["' + bone + '"]'
    return obj, path + ('["' + component + '"]' if field == "custom_properties" else "." + field), 0 if field == "custom_properties" else component


def verify_pose_scope(bpy, expected):
    for row in delta.pose_corrections():
        obj, path, index = driven_path(row)
        data = bpy.data.objects[obj].animation_data
        drivers = [fc for fc in data.drivers if fc.data_path == path and fc.array_index == index]
        is_driven = row["mode"] == "unchanged_driver_recompute"
        delta.require(len(drivers) == int(is_driven), "pose correction driver classification differs")
        for name in (delta.BASE_ACTION, delta.RIG_ACTION):
            if name in bpy.data.actions:
                delta.require(bpy.data.actions[name].fcurves.find(path, index=index) is None,
                              "lineage correction unexpectedly overlaps a keyed scalar")
        delta.require(delta.digest(pose_value(bpy, row)) == row[expected + "_sha256"],
                      "lineage pose scalar hash differs: " + str(row["path"]))


def static_same_except_pose(base, target):
    delta.require(set(base) == set(target) == delta.STATIC_CATEGORIES, "static category scope differs")
    for key in sorted(delta.STATIC_CATEGORIES - {"pose_channel_defaults"}):
        delta.require(base[key] == target[key], "unexpected non-Action difference: " + key)


def validate_recipe(recipe):
    fields = {"schema", "base_sha256", "approved_source_sha256", "base_action", "rig_action", "camera_action",
              "reset_action", "reset_fingerprint", "clock", "base_static_hashes", "approved_static_hashes",
              "inherited_actions", "action", "metadata", "action_auxiliary_sha256", "producer_sha256",
              "pose_corrections_sha256", "scope"}
    delta.require(set(recipe) == fields, "unexpected recipe fields")
    expected = {"schema": delta.SCHEMA, "base_sha256": delta.BASE_SHA,
                "approved_source_sha256": delta.APPROVED_SHA, "base_action": delta.BASE_ACTION,
                "rig_action": delta.RIG_ACTION, "camera_action": None, "reset_action": delta.RESET_ACTION,
                "reset_fingerprint": delta.RESET_FINGERPRINT,
                "clock": {"frames": [1, 96], "fps": [60, 1], "grid_sha256": delta.GRID_SHA, "sample_count": 4240},
                "pose_corrections_sha256": delta.POSE_CORRECTIONS_SHA,
                "scope": "Original final Action deltas and 12 original scalar corrections; inherited content by hash reference only."}
    for key, value in expected.items():
        delta.require(recipe[key] == value, "recipe identity differs: " + key)
    static_same_except_pose(recipe["base_static_hashes"], recipe["approved_static_hashes"])
    for state in (recipe["base_static_hashes"], recipe["approved_static_hashes"]):
        delta.require(all(delta.is_sha256(v) for v in state.values()), "invalid static hash")
    delta.require(len(recipe["inherited_actions"]) == 88, "expected all 88 inherited Actions")
    for record in recipe["inherited_actions"].values():
        delta.require(set(record) == {"legacy", "complete", "metadata", "auxiliary"}
                      and all(delta.is_sha256(v) for v in record.values()), "invalid inherited Action reference")
    delta.require(recipe["inherited_actions"][delta.BASE_ACTION]["legacy"] == delta.BASE_FINGERPRINT
                  and recipe["inherited_actions"][delta.RESET_ACTION]["legacy"] == delta.RESET_FINGERPRINT,
                  "baseline or canonical reset Action differs")
    delta.validate_delta_shape(recipe["action"])
    delta.validate_metadata_shape(recipe["metadata"])
    delta.require(recipe["action"]["role"] == "rig"
                  and recipe["action"]["base_fingerprint"] == delta.BASE_FINGERPRINT
                  and recipe["action"]["target_fingerprint"] == delta.RIG_FINGERPRINT,
                  "target Action identity differs")
    delta.require(recipe["action_auxiliary_sha256"] == recipe["inherited_actions"][delta.BASE_ACTION]["auxiliary"],
                  "target group/marker state must remain inherited")
    delta.require(set(recipe["producer_sha256"]) == set(CODE_FILES)
                  and all(delta.is_sha256(v) for v in recipe["producer_sha256"].values()), "invalid producer pins")


def verify_scene_contract(bpy):
    scene = bpy.context.scene
    rig = bpy.data.objects[delta.RIG_OBJECT]; camera = bpy.data.objects[delta.CAMERA_OBJECT]
    delta.require(scene.camera == camera and camera.animation_data is None,
                  "one-hand source requires its static camera with no animation data")
    delta.require((scene.render.fps, scene.render.fps_base) == (60, 1.0), "source native clock differs")
    delta.require(len(rig.pose.bones) == len(rig.data.bones) == 148, "source skeleton count differs")
    delta.require(tuple(sorted(o.name for o in bpy.data.objects if o.type == "MESH" and
                  any(m.type == "ARMATURE" and m.object == rig for m in o.modifiers))) == SKINS,
                  "skin object inventory differs")
    delta.require(sum(len(bpy.data.objects[n].data.vertices) for n in SKINS) == 10234, "skin vertex count differs")
    delta.require(all(bpy.data.objects[n].type == "MESH" for n in ACTORS), "actual rigid actor is missing")


def extract(bpy, args):
    base, approved = args.base.resolve(), args.approved.resolve()
    delta.require(base != approved and not args.output.exists(), "input alias or existing recipe")
    open_pinned(bpy, base, delta.BASE_SHA); verify_scene_contract(bpy)
    prior = action_hashes(bpy)
    delta.require(len(prior) == 88 and prior[delta.BASE_ACTION]["legacy"] == delta.BASE_FINGERPRINT,
                  "expected baseline 88 Actions and exact one-hand r3")
    delta.require(prior[delta.RESET_ACTION]["legacy"] == delta.RESET_FINGERPRINT, "canonical reset differs")
    verify_pose_scope(bpy, "before")
    base_record = action_record(bpy.data.actions[delta.BASE_ACTION])
    base_meta = action_metadata(bpy.data.actions[delta.BASE_ACTION])
    base_aux = delta.digest(action_auxiliary(bpy.data.actions[delta.BASE_ACTION]))
    base_static = non_action_hashes(bpy)
    open_pinned(bpy, approved, delta.APPROVED_SHA); verify_scene_contract(bpy)
    current = action_hashes(bpy)
    delta.require(len(current) == 95 and all(current.get(k) == v for k, v in prior.items()),
                  "approved source changed inherited Actions")
    verify_pose_scope(bpy, "after")
    approved_static = non_action_hashes(bpy); static_same_except_pose(base_static, approved_static)
    action = bpy.data.actions[delta.RIG_ACTION]
    target = action_record(action)
    delta.require(delta.fingerprint(target) == delta.RIG_FINGERPRINT, "approved target fingerprint differs")
    delta.require(delta.digest(action_auxiliary(action)) == base_aux, "target group/marker state differs")
    recipe = {"schema": delta.SCHEMA, "base_sha256": delta.BASE_SHA, "approved_source_sha256": delta.APPROVED_SHA,
              "base_action": delta.BASE_ACTION, "rig_action": delta.RIG_ACTION, "camera_action": None,
              "reset_action": delta.RESET_ACTION, "reset_fingerprint": delta.RESET_FINGERPRINT,
              "clock": {"frames": [1, 96], "fps": [60, 1], "grid_sha256": delta.GRID_SHA, "sample_count": 4240},
              "base_static_hashes": base_static, "approved_static_hashes": approved_static,
              "inherited_actions": prior, "action": delta.build_action_delta(base_record, target, {}, "rig"),
              "metadata": delta.metadata_delta(base_meta, action_metadata(action)), "action_auxiliary_sha256": base_aux,
              "pose_corrections_sha256": delta.POSE_CORRECTIONS_SHA, "producer_sha256": producer_hashes(),
              "scope": "Original final Action deltas and 12 original scalar corrections; inherited content by hash reference only."}
    validate_recipe(recipe)
    delta.require(delta.sha(base) == delta.BASE_SHA and delta.sha(approved) == delta.APPROVED_SHA,
                  "extraction changed input bytes")
    delta.write_fresh_json(args.output, recipe)
    print("ONEHAND_V6_DELTA_EXTRACTED", delta.sha(args.output), flush=True)


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


def check_replayed(bpy, recipe):
    verify_scene_contract(bpy)
    prior = recipe["inherited_actions"]; current = action_hashes(bpy)
    delta.require(len(current) == 89 and set(current) - set(prior) == {delta.RIG_ACTION}, "unexpected saved Action set")
    delta.require(all(current.get(k) == v for k, v in prior.items()), "an original Action changed")
    wanted = {"legacy": delta.RIG_FINGERPRINT, "complete": recipe["action"]["target_complete_sha256"],
              "metadata": recipe["metadata"]["after_sha256"], "auxiliary": recipe["action_auxiliary_sha256"]}
    delta.require(current[delta.RIG_ACTION] == wanted, "replayed full Action differs")
    verify_pose_scope(bpy, "after")
    actual = non_action_hashes(bpy)
    for key, value in recipe["approved_static_hashes"].items():
        delta.require(actual[key] == value, "replayed static state differs: " + key)


def replay(bpy, args):
    base, output = args.base.resolve(), args.output.resolve()
    delta.require(output.suffix.lower() == ".blend" and output != base, "output must be a distinct BLEND")
    delta.require(not output.exists() and not args.receipt.exists(), "refuse to overwrite replay or receipt")
    delta.require(delta.sha(args.delta) == args.delta_sha256, "delta bytes differ")
    recipe = delta.load_json(args.delta); validate_recipe(recipe)
    delta.require(recipe["producer_sha256"] == producer_hashes(), "replay producer code differs")
    open_pinned(bpy, base, delta.BASE_SHA); verify_scene_contract(bpy)
    delta.require(action_hashes(bpy) == recipe["inherited_actions"], "baseline Action set differs")
    delta.require(non_action_hashes(bpy) == recipe["base_static_hashes"], "baseline static state differs")
    verify_pose_scope(bpy, "before")
    original = bpy.data.actions[delta.BASE_ACTION]
    desired = delta.apply_action_delta(action_record(original), recipe["action"], {})
    target_meta = delta.apply_metadata_delta(action_metadata(original), recipe["metadata"])
    action = install_action(bpy, original, desired, delta.RIG_ACTION)
    action.use_fake_user = target_meta["use_fake_user"]
    for key, operation in recipe["metadata"]["properties"].items():
        action[key] = operation["value"]
    # No driven output or wholesale defaults are written. Exact 12-scalar deltas only.
    for row in delta.pose_corrections():
        if row["mode"] == "original_scalar_delta":
            value = delta.corrected_scalar(pose_value(bpy, row), row)
            obj, bone, field, component = row["path"]
            getattr(bpy.data.objects[obj].pose.bones[bone], field)[component] = value
    # Re-evaluate the unchanged original drivers at the original saved scene state.
    # Any unrelated default drift is a failure, not normalized away.
    bpy.data.objects[delta.RIG_OBJECT].update_tag()
    bpy.context.view_layer.update(); bpy.context.evaluated_depsgraph_get().update()
    check_replayed(bpy, recipe)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True, check_existing=False)
    generated = delta.sha(output)
    delta.require(generated not in (delta.BASE_SHA, delta.APPROVED_SHA), "regenerated bytes alias an input")
    open_pinned(bpy, output, generated); check_replayed(bpy, recipe)
    delta.require(delta.sha(base) == delta.BASE_SHA and delta.sha(args.delta) == args.delta_sha256, "replay input changed")
    receipt = {"schema": "rust-duty-onehand-v6-source-replay/v1", "passed": True, "fresh_reopen_passed": True,
               "base_sha256": delta.BASE_SHA, "approved_source_sha256": delta.APPROVED_SHA,
               "generated_source_sha256": generated, "delta_sha256": args.delta_sha256,
               "prior_actions_preserved": 88, "created_actions": [delta.RIG_ACTION], "result_action_count": 89,
               "action_hashes": action_hashes(bpy)[delta.RIG_ACTION], "static_hashes": non_action_hashes(bpy),
               "original_scalar_corrections_applied": 12, "unchanged_driven_outputs_recomputed": 4,
               "producer_sha256": producer_hashes(), "blender_version": bpy.app.version_string,
               "source_byte_identity_with_approved": False, "evaluated_equivalence_proved": False,
               "runtime_equivalence_proved": False, "rendered": False,
               "limits": ["Independent exact 4240-time witness comparison remains required.",
                          "The regenerated private BLEND is never a source-only publication artifact."]}
    delta.write_fresh_json(args.receipt, receipt)
    print("ONEHAND_V6_SOURCE_REPLAYED", generated, delta.sha(args.receipt), flush=True)
def motion_witness(bpy, chunk_index):
    """Bounded hash-only full geometry proof. No matrices or vertices leave memory."""
    import numpy as np
    rig = bpy.data.objects[delta.RIG_OBJECT]; camera = bpy.data.objects[delta.CAMERA_OBJECT]
    scene = bpy.context.scene
    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data.use_nla = False
            for track in obj.animation_data.nla_tracks:
                track.mute = True; track.is_solo = False
    rig.animation_data.action = bpy.data.actions[delta.RESET_ACTION]
    scene.frame_set(1); rig.update_tag(); bpy.context.view_layer.update()
    bpy.context.evaluated_depsgraph_get().update()
    rig.animation_data.action = bpy.data.actions[delta.RIG_ACTION]
    delta.require(list(rig.animation_data.action.frame_range) == [1.0, 96.0], "source Action range differs")

    def evaluate(frame):
        scene.frame_set(math.floor(frame), subframe=frame % 1)
        rig.update_tag(); camera.update_tag(); bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get(); dg.update()
        return dg

    def exact_hash(values, dtype="<f8"):
        array = np.asarray(values, dtype=dtype)
        delta.require(bool(np.isfinite(array).all()), "non-finite evaluated data")
        return hashlib.sha256(array.tobytes(order="C")).hexdigest()

    def projection():
        return {"rays": [list(v.normalized()) for v in camera.data.view_frame(scene=scene)],
                **{k: atom(getattr(camera.data, k)) for k in
                   ("type", "lens", "sensor_fit", "sensor_width", "sensor_height", "shift_x", "shift_y", "clip_start", "clip_end")},
                "resolution": [scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage],
                "pixel_aspect": [scene.render.pixel_aspect_x, scene.render.pixel_aspect_y]}

    def geometry(dg):
        output = []
        for name in GEOMETRY:
            evaluated = bpy.data.objects[name].evaluated_get(dg); mesh = evaluated.to_mesh()
            try:
                points = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
                mesh.vertices.foreach_get("co", points); points = points.reshape((-1, 3))
                transform = np.asarray(evaluated.matrix_world, dtype=np.float64)
                world = points @ transform[:3, :3].T + transform[:3, 3]
                edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
                mesh.edges.foreach_get("vertices", edges)
                loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
                mesh.loops.foreach_get("vertex_index", loop_vertices)
                polygons = np.asarray([(p.loop_start, p.loop_total, p.material_index, int(p.use_smooth))
                                       for p in mesh.polygons], dtype="<i8")
                topology = {"edge_indices_sha256": exact_hash(edges, "<i8"),
                            "loop_vertex_indices_sha256": exact_hash(loop_vertices, "<i8"),
                            "polygon_records_sha256": exact_hash(polygons, "<i8"),
                            "vertices": len(mesh.vertices), "edges": len(mesh.edges),
                            "loops": len(mesh.loops), "polygons": len(mesh.polygons)}
                output.append({"name": name, "role": "skin" if name in SKINS else "rigid",
                               "vertices": len(points), "local_positions_sha256": exact_hash(points),
                               "world_positions_sha256": exact_hash(world), "topology_sha256": delta.digest(topology)})
            finally:
                evaluated.to_mesh_clear()
        delta.require(sum(r["vertices"] for r in output if r["role"] == "skin") == 10234,
                      "evaluated skin vertex inventory differs")
        return output

    dg = evaluate(1)
    base_rig = exact_hash(matrix(rig.evaluated_get(dg).matrix_world))
    base_camera = exact_hash(matrix(camera.evaluated_get(dg).matrix_world))
    base_projection = delta.digest(projection())
    base_geometry = geometry(dg)
    bone_order = [b.name for b in rig.pose.bones]
    object_order = sorted(o.name for o in bpy.data.objects)
    rest_hash = exact_hash([matrix(rig.matrix_world @ b.matrix_local) for b in rig.data.bones])
    hierarchy_hash = delta.digest([(b.name, b.parent.name if b.parent else None) for b in rig.data.bones])
    start, stop = delta.chunk_bounds(chunk_index); rows = []; times = delta.probe_times()
    for index in range(start, stop):
        frame = times[index]
        dg = evaluate(frame); evaluated_rig = rig.evaluated_get(dg)
        rig_hash = exact_hash(matrix(evaluated_rig.matrix_world))
        camera_hash = exact_hash(matrix(camera.evaluated_get(dg).matrix_world))
        projection_hash = delta.digest(projection())
        delta.require(rig_hash == base_rig and camera_hash == base_camera and projection_hash == base_projection,
                      "static rig/camera/projection contract changed")
        geometry_rows = geometry(dg)
        for actual, initial in zip(geometry_rows, base_geometry):
            delta.require(actual["name"] == initial["name"] and actual["vertices"] == initial["vertices"]
                          and actual["topology_sha256"] == initial["topology_sha256"], "evaluated geometry topology changed")
            if actual["role"] == "rigid":
                delta.require(actual["local_positions_sha256"] == initial["local_positions_sha256"],
                              "actual actor is not rigid at sampled time")
        rows.append({"sample_index": index, "frame": frame,
                     "bones_world_sha256": exact_hash([matrix(evaluated_rig.matrix_world @ evaluated_rig.pose.bones[n].matrix)
                                                        for n in bone_order]),
                     "rig_world_sha256": rig_hash, "camera_world_sha256": camera_hash,
                     "projection_sha256": projection_hash,
                     "actors_world_sha256": exact_hash([matrix(bpy.data.objects[n].evaluated_get(dg).matrix_world) for n in ACTORS]),
                     "all_objects_world_sha256": exact_hash([matrix(bpy.data.objects[n].evaluated_get(dg).matrix_world) for n in object_order]),
                     "geometry": geometry_rows})
        if (index - start) % 32 == 0:
            print("ONEHAND_V6_HASH_WITNESS", index, "/4240", flush=True)
    return {"chunk_index": chunk_index, "index_range_half_open": [start, stop], "sample_count": len(rows),
            "grid_sha256": delta.GRID_SHA, "numeric_contract": NUMERIC_CONTRACT,
            "bone_count": 148, "bone_order_sha256": delta.digest(bone_order),
            "object_order_sha256": delta.digest(object_order), "hierarchy_sha256": hierarchy_hash,
            "rest_world_sha256": rest_hash, "actors": list(ACTORS), "skins": list(SKINS),
            "canonical_reset_action": delta.RESET_ACTION, "frame1_geometry": base_geometry,
            "static_rig_world_sha256": base_rig, "static_camera_world_sha256": base_camera,
            "static_projection_sha256": base_projection, "rows": rows}


def witness(bpy, args):
    delta.require(not args.output.exists(), "refuse to overwrite witness")
    delta.require(delta.sha(args.delta) == args.delta_sha256, "witness delta bytes differ")
    recipe = delta.load_json(args.delta); validate_recipe(recipe)
    delta.require(recipe["producer_sha256"] == producer_hashes(), "witness producer code differs")
    if args.kind == "approved":
        delta.require(args.source_sha256 == delta.APPROVED_SHA, "approved witness must use frozen bytes")
    else:
        delta.require(args.replay_receipt is not None and args.replay_receipt_sha256 is not None,
                      "regenerated witness needs pinned fresh-reopen receipt")
        delta.require(delta.sha(args.replay_receipt) == args.replay_receipt_sha256, "replay receipt bytes differ")
        receipt = delta.load_json(args.replay_receipt)
        delta.require(receipt["passed"] is True and receipt["fresh_reopen_passed"] is True
                      and receipt["generated_source_sha256"] == args.source_sha256
                      and receipt["delta_sha256"] == args.delta_sha256
                      and receipt["producer_sha256"] == producer_hashes(), "regenerated source provenance differs")
    source = args.source.resolve(); open_pinned(bpy, source, args.source_sha256); verify_scene_contract(bpy)
    if args.kind == "regenerated":
        check_replayed(bpy, recipe)
    else:
        current = action_hashes(bpy)
        delta.require(len(current) == 95 and all(current.get(k) == v for k, v in recipe["inherited_actions"].items()),
                      "approved inherited Action scope differs")
        verify_pose_scope(bpy, "after")
        delta.require(non_action_hashes(bpy) == recipe["approved_static_hashes"], "approved static state differs")
    hashes = action_hashes(bpy)[delta.RIG_ACTION]
    expected = {"legacy": delta.RIG_FINGERPRINT, "complete": recipe["action"]["target_complete_sha256"],
                "metadata": recipe["metadata"]["after_sha256"], "auxiliary": recipe["action_auxiliary_sha256"]}
    delta.require(hashes == expected, "witness full Action differs")
    result = {"schema": "rust-duty-onehand-v6-source-witness-chunk/v1", "kind": args.kind,
              "source_sha256": args.source_sha256, "approved_source_sha256": delta.APPROVED_SHA,
              "delta_sha256": args.delta_sha256, "action_hashes": hashes,
              "inherited_actions_sha256": delta.digest(recipe["inherited_actions"]),
              "static_hashes": non_action_hashes(bpy), "producer_sha256": producer_hashes(),
              "blender_version": bpy.app.version_string, "motion": motion_witness(bpy, args.chunk_index),
              "source_saved": False, "source_bytes_unchanged": delta.sha(source) == args.source_sha256,
              "rendered": False, "runtime_equivalence_proved": False}
    delta.require(result["source_bytes_unchanged"], "witness changed source bytes")
    delta.write_fresh_json(args.output, result)
    print("ONEHAND_V6_WITNESS_COMPLETE", args.chunk_index, delta.sha(args.output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract")
    for name in ("base", "approved", "output"):
        extract_parser.add_argument("--" + name, type=Path, required=True)
    replay_parser = commands.add_parser("replay")
    for name in ("base", "delta", "output", "receipt"):
        replay_parser.add_argument("--" + name, type=Path, required=True)
    replay_parser.add_argument("--delta-sha256", required=True)
    witness_parser = commands.add_parser("witness")
    for name in ("source", "delta", "output"):
        witness_parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-sha256", "delta-sha256"):
        witness_parser.add_argument("--" + name, required=True)
    witness_parser.add_argument("--kind", choices=("approved", "regenerated"), required=True)
    witness_parser.add_argument("--chunk-index", type=int, required=True)
    witness_parser.add_argument("--replay-receipt", type=Path)
    witness_parser.add_argument("--replay-receipt-sha256")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    import bpy
    native_preflight(bpy)
    {"extract": extract, "replay": replay, "witness": witness}[args.command](bpy, args)


if __name__ == "__main__":
    main()
