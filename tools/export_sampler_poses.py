#!/usr/bin/env python3
"""Export actual Rust sampler values for frame comparison; never approximates Rust."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BASELINE_COMMIT = "573e7edf19097cdd458d5b9bf8f25be2c7f94805"
BASELINE_BLOB = "843efd95eb442b9b10c7f0d35fe4b73b530880a4"
SOURCE_DEFAULT = Path(__file__).resolve().parents[1] / "src" / "weapon_animation.rs"
VECTORS = ["weapon_translation", "weapon_euler_yxz", "magazine_translation", "right_grip", "left_grip", "bolt_translation"]
CHANNELS = [f"{name}_{axis}" for name in VECTORS for axis in ("yxz" if name == "weapon_euler_yxz" else "xyz")] + ["trigger_pull"]
RUST_MAIN = r'''
use std::io::{self, BufRead};
use weapon_animation::{sample_weapon_animation, AnimationInput};
fn main() -> Result<(), Box<dyn std::error::Error>> {
    for line in io::stdin().lock().lines() {
        let line = line?;
        let fields: Vec<&str> = line.split('\t').collect();
        if fields.len() != 6 { return Err("expected six tab-separated input fields".into()); }
        let reload_progress = if fields[0] == "none" { None } else { Some(fields[0].parse::<f32>()?) };
        let p = sample_weapon_animation(AnimationInput {
            reload_progress,
            reload_credit_fraction: fields[1].parse()?,
            empty_reload: fields[2].parse()?,
            ads: fields[3].parse()?,
            recoil: fields[4].parse()?,
            sprint: fields[5].parse()?,
        });
        let values = [p.weapon_translation, p.weapon_euler_yxz, p.magazine_translation,
                      p.right_grip, p.left_grip, p.bolt_translation];
        let mut fields: Vec<String> = values.iter().flat_map(|a| a.iter()).map(|v| v.to_string()).collect();
        fields.push(p.trigger_pull.to_string());
        println!("{}", fields.join("\t"));
    }
    Ok(())
}
'''


def finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def unit(value: object, label: str) -> float:
    value = finite(value, label)
    if not 0 <= value <= 1:
        raise ValueError(f"{label} must be in [0,1]")
    return value


def validate_schedule(data: dict) -> list[dict]:
    if data.get("schema") != "weapon-frame-schedule/v1":
        raise ValueError("unknown schedule schema")
    if not isinstance(data.get("samples"), list) or not data["samples"]:
        raise ValueError("schedule requires a nonempty samples list")
    seen = set()
    checked = []
    for index, row in enumerate(data["samples"]):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in seen:
            raise ValueError(f"sample {index} needs a unique nonempty id")
        seen.add(row["id"])
        kind = row.get("kind")
        if kind not in {"tactical", "empty", "no_reload"}:
            raise ValueError(f"{row['id']}: kind must be tactical, empty, or no_reload")
        progress = row.get("reload_progress")
        if kind == "no_reload":
            if progress is not None:
                raise ValueError("no_reload progress must be null")
        else:
            progress = unit(progress, "reload_progress")
        reference_seconds = row.get("reference_seconds")
        if reference_seconds is not None:
            reference_seconds = finite(reference_seconds, "reference_seconds")
            if reference_seconds < 0:
                raise ValueError("reference_seconds must be nonnegative")
        frame = row.get("reference_frame_index")
        if frame is not None and (isinstance(frame, bool) or not isinstance(frame, int) or frame < 0):
            raise ValueError("reference_frame_index must be a nonnegative integer or null")
        checked.append({**row, "reload_progress": progress, "reference_seconds": reference_seconds,
                        "reload_credit_fraction": unit(row.get("reload_credit_fraction", 1.1 / 2.029), "reload_credit_fraction"),
                        **{key: unit(row.get(key, 0.0), key) for key in ("ads", "recoil", "sprint")}})
    return checked


def make_schedule(hz: float) -> dict:
    if not math.isfinite(hz) or hz <= 0 or hz > 1000:
        raise ValueError("sampling Hz must be finite and in (0,1000]")
    samples = []
    ranges = [("tactical", 7.8, 9.8, 2.029, {8.7: "insert_window_start", 8.9: "insert_window_end"}),
              ("empty", 14.0, 16.2, 2.359, {14.3: "discard_window_start", 14.4: "discard_window_end",
                                           15.0: "insert_window_start", 15.3: "insert_window_end",
                                           15.5: "receiver_window_start", 15.7: "receiver_window_end"})]
    for kind, start, end, candidate_duration, landmarks in ranges:
        duration = end - start
        for alignment in ("elapsed_from_onset", "normalized_phase"):
            span = max(duration, candidate_duration) if alignment == "elapsed_from_onset" else duration
            times = {round(start + i / hz, 9): "dense_sample" for i in range(math.ceil(span * hz))}
            times.update({start: "reload_start", end: "reference_reload_end", start + span: "comparison_end"})
            times.update(landmarks)
            for q in (0.1, 0.25, 0.5, 0.75, 0.9):
                times.setdefault(round(start + duration * q, 9), "coarse_reference_phase")
            for index, (reference, label) in enumerate(sorted(times.items())):
                elapsed = reference - start
                ref_phase = max(0.0, min(1.0, elapsed / duration))
                candidate_elapsed = elapsed if alignment == "elapsed_from_onset" else ref_phase * candidate_duration
                candidate_phase = max(0.0, min(1.0, candidate_elapsed / candidate_duration))
                samples.append({"id": f"{kind}_{alignment}_{index:03d}", "kind": kind, "label": label,
                                "alignment_mode": alignment,
                                "reference_seconds": reference,
                                "reference_elapsed_seconds": elapsed,
                                "reference_onset_seconds": start, "reference_end_seconds": end,
                                "reference_duration_seconds": duration, "reference_phase": ref_phase,
                                "candidate_duration_seconds": candidate_duration,
                                "duration_delta_seconds": candidate_duration - duration,
                                "candidate_requested_elapsed_seconds": candidate_elapsed,
                                "reference_frame_index": None, "reference_image": None,
                                "candidate_image": None, "candidate_actual_pts_seconds": None,
                                "capture": {"resolution": None, "playable_viewport_bounds": None,
                                            "camera_fov_degrees": None, "viewmodel_fov_degrees": None},
                                "reload_progress": candidate_phase,
                                "ads": 0.0, "recoil": 0.0, "sprint": 0.0})
    return {"schema": "weapon-frame-schedule/v1", "baseline_commit": BASELINE_COMMIT,
            "sampling_hz": hz,
            "reference_status": "Secondhand approximate Aella intervals; replace with decoded frame PTS/landmarks before claiming measured match",
            "alignment": "Primary elapsed_from_onset pairs preserve timing mismatch and candidate tails. Secondary normalized_phase pairs compare path shape with duration deltas explicit. Neither establishes engine equivalence.",
            "samples": samples}


def rust_string(value: str) -> str:
    hashes = ""
    while '"' + hashes in value:
        hashes += "#"
    return f'r{hashes}"{value}"{hashes}'


def export(source: Path, schedule: dict, output: Path, rustc: str, expected_blob: str | None) -> None:
    samples = validate_schedule(schedule)
    if output.suffix.lower() != ".json":
        raise ValueError("output path must end in .json; companion .csv is written separately")
    source = source.resolve(strict=True)
    content = source.read_bytes()
    source_sha = hashlib.sha256(content).hexdigest()
    has_hand_modes = b"pub left_hand_blend:" in content
    has_magazine_rotation = b"pub magazine_euler_yxz:" in content
    rotation_columns = ["magazine_yaw", "magazine_pitch", "magazine_roll"] if has_magazine_rotation else []
    extras = []
    for name, size, expression in [
        ("seated_magazine_translation",3,"p.seated_magazine_translation"),
        ("seated_magazine_euler_yxz",3,"p.seated_magazine_euler_yxz"),
        ("left_hand_euler_yxz",3,"p.left_hand_euler_yxz"),
        ("magazine_visibility",2,"p.magazine_visibility.map(|v| if v {1.0} else {0.0})"),
        ("left_hand_orientation_xyzw",4,"weapon_animation::effective_hand_orientation(&p)"),
        ("magazine_orientation_xyzw",4,"weapon_animation::effective_magazine_orientation(&p)"),
    ]:
        if ("pub " + name + ":").encode() in content:
            extras.append((name,size,expression))
    extra_columns = [f"{name}_{i}" for name,size,_ in extras for i in range(size)]
    hand_columns = ["left_hand_support", "left_hand_magazine", "left_hand_receiver", "left_hand_open"] if has_hand_modes else []
    blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    if expected_blob and blob != expected_blob:
        raise ValueError(f"source blob {blob} differs from requested {expected_blob}; use the intended source pin")
    compiler = shutil.which(rustc)
    if compiler is None:
        raise RuntimeError(f"Rust compiler '{rustc}' unavailable; no poses were generated. Run in the native Rust build environment.")
    compiler_version = subprocess.run([compiler, "--version"], check=True, capture_output=True, text=True).stdout.strip()
    inputs = []
    for row in samples:
        inputs.append("\t".join(["none" if row["reload_progress"] is None else repr(row["reload_progress"]),
                                 repr(row["reload_credit_fraction"]), str(row["kind"] == "empty").lower(),
                                 *[repr(row[key]) for key in ("ads", "recoil", "sprint")]]))
    with tempfile.TemporaryDirectory(prefix="weapon-pose-export-") as temporary:
        work = Path(temporary)
        harness = work / "sample_poses.rs"
        rust_main = RUST_MAIN
        if has_hand_modes:
            rust_main = rust_main.replace('        println!("{}", fields.join("\\t"));',
                                          '        fields.extend(p.left_hand_blend.iter().map(|v| v.to_string()));\n        println!("{}", fields.join("\\t"));')
        if has_magazine_rotation:
            rust_main = rust_main.replace('        println!("{}", fields.join("\\t"));', '        fields.extend(p.magazine_euler_yxz.iter().map(|v| v.to_string()));\n        println!("{}", fields.join("\\t"));')
        for _, _, expression in extras:
            rust_main = rust_main.replace('        println!("{}", fields.join("\\t"));', f'        fields.extend(({expression}).iter().map(|v| v.to_string()));\n        println!("{{}}", fields.join("\\t"));')
        harness.write_text(f"#[allow(dead_code)]\n#[path = {rust_string(str(source))}]\nmod weapon_animation;\n" + rust_main, encoding="utf-8")
        binary = work / ("sample_poses.exe" if sys.platform == "win32" else "sample_poses")
        subprocess.run([compiler, "--edition=2021", str(harness), "-o", str(binary)], check=True)
        raw = subprocess.run([str(binary)], input="\n".join(inputs) + "\n", check=True, capture_output=True, text=True).stdout
    if source.read_bytes() != content:
        raise RuntimeError("source changed during export; discard mixed-source result and rerun")
    lines = raw.splitlines()
    if len(lines) != len(samples):
        raise RuntimeError("sampler row count mismatch")
    result = []
    for row, line in zip(samples, lines):
        numbers = [float(v) for v in line.split("\t")]
        if len(numbers) != 19 + len(hand_columns) + len(rotation_columns) + len(extra_columns) or not all(math.isfinite(v) for v in numbers):
            raise RuntimeError(f"non-finite or incomplete pose for {row['id']}")
        pose = {name: numbers[i * 3:i * 3 + 3] for i, name in enumerate(VECTORS)}
        pose["trigger_pull"] = numbers[18]
        if has_hand_modes:
            pose["left_hand_blend"] = numbers[19:23]
        if has_magazine_rotation:
            pose["magazine_euler_yxz"] = numbers[19 + len(hand_columns):22 + len(hand_columns)]
        cursor = 19 + len(hand_columns) + len(rotation_columns)
        for name,size,_ in extras:
            pose[name] = numbers[cursor:cursor+size]
            if name == "magazine_visibility": pose[name] = [bool(v) for v in pose[name]]
            cursor += size
        candidate = None if row["reload_progress"] is None else row["reload_progress"] * (2.359 if row["kind"] == "empty" else 2.029)
        result.append({**row, "candidate_elapsed_seconds": candidate, "pose": pose})
    payload = {"schema": "weapon-pose-export/v1", "source_blob": blob, "source_sha256": source_sha,
               "compiler": compiler_version, "source_file": str(source),
               "hand_mode_order": ["support", "magazine", "receiver", "open"] if has_hand_modes else None,
               "schedule": {k: v for k, v in schedule.items() if k != "samples"},
               "units": {"translation": "metres", "euler": "radians, yaw(Y), pitch(X), roll(Z), YXZ composition"},
               "space": "+X right, +Y up, -Z barrel; root is additive AFTER renderer hip/ADS; grips are absolute weapon-local and inherit the same animated root",
               "limits": "Standalone Rust hand/prop sampler output. The renderer replaces its legacy reload root via reference_motion.rs; use the export_presentation Cargo example for actual integrated roots/clocks. No camera/FOV/base hip/ADS/rig transform included. Do not compare these local-space coordinates directly against image pixels.",
               "samples": result}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        metadata_columns = ["id", "kind", "label", "alignment_mode", "reference_seconds", "reference_frame_index",
                            "reference_elapsed_seconds", "reference_duration_seconds", "candidate_duration_seconds",
                            "duration_delta_seconds", "reload_progress", "candidate_elapsed_seconds"]
        writer.writerow(metadata_columns + CHANNELS + hand_columns + rotation_columns + extra_columns)
        for row in result:
            flat = [v for name in VECTORS for v in row["pose"][name]] + [row["pose"]["trigger_pull"]] + row["pose"].get("left_hand_blend", []) + row["pose"].get("magazine_euler_yxz", [])
            writer.writerow([row.get(key, "") for key in metadata_columns] + flat + [v for name,_,_ in extras for v in row["pose"][name]])
    print(f"Exported {len(result)} actual Rust poses to {output} and {csv_path}; source blob {blob}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("schedule", help="Create a provisional event-normalized schedule, not observed frame measurements")
    build.add_argument("--hz", type=float, default=60000 / 1001)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("export", help="Compile and call the exact supplied Rust source")
    run.add_argument("--source", type=Path, default=SOURCE_DEFAULT)
    run.add_argument("--schedule", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--rustc", default="rustc")
    run.add_argument("--expected-blob", help="Optional exact Git blob guard; baseline blob is " + BASELINE_BLOB)
    args = parser.parse_args()
    try:
        if args.action == "schedule":
            data = make_schedule(args.hz)
            validate_schedule(data)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            print(f"Wrote {len(data['samples'])} provisional comparison samples to {args.output}; no images inspected or pose values fabricated")
        else:
            export(args.source, json.loads(args.schedule.read_text(encoding="utf-8")), args.output, args.rustc, args.expected_blob)
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
