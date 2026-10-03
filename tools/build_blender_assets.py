#!/usr/bin/env python3
"""Rebuild the selected current WIP from committed Blender source through FBX."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import re


def selections(contract):
    yield "", contract
    for extra in contract.get("additional_selections", []):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", extra["id"]):
            raise ValueError("unsafe selection id")
        selected = {k: v for k, v in contract.items() if k not in ("additional_selections", "unreviewed_prefix")}
        selected.update(extra)
        yield extra["id"], selected


def build(blender: str, root: Path, output: Path):
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("use a fresh output directory")
    source_dir = root / "assets/source/reload"
    contract = json.loads((source_dir / "source.json").read_text())
    if (contract.get("schema") != "rust-duty-blender-source/v1"
            or contract.get("file") != "current.blend"
            or contract.get("blender") != "4.3.2"
            or contract.get("native_fps") != [60000, 1001]):
        raise ValueError("unsupported source contract")
    source = source_dir / contract["file"]
    if (source.stat().st_size != contract["bytes"]
            or hashlib.sha256(source.read_bytes()).hexdigest() != contract["sha256"]):
        raise ValueError("canonical .blend differs from committed source contract")
    output.mkdir(parents=True)
    for key, selected in selections(contract):
        export_selection(blender, root, output, source, key, selected)
    return output / "reload"


def export_selection(blender, root, output, source, key, contract):
    start, end = contract["native_range"]
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= 10000:
        raise ValueError("invalid native range")
    fbx_dir = output / ("fbx-" + key if key else "fbx")
    runtime = output / "reload"
    if key:
        runtime = runtime / "alternates" / key
    def run(script, *args):
        subprocess.run([blender, "--background", "--disable-autoexec", "--python-exit-code", "1",
                        "--python", str(root / "tools" / script), "--", *map(str, args)],
                       cwd=root, check=True)
    run("export_reload_wip_fbx.py", "--source", source,
        "--source-sha256", contract["sha256"], "--action", contract["action"],
        "--native-start", start, "--native-end", end, "--output", fbx_dir)
    exported = json.loads((fbx_dir / "export-manifest.json").read_text())
    switches = [arg for value in (112, 111.98) if start < value < end for arg in ("--switch", str(value))]
    run("import_fbx_viewmodel.py", "--fbx", fbx_dir / "current-full-wip.fbx",
        "--fbx-sha256", exported["files"]["current-full-wip.fbx"]["sha256"],
        "--source-sha256", contract["sha256"], "--material-source", source,
        "--skeleton-vra", root / "assets/locomotion/asset.vra", "--name", contract["clip"],
        "--native-start", start, "--native-end", end, *switches,
        "--actor", "hk416_weapon", "--actor", "hk416_magazine",
        "--actor", "hk416_magazine_outgoing", "--output", runtime)
    shutil.copy2(fbx_dir / "export-manifest.json", runtime / "export-manifest.json")
    (runtime / "source.json").write_text(json.dumps(contract, indent=2) + "\n")


def verify(root: Path, output: Path, sampler: Path):
    contract = json.loads((root / "assets/source/reload/source.json").read_text())
    for key, selected in selections(contract):
        runtime = output / "reload"
        if key:
            runtime = runtime / "alternates" / key
        fbx = output / ("fbx-" + key if key else "fbx")
        subprocess.run([sys.executable, str(root / "tools/verify_fbx_segment.py"),
            str(runtime / "asset.vra"), str(fbx / "source-witnesses.npz"),
            "--native-start", str(selected["native_range"][0]), "--clip", selected["clip"],
            "--sampler", str(sampler), "--report", str(runtime / "parity.json")], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender")
    parser.add_argument("--verify-sampler", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("build-assets"))
    args = parser.parse_args()
    if args.verify_sampler:
        verify(args.root, args.output, args.verify_sampler)
    elif args.blender:
        print(build(args.blender, args.root, args.output))
    else:
        parser.error("choose --blender or --verify-sampler")


if __name__ == "__main__":
    main()
