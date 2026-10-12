#!/usr/bin/env python3
"""Bounded private-notebook transport for an evidence-only archive; no network.

Emission is not proof of notebook persistence, external retrieval, or GPU shutdown.
Materialization verifies chunks and exact archive bytes without extracting files.
"""
from __future__ import annotations
import argparse
import base64
import contextlib
import hashlib
import json
import math
from pathlib import Path
import re
import signal
import sys
import time

MAX_ARCHIVE_BYTES = 8 * 1024**2
CHUNK_BYTES = 48 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
MAX_TRANSCRIPT_BYTES = 12 * 1024**2
PREFIX = "A100_EVIDENCE_"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def read_regular(path, limit):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and not any(p.is_symlink() for p in path.parents), "Expected regular unlinked file")
    require(path.stat().st_size <= limit, "Text export size bound exceeded; raw files were not altered or truncated")
    data = path.read_bytes()
    require(len(data) <= limit, "Text export size bound exceeded")
    return data


def prepare_transport(root):
    root = Path(root)
    receipt_raw = read_regular(root / "EVIDENCE_EXPORT_RECEIPT.json", MAX_MANIFEST_BYTES)
    result_raw = read_regular(root / "RESULT.json", MAX_MANIFEST_BYTES)
    receipt, result = json.loads(receipt_raw), json.loads(result_raw)
    require(receipt.get("schema") == "rust-duty-evidence-export/v1" and receipt.get("kind") == "evidence-only"
            and receipt.get("includes_executable") is False and receipt.get("includes_raw_assets") is False
            and receipt.get("all_archived_file_hashes_verified") is True
            and receipt.get("file") == "a100-evidence-only.tar.gz", "Only verified evidence-only archives support notebook text export")
    require(result.get("export_status") == "verified" and result.get("export") == receipt, "Final result is not bound to the evidence receipt")
    archive = read_regular(root / receipt["file"], MAX_ARCHIVE_BYTES)
    require(len(archive) == receipt.get("bytes") and sha(archive) == receipt.get("sha256"), "Evidence archive differs from receipt")
    chunks = [archive[offset:offset + CHUNK_BYTES] for offset in range(0, len(archive), CHUNK_BYTES)]
    require(chunks, "Empty evidence archive")
    manifest = {"schema": "rust-duty-notebook-evidence-text/v1", "export_id": sha(archive), "archive_file": receipt["file"],
                "archive_bytes": len(archive), "archive_sha256": sha(archive), "chunk_bytes": CHUNK_BYTES,
                "chunk_count": len(chunks), "chunks": [{"index": i, "bytes": len(data), "sha256": sha(data)} for i, data in enumerate(chunks)],
                "evidence_receipt_utf8": receipt_raw.decode(), "final_result_utf8": result_raw.decode(),
                "claim": "Emitted text only; notebook persistence, external retrieval and GPU shutdown need independent verification"}
    require(len(compact(manifest).encode()) <= MAX_MANIFEST_BYTES, "Notebook manifest exceeds bound")
    return manifest, chunks


def transport_lines(manifest, chunks):
    digest = sha(compact(manifest).encode())
    yield PREFIX + "MANIFEST " + compact(manifest)
    for i, chunk in enumerate(chunks):
        yield PREFIX + "CHUNK " + compact({"export_id": manifest["export_id"], "index": i,
                                          "count": len(chunks), "sha256": sha(chunk), "data": base64.b64encode(chunk).decode("ascii")})
    yield PREFIX + "END " + digest


