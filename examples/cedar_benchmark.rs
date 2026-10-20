//! Deterministic production-facade Cedar Junction benchmark. No simulation ticks.
use glam::Vec3;
use serde_json::{json, Value};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    time::Instant,
};
use vector_range::{
    city_level::{CityLevel, CITY_FAR_PLANE},
    draw::{facade, Command, DrawList},
};
#[cfg(feature = "wgpu-runtime")]
use vector_range::{
    draw::Renderer,
    render::{BackendSelection, WgpuRenderer},
};

const PATH_ID: &str = "cedar-junction-streets-v1";
const PATH_FRAMES: u32 = 720;
const WAYPOINTS: [[f32; 3]; 9] = [
    [0., 2., 38.],
    [0., 2., -38.],
    [38., 3., -38.],
    [38., 3., 38.],
    [0., 8., 68.],
    [-38., 3., 38.],
    [-38., 3., -38.],
    [0., 8., -68.],
    [0., 2., 38.],
];
#[derive(Debug)]
struct Options {
    mode: String,
    output: PathBuf,
    level: PathBuf,
    width: u32,
    height: u32,
    frames: u32,
    warmup: u32,
    renderer: String,
    fallback: bool,
}
impl Options {
    fn parse(args: impl IntoIterator<Item = String>) -> Result<Self, String> {
        let mut out = Self {
            mode: "headless-gpu".into(),
            output: PathBuf::new(),
            level: Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("assets/levels/cedar_junction/level.json"),
            width: 1280,
            height: 720,
            frames: PATH_FRAMES,
            warmup: 60,
            renderer: "auto".into(),
            fallback: false,
        };
        let mut seen = std::collections::HashSet::new();
        let mut args = args.into_iter();
        while let Some(key) = args.next() {
            if !seen.insert(key.clone()) {
                return Err(format!("duplicate option {key}"));
            }
            if key == "--force-fallback-adapter" {
                out.fallback = true;
                continue;
            }
            let value = args
                .next()
                .ok_or_else(|| format!("missing value for {key}"))?;
            match key.as_str() {
                "--mode" => out.mode = value,
                "--output" => out.output = value.into(),
                "--level" | "--level-file" => out.level = value.into(),
                "--renderer" => out.renderer = value,
                "--width" => out.width = value.parse().map_err(|_| "invalid width")?,
                "--height" => out.height = value.parse().map_err(|_| "invalid height")?,
                "--frames" => out.frames = value.parse().map_err(|_| "invalid frames")?,
                "--warmup" => out.warmup = value.parse().map_err(|_| "invalid warmup")?,
                _ => return Err(format!("unknown option {key}")),
            }
        }
        if !matches!(out.mode.as_str(), "cpu-scene" | "headless-gpu") {
            return Err("--mode must be cpu-scene or headless-gpu".into());
        }
        if out.output.as_os_str().is_empty()
            || out.width == 0
            || out.height == 0
            || out.frames == 0
            || out.frames > 100_000
            || out.warmup > 100_000
        {
            return Err(
                "require --output NEW_FILE, nonzero extent, 1..100000 frames and <=100000 warmup"
                    .into(),
            );
        }
        if out.mode == "cpu-scene" && (out.fallback || out.renderer != "auto") {
            return Err("GPU selection options do not apply to cpu-scene mode".into());
        }
        Ok(out)
    }
}
fn camera_at(frame: u32) -> facade::Camera3D {
    let phase = frame % PATH_FRAMES;
    let segment_frames = PATH_FRAMES / (WAYPOINTS.len() as u32 - 1);
    let segment = (phase / segment_frames) as usize;
    let t = (phase % segment_frames) as f32 / segment_frames as f32;
    let position =
        Vec3::from_array(WAYPOINTS[segment]).lerp(Vec3::from_array(WAYPOINTS[segment + 1]), t);
    // Look along each street with a slight downward pitch; no wall-clock input.
    let direction = (Vec3::from_array(WAYPOINTS[segment + 1])
        - Vec3::from_array(WAYPOINTS[segment]))
    .normalize();
    facade::Camera3D {
        position,
        target: position + direction * 20. - Vec3::Y * 1.,
        up: Vec3::Y,
        fovy: 70_f32.to_radians(),
        z_near: 0.05,
        z_far: CITY_FAR_PLANE,
        ..Default::default()
    }
}
fn record(city: &CityLevel, frame: u32, width: u32, height: u32) -> Result<DrawList, String> {
    let camera = camera_at(frame);
    facade::begin_frame(width, height, 1.)?;
    facade::set_camera(&camera);
    facade::clear_background(facade::Color::new(0.42, 0.57, 0.70, 1.));
    let result = facade::current_camera()
        .map(|draw_camera| city.draw(camera.position, draw_camera.view_projection));
    let list = facade::take_draw_list(); // Consume recorder even on error.
    result?;
    list
}
fn recorded_counts(list: &DrawList) -> (u64, u64) {
    let mut counts = (0, 0);
    for command in &list.commands {
        if let Command::Mesh { mesh, .. } = command {
            counts.0 += 1;
            counts.1 += mesh.indices.len() as u64 / 3;
        }
    }
    counts
}
/// A stable content identity, explicitly not a cryptographic authenticity check.
fn file_identity(path: &Path) -> Result<Value, String> {
    let mut file = fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut hash = 0xcbf29ce484222325_u64;
    let mut size = 0_u64;
    let mut buffer = [0; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
        if count == 0 {
            break;
        }
        size += count as u64;
        for &byte in &buffer[..count] {
            hash = (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3);
        }
    }
    Ok(
        json!({"name":path.file_name().and_then(|s| s.to_str()), "bytes":size, "fnv1a64":format!("{hash:016x}")}),
    )
}
fn ns(start: Instant) -> u64 {
    start.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64
}
fn run(options: Options) -> Result<(), String> {
    // Refuse to destroy a previous baseline, including when a later step fails.
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&options.output)
        .map_err(|e| format!("create {}: {e}", options.output.display()))?;
    let result = collect(&options);
    let report = match result {
        Ok(report) => report,
        Err(error) => {
            let failure = json!({"schema":"rust-duty-cedar-benchmark/v1", "status":"failed", "error":error, "mode":options.mode});
            serde_json::to_writer_pretty(&mut output, &failure).map_err(|e| e.to_string())?;
            return Err(error);
        }
    };
    serde_json::to_writer_pretty(&mut output, &report).map_err(|e| e.to_string())?;
    println!(
        "{} frames written to {} ({})",
        options.frames,
        options.output.display(),
        options.mode
    );
    Ok(())
}
fn collect(options: &Options) -> Result<Value, String> {
    let city = CityLevel::load(&options.level)?;
    let mesh_path = options.level.with_file_name("lighting.bin");
    let mesh_path = if mesh_path.exists() {
        mesh_path
    } else {
        options.level.with_file_name("meshes.bin")
    };
    let assets = json!([file_identity(&options.level)?, file_identity(&mesh_path)?]);
    #[cfg(feature = "wgpu-runtime")]
    let mut renderer = if options.mode == "headless-gpu" {
        Some(pollster::block_on(WgpuRenderer::new_headless_profiled(
            options.width,
            options.height,
            options.renderer.parse::<BackendSelection>()?,
            options.fallback,
        ))?)
    } else {
        None
    };
    #[cfg(not(feature = "wgpu-runtime"))]
    if options.mode == "headless-gpu" {
        return Err("headless-gpu requires --features wgpu-runtime".into());
    }
    let mut samples = Vec::with_capacity(options.frames as usize);
    for iteration in 0..options.warmup + options.frames {
        let warmup = iteration < options.warmup;
        let frame = if warmup {
            iteration
        } else {
            iteration - options.warmup
        };
        let total_start = Instant::now();
        let recording_start = Instant::now();
        let list = record(&city, frame, options.width, options.height)?;
        let recording_ns = ns(recording_start);
        #[cfg(feature = "wgpu-runtime")]
        let submitted = if let Some(renderer) = &mut renderer {
            let submit_start = Instant::now();
            renderer.submit(&list)?;
            let submit_ns = ns(submit_start);
            let frame_ns = ns(total_start);
            let wait_start = Instant::now();
            renderer.wait_for_frame()?;
            let wait_ns = ns(wait_start);
            let metrics = renderer
                .last_frame_metrics()
                .ok_or("missing renderer metrics")?
                .clone();
            Some((submit_ns, frame_ns, wait_ns, metrics))
        } else {
            None
        };
        let (recorded_draws, recorded_triangles) = recorded_counts(&list);
        #[allow(unused_mut)]
        let mut sample = json!({"frame_index":frame, "path_frame":frame % PATH_FRAMES,
            "camera_position":camera_at(frame).position.to_array(), "cpu_record_ns":recording_ns,
            "cpu_submit_ns":null, "cpu_frame_ns":null, "cpu_gpu_wait_ns":null,
            "recorded_draws":recorded_draws, "recorded_triangles":recorded_triangles,
            "draw_calls":null, "triangles":null, "line_segments":null, "upload_bytes":null,
            "vertex_upload_bytes":null, "index_upload_bytes":null, "uniform_upload_bytes":null,
            "texture_upload_bytes":null, "gpu_timestamp_ns":null});
        #[cfg(feature = "wgpu-runtime")]
        if let Some((submit_ns, frame_ns, wait_ns, m)) = submitted {
            sample["cpu_submit_ns"] = json!(submit_ns);
            sample["cpu_frame_ns"] = json!(frame_ns);
            sample["cpu_gpu_wait_ns"] = json!(wait_ns);
            sample["draw_calls"] = json!(m.draw_calls);
            sample["triangles"] = json!(m.triangles);
            sample["line_segments"] = json!(m.line_segments);
            sample["upload_bytes"] = json!(m.upload_bytes());
            sample["vertex_upload_bytes"] = json!(m.vertex_upload_bytes);
            sample["index_upload_bytes"] = json!(m.index_upload_bytes);
            sample["uniform_upload_bytes"] = json!(m.uniform_upload_bytes);
            sample["texture_upload_bytes"] = json!(m.texture_upload_bytes);
            sample["gpu_timestamp_ns"] = json!(m.gpu_timestamp_ns);
        }
        // cpu-scene measures only recording, not renderer preparation or encoding.
        let _ = total_start;
        if !warmup {
            samples.push(sample);
        }
    }
    #[allow(unused_mut)]
    let mut adapter = Value::Null;
    #[allow(unused_mut)]
    let mut gpu_timestamps_available = false;
    #[cfg(feature = "wgpu-runtime")]
    if let Some(renderer) = renderer {
        adapter = renderer.adapter_evidence().clone();
        gpu_timestamps_available = renderer.gpu_timestamps_available();
    }
    Ok(json!({
        "schema":"rust-duty-cedar-benchmark/v1", "status":"complete", "mode":options.mode,
        "source":{"revision":option_env!("RUST_DUTY_BENCH_REVISION"), "dirty":option_env!("RUST_DUTY_BENCH_DIRTY"), "build_label":vector_range::BUILD_LABEL},
        "host":{"os":std::env::consts::OS, "arch":std::env::consts::ARCH, "machine_label":std::env::var("RUST_DUTY_BENCH_MACHINE").ok(), "profile":if cfg!(debug_assertions) {"debug"} else {"release"}},
        "scene":{"name":city.name, "assets":assets, "chunks":city.chunks.len()},
        "path":{"id":PATH_ID, "cycle_frames":PATH_FRAMES, "waypoints":WAYPOINTS, "fovy_degrees":70, "near":0.05, "far":CITY_FAR_PLANE},
        "config":{"width":options.width, "height":options.height, "frames":options.frames, "warmup_frames":options.warmup, "presentation":false, "gpu_completion_fence_per_frame":options.mode=="headless-gpu"},
        "adapter":adapter, "gpu_timestamps_available":gpu_timestamps_available,
        "interpretation":"CPU spans are monotonic host wall time, never GPU time. cpu_frame_ns covers recording and renderer submit, excluding explicit wait and report/count bookkeeping. cpu_gpu_wait_ns is host fence/readback wait, not GPU duration. GPU timestamps bracket encoded frame commands, excluding host upload/planning, query resolve/readback and presentation. Uploads count actual payload bytes including transform alignment, excluding allocation padding and initialization. cpu-scene has no issued/GPU/upload metrics. No gameplay FPS or display cadence claim.",
        "samples":samples,
    }))
}
fn main() {
    if let Err(error) = Options::parse(std::env::args().skip(1)).and_then(run) {
        eprintln!("cedar_benchmark: {error}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn path_repeats_exactly_and_is_frame_indexed() {
        for frame in 0..PATH_FRAMES {
            let a = camera_at(frame);
            let b = camera_at(frame + PATH_FRAMES);
            assert_eq!(a.position, b.position);
            assert_eq!(a.target, b.target);
            assert!(a.position.is_finite() && a.target.is_finite());
            assert!((a.target - a.position).cross(a.up).length_squared() > 0.);
        }
        assert_eq!(camera_at(0).position, Vec3::new(0., 2., 38.));
        assert_eq!(camera_at(90).position, Vec3::new(0., 2., -38.));
    }
    #[test]
    fn options_reject_zero_samples_duplicate_and_gpu_options_in_cpu_mode() {
        let parse = |args: &[&str]| Options::parse(args.iter().map(|s| s.to_string()));
        assert!(parse(&["--output", "x", "--frames", "0"]).is_err());
        assert!(parse(&["--output", "x", "--frames", "1", "--frames", "2"]).is_err());
        assert!(parse(&[
            "--output",
            "x",
            "--mode",
            "cpu-scene",
            "--force-fallback-adapter"
        ])
        .is_err());
        let options = parse(&[
            "--output",
            "x",
            "--mode",
            "cpu-scene",
            "--frames",
            "3",
            "--warmup",
            "0",
        ])
        .unwrap();
        assert_eq!(options.frames, 3);
        assert_eq!(options.warmup, 0);
    }
    #[test]
    fn source_recording_uses_real_city_culling_and_facade() {
        use vector_range::{
            city_level::CityChunk,
            draw::{Color, Mesh, Vertex},
            sim::Aabb,
        };
        let triangle = Mesh {
            vertices: vec![
                Vertex::new(-1., 0., 0., 0., 0., Color::WHITE),
                Vertex::new(1., 0., 0., 0., 0., Color::WHITE),
                Vertex::new(0., 3., 0., 0., 0., Color::WHITE),
            ],
            indices: vec![0, 1, 2],
            texture: None,
        };
        let city = CityLevel {
            name: "fixture".into(),
            spawn_position: Vec3::ZERO,
            spawn_yaw: 0.,
            supply_position: Vec3::ZERO,
            colliders: vec![],
            chunks: vec![CityChunk {
                bounds: Aabb {
                    min: Vec3::new(-1., 0., -0.1),
                    max: Vec3::new(1., 3., 0.1),
                },
                mesh: triangle,
            }],
        };
        let first = record(&city, 0, 1280, 720).unwrap();
        let repeated = record(&city, PATH_FRAMES, 1280, 720).unwrap();
        assert_eq!(recorded_counts(&first), (1, 1));
        assert_eq!(recorded_counts(&repeated), (1, 1));
        assert!(first
            .commands
            .iter()
            .all(|c| !matches!(c, Command::Capture { .. })));
    }
}
