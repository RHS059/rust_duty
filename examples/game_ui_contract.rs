//! Native evidence for the real game UI draw paths inside a live game window
//! runtime, not OS DPI events, presentation or human legibility approval.
//!
//! Windows DX12 (use fresh directories; the runner keeps stdout/stderr as evidence):
//! cargo build --locked --no-default-features --features wgpu-runtime --example game_ui_contract
//! python tools/run_dx12_game_ui_fixture.py --executable target/debug/examples/game_ui_contract.exe
//!   --evidence evidence/game-ui-process --output evidence/game-ui
//!
//! Native OpenGL (legacy Macroquad window, same cases and rules):
//! cargo run --locked --example game_ui_contract -- --renderer=gl --output-dir evidence/game-ui-gl
//!
//! Coverage: the production pause menu, updater panel (current/unavailable),
//! HUD with and without the telemetry panel, and ammo supply hint, each drawn
//! into an offscreen target via `set_screen_camera` at 100% and 200% of the
//! 960x540 logical viewport. DX12 runs inside `platform::window::run` +
//! `create_frame_hooks(Dx12)`; GL inside the game's Macroquad window with the
//! `legacy_macroquad::runtime` lifecycle. Both share one capture loop through
//! `platform::runtime::next_frame`. `game-ui-contract-report.json` is written only after every
//! capture passes. Compiler identity comes from the runner's captured startup
//! log, never from this fixture.

