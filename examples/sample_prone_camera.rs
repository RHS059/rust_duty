//! CPU-only normal-loader paired camera probe; no native-render or art approval.
//! Usage: sample_prone_camera ASSET.vra CAMERA.json RECEIPT.json CLIP TIME [TIME...]
//! Times are native seconds. Output is one JSON line per requested time.
use glam::Vec3;
use serde_json::json;
use std::{
    error::Error,
    io::{self, BufWriter, Write},
    path::Path,
};
use vector_range::{
    authored_prone::{camera_axes, ProneCameraTrack, ENTRY_SECONDS, PRONE_EYE_HEIGHT},
    viewmodel_animation::AnimationSet,
};

fn run() -> Result<(), Box<dyn Error>> {
    let usage = "usage: sample_prone_camera ASSET.vra CAMERA.json RECEIPT.json CLIP TIME [TIME...]";
    let mut args = std::env::args().skip(1);
    let asset = args.next().ok_or(usage)?;
    if asset == "--help" || asset == "-h" {
        println!("{usage}");
        return Ok(());
    }
    let camera = args.next().ok_or(usage)?;
    let receipt = args.next().ok_or(usage)?;
    let clip = args.next().ok_or(usage)?;
    let times = args
        .map(|arg| {
            arg.parse::<f64>()
                .ok()
                .filter(|time| time.is_finite())
                .ok_or_else(|| format!("invalid finite sample time: {arg}"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    if times.is_empty() {
        return Err(usage.into());
    }
    let (animation, _, _) = AnimationSet::load_with_companions(&asset)?;
    let selected = animation
        .clips()
        .iter()
        .find(|c| c.name == clip)
        .ok_or("missing paired clip")?;
    if selected.looping || (f64::from(selected.duration()) - ENTRY_SECONDS).abs() > 1e-6 {
        return Err("paired clip must be nonlooping with a 68/60 second key span".into());
    }
    let track = ProneCameraTrack::load(
        Path::new(&asset),
        Path::new(&camera),
        Path::new(&receipt),
        &clip,
    )?;
    let mut out = BufWriter::new(io::stdout().lock());
    for time in times {
        let entry_height = 1.016_f32;
        let sample = track.sample(time, entry_height);
        let weapon = animation.sample_clamped(&clip, sample.seconds as f32)?;
        let (forward, up) = camera_axes(-Vec3::Z, Vec3::Y, Some(sample));
        serde_json::to_writer(
            &mut out,
            &json!({
                "requested_seconds": time,
                "seconds": sample.seconds,
            "time_seconds": sample.seconds,
                "source_frame": sample.frame,
                "weapon_sample_seconds": weapon.sample_time,
                "entry_eye_height": entry_height,
                "eye_height": sample.eye_height,
                "normalized_depth_fraction": (entry_height-sample.eye_height)/(entry_height-PRONE_EYE_HEIGHT),
                "camera_local_orientation_xyzw": sample.orientation.to_array(),
            "camera_orientation": sample.orientation.to_array(),
            "orientation_convention": "inverse(initial_camera_rotation) * sampled_camera_rotation; XYZW; camera-local +X right, +Y up, -Z forward",
                "camera_local_forward": forward.to_array(),
                "camera_local_up": up.to_array(),
                "scope": "normal-loader CPU pair sampling only",
            }),
        )?;
        writeln!(out)?;
    }
    out.flush()?;
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("sample_prone_camera: {error}");
        std::process::exit(1);
    }
}
