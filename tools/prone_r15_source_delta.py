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

SCHEMA = "rust-duty-prone-r15-original-delta/v1"
BASE_SHA = "67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad"
APPROVED_SHA = "cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4"
BASE_ACTION = "prone_crawl_enter_r5"
BASE_FINGERPRINT = "d8f5c085431904b5713d3ee4c8b1bb31a3d2cf9848d73dfdd0c06880d1d4b439"
RIG_ACTION = "aella_prone_crawl_enter_r15_roll_v1"
RIG_FINGERPRINT = "93ffbed2bd91d33bb2d6e1788ce3c3d95f915c228b8ce7f3c17af05b265c9640"
CAMERA_ACTION = "aella_prone_crawl_enter_camera_r9_viewray_v3"
CAMERA_FINGERPRINT = "6872ef8f4301690dfd340ec9479f4a533fba743f1dc23b6a3691cd85c9e08844"
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
OBJECT_PATHS = frozenset(("location", "rotation_euler"))
RIG_PATHS = OBJECT_PATHS | frozenset((
    'pose.bones["righthand_prop"].location', 'pose.bones["righthand_prop"].rotation_euler',
    'pose.bones["clavicle_l"].location', 'pose.bones["clavicle_r"].location',
    'pose.bones["elbow_pole_l"].location',
))
STATIC_CATEGORIES = frozenset(("meshes", "armatures", "objects_and_bindings", "object_defaults",
    "pose_channel_defaults", "drivers", "nla", "materials", "cameras", "scene", "packed_images",
    "embedded_text", "collections"))
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
    """Matches the retained r15 support.complete_actions serialization."""
    return digest(record)


def probe_times():
    frames = set(1 + i / 8 for i in range(545))
    frames.update(24 + i / 16 for i in range(337))
    frames.update(35 + i / 128 for i in range(1281))
    frames.update(x + i / 512 for x in (35, 45) for i in range(-32, 33))
    result = sorted(frames)
    require(len(result) == 1944, "probe clock changed")
    return result


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
    require(type(index) is int and 0 <= index < 3, "curve axis outside authored scope")
    require(path in (RIG_PATHS if role == "rig" else OBJECT_PATHS), "curve outside authored allowlist")
    if added:
        require(path in OBJECT_PATHS, "only original object co-motion channels may be added")


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
    require(role in ("rig", "camera"), "unknown role")
    validate_record(base); validate_record(target)
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
            require(1 <= frame <= 69 and frame * 512 == int(frame * 512), "key outside authored clock/grid")
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
    require(role in ("rig", "camera"), "unknown delta role")
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
                        and math.isfinite(frame) and 1 <= frame <= 69 and frame * 512 == int(frame * 512),
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
