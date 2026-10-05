mod app;
mod authored_viewmodel;
mod capture;
mod game_update;
mod hud;
mod pause_menu;
mod sound;
mod viewmodel_draw;
mod weapon_model;
mod world_draw;
use macroquad::prelude::Conf;
fn config() -> Conf {
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
            Err(error) => {
                eprintln!("Managed game assets could not be verified: {error}");
                std::process::exit(1);
            }
        }
        std::process::exit(0);
    }
    if let Some(code) = rust_duty_launcher::game::dispatch_helper() {
        std::process::exit(code);
    }
    if let Some(code) = rust_duty_launcher::game::dispatch_headless(vector_range::BUILD_VERSION) {
        std::process::exit(code);
    }
    let reference = std::env::args().any(|a| a == "--reference-viewport");
    Conf {
        window_title: format!("VECTOR RANGE | {}", vector_range::BUILD_LABEL),
        window_width: if reference { 960 } else { 1440 },
        window_height: if reference { 540 } else { 900 },
        high_dpi: !reference,
        sample_count: 4,
        ..Default::default()
    }
}
#[macroquad::main(config)]
async fn main() {
    app::run().await;
}
