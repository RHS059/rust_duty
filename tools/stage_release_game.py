#!/usr/bin/env python3
"""Stage with the exact game's packager, then independently verify every asset.

Never rebuild or publish. Source control files and CI artifacts are read-only;
only a fresh staging directory may be created. The release-control checkout must
not substitute its older packaging allowlist for the selected game's toolchain.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import zipfile

from release_update import REPOSITORY, safe_path

KINDS = ("locomotion", "walk", "ads", "directional", "reload", "jump")
COMPANIONS = ("asset.vra", "asset.vrs", "asset.vrm")
REQUIRED_ASSETS = {"assets/animations.cfg"} | {
    f"assets/{kind}/{name}" for kind in KINDS if kind != "jump" for name in COMPANIONS}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular(root, relative):
    root, relative = Path(root), Path(relative)
    require(not root.is_symlink() and root.is_dir(), "unsafe distribution root")
    require(not relative.is_absolute() and ".." not in relative.parts, "unsafe relative path")
    cursor = root
    for part in relative.parts:
        cursor /= part
        require(not cursor.is_symlink(), f"symlink in distribution: {relative}")
    require(cursor.is_file(), f"required distribution file missing: {relative}")
    return cursor


def record(path):
    with Path(path).open("rb") as stream:
        return {"size": Path(path).stat().st_size,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def files(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "unsafe directory")
    result = {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), f"symlink in distribution: {path}")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            require(name.lower() not in {p.lower() for p in result}, "case-colliding distribution paths")
            result[name] = record(path)
    return result


def managed_assets(root):
    result = files(root)
    selected = {name: value for name, value in result.items()
                if name == "assets/animations.cfg" or
                any(name.startswith(f"assets/{kind}/") for kind in KINDS)}
    require(REQUIRED_ASSETS <= set(selected), "complete authored runtime assets are missing")
    return selected


def verify_source_contract(source, artifact):
    source, artifact = Path(source), Path(artifact)
    # Git checkout on Windows uses CRLF for this text file. Preserve artifact
    # bytes in the package, but compare source bindings with CRLF normalized;
    # no other whitespace, comments, values or bare-CR bytes are discarded.
    expected_bindings = regular(source, "assets/animations.cfg").read_bytes()
    artifact_bindings = regular(artifact, "assets/animations.cfg").read_bytes()
    require(expected_bindings.replace(b"\r\n", b"\n") == artifact_bindings.replace(b"\r\n", b"\n"),
            "artifact animation bindings differ from exact game source")
    bound_kinds = set()
    for line in regular(source, "assets/animations.cfg").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key.endswith(".asset"):
            relative = Path(value)
            require(not relative.is_absolute() and ".." not in relative.parts and
                    "\\" not in value and relative.parts and relative.parts[0] in KINDS,
                    "unknown or unsafe source runtime asset binding")
            bound_kinds.add(relative.parts[0])
    contract = json.loads(regular(source, "assets/source/reload/source.json").read_text())
    actual = json.loads(regular(artifact, "assets/reload/source.json").read_text())
    require(actual == contract, "artifact reload contract differs from exact game source")
    for extra in contract.get("additional_selections", []):
        key = extra.get("id")
        require(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_]*", key), "unsafe reload selection")
        expected = {k: v for k, v in contract.items() if k not in ("additional_selections", "unreviewed_prefix")}
        expected.update(extra)
        folder = f"assets/reload/alternates/{key}"
        actual = json.loads(regular(artifact, folder + "/source.json").read_text())
        require(actual == expected, "artifact reload alternate differs from exact source")
        for name in COMPANIONS:
            regular(artifact, folder + "/" + name)
    # Locomotion is the immutable baseline. Walk/ADS/directional are freshly
    # generated CI outputs, not necessarily byte-identical to a committed cache.
    # Bind their authoring recipe/source and verify their actual output hashes;
    # do not substitute cache hashes or volatile FBX export/parity measurements.
    for kind in ("locomotion", "walk", "ads", "directional", "jump"):
        if kind == "jump" and kind not in bound_kinds:
            continue
        path = f"assets/{kind}/manifest.json"
        actual = json.loads(regular(artifact, path).read_text())
        require(set(actual.get("files", {})) == set(COMPANIONS), "invalid companion inventory")
        for name in COMPANIONS:
            value = record(regular(artifact, f"assets/{kind}/{name}"))
            require(actual["files"][name] == {"bytes": value["size"], "sha256": value["sha256"]},
                    f"artifact {kind} companion does not match its verified metadata")
        if (source / path).exists():
            expected = json.loads(regular(source, path).read_text())
            if kind == "locomotion":
                require(actual == expected, "artifact locomotion manifest differs from exact source")
            else:
                require(authoring_recipe(actual) == authoring_recipe(expected),
                        f"artifact {kind} authoring recipe differs from exact source")
        if kind == "jump":
            # Jump's immutable blend lives in the source commit pinned by CI,
            # while this exact game checkout owns its content hash and recipe.
            config = json.loads(regular(source, "assets/authoring/jump/export_config.json").read_text())
            origin = actual.get("source", {})
            require(config.get("schema") == "rust-duty-jump-authoring-export/v1" and
                    config.get("source_file") == "halcyon_jump.blend" and
                    re.fullmatch(r"[0-9a-f]{64}", config.get("source_sha256", "")),
                    "invalid source-owned Jump export contract")
            require(origin.get("file") == "assets/authoring/jump/" + config["source_file"] and
                    origin.get("sha256") == config["source_sha256"] and
                    origin.get("fps") == config["source_fps"] and
                    origin.get("bake_hz") == config["bake_hz"],
                    "artifact Jump differs from exact source-owned export contract")
            expected_takes = [{"name": take["name"], "loop": take["loop"],
                               "duration": (take["frame_end"] - take["frame_start"]) / config["source_fps"],
                               "action": take["action"], "frame_start": take["frame_start"],
                               "frame_end": take["frame_end"]} for take in config["source_takes"]]
            require(actual.get("jump_clips") == expected_takes,
                    "artifact Jump clip recipe differs from selected source")
        elif kind != "locomotion" and "source" in actual:
            origin = actual["source"]
            relative = origin.get("file", "")
            require(isinstance(relative, str) and relative.startswith("assets/authoring/"),
                    "unexpected authored source path")
            value = record(regular(source, relative))
            require(value == {"size": origin.get("bytes"), "sha256": origin.get("sha256")},
                    f"artifact {kind} differs from exact Blender source")
    return managed_assets(artifact)


def authoring_recipe(manifest):
    result = {k: v for k, v in manifest.items()
              if k not in ("files", "repository_transport", "validation", "preservation")}
    if isinstance(result.get("source"), dict):
        result["source"] = {k: v for k, v in result["source"].items() if k != "fbx"}
    return result


def verify_staged_assets(artifact, staged, *, update):
    expected = managed_assets(artifact)
    actual = managed_assets(staged)
    require(actual == expected, "staging omitted or changed authored runtime members")
    all_files = files(staged)
    if update:
        for name in all_files:
            safe_path(name)
            require(not name.lower().startswith(("profiles/", "assets/arms/", "assets/weapons/")),
                    "managed update contains user-owned profile or private asset path")
    return {"asset_files": len(actual), "total_files": len(all_files), "assets": actual}


def verify_archive(archive, complete):
    expected = files(complete)
    actual = {}
    directories = {parent.as_posix() + "/" for name in expected
                   for parent in Path(name).parents if parent != Path(".")}
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            require((item.external_attr >> 16) & 0o170000 != 0o120000, "symlink in ZIP")
            if item.is_dir():
                require(item.filename in directories, "unexpected ZIP directory")
                continue
            name = item.filename
            require(name in expected and name not in actual, "ZIP inventory differs from complete stage")
            require(item.file_size == expected[name]["size"], "ZIP member size differs")
            require((item.external_attr >> 16) & 0o170000 != 0o120000, "symlink in ZIP")
            with bundle.open(item) as stream:
                actual[name] = {"size": item.file_size,
                                "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}
    require(actual == expected, "ZIP omitted or changed complete game files")
    return {"files": len(actual), **record(archive)}


def bundle_records(bundle):
    bundle = Path(bundle)
    require(bundle.is_file() and not bundle.is_symlink(), "unsafe bundle")
    result, folded = {}, set()
    with bundle.open("rb") as stream:
        def read(size):
            data = stream.read(size)
            require(len(data) == size, "truncated bundle")
            return data
        require(read(8) == b"RDBND001", "wrong bundle magic")
        count, = struct.unpack("<I", read(4))
        require(0 < count <= 50000, "invalid bundle count")
        for _ in range(count):
            length, = struct.unpack("<H", read(2))
            require(0 < length <= 240, "invalid bundle path length")
            name = read(length).decode("ascii")
            safe_path(name)
            require(not name.lower().startswith(("profiles/", "assets/arms/", "assets/weapons/")),
                    "bundle contains user-owned profile or private asset path")
            require(name.lower() not in folded, "duplicate bundle member")
            folded.add(name.lower())
            require(read(1)[0] in (0, 1), "invalid bundle mode")
            size, = struct.unpack("<Q", read(8))
            require(size <= bundle.stat().st_size, "invalid bundle size")
            digest, remaining = hashlib.sha256(), size
            while remaining:
                chunk = read(min(remaining, 1024 * 1024))
                digest.update(chunk)
                remaining -= len(chunk)
            result[name] = {"size": size, "sha256": digest.hexdigest()}
        require(not stream.read(1), "trailing bundle bytes")
    return result


def verify_bundle_members(bundle, directory, *, exact=True):
    expected = bundle_records(bundle)
    require(REQUIRED_ASSETS <= set(expected), "bundle omits required authored animation assets")
    for name, value in expected.items():
        require(record(regular(directory, name)) == value, f"bundle bytes differ for {name}")
    if exact:
        require(files(directory) == expected, "bundle omitted or changed staged members")
    return {"files": len(expected), "assets": len([p for p in expected if p.startswith("assets/")])}


def stage_game(toolchain, source_sha, artifact, binary, output, update=False, version=None):
    toolchain, artifact, output = Path(toolchain), Path(artifact), Path(output)
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha), "game source must be an exact SHA")
    actual = subprocess.check_output(["git", "-C", str(toolchain), "rev-parse", "HEAD"], text=True).strip()
    require(actual == source_sha, "packaging toolchain is not the selected exact game source")
    require(binary in ("vector-range", "vector-range.exe"), "unexpected game binary")
    require(not output.exists() and not output.is_symlink(), "stage output already exists")
    verify_source_contract(toolchain, artifact)
    identity = json.loads(regular(artifact, "BUILD_IDENTITY.json").read_text())
    executable = regular(artifact, binary)
    require(identity.get("repository") == REPOSITORY and
            identity.get("source", {}).get("commit") == source_sha and
            identity.get("executable") == {"name": binary, **record(executable)},
            "artifact identity does not bind this source and executable")
    if version is not None:
        require(identity.get("version") == version, "artifact version differs from release plan")
    script = regular(toolchain, "tools/package_game.py")
    command = [sys.executable, str(script.resolve()), "stage", "--root", str(artifact.resolve()),
               "--binary", binary, "--output", str(output.absolute()), "--require-generated"]
    if update:
        command.append("--update")
    subprocess.run(command, check=True)
    require(record(regular(output, binary)) == record(executable),
            "staged game executable differs from the verified native artifact")
    return {"toolchain_commit": source_sha, "version": identity.get("version"),
            "binding_line_endings": {
                "source_crlf": regular(toolchain, "assets/animations.cfg").read_bytes().count(b"\r\n"),
                "artifact_crlf": regular(artifact, "assets/animations.cfg").read_bytes().count(b"\r\n")},
            **verify_staged_assets(artifact, output, update=update)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage")
    for name in ("toolchain", "artifact", "output"):
        stage.add_argument("--" + name, type=Path, required=True)
    stage.add_argument("--source-sha", required=True)
    stage.add_argument("--binary", required=True)
    stage.add_argument("--version", required=True)
    stage.add_argument("--update", action="store_true")
    bundle = commands.add_parser("verify-bundle")
    bundle.add_argument("--bundle", type=Path, required=True)
    bundle.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "stage":
        value = stage_game(args.toolchain, args.source_sha, args.artifact, args.binary,
                           args.output, args.update, args.version)
    else:
        value = verify_bundle_members(args.bundle, args.directory)
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

