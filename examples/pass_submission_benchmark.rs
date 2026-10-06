//! Bounded native submission diagnostic, not gameplay FPS or GPU timestamp timing.
// Test-only inclusion exercises the actual private planner without modifying its API.
#[cfg(all(test, feature = "wgpu-runtime"))]
use vector_range::draw;
#[cfg(all(test, feature = "wgpu-runtime"))]
#[allow(dead_code)]
#[path = "../src/render/arena.rs"]
mod arena;
#[cfg(all(test, feature = "wgpu-runtime"))]
#[allow(dead_code)]
#[path = "../src/render/lines.rs"]
mod lines;
#[cfg(all(test, feature = "wgpu-runtime"))]
#[allow(dead_code)]
#[path = "../src/render/plan.rs"]
mod plan;
#[cfg(all(test, feature = "wgpu-runtime"))]
#[allow(dead_code)]
#[path = "../src/render/sprite2d.rs"]
mod sprite2d;
#[cfg(all(test, feature = "wgpu-runtime"))]
#[allow(dead_code)]
#[path = "../src/render/text.rs"]
mod text;
#[cfg(feature = "wgpu-runtime")]
mod diagnostic {
    use glam::{Mat4, Vec2, Vec3};
    use serde_json::json;
    use std::{fs, path::PathBuf, time::Instant};
    use vector_range::{
        draw::{
            BlendMode, Camera, Color, DrawList, Line, Mesh, Rect, RenderTarget, Renderer, Vertex,
        },
        render::{BackendSelection, WgpuRenderer},
    };

    const WIDTH: u32 = 320;
    const HEIGHT: u32 = 180;
    const WARMUP: usize = 2;
    const FRAMES: usize = 4;
    const FIXTURE: &str = "pass-submission-synthetic-305-v1";

    fn quad(x: f32, y: f32, z: f32, color: Color) -> Mesh {
        Mesh {
            vertices: vec![
                Vertex::new(x, y, z, 0., 0., color),
                Vertex::new(x + 16., y, z, 1., 0., color),
                Vertex::new(x + 16., y + 12., z, 1., 1., color),
                Vertex::new(x, y + 12., z, 0., 1., color),
            ],
            indices: vec![0, 1, 2, 0, 2, 3],
            texture: None,
        }
    }

    fn fixture() -> Result<DrawList, String> {
        let mut list = DrawList::new(WIDTH, HEIGHT);
        let mut world = Camera::screen(WIDTH, HEIGHT);
        world.depth_test = true;
        list.camera(world.clone());
        list.clear(Color::new(0.02, 0.03, 0.05, 1.));
        for i in 0..80 {
            // An identical camera is still an explicit ordered pass boundary.
            if i == 40 {
                list.camera(world.clone());
            }
            let blend = [BlendMode::Opaque, BlendMode::Alpha, BlendMode::Additive][i % 3];
            list.draw_mesh(
                &quad(
                    (i % 16 * 18) as f32,
                    (i / 16 * 14) as f32,
                    (i % 5) as f32 * 0.1,
                    Color::new((i % 7) as f32 / 7., 0.4, 0.7, 0.65),
                ),
                Mat4::IDENTITY,
                blend,
            );
        }
        for i in 0..20 {
            list.draw_lines(
                &[Line {
                    start: Vec3::new((i * 15) as f32, 0., 0.8),
                    end: Vec3::new((i * 15 + 7) as f32, 76., 0.8),
                    color: Color::new(0.3, 0.8, 0.2, 1.),
                }],
                Mat4::IDENTITY,
            );
        }
        let target = RenderTarget::new(96, 64, true)?;
        let mut camera = Camera::screen(96, 64);
        camera.target = Some(target.clone());
        camera.depth_test = true;
        list.camera(camera.clone());
        list.clear(Color::TRANSPARENT);
        for i in 0..24 {
            list.draw_mesh(
                &quad(
                    (i % 6 * 14) as f32,
                    (i / 6 * 13) as f32,
                    (i % 3) as f32 * 0.1,
                    Color::new(0.8, (i % 5) as f32 / 5., 0.15, 0.6),
                ),
                Mat4::IDENTITY,
                if i % 2 == 0 {
                    BlendMode::Alpha
                } else {
                    BlendMode::Additive
                },
            );
        }
        camera.depth_test = false;
        list.camera(camera);
        for i in 0..10 {
            list.draw_rect(
                Rect::new((i * 8) as f32, (i * 5) as f32, 12., 8.),
                Color::new(0.1, 0.4, 0.9, 0.35),
            );
        }
        list.camera(Camera::screen(WIDTH, HEIGHT));
        list.draw_texture(
            &target.texture,
            Rect::new(218., 106., 96., 64.),
            Color::WHITE,
        );
        for i in 0..19 {
            list.draw_rect(
                Rect::new((i * 16) as f32, 80., 11., 8.),
                Color::new(0.9, (i % 9) as f32 / 9., 0.1, 0.5),
            );
        }
        // 170 glyph draws + 135 other prepared draws (20 line commands batch to one).
        for i in 0..10 {
            list.draw_text(
                "RUSTDUTY012345678",
                Vec2::new(4., 97. + i as f32 * 8.),
                10.,
                Color::WHITE,
            );
        }
        Ok(list)
    }

