#[cfg(feature = "wgpu-runtime")]
mod app;
#[cfg(feature = "wgpu-runtime")]
mod authored_viewmodel;
#[cfg(feature = "wgpu-runtime")]
mod capture;
#[cfg(feature = "wgpu-runtime")]
mod combined_capture;
#[cfg(feature = "wgpu-runtime")]
mod high_app_edge_capture;
#[cfg(feature = "wgpu-runtime")]
mod high_mantle_capture;
#[cfg(feature = "wgpu-runtime")]
mod level_menu;
#[cfg(feature = "wgpu-runtime")]
mod sound;
#[cfg(feature = "wgpu-runtime")]
mod telemetry_export;
#[cfg(feature = "wgpu-runtime")]
mod viewmodel_draw;
#[cfg(feature = "wgpu-runtime")]
mod weapon_model;
#[cfg(feature = "wgpu-runtime")]
mod world_draw;
use vector_range::platform::launch::{LaunchOptions, RuntimeChoice};

/// Helper and metadata commands must complete before creating the native window.
fn dispatch_before_window() {
    if std::env::args().any(|arg| arg == "--renderer-build-info") {
        #[cfg(feature = "wgpu-runtime")]
        let native_backends: Vec<_> = {
            let enabled = wgpu::Instance::enabled_backend_features();
            [
                ("dx12", wgpu::Backends::DX12),
                ("vulkan", wgpu::Backends::VULKAN),
                ("metal", wgpu::Backends::METAL),
                ("gl", wgpu::Backends::GL),
                ("browser-webgpu", wgpu::Backends::BROWSER_WEBGPU),
            ]
            .into_iter()
            .filter_map(|(name, backend)| enabled.intersects(backend).then_some(name))
            .collect()
        };
        #[cfg(not(feature = "wgpu-runtime"))]
        let native_backends: Vec<&str> = Vec::new();
        println!(
            "{}",
            serde_json::json!({
                "schema": "rust-duty-renderer-build/v1",
                "build_version": vector_range::BUILD_VERSION,
                "build_number": vector_range::BUILD_NUMBER,
                "wgpu_runtime": cfg!(feature = "wgpu-runtime"),
                "debug_assertions": cfg!(debug_assertions),
                "native_backends": native_backends,
            })
        );
        std::process::exit(0);
    }
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

fn main() {
    dispatch_before_window();
    let args: Vec<String> = std::env::args().collect();
    let mut options = LaunchOptions::parse(&args).unwrap_or_else(|error| fatal(error));
    let graphics = vector_range::graphics_device::prepare_launch(&args, &mut options)
        .unwrap_or_else(|error| fatal(error));
    vector_range::graphics_device::initialize(graphics);
    let runtime = options
        .runtime(cfg!(feature = "wgpu-runtime"))
        .unwrap_or_else(|error| fatal(error));
    let reference = args.iter().any(|arg| arg == "--reference-viewport");
    // Separately pinned readiness candidate: window/render-cost changes only.
    // The existing app-edge parser still owns admission and mixed-mode rejection.
    let app_edge_readiness = args.iter().any(|arg| arg == "--app-edge-case=pause");
    let (width, height) = if app_edge_readiness {
        (320, 200)
    } else if reference {
        (960, 540)
    } else {
        (1440, 900)
    };
    let title = format!("RUST DUTY | {}", vector_range::BUILD_LABEL);
    let RuntimeChoice::Wgpu {
        requested,
        force_fallback,
    } = runtime;
    #[cfg(feature = "wgpu-runtime")]
    {
        let selection = requested.parse().unwrap_or_else(|error| fatal(error));
        let run_result = vector_range::platform::window::run(
            &title,
            width as u32,
            height as u32,
            move |window| {
                vector_range::render::runtime::create_frame_hooks(
                    window,
                    selection,
                    force_fallback,
                )
            },
            app::run(options.ui_theme),
        );
        // Successful deferred stops were consumed by the renderer.
        // Native-close/error exits without that present remain incomplete.
        vector_range::frame_performance_session::log_completion(
            vector_range::frame_performance_session::shutdown(),
        );
        run_result.unwrap_or_else(|error| fatal(error));
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    {
        let _ = (requested, force_fallback, width, height, title);
        fatal("requested renderer is unavailable; build with wgpu-runtime");
    }
}
