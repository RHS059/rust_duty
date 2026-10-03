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
    start, end = contract["native_range"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= 10000:
        raise ValueError("invalid native range")
    output.mkdir(parents=True)
    fbx_dir, runtime = output / "fbx", output / "reload"
    def run(script, *args):
        subprocess.run([blender, "--background", "--disable-autoexec", "--python-exit-code", "1",
                        "--python", str(root / "tools" / script), "--", *map(str, args)],
                       cwd=root, check=True)
    run("export_reload_wip_fbx.py", "--source", source,
        "--source-sha256", contract["sha256"], "--action", contract["action"],
        "--native-start", start, "--native-end", end, "--output", fbx_dir)
    exported = json.loads((fbx_dir / "export-manifest.json").read_text())
    run("import_fbx_viewmodel.py", "--fbx", fbx_dir / "current-full-wip.fbx",
        "--fbx-sha256", exported["files"]["current-full-wip.fbx"]["sha256"],
        "--source-sha256", contract["sha256"], "--material-source", source,
        "--skeleton-vra", root / "assets/locomotion/asset.vra", "--name", contract["clip"],
        "--native-start", start, "--native-end", end, "--switch", "112", "--switch", "111.98",
        "--actor", "hk416_weapon", "--actor", "hk416_magazine",
        "--actor", "hk416_magazine_outgoing", "--output", runtime)
    shutil.copy2(fbx_dir / "export-manifest.json", runtime / "export-manifest.json")
    shutil.copy2(source_dir / "source.json", runtime / "source.json")
    return runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("build-assets"))
    args = parser.parse_args()
    print(build(args.blender, args.root, args.output))


if __name__ == "__main__":
    main()
