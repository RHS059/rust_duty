"""Pure Blender-data snapshots used to verify this authoring handoff.

No handlers or embedded source scripts are executed. Run under Blender 4.3.2.
"""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def action_fingerprint(action):
    # Compatible with the original source_provenance.json fingerprint.
    return digest([
        (curve.data_path, curve.array_index, [
            (list(key.co), list(key.handle_left), list(key.handle_right), key.interpolation)
            for key in curve.keyframe_points
        ]) for curve in action.fcurves
    ])


def nla_snapshot(bpy):
    result = {}
    for obj in bpy.data.objects:
        data = obj.animation_data
        if data is None:
            continue
        result[obj.name] = {
            "action": data.action.name if data.action else None,
            "use_nla": data.use_nla,
            "tracks": [{
                "name": track.name, "mute": track.mute, "is_solo": track.is_solo,
                "strips": [{
                    "name": strip.name,
                    "action": strip.action.name if strip.action else None,
                    **{key: getattr(strip, key) for key in (
                        "frame_start", "frame_end", "action_frame_start", "action_frame_end",
                        "scale", "repeat", "blend_type", "extrapolation", "influence",
                        "mute", "use_auto_blend", "blend_in", "blend_out",
                    )},
                } for strip in track.strips],
            } for track in data.nla_tracks],
        }
    return result


def snapshot(bpy):
    return {
        "actions": {action.name: action_fingerprint(action) for action in bpy.data.actions},
        "nla": nla_snapshot(bpy),
        "packed_images": {
            image.name: hashlib.sha256(bytes(image.packed_file.data)).hexdigest()
            for image in bpy.data.images if image.packed_file
        },
        "drivers": {
            obj.name: [{
                "data_path": curve.data_path, "array_index": curve.array_index,
                "type": curve.driver.type, "expression": curve.driver.expression,
                "variables": [{
                    "name": variable.name, "type": variable.type,
                    "targets": [{
                        "id": target.id.name if target.id else None,
                        **{key: getattr(target, key) for key in (
                            "data_path", "bone_target", "transform_type", "transform_space",
                            "rotation_mode",
                        )},
                    } for target in variable.targets],
                } for variable in curve.driver.variables],
            } for curve in obj.animation_data.drivers]
            for obj in bpy.data.objects if obj.animation_data and obj.animation_data.drivers
        },
    }
