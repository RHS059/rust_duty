#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/app.rs"]
mod app;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/capture.rs"]
mod capture;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/sound.rs"]
mod sound;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/telemetry_export.rs"]
mod telemetry_export;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/viewmodel_draw.rs"]
mod viewmodel_draw;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/weapon_model.rs"]
mod weapon_model;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
#[path = "../src/world_draw.rs"]
mod world_draw;
use vector_range::platform::launch::LaunchOptions;

/// Helper and metadata commands must complete before creating either window.
fn dispatch_before_window() {
    if std::env::args().any(|arg| arg == "--build-label") {
        println!("{}", vector_range::BUILD_LABEL);
        std::process::exit(0);
    }
    if std::env::args().any(|arg| arg == "--build-number") {
        println!("{}", vector_range::BUILD_NUMBER);
        std::process::exit(0);
    }
    if std::env::args().any(|arg| arg == "--build-version") {
        println!("{}", vector_range::BUILD_VERSION);
        std::process::exit(0);
    }
    if std::env::args().any(|arg| arg == "--verify-managed-assets") {
        match rust_duty_launcher::game::managed_asset_executable(vector_range::BUILD_VERSION) {
            Ok(Some(path)) => println!("{}", path.display()),
            Ok(None) => println!("adjacent packaged assets"),
            Err(error) => fatal(format!(
                "Managed game assets could not be verified: {error}"
            )),
        }
        std::process::exit(0);
    }
    if let Some(code) = rust_duty_launcher::game::dispatch_helper() {
        std::process::exit(code);
    }
    if let Some(code) = rust_duty_launcher::game::dispatch_headless(vector_range::BUILD_VERSION) {
        std::process::exit(code);
    }
}

fn fatal(error: impl std::fmt::Display) -> ! {
    eprintln!("Rust Duty: {error}");
    std::process::exit(1);
}

// Test-only entry point. Production modules, surface runtime, simulation,
// rendering, input and Record exports are imported unchanged. The only launch
// difference is explicit native wgpu GL selection (main's gl means legacy).
fn main() {
    dispatch_before_window();
    let args: Vec<String> = std::env::args().collect();
    let mut options = LaunchOptions::parse(&args).unwrap_or_else(|error| fatal(error));
    if options.renderer.as_deref() != Some("gl") || options.force_fallback_adapter {
        fatal("linux_actual_game_gl requires --renderer=gl and disallows forced software fallback");
    }
    if !args.iter().any(|arg| arg == "--graphics-device=auto") {
        fatal("linux_actual_game_gl requires --graphics-device=auto to avoid reading persistent preferences");
    }
    let mut graphics = vector_range::graphics_device::prepare_launch(&args, &mut options)
        .unwrap_or_else(|error| fatal(error));
    // The production JSON preference parser intentionally excludes GL. Keep it
    // unchanged; this single-device harness supplies the exact diagnostic ID in
    // memory, invoking the production unique-match and surface-support checks.
    let required = vector_range::graphics_device::Preference::Adapter(
        vector_range::graphics_device::Fingerprint {
            backend: "gl".into(),
            name: "NVIDIA A100-SXM4-40GB/PCIe/SSE2".into(),
            vendor: 4318,
            device: 0,
            device_type: "Other".into(),
        },
    );
    graphics.preference = required.clone();
    graphics.startup_preference = required;
    vector_range::graphics_device::initialize(graphics);
    let reference = args.iter().any(|arg| arg == "--reference-viewport");
    let (width, height) = if reference { (960, 540) } else { (1440, 900) };
    let title = format!(
        "VECTOR RANGE | {} | LINUX WGPU GL TEST HARNESS",
        vector_range::BUILD_LABEL
    );
    eprintln!("test_harness=linux_actual_game_gl production_source_commit=49c3bf9b3d0482ce81a7d50683904bda28468d7d dependency_context=linux-gl43-overlay");
    let run_result = vector_range::platform::window::run(
        &title,
        width,
        height,
        move |window| {
            vector_range::render::runtime::create_frame_hooks(
                window,
                vector_range::render::BackendSelection::Gl,
                false,
            )
        },
        app::run(options.ui_theme),
    );
    vector_range::frame_performance_session::log_completion(
        vector_range::frame_performance_session::shutdown(),
    );
    run_result.unwrap_or_else(|error| fatal(error));
}
