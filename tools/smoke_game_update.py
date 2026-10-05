#!/usr/bin/env python3
"""Exercise the actual game's update entry point against the live GitHub channel.

Disposable root only. The diagnostic CLI seeds an already-installed verified A
baseline; the game itself checks/downloads/applies B through its production
controller and hidden self-helper. No graphical-window interaction is claimed.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from release_update import one_file_executable

from smoke_live_update import (
    check_file, check_manifest, check_sentinels, latest_manifest, require,
    seed_sentinels, sha256, validate_install,
)


def validate_relaunch(outcome, relaunched, expected_version):
    """Helper admission alone is not a successful replacement/relaunch."""
    require(outcome == "Update installed and replacement startup acknowledged",
            f"helper failed: {outcome}")
    require(relaunched["version"] == expected_version and relaunched["status"] == "current"
            and relaunched["exit_code"] == 0,
            "helper did not relaunch and finish the actual B game")


def headless_transfer_budget(mode):
    if mode not in ('full', 'one-file'):
        raise ValueError('unknown baseline mode')
    # Real Windows preflight measured246s for a317MB executable-baseline delta.
    # Use the existing game CLI maximum, without changing its production limit.
    return 600 if mode == 'one-file' else 150


def run(args):
    require(args.target in {"x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu"}, "unsupported target")
    require((os.name == "nt") == args.target.endswith("windows-msvc"), "target must match operating system")
    if os.name != "nt":
        args.launcher.chmod(args.launcher.stat().st_mode | 0o100)
    report = {"kind": "actual_game_entry_live_github_update", "target": args.target,
              "version_a": args.version_a, "version_b": args.version_b,
              "graphical_window": "NOT_EXERCISED; separate native UI smoke required",
              "bootstrap": "retained verified A bundle models an existing updated install",
              "commands": []}
    with tempfile.TemporaryDirectory(prefix="rust-duty-game-update-") as temporary:
        work = Path(temporary)
        root = work / "Game folder with spaces"
        root.mkdir()
        metadata = root / ".rust-duty-updates"
        a = check_manifest(args.manifest_a, args.version_a, args.target)
        b = check_manifest(args.manifest_b, args.version_b, args.target)
        check_file(args.bundle_a, a["bundle"], "published A bundle")
        live = latest_manifest(work, args.version_b, args.target, "before")
        require(live == b, "latest channel differs from requested B")

        def execute(command, timeout=180):
            start = time.monotonic()
            result = subprocess.run([str(x) for x in command], cwd=work,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout)
            report["commands"].append({"arguments": [str(x) for x in command[1:]],
                "exit_code": result.returncode, "elapsed_seconds": time.monotonic()-start,
                "stdout": result.stdout[-12000:], "stderr": result.stderr[-8000:]})
            require(result.returncode == 0, f"command failed: {result.stderr[-2000:]}")
            return result

        mode = getattr(args, 'baseline_mode', 'full')
        seed_metadata = metadata if mode == 'full' else work / 'baseline-extraction'
        execute([args.launcher.resolve(), "--root", seed_metadata, "install-local",
                 args.bundle_a.resolve(), args.version_a, a["entrypoint"]])
        base = seed_metadata / "versions" / f'0-{args.version_a}' / a["entrypoint"]
        game = root / a["entrypoint"]
        shutil.copy2(base, game)
        old_hash = sha256(game)
        baseline_sha = a['bundle']['sha256']
        if mode == 'one-file':
            one_file = work / 'running-executable-baseline.rdb'
            one_file.write_bytes(one_file_executable(a['entrypoint'], game.read_bytes()))
            baseline_sha = sha256(one_file)
            # Seed only this disposable smoke root. The published A bytes
            # stay unchanged; this models a game that retained only its EXE image.
            execute([args.launcher.resolve(), '--root', metadata, 'install-local',
                     one_file, args.version_a, a['entrypoint']])
        report['baseline_mode'] = mode
        report['baseline_sha256'] = baseline_sha
        sentinels = seed_sentinels(root)
        delta = next((d for d in b["deltas"] if d["base_version"] == args.version_a
                     and d["base_sha256"] == baseline_sha), None)
        require(delta is not None, "B has no exact A delta")
        transfer_budget = headless_transfer_budget(mode)
        report['headless_transfer_budget_seconds'] = transfer_budget
        first = execute([game, "--update-headless", "--update-apply",
                         f"--update-timeout-seconds={transfer_budget}"], timeout=transfer_budget + 30)
        first_lines = [json.loads(line) for line in first.stdout.splitlines() if line.startswith("{")]
        require(any(x.get("helper_admitted") for x in first_lines), "game did not admit its hidden helper")
        until = time.monotonic() + 100
        result_files = []
        while time.monotonic() < until:
            result_files = list((metadata / "jobs").glob("*/result.json"))
            if result_files:
                break
            time.sleep(.1)
        require(len(result_files) == 1, "replacement helper did not finish exactly once")
        outcome = json.loads(result_files[0].read_text())
        relaunched = json.loads((metadata / "headless-result.json").read_text())
        validate_relaunch(outcome, relaunched, args.version_b)
        report["helper_relaunch_proof"] = relaunched
        installed = validate_install(metadata, b)
        staged_game = metadata / "versions" / f'{b["sequence"]}-{args.version_b}' / b["entrypoint"]
        require(sha256(game) == sha256(staged_game) != old_hash, "normal game EXE was not replaced with B")
        check_sentinels(root, sentinels)
        check_file(metadata / "cache" / f'{delta["asset"]["sha256"]}.ready', delta["asset"], "actual downloaded delta")
        require(not (metadata / "cache" / f'{b["bundle"]["sha256"]}.ready').exists(), "unexpected full B download")
        # The same user-facing path now reports B, with no launcher involved.
        second = execute([game, "--update-headless", "--update-timeout-seconds=90"], timeout=110)
        second_lines = [json.loads(line) for line in second.stdout.splitlines() if line.startswith("{")]
        require(second_lines and all(x.get("running_version") == args.version_b for x in second_lines),
                "updated game did not report B from the same normal EXE path")
        require(any("is current" in x.get("message", "") for x in second_lines), "B did not settle as current")
        require(latest_manifest(work, args.version_b, args.target, "after") == b,
                "channel changed during smoke")
        check_sentinels(root, sentinels)
        report.update({"passed": True, "helper_result": outcome, "same_game_path": True,
            "delta_bytes": delta["asset"]["size"], "full_bytes": b["bundle"]["size"],
            "private_data_unchanged": True, "version_after": installed["active"]["version"],
            "pause_resume_cancel": "covered by controller tests; not timed in this short live transfer"})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "commands"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["launcher", "bundle-a", "manifest-a", "manifest-b", "report"]:
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ["version-a", "version-b", "target"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--baseline-mode", choices=("full", "one-file"), default="full")
    run(parser.parse_args())
