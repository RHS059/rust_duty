#!/usr/bin/env python3
"""Verify a published A -> B update using the real fixed GitHub production channel.

Only disposable installs and synthetic private-data sentinels are used. This tool
does not publish releases, start the graphical game, or touch an existing install.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from release_update import REPOSITORY, verify_manifest


TARGETS = {"x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu"}
MAX_MANIFEST = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def allowed_redirect(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
            return False
        return (
            parsed.hostname == "github.com"
            and parsed.path.startswith(f"/{REPOSITORY}/releases/")
        ) or parsed.hostname in {
            "release-assets.githubusercontent.com", "objects.githubusercontent.com"
        }
    except ValueError:
        return False


class GitHubRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        count = getattr(request, "rust_duty_redirects", 0) + 1
        require(count <= 5 and allowed_redirect(new_url), "redirect outside the fixed GitHub release origin/CDN")
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if redirected is not None:
            redirected.rust_duty_redirects = count
        return redirected


def check_manifest(path, version, target):
    return verify_manifest(argparse.Namespace(
        manifest=path, assets_dir=None, bundle_only=True, version=version, target=target
    ))


def latest_manifest(workspace, version, target, suffix):
    url = f"https://github.com/{REPOSITORY}/releases/latest/download/update-{target}.json"
    request = Request(url, headers={
        "User-Agent": "RustDutyLiveUpdateSmoke/1.0", "Accept-Encoding": "identity"
    })
    with build_opener(GitHubRedirects()).open(request, timeout=30) as response:
        require(response.status == 200, f"manifest HTTP {response.status}")
        encoded = response.read(MAX_MANIFEST + 1)
    require(len(encoded) <= MAX_MANIFEST, "oversized live manifest")
    path = workspace / f"live-manifest-{suffix}.json"
    path.write_bytes(encoded)
    return check_manifest(path, version, target)


def check_file(path, expected, label):
    require(path.is_file() and not path.is_symlink(), f"{label} is not a regular file: {path}")
    require(path.stat().st_size == expected["size"], f"{label} size mismatch")
    require(sha256(path) == expected["sha256"], f"{label} SHA-256 mismatch")


def load_state(root):
    return json.loads((root / "install.json").read_text(encoding="utf-8"))


def validate_install(root, manifest):
    state = load_state(root)
    active = state["active"]
    require(active["version"] == manifest["version"], "activated version differs from expected B (the channel may have moved)")
    require(active["sequence"] == manifest["sequence"], "activated sequence mismatch")
    require(state["highest_sequence"] == manifest["sequence"], "highest sequence mismatch")
    require(active["bundle_sha256"] == manifest["bundle"]["sha256"], "installed bundle identity mismatch")
    require(active["entrypoint"] == manifest["entrypoint"], "installed entrypoint mismatch")
    require(state["pending_launch"] is False, "unexpected pending game process")
    version_dir = root / "versions" / f'{active["sequence"]}-{active["version"]}'
    check_file(version_dir / "payload.rdb", manifest["bundle"], "reconstructed B bundle")
    require((version_dir / manifest["entrypoint"]).is_file(), "activated game executable is missing")
    require(not (version_dir / "assets").exists(), "code-only release unexpectedly contains assets")
    require(not (version_dir / "private-assets").exists(), "release unexpectedly contains private assets")
    return state


def command(launcher, root, args, report, timeout, success=True):
    started = time.monotonic()
    print("Live update smoke:", " ".join(args), file=sys.stderr, flush=True)
    result = subprocess.run(
        [str(launcher), "--root", str(root), *args],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    report["commands"].append({
        "arguments": args, "exit_code": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": result.stdout[-8000:], "stderr": result.stderr[-8000:],
    })
    if success:
        require(result.returncode == 0, f"launcher {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def seed_sentinels(root):
    sentinels = {
        "settings.cfg": b"SYNTHETIC SETTINGS SENTINEL\n",
        "profiles/kestrel.cfg": b"SYNTHETIC PROFILE SENTINEL\n",
        "assets/arms/first-person.vrs": b"SYNTHETIC PRIVATE ARMS, NOT A REAL MODEL\n",
        "assets/weapons/hk416a5.vrm": b"SYNTHETIC PRIVATE WEAPON, NOT A REAL MODEL\n",
        "private-assets/keep.txt": b"SYNTHETIC PRIVATE FILE\n",
    }
    for relative, contents in sentinels.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    return sentinels


def check_sentinels(root, sentinels):
    for relative, expected in sentinels.items():
        path = root / relative
        require(path.is_file() and path.read_bytes() == expected, f"persistent user-data sentinel changed: {relative}")


def smoke(args, report):
    require(args.target in TARGETS, "unsupported target")
    require((os.name == "nt") == args.target.endswith("windows-msvc"), "target must match the smoke runner's operating system")
    require(30 <= args.timeout <= 1800, "timeout must be between 30 and 1800 seconds")
    inputs = [args.launcher, args.baseline_bundle, args.baseline_manifest, args.expected_manifest]
    for path in inputs:
        require(path.is_file() and not path.is_symlink(), f"input is not a regular file: {path}")
    first = check_manifest(args.baseline_manifest, args.baseline_version, args.target)
    second = check_manifest(args.expected_manifest, args.expected_version, args.target)
    require(second["sequence"] > first["sequence"], "B must advance the release sequence")
    require(tuple(map(int, second["version"].split('.'))) > tuple(map(int, first["version"].split('.'))), "B must advance the stable version")
    require(first["entrypoint"] == second["entrypoint"], "A and B entrypoints differ")
    require(first["entrypoint"] == ("vector-range.exe" if args.target.endswith("windows-msvc") else "vector-range"), "unexpected game entrypoint")
    check_file(args.baseline_bundle, first["bundle"], "exact A baseline")
    candidates = [delta for delta in second["deltas"] if
        delta["base_version"] == first["version"]
        and delta["base_sha256"] == first["bundle"]["sha256"]
        and delta["asset"]["size"] < second["bundle"]["size"]]
    require(len(candidates) == 1, "B must advertise one smaller delta for this exact A bundle")
    delta = candidates[0]["asset"]
    report.update({
        "trust": "fixed GitHub HTTPS repository + SHA256 integrity; no independent signing key",
        "target": args.target, "baseline_version": first["version"], "expected_version": second["version"],
        "baseline_release": f'https://github.com/{REPOSITORY}/releases/tag/v{first["version"]}',
        "target_release": f'https://github.com/{REPOSITORY}/releases/tag/v{second["version"]}',
        "baseline_bundle": first["bundle"], "target_bundle": second["bundle"], "delta": delta,
    })
    workspace = Path(tempfile.mkdtemp(prefix="rust-duty-live-update-"))
    report["temporary_root"] = str(workspace)
    report["temporary_root_retained"] = args.keep_root
    try:
        require(latest_manifest(workspace, args.expected_version, args.target, "before") == second,
                "live latest manifest differs from the expected exact B release")
        report["live_latest_before_matches_b"] = True
        # Run a disposable copy; do not alter permissions or content of the supplied artifact.
        launcher = workspace / ("RustDuty.exe" if os.name == "nt" else "RustDuty")
        shutil.copyfile(args.launcher, launcher)
        if os.name != "nt":
            launcher.chmod(0o700)
        root = workspace / "install with spaces"
        root.mkdir()
        trust = command(launcher, root, ["trust-status"], report, args.timeout)
        require(trust.stdout.strip() == f"GITHUB_HTTPS_SHA256 {REPOSITORY}", "supplied launcher has the wrong trust mode")
        command(launcher, root, ["install-local", str(args.baseline_bundle.resolve()), args.baseline_version, first["entrypoint"]], report, args.timeout)
        require(load_state(root)["active"]["version"] == args.baseline_version, "A was not installed")
        sentinels = seed_sentinels(root)
        command(launcher, root, ["configure", "--settings=settings.cfg", "--arms-asset=assets/arms/first-person.vrs", "--weapon-asset=assets/weapons/hk416a5.vrm"], report, args.timeout)
        sentinels["launch.json"] = (root / "launch.json").read_bytes()
        command(launcher, root, ["status"], report, args.timeout)
        command(launcher, root, ["update"], report, args.timeout)
        report["state_after_update"] = validate_install(root, second)
        check_file(root / "cache" / f'{delta["sha256"]}.ready', delta, "downloaded delta")
        require(not (root / "cache" / f'{second["bundle"]["sha256"]}.ready').exists(),
                "B full bundle was downloaded: delta-only proof failed")
        check_sentinels(root, sentinels)
        report["delta_cache_present"] = True
        report["full_bundle_cache_absent"] = True
        report["reconstructed_bundle_matches_b"] = True
        report["persistent_data_unchanged"] = True
        report["bytes_saved_against_full"] = second["bundle"]["size"] - delta["size"]
        command(launcher, root, ["status"], report, args.timeout)
        report["transfer_controls"] = {
            "status": "exercised before and after update",
            "pause": "not_exercised", "resume": "not_exercised", "cancel": "not_exercised",
            "reason": "This synchronous live smoke does not certify in-flight controls or manufacture a pause window; use the separate native interruption/stress suite.",
        }
        command(launcher, root, ["rollback"], report, args.timeout)
        rolled_back = load_state(root)
        require(rolled_back["active"]["version"] == first["version"], "rollback did not restore A")
        require(rolled_back["highest_sequence"] == second["sequence"], "rollback lowered anti-replay sequence")
        check_file(root / "versions" / f'0-{first["version"]}' / "payload.rdb", first["bundle"], "retained A after rollback")
        check_sentinels(root, sentinels)
        report["rollback_restored_a"] = True
        report["rollback_preserved_highest_sequence"] = True
        # The identical B is intentionally forbidden after rollback. Never lower the
        # sequence or rewrite state to pretend a replay is a legitimate new update.
        latest = latest_manifest(workspace, None, args.target, "after-rollback")
        if latest != second:
            report["post_rollback_replay"] = {"status": "not_exercised", "reason": "live channel changed after the B proof"}
        else:
            retry = command(launcher, root, ["update"], report, args.timeout, success=False)
            require(retry.returncode != 0, "rolled-back B was incorrectly replayed")
            require("replay rejected" in retry.stderr, "post-rollback failure did not demonstrate anti-replay protection")
            require(load_state(root) == rolled_back, "rejected replay altered install state")
            check_sentinels(root, sentinels)
            report["post_rollback_replay"] = {"status": "correctly_rejected", "newer_release_required_to_update_again": True}
        report["manual_gui_limits"] = [
            "No native folder-picker interaction is automated by this script.",
            "No real game rendering or user desktop shortcut is exercised.",
            "Native process/path preservation is covered by the separate Windows/Linux child-fixture test.",
        ]
        report["final_temporary_install_version"] = first["version"]
    finally:
        if not args.keep_root:
            try:
                shutil.rmtree(workspace)
            except OSError as error:
                report["temporary_root_retained"] = True
                report["cleanup_warning"] = str(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["launcher", "baseline-bundle", "baseline-manifest", "expected-manifest", "report"]:
        parser.add_argument(f"--{name}", required=True, type=Path)
    for name in ["baseline-version", "expected-version", "target"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--keep-root", action="store_true", help="retain only this disposable test root for debugging")
    args = parser.parse_args()
    if args.report.resolve() in {path.resolve() for path in [args.launcher, args.baseline_bundle, args.baseline_manifest, args.expected_manifest]}:
        parser.error("report must not replace an input artifact")
    report = {"schema": 1, "status": "running", "commands": []}
    try:
        smoke(args, report)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        print(f"Live update smoke failed: {error}", file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
