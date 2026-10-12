//! Windows DX12/WARP selection and live CPU-stage contract, using public APIs.
//!
//! Build with --no-default-features --features wgpu-runtime. The runner must set
//! GRAPHICS_CPU_SOURCE_SHA256 to its verified source digest at compile time and
//! pass the same digest as --source-sha. Each mode needs a fresh process and an
//! empty --output-dir. Preserve stdout, stderr, original process exit status,
//! executable/source hashes and report.json. Use an external 60-second timeout.
//!
//! Modes: seed, windowed-saved, windowed-missing, windowed-forced,
//! headless-bypass, windowed-cpu. Seed creates --graphics-settings via the actual
//! save_choice API. Saved/cpu consume that exact file unchanged. Each negative
//! control requires its own new settings path and creates an impossible identity.
//! Headless-bypass creates two renderers, with force_fallback false then true.
//! Its full actual identities are the production graphics_device_evidence stderr
//! lines: the public headless info API does not expose device_type or fingerprint.
//!
//! A successful native run proves these bounded synthetic contracts only. CPU
//! wall spans are not GPU execution/scan-out timing, and headless pixels are not
//! window presentation evidence. There is no RTX, 1080p60 or gameplay claim.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = contract::run(std::env::args().skip(1)) {
        eprintln!("graphics_cpu_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("graphics_cpu_contract requires --features wgpu-runtime and Windows DX12");
    std::process::exit(1);
}

#[cfg(feature = "wgpu-runtime")]
mod contract {
    use image::RgbaImage;
    use serde_json::{json, Value};
    use std::{
        cell::RefCell,
        fs,
        io::Write,
        path::{Path, PathBuf},
        rc::Rc,
        time::Instant,
    };
    use vector_range::{
        draw::{facade, Renderer},
        frame_performance::{CaptureLimits, RunIdentity, RuntimeIdentity},
        frame_performance_session as performance,
        graphics_device::{self as graphics, Fingerprint, Preference},
        platform::{launch::LaunchOptions, window},
        render::{runtime::create_frame_hooks, BackendSelection, WgpuRenderer},
    };

    const SOURCE_COMMIT: &str = "ebf4bcb7f489766e3c7ec188c35db9bb4146c62b";
    const COMPILED_SOURCE_SHA256: Option<&str> = option_env!("GRAPHICS_CPU_SOURCE_SHA256");
    const WARP_NAME: &str = "Microsoft Basic Render Driver";
    const WIDTH: u32 = 320;
    const HEIGHT: u32 = 180;
    const CPU_FRAMES: usize = 6;
    const STAGES: [&str; 4] = [
        "surface_acquire",
        "game_recording",
        "renderer_submit",
        "present_call",
    ];

    #[derive(Clone, Debug)]
    struct Options {
        mode: String,
        output: PathBuf,
        preference: PathBuf,
        source_sha: String,
    }
    impl Options {
        fn parse(args: impl IntoIterator<Item = String>) -> Result<Self, String> {
            let mut values = std::collections::BTreeMap::new();
            let mut args = args.into_iter();
            while let Some(arg) = args.next() {
                let (key, value) = match arg.split_once('=') {
                    Some((key, value)) => (key.to_owned(), value.to_owned()),
                    None => (arg, args.next().ok_or("option requires a value")?),
                };
                if !matches!(
                    key.as_str(),
                    "--mode" | "--output-dir" | "--graphics-settings" | "--source-sha"
                ) || value.is_empty()
                    || value.starts_with("--")
                    || values.insert(key, value).is_some()
                {
                    return Err("unknown, empty, or repeated argument".into());
                }
            }
            let mode = values.remove("--mode").ok_or("--mode is required")?;
            if !matches!(
                mode.as_str(),
                "seed"
                    | "windowed-saved"
                    | "windowed-missing"
                    | "windowed-forced"
                    | "headless-bypass"
                    | "windowed-cpu"
            ) {
                return Err("unknown contract mode".into());
            }
            Ok(Self {
                mode,
                output: values
                    .remove("--output-dir")
                    .ok_or("--output-dir is required")?
                    .into(),
                preference: values
                    .remove("--graphics-settings")
                    .ok_or("--graphics-settings is required")?
                    .into(),
                source_sha: values
                    .remove("--source-sha")
                    .ok_or("--source-sha is required")?,
            })
        }
    }

