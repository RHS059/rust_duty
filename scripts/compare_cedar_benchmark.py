#!/usr/bin/env python3
"""Compare like-for-like Cedar results; missing GPU observations stay unavailable."""
import argparse
import hashlib
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

SCHEMA = "rust-duty-cedar-benchmark/v1"
METRICS = (
    "cpu_record_ns", "cpu_submit_ns", "cpu_frame_ns", "cpu_gpu_wait_ns",
    "gpu_timestamp_ns", "recorded_draws", "recorded_triangles", "draw_calls",
    "triangles", "line_segments", "upload_bytes", "vertex_upload_bytes",
    "index_upload_bytes", "uniform_upload_bytes", "texture_upload_bytes",
)
GPU_ONLY = set(METRICS) - {"cpu_record_ns", "recorded_draws", "recorded_triangles"}
UPLOAD_PARTS = ("vertex_upload_bytes", "index_upload_bytes", "uniform_upload_bytes", "texture_upload_bytes")


def validate(report):
    if report.get("schema") != SCHEMA or report.get("status") != "complete":
        raise ValueError("requires a complete rust-duty-cedar-benchmark/v1 report")
    if report.get("mode") not in ("cpu-scene", "headless-gpu"):
        raise ValueError("unknown benchmark mode")
    for key in ("config", "path", "scene", "host", "source", "adapter", "gpu_timestamps_available"):
        if key not in report:
            raise ValueError(f"missing {key}")
    samples = report.get("samples", [])
    if not samples or len(samples) != report["config"].get("frames"):
        raise ValueError("sample count must equal nonzero config.frames")
    cycle = report["path"].get("cycle_frames", 0)
    if not isinstance(cycle, int) or cycle <= 0:
        raise ValueError("invalid path cycle")
    for index, sample in enumerate(samples):
        if sample.get("frame_index") != index or sample.get("path_frame") != index % cycle:
            raise ValueError("samples must be ordered, contiguous measured frames after warmup")
        camera = sample.get("camera_position")
        if not isinstance(camera, list) or len(camera) != 3 or not all(is_number(v) for v in camera):
            raise ValueError("invalid camera position")
        for metric in METRICS:
            if metric not in sample:
                raise ValueError(f"missing sample metric {metric}")
            value = sample[metric]
            if value is not None and (not is_number(value) or value < 0):
                raise ValueError(f"invalid sample metric {metric}")
            if report["mode"] == "cpu-scene" and metric in GPU_ONLY and value is not None:
                raise ValueError("cpu-scene cannot report issued draws, upload bytes, renderer CPU or GPU timing")
            if (metric not in GPU_ONLY or (report["mode"] == "headless-gpu" and metric != "gpu_timestamp_ns")) and value is None:
                raise ValueError(f"missing actual measurement {metric}")
        if sample["gpu_timestamp_ns"] is not None and not report["gpu_timestamps_available"]:
            raise ValueError("GPU duration without timestamp support")
        if report["mode"] == "headless-gpu" and sample["upload_bytes"] != sum(sample[k] for k in UPLOAD_PARTS):
            raise ValueError("upload byte total does not equal actual components")
    return report


def is_number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def summary(values):
    present = sorted(v for v in values if v is not None)
    if not present:
        return {"available_samples": 0, "total_samples": len(values), "mean": None, "p50": None, "p95": None, "min": None, "max": None}
    return {"available_samples": len(present), "total_samples": len(values),
            "mean": statistics.fmean(present), "p50": present[math.ceil(0.50 * len(present))-1],
            "p95": present[math.ceil(0.95 * len(present))-1], "min": min(present), "max": max(present)}


