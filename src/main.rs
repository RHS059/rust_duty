#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod app;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod authored_viewmodel;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod capture;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod game_update;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod hud;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod pause_menu;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod sound;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod telemetry_export;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod viewmodel_draw;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod weapon_model;
#[cfg(any(feature = "legacy-macroquad", feature = "wgpu-runtime"))]
mod world_draw;
use vector_range::platform::launch::{LaunchOptions, RuntimeChoice};

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

fn main() {
    dispatch_before_window();
    let args: Vec<String> = std::env::args().collect();
    let options = LaunchOptions::parse(&args).unwrap_or_else(|error| fatal(error));
    let runtime = options
        .runtime(
            cfg!(feature = "legacy-macroquad"),
            cfg!(feature = "wgpu-runtime"),
        )
        .unwrap_or_else(|error| fatal(error));
    let reference = args.iter().any(|arg| arg == "--reference-viewport");
    let (width, height) = if reference { (960, 540) } else { (1440, 900) };
    let title = format!("VECTOR RANGE | {}", vector_range::BUILD_LABEL);
    match runtime {
        RuntimeChoice::Legacy => {
            #[cfg(feature = "legacy-macroquad")]
            {
                let requested = options.renderer.unwrap_or_else(|| "legacy-default".into());
                macroquad::Window::from_config(
                    macroquad::prelude::Conf {
                        window_title: title,
                        window_width: width,
                        window_height: height,
                        high_dpi: !reference,
                        sample_count: 4,
                        ..Default::default()
                    },
                    async move {
                        use vector_range::legacy_macroquad::runtime;
                        runtime::initialize(requested).unwrap_or_else(|error| fatal(error));
                        let info = vector_range::draw::facade::backend_info()
                            .unwrap_or_else(|error| fatal(error));
                        eprintln!(
                            "renderer requested={} backend={} adapter={}",
                            info.requested, info.backend, info.adapter
                        );
                        let app_result = app::run(options.ui_theme).await;
                        // Captures on the final application frame must complete
                        // even when no further next_frame await occurs.
                        let finish_result = runtime::shutdown();
                        vector_range::frame_performance_session::log_completion(
                            vector_range::frame_performance_session::shutdown(),
                        );
                        app_result
                            .and(finish_result)
                            .unwrap_or_else(|error| fatal(error));
                    },
                );
            }
            #[cfg(not(feature = "legacy-macroquad"))]
            fatal("legacy OpenGL is unavailable; build with legacy-macroquad");
        }
        RuntimeChoice::Wgpu {
            requested,
            force_fallback,
        } => {
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
    }
}