    fn capture(renderer: &mut WgpuRenderer, list: &DrawList, path: PathBuf) -> Result<f64, String> {
        let mut control = list.clone();
        control.capture_png(None, &path);
        let start = Instant::now();
        let output = renderer.submit(&control)?;
        let elapsed = start.elapsed().as_secs_f64() * 1000.;
        if output.captures != [path] {
            return Err("control submission did not return its exact capture path".into());
        }
        Ok(elapsed)
    }

    fn strict_pixels(before: &std::path::Path, after: &std::path::Path) -> Result<(), String> {
        let read = |path: &std::path::Path| {
            image::open(path)
                .map(|v| v.to_rgba8())
                .map_err(|e| e.to_string())
        };
        let before = read(before)?;
        let after = read(after)?;
        if before.dimensions() != (WIDTH, HEIGHT)
            || after.dimensions() != (WIDTH, HEIGHT)
            || before.as_raw() != after.as_raw()
        {
            return Err("pre/post control pixels differ (zero tolerance)".into());
        }
        if before.pixels().any(|p| p[3] != 255)
            || before.pixels().all(|p| p == before.get_pixel(0, 0))
        {
            return Err("control is uniform or has nonopaque display alpha".into());
        }
        Ok(())
    }

    pub fn run() -> Result<(), String> {
        if !cfg!(target_os = "windows") {
            return Err("this diagnostic requires native Windows DX12/WARP".into());
        }
        let mut args = std::env::args_os().skip(1);
        if args.next().as_deref() != Some(std::ffi::OsStr::new("--output-dir")) {
            return Err("usage: pass_submission_benchmark --output-dir NEW_DIRECTORY".into());
        }
        let out = PathBuf::from(args.next().ok_or("missing output directory")?);
        if args.next().is_some() {
            return Err("unexpected argument".into());
        }
        fs::create_dir(&out).map_err(|e| format!("create new output directory: {e}"))?;
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
            WIDTH,
            HEIGHT,
            BackendSelection::Dx12,
            true,
        ))?;
        if renderer.info().backend != "Dx12"
            || renderer.info().requested != "dx12"
            || renderer.info().adapter != "Microsoft Basic Render Driver"
        {
            return Err(format!(
                "expected DX12 Microsoft WARP; received {:?}",
                renderer.info()
            ));
        }
        let list = fixture()?;
        for _ in 0..WARMUP {
            renderer.submit(&list)?;
        }
        let before = out.join("before.png");
        let after = out.join("after.png");
        let pre_control_ms = capture(&mut renderer, &list, before.clone())?;
        let mut submit_ms = Vec::with_capacity(FRAMES);
        let total = Instant::now();
        for _ in 0..FRAMES {
            let start = Instant::now();
            let output = renderer.submit(&list)?;
            submit_ms.push(start.elapsed().as_secs_f64() * 1000.);
            if !output.captures.is_empty() {
                return Err("timed frame unexpectedly captured pixels".into());
            }
        }
        // Public API has no drain-only call. This is one EXTRA full fixture submission,
        // its ordered readback, GPU completion wait, map, PNG encoding and file write.
        let final_control_submit_drain_png_ms = capture(&mut renderer, &list, after.clone())?;
        let bounded_batch_with_final_control_ms = total.elapsed().as_secs_f64() * 1000.;
        strict_pixels(&before, &after)?;
        let report = json!({
            "schema_version":1, "status":"passed", "fixture":FIXTURE,
            "source_receipt_sha256":option_env!("PASS_SUBMISSION_SOURCE_SHA256"),
            "platform":std::env::consts::OS, "requested":renderer.info().requested,
            "backend":renderer.info().backend, "adapter":renderer.info().adapter,
            "force_fallback_adapter":true, "width":WIDTH, "height":HEIGHT,
            "prepared_draw_count":305, "nontext_draw_count":135, "glyph_draw_count":170,
            "warmup_frames":WARMUP, "timed_frames":FRAMES, "timed_capture_count":0,
            "pre_control_submit_drain_png_ms":pre_control_ms, "whole_submit_ms":submit_ms,
            "final_control_submit_drain_png_ms":final_control_submit_drain_png_ms,
            "bounded_batch_with_final_control_ms":bounded_batch_with_final_control_ms,
            "pixel_comparison":"exact RGBA equality; zero tolerance",
            "gpu_timestamp_ms":null, "presentation":false,
            "scope":"synthetic CPU whole-submit wall time includes validation, text planning, arena upload, encoding, queue submission and polling/backpressure; no surface acquisition or present; final control also includes one extra fixture and GPU drain/readback/PNG; no GPU duration or gameplay FPS claim"
        });
        fs::write(
            out.join("report.json"),
            serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        println!("{}", report);
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use vector_range::draw::Command;
        #[test]
        fn fixture_is_bounded_and_has_exact_source_command_and_glyph_counts() {
            let list = fixture().unwrap();
            let mut text = vector_range::render::text::TextRenderer::new().unwrap();
            let mut counts = [0; 7];
            let mut glyphs = 0;
            for command in &list.commands {
                match command {
                    Command::Mesh { mesh, .. } => {
                        mesh.validate().unwrap();
                        counts[0] += 1;
                    }
                    Command::Lines { lines, .. } => {
                        assert_eq!(lines.len(), 1);
                        counts[1] += 1;
                    }
                    Command::Rect { .. } => counts[2] += 1,
                    Command::Sprite { .. } => counts[3] += 1,
                    Command::Text {
                        text: value,
                        baseline,
                        size,
                        color,
                    } => {
                        counts[4] += 1;
                        glyphs += text.meshes(value, *baseline, *size, *color).unwrap().len();
                    }
                    Command::Camera(_) => counts[5] += 1,
                    Command::Clear(_) => counts[6] += 1,
                    Command::Capture { .. } => panic!("timed fixture contains a capture"),
                }
            }
            assert_eq!(counts, [104, 20, 29, 1, 10, 5, 2]);
            assert_eq!(glyphs, 170);
            assert_eq!(counts[..4].iter().sum::<usize>(), 154);
        }

        #[test]
        fn production_frame_plan_batches_lines_and_prepares_exactly_305_draws() {
            let list = fixture().unwrap();
            let prepare = |list: &DrawList| {
                let mut text = crate::text::TextRenderer::new().unwrap();
                text.prepare_frame(list.commands.iter().filter_map(|command| match command {
                    Command::Text { text, size, .. } => Some((text.as_str(), *size)),
                    _ => None,
                }))
                .unwrap();
                crate::plan::FramePlan::new(list, &mut text, 256, 256 * 1024 * 1024, false).unwrap()
            };
            let plan = prepare(&list);
            let draws: Vec<_> = plan
                .commands
                .iter()
                .filter_map(|command| match command {
                    crate::plan::PreparedCommand::Draw(draw) => Some(draw),
                    _ => None,
                })
                .collect();
            assert_eq!(draws.len(), 305);
            let lines: Vec<_> = draws.iter().filter(|draw| draw.lines).collect();
            assert_eq!(lines.len(), 1);
            assert_eq!(lines[0].geometry.range.count, 40);
            let mut without_text = list.clone();
            without_text
                .commands
                .retain(|c| !matches!(c, Command::Text { .. }));
            let nontext = prepare(&without_text)
                .commands
                .iter()
                .filter(|c| matches!(c, crate::plan::PreparedCommand::Draw(_)))
                .count();
            assert_eq!(nontext, 135);
            assert_eq!(draws.len() - nontext, 170);
        }
    }
}

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = diagnostic::run() {
        eprintln!("pass submission diagnostic failed: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("pass submission diagnostic requires --features wgpu-runtime");
    std::process::exit(1);
}
