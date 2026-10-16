"""Sparse original-Action corrections over an independently supplied private base.

Pure Python: this module never opens Blender, downloads, or publishes anything.
Unchanged keys/curves remain references to the permitted existing baseline.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import struct

SCHEMA = "rust-duty-onehand-v6-original-delta/v1"
BASE_SHA = "6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79"
APPROVED_SHA = "b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77"
BASE_ACTION = "aella_mantle_onehand_r3"
BASE_FINGERPRINT = "ca59e0f53fdde2a642432345119a65e0dcb04fad11838a4a0484254fdaf958af"
RIG_ACTION = "aella_mantle_onehand_r6_camera_reconstructed_v6"
RIG_FINGERPRINT = "c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01"
CAMERA_ACTION = None
CAMERA_FINGERPRINT = None
RESET_ACTION = "RD_00_Supplied_Base_Guarded_Recovered"
RESET_FINGERPRINT = "49b7da5f9d6ea12be52bade40b09aeb67d6adc6eb34a1a7026e3f111b3c61ed8"
RIG_OBJECT = "Arms"
CAMERA_OBJECT = "RD First Person Review"
BLENDER_VERSION = "4.3.2"
COORDINATES = ("co", "handle_left", "handle_right")
KEY_SETTINGS = frozenset(("interpolation", "handle_left_type", "handle_right_type", "type",
                         "easing", "amplitude", "back", "period", "select_control_point",
                         "select_left_handle", "select_right_handle"))
CURVE_SETTINGS = frozenset(("extrapolation", "mute", "lock", "hide", "select", "color_mode",
                           "color", "auto_smoothing", "group"))
ACTION_SETTINGS = frozenset(("use_frame_range", "frame_start", "frame_end", "use_cyclic"))
OBJECT_PATHS = frozenset()  # The one-hand camera and rig object are static.
RIG_PATHS = frozenset('pose.bones["' + bone + '"].' + channel
    for bone in ("righthand_prop", "righthand_prop_lefthand")
    for channel in ("location", "rotation_euler")) | {'pose.bones["elbow_pole_r"].location'}
SCALAR_PATHS = frozenset('pose.bones["righthand_prop_lefthand"]["' + key + '"]'
    for key in ("weapon_follow", "magazine_follow", "forearm_roll", "wrist_flex", "wrist_twist",
                "wrist_deviation", "thumb_curl", "index_curl", "middle_curl", "ring_curl", "pinky_curl"))
STATIC_CATEGORIES = frozenset(("meshes", "armatures", "objects_and_bindings", "object_defaults",
    "pose_channel_defaults", "drivers", "nla", "materials", "cameras", "scene", "packed_images",
    "embedded_text", "collections", "pose_defaults_except_lineage"))
MAX_JSON_BYTES = 32 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def exact_equal(left, right):
    """Equality of the canonical fingerprint representation, including zero sign."""
    return digest(left) == digest(right)


def first_difference(expected, actual, path="record"):
    """Return only field/index and type details; never expose compared values."""
    if exact_equal(expected, actual):
        return "none"
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            child = path + "." + str(key)
            if key not in expected or key not in actual:
                return child + " (missing or unexpected field)"
            if not exact_equal(expected[key], actual[key]):
                return first_difference(expected[key], actual[key], child)
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            return path + " (sequence length differs)"
        for index, (left, right) in enumerate(zip(expected, actual)):
            if not exact_equal(left, right):
                return first_difference(left, right, path + "[" + str(index) + "]")
    return path + " (" + type(expected).__name__ + "/" + type(actual).__name__ + " differ; values redacted)"


def is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def f32(value):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), "non-finite or non-numeric coordinate")
    return struct.unpack("<f", struct.pack("<f", value))[0]


def fingerprint(record):
    return digest([(c["path"], c["index"], [(k["co"], k["handle_left"], k["handle_right"],
                    k["interpolation"]) for k in c["keys"]]) for c in record["curves"]])


def complete_fingerprint(record):
    """Complete curve/handle/setting representation, separately from Action metadata."""
    return digest(record)


GRID_SHA = "a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f"
SAMPLE_COUNT = 4240
CHUNK_SIZE = 256


def probe_times(path=None):
    path = Path(path) if path else Path(__file__).with_name("dense-times.json")
    require(sha(path) == GRID_SHA, "exact 4240-time grid bytes differ")
    times = load_json(path)
    require(isinstance(times, list) and len(times) == SAMPLE_COUNT
            and times == sorted(set(times)) and times[0] == 1 and times[-1] == 96
            and all(isinstance(t, (int, float)) and not isinstance(t, bool)
                    and math.isfinite(t) for t in times), "invalid source clock")
    return times


def chunk_bounds(index):
    require(type(index) is int and 0 <= index < math.ceil(SAMPLE_COUNT / CHUNK_SIZE), "invalid chunk index")
    return index * CHUNK_SIZE, min((index + 1) * CHUNK_SIZE, SAMPLE_COUNT)


def empty_action():
    return {"curves": [], "use_frame_range": False, "frame_start": 0.0,
            "frame_end": 0.0, "use_cyclic": False}


def curve_id(curve):
    return curve["path"], curve["index"]


def _key_map(curve):
    keys = curve["keys"]
    frames = [k["co"][0] for k in keys]
    require(frames == sorted(set(frames)), "keys must have unique ascending frames")
    return dict(zip(frames, keys))


def validate_record(record):
    require(set(record) == {"curves"} | ACTION_SETTINGS, "unsupported Action state")
    seen = set()
    for curve in record["curves"]:
        require(set(curve) == {"path", "index", "modifiers", "samples", "keys"} | CURVE_SETTINGS,
                "unsupported FCurve state")
        require(curve_id(curve) not in seen, "duplicate FCurve identity")
        seen.add(curve_id(curve))
        for key in _key_map(curve).values():
            require(set(key) <= set(COORDINATES) | KEY_SETTINGS | {"co_ui"}, "unsupported key property")
            require(set(COORDINATES) <= set(key), "missing key coordinate")
            for field in COORDINATES:
                require(len(key[field]) == 2, "invalid key coordinate shape")
                for value in key[field]:
                    require(math.isfinite(value), "non-finite key")
            if "co_ui" in key:
                require(exact_equal(key["co_ui"], key["co"]), "unexpected distinct co_ui")
    digest(record)  # Reject non-finite numbers in every remaining field too.


def _origin(curve, frame, default_value):
    """Encoding origin only; never claims to evaluate a Bezier baseline."""
    if curve is not None:
        keys = curve["keys"]
        require(bool(keys), "an inherited correction curve has no keys")
        mapping = _key_map(curve)
        if frame in mapping:
            return copy.deepcopy(mapping[frame])
        lo = max((k for k in keys if k["co"][0] < frame), key=lambda k: k["co"][0], default=keys[0])
        hi = min((k for k in keys if k["co"][0] > frame), key=lambda k: k["co"][0], default=keys[-1])
        span = hi["co"][0] - lo["co"][0]
        weight = 0.0 if span == 0 else (frame - lo["co"][0]) / span
        value = f32(lo["co"][1] + weight * (hi["co"][1] - lo["co"][1]))
        result = copy.deepcopy(lo)
    else:
        value = f32(default_value)
        result = {}  # Newly authored settings only, no inherited key payload.
    for field in COORDINATES:
        result[field] = [float(frame), value]
    if "co_ui" in result:
        result["co_ui"] = result["co"][:]
    return result


def _allowed(path, index, role, added=False):
    require(role == "rig", "one-hand has no camera Action")
    require(not added, "all one-hand correction curves must reference inherited curves")
    require(type(index) is int and 0 <= index < 3, "curve axis outside authored scope")
    require(path in RIG_PATHS or (path in SCALAR_PATHS and index == 0), "curve outside authored allowlist")


def _default(defaults, path, index):
    require(path in OBJECT_PATHS, "missing inherited curve cannot use an arbitrary default")
    return defaults[path][index]


def _key_delta(origin, target):
    require(set(origin) <= set(target), "removing key properties is unsupported")
    change = {"delta": {}, "settings": {}, "zero_signs": []}
    for field in COORDINATES:
        if not exact_equal(origin[field], target[field]):
            delta = [b - a for a, b in zip(origin[field], target[field])]
            recovered = [f32(a + d) for a, d in zip(origin[field], delta)]
            require(recovered == target[field], "float32 delta cannot exactly reconstruct target")
            for axis, (value, wanted) in enumerate(zip(recovered, target[field])):
                if value == wanted == 0.0 and math.copysign(1.0, value) != math.copysign(1.0, wanted):
                    change["zero_signs"].append([field, axis, int(math.copysign(1.0, wanted))])
            change["delta"][field] = delta
    for field in KEY_SETTINGS:
        if field in target and (field not in origin or not exact_equal(origin[field], target[field])):
            change["settings"][field] = target[field]
    # co_ui is an alias of co, not a second independently serialized transform.
    change["co_ui_present"] = "co_ui" in target
    return change


def _apply_key(origin, operation):
    require(set(operation) == {"op", "frame", "before_sha256", "delta", "settings", "co_ui_present", "zero_signs"},
            "unexpected key-operation field")
    require(set(operation["delta"]) <= set(COORDINATES), "forbidden key-delta field")
    require(set(operation["settings"]) <= KEY_SETTINGS, "forbidden key-setting field")
    result = copy.deepcopy(origin)
    for field, delta in operation["delta"].items():
        require(isinstance(delta, list) and len(delta) == 2, "invalid delta shape")
        result[field] = [f32(a + d) for a, d in zip(origin[field], delta)]
    signed = set()
    for flag in operation["zero_signs"]:
        require(isinstance(flag, list) and len(flag) == 3, "invalid signed-zero shape")
        field, axis, sign = flag
        require(field in COORDINATES and type(axis) is int and axis in (0, 1)
                and type(sign) is int and sign in (-1, 1) and (field, axis) not in signed,
                "invalid signed-zero flag")
        require(result[field][axis] == 0.0, "signed-zero flag cannot change nonzero data")
        result[field][axis] = math.copysign(0.0, sign)
        signed.add((field, axis))
    result.update(operation["settings"])
    require(result["co"][0] == operation["frame"], "delta changes key time")
    if operation["co_ui_present"]:
        result["co_ui"] = result["co"][:]
    else:
        result.pop("co_ui", None)
    return result


def build_action_delta(base, target, defaults, role):
    """Return reference/edit/add operations; no wholesale inherited curve copies."""
    require(role == "rig", "unknown role")
    validate_record(base); validate_record(target)
    require([curve_id(c) for c in base["curves"]] == [curve_id(c) for c in target["curves"]],
            "one-hand curve additions/removals/ordering changes are unsupported")
    positions = {curve_id(c): i for i, c in enumerate(base["curves"])}
    require(set(positions) <= {curve_id(c) for c in target["curves"]}, "removing inherited curves is unsupported")
    operations = []
    for curve in target["curves"]:
        identity = curve_id(curve)
        ordinal = positions.get(identity)
        prior = None if ordinal is None else base["curves"][ordinal]
        if prior is not None and exact_equal(curve, prior):
            operations.append({"op": "reference", "base_index": ordinal, "before_sha256": digest(prior)})
            continue
        _allowed(*identity, role, added=prior is None)
        require(not curve["modifiers"] and not curve["samples"], "changed curves with modifiers/samples require explicit support")
        require(prior is None or (not prior["modifiers"] and not prior["samples"]), "inherited modifier/sample curve cannot be edited")
        old_keys = {} if prior is None else _key_map(prior)
        new_keys = _key_map(curve)
        keys = [{"op": "remove", "frame": frame, "before_sha256": digest(old_keys[frame])}
                for frame in old_keys if frame not in new_keys]
        for frame, key in new_keys.items():
            if frame in old_keys and exact_equal(key, old_keys[frame]):
                continue
            require(1 <= frame <= 96 and frame * 512 == int(frame * 512), "key outside authored clock/grid")
            origin = _origin(prior, frame, _default(defaults, *identity) if prior is None else None)
            keys.append({"op": "replace" if frame in old_keys else "add", "frame": frame,
                         "before_sha256": digest(old_keys[frame]) if frame in old_keys else None,
                         **_key_delta(origin, key)})
        settings = {field: curve[field] for field in CURVE_SETTINGS
                    if prior is None or not exact_equal(curve[field], prior[field])}
        operations.append({"op": "add_curve" if prior is None else "edit_curve", "base_index": ordinal,
                           "path": identity[0], "index": identity[1],
                           "before_sha256": digest(prior) if prior is not None else None,
                           "settings": settings, "keys": keys, "after_sha256": digest(curve)})
    patch = {"role": role, "base_complete_sha256": digest(base), "target_complete_sha256": digest(target),
             "base_fingerprint": fingerprint(base), "target_fingerprint": fingerprint(target),
             "settings": {k: target[k] for k in ACTION_SETTINGS if not exact_equal(target[k], base[k])},
             "curves": operations}
    require(exact_equal(apply_action_delta(base, patch, defaults, diagnostic_target=target), target),
            "pure delta round trip failed")
    return patch


def apply_action_delta(base, patch, defaults, *, diagnostic_target=None):
    require(set(patch) == {"role", "base_complete_sha256", "target_complete_sha256", "base_fingerprint",
                           "target_fingerprint", "settings", "curves"}, "unexpected Action delta field")
    role = patch["role"]
    require(role == "rig", "unknown delta role")
    validate_record(base)
    require(digest(base) == patch["base_complete_sha256"] and fingerprint(base) == patch["base_fingerprint"],
            "baseline Action differs")
    require(set(patch["settings"]) <= ACTION_SETTINGS, "unsupported Action settings")
    result = {**copy.deepcopy(base), **patch["settings"], "curves": []}
    seen = set()
    for target_index, item in enumerate(patch["curves"]):
        kind = item.get("op")
        ordinal = item.get("base_index")
        if kind == "reference":
            require(set(item) == {"op", "base_index", "before_sha256"}, "reference embeds data")
        else:
            require(set(item) == {"op", "base_index", "path", "index", "before_sha256", "settings", "keys", "after_sha256"},
                    "unexpected curve operation field")
        if kind in ("reference", "edit_curve"):
            require(type(ordinal) is int and 0 <= ordinal < len(base["curves"]) and ordinal not in seen,
                    "invalid or duplicate baseline curve reference")
            seen.add(ordinal)
            prior = base["curves"][ordinal]
            require(digest(prior) == item["before_sha256"], "referenced curve differs")
            curve = copy.deepcopy(prior)
        else:
            require(kind == "add_curve" and ordinal is None and item["before_sha256"] is None,
                    "invalid new curve operation")
            prior = None
            curve = {"path": item["path"], "index": item["index"], "modifiers": [], "samples": [], "keys": []}
        if kind != "reference":
            identity = (item["path"], item["index"])
            _allowed(*identity, role, added=prior is None)
            require(curve_id(curve) == identity, "curve identity changed")
            require(set(item["settings"]) <= CURVE_SETTINGS, "forbidden curve settings")
            require(not curve["modifiers"] and not curve["samples"], "curve modifiers/samples unsupported")
            curve.update(item["settings"])
            inherited = {} if prior is None else _key_map(prior)
            keys = copy.deepcopy(inherited)
            touched = set()
            for op in item["keys"]:
                frame = op["frame"]
                require(isinstance(frame, (int, float)) and not isinstance(frame, bool)
                        and math.isfinite(frame) and 1 <= frame <= 96 and frame * 512 == int(frame * 512),
                        "operation frame outside authored clock/grid")
                require(frame not in touched, "duplicate key operation")
                touched.add(frame)
                if op["op"] in ("remove", "replace"):
                    require(frame in inherited and digest(inherited[frame]) == op["before_sha256"], "key precondition differs")
                else:
                    require(op["op"] == "add" and frame not in inherited and op["before_sha256"] is None,
                            "invalid key addition")
                if op["op"] == "remove":
                    require(set(op) == {"op", "frame", "before_sha256"}, "removal embeds key data")
                    del keys[frame]
                else:
                    origin = _origin(prior, frame, _default(defaults, *identity) if prior is None else None)
                    keys[frame] = _apply_key(origin, op)
            curve["keys"] = [keys[f] for f in sorted(keys)]
            if digest(curve) != item["after_sha256"]:
                detail = "field unavailable without in-memory target"
                if diagnostic_target is not None:
                    detail = first_difference(diagnostic_target["curves"][target_index], curve)
                raise ValueError("curve reconstruction differs: role=" + role + " curve=" + str(identity)
                                 + " field=" + detail)
        result["curves"].append(curve)
    require(seen == set(range(len(base["curves"]))), "an inherited curve was omitted")
    validate_record(result)
    require(digest(result) == patch["target_complete_sha256"] and fingerprint(result) == patch["target_fingerprint"],
            "reconstructed Action differs")
    return result


def load_json(path):
    path = Path(path)
    require(path.stat().st_size <= MAX_JSON_BYTES, "JSON input exceeds bounded size")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def write_fresh_json(path, value):
    path = Path(path)
    data = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    require(len(data.encode()) <= MAX_JSON_BYTES, "JSON output exceeds bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(data)


POSE_CORRECTIONS_SHA = '08e25bf4c8731c073ace8749e2225f60d3e95a06eec6627239d7a9ba57aba58c'


def pose_corrections():
    path = Path(__file__).with_name("pose-corrections.json")
    require(sha(path) == POSE_CORRECTIONS_SHA, "pose correction scope changed")
    record = load_json(path)
    require(record["schema"] == "rust-duty-onehand-v6-pose-correction-scope/v1"
            and record["base_sha256"] == BASE_SHA and record["approved_source_sha256"] == APPROVED_SHA,
            "pose correction identity mismatch")
    rows = record["corrections"]
    require(len(rows) == 16 and sum(r["mode"] == "original_scalar_delta" for r in rows) == 12,
            "pose correction inventory differs")
    return rows


def mask_pose_exceptions(poses):
    result = copy.deepcopy(poses)
    for row in pose_corrections():
        obj, bone, field, component = row["path"]
        result[obj][bone][field][component] = {"explicit_lineage_exception": row["mode"]}
    return result


def corrected_scalar(before, row):
    require(row["mode"] == "original_scalar_delta", "driven outputs must never be assigned")
    require(digest(before) == row["before_sha256"], "pose correction baseline hash differs")
    require(isinstance(row["delta"], (int, float)) and not isinstance(row["delta"], bool)
            and math.isfinite(row["delta"]) and 0 < abs(row["delta"]) <= 2 ** -23,
            "pose delta exceeds original correction scope")
    after = f32(before + row["delta"])
    require(digest(after) == row["after_sha256"], "pose correction exact reconstruction differs")
    return after


def metadata_delta(base, target):
    require(set(base) == set(target) == {"use_fake_user", "properties"}, "Action metadata fields differ")
    require(set(base["properties"]) <= set(target["properties"]), "removing inherited metadata unsupported")
    changes = {}
    for key, value in target["properties"].items():
        if key not in base["properties"] or not exact_equal(base["properties"][key], value):
            require(isinstance(key, str) and len(key) <= 256, "invalid authored property key")
            require(isinstance(value, (str, bool, int, float)) and
                    (not isinstance(value, str) or len(value) <= 4096), "metadata must be bounded authored scalar/text")
            changes[key] = {"before_sha256": digest(base["properties"][key]) if key in base["properties"] else None,
                            "value": value}
    patch = {"before_sha256": digest(base), "after_sha256": digest(target), "properties": changes,
             "use_fake_user": target["use_fake_user"] if target["use_fake_user"] != base["use_fake_user"] else None}
    require(exact_equal(apply_metadata_delta(base, patch), target), "metadata roundtrip differs")
    return patch


def apply_metadata_delta(base, patch):
    require(set(patch) == {"before_sha256", "after_sha256", "properties", "use_fake_user"},
            "unexpected metadata delta field")
    require(digest(base) == patch["before_sha256"], "metadata baseline differs")
    out = copy.deepcopy(base)
    require(patch["use_fake_user"] is None or type(patch["use_fake_user"]) is bool, "invalid fake-user setting")
    if patch["use_fake_user"] is not None:
        out["use_fake_user"] = patch["use_fake_user"]
    for key, operation in patch["properties"].items():
        require(set(operation) == {"before_sha256", "value"}, "unexpected metadata property field")
        expected = digest(base["properties"][key]) if key in base["properties"] else None
        require(expected == operation["before_sha256"], "metadata property precondition differs")
        value = operation["value"]
        require(isinstance(value, (str, bool, int, float)) and (not isinstance(value, str) or len(value) <= 4096),
                "metadata must be bounded authored scalar/text")
        out["properties"][key] = value
    require(digest(out) == patch["after_sha256"], "metadata reconstruction differs")
    return out


def validate_delta_shape(patch):
    """Reject raw/inherited payloads before a recipe is accepted for comparison."""
    require(set(patch) == {"role", "base_complete_sha256", "target_complete_sha256", "base_fingerprint",
                           "target_fingerprint", "settings", "curves"}, "unexpected Action delta field")
    require(patch["role"] == "rig", "one-hand requires one rig Action")
    require(all(is_sha256(patch[k]) for k in ("base_complete_sha256", "target_complete_sha256", "base_fingerprint", "target_fingerprint")),
            "invalid Action fingerprint")
    require(set(patch["settings"]) <= ACTION_SETTINGS, "unsupported Action settings")
    for key, value in patch["settings"].items():
        require(type(value) is bool if key.startswith("use_") else isinstance(value, (int, float)) and not isinstance(value, bool),
                "invalid Action setting type")
    require(isinstance(patch["curves"], list) and 0 < len(patch["curves"]) <= 4096, "invalid curve operation count")
    seen = set()
    for curve in patch["curves"]:
        kind = curve.get("op")
        if kind == "reference":
            require(set(curve) == {"op", "base_index", "before_sha256"}, "reference embeds data")
        else:
            require(kind == "edit_curve" and set(curve) == {"op", "base_index", "path", "index", "before_sha256", "settings", "keys", "after_sha256"},
                    "unexpected curve operation field")
            _allowed(curve["path"], curve["index"], "rig")
            require(is_sha256(curve["after_sha256"]), "invalid curve target hash")
            require(set(curve["settings"]) <= CURVE_SETTINGS, "unsupported curve setting")
            for key, value in curve["settings"].items():
                if key == "color":
                    require(isinstance(value, list) and len(value) == 3 and all(type(x) in (int, float) for x in value),
                            "invalid curve color")
                elif key in ("mute", "lock", "hide", "select"):
                    require(type(value) is bool, "invalid curve boolean setting")
                else:
                    require(value is None and key == "group" or isinstance(value, str) and len(value) <= 256,
                            "invalid curve string setting")
            require(isinstance(curve["keys"], list) and len(curve["keys"]) <= 50000, "invalid key operation count")
            frames = set()
            for operation in curve["keys"]:
                frame = operation["frame"]
                require(type(frame) in (int, float) and math.isfinite(frame) and 1 <= frame <= 96
                        and frame * 512 == int(frame * 512) and frame not in frames, "invalid key operation time")
                frames.add(frame)
                if operation.get("op") == "remove":
                    require(set(operation) == {"op", "frame", "before_sha256"}, "removal embeds data")
                else:
                    require(operation.get("op") in ("add", "replace") and set(operation) ==
                            {"op", "frame", "before_sha256", "delta", "settings", "co_ui_present", "zero_signs"},
                            "unexpected key operation field")
                    require(set(operation["delta"]) <= set(COORDINATES), "unsupported coordinate delta")
                    for vector in operation["delta"].values():
                        require(isinstance(vector, list) and len(vector) == 2 and all(type(x) in (int, float) for x in vector),
                                "invalid coordinate delta vector")
                    require(set(operation["settings"]) <= KEY_SETTINGS and type(operation["co_ui_present"]) is bool,
                            "unsupported key setting")
                    for key, value in operation["settings"].items():
                        if key.startswith("select_"):
                            require(type(value) is bool, "invalid key boolean setting")
                        elif key in ("amplitude", "back", "period"):
                            require(type(value) in (int, float), "invalid key numeric setting")
                        else:
                            require(isinstance(value, str) and len(value) <= 256, "invalid key string setting")
                    flags = set()
                    for flag in operation["zero_signs"]:
                        require(isinstance(flag, list) and len(flag) == 3, "invalid signed-zero shape")
                        field, axis, sign = flag
                        require(field in COORDINATES and type(axis) is int and axis in (0, 1)
                                and type(sign) is int and sign in (-1, 1) and (field, axis) not in flags,
                                "invalid signed-zero flag")
                        flags.add((field, axis))
                require(operation["before_sha256"] is None if operation["op"] == "add" else is_sha256(operation["before_sha256"]),
                        "invalid key precondition hash")
        ordinal = curve["base_index"]
        require(type(ordinal) is int and 0 <= ordinal < 4096 and ordinal not in seen and is_sha256(curve["before_sha256"]),
                "invalid or duplicate inherited curve reference")
        seen.add(ordinal)
    require([c["base_index"] for c in patch["curves"]] == list(range(len(patch["curves"]))),
            "inherited FCurve ordering must remain exact")
    digest(patch)


def validate_metadata_shape(patch):
    require(set(patch) == {"before_sha256", "after_sha256", "properties", "use_fake_user"}, "unexpected metadata delta field")
    require(is_sha256(patch["before_sha256"]) and is_sha256(patch["after_sha256"]), "invalid metadata fingerprint")
    require(patch["use_fake_user"] is None or type(patch["use_fake_user"]) is bool, "invalid fake-user setting")
    require(isinstance(patch["properties"], dict) and len(patch["properties"]) <= 256, "invalid metadata property count")
    for key, row in patch["properties"].items():
        require(isinstance(key, str) and len(key) <= 256 and set(row) == {"before_sha256", "value"}, "unexpected metadata property field")
        require(row["before_sha256"] is None or is_sha256(row["before_sha256"]), "invalid metadata precondition")
        require(isinstance(row["value"], (str, bool, int, float)) and
                (not isinstance(row["value"], str) or len(row["value"]) <= 4096), "metadata must be bounded authored scalar/text")
    digest(patch)
