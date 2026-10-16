"""Strict provenance for newly exported proven-equivalent r15 runtime data.

No Blender, renderer or process starts on import. Original verifier pins remain
unchanged. This is a separate proof-bearing route, never a constant override.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

import prone_camera_pair as pair
import prone_r15_source_delta as delta

ACTION = delta.RIG_ACTION
CAMERA_ACTION = delta.CAMERA_ACTION
CAMERA = delta.CAMERA_OBJECT
SKINS = [f"Actual arms mesh {i}" for i in range(3)]
ACTORS = ["hk416_weapon", "hk416_magazine", "hk416_magazine_outgoing"]
SELECTED = [delta.RIG_OBJECT, *SKINS, *ACTORS, CAMERA]
GRID_SHA = "f47bb34d734b7e5bf01806530c23367a45214e9037ea445c102e9405db9ff1e4"
ORIGINAL_ORACLE_SHA = "94195fd1f003a56711add86caf81a762ce9a392741c9de0c8e0cfdf0a948dcb9"
EVIDENCE_FILES = {"export-receipt.json", "paired-camera-contract.json", "fresh-import-parity.json", "fbx-take-contract.json"}
DENSE_SETTINGS = {"use_selection": True, "object_types": {"MESH", "ARMATURE", "CAMERA"},
    "add_leaf_bones": False, "bake_anim": True, "bake_anim_use_nla_strips": False,
    "bake_anim_use_all_actions": False, "bake_anim_use_all_bones": True,
    "bake_anim_simplify_factor": 0., "bake_anim_step": 1/64, "path_mode": "AUTO",
    "axis_forward": "-Z", "axis_up": "Y", "use_armature_deform_only": False}
ERROR_FIELDS = {"bone_deformation_world_matrix", "bone_head_world_m", "actor_world_matrix",
    "actor_camera_relative_matrix", "camera_world_matrix", "rig_world_matrix", "skin_world_m", "skin_camera_relative_m"}
CODE_FILES = ("produce_prone_r15_regenerated_runtime.py", "export_prone_r15_regenerated_dense.py",
    "prone_r15_regenerated_contract.py", "sample_prone_r15_regenerated_rigid.py", "verify_prone_r15_runtime.py", "import_fbx_viewmodel.py", "export_viewmodel.py",
    "prone_camera_pair.py", "prone_r15_equivalence_contract.json", "prone_r15_source_native.py", "prone_r15_source_delta.py",
    "run_prone_r15_source_proof.py", "sample_prone_r15_camera.py", "export_prone_pair.py", "vrpack.py", "vrskin.py", "vrview.py")


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "regular provenance input required")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    require(delta.is_sha256(value), "invalid provenance SHA-256")
    return value


def read(path, expected=None):
    if expected is not None:
        require(sha(path) == digest(expected), "provenance bytes differ")
    return delta.load_json(path)


def write(path, value):
    delta.write_fresh_json(Path(path), value)


def code_hashes():
    here = Path(__file__).resolve().parent
    return {name: sha(here / name) for name in CODE_FILES}


def grid():
    frames = delta.probe_times()
    require(len(frames) == 1944 and hashlib.sha256((json.dumps(frames) + "\n").encode()).hexdigest() == GRID_SHA,
            "independent approved clock changed")
    return frames


def descriptor(equivalence_path, equivalence_sha256, source):
    source_sha = sha(source)
    require(source_sha not in (delta.APPROVED_SHA, delta.BASE_SHA), "regenerated source must have distinct actual identity")
    # Missing/unpinned shared contract fails here, before any native process.
    return pair.load_r15_equivalence_report(equivalence_path, equivalence_sha256, source_sha)


def load_runtime_provenance(path, expected_sha, source, equivalence, equivalence_sha):
    require(all(value is not None for value in (expected_sha, source, equivalence, equivalence_sha)),
            "complete regenerated provenance arguments are required")
    value = read(path, expected_sha)
    fields = {"schema", "generated_source_sha256", "approved_source_sha256", "source_equivalence_sha256",
        "source_equivalence_descriptor", "source_witness_sha256", "source_witness_source_sha256",
        "source_fbx_sha256", "camera_sidecar_sha256", "rigid_witness_sha256", "export_evidence_sha256", "producer_sha256"}
    require(type(value) is dict and set(value) == fields, "regenerated provenance fields differ")
    require(value["schema"] == "rust-duty-prone-r15-regenerated-runtime-provenance/v1", "regenerated provenance schema differs")
    require(value["generated_source_sha256"] == sha(source) and value["approved_source_sha256"] == delta.APPROVED_SHA,
            "regenerated/original source provenance differs")
    require(value["source_equivalence_sha256"] == equivalence_sha and
            value["source_equivalence_descriptor"] == descriptor(equivalence, equivalence_sha, source),
            "regenerated proof descriptor differs")
    require(value["source_witness_source_sha256"] in (delta.APPROVED_SHA, value["generated_source_sha256"]),
            "oracle source is neither the proven candidate nor approved reference")
    if value["source_witness_source_sha256"] == delta.APPROVED_SHA:
        require(value["source_witness_sha256"] == ORIGINAL_ORACLE_SHA, "original private oracle must retain immutable identity")
    for name in ("source_witness_sha256", "source_fbx_sha256", "camera_sidecar_sha256", "rigid_witness_sha256"):
        digest(value[name])
    require(set(value["export_evidence_sha256"]) == EVIDENCE_FILES, "dense evidence inventory differs")
    for file_sha in value["export_evidence_sha256"].values():
        digest(file_sha)
    require(value["producer_sha256"] == code_hashes(), "regenerated producer/verifier code differs")
    return value


def validate_dense_evidence(receipt, parity, provenance):
    actual = provenance["generated_source_sha256"]
    for document in (receipt, parity):
        require(document["source_sha256"] == actual and document["fbx_sha256"] == provenance["source_fbx_sha256"],
                "dense evidence source/FBX identity differs")
        require(document["source_equivalence_sha256"] == provenance["source_equivalence_sha256"] and
                document["source_equivalence_descriptor"] == provenance["source_equivalence_descriptor"],
                "dense evidence proof descriptor differs")
        require(document["sample_grid_sha256"] == GRID_SHA and document["fbx_bake_step"] == 1/64,
                "dense bake/sample clock differs")
    require(receipt["source_sample_count"] == 1944 and receipt["frames"] == [1, 69] and receipt["fps"] == [60, 1]
            and receipt["export_bind_frame"] == 1 and receipt["selected"] == SELECTED,
            "dense export pair/inventory differs")
    require(receipt["settings"] == {k: sorted(v) if isinstance(v, set) else v for k, v in DENSE_SETTINGS.items()},
            "dense FBX settings differ")
    require(receipt["source_bytes_unchanged"] is True and receipt["in_memory_source_state_restored"] is True and
            receipt["source_saved"] is False and receipt["rendered"] is False, "dense export altered source or rendered")
    require(parity["passed"] is True and parity["samples"] == 1944 and parity["source_total_bones_including_helpers"] == 148
            and parity["skin_vertex_samples"] == 1944 * 10234, "fresh import coverage incomplete")
    required_checks = ERROR_FIELDS | {"bone_inventory", "hierarchy", "animated_camera_bound", "animated_rig_bound",
        "single_exact_take", "finite_bones", "skin_topology", "camera_projection_rays", "camera_type", "single_native_clock",
        "fps", "source_unchanged", "fbx_unchanged"}
    require(set(parity["checks"]) == required_checks and all(v is True for v in parity["checks"].values()),
            "fresh import required check failed/missing")
    require(set(parity["maxima"]) == ERROR_FIELDS and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v < 1e-4
            for v in parity["maxima"].values()), "fresh import numerical bound failed")
    ray = parity["camera_projection_ray_error"]
    require(type(ray) in (int, float) and math.isfinite(ray) and 0 <= ray < 1e-5, "camera projection bound failed")
    require(parity["camera_included_and_measured"] is True and parity["camera_relative_geometry_measured"] is True
            and parity["subframe_parity"] is True, "paired geometry coverage missing")
