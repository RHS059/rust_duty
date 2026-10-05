//! Headless native DX12 evidence for the real game UI draw paths, not OS DPI,
//! window presentation or human legibility approval.
//!
//! Windows (use fresh directories; the runner keeps stdout/stderr as evidence):
//! cargo build --locked --no-default-features --features wgpu-runtime --example game_ui_contract
//! python tools/run_dx12_game_ui_fixture.py --executable target/debug/examples/game_ui_contract.exe
//!   --evidence evidence/game-ui-process --output evidence/game-ui
//!
//! Current coverage: the production `ammo_supply_view::draw_ammo_supply_hint`
//! at 100% and 200% scale (idle, half hold, full hold, ammo full). The pause
//! menu and updater panel are private to the game binary and are added once
//! they are exported from the library. `game-ui-contract-report.json` is
//! written only after every capture passes. Compiler identity comes from the
//! runner's captured startup log, never from this fixture.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("game_ui_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("game_ui_contract requires --features wgpu-runtime and native Windows DX12");
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", test))]
mod fixture {
    use image::RgbaImage;
    #[cfg(feature = "wgpu-runtime")]
    use serde_json::{json, Value};
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    #[cfg(feature = "wgpu-runtime")]
    use vector_range::{
        ammo_supply::SupplyFocus,
        ammo_supply_view::draw_ammo_supply_hint,
        draw::{facade, BackendInfo, Color, Renderer},
        render::{BackendSelection, WgpuRenderer},
    };

    #[cfg(feature = "wgpu-runtime")]
    pub const SCALES: [u32; 2] = [100, 200];
    pub const LOGICAL_SIZE: [u32; 2] = [480, 270];
    /// Logical screen anchor of the projected crate.
    pub const ANCHOR: [f64; 2] = [240., 120.];
    /// Logical window that must contain every lit pixel of the prompt.
    pub const INK_WINDOW: [f64; 4] = [90., 80., 390., 190.];
    #[cfg(feature = "wgpu-runtime")]
    const REPORT: &str = "game-ui-contract-report.json";

    #[cfg(feature = "wgpu-runtime")]
    /// (name, hold progress, ammo already full)
    pub const AMMO_CASES: [(&str, f32, bool); 4] = [
        ("idle", 0., false),
        ("half", 0.5, false),
        ("complete", 1., false),
        ("ammo-full", 0., true),
    ];

    #[derive(Debug, PartialEq, Eq)]
    pub struct Options {
        pub output_dir: PathBuf,
        pub force_fallback_adapter: bool,
    }
    impl Options {
        pub fn parse(args: impl IntoIterator<Item = impl Into<String>>) -> Result<Self, String> {
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
    pub fn prepare_output(path: &Path) -> Result<(), String> {
        if path.exists() {
            let mut entries = fs::read_dir(path).map_err(|e| e.to_string())?;
            if entries.next().is_some() {
                return Err(
                    "output directory must be empty; choose a fresh evidence directory".into(),
                );
            }
        } else {
            fs::create_dir_all(path).map_err(|e| e.to_string())?;
        }
        Ok(())
    }
    pub fn physical_size(percent: u32) -> [u32; 2] {
        LOGICAL_SIZE.map(|v| v * percent / 100)
    }
    pub fn read_png(path: &Path, size: [u32; 2]) -> Result<RgbaImage, String> {
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
            return Err("capture alpha must be opaque everywhere".into());
        }
        Ok(image)
    }

