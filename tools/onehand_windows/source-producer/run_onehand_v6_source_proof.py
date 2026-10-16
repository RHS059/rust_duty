"""Explicit serialized native-job wrapper and CPU-only paired-witness comparison.

Preparation and tests do not invoke Blender. `native` launches exactly one job,
with a required owner-selected serialization lock and bounded timeout. The owner
must additionally coordinate this job with the wider native graphics queue.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import onehand_v6_source_delta as delta


@contextmanager
def exclusive_lock(path):
    path = Path(path).resolve(); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "started_unix": time.time()}, stream)
    try:
        yield
    finally:
        path.unlink()


def native_command(blender, arguments):
    return [str(Path(blender).resolve()), "--background", "--factory-startup", "--disable-autoexec",
            "--threads", "1", "--python-exit-code", "1", "--python",
            str(Path(__file__).resolve().with_name("onehand_v6_source_native.py")), "--", *arguments]


def run_native(args):
    delta.require(args.arguments and args.arguments[0] in ("extract", "replay", "witness"), "unsupported native job")
    delta.require(30 <= args.timeout_seconds <= 7200, "timeout must be 30..7200 seconds")
    verify_pins(args.pins, args.pins_sha256)
    executable = Path(args.blender).resolve()
    delta.require(executable.is_file(), "Blender executable missing")
    command = native_command(executable, args.arguments)
    job = args.job_directory.resolve()
    result = {"schema": "rust-duty-onehand-v6-bounded-native-job/v1", "command": command,
              "timeout_seconds": args.timeout_seconds, "started_unix": time.time(),
              "completed": False, "exit_code": None, "timed_out": False,
              "source_code_sha256": {name: delta.sha(Path(__file__).with_name(name)) for name in
                                     ("onehand_v6_source_delta.py", "onehand_v6_source_native.py", "run_onehand_v6_source_proof.py", "dense-times.json", "pose-corrections.json")}}
    # A parent-native-owner lock is required. Never remove a lock owned elsewhere.
    with exclusive_lock(args.lock):
        job.mkdir(parents=True, exist_ok=False)
        with (job / "stdout.log").open("xb") as out, (job / "stderr.log").open("xb") as err:
            try:
                process = subprocess.run(command, stdout=out, stderr=err, timeout=args.timeout_seconds,
                                         check=False, stdin=subprocess.DEVNULL)
                result["exit_code"] = process.returncode
                result["completed"] = process.returncode == 0
            except subprocess.TimeoutExpired:
                result["timed_out"] = True
    result["ended_unix"] = time.time()
    result["source_code_unchanged"] = all(delta.sha(Path(__file__).with_name(name)) == value
                                          for name, value in result["source_code_sha256"].items())
    result["completed"] = result["completed"] and result["source_code_unchanged"]
    result["stdout_sha256"] = delta.sha(job / "stdout.log")
    result["stderr_sha256"] = delta.sha(job / "stderr.log")
    delta.write_fresh_json(job / "process-receipt.json", result)
    delta.require(result["completed"], "native job failed or timed out; inspect fresh bounded logs")


def verify_pins(path, expected):
    delta.require(delta.sha(path) == expected, "package pin manifest differs")
    pins = delta.load_json(path)
    from onehand_v6_source_native import CODE_FILES
    delta.require(set(CODE_FILES) <= set(pins), "package pin inventory incomplete")
    here = Path(__file__).resolve().parent
    for name, wanted in pins.items():
        delta.require(Path(name).name == name and delta.is_sha256(wanted), "invalid package pin entry")
        delta.require(delta.sha(here / name) == wanted, "package file changed: " + name)
    return pins


def same_hash(path, expected):
    delta.require(delta.sha(path) == expected, "pinned evidence differs: " + Path(path).name)
    return delta.load_json(path)


def expected_action_hashes(recipe):
    return {"legacy": delta.RIG_FINGERPRINT, "complete": recipe["action"]["target_complete_sha256"],
            "metadata": recipe["metadata"]["after_sha256"], "auxiliary": recipe["action_auxiliary_sha256"]}


def validate_replay(recipe, replay, delta_sha):
    from onehand_v6_source_native import validate_recipe
    validate_recipe(recipe)
    delta.require(set(replay) == {"schema", "passed", "fresh_reopen_passed", "base_sha256", "approved_source_sha256",
               "generated_source_sha256", "delta_sha256", "prior_actions_preserved", "created_actions", "result_action_count",
               "action_hashes", "static_hashes", "original_scalar_corrections_applied", "unchanged_driven_outputs_recomputed",
               "producer_sha256", "blender_version", "source_byte_identity_with_approved", "evaluated_equivalence_proved",
               "runtime_equivalence_proved", "rendered", "limits"}, "raw or unexpected replay fields")
    delta.require(replay["evaluated_equivalence_proved"] is False, "replay cannot preclaim evaluated equivalence")
    delta.require(replay["limits"] == ["Independent exact 4240-time witness comparison remains required.",
                          "The regenerated private BLEND is never a source-only publication artifact."], "replay limit declaration differs")
    delta.require(replay.get("schema") == "rust-duty-onehand-v6-source-replay/v1", "unexpected replay schema")
    delta.require(replay["passed"] is True and replay["fresh_reopen_passed"] is True, "fresh reopen not proved")
    delta.require(replay["base_sha256"] == delta.BASE_SHA and replay["approved_source_sha256"] == delta.APPROVED_SHA
                  and replay["delta_sha256"] == delta_sha, "replay source/delta identity differs")
    generated = replay["generated_source_sha256"]
    delta.require(delta.is_sha256(generated) and generated not in (delta.BASE_SHA, delta.APPROVED_SHA),
                  "new serialized source identity required")
    delta.require(replay["prior_actions_preserved"] == 88 and replay["result_action_count"] == 89
                  and replay["created_actions"] == [delta.RIG_ACTION], "all 88 originals plus one final Action required")
    delta.require(replay["original_scalar_corrections_applied"] == 12
                  and replay["unchanged_driven_outputs_recomputed"] == 4, "lineage correction coverage differs")
    delta.require(replay["action_hashes"] == expected_action_hashes(recipe), "replay exact Action differs")
    delta.require(replay["static_hashes"] == recipe["approved_static_hashes"], "replay static state differs")
    delta.require(replay["producer_sha256"] == recipe["producer_sha256"]
                  and replay["blender_version"] == delta.BLENDER_VERSION, "replay producer differs")
    delta.require(replay["source_byte_identity_with_approved"] is False and replay["rendered"] is False
                  and replay["runtime_equivalence_proved"] is False, "replay makes unsupported claims")
    return generated


def validate_geometry(rows):
    from onehand_v6_source_native import GEOMETRY, SKINS
    delta.require(isinstance(rows, list) and [r["name"] for r in rows] == list(GEOMETRY), "incomplete geometry coverage")
    for row in rows:
        delta.require(set(row) == {"name", "role", "vertices", "local_positions_sha256", "world_positions_sha256", "topology_sha256"},
                      "raw or unexpected geometry fields")
        delta.require(row["role"] == ("skin" if row["name"] in SKINS else "rigid")
                      and type(row["vertices"]) is int and row["vertices"] > 0, "invalid evaluated geometry inventory")
        delta.require(all(delta.is_sha256(row[k]) for k in ("local_positions_sha256", "world_positions_sha256", "topology_sha256")),
                      "malformed geometry hash")
    delta.require(sum(r["vertices"] for r in rows if r["role"] == "skin") == 10234, "incomplete skin vertex inventory")


def validate_chunk(witness, recipe, replay, kind, chunk_index):
    from onehand_v6_source_native import ACTORS, SKINS, NUMERIC_CONTRACT
    delta.require(set(witness) == {"schema", "kind", "source_sha256", "approved_source_sha256", "delta_sha256",
              "action_hashes", "inherited_actions_sha256", "static_hashes", "producer_sha256", "blender_version",
              "motion", "source_saved", "source_bytes_unchanged", "rendered", "runtime_equivalence_proved"},
              "raw or unexpected witness fields")
    delta.require(witness["schema"] == "rust-duty-onehand-v6-source-witness-chunk/v1" and witness["kind"] == kind,
                  "unexpected witness schema/role")
    expected_sha = delta.APPROVED_SHA if kind == "approved" else replay["generated_source_sha256"]
    delta.require(witness["source_sha256"] == expected_sha and witness["approved_source_sha256"] == delta.APPROVED_SHA
                  and witness["delta_sha256"] == replay["delta_sha256"], "witness source provenance differs")
    delta.require(witness["action_hashes"] == expected_action_hashes(recipe)
                  and witness["inherited_actions_sha256"] == delta.digest(recipe["inherited_actions"]), "witness Action preservation differs")
    delta.require(witness["static_hashes"] == recipe["approved_static_hashes"], "witness static state differs")
    delta.require(witness["producer_sha256"] == recipe["producer_sha256"]
                  and witness["blender_version"] == delta.BLENDER_VERSION, "witness producer differs")
    delta.require(witness["source_saved"] is False and witness["rendered"] is False
                  and witness["source_bytes_unchanged"] is True and witness["runtime_equivalence_proved"] is False,
                  "witness must be read-only with no runtime claim")
    motion = witness["motion"]
    delta.require(set(motion) == {"chunk_index", "index_range_half_open", "sample_count", "grid_sha256", "numeric_contract",
            "bone_count", "bone_order_sha256", "object_order_sha256", "hierarchy_sha256", "rest_world_sha256",
            "actors", "skins", "canonical_reset_action", "frame1_geometry", "static_rig_world_sha256",
            "static_camera_world_sha256", "static_projection_sha256", "rows"}, "raw or unexpected motion fields")
    start, stop = delta.chunk_bounds(chunk_index)
    delta.require(motion["chunk_index"] == chunk_index and motion["index_range_half_open"] == [start, stop]
                  and motion["sample_count"] == len(motion["rows"]) == stop - start, "incomplete chunk coverage")
    delta.require(motion["grid_sha256"] == delta.GRID_SHA and motion["numeric_contract"] == NUMERIC_CONTRACT,
                  "clock or strict numeric contract differs")
    delta.require(motion["bone_count"] == 148 and motion["actors"] == list(ACTORS) and motion["skins"] == list(SKINS)
                  and motion["canonical_reset_action"] == delta.RESET_ACTION, "coverage/reset differs")
    for key in ("bone_order_sha256", "object_order_sha256", "hierarchy_sha256", "rest_world_sha256",
                "static_rig_world_sha256", "static_camera_world_sha256", "static_projection_sha256"):
        delta.require(delta.is_sha256(motion[key]), "malformed motion scope hash")
    validate_geometry(motion["frame1_geometry"])
    times = delta.probe_times()
    for index, row in enumerate(motion["rows"], start):
        delta.require(set(row) == {"sample_index", "frame", "bones_world_sha256", "rig_world_sha256", "camera_world_sha256",
                     "projection_sha256", "actors_world_sha256", "all_objects_world_sha256", "geometry"}, "raw or unexpected row fields")
        delta.require(row["sample_index"] == index and row["frame"] == times[index], "exact sample index/time differs")
        for key in ("bones_world_sha256", "rig_world_sha256", "camera_world_sha256", "projection_sha256",
                    "actors_world_sha256", "all_objects_world_sha256"):
            delta.require(delta.is_sha256(row[key]), "malformed row hash")
        delta.require(row["rig_world_sha256"] == motion["static_rig_world_sha256"]
                      and row["camera_world_sha256"] == motion["static_camera_world_sha256"]
                      and row["projection_sha256"] == motion["static_projection_sha256"], "static camera/rig contract drift")
        validate_geometry(row["geometry"])
        for current, initial in zip(row["geometry"], motion["frame1_geometry"]):
            delta.require(current["vertices"] == initial["vertices"] and current["topology_sha256"] == initial["topology_sha256"],
                          "geometry topology drift")
            if current["role"] == "rigid":
                delta.require(current["local_positions_sha256"] == initial["local_positions_sha256"], "rigid geometry drift")
    return {key: value for key, value in motion.items() if key not in ("chunk_index", "index_range_half_open", "sample_count", "rows")}


def compare_chunks(approved, regenerated, recipe, replay, chunk_index):
    a = validate_chunk(approved, recipe, replay, "approved", chunk_index)
    b = validate_chunk(regenerated, recipe, replay, "regenerated", chunk_index)
    delta.require(delta.exact_equal(approved["motion"], regenerated["motion"]), "exact evaluated motion/geometry mismatch")
    delta.require(a == b, "paired motion scope differs")
    return a


def build_equivalence_result(args):
    """Strict read-only revalidation of every sealed input; creates no files."""
    recipe = same_hash(args.delta, args.delta_sha256)
    from onehand_v6_source_native import producer_hashes
    delta.require(recipe["producer_sha256"] == producer_hashes(), "recipe producer differs from current package code")
    replay = same_hash(args.replay_receipt, args.replay_receipt_sha256)
    generated = validate_replay(recipe, replay, args.delta_sha256)
    index = same_hash(args.witness_index, args.witness_index_sha256)
    names = [f"{kind}-{i:03}.json" for i in range(17) for kind in ("approved", "regenerated")]
    delta.require(set(index) == set(names) and all(delta.is_sha256(v) for v in index.values()), "incomplete witness index")
    common = None; chunk_hashes = []; sample_count = 0
    for i in range(17):
        a, b = [same_hash(args.directory / f"{kind}-{i:03}.json", index[f"{kind}-{i:03}.json"])
                for kind in ("approved", "regenerated")]
        scope = compare_chunks(a, b, recipe, replay, i)
        if common is None:
            common = scope
        delta.require(scope == common, "witness scope changed across chunks")
        sample_count += a["motion"]["sample_count"]
        chunk_hashes.append(delta.digest(a["motion"]))
    delta.require(sample_count == 4240, "incomplete all-time comparison")
    result = {"schema": "rust-duty-onehand-v6-source-equivalence/v1", "passed": True,
              "base_sha256": delta.BASE_SHA, "approved_source_sha256": delta.APPROVED_SHA,
              "generated_source_sha256": generated, "delta_sha256": args.delta_sha256,
              "replay_receipt_sha256": args.replay_receipt_sha256, "witness_index_sha256": args.witness_index_sha256,
              "sample_count": sample_count, "chunk_count": 17, "grid_sha256": delta.GRID_SHA,
              "motion_chunks_sha256": delta.digest(chunk_hashes), "common_motion_scope_sha256": delta.digest(common),
              "exact_action_hashes": expected_action_hashes(recipe), "prior_actions_preserved": 88,
              "result_action_count": 89, "original_scalar_corrections_applied": 12, "unchanged_driven_outputs_recomputed": 4,
              "static_state_sha256": delta.digest(recipe["approved_static_hashes"]),
              "producer_sha256": recipe["producer_sha256"], "blender_version": delta.BLENDER_VERSION,
              "source_byte_identity_with_approved": False, "evaluated_source_equivalence_proved": True,
              "runtime_equivalence_proved": False, "rendered": False,
              "limits": ["Serialized identities are distinct; proof covers exact Action and 4240 sampled evaluations.",
                         "No continuous-time proof or converted/native runtime acceptance is inferred.",
                         "No permission to publish private geometry, scene defaults, rest data or full BLEND is inferred."]}
    return result


def verify_saved_equivalence(args):
    """A saved completion is valid only if its entire proof matches current evidence."""
    expected = build_equivalence_result(args)
    saved = delta.load_json(args.output)
    delta.require(delta.exact_equal(saved, expected),
                  "saved equivalence proof differs from full current sealed evidence")
    return expected


def compare_directory(args):
    result = build_equivalence_result(args)
    delta.write_fresh_json(args.output, result)
    print("ONEHAND_V6_SOURCE_EQUIVALENCE", delta.sha(args.output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    native = commands.add_parser("native")
    native.add_argument("--blender", required=True)
    native.add_argument("--lock", type=Path, required=True)
    native.add_argument("--job-directory", type=Path, required=True)
    native.add_argument("--pins", type=Path, required=True)
    native.add_argument("--pins-sha256", required=True)
    native.add_argument("--timeout-seconds", type=int, default=1800)
    native.add_argument("arguments", nargs=argparse.REMAINDER)
    compare = commands.add_parser("compare")
    compare.add_argument("--directory", type=Path, required=True)
    for name in ("delta", "replay-receipt", "witness-index"):
        compare.add_argument("--" + name, type=Path, required=True)
        compare.add_argument("--" + name + "-sha256", required=True)
    compare.add_argument("--output", type=Path, required=True)
    seal = commands.add_parser("seal")
    seal.add_argument("--directory", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "native":
        if args.arguments and args.arguments[0] == "--":
            args.arguments = args.arguments[1:]
        run_native(args)
    elif args.mode == "compare":
        compare_directory(args)
    else:
        names = [f"{kind}-{i:03}.json" for i in range(17) for kind in ("approved", "regenerated")]
        delta.write_fresh_json(args.output, {name: delta.sha(args.directory / name) for name in names})


if __name__ == "__main__":
    main()
