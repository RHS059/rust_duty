"""CPU-only portable source planner/admission. Never launches a subprocess.

The exact reviewed source package is a separately supplied dependency. The
adapter verifies it BEFORE import, and never copies inputs or changes its code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys
from types import ModuleType, SimpleNamespace

sys.dont_write_bytecode = True
PACKAGE_SHA = "3b52a15fe761b9b1ae30b88caab7be132ad635f9aa2d070b6bb2f6d3133fbd71"
DELTA_SHA = "3a6a244d560e3688742e03133ce2d6afe065128ef231e37b3b55339abee582c8"
BASE_SHA = "6b95bdcdfa78e8127ef4b4fa5ac88e4cf9a0654bd0a1271c9916b903f6ee4e79"
APPROVED_SHA = "b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77"
HISTORICAL_GENERATED_SHA = "4362ab61499e463e9d9ecf83ffbeffb40ce6c5662d99d5dc1358918d0d3805d4"
PACKAGE_FILES = {'historical_reference.py', 'project_original.py', 'verify_freeze.py', 'UNCHANGED_MATH.json', 'test_privacy_projection.py', 'test_projected_receipts.py', 'test_unchanged_source_math.py', 'RESULTS.json', 'dense-times.json', 'privacy_projection.py', 'PROJECTION.json', 'onehand_v6_source_delta.py', 'FUNCTION_DIFF.json', 'README.md', 'run_onehand_v6_source_proof.py', 'pose-corrections.json', 'cpu-tests.log', 'onehand_v6_source_native.py'}
EVIDENCE_NAMES = tuple(f"{kind}-{i:03}.json" for i in range(17)
                       for kind in ("approved", "regenerated"))
OUTPUT_NAMES = ("regenerated-onehand-v6.blend", "replay-receipt.json",
                "witness-index.json", "source-equivalence.json", *EVIDENCE_NAMES)
RESERVE_BYTES = 96 * 1024**2
FREE_FLOOR_BYTES = 1024**3


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def strict_json(path, cap=1024**2):
    path = Path(path)
    require(path.stat().st_size <= cap, "JSON exceeds admission bound")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))



def pinned_json(path,expected,cap=1024**2):
    path=ordinary_path(path)
    with path.open('rb') as stream:raw=stream.read(cap+1)
    require(len(raw)<=cap and hashlib.sha256(raw).hexdigest()==expected,'same-buffer pinned JSON differs')
    def unique(items):
        out={}
        for k,v in items:require(k not in out,'duplicate JSON key');out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def ordinary_path(path):
    """Reject redirects in existing path components, including Windows reparse points."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400),
                "symlink/reparse path is not admitted")
    return path.resolve()


def pinned_file(path, expected):
    require(is_sha(expected), "explicit lowercase SHA-256 required")
    path = ordinary_path(path)
    require(path.is_file() and sha(path) == expected, "file bytes differ from pin: " + path.name)
    return path


def load_core(package):
    package = ordinary_path(package)
    manifest = package / "PINS.json"
    pins = pinned_json(manifest, PACKAGE_SHA)
    require(set(pins) == PACKAGE_FILES, "exact projected source package required")
    for name, expected in pins.items():
        pinned_file(package / name, expected)
    # No unverified shadow module may satisfy these imports.
    modules = ("privacy_projection", "onehand_v6_source_delta", "onehand_v6_source_native", "historical_reference", "run_onehand_v6_source_proof")
    for name in modules:
        if name in sys.modules:
            require(Path(sys.modules[name].__file__).resolve() == package / (name + ".py"),
                    "source module already loaded from another package")
    previous_path = list(sys.path)
    previous_modules = {name: sys.modules.get(name) for name in modules}
    loaded = []
    try:
        # dont_write_bytecode alone would still LOAD unpinned cached bytecode.
        # Compile the just-verified source bytes directly, replacing same-path
        # loaded modules rather than trusting mutable in-memory implementations.
        for name in modules:
            source = package / (name + ".py")
            raw = source.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == pins[source.name], "source changed before compilation")
            module = ModuleType(name)
            module.__file__ = str(source)
            module.__package__ = ""
            sys.modules[name] = module
            exec(compile(raw, str(source), "exec", dont_inherit=True), module.__dict__)
            loaded.append(module)
        privacy, d, native, historical, runner = loaded
    except BaseException:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        raise
    finally:
        sys.path[:] = previous_path
    for module in (d, native, runner):
        require(Path(module.__file__).resolve().parent == package, "source import escaped verified package")
    runner.verify_pins(manifest, PACKAGE_SHA)
    return SimpleNamespace(delta=d, native=native, runner=runner, historical=historical, privacy=privacy, package=package, pins=pins)


