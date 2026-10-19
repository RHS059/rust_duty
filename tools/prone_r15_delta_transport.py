"""Transparent JSON source shards for the original prone-r15 Action delta.

No compression, binary encoding, base64, downloads or publication. Shards contain
ordinary JSON objects for authored operations. Assembly verifies every file and
reproduces the original canonical JSON bytes and SHA-256 exactly.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_r15_source_delta as delta

SCHEMA = "rust-duty-prone-r15-delta-source-shards/v1"
MAX_FILE_BYTES = 200 * 1024  # Every file must be strictly smaller.
DEFAULT_TARGET_BYTES = 180 * 1024
MAX_FILES = 512
CODEC = "UTF-8 canonical JSON; indent=2; sort_keys=true; ensure_ascii=true; trailing newline"
CURVE_FIELDS = {"op", "base_index", "path", "index", "before_sha256", "settings", "keys", "after_sha256"}
ACTION_FIELDS = {"role", "base_complete_sha256", "target_complete_sha256", "base_fingerprint",
                 "target_fingerprint", "settings", "curves"}
KEY_FIELDS = {"op", "frame", "before_sha256", "delta", "settings", "co_ui_present", "zero_signs"}


def canonical(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=True) + "\n").encode("utf-8")


def bytes_sha(value):
    return hashlib.sha256(value).hexdigest()


def _number(value, minimum, maximum, label):
    delta.require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum,
                  "invalid bounded numeric " + label)


def _settings(settings, kind):
    """Accept only bounded Blender setting scalars, never nested payloads."""
    delta.require(type(settings) is dict, "settings must be a plain object")
    allowed = {"action": delta.ACTION_SETTINGS, "curve": delta.CURVE_SETTINGS, "key": delta.KEY_SETTINGS}[kind]
    delta.require(set(settings) <= allowed, "unexpected " + kind + " setting")
    booleans = {"use_frame_range", "use_cyclic", "mute", "lock", "hide", "select",
                "select_control_point", "select_left_handle", "select_right_handle"}
    enums = {
        "extrapolation": {"CONSTANT", "LINEAR"},
        "color_mode": {"AUTO_RAINBOW", "AUTO_RGB", "CUSTOM"},
        "auto_smoothing": {"NONE", "CONT_ACCEL"},
        "interpolation": {"CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC", "QUART", "QUINT",
                          "EXPO", "CIRC", "BACK", "BOUNCE", "ELASTIC"},
        "handle_left_type": {"FREE", "VECTOR", "ALIGNED", "AUTO", "AUTO_CLAMPED"},
        "handle_right_type": {"FREE", "VECTOR", "ALIGNED", "AUTO", "AUTO_CLAMPED"},
        "easing": {"AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"},
        "type": {"KEYFRAME", "BREAKDOWN", "MOVING_HOLD", "EXTREME", "JITTER", "GENERATED"},
    }
    for name, value in settings.items():
        if name in booleans:
            delta.require(type(value) is bool, "invalid boolean setting " + name)
        elif name in enums:
            delta.require(type(value) is str and value in enums[name], "invalid enum setting " + name)
        elif name == "group":
            delta.require(value is None or (type(value) is str and 0 < len(value.encode("utf-8")) <= 63
                                           and all(ch.isprintable() for ch in value)), "invalid bounded group setting")
        elif name == "color":
            delta.require(type(value) is list and len(value) == 3, "invalid color setting shape")
            for component in value:
                _number(component, 0.0, 1.0, "color setting")
        elif name in ("frame_start", "frame_end"):
            _number(value, 0.0, 69.0, name + " setting")
        elif name in ("amplitude", "back", "period"):
            _number(value, -1_000_000.0, 1_000_000.0, name + " setting")
        else:
            raise ValueError("unclassified setting " + name)


def _key_operation(operation):
    delta.require(type(operation) is dict, "key operation must be a plain object")
    op = operation.get("op")
    delta.require(type(op) is str and op in ("add", "replace", "remove"), "unknown key operation")
    expected = {"op", "frame", "before_sha256"} if op == "remove" else KEY_FIELDS
    delta.require(set(operation) == expected, "unexpected key-operation payload")
    _number(operation["frame"], 1.0, 69.0, "key frame")
    delta.require(operation["frame"] * 512 == int(operation["frame"] * 512), "key frame outside grid")
    delta.require(operation["before_sha256"] is None if op == "add" else delta.is_sha256(operation["before_sha256"]),
                  "invalid key precondition hash")
    if op == "remove":
        return
    delta.require(type(operation["co_ui_present"]) is bool, "invalid co_ui flag")
    coordinates = operation["delta"]
    delta.require(type(coordinates) is dict and set(coordinates) <= set(delta.COORDINATES), "unexpected delta field")
    for value in coordinates.values():
        delta.require(type(value) is list and len(value) == 2, "invalid key delta shape")
        for component in value:
            _number(component, -1_000_000.0, 1_000_000.0, "key delta")
    _settings(operation["settings"], "key")
    flags = operation["zero_signs"]
    delta.require(type(flags) is list and len(flags) <= 6, "invalid zero-sign flags")
    seen = set()
    for flag in flags:
        delta.require(type(flag) is list and len(flag) == 3, "invalid zero-sign shape")
        field, axis, sign = flag
        delta.require(type(field) is str and field in delta.COORDINATES and type(axis) is int and axis in (0, 1)
                      and type(sign) is int and sign in (-1, 1) and (field, axis) not in seen, "invalid zero-sign value")
        seen.add((field, axis))


def audit_scope(recipe):
    """Reject raw key/curve payloads or fields outside the extractor schema."""
    from prone_r15_source_native import validate_recipe
    validate_recipe(recipe)
    delta.require(delta.is_sha256(recipe["base_actions_sha256"]), "invalid base Action-set hash")
    counts = {}
    for role in ("rig", "camera"):
        action = recipe["actions"][role]
        delta.require(set(action) == ACTION_FIELDS, "unexpected action payload")
        delta.require(type(action) is dict and action["role"] == role, "invalid Action role")
        for field in ("base_complete_sha256", "target_complete_sha256", "base_fingerprint", "target_fingerprint"):
            delta.require(delta.is_sha256(action[field]), "invalid Action hash")
        _settings(action["settings"], "action")
        delta.require(type(action["curves"]) is list and 0 < len(action["curves"]) <= 2000, "invalid curve collection")
        stats = {"reference": 0, "edit_curve": 0, "add_curve": 0, "add": 0, "replace": 0,
                 "remove": 0, "zero_sign_flags": 0}
        for curve in action["curves"]:
            delta.require(type(curve) is dict, "curve operation must be a plain object")
            kind = curve["op"]
            delta.require(type(kind) is str and kind in ("reference", "edit_curve", "add_curve"), "unknown curve operation")
            if kind == "add_curve":
                delta.require(curve["base_index"] is None and curve["before_sha256"] is None, "invalid added curve origin")
            else:
                delta.require(type(curve["base_index"]) is int and 0 <= curve["base_index"] < 2000
                              and delta.is_sha256(curve["before_sha256"]), "invalid inherited curve reference")
            stats[kind] += 1
            if kind == "reference":
                delta.require(set(curve) == {"op", "base_index", "before_sha256"}, "reference carries inherited data")
                continue
            delta.require(set(curve) == CURVE_FIELDS, "unexpected authored curve payload")
            delta.require(type(curve["path"]) is str and delta.is_sha256(curve["after_sha256"]), "invalid curve identity/hash")
            delta._allowed(curve["path"], curve["index"], role, added=kind == "add_curve")
            _settings(curve["settings"], "curve")
            delta.require(type(curve["keys"]) is list and len(curve["keys"]) <= 5000, "invalid key collection")
            for operation in curve["keys"]:
                _key_operation(operation)
                op = operation["op"]; stats[op] += 1
                if op != "remove":
                    stats["zero_sign_flags"] += len(operation["zero_signs"])
        counts[role] = stats
    return counts


def _bounded_partition(rows, make_document, target_bytes):
    """Greedy contiguous parts, deterministic and below the configured byte cap."""
    delta.require(1024 <= target_bytes < MAX_FILE_BYTES, "invalid shard byte target")
    start = 0
    while start < len(rows):
        low, high, count = 1, len(rows) - start, 0
        while low <= high:
            middle = (low + high) // 2
            size = len(canonical(make_document(start, rows[start:start + middle])))
            if size <= target_bytes:
                count = middle; low = middle + 1
            else:
                high = middle - 1
        delta.require(count > 0, "one JSON operation exceeds the transparent shard limit")
        document = make_document(start, rows[start:start + count])
        delta.require(len(canonical(document)) < MAX_FILE_BYTES, "shard exceeds hard size limit")
        yield document
        start += count


def partition_recipe(recipe, target_bytes=DEFAULT_TARGET_BYTES):
    """Return filename/document pairs with real, inspectable JSON structures."""
    audit_scope(recipe)
    files = []
    header = {"schema": SCHEMA + "/header", "metadata": {k: v for k, v in recipe.items() if k != "actions"},
              "actions": {role: {"metadata": {k: v for k, v in action.items() if k != "curves"},
                                 "curve_count": len(action["curves"])} for role, action in recipe["actions"].items()}}
    delta.require(len(canonical(header)) <= target_bytes, "header exceeds shard limit")
    files.append(("header.json", header))
    for role in sorted(recipe["actions"]):
        curves = recipe["actions"][role]["curves"]
        metadata = [{"operation": {k: v for k, v in c.items() if k != "keys"},
                     "key_count": len(c["keys"]) if "keys" in c else None} for c in curves]
        def curve_document(start, rows):
            return {"schema": SCHEMA + "/curves", "role": role, "curve_start": start, "curves": rows}
        for index, document in enumerate(_bounded_partition(metadata, curve_document, target_bytes)):
            files.append((f"curves-{role}-{index:04d}.json", document))
        for curve_index, curve in enumerate(curves):
            if "keys" not in curve or not curve["keys"]:
                continue
            def key_document(start, rows):
                return {"schema": SCHEMA + "/keys", "role": role, "curve_index": curve_index,
                        "key_start": start, "keys": rows}
            for index, document in enumerate(_bounded_partition(curve["keys"], key_document, target_bytes)):
                files.append((f"keys-{role}-{curve_index:04d}-{index:04d}.json", document))
    delta.require(len(files) <= MAX_FILES, "excessive shard count")
    return files


def write_package(source, expected_sha256, directory, target_bytes=DEFAULT_TARGET_BYTES):
    source = Path(source).resolve(); directory = Path(directory).resolve()
    delta.require(delta.sha(source) == expected_sha256, "source delta SHA-256 differs")
    raw = source.read_bytes(); recipe = delta.load_json(source)
    delta.require(canonical(recipe) == raw, "input is not exact supported canonical JSON")
    counts = audit_scope(recipe)
    partitions = partition_recipe(recipe, target_bytes)
    directory.mkdir(parents=True, exist_ok=False)
    descriptors = []
    for filename, document in partitions:
        data = canonical(document)
        delta.require(len(data) < MAX_FILE_BYTES, "source shard too large")
        with (directory / filename).open("xb") as stream:
            stream.write(data)
        descriptors.append({"file": filename, "bytes": len(data), "sha256": bytes_sha(data)})
    manifest = {"schema": SCHEMA, "codec": CODEC, "source_sha256": expected_sha256,
                "source_bytes": len(raw), "hard_file_limit_exclusive": MAX_FILE_BYTES,
                "target_shard_bytes": target_bytes, "files": descriptors, "scope_counts": counts,
                "transport": "plain structured JSON source; no compression, binary encoding or hidden payload",
                "source_contains_private_geometry": False,
                "base_supplied_separately": True, "source_identity_is_original_delta": True}
    encoded_manifest = canonical(manifest)
    delta.require(len(encoded_manifest) < MAX_FILE_BYTES, "manifest exceeds file limit")
    with (directory / "manifest.json").open("xb") as stream:
        stream.write(encoded_manifest)
    result = assemble_bytes(directory / "manifest.json", bytes_sha(encoded_manifest))
    delta.require(result == raw and delta.sha(source) == expected_sha256, "transport roundtrip or source preservation failed")
    return manifest


def _load_part(directory, descriptor):
    delta.require(set(descriptor) == {"file", "bytes", "sha256"}, "unexpected part descriptor")
    name = descriptor["file"]
    delta.require(isinstance(name, str) and re.fullmatch(r"(?:header|curves-(?:rig|camera)-\d{4}|keys-(?:rig|camera)-\d{4}-\d{4})\.json", name),
                  "unsafe or unknown shard filename")
    delta.require(type(descriptor["bytes"]) is int and 0 < descriptor["bytes"] < MAX_FILE_BYTES
                  and delta.is_sha256(descriptor["sha256"]), "invalid shard size/hash")
    path = directory / name
    delta.require(path.is_file() and not path.is_symlink(), "shard must be an ordinary local file")
    delta.require(path.stat().st_size == descriptor["bytes"] and delta.sha(path) == descriptor["sha256"],
                  "shard bytes/hash mismatch: " + name)
    document = delta.load_json(path)
    delta.require(canonical(document) == path.read_bytes(), "shard is not canonical JSON")
    return document


def assemble_bytes(manifest_path, expected_manifest_sha256):
    manifest_path = Path(manifest_path)
    delta.require(manifest_path.name == "manifest.json" and manifest_path.is_file() and not manifest_path.is_symlink(),
                  "manifest must be an ordinary manifest.json file")
    manifest_path = manifest_path.resolve()
    delta.require(manifest_path.stat().st_size < MAX_FILE_BYTES, "manifest exceeds file limit")
    delta.require(delta.sha(manifest_path) == expected_manifest_sha256, "manifest SHA-256 differs")
    manifest = delta.load_json(manifest_path)
    delta.require(set(manifest) == {"schema", "codec", "source_sha256", "source_bytes", "hard_file_limit_exclusive",
                                  "target_shard_bytes", "files", "scope_counts", "transport", "source_contains_private_geometry",
                                  "base_supplied_separately", "source_identity_is_original_delta"}, "unexpected manifest field")
    delta.require(manifest["schema"] == SCHEMA and manifest["codec"] == CODEC
                  and manifest["hard_file_limit_exclusive"] == MAX_FILE_BYTES, "unsupported source-shard contract")
    delta.require(manifest["source_contains_private_geometry"] is False and manifest["base_supplied_separately"] is True
                  and manifest["source_identity_is_original_delta"] is True, "invalid source-shard privacy boundary")
    delta.require(delta.is_sha256(manifest["source_sha256"]) and type(manifest["source_bytes"]) is int
                  and 0 < manifest["source_bytes"] <= delta.MAX_JSON_BYTES, "invalid assembled source size/hash")
    descriptors = manifest["files"]
    delta.require(0 < len(descriptors) <= MAX_FILES and len({d["file"] for d in descriptors}) == len(descriptors),
                  "missing, duplicate or excessive shard descriptors")
    for descriptor in descriptors:
        delta.require(type(descriptor) is dict and set(descriptor) == {"file", "bytes", "sha256"},
                      "unexpected part descriptor")
        delta.require(type(descriptor["file"]) is str and re.fullmatch(
            r"(?:header|curves-(?:rig|camera)-\d{4}|keys-(?:rig|camera)-\d{4}-\d{4})\.json", descriptor["file"]),
            "unsafe or unknown shard filename")
    expected_entries = {"manifest.json"} | {part["file"] for part in descriptors}
    entries = list(manifest_path.parent.iterdir())
    delta.require({entry.name for entry in entries} == expected_entries,
                  "manifest directory is not closed: missing or unlisted entries")
    delta.require(all(entry.is_file() and not entry.is_symlink() for entry in entries),
                  "manifest directory may contain only declared ordinary regular files")
    recipe = None
    for descriptor in descriptors:
        document = _load_part(manifest_path.parent, descriptor)
        kind = document.get("schema")
        if kind == SCHEMA + "/header":
            delta.require(recipe is None and descriptor["file"] == "header.json"
                          and set(document) == {"schema", "metadata", "actions"}, "duplicate/malformed source header")
            delta.require(set(document["actions"]) == {"rig", "camera"} and "actions" not in document["metadata"],
                          "invalid source header actions")
            recipe = copy.deepcopy(document["metadata"]); recipe["actions"] = {}
            for role, row in document["actions"].items():
                delta.require(set(row) == {"metadata", "curve_count"} and "curves" not in row["metadata"]
                              and type(row["curve_count"]) is int and 0 < row["curve_count"] <= 2000,
                              "invalid curve allocation")
                recipe["actions"][role] = {**row["metadata"], "curves": [None] * row["curve_count"]}
        elif kind == SCHEMA + "/curves":
            delta.require(recipe is not None and set(document) == {"schema", "role", "curve_start", "curves"},
                          "curve part before header or malformed")
            delta.require(document["role"] in recipe["actions"], "unknown curve role")
            curves = recipe["actions"][document["role"]]["curves"]
            start = document["curve_start"]; rows = document["curves"]
            delta.require(type(start) is int and 0 <= start < len(curves) and rows and start + len(rows) <= len(curves),
                          "invalid curve range")
            for offset, row in enumerate(rows):
                delta.require(curves[start + offset] is None and set(row) == {"operation", "key_count"}
                              and "keys" not in row["operation"], "duplicate/malformed curve slot")
                operation = copy.deepcopy(row["operation"])
                if row["key_count"] is not None:
                    delta.require(type(row["key_count"]) is int and 0 <= row["key_count"] <= 5000,
                                  "invalid key allocation")
                    operation["keys"] = [None] * row["key_count"]
                curves[start + offset] = operation
        elif kind == SCHEMA + "/keys":
            delta.require(recipe is not None and set(document) == {"schema", "role", "curve_index", "key_start", "keys"},
                          "key part before header or malformed")
            delta.require(document["role"] in recipe["actions"], "unknown key role")
            curves = recipe["actions"][document["role"]]["curves"]
            curve_index = document["curve_index"]
            delta.require(type(curve_index) is int and 0 <= curve_index < len(curves)
                          and curves[curve_index] is not None and "keys" in curves[curve_index], "key part lacks curve metadata")
            keys = curves[curve_index]["keys"]; start = document["key_start"]; rows = document["keys"]
            delta.require(type(start) is int and rows and 0 <= start < len(keys) and start + len(rows) <= len(keys),
                          "invalid key range")
            for offset, row in enumerate(rows):
                delta.require(keys[start + offset] is None, "duplicate key slot")
                keys[start + offset] = row
        else:
            raise ValueError("unexpected source-shard schema")
    delta.require(recipe is not None, "source header absent")
    for action in recipe["actions"].values():
        delta.require(all(c is not None for c in action["curves"]), "missing curve slots")
        for curve in action["curves"]:
            if "keys" in curve:
                delta.require(all(k is not None for k in curve["keys"]), "missing key slots")
    delta.require(audit_scope(recipe) == manifest["scope_counts"], "source scope audit differs")
    result = canonical(recipe)
    delta.require(len(result) == manifest["source_bytes"] and bytes_sha(result) == manifest["source_sha256"],
                  "assembled source differs from original bytes")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    split = commands.add_parser("split")
    split.add_argument("--source", type=Path, required=True)
    split.add_argument("--source-sha256", required=True)
    split.add_argument("--directory", type=Path, required=True)
    split.add_argument("--target-bytes", type=int, default=DEFAULT_TARGET_BYTES)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--manifest", type=Path, required=True)
    assemble.add_argument("--manifest-sha256", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "split":
        manifest = write_package(args.source, args.source_sha256, args.directory, args.target_bytes)
        print("PRONE_R15_JSON_SHARDS", len(manifest["files"]), "manifest_sha256", delta.sha(args.directory / "manifest.json"))
    else:
        delta.require(not args.output.exists(), "refuse to overwrite assembled source")
        data = assemble_bytes(args.manifest, args.manifest_sha256)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(data)
        print("PRONE_R15_DELTA_REASSEMBLED", len(data), bytes_sha(data))


if __name__ == "__main__":
    main()
