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
import prone_r15_source_delta as delta


def same_hash(path, expected):
    delta.require(delta.sha(path) == expected, "pinned evidence differs: " + Path(path).name)
    return delta.load_json(path)


def compare_witnesses(approved, regenerated, replay, recipe):
    """A strict comparison, deliberately separate from extraction/replay."""
    from prone_r15_source_native import validate_recipe
    validate_recipe(recipe)
    delta.require(approved.get("schema") == regenerated.get("schema") == "rust-duty-prone-r15-paired-witness/v1",
                  "unexpected witness schema")
    delta.require(replay.get("schema") == "rust-duty-prone-r15-source-replay/v1", "unexpected replay schema")
    delta.require(approved["kind"] == "approved" and regenerated["kind"] == "regenerated", "witness role differs")
    delta.require(approved["source_sha256"] == approved["approved_source_sha256"] == delta.APPROVED_SHA,
                  "approved source identity differs")
    generated_sha = regenerated["source_sha256"]
    delta.require(generated_sha == replay["generated_source_sha256"] and delta.is_sha256(generated_sha)
                  and generated_sha not in (delta.BASE_SHA, delta.APPROVED_SHA), "regenerated source identity differs")
    delta.require(regenerated["approved_source_sha256"] == replay["approved_source_sha256"] == delta.APPROVED_SHA,
                  "approved-motion provenance differs")
    delta.require(replay["base_sha256"] == delta.BASE_SHA, "replay base differs")
    delta.require(replay["passed"] is True and replay["fresh_reopen_passed"] is True
                  and replay["saved_default_bindings_unchanged"] is True
                  and replay["source_byte_identity_with_approved"] is False, "fresh source preservation not established")
    delta.require(replay["prior_actions_preserved"] == 112
                  and set(replay["created_actions"]) == {delta.RIG_ACTION, delta.CAMERA_ACTION}, "replay Action set differs")
    expected = {delta.RIG_ACTION: delta.RIG_FINGERPRINT, delta.CAMERA_ACTION: delta.CAMERA_FINGERPRINT}
    delta.require(replay["rig_action_fingerprint"] == delta.RIG_FINGERPRINT
                  and replay["camera_action_fingerprint"] == delta.CAMERA_FINGERPRINT, "replay pair differs")
    complete = {role: recipe["actions"][role]["target_complete_sha256"] for role in ("rig", "camera")}
    delta.require(replay["complete_action_fingerprints"] == complete, "complete replay Action hashes differ")
    for witness in (approved, regenerated):
        delta.require(witness["complete_action_fingerprints"] == complete, "complete witness Actions differ")
        delta.require(witness["producer_sha256"] == replay["producer_sha256"] == recipe["producer_sha256"],
                      "producer code identity differs")
        delta.require(witness["action_fingerprints"] == expected, "witness pair differs")
        delta.require(witness["source_saved"] is False and witness["rendered"] is False, "witness is not read-only")
        delta.require(witness["blender_version"] == replay["blender_version"] == delta.BLENDER_VERSION, "Blender version differs")
        delta.require(witness["static_hashes"] == replay["static_hashes"] == recipe["static_hashes"], "non-Action preservation differs")
        motion = witness["motion"]
        delta.require(motion["bone_count"] == 148 and motion["actors"] == ["hk416_weapon", "hk416_magazine", "hk416_magazine_outgoing"],
                      "incomplete bone or actor coverage")
        delta.require(motion["sample_count"] == len(motion["rows"]) == 1944, "incomplete evaluated witness")
        delta.require([r["frame"] for r in motion["rows"]] == delta.probe_times(), "sample times differ")
        delta.require(motion["times_sha256"] == delta.digest(delta.probe_times()), "sample clock hash differs")
        delta.require(motion["canonical_reset_action"] == delta.RESET_ACTION, "canonical reset differs")
        delta.require(motion["numeric_contract"] == "strict little-endian float64 bytes; no quantization; same Blender 4.3.2 evaluation",
                      "numeric equality was relaxed")
        for row in motion["rows"]:
            delta.require(set(row) == {"frame", "bones_world_sha256", "rig_world_sha256", "camera_world_sha256",
                                       "actors_world_sha256", "skins"}, "witness field set differs")
            delta.require(len(row["skins"]) == 3 and len({s["name"] for s in row["skins"]}) == 3,
                          "incomplete skin coverage")
            for key in ("bones_world_sha256", "rig_world_sha256", "camera_world_sha256", "actors_world_sha256"):
                delta.require(delta.is_sha256(row[key]), "malformed motion hash")
            for skin in row["skins"]:
                delta.require(set(skin) == {"name", "vertices", "sha256"} and skin["vertices"] > 0
                              and delta.is_sha256(skin["sha256"]), "malformed skin witness")
    delta.require(approved["motion"] == regenerated["motion"], "evaluated paired-motion witness differs")
    return {"schema": "rust-duty-prone-r15-source-equivalence/v1", "passed": True,
            "base_sha256": delta.BASE_SHA, "approved_source_sha256": delta.APPROVED_SHA,
            "generated_source_sha256": generated_sha,
            "rig_action": delta.RIG_ACTION, "rig_action_fingerprint": delta.RIG_FINGERPRINT,
            "camera_action": delta.CAMERA_ACTION, "camera_action_fingerprint": delta.CAMERA_FINGERPRINT,
            "canonical_reset_action": delta.RESET_ACTION, "canonical_reset_fingerprint": delta.RESET_FINGERPRINT,
            "sample_count": 1944, "times_sha256": delta.digest(delta.probe_times()),
            "approved_motion_sha256": delta.digest(approved["motion"]),
            "regenerated_motion_sha256": delta.digest(regenerated["motion"]),
            "complete_action_fingerprints": complete,
            "producer_sha256": recipe["producer_sha256"],
            "static_hashes_sha256": delta.digest(recipe["static_hashes"]),
            "numeric_contract": approved["motion"]["numeric_contract"],
            "source_frame_range": [1, 69], "native_fps": [60, 1], "camera_sample_hz": 3840,
            "exact_complete_actions_proved": True, "non_action_preservation_proved": True,
            "evaluated_pair_equivalence_proved": True, "source_byte_identity_with_approved": False,
            "runtime_equivalence_proved": False, "rendered": False,
            "blender_version": delta.BLENDER_VERSION, "delta_sha256": replay["delta_sha256"],
            "limits": ["Original approved and regenerated serialized BLEND identities are distinct.",
                       "Converted runtime and actual native-renderer equivalence remain separate checks.",
                       "Exact native float hashes can expose cross-platform numeric differences; no tolerance is inferred."]}


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
            str(Path(__file__).resolve().with_name("prone_r15_source_native.py")), "--", *arguments]