@contextlib.contextmanager
def emission_deadline(result):
    deadline = result.get("deadline_unix")
    clock = result.get("allocation_clock", {})
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    require(clock.get("schema") == "rust-duty-allocation-clock/v1" and clock.get("boot_id") == boot, "Allocation boot identity changed; do not emit from a different runtime")
    monotonic_end = clock.get("monotonic_deadline")
    require(type(monotonic_end) in (int, float) and math.isfinite(monotonic_end), "Missing persisted allocation monotonic deadline")
    require(type(deadline) in (int, float) and math.isfinite(deadline), "Missing allocation deadline")
    seconds = min(30.0, deadline - time.time() - 15.0, monotonic_end - time.monotonic() - 15.0)
    require(seconds > 0, "No text-export time remains; disconnect now and disclose incomplete external export")
    require(signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "An existing process deadline is active")
    def expired(signum, frame):
        raise TimeoutError("Notebook text emission deadline reached; disconnect now; emitted prefix is incomplete")
    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _emit_one(root, kind, emit, expected_manifest_sha256=None, index=None, expected_chunk_sha256=None, acknowledged_through=None):
    """One separately requested output only; acknowledgement comes from the operator."""
    root = Path(root)
    result = json.loads(read_regular(root / "RESULT.json", MAX_MANIFEST_BYTES))
    with emission_deadline(result):
        emit = (lambda line: print(line, flush=True)) if emit is None else emit
        manifest, chunks = prepare_transport(root)
        digest = sha(compact(manifest).encode())
        if kind == "index":
            line = PREFIX + "MANIFEST " + compact(manifest)
        else:
            require(expected_manifest_sha256 == digest, "Requested manifest digest differs")
            if kind == "chunk":
                require(type(index) is int and 0 <= index < len(chunks), "Invalid requested chunk index")
                require(type(acknowledged_through) is int and acknowledged_through == index - 1,
                        "Acknowledge previous chunk before requesting the next")
                chunk = chunks[index]
                require(expected_chunk_sha256 == sha(chunk), "Requested chunk digest differs")
                line = PREFIX + "CHUNK " + compact({"export_id": manifest["export_id"], "index": index,
                       "count": len(chunks), "sha256": sha(chunk), "data": base64.b64encode(chunk).decode("ascii")})
            else:
                require(kind == "finish" and type(acknowledged_through) is int and acknowledged_through == len(chunks) - 1,
                        "Acknowledge every chunk before END")
                line = PREFIX + "END " + digest
        emit(line)
    return {"status": "one_output_emitted_not_persistence_verified", "kind": kind, "export_id": manifest["export_id"],
            "manifest_sha256": digest, "archive_sha256": manifest["archive_sha256"], "archive_bytes": manifest["archive_bytes"],
            "chunks": manifest["chunk_count"], "chunk_index": index, "gpu_shutdown_confirmed": False}


def emit_index(root, emit=None):
    return _emit_one(root, "index", emit)


def emit_chunk(root, index, manifest_sha256, chunk_sha256, acknowledged_through, emit=None):
    return _emit_one(root, "chunk", emit, manifest_sha256, index, chunk_sha256, acknowledged_through)


def emit_finish(root, manifest_sha256, acknowledged_through, emit=None):
    return _emit_one(root, "finish", emit, manifest_sha256, acknowledged_through=acknowledged_through)