def context(args):
    raise ValueError("legacy approved/replay paired-witness mode is unavailable for projected source; use the explicit authored bridge and fresh Windows fidelity proof")
    core = load_core(args.source_package)
    d = core.delta
    inputs = {"baseline": pinned_file(args.baseline, BASE_SHA),
              "approved": pinned_file(args.approved, APPROVED_SHA),
              "delta": pinned_file(args.delta, DELTA_SHA)}
    require(len(set(inputs.values())) == 3, "distinct source input paths required")
    recipe = d.load_json(inputs["delta"])
    core.native.validate_recipe(recipe)
    require(recipe["producer_sha256"] == core.native.producer_hashes(), "recipe producer differs from frozen code")
    d.probe_times(); d.pose_corrections()
    root = ordinary_path(args.directory)
    require(root != core.package and root not in core.package.parents,
            "output directory aliases or contains source package")
    protected = [*inputs.values(), *(core.package / n for n in PACKAGE_FILES), core.package / "PINS.json"]
    for name in OUTPUT_NAMES:
        target = ordinary_path(root / name)
        require(target.parent == root and target not in protected, "output aliases protected input/package")
        if target.exists():
            require(target.is_file(), "output path is not a regular file")
            require(all(not target.samefile(p) for p in protected), "output hardlink aliases protected input")
    return SimpleNamespace(core=core, inputs=inputs, recipe=recipe, root=root)


def input_receipt(ctx):
    return {"schema": "rust-duty-onehand-portable-input-admission/v1",
            "adapter_sha256": sha(Path(__file__)),
            "source_package_pins_sha256": PACKAGE_SHA,
            "baseline_sha256": BASE_SHA, "approved_source_sha256": APPROVED_SHA,
            "original_delta_sha256": DELTA_SHA,
            "producer_sha256": ctx.recipe["producer_sha256"],
            "grid_sha256": ctx.core.delta.GRID_SHA,
            "original_scalar_corrections": 12, "unchanged_driver_outputs": 4,
            "private_inputs_copied": False, "native_execution_performed": False,
            "publication_authorized": False}


def cache_free_execution_package(package):
    """The unchanged future runner uses imports; refuse unpinned import candidates."""
    require(not (package / "__pycache__").exists(), "native handoff requires a cache-free source package")
    code_suffixes = (".py", ".pyc", ".pyo", ".pyd", ".so")
    for child in package.iterdir():
        if child.is_file() and child.name.lower().endswith(code_suffixes):
            require(child.name in PACKAGE_FILES, "unexpected importable source-package file")
        if child.is_dir():
            require(not any(p.name.lower().startswith("__init__.") and p.name.lower().endswith(code_suffixes)
                            for p in child.iterdir()),
                    "unexpected importable source-package directory")


def evidence_args(ctx, pins):
    require(set(pins) == {"generated_source_sha256", "replay_receipt_sha256",
                         "witness_index_sha256", "source_equivalence_sha256"}
            and all(is_sha(v) for v in pins.values()), "four explicit output pins required")
    root = ctx.root
    for name, key in (("regenerated-onehand-v6.blend", "generated_source_sha256"),
                      ("replay-receipt.json", "replay_receipt_sha256"),
                      ("witness-index.json", "witness_index_sha256"),
                      ("source-equivalence.json", "source_equivalence_sha256")):
        pinned_file(root / name, pins[key])
    return SimpleNamespace(delta=ctx.inputs["delta"], delta_sha256=DELTA_SHA,
        replay_receipt=root / "replay-receipt.json", replay_receipt_sha256=pins["replay_receipt_sha256"],
        witness_index=root / "witness-index.json", witness_index_sha256=pins["witness_index_sha256"],
        directory=root, output=root / "source-equivalence.json")


