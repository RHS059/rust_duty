#!/usr/bin/env python3
"""Stream the original one-hand runtime clip into VRANIM01 without a frame list.

Production entry point: assemble(metadata_path, vrs_path, vrm_path,
                               block_paths, output_path).
``block_paths`` contains the twelve receipt JSON paths in block-index order.
Each receipt's binary is named ``frames.bin`` in that receipt's directory.
The source blocks are immutable inputs and are never removed or rewritten.

Geometry metadata (SHA-256 identity is over exact UTF-8 file bytes):
  schema: rust-duty-onehand-bounded-runtime-geometry/v1, passed: true
  source_sha256, fbx_sha256, canonical_sha256: lowercase SHA-256
  files: {"asset.vrs": {sha256, bytes}, "asset.vrm": {sha256, bytes}, ...}
  static_import, static_import_sha256, recipe_pins_sha256, window_admission
  clip_name, loop: false, ticks_per_second, last_tick
  bones: [[name, parent], ...] in the VRS skeleton order
  actors: [{name, meshes: [index, ...], inverse_rest_global: [16 floats]}, ...]
Receipts:
  schema: rust-duty-onehand-bounded-runtime-block/v1
  block_index, start_tick, end_tick, frames, frame_bytes
  source_sha256, fbx_sha256, geometry_metadata_sha256
  canonical_sha256, static_import_sha256, recipe_pins_sha256, window_admission
  frame_file_sha256, frame_file_bytes, passed: true
  final_full_key_count: 24321, full_clip_instantiated: false
Window claims and raw/transformed admission digests are checked, but are not a
replacement for independent native-import or Rust parity verification.

A frame is <f global_time, followed by bone then actor <10f TRS records and one
0/1 visibility byte per actor. Adjacent windows share one byte-identical record.
TRS values are validated using the established vrview helper, but the record
bytes are preserved. Native blocks already apply decompose/validate_transform
before float32 serialization, exactly at the original encode_vra boundary;
normalizing the decoded float32 values again could change quaternion bits.

The output is exclusive-create and has a deliberately invalid zero header until
every frame, seam, file digest and size passes. A failed partial output is kept
with its invalid header; use a new destination when retrying. This module never
deletes files, overwrites existing output, launches Blender, or publishes.
Actual Rust/native parity is a separate mandatory check, not implied by this
assembler's successful Python validation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import zlib


# Import only the already-established format validators. Suppress cache writes
# so the read-only helper source directory is not modified by an import.
_default_tools = (Path(__file__).resolve().parents[2] /
                  "onehand-runtime-20261016/importer-patch/tools")
_tools_path = Path(os.environ.get("VRVIEW_TOOLS_PATH", str(_default_tools)))
_old_no_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
sys.path.insert(0, str(_tools_path))
try:
    import vrview
    import vrpack as core
    import vrskin
finally:
    sys.path.pop(0)
    sys.dont_write_bytecode = _old_no_bytecode

AssetError = core.AssetError
require = core.require
GEOMETRY_SCHEMA = "rust-duty-onehand-bounded-runtime-geometry/v1"
BLOCK_SCHEMA = "rust-duty-onehand-bounded-runtime-block/v1"
REPORT_SCHEMA = "rust-duty-streamed-vra-report/v1"
SOURCE_SHA256 = "b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77"
FBX_SHA256 = "5b847bf47cfafdf9a4b4d32f3d5972e677698db3f47cdc7a4a36a4b7698ee2c2"
CANONICAL_SHA256 = "d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab"
FULL_KEY_COUNT = 24321
SUBDIVISIONS = 256
CLIP_NAME = "aella_mantle_onehand_r6_camera_reconstructed_v6"
JSON_LIMIT = 2 * 1024 * 1024
READ_CHUNK = 64 * 1024


@dataclass(frozen=True)
class StreamContract:
    """Low-level fixture contract; assemble() always uses PRODUCTION_CONTRACT.

    Size budgets can be tightened for tests, but never relax the established
    2,000,000-transform or 128 MiB format limits.
    """
    clip_name: str = CLIP_NAME
    bone_count: int = 72
    actor_count: int = 3
    ticks_per_second: int = 15360
    last_tick: int = 24320
    block_ticks: int = 2048
    source_sha256: str = SOURCE_SHA256
    fbx_sha256: str = FBX_SHA256
    canonical_sha256: str = CANONICAL_SHA256
    max_transforms: int = vrview.MAX_TRANSFORMS
    max_file_bytes: int = core.MAX_FILE

    @property
    def frame_bytes(self):
        return 4 + (self.bone_count + self.actor_count) * vrview.TRANSFORM.size + self.actor_count

    @property
    def block_count(self):
        return max(1, (self.last_tick + self.block_ticks - 1) // self.block_ticks)


PRODUCTION_CONTRACT = StreamContract()


def _sha(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            f"{label} must be a lowercase SHA-256")
    return value


def _integer(value, label, minimum=0, maximum=0xFFFFFFFF):
    require(type(value) is int and minimum <= value <= maximum,
            f"{label} must be an integer in {minimum}..{maximum}")
    return value


def _json_file(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(JSON_LIMIT + 1)
    require(len(raw) <= JSON_LIMIT, "metadata/receipt JSON exceeds 2 MiB")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=core._no_duplicate_keys,
                          parse_constant=core._bad_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AssetError(f"invalid JSON in {path}: {exc}") from exc
    require(isinstance(data, dict), "metadata/receipt must be a JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def _check_contract(contract):
    require(isinstance(contract, StreamContract), "invalid streaming contract")
    vrview.string(contract.clip_name, "clip name")
    _integer(contract.bone_count, "bone count", 1, 128)
    _integer(contract.actor_count, "actor count", 0, 256)
    _integer(contract.ticks_per_second, "ticks per second", 1)
    _integer(contract.last_tick, "last tick", 0, 65535)
    _integer(contract.block_ticks, "block ticks", 1, 65536)
    _integer(contract.max_transforms, "transform limit", 1, vrview.MAX_TRANSFORMS)
    _integer(contract.max_file_bytes, "file byte limit", vrview.HEADER.size, core.MAX_FILE)
    _sha(contract.source_sha256, "contract source_sha256")
    _sha(contract.fbx_sha256, "contract fbx_sha256")
    _sha(contract.canonical_sha256, "contract canonical_sha256")
    require((contract.last_tick + 1) * (contract.bone_count + contract.actor_count)
            <= contract.max_transforms, "aggregate transform budget exceeded")


def _json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _exact(actual, expected, label):
    # bool must not impersonate 0/1. JSON integers may represent exact floats.
    if type(expected) is bool or type(expected) is int:
        require(type(actual) is type(expected) and actual == expected, f"{label} mismatch")
    else:
        require(actual == expected, f"{label} mismatch")


def _window_admission(value, requested, contract, expected_raw_sha=None, expected_recipe_sha=None):
    require(isinstance(value, dict), "missing window admission")
    for key, expected in {
            "schema": "rust-duty-fbx-bounded-key-window/v1", "passed": True,
            "fbx_sha256": contract.fbx_sha256, "full_key_count": FULL_KEY_COUNT,
            "subdivisions": SUBDIVISIONS, "linear_interpolation": True,
            "partial_instantiation_only": True, "full_clip_instantiated": False,
            "selection_stage": "after complete official transformation/hemisphere/unwrap sequence",
            "requested_source_frames": requested,
            "allowed_evaluation_frames": sorted(set([1.0, *requested]))}.items():
        _exact(value.get(key), expected, "window " + key)
    require(all(type(frame) in (int, float) and math.isfinite(frame)
                for frame in value["requested_source_frames"]), "invalid window requested frames")
    raw = value.get("full_raw_admission")
    require(isinstance(raw, dict), "missing full raw admission")
    for key, expected in {"passed": True, "fbx_sha256": contract.fbx_sha256,
                          "key_count": FULL_KEY_COUNT, "subdivisions": SUBDIVISIONS,
                          "all_times_values_finite_checked": True, "linear_flags": 24836}.items():
        _exact(raw.get(key), expected, "full raw admission " + key)
    raw_sha = _sha(value.get("full_raw_admission_sha256"), "full_raw_admission_sha256")
    require(raw_sha == _json_digest(raw), "full raw admission digest mismatch")
    if expected_raw_sha is not None:
        require(raw_sha == expected_raw_sha, "full raw admission identity mismatch")
    transformed = value.get("full_transformed_admission")
    require(isinstance(transformed, dict), "missing full transformed admission")
    for key in ("passed", "full_transform_sequence_preserved_before_selection",
                "all_full_input_times_values_checked"):
        _exact(transformed.get(key), True, "full transformed admission " + key)
    transformed_sha = _sha(value.get("full_transformed_admission_sha256"),
                           "full_transformed_admission_sha256")
    require(transformed_sha == _json_digest(transformed), "full transformed admission digest mismatch")
    recipe_sha = _sha(value.get("recipe_pins_sha256"), "window recipe_pins_sha256")
    if expected_recipe_sha is not None:
        require(recipe_sha == expected_recipe_sha, "window recipe identity mismatch")
    return raw_sha, recipe_sha


def _validate_metadata(metadata, contract):
    require(metadata.get("schema") == GEOMETRY_SCHEMA, "invalid geometry metadata schema")
    require(metadata.get("passed") is True, "geometry metadata did not pass")
    for key in ("source_sha256", "fbx_sha256", "canonical_sha256"):
        require(_sha(metadata.get(key), key) == getattr(contract, key), f"{key} identity mismatch")
    files = metadata.get("files")
    require(isinstance(files, dict), "missing companion file identities")
    for name in ("asset.vrs", "asset.vrm"):
        record = files.get(name)
        require(isinstance(record, dict), f"missing {name} identity")
        _sha(record.get("sha256"), name + " sha256")
        _integer(record.get("bytes"), name + " bytes", vrview.HEADER.size, core.MAX_FILE)
    _sha(metadata.get("recipe_pins_sha256"), "recipe_pins_sha256")
    static = metadata.get("static_import")
    require(isinstance(static, dict), "missing authoritative static import")
    require(_sha(metadata.get("static_import_sha256"), "static_import_sha256") == _json_digest(static),
            "static import digest mismatch")
    _window_admission(metadata.get("window_admission"), [1.0], contract)
    require(metadata.get("clip_name") == contract.clip_name, "clip name mismatch")
    require(metadata.get("loop") is False, "clip must be nonlooping")
    for key in ("ticks_per_second", "last_tick"):
        require(_integer(metadata.get(key), key) == getattr(contract, key), f"{key} mismatch")
    bones = metadata.get("bones")
    require(isinstance(bones, list) and len(bones) == contract.bone_count, "bone count mismatch")
    canonical_bones = []
    for bone in bones:
        require(isinstance(bone, list) and len(bone) == 2, "bone must be [name, parent]")
        name = vrview.string(bone[0], "bone name", maximum=64)
        parent = _integer(bone[1], "bone parent", -1, len(bones) - 1)
        canonical_bones.append((name, parent))
    require(len({name for name, _ in canonical_bones}) == len(bones), "duplicate bone name")
    vrskin.validate_parents([parent for _, parent in canonical_bones])
    authoritative = static.get("canonical_bones")
    require(isinstance(authoritative, list) and len(authoritative) == len(bones),
            "missing canonical bone hierarchy")
    for bone in authoritative:
        require(isinstance(bone, list) and len(bone) == 2, "invalid canonical bone pair")
        vrview.string(bone[0], "canonical bone name", maximum=64)
        _integer(bone[1], "canonical bone parent", -1, len(bones) - 1)
    require(len({bone[0] for bone in authoritative}) == len(bones), "duplicate canonical bone name")
    vrskin.validate_parents([bone[1] for bone in authoritative])
    def hierarchy(rows):
        return {name: rows[parent][0] if parent >= 0 else None for name, parent in rows}
    require(hierarchy(canonical_bones) == hierarchy(authoritative), "canonical hierarchy differs")
    actors = metadata.get("actors")
    require(isinstance(actors, list) and len(actors) == contract.actor_count, "actor count mismatch")
    actor_names, assigned = set(), set()
    for actor in actors:
        require(isinstance(actor, dict), "actor must be an object")
        name = vrview.string(actor.get("name"), "actor name")
        require(name not in actor_names, "duplicate actor name")
        actor_names.add(name)
        meshes = actor.get("meshes")
        require(isinstance(meshes, list) and len(meshes) <= 256, "invalid actor meshes")
        for mesh in meshes:
            _integer(mesh, "actor mesh", 0, 255)
            require(mesh not in assigned, "duplicate actor mesh assignment")
            assigned.add(mesh)
        inverse = actor.get("inverse_rest_global")
        require(isinstance(inverse, list) and len(inverse) == 16, "invalid actor inverse rest global")
        inverse = tuple(core.number(v, "actor inverse rest global") for v in inverse)
        # Validate the serialized float32 matrix, exactly as the VRA decoder.
        packed_inverse = struct.unpack("<16f", struct.pack("<16f", *inverse))
        vrskin.matrix_valid(packed_inverse, "actor inverse rest global")
    return canonical_bones, actors, assigned


def _companion(path, identity, kind, bones, assigned):
    data = core.read_limited(path)
    require(len(data) == identity["bytes"], f"{kind} companion byte count mismatch")
    require(hashlib.sha256(data).hexdigest() == identity["sha256"], f"{kind} companion SHA-256 mismatch")
    if kind == "VRS":
        vrskin.inspect_vrs(data)
        cursor = 28
        count, = struct.unpack_from("<I", data, 24)
        actual = []
        for _ in range(count):
            size, = struct.unpack_from("<H", data, cursor)
            cursor += 2
            name = data[cursor:cursor + size].decode("utf-8")
            cursor += size
            parent, = struct.unpack_from("<i", data, cursor)
            cursor += 132
            actual.append((name, parent))
        require(actual == bones, "VRS companion skeleton mismatch")
    else:
        info = core.inspect_vrm(data)
        require(assigned == set(range(info["meshes"])), "rigid companion meshes must be assigned exactly once")
    return zlib.crc32(data), len(data)


def _prefix(bones, actors, contract, vrs_crc, vrm_crc):
    payload = bytearray(struct.pack("<III", vrs_crc, vrm_crc, len(bones)))

    def name(value):
        raw = value.encode("utf-8")
        payload.extend(struct.pack("<H", len(raw)))
        payload.extend(raw)

    for bone_name, parent in bones:
        name(bone_name)
        payload.extend(struct.pack("<i", parent))
    payload.extend(struct.pack("<I", len(actors)))
    for actor in actors:
        name(actor["name"])
        payload.extend(struct.pack("<I", len(actor["meshes"])))
        for mesh in actor["meshes"]:
            payload.extend(struct.pack("<I", mesh))
        payload.extend(struct.pack("<16f", *actor["inverse_rest_global"]))
    payload.extend(struct.pack("<I", 1))
    name(contract.clip_name)
    payload.extend(struct.pack("<II", 0, contract.last_tick + 1))
    return bytes(payload)


def _block_descriptors(block_paths, metadata, metadata_sha, contract):
    require(isinstance(block_paths, (list, tuple)) and len(block_paths) == contract.block_count,
            f"expected exactly {contract.block_count} block receipts")
    paths = [Path(path) for path in block_paths]
    require(len({path.resolve() for path in paths}) == len(paths), "duplicate block receipt path")
    frame_paths = [path.parent / "frames.bin" for path in paths]
    require(len({path.resolve() for path in frame_paths}) == len(paths), "duplicate frame block path")
    descriptors = []
    for index, (path, frame_path) in enumerate(zip(paths, frame_paths)):
        receipt, receipt_sha = _json_file(path)
        require(receipt.get("schema") == BLOCK_SCHEMA, "invalid block receipt schema")
        require(receipt.get("passed") is True, "block receipt did not pass")
        start = index * contract.block_ticks
        end = min(start + contract.block_ticks, contract.last_tick)
        expected = {"block_index": index, "start_tick": start, "end_tick": end,
                    "frames": end - start + 1, "frame_bytes": contract.frame_bytes,
                    "frame_file_bytes": (end - start + 1) * contract.frame_bytes}
        for key, value in expected.items():
            require(_integer(receipt.get(key), key) == value, f"block {index}: {key} mismatch")
        for key, value in (("source_sha256", contract.source_sha256),
                           ("fbx_sha256", contract.fbx_sha256),
                           ("canonical_sha256", contract.canonical_sha256),
                           ("static_import_sha256", metadata["static_import_sha256"]),
                           ("recipe_pins_sha256", metadata["recipe_pins_sha256"]),
                           ("geometry_metadata_sha256", metadata_sha)):
            require(_sha(receipt.get(key), key) == value, f"block {index}: {key} identity mismatch")
        _exact(receipt.get("final_full_key_count"), FULL_KEY_COUNT, "block final_full_key_count")
        _exact(receipt.get("full_clip_instantiated"), False, "block full_clip_instantiated")
        _window_admission(receipt.get("window_admission"),
                          [1 + tick / SUBDIVISIONS for tick in range(start, end + 1)], contract,
                          metadata["window_admission"]["full_raw_admission_sha256"],
                          metadata["window_admission"]["recipe_pins_sha256"])
        _sha(receipt.get("frame_file_sha256"), "frame_file_sha256")
        require(frame_path.stat().st_size == expected["frame_file_bytes"],
                f"block {index}: frame file size mismatch")
        require(expected["frame_file_bytes"] <= contract.max_file_bytes, "frame block exceeds file byte limit")
        # Do not retain twelve large, detailed native curve admission reports.
        summary = {key: receipt[key] for key in expected}
        summary["frame_file_sha256"] = receipt["frame_file_sha256"]
        descriptors.append((path, frame_path, summary, receipt_sha))
    return descriptors


def _validated_record(record, tick, contract):
    require(len(record) == contract.frame_bytes, "truncated frame record")
    expected_time = struct.pack("<f", tick / contract.ticks_per_second)
    require(record[:4] == expected_time, f"invalid frame time at tick {tick}")
    cursor = 4
    for _ in range(contract.bone_count + contract.actor_count):
        values = vrview.TRANSFORM.unpack_from(record, cursor)
        vrview.validate_transform(values)
        cursor += vrview.TRANSFORM.size
    visible = record[cursor:]
    require(all(value in (0, 1) for value in visible), f"invalid visibility at tick {tick}")
    return record


def assemble_stream(metadata_path, vrs_path, vrm_path, block_paths, output_path, *, contract):
    """Low-memory generic implementation; use assemble() for production.

    At most the two companion validations (one at a time), small metadata,
    and a few individual frame records are held, never a decoded clip.
    All identity checks are mandatory even when a smaller fixture contract is
    supplied. Input receipts must already be in exact contiguous block order.
    """
    _check_contract(contract)
    metadata, metadata_sha = _json_file(metadata_path)
    bones, actors, assigned = _validate_metadata(metadata, contract)
    vrs_crc, vrs_bytes = _companion(vrs_path, metadata["files"]["asset.vrs"], "VRS", bones, assigned)
    vrm_crc, vrm_bytes = _companion(vrm_path, metadata["files"]["asset.vrm"], "VRM", bones, assigned)
    prefix = _prefix(bones, actors, contract, vrs_crc, vrm_crc)
    payload_bytes = len(prefix) + (contract.last_tick + 1) * contract.frame_bytes
    output_bytes = vrview.HEADER.size + payload_bytes
    require(output_bytes <= contract.max_file_bytes, "VRA exceeds file byte limit")
    descriptors = _block_descriptors(block_paths, metadata, metadata_sha, contract)
    output_path = Path(output_path)
    input_paths = [Path(metadata_path), Path(vrs_path), Path(vrm_path)]
    input_paths.extend(path for descriptor in descriptors for path in descriptor[:2])
    require(output_path.resolve() not in {path.resolve() for path in input_paths},
            "output must not alias an input")
    require(not output_path.exists(), "output already exists; choose a new path")

    crc = zlib.crc32(prefix)
    count = 0
    previous_raw = None
    previous_time = -1.0
    seam_ticks = []
    source_records = 0
    with output_path.open("xb+") as output:
        output.write(b"\0" * vrview.HEADER.size)
        output.write(prefix)
        for index, (_, frame_path, receipt, _) in enumerate(descriptors):
            digest = hashlib.sha256()
            byte_count = 0
            with frame_path.open("rb") as frames:
                for tick in range(receipt["start_tick"], receipt["end_tick"] + 1):
                    raw = frames.read(contract.frame_bytes)
                    digest.update(raw)
                    byte_count += len(raw)
                    encoded = _validated_record(raw, tick, contract)
                    source_records += 1
                    if index and tick == receipt["start_tick"]:
                        require(raw == previous_raw, f"nonidentical seam record at tick {tick}")
                        seam_ticks.append(tick)
                        continue
                    require(tick == count, f"frame gap/duplicate at tick {tick}")
                    current_time, = struct.unpack_from("<f", raw)
                    require(math.isfinite(current_time) and current_time > previous_time,
                            "frame times must strictly increase")
                    output.write(encoded)
                    crc = zlib.crc32(encoded, crc)
                    count += 1
                    previous_raw = raw
                    previous_time = current_time
                require(frames.read(1) == b"", f"block {index}: trailing frame bytes")
            require(byte_count == receipt["frame_file_bytes"], f"block {index}: frame byte count mismatch")
            require(digest.hexdigest() == receipt["frame_file_sha256"], f"block {index}: frame SHA-256 mismatch")
        require(count == contract.last_tick + 1, "final frame count mismatch")
        require(len(seam_ticks) == contract.block_count - 1, "incomplete seam coverage")
        require(output.tell() == output_bytes, "output size mismatch")
        header = vrview.HEADER.pack(vrview.MAGIC, vrview.VERSION, payload_bytes, crc, 0)
        output.seek(0)
        output.write(header)
        output.flush()
        os.fsync(output.fileno())
        output.seek(0)
        digest = hashlib.sha256()
        while chunk := output.read(READ_CHUNK):
            digest.update(chunk)
        require(output.tell() == output_bytes, "written output size mismatch")

    return {"schema": REPORT_SCHEMA, "passed": True, "format": vrview.MAGIC.decode("ascii"),
            "sha256": digest.hexdigest(), "bytes": output_bytes, "payload_crc32": f"{crc:08x}",
            "clip_name": contract.clip_name, "loop": False, "frames": count,
            "bones": len(bones), "actors": len(actors), "frame_bytes": contract.frame_bytes,
            "transforms": count * (len(bones) + len(actors)),
            "blocks": len(descriptors), "source_records": source_records,
            "seams_verified": len(seam_ticks), "seam_ticks": seam_ticks,
            "duplicate_seam_records_removed": len(seam_ticks),
            "source_sha256": contract.source_sha256, "fbx_sha256": contract.fbx_sha256,
            "canonical_sha256": contract.canonical_sha256,
            "geometry_metadata_sha256": metadata_sha,
            "static_import_sha256": metadata["static_import_sha256"],
            "recipe_pins_sha256": metadata["recipe_pins_sha256"],
            "full_raw_admission_sha256": metadata["window_admission"]["full_raw_admission_sha256"],
            "vrs_sha256": metadata["files"]["asset.vrs"]["sha256"],
            "vrm_sha256": metadata["files"]["asset.vrm"]["sha256"],
            "vrs_bytes": vrs_bytes, "vrm_bytes": vrm_bytes,
            "inputs_retained": True, "rust_parity_verified": False}


def assemble(metadata_path, vrs_path, vrm_path, block_paths, output_path):
    """Assemble only the fixed 72-bone/3-actor, 24,321-frame one-hand clip."""
    return assemble_stream(metadata_path, vrs_path, vrm_path, block_paths, output_path,
                           contract=PRODUCTION_CONTRACT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--vrs", type=Path, required=True)
    parser.add_argument("--vrm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("receipts", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assemble(args.metadata, args.vrs, args.vrm, args.receipts, args.output)
    except (AssetError, OSError, OverflowError, struct.error, UnicodeError) as exc:
        print(f"assemble_runtime: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
