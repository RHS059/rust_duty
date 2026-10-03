#!/usr/bin/env python3
"""Prove a real native full-download upgrade from an existing complete game.

Only a disposable install is modified. No graphical or gameplay claim is made.
The original binary drives the production update controller and hidden helper;
this script never installs, replaces, or edits updater state on its behalf.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from release_update import REPOSITORY, safe_path, stable_version
from smoke_game_update import validate_relaunch
from smoke_live_update import (
    GitHubRedirects, check_file, check_sentinels, latest_manifest,
    load_state, require, seed_sentinels, sha256,
)

TARGETS = {"x86_64-pc-windows-msvc": "windows", "x86_64-unknown-linux-gnu": "linux"}
REQUIRED_ASSETS = ["assets/animations.cfg"] + [
    f"assets/{kind}/{name}" for kind in ("reload", "walk", "ads", "directional", "locomotion")
    for name in ("asset.vra", "asset.vrs", "asset.vrm")
]


def bundle_records(bundle):
    """Independently hash every exact file from the authenticated RDBND001 bytes."""
    records, folded = {}, set()
    with bundle.open("rb") as stream:
        def read(size):
            data = stream.read(size)
            require(len(data) == size, "truncated expected bundle")
            return data
        require(read(8) == b"RDBND001", "wrong bundle magic")
        count, = struct.unpack("<I", read(4))
        require(0 < count <= 50000, "invalid bundle count")
        for _ in range(count):
            length, = struct.unpack("<H", read(2))
            require(0 < length <= 240, "invalid bundle path length")
            name = read(length).decode("ascii")
            safe_path(name)
            require(name.lower() not in folded, "duplicate bundle path")
            folded.add(name.lower())
            mode = read(1)[0]
            require(mode in (0, 1), "unsupported bundle mode")
            size, = struct.unpack("<Q", read(8))
            require(size <= bundle.stat().st_size, "invalid bundle size")
            digest, remaining = hashlib.sha256(), size
            while remaining:
                chunk = read(min(remaining, 1024 * 1024))
                digest.update(chunk)
                remaining -= len(chunk)
            records[name] = {"size": size, "sha256": digest.hexdigest()}
        require(not stream.read(1), "trailing bundle data")
    return records


def verify_version_root(metadata, manifest):
    state = load_state(metadata)
    active = state["active"]
    for key in ("version", "sequence", "entrypoint"):
        require(active[key] == manifest[key], f"installed {key} mismatch")
    require(active["bundle_sha256"] == manifest["bundle"]["sha256"], "installed bundle mismatch")
    require(state["highest_sequence"] == manifest["sequence"], "highest sequence mismatch")
    require(state["pending_launch"] is False, "replacement still pending")
    directory = metadata / "versions" / f'{manifest["sequence"]}-{manifest["version"]}'
    payload = directory / "payload.rdb"
    check_file(payload, manifest["bundle"], "installed authenticated full bundle")
    records = bundle_records(payload)
    require(manifest["entrypoint"] in records, "bundle lacks game")
    for relative in REQUIRED_ASSETS:
        require(relative in records, f"complete bundle lacks {relative}")
    for relative, expected in records.items():
        path = directory / relative
        require(directory.resolve() in path.resolve().parents, "bundle path escapes version root")
        check_file(path, expected, f"managed file {relative}")
    require(not (directory / "private-assets").exists(), "private assets in version root")
    return directory, records, state


def download_small_release_json(version, name):
    url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/{name}"
    request = Request(url, headers={"User-Agent": "RustDutyCompleteUpgradeSmoke/1.0"})
    with build_opener(GitHubRedirects()).open(request, timeout=30) as response:
        data = response.read(1024 * 1024 + 1)
    require(len(data) <= 1024 * 1024, "oversized release evidence")
    return json.loads(data)


def wait_for_release(args, work, report):
    deadline, attempts = time.monotonic() + args.wait_seconds, 0
    while True:
        attempts += 1
        try:
            manifest = latest_manifest(work, None, args.target, "waiting")
            observed = manifest["version"]
            report["latest_observed_version"] = observed
            if observed == args.version_b:
                require(manifest["sequence"] == args.sequence, "wrong requested release sequence")
                report["release_poll_attempts"] = attempts
                return manifest
            require(stable_version(observed) < stable_version(args.version_b),
                    "latest channel advanced beyond the specifically requested release")
            message = f"latest is {observed}; awaiting {args.version_b}"
        except (HTTPError, URLError, TimeoutError) as error:
            message = f"release request pending: {error}"
        require(time.monotonic() < deadline, f"requested release did not arrive: {message}")
        print(message, flush=True)
        time.sleep(min(30, max(0, deadline - time.monotonic())))


def smoke(args, report):
    require(args.target in TARGETS, "unsupported target")
    require((os.name == "nt") == (TARGETS[args.target] == "windows"), "native target mismatch")
    require(0 <= args.wait_seconds <= 2400, "release wait must be bounded to 40 minutes")
    game_name = "vector-range.exe" if os.name == "nt" else "vector-range"
    require((args.baseline / game_name).is_file(), "baseline executable missing")
    for path in args.baseline.rglob("*"):
        require(not path.is_symlink(), "symlink in baseline artifact")
    require(not (args.baseline / ".rust-duty-updates").exists(), "baseline has updater state")
    work = Path(tempfile.mkdtemp(prefix="rust-duty-native-upgrade-"))
    report["temporary_root"] = str(work)
    try:
        manifest = wait_for_release(args, work, report)
        require(manifest["entrypoint"] == game_name, "unexpected manifest entrypoint")
        report["expected_manifest"] = manifest
        provenance = download_small_release_json(args.version_b, "SOURCE_PROVENANCE.json")
        require(provenance["source"]["commit"] == args.expected_commit, "unexpected release source commit")
        require(provenance["version"] == args.version_b and provenance["sequence"] == args.sequence,
                "release provenance identity mismatch")
        expected_exe = provenance["artifacts"][TARGETS[args.target]]["identity"]["executable"]
        require(expected_exe["name"] == game_name, "provenance executable name mismatch")
        require(provenance["assets"][manifest["bundle"]["name"]] == manifest["bundle"],
                "provenance does not match expected bundle")
        report["release_source"] = provenance["source"]
        root = work / "Game folder with spaces"
        shutil.copytree(args.baseline, root)
        game, metadata = root / game_name, root / ".rust-duty-updates"
        if os.name != "nt":
            game.chmod(game.stat().st_mode | 0o100)
        old_hash = sha256(game)
        sentinels = seed_sentinels(root)
        before = {p.relative_to(root).as_posix(): sha256(p)
                  for p in root.rglob("*") if p.is_file() and p != game}

        def execute(arguments, timeout=120):
            start = time.monotonic()
            result = subprocess.run([str(game), *arguments], cwd=work,
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout)
            report["commands"].append({"arguments": arguments, "exit_code": result.returncode,
                "elapsed_seconds": round(time.monotonic()-start, 3),
                "stdout": result.stdout[-16000:], "stderr": result.stderr[-8000:]})
            require(result.returncode == 0, f"native command failed: {result.stderr[-2000:]}")
            return result

        first = execute(["--update-headless", "--update-apply", "--update-timeout-seconds=600"], 630)
        lines = [json.loads(line) for line in first.stdout.splitlines() if line.startswith("{")]
        require(lines and all(x.get("running_version") == args.version_a for x in lines),
                "baseline executable did not identify as requested old version")
        require(any(x.get("helper_admitted") is True for x in lines), "hidden helper was not admitted")
        deadline = time.monotonic() + 180
        outcome, relaunched = None, None
        while time.monotonic() < deadline:
            results = list((metadata / "jobs").glob("*/result.json"))
            require(len(results) <= 1, "multiple hidden helper attempts")
            if results:
                outcome = json.loads(results[0].read_text(encoding="utf-8"))
                require(outcome == "Update installed and replacement startup acknowledged",
                        f"replacement helper failed: {outcome}")
                proof = metadata / "headless-result.json"
                if proof.exists():
                    relaunched = json.loads(proof.read_text(encoding="utf-8"))
                    if relaunched.get("version") == args.version_b and relaunched.get("status") == "current":
                        break
                    if relaunched.get("status") == "error":
                        raise ValueError(f"replacement headless check failed: {relaunched}")
            time.sleep(.2)
        require(relaunched is not None, "replacement did not finish")
        validate_relaunch(outcome, relaunched, args.version_b)
        report["helper_result"], report["replacement_proof"] = outcome, relaunched
        directory, records, state = verify_version_root(metadata, manifest)
        new_hash = sha256(game)
        require(new_hash == sha256(directory / game_name) != old_hash, "same-path executable not replaced")
        check_file(game, expected_exe, "same-path published executable")
        require(relaunched["sha256"] == new_hash, "replacement proof executable hash mismatch")
        require(Path(relaunched["executable"]).samefile(game), "helper relaunched a different executable")
        check_file(metadata / "cache" / f'{manifest["bundle"]["sha256"]}.ready',
                   manifest["bundle"], "actual full download cache")
        require(execute(["--build-version"]).stdout.strip() == args.version_b, "wrong embedded new version")
        selected = Path(execute(["--verify-managed-assets"]).stdout.strip())
        require(selected.samefile(directory / game_name), "game selected stale adjacent assets")
        second = execute(["--update-headless", "--update-timeout-seconds=90"])
        current = [json.loads(line) for line in second.stdout.splitlines() if line.startswith("{")]
        require(current and all(x.get("running_version") == args.version_b for x in current),
                "second same-path launch did not report new version")
        require(any("is current" in x.get("message", "") for x in current), "new game is not current")
        require(latest_manifest(work, args.version_b, args.target, "after") == manifest,
                "latest channel changed during proof")
        check_sentinels(root, sentinels)
        for relative, digest in before.items():
            require(sha256(root / relative) == digest, f"existing user/root file changed: {relative}")
        report.update(same_game_path=True, old_executable_sha256=old_hash,
            new_executable_sha256=new_hash, version_after=state["active"]["version"],
            full_bundle_bytes=manifest["bundle"]["size"], managed_asset_executable=str(selected),
            managed_bundle_file_count=len(records), verified_managed_assets=REQUIRED_ASSETS,
            root_files_unchanged=len(before), private_data_unchanged=True)
    finally:
        try:
            shutil.rmtree(work)
        except OSError as error:
            report["cleanup_warning"] = str(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--version-a", default="0.1.4")
    parser.add_argument("--version-b", default="0.1.5")
    parser.add_argument("--sequence", type=int, default=5)
    parser.add_argument("--wait-seconds", type=int, default=2400)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    report = dict(schema=1, status="running", kind="native_complete_game_live_full_upgrade",
        target=args.target, version_a=args.version_a, version_b=args.version_b, commands=[],
        graphical_window="NOT_EXERCISED; headless production updater only",
        baseline_run="https://github.com/RHS059/rust_duty/actions/runs/37151455895")
    try:
        smoke(args, report)
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
