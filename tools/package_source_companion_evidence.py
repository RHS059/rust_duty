#!/usr/bin/env python3
"""Split this run's validated public primary reload pack into bounded evidence.

This tool has no retrieval or export path. The caller supplies only the output
of its same-run, unchanged Blender producer. Existing full artifacts survive;
these parts do not claim fresh export/parity on a validated producer cache hit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from build_blender_assets import selections
from exclusive_output import write_bytes_exclusive


REPOSITORY = "RHS059/rust_duty"
WORKFLOW = ".github/workflows/renderer-source-companion-evidence.yml"
PRODUCER = ".github/workflows/blender-assets.yml"
COMPANIONS = ("asset.vra", "asset.vrs", "asset.vrm")
REPORTS = ("source.json", "manifest.json", "export-manifest.json", "parity.json")
FILES = (*COMPANIONS, *REPORTS)
MAX_PART_BYTES = 31 * 1024**2
MAX_REPORT_BYTES = 1024**2


def digest(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def safe_path(path):
    """Reject traversal and links, including existing ancestors of new outputs."""
    path = Path(path)
    if ".." in path.parts or "\\" in str(path):
        raise ValueError(f"unsafe path: {path}")
    path = path.absolute()
    for entry in (*reversed(path.parents), path):
        try:
            mode = entry.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError(f"link in path: {entry}")
    return path


def relative_path(root, value):
    value = Path(value)
    if value.is_absolute() or not value.parts:
        raise ValueError("input and output must be nonempty paths relative to the checkout")
    return safe_path(root / value)


def read_regular(path, limit):
    path = safe_path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"not an unlinked regular file: {path}")
    if not 0 < info.st_size <= limit:
        raise ValueError(f"file exceeds byte bound or is empty: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    after = path.lstat()
    attributes = ("st_ino", "st_dev", "st_mode", "st_size", "st_nlink", "st_mtime_ns")
    if len(data) != info.st_size or any(getattr(after, key) != getattr(info, key)
                                     for key in attributes):
        raise ValueError(f"file changed while reading: {path}")
    return data


def github_identity(root, environ):
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW}@refs/heads/main",
    }
    if any(environ.get(key) != value for key, value in expected.items()):
        raise ValueError("requires this repository's main-branch evidence caller")
    sha = environ.get("GITHUB_SHA", "")
    if (not re.fullmatch(r"[0-9a-f]{40}", sha)
            or environ.get("GITHUB_WORKFLOW_SHA") != sha
            or environ.get("GITHUB_EVENT_NAME") not in ("push", "workflow_dispatch")):
        raise ValueError("caller/source identity mismatch")
    run_id, attempt = (environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    if not all(re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
        raise ValueError("invalid run/attempt identity")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, text=True)
    if head != sha or dirty:
        raise ValueError("checkout must match the clean current caller commit")
    return {
        "repository": REPOSITORY, "source_commit": sha,
        "run_id": int(run_id), "run_attempt": int(attempt),
        "run_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}",
        "event": environ["GITHUB_EVENT_NAME"], "ref": "refs/heads/main",
        "caller_workflow": WORKFLOW, "producer_workflow": PRODUCER,
        "input_artifact": f"generated-reload-runtime-attempt-{attempt}",
        "full_canonical_artifact": "generated-reload-runtime",
        "full_attempt_artifact": f"generated-reload-runtime-attempt-{attempt}",
        "input_scope": "same run, after successful reusable producer",
        "generation": "fresh export or exact-input validated producer cache",
    }


def inventory(directory, contract):
    expected = {name for name in FILES}
    for key, _ in selections(contract):
        if key:
            expected.update(f"alternates/{key}/{name}" for name in FILES)
    expected_dirs = {str(parent) for name in expected for parent in Path(name).parents
                     if str(parent) != "."}
    if not directory.is_dir():
        raise ValueError("missing generated input directory")
    actual = set()
    for folder, directories, files in os.walk(directory, followlinks=False):
        for name in directories:
            path = safe_path(Path(folder) / name)
            if (not stat.S_ISDIR(path.lstat().st_mode)
                    or path.relative_to(directory).as_posix() not in expected_dirs):
                raise ValueError(f"unexpected input directory: {path}")
        for name in files:
            path = safe_path(Path(folder) / name)
            relative = path.relative_to(directory).as_posix()
            if relative not in expected:
                raise ValueError(f"unexpected input file: {relative}")
            actual.add(relative)
    if actual != expected:
        raise ValueError(f"missing generated files: {sorted(expected - actual)}")
    return {name: digest(read_regular(directory / name,
                                     MAX_REPORT_BYTES if name.endswith(".json") else MAX_PART_BYTES))
            for name in sorted(expected)}


def package(root, directory, output, identity):
    root = safe_path(root)
    source = relative_path(root, directory)
    output = relative_path(root, output)
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("input and output directories must be separate")
    if output.exists():
        raise FileExistsError("evidence output must be fresh")
    contract_bytes = read_regular(root / "assets/source/reload/source.json", MAX_REPORT_BYTES)
    contract = json.loads(contract_bytes)
    if contract.get("file") != "current.blend":
        raise ValueError("unexpected authoring source")
    blend = digest(read_regular(root / "assets/source/reload/current.blend", MAX_PART_BYTES))
    if blend != {"bytes": contract.get("bytes"), "sha256": contract.get("sha256")}:
        raise ValueError("current authoring source hash mismatch")
    before = inventory(source, contract)
    # Run the existing validator unchanged, over primary AND all source selections.
    command = [sys.executable, "tools/check_generated_assets.py", "--kind", "reload",
               "--directory", str(Path(directory))]
    validation = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, check=True).stdout
    if not 0 < len(validation) <= MAX_REPORT_BYTES:
        raise ValueError("invalid validation receipt size")
    report = json.loads(validation)
    if set(report) != {key or "primary" for key, _ in selections(contract)}:
        raise ValueError("validation receipt misses selected packs")
    if inventory(source, contract) != before:
        raise ValueError("generated input changed during validation")
    originals = {name: read_regular(source / name,
                                   MAX_REPORT_BYTES if name in REPORTS else MAX_PART_BYTES)
                 for name in FILES}
    if any(digest(value) != before[name] for name, value in originals.items()):
        raise ValueError("primary input changed after validation")
    if json.loads(originals["source.json"]) != contract:
        raise ValueError("primary source differs from committed selection")
    receipt = {
        "schema": "rust-duty-source-companion-evidence/v1", "origin": identity,
        "source_contract": digest(contract_bytes), "authoring_source": blend,
        "input_files": before,
        "validation": {"command": command[1:], "returncode": 0,
                       "report": "revalidation.json", **digest(validation)},
        "workflow_files": {name: digest(read_regular(root / name, MAX_REPORT_BYTES))
                           for name in (WORKFLOW, PRODUCER)},
        "max_part_raw_bytes": MAX_PART_BYTES,
        "parts": {name.rsplit(".", 1)[1]: {
            "companion": name,
            "artifact": f"renderer-source-reload-{name.rsplit('.', 1)[1]}-attempt-{identity['run_attempt']}",
        } for name in COMPANIONS},
        "scope": "Exact primary bytes and original reports from current-run producer output. "
                 "Original full artifacts are retained. Cache reuse does not rerun source-oracle "
                 "parity. No renderer, gameplay, visual or human approval claim.",
    }
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    shared = {name: originals[name] for name in REPORTS}
    shared.update({"revalidation.json": validation, "receipt.json": receipt_bytes})
    shared_size = sum(map(len, shared.values()))
    if any(len(originals[name]) + shared_size > MAX_PART_BYTES for name in COMPANIONS):
        raise ValueError("part exceeds 31 MiB bound including all metadata")
    # No new output is created until every input and every part passes validation.
    output.parent.mkdir(parents=True, exist_ok=True)
    safe_path(output.parent)
    output.mkdir()
    for name in COMPANIONS:
        part = output / name.rsplit(".", 1)[1]
        part.mkdir()
        for filename, data in {name: originals[name], **shared}.items():
            write_bytes_exclusive(part / filename, data)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = safe_path(args.root)
    result = package(root, args.directory, args.output, github_identity(root, os.environ))
    print(json.dumps({"origin": result["origin"], "parts": result["parts"]}, indent=2))


if __name__ == "__main__":
    main()
