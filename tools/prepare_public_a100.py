#!/usr/bin/env python3
"""Explicit future A100 task: public fresh build, bounded surface smoke/pilot, compact export.

Requires a separately authorized allocated A100 and observed allocation timestamps.
--dry-run and --self-check perform no setup, GPU query, graphics, or network work.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import sys
import tempfile
import time
import tarfile

import a100_public_build as b
from run_public_a100_matrix import Budget


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs-root", type=Path, default=Path("/content/rust-duty-public-a100-runs"))
    p.add_argument("--support-commit")
    p.add_argument("--allocation-start-unix", type=float)
    p.add_argument("--deadline-unix", type=float)
    p.add_argument("--export-reserve-seconds", type=int, default=90)
    p.add_argument("--install-system-deps", action="store_true")
    p.add_argument("--smoke-only", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--self-check", action="store_true")
    p.add_argument("--build-worker", type=Path, help=argparse.SUPPRESS)
    return p


def worker(args, budget):
    b.require(args.build_worker.is_dir() and not any(args.build_worker.iterdir()), "Worker needs fresh empty build directory")
    inventory = b.a100_gate()
    args.asset_mode, args.asset_helper_sha256, args.archive = "public-release", None, False
    args.work_seconds = budget.require_time(1)
    result = {"status": "running", "host_kind": b.A100_NAME, "runtime_executed": False}
    try:
        result.update(b.prepare_a100(args, args.build_worker, inventory))
    except BaseException as error:
        result.update(status="failed", error=type(error).__name__ + ": " + str(error))
    b.save(args.build_worker / "BUILD_RESULT.json", result)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "prepared" else 1


def merge_runtime_result(result, path):
    """A damaged subordinate receipt must never suppress export or shutdown notice."""
    try:
        if path.is_file():
            runtime = json.loads(path.read_text())
            b.require(isinstance(runtime, dict), "Runtime result must be an object")
            result["surface_and_record_proven"] = runtime.get("actual_surface_record_passed") is True
            result["pilot_proven"] = runtime.get("pilot_passed") is True
            if runtime.get("status") == "partial" and result["surface_and_record_proven"]:
                result["status"] = "partial"
                result["pilot_skip_reason"] = runtime.get("pilot_skip_reason")
    except (OSError, ValueError, TypeError) as error:
        result.update(status="failed", surface_and_record_proven=False, pilot_proven=False,
                      runtime_receipt_error=type(error).__name__ + ": " + str(error))


EVIDENCE_MEMBERS = (
    "RESULT.json", "PHASES.json", "ALLOCATION_HOST.json", "logs", "runtime",
    "build/BUILD_RESULT.json", "build/PREPARATION_INPUTS.json", "build/NEW_EXPECTATIONS.json", "build/PACKAGE_FILES.json",
    "build/PHASES.json", "build/evidence", "build/logs", "build/source-witness", "build/matrix-tools",
    "build/smoke-plan.json", "build/pilot-plan.json", "build/expected-a100.json",
    "build/package/BUILD_IDENTITY.json", "build/package/ACTUAL_GAME_HARNESS_RECEIPT.json",
)


def export_evidence(root):
    """Keep every raw runtime output; never bundle the executable or raw assets."""
    root = Path(root)
    members = [name for name in EVIDENCE_MEMBERS if (root / name).exists()]
    target = root / "a100-evidence-only.tar.gz"
    b.require(not target.exists() and not target.is_symlink(), "Evidence archive already exists; preserve its verified bytes")
    try:
        receipt = b.make_archive(root, members, target)
        # Inventory the actual verified archive, including unsuccessful/partial captures.
        with tarfile.open(target, "r:gz") as archive:
            inventory = {item.name: {"bytes": item.size, "sha256": hashlib.file_digest(archive.extractfile(item), "sha256").hexdigest()} for item in archive}
        b.require(not any(name == "build/package/vector-range" or name.startswith("build/package/assets/") for name in inventory),
                  "Evidence-only archive contains excluded payload")
        runtime_files = {"runtime/" + name for name in b.tree_manifest(root / "runtime")} if (root / "runtime").exists() else set()
        b.require(runtime_files <= set(inventory), "Raw runtime evidence omitted from archive")
        receipt.update(schema="rust-duty-evidence-export/v1", kind="evidence-only", includes_executable=False,
                       includes_raw_assets=False, archived_files=inventory, raw_runtime_files=len(runtime_files),
                       result_snapshot="Archived RESULT.json predates export verification; final RESULT.json and EVIDENCE_EXPORT_RECEIPT.json are separate authoritative files",
                       capture_scope="All retained raw frames, CSV, GPU, status, identity, driver and validation files; failures retained")
        b.save(root / "EVIDENCE_EXPORT_RECEIPT.json", receipt)
        return receipt
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def export_executable(root):
    """Optional separately bound executable artifact; never a prerequisite for shutdown."""
    root = Path(root)
    target = root / "a100-executable-optional.tar.gz"
    b.require(not target.exists() and not target.is_symlink(), "Executable archive already exists; preserve its verified bytes")
    try:
        receipt = b.make_archive(root, ["build/package/vector-range", "build/package/BUILD_IDENTITY.json",
                                      "build/package/ACTUAL_GAME_HARNESS_RECEIPT.json"], target)
        receipt.update(schema="rust-duty-executable-export/v1", kind="optional-executable", includes_raw_assets=False)
        b.save(root / "EXECUTABLE_EXPORT_RECEIPT.json", receipt)
        return receipt
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def main(argv=None):
    args = parser().parse_args(argv)
    if args.dry_run or args.self_check:
        print(json.dumps({"status": "self-check-passed" if args.self_check else "dry-run",
                          "source_commit": b.SOURCE_COMMIT, "asset_mode": "public-release", "host_kind": b.A100_NAME,
                          "gpu_query_performed": False, "runtime_executed": False, "python": "/usr/bin/python3.12",
                          "allocation_budget_seconds_maximum": 1800, "export_disconnect_reserve_seconds_minimum": 90,
                          "observed_cpu_preparation_seconds": 870.439,
                          "measurement_limit": "CPU retry reused system dependencies; not a pristine cold-start measurement",
                          "cold_build_plus_pilot_fits_budget": "Unproven; 30-minute admission uses observed allocation time, not a cold-build guarantee",
                          "phases": ["fresh public build", "10+10 smoke", "15+30 five-case pilot if budget allows", "evidence-only export; executable optional", "browser disconnect required"],
                          "frozen_cpu_helpers_sha256": b.CPU_HELPERS_SHA, "tool_hashes": b.preparation_tool_hashes()}, indent=2))
        return 0
    b.require(args.execute, "This separately reviewed A100 task requires --execute")
    b.pin(args.support_commit, 40)
    b.require(args.allocation_start_unix is not None and args.deadline_unix is not None, "Supply observed allocation start and absolute deadline")
    budget = Budget(args.allocation_start_unix, args.deadline_unix, args.export_reserve_seconds)
    b.require(sys.version_info[:2] == (3, 12) and Path(sys.executable).resolve() == Path("/usr/bin/python3.12").resolve()
              and platform.system() == "Linux" and platform.machine() == "x86_64", "Invoke using verified distro /usr/bin/python3.12")
    if args.build_worker is not None:
        return worker(args, budget)
    inventory = b.a100_gate()  # Before any filesystem/setup work, independently of CPU-only frontend.
    parent = args.runs_root.absolute()
    b.require(not parent.is_symlink() and not any(p.is_symlink() for p in parent.parents), "Linked run root rejected")
    budget.require_time(150)
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="run-", dir=parent)).resolve()
    print("A100_RUN_ROOT", str(root), flush=True)
    env = b.public_env(root)
    for name in ("config", "tmp", "build"):
        (root / name).mkdir()
    (root / "empty-netrc").write_text("")
    runner = b.Runner(root, env, overall_seconds=budget.require_time(1))
    result = {"status": "running", "host_kind": b.A100_NAME, "allocation_start_unix": args.allocation_start_unix,
              "deadline_unix": args.deadline_unix, "allocation_clock": budget.clock_receipt(), "run_root": str(root), "gpu_shutdown_confirmed": False,
              "gpu_shutdown_required_after_export": True, "surface_and_record_proven": False, "pilot_proven": False,
              "asset_comparison_limits": "Public v0.1.9 assets; 8 of 12 reload companions differ from frozen fixture; no fresh parity claim"}
    b.save(root / "RESULT.json", result)
    b.save(root / "ALLOCATION_HOST.json", inventory)
    def interrupted(signum, frame):
        raise InterruptedError("A100 public task signal " + str(signum))
    old_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        clock_args = ["--allocation-start-unix", str(args.allocation_start_unix), "--deadline-unix", str(args.deadline_unix),
                      "--export-reserve-seconds", str(args.export_reserve_seconds)]
        command = ["/usr/bin/python3.12", "-B", str(Path(__file__).resolve()), "--build-worker", str(root / "build"),
                   "--support-commit", args.support_commit, "--execute", *clock_args]
        if args.install_system_deps:
            command.append("--install-system-deps")
        runner.run("fresh-public-build", command, timeout=budget.require_time(1))
        expectations_sha = b.sha(root / "build/NEW_EXPECTATIONS.json")
        result["new_expectations_sha256"] = expectations_sha
        b.save(root / "RESULT.json", result)
        command = ["/usr/bin/python3.12", "-B", str(Path(__file__).with_name("run_public_a100_matrix.py")),
                   "--build-root", str(root / "build"), "--expectations-sha256", expectations_sha,
                   "--output", str(root / "runtime"), *clock_args]
        if args.install_system_deps:
            command.append("--install-system-deps")
        if args.smoke_only:
            command.append("--smoke-only")
        runner.run("surface-smoke-pilot", command, timeout=budget.require_time(150))
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=type(error).__name__ + ": " + str(error))
    finally:
        runtime_receipt = root / "runtime/RESULT.json"
        merge_runtime_result(result, runtime_receipt)
        result["remaining_seconds_at_export"] = args.deadline_unix - time.time()
        result["export_status"] = "pending"
        b.save(root / "RESULT.json", result)
        def export_timeout(signum, frame):
            raise TimeoutError("Export deadline reached; preserve available evidence and disconnect now")
        old_alarm = signal.signal(signal.SIGALRM, export_timeout)
        try:
            remaining = budget.monotonic_end - time.monotonic()
            b.require(remaining > 45, "No safe export time remains; preserve loose receipts and disconnect now")
            signal.setitimer(signal.ITIMER_REAL, min(45, remaining - 45))
            receipt = export_evidence(root)
            result["export_status"] = "verified"
            result["export"] = receipt
            result["executable_export"] = {"status": "not_requested"}
        except BaseException as error:
            result.update(export_status="failed", export_error=type(error).__name__ + ": " + str(error))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_alarm)
        b.save(root / "RESULT.json", result)
        signal.signal(signal.SIGTERM, old_term)
        print("A100_PUBLIC_FINAL_RESULT", json.dumps(result), flush=True)
    return 0 if result["status"] == "passed" and result["export_status"] == "verified" else 1


def cli(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        return main(argv)
    except BaseException as error:
        print("A100_PUBLIC_ENTRY_STOPPED", type(error).__name__ + ": " + str(error), flush=True)
        return 1
    finally:
        if "--execute" in argv and not any(flag in argv for flag in ("--dry-run", "--self-check", "--build-worker")):
            print("SAVE_EVIDENCE_ONLY_EXPORT_OR_BOUNDED_NOTEBOOK_TEXT_THEN_DISCONNECT_AND_DELETE_COLAB_RUNTIME_NOW; this script cannot confirm GPU shutdown", flush=True)


if __name__ == "__main__":
    raise SystemExit(cli())