    /// Lit pixels (anything not the black clear colour), their bounds, and gold
    /// sweep pixels split by the anchor's vertical axis.
    #[derive(Debug, Clone, Copy, PartialEq)]
    pub struct Ink {
        pub lit: u64,
        pub bounds: Option<[u32; 4]>,
        pub gold_left: u64,
        pub gold_right: u64,
    }
    impl Ink {
        pub fn gold(&self) -> u64 {
            self.gold_left + self.gold_right
        }
    }
    /// Independent oracle colour: SUPPLY_GOLD is #FFC233; tolerance allows edge
    /// blending without admitting the white caption or the dark backplate.
    pub fn is_gold(p: [u8; 4]) -> bool {
        p[0] >= 235 && (170..=215).contains(&p[1]) && p[2] <= 95
    }
    pub fn measure(image: &RgbaImage, scale: f64) -> Ink {
        let axis = ANCHOR[0] * scale;
        let mut ink = Ink {
            lit: 0,
            bounds: None,
            gold_left: 0,
            gold_right: 0,
        };
        for (x, y, pixel) in image.enumerate_pixels() {
            let p = pixel.0;
            if p[0] == 0 && p[1] == 0 && p[2] == 0 {
                continue;
            }
            ink.lit += 1;
            let b = ink.bounds.get_or_insert([x, y, x, y]);
            b[0] = b[0].min(x);
            b[1] = b[1].min(y);
            b[2] = b[2].max(x);
            b[3] = b[3].max(y);
            if is_gold(p) {
                if f64::from(x) + 0.5 < axis {
                    ink.gold_left += 1;
                } else {
                    ink.gold_right += 1;
                }
            }
        }
        ink
    }

    /// Per-capture rules from the hint's documented behaviour, never from its code.
    pub fn check_case(case: &str, ink: Ink, scale: f64) -> Result<(), String> {
        let bounds = ink
            .bounds
            .ok_or_else(|| format!("{case}: capture is empty"))?;
        let window = INK_WINDOW.map(|v| v * scale);
        if f64::from(bounds[0]) < window[0]
            || f64::from(bounds[1]) < window[1]
            || f64::from(bounds[2]) > window[2]
            || f64::from(bounds[3]) > window[3]
        {
            return Err(format!("{case}: lit bounds {bounds:?} escape {window:?}"));
        }
        match case {
            "idle" | "ammo-full" if ink.gold() != 0 => Err(format!(
                "{case}: no hold circle may be drawn, found {} gold pixels",
                ink.gold()
            )),
            // Clockwise from twelve o'clock: half a turn fills only the right half.
            "half" if ink.gold_right == 0 || ink.gold_left > ink.gold_right / 50 => Err(format!(
                "half: gold sweep must sit right of the anchor, got left {} right {}",
                ink.gold_left, ink.gold_right
            )),
            "complete" if ink.gold_left == 0 || ink.gold_right == 0 => {
                Err("complete: gold sweep must cover both halves".into())
            }
            _ => Ok(()),
        }
    }