#[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
fn main() {
    if let Err(error) = fixture::run(std::env::args().skip(1)) {
        eprintln!("game_ui_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(any(feature = "wgpu-runtime", feature = "legacy-macroquad")))]
fn main() {
    eprintln!("game_ui_contract requires wgpu-runtime (DX12) or legacy-macroquad (GL)");
    std::process::exit(1);
}

#[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad", test))]
mod fixture {
    use image::RgbaImage;
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    use serde_json::{json, Value};
    use std::{
        fs,
        path::{Path, PathBuf},
    };
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    use vector_range::{
        ammo_supply::SupplyFocus,
        ammo_supply_view::draw_ammo_supply_hint,
        control::ControlMode,
        draw::{facade, BackendInfo, Color},
        game_update::UpdatePanel,
        hud,
        pause_menu::PauseMenu,
        platform::runtime,
        settings::Settings,
        sim::Simulation,
    };

    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    pub const SCALES: [u32; 2] = [100, 200];
    pub const LOGICAL_SIZE: [u32; 2] = [960, 540];
    /// Logical screen anchor of the projected crate.
    pub const ANCHOR: [f64; 2] = [240., 120.];
    /// Logical window that must contain every lit pixel of the prompt.
    pub const INK_WINDOW: [f64; 4] = [90., 80., 390., 190.];
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    const REPORT: &str = "game-ui-contract-report.json";

    /// Every capture, in order, at each scale.
    pub const CASES: [&str; 9] = [
        "pause-menu",
        "updater-current",
        "updater-unavailable",
        "hud",
        "hud-telemetry",
        "ammo-idle",
        "ammo-half",
        "ammo-complete",
        "ammo-full",
    ];
    pub fn element(case: &str) -> &'static str {
        match case {
            "pause-menu" => "pause-menu",
            "updater-current" | "updater-unavailable" => "updater-panel",
            "hud" => "hud",
            "hud-telemetry" => "telemetry",
            _ => "ammo-hint",
        }
    }
    /// Ammo case name as used by the hint rules.
    pub fn ammo_case(case: &str) -> Option<&str> {
        match case {
            "ammo-full" => Some("ammo-full"),
            _ => case.strip_prefix("ammo-"),
        }
    }
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    /// (case, hold progress, ammo already full)
    pub const AMMO_CASES: [(&str, f32, bool); 4] = [
        ("ammo-idle", 0., false),
        ("ammo-half", 0.5, false),
        ("ammo-complete", 1., false),
        ("ammo-full", 0., true),
    ];

    #[derive(Debug, PartialEq, Eq)]
    pub struct Options {
        /// "dx12" or "gl".
        pub renderer: String,
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
                        args.next().ok_or("--renderer requires dx12 or gl")?,
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
            let renderer = renderer
                .filter(|r| r == "dx12" || r == "gl")
                .ok_or("explicit --renderer=dx12 or --renderer=gl is required")?;
            if renderer == "gl" && force_fallback_adapter {
                return Err("--force-fallback-adapter applies only to dx12".into());
            }
            let output_dir = output_dir
                .filter(|v| !v.trim().is_empty() && !v.starts_with("--"))
                .ok_or("--output-dir requires an explicit nonempty directory")?;
            Ok(Self {
                renderer,
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

    /// Lit pixels (anything not the black clear colour), their bounds, gold sweep
    /// pixels split by the anchor's vertical axis, and white key/caption pixels.
    #[derive(Debug, Clone, Copy, PartialEq)]
    pub struct Ink {
        pub lit: u64,
        pub bounds: Option<[u32; 4]>,
        pub gold_left: u64,
        pub gold_right: u64,
        pub key_white: u64,
        pub caption_white: u64,
    }
    impl Ink {
        pub fn gold(&self) -> u64 {
            self.gold_left + self.gold_right
        }
    }
    /// Logical regions for the white key glyph and the caption (or AMMO FULL text).
    pub const KEY_BOX: [f64; 4] = [230., 108., 250., 132.];
    pub const CAPTION_BAND: [f64; 4] = [90., 140., 390., 172.];
    pub const FULL_TEXT_BAND: [f64; 4] = [90., 100., 390., 128.];
    /// Independent oracle colour: SUPPLY_GOLD is #FFC233; tolerance allows edge
    /// blending without admitting the white caption or the dark backplate.
    pub fn is_gold(p: [u8; 4]) -> bool {
        p[0] >= 235 && (170..=215).contains(&p[1]) && p[2] <= 95
    }
    pub fn is_white(p: [u8; 4]) -> bool {
        p[0].min(p[1]).min(p[2]) >= 200 && !is_gold(p)
    }
    fn inside(x: u32, y: u32, region: [f64; 4], scale: f64) -> bool {
        let (x, y) = (f64::from(x) + 0.5, f64::from(y) + 0.5);
        region[0] * scale <= x
            && x < region[2] * scale
            && region[1] * scale <= y
            && y < region[3] * scale
    }
    pub fn measure(image: &RgbaImage, scale: f64, full: bool) -> Ink {
        let axis = ANCHOR[0] * scale;
        let caption = if full { FULL_TEXT_BAND } else { CAPTION_BAND };
        let mut ink = Ink {
            lit: 0,
            bounds: None,
            gold_left: 0,
            gold_right: 0,
            key_white: 0,
            caption_white: 0,
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
            } else if is_white(p) {
                if !full && inside(x, y, KEY_BOX, scale) {
                    ink.key_white += 1;
                }
                if inside(x, y, caption, scale) {
                    ink.caption_white += 1;
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
        let area = (scale * scale) as u64;
        if ink.caption_white < if case == "ammo-full" { 20 } else { 60 } * area {
            return Err(format!("{case}: caption text is missing"));
        }
        if case == "ammo-full" {
            let band = FULL_TEXT_BAND.map(|v| v * scale);
            if f64::from(bounds[1]) < band[1] || f64::from(bounds[3]) >= band[3] {
                return Err("ammo-full: only the AMMO FULL text may be drawn".into());
            }
            return if ink.gold() != 0 || ink.key_white != 0 {
                Err("ammo-full: no hold circle or key may be drawn".into())
            } else {
                Ok(())
            };
        }
        if ink.key_white < 8 * area {
            return Err(format!("{case}: the F key glyph is missing"));
        }
        match case {
            "idle" if ink.gold() != 0 => Err(format!(
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
    /// 200% must be the same drawing at twice the size: ~4x area, ~2x extent.
    pub fn check_scaling(
        one_lit: u64,
        one: Option<[u32; 4]>,
        two_lit: u64,
        two: Option<[u32; 4]>,
    ) -> Result<(), String> {
        let (a, b) = (
            one.ok_or("empty 100% capture")?,
            two.ok_or("empty 200% capture")?,
        );
        let area = two_lit as f64 / one_lit.max(1) as f64;
        let width = f64::from(b[2] - b[0] + 1) / f64::from(a[2] - a[0] + 1);
        if !(3.0..=5.0).contains(&area) || !(1.8..=2.2).contains(&width) {
            return Err(format!(
                "200% capture is not a 2x rendering: area x{area:.2}, width x{width:.2}"
            ));
        }
        Ok(())
    }

    /// Logical HUD corner panels: title, score, stance, weapon.
    pub const CORNERS: [[f64; 4]; 4] = [
        [24., 24., 312., 105.],
        [685., 24., 936., 105.],
        [24., 435., 272., 516.],
        [710., 415., 936., 516.],
    ];
    /// Telemetry (debug) panel drawn under the title panel.
    pub const DEBUG_PANEL: [f64; 4] = [24., 119., 334., 326.];
    /// The scaled pause menu is centred horizontally.
    pub const MENU_BAND: [f64; 4] = [200., 0., 760., 540.];
    /// Warm accent family: the HUD/menu accent #FA9E38, GOLD #FFCB00 and the
    /// supply gold; excludes white, cyan, muted grey and the dark panels.
    pub fn is_warm(p: [u8; 4]) -> bool {
        p[0] >= 200 && (100..=215).contains(&p[1]) && p[2] <= 110
    }

    /// UI-wide ink: lit pixels and bounds, warm pixels (all and inside the
    /// menu band), white pixels, white pixels per HUD corner, and lit pixels
    /// inside the telemetry panel.
    #[derive(Debug, Clone, Copy, PartialEq)]
    pub struct UiInk {
        pub lit: u64,
        pub bounds: Option<[u32; 4]>,
        pub warm: u64,
        pub warm_menu_band: u64,
        pub white: u64,
        pub corner_white: [u64; 4],
        pub debug_lit: u64,
    }
    pub fn measure_ui(image: &RgbaImage, scale: f64) -> UiInk {
        let mut ink = UiInk {
            lit: 0,
            bounds: None,
            warm: 0,
            warm_menu_band: 0,
            white: 0,
            corner_white: [0; 4],
            debug_lit: 0,
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
            if inside(x, y, DEBUG_PANEL, scale) {
                ink.debug_lit += 1;
            }
            if is_warm(p) {
                ink.warm += 1;
                if inside(x, y, MENU_BAND, scale) {
                    ink.warm_menu_band += 1;
                }
            } else if is_white(p) {
                ink.white += 1;
                for (count, corner) in ink.corner_white.iter_mut().zip(CORNERS) {
                    if inside(x, y, corner, scale) {
                        *count += 1;
                    }
                }
            }
        }
        ink
    }
    /// Per-capture rules for the non-ammo elements, from their documented layout.
    pub fn check_ui_case(case: &str, ink: UiInk, scale: f64) -> Result<(), String> {
        let area = (scale * scale) as u64;
        if ink.bounds.is_none() {
            return Err(format!("{case}: capture is empty"));
        }
        match case {
            "pause-menu" if ink.warm_menu_band < 500 * area || ink.white < 75 * area => {
                Err(format!(
                    "pause-menu: expected accent and white text in the centred menu, got warm {} white {}",
                    ink.warm_menu_band, ink.white
                ))
            }
            "updater-current" | "updater-unavailable"
                if ink.warm < 50 * area || ink.white < 50 * area =>
            {
                Err(format!(
                    "{case}: expected gold title/frame and white message, got warm {} white {}",
                    ink.warm, ink.white
                ))
            }
            "hud" | "hud-telemetry" if ink.corner_white.iter().any(|&n| n < 20 * area) => Err(
                format!("{case}: every HUD corner needs white text, got {:?}", ink.corner_white),
            ),
            _ => Ok(()),
        }
    }
    /// The telemetry panel must add visible ink over the plain HUD.
    pub fn check_telemetry(hud: UiInk, telemetry: UiInk, scale: f64) -> Result<(), String> {
        if telemetry.debug_lit < hud.debug_lit + 300 * (scale * scale) as u64 {
            return Err(format!(
                "hud-telemetry: telemetry panel missing ({} vs {} lit)",
                telemetry.debug_lit, hud.debug_lit
            ));
        }
        Ok(())
    }

    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn write_json(path: &Path, value: &Value) -> Result<(), String> {
        let mut bytes = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
        bytes.push(b'\n');
        fs::write(path, bytes).map_err(|e| format!("write {}: {e}", path.display()))
    }
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn verify_backend(info: &BackendInfo, renderer: &str) -> Result<(), String> {
        let backend = if renderer == "dx12" { "Dx12" } else { "OpenGl" };
        if info.requested != renderer || info.backend != backend || info.adapter.trim().is_empty() {
            return Err(format!(
                "expected requested={renderer}, backend={backend} and a named actual adapter; got {info:?}"
            ));
        }
        Ok(())
    }
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    const WEAPON: &str = "hk416a5";
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    const WEAPON_LABEL: &str = "M4 / CANDIDATE";
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn updater_message(case: &str) -> &'static str {
        if case == "updater-current" {
            "Version is current."
        } else {
            "Can't reach GitHub. Retry, or play this version."
        }
    }

    /// Draw one case with its production entry point; returns its parameters.
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn draw_case(case: &str, cfg: &Settings, sim: &Simulation) -> Value {
        use rust_duty_launcher::game::{UpdatePhase, UpdateSnapshot};
        match case {
            "pause-menu" => {
                PauseMenu::default().draw(cfg, WEAPON, false, ControlMode::Toggle, None);
                json!({"weapon":WEAPON,"initial":false,"control_mode":"toggle","status":null})
            }
            "updater-current" | "updater-unavailable" => {
                let (phase, name) = if case == "updater-current" {
                    (UpdatePhase::Current, "current")
                } else {
                    (UpdatePhase::Unavailable, "unavailable")
                };
                UpdatePanel::from_snapshot(UpdateSnapshot {
                    phase,
                    message: updater_message(case).into(),
                    ..Default::default()
                })
                .draw(true);
                json!({"phase":name,"message":updater_message(case),"menu":true})
            }
            "hud" | "hud-telemetry" => {
                let debug = case == "hud-telemetry";
                hud::hud(sim, cfg, 0., false, debug, false, "", 0., WEAPON_LABEL);
                json!({"debug":debug,"recording":false,"weapon_label":WEAPON_LABEL})
            }
            _ => {
                let (_, progress, full) = AMMO_CASES
                    .into_iter()
                    .find(|(name, _, _)| *name == case)
                    .expect("every remaining case is an ammo case");
                draw_ammo_supply_hint(
                    SupplyFocus {
                        screen_anchor: glam::vec2(ANCHOR[0] as f32, ANCHOR[1] as f32),
                        world_anchor: glam::Vec3::ZERO,
                        distance: 1.,
                    },
                    progress,
                    full,
                );
                json!({"progress":progress,"ammo_full":full,"anchor_logical":ANCHOR})
            }
        }
    }

    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn ammo_ink_json(ink: Ink) -> Value {
        json!({"lit_pixels":ink.lit,"lit_bounds":ink.bounds,"gold_left":ink.gold_left,"gold_right":ink.gold_right,"key_white":ink.key_white,"caption_white":ink.caption_white})
    }
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn ui_ink_json(ink: UiInk) -> Value {
        json!({"lit_pixels":ink.lit,"lit_bounds":ink.bounds,"warm":ink.warm,"warm_menu_band":ink.warm_menu_band,"white":ink.white,"corner_white":ink.corner_white,"debug_lit":ink.debug_lit})
    }

    /// Runs inside the live window: one case per presented frame, each drawn
    /// into an offscreen target at the requested logical scale.
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    async fn capture_all(out: PathBuf) -> Result<Vec<(String, u32, Value)>, String> {
        runtime::next_frame().await?;
        let viewport = [runtime::screen_width(), runtime::screen_height()];
        if viewport != LOGICAL_SIZE.map(|v| v as f32) {
            return Err(format!(
                "live logical viewport is {viewport:?}, expected {LOGICAL_SIZE:?}"
            ));
        }
        let cfg = Settings::default();
        let sim = Simulation::new();
        let mut captures = Vec::new();
        for percent in SCALES {
            let size = physical_size(percent);
            let target = facade::render_target_ex(
                size[0],
                size[1],
                facade::RenderTargetParams { depth: false },
            )?;
            for case in CASES {
                let filename = format!("{case}-{percent}.png");
                facade::set_screen_camera(Some(&target), percent as f32 / 100.);
                facade::clear_background(Color::new(0., 0., 0., 1.));
                let parameters = draw_case(case, &cfg, &sim);
                facade::capture_png(Some(&target), out.join(&filename));
                facade::set_default_camera();
                facade::clear_background(Color::new(0., 0., 0., 1.));
                runtime::next_frame().await?;
                captures.push((filename, percent, parameters));
            }
        }
        // The last capture is written by the frame that the await above submitted.
        runtime::next_frame().await?;
        Ok(captures)
    }

    /// Re-read every capture, apply all rules, then write sidecars and the report.
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    fn verify_and_report(
        out: &Path,
        info: &BackendInfo,
        force_fallback_adapter: bool,
        captures: Vec<(String, u32, Value)>,
    ) -> Result<usize, String> {
        let mut sidecars = Vec::new();
        let mut first_scale = Vec::new();
        for percent in SCALES {
            let scale = f64::from(percent) / 100.;
            let mut images = Vec::new();
            let mut ammo_inks = Vec::new();
            let mut ui_inks = Vec::new();
            let mut lit = Vec::new();
            for (filename, _, parameters) in captures.iter().filter(|c| c.1 == percent) {
                let case = filename.trim_end_matches(&format!("-{percent}.png"));
                let image = read_png(&out.join(filename), physical_size(percent))?;
                let ink = if let Some(ammo) = ammo_case(case) {
                    let ink = measure(&image, scale, ammo == "ammo-full");
                    check_case(ammo, ink, scale)?;
                    ammo_inks.push((ammo, ink));
                    lit.push((case.to_owned(), ink.lit, ink.bounds));
                    ammo_ink_json(ink)
                } else {
                    let ink = measure_ui(&image, scale);
                    check_ui_case(case, ink, scale)?;
                    ui_inks.push((case, ink));
                    lit.push((case.to_owned(), ink.lit, ink.bounds));
                    ui_ink_json(ink)
                };
                let metadata = json!({"schema_version":2,"filename":filename,"element":element(case),"case":case,"parameters":parameters,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"scale_percent":percent,"logical_size":LOGICAL_SIZE,"physical_size":physical_size(percent),"ink":ink});
                write_json(&out.join(format!("{filename}.json")), &metadata)?;
                sidecars.push(metadata);
                images.push((case, image));
            }
            if images.iter().map(|(c, _)| *c).ne(CASES) {
                return Err(format!(
                    "{percent}%: captures do not cover every case in order"
                ));
            }
            check_distinct(&images)?;
            check_progression(&ammo_inks)?;
            let get = |name| ui_inks.iter().find(|(c, _)| *c == name).map(|(_, i)| *i);
            check_telemetry(
                get("hud").ok_or("missing hud")?,
                get("hud-telemetry").ok_or("missing hud-telemetry")?,
                scale,
            )?;
            if percent == SCALES[0] {
                first_scale = lit;
            } else {
                for ((case, a_lit, a_bounds), (_, b_lit, b_bounds)) in first_scale.iter().zip(&lit)
                {
                    check_scaling(*a_lit, *a_bounds, *b_lit, *b_bounds)
                        .map_err(|e| format!("{case}: {e}"))?;
                }
            }
        }
        let count = sidecars.len();
        let report = json!({"schema_version":2,"status":"passed","native_execution":true,"requested":info.requested,"backend":info.backend,"adapter":info.adapter,"force_fallback_adapter":force_fallback_adapter,"platform":std::env::consts::OS,"build_version":vector_range::BUILD_VERSION,"build_number":vector_range::BUILD_NUMBER,"live_logical_viewport":LOGICAL_SIZE,"scales_percent":SCALES,"cases":CASES,"captures":sidecars,"elements_covered":["pause-menu","updater-panel","hud","telemetry","ammo-hint"],"compiler_identity_source":"external captured renderer startup log; not inferred by this fixture","scope":"live game window runtime, native production game-UI draw paths to offscreen PNG","boundaries":{"os_dpi_events_verified":false,"window_presentation_verified":false,"native_pointer_or_click_verified":false,"human_legibility_approved":false}});
        write_json(&out.join(REPORT), &report)?;
        Ok(count)
    }

    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    pub fn run(args: impl IntoIterator<Item = impl Into<String>>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if options.renderer == "dx12" {
            run_dx12(options)
        } else {
            run_gl(options)
        }
    }

    /// Shared by both windows: identity, captures, rules and report.
    #[cfg(any(feature = "wgpu-runtime", feature = "legacy-macroquad"))]
    async fn contract(out: PathBuf, renderer: String, fallback: bool) -> Result<(), String> {
        let info = facade::backend_info()?;
        verify_backend(&info, &renderer)?;
        eprintln!(
            "renderer requested={} backend={} adapter={}",
            info.requested, info.backend, info.adapter
        );
        let captures = capture_all(out.clone()).await?;
        if facade::backend_info()? != info {
            return Err("renderer identity changed during the run".into());
        }
        let count = verify_and_report(&out, &info, fallback, captures)?;
        println!(
            "{} game UI contract passed on {}: {count} captures; {}",
            info.backend,
            info.adapter,
            out.join(REPORT).display()
        );
        Ok(())
    }

    #[cfg(feature = "wgpu-runtime")]
    fn run_dx12(options: Options) -> Result<(), String> {
        use vector_range::{
            platform::window,
            render::{runtime::create_frame_hooks, BackendSelection},
        };
        if !cfg!(target_os = "windows") {
            return Err("native DX12 game UI contract requires Windows; CPU compilation/tests cannot produce a native pass".into());
        }
        prepare_output(&options.output_dir)?;
        let fallback = options.force_fallback_adapter;
        window::run(
            "game_ui_contract",
            LOGICAL_SIZE[0],
            LOGICAL_SIZE[1],
            move |w| create_frame_hooks(w, BackendSelection::Dx12, fallback),
            contract(options.output_dir, options.renderer, fallback),
        )
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    fn run_dx12(_: Options) -> Result<(), String> {
        Err("--renderer=dx12 requires --features wgpu-runtime".into())
    }

    #[cfg(feature = "legacy-macroquad")]
    fn run_gl(options: Options) -> Result<(), String> {
        use vector_range::legacy_macroquad::runtime as legacy;
        prepare_output(&options.output_dir)?;
        macroquad::Window::from_config(
            macroquad::prelude::Conf {
                window_title: "game_ui_contract".into(),
                window_width: LOGICAL_SIZE[0] as i32,
                window_height: LOGICAL_SIZE[1] as i32,
                high_dpi: false,
                ..Default::default()
            },
            async move {
                let result = match legacy::initialize("gl") {
                    Ok(()) => {
                        let result = contract(options.output_dir, options.renderer, false).await;
                        // Finish the final recorder while the GL context is live.
                        result.and(legacy::shutdown())
                    }
                    Err(error) => Err(error),
                };
                if let Err(error) = result {
                    eprintln!("game_ui_contract: {error}");
                    std::process::exit(1);
                }
            },
        );
        Ok(())
    }
    #[cfg(not(feature = "legacy-macroquad"))]
    fn run_gl(_: Options) -> Result<(), String> {
        Err("--renderer=gl requires the legacy-macroquad feature".into())
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
            // White key glyph over the circle.
            for x in 236 * s..244 * s {
                for y in 112 * s..126 * s {
                    image.put_pixel(x, y, WHITE);
                }
            }
            image
        }

        #[test]
        fn missing_key_or_caption_text_is_rejected() {
            let mut no_caption = synthetic(1, Some(false));
            for x in 200..280 {
                for y in 150..158 {
                    no_caption.put_pixel(x, y, Rgba([0, 0, 0, 255]));
                }
            }
            assert!(check_case("half", measure(&no_caption, 1., false), 1.).is_err());
            let mut no_key = synthetic(2, None);
            for x in 472..488 {
                for y in 224..252 {
                    no_key.put_pixel(x, y, Rgba([0, 0, 0, 255]));
                }
            }
            assert!(check_case("idle", measure(&no_key, 2., false), 2.).is_err());
            // AMMO FULL text in its own band, with no key glyph.
            let mut full = RgbaImage::from_pixel(480, 270, Rgba([0, 0, 0, 255]));
            for x in 205..275 {
                for y in 112..120 {
                    full.put_pixel(x, y, Rgba([224, 237, 222, 255]));
                }
            }
            check_case("ammo-full", measure(&full, 1., true), 1.).unwrap();
            assert!(check_case("ammo-full", measure(&synthetic(1, None), 1., true), 1.).is_err());
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
            assert_eq!(
                Options::parse(["--renderer=gl", "--output-dir=out"])
                    .unwrap()
                    .renderer,
                "gl"
            );
            for args in [
                vec![],
                vec!["--output-dir=out"],
                vec!["--renderer=vulkan", "--output-dir=out"],
                vec![
                    "--renderer=gl",
                    "--output-dir=out",
                    "--force-fallback-adapter",
                ],
                vec!["--renderer=gl", "--renderer=dx12", "--output-dir=out"],
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
                let idle = measure(&synthetic(scale, None), s, false);
                let half = measure(&synthetic(scale, Some(false)), s, false);
                let full = measure(&synthetic(scale, Some(true)), s, false);
                check_case("idle", idle, s).unwrap();
                check_case("half", half, s).unwrap();
                check_case("complete", full, s).unwrap();
                check_progression(&[("half", half), ("complete", full)]).unwrap();
            }
            let one = measure(&synthetic(1, Some(true)), 1., false);
            let two = measure(&synthetic(2, Some(true)), 2., false);
            check_scaling(one.lit, one.bounds, two.lit, two.bounds).unwrap();
        }

        #[test]
        fn discriminating_failures_are_rejected() {
            let s = 1.;
            // Gold where no circle may be drawn.
            assert!(check_case("idle", measure(&synthetic(1, Some(false)), s, false), s).is_err());
            assert!(
                check_case("ammo-full", measure(&synthetic(1, Some(true)), s, false), s).is_err()
            );
            // Counter-clockwise half sweep (left half) and a missing sweep.
            let mut flipped = synthetic(1, None);
            for x in 221..240 {
                for y in 101..139 {
                    flipped.put_pixel(x, y, GOLD);
                }
            }
            assert!(check_case("half", measure(&flipped, s, false), s).is_err());
            assert!(check_case("half", measure(&synthetic(1, None), s, false), s).is_err());
            assert!(
                check_case("complete", measure(&synthetic(1, Some(false)), s, false), s).is_err()
            );
            // Empty capture and ink outside the prompt window.
            let empty = RgbaImage::from_pixel(480, 270, Rgba([0, 0, 0, 255]));
            assert!(check_case("idle", measure(&empty, s, false), s).is_err());
            let mut stray = synthetic(1, None);
            stray.put_pixel(5, 5, WHITE);
            assert!(check_case("idle", measure(&stray, s, false), s).is_err());
            // No growth between half and complete.
            let half = measure(&synthetic(1, Some(false)), s, false);
            assert!(check_progression(&[("half", half), ("complete", half)]).is_err());
            // Identical states and an unscaled 200% capture.
            let a = synthetic(1, None);
            assert!(check_distinct(&[("idle", a.clone()), ("ammo-full", a)]).is_err());
            let one = measure(&synthetic(1, Some(true)), 1., false);
            assert!(check_scaling(one.lit, one.bounds, one.lit, one.bounds).is_err());
        }

        fn fill(image: &mut RgbaImage, region: [u32; 4], scale: u32, colour: Rgba<u8>) {
            for x in region[0] * scale..region[2] * scale {
                for y in region[1] * scale..region[3] * scale {
                    image.put_pixel(x, y, colour);
                }
            }
        }
        fn blank(scale: u32) -> RgbaImage {
            let size = physical_size(scale * 100);
            RgbaImage::from_pixel(size[0], size[1], Rgba([0, 0, 0, 255]))
        }
        const ACCENT: Rgba<u8> = Rgba([250, 158, 56, 255]);

        #[test]
        fn cases_cover_every_element() {
            let mut elements: Vec<_> = CASES.iter().map(|c| element(c)).collect();
            elements.dedup();
            assert_eq!(
                elements,
                [
                    "pause-menu",
                    "updater-panel",
                    "hud",
                    "telemetry",
                    "ammo-hint"
                ]
            );
            let ammo: Vec<_> = CASES.iter().filter_map(|c| ammo_case(c)).collect();
            assert_eq!(ammo, ["idle", "half", "complete", "ammo-full"]);
            assert!(is_warm(ACCENT.0) && is_warm(GOLD.0) && is_warm([255, 203, 0, 255]));
            assert!(!is_warm(WHITE.0) && !is_warm([84, 214, 222, 255]));
        }

        #[test]
        fn ui_rules_accept_controls_and_reject_missing_parts() {
            for scale in [1u32, 2] {
                let s = f64::from(scale);
                let mut hud = blank(scale);
                for c in CORNERS {
                    let c = c.map(|v| v as u32);
                    fill(
                        &mut hud,
                        [c[0] + 10, c[1] + 10, c[0] + 20, c[1] + 15],
                        scale,
                        WHITE,
                    );
                }
                let plain = measure_ui(&hud, s);
                check_ui_case("hud", plain, s).unwrap();
                let mut telemetry = hud.clone();
                fill(&mut telemetry, [40, 140, 300, 160], scale, WHITE);
                let debug = measure_ui(&telemetry, s);
                check_ui_case("hud-telemetry", debug, s).unwrap();
                check_telemetry(plain, debug, s).unwrap();
                assert!(check_telemetry(plain, plain, s).is_err());
                let mut missing = hud.clone();
                fill(
                    &mut missing,
                    [710, 415, 936, 516],
                    scale,
                    Rgba([0, 0, 0, 255]),
                );
                assert!(check_ui_case("hud", measure_ui(&missing, s), s).is_err());

                let mut menu = blank(scale);
                fill(&mut menu, [300, 40, 660, 100], scale, WHITE);
                fill(&mut menu, [300, 120, 500, 130], scale, ACCENT);
                check_ui_case("pause-menu", measure_ui(&menu, s), s).unwrap();
                let mut off_centre = blank(scale);
                fill(&mut off_centre, [300, 40, 660, 100], scale, WHITE);
                fill(&mut off_centre, [0, 120, 190, 135], scale, ACCENT);
                assert!(check_ui_case("pause-menu", measure_ui(&off_centre, s), s).is_err());

                let mut updater = blank(scale);
                fill(&mut updater, [200, 100, 400, 105], scale, GOLD);
                fill(&mut updater, [200, 120, 400, 125], scale, WHITE);
                check_ui_case("updater-current", measure_ui(&updater, s), s).unwrap();
                let mut no_title = blank(scale);
                fill(&mut no_title, [200, 120, 400, 125], scale, WHITE);
                assert!(check_ui_case("updater-unavailable", measure_ui(&no_title, s), s).is_err());
                assert!(check_ui_case("hud", measure_ui(&blank(scale), s), s).is_err());
            }
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