def file_identity(path):
    """Match the producer's explicit FNV identity and independently compute SHA."""
    fnv, size = 0xcbf29ce484222325, 0
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(block)
            size += len(block)
            for byte in block:
                fnv = ((fnv ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return {"name":path.name, "bytes":size, "fnv1a64":f"{fnv:016x}"}, sha.hexdigest()


def run_geometry_verifier(baseline_city, candidate_city):
    verifier = Path(__file__).resolve().parents[1] / "tools" / "verify_city_geometry.py"
    if not verifier.is_file():
        raise ValueError("geometry-parity comparison requires the stage 2 repository geometry verifier")
    result = subprocess.run([sys.executable, str(verifier), str(baseline_city), str(candidate_city)],
                            check=False, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"fresh geometry verification failed: {result.stdout[-2000:]} {result.stderr[-2000:]}")
    return json.loads(result.stdout)


def bind_geometry_parity(before, after, parity, baseline_city, candidate_city):
    """Bind metadata+mesh bytes and recompute parity; never trust JSON alone."""
    if parity.get("schema") != "rust-duty-city-geometry-parity/v1" or parity.get("passed") is not True or parity.get("placement_metadata_checked") is not True:
        raise ValueError("requires passed geometry and placement parity")
    checks = parity.get("checks", {})
    required = {"winding_sensitive_triangle_vertex_normal_rgba_multiset_equal"}
    required.update(f"original_level_{field}_fields_equal" for field in ("colliders", "buildings", "spawn", "supply_position", "landmarks", "bounds"))
    required.update(f"original_layout_{field}_fields_equal" for field in ("buildings", "instances"))
    if not required.issubset(checks) or not all(value is True for value in checks.values()):
        raise ValueError("incomplete or failed geometry parity checks")
    for side, report, directory in (("baseline", before, baseline_city), ("candidate", after, candidate_city)):
        directory = Path(directory)
        if not directory.is_dir():
            raise ValueError("geometry parity requires city directories with placement metadata")
        identities = []
        mesh_sha = None
        for name in ("level.json", "meshes.bin"):
            identity, sha = file_identity(directory / name)
            identities.append(identity)
            if name == "meshes.bin":
                mesh_sha = sha
        if report["scene"]["assets"] != identities:
            raise ValueError(f"{side} benchmark asset identities do not match supplied city files; lighting/source substitution is not allowed")
        if parity.get(side, {}).get("mesh_sha256") != mesh_sha:
            raise ValueError(f"{side} parity SHA256 does not bind the measured mesh")
    if parity["baseline"].get("sorted_triangle_hashes_sha256") != parity["candidate"].get("sorted_triangle_hashes_sha256"):
        raise ValueError("geometry triangle digests differ")
    fresh = run_geometry_verifier(baseline_city, candidate_city)
    if fresh != parity:
        raise ValueError("supplied parity report does not equal fresh independent geometry/placement verification")
    return {"schema":parity["schema"], "freshly_verified":True, "placement_metadata_checked":True,
            "baseline_mesh_sha256":parity["baseline"]["mesh_sha256"],
            "candidate_mesh_sha256":parity["candidate"]["mesh_sha256"],
            "sorted_triangle_hashes_sha256":parity["baseline"]["sorted_triangle_hashes_sha256"]}


def compare(before, after, verified_geometry=None):
    validate(before)
    validate(after)
    # A new source revision is the independent variable. Machine, driver,
    # content, path and workload configuration must otherwise remain identical.
    for key in ("mode", "config", "path", "adapter", "host"):
        if before[key] != after[key]:
            raise ValueError(f"incomparable {key}: baseline and candidate differ")
    if before["scene"]["assets"] != after["scene"]["assets"] and verified_geometry is None:
        raise ValueError("incomparable scene assets; reencoding requires explicit bound, freshly recomputed geometry parity")
    if not before["host"].get("machine_label"):
        raise ValueError("set RUST_DUTY_BENCH_MACHINE to identify the measured machine")
    if [s["camera_position"] for s in before["samples"]] != [s["camera_position"] for s in after["samples"]]:
        raise ValueError("incomparable camera path samples")
    metrics = {}
    for metric in METRICS:
        left = summary([s[metric] for s in before["samples"]])
        right = summary([s[metric] for s in after["samples"]])
        # Partial GPU coverage is visible, but never compare mismatched subsets.
        paired = all((a[metric] is None) == (b[metric] is None) for a, b in zip(before["samples"], after["samples"]))
        comparable = paired and left["available_samples"] == left["total_samples"] and right["available_samples"] == right["total_samples"]
        delta = right["mean"] - left["mean"] if comparable else None
        percent = 100. * delta / left["mean"] if comparable and left["mean"] else None
        metrics[metric] = {"before":left, "after":right, "mean_delta":delta, "mean_delta_percent":percent}
    return {"schema":"rust-duty-cedar-comparison/v1", "before_source":before["source"], "after_source":after["source"],
            "mode":before["mode"], "metrics":metrics, "scene_reencoding_evidence":verified_geometry,
            "interpretation":"Negative deltas mean less time/work/upload traffic. Null is unavailable, never zero. p50/p95 use nearest rank. Per-frame fence/readback affects throughput; no gameplay FPS, display cadence or performance pass is inferred."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--geometry-parity", type=Path, help="Explicit geometry-reencoding comparison; report is rebound and recomputed")
    parser.add_argument("--baseline-city", type=Path)
    parser.add_argument("--candidate-city", type=Path)
    args = parser.parse_args()
    try:
        before, after = validate(json.loads(args.before.read_text())), validate(json.loads(args.after.read_text()))
        geometry_options = (args.geometry_parity, args.baseline_city, args.candidate_city)
        if any(geometry_options) and not all(geometry_options):
            raise ValueError("--geometry-parity requires both --baseline-city and --candidate-city")
        evidence = None
        if args.geometry_parity:
            evidence = bind_geometry_parity(before, after, json.loads(args.geometry_parity.read_text()), args.baseline_city, args.candidate_city)
        result = compare(before, after, evidence)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