    /// Cross-capture rules for one scale: distinct states and sweep growth.
    pub fn check_progression(inks: &[(&str, Ink)]) -> Result<(), String> {
        let get = |name: &str| {
            inks.iter()
                .find(|(n, _)| *n == name)
                .map(|(_, ink)| *ink)
                .ok_or_else(|| format!("missing {name}"))
        };
        let (half, complete) = (get("half")?.gold(), get("complete")?.gold());
        let ratio = complete as f64 / half.max(1) as f64;
        if !(1.6..=2.4).contains(&ratio) {
            return Err(format!(
                "full sweep should be about twice the half sweep, got {ratio:.2}"
            ));
        }
        Ok(())
    }
    pub fn check_distinct(images: &[(&str, RgbaImage)]) -> Result<(), String> {
        for (i, (a, left)) in images.iter().enumerate() {
            for (b, right) in &images[i + 1..] {
                if left == right {
                    return Err(format!("{a} and {b} rendered identical pixels"));
                }
            }
        }
        Ok(())
    }
    /// 200% must be the same prompt at twice the size: ~4x area, ~2x extent.
    pub fn check_scaling(one: Ink, two: Ink) -> Result<(), String> {
        let (a, b) = (
            one.bounds.ok_or("empty 100% capture")?,
            two.bounds.ok_or("empty 200% capture")?,
        );
        let area = two.lit as f64 / one.lit.max(1) as f64;
        let width = f64::from(b[2] - b[0] + 1) / f64::from(a[2] - a[0] + 1);
        if !(3.0..=5.0).contains(&area) || !(1.8..=2.2).contains(&width) {
            return Err(format!(
                "200% capture is not a 2x rendering: area x{area:.2}, width x{width:.2}"
            ));
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
    #[cfg(feature = "wgpu-runtime")]
    fn ammo_scene(
        percent: u32,
        progress: f32,
        full: bool,
        path: &Path,
    ) -> Result<vector_range::draw::DrawList, String> {
        let size = physical_size(percent);
        facade::begin_frame(size[0], size[1], f64::from(percent) / 100.)?;
        facade::clear_background(Color::new(0., 0., 0., 1.));
        draw_ammo_supply_hint(
            SupplyFocus {
                screen_anchor: glam::vec2(ANCHOR[0] as f32, ANCHOR[1] as f32),
                world_anchor: glam::Vec3::ZERO,
                distance: 1.,
            },
            progress,
            full,
        );
        facade::capture_png(None, path);
        facade::take_draw_list()
    }

    #[cfg(feature = "wgpu-runtime")]
    fn ink_json(ink: Ink) -> Value {
        json!({"lit_pixels":ink.lit,"lit_bounds":ink.bounds,"gold_left":ink.gold_left,"gold_right":ink.gold_right})
    }

    #[cfg(feature = "wgpu-runtime")]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if !cfg!(target_os = "windows") {
            return Err("native game UI contract requires Windows DX12; CPU compilation/tests cannot produce a native pass".into());
        }
        prepare_output(&options.output_dir)?;
        let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
            LOGICAL_SIZE[0],
            LOGICAL_SIZE[1],
            BackendSelection::Dx12,
            options.force_fallback_adapter,
        ))?;
        verify_backend(renderer.info())?;
        let mut captures = Vec::new();
        let mut first_scale = Vec::new();
        for percent in SCALES {
            let scale = f64::from(percent) / 100.;
            let mut images = Vec::new();
            let mut inks = Vec::new();
            for (case, progress, full) in AMMO_CASES {
                let filename = format!("ammo-{case}-{percent}.png");
                let path = options.output_dir.join(&filename);
                let result = renderer.submit(&ammo_scene(percent, progress, full, &path)?)?;
                if result.captures != [path.clone()] {
                    return Err("renderer returned different capture paths".into());
                }
                verify_backend(renderer.info())?;
                let image = read_png(&path, physical_size(percent))?;
                let ink = measure(&image, scale);
                check_case(case, ink, scale)?;
                let info = renderer.info();
                let metadata = json!({"schema_version":1,"filename":filename,"element":"ammo-hint","case":case,"progress":progress,"ammo_full":full,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"scale_percent":percent,"logical_size":LOGICAL_SIZE,"physical_size":physical_size(percent),"anchor_logical":ANCHOR,"ink":ink_json(ink)});
                write_json(
                    &options.output_dir.join(format!("{filename}.json")),
                    &metadata,
                )?;
                captures.push(metadata);
                images.push((case, image));
                inks.push((case, ink));
            }
            check_distinct(&images)?;
            check_progression(&inks)?;
            if percent == SCALES[0] {
                first_scale = inks;
            } else {
                for ((case, one), (_, two)) in first_scale.iter().zip(&inks) {
                    check_scaling(*one, *two).map_err(|e| format!("{case}: {e}"))?;
                }
            }
        }
        let info = renderer.info();
        let report = json!({"schema_version":1,"status":"passed","native_execution":true,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"force_fallback_adapter":options.force_fallback_adapter,"platform":std::env::consts::OS,"build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,"scales_percent":SCALES,"captures":captures,"elements_covered":["ammo-hint"],"elements_pending":{"pause-menu":"PauseMenu is private to the game binary","updater-panel":"UpdatePanel is private to the game binary"},"compiler_identity_source":"external captured renderer startup log; not inferred by this fixture","scope":"headless native DX12 production game-UI draw paths to PNG","boundaries":{"os_dpi_events_verified":false,"window_presentation_verified":false,"native_pointer_or_click_verified":false,"human_legibility_approved":false}});
        write_json(&options.output_dir.join(REPORT), &report)?;
        println!(
            "DX12 game UI contract passed on {}: {} captures; {}",
            info.adapter,
            captures.len(),
            options.output_dir.join(REPORT).display()
        );
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use image::Rgba;

        const GOLD: Rgba<u8> = Rgba([255, 194, 51, 255]);
        const WHITE: Rgba<u8> = Rgba([255, 255, 255, 255]);

        /// Synthetic prompt: caption bar plus an optional gold half/full disc.
        fn synthetic(scale: u32, sweep: Option<bool>) -> RgbaImage {
            let size = physical_size(scale * 100);
            let mut image = RgbaImage::from_pixel(size[0], size[1], Rgba([0, 0, 0, 255]));
            let s = scale;
            for x in 200 * s..280 * s {
                for y in 150 * s..158 * s {
                    image.put_pixel(x, y, WHITE);
                }
            }
            if let Some(full) = sweep {
                let (cx, cy, r) = (240 * s, 120 * s, 19 * s);
                for x in cx - r..cx + r {
                    for y in cy - r..cy + r {
                        let (dx, dy) = (
                            f64::from(x) + 0.5 - f64::from(cx),
                            f64::from(y) + 0.5 - f64::from(cy),
                        );
                        if dx * dx + dy * dy <= f64::from(r * r) && (full || dx > 0.) {
                            image.put_pixel(x, y, GOLD);
                        }
                    }
                }
            }
            image
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
                vec!["--renderer=vulkan", "--output-dir=out"],
                vec!["--renderer=dx12"],
                vec!["--renderer=dx12", "--output-dir="],
                vec!["--renderer=dx12", "--output-dir=out", "--other"],
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
        fn controls_pass_every_rule() {
            for scale in [1u32, 2] {
                let s = f64::from(scale);
                let idle = measure(&synthetic(scale, None), s);
                let half = measure(&synthetic(scale, Some(false)), s);
                let full = measure(&synthetic(scale, Some(true)), s);
                check_case("idle", idle, s).unwrap();
                check_case("half", half, s).unwrap();
                check_case("complete", full, s).unwrap();
                check_progression(&[("half", half), ("complete", full)]).unwrap();
            }
            let one = measure(&synthetic(1, Some(true)), 1.);
            let two = measure(&synthetic(2, Some(true)), 2.);
            check_scaling(one, two).unwrap();
        }

        #[test]
        fn discriminating_failures_are_rejected() {
            let s = 1.;
            // Gold where no circle may be drawn.
            assert!(check_case("idle", measure(&synthetic(1, Some(false)), s), s).is_err());
            assert!(check_case("ammo-full", measure(&synthetic(1, Some(true)), s), s).is_err());
            // Counter-clockwise half sweep (left half) and a missing sweep.
            let mut flipped = synthetic(1, None);
            for x in 221..240 {
                for y in 101..139 {
                    flipped.put_pixel(x, y, GOLD);
                }
            }
            assert!(check_case("half", measure(&flipped, s), s).is_err());
            assert!(check_case("half", measure(&synthetic(1, None), s), s).is_err());
            assert!(check_case("complete", measure(&synthetic(1, Some(false)), s), s).is_err());
            // Empty capture and ink outside the prompt window.
            let empty = RgbaImage::from_pixel(480, 270, Rgba([0, 0, 0, 255]));
            assert!(check_case("idle", measure(&empty, s), s).is_err());
            let mut stray = synthetic(1, None);
            stray.put_pixel(5, 5, WHITE);
            assert!(check_case("idle", measure(&stray, s), s).is_err());
            // No growth between half and complete.
            let half = measure(&synthetic(1, Some(false)), s);
            assert!(check_progression(&[("half", half), ("complete", half)]).is_err());
            // Identical states and an unscaled 200% capture.
            let a = synthetic(1, None);
            assert!(check_distinct(&[("idle", a.clone()), ("ammo-full", a)]).is_err());
            let one = measure(&synthetic(1, Some(true)), 1.);
            assert!(check_scaling(one, one).is_err());
        }

        #[test]
        fn stale_output_and_invalid_png_fail() {
            let dir =
                std::env::temp_dir().join(format!("rust-duty-game-ui-{}", std::process::id()));
            let _ = fs::remove_dir_all(&dir);
            prepare_output(&dir).unwrap();
            let path = dir.join("capture.png");
            fs::write(&path, b"not a PNG").unwrap();
            assert!(prepare_output(&dir).is_err());
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
            fs::remove_dir_all(&dir).unwrap();
        }
    }
}
