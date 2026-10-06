#!/usr/bin/env python3
"""Fresh, exact-A100 X11 surface/Record smoke and five-case pilot only."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import a100_public_build as b


class Budget:
    """One observed allocation clock. No phase is allowed to restart its budget."""
    def __init__(self, allocation_start, deadline, reserve=90, now=None):
        now = time.time() if now is None else now
        b.require(all(math.isfinite(v) for v in (allocation_start, deadline, reserve, now)), "Invalid allocation clock")
        b.require(allocation_start <= now < deadline and 0 < deadline - allocation_start <= 1800,
                  "Deadline must be within 30 minutes of observed allocation start")
        b.require(90 <= reserve <= 300, "Reserve 90..300 seconds for export and browser disconnect")
        self.deadline, self.reserve = deadline, reserve
        self.monotonic_end = time.monotonic() + deadline - now

    def remaining(self):
        return min(self.deadline - time.time(), self.monotonic_end - time.monotonic()) - self.reserve

    def clock_receipt(self):
        return {"schema": "rust-duty-allocation-clock/v1", "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "monotonic_deadline": self.monotonic_end}

    def require_time(self, needed):
        left = self.remaining()
        b.require(left >= needed, "Insufficient allocation time; preserve/export results and disconnect now")
        return left


def read(path):
    path = Path(path)
    b.require(path.is_file() and not path.is_symlink(), "Missing regular receipt: " + str(path))
    b.require(path.stat().st_size <= 16 * 1024**2, "Receipt exceeds bounds")
    return json.loads(path.read_text())


def verify_fresh(root, expected_sha):
    """All package, source, helper and artifact pins before a graphics operation."""
    root = Path(root).absolute()
    b.require(not root.is_symlink() and not any(p.is_symlink() for p in root.parents), "Linked build root")
    b.pin(expected_sha)
    b.require(b.sha(root / "NEW_EXPECTATIONS.json") == expected_sha, "Fresh expectations SHA differs")
    x = read(root / "NEW_EXPECTATIONS.json")
    b.require(x.get("schema") == "rust-duty-fresh-linux-matrix-inputs/v1" and x.get("source_commit") == b.SOURCE_COMMIT
              and x.get("asset_mode") == "public-release" and x.get("host_kind") == b.A100_NAME
              and x.get("runtime_executed") is False, "Wrong fresh source/asset/host expectations")
    b.require(x.get("matrix_tools") == b.MATRIX_FILES and x.get("preparation_tools") == b.preparation_tool_hashes(),
              "Preparation/matrix tool identities changed")
    b.require(b.tree_manifest(root / "matrix-tools") == {name: {"sha256": digest, "bytes": (root / "matrix-tools" / name).stat().st_size}
              for name, digest in b.MATRIX_FILES.items()}, "Matrix tools differ or contain extra files")
    for key, name in (("package_manifest_sha256", "PACKAGE_FILES.json"), ("build_identity_sha256", "package/BUILD_IDENTITY.json"),
                      ("harness_receipt_sha256", "package/ACTUAL_GAME_HARNESS_RECEIPT.json"), ("executable_sha256", "package/vector-range"),
                      ("preparation_inputs_sha256", "PREPARATION_INPUTS.json"), ("expected_adapter_sha256", "expected-a100.json")):
        b.require(b.sha(root / name) == x.get(key), "Fresh artifact pin differs: " + name)
    b.require(b.tree_manifest(root / "package") == read(root / "PACKAGE_FILES.json"), "Package inventory differs")
    b.require(b.tree_manifest(root / "evidence") == x.get("evidence_files"), "Build evidence inventory differs")
    host = read(root / "PREPARATION_INPUTS.json")
    b.require(host.get("host_kind") == b.A100_NAME and host.get("production_files_preserved") is True
              and host.get("runtime_executed") is False and "cpu_only_preflight" not in host
              and host.get("source_commit") == b.SOURCE_COMMIT and host.get("asset_mode") == "public-release", "Invalid A100 preparation receipt")
    b.require(host["a100_preflight"]["gpus"] == host["a100_postflight"]["gpus"], "Preparation A100 changed")
    b.require(read(root / "expected-a100.json") == {"schema": "rust-duty-graphics-device/v1", "adapter": b.ADAPTER}, "Wrong GL adapter fingerprint")
    source_before = read(root / "evidence/source-before.json")
    source_after = read(root / "evidence/source-after.json")
    source_identity = read(root / "evidence/source-identity.json")
    b.require(len(source_before) == 110 and source_before == source_after == source_identity.get("production_files")
              and source_identity.get("source_commit") == b.SOURCE_COMMIT
              and source_identity.get("production_files_byte_identical_to_commit") is True, "Production source changed")
    assets = read(root / "evidence/authored-assets.json")
    b.require(assets.get("schema") == "rust-duty-public-release-assets/v1" and assets.get("status") == "passed"
              and assets.get("origin") == {"url": b.RELEASE_URL, "sha256": b.RELEASE_SHA, "bytes": b.RELEASE_BYTES}
              and assets.get("new_parity_measured") is False and assets.get("release_executable_used") is False
              and assets.get("freshly_generated") is False and "8 of 12 reload companions differ" in assets.get("comparison_limits", "")
              and set(assets.get("source_contract_bindings", {})) == {"locomotion", "walk", "ads", "directional", "jump", "reload"},
              "Public asset provenance/limits invalid")
    receipt = read(root / "package/ACTUAL_GAME_HARNESS_RECEIPT.json")
    overlay = receipt.get("dependency_overlay", {})
    b.require(receipt.get("schema") == "rust-duty-actual-game-harness/v1" and receipt.get("kind") == "linux_native_gl_actual_game_harness"
              and receipt.get("source_commit") == b.SOURCE_COMMIT and receipt.get("source_sha256") == b.HARNESS_SHA
              and receipt.get("executable_sha256") == x["executable_sha256"] and receipt.get("production_modules_byte_identical") is True
              and receipt.get("authored_assets", {}).get("receipt_sha256") == b.sha(root / "evidence/authored-assets.json")
              and overlay.get("patch_sha256") == b.PATCH_SHA and overlay.get("official_crate_sha256") == b.CRATE_SHA
              and overlay.get("egl_patched_sha256") == b.neutral.EGL_AFTER
              and overlay.get("validation_flags_changed") is False and overlay.get("game_sources_changed") is False,
              "Experimental harness/GL43/source/asset binding differs")
    b.require(overlay == read(root / "evidence/dependency-overlay.json"), "Dependency receipt copies differ")
    # Import only after exact reviewed tool byte verification. Never generate pycache
    # inside the attested matrix-tools inventory.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "matrix-tools"))
    spec = importlib.util.spec_from_file_location("verified_fresh_matrix", root / "matrix-tools/performance_matrix.py")
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)
    source = matrix.artifact_source(root / "source-witness", x["source_witness_sha256"])
    b.require(source["commit"] == b.SOURCE_COMMIT, "Witness source differs")
    b.require(b.sha(root / "source-witness/examples/linux_actual_game_gl.rs") == b.HARNESS_SHA, "Witness harness differs")
    identity = matrix.package_identity(root / "package/vector-range", source, "gl-harness")
    b.require(identity["adjacent_files_digest"] == x["adjacent_files_digest"]
              and identity == read(root / "evidence/matrix-package-identity.json"), "Package/source identity changed")
    for kind, warmup, sample, order in (("smoke", 10, 10, ["baseline"]), ("pilot", 15, 30, ["baseline", "720p", "1440p", "ads", "baseline"])):
        b.require(b.sha(root / (kind + "-plan.json")) == x["plans"][kind], "Fresh plan pin changed; explicit new expectations required")
        plan = read(root / (kind + "-plan.json"))
        matrix.validate_plan(plan)
        b.require(plan["source"] == source and plan["source_origin"] == {"mode": "artifact-witness", "witness_sha256": x["source_witness_sha256"]}
                  and plan["renderer"] == "gl-harness" and plan["warmup_seconds"] == warmup and plan["sample_seconds"] == sample
                  and [row["case_id"] for row in plan["order"]] == order, "Only bounded smoke and five-case pilot accepted")
    return x, host, matrix


def completed_summary(matrix, folder, count):
    summary = matrix.analyze_matrix(folder)  # Recheck frames, CSV/GPU stop, F8, extent, exact observed backend/adapter.
    b.require(summary.get("state") == "complete" and not summary.get("failures") and len(summary.get("runs", [])) == count,
              "Actual surface/Record evidence incomplete; no FPS claim")
    for row in summary["runs"]:
        observed = row["runtime_observed"]
        b.require(observed["actual_backend"] == matrix.BACKENDS["gl-harness"] and observed["actual_adapter"]["actual_fingerprint"] == b.ADAPTER
                  and row["gpu_frame_duration_ns"] is None, "Observed GL/A100 identity or timing scope differs")
    b.require(summary == read(folder / "SUMMARY.json"), "Stored matrix summary differs from fresh analysis")
    return summary


def run(args):
    budget = Budget(args.allocation_start_unix, args.deadline_unix, args.export_reserve_seconds)
    budget.require_time(150)
    root, output = args.build_root.absolute(), args.output.absolute()
    expectations, host, matrix = verify_fresh(root, args.expectations_sha256)
    inventory = b.a100_gate()
    b.require(inventory["gpus"] == host["a100_postflight"]["gpus"], "Runtime GPU differs from build host")
    output.mkdir(exist_ok=False)
    env = b.public_env(output)
    for name in ("config", "tmp"):
        (output / name).mkdir()
    (output / "empty-netrc").write_text("")
    runner = b.Runner(output, env, overall_seconds=budget.require_time(150))
    children, streams = [], []
    smoke_captured = pilot_captured = False
    result = {"status": "running", "host_kind": b.A100_NAME, "expectations_sha256": args.expectations_sha256,
              "actual_surface_record_passed": False, "pilot_passed": False,
              "gpu_frame_duration_available": False, "gpu_shutdown_confirmed": False,
              "gpu_shutdown_required_after_export": True, "deadline_unix": args.deadline_unix}
    b.save(output / "RESULT.json", result)
    def terminate_signal(signum, frame):
        raise InterruptedError("A100 controller signal " + str(signum))
    old_term = signal.signal(signal.SIGTERM, terminate_signal)
    try:
        b.save(output / "a100-inventory.json", inventory)
        runner.run("nvidia-smi-full", ["nvidia-smi"], timeout=20)
        runner.run("lscpu", ["lscpu"], timeout=20)
        linkage = runner.run("ldd", ["ldd", str(root / "package/vector-range")], timeout=20)
        b.require("not found" not in linkage, "Required game shared library unavailable")
        required = ("Xvfb", "openbox", "xdotool")
        if any(shutil.which(name, path=env["PATH"]) is None for name in required):
            b.require(args.install_system_deps, "Missing X11 tools; official distro dependency install flag required")
            budget.require_time(360)
            prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
            runner.run("apt-x11-index", prefix + ["apt-get", "update", "-qq"], timeout=120)
            runner.run("apt-x11-tools", prefix + ["apt-get", "install", "-y", "--no-install-recommends", "xvfb", "openbox", "xdotool", "libxkbcommon0"], timeout=180)
        library = Path("/usr/lib64-nvidia/libEGL_nvidia.so.0")
        b.require(library.is_file(), "Existing NVIDIA EGL missing; no driver installation")
        b.require(not Path("/tmp/.X97-lock").exists() and not Path("/tmp/.X11-unix/X97").exists(), "Display :97 already exists; refuse to control another desktop")
        vendor = output / "nvidia-egl-vendor.json"
        b.save(vendor, {"file_format_version": "1.0.0", "ICD": {"library_path": str(library)}})
        runtime = output / "xdg-runtime"
        runtime.mkdir(mode=0o700)
        env.update(DISPLAY=":97", XDG_RUNTIME_DIR=str(runtime), __EGL_VENDOR_LIBRARY_FILENAMES=str(vendor),
                   LD_LIBRARY_PATH="/usr/lib64-nvidia", WINIT_UNIX_BACKEND="x11", PYTHONDONTWRITEBYTECODE="1")
        budget.require_time(150)
        for command, name in ((["Xvfb", ":97", "-screen", "0", "4096x2304x24", "-nolisten", "tcp", "-noreset"], "xvfb"),
                              (["openbox", "--sm-disable"], "openbox")):
            stream = (output / (name + ".log")).open("x")
            streams.append(stream)
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=env, start_new_session=True)
            children.append((process, {}))
            if name == "xvfb":
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    b.require(process.poll() is None, "Xvfb exited")
                    probe = subprocess.run(["xdotool", "getdisplaygeometry"], env=env, text=True, capture_output=True, timeout=2)
                    if probe.returncode == 0:
                        b.require(probe.stdout.strip() == "4096 2304", "Unexpected X11 extent")
                        (output / "display-geometry.txt").write_text(probe.stdout)
                        break
                    time.sleep(.2)
                else:
                    raise TimeoutError("Xvfb did not become ready")
        def run_plan(kind, seconds, count):
            budget.require_time(seconds)
            b.require(all(process.poll() is None for process, _ in children), "Owned display/window manager exited")
            command = ["/usr/bin/python3.12", "-B", str(root / "matrix-tools/performance_matrix.py"), "run", "--plan", str(root / (kind + "-plan.json")),
                       "--source-witness", str(root / "source-witness"), "--witness-sha256", expectations["source_witness_sha256"],
                       "--executable", str(root / "package/vector-range"), "--settings", str(root / "package/settings.cfg"),
                       "--graphics-settings", str(root / "expected-a100.json"), "--driver", "x11", "--output", str(output / kind),
                       "--lock-file", str(output / "desktop.lock"), "--execute"]
            runner.run(kind, command, timeout=seconds)
            b.save(output / (kind + "-summary.json"), completed_summary(matrix, output / kind, count))
        run_plan("smoke", 150, 1)
        smoke_captured = True
        result["status"] = "passed"
        if not args.smoke_only:
            if budget.remaining() < 480:
                result.update(status="partial", pilot_skip_reason="Insufficient allocation time for five cases plus export/disconnect reserve")
            else:
                run_plan("pilot", 480, 5)
                pilot_captured = True
    except BaseException as error:
        result.update(status="failed", error=type(error).__name__ + ": " + str(error))
        print("A100_ACTUAL_GAME_STOPPED", result["error"], flush=True)
    finally:
        for process, known in reversed(children):
            b.terminate_group(process, known)
        for stream in streams:
            stream.close()
        if smoke_captured:
            try:
                verify_fresh(root, args.expectations_sha256)
                postflight = b.a100_gate()
                b.require(postflight["gpus"] == inventory["gpus"], "GPU changed during runtime")
                b.save(output / "a100-postflight.json", postflight)
                result.update(actual_surface_record_passed=True, pilot_passed=pilot_captured, postflight_passed=True)
                print("A100_ACTUAL_GAME_SURFACE_AND_RECORD_SMOKE_PASSED", flush=True)
            except BaseException as error:
                result.update(status="failed", postflight_passed=False, actual_surface_record_passed=False, pilot_passed=False,
                              postflight_error=type(error).__name__ + ": " + str(error))
        result["remaining_work_seconds"] = budget.remaining()
        b.save(output / "RESULT.json", result)
        signal.signal(signal.SIGTERM, old_term)
    return 0 if result["status"] == "passed" else 1


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-root", type=Path, required=True)
    p.add_argument("--expectations-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--allocation-start-unix", type=float, required=True)
    p.add_argument("--deadline-unix", type=float, required=True)
    p.add_argument("--export-reserve-seconds", type=int, default=90)
    p.add_argument("--install-system-deps", action="store_true")
    p.add_argument("--smoke-only", action="store_true")
    return p


def cli(argv=None):
    try:
        return run(parser().parse_args(argv))
    except BaseException as error:
        print("A100_RUNTIME_ENTRY_STOPPED", type(error).__name__ + ": " + str(error), flush=True)
        return 1
    finally:
        print("EXPORT_RESULTS_AND_DISCONNECT_COLAB_RUNTIME_NOW; GPU shutdown is not confirmed", flush=True)


if __name__ == "__main__":
    raise SystemExit(cli())
