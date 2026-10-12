//! Asset-free Windows DX12/WARP stop/restart through the real window/session APIs.
//! The runner builds and binds this executable to a clean source inventory.
//! No extra GPU poll, wait, readback, or synthetic timestamp is introduced.

#[cfg(feature = "wgpu-runtime")]
fn main() {
    if let Err(error) = contract::run() {
        eprintln!("gpu_session_contract: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(feature = "wgpu-runtime"))]
fn main() {
    eprintln!("gpu_session_contract requires --features wgpu-runtime");
    std::process::exit(1);
}

#[cfg(feature = "wgpu-runtime")]
mod contract {
    use serde_json::{json, Value};
    use std::{cell::RefCell, fs, io::Write, path::Path, rc::Rc, time::Instant};
    use vector_range::{
        draw::facade,
        frame_performance::{CaptureLimits, CaptureStatus, RunIdentity, RuntimeIdentity},
        frame_performance_session as performance, graphics_device as graphics,
        platform::{launch::LaunchOptions, window},
        render::{
            runtime::{create_frame_hooks, create_frame_hooks_with_diagnostics},
            BackendSelection, RuntimeDiagnostics,
        },
    };

    const FRAMES: usize = 64;
    const IDLE: usize = 4;
    const SOURCE: Option<&str> = option_env!("GPU_SESSION_SOURCE_SHA256");
    const COMMIT: Option<&str> = option_env!("GPU_SESSION_SOURCE_COMMIT");

    fn require(value: bool, message: &str) -> Result<(), String> {
        if value {
            Ok(())
        } else {
            Err(message.into())
        }
    }

    fn paint() {
        facade::set_screen_camera(None, 1.);
        facade::clear_background(facade::BLACK);
        for (x, color) in [
            (8., facade::RED),
            (64., facade::Color::new(0., 1., 0., 1.)),
            (120., facade::Color::new(0., 0., 1., 1.)),
        ] {
            facade::draw_rectangle(x, 8., 40., 32., color);
        }
    }

    #[derive(Default)]
    struct State {
        attempts: usize,
        presents: usize,
        sessions: Vec<Value>,
    }
    struct Hooks {
        inner: Box<dyn window::FrameHooks>,
        state: Rc<RefCell<State>>,
        started: Instant,
    }
    impl window::FrameHooks for Hooks {
        fn resize(&mut self, width: u32, height: u32, scale: f64) -> Result<(), String> {
            self.inner.resize(width, height, scale)
        }
        fn begin_frame(&mut self, width: f32, height: f32) -> Result<window::FrameStart, String> {
            self.state.borrow_mut().attempts += 1;
            require(
                self.started.elapsed().as_secs() < 45 && self.state.borrow().attempts <= 512,
                "bounded window attempt/time limit exceeded",
            )?;
            self.inner.begin_frame(width, height)
        }
        fn end_frame(&mut self) -> Result<(), String> {
            self.inner.end_frame()?;
            self.state.borrow_mut().presents += 1;
            Ok(())
        }
    }

    fn completed(path: &Path, enabled: bool) -> Result<(), String> {
        require(
            !performance::is_active(),
            "stop did not finish on the final normal present",
        )?;
        let primary =
            performance::take_completion_notice().ok_or("missing primary completion notice")?;
        require(
            primary.output_path == path
                && primary.status == CaptureStatus::Complete
                && primary.export_error.is_none(),
            "primary capture/export was incomplete",
        )?;
        let gpu = performance::take_gpu_timing_export_notice();
        if enabled {
            let gpu = gpu.ok_or("missing GPU export notice")?;
            require(
                gpu.output_path == path.with_extension("gpu-timing.json")
                    && gpu.accounting_complete
                    && gpu.export_error.is_none(),
                "GPU accounting/export was incomplete",
            )?;
        } else {
            require(
                gpu.is_none() && !path.with_extension("gpu-timing.json").exists(),
                "default-off control produced a GPU notice or sidecar",
            )?;
        }
        let cpu = performance::take_cpu_substage_export_notice()
            .ok_or("missing CPU substage export notice")?;
        require(
            cpu.output_path == path.with_extension("cpu-substages.json") && cpu.error.is_none(),
            "CPU substage export failed",
        )?;
        let encode = performance::take_cpu_encode_detail_export_notice()
            .ok_or("missing CPU encode-detail export notice")?;
        require(
            encode.output_path == path.with_extension("cpu-encode-detail.json")
                && encode.error.is_none(),
            "CPU encode-detail export failed",
        )?;
        require(
            performance::take_completion_notice().is_none()
                && performance::take_gpu_timing_export_notice().is_none()
                && performance::take_cpu_substage_export_notice().is_none()
                && performance::take_cpu_encode_detail_export_notice().is_none(),
            "completion notices were not consumed",
        )
    }

    pub fn run() -> Result<(), String> {
        let mut output = None;
        let mut renderer = false;
        let mut fallback = false;
        let mut args = std::env::args().skip(1);
        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--renderer=dx12" if !renderer => renderer = true,
                "--force-fallback-adapter" if !fallback => fallback = true,
                "--output-dir" if output.is_none() => {
                    output = args.next().map(std::path::PathBuf::from)
                }
                _ => {
                    return Err(
                        "expected only --renderer=dx12 --force-fallback-adapter --output-dir PATH"
                            .into(),
                    )
                }
            }
        }
        require(
            renderer && fallback,
            "explicit DX12/WARP selection is required",
        )?;
        require(cfg!(target_os = "windows"), "Windows DX12 is required")?;
        let mode =
            std::env::var("GPU_SESSION_CONTRACT_MODE").map_err(|_| "runner mode is missing")?;
        let enabled = match mode.as_str() {
            "enabled" => true,
            "default-off" => false,
            _ => return Err("runner mode must be enabled or default-off".into()),
        };
        let source = SOURCE.ok_or("runner compile-time source digest is missing")?;
        let commit = COMMIT.ok_or("runner compile-time source commit is missing")?;
        require(
            source.len() == 64
                && commit.len() == 40
                && source
                    .bytes()
                    .chain(commit.bytes())
                    .all(|v| v.is_ascii_hexdigit()),
            "invalid build binding",
        )?;
        let output = output.ok_or("--output-dir is required")?;
        fs::create_dir_all(&output).map_err(|e| e.to_string())?;
        require(
            fs::read_dir(&output)
                .map_err(|e| e.to_string())?
                .next()
                .is_none(),
            "output directory must be empty",
        )?;
        let mut launch = LaunchOptions {
            renderer: Some("dx12".into()),
            force_fallback_adapter: true,
            gpu_timestamps: enabled,
            ..Default::default()
        };
        let settings = output.join("unused-graphics-settings.json");
        graphics::initialize(graphics::prepare_launch(
            &[format!("--graphics-settings={}", settings.display())],
            &mut launch,
        )?);
        let state = Rc::new(RefCell::new(State::default()));
        let hook_state = state.clone();
        let app_state = state.clone();
        let app_output = output.clone();
        let result = window::run_with_size(
            "Rust Duty GPU session contract",
            winit::dpi::PhysicalSize::new(1920, 1080).into(),
            move |native| {
                let inner = if enabled {
                    create_frame_hooks_with_diagnostics(
                        native,
                        BackendSelection::Dx12,
                        true,
                        RuntimeDiagnostics {
                            gpu_timestamps: true,
                            ..Default::default()
                        },
                    )?
                } else {
                    create_frame_hooks(native, BackendSelection::Dx12, true)?
                };
                Ok(Box::new(Hooks {
                    inner,
                    state: hook_state,
                    started: Instant::now(),
                }))
            },
            async move {
                for ordinal in 0..2 {
                    // Let ordinary idle presents deliver callbacks from the retired session.
                    // The next capture must still start with its own session and attempt zero.
                    for _ in 0..IDLE {
                        require(
                            !performance::is_active(),
                            "session remained active during idle gap",
                        )?;
                        paint();
                        window::next_frame().await;
                    }
                    require(
                        performance::take_completion_notice().is_none()
                            && performance::take_gpu_timing_export_notice().is_none()
                            && performance::take_cpu_substage_export_notice().is_none()
                            && performance::take_cpu_encode_detail_export_notice().is_none(),
                        "stale completion crossed the idle gap",
                    )?;
                    let runtime = graphics::snapshot();
                    require(
                        runtime.evidence["backend"] == "Dx12"
                            && runtime.evidence["name"] == "Microsoft Basic Render Driver"
                            && runtime.evidence["device_type"] == "Cpu"
                            && runtime.evidence["present_mode"] == "Fifo"
                            && runtime.evidence["gpu_timestamps_requested"] == enabled,
                        "actual DX12/WARP/Fifo renderer or timestamp opt-in differs",
                    )?;
                    let path = app_output.join(format!("session-{ordinal}.json"));
                    let started_after = app_state.borrow().presents;
                    performance::start(RunIdentity {
                    runtime: RuntimeIdentity {
                        actual_backend: runtime.actual.map(|info| info.backend),
                        actual_adapter: runtime.evidence,
                        build: json!({"source_commit":commit,"source_sha256":source}),
                        initial_window: window::performance_window_context(),
                        scene: json!({"fixture":"gpu-session-contract","ordinal":ordinal,"gameplay":false}),
                    }, operator_supplied: Value::Null,
                }, path.clone(), CaptureLimits { max_records: 512, ..Default::default() })
                    .map_err(|e| e.to_string())?;
                    for frame in 0..FRAMES {
                        paint();
                        if frame + 1 == FRAMES {
                            performance::request_stop();
                            require(
                                performance::is_active()
                                    && performance::is_stop_requested()
                                    && !path.exists()
                                    && !path.with_extension("gpu-timing.json").exists()
                                    && !path.with_extension("cpu-substages.json").exists()
                                    && !path.with_extension("cpu-encode-detail.json").exists(),
                                "export occurred before the final normal present",
                            )?;
                        }
                        window::next_frame().await;
                    }
                    completed(&path, enabled)?;
                    let finished_after = app_state.borrow().presents;
                    require(
                        finished_after == started_after + FRAMES,
                        "session normal-present count differs",
                    )?;
                    app_state
                        .borrow_mut()
                        .sessions
                        .push(json!({"ordinal":ordinal,
                    "started_after_present":started_after,"completed_after_present":finished_after,
                    "stop_before_final_present":true,"completion_consumed_once":true}));
                }
                paint();
                Ok(())
            },
        );
        let observed = state.borrow();
        let report = json!({"schema":"rust-duty-gpu-session-contract/v1",
            "status":if result.is_ok() {"passed"} else {"failed"}, "error":result.as_ref().err(),
            "platform":std::env::consts::OS,"source_commit":commit,"source_sha256":source,
            "mode":mode,"gpu_timestamps_requested":enabled,"backend_evidence":graphics::snapshot().evidence,
            "frames_per_session":FRAMES,"idle_frames_before_each":IDLE,
            "successful_end_frames":observed.presents,"attempts":observed.attempts,
            "sessions":observed.sessions,
            "scope":"bounded synthetic DX12/WARP session lifecycle; no FPS, RTX, gameplay, scan-out, or performance verdict"});
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(output.join("gpu-session-contract.json"))
            .map_err(|e| e.to_string())?;
        file.write_all(&serde_json::to_vec_pretty(&report).map_err(|e| e.to_string())?)
            .and_then(|_| file.sync_all())
            .map_err(|e| e.to_string())?;
        result?;
        require(
            observed.sessions.len() == 2 && observed.presents == 2 * (FRAMES + IDLE) + 1,
            "window closed before both sessions and the final idle present completed",
        )
    }
}
