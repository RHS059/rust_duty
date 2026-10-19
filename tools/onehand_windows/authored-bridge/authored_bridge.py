"""Read-only authored-input admission bridge; never launches native programs.

Reuses the exact original source proof implementation. A pass admits only the
recorded authored state. It never establishes Windows execution, cross-platform
float64 evaluation equality, runtime parity, publication or activation authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path
import struct
import sys
from types import ModuleType, SimpleNamespace

sys.dont_write_bytecode = True
ADAPTER_PINS_SHA = "3a7dfc3f96a83b530f125f239dc8e5aac0052030366e30ef55fe45ca9950bb8d"
ADAPTER_CODE_SHA = "c7dd33dcd61e4e4dfa6afe0e370c55d4d35df6ba000fa47a4268476608d99fb1"
SOURCE_PINS_SHA = "0c7e6e1ef7a2f0c3637e7eb800d0fc7a1bd196c69bdb3c377db76680e0663a5f"
DELTA_SHA = "7be513e2c9fa5d0ff1c00684c542a73354d49fd561fd406a08dad8e05c219a9d"
BASE_SHA = "6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79"
APPROVED_SHA = "b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77"
CANONICAL_SHA = "d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab"
APPROVED_FBX_SHA = "5b847bf47cfafdf9a4b4d32f3d5972e677698db3f47cdc7a4a36a4b7698ee2c2"
CURRENT_VRA_SHA = "26aca4fbb5efd04587feb513658348b1cd217c456d8a22a57eb29defb9309380"
MANIFEST_FILES = {
    "onehand-runtime-20261016/source-producer-preparation/PINS.json": SOURCE_PINS_SHA,
    "onehand-runtime-20261016/source-producer-preparation/windows-portable-v1/PINS.json": ADAPTER_PINS_SHA,
    "onehand-runtime-20261016-r2/runtime-conversion-v2/pins.json": "6f1d03f86ec0464d0fd249fc2ac82e8d415cd11149f679fe56aa22dbe3922212",
    "onehand-runtime-20261016-r2/runtime-parity/implementation-pins.json": "1e31cf591879b0946110ee4cbf154d41e447b152c05000d9775100bd2d91f37a",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_dependencies(package):
    """Compile verified portable adapter source, then let it verify/load its core."""
    package = Path(package).absolute()
    # Initial path redirect validation cannot depend on an unverified import.
    import stat
    for path in (package, *package.parents):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "redirected source package")
    directory = package / "windows-portable-v1"
    for path in (directory, directory / "PINS.json", directory / "portable_source.py"):
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "redirected portable dependency")
    require(sha(directory / "PINS.json") == ADAPTER_PINS_SHA, "portable adapter manifest differs")
    raw = (directory / "portable_source.py").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ADAPTER_CODE_SHA, "portable adapter code differs")
    module = ModuleType("_onehand_windows_verified_portable")
    module.__file__ = str(directory / "portable_source.py")
    exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    pins = module.strict_json(directory / "PINS.json")
    for name, expected in pins.items():
        require(Path(name).name == name, "unsafe adapter dependency name")
        module.pinned_file(directory / name, expected)
    return SimpleNamespace(portable=module, core=module.load_core(package))


def bounded_json(deps, path, expected, cap=1024 * 1024):
    path = deps.portable.pinned_file(path, expected)
    return deps.portable.strict_json(path, cap=cap)


def verify_inputs(deps, args):
    p, core = deps.portable, deps.core
    baseline = p.pinned_file(args.baseline, BASE_SHA)
    delta = p.pinned_file(args.delta, DELTA_SHA)
    canonical = p.pinned_file(args.canonical, CANONICAL_SHA)
    require(len({baseline, delta, canonical}) == 3, "input role paths alias")
    recipe = p.strict_json(delta, cap=32 * 1024**2)
    core.native.validate_recipe(recipe)
    require(recipe["producer_sha256"] == core.native.producer_hashes(), "delta producer differs")
    core.delta.probe_times()
    core.delta.pose_corrections()
    return recipe


def verify_reference(deps, args, recipe):
    """Require the complete sealed Linux proof, not a five-pair partial result.

    No approved or historical generated BLEND is read, copied or uploaded here.
    Reference witnesses contain hashes only, validated by the unchanged core.
    """
    p, core = deps.portable, deps.core
    root = p.ordinary_path(args.reference_directory)
    for name, expected in (
        ("replay-receipt.json", args.reference_replay_sha256),
        ("witness-index.json", args.reference_index_sha256),
        ("source-equivalence.json", args.reference_proof_sha256),
    ):
        bounded_json(deps, root / name, expected)
    index = p.strict_json(root / "witness-index.json")
    expected_names = set(p.EVIDENCE_NAMES)
    require(set(index) == expected_names, "all 34 reference witnesses required")
    for name, expected in index.items():
        # Validate each read before the core's own complete validation, rejecting
        # redirected inputs and JSON with duplicate keys/non-finite values.
        bounded_json(deps, root / name, expected, cap=32 * 1024**2)
    evidence = SimpleNamespace(
        delta=p.ordinary_path(args.delta), delta_sha256=DELTA_SHA,
        replay_receipt=root / "replay-receipt.json", replay_receipt_sha256=args.reference_replay_sha256,
        witness_index=root / "witness-index.json", witness_index_sha256=args.reference_index_sha256,
        directory=root, output=root / "source-equivalence.json")
    proof = core.runner.verify_saved_equivalence(evidence)
    require(proof["exact_action_hashes"] == core.runner.expected_action_hashes(recipe),
            "reference Action identity differs")
    require(proof["approved_source_sha256"] == APPROVED_SHA and proof["sample_count"] == 4240
            and proof["chunk_count"] == 17, "complete approved reference required")
    # The label Linux is retained from owner-selected provenance; the proof's
    # schema itself does not attest an OS. Never claim that it does.
    return proof


def admit_authored(deps, args):
    recipe = verify_inputs(deps, args)
    reference = verify_reference(deps, args, recipe)
    target = deps.portable.pinned_file(args.generated_source, args.generated_source_sha256)
    replay = bounded_json(deps, args.target_replay, args.target_replay_sha256)
    generated = deps.core.runner.validate_replay(recipe, replay, DELTA_SHA)
    require(generated == args.generated_source_sha256, "target source/replay identity differs")
    require(target not in (deps.portable.ordinary_path(args.baseline), deps.portable.ordinary_path(args.delta)),
            "target aliases an input")
    require(reference["static_state_sha256"] == deps.core.delta.digest(replay["static_hashes"]),
            "target/reference static state differs")
    # Recheck externally trusted pins after all read-only validation.
    deps.core.runner.verify_pins(deps.core.package / "PINS.json", SOURCE_PINS_SHA)
    verify_inputs(deps, args)
    deps.portable.pinned_file(target, generated)
    deps.portable.pinned_file(args.target_replay, args.target_replay_sha256)
    return {
        "schema": "rust-duty-onehand-authored-input-bridge/v1",
        "authored_input_admitted": True,
        "source_relation": "exact-base-and-original-delta; exact recorded Action/static state",
        "approved_source_sha256": APPROVED_SHA,
        "generated_source_sha256": generated,
        "baseline_sha256": BASE_SHA, "delta_sha256": DELTA_SHA,
        "canonical_sha256": CANONICAL_SHA,
        "source_package_pins_sha256": SOURCE_PINS_SHA,
        "bridge_sha256": sha(Path(__file__)),
        "reference_replay_sha256": args.reference_replay_sha256,
        "reference_witness_index_sha256": args.reference_index_sha256,
        "reference_source_equivalence_sha256": args.reference_proof_sha256,
        "reference_generated_source_sha256": reference["generated_source_sha256"],
        "target_replay_sha256": args.target_replay_sha256,
        "action_hashes": replay["action_hashes"],
        "static_state_sha256": reference["static_state_sha256"],
        "prior_actions_preserved": 88, "result_action_count": 89,
        "original_scalar_corrections": 12, "unchanged_driven_outputs": 4,
        "reference_samples": 4240, "reference_chunk_pairs": 17,
        "source_byte_identity_with_approved": False,
        "target_evaluated_source_equivalence_proved": False,
        "cross_platform_float64_equality_proved": False,
        "windows_execution_proved": False,
        "runtime_equivalence_proved": False, "activation_authorized": False,
        "private_assets_copied_or_uploaded": False,
        "required_next_gate": "Explicit distinct-source runtime contract and actual Windows all-grid/offkey proof",
        "limits": [
            "Admission is conditional on authentic externally pinned native replay/reference evidence.",
            "Receipts do not cryptographically attest the host or prove a native process ran.",
            "Only preservation categories covered by the frozen source producer are asserted.",
            "No cross-platform evaluated numeric equality follows from matching authored data.",
            "Do not substitute this generated source into an approved-source receipt.",
            "No current Linux FBX/VRA equivalence or art acceptance is inferred.",
        ],
    }


def pe_machine(path):
    """Read PE machine metadata without loading/running an executable."""
    with Path(path).open("rb") as stream:
        header = stream.read(64)
        require(len(header) == 64 and header[:2] == b"MZ", "Windows PE executable required")
        offset = struct.unpack_from("<I", header, 60)[0]
        require(64 <= offset <= 16 * 1024**2, "invalid bounded PE header offset")
        stream.seek(offset)
        pe = stream.read(24)
        require(len(pe) == 24 and pe[:4] == b"PE\0\0", "invalid PE signature")
        machine = struct.unpack_from("<H", pe, 4)[0]
        require(machine == 0x8664, "Windows x64 PE required")
    return "x86_64"


def host_snapshot(deps, args):
    """Host observation only. Calling it does not establish Blender/build execution."""
    require(sys.platform == "win32" and platform.system() == "Windows", "actual Windows Python host required")
    require(struct.calcsize("P") == 8, "64-bit Python required")
    python = deps.portable.pinned_file(sys.executable, args.python_sha256)
    blender = deps.portable.pinned_file(args.blender, args.blender_sha256)
    require(python != blender, "tool roles alias")
    return {"schema": "rust-duty-windows-host-observation/v1",
            "system": platform.system(), "release": platform.release(), "version": platform.version(),
            "machine": platform.machine(), "python_version": platform.python_version(),
            "python_sha256": args.python_sha256, "python_machine": pe_machine(python),
            "blender_sha256": args.blender_sha256, "blender_machine": pe_machine(blender),
            "native_execution_proved": False, "build_proved": False,
            "scope": "Observed current Python host and inspected tool bytes; no native tool was run."}


def replay_plan(deps, args):
    """Plan the unchanged native replay without requiring approved raw source.

    This refuses partial output. The Windows supervisor is still a separate
    implementation/review gate, so producing an argv never enables execution.
    """
    recipe = verify_inputs(deps, args)
    verify_reference(deps, args, recipe)
    host = host_snapshot(deps, args)
    p, core = deps.portable, deps.core
    p.cache_free_execution_package(core.package)
    output = p.ordinary_path(args.directory)
    require(not output.exists(), "fresh target output directory required")
    require(output != core.package and output not in core.package.parents,
            "output aliases or contains source package")
    protected = [p.ordinary_path(value) for value in
                 (args.baseline, args.delta, args.canonical, args.reference_directory, args.blender, sys.executable)]
    require(all(output != value and output not in value.parents for value in protected),
            "output aliases or contains protected input")
    ancestor = output.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    require(shutil.disk_usage(ancestor).free >= 1024**3 + 96 * 1024**2,
            "source replay requires 1 GiB floor plus 96 MiB reserve")
    generated, receipt = output / "regenerated-onehand-v6.blend", output / "replay-receipt.json"
    arguments = ["replay", "--base", str(p.ordinary_path(args.baseline)),
                 "--delta", str(p.ordinary_path(args.delta)), "--delta-sha256", DELTA_SHA,
                 "--output", str(generated), "--receipt", str(receipt)]
    return {"schema": "rust-duty-windows-source-replay-plan/v1",
            "native_argv": core.runner.native_command(p.ordinary_path(args.blender), arguments),
            "host_observation": host, "source_package_pins_sha256": SOURCE_PINS_SHA,
            "reference_source_equivalence_sha256": args.reference_proof_sha256,
            "generated_output": str(generated), "replay_receipt": str(receipt),
            "expected_generated_source_sha256": None,
            "timeout_seconds": 1800, "free_floor_bytes": 1024**3,
            "reserved_output_bytes": 96 * 1024**2,
            "launch_enabled": False, "native_execution_performed": False,
            "requires_serialized_owner": True,
            "blocking_interface": "Reviewed Windows owned-process supervisor with durable host/process provenance",
            "approved_raw_source_required": False, "private_assets_uploaded": False}


def inspect_dependencies(root):
    root = Path(root).resolve()
    records = {}
    for relative, expected in MANIFEST_FILES.items():
        path = root / relative
        records[relative] = {"expected_sha256": expected,
                             "actual_sha256": sha(path) if path.is_file() else None}
    require(all(v["actual_sha256"] == v["expected_sha256"] for v in records.values()),
            "inspected dependency manifest changed")
    return {"schema": "rust-duty-windows-proof-dependency-inspection/v1", "manifests": records,
            "native_runs": 0, "windows_execution_proved": False,
            "runtime_candidate_accepted_by_this_adapter": False,
            "approved_fbx_sha256": APPROVED_FBX_SHA, "current_linux_vra_sha256": CURRENT_VRA_SHA,
            "canonical_sha256": CANONICAL_SHA,
            "requires_versioned_portability_revision": True,
            "missing_runtime_interfaces": ["role-bound paths and generated-source identity",
                "Windows-owned process lifetime/RSS/disk/time monitor",
                "bounded Windows pipe reader", "Windows build and backend provenance",
                "new per-host loading/focus/all-grid receipts", "Windows OS-input GL/DX12 capture"]}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="mode", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--workspace", required=True, type=Path)
    admit = commands.add_parser("admit-authored")
    replay = commands.add_parser("replay-plan")
    host = commands.add_parser("host")
    for sub in (admit, replay, host):
        sub.add_argument("--source-package", required=True, type=Path)
    for sub in (admit, replay):
        for name in ("baseline", "delta", "canonical", "reference-directory"):
            sub.add_argument("--" + name, required=True, type=Path)
        for name in ("reference-replay", "reference-index", "reference-proof"):
            sub.add_argument("--" + name + "-sha256", required=True)
    for name in ("generated-source", "target-replay"):
        admit.add_argument("--" + name, required=True, type=Path)
        admit.add_argument("--" + name + "-sha256", required=True)
    replay.add_argument("--directory", required=True, type=Path)
    for sub in (host, replay):
        sub.add_argument("--blender", required=True, type=Path)
        for name in ("python", "blender"):
            sub.add_argument("--" + name + "-sha256", required=True)
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    if args.mode == "inspect":
        result = inspect_dependencies(args.workspace)
    else:
        deps = load_dependencies(args.source_package)
        result = {"host": host_snapshot, "admit-authored": admit_authored,
                  "replay-plan": replay_plan}[args.mode](deps, args)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