def admit_outputs(ctx, pins):
    args = evidence_args(ctx, pins)
    proof = ctx.core.runner.verify_saved_equivalence(args)
    require(proof["generated_source_sha256"] == pins["generated_source_sha256"],
            "actual generated bytes differ from replay/equivalence")
    # Recheck mutable inputs, package, and all externally pinned completion files.
    for role, expected in (("baseline", BASE_SHA), ("approved", APPROVED_SHA), ("delta", DELTA_SHA)):
        pinned_file(ctx.inputs[role], expected)
    ctx.core.runner.verify_pins(ctx.core.package / "PINS.json", PACKAGE_SHA)
    evidence_args(ctx, pins)
    return {"schema": "rust-duty-onehand-portable-source-admission/v1", "passed": True,
            "input_admission": input_receipt(ctx), "output_pins": dict(pins),
            "sample_count": 4240, "chunk_pairs": 17, "witness_files": 34,
            "source_byte_identity_with_approved": False,
            "evaluated_source_equivalence_proved": True,
            "runtime_equivalence_proved": False, "windows_execution_proved": False,
            "proof_scope": "Exact same-producer Action/static state and all 4240 paired sampled evaluations.",
            "execution_provenance_limit": "CPU admission does not establish OS, executable/build identity, or cross-host repeatability.",
            "runtime_handoff": {"converter": "onehand-runtime-20261016-r2/runtime-conversion-v2",
                "converter_source_sha256": APPROVED_SHA, "substitute_regenerated_source": False,
                "runtime_acceptance": "pending independent converter and actual Rust parity evidence"}}


