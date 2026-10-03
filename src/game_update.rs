//! In-game presentation of the background GitHub update worker.
//! Input is consumed before the pause controller so a button cannot resume play.
use macroquad::prelude::*;
use rust_duty_launcher::game::{GameUpdater, UpdateAction, UpdatePhase, UpdateSnapshot};

pub struct UpdatePanel {
    updater: Option<GameUpdater>,
    error: Option<String>,
    pointer_captured: PointerCapture,
    restart_requested: bool,
    startup: StartupGate,
    snapshot: Option<UpdateSnapshot>,
}

/// The world unlocks only on a confirmed check or an explicit player choice.
/// Paused, cancelled, offline and failed checks are never labeled successful.
#[derive(Default)]
struct StartupGate {
    resolved: bool,
}
impl StartupGate {
    fn observe(&mut self, phase: Option<UpdatePhase>) {
        if phase == Some(UpdatePhase::Current) {
            self.resolved = true;
        }
    }

    fn blocked(&self) -> bool {
        !self.resolved
    }

    fn continue_current(&mut self) {
        self.resolved = true;
    }
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
                startup: StartupGate { resolved: !enabled },
                snapshot: None,
            };
        }
        match GameUpdater::start(env!("CARGO_PKG_VERSION")) {
            Ok(updater) => Self {
                updater: Some(updater),
                error: None,
                pointer_captured: PointerCapture::default(),
                restart_requested: false,
                startup: StartupGate { resolved: !enabled },
                snapshot: Some(UpdateSnapshot {
                    message: "Checking for updates…".into(),
                    running: true,
                    ..Default::default()
                }),
            },
            Err(error) => Self {
                updater: None,
                error: Some(error.to_string()),
                pointer_captured: PointerCapture::default(),
                restart_requested: false,
                startup: StartupGate { resolved: !enabled },
                snapshot: None,
            },
        }
    }

    fn area(&self) -> Rect {
        let width = (screen_width() - 32.).clamp(280., 600.);
        if self.startup.blocked() {
            Rect::new((screen_width() - width) / 2., (screen_height() - 220.) / 2., width, 220.)
        } else {
            Rect::new(18., 18., width, 150.)
        }
    }

    /// Poll before session input. Success can unlock the menu, never active play.
    pub fn startup_blocked(&mut self) -> bool {
        self.snapshot = self.updater.as_mut().map(GameUpdater::snapshot);
        if self.error.is_none() {
            self.startup.observe(self.snapshot.as_ref().map(|s| s.phase));
        }
        self.startup.blocked()
    }

    fn retry_worker(&mut self) {
        self.updater.take();
        self.snapshot = None;
        match GameUpdater::start(env!("CARGO_PKG_VERSION")) {
            Ok(updater) => { self.updater = Some(updater); self.error = None; }
            Err(error) => self.error = Some(error.to_string()),
        }
    }

    pub fn consumes_pointer(&mut self, menu: bool) -> bool {
        let down = is_mouse_button_down(MouseButton::Left);
        let pressed = is_mouse_button_pressed(MouseButton::Left);
        self.pointer_captured.step(
            menu,
            self.updater.is_some() || self.error.is_some(),
            self.area().contains(mouse_position().into()),
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
        let snapshot = self.snapshot.clone();
        if snapshot.is_none() && self.error.is_none() {
            return false;
        }
        let startup = self.startup.blocked();
        if startup {
            clear_background(Color::new(0.015, 0.025, 0.036, 1.));
        }
        let area = self.area();
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
        let title = if self.restart_requested {
            "Preparing restart"
        } else if self.error.is_some() {
            "Update unavailable"
        } else {
            match snapshot.as_ref().map(|s| s.phase) {
                Some(UpdatePhase::Ready) => "Update ready to install",
                Some(UpdatePhase::Current) => "Game is up to date",
                Some(UpdatePhase::Paused) => "Update paused",
                Some(UpdatePhase::Cancelled) => "Update cancelled",
                Some(UpdatePhase::Unavailable) => "Update unavailable",
                _ if snapshot.as_ref().is_some_and(|s| s.total > 0) => "Downloading update",
                _ => "Checking for updates",
            }
        };
        draw_text(title, area.x + 16., area.y + 28., 24., GOLD);
        let message =
            if message.contains("network stalled") || message.contains("error sending request") {
                "Can't reach GitHub. Retry, or play this version."
            } else {
                message
            };
        // Fit the status to this window without letting paths spill off-screen.
        let mut text = message.to_owned();
        while measure_text(&text, None, 16, 1.).width > area.w - 32. {
            if text.pop().is_none() { break; }
        }
        draw_text(&text, area.x + 16., area.y + 53., 16., WHITE);
        if let Some(state) = snapshot {
            if state.total > 0 {
                draw_text(
                    &format!(
                        "{:.1} / {:.1} MiB",
                        state.bytes as f64 / 1_048_576.,
                        state.total as f64 / 1_048_576.
                    ),
                    area.x + area.w - 170.,
                    area.y + 78.,
                    15.,
                    LIGHTGRAY,
                );
            }
            let progress = if state.total > 0 {
                (state.bytes as f32 / state.total as f32).clamp(0., 1.)
            } else {
                0.
            };
            draw_rectangle(area.x + 12., area.y + 88., area.w - 24., 10., DARKGRAY);
            draw_rectangle(
                area.x + 12.,
                area.y + 88.,
                (area.w - 24.) * progress,
                10.,
                GOLD,
            );
            if state.total == 0 && (state.running || self.restart_requested) {
                let track = area.w - 24.;
                let segment = track * 0.22;
                let offset = ((get_time() * 1.4).sin() as f32 + 1.) * 0.5 * (track - segment);
                draw_rectangle(area.x + 12. + offset, area.y + 88., segment, 10., GOLD);
            }
            let actions = if self.restart_requested {
                vec![("Cancel restart", UpdateAction::Cancel)]
            } else {
                actions(&state)
            };
            for (i, (label, action)) in actions.into_iter().enumerate() {
                let width = ((area.w - 36.) / 2.).min(190.);
                let button = Rect::new(area.x + 12. + i as f32 * (width + 12.), area.y + 110., width, 31.);
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
                            Err(error) => {
                                self.error = Some(error.to_string());
                                if action == UpdateAction::Restart {
                                    self.restart_requested = false;
                                }
                                if action == UpdateAction::Resume {
                                    self.retry_worker();
                                }
                            }
                        }
                    }
                }
            }
        }
        if self.updater.is_none() {
            let button = Rect::new(area.x + 12., area.y + 110., 190., 31.);
            let hovered = button.contains(mouse_position().into());
            draw_rectangle(button.x, button.y, button.w, button.h, DARKGRAY);
            draw_text("Retry update check", button.x + 10., button.y + 21., 17., WHITE);
            if hovered && is_mouse_button_pressed(MouseButton::Left) {
                self.retry_worker();
            }
        }
        if startup && !self.restart_requested {
            let button = Rect::new(area.x + 12., area.y + 161., area.w - 24., 36.);
            let hovered = button.contains(mouse_position().into());
            draw_rectangle(button.x, button.y, button.w, button.h, if hovered { DARKGRAY } else { Color::new(0.12, 0.18, 0.22, 1.) });
            draw_text("Play current version", button.x + 12., button.y + 24., 19., WHITE);
            if hovered && is_mouse_button_pressed(MouseButton::Left) {
                // Stop pending startup work, but never claim it was installed/current.
                // Cancellation failure must not strand an offline player at startup.
                if let Some(updater) = self.updater.as_mut() {
                    if let Err(error) = updater.action(UpdateAction::Cancel) {
                        self.error = Some(error.to_string());
                    }
                }
                self.startup.continue_current();
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
    use super::{PointerCapture, StartupGate, UpdatePhase};
    use vector_range::session::{SessionController, SessionInput};

    #[test]
    fn only_confirmed_current_automatically_resolves_startup() {
        for phase in [None, Some(UpdatePhase::Checking), Some(UpdatePhase::Paused),
            Some(UpdatePhase::Cancelled), Some(UpdatePhase::Ready),
            Some(UpdatePhase::Restarting), Some(UpdatePhase::Unavailable)] {
            let mut gate = StartupGate::default();
            gate.observe(phase);
            assert!(gate.blocked(), "{phase:?} must not be treated as success");
        }
        let mut gate = StartupGate::default();
        gate.observe(Some(UpdatePhase::Current));
        assert!(!gate.blocked());
        gate.observe(Some(UpdatePhase::Checking));
        assert!(!gate.blocked(), "later menu checks do not repeat startup");
    }

    #[test]
    fn explicit_offline_choice_is_recoverable_without_claiming_success() {
        let mut gate = StartupGate::default();
        gate.observe(Some(UpdatePhase::Unavailable));
        assert!(gate.blocked());
        gate.continue_current();
        assert!(!gate.blocked());
    }

    #[test]
    fn all_resume_inputs_are_consumed_across_the_startup_boundary() {
        for held in [
            SessionInput { esc_pressed: true, esc_down: true, ..Default::default() },
            SessionInput { enter_pressed: true, enter_down: true, ..Default::default() },
            SessionInput { click_pressed: true, click_down: true, ..Default::default() },
        ] {
            let mut gate = StartupGate::default();
            let mut session = SessionController::default();
            for phase in [UpdatePhase::Checking, UpdatePhase::Paused, UpdatePhase::Ready,
                UpdatePhase::Restarting, UpdatePhase::Unavailable] {
                gate.observe(Some(phase));
                let transition = session.step(SessionInput { blocked: gate.blocked(), dt: 0.016, ..held });
                assert!(!transition.active);
                assert!(transition.discard_timing);
            }
            gate.continue_current();
            assert!(!session.step(SessionInput { blocked: gate.blocked(), dt: 0.016, ..held }).active);
            session.step(SessionInput { dt: 0.016, ..Default::default() });
            assert!(session.step(SessionInput { dt: 0.016, ..held }).resumed);
        }
    }

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
