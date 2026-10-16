//! Pre-spawn level selection. Loading happens only after explicit confirmation.
use std::path::Path;
use vector_range::{
    city_level::{CityLevel, LevelSelection},
    draw::facade::*,
    game_update::UpdatePanel,
    hud::label,
    platform::{
        input::{KeyCode, MouseButton},
        runtime::{mouse_position, next_frame, set_cursor_grab, show_mouse},
    },
    session::FocusInput,
};

pub(crate) async fn choose(
    args: &[String],
    executable: &Path,
    updater: &mut UpdatePanel,
    app_edge: Option<&vector_range::high_app_edge_input::Options>,
) -> Result<(LevelSelection, Option<CityLevel>), String> {
    let mut selected =
        LevelSelection::from_options(args, std::env::var("RUST_DUTY_LEVEL").ok().as_deref())?;
    let menu_capture = args.iter().any(|a| a == "--capture-level-menu");
    let mut frames = 0;
    let scripted = vector_range::high_app_edge_input::starts_without_level_menu(args, app_edge);
    if scripted {
        return load(selected, executable);
    }
    set_cursor_grab(false);
    show_mouse(true);
    let mut input = FocusInput::new();
    let mut error = String::new();
    loop {
        frames += 1;
        let focus = input.sample();
        let enabled = !focus.unfocused
            && !focus.changed
            && !updater.startup_blocked()
            && !updater.consumes_pointer(true);
        if input.is_key_pressed(KeyCode::F10) {
            std::process::exit(0);
        }
        updater.set_pointer_input(
            input.is_mouse_button_pressed(MouseButton::Left),
            input.is_mouse_button_down(MouseButton::Left),
        );
        let w = screen_width();
        let h = screen_height();
        let x = (w - 620.).max(24.) * 0.5;
        let width = (w - 48.).min(620.);
        let top = (h * 0.5 - 140.).max(100.);
        let cards = [
            Rect::new(x, top, width, 90.),
            Rect::new(x, top + 104., width, 90.),
        ];
        let start = Rect::new(x, top + 222., width, 48.);
        let mouse = Vec2::from(mouse_position());
        let click = enabled && input.is_mouse_button_pressed(MouseButton::Left);
        if enabled
            && (input.is_key_pressed(KeyCode::Up)
                || input.is_key_pressed(KeyCode::Down)
                || input.is_key_pressed(KeyCode::Tab))
        {
            selected = if selected == LevelSelection::Range {
                LevelSelection::CedarJunction
            } else {
                LevelSelection::Range
            };
        }
        for (i, rect) in cards.iter().enumerate() {
            if click && rect.contains(mouse) {
                selected = if i == 0 {
                    LevelSelection::Range
                } else {
                    LevelSelection::CedarJunction
                };
                error.clear();
            }
        }
        set_default_camera();
        clear_background(Color::new(0.055, 0.075, 0.085, 1.));
        label("RUST DUTY", x, top - 52., 34., WHITE);
        label(
            "Choose a level",
            x,
            top - 20.,
            20.,
            Color::new(0.65, 0.74, 0.76, 1.),
        );
        for (i, (name, description)) in [
            (
                "Test Range",
                "Movement, weapons, targets and traversal fixtures",
            ),
            (
                "Cedar Junction",
                "City streets, shops and multi-story interiors",
            ),
        ]
        .iter()
        .enumerate()
        {
            let rect = cards[i];
            let current = (i == 0) == (selected == LevelSelection::Range);
            draw_rectangle(
                rect.x,
                rect.y,
                rect.w,
                rect.h,
                if current {
                    Color::new(0.18, 0.25, 0.27, 1.)
                } else {
                    Color::new(0.10, 0.14, 0.16, 1.)
                },
            );
            draw_rectangle_lines(
                rect.x,
                rect.y,
                rect.w,
                rect.h,
                2.,
                if current {
                    Color::new(0.95, 0.67, 0.33, 1.)
                } else {
                    Color::new(0.23, 0.30, 0.32, 1.)
                },
            );
            label(name, rect.x + 18., rect.y + 33., 24., WHITE);
            label(
                description,
                rect.x + 18.,
                rect.y + 62.,
                16.,
                Color::new(0.70, 0.78, 0.80, 1.),
            );
        }
        draw_rectangle(
            start.x,
            start.y,
            start.w,
            start.h,
            Color::new(0.80, 0.51, 0.22, 1.),
        );
        label(
            "Spawn in selected level",
            start.x + 18.,
            start.y + 31.,
            21.,
            WHITE,
        );
        label(
            "Up / Down to choose  ·  Enter to spawn  ·  F10 to quit",
            x,
            top + 300.,
            15.,
            Color::new(0.65, 0.74, 0.76, 1.),
        );
        if !error.is_empty() {
            label(&error, x, top + 330., 15., Color::new(1., 0.55, 0.4, 1.));
        }
        let confirm =
            enabled && (input.is_key_pressed(KeyCode::Enter) || (click && start.contains(mouse)));
        if confirm {
            label("Loading level and lighting…", x, top + 360., 18., WHITE);
            next_frame().await?;
            match load(selected, executable) {
                Ok(level) => return Ok(level),
                Err(e) => {
                    eprintln!("{e}");
                    error = "Could not load this level. Retry or select Test Range.".into();
                }
            }
        }
        if menu_capture && frames == 3 {
            let output = args
                .iter()
                .find_map(|a| a.strip_prefix("--output="))
                .unwrap_or("level-menu.png");
            capture_png(None, output);
            next_frame().await?;
            std::process::exit(0);
        }
        if updater.draw(true) {
            std::process::exit(0);
        }
        next_frame().await?;
    }
}
fn load(
    selected: LevelSelection,
    executable: &Path,
) -> Result<(LevelSelection, Option<CityLevel>), String> {
    Ok((
        selected,
        match selected {
            LevelSelection::Range => None,
            LevelSelection::CedarJunction => {
                Some(CityLevel::load(&CityLevel::resolve(executable))?)
            }
        },
    ))
}
