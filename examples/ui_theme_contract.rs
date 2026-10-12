//! Headless native DX12 CSS-theme evidence, not OS DPI or human legibility approval.
//!
//! Windows (use a fresh directory; retain stdout/stderr beside the evidence):
//! cargo run --locked --no-default-features --features wgpu-runtime --example
//! ui_theme_contract -- --renderer=dx12 --force-fallback-adapter
//! --output-dir evidence/ui-theme-dx12
//!
//! `ui-theme-contract-report.json` is written only after all 15 PNGs pass. It
//! contains schema_version/status/native_execution, requested/backend/adapter,
//! scales_percent, captures and reload_checks. Compiler identity must be taken
//! from the real `renderer dx12_shader_compiler=...` startup log, never inferred
//! from a requested backend or fabricated by this fixture. Omitting the fallback
//! flag requests hardware-first DX12. CPU helper tests cannot produce a report.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("ui_theme_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("ui_theme_contract requires --features wgpu-runtime and native Windows DX12");
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
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        draw::{facade, BackendInfo, Color, Rect, Renderer},
        render::{BackendSelection, WgpuRenderer},
        ui_theme::{self, UiClass, UiScope},
    };

    const SCALES: [u32; 5] = [100, 125, 150, 175, 200];
    const LOGICAL_SIZE: [u32; 2] = [320, 192];
    const TOLERANCE: u8 = 4;
    #[cfg(feature = "wgpu-runtime")]
    const REPORT: &str = "ui-theme-contract-report.json";
    #[cfg(feature = "wgpu-runtime")]
    const INITIAL_CSS: &str = "\
#pause-menu .panel { background-color:#204060; border-color:#e0c020; border-width:4px; }
#pause-menu .label { color:#40e080; font-size:16px; }
#pause-menu .button { background-color:#8040c0; border-color:#20c0e0; border-width:8px; opacity:0.5; }
";
    #[cfg(feature = "wgpu-runtime")]
    const RELOADED_CSS: &str = "\
#pause-menu .panel { background-color:#502080; border-color:#20c080; border-width:8px; }
#pause-menu .label { color:#e08040; font-size:32px; opacity:0.5; }
#pause-menu .button { background-color:#4080c0; border-color:#e08020; border-width:4px; opacity:0.75; }
";
    // A valid early replacement followed by an invalid later rule discriminates
    // atomic replacement from partially applying a failed parse.
    #[cfg(feature = "wgpu-runtime")]
    const INVALID_CSS: &str = "\
#pause-menu .panel { background-color:#ff0000; border-width:1px; }
#pause-menu .label { opacity:NaN; }
";

    #[derive(Debug, PartialEq, Eq)]
    struct Options {
        output_dir: PathBuf,
        force_fallback_adapter: bool,
    }
    impl Options {
        fn parse(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Self, String> {
            let mut args = args.into_iter().map(Into::into);
            let mut renderer = None;
            let mut output_dir = None;
            let mut force_fallback_adapter = false;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--renderer" => set_once(
                        &mut renderer,
                        args.next().ok_or("--renderer requires dx12")?,
                        "--renderer",
                    )?,
                    "--output-dir" => set_once(
                        &mut output_dir,
                        args.next().ok_or("--output-dir requires a directory")?,
                        "--output-dir",
                    )?,
                    "--force-fallback-adapter" if !force_fallback_adapter => {
                        force_fallback_adapter = true
                    }
                    _ if arg.starts_with("--renderer=") => {
                        set_once(&mut renderer, arg[11..].into(), "--renderer")?
                    }
                    _ if arg.starts_with("--output-dir=") => {
                        set_once(&mut output_dir, arg[13..].into(), "--output-dir")?
                    }
                    _ => return Err(format!("unknown or repeated fixture argument {arg:?}")),
                }
            }
            if renderer.as_deref() != Some("dx12") {
                return Err(
                    "explicit --renderer=dx12 is required; no other backend is accepted".into(),
                );
            }
            let output_dir = output_dir
                .filter(|v| !v.trim().is_empty() && !v.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                output_dir: output_dir.into(),
                force_fallback_adapter,
            })
        }
    }
    fn set_once(slot: &mut Option<String>, value: String, name: &str) -> Result<(), String> {
        if slot.replace(value).is_some() {
            return Err(format!("{name} may appear only once"));
        }
        Ok(())
    }
    fn prepare_output(path: &Path) -> Result<(), String> {
        if path.exists() {
            if fs::read_dir(path)
                .map_err(|e| e.to_string())?
                .next()
                .transpose()
                .map_err(|e| e.to_string())?
                .is_some()
            {
                return Err(
                    "output directory must be empty; choose a fresh evidence directory".into(),
                );
            }
        } else {
            fs::create_dir_all(path).map_err(|e| e.to_string())?;
        }
        Ok(())
    }
    #[cfg(feature = "wgpu-runtime")]
    fn write_json(path: &Path, value: &Value) -> Result<(), String> {
        let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        fs::write(path, bytes).map_err(|e| format!("write {}: {e}", path.display()))
    }
    #[cfg(feature = "wgpu-runtime")]
    fn verify_backend(info: &BackendInfo) -> Result<(), String> {
        if info.requested != "dx12" || info.backend != "Dx12" || info.adapter.trim().is_empty() {
            return Err(format!(
                "expected requested=dx12, backend=Dx12 and a named actual adapter; got {info:?}"
            ));
        }
        Ok(())
    }
    fn physical_size(percent: u32) -> [u32; 2] {
        LOGICAL_SIZE.map(|v| v * percent / 100)
    }
    fn read_png(path: &Path, size: [u32; 2]) -> Result<RgbaImage, String> {
        let reader = image::io::Reader::open(path)
            .map_err(|e| e.to_string())?
            .with_guessed_format()
            .map_err(|e| e.to_string())?;
        if reader.format() != Some(image::ImageFormat::Png) {
            return Err("capture is not a PNG".into());
        }
        let image = reader.decode().map_err(|e| e.to_string())?;
        if [image.width(), image.height()] != size || image.color() != image::ColorType::Rgba8 {
            return Err(format!("expected {size:?} RGBA8 capture"));
        }
        let image = image.into_rgba8();
        if image.pixels().any(|p| p[3] != 255) {
            return Err("main PNG alpha must be opaque everywhere".into());
        }
        Ok(image)
    }

    #[derive(Clone, Copy)]
    struct Expected {
        background: [u8; 4],
        border: [u8; 4],
        inner_strip: [u8; 4],
        button: [u8; 4],
        button_border: [u8; 4],
        button_inner_strip: [u8; 4],
        text_rgb: [u8; 3],
        text_alpha: u8,
        font_size: u32,
    }
    fn expected(reloaded: bool) -> Expected {
        // Independent expected constants, never produced by UiTheme/style methods
        // or sampled from a golden capture. Translucent borders are painted over
        // the already translucent background, as the native UI contract specifies.
        if reloaded {
            Expected {
                background: [80, 32, 128, 255],
                border: [32, 192, 128, 255],
                inner_strip: [32, 192, 128, 255],
                button: [48, 96, 144, 255],
                button_border: [180, 120, 60, 255],
                button_inner_strip: [48, 96, 144, 255],
                text_rgb: [224, 128, 64],
                text_alpha: 127,
                font_size: 32,
            }
        } else {
            Expected {
                background: [32, 64, 96, 255],
                border: [224, 192, 32, 255],
                inner_strip: [32, 64, 96, 255],
                button: [64, 32, 96, 255],
                button_border: [48, 112, 160, 255],
                button_inner_strip: [48, 112, 160, 255],
                text_rgb: [64, 224, 128],
                text_alpha: 255,
                font_size: 16,
            }
        }
    }
    #[derive(Clone, Copy)]
    struct Probe {
        label: &'static str,
        logical_bounds: [f64; 4],
        rgba: [u8; 4],
    }
    fn panel_probes(e: Expected) -> Vec<Probe> {
        [
            ("panel background", [96., 36., 184., 68.], e.background),
            ("panel top border", [32., 21., 192., 23.], e.border),
            ("panel bottom border", [32., 81., 192., 83.], e.border),
            ("panel left border", [25., 32., 27., 72.], e.border),
            ("panel right border", [197., 32., 199., 72.], e.border),
            ("panel border width", [32., 25., 192., 27.], e.inner_strip),
            (
                "button background opacity",
                [40., 124., 184., 148.],
                e.button,
            ),
            (
                "button top border opacity",
                [32., 109., 192., 111.],
                e.button_border,
            ),
            (
                "button bottom border opacity",
                [32., 161., 192., 163.],
                e.button_border,
            ),
            (
                "button left border opacity",
                [25., 120., 27., 152.],
                e.button_border,
            ),
            (
                "button right border opacity",
                [197., 120., 199., 152.],
                e.button_border,
            ),
            (
                "button border width",
                [32., 113., 192., 115.],
                e.button_inner_strip,
            ),
            (
                "inward panel left guard",
                [20., 20., 23., 84.],
                [0, 0, 0, 255],
            ),
            (
                "inward panel right guard",
                [201., 20., 204., 84.],
                [0, 0, 0, 255],
            ),
            (
                "inward button top guard",
                [24., 104., 200., 107.],
                [0, 0, 0, 255],
            ),
            (
                "inward button bottom guard",
                [24., 165., 200., 168.],
                [0, 0, 0, 255],
            ),
        ]
        .into_iter()
        .map(|(label, logical_bounds, rgba)| Probe {
            label,
            logical_bounds,
            rgba,
        })
        .collect()
    }
    fn pixel_bounds(bounds: [f64; 4], scale: f64, image: &RgbaImage) -> Result<[u32; 4], String> {
        if !scale.is_finite() || scale <= 0. || bounds.iter().any(|v| !v.is_finite() || *v < 0.) {
            return Err("invalid probe bounds or scale".into());
        }
        let b = [
            (bounds[0] * scale).ceil() as u32,
            (bounds[1] * scale).ceil() as u32,
            (bounds[2] * scale).floor() as u32,
            (bounds[3] * scale).floor() as u32,
        ];
        if b[0] >= b[2] || b[1] >= b[3] || b[2] > image.width() || b[3] > image.height() {
            return Err("empty or out-of-frame pixel probe".into());
        }
        Ok(b)
    }
    fn inspect_probe(image: &RgbaImage, scale: f64, probe: Probe) -> Result<Value, String> {
        let b = pixel_bounds(probe.logical_bounds, scale, image)?;
        let mut max_error = 0;
        for y in b[1]..b[3] {
            for x in b[0]..b[2] {
                let actual = image.get_pixel(x, y).0;
                let error = actual
                    .iter()
                    .zip(probe.rgba)
                    .map(|(a, b)| a.abs_diff(b))
                    .max()
                    .unwrap();
                max_error = max_error.max(error);
                if error > TOLERANCE {
                    return Err(format!(
                        "{}: pixel ({x},{y}) {actual:?}, expected {:?} within {TOLERANCE}",
                        probe.label, probe.rgba
                    ));
                }
            }
        }
        Ok(
            json!({"label":probe.label,"logical_bounds":probe.logical_bounds,"pixel_bounds":b,"expected_rgba":probe.rgba,"checked_pixels":(b[2]-b[0])*(b[3]-b[1]),"maximum_channel_error":max_error,"channel_tolerance":TOLERANCE,"required_match_fraction":1.0}),
        )
    }

    // Independently transcribed from the embedded licensed ProggyClean design
    // grid: H and I at 16px, independently placed at x=40/64 logical.
    // Integer physical baselines at all five scales isolate glyph rasterization
    // from fractional advance/sampler interpolation. This oracle never calls fontdue,
    // TextRenderer, measure_text, UiStyle, shaders, or the image under test.
    const GLYPHS: [[&str; 8]; 2] = [
        [
            "100001", "100001", "100001", "111111", "100001", "100001", "100001", "100001",
        ],
        [
            "011100", "001000", "001000", "001000", "001000", "001000", "001000", "011100",
        ],
    ];
    fn overlap(lo: f64, hi: f64, pixel: u32) -> f64 {
        (hi.min(f64::from(pixel) + 1.) - lo.max(f64::from(pixel))).max(0.)
    }
    fn text_pixel(x: u32, y: u32, scale: f64, e: Expected) -> [u8; 4] {
        let q = f64::from(e.font_size) / 16. * scale;
        let mut coverage = 0.;
        for (glyph, rows) in GLYPHS.iter().enumerate() {
            for (row, line) in rows.iter().enumerate() {
                for (column, cell) in line.bytes().enumerate() {
                    if cell != b'1' {
                        continue;
                    }
                    let left = (40. + 24. * glyph as f64) * scale + (1. + column as f64) * q;
                    let top = 60. * scale + (-8. + row as f64) * q;
                    coverage += overlap(left, left + q, x) * overlap(top, top + q, y);
                }
            }
        }
        let alpha = coverage.clamp(0., 1.) * f64::from(e.text_alpha) / 255.;
        let mut rgba = e.background;
        for (i, channel) in rgba[..3].iter_mut().enumerate() {
            *channel = (f64::from(e.text_rgb[i]) * alpha
                + f64::from(e.background[i]) * (1. - alpha))
                .round() as u8;
        }
        rgba
    }
    fn inspect_text(image: &RgbaImage, scale: f64, e: Expected) -> Result<Value, String> {
        let b = pixel_bounds([36., 36., 80., 68.], scale, image)?;
        let mut ink = 0;
        let mut max_error = 0;
        for y in b[1]..b[3] {
            for x in b[0]..b[2] {
                let expected = text_pixel(x, y, scale, e);
                ink += u32::from(expected != e.background);
                let actual = image.get_pixel(x, y).0;
                let error = actual
                    .iter()
                    .zip(expected)
                    .map(|(a, b)| a.abs_diff(b))
                    .max()
                    .unwrap();
                max_error = max_error.max(error);
                if error > TOLERANCE {
                    return Err(format!("styled H/I raster: pixel ({x},{y}) {actual:?}, independent expected {expected:?} within {TOLERANCE}"));
                }
            }
        }
        if ink == 0 {
            return Err("text expectation contains no ink".into());
        }
        Ok(
            json!({"glyphs":[{"text":"H","baseline_logical":[40,60]},{"text":"I","baseline_logical":[64,60]}],"font_size_css_px":e.font_size,"font_size_physical_px":f64::from(e.font_size)*scale,"pixel_bounds":b,"expected_ink_pixels":ink,"checked_pixels":(b[2]-b[0])*(b[3]-b[1]),"maximum_channel_error":max_error,"channel_tolerance":TOLERANCE,"required_match_fraction":1.0,"oracle":"independent fixed ProggyClean H/I design-grid area coverage, including negative-space pixels","human_legibility_approved":false}),
        )
    }

    #[cfg(feature = "wgpu-runtime")]
    fn scene(percent: u32, path: &Path) -> Result<vector_range::draw::DrawList, String> {
        let size = physical_size(percent);
        facade::begin_frame(size[0], size[1], f64::from(percent) / 100.)?;
        facade::clear_background(Color::new(0., 0., 0., 1.));
        ui_theme::style(UiScope::PauseMenu, &[UiClass::Panel]).rect(
            Rect::new(24., 20., 176., 64.),
            Color::WHITE,
            Color::WHITE,
            1.,
        );
        let label = ui_theme::style(UiScope::PauseMenu, &[UiClass::Label]);
        label.text("H", 40., 60., 11., Color::WHITE);
        label.text("I", 64., 60., 11., Color::WHITE);
        ui_theme::style(UiScope::PauseMenu, &[UiClass::Button]).rect(
            Rect::new(24., 108., 176., 56.),
            Color::WHITE,
            Color::WHITE,
            1.,
        );
        facade::capture_png(None, path);
        facade::take_draw_list()
    }
    #[cfg(feature = "wgpu-runtime")]
    fn cpu_hit_geometry() -> Result<Value, String> {
        // CPU-only evidence. No native pointer, click routing or OS DPI event is
        // synthesized. Existing ui_scale_contract owns the detailed CPU suite.
        let rect = Rect::new(24., 108., 176., 56.);
        let samples = [
            (24., 108., true),
            (200., 164., true),
            (112., 136., true),
            (23.75, 136., false),
            (200.25, 136., false),
        ];
        for (x, y, want) in samples {
            if rect.contains(glam::vec2(x, y)) != want {
                return Err("CPU logical hit geometry changed".into());
            }
        }
        Ok(
            json!({"evidence":"CPU only; Rect::contains at the logical draw rectangle","button_logical_xywh":[24,108,176,56],"samples":samples.map(|(x,y,inside)|json!({"point":[x,y],"inside":inside})),"native_pointer_or_click_verified":false}),
        )
    }
    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native UI theme contract requires Windows DX12; CPU compilation/tests cannot produce a native pass".into());
        }
        prepare_output(&options.output_dir)?;
        let path = options.output_dir.join("active-theme.css");
        for (name, css) in [
            ("initial-theme.css", INITIAL_CSS),
            ("reloaded-theme.css", RELOADED_CSS),
            ("rejected-theme.css", INVALID_CSS),
        ] {
            fs::write(options.output_dir.join(name), css).map_err(|e| e.to_string())?;
        }
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
            320,
            192,
            BackendSelection::Dx12,
            options.force_fallback_adapter,
        ))?;
        verify_backend(renderer.info())?;
        let mut captures = Vec::new();
        let mut reload_checks = Vec::new();
        let mut reloaded_images = Vec::new();
        for (phase, css, reloaded) in [
            ("initial", INITIAL_CSS, false),
            ("reloaded", RELOADED_CSS, true),
            ("invalid-last-good", INVALID_CSS, true),
        ] {
            fs::write(&path, css).map_err(|e| e.to_string())?;
            match phase {
                "initial" => {
                    ui_theme::load_theme(&path).map_err(|e| e.to_string())?;
                    reload_checks.push(json!({"phase":phase,"api":"load_theme","status":"loaded"}));
                }
                "reloaded" => {
                    ui_theme::reload_theme().map_err(|e| e.to_string())?;
                    reload_checks
                        .push(json!({"phase":phase,"api":"reload_theme","status":"reloaded"}));
                }
                _ => {
                    let error = ui_theme::reload_theme()
                        .err()
                        .ok_or("invalid CSS was accepted")?;
                    reload_checks.push(json!({"phase":phase,"api":"reload_theme","status":"expected-error","error":error.to_string(),"file":error.file,"line":error.line,"column":error.column}));
                }
            }
            for (index, percent) in SCALES.into_iter().enumerate() {
                let filename = format!("theme-{phase}-{percent}.png");
                let capture_path = options.output_dir.join(&filename);
                let result = renderer.submit(&scene(percent, &capture_path)?)?;
                if result.captures != [capture_path.clone()] {
                    return Err("renderer returned different capture paths".into());
                }
                verify_backend(renderer.info())?;
                let image = read_png(&capture_path, physical_size(percent))?;
                let e = expected(reloaded);
                let scale = f64::from(percent) / 100.;
                let probes: Vec<_> = panel_probes(e)
                    .into_iter()
                    .map(|p| inspect_probe(&image, scale, p))
                    .collect::<Result<_, _>>()?;
                let text = inspect_text(&image, scale, e)?;
                if phase == "reloaded" {
                    reloaded_images.push(image.clone());
                }
                if phase == "invalid-last-good" && image != reloaded_images[index] {
                    return Err(format!(
                        "{percent}% failed reload changed last-good PNG pixels"
                    ));
                }
                let info = renderer.info();
                let metadata = json!({"schema_version":1,"filename":filename,"phase":phase,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"scale_percent":percent,"logical_size":LOGICAL_SIZE,"physical_size":physical_size(percent),"row_origin":"top-left","alpha_representation":"opaque-rgba8-rgb-preserved-over-black","probes":probes,"styled_text":text,"last_good_identical_to_successful_reload":if phase=="invalid-last-good" {Some(true)} else {None}});
                write_json(
                    &options.output_dir.join(format!("{filename}.json")),
                    &metadata,
                )?;
                captures.push(metadata);
            }
        }
        let info = renderer.info();
        let report = json!({"schema_version":1,"status":"passed","native_execution":true,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"force_fallback_adapter":options.force_fallback_adapter,"platform":std::env::consts::OS,"build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,"scales_percent":SCALES,"captures":captures,"reload_checks":reload_checks,"cpu_hit_geometry":cpu_hit_geometry()?,"compiler_identity_source":"external captured renderer startup log; not inferred by this fixture","scope":"headless native DX12 UiTheme-to-facade-to-PNG contract","boundaries":{"os_dpi_events_verified":false,"window_presentation_verified":false,"native_pointer_or_click_verified":false,"human_legibility_approved":false,"private_assets_loaded":false}});
        write_json(&options.output_dir.join(REPORT), &report)?;
        println!(
            "DX12 UI theme contract passed on {}: 15 captures; {}",
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
                let path = std::env::temp_dir().join(format!(
                    "rust-duty-ui-theme-contract-{}-{}",
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
        fn strict_native_cli() {
            assert!(
                Options::parse([
                    "--renderer=dx12",
                    "--output-dir=out",
                    "--force-fallback-adapter"
                ])
                .unwrap()
                .force_fallback_adapter
            );
            assert!(Options::parse(["--renderer", "dx12", "--output-dir", "out"]).is_ok());
            for args in [
                vec![],
                vec!["--output-dir=out"],
                vec!["--renderer=auto", "--output-dir=out"],
                vec!["--renderer=vulkan", "--output-dir=out"],
                vec!["--renderer=dx12"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--output-dir=out", "--other"],
                vec!["--renderer=dx12", "--output-dir=out", "--renderer=dx12"],
                vec!["--renderer=dx12", "--output-dir=out", "--output-dir=other"],
                vec![
                    "--renderer=dx12",
                    "--output-dir=out",
                    "--force-fallback-adapter",
                    "--force-fallback-adapter",
                ],
            ] {
                assert!(Options::parse(args.clone()).is_err(), "accepted {args:?}");
            }
        }
        #[test]
        fn stale_evidence_and_invalid_png_fail() {
            let scratch = Scratch::new();
            prepare_output(&scratch.0).unwrap();
            let path = scratch.0.join("capture.png");
            fs::write(&path, b"not a PNG").unwrap();
            assert!(prepare_output(&scratch.0).is_err());
            assert!(prepare_output(&path).is_err());
            assert!(read_png(&path, [1, 1]).is_err());
            RgbaImage::from_pixel(1, 1, Rgba([0, 0, 0, 255]))
                .save(&path)
                .unwrap();
            assert!(read_png(&path, [1, 1]).is_ok());
            assert!(read_png(&path, [2, 1]).is_err());
            RgbaImage::from_pixel(1, 1, Rgba([0, 0, 0, 127]))
                .save(&path)
                .unwrap();
            assert!(read_png(&path, [1, 1]).is_err());
        }
        #[test]
        fn solid_probes_require_every_pixel_and_valid_extent() {
            let mut image = RgbaImage::from_pixel(8, 8, Rgba([32, 64, 96, 255]));
            let probe = Probe {
                label: "control",
                logical_bounds: [0., 0., 8., 8.],
                rgba: [32, 64, 96, 255],
            };
            inspect_probe(&image, 1., probe).unwrap();
            image.put_pixel(4, 4, Rgba([64, 32, 96, 255]));
            assert!(inspect_probe(&image, 1., probe).is_err());
            assert!(inspect_probe(&image, 0., probe).is_err());
            assert!(inspect_probe(&image, 2., probe).is_err());
            for percent in SCALES {
                let size = physical_size(percent);
                let extent = RgbaImage::new(size[0], size[1]);
                for reloaded in [false, true] {
                    let probes = panel_probes(expected(reloaded));
                    assert_eq!(probes.len(), 16);
                    for probe in probes {
                        pixel_bounds(probe.logical_bounds, f64::from(percent) / 100., &extent)
                            .unwrap();
                    }
                }
            }
        }
        #[test]
        fn fixed_glyph_oracle_rejects_wrong_color_size_missing_strokes_and_flip() {
            for percent in SCALES {
                for reloaded in [false, true] {
                    let scale = f64::from(percent) / 100.;
                    let size = physical_size(percent);
                    let e = expected(reloaded);
                    let image = RgbaImage::from_fn(size[0], size[1], |x, y| {
                        Rgba(text_pixel(x, y, scale, e))
                    });
                    inspect_text(&image, scale, e).unwrap();
                    let blank = RgbaImage::from_pixel(size[0], size[1], Rgba(e.background));
                    assert!(inspect_text(&blank, scale, e).is_err());
                    let mut wrong = e;
                    wrong.text_rgb = [255, 0, 255];
                    let image_wrong = RgbaImage::from_fn(size[0], size[1], |x, y| {
                        Rgba(text_pixel(x, y, scale, wrong))
                    });
                    assert!(inspect_text(&image_wrong, scale, e).is_err());
                    wrong = e;
                    wrong.font_size = if reloaded { 16 } else { 32 };
                    let image_wrong = RgbaImage::from_fn(size[0], size[1], |x, y| {
                        Rgba(text_pixel(x, y, scale, wrong))
                    });
                    assert!(inspect_text(&image_wrong, scale, e).is_err());
                    assert!(
                        inspect_text(&image::imageops::flip_vertical(&image), scale, e).is_err()
                    );
                    let mut missing = image.clone();
                    let point = image
                        .enumerate_pixels()
                        .find(|(_, _, p)| {
                            p.0.iter()
                                .zip(e.background)
                                .any(|(a, b)| a.abs_diff(b) > TOLERANCE)
                        })
                        .unwrap();
                    missing.put_pixel(point.0, point.1, Rgba(e.background));
                    assert!(inspect_text(&missing, scale, e).is_err());
                }
            }
        }
        #[test]
        fn fixed_design_grid_has_independent_known_samples() {
            let e = expected(false);
            // Known 16px H stems, crossbar, hole, and I cap; not recomputed using
            // production font metrics or image generation output.
            for (x, y) in [(41, 52), (46, 59), (43, 55), (66, 52), (67, 56)] {
                assert_eq!(text_pixel(x, y, 1., e), [64, 224, 128, 255]);
            }
            for (x, y) in [(42, 52), (45, 59), (65, 55), (40, 52), (68, 56)] {
                assert_eq!(text_pixel(x, y, 1., e), e.background);
            }
        }
        #[test]
        fn fixed_mask_matches_embedded_font_cpu_raster_at_all_scales() {
            // CPU-only oracle qualification, not a GPU render or capture golden.
            let font = fontdue::Font::from_bytes(
                &include_bytes!("../src/render/font/ProggyClean.ttf")[..],
                fontdue::FontSettings::default(),
            )
            .unwrap();
            for percent in SCALES {
                for reloaded in [false, true] {
                    let scale = f64::from(percent) / 100.;
                    let size = physical_size(percent);
                    let e = expected(reloaded);
                    let mut control = RgbaImage::from_pixel(size[0], size[1], Rgba(e.background));
                    for (glyph, baseline_x) in [('H', 40.), ('I', 64.)] {
                        let (metrics, bitmap) =
                            font.rasterize(glyph, e.font_size as f32 * scale as f32);
                        let left = (baseline_x * scale) as i32 + metrics.xmin;
                        let top = (60. * scale) as i32 - metrics.ymin - metrics.height as i32;
                        for row in 0..metrics.height {
                            for column in 0..metrics.width {
                                let alpha = f64::from(bitmap[row * metrics.width + column]) / 255.
                                    * f64::from(e.text_alpha)
                                    / 255.;
                                let mut rgba = e.background;
                                for (i, value) in rgba[..3].iter_mut().enumerate() {
                                    *value = (f64::from(e.text_rgb[i]) * alpha
                                        + f64::from(e.background[i]) * (1. - alpha))
                                        .round() as u8;
                                }
                                control.put_pixel(
                                    (left + column as i32) as u32,
                                    (top + row as i32) as u32,
                                    Rgba(rgba),
                                );
                            }
                        }
                    }
                    inspect_text(&control, scale, e)
                        .unwrap_or_else(|error| panic!("{percent}% reloaded={reloaded}: {error}"));
                }
            }
        }

        #[cfg(feature = "wgpu-runtime")]
        #[test]
        fn real_parser_and_facade_wire_fixture_without_gpu() {
            for css in [INITIAL_CSS, RELOADED_CSS] {
                ui_theme::set_theme(ui_theme::UiTheme::parse("fixture.css", css).unwrap());
                let list = scene(125, Path::new("fixture.png")).unwrap();
                assert_eq!([list.width, list.height], [400, 240]);
                assert!(
                    matches!(list.commands.last(),Some(vector_range::draw::Command::Capture {path,..}) if path==Path::new("fixture.png"))
                );
            }
            assert!(ui_theme::UiTheme::parse("rejected.css", INVALID_CSS).is_err());
        }
        #[cfg(all(feature = "wgpu-runtime", not(target_os = "windows")))]
        #[test]
        fn non_windows_cannot_write_a_native_pass() {
            let scratch = Scratch::new();
            let out = scratch.0.join("never-created");
            let error = run([
                "--renderer=dx12".into(),
                format!("--output-dir={}", out.display()),
            ])
            .unwrap_err();
            assert!(error.contains("Windows DX12"));
            assert!(!out.exists());
            assert!(!scratch.0.join(REPORT).exists());
        }
    }
}
