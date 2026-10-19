"""Lossless transport only. Never grants native admission or changes raw identities.

No archives, extraction paths, native tools, Git, network or automatic publication.
The one supported closure is the independently selected explicit comment-projected delta and all 37
hash-only reference records. The decoder never handles either held older payload.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import zlib

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
RAW_PIN_SHA = "135250e7fd259bbb50d4295639ca6e80a2c10e6a298a35510513bc8ddb50679c"
SCHEMA = "rust-duty-onehand-lossless-source-transport/v1"
CHUNK = 64 * 1024
RAW_CAP = 32 * 1024**2
TRANSPORT_CAP = 16 * 1024**2
DISK_FLOOR = 1288490189  # ceil(1.2 GiB)


def require(value, message):
    if not value:
        raise ValueError(message)


def strict_load(raw):
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def sha(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value), "exact SHA256 required")


def relative(value):
    require(type(value) is str and value and "\\" not in value and "\0" not in value,
            "plain relative path required")
    p = Path(value)
    require(not p.is_absolute() and all(part not in ("", ".", "..") and ":" not in part
            and part == part.rstrip(" .")
            and not re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
            for part in value.split("/")), "unsafe relative path")
    return p


def ordinary(path, exists=True):
    p = Path(path).absolute()
    require(".." not in p.parts, "parent traversal")
    for part in (*reversed(p.parents), p):
        if part.exists() or part.is_symlink():
            s = part.lstat()
            require(not stat.S_ISLNK(s.st_mode) and not getattr(s, "st_file_attributes", 0) & 0x400,
                    "redirected path")
    if exists:
        require(p.is_file() and p.stat().st_nlink == 1, "ordinary non-hardlinked file required")
    return p


def fingerprint(path, cap):
    p = ordinary(path)
    require(p.stat().st_size <= cap, "file cap exceeded")
    h = hashlib.sha256(); count = 0
    with p.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            count += len(block); require(count <= cap, "file grew beyond cap"); h.update(block)
    return {"sha256": h.hexdigest(), "bytes": count}


def read_pinned_json(path, expected_sha, cap):
    """Read, verify and parse one identical bounded byte string; never reopen."""
    sha(expected_sha)
    p = ordinary(path)
    with p.open("rb") as stream:
        raw = stream.read(cap + 1)
    require(len(raw) <= cap, "pinned JSON cap exceeded")
    require(hashlib.sha256(raw).hexdigest() == expected_sha, "pinned JSON bytes differ")
    return strict_load(raw)


def canonical_pins():
    value = read_pinned_json(HERE / "RAW_INPUT_PINS.json", RAW_PIN_SHA, 128 * 1024)
    require(type(value) is dict and type(value.get("files")) is list
            and len(value["files"]) == 38, "fixed nonempty 38-file canonical inventory required")
    return value["files"]


def validate_manifest(value):
    require(type(value) is dict and set(value) == {"schema", "canonical_pins_sha256", "files"},
            "manifest fields differ")
    require(value["schema"] == SCHEMA and value["canonical_pins_sha256"] == RAW_PIN_SHA,
            "manifest identity differs")
    pins = canonical_pins(); rows = value["files"]
    require(type(rows) is list and len(rows) == len(pins), "complete canonical input inventory required")
    for row, pin in zip(rows, pins):
        require(type(row) is dict and set(row) == {"name", "kind", "canonical", "transport"},
                "transport row fields differ")
        require(row["name"] == pin["name"] and row["kind"] == pin["kind"], "input order/role differs")
        require(row["canonical"] == {"path": pin["canonical_path"], "sha256": pin["sha256"], "bytes": pin["bytes"]},
                "canonical raw identity differs")
        t = row["transport"]
        require(type(t) is dict and set(t) == {"path", "encoding", "sha256", "bytes"}, "transport fields differ")
        require(t["path"] == "payload/" + pin["name"] + ".gz" and t["encoding"] == "gzip-single-member",
                "explicit single-file gzip transport required")
        relative(t["path"]); relative(row["canonical"]["path"]); sha(t["sha256"])
        require(type(t["bytes"]) is int and 0 < t["bytes"] <= TRANSPORT_CAP, "compressed byte cap")
    require(sum(r["transport"]["bytes"] for r in rows) <= TRANSPORT_CAP, "total transport byte cap")
    return rows



def stream_fingerprint(stream, cap):
    h = hashlib.sha256(); count = 0
    for block in iter(lambda: stream.read(CHUNK), b""):
        count += len(block); require(count <= cap, "file grew beyond cap"); h.update(block)
    return {"sha256": h.hexdigest(), "bytes": count}

def decode_verified(source, transport, canonical, sink):
    """Stream exact canonical bytes to a caller-owned sink in <=64 KiB writes.

    Caller must keep output private/unadmitted until this returns successfully.
    A hash/size pass occurs before any decoding. A second encoded hash during
    decoding detects changes between the passes. Concatenation/trailing data,
    truncation, footer errors and expansion beyond the exact raw size fail.
    """
    require(type(canonical["bytes"]) is int and 0 < canonical["bytes"] <= RAW_CAP, "raw byte cap")
    sha(canonical["sha256"]); sha(transport["sha256"])
    require(type(transport["bytes"]) is int and 0 < transport["bytes"] <= TRANSPORT_CAP, "encoded byte cap")
    expected_transport = {k: transport[k] for k in ("sha256", "bytes")}
    source = ordinary(source)
    dec = zlib.decompressobj(31); raw_hash = hashlib.sha256(); encoded_hash = hashlib.sha256()
    raw_count = encoded_count = 0
    # One opened file supplies prehash, header and bounded decoding. A second
    # encoded hash still detects in-place changes between the two passes.
    with source.open("rb") as stream:
        require(stream_fingerprint(stream, TRANSPORT_CAP) == expected_transport, "encoded hash/size differs")
        stream.seek(0); header = stream.read(10)
        require(len(header) == 10 and header[:8] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00",
                "gzip optional fields or timestamp forbidden")
        stream.seek(0)
        for block in iter(lambda: stream.read(CHUNK), b""):
            require(not dec.eof, "trailing encoded data")
            encoded_count += len(block); require(encoded_count <= transport["bytes"], "encoded size grew")
            encoded_hash.update(block); pending = block
            while pending:
                raw = dec.decompress(pending, min(CHUNK, canonical["bytes"] - raw_count + 1))
                raw_count += len(raw); require(raw_count <= canonical["bytes"], "decompression exceeds exact raw size")
                require(not dec.unused_data, "trailing data or multiple gzip members")
                if raw:
                    raw_hash.update(raw); sink(raw)
                pending = dec.unconsumed_tail
    require(dec.eof and not dec.unused_data and not dec.unconsumed_tail, "truncated gzip member")
    require(encoded_count == transport["bytes"] and encoded_hash.hexdigest() == transport["sha256"],
            "encoded file changed during decoding")
    require(raw_count == canonical["bytes"] and raw_hash.hexdigest() == canonical["sha256"],
            "decoded canonical hash/size differs")
    return {"sha256": raw_hash.hexdigest(), "bytes": raw_count}


def materialize(manifest, package_root, output_root):
    rows = validate_manifest(manifest); package_root = Path(package_root).absolute()
    root = ordinary(output_root, False); require(not root.exists(), "fresh output root required")
    # This API is intended for the later independently reviewed runner. It is
    # not called against real inputs by this local preparation or its tests.
    parent = root.parent
    require(parent.is_dir(), "output parent must already exist")
    require(shutil.disk_usage(parent).free >= DISK_FLOOR + sum(r["canonical"]["bytes"] for r in rows),
            "full decoded inventory plus disk floor required")
    root.mkdir(); results = []
    for row in rows:
        source = package_root / relative(row["transport"]["path"])
        target = root / relative(row["canonical"]["path"])
        require(shutil.disk_usage(root).free >= DISK_FLOOR + row["canonical"]["bytes"], "disk floor")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            actual = decode_verified(source, row["transport"], row["canonical"], stream.write)
        require(fingerprint(target, RAW_CAP) == actual, "written canonical bytes differ")
        results.append({"name": row["name"], **actual})
    return {"schema": "rust-duty-onehand-lossless-materialization/v1", "native_admission": False, "files": results}


def main():
    p = argparse.ArgumentParser(); p.add_argument("--manifest", required=True)
    p.add_argument("--manifest-sha256", required=True); p.add_argument("--output", required=True)
    args = p.parse_args(); sha(args.manifest_sha256)
    path = ordinary(args.manifest)
    manifest = read_pinned_json(path, args.manifest_sha256, 256 * 1024)
    result = materialize(manifest, path.parent, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