def plan_next(ctx, args):
    """Return explicit argv only. The owner must separately authorize and run it."""
    d, runner, root = ctx.core.delta, ctx.core.runner, ctx.root
    runner.verify_pins(ctx.core.package / "PINS.json", PACKAGE_SHA)
    cache_free_execution_package(ctx.core.package)
    blender = pinned_file(args.blender, args.blender_sha256)
    python = pinned_file(args.python, args.python_sha256)
    require(python == Path(sys.executable).resolve(), "planner must run with the explicitly pinned Python")
    lock = ordinary_path(args.lock)
    require(not lock.exists(), "native owner lock already exists")
    protected = [*ctx.inputs.values(), *(ctx.core.package / n for n in PACKAGE_FILES),
                 ctx.core.package / "PINS.json", blender, python, *(root / n for n in OUTPUT_NAMES)]
    require(lock not in protected and lock != root and lock != ctx.core.package,
            "lock aliases an input or output")
    require(blender not in [root / n for n in OUTPUT_NAMES] and python not in [root / n for n in OUTPUT_NAMES],
            "output aliases a tool executable")
    script = str(ctx.core.package / "run_onehand_v6_source_proof.py")
    base = {"input_admission": input_receipt(ctx), "launch_authorized_by_this_plan": False,
            "native_execution_performed": False,
            "tool_pins": {"blender_sha256": args.blender_sha256, "python_sha256": args.python_sha256},
            "tool_pin_scope": "Checked at planning only; owner must recheck immediately before and after execution.",
            "execution_package_scope": "Cache-free package checked at planning; keep it owner-controlled and recheck before execution.",
            "expected_blender_version": "4.3.2"}
    def command(stage, argv, native=False):
        return {**base, "stage": stage, "argv": argv, "requires_serialized_native_owner": native}
    def native(stage, argv):
        job = ordinary_path(root / (stage + "-job"))
        require(job.parent == root and not job.exists(), "previous native attempt requires owner inspection")
        require(job not in protected and lock != job and job not in lock.parents,
                "native job directory aliases protected path or lock")
        disk_root = root
        while not disk_root.exists():
            disk_root = disk_root.parent
        require(shutil.disk_usage(disk_root).free >= FREE_FLOOR_BYTES + RESERVE_BYTES,
                "source proof requires 1 GiB free floor plus 96 MiB reserve")
        return command(stage, [str(python), "-I", "-B", script, "native", "--blender", str(blender),
            "--lock", str(lock), "--pins", str(ctx.core.package / "PINS.json"),
            "--pins-sha256", PACKAGE_SHA, "--job-directory", str(job),
            "--timeout-seconds", "1800", "--", *argv], True)
    replay_path, generated_path = root / "replay-receipt.json", root / "regenerated-onehand-v6.blend"
    if not replay_path.exists():
        require(not generated_path.exists(), "partial replay requires owner inspection")
        require(not any((root / n).exists() for n in OUTPUT_NAMES if n not in
                        ("regenerated-onehand-v6.blend", "replay-receipt.json")), "orphan proof before replay")
        return native("replay", ["replay", "--base", str(ctx.inputs["baseline"]),
            "--delta", str(ctx.inputs["delta"]), "--delta-sha256", DELTA_SHA,
            "--output", str(generated_path), "--receipt", str(replay_path)])
    replay = d.load_json(replay_path)
    generated_sha = runner.validate_replay(ctx.recipe, replay, DELTA_SHA)
    pinned_file(generated_path, generated_sha)
    for i in range(17):
        for kind in ("approved", "regenerated"):
            target = root / f"{kind}-{i:03}.json"
            if not target.exists():
                require(not (root / "witness-index.json").exists() and not (root / "source-equivalence.json").exists(),
                        "sealed proof has missing witness")
                argv = ["witness", "--source", str(ctx.inputs["approved"] if kind == "approved" else generated_path),
                    "--source-sha256", APPROVED_SHA if kind == "approved" else generated_sha,
                    "--delta", str(ctx.inputs["delta"]), "--delta-sha256", DELTA_SHA,
                    "--kind", kind, "--chunk-index", str(i), "--output", str(target)]
                if kind == "regenerated":
                    argv += ["--replay-receipt", str(replay_path), "--replay-receipt-sha256", sha(replay_path)]
                return native(f"{kind}-{i:03}", argv)
        runner.compare_chunks(d.load_json(root / f"approved-{i:03}.json"),
                              d.load_json(root / f"regenerated-{i:03}.json"), ctx.recipe, replay, i)
    index, proof = root / "witness-index.json", root / "source-equivalence.json"
    if not index.exists():
        require(not proof.exists(), "saved proof without sealed index")
        return command("seal", [str(python), "-I", "-B", script, "seal", "--directory", str(root), "--output", str(index)])
    if not proof.exists():
        return command("compare", [str(python), "-I", "-B", script, "compare", "--directory", str(root),
            "--delta", str(ctx.inputs["delta"]), "--delta-sha256", DELTA_SHA,
            "--replay-receipt", str(replay_path), "--replay-receipt-sha256", sha(replay_path),
            "--witness-index", str(index), "--witness-index-sha256", sha(index), "--output", str(proof)])
    return {**base, "stage": "admission_required", "complete": False,
            "required_external_output_pins": ["generated_source_sha256", "replay_receipt_sha256",
                                              "witness_index_sha256", "source_equivalence_sha256"],
            "next_step": "Use admit with four separately retained expected pins; never infer completion from file presence."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inputs", "plan", "admit"))
    for name in ("source-package", "baseline", "approved", "delta", "directory"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("blender", "python", "lock"):
        parser.add_argument("--" + name, type=Path)
    for name in ("blender", "python", "generated-source", "replay-receipt", "witness-index", "source-equivalence"):
        parser.add_argument("--" + name + "-sha256")
    args = parser.parse_args(argv)
    ctx = context(args)
    if args.mode == "inputs":
        result = input_receipt(ctx)
    elif args.mode == "plan":
        require(all(getattr(args, name) is not None for name in
                    ("blender", "python", "lock", "blender_sha256", "python_sha256")),
                "plan requires explicit Blender/Python/lock paths and tool pins")
        result = plan_next(ctx, args)
    else:
        pins = {key: getattr(args, key) for key in ("generated_source_sha256", "replay_receipt_sha256",
                                                   "witness_index_sha256", "source_equivalence_sha256")}
        result = admit_outputs(ctx, pins)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
