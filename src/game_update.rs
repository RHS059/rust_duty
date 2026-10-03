//! In-game presentation of the background GitHub update worker.
//! Input is consumed before the pause controller so a button cannot resume play.
use macroquad::prelude::*;
use rust_duty_launcher::game::{GameUpdater, UpdateAction, UpdateSnapshot};

pub struct UpdatePanel {
    updater: Option<GameUpdater>,
    error: Option<String>,
    pointer_captured: PointerCapture,
    restart_requested: bool,
}

#[derive(Default)]
struct PointerCapture(bool);
impl PointerCapture {
    fn step(
        &mut self,
        menu: bool,
        visible: bool,
        hovered: bool,
        pressed: bool,
        down: bool,
    ) -> bool {
        if !down && !pressed {
            self.0 = false;
        }
        if menu && visible && hovered && (pressed || down) {
            self.0 = true;
        }
        self.0
    }
}

impl UpdatePanel {
    pub fn start(enabled: bool) -> Self {
        if !enabled {
            return Self {
                updater: None,
                error: None,
                pointer_captured: PointerCapture::default(),
                restart_requested: false,
            };
        }
        match GameUpdater::start(env!("CARGO_PKG_VERSION")) {
            Ok(updater) => Self {
                updater: Some(updater),
                error: None,
                pointer_captured: PointerCapture::default(),
                restart_requested: false,
            },
            Err(error) => Self {
                updater: None,
                error: Some(error.to_string()),
                pointer_captured: PointerCapture::default(),
                restart_requested: false,
            },
        }
    }

    fn area() -> Rect {
        Rect::new(18., 18., (screen_width() - 36.).min(520.), 116.)
    }

    pub fn consumes_pointer(&mut self, menu: bool) -> bool {
        let down = is_mouse_button_down(MouseButton::Left);
        let pressed = is_mouse_button_pressed(MouseButton::Left);
        self.pointer_captured.step(
            menu,
            self.updater.is_some() || self.error.is_some(),
            Self::area().contains(mouse_position().into()),
            pressed,
            down,
        )
    }

    /// Returns true only after the replacement helper was successfully started.
    pub fn draw(&mut self, menu: bool) -> bool {
        if self.restart_requested {
            if let Some(updater) = self.updater.as_mut() {
                match updater.action(UpdateAction::Restart) {
                    Ok(true) => return true,
                    Ok(false) => (),
                    Err(error) => {
                        self.restart_requested = false;
                        self.error = Some(error.to_string());
                    }
                }
            }
        }
        let snapshot = self.updater.as_mut().map(GameUpdater::snapshot);
        if snapshot.is_none() && self.error.is_none() {
            return false;
        }
        let area = Self::area();
        let message = self
            .error
            .as_deref()
            .unwrap_or_else(|| snapshot.as_ref().map_or("", |s| s.message.as_str()));
        if !menu {
            if snapshot.as_ref().is_some_and(|s| s.ready) {
                draw_text("Update ready - Esc for restart", 20., 26., 19., GOLD);
            }
            return false;
        }
        draw_rectangle(
            area.x,
            area.y,
            area.w,
            area.h,
            Color::new(0.025, 0.043, 0.058, 0.98),
        );
        draw_text("GAME UPDATES", area.x + 12., area.y + 22., 19., GOLD);
        let message =
            if message.contains("network stalled") || message.contains("error sending request") {
                "Can't reach GitHub. Keep playing, or retry below."
            } else {
                message
            };
        let text: String = message.chars().take(66).collect();
        draw_text(&text, area.x + 12., area.y + 44., 15., WHITE);
        if let Some(state) = snapshot {
            if state.total > 0 {
                draw_text(
                    &format!(
                        "{:.1} / {:.1} MiB",
                        state.bytes as f64 / 1_048_576.,
                        state.total as f64 / 1_048_576.
                    ),
                    area.x + area.w - 170.,
                    area.y + 22.,
                    15.,
                    LIGHTGRAY,
                );
            }
            let progress = if state.total > 0 {
                (state.bytes as f32 / state.total as f32).clamp(0., 1.)
            } else {
                0.
            };
            draw_rectangle(area.x + 12., area.y + 53., area.w - 24., 4., DARKGRAY);
            draw_rectangle(
                area.x + 12.,
                area.y + 53.,
                (area.w - 24.) * progress,
                4.,
                GOLD,
            );
            let actions = if self.restart_requested {
                vec![("Cancel restart", UpdateAction::Cancel)]
            } else {
                actions(&state)
            };
            for (i, (label, action)) in actions.into_iter().enumerate() {
                let button = Rect::new(area.x + 12. + i as f32 * 160., area.y + 70., 148., 31.);
                let hovered = button.contains(mouse_position().into());
                draw_rectangle(
                    button.x,
                    button.y,
                    button.w,
                    button.h,
                    if hovered {
                        Color::new(0.23, 0.29, 0.32, 1.)
                    } else {
                        Color::new(0.12, 0.18, 0.22, 1.)
                    },
                );
                draw_text(label, button.x + 10., button.y + 21., 17., WHITE);
                if hovered && is_mouse_button_pressed(MouseButton::Left) {
                    if action == UpdateAction::Restart {
                        self.restart_requested = true;
                    }
                    if action == UpdateAction::Cancel {
                        self.restart_requested = false;
                    }
                    if let Some(updater) = self.updater.as_mut() {
                        match updater.action(action) {
                            Ok(restart) => {
                                self.error = None;
                                return restart;
                            }
                            Err(error) => self.error = Some(error.to_string()),
                        }
                    }
                }
            }
        }
        false
    }
}

fn actions(state: &UpdateSnapshot) -> Vec<(&'static str, UpdateAction)> {
    if state.ready {
        vec![
            ("Restart & apply", UpdateAction::Restart),
            ("Cancel", UpdateAction::Cancel),
        ]
    } else if state.running {
        vec![
            ("Pause", UpdateAction::Pause),
            ("Cancel", UpdateAction::Cancel),
        ]
    } else {
        vec![("Resume / check", UpdateAction::Resume)]
    }
}

#[cfg(test)]
mod tests {
    use super::PointerCapture;
    use vector_range::session::{SessionController, SessionInput};

    #[test]
    fn update_click_and_drag_cannot_resume_the_paused_game() {
        let mut capture = PointerCapture::default();
        let mut session = SessionController::default();
        for (hover, pressed, down) in [
            (true, true, true),
            (false, false, true),
            (false, false, false),
        ] {
            let consumed = capture.step(true, true, hover, pressed, down);
            let transition = session.step(SessionInput {
                click_pressed: pressed && !consumed,
                click_down: down && !consumed,
                dt: 1.0 / 60.0,
                ..Default::default()
            });
            assert!(!transition.active);
        }
        let consumed = capture.step(true, true, false, true, true);
        assert!(!consumed);
        assert!(
            session
                .step(SessionInput {
                    click_pressed: true,
                    click_down: true,
                    dt: 1.0 / 60.0,
                    ..Default::default()
                })
                .resumed
        );
    }

    #[test]
    fn hidden_update_panel_never_eats_gameplay_clicks() {
        let mut capture = PointerCapture::default();
        assert!(!capture.step(false, true, true, true, true));
        assert!(!capture.step(true, false, true, true, true));
    }
}
