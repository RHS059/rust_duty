#!/usr/bin/env python3
"""Bind the checked native executable to its GitHub build's update identity."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

import release_update

REPOSITORY = "RHS059/rust_duty"
WORKFLOW = ".github/workflows/build.yml"
IDENTITY_FILE = "BUILD_IDENTITY.json"
TARGETS = {
    "windows": ("x86_64-pc-windows-msvc", "vector-range.exe", "Windows", b"MZ"),
    "linux": ("x86_64-unknown-linux-gnu", "vector-range", "Linux", b"\x7fELF"),
}
# Candidate metadata only: builds do not allocate or publish a release.
BUILD_SEQUENCE = 9
# Freeze the legacy one-time publisher; a new package version cannot enable it.
RELEASE_BRANCHES = {"aella/automatic-game-updates-r1"}
LEGACY_RELEASE_VERSION = "0.1.7"
LEGACY_RELEASE_SEQUENCE = 5


def package_version():
    """Use the same checked-out Cargo package identity as build.rs."""
    with (Path(__file__).resolve().parents[1] / "Cargo.toml").open("rb") as stream:
        version = tomllib.load(stream)["package"]["version"]
    parts = release_update.stable_version(version)
    if any(part > 2**64 - 1 for part in parts):
        raise ValueError("oversized Cargo package version")
    return version


def positive_integer(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError(f"invalid {label}")
    result = int(value)
    if result > 2**64 - 1:
        raise ValueError(f"oversized {label}")
    return result


def context(env=None, *, publication=False):
    env = os.environ if env is None else env
    repository = env.get("GITHUB_REPOSITORY", "")
    number = positive_integer(env.get("GITHUB_RUN_NUMBER"), "run number")
    run_id = positive_integer(env.get("GITHUB_RUN_ID"), "run id")
    attempt = positive_integer(env.get("GITHUB_RUN_ATTEMPT"), "run attempt")
    build_number = f"{run_id}.{attempt}"
    commit = env.get("GITHUB_SHA", "")
    branch = env.get("GITHUB_REF_NAME", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not branch or "\n" in branch:
        raise ValueError("invalid exact source commit or branch")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    version = package_version()
    historical = version == LEGACY_RELEASE_VERSION
    sequence = LEGACY_RELEASE_SEQUENCE if historical else BUILD_SEQUENCE
    pinned = env.get("RUST_DUTY_BUILD_VERSION")
    # Only the historical publisher may retain its historical workflow pin.
    allowed = {version, "0.1.5"} if historical else {None, version}
    if pinned not in allowed:
        raise ValueError("build version must match the Cargo package version")
    if publication and (not historical or repository != REPOSITORY or env.get("GITHUB_EVENT_NAME") != "push"
                        or branch not in RELEASE_BRANCHES
                        or env.get("GITHUB_REF") != f"refs/heads/{branch}"
                        or env.get("RUST_DUTY_BUILD_RESULT") != "success"):
        raise ValueError("publication requires a successful explicitly authorized one-time release push build")
    return {
        "repository": repository, "version": version, "sequence": sequence,
        "build_number": build_number, "display_version": f"{version}+build.{build_number}",
        "source": {"commit": commit, "branch": branch, "workflow": WORKFLOW,
                   "run_id": run_id, "run_number": number, "run_attempt": attempt,
                   "run_url": f"https://github.com/{repository}/actions/runs/{run_id}"},
    }


def executable_record(root, platform):
    _, name, _, magic = TARGETS[platform]
    binary = Path(root) / name
    if binary.is_symlink() or not binary.is_file():
        raise ValueError("native game executable missing or symlinked")
    with binary.open("rb") as stream:
        if stream.read(len(magic)) != magic:
            raise ValueError("wrong native executable format")
    return release_update.asset(binary)


def stamp(root, platform, env=None):
    root = Path(root)
    identity = context(env)
    target, name, _, _ = TARGETS[platform]
    record = executable_record(root, platform)
    reported = subprocess.check_output([str((root / name).resolve()), "--build-version"],
                                       text=True, timeout=30).strip()
    if reported != identity["version"]:
        raise ValueError(f"embedded game version {reported!r} differs from build identity")
    reported_label = subprocess.check_output([str((root / name).resolve()), "--build-label"],
                                             text=True, timeout=30).strip()
    if reported_label != identity["display_version"]:
        raise ValueError(f"embedded game build label {reported_label!r} differs from build identity")
    identity.update(schema="rust-duty-build-identity/v1", target=target, executable=record)
    destination = root / IDENTITY_FILE
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to overwrite build identity")
    destination.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return identity


def verify(root, platform, expected):
    path = Path(root) / IDENTITY_FILE
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024:
        raise ValueError("missing or unsafe build identity")
    actual = json.loads(path.read_text(encoding="utf-8"))
    required = {**expected, "schema": "rust-duty-build-identity/v1",
                "target": TARGETS[platform][0], "executable": executable_record(root, platform)}
    if actual != required:
        raise ValueError("artifact identity, source run or executable hash mismatch")
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--platform", choices=TARGETS)
    parser.add_argument("--print-label", action="store_true")
    args = parser.parse_args()
    if args.print_label:
        print(context()["display_version"])
    else:
        if args.root is None or args.platform is None:
            parser.error("--root and --platform are required for stamping")
        print(json.dumps(stamp(args.root, args.platform), indent=2))


if __name__ == "__main__":
    main()