    fn require(condition: bool, message: impl Into<String>) -> Result<(), String> {
        if condition {
            Ok(())
        } else {
            Err(message.into())
        }
    }
    fn write_new(path: &Path, bytes: &[u8]) -> Result<(), String> {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|e| format!("create {}: {e}", path.display()))?;
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|e| e.to_string())
    }
    fn read_bytes(path: &Path) -> Result<Vec<u8>, String> {
        fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))
    }
    fn bytes_evidence(bytes: &[u8]) -> Value {
        json!({"length":bytes.len(), "bytes":bytes,
            "utf8":std::str::from_utf8(bytes).ok()})
    }
    fn preference_bytes(path: &Path) -> Result<Value, String> {
        Ok(bytes_evidence(&read_bytes(path)?))
    }
    fn phase(name: &str, value: Value) {
        println!("graphics_cpu_contract phase={name} evidence={value}");
    }
    fn launch(path: &Path, force_fallback: bool) -> Result<Preference, String> {
        let args = vec![format!("--graphics-settings={}", path.display())];
        let mut options = LaunchOptions {
            renderer: Some("dx12".into()),
            force_fallback_adapter: force_fallback,
            ..Default::default()
        };
        let session = graphics::prepare_launch(&args, &mut options)?;
        let preference = session.startup_preference.clone();
        graphics::initialize(session);
        Ok(preference)
    }
    fn warp(id: &Fingerprint) -> bool {
        id.backend == "dx12" && id.name == WARP_NAME && id.device_type == "Cpu"
    }

    pub fn run(args: impl IntoIterator<Item = String>) -> Result<(), String> {
        let options = Options::parse(args)?;
        if options.output.exists() {
            require(
                fs::read_dir(&options.output)
                    .map_err(|e| e.to_string())?
                    .next()
                    .is_none(),
                "output directory must be empty; stale evidence is not accepted",
            )?;
        } else {
            fs::create_dir_all(&options.output).map_err(|e| e.to_string())?;
        }
        let mut report = json!({
            "schema":"rust-duty-graphics-cpu-contract/v1", "mode":options.mode,
            "pid":std::process::id(), "source_commit":SOURCE_COMMIT,
            "source_sha":options.source_sha, "compiled_source_sha256":COMPILED_SOURCE_SHA256,
            "build_label":vector_range::BUILD_LABEL, "build_version":vector_range::BUILD_VERSION,
            "build_number":vector_range::BUILD_NUMBER, "platform":std::env::consts::OS,
            "graphics_settings":options.preference, "status":"running",
            "scope":"bounded Windows DX12/WARP synthetic selection and CPU-wall-stage controls; no hardware-performance or scan-out claim",
        });
        phase("start", report.clone());
        let result = (|| {
            let compiled = COMPILED_SOURCE_SHA256
                .ok_or("GRAPHICS_CPU_SOURCE_SHA256 was not set at build time")?;
            require(
                compiled.len() == 64 && compiled.bytes().all(|c| c.is_ascii_hexdigit()),
                "compile-time source digest must be 64 hexadecimal characters",
            )?;
            require(
                compiled == options.source_sha,
                "--source-sha differs from compile-time source digest",
            )?;
            require(
                cfg!(target_os = "windows"),
                "Windows DX12/WARP required; native controls are not run on this platform",
            )?;
            match options.mode.as_str() {
                "seed" => seed(&options, &mut report),
                "headless-bypass" => headless(&options, &mut report),
                _ => windowed(&options, &mut report),
            }
        })();
        report["status"] = json!(if result.is_ok() { "passed" } else { "failed" });
        if let Err(error) = &result {
            report["error"] = json!(error);
        }
        if options.preference.exists() {
            match preference_bytes(&options.preference) {
                Ok(bytes) => report["preference_after"] = bytes,
                Err(error) => report["preference_after_error"] = json!(error),
            }
        }
        write_new(
            &options.output.join("report.json"),
            &serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?,
        )?;
        phase("complete", report);
        result
    }

    fn seed(options: &Options, report: &mut Value) -> Result<(), String> {
        require(
            !options.preference.exists(),
            "seed preference path must be new",
        )?;
        require(
            launch(&options.preference, false)? == Preference::Auto,
            "new seed path was not Auto",
        )?;
        // This public menu path enumerates actual PRIMARY adapters (including
        // DX12); filter on the complete observed DX12 identity, never list order.
        graphics::ensure_catalog();
        let session = graphics::snapshot();
        if let Some(error) = session.catalog_error {
            return Err(error);
        }
        report["catalog"] = json!(session.candidates.iter().map(|candidate|
            json!({"fingerprint":candidate.id.json(), "surface_supported":candidate.surface_supported})
        ).collect::<Vec<_>>());
        report["catalog_surface_checked"] = json!(false);
        report["catalog_api"] = json!(
            "graphics_device::ensure_catalog; actual PRIMARY adapter enumeration, filtered to DX12"
        );
        let matches: Vec<_> = session
            .candidates
            .iter()
            .filter(|candidate| warp(&candidate.id))
            .collect();
        require(
            matches.len() == 1,
            format!(
                "need exactly one observed DX12 {WARP_NAME}/Cpu adapter; found {}",
                matches.len()
            ),
        )?;
        let preference = Preference::Adapter(matches[0].id.clone());
        graphics::save_choice(preference.clone())?;
        require(
            Preference::load(&options.preference)? == preference,
            "saved WARP choice did not round-trip",
        )?;
        report["saved_fingerprint"] = preference.json();
        report["preference_before"] = Value::Null;
        report["save_api"] = json!("graphics_device::save_choice");
        report["preference_after"] = preference_bytes(&options.preference)?;
        Ok(())
    }

    fn missing_fixture(options: &Options, report: &mut Value) -> Result<Preference, String> {
        require(
            !options.preference.exists(),
            "negative control preference path must be new",
        )?;
        let preference = Preference::Adapter(Fingerprint {
            backend: "dx12".into(),
            name: format!(
                "Rust Duty deliberately missing adapter {}",
                std::process::id()
            ),
            vendor: u32::MAX,
            device: u32::MAX,
            device_type: "Cpu".into(),
        });
        // A missing identity cannot pass save_choice. This deliberately hostile
        // saved-file fixture exercises the normal prepare_launch reader instead.
        preference.save(&options.preference)?;
        report["fixture_save_api"] =
            json!("Preference::save (intentionally nonexistent fingerprint)");
        report["fixture_fingerprint"] = preference.json();
        Ok(preference)
    }

    fn paint() {
        facade::set_screen_camera(None, 1.);
        facade::clear_background(facade::BLACK);
        // Physical-pixel coordinates, unaffected by Windows DPI scaling.
        facade::draw_rectangle(8., 8., 40., 32., facade::Color::new(1., 0., 0., 1.));
        facade::draw_rectangle(64., 8., 40., 32., facade::Color::new(0., 1., 0., 1.));
        facade::draw_rectangle(120., 8., 40., 32., facade::Color::new(0., 0., 1., 1.));
    }
    fn verify_pixels(image: &RgbaImage) -> Result<Value, String> {
        require(
            image.width() >= 176 && image.height() >= 64,
            "capture dimensions are too small",
        )?;
        // Independent expected bytes; never derived from the renderer output.
        let probes = [
            (24, 24, [255, 0, 0, 255]),
            (80, 24, [0, 255, 0, 255]),
            (136, 24, [0, 0, 255, 255]),
            (168, 56, [0, 0, 0, 255]),
        ];
        for (x, y, expected) in probes {
            let actual = image.get_pixel(x, y).0;
            require(
                actual.iter().zip(expected).all(|(a, e)| a.abs_diff(e) <= 2),
                format!("pixel ({x},{y}) expected {expected:?}, got {actual:?}"),
            )?;
        }
        Ok(
            json!({"width":image.width(), "height":image.height(), "probe_count":4,
            "tolerance":2, "probes":[[24,24,[255,0,0,255]], [80,24,[0,255,0,255]],
                [136,24,[0,0,255,255]], [168,56,[0,0,0,255]]]}),
        )
    }

    #[derive(Default)]
    struct HookState {
        attempts: usize,
        successful_end_frames: usize,
        app_frames: usize,
        physical_width: u32,
        physical_height: u32,
        scale_factor: f64,
        events: Vec<Value>,
    }
    struct ObservedHooks {
        inner: Box<dyn window::FrameHooks>,
        state: Rc<RefCell<HookState>>,
        started: Instant,
    }
    impl window::FrameHooks for ObservedHooks {
        fn resize(&mut self, width: u32, height: u32, scale: f64) -> Result<(), String> {
            self.inner.resize(width, height, scale)?;
            let mut state = self.state.borrow_mut();
            state.physical_width = width;
            state.physical_height = height;
            state.scale_factor = scale;
            Ok(())
        }
        fn begin_frame(&mut self, width: f32, height: f32) -> Result<window::FrameStart, String> {
            require(
                self.started.elapsed().as_secs() < 30,
                "windowed control exceeded 30 seconds",
            )?;
            let mut state = self.state.borrow_mut();
            state.attempts += 1;
            require(
                state.attempts <= 128,
                "windowed control exceeded 128 frame attempts",
            )?;
            let active_before = performance::is_active();
            let result = self.inner.begin_frame(width, height)?;
            let attempt = state.attempts;
            state.events.push(json!({"event":"begin", "attempt":attempt,
                "ready":result == window::FrameStart::Ready, "cpu_active_before":active_before}));
            Ok(result)
        }
        fn end_frame(&mut self) -> Result<(), String> {
            let active_before = performance::is_active();
            let stop_before = performance::is_stop_requested();
            self.inner.end_frame()?;
            let mut state = self.state.borrow_mut();
            state.successful_end_frames += 1;
            let count = state.successful_end_frames;
            state
                .events
                .push(json!({"event":"end", "successful_end_frame":count,
                "cpu_active_before":active_before, "stop_requested_before":stop_before,
                "cpu_active_after":performance::is_active()}));
            Ok(())
        }
    }

    fn verify_window_evidence(saved: &Preference, forced: bool) -> Result<Value, String> {
        let state = graphics::snapshot();
        let evidence = state.evidence;
        require(
            state.actual.is_some(),
            "windowed renderer did not publish actual adapter",
        )?;
        require(
            evidence["backend"] == "Dx12"
                && evidence["name"] == WARP_NAME
                && evidence["device_type"] == "Cpu",
            "actual windowed renderer is not DX12 WARP/Cpu",
        )?;
        require(
            evidence["present_mode"]
                .as_str()
                .is_some_and(|s| !s.is_empty()),
            "missing actual window present mode",
        )?;
        require(
            evidence["force_fallback_requested"] == forced,
            "force fallback evidence differs",
        )?;
        if forced {
            require(
                evidence["selection_mode"] == "forced_fallback"
                    && evidence["requested_fingerprint"].is_null(),
                "forced window did not bypass saved fingerprint",
            )?;
        } else {
            require(evidence["selection_mode"] == "explicit_fingerprint"
                && evidence["requested_fingerprint"] == saved.json()
                && evidence["actual_fingerprint"] == saved.json(),
                "actual windowed adapter differs from saved full fingerprint or selection is not explicit")?;
        }
        Ok(evidence)
    }

    fn windowed(options: &Options, report: &mut Value) -> Result<(), String> {
        let missing = options.mode == "windowed-missing";
        let forced = options.mode == "windowed-forced";
        let cpu = options.mode == "windowed-cpu";
        if missing || forced {
            missing_fixture(options, report)?;
        }
        let before = read_bytes(&options.preference)?;
        report["preference_before"] = bytes_evidence(&before);
        let saved = Preference::load(&options.preference)?;
        let loaded = launch(&options.preference, forced)?;
        report["loaded_startup_preference"] = loaded.json();
        require(
            if forced {
                loaded == Preference::Auto
            } else {
                loaded == saved
            },
            "prepare_launch did not apply preference policy",
        )?;
        if !missing && !forced {
            require(
                matches!(&saved, Preference::Adapter(id) if warp(id)),
                "saved preference is not a full WARP/Cpu identity",
            )?;
        }
        let state = Rc::new(RefCell::new(HookState::default()));
        let hook_state = state.clone();
        let app_state = state.clone();
        let output = options.output.clone();
        let source_sha = options.source_sha.clone();
        let result = window::run(
            "Rust Duty bounded graphics/CPU contract",
            WIDTH,
            HEIGHT,
            move |native_window| {
                let hooks = create_frame_hooks(native_window, BackendSelection::Dx12, forced)?;
                Ok(Box::new(ObservedHooks {
                    inner: hooks,
                    state: hook_state,
                    started: Instant::now(),
                }))
            },
            async move {
                if missing {
                    return Err("missing fingerprint unexpectedly created a renderer".into());
                }
                let frames = if cpu { CPU_FRAMES } else { 2 };
                for frame in 0..frames {
                    if cpu && frame == 1 {
                        require(
                            app_state.borrow().successful_end_frames == 1,
                            "CPU recording did not start after exactly one uninstrumented present",
                        )?;
                        require(
                            !performance::is_active(),
                            "CPU observer was unexpectedly active",
                        )?;
                        let runtime = graphics::snapshot();
                        performance::start(RunIdentity {
                            runtime: RuntimeIdentity {
                                actual_backend: runtime.actual.map(|info| info.backend),
                                actual_adapter:runtime.evidence,
                                build:json!({"source_commit":SOURCE_COMMIT, "source_sha256":source_sha,
                                    "build_label":vector_range::BUILD_LABEL}),
                                initial_window:window::performance_window_context(),
                                scene:json!({"fixture":"three original solid rectangles", "gameplay":false}),
                            }, operator_supplied:Value::Null,
                        }, output.join("cpu-capture.json"), CaptureLimits {max_records:256, ..Default::default()})
                            .map_err(|e| e.to_string())?;
                    }
                    paint();
                    // Capture is outside the CPU recording period. The final
                    // measured frame still returns through ordinary end_frame.
                    if frame == 0 {
                        facade::capture_png(None, output.join("windowed.png"));
                    }
                    app_state.borrow_mut().app_frames += 1;
                    if frame + 1 == frames {
                        if cpu {
                            performance::request_stop();
                            require(
                                performance::is_active() && performance::is_stop_requested(),
                                "CPU stop was not pending before final normal present",
                            )?;
                            require(
                                !output.join("cpu-capture.json").exists(),
                                "CPU report was written before the final present",
                            )?;
                        }
                        return Ok(());
                    }
                    window::next_frame().await;
                }
                Err("frame loop did not return its final frame".into())
            },
        );
        let observed = state.borrow();
        report["window"] = json!({"requested_logical_width":WIDTH,"requested_logical_height":HEIGHT,
            "physical_width":observed.physical_width,"physical_height":observed.physical_height,
            "scale_factor":observed.scale_factor,"attempts":observed.attempts,
            "app_frames":observed.app_frames,"successful_end_frames":observed.successful_end_frames,
            "events":observed.events});
        report["window_run_result"] = json!(result);
        report["backend_evidence"] = graphics::snapshot().evidence;
        require(
            read_bytes(&options.preference)? == before,
            "windowed control changed preference bytes",
        )?;
        if missing {
            let error = result
                .err()
                .ok_or("missing preference unexpectedly launched successfully")?;
            require(
                error.contains("is missing. No fallback was used."),
                format!("wrong missing-fingerprint failure: {error}"),
            )?;
            require(
                observed.app_frames == 0
                    && observed.successful_end_frames == 0
                    && graphics::snapshot().actual.is_none(),
                "missing fingerprint rendered or fell back",
            )?;
            report["expected_failure"] = json!(error);
            report["no_fallback_verified"] = json!(true);
            return Ok(());
        }
        result?;
        let frames = if cpu { CPU_FRAMES } else { 2 };
        require(
            observed.app_frames == frames && observed.successful_end_frames == frames,
            "window was closed or final normal presentation did not finish",
        )?;
        report["backend_evidence"] = verify_window_evidence(&saved, forced)?;
        let image = image::open(options.output.join("windowed.png"))
            .map_err(|e| e.to_string())?
            .to_rgba8();
        let pixels = verify_pixels(&image)?;
        require(
            image.width() == observed.physical_width && image.height() == observed.physical_height,
            "physical window extent changed during the bounded capture",
        )?;
        report["pixels"] = pixels;
        report["artifacts"] = json!(["windowed.png"]);
        if cpu {
            require(
                !performance::is_active(),
                "normal final present did not complete CPU export",
            )?;
            let capture: Value =
                serde_json::from_slice(&read_bytes(&options.output.join("cpu-capture.json"))?)
                    .map_err(|e| e.to_string())?;
            validate_cpu_report(&capture, observed.physical_width, observed.physical_height)?;
            report["cpu_validation"] = json!({"complete":true, "uninstrumented_present_count":1,
                "recorded_present_count":CPU_FRAMES-1,"complete_cpu_sample_count":CPU_FRAMES-2,
                "first_recorded_present_has_cpu_sample":false,"normal_final_present_export":true});
            report["artifacts"] = json!(["windowed.png", "cpu-capture.json"]);
        }
        Ok(())
    }

    fn headless(options: &Options, report: &mut Value) -> Result<(), String> {
        let missing = missing_fixture(options, report)?;
        let before = read_bytes(&options.preference)?;
        report["preference_before"] = bytes_evidence(&before);
        let mut creations = Vec::new();
        for force in [false, true] {
            let loaded = launch(&options.preference, false)?;
            require(
                loaded == missing,
                "headless control must load the impossible identity before renderer creation",
            )?;
            phase(
                "headless-create",
                json!({"force_fallback":force,"loaded_preference":loaded.json()}),
            );
            let mut renderer = pollster::block_on(WgpuRenderer::new_headless(
                WIDTH,
                HEIGHT,
                BackendSelection::Dx12,
                force,
            ))?;
            let info = renderer.info().clone();
            require(
                info.requested == "dx12" && info.backend == "Dx12" && info.adapter == WARP_NAME,
                format!("headless actual adapter is not DX12 WARP: {info:?}"),
            )?;
            // This verifies bypass at the real constructor boundary, independently
            // of forced prepare_launch's earlier preference-reading bypass.
            require(
                graphics::snapshot().startup_preference == missing,
                "headless constructor rewrote the loaded impossible preference",
            )?;
            facade::begin_frame(WIDTH, HEIGHT, 1.)?;
            paint();
            let name = if force {
                "headless-forced.png"
            } else {
                "headless-auto.png"
            };
            facade::capture_png(None, options.output.join(name));
            renderer.submit(&facade::take_draw_list()?)?;
            let pixels = verify_pixels(
                &image::open(options.output.join(name))
                    .map_err(|e| e.to_string())?
                    .to_rgba8(),
            )?;
            creations.push(json!({"force_fallback_requested":force, "requested":info.requested,
                "backend":info.backend,"adapter":info.adapter,"loaded_startup_preference":loaded.json(),
                "present_mode":null,"windowed":false,"pixels":pixels,"artifact":name,
                "full_actual_evidence_source":"matching production renderer graphics_device_evidence stderr line"}));
            report["headless_creations"] = json!(creations);
            phase("headless-created", creations.last().unwrap().clone());
        }
        require(
            read_bytes(&options.preference)? == before,
            "headless controls changed preference bytes",
        )?;
        report["artifacts"] = json!(["headless-auto.png", "headless-forced.png"]);
        Ok(())
    }

    fn number(value: &Value, key: &str) -> Result<u64, String> {
        value[key]
            .as_u64()
            .ok_or_else(|| format!("missing integer {key}"))
    }
    fn validate_cpu_report(report: &Value, width: u32, height: u32) -> Result<(), String> {
        require(
            report["schema"] == "rust_duty_frame_performance_v1"
                && report["status"]["state"] == "complete",
            "CPU report is not complete",
        )?;
        require(
            report["successful_present_count"] == CPU_FRAMES - 1,
            "wrong CPU present count",
        )?;
        require(
            report["cpu_frame_stages"]["measurement"] == "cpu_wall_clock_paired_frame_stage_ns",
            "wrong CPU stage measurement",
        )?;
        let records = report["records"].as_array().ok_or("missing CPU records")?;
        let presents: Vec<_> = records
            .iter()
            .enumerate()
            .filter(|(_, r)| r["kind"] == "successful_present_return")
            .collect();
        require(
            presents.len() == CPU_FRAMES - 1,
            "wrong retained present count",
        )?;
        let final_present = presents.last().unwrap().1;
        require(
            report["stopped_at_ns"] == final_present["at_ns"]
                && number(report, "stop_requested_ns")? <= number(final_present, "at_ns")?,
            "CPU export did not stop on final present",
        )?;
        let samples = report["cpu_frame_stages"]["samples"]
            .as_array()
            .ok_or("missing CPU samples")?;
        let mut complete = 0;
        let mut eligible_interval_samples = 0;
        let mut seen = std::collections::BTreeSet::new();
        for sample in samples {
            let index =
                usize::try_from(number(sample, "record_index")?).map_err(|e| e.to_string())?;
            require(
                index < records.len() && seen.insert(index),
                "CPU sample has invalid or duplicate record index",
            )?;
            require(
                index != presents[0].0,
                "mid-frame activation fabricated CPU timing for the first recorded present",
            )?;
            require(
                sample["physical_width"] == width && sample["physical_height"] == height,
                "CPU sample did not preserve physical dimensions",
            )?;
            let record = &records[index];
            require(
                sample["finished_at_ns"] == record["at_ns"],
                "CPU sample was not paired to its retained event",
            )?;
            let success = record["kind"] == "successful_present_return";
            if success {
                complete += 1;
                if record["eligible"] == true && record["interval_ns"].as_u64().is_some() {
                    eligible_interval_samples += 1;
                }
            }
            let mut previous_end = number(sample, "started_at_ns")?;
            let finish = number(sample, "finished_at_ns")?;
            for stage in STAGES {
                let span = &sample["spans"][stage];
                if span.is_null() {
                    require(!success, format!("successful CPU frame lacks {stage}"))?;
                    continue;
                }
                let start = number(span, "started_at_ns")?;
                let end = number(span, "ended_at_ns")?;
                require(
                    previous_end <= start
                        && start <= end
                        && end <= finish
                        && number(span, "duration_ns")? == end - start,
                    format!("invalid or overlapping CPU stage {stage}"),
                )?;
                previous_end = end;
            }
        }
        require(
            complete == CPU_FRAMES - 2,
            "wrong complete CPU sample count",
        )?;
        require(
            eligible_interval_samples >= 2,
            "need at least two eligible interval-bearing samples with all CPU stages",
        )?;
        require(
            seen.contains(&presents.last().unwrap().0),
            "final present lacks CPU stages",
        )
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn independent_pixels_detect_wrong_or_missing_rectangle() {
            let mut image = RgbaImage::from_pixel(WIDTH, HEIGHT, image::Rgba([0, 0, 0, 255]));
            for (x, y, color) in [
                (24, 24, [255, 0, 0, 255]),
                (80, 24, [0, 255, 0, 255]),
                (136, 24, [0, 0, 255, 255]),
            ] {
                image.put_pixel(x, y, image::Rgba(color));
            }
            assert!(verify_pixels(&image).is_ok());
            image.put_pixel(80, 24, image::Rgba([255, 0, 0, 255]));
            assert!(verify_pixels(&image).unwrap_err().contains("pixel (80,24)"));
            assert!(verify_pixels(&RgbaImage::new(10, 10)).is_err());
        }
        #[test]
        fn warp_requires_full_observed_backend_name_and_cpu_type() {
            let mut id = Fingerprint {
                backend: "dx12".into(),
                name: WARP_NAME.into(),
                vendor: 1,
                device: 2,
                device_type: "Cpu".into(),
            };
            assert!(warp(&id));
            id.device_type = "DiscreteGpu".into();
            assert!(!warp(&id));
            id.device_type = "Cpu".into();
            id.backend = "vulkan".into();
            assert!(!warp(&id));
            id.backend = "dx12".into();
            id.name = "Basic Render Driver".into();
            assert!(!warp(&id));
        }
        #[test]
        fn cli_requires_explicit_mode_paths_digest_and_rejects_duplicates() {
            let args = [
                "--mode",
                "seed",
                "--output-dir",
                "out",
                "--graphics-settings",
                "pref",
                "--source-sha",
                "digest",
            ]
            .map(str::to_owned);
            assert_eq!(Options::parse(args.clone()).unwrap().mode, "seed");
            assert!(Options::parse(args[..6].iter().cloned()).is_err());
            assert!(Options::parse(args.into_iter().chain(["--mode=seed".into()])).is_err());
        }
        fn capture() -> Value {
            let records: Vec<_> = (0..5)
                .map(|i| {
                    json!({"kind":"successful_present_return","at_ns":100+i*100,
                    "eligible":true,"interval_ns":if i == 0 {None} else {Some(100)}})
                })
                .collect();
            let samples: Vec<_> = (1..5)
                .map(|i| {
                    let start = 100 + i * 100 - 50;
                    let spans: serde_json::Map<String, Value> = STAGES
                        .iter()
                        .enumerate()
                        .map(|(j, stage)| {
                            let at = start + j * 10;
                            (
                                (*stage).into(),
                                json!({"started_at_ns":at,"ended_at_ns":at+5,"duration_ns":5}),
                            )
                        })
                        .collect();
                    json!({"record_index":i,"started_at_ns":start,"finished_at_ns":100+i*100,
                    "physical_width":320,"physical_height":180,"spans":spans})
                })
                .collect();
            json!({"schema":"rust_duty_frame_performance_v1","status":{"state":"complete"},
                "successful_present_count":5,"stop_requested_ns":480,"stopped_at_ns":500,
                "records":records,"cpu_frame_stages":{"measurement":"cpu_wall_clock_paired_frame_stage_ns","samples":samples}})
        }
        #[test]
        fn cpu_checker_rejects_fabricated_first_span_overlap_missing_and_early_stop() {
            let valid = capture();
            assert!(validate_cpu_report(&valid, 320, 180).is_ok());
            let mut altered = valid.clone();
            altered["cpu_frame_stages"]["samples"][0]["record_index"] = json!(0);
            assert!(validate_cpu_report(&altered, 320, 180).is_err());
            let mut altered = valid.clone();
            altered["cpu_frame_stages"]["samples"][0]["spans"]["game_recording"]["started_at_ns"] =
                json!(151);
            assert!(validate_cpu_report(&altered, 320, 180).is_err());
            let mut altered = valid.clone();
            altered["cpu_frame_stages"]["samples"][0]["spans"]["present_call"] = Value::Null;
            assert!(validate_cpu_report(&altered, 320, 180).is_err());
            let mut altered = valid.clone();
            for record in altered["records"].as_array_mut().unwrap() {
                record["interval_ns"] = Value::Null;
            }
            assert!(validate_cpu_report(&altered, 320, 180).is_err());
            let mut altered = valid;
            altered["stopped_at_ns"] = json!(480);
            assert!(validate_cpu_report(&altered, 320, 180).is_err());
        }
    }
}