def decode_transcript(text, expected_manifest_sha256):
    require(isinstance(expected_manifest_sha256, str) and re.fullmatch("[0-9a-f]{64}", expected_manifest_sha256), "Supply separately observed manifest SHA-256")
    require(len(text.encode()) <= MAX_TRANSCRIPT_BYTES, "Transcript exceeds explicit bound")
    manifest, chunks, end = None, {}, None
    for line in text.splitlines():
        if not line.startswith(PREFIX):
            continue
        marker, separator, value = line.partition(" ")
        require(separator, "Truncated notebook marker")
        if marker == PREFIX + "MANIFEST":
            require(manifest is None and end is None and not chunks, "Duplicate or out-of-order manifest")
            require(len(value.encode()) <= MAX_MANIFEST_BYTES, "Manifest exceeds bound")
            require(sha(value.encode()) == expected_manifest_sha256, "Notebook manifest digest differs")
            manifest = json.loads(value)
            require(manifest.get("schema") == "rust-duty-notebook-evidence-text/v1" and manifest.get("archive_file") == "a100-evidence-only.tar.gz"
                    and manifest.get("export_id") == manifest.get("archive_sha256") and re.fullmatch("[0-9a-f]{64}", manifest["export_id"])
                    and type(manifest.get("archive_bytes")) is int and 0 < manifest["archive_bytes"] <= MAX_ARCHIVE_BYTES
                    and manifest.get("chunk_bytes") == CHUNK_BYTES and type(manifest.get("chunk_count")) is int
                    and manifest["chunk_count"] == math.ceil(manifest["archive_bytes"] / CHUNK_BYTES)
                    and isinstance(manifest.get("chunks"), list) and len(manifest["chunks"]) == manifest["chunk_count"], "Invalid bounded transport manifest")
        elif marker == PREFIX + "CHUNK":
            require(manifest is not None and end is None, "Chunk without manifest or after END")
            require(len(value) <= 4 * ((CHUNK_BYTES + 2) // 3) + 512, "Encoded chunk exceeds bound")
            row = json.loads(value)
            i = row.get("index")
            require(type(i) is int and 0 <= i < manifest["chunk_count"] and i not in chunks
                    and row.get("count") == manifest["chunk_count"] and row.get("export_id") == manifest["export_id"], "Duplicate, mixed or invalid chunk")
            require(isinstance(row.get("data"), str), "Missing encoded chunk")
            data = base64.b64decode(row["data"], validate=True)
            record = manifest["chunks"][i]
            expected_bytes = min(CHUNK_BYTES, manifest["archive_bytes"] - i * CHUNK_BYTES)
            require(len(data) == expected_bytes and record == {"index": i, "bytes": len(data), "sha256": sha(data)}
                    and row.get("sha256") == sha(data), "Chunk bytes/digest differ")
            chunks[i] = data
        elif marker == PREFIX + "END":
            require(manifest is not None and end is None and value == expected_manifest_sha256, "Invalid or duplicate END marker")
            end = value
        else:
            raise ValueError("Unknown evidence transport marker")
    require(manifest is not None and end is not None and len(chunks) == manifest["chunk_count"], "Missing or truncated notebook evidence")
    archive = b"".join(chunks[i] for i in range(manifest["chunk_count"]))
    require(len(archive) == manifest["archive_bytes"] and sha(archive) == manifest["archive_sha256"], "Reassembled archive bytes/digest differ")
    receipt = json.loads(manifest["evidence_receipt_utf8"])
    result = json.loads(manifest["final_result_utf8"])
    require(receipt.get("schema") == "rust-duty-evidence-export/v1" and receipt.get("kind") == "evidence-only"
            and receipt.get("includes_executable") is False and receipt.get("includes_raw_assets") is False
            and receipt.get("all_archived_file_hashes_verified") is True
            and receipt.get("file") == manifest["archive_file"] and receipt.get("sha256") == sha(archive)
            and receipt.get("bytes") == len(archive) and result.get("export_status") == "verified" and result.get("export") == receipt,
            "Reassembled archive/result/receipt identities differ")
    return manifest, archive


def materialize(transcript, expected_sha, output):
    raw = read_regular(transcript, MAX_TRANSCRIPT_BYTES)
    manifest, archive = decode_transcript(raw.decode(), expected_sha)
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink() and not any(p.is_symlink() for p in output.parents), "Output must be a fresh unlinked directory")
    output.mkdir(parents=True)
    (output / manifest["archive_file"]).write_bytes(archive)
    (output / "EVIDENCE_EXPORT_RECEIPT.json").write_text(manifest["evidence_receipt_utf8"])
    (output / "FINAL_RESULT.json").write_text(manifest["final_result_utf8"])
    result = {"status": "materialized", "archive_sha256": sha(archive), "archive_bytes": len(archive),
              "manifest_sha256": expected_sha, "archive_extracted": False, "gpu_shutdown_confirmed": False}
    (output / "MATERIALIZATION_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index", help="Emit only the manifest; acknowledge its notebook output before requesting chunks")
    index.add_argument("--run-root", required=True, type=Path)
    for command in ("chunk", "finish"):
        item = sub.add_parser(command, help="One separately requested, acknowledged notebook output")
        item.add_argument("--run-root", required=True, type=Path)
        item.add_argument("--manifest-sha256", required=True)
        item.add_argument("--acknowledged-through", required=True, type=int)
        if command == "chunk":
            item.add_argument("--index", required=True, type=int)
            item.add_argument("--chunk-sha256", required=True)
    recover = sub.add_parser("materialize", help="Run after GPU disconnect; verifies bytes, never extracts or executes them")
    recover.add_argument("--transcript", required=True, type=Path)
    recover.add_argument("--manifest-sha256", required=True)
    recover.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "index":
        value = emit_index(args.run_root)
    elif args.command == "chunk":
        value = emit_chunk(args.run_root, args.index, args.manifest_sha256, args.chunk_sha256, args.acknowledged_through)
    elif args.command == "finish":
        value = emit_finish(args.run_root, args.manifest_sha256, args.acknowledged_through)
    else:
        value = materialize(args.transcript, args.manifest_sha256, args.output)
    if args.command == "materialize":
        print(json.dumps(value, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
