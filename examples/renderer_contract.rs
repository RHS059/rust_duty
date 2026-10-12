//! Native DX12 evidence, deliberately separate from gameplay capture telemetry.
//! See docs/engineering/renderer-contract.md for invocation and proof boundaries.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("renderer_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("renderer_contract requires --features wgpu-runtime; native validation requires Windows DX12");
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", test))]
mod fixture {
    #[cfg(feature = "wgpu-runtime")]
    use glam::{Mat4, Vec2};
    use image::RgbaImage;
    use serde_json::{json, Value};
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        draw::{
            BackendInfo, BlendMode, Camera, Color, DrawList, Mesh, Rect, RenderTarget, Renderer,
            Vertex,
        },
        render::{BackendSelection, WgpuRenderer},
    };

    const TOLERANCE: u8 = 8;
    const MINIMUM_MATCH: f64 = 0.9;
    const REPORT: &str = "renderer-contract-report.json";
    #[cfg(feature = "wgpu-runtime")]
    const OPAQUE: &str = "opaque-rgba8-rgb-preserved-over-black";
    #[cfg(feature = "wgpu-runtime")]
    const ASSOCIATED: &str = "raw-associated-emissive-rgba8";

    #[derive(Debug, PartialEq, Eq)]
    struct Options {
        force_fallback_adapter: bool,
        output_dir: PathBuf,
    }

    impl Options {
        fn parse(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Self, String> {
            let mut args = args.into_iter().map(Into::into);
            let mut renderer = None;
            let mut output_dir = None;
            let mut force_fallback_adapter = false;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--force-fallback-adapter" => {
                        if force_fallback_adapter {
                            return Err(
                                "--force-fallback-adapter may be specified only once".into()
                            );
                        }
                        force_fallback_adapter = true;
                    }
                    "--renderer" => {
                        let value = args.next().ok_or("--renderer requires dx12")?;
                        set_once(&mut renderer, value, "--renderer")?;
                    }
                    "--output-dir" => {
                        let value = args.next().ok_or("--output-dir requires a directory")?;
                        set_once(&mut output_dir, value, "--output-dir")?;
                    }
                    _ if arg.starts_with("--renderer=") => {
                        set_once(&mut renderer, arg[11..].to_owned(), "--renderer")?;
                    }
                    _ if arg.starts_with("--output-dir=") => {
                        set_once(&mut output_dir, arg[13..].to_owned(), "--output-dir")?;
                    }
                    _ => return Err(format!("unknown fixture argument {arg:?}")),
                }
            }
            if renderer.as_deref() != Some("dx12") {
                return Err(
                    "this fixture requires explicit --renderer=dx12; no other backend is accepted"
                        .into(),
                );
            }
            let output_dir = output_dir
                .filter(|value| !value.trim().is_empty() && !value.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                force_fallback_adapter,
                output_dir: PathBuf::from(output_dir),
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
            let mut entries = fs::read_dir(path)
                .map_err(|error| format!("read output directory {}: {error}", path.display()))?;
            if entries
                .next()
                .transpose()
                .map_err(|error| format!("read output entry: {error}"))?
                .is_some()
            {
                return Err(format!("output directory {} must be empty; choose a fresh directory so stale evidence cannot pass", path.display()));
            }
        } else {
            fs::create_dir_all(path)
                .map_err(|error| format!("create output directory {}: {error}", path.display()))?;
        }
        Ok(())
    }

    #[derive(Clone, Copy)]
    struct Probe {
        label: &'static str,
        // Normalized top-left origin, [x0, x1) by [y0, y1).
        bounds: [f64; 4],
        rgba: [u8; 4],
    }

    fn quadrant_probes() -> [Probe; 4] {
        [
            Probe {
                label: "top-left red",
                bounds: [0.1, 0.4, 0.1, 0.4],
                rgba: [255, 0, 0, 255],
            },
            Probe {
                label: "top-right green",
                bounds: [0.6, 0.9, 0.1, 0.4],
                rgba: [0, 255, 0, 255],
            },
            Probe {
                label: "bottom-left blue",
                bounds: [0.1, 0.4, 0.6, 0.9],
                rgba: [0, 0, 255, 255],
            },
            Probe {
                label: "bottom-right yellow",
                bounds: [0.6, 0.9, 0.6, 0.9],
                rgba: [255, 255, 0, 255],
            },
        ]
    }

    #[cfg(feature = "wgpu-runtime")]
    fn solid_probe(rgba: [u8; 4]) -> [Probe; 1] {
        [Probe {
            label: "solid interior",
            bounds: [0.1, 0.9, 0.1, 0.9],
            rgba,
        }]
    }

    fn inspect_probe(image: &RgbaImage, probe: Probe) -> Result<Value, String> {
        let [x0, x1, y0, y1] = probe.bounds;
        if !probe
            .bounds
            .iter()
            .all(|value| value.is_finite() && (0.0..=1.0).contains(value))
            || x0 >= x1
            || y0 >= y1
        {
            return Err(format!(
                "{} has invalid normalized probe bounds",
                probe.label
            ));
        }
        let left = (x0 * f64::from(image.width())).floor() as u32;
        let right = (x1 * f64::from(image.width())).floor() as u32;
        let top = (y0 * f64::from(image.height())).floor() as u32;
        let bottom = (y1 * f64::from(image.height())).floor() as u32;
        let total = (right - left) as u64 * (bottom - top) as u64;
        if total == 0 {
            return Err(format!("{} has empty pixel coverage", probe.label));
        }
        let mut matched = 0_u64;
        for y in top..bottom {
            for x in left..right {
                if image
                    .get_pixel(x, y)
                    .0
                    .iter()
                    .zip(probe.rgba)
                    .all(|(actual, expected)| actual.abs_diff(expected) <= TOLERANCE)
                {
                    matched += 1;
                }
            }
        }
        let fraction = matched as f64 / total as f64;
        if !fraction.is_finite() || fraction < MINIMUM_MATCH {
            return Err(format!("{}: {matched}/{total} pixels ({fraction:.3}) match {:?}, need >=90% within {TOLERANCE}", probe.label, probe.rgba));
        }
        Ok(
            json!({"label": probe.label, "normalized_bounds": probe.bounds,
            "pixel_bounds": [left, right, top, bottom], "expected_rgba": probe.rgba,
            "matching_pixels": matched, "total_pixels": total, "match_fraction": fraction,
            "minimum_match_fraction": MINIMUM_MATCH, "channel_tolerance": TOLERANCE}),
        )
    }

    fn coverage(image: &RgbaImage) -> Result<Value, String> {
        let total = image.width() as u64 * image.height() as u64;
        let nonblack = image
            .pixels()
            .filter(|pixel| pixel.0[..3].iter().any(|&v| v != 0))
            .count();
        if total == 0 || nonblack == 0 {
            return Err("capture has empty or entirely black RGB coverage".into());
        }
        let fraction = nonblack as f64 / total as f64;
        if !fraction.is_finite() || fraction <= 0.0 || fraction > 1.0 {
            return Err("capture coverage is non-finite or outside (0,1]".into());
        }
        Ok(
            json!({"nonblack_pixels": nonblack, "total_pixels": total, "nonblack_fraction": fraction}),
        )
    }

    fn read_png(path: &Path, width: u32, height: u32) -> Result<RgbaImage, String> {
        let image = image::io::Reader::open(path)
            .map_err(|error| format!("read PNG {}: {error}", path.display()))?
            .with_guessed_format()
            .map_err(|error| format!("identify PNG {}: {error}", path.display()))?;
        if image.format() != Some(image::ImageFormat::Png) {
            return Err(format!("{} is not a PNG", path.display()));
        }
        let image = image
            .decode()
            .map_err(|error| format!("decode PNG {}: {error}", path.display()))?;
        if image.width() != width
            || image.height() != height
            || image.color() != image::ColorType::Rgba8
        {
            return Err(format!(
                "{} expected {width}x{height} RGBA8, got {}x{} {:?}",
                path.display(),
                image.width(),
                image.height(),
                image.color()
            ));
        }
        Ok(image.into_rgba8())
    }

    fn write_json(path: &Path, value: &Value) -> Result<(), String> {
        let mut bytes =
            serde_json::to_vec_pretty(value).map_err(|error| format!("encode JSON: {error}"))?;
        bytes.push(b'\n');
        fs::write(path, bytes).map_err(|error| format!("write JSON {}: {error}", path.display()))
    }

    #[cfg(feature = "wgpu-runtime")]
    fn verify_backend(info: &BackendInfo) -> Result<(), String> {
        if info.requested != "dx12" || info.backend != "Dx12" || info.adapter.trim().is_empty() {
            return Err(format!("DX12 evidence requires requested=dx12, actual backend=Dx12 and a named adapter; got {info:?}"));
        }
        Ok(())
    }

    #[cfg(feature = "wgpu-runtime")]
    struct Contract {
        renderer: WgpuRenderer,
        options: Options,
        captures: Vec<Value>,
    }

    #[cfg(feature = "wgpu-runtime")]
    impl Contract {
        fn path(&self, filename: &str) -> PathBuf {
            self.options.output_dir.join(filename)
        }

        fn submit(&mut self, list: &DrawList, filenames: &[&str]) -> Result<(), String> {
            let expected: Vec<_> = filenames.iter().map(|name| self.path(name)).collect();
            let result = self.renderer.submit(list)?;
            if result.captures != expected {
                return Err(format!(
                    "ordered capture outputs differ: expected {expected:?}, got {:?}",
                    result.captures
                ));
            }
            Ok(())
        }

        fn record(
            &mut self,
            filename: &str,
            case: &str,
            size: (u32, u32),
            alpha: &str,
            probes: &[Probe],
            extra: Value,
        ) -> Result<RgbaImage, String> {
            let path = self.path(filename);
            let image = read_png(&path, size.0, size.1)?;
            let coverage = coverage(&image)?;
            if alpha == OPAQUE && image.pixels().any(|pixel| pixel[3] != 255) {
                return Err(format!(
                    "{filename}: main capture must have opaque alpha in every pixel"
                ));
            }
            let probes: Vec<_> = probes
                .iter()
                .map(|&probe| inspect_probe(&image, probe))
                .collect::<Result<_, _>>()?;
            let info = self.renderer.info();
            verify_backend(info)?;
            let metadata = json!({
                "schema_version": 1, "fixture_case": case, "filename": filename,
                "requested": info.requested, "backend": info.backend, "adapter": info.adapter,
                "renderer": {"requested": info.requested, "backend": info.backend, "adapter": info.adapter},
                "force_fallback_adapter": self.options.force_fallback_adapter,
                "alpha_representation": alpha, "diagnostic_raw_target": alpha == ASSOCIATED,
                "row_origin": "top-left",
                "size": {"width": size.0, "height": size.1}, "width": size.0, "height": size.1,
                "coverage": coverage, "probes": probes, "extra": extra,
            });
            write_json(&self.path(&format!("{filename}.json")), &metadata)?;
            self.captures.push(metadata);
            Ok(image)
        }

        fn quadrants(&mut self, width: u32, height: u32, filename: &str) -> Result<(), String> {
            let mut list = DrawList::new(width, height);
            list.clear(Color::new(0., 0., 0., 1.));
            let half_w = width as f32 / 2.;
            let half_h = height as f32 / 2.;
            for (x, y, color) in [
                (0., 0., Color::new(1., 0., 0., 1.)),
                (half_w, 0., Color::new(0., 1., 0., 1.)),
                (0., half_h, Color::new(0., 0., 1., 1.)),
                (half_w, half_h, Color::new(1., 1., 0., 1.)),
            ] {
                list.draw_mesh(
                    &quad(Rect::new(x, y, half_w, half_h), 0., color),
                    Mat4::IDENTITY,
                    BlendMode::Opaque,
                );
            }
            list.capture_png(None, self.path(filename));
            self.submit(&list, &[filename])?;
            self.record(
                filename,
                if width == 65 {
                    "readback-width-65"
                } else {
                    "orientation-quadrants"
                },
                (width, height),
                OPAQUE,
                &quadrant_probes(),
                json!({"row_padding_required": width == 65}),
            )?;
            Ok(())
        }

        fn ordered_captures(&mut self) -> Result<(), String> {
            let mut list = DrawList::new(96, 64);
            list.draw_mesh(
                &quad(Rect::new(0., 0., 96., 64.), 0., Color::new(1., 0., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(None, self.path("ordered-a-red.png"));
            list.draw_mesh(
                &quad(Rect::new(0., 0., 96., 64.), 0., Color::new(0., 1., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(None, self.path("ordered-b-green.png"));
            self.submit(&list, &["ordered-a-red.png", "ordered-b-green.png"])?;
            self.record(
                "ordered-a-red.png",
                "same-submission-checkpoint-a",
                (96, 64),
                OPAQUE,
                &solid_probe([255, 0, 0, 255]),
                json!({"submission_group": "red-then-green", "checkpoint": 0}),
            )?;
            self.record(
                "ordered-b-green.png",
                "same-submission-checkpoint-b",
                (96, 64),
                OPAQUE,
                &solid_probe([0, 255, 0, 255]),
                json!({"submission_group": "red-then-green", "checkpoint": 1}),
            )?;
            Ok(())
        }

        fn target_quadrants(&mut self) -> Result<(), String> {
            let raw = "quadrant-target.png";
            let composite = "quadrant-target-composite.png";
            let list = named_target_quadrants(self.path(raw), self.path(composite))?;
            self.submit(&list, &[raw, composite])?;
            for (filename, case, alpha, stage) in [
                (
                    raw,
                    "orientation-named-target-raw",
                    ASSOCIATED,
                    "raw-target",
                ),
                (
                    composite,
                    "orientation-named-target-composite",
                    OPAQUE,
                    "sampled-main",
                ),
            ] {
                // Both captures use fixed expectations, never the other capture as a golden.
                self.record(
                    filename,
                    case,
                    (96, 64),
                    alpha,
                    &quadrant_probes(),
                    json!({"orientation_group":"named-target-to-main","stage":stage}),
                )?;
            }
            Ok(())
        }

        fn camera_depth(&mut self) -> Result<(), String> {
            let target = RenderTarget::new(96, 64, true)?;
            let mut main_camera = Camera::screen(96, 64);
            main_camera.depth_test = true;
            let mut target_camera = main_camera.clone();
            target_camera.target = Some(target.clone());
            let mut list = DrawList::new(96, 64);
            let full = Rect::new(0., 0., 96., 64.);
            list.camera(main_camera.clone());
            list.clear(Color::new(0., 0., 0., 1.));
            // Screen camera maps z=+0.5 to depth 0.25 and z=-0.5 to 0.75.
            list.draw_mesh(
                &quad(full, 0.5, Color::new(1., 0., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.draw_mesh(
                &quad(full, -0.5, Color::new(0., 1., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(None, self.path("depth-main-near.png"));
            list.camera(target_camera);
            list.clear(Color::new(0., 0., 0., 1.));
            list.draw_mesh(
                &quad(full, 0.5, Color::new(0., 0., 1., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(Some(&target), self.path("depth-target-near.png"));
            list.clear(Color::new(0., 0., 0., 1.));
            list.draw_mesh(
                &quad(full, -0.5, Color::new(1., 1., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(Some(&target), self.path("depth-target-reset.png"));
            list.camera(main_camera);
            list.draw_mesh(
                &quad(full, -0.5, Color::new(0., 1., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(None, self.path("depth-main-preserved.png"));
            list.clear(Color::new(0., 0., 0., 1.));
            list.draw_mesh(
                &quad(full, -0.5, Color::new(0., 1., 0., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(None, self.path("depth-main-reset.png"));
            // Returning to a 2D camera must stop depth rejection.
            list.camera(Camera::screen(96, 64));
            list.draw_mesh(
                &quad(full, -0.9, Color::new(0., 0., 1., 1.)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(None, self.path("depth-disabled.png"));
            let checks = [
                (
                    "depth-main-near.png",
                    "near-surface-occludes-far",
                    [255, 0, 0, 255],
                    OPAQUE,
                ),
                (
                    "depth-target-near.png",
                    "camera-selects-named-target",
                    [0, 0, 255, 255],
                    ASSOCIATED,
                ),
                (
                    "depth-target-reset.png",
                    "named-target-clear-resets-depth",
                    [255, 255, 0, 255],
                    ASSOCIATED,
                ),
                (
                    "depth-main-preserved.png",
                    "named-target-clear-preserves-main",
                    [255, 0, 0, 255],
                    OPAQUE,
                ),
                (
                    "depth-main-reset.png",
                    "main-clear-resets-depth",
                    [0, 255, 0, 255],
                    OPAQUE,
                ),
                (
                    "depth-disabled.png",
                    "screen-camera-disables-depth",
                    [0, 0, 255, 255],
                    OPAQUE,
                ),
            ];
            self.submit(&list, &checks.map(|check| check.0))?;
            for (file, case, rgba, alpha) in checks {
                self.record(file, case, (96, 64), alpha, &solid_probe(rgba), Value::Null)?;
            }
            Ok(())
        }

        fn alpha_targets(&mut self) -> Result<(), String> {
            let target = RenderTarget::new(96, 64, false)?;
            let mut camera = Camera::screen(96, 64);
            camera.target = Some(target.clone());
            let mut list = DrawList::new(96, 64);
            list.camera(camera);
            list.clear(Color::TRANSPARENT);
            list.draw_mesh(
                &quad(Rect::new(0., 0., 32., 64.), 0., Color::new(1., 1., 1., 0.5)),
                Mat4::IDENTITY,
                BlendMode::Alpha,
            );
            // This contributes red light while preserving the cleared coverage alpha=0.
            list.draw_mesh(
                &quad(
                    Rect::new(32., 0., 32., 64.),
                    0.,
                    Color::new(1., 0., 0., 0.5),
                ),
                Mat4::IDENTITY,
                BlendMode::Additive,
            );
            list.capture_png(Some(&target), self.path("alpha-target.png"));
            list.camera(Camera::screen(96, 64));
            list.clear(Color::TRANSPARENT);
            list.draw_texture(&target.texture, Rect::new(0., 0., 96., 64.), Color::WHITE);
            list.capture_png(None, self.path("alpha-main-display.png"));
            list.clear(Color::new(0., 0., 0., 1.));
            list.draw_texture(&target.texture, Rect::new(0., 0., 96., 64.), Color::WHITE);
            list.capture_png(None, self.path("alpha-composite.png"));
            list.clear(Color::new(0., 0., 0., 1.));
            list.draw_texture(
                &target.texture,
                Rect::new(0., 0., 96., 64.),
                Color::new(0.5, 0.25, 1., 0.5),
            );
            list.capture_png(None, self.path("alpha-tinted-composite.png"));
            let mut camera = Camera::screen(96, 64);
            camera.target = Some(target.clone());
            list.camera(camera);
            list.clear(Color::new(1., 1., 1., 0.5));
            list.capture_png(Some(&target), self.path("alpha-clear.png"));
            list.clear(Color::TRANSPARENT);
            list.draw_mesh(
                &quad(Rect::new(0., 0., 96., 64.), 0., Color::new(1., 1., 1., 0.5)),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
            list.capture_png(Some(&target), self.path("alpha-opaque-source.png"));
            self.submit(
                &list,
                &[
                    "alpha-target.png",
                    "alpha-main-display.png",
                    "alpha-composite.png",
                    "alpha-tinted-composite.png",
                    "alpha-clear.png",
                    "alpha-opaque-source.png",
                ],
            )?;
            for (file, case, alpha, colors) in [
                (
                    "alpha-target.png",
                    "raw-associated-and-emissive-target",
                    ASSOCIATED,
                    [[127, 127, 127, 127], [127, 0, 0, 0], [0, 0, 0, 0]],
                ),
                (
                    "alpha-main-display.png",
                    "main-capture-flattens-coverage-preserving-emission",
                    OPAQUE,
                    [[127, 127, 127, 255], [127, 0, 0, 255], [0, 0, 0, 255]],
                ),
                (
                    "alpha-composite.png",
                    "target-composited-over-opaque-black",
                    OPAQUE,
                    [[127, 127, 127, 255], [127, 0, 0, 255], [0, 0, 0, 255]],
                ),
                // Independent constants: 127*(127/255)*(127/255),
                // 127*(63/255)*(127/255), and 127*(127/255).
                (
                    "alpha-tinted-composite.png",
                    "target-tint-opacity-scales-associated-rgb",
                    OPAQUE,
                    [[32, 16, 63, 255], [32, 0, 0, 255], [0, 0, 0, 255]],
                ),
            ] {
                let probes = [
                    Probe {
                        label: "half-alpha white",
                        bounds: [0.1, 0.25, 0.1, 0.9],
                        rgba: colors[0],
                    },
                    Probe {
                        label: "red emission with zero coverage",
                        bounds: [0.4, 0.6, 0.1, 0.9],
                        rgba: colors[1],
                    },
                    Probe {
                        label: "transparent untouched region",
                        bounds: [0.75, 0.9, 0.1, 0.9],
                        rgba: colors[2],
                    },
                ];
                self.record(
                    file,
                    case,
                    (96, 64),
                    alpha,
                    &probes,
                    json!({"vertex_alpha_u8":127}),
                )?;
            }
            self.record(
                "alpha-clear.png",
                "clear-associates-straight-color",
                (96, 64),
                ASSOCIATED,
                &solid_probe([128, 128, 128, 128]),
                Value::Null,
            )?;
            self.record(
                "alpha-opaque-source.png",
                "opaque-replacement-associates-straight-source",
                (96, 64),
                ASSOCIATED,
                &solid_probe([127, 127, 127, 127]),
                Value::Null,
            )?;
            Ok(())
        }

        fn text_dpi(&mut self) -> Result<(), String> {
            for (scale, filename) in [(1, "text-100-percent.png"), (2, "text-200-percent.png")] {
                let width = 64 * scale;
                let height = 48 * scale;
                let size = 16. * scale as f32;
                let dimensions = self.renderer.measure_text("Ag ", size)?;
                let expected = [21., 11., 8.].map(|v| v * scale as f32);
                if [dimensions.width, dimensions.height, dimensions.offset_y] != expected {
                    return Err(format!(
                        "text {size}px dimensions changed: {dimensions:?}, expected {expected:?}"
                    ));
                }
                let mut list = DrawList::new(width, height);
                list.clear(Color::new(0., 0., 0., 1.));
                list.draw_text("Ag", Vec2::new(10., 20.) * scale as f32, size, Color::WHITE);
                list.capture_png(None, self.path(filename));
                self.submit(&list, &[filename])?;
                let image = read_png(&self.path(filename), width, height)?;
                // Fixed ProggyClean raster bounds, independently recorded in text's CPU contract.
                let expected_bounds = [11 * scale, 12 * scale, 23 * scale, 23 * scale];
                let actual_bounds = ink_bounds(&image)?;
                if actual_bounds != expected_bounds {
                    return Err(format!(
                        "{filename}: ink bounds {actual_bounds:?}, expected {expected_bounds:?}"
                    ));
                }
                self.record(filename, "physical-pixel-text-rasterization", (width,height), OPAQUE, &[],
                    json!({"dpi_percent":100*scale,"font_size_physical_px":size,
                        "text":"Ag", "measured_with_trailing_space":"Ag ",
                        "metrics":{"width":dimensions.width,"height":dimensions.height,"offset_y":dimensions.offset_y},
                        "ink_bounds_exclusive":actual_bounds,"claim":"raster dimensions only; no font-style or OS-DPI claim"}))?;
            }
            Ok(())
        }

        fn expected_failures(&mut self) -> Result<Value, String> {
            let blocked = self.path("blocked-parent");
            fs::write(
                &blocked,
                b"This regular file intentionally blocks PNG parent creation.\n",
            )
            .map_err(|error| format!("prepare invalid PNG parent: {error}"))?;
            let directory = self.path("capture-is-directory.png");
            fs::create_dir(&directory)
                .map_err(|error| format!("prepare invalid PNG filename: {error}"))?;
            let mut errors = Vec::new();
            for (path, expected) in [
                (blocked.join("capture.png"), "create capture directory"),
                (directory, "write capture"),
                (PathBuf::new(), "capture path must not be empty"),
            ] {
                let mut list = DrawList::new(16, 16);
                list.clear(Color::WHITE);
                list.capture_png(None, path);
                let error = self
                    .renderer
                    .submit(&list)
                    .expect_err_or("invalid PNG path was unexpectedly accepted")?;
                if !error.contains(expected) {
                    return Err(format!("invalid PNG path reached the wrong failure: expected {expected:?}, got {error:?}"));
                }
                errors.push(json!({"expected_error":expected,"actual_error":error}));
            }
            let mut invalid = DrawList::new(16, 16);
            let mut mesh = quad(Rect::new(0., 0., 16., 16.), 0., Color::WHITE);
            mesh.vertices[0].position.x = f32::NAN;
            invalid.draw_mesh(&mesh, Mat4::IDENTITY, BlendMode::Opaque);
            let error = self
                .renderer
                .submit(&invalid)
                .expect_err_or("non-finite mesh was unexpectedly accepted")?;
            if !error.contains("non-finite") {
                return Err(format!("wrong non-finite rejection: {error}"));
            }
            errors.push(json!({"expected_error":"non-finite","actual_error":error}));
            let mut recovery = DrawList::new(16, 16);
            recovery.clear(Color::new(0., 1., 0., 1.));
            recovery.capture_png(None, self.path("after-errors.png"));
            self.submit(&recovery, &["after-errors.png"])?;
            self.record(
                "after-errors.png",
                "renderer-recovers-after-rejected-captures",
                (16, 16),
                OPAQUE,
                &solid_probe([0, 255, 0, 255]),
                Value::Null,
            )?;
            Ok(json!(errors))
        }
    }

    #[cfg(feature = "wgpu-runtime")]
    trait ExpectedError {
        fn expect_err_or(self, accepted: &str) -> Result<String, String>;
    }
    #[cfg(feature = "wgpu-runtime")]
    impl<T> ExpectedError for Result<T, String> {
        fn expect_err_or(self, accepted: &str) -> Result<String, String> {
            match self {
                Ok(_) => Err(accepted.into()),
                Err(error) => Ok(error),
            }
        }
    }

    #[cfg(feature = "wgpu-runtime")]
    fn quad(rect: Rect, z: f32, color: Color) -> Mesh {
        Mesh {
            vertices: vec![
                Vertex::new(rect.x, rect.y, z, 0., 0., color),
                Vertex::new(rect.x + rect.w, rect.y, z, 1., 0., color),
                Vertex::new(rect.x + rect.w, rect.y + rect.h, z, 1., 1., color),
                Vertex::new(rect.x, rect.y + rect.h, z, 0., 1., color),
            ],
            indices: vec![0, 1, 2, 0, 2, 3],
            texture: None,
        }
    }

    #[cfg(feature = "wgpu-runtime")]
    fn named_target_quadrants(raw: PathBuf, composite: PathBuf) -> Result<DrawList, String> {
        let target = RenderTarget::new(96, 64, false)?;
        let mut camera = Camera::screen(96, 64);
        camera.target = Some(target.clone());
        let mut list = DrawList::new(96, 64);
        list.camera(camera);
        list.clear(Color::TRANSPARENT);
        for (x, y, color) in [
            (0., 0., Color::new(1., 0., 0., 1.)),
            (48., 0., Color::new(0., 1., 0., 1.)),
            (0., 32., Color::new(0., 0., 1., 1.)),
            (48., 32., Color::new(1., 1., 0., 1.)),
        ] {
            list.draw_mesh(
                &quad(Rect::new(x, y, 48., 32.), 0., color),
                Mat4::IDENTITY,
                BlendMode::Opaque,
            );
        }
        list.capture_png(Some(&target), raw);
        list.camera(Camera::screen(96, 64));
        list.clear(Color::new(0., 0., 0., 1.));
        // Sample the unchanged target through the real Sprite path, without UV compensation.
        list.draw_texture(&target.texture, Rect::new(0., 0., 96., 64.), Color::WHITE);
        list.capture_png(None, composite);
        Ok(list)
    }

    fn ink_bounds(image: &RgbaImage) -> Result<[u32; 4], String> {
        let mut bounds = [image.width(), image.height(), 0, 0];
        for (x, y, pixel) in image.enumerate_pixels() {
            if pixel.0[..3].iter().any(|&value| value > 8) {
                bounds[0] = bounds[0].min(x);
                bounds[1] = bounds[1].min(y);
                bounds[2] = bounds[2].max(x + 1);
                bounds[3] = bounds[3].max(y + 1);
            }
        }
        if bounds[0] >= bounds[2] || bounds[1] >= bounds[3] {
            return Err("text capture has no visible glyph coverage".into());
        }
        Ok(bounds)
    }

    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native DX12 renderer contract requires Windows; this platform can compile and run CPU helper tests, but cannot produce a native pass".into());
        }
        prepare_output(&options.output_dir)?;
        let renderer = pollster::block_on(WgpuRenderer::new_headless(
            96,
            64,
            BackendSelection::Dx12,
            options.force_fallback_adapter,
        ))?;
        verify_backend(renderer.info())?;
        let mut contract = Contract {
            renderer,
            options,
            captures: Vec::new(),
        };
        contract.quadrants(96, 64, "quadrant.png")?;
        contract.quadrants(65, 49, "readback-width-65.png")?;
        contract.target_quadrants()?;
        contract.ordered_captures()?;
        contract.camera_depth()?;
        contract.alpha_targets()?;
        contract.text_dpi()?;
        let expected_failures = contract.expected_failures()?;
        let info = contract.renderer.info();
        let report = json!({
            "schema_version":1, "status":"passed", "native_execution":true,
            "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
            "force_fallback_adapter":contract.options.force_fallback_adapter,
            "platform":std::env::consts::OS,"build_version":vector_range::BUILD_VERSION,
            "build_number":vector_range::BUILD_NUMBER,
            "captures":contract.captures,"expected_failures":expected_failures,
            "scope":"headless DX12 renderer contract; not window presentation, native DPI, gameplay, performance or artistic approval",
        });
        write_json(&contract.path(REPORT), &report)?;
        println!(
            "DX12 renderer contract passed on {}: {} captures; {}",
            info.adapter,
            contract.captures.len(),
            contract.path(REPORT).display()
        );
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use image::Rgba;
        use std::sync::atomic::{AtomicU64, Ordering};

        struct Scratch(PathBuf);
        impl Scratch {
            fn new() -> Self {
                static NEXT: AtomicU64 = AtomicU64::new(0);
                let path = std::env::temp_dir().join(format!(
                    "rust-duty-renderer-contract-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                ));
                fs::create_dir(&path).unwrap();
                Self(path)
            }
        }
        impl Drop for Scratch {
            fn drop(&mut self) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }

        #[test]
        fn cli_requires_explicit_dx12_and_output_directory() {
            let options = Options::parse([
                "--renderer=dx12",
                "--force-fallback-adapter",
                "--output-dir",
                "out",
            ])
            .unwrap();
            assert_eq!(
                options,
                Options {
                    force_fallback_adapter: true,
                    output_dir: PathBuf::from("out")
                }
            );
            let options = Options::parse(["--renderer", "dx12", "--output-dir=out"]).unwrap();
            assert!(!options.force_fallback_adapter);
            for args in [
                vec![],
                vec!["--renderer=dx12"],
                vec!["--output-dir=out"],
                vec!["--renderer"],
                vec!["--renderer=dx12", "--output-dir"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--output-dir=out", "--unknown"],
                vec!["--renderer=dx12", "--renderer=dx12", "--output-dir=out"],
                vec!["--renderer=dx12", "--output-dir=out", "--output-dir=out"],
                vec![
                    "--renderer=dx12",
                    "--output-dir=out",
                    "--force-fallback-adapter",
                    "--force-fallback-adapter",
                ],
            ] {
                assert!(Options::parse(args.clone()).is_err(), "accepted {args:?}");
            }
            for backend in ["auto", "vulkan", "metal", "gl", "DX12", ""] {
                assert!(Options::parse([
                    format!("--renderer={backend}"),
                    "--output-dir=out".into()
                ])
                .is_err());
            }
        }

        fn independent_quadrants() -> RgbaImage {
            // Independent CPU control data: never read renderer shaders or capture outputs.
            RgbaImage::from_fn(100, 100, |x, y| {
                Rgba(match (x < 50, y < 50) {
                    (true, true) => [255, 0, 0, 255],
                    (false, true) => [0, 255, 0, 255],
                    (true, false) => [0, 0, 255, 255],
                    (false, false) => [255, 255, 0, 255],
                })
            })
        }

        #[test]
        fn fixed_quadrant_probes_reject_vertical_flip_and_color_swaps() {
            let image = independent_quadrants();
            for probe in quadrant_probes() {
                inspect_probe(&image, probe).unwrap();
            }
            let flipped = image::imageops::flip_vertical(&image);
            for probe in quadrant_probes() {
                assert!(inspect_probe(&flipped, probe).is_err());
            }
            let swapped = RgbaImage::from_fn(100, 100, |x, y| {
                let p = image.get_pixel(x, y);
                Rgba([p[2], p[1], p[0], p[3]])
            });
            assert!(inspect_probe(&swapped, quadrant_probes()[0]).is_err());
        }

        #[cfg(feature = "wgpu-runtime")]
        #[test]
        fn named_target_quadrants_capture_then_sample_the_same_unchanged_target() {
            use vector_range::draw::{Command, TextureSource};

            let raw = PathBuf::from("quadrant-target.png");
            let composite = PathBuf::from("quadrant-target-composite.png");
            let list = named_target_quadrants(raw.clone(), composite.clone()).unwrap();
            assert_eq!((list.width, list.height), (96, 64));
            let [Command::Camera(target_camera), Command::Clear(target_clear), quadrants @ .., Command::Capture {
                target: Some(captured_target),
                path: raw_path,
            }, Command::Camera(main_camera), Command::Clear(main_clear), Command::Sprite {
                texture,
                destination,
                tint,
            }, Command::Capture {
                target: None,
                path: composite_path,
            }] = list.commands.as_slice()
            else {
                panic!(
                    "expected named-target drawing, raw capture, then target sampling into main"
                );
            };
            let target = target_camera.target.as_ref().unwrap();
            assert_eq!((target.texture.width, target.texture.height), (96, 64));
            assert!(matches!(
                target.texture.source,
                TextureSource::Target { depth: false }
            ));
            assert_eq!(target.texture.id, captured_target.texture.id);
            assert_eq!(target.texture.id, texture.id);
            assert!(!target_camera.depth_test);
            assert!(main_camera.target.is_none());
            assert_eq!(*target_clear, Color::TRANSPARENT);
            assert_eq!(*main_clear, Color::new(0., 0., 0., 1.));
            assert_eq!(*destination, Rect::new(0., 0., 96., 64.));
            assert_eq!(*tint, Color::WHITE);
            assert_eq!(*raw_path, raw);
            assert_eq!(*composite_path, composite);
            assert_eq!(quadrants.len(), 4);
            for (command, (x, y, rgba)) in quadrants.iter().zip([
                (0., 0., [255, 0, 0, 255]),
                (48., 0., [0, 255, 0, 255]),
                (0., 32., [0, 0, 255, 255]),
                (48., 32., [255, 255, 0, 255]),
            ]) {
                let Command::Mesh { mesh, model, blend } = command else {
                    panic!("expected a colored quadrant mesh");
                };
                assert_eq!(*model, Mat4::IDENTITY);
                assert_eq!(*blend, BlendMode::Opaque);
                assert!(mesh.texture.is_none());
                assert_eq!(mesh.indices, [0, 1, 2, 0, 2, 3]);
                assert_eq!(
                    mesh.vertices
                        .iter()
                        .map(|v| v.position.to_array())
                        .collect::<Vec<_>>(),
                    [
                        [x, y, 0.],
                        [x + 48., y, 0.],
                        [x + 48., y + 32., 0.],
                        [x, y + 32., 0.]
                    ]
                );
                assert!(mesh.vertices.iter().all(|v| v.color == rgba));
            }
        }

        #[test]
        fn probe_tolerance_and_ninety_percent_threshold_are_enforced() {
            let probe = Probe {
                label: "threshold",
                bounds: [0., 1., 0., 1.],
                rgba: [127, 127, 127, 255],
            };
            let mut image = RgbaImage::from_pixel(10, 10, Rgba([135, 119, 127, 255]));
            for x in 0..10 {
                image.put_pixel(x, 0, Rgba([0, 0, 0, 255]));
            }
            inspect_probe(&image, probe).unwrap();
            image.put_pixel(0, 1, Rgba([0, 0, 0, 255]));
            assert!(inspect_probe(&image, probe).is_err());
            assert!(inspect_probe(
                &RgbaImage::from_pixel(10, 10, Rgba([136, 127, 127, 255])),
                probe
            )
            .is_err());
            assert!(inspect_probe(
                &image,
                Probe {
                    bounds: [f64::NAN, 1., 0., 1.],
                    ..probe
                }
            )
            .is_err());
            assert!(inspect_probe(&RgbaImage::new(0, 0), probe).is_err());
        }

        #[test]
        fn alpha_probe_distinguishes_double_alpha_and_lost_emission() {
            let associated = Probe {
                label: "associated white",
                bounds: [0., 1., 0., 1.],
                rgba: [127, 127, 127, 127],
            };
            inspect_probe(
                &RgbaImage::from_pixel(8, 8, Rgba([127, 127, 127, 127])),
                associated,
            )
            .unwrap();
            assert!(inspect_probe(
                &RgbaImage::from_pixel(8, 8, Rgba([255, 255, 255, 127])),
                associated
            )
            .is_err());
            let composite = Probe {
                rgba: [127, 127, 127, 255],
                ..associated
            };
            assert!(inspect_probe(
                &RgbaImage::from_pixel(8, 8, Rgba([63, 63, 63, 255])),
                composite
            )
            .is_err());
            let emission = Probe {
                rgba: [127, 0, 0, 255],
                ..associated
            };
            assert!(
                inspect_probe(&RgbaImage::from_pixel(8, 8, Rgba([0, 0, 0, 255])), emission)
                    .is_err()
            );
            let tint = Probe {
                rgba: [32, 16, 63, 255],
                ..associated
            };
            assert!(
                inspect_probe(&RgbaImage::from_pixel(8, 8, Rgba([63, 31, 127, 255])), tint)
                    .is_err()
            );
        }

        #[test]
        fn coverage_and_ink_bounds_require_real_pixels() {
            assert!(coverage(&RgbaImage::new(0, 0)).is_err());
            assert!(coverage(&RgbaImage::from_pixel(10, 10, Rgba([0, 0, 0, 255]))).is_err());
            let mut image = RgbaImage::from_pixel(10, 10, Rgba([0, 0, 0, 255]));
            assert!(ink_bounds(&image).is_err());
            image.put_pixel(2, 3, Rgba([127, 0, 0, 0]));
            image.put_pixel(5, 6, Rgba([255, 255, 255, 255]));
            coverage(&image).unwrap();
            assert_eq!(ink_bounds(&image).unwrap(), [2, 3, 6, 7]);
        }

        #[test]
        fn text_probe_uses_fixed_physical_pixel_goldens() {
            use glam::Vec2;
            use vector_range::{
                draw::{Color, TextureSource},
                render::text::TextRenderer,
            };
            let mut text = TextRenderer::new().unwrap();
            for scale in [1, 2] {
                let mut image = RgbaImage::new(64 * scale, 48 * scale);
                let meshes = text
                    .meshes(
                        "Ag",
                        Vec2::new(10., 20.) * scale as f32,
                        16. * scale as f32,
                        Color::WHITE,
                    )
                    .unwrap();
                for mesh in meshes {
                    let origin = mesh.vertices[0].position;
                    let texture = mesh.texture.unwrap();
                    let TextureSource::Rgba8(bytes) = texture.source else {
                        panic!("text raster must provide CPU pixels");
                    };
                    for y in 0..texture.height {
                        for x in 0..texture.width {
                            let alpha = bytes[((y * texture.width + x) * 4 + 3) as usize];
                            image.put_pixel(
                                origin.x as u32 + x,
                                origin.y as u32 + y,
                                Rgba([alpha, alpha, alpha, 255]),
                            );
                        }
                    }
                }
                assert_eq!(
                    ink_bounds(&image).unwrap(),
                    [11 * scale, 12 * scale, 23 * scale, 23 * scale]
                );
            }
        }

        #[test]
        fn output_and_png_io_failures_are_errors_and_do_not_publish_a_report() {
            let scratch = Scratch::new();
            let output = scratch.0.join("out");
            prepare_output(&output).unwrap();
            prepare_output(&output).unwrap();
            let png = output.join("control.png");
            independent_quadrants().save(&png).unwrap();
            read_png(&png, 100, 100).unwrap();
            assert!(read_png(&png, 65, 100).is_err());
            assert!(read_png(&output.join("missing.png"), 100, 100).is_err());
            assert!(prepare_output(&output).is_err());
            assert!(prepare_output(&png).is_err());
            assert!(prepare_output(&png.join("child")).is_err());
            let invalid = output.join("invalid.png");
            fs::write(&invalid, b"not an image").unwrap();
            assert!(read_png(&invalid, 1, 1).is_err());
            assert!(write_json(&png.join("bad.json"), &json!({"status":"passed"})).is_err());
            assert!(!output.join(REPORT).exists());
        }

        #[cfg(feature = "wgpu-runtime")]
        #[test]
        fn backend_identity_cannot_be_faked_by_request_alone() {
            let valid = BackendInfo {
                requested: "dx12".into(),
                backend: "Dx12".into(),
                adapter: "WARP".into(),
            };
            verify_backend(&valid).unwrap();
            for invalid in [
                BackendInfo {
                    backend: "Vulkan".into(),
                    ..valid.clone()
                },
                BackendInfo {
                    adapter: " ".into(),
                    ..valid.clone()
                },
                BackendInfo {
                    requested: "auto".into(),
                    ..valid
                },
            ] {
                assert!(verify_backend(&invalid).is_err());
            }
        }

        #[cfg(all(feature = "wgpu-runtime", not(target_os = "windows")))]
        #[test]
        fn non_windows_native_run_is_an_error_without_artifacts() {
            let scratch = Scratch::new();
            let output = scratch.0.join("not-created");
            let error = run([
                "--renderer=dx12".to_owned(),
                "--force-fallback-adapter".into(),
                format!("--output-dir={}", output.display()),
            ])
            .unwrap_err();
            assert!(error.contains("requires Windows"));
            assert!(!output.exists());
        }
    }
}
