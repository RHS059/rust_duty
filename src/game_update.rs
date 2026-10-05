//! In-game presentation of the background GitHub update worker.
//! Input is consumed before the pause controller so a button cannot resume play.
use rust_duty_launcher::game::{GameUpdater, UpdateAction, UpdatePhase, UpdateSnapshot};
use vector_range::draw::facade::*;
use vector_range::platform::runtime::{get_time, mouse_position, screen_height, screen_width};
use vector_range::ui_theme::{self, flow_y, FlowBand, UiClass, UiScope, UiStyle};

fn update_style(class: UiClass) -> UiStyle {
    ui_theme::style(UiScope::UpdaterPanel, &[UiClass::Label, class])
}

/// Presentation-only flow. These exact rectangles also own pointer capture.
struct UpdateLayout {
    area: Rect,
    width: f32,
    scale: f32,
    bands: [FlowBand; 5],
}
impl UpdateLayout {
    fn new(width: f32, height: f32, startup: bool) -> Self {
        let content_width = (width - 32.).clamp(280., 600.);
        let bands = [
            FlowBand::new(
                4.,
                32.,
                &[
                    (update_style(UiClass::Accent), 24.),
                    (update_style(UiClass::Warning), 24.),
                ],
            ),
            FlowBand::new(
                37.,
                57.,
                &[
                    (update_style(UiClass::Label), 16.),
                    (update_style(UiClass::Warning), 16.),
                ],
            ),
            FlowBand::new(63., 82., &[(update_style(UiClass::Muted), 15.)]),
            FlowBand::new(110., 141., &[(update_style(UiClass::Button), 17.)]),
            FlowBand::new(161., 197., &[(update_style(UiClass::Button), 19.)]),
        ];
        let content_height = flow_y(if startup { 220. } else { 150. }, &bands);
        let scale = ((height - 32.).max(1.) / content_height).min(1.);
        let panel_width = content_width * scale;
        let panel_height = content_height * scale;
        let area = if startup {
            Rect::new(
                (width - panel_width) / 2.,
                (height - panel_height) / 2.,
                panel_width,
                panel_height,
            )
        } else {
            Rect::new(18., 18., panel_width, panel_height)
        };
        Self {
            area,
            width: content_width,
            scale,
            bands,
        }
    }
    fn point(&self, x: f32, y: f32) -> Vec2 {
        vec2(
            self.area.x + x * self.scale,
            self.area.y + flow_y(y, &self.bands) * self.scale,
        )
    }
    fn rect(&self, rect: Rect) -> Rect {
        let point = self.point(rect.x, rect.y);
        Rect::new(
            point.x,
            point.y,
            rect.w * self.scale,
            (flow_y(rect.y + rect.h, &self.bands) - flow_y(rect.y, &self.bands)) * self.scale,
        )
    }
    fn action_button(&self, index: usize) -> Rect {
        let width = ((self.width - 36.) / 2.).min(190.);
        self.rect(Rect::new(
            12. + index as f32 * (width + 12.),
            110.,
            width,
            31.,
        ))
    }
    fn retry_button(&self) -> Rect {
        self.rect(Rect::new(12., 110., 190., 31.))
    }
    fn continue_button(&self) -> Rect {
        self.rect(Rect::new(12., 161., self.width - 24., 36.))
    }
    fn text(&self, class: UiClass, value: &str, point: Vec2, size: f32, color: Color, width: f32) {
        let style = update_style(class);
        let text = if style.font_size.is_some() {
            style.fit_text(value, size, width)
        } else {
            value.to_owned()
        };
        let point = self.point(point.x, point.y);
        style.text_scaled(&text, point.x, point.y, size, color, self.scale);
    }
    fn button(&self, button: Rect, label: &str, size: f32, inset: Vec2, background: Color) {
        let style = ui_theme::style(UiScope::UpdaterPanel, &[UiClass::Button]);
        style.rect(button, background, GOLD, self.scale);
        let style = update_style(UiClass::Button);
        let text = if style.font_size.is_some() {
            style.fit_text(label, size, button.w / self.scale - 2. * inset.x)
        } else {
            label.to_owned()
        };
        // Keep the legacy baseline in an unstyled row, proportional within a grown row.
        let default_height = if size == 19. { 36. } else { 31. };
        style.text_scaled(
            &text,
            button.x + inset.x * self.scale,
            button.y + button.h * inset.y / default_height,
            size,
            WHITE,
            self.scale,
        );
    }
}

