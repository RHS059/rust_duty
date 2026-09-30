#!/usr/bin/env python3
"""Prepare deterministic Rust Duty release bundles, REAL copy/add patches, and manifests.

No network requests, uploads, key generation, or private signing keys. `seal` accepts
an already-created Ed25519 signature and checks it against the approved public key.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import struct
import sys
import tempfile

REPOSITORY = "RHS059/rust_duty"
MAX_SIZE = 2 * 1024**3
PROTECTED = {"settings.cfg", "telemetry.csv", "private-assets", "user", "userdata", "saves", "cache", "versions", "install.json", "control.json", "payload.rdb", "version.json", "launcher.lock", "manifest.cache.json", "status.json", "launch.json", ".git"}


def stable_version(value):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("version must be stable MAJOR.MINOR.PATCH")
    return tuple(map(int, value.split(".")))


def safe_path(value):
    if not value or len(value) > 240 or not value.isascii() or "\\" in value:
        raise ValueError(f"unsafe path: {value}")
    for part in value.split("/"):
        if not re.fullmatch(r"[A-Za-z0-9._ -]+", part) or part in {".", ".."} or part.endswith((".", " ")):
            raise ValueError(f"unsafe path: {value}")
        stem = part.split(".")[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(COM|LPT)[0-9]", stem):
            raise ValueError(f"Windows device name: {value}")
    if any(part.lower() in {"private-assets", "fps-arms.vrs"} for part in value.split("/")):
        raise ValueError(f"private asset path: {value}")
    if value.split("/")[0].lower() in PROTECTED:
        raise ValueError(f"protected path: {value}")


def sha(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def asset(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_SIZE:
        raise ValueError("asset must be between 1 byte and 2 GiB")
    return {"name": path.name, "size": path.stat().st_size, "sha256": sha(path)}


def atomic_output(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return tempfile.NamedTemporaryFile(prefix=".prepare-", dir=path.parent, delete=False)


def pack(source, output, entrypoint):
    source, output = Path(source).resolve(), Path(output).resolve()
    safe_path(entrypoint)
    if source == output or source in output.parents:
        raise ValueError("bundle output must be outside input directory")
    files = []
    excluded = []
    for directory, dirs, names in os.walk(source, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"symlinks are forbidden: {path}")
        # Never put private assets, user settings, telemetry or updater state in a release.
        dirs[:] = sorted(d for d in dirs if d.lower() != "private-assets" and (Path(directory) / d).relative_to(source).parts[0].lower() not in PROTECTED)
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(source).as_posix()
            if relative.split("/")[0].lower() in PROTECTED or name.lower() in {"fps-arms.vrs", "launch.json"}:
                excluded.append(relative)
                continue
            safe_path(relative)
            if not path.is_file():
                raise ValueError(f"regular files only: {path}")
            files.append((relative, path))
    files.sort()
    if not 0 < len(files) <= 50000:
        raise ValueError("bundle must contain 1 to 50000 files")
    if len({p.lower() for p, _ in files}) != len(files):
        raise ValueError("case-colliding paths are forbidden")
    if entrypoint not in [p for p, _ in files]:
        raise ValueError("entrypoint is missing")
    temporary = atomic_output(output)
    try:
        with temporary as stream:
            stream.write(b"RDBND001" + struct.pack("<I", len(files)))
            for relative, path in files:
                name = relative.encode("ascii")
                size = path.stat().st_size
                stream.write(struct.pack("<H", len(name)) + name)
                stream.write(bytes([int(relative == entrypoint or bool(path.stat().st_mode & 0o111))]))
                stream.write(struct.pack("<Q", size))
                with path.open("rb") as contents:
                    while chunk := contents.read(1024**2):
                        stream.write(chunk)
            if stream.tell() > MAX_SIZE:
                raise ValueError("bundle exceeds 2 GiB safety limit")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary.name, output)
    finally:
        Path(temporary.name).unlink(missing_ok=True)
    return {"files": len(files), "excluded_user_files": excluded, **asset(output)}


def weak(block):
    n = len(block)
    return sum(block) & 0xFFFF, sum((n - i) * byte for i, byte in enumerate(block)) & 0xFFFF


def make_delta(base, new, output, block_size=4096):
    """Rsync-style rolling weak checksums plus SHA-256 match confirmation.

    COPY references unchanged byte ranges of the old bundle. ADD embeds only new
    bytes. Matching scans every byte, so inserts do not destroy block alignment.
    Memory-mapped inputs avoid loading the complete release twice into RAM.
    """
    base, new, output = Path(base), Path(new), Path(output)
    old_size, new_size = base.stat().st_size, new.stat().st_size
    if not 0 < old_size <= MAX_SIZE or not 0 < new_size <= MAX_SIZE:
        raise ValueError("delta inputs must be between 1 byte and 2 GiB")
    if output.resolve() in {base.resolve(), new.resolve()}:
        raise ValueError("delta output must not overwrite an input")
    if not 64 <= block_size <= 1024**2:
        raise ValueError("block size must be 64 bytes to 1 MiB")
    copied, added, operations = 0, 0, 0
    temporary = atomic_output(output)
    try:
        with base.open("rb") as old_file, new.open("rb") as new_file, mmap.mmap(old_file.fileno(), 0, access=mmap.ACCESS_READ) as old, mmap.mmap(new_file.fileno(), 0, access=mmap.ACCESS_READ) as data, temporary as stream:
            index = {}
            for offset in range(0, old_size - block_size + 1, block_size):
                block = old[offset:offset + block_size]
                index.setdefault(weak(block), []).append((offset, hashlib.sha256(block).digest()))
            stream.write(b"RDDLT001" + struct.pack("<QQ", old_size, new_size))
            pending_copy = None

            def flush_copy():
                nonlocal pending_copy, operations
                if pending_copy is not None:
                    stream.write(b"\0" + struct.pack("<QQ", *pending_copy))
                    operations += 1
                    pending_copy = None

            def add(begin, end):
                nonlocal added, operations
                if end > begin:
                    flush_copy()
                    stream.write(b"\1" + struct.pack("<Q", end - begin))
                    # Write bounded pieces rather than copying a large literal into memory.
                    for position in range(begin, end, 1024**2):
                        stream.write(data[position:min(end, position + 1024**2)])
                    added += end - begin
                    operations += 1

            position = literal = 0
            checksum = weak(data[:block_size]) if new_size >= block_size else (0, 0)
            while position + block_size <= new_size:
                match = None
                candidates = index.get(checksum)
                if candidates:
                    digest = hashlib.sha256(data[position:position + block_size]).digest()
                    match = next((offset for offset, fingerprint in candidates if fingerprint == digest), None)
                if match is not None:
                    add(literal, position)
                    if pending_copy is not None and pending_copy[0] + pending_copy[1] == match:
                        pending_copy = (pending_copy[0], pending_copy[1] + block_size)
                    else:
                        flush_copy()
                        pending_copy = (match, block_size)
                    copied += block_size
                    position += block_size
                    literal = position
                    if position + block_size <= new_size:
                        checksum = weak(data[position:position + block_size])
                else:
                    if position + block_size < new_size:
                        a = (checksum[0] - data[position] + data[position + block_size]) & 0xFFFF
                        checksum = (a, (checksum[1] - block_size * data[position] + a) & 0xFFFF)
                    position += 1
            add(literal, new_size)
            flush_copy()
            stream.write(b"\xff")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary.name, output)
    finally:
        Path(temporary.name).unlink(missing_ok=True)
    return {"copied_bytes": copied, "added_bytes": added, "operations": operations, **asset(output)}


def prepare(args):
    stable_version(args.version)
    if args.sequence < 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", args.target):
        raise ValueError("positive sequence and safe target required")
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    bundle = destination / f"rust-duty-{args.version}-{args.target}.rdb"
    pack_info = pack(args.input, bundle, args.entrypoint)
    payload = {"schema": 1, "repository": REPOSITORY, "version": args.version, "sequence": args.sequence, "target": args.target, "entrypoint": args.entrypoint, "bundle": asset(bundle), "deltas": []}
    delta_info = None
    if args.previous:
        if not args.previous_version or stable_version(args.previous_version) >= stable_version(args.version):
            raise ValueError("previous bundle needs a strictly older --previous-version")
        patch = destination / f"rust-duty-{args.previous_version}-to-{args.version}-{args.target}.rdd"
        delta_info = make_delta(args.previous, bundle, patch)
        if patch.stat().st_size < bundle.stat().st_size:
            payload["deltas"].append({"base_version": args.previous_version, "base_sha256": sha(args.previous), "asset": asset(patch)})
    payload_path = destination / f"update-{args.target}.payload.json"
    payload_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return {"bundle": pack_info, "delta": delta_info, "unsigned_payload": str(payload_path), "next": "Have the approved offline Ed25519 signer sign these exact payload bytes, then use seal. Do not publish an unsigned channel."}


def seal(args):
    # Only public verification material is accepted by this tool.
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as error:
        raise ValueError("seal needs the cryptography package for public signature verification") from error
    payload = Path(args.payload).read_bytes()
    signature = Path(args.signature).read_bytes()
    if len(signature) != 64:
        signature = bytes.fromhex(signature.decode("ascii").strip())
    key = bytes.fromhex(Path(args.public_key).read_text().strip())
    Ed25519PublicKey.from_public_bytes(key).verify(signature, payload)
    parsed = json.loads(payload)
    if parsed["repository"] != REPOSITORY:
        raise ValueError("wrong repository")
    envelope = {"payload": payload.decode("utf-8"), "signature": signature.hex()}
    output = Path(args.output)
    output.write_text(json.dumps(envelope, separators=(",", ":")), encoding="utf-8")
    return {"signed_manifest": str(output), "sha256": sha(output)}



def verify_manifest(args):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    encoded = Path(args.manifest).read_bytes()
    if len(encoded) > 1024**2: raise ValueError("oversized manifest")
    envelope = json.loads(encoded)
    if set(envelope) != {"payload", "signature"}: raise ValueError("unexpected envelope fields")
    payload = envelope["payload"].encode("utf-8")
    key = bytes.fromhex(Path(args.public_key).read_text().strip())
    Ed25519PublicKey.from_public_bytes(key).verify(bytes.fromhex(envelope["signature"]), payload)
    manifest = json.loads(payload)
    if manifest["schema"] != 1 or manifest["repository"] != REPOSITORY or type(manifest["sequence"]) is not int or manifest["sequence"] < 1:
        raise ValueError("wrong manifest schema, repository or sequence")
    stable_version(manifest["version"])
    if args.version and manifest["version"] != args.version: raise ValueError("unexpected release version")
    if args.target and manifest["target"] != args.target: raise ValueError("unexpected release target")
    safe_path(manifest["entrypoint"])
    assets = [manifest["bundle"]]
    if not args.bundle_only: assets.extend(delta["asset"] for delta in manifest["deltas"])
    for item in assets:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,149}", item["name"]) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("unsafe asset name or hash")
        if not 0 < item["size"] <= MAX_SIZE: raise ValueError("invalid asset size")
        if args.assets_dir:
            path = Path(args.assets_dir) / item["name"]
            if path.is_symlink() or path.stat().st_size != item["size"] or sha(path) != item["sha256"]:
                raise ValueError("release asset size/hash verification failed")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    pack_parser = subs.add_parser("pack")
    pack_parser.add_argument("--input", required=True)
    pack_parser.add_argument("--output", required=True)
    pack_parser.add_argument("--entrypoint", required=True)
    delta_parser = subs.add_parser("delta")
    delta_parser.add_argument("--base", required=True)
    delta_parser.add_argument("--new", required=True)
    delta_parser.add_argument("--output", required=True)
    delta_parser.add_argument("--block-size", type=int, default=4096)
    release = subs.add_parser("prepare")
    for argument in ("input", "output", "version", "target", "entrypoint"):
        release.add_argument(f"--{argument}", required=True)
    release.add_argument("--sequence", type=int, required=True)
    release.add_argument("--previous")
    release.add_argument("--previous-version")
    signing = subs.add_parser("seal")
    for argument in ("payload", "signature", "public-key", "output"):
        signing.add_argument(f"--{argument}", required=True)
    verifying = subs.add_parser("verify")
    verifying.add_argument("--manifest", required=True)
    verifying.add_argument("--public-key", required=True)
    verifying.add_argument("--assets-dir")
    verifying.add_argument("--version")
    verifying.add_argument("--target")
    verifying.add_argument("--bundle-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "pack": result = pack(args.input, args.output, args.entrypoint)
        elif args.command == "delta": result = make_delta(args.base, args.new, args.output, args.block_size)
        elif args.command == "prepare": result = prepare(args)
        elif args.command == "seal": result = seal(args)
        else: result = verify_manifest(args)
        print(json.dumps(result, indent=2))
    except Exception as error:
        print(f"Release preparation failed: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
