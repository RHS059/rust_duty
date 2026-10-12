//! Consecutive production-recorder frames through one real DX12 renderer/target.
//!
//! Windows: cargo run --locked --no-default-features --features wgpu-runtime
//! --example renderer_frame_identity -- --renderer=dx12 --force-fallback-adapter
//! --output-dir evidence/renderer-frame-identity
//!
//! Retain stderr and require the renderer's actual initialization line
//! `renderer dx12_shader_compiler=Fxc` as compiler provenance. BackendInfo does
//! not expose a compiler field, so this fixture does not invent one. CPU tests
//! test the recorder and pixel checker; only the Windows invocation exercises
//! GPU submission/readback. This is not authored pose-to-pixel parity, window
//! presentation, gameplay, or artistic approval. No game pixels are modified.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("renderer_frame_identity: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("renderer_frame_identity requires --features wgpu-runtime and Windows DX12");
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", test))]
mod fixture {
    use image::RgbaImage;
    #[cfg(feature = "wgpu-runtime")]
    use serde_json::json;
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    use vector_range::draw::{facade, BackendInfo, DrawList, RenderTarget};
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        draw::Renderer,
        render::{BackendSelection, WgpuRenderer},
    };

    const WIDTH: u32 = 65; // 260-byte rows require a 512-byte GPU copy stride.
    const HEIGHT: u32 = 49;
    const TOLERANCE: u8 = 2;
    #[cfg(feature = "wgpu-runtime")]
    const REPORT: &str = "renderer-frame-identity-report.json";
    const RECTS: [[u32; 4]; 4] = [
        [4, 4, 23, 16],
        [38, 4, 23, 16],
        [4, 29, 23, 16],
        [38, 29, 23, 16],
    ];

    struct FrameCase {
        first_slot: usize,
        second_slot: usize,
        first: [u8; 4],
        second: [u8; 4],
    }
    // Independent authored expectations: no shader, capture, pose telemetry,
    // random source, or previous output is used to choose these values.
    const FRAMES: [FrameCase; 6] = [
        FrameCase {
            first_slot: 0,
            second_slot: 3,
            first: [255, 0, 0, 255],
            second: [255, 255, 0, 255],
        },
        FrameCase {
            first_slot: 2,
            second_slot: 1,
            first: [0, 255, 0, 255],
            second: [255, 0, 255, 255],
        },
        FrameCase {
            first_slot: 1,
            second_slot: 2,
            first: [0, 0, 255, 255],
            second: [0, 255, 255, 255],
        },
        FrameCase {
            first_slot: 3,
            second_slot: 0,
            first: [255, 255, 0, 255],
            second: [0, 0, 255, 255],
        },
        FrameCase {
            first_slot: 0,
            second_slot: 2,
            first: [255, 0, 255, 255],
            second: [0, 255, 0, 255],
        },
        FrameCase {
            first_slot: 2,
            second_slot: 3,
            first: [0, 255, 255, 255],
            second: [255, 0, 0, 255],
        },
    ];

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    enum Stage {
        EarlyTarget,
        LateTarget,
        Main,
    }
    const STAGES: [Stage; 3] = [Stage::EarlyTarget, Stage::LateTarget, Stage::Main];
    impl Stage {
        fn name(self) -> &'static str {
            match self {
                Self::EarlyTarget => "early-target",
                Self::LateTarget => "late-target",
                Self::Main => "main",
            }
        }
        fn background(self) -> [u8; 4] {
            [0, 0, 0, if self == Self::Main { 255 } else { 0 }]
        }
    }

    #[derive(Debug, PartialEq, Eq)]
    struct Options {
        output: PathBuf,
        fallback: bool,
    }
    impl Options {
        fn parse(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Self, String> {
            let mut args = args.into_iter().map(Into::into);
            let mut renderer = None;
            let mut output = None;
            let mut fallback = false;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--force-fallback-adapter" if !fallback => fallback = true,
                    "--renderer" => set_once(
                        &mut renderer,
                        args.next().ok_or("--renderer requires dx12")?,
                        "--renderer",
                    )?,
                    "--output-dir" => set_once(
                        &mut output,
                        args.next().ok_or("--output-dir requires a directory")?,
                        "--output-dir",
                    )?,
                    _ if arg.starts_with("--renderer=") => {
                        set_once(&mut renderer, arg[11..].into(), "--renderer")?
                    }
                    _ if arg.starts_with("--output-dir=") => {
                        set_once(&mut output, arg[13..].into(), "--output-dir")?
                    }
                    _ => return Err(format!("unknown or repeated argument {arg:?}")),
                }
            }
            if renderer.as_deref() != Some("dx12") {
                return Err(
                    "explicit --renderer=dx12 is required; no backend substitution is accepted"
                        .into(),
                );
            }
            let output = output
                .filter(|value| !value.trim().is_empty() && !value.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                output: output.into(),
                fallback,
            })
        }
    }
    fn set_once(slot: &mut Option<String>, value: String, name: &str) -> Result<(), String> {
        if slot.replace(value).is_some() {
            return Err(format!("{name} may be specified only once"));
        }
        Ok(())
    }
    fn prepare_output(path: &Path) -> Result<(), String> {
        if path.exists() {
            if fs::read_dir(path)
                .map_err(|e| format!("read output directory: {e}"))?
                .next()
                .transpose()
                .map_err(|e| format!("read output entry: {e}"))?
                .is_some()
            {
                return Err(
                    "output directory must be empty; stale evidence is not accepted".into(),
                );
            }
        } else {
            fs::create_dir_all(path).map_err(|e| format!("create output directory: {e}"))?;
        }
        Ok(())
    }
    fn verify_backend(info: &BackendInfo) -> Result<(), String> {
        if info.requested != "dx12" || info.backend != "Dx12" || info.adapter.trim().is_empty() {
            return Err(format!(
                "expected requested=dx12, backend=Dx12 and a named actual adapter; got {info:?}"
            ));
        }
        Ok(())
    }
    fn filename(frame: usize, stage: Stage) -> String {
        format!("frame-{frame:02}-{}.png", stage.name())
    }

    fn paint(slot: usize, rgba: [u8; 4]) {
        let [x, y, width, height] = RECTS[slot];
        let [r, g, b, a] = rgba.map(|channel| f32::from(channel) / 255.);
        facade::draw_rectangle(
            x as f32,
            y as f32,
            width as f32,
            height as f32,
            facade::Color::new(r, g, b, a),
        );
    }

    /// Uses the exact recorder consumed by DrawHooks::end_frame, never a mock
    /// Renderer or a test-only reconstruction of the draw commands.
    fn record_frame(
        frame: usize,
        target: &RenderTarget,
        output: &Path,
    ) -> Result<DrawList, String> {
        let case = &FRAMES[frame];
        facade::begin_frame(WIDTH, HEIGHT, 1.)?;
        facade::clear_background(facade::BLACK);
        facade::set_camera(&facade::Camera3D {
            render_target: Some(target.clone()),
            ..Default::default()
        });
        facade::clear_background(facade::BLANK);
        paint(case.first_slot, case.first);
        facade::capture_png(
            Some(target),
            output.join(filename(frame, Stage::EarlyTarget)),
        );
        paint(case.second_slot, case.second);
        facade::capture_png(
            Some(target),
            output.join(filename(frame, Stage::LateTarget)),
        );
        facade::set_default_camera();
        facade::draw_texture_ex(
            &target.texture,
            0.,
            0.,
            facade::WHITE,
            facade::DrawTextureParams::default(),
        );
        facade::capture_png(None, output.join(filename(frame, Stage::Main)));
        facade::take_draw_list()
    }

    fn probes(frame: usize, stage: Stage) -> Vec<([u32; 4], [u8; 4])> {
        let case = &FRAMES[frame];
        let mut probes: Vec<_> = RECTS
            .iter()
            .enumerate()
            .map(|(slot, &[x, y, w, h])| {
                let expected = if slot == case.first_slot {
                    case.first
                } else if stage != Stage::EarlyTarget && slot == case.second_slot {
                    case.second
                } else {
                    stage.background()
                };
                ([x + 1, y + 1, x + w - 1, y + h - 1], expected)
            })
            .collect();
        // The transparent/opaque center stripe also distinguishes raw late
        // target bytes from the main composite in the very same frame.
        probes.push(([30, 0, 35, HEIGHT], stage.background()));
        probes
    }
    fn verify_pixels(image: &RgbaImage, frame: usize, stage: Stage) -> Result<usize, String> {
        if image.dimensions() != (WIDTH, HEIGHT) {
            return Err("capture extent differs".into());
        }
        if stage == Stage::Main && image.pixels().any(|pixel| pixel[3] != 255) {
            return Err("main capture contains nonopaque alpha".into());
        }
        let mut checked = 0;
        for ([x0, y0, x1, y1], expected) in probes(frame, stage) {
            for y in y0..y1 {
                for x in x0..x1 {
                    let actual = image.get_pixel(x, y).0;
                    if actual
                        .iter()
                        .zip(expected)
                        .any(|(&a, e)| a.abs_diff(e) > TOLERANCE)
                    {
                        return Err(format!(
                            "frame {frame} {} at ({x},{y}): expected {expected:?}, got {actual:?}",
                            stage.name()
                        ));
                    }
                    checked += 1;
                }
            }
        }
        Ok(checked)
    }
    fn read_png(path: &Path) -> Result<RgbaImage, String> {
        let reader = image::io::Reader::open(path)
            .map_err(|e| format!("read {}: {e}", path.display()))?
            .with_guessed_format()
            .map_err(|e| format!("identify PNG: {e}"))?;
        if reader.format() != Some(image::ImageFormat::Png) {
            return Err("capture is not PNG".into());
        }
        let decoded = reader.decode().map_err(|e| format!("decode PNG: {e}"))?;
        if decoded.color() != image::ColorType::Rgba8 {
            return Err("capture is not RGBA8".into());
        }
        Ok(decoded.to_rgba8())
    }
    fn reject_other_identities(
        image: &RgbaImage,
        frame: usize,
        stage: Stage,
    ) -> Result<usize, String> {
        let mut rejected = 0;
        for other_frame in 0..FRAMES.len() {
            for other_stage in STAGES {
                if (other_frame, other_stage) == (frame, stage) {
                    continue;
                }
                if verify_pixels(image, other_frame, other_stage).is_ok() {
                    return Err(format!("frame {frame} {} also passes as frame {other_frame} {}; identity is ambiguous", stage.name(), other_stage.name()));
                }
                rejected += 1;
            }
        }
        Ok(rejected)
    }

    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native frame identity requires Windows DX12; CPU tests cannot produce a native pass".into());
        }
        prepare_output(&options.output)?;
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
            WIDTH,
            HEIGHT,
            BackendSelection::Dx12,
            options.fallback,
        ))?;
        verify_backend(renderer.info())?;
        facade::set_backend_info(renderer.info().clone());
        let target = RenderTarget::new(WIDTH, HEIGHT, true)?;
        let mut captures = Vec::new();
        let mut rejections = 0;
        for frame in 0..FRAMES.len() {
            // Neither the renderer nor target is replaced between frames.
            let list = record_frame(frame, &target, &options.output)?;
            let output = renderer.submit(&list)?;
            let expected: Vec<_> = STAGES
                .iter()
                .map(|&stage| options.output.join(filename(frame, stage)))
                .collect();
            if output.captures != expected {
                return Err("capture return paths differ from recorder order".into());
            }
            for stage in STAGES {
                let name = filename(frame, stage);
                let image = read_png(&options.output.join(&name))?;
                let checked = verify_pixels(&image, frame, stage)?;
                rejections += reject_other_identities(&image, frame, stage)?;
                captures.push(json!({"filename":name,"frame":frame,"stage":stage.name(),
                    "width":WIDTH,"height":HEIGHT,"row_origin":"top-left",
                    "expected_probes":probes(frame,stage),"checked_pixels":checked,
                    "channel_tolerance":TOLERANCE,"other_identities_rejected":FRAMES.len()*STAGES.len()-1}));
            }
        }
        // Reopen every earlier PNG after all reuse, detecting late writes or
        // accidental overwrites rather than retaining only an in-memory pass.
        for frame in 0..FRAMES.len() {
            for stage in STAGES {
                verify_pixels(
                    &read_png(&options.output.join(filename(frame, stage)))?,
                    frame,
                    stage,
                )?;
            }
        }
        let info = renderer.info();
        verify_backend(info)?;
        let report = json!({"schema_version":1,"status":"passed","native_execution":true,
            "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
            "force_fallback_adapter":options.fallback,"platform":std::env::consts::OS,
            "build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,
            "compiler_provenance":"require renderer initialization stderr: renderer dx12_shader_compiler=Fxc",
            "frame_count":FRAMES.len(),"capture_count":captures.len(),"captures":captures,
            "cross_identity_rejections":rejections,"rechecked_after_all_submissions":true,
            "persistent_renderer":true,"persistent_target":true,
            "scope":"headless production-recorder DX12 frame identity; not authored pose-to-pixel parity, window presentation, gameplay or artistic approval"});
        let mut bytes =
            serde_json::to_vec_pretty(&report).map_err(|e| format!("encode report: {e}"))?;
        bytes.push(b'\n');
        fs::write(options.output.join(REPORT), bytes).map_err(|e| format!("write report: {e}"))?;
        println!("DX12 frame identity passed: {} consecutive frames, {} captures, {rejections} wrong identities rejected", FRAMES.len(), FRAMES.len()*STAGES.len());
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use image::Rgba;
        use std::sync::atomic::{AtomicU64, Ordering};
        use vector_range::draw::Command;

        struct Scratch(PathBuf);
        impl Scratch {
            fn new() -> Self {
                static NEXT: AtomicU64 = AtomicU64::new(0);
                Self(std::env::temp_dir().join(format!(
                    "rust-duty-frame-identity-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                )))
            }
        }
        impl Drop for Scratch {
            fn drop(&mut self) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }

        fn control(frame: usize, stage: Stage) -> RgbaImage {
            let mut image = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba(stage.background()));
            let case = &FRAMES[frame];
            for (slot, rgba) in [
                (case.first_slot, case.first),
                (case.second_slot, case.second),
            ] {
                if slot == case.second_slot && stage == Stage::EarlyTarget {
                    continue;
                }
                let [x, y, w, h] = RECTS[slot];
                for py in y..y + h {
                    for px in x..x + w {
                        image.put_pixel(px, py, Rgba(rgba));
                    }
                }
            }
            image
        }

        #[test]
        fn every_distinct_control_rejects_same_frame_and_prior_or_later_pixels() {
            let mut total = 0;
            for frame in 0..FRAMES.len() {
                for stage in STAGES {
                    let image = control(frame, stage);
                    assert_eq!(verify_pixels(&image, frame, stage).unwrap(), 1421);
                    total += reject_other_identities(&image, frame, stage).unwrap();
                }
            }
            assert_eq!(total, 306);
        }

        #[test]
        fn blank_flip_channel_swap_and_wrong_extent_do_not_satisfy_identity() {
            let valid = control(0, Stage::LateTarget);
            assert!(verify_pixels(&valid, 0, Stage::LateTarget).is_ok());
            assert!(verify_pixels(&RgbaImage::new(WIDTH, HEIGHT), 0, Stage::LateTarget).is_err());
            assert!(verify_pixels(
                &image::imageops::flip_vertical(&valid),
                0,
                Stage::LateTarget
            )
            .is_err());
            let mut swapped = valid.clone();
            for pixel in swapped.pixels_mut() {
                pixel.0.swap(0, 2);
            }
            assert!(verify_pixels(&swapped, 0, Stage::LateTarget).is_err());
            assert!(verify_pixels(&RgbaImage::new(64, 49), 0, Stage::LateTarget).is_err());
        }

        #[test]
        fn consecutive_real_recordings_keep_one_target_and_separate_capture_snapshots() {
            let target = RenderTarget::new(WIDTH, HEIGHT, true).unwrap();
            let scratch = Scratch::new();
            let first = record_frame(0, &target, &scratch.0).unwrap();
            let second = record_frame(1, &target, &scratch.0).unwrap();
            assert!(
                !scratch.0.exists(),
                "recording must not save files before submission"
            );
            assert!(
                facade::take_draw_list().is_err(),
                "the second frame must have been consumed exactly once"
            );
            for (frame, list) in [(0, &first), (1, &second)] {
                assert_eq!((list.width, list.height), (WIDTH, HEIGHT));
                let captures: Vec<_> = list
                    .commands
                    .iter()
                    .filter_map(|command| match command {
                        Command::Capture { target, path } => {
                            Some((target.as_ref().map(|t| t.texture.id), path.clone()))
                        }
                        _ => None,
                    })
                    .collect();
                assert_eq!(
                    captures,
                    vec![
                        (
                            Some(target.texture.id),
                            scratch.0.join(filename(frame, Stage::EarlyTarget))
                        ),
                        (
                            Some(target.texture.id),
                            scratch.0.join(filename(frame, Stage::LateTarget))
                        ),
                        (None, scratch.0.join(filename(frame, Stage::Main))),
                    ]
                );
                let draws: Vec<_> = list
                    .commands
                    .iter()
                    .filter_map(|command| match command {
                        Command::Rect { rect, color } => Some((*rect, <[u8; 4]>::from(*color))),
                        _ => None,
                    })
                    .collect();
                let case = &FRAMES[frame];
                assert_eq!(draws.len(), 2);
                for ((rect, color), (slot, rgba)) in draws.iter().zip([
                    (case.first_slot, case.first),
                    (case.second_slot, case.second),
                ]) {
                    let [x, y, w, h] = RECTS[slot];
                    assert_eq!(
                        *rect,
                        facade::Rect::new(x as f32, y as f32, w as f32, h as f32)
                    );
                    assert_eq!(*color, rgba);
                }
                let sequence: Vec<_> = list
                    .commands
                    .iter()
                    .filter_map(|command| match command {
                        Command::Rect { .. } => Some("draw"),
                        Command::Capture {
                            target: Some(_), ..
                        } => Some("raw"),
                        Command::Sprite { texture, .. } => {
                            assert_eq!(texture.id, target.texture.id);
                            Some("sample")
                        }
                        Command::Capture { target: None, .. } => Some("main"),
                        _ => None,
                    })
                    .collect();
                assert_eq!(sequence, ["draw", "raw", "draw", "raw", "sample", "main"]);
            }
            assert!(facade::current_camera().is_err());
        }

        #[test]
        fn png_decode_and_disk_recheck_reject_a_stale_replacement() {
            let scratch = Scratch::new();
            prepare_output(&scratch.0).unwrap();
            let path = scratch.0.join("capture.png");
            control(1, Stage::Main).save(&path).unwrap();
            assert!(verify_pixels(&read_png(&path).unwrap(), 1, Stage::Main).is_ok());
            control(0, Stage::Main).save(&path).unwrap();
            assert!(verify_pixels(&read_png(&path).unwrap(), 1, Stage::Main).is_err());
            fs::write(&path, b"not a PNG").unwrap();
            assert!(read_png(&path).is_err());
        }

        #[test]
        fn arguments_backend_and_stale_output_fail_closed() {
            let valid = Options::parse([
                "--renderer=dx12",
                "--force-fallback-adapter",
                "--output-dir=fresh",
            ])
            .unwrap();
            assert!(valid.fallback);
            assert_eq!(valid.output, PathBuf::from("fresh"));
            for args in [
                vec!["--output-dir=fresh"],
                vec!["--renderer=vulkan", "--output-dir=fresh"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--renderer=dx12", "--output-dir=fresh"],
                vec![
                    "--renderer=dx12",
                    "--force-fallback-adapter",
                    "--force-fallback-adapter",
                    "--output-dir=fresh",
                ],
            ] {
                assert!(Options::parse(args).is_err());
            }
            let info = BackendInfo {
                requested: "dx12".into(),
                backend: "Dx12".into(),
                adapter: "CPU identity-validation control, not a GPU pass".into(),
            };
            assert!(verify_backend(&info).is_ok());
            for invalid in [
                BackendInfo {
                    requested: "auto".into(),
                    ..info.clone()
                },
                BackendInfo {
                    backend: "Vulkan".into(),
                    ..info.clone()
                },
                BackendInfo {
                    adapter: " ".into(),
                    ..info
                },
            ] {
                assert!(verify_backend(&invalid).is_err());
            }
            let scratch = Scratch::new();
            prepare_output(&scratch.0).unwrap();
            fs::write(scratch.0.join("stale.png"), b"old evidence").unwrap();
            assert!(prepare_output(&scratch.0).is_err());
        }

        #[cfg(all(feature = "wgpu-runtime", not(target_os = "windows")))]
        #[test]
        fn non_windows_cannot_initialize_any_backend_or_write_a_native_report() {
            let scratch = Scratch::new();
            let error = run([
                "--renderer=dx12".to_owned(),
                format!("--output-dir={}", scratch.0.display()),
            ])
            .unwrap_err();
            assert!(error.contains("Windows DX12"));
            assert!(!scratch.0.exists());
        }
    }
}
