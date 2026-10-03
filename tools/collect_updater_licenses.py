#!/usr/bin/env python3
"""Copy real packaged dependency license/notice texts from Cargo's resolved registry packages.

No guessed copyright text or external downloads. Run cargo fetch --locked first.
Includes dependency closure for Windows MSVC and Linux GNU, including build/proc-macro crates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def collect(manifest, output):
    selected = {}
    targets = ["x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu"]
    for target in targets:
        metadata = json.loads(subprocess.check_output([
            "cargo", "metadata", "--manifest-path", str(manifest), "--locked", "--offline",
            "--format-version", "1", "--filter-platform", target], text=True))
        graph = {node["id"]: node for node in metadata["resolve"]["nodes"]}
        pending, reachable = [metadata["resolve"]["root"]], set()
        while pending:
            package = pending.pop()
            if package in reachable: continue
            reachable.add(package)
            pending.extend(dependency["pkg"] for dependency in graph[package]["deps"])
        for package in metadata["packages"]:
            if package["id"] in reachable and package["source"]:
                selected[package["id"]] = package
    inventory = []
    notice = ["RUST DUTY UPDATER — THIRD-PARTY LICENSES AND NOTICES\n",
              "Generated from Cargo.lock resolution and actual packaged registry license files.\n",
              "Coverage: x86_64-pc-windows-msvc + x86_64-unknown-linux-gnu dependency closure.\n",
              "Includes build-time dependencies as a conservative superset; no copyright attribution was invented.\n\n"]
    for package in sorted(selected.values(), key=lambda p: (p["name"], p["version"])):
        root = Path(package["manifest_path"]).parent
        files = {path for path in root.rglob("*") if path.is_file() and path.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT"))}
        if package.get("license_file"):
            explicit = root / package["license_file"]
            if explicit.is_file(): files.add(explicit)
        if not files:
            raise RuntimeError(f"No packaged license text found for {package['name']} {package['version']}; resolve manually rather than guessing")
        record = {"name": package["name"], "version": package["version"], "license_expression": package["license"], "authors": package["authors"], "repository": package["repository"], "source": package["source"], "files": []}
        notice.append(f"\n{'=' * 78}\n{package['name']} {package['version']}\nLicense expression: {package['license']}\nRegistry source: {package['source']}\n")
        for path in sorted(files):
            relative = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            record["files"].append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest()})
            notice.append(f"\n--- Packaged file: {relative} ---\n{text}\n")
        inventory.append(record)
    output.mkdir(parents=True, exist_ok=True)
    (output / "THIRD_PARTY_UPDATER_LICENSES.txt").write_text("".join(notice), encoding="utf-8")
    (output / "UPDATER_DEPENDENCIES.json").write_text(json.dumps({"targets": targets, "packages": inventory}, indent=2) + "\n", encoding="utf-8")
    print(f"Collected actual license/notice files for {len(inventory)} dependency packages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("updater/Cargo.toml"))
    parser.add_argument("--output", type=Path, default=Path("updater/notices"))
    arguments = parser.parse_args()
    collect(arguments.manifest, arguments.output)