pub struct UpdatePanel {
    updater: Option<GameUpdater>,
    error: Option<String>,
    pointer_captured: PointerCapture,
    pointer_pressed: bool,
    pointer_down: bool,
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
                pointer_pressed: false,
                pointer_down: false,
                restart_requested: false,
                startup: StartupGate { resolved: !enabled },
                snapshot: None,
            };
        }
        match GameUpdater::start(vector_range::BUILD_VERSION) {
            Ok(updater) => Self {
                updater: Some(updater),
                error: None,
                pointer_captured: PointerCapture::default(),
                pointer_pressed: false,
                pointer_down: false,
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
                pointer_pressed: false,
                pointer_down: false,
                restart_requested: false,
                startup: StartupGate { resolved: !enabled },
                snapshot: None,
            },
        }
    }

    fn layout(&self) -> UpdateLayout {
        UpdateLayout::new(screen_width(), screen_height(), self.startup.blocked())
    }

    fn area(&self) -> Rect {
        self.layout().area
    }

    /// Poll before session input. Success can unlock the menu, never active play.
    pub fn startup_blocked(&mut self) -> bool {
        self.snapshot = self.updater.as_mut().map(GameUpdater::snapshot);
        if self.error.is_none() {
            self.startup
                .observe(self.snapshot.as_ref().map(|s| s.phase));
        }
        self.startup.blocked()
    }

    fn retry_worker(&mut self) {
        self.updater.take();
        self.snapshot = None;
        match GameUpdater::start(vector_range::BUILD_VERSION) {
            Ok(updater) => {
                self.updater = Some(updater);
                self.error = None;
            }
            Err(error) => self.error = Some(error.to_string()),
        }
    }

    /// The same focus-sanitized input as gameplay; refocus cannot click a button.
    pub fn set_pointer_input(&mut self, pressed: bool, down: bool) {
        self.pointer_pressed = pressed;
        self.pointer_down = down;
        if !pressed && !down {
            self.pointer_captured.0 = false;
        }
    }

    pub fn consumes_pointer(&mut self, menu: bool) -> bool {
        let down = self.pointer_down;
        let pressed = self.pointer_pressed;
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
        let layout = self.layout();
        let area = layout.area;
        let message = self
            .error
            .as_deref()
            .unwrap_or_else(|| snapshot.as_ref().map_or("", |s| s.message.as_str()));
        if !menu {
            if snapshot.as_ref().is_some_and(|s| s.ready) {
                update_style(UiClass::Accent).text(
                    "Update ready - Esc for restart",
                    20.,
                    26.,
                    19.,
                    GOLD,
                );
            }
            return false;
        }
        ui_theme::style(UiScope::UpdaterPanel, &[UiClass::Panel]).rect(
            area,
            Color::new(0.025, 0.043, 0.058, 0.98),
            GOLD,
            layout.scale,
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
        let message_class = if self.error.is_some() {
            UiClass::Warning
        } else {
            UiClass::Label
        };
        layout.text(
            if self.error.is_some() {
                UiClass::Warning
            } else {
                UiClass::Accent
            },
            title,
            vec2(16., 28.),
            24.,
            GOLD,
            layout.width - 32.,
        );
        let message =
            if message.contains("network stalled") || message.contains("error sending request") {
                "Can't reach GitHub. Retry, or play this version."
            } else {
                message
            };
        // Measure and draw the same resolved font; long paths cannot spill out.
        let message = update_style(message_class).fit_text(message, 16., layout.width - 32.);
        layout.text(
            message_class,
            &message,
            vec2(16., 53.),
            16.,
            WHITE,
            layout.width - 32.,
        );
        if let Some(state) = snapshot {
            if state.total > 0 {
                layout.text(
                    UiClass::Muted,
                    &format!(
                        "{:.1} / {:.1} MiB",
                        state.bytes as f64 / 1_048_576.,
                        state.total as f64 / 1_048_576.
                    ),
                    vec2(layout.width - 170., 78.),
                    15.,
                    LIGHTGRAY,
                    154.,
                );
            }
            let progress = if state.total > 0 {
                (state.bytes as f32 / state.total as f32).clamp(0., 1.)
            } else {
                0.
            };
            let track_style = ui_theme::style(UiScope::UpdaterPanel, &[UiClass::Slider]);
            track_style.rect(
                layout.rect(Rect::new(12., 88., layout.width - 24., 10.)),
                DARKGRAY,
                GOLD,
                layout.scale,
            );
            let bar = layout.rect(Rect::new(12., 88., (layout.width - 24.) * progress, 10.));
            draw_rectangle(
                bar.x,
                bar.y,
                bar.w,
                bar.h,
                ui_theme::style(UiScope::UpdaterPanel, &[UiClass::Accent]).tint(GOLD),
            );
            if state.total == 0 && (state.running || self.restart_requested) {
                let track = layout.width - 24.;
                let segment = track * 0.22;
                let offset = ((get_time() * 1.4).sin() as f32 + 1.) * 0.5 * (track - segment);
                let bar = layout.rect(Rect::new(12. + offset, 88., segment, 10.));
                draw_rectangle(
                    bar.x,
                    bar.y,
                    bar.w,
                    bar.h,
                    ui_theme::style(UiScope::UpdaterPanel, &[UiClass::Accent]).tint(GOLD),
                );
            }
            let actions = if self.restart_requested {
                vec![("Cancel restart", UpdateAction::Cancel)]
            } else {
                actions(&state)
            };
            for (i, (label, action)) in actions.into_iter().enumerate() {
                let button = layout.action_button(i);
                let hovered = button.contains(mouse_position().into());
                layout.button(
                    button,
                    label,
                    17.,
                    vec2(10., 21.),
                    if hovered {
                        Color::new(0.23, 0.29, 0.32, 1.)
                    } else {
                        Color::new(0.12, 0.18, 0.22, 1.)
                    },
                );
                if hovered && self.pointer_pressed {
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
            let button = layout.retry_button();
            let hovered = button.contains(mouse_position().into());
            layout.button(button, "Retry update check", 17., vec2(10., 21.), DARKGRAY);
            if hovered && self.pointer_pressed {
                self.retry_worker();
            }
        }
        if startup && !self.restart_requested {
            let button = layout.continue_button();
            let hovered = button.contains(mouse_position().into());
            layout.button(
                button,
                "Play current version",
                19.,
                vec2(12., 24.),
                if hovered {
                    DARKGRAY
                } else {
                    Color::new(0.12, 0.18, 0.22, 1.)
                },
            );
            if hovered && self.pointer_pressed {
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
        for phase in [
            None,
            Some(UpdatePhase::Checking),
            Some(UpdatePhase::Paused),
            Some(UpdatePhase::Cancelled),
            Some(UpdatePhase::Ready),
            Some(UpdatePhase::Restarting),
            Some(UpdatePhase::Unavailable),
        ] {
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
            SessionInput {
                esc_pressed: true,
                esc_down: true,
                ..Default::default()
            },
            SessionInput {
                enter_pressed: true,
                enter_down: true,
                ..Default::default()
            },
            SessionInput {
                click_pressed: true,
                click_down: true,
                ..Default::default()
            },
        ] {
            let mut gate = StartupGate::default();
            let mut session = SessionController::default();
            for phase in [
                UpdatePhase::Checking,
                UpdatePhase::Paused,
                UpdatePhase::Ready,
                UpdatePhase::Restarting,
                UpdatePhase::Unavailable,
            ] {
                gate.observe(Some(phase));
                let transition = session.step(SessionInput {
                    blocked: gate.blocked(),
                    dt: 0.016,
                    ..held
                });
                assert!(!transition.active);
                assert!(transition.discard_timing);
            }
            gate.continue_current();
            assert!(
                !session
                    .step(SessionInput {
                        blocked: gate.blocked(),
                        dt: 0.016,
                        ..held
                    })
                    .active
            );
            session.step(SessionInput {
                dt: 0.016,
                ..Default::default()
            });
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
    struct ThemeReset;
    impl Drop for ThemeReset {
        fn drop(&mut self) {
            vector_range::ui_theme::set_theme(vector_range::ui_theme::UiTheme::default());
        }
    }
    #[test]
    fn default_updater_layout_keeps_panel_and_button_geometry() {
        use super::*;
        let _reset = ThemeReset;
        ui_theme::set_theme(ui_theme::UiTheme::default());
        let startup = UpdateLayout::new(1000., 800., true);
        assert_eq!(startup.area, Rect::new(200., 290., 600., 220.));
        assert_eq!(startup.action_button(0), Rect::new(212., 400., 190., 31.));
        assert_eq!(startup.continue_button(), Rect::new(212., 451., 576., 36.));
        let regular = UpdateLayout::new(1000., 800., false);
        assert_eq!(regular.area, Rect::new(18., 18., 600., 150.));
    }
    #[test]
    fn styled_updater_buttons_are_inside_capture_area_and_match_painted_bounds() {
        use super::*;
        use vector_range::draw::Command;
        let _reset = ThemeReset;
        ui_theme::set_theme(ui_theme::UiTheme::parse("test.css",
            "#updater-panel .button {font-size:48px; background-color:#123456; border-width:8px}").unwrap());
        let layout = UpdateLayout::new(1000., 800., true);
        let button = layout.continue_button();
        let first = layout.action_button(0);
        assert!(first.y + first.h < button.y);
        assert!(layout.area.contains(vec2(button.x, button.y)));
        assert!(layout
            .area
            .contains(vec2(button.x + button.w, button.y + button.h)));
        begin_frame(1000, 800, 1.).unwrap();
        layout.button(button, "Play current version", 19., vec2(12., 24.), WHITE);
        let list = take_draw_list().unwrap();
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Rect {rect, color} if *rect == button && *color == Color::new(18./255., 52./255., 86./255., 1.))));
        let inside = vec2(button.x + 1., button.y + button.h - 0.1);
        assert!(button.contains(inside));
        let mut capture = PointerCapture::default();
        assert!(capture.step(true, true, layout.area.contains(inside), true, true));
        assert!(capture.step(true, true, false, false, true));
        assert!(!capture.step(true, true, false, false, false));
    }
}
