#!/usr/bin/env python3
"""Bind the checked native executable to its GitHub build's update identity."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

import release_update

REPOSITORY = "RHS059/rust_duty"
WORKFLOW = ".github/workflows/build.yml"
IDENTITY_FILE = "BUILD_IDENTITY.json"
TARGETS = {
    "windows": ("x86_64-pc-windows-msvc", "vector-range.exe", "Windows", b"MZ"),
    "linux": ("x86_64-unknown-linux-gnu", "vector-range", "Linux", b"\x7fELF"),
}
# Explicit one-time owner-authorized 0.1.5 delivery. Future version increments
# belong to merged-PR release automation, never to ordinary draft/push builds.
RELEASE_BRANCHES = {"aella/automatic-game-updates-r1"}
RELEASE_VERSION = "0.1.5"
RELEASE_SEQUENCE = 5


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
    commit = env.get("GITHUB_SHA", "")
    branch = env.get("GITHUB_REF_NAME", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not branch or "\n" in branch:
        raise ValueError("invalid exact source commit or branch")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    if env.get("RUST_DUTY_RELEASE_PR"):
        return merged_context(env, repository, number, run_id, publication=publication)
    version = RELEASE_VERSION
    if env.get("RUST_DUTY_BUILD_VERSION") != version:
        raise ValueError("build version must match the one-time approved 0.1.5 release")
    if publication and (repository != REPOSITORY or env.get("GITHUB_EVENT_NAME") != "push"
                        or branch not in RELEASE_BRANCHES
                        or env.get("GITHUB_REF") != f"refs/heads/{branch}"
                        or env.get("RUST_DUTY_BUILD_RESULT") != "success"):
        raise ValueError("publication requires a successful explicitly authorized one-time release push build")
    return {
        "repository": repository, "version": version, "sequence": RELEASE_SEQUENCE,
        "source": {"commit": commit, "branch": branch, "workflow": WORKFLOW,
                   "run_id": run_id, "run_number": number,
                   "run_url": f"https://github.com/{repository}/actions/runs/{run_id}"},
    }



def merged_context(env, repository, number, run_id, *, publication=False):
    """A ledger allocation, not a run counter, names a merged game build.

    The publication entrypoint additionally rereads the immutable PR allocation
    and GitHub's actual merged PR before any release writes.
    """
    pr = positive_integer(env.get("RUST_DUTY_RELEASE_PR"), "merged PR")
    sequence = positive_integer(env.get("RUST_DUTY_RELEASE_SEQUENCE"), "release sequence")
    version = env.get("RUST_DUTY_BUILD_VERSION")
    commit = env.get("RUST_DUTY_SOURCE_SHA", "")
    workflow = ".github/workflows/merged-game-release.yml"
    if (repository != REPOSITORY or sequence <= RELEASE_SEQUENCE
            or version != f"0.1.{sequence}"
            or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or env.get("GITHUB_REF") != "refs/heads/main"
            or env.get("GITHUB_EVENT_NAME") not in ("pull_request_target", "workflow_dispatch", "schedule")
            or env.get("GITHUB_WORKFLOW_REF") != f"{REPOSITORY}/{workflow}@refs/heads/main"):
        raise ValueError("merged build requires a trusted main workflow and a valid patch allocation")
    if publication and env.get("RUST_DUTY_BUILD_RESULT") != "success":
        raise ValueError("merged publication requires both complete native builds to succeed")
    return {
        "repository": repository, "version": version, "sequence": sequence,
        "merge": {"pull_request": pr, "base": "main"},
        "source": {"commit": commit, "branch": "main", "workflow": workflow,
                   "run_id": run_id, "run_number": number,
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
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--platform", choices=TARGETS, required=True)
    args = parser.parse_args()
    print(json.dumps(stamp(args.root, args.platform), indent=2))


if __name__ == "__main__":
    main()
