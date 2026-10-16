"""CPU-only next-command planner. Prints one reviewed-owner command; never runs it."""
from pathlib import Path
import argparse
import json
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import onehand_v6_source_delta as d
from onehand_v6_source_native import validate_recipe, producer_hashes
from run_onehand_v6_source_proof import verify_pins, validate_replay, compare_chunks, verify_saved_equivalence
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "reboot-recovery-20261014/aella_mantle_r3.baseline.blend"
APPROVED = ROOT / "recovery/onehand-camera-solve-v6/candidate-v1/onehand-r6-camera-reconstructed-v6.blend"


def next_command(args):
    verify_pins(HERE / "PINS.json", args.pins_sha256)
    d.require(d.sha(BASE) == d.BASE_SHA and d.sha(APPROVED) == d.APPROVED_SHA, "frozen input bytes differ")
    d.probe_times(); d.pose_corrections()
    root = args.output_directory.resolve()
    d.require(root == HERE or HERE in root.parents, "preparation owner outputs must stay under this preparation directory")
    d.require(root != HERE, "use a distinct fresh native-result subdirectory")
    script = str(HERE / "run_onehand_v6_source_proof.py")

    def native(label, arguments):
        job = root / (label + "-job")
        d.require(not job.exists(), "previous native attempt needs owner inspection; do not automatically retry or overwrite: " + label)
        return {"stage": label, "command": [sys.executable, script, "native", "--blender", args.blender,
                "--lock", str(args.lock.resolve()), "--pins", str(HERE / "PINS.json"), "--pins-sha256", args.pins_sha256,
                "--job-directory", str(job), "--timeout-seconds", "1800", "--", *arguments],
                "requires_serialized_native_owner": True, "launch_authorized_by_this_plan": False,
                "scope": "No rendering, no solver, no source-input save, no upload or publication."}

    delta_file = root / "original-delta.json"
    replay_file = root / "replay-receipt.json"
    source = root / "regenerated-onehand-v6.blend"
    if not delta_file.exists():
        return native("extract", ["extract", "--base", str(BASE), "--approved", str(APPROVED), "--output", str(delta_file)])
    recipe = d.load_json(delta_file); validate_recipe(recipe); delta_sha = d.sha(delta_file)
    d.require(recipe["producer_sha256"] == producer_hashes(), "loaded recipe was produced by different current package code")
    if not replay_file.exists():
        d.require(not source.exists(), "partial replay source exists without passed receipt; owner inspection required")
        return native("replay", ["replay", "--base", str(BASE), "--delta", str(delta_file), "--delta-sha256", delta_sha,
                                "--output", str(source), "--receipt", str(replay_file)])
    replay = d.load_json(replay_file); generated = validate_replay(recipe, replay, delta_sha)
    d.require(d.sha(source) == generated, "regenerated source differs from fresh-reopen receipt")
    for i in range(17):
        for kind in ("approved", "regenerated"):
            destination = root / f"{kind}-{i:03}.json"
            if not destination.exists():
                arguments = ["witness", "--source", str(APPROVED if kind == "approved" else source),
                             "--source-sha256", d.APPROVED_SHA if kind == "approved" else generated,
                             "--delta", str(delta_file), "--delta-sha256", delta_sha, "--kind", kind,
                             "--chunk-index", str(i), "--output", str(destination)]
                if kind == "regenerated":
                    arguments += ["--replay-receipt", str(replay_file), "--replay-receipt-sha256", d.sha(replay_file)]
                return native(f"{kind}-{i:03}", arguments)
        compare_chunks(d.load_json(root / f"approved-{i:03}.json"), d.load_json(root / f"regenerated-{i:03}.json"),
                       recipe, replay, i)
    index = root / "witness-index.json"
    if not index.exists():
        return {"stage": "seal", "command": [sys.executable, script, "seal", "--directory", str(root), "--output", str(index)],
                "requires_serialized_native_owner": False, "scope": "CPU-only hash index, no native launch."}
    output = root / "source-equivalence.json"
    if not output.exists():
        return {"stage": "compare", "command": [sys.executable, script, "compare", "--directory", str(root),
                "--delta", str(delta_file), "--delta-sha256", delta_sha, "--replay-receipt", str(replay_file),
                "--replay-receipt-sha256", d.sha(replay_file), "--witness-index", str(index), "--witness-index-sha256", d.sha(index),
                "--output", str(output)], "requires_serialized_native_owner": False,
                "scope": "CPU-only strict all-4240 comparison; no runtime/render acceptance."}
    # Never accept a completion flag or partial/stale summary. Read all 34 sealed
    # chunks again and reproduce the entire proof, including evidence identities.
    proof = verify_saved_equivalence(SimpleNamespace(
        delta=delta_file, delta_sha256=delta_sha,
        replay_receipt=replay_file, replay_receipt_sha256=d.sha(replay_file),
        witness_index=index, witness_index_sha256=d.sha(index),
        directory=root, output=output))
    return {"stage": "complete", "source_equivalence_sha256": d.sha(output),
            "source_byte_identity_with_approved": False, "runtime_equivalence_proved": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pins-sha256", required=True)
    parser.add_argument("--blender", default="/usr/bin/blender")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=HERE / "native-r1")
    args = parser.parse_args()
    print(json.dumps(next_command(args), indent=2))


if __name__ == "__main__":
    main()
