#!/usr/bin/env python3
"""Fail-closed source-only r15 Windows proof orchestration.

ADMISSION_SHA256 binds real source proof inputs and reviewed producer/consumer
code. Preparation/tests run no native
processes. Raw sources, geometry, process logs and runtime packs stay private.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time

BASE_COMMIT = "659fd15ec77a7b4df5018bc7c86a54deace5333e"
BASE_PATH = "assets/authoring/prone_crawl/revisions/entry_r5/halcyon_prone_crawl_r5.blend"
BASE_BLOB = "65e82510e83cfcd2a8e6a27ee849dc5a0f1531b8"
BASE_SHA256 = "67cf025fc31d9804cb0259432a91e496d7d8f84d1d4ac6be2b1914a6a98510ad"
APPROVED_SHA256 = "cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4"
ADMISSION_PATH = "tools/prone_r15_windows_admission.json"
# Set only after real local extraction/replay/equivalence and adapter review.
# No environment variable, CLI override, zero hash or success-shaped fallback.
ADMISSION_SHA256 = '07849c6a97b792654394ca290a7936ef51eafcfc9a449c2e7cf86a3f8619fd9c'
ADAPTER_PATH = "tools/produce_prone_r15_regenerated_runtime.py"
INPUT_DIRECTORY = "assets/authoring/prone_r15_sourceproof/"
SOURCE_INPUTS = ("delta", "approved_witness", "regenerated_witness", "replay_receipt", "source_equivalence")
MINIMUM_CODE_PINS = {
    "tools/prone_r15_source_delta.py", "tools/prone_r15_source_native.py",
    "tools/run_prone_r15_source_proof.py", "tools/prone_r15_delta_transport.py", ADAPTER_PATH,
    "tools/prone_r15_equivalence_contract.json", "tools/prone_r15_regenerated_contract.py",
    "tools/export_prone_r15_regenerated_dense.py", "tools/sample_prone_r15_regenerated_rigid.py",
    "tools/verify_prone_r15_runtime.py",
    "tools/import_fbx_viewmodel.py", "tools/export_viewmodel.py", "tools/prone_camera_pair.py",
    "tools/verify_prone_gameplay_capture.py", "tools/verify_capture_frame_witness.py",
    "tools/verify_render_capture.py", "src/authored_prone.rs",
    "examples/sample_prone_camera.rs", "examples/sample_viewmodel_clip.rs",
}
RATES = {60: 283, 30: 142}
CAPTURE_SUFFIXES = (".png", ".png.json", ".png.prone.json", ".png.gameplay.json", ".png.time.json")
RUNTIME_FILES = ("asset.vra", "asset.vrs", "asset.vrm", "asset.prone-camera.json", "asset.prone-pair.json")
BLENDER_SHA256 = "933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6"
BLENDER_BYTES = 405_138_423
BLENDER_ROOT = "https://download.blender.org/release/Blender4.3/"
BRANCH_PREFIX = "aella/prone-r15-sourceproof-"
INVOCATION_SOURCE = ("tools/run_prone_r15_windows_sourceproof.py",
                     ".github/workflows/prone-r15-windows-sourceproof.yml", "Cargo.toml", "Cargo.lock")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "a real lowercase SHA-256 pin is required")
    return value


def linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def regular(path, limit=256 * 1024 * 1024):
    path = Path(path).absolute()
    require(not any(linked(p) for p in (path, *path.parents)), "linked input/output is forbidden")
    require(path.is_file() and path.stat().st_size <= limit, "required bounded regular file missing or oversized: " + path.name)
    return path


def sha(path, limit=256 * 1024 * 1024):
    with regular(path, limit).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read(path, limit=16 * 1024 * 1024):
    return json.loads(regular(path, limit).read_text(encoding="utf-8"), object_pairs_hook=unique_keys,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def relative(value):
    require(type(value) is str and "\\" not in value and ":" not in value, "unsafe relative path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in ("", ".", "..") for p in value.split("/")), "unsafe relative path")
    return Path(*path.parts)


def pinned(root, item):
    require(type(item) is dict and set(item) == {"path", "sha256"}, "unexpected file pin fields")
    path = root / relative(item["path"])
    require(sha(path) == digest(item["sha256"]), "pinned bytes differ: " + item["path"])
    return path


def delta_bytes(root, item):
    """Reassemble audited transparent shards without publishing a second payload."""
    if set(item) == {"path", "sha256"}:
        return pinned(root, item).read_bytes()
    require(set(item) == {"manifest_path", "manifest_sha256", "sha256"}, "unexpected delta transport fields")
    manifest = pinned(root, {"path": item["manifest_path"], "sha256": item["manifest_sha256"]})
    require(item["manifest_path"].startswith(INPUT_DIRECTORY) and manifest.name == "manifest.json",
            "source delta transport outside reviewed directory")
    from prone_r15_delta_transport import assemble_bytes
    data = assemble_bytes(manifest, item["manifest_sha256"])
    require(hashlib.sha256(data).hexdigest() == digest(item["sha256"]), "reassembled delta identity differs")
    return data


def verify_local_equivalence(root, inputs):
    # Recompute the proof from independently pinned inputs; a passed flag alone
    # is never sufficient. This comparison retains exact float-byte equality.
    from run_prone_r15_source_proof import compare_witnesses
    from prone_r15_source_native import producer_hashes
    documents = {name: read(pinned(root, inputs[name])) for name in SOURCE_INPUTS if name != "delta"}
    documents["delta"] = json.loads(delta_bytes(root, inputs["delta"]), object_pairs_hook=unique_keys)
    recipe = documents["delta"]
    require(recipe["producer_sha256"] == producer_hashes(), "witness producer code differs from actual checkout")
    require(documents["replay_receipt"]["delta_sha256"] == inputs["delta"]["sha256"], "local replay consumed another delta")
    expected = compare_witnesses(documents["approved_witness"], documents["regenerated_witness"],
                                 documents["replay_receipt"], recipe)
    expected["evidence_sha256"] = {name: inputs[name]["sha256"] for name in
                                     ("approved_witness", "regenerated_witness", "replay_receipt", "delta")}
    require(documents["source_equivalence"] == expected, "local source-equivalence receipt differs from recomputation")
    return expected


def preflight(root):
    require(ADMISSION_SHA256 is not None,
            "BLOCKED: real source-only delta/witness, local strict equivalence and regenerated-runtime code are not admitted")
    admission = read(pinned(root, {"path": ADMISSION_PATH, "sha256": ADMISSION_SHA256}))
    require(set(admission) == {"schema", "base_sha256", "approved_source_sha256", "inputs", "code_sha256"}, "unexpected admission fields")
    require(admission["schema"] == "rust-duty-prone-r15-windows-admission/v1" and
            admission["base_sha256"] == BASE_SHA256 and admission["approved_source_sha256"] == APPROVED_SHA256,
            "admission source identities differ")
    require(set(admission["inputs"]) == set(SOURCE_INPUTS), "missing or extra source-only proof inputs")
    for name, item in admission["inputs"].items():
        if name == "delta" and "manifest_path" in item:
            delta_bytes(root, item)
            continue
        require(item["path"].startswith(INPUT_DIRECTORY) and item["path"].endswith(".json"), "proof input is not source-only JSON")
        pinned(root, item)
    require(MINIMUM_CODE_PINS <= set(admission["code_sha256"]), "incomplete producer/consumer code pins")
    require(any(name.startswith("tests/") and name.endswith(".rs") for name in admission["code_sha256"]) and
            any(name.startswith("tools/test_") and name.endswith(".py") for name in admission["code_sha256"]),
            "regenerated consumer rejection tests must also be pinned")
    for name, value in admission["code_sha256"].items():
        pinned(root, {"path": name, "sha256": value})
    verify_local_equivalence(root, admission["inputs"])
    return admission


def verify_base(path):
    data = regular(path, 128 * 1024 * 1024).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    require(hashlib.sha256(data).hexdigest() == BASE_SHA256 and blob == BASE_BLOB, "existing permitted r5 base identity differs")
    return {"commit": BASE_COMMIT, "path": BASE_PATH, "git_blob": blob, "sha256": BASE_SHA256,
            "bytes": len(data), "redistribution_permitted": False}


def verify_blender(receipt, executable):
    expected = {"schema": "rust-duty-prone-r15-blender-toolchain/v1", "version": "4.3.2",
                "vendor_checksum_url": BLENDER_ROOT + "blender-4.3.2.sha256",
                "archive_url": BLENDER_ROOT + "blender-4.3.2-windows-x64.zip",
                "vendor_sha256": BLENDER_SHA256, "archive_sha256": BLENDER_SHA256,
                "archive_bytes": BLENDER_BYTES, "executable_sha256": sha(executable)}
    for key, value in expected.items():
        require(type(receipt.get(key)) is type(value) and receipt[key] == value, "Blender receipt differs: " + key)
    archive = regular(receipt["archive_path"], BLENDER_BYTES)
    require(archive.stat().st_size == BLENDER_BYTES and sha(archive, BLENDER_BYTES) == BLENDER_SHA256, "actual Blender archive differs")
    return expected


def verify_caller(root, env):
    require(env.get("GITHUB_REPOSITORY") == "RHS059/rust_duty", "unexpected repository")
    event = read(Path(env["GITHUB_EVENT_PATH"]))
    if env.get("GITHUB_EVENT_NAME") == "pull_request":
        pr = event["pull_request"]
        require(pr["head"]["repo"]["full_name"] == pr["base"]["repo"]["full_name"] == env["GITHUB_REPOSITORY"], "fork caller not admitted")
        branch = pr["head"]["ref"]
    else:
        require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "unexpected workflow event")
        require(env.get("GITHUB_REF", "").startswith("refs/heads/"), "branch caller required")
        branch = env["GITHUB_REF"][len("refs/heads/"):]
    require(branch.startswith(BRANCH_PREFIX), "dedicated sourceproof branch required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    require(commit == env.get("GITHUB_SHA") and re.fullmatch(r"[0-9a-f]{40}", commit), "checkout/caller identity differs")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        require(re.fullmatch(r"[1-9][0-9]{0,19}", env.get(key, "")), "missing exact run identity")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "src", "tools", "tests", "examples",
                    "Cargo.toml", "Cargo.lock", "assets/animations.cfg", INPUT_DIRECTORY], cwd=root,
                   check=True, stdout=subprocess.DEVNULL)
    return {"commit": commit, "branch": branch, "run_id": env["GITHUB_RUN_ID"], "run_attempt": env["GITHUB_RUN_ATTEMPT"]}


def isolated_manifest(root, runtime, destination):
    text = regular(root / "assets/animations.cfg", 256 * 1024).read_text(encoding="utf-8")
    assets, keys = set(), set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        require("=" in line, "malformed default manifest")
        key, value = [part.strip() for part in line.split("=", 1)]
        require(key not in keys and not key.startswith("prone_entry."), "duplicate/default prone activation")
        keys.add(key)
        if key.endswith(".asset"):
            require(value.endswith(".vra"), "unsupported companion path")
            assets.add(relative(value))
    require(Path("locomotion/asset.vra") in assets and Path("reload/asset.vra") in assets, "missing canonical companions")
    destination.mkdir(exist_ok=False)
    for asset in assets:
        for suffix in (".vra", ".vrs", ".vrm"):
            source = root / "assets" / asset.with_suffix(suffix)
            target = destination / asset.with_suffix(suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(regular(source), target)
    (destination / "prone_entry").mkdir()
    for name in RUNTIME_FILES:
        shutil.copyfile(regular(runtime / name), destination / "prone_entry" / name)
    additions = {"prone_entry.policy": "paired_r15_wip", "prone_entry.asset": "prone_entry/asset.vra",
                 "prone_entry.clip": "aella_prone_crawl_enter_r15_roll_v1",
                 "prone_entry.camera": "prone_entry/asset.prone-camera.json",
                 "prone_entry.receipt": "prone_entry/asset.prone-pair.json"}
    manifest = destination / "animations.cfg"
    manifest.write_text(text + "\n" + "\n".join(k + "=" + v for k, v in additions.items()) + "\n", encoding="utf-8")
    return manifest


def capture_command(executable, manifest, output, hz, identity):
    require(hz in RATES, "unsupported capture rate")
    digest(identity)
    return [str(executable), "--renderer=dx12", "--force-fallback-adapter", "--no-update", "--level=range",
            "--capture", "--capture-native-window", "--capture-sequence=gameplay-prone", f"--capture-hz={hz}",
            f"--animation-manifest={manifest}", f"--capture-frame-witness={identity}", f"--output={output}"]


def verify_capture(folder, hz, identity, receipt):
    # Reuse gameplay checks, never the old Linux run-identity verifier.
    import verify_prone_gameplay_capture as gameplay
    from verify_capture_frame_witness import verify as witness
    from verify_render_capture import verify as render
    expected = {f"{i:04d}{suffix}" for i in range(RATES[hz]) for suffix in CAPTURE_SUFFIXES}
    require({p.name for p in folder.iterdir()} == expected, "capture inventory incomplete or unexpected")
    binding = gameplay.expected_binding(receipt)
    if receipt["schema"] == "rust-duty-prone-camera-pair/v3":
        from prone_camera_pair import validate_r15_equivalence_descriptor
        binding["sidecar_schema"] = "prone-entry-r15-camera-motion/v2"
        binding["source_equivalence"] = validate_r15_equivalence_descriptor(receipt["source_equivalence"], receipt["candidate_sha256"])
    frames, coverage = [], []
    for i in range(RATES[hz]):
        png = regular(folder / f"{i:04d}.png", 16 * 1024 * 1024)
        metadata = read(str(png) + ".json", 32768)
        require(metadata.get("backend") == "Dx12" and metadata.get("requested") == "dx12" and
                metadata.get("adapter") == "Microsoft Basic Render Driver" and metadata.get("capture") == "native window" and
                (metadata.get("width"), metadata.get("height")) == (1440, 900), "not native Windows DX12 WARP window capture")
        witness(png, metadata, i, identity)
        coverage.append(render(png, (1440, 900), (0, 0, 0, 255), .01, 8, None)["foreground_coverage"])
        frame = read(str(png) + ".prone.json", 32768)
        gameplay.validate_frame(frame, i, hz, binding)
        general, timing = read(str(png) + ".gameplay.json", 32768), read(str(png) + ".time.json", 32768)
        require(gameplay.near(general["simulation_time"], frame["simulation_time"]) and
                general["segment"] == frame["segment"] and general["shots"] == frame["shots"] and
                general["grounded"] == frame["grounded"] and gameplay.near(general["eye_height"], frame["eye_height"]) and
                gameplay.close_vector(general["position"], frame["position"]), "general gameplay sidecar differs")
        require(gameplay.near(timing["elapsed_seconds"], i / hz) and timing["sampling_hz"] == hz and
                timing["visual_duration_seconds"] == 4.5 and
                gameplay.near(timing["normalized_phase"], min(1., i / hz / 4.5)), "capture timing differs")
        frames.append(frame)
    return {"hz": hz, **gameplay.validate_sequence(frames, hz), "minimum_foreground_coverage": min(coverage),
            "rendered_frame_witnesses": len(frames)}, frames


def publish_capture(source, destination, hz):
    destination.mkdir(exist_ok=False)
    for i in range(RATES[hz]):
        for suffix in CAPTURE_SUFFIXES:
            name = f"{i:04d}{suffix}"
            shutil.copyfile(regular(source / name, 16 * 1024 * 1024), destination / name)


def evidence_inventory(folder):
    result = {}
    for path in folder.rglob("*"):
        if path.is_dir():
            require(not linked(path), "linked evidence directory")
            continue
        rel = path.relative_to(folder).as_posix()
        require(rel == "summary.json" or re.fullmatch(r"(?:30|60)/[0-9]{4}\.png(?:\.json|\.prone\.json|\.gameplay\.json|\.time\.json)?", rel),
                "unexpected publication artifact")
        if rel != "summary.json":
            result[rel] = sha(regular(path, 16 * 1024 * 1024))
    return result


class Runner:
    def __init__(self, root, work, evidence, report):
        self.root, self.work, self.evidence, self.report = root, work, evidence, report

    def run(self, label, command, timeout=7200):
        require(re.fullmatch(r"[a-z0-9-]+", label), "invalid stage label")
        stage = {"name": label, "completed": False}
        self.report["stages"].append(stage)
        write(self.evidence / "summary.json", self.report)
        log = self.work / (label + ".log")
        started = time.monotonic()
        try:
            with log.open("xb") as stream:
                process = subprocess.run(list(map(str, command)), cwd=self.root, stdout=stream,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout, check=False)
            stage["exit_code"] = process.returncode
            require(process.returncode == 0, label + " failed; private logs retained on runner only")
            stage["completed"] = True
        finally:
            stage["seconds"] = time.monotonic() - started
            stage["private_log_sha256"] = sha(log)
            write(self.evidence / "summary.json", self.report)


def run(args):
    require(sys.platform == "win32", "actual Windows is required; no emulated pass")
    root = args.root.resolve()
    admission = preflight(root)  # No native process before immutable admission.
    caller = verify_caller(root, os.environ)
    work, evidence = args.work.absolute(), args.evidence.absolute()
    require(not work.exists() and not evidence.exists(), "fresh work/evidence directories required")
    require(not work.is_relative_to(root) and not root.is_relative_to(work), "private work must be outside checkout")
    require(not work.is_relative_to(evidence) and not evidence.is_relative_to(work), "private work/evidence overlap")
    require(not any(linked(p) for p in (*work.parents, *evidence.parents)), "linked output parent")
    work.mkdir(parents=True, mode=0o700)
    evidence.mkdir(parents=True)
    report = {"schema": "rust-duty-prone-r15-windows-sourceproof/v1", "passed": False, "caller": caller,
              "stages": [], "default_runtime_activation": False, "windows_dx12_verified": False,
              "source_byte_identity_with_approved": False,
              "limits": ["Strict cross-platform source witness differences are failures, not permission to relax precision.",
                         "30/60 Hz deterministic sampling is not sustained display FPS or arbitrary continuous-time parity.",
                         "Motion retains its original artistic approval only after exact equivalence; no new art score is assigned.",
                         "Only native previews and bounded summary are published by this lane."]}
    runner = Runner(root, work, evidence, report)
    try:
        report["base"] = verify_base(args.base)
        report["blender"] = verify_blender(read(args.blender_receipt), args.blender)
        executable = regular(root / "target/release/vector-range.exe")
        runtime_sampler = regular(root / "target/release/examples/sample_viewmodel_clip.exe")
        camera_sampler = regular(root / "target/release/examples/sample_prone_camera.exe")
        source_inventory = set(admission["code_sha256"]) | set(INVOCATION_SOURCE)
        frozen = {name: sha(root / name) for name in source_inventory}
        frozen.update({"binary": sha(executable), "runtime_sampler": sha(runtime_sampler), "camera_sampler": sha(camera_sampler),
                       "default_manifest": sha(root / "assets/animations.cfg"), "base": sha(args.base)})
        inputs = {name: root / item["path"] for name, item in admission["inputs"].items() if name != "delta"}
        inputs["delta"] = work / "original-delta.json"
        with inputs["delta"].open("xb") as stream:
            stream.write(delta_bytes(root, admission["inputs"]["delta"]))
        candidate, replay, witness, equivalence = [work / name for name in
            ("regenerated.blend", "replay.json", "regenerated-witness.json", "source-equivalence.json")]
        wrapper = [sys.executable, root / "tools/run_prone_r15_source_proof.py"]
        native = wrapper + ["native", "--blender", args.blender, "--lock", work / "native.lock", "--timeout-seconds", "7200"]
        runner.run("replay", native + ["--job-directory", work / "replay-job", "--", "replay", "--base", args.base,
                   "--delta", inputs["delta"], "--delta-sha256", sha(inputs["delta"]), "--output", candidate, "--receipt", replay])
        generated = sha(candidate)
        require(generated not in (BASE_SHA256, APPROVED_SHA256), "regenerated identity aliases an original")
        runner.run("witness", native + ["--job-directory", work / "witness-job", "--", "witness", "--source", candidate,
                   "--source-sha256", generated, "--kind", "regenerated", "--replay-receipt", replay,
                   "--replay-receipt-sha256", sha(replay), "--output", witness])
        compare = wrapper + ["compare", "--output", equivalence]
        for name, path in (("approved-witness", inputs["approved_witness"]), ("regenerated-witness", witness),
                           ("replay-receipt", replay), ("delta", inputs["delta"])):
            compare += ["--" + name, path, "--" + name + "-sha256", sha(path)]
        runner.run("source-equivalence", compare)
        proof = read(equivalence)
        require(proof["passed"] is True and proof["generated_source_sha256"] == generated and
                proof["approved_source_sha256"] == APPROVED_SHA256 and proof["source_byte_identity_with_approved"] is False,
                "Windows source equivalence failed")
        report["source_equivalence"] = {k: proof[k] for k in ("generated_source_sha256", "approved_source_sha256",
            "sample_count", "times_sha256", "exact_complete_actions_proved", "evaluated_pair_equivalence_proved")}
        report["source_equivalence"]["receipt_sha256"] = sha(equivalence)
        runtime = work / "runtime"
        adapter = [sys.executable, root / ADAPTER_PATH, "--root", root, "--source", candidate,
                   "--source-equivalence", equivalence, "--blender", args.blender, "--work", work / "production",
                   "--output", runtime, "--runtime-sampler", runtime_sampler, "--camera-sampler", camera_sampler]
        # Adapter must independently implement/verify dense export, fresh import,
        # actual Rust parity, genuine candidate hashes and regenerated admission.
        runner.run("produce-dense-runtime", adapter + ["produce"])
        runner.run("verify-dense-runtime", adapter + ["verify"])
        receipt = read(runtime / "asset.prone-pair.json", 32768)
        require(receipt["candidate_sha256"] == generated and receipt["asset_vra_sha256"] == sha(runtime / "asset.vra") and
                receipt["camera_sidecar_sha256"] == sha(runtime / "asset.prone-camera.json"), "runtime identifies different source/bytes")
        manifest = isolated_manifest(root, runtime, work / "isolated-assets")
        pack_pins = {p.relative_to(manifest.parent).as_posix(): sha(p) for p in manifest.parent.rglob("*") if p.is_file()}
        identity = hashlib.sha256(json.dumps({"caller": caller, "inputs": frozen, "runtime": pack_pins,
            "source_equivalence": sha(equivalence), "generated_source": generated, "backend": "Dx12"},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        report["capture_identity"] = identity
        report["runtime_sha256"] = {name: sha(runtime / name) for name in RUNTIME_FILES}
        report["rates"] = []
        frames = {}
        for hz in (60, 30):
            folder = work / f"capture-{hz}"
            folder.mkdir()
            runner.run(f"capture-{hz}", capture_command(executable, manifest, folder, hz, identity), timeout=3600)
            stats, frames[hz] = verify_capture(folder, hz, identity, receipt)
            report["rates"].append(stats)
            publish_capture(folder, evidence / str(hz), hz)
        from verify_prone_gameplay_capture import compare_rates
        report["rate_comparison"] = compare_rates(frames[60], frames[30])
        require(pack_pins == {p.relative_to(manifest.parent).as_posix(): sha(p) for p in manifest.parent.rglob("*") if p.is_file()},
                "isolated runtime changed during capture")
        require(frozen == {**{name: sha(root / name) for name in source_inventory}, "binary": sha(executable),
                          "runtime_sampler": sha(runtime_sampler), "camera_sampler": sha(camera_sampler),
                          "default_manifest": sha(root / "assets/animations.cfg"), "base": sha(args.base)}, "proof inputs changed")
        require(sha(candidate) == generated, "candidate changed during conversion/capture")
        preflight(root)
        require(verify_caller(root, os.environ) == caller, "source/caller changed during proof")
        report["evidence_sha256"] = evidence_inventory(evidence)
        report.update(passed=True, windows_dx12_verified=True, inputs_unchanged=True)
    finally:
        # No exception text, local paths or raw process logs are published.
        write(evidence / "summary.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "run"))
    parser.add_argument("--root", type=Path, default=Path("."))
    for name in ("base", "blender", "blender-receipt", "work", "evidence"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "preflight":
            preflight(args.root.resolve())
        else:
            require(all(getattr(args, k) is not None for k in ("base", "blender", "blender_receipt", "work", "evidence")),
                    "run requires base, Blender, receipt, private work and evidence paths")
            run(args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Detailed native logs remain private; this message is bounded orchestration diagnostics.
        print("Prone Windows proof blocked/failed: " + str(error)[:1000], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