def run_native(args):
    delta.require(args.arguments and args.arguments[0] in ("extract", "replay", "witness"), "unsupported native job")
    delta.require(30 <= args.timeout_seconds <= 7200, "timeout must be 30..7200 seconds")
    executable = Path(args.blender).resolve()
    delta.require(executable.is_file(), "Blender executable missing")
    command = native_command(executable, args.arguments)
    job = args.job_directory.resolve()
    job.mkdir(parents=True, exist_ok=False)
    result = {"schema": "rust-duty-prone-r15-bounded-native-job/v1", "command": command,
              "timeout_seconds": args.timeout_seconds, "started_unix": time.time(),
              "completed": False, "exit_code": None, "timed_out": False,
              "source_code_sha256": {name: delta.sha(Path(__file__).with_name(name)) for name in
                                     ("prone_r15_source_delta.py", "prone_r15_source_native.py", "run_prone_r15_source_proof.py")}}
    # A parent-native-owner lock is required. Never remove a lock owned elsewhere.
    with exclusive_lock(args.lock):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    native = commands.add_parser("native")
    native.add_argument("--blender", required=True)
    native.add_argument("--lock", type=Path, required=True)
    native.add_argument("--job-directory", type=Path, required=True)
    native.add_argument("--timeout-seconds", type=int, default=1800)
    native.add_argument("arguments", nargs=argparse.REMAINDER)
    compare = commands.add_parser("compare")
    for name in ("approved-witness", "regenerated-witness", "replay-receipt", "delta"):
        compare.add_argument("--" + name, type=Path, required=True)
        compare.add_argument("--" + name + "-sha256", required=True)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "native":
        if args.arguments and args.arguments[0] == "--":
            args.arguments = args.arguments[1:]
        run_native(args)
        return
    delta.require(not args.output.exists(), "refuse to overwrite equivalence proof")
    inputs = {name: same_hash(getattr(args, name), getattr(args, name + "_sha256"))
              for name in ("approved_witness", "regenerated_witness", "replay_receipt", "delta")}
    delta.require(inputs["replay_receipt"]["delta_sha256"] == args.delta_sha256, "replay consumed a different delta")
    result = compare_witnesses(inputs["approved_witness"], inputs["regenerated_witness"],
                               inputs["replay_receipt"], inputs["delta"])
    result["evidence_sha256"] = {name: getattr(args, name + "_sha256") for name in inputs}
    delta.write_fresh_json(args.output, result)
    print("PRONE_R15_SOURCE_EQUIVALENCE", delta.sha(args.output))


if __name__ == "__main__":
    main()
