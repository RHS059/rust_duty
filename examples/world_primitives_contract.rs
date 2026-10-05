//! Independent native evidence for the public world's line, wire and sphere facade.
//!
//! Windows: cargo run --locked --no-default-features --features wgpu-runtime
//! --example world_primitives_contract -- --renderer=dx12
//! --force-fallback-adapter --output-dir <fresh-directory>
//!
//! Every expected region below is fixed analytically, never fitted to a capture or
//! computed by the renderer's projection/geometry implementation. For our camera
//! (1,2,3), looking down -Z, fovy=90 degrees, aspect=4/3, near=1 and far=20:
//! d=3-z, pixel x=80+60*(x-1)/d, pixel y=60-60*(y-2)/d.
//! Thus near/far lines at d=3/6 project to (20..60,40)/(50..70,50).
//! Wire faces at d=3/5 have independently specified edge and connector probes.
//! Two nested spheres are separated in depth; later far geometry must not win.
//! CPU tests and non-Windows execution can never generate a native success report.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("world_primitives_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("world_primitives_contract requires --features wgpu-runtime and Windows DX12");
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", test))]
mod fixture {
    use image::RgbaImage;
    use serde_json::{json, Value};
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    use vector_range::draw::{facade as draw, BackendInfo, DrawList};
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        draw::Renderer,
        render::{BackendSelection, WgpuRenderer},
    };

    const WIDTH: u32 = 160;
    const HEIGHT: u32 = 120;
    const TOLERANCE: u8 = 8;
    const REPORT: &str = "world-primitives-contract-report.json";
    const WARP: &str = "Microsoft Basic Render Driver";
    #[cfg(feature = "wgpu-runtime")]
    const SCOPE: &str = "headless public-facade world primitive projection, model transforms, clipping and depth; not window presentation, gameplay, performance or artistic approval";
    const BLACK: [u8; 4] = [0, 0, 0, 255];
    const RED: [u8; 4] = [255, 0, 0, 255];
    const GREEN: [u8; 4] = [0, 255, 0, 255];
    const BLUE: [u8; 4] = [0, 0, 255, 255];
    const CYAN: [u8; 4] = [0, 255, 255, 255];
    const YELLOW: [u8; 4] = [255, 255, 0, 255];
    const MAGENTA: [u8; 4] = [255, 0, 255, 255];

    #[derive(Debug, PartialEq, Eq)]
    struct Options {
        force_fallback_adapter: bool,
        output_dir: PathBuf,
    }
    impl Options {
        fn parse(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Self, String> {
            let mut args = args.into_iter().map(Into::into);
            let (mut renderer, mut output) = (None, None);
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
                    _ => return Err(format!("unknown or duplicate argument {arg:?}")),
                }
            }
            if renderer.as_deref() != Some("dx12") {
                return Err(
                    "explicit --renderer=dx12 is required; no fallback backend is accepted".into(),
                );
            }
            let output = output
                .filter(|value| !value.trim().is_empty() && !value.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                force_fallback_adapter: fallback,
                output_dir: output.into(),
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
                .map_err(|e| format!("read output: {e}"))?
                .next()
                .transpose()
                .map_err(|e| format!("read output entry: {e}"))?
                .is_some()
            {
                return Err("output directory must be empty; stale evidence cannot pass".into());
            }
        } else {
            fs::create_dir_all(path).map_err(|e| format!("create output: {e}"))?;
        }
        Ok(())
    }
    fn verify_backend(info: &BackendInfo, fallback: bool) -> Result<(), String> {
        if info.requested != "dx12"
            || info.backend != "Dx12"
            || info.adapter.trim().is_empty()
            || (fallback && !info.adapter.eq_ignore_ascii_case(WARP))
        {
            return Err(format!(
                "requires actual Dx12 and {}named adapter, got {info:?}",
                if fallback { "WARP " } else { "" }
            ));
        }
        Ok(())
    }

    #[derive(Clone, Copy, Debug)]
    struct Probe {
        label: &'static str,
        mode: &'static str,
        bounds: [u32; 4],
        rgba: [u8; 4],
    }
    const fn probe(
        label: &'static str,
        mode: &'static str,
        bounds: [u32; 4],
        rgba: [u8; 4],
    ) -> Probe {
        Probe {
            label,
            mode,
            bounds,
            rgba,
        }
    }
    #[derive(Clone, Debug)]
    struct Case {
        filename: &'static str,
        case: &'static str,
        probes: Vec<Probe>,
        // Axis-aligned conservative envelopes, not a generated silhouette mask.
        envelopes: Vec<[u32; 4]>,
        palette: Vec<[u8; 4]>,
        forbidden: Vec<[u8; 4]>,
    }
    fn cases() -> [Case; 3] {
        [
            Case {
                filename: "world-lines-perspective.png",
                case: "facade-lines-perspective-model-and-clipping",
                probes: vec![
                    probe(
                        "near red perspective line",
                        "horizontal",
                        [23, 57, 39, 42],
                        RED,
                    ),
                    probe(
                        "far green perspective line",
                        "horizontal",
                        [53, 67, 49, 52],
                        GREEN,
                    ),
                    probe(
                        "cyan vertical world line",
                        "vertical",
                        [139, 142, 43, 77],
                        CYAN,
                    ),
                    probe(
                        "rotated translated blue model line",
                        "vertical",
                        [79, 82, 63, 97],
                        BLUE,
                    ),
                    probe("clear background", "area", [5, 15, 5, 15], BLACK),
                ],
                envelopes: vec![
                    [18, 62, 38, 42],
                    [48, 72, 48, 52],
                    [138, 142, 38, 82],
                    [78, 82, 58, 102],
                ],
                palette: vec![RED, GREEN, CYAN, BLUE],
                forbidden: vec![MAGENTA, YELLOW],
            },
            Case {
                filename: "world-wires-perspective.png",
                case: "facade-wire-box-twelve-edges-and-model",
                probes: vec![
                    probe("green near top", "horizontal", [23, 57, 39, 42], GREEN),
                    probe("green near bottom", "horizontal", [23, 57, 79, 82], GREEN),
                    probe("green near left", "vertical", [19, 22, 43, 77], GREEN),
                    probe("green near right", "vertical", [59, 62, 43, 77], GREEN),
                    probe("green far top", "horizontal", [47, 65, 47, 50], GREEN),
                    probe("green far bottom", "horizontal", [47, 65, 71, 74], GREEN),
                    probe("green far left", "vertical", [43, 46, 51, 69], GREEN),
                    probe("green far right", "vertical", [67, 70, 51, 69], GREEN),
                    probe("green upper left connector", "any", [30, 35, 42, 47], GREEN),
                    probe(
                        "green upper right connector",
                        "any",
                        [62, 67, 42, 47],
                        GREEN,
                    ),
                    probe("green lower left connector", "any", [30, 35, 74, 79], GREEN),
                    probe(
                        "green lower right connector",
                        "any",
                        [62, 67, 74, 79],
                        GREEN,
                    ),
                    probe(
                        "yellow model near top",
                        "horizontal",
                        [103, 137, 49, 52],
                        YELLOW,
                    ),
                    probe(
                        "yellow model near bottom",
                        "horizontal",
                        [103, 137, 69, 72],
                        YELLOW,
                    ),
                    probe(
                        "yellow model near left",
                        "vertical",
                        [99, 102, 53, 67],
                        YELLOW,
                    ),
                    probe(
                        "yellow model near right",
                        "vertical",
                        [139, 142, 53, 67],
                        YELLOW,
                    ),
                    probe(
                        "yellow model far top",
                        "horizontal",
                        [95, 113, 53, 56],
                        YELLOW,
                    ),
                    probe(
                        "yellow model far bottom",
                        "horizontal",
                        [95, 113, 65, 68],
                        YELLOW,
                    ),
                    probe(
                        "yellow model far left",
                        "vertical",
                        [91, 94, 57, 63],
                        YELLOW,
                    ),
                    probe(
                        "yellow model far right",
                        "vertical",
                        [115, 118, 57, 63],
                        YELLOW,
                    ),
                    probe(
                        "yellow upper left connector",
                        "any",
                        [94, 99, 51, 54],
                        YELLOW,
                    ),
                    probe(
                        "yellow upper right connector",
                        "any",
                        [125, 131, 51, 54],
                        YELLOW,
                    ),
                    probe(
                        "yellow lower left connector",
                        "any",
                        [94, 99, 67, 70],
                        YELLOW,
                    ),
                    probe(
                        "yellow lower right connector",
                        "any",
                        [125, 131, 67, 70],
                        YELLOW,
                    ),
                    probe("wire interior is unfilled", "area", [25, 35, 50, 70], BLACK),
                    probe(
                        "transformed wire interior is unfilled",
                        "area",
                        [123, 133, 57, 63],
                        BLACK,
                    ),
                    probe("clear background", "area", [5, 15, 5, 15], BLACK),
                ],
                envelopes: vec![[18, 70, 38, 82], [90, 142, 48, 72]],
                palette: vec![GREEN, YELLOW],
                forbidden: vec![],
            },
            Case {
                filename: "world-spheres-depth.png",
                case: "facade-sphere-perspective-model-and-occluded-lines",
                probes: vec![
                    probe(
                        "near sphere occludes later far sphere and line",
                        "area",
                        [40, 58, 56, 65],
                        RED,
                    ),
                    probe("near sphere upper interior", "area", [45, 55, 49, 54], RED),
                    probe("near sphere lower interior", "area", [45, 55, 67, 72], RED),
                    probe(
                        "near cyan line in front of sphere",
                        "horizontal",
                        [29, 71, 44, 47],
                        CYAN,
                    ),
                    probe(
                        "far yellow line exposed left",
                        "horizontal",
                        [21, 28, 59, 62],
                        YELLOW,
                    ),
                    probe(
                        "far yellow line exposed right",
                        "horizontal",
                        [69, 77, 59, 62],
                        YELLOW,
                    ),
                    probe(
                        "scaled sphere upper interior",
                        "area",
                        [107, 113, 50, 55],
                        GREEN,
                    ),
                    probe(
                        "scaled sphere lower interior",
                        "area",
                        [107, 113, 65, 70],
                        GREEN,
                    ),
                    probe("clear background", "area", [5, 15, 5, 15], BLACK),
                    probe("sphere gap remains clear", "area", [85, 95, 50, 70], BLACK),
                ],
                envelopes: vec![[18, 82, 39, 81], [98, 122, 42, 78]],
                palette: vec![RED, CYAN, YELLOW, GREEN],
                forbidden: vec![BLUE],
            },
        ]
    }
    fn near(actual: [u8; 4], expected: [u8; 4]) -> bool {
        actual
            .into_iter()
            .zip(expected)
            .all(|(a, e)| a.abs_diff(e) <= TOLERANCE)
    }
    fn inspect_probe(image: &RgbaImage, p: Probe) -> Result<Value, String> {
        let [left, right, top, bottom] = p.bounds;
        if left >= right || top >= bottom || right > image.width() || bottom > image.height() {
            return Err(format!("{}: invalid or empty probe bounds", p.label));
        }
        let matches = |x, y| near(image.get_pixel(x, y).0, p.rgba);
        let (matched, total, minimum) = match p.mode {
            "area" => (
                (top..bottom)
                    .map(|y| (left..right).filter(|&x| matches(x, y)).count() as u64)
                    .sum(),
                u64::from(right - left) * u64::from(bottom - top),
                0.95,
            ),
            "horizontal" => (
                (left..right)
                    .filter(|&x| (top..bottom).any(|y| matches(x, y)))
                    .count() as u64,
                u64::from(right - left),
                0.9,
            ),
            "vertical" => (
                (top..bottom)
                    .filter(|&y| (left..right).any(|x| matches(x, y)))
                    .count() as u64,
                u64::from(bottom - top),
                0.9,
            ),
            "any" => (
                u64::from((top..bottom).any(|y| (left..right).any(|x| matches(x, y)))),
                1,
                1.0,
            ),
            _ => return Err(format!("{}: unknown probe mode", p.label)),
        };
        let fraction = matched as f64 / total as f64;
        if fraction < minimum {
            return Err(format!(
                "{}: {matched}/{total} matching samples, need {minimum}",
                p.label
            ));
        }
        Ok(
            json!({"label":p.label,"mode":p.mode,"pixel_bounds":p.bounds,"expected_rgba":p.rgba,
            "matching_samples":matched,"total_samples":total,"match_fraction":fraction,
            "minimum_match_fraction":minimum,"channel_tolerance":TOLERANCE}),
        )
    }
    fn inspect_image(image: &RgbaImage, spec: &Case) -> Result<Value, String> {
        if image.dimensions() != (WIDTH, HEIGHT) {
            return Err("wrong PNG dimensions".into());
        }
        let mut nonblack = 0_u64;
        let mut colors = vec![0_u64; spec.palette.len()];
        for (x, y, p) in image.enumerate_pixels() {
            if p[3] != 255 {
                return Err("main capture alpha is not opaque".into());
            }
            if near(p.0, BLACK) {
                continue;
            }
            if spec.forbidden.iter().any(|&color| near(p.0, color)) {
                return Err(format!(
                    "{}: forbidden clipped/occluded color at ({x},{y})",
                    spec.filename
                ));
            }
            if !spec
                .envelopes
                .iter()
                .any(|&[l, r, t, b]| x >= l && x < r && y >= t && y < b)
            {
                return Err(format!(
                    "{}: nonblack pixel outside fixed projection envelopes at ({x},{y})",
                    spec.filename
                ));
            }
            let index = spec
                .palette
                .iter()
                .position(|&color| near(p.0, color))
                .ok_or_else(|| format!("{}: unexpected color at ({x},{y})", spec.filename))?;
            colors[index] += 1;
            nonblack += 1;
        }
        if nonblack == 0 || colors.contains(&0) {
            return Err("capture is missing a required primitive color".into());
        }
        let probes = spec
            .probes
            .iter()
            .map(|&p| inspect_probe(image, p))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(
            json!({"coverage":{"nonblack_pixels":nonblack,"total_pixels":u64::from(WIDTH)*u64::from(HEIGHT),
            "nonblack_fraction":nonblack as f64/f64::from(WIDTH*HEIGHT)},"probes":probes,
            "projection_envelopes":spec.envelopes,"palette":spec.palette,"palette_pixel_counts":colors,
            "forbidden_colors":spec.forbidden,"forbidden_color_pixels":0,"outside_envelope_pixels":0,
            "channel_tolerance":TOLERANCE}),
        )
    }
    fn read_png(path: &Path) -> Result<RgbaImage, String> {
        let reader = image::io::Reader::open(path)
            .map_err(|e| format!("read PNG: {e}"))?
            .with_guessed_format()
            .map_err(|e| format!("identify PNG: {e}"))?;
        if reader.format() != Some(image::ImageFormat::Png) {
            return Err("capture is not PNG".into());
        }
        let image = reader.decode().map_err(|e| format!("decode PNG: {e}"))?;
        if (image.width(), image.height()) != (WIDTH, HEIGHT)
            || image.color() != image::ColorType::Rgba8
        {
            return Err("capture must be 160x120 RGBA8 PNG".into());
        }
        Ok(image.into_rgba8())
    }
    fn write_json(path: &Path, value: &Value) -> Result<(), String> {
        let mut bytes =
            serde_json::to_vec_pretty(value).map_err(|e| format!("encode JSON: {e}"))?;
        bytes.push(b'\n');
        fs::write(path, bytes).map_err(|e| format!("write JSON: {e}"))
    }
    fn color(rgba: [u8; 4]) -> draw::Color {
        draw::Color::new(
            f32::from(rgba[0]) / 255.,
            f32::from(rgba[1]) / 255.,
            f32::from(rgba[2]) / 255.,
            1.,
        )
    }
    fn scene(index: usize, path: &Path) -> Result<DrawList, String> {
        use draw::{vec3, Mat4, Vec3};
        draw::begin_frame(WIDTH, HEIGHT, 1.)?;
        draw::set_camera(&draw::Camera3D {
            position: vec3(1., 2., 3.),
            target: vec3(1., 2., 2.),
            up: Vec3::Y,
            fovy: std::f32::consts::FRAC_PI_2,
            aspect: Some(4. / 3.),
            z_near: 1.,
            z_far: 20.,
            render_target: None,
        });
        draw::clear_background(color(BLACK));
        match index {
            0 => {
                draw::draw_line_3d(vec3(-2., 3., 0.), vec3(0., 3., 0.), color(RED));
                draw::draw_line_3d(vec3(-2., 3., -3.), vec3(0., 3., -3.), color(GREEN));
                // d=1.5 is inside near=1 but still has negative OpenGL clip Z;
                // this witness fails if the backend omits the 0..1 depth remap.
                draw::draw_line_3d(vec3(2.5, 1.5, 1.5), vec3(2.5, 2.5, 1.5), color(CYAN));
                draw::with_model_matrix(
                    Mat4::from_translation(vec3(1., 1., 0.))
                        * Mat4::from_rotation_z(std::f32::consts::FRAC_PI_2),
                    || {
                        draw::draw_line_3d(-Vec3::X, Vec3::X, color(BLUE));
                    },
                );
                // Both lines would be visible in distinct regions without proper clip depth.
                draw::draw_line_3d(vec3(0.7, 2.2, 2.5), vec3(1.3, 2.2, 2.5), color(MAGENTA));
                draw::draw_line_3d(vec3(-7., -6., -21.), vec3(9., -6., -21.), color(YELLOW));
            }
            1 => {
                draw::draw_cube_wires(vec3(-1., 2., -1.), Vec3::splat(2.), color(GREEN));
                draw::with_model_matrix(
                    Mat4::from_translation(vec3(3., 2., -1.))
                        * Mat4::from_rotation_z(std::f32::consts::FRAC_PI_2)
                        * Mat4::from_scale(vec3(0.5, 1., 1.)),
                    || {
                        draw::draw_cube_wires(Vec3::ZERO, Vec3::splat(2.), color(YELLOW));
                    },
                );
            }
            2 => {
                draw::draw_sphere(vec3(-1., 2., -1.), 1., None, color(RED));
                // Far sphere has an inset angular silhouette and cannot leak tessellation edges.
                draw::draw_sphere(vec3(-3., 2., -5.), 1.8, None, color(BLUE));
                draw::draw_line_3d(vec3(-5., 2., -3.), vec3(1., 2., -3.), color(YELLOW));
                draw::draw_line_3d(vec3(-0.8, 2.5, 1.), vec3(0.8, 2.5, 1.), color(CYAN));
                draw::with_model_matrix(
                    Mat4::from_translation(vec3(3., 2., -1.)) * Mat4::from_scale(vec3(1., 2., 1.)),
                    || {
                        draw::draw_sphere(Vec3::ZERO, 0.5, None, color(GREEN));
                    },
                );
            }
            _ => {
                let _ = draw::take_draw_list();
                return Err("unknown scene".into());
            }
        }
        draw::capture_png(None, path);
        draw::take_draw_list()
    }
    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native world primitive contract requires Windows DX12; CPU tests cannot produce a native pass".into());
        }
        prepare_output(&options.output_dir)?;
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
            WIDTH,
            HEIGHT,
            BackendSelection::Dx12,
            options.force_fallback_adapter,
        ))?;
        verify_backend(renderer.info(), options.force_fallback_adapter)?;
        let mut captures = Vec::new();
        for (index, spec) in cases().iter().enumerate() {
            let path = options.output_dir.join(spec.filename);
            let list = scene(index, &path)?;
            let submitted = renderer.submit(&list)?;
            if submitted.captures != [path.clone()] {
                return Err(
                    "ordered capture output differs from the requested facade checkpoint".into(),
                );
            }
            let image = read_png(&path)?;
            let evidence = inspect_image(&image, spec)?;
            verify_backend(renderer.info(), options.force_fallback_adapter)?;
            let info = renderer.info();
            let record = json!({"schema_version":1,"fixture_case":spec.case,"filename":spec.filename,
                "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
                "renderer":{"requested":info.requested,"backend":info.backend,"adapter":info.adapter},
                "force_fallback_adapter":options.force_fallback_adapter,
                "alpha_representation":"opaque-rgba8-rgb-preserved-over-black","diagnostic_raw_target":false,
                "row_origin":"top-left","width":WIDTH,"height":HEIGHT,"size":{"width":WIDTH,"height":HEIGHT},
                "evidence":evidence});
            write_json(
                &options.output_dir.join(format!("{}.json", spec.filename)),
                &record,
            )?;
            captures.push(record);
        }
        let info = renderer.info();
        let report = json!({"schema_version":1,"status":"passed","native_execution":true,
            "requested":info.requested,"backend":info.backend,"adapter":info.adapter,
            "force_fallback_adapter":options.force_fallback_adapter,"platform":std::env::consts::OS,
            "build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,
            "captures":captures,"scope":SCOPE});
        write_json(&options.output_dir.join(REPORT), &report)?;
        println!(
            "DX12 world primitives contract passed on {}: 3 captures; {}",
            info.adapter,
            options.output_dir.join(REPORT).display()
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
                let p = std::env::temp_dir().join(format!(
                    "rust-duty-world-primitives-{}-{}",
                    std::process::id(),
                    NEXT.fetch_add(1, Ordering::Relaxed)
                ));
                fs::create_dir(&p).unwrap();
                Self(p)
            }
        }
        impl Drop for Scratch {
            fn drop(&mut self) {
                let _ = fs::remove_dir_all(&self.0);
            }
        }
        fn painted_control(spec: &Case) -> RgbaImage {
            let mut image = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba(BLACK));
            // Synthetic guard controls deliberately do not claim native geometry evidence.
            for p in &spec.probes {
                let [l, r, t, b] = p.bounds;
                match p.mode {
                    "horizontal" => {
                        for x in l..r {
                            image.put_pixel(x, (t + b) / 2, Rgba(p.rgba));
                        }
                    }
                    "vertical" => {
                        for y in t..b {
                            image.put_pixel((l + r) / 2, y, Rgba(p.rgba));
                        }
                    }
                    "any" => image.put_pixel((l + r) / 2, (t + b) / 2, Rgba(p.rgba)),
                    _ => {
                        for y in t..b {
                            for x in l..r {
                                image.put_pixel(x, y, Rgba(p.rgba));
                            }
                        }
                    }
                }
            }
            image
        }
        #[test]
        fn cli_is_explicit_and_rejects_ambiguous_or_duplicate_arguments() {
            assert_eq!(
                Options::parse([
                    "--renderer=dx12",
                    "--force-fallback-adapter",
                    "--output-dir=out"
                ])
                .unwrap(),
                Options {
                    force_fallback_adapter: true,
                    output_dir: "out".into()
                }
            );
            assert!(
                !Options::parse(["--renderer", "dx12", "--output-dir", "out"])
                    .unwrap()
                    .force_fallback_adapter
            );
            for args in [
                vec![],
                vec!["--renderer=auto", "--output-dir=out"],
                vec!["--renderer=vulkan", "--output-dir=out"],
                vec!["--renderer=dx12"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--output-dir", "--other"],
                vec!["--renderer=dx12", "--renderer=dx12", "--output-dir=out"],
                vec!["--renderer=dx12", "--output-dir=out", "--output-dir=out"],
                vec![
                    "--renderer=dx12",
                    "--output-dir=out",
                    "--force-fallback-adapter",
                    "--force-fallback-adapter",
                ],
            ] {
                assert!(Options::parse(args).is_err());
            }
        }
        #[test]
        fn all_fixed_probe_controls_pass_but_empty_frames_do_not() {
            for spec in cases() {
                inspect_image(&painted_control(&spec), &spec).unwrap();
                assert!(
                    inspect_image(&RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba(BLACK)), &spec)
                        .is_err()
                );
            }
        }
        #[test]
        fn flips_wrong_channels_and_shifted_projection_are_rejected() {
            for spec in cases() {
                let image = painted_control(&spec);
                // Both wire boxes are intentionally symmetric in Y; the other two
                // independent scenes are the vertical-origin witnesses.
                if spec.filename != "world-wires-perspective.png" {
                    assert!(inspect_image(&image::imageops::flip_vertical(&image), &spec).is_err());
                }
                assert!(inspect_image(&image::imageops::flip_horizontal(&image), &spec).is_err());
                let swapped = RgbaImage::from_fn(WIDTH, HEIGHT, |x, y| {
                    let p = image.get_pixel(x, y);
                    Rgba([p[2], p[0], p[1], p[3]])
                });
                assert!(inspect_image(&swapped, &spec).is_err());
                let shifted = RgbaImage::from_fn(WIDTH, HEIGHT, |x, y| {
                    if x >= 5 {
                        *image.get_pixel(x - 5, y)
                    } else {
                        Rgba(BLACK)
                    }
                });
                assert!(inspect_image(&shifted, &spec).is_err());
            }
        }
        #[test]
        fn every_positive_probe_is_required() {
            for spec in cases() {
                let control = painted_control(&spec);
                for p in &spec.probes {
                    if p.rgba == BLACK {
                        continue;
                    }
                    let mut image = control.clone();
                    let [l, r, t, b] = p.bounds;
                    for y in t..b {
                        for x in l..r {
                            image.put_pixel(x, y, Rgba(BLACK));
                        }
                    }
                    assert!(
                        inspect_image(&image, &spec).is_err(),
                        "missing {} passed",
                        p.label
                    );
                }
            }
        }
        #[test]
        fn clip_leaks_depth_failures_alpha_and_stray_pixels_are_rejected() {
            for spec in cases() {
                let control = painted_control(&spec);
                for p in [
                    Rgba([255, 255, 255, 255]),
                    Rgba([0, 0, 0, 254]),
                    Rgba(spec.palette[0]),
                ] {
                    let mut image = control.clone();
                    image.put_pixel(1, 1, p);
                    assert!(inspect_image(&image, &spec).is_err());
                }
                for &forbidden in &spec.forbidden {
                    let mut image = control.clone();
                    image.put_pixel(50, 60, Rgba(forbidden));
                    assert!(inspect_image(&image, &spec).is_err());
                }
            }
            let spec = &cases()[2];
            let mut image = painted_control(spec);
            for x in 40..58 {
                image.put_pixel(x, 60, Rgba(YELLOW));
            }
            assert!(
                inspect_image(&image, spec).is_err(),
                "far line drawn over sphere must fail"
            );
        }
        #[test]
        fn strokes_require_span_coverage_not_a_pixel_count_cluster() {
            let p = probe("stroke", "horizontal", [10, 30, 10, 13], RED);
            let mut image = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba(BLACK));
            for x in 10..28 {
                image.put_pixel(x, 11, Rgba(RED));
            } // Exactly 90%.
            inspect_probe(&image, p).unwrap();
            image.put_pixel(27, 11, Rgba(BLACK));
            assert!(inspect_probe(&image, p).is_err());
            for y in 10..13 {
                for x in 10..17 {
                    image.put_pixel(x, y, Rgba(RED));
                }
            }
            assert!(
                inspect_probe(&image, p).is_err(),
                "a cluster cannot stand in for a full line"
            );
        }
        #[test]
        fn invalid_bounds_modes_and_channel_tolerance_are_checked() {
            let image = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba([247, 8, 8, 255]));
            let p = probe("area", "area", [1, 11, 1, 11], RED);
            inspect_probe(&image, p).unwrap();
            let bad = RgbaImage::from_pixel(WIDTH, HEIGHT, Rgba([246, 8, 8, 255]));
            assert!(inspect_probe(&bad, p).is_err());
            for bounds in [[0, 0, 0, 1], [0, 1, 2, 1], [0, 161, 0, 1], [0, 1, 0, 121]] {
                assert!(inspect_probe(&image, Probe { bounds, ..p }).is_err());
            }
            assert!(inspect_probe(&image, Probe { mode: "bogus", ..p }).is_err());
        }
        #[test]
        fn png_decoder_rejects_missing_corrupt_rgb_and_wrong_extent() {
            let dir = Scratch::new();
            let path = dir.0.join("capture.png");
            assert!(read_png(&path).is_err());
            fs::write(&path, b"not png").unwrap();
            assert!(read_png(&path).is_err());
            image::RgbImage::new(WIDTH, HEIGHT).save(&path).unwrap();
            assert!(read_png(&path).is_err());
            RgbaImage::new(1, 1).save(&path).unwrap();
            assert!(read_png(&path).is_err());
            painted_control(&cases()[0]).save(&path).unwrap();
            assert!(read_png(&path).is_ok());
        }
        #[test]
        fn fresh_output_and_json_write_fail_closed() {
            let dir = Scratch::new();
            prepare_output(&dir.0).unwrap();
            fs::write(dir.0.join("stale"), b"stale").unwrap();
            assert!(prepare_output(&dir.0).is_err());
            assert!(prepare_output(&dir.0.join("stale")).is_err());
            assert!(write_json(&dir.0, &json!({"status":"passed"})).is_err());
            assert!(!dir.0.join(REPORT).exists());
        }
        #[test]
        fn backend_guard_rejects_fallback_and_false_warp_claims() {
            let mut info = BackendInfo {
                requested: "dx12".into(),
                backend: "Dx12".into(),
                adapter: WARP.into(),
            };
            verify_backend(&info, true).unwrap();
            info.backend = "Vulkan".into();
            assert!(verify_backend(&info, true).is_err());
            info.backend = "Dx12".into();
            info.adapter = "hardware adapter".into();
            assert!(verify_backend(&info, true).is_err());
            verify_backend(&info, false).unwrap();
            info.requested = "auto".into();
            assert!(verify_backend(&info, false).is_err());
        }
        #[test]
        fn scenes_use_public_facade_perspective_lines_wires_and_spheres() {
            use vector_range::draw::Command;
            for (index, spec) in cases().iter().enumerate() {
                assert_eq!(
                    spec.case,
                    [
                        "facade-lines-perspective-model-and-clipping",
                        "facade-wire-box-twelve-edges-and-model",
                        "facade-sphere-perspective-model-and-occluded-lines",
                    ][index]
                );
                let list = scene(index, Path::new(spec.filename)).unwrap();
                assert_eq!((list.width, list.height), (WIDTH, HEIGHT));
                assert!(list.commands.iter().any(|c|matches!(c,Command::Camera(camera) if camera.depth_test && camera.target.is_none())));
                let counts: Vec<_> = list
                    .commands
                    .iter()
                    .filter_map(|c| {
                        if let Command::Lines { lines, .. } = c {
                            Some(lines.len())
                        } else {
                            None
                        }
                    })
                    .collect();
                assert_eq!(
                    counts,
                    match index {
                        0 => vec![1; 6],
                        1 => vec![12; 2],
                        _ => vec![1; 2],
                    }
                );
                let meshes = list
                    .commands
                    .iter()
                    .filter(|c| matches!(c, Command::Mesh { .. }))
                    .count();
                assert_eq!(meshes, if index == 2 { 3 } else { 0 });
                assert!(
                    matches!(list.commands.last(),Some(Command::Capture{target:None,path}) if path==Path::new(spec.filename))
                );
                assert!(draw::current_camera().is_err());
            }
        }
        #[cfg(all(feature = "wgpu-runtime", not(target_os = "windows")))]
        #[test]
        fn non_windows_never_creates_native_evidence() {
            let dir = Scratch::new();
            let output = dir.0.join("native");
            assert!(run([
                "--renderer=dx12".to_owned(),
                "--force-fallback-adapter".to_owned(),
                format!("--output-dir={}", output.display())
            ])
            .unwrap_err()
            .contains("requires Windows"));
            assert!(!output.exists());
        }
    }
}
