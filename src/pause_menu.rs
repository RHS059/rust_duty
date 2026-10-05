//! Pause-only controls. Pointer gestures are consumed before resume input.
use vector_range::draw::facade::*;
use vector_range::platform::runtime::{screen_height, screen_width};
use vector_range::ui_theme::{self, flow_y, FlowBand, UiClass, UiScope, UiStyle};
use vector_range::{
    control::ControlMode,
    settings::{Settings, WalkTranslation},
};

const ACCENT: Color = Color::new(0.98, 0.62, 0.22, 1.);
const MUTED: Color = Color::new(0.62, 0.69, 0.72, 1.);
fn text_style(class: UiClass, color: Color) -> UiStyle {
    let tone = if color == ACCENT {
        UiClass::Accent
    } else if color == MUTED {
        UiClass::Muted
    } else {
        UiClass::Label
    };
    ui_theme::style(UiScope::PauseMenu, &[UiClass::Label, class, tone])
}

struct Layout {
    origin: Vec2,
    scale: f32,
    bands: Vec<FlowBand>,
    viewport: Vec2,
}
impl Layout {
    fn new(width: f32, height: f32) -> Self {
        let label = text_style(UiClass::Label, WHITE);
        let muted = text_style(UiClass::Label, MUTED);
        let accent = text_style(UiClass::Label, ACCENT);
        let warning = text_style(UiClass::Warning, MUTED);
        let button = text_style(UiClass::Button, WHITE);
        let button_accent = text_style(UiClass::Button, ACCENT);
        let button_muted = text_style(UiClass::Button, MUTED);
        let slider = text_style(UiClass::Slider, WHITE);
        let mut bands = vec![
            FlowBand::new(18., 80., &[(label, 34.), (muted, 16.)]),
            FlowBand::new(99., 144., &[(button_accent, 23.), (button_muted, 17.)]),
            FlowBand::new(155., 251., &[(muted, 17.)]),
            FlowBand::new(279., 325., &[(label, 18.)]),
            FlowBand::new(346., 366., &[(accent, 20.)]),
            FlowBand::new(497., 525., &[(button, 16.), (muted, 15.)]),
            FlowBand::new(525., 545., &[(accent, 20.)]),
            FlowBand::new(552., 567., &[(muted, 15.)]),
            FlowBand::new(720., 754., &[(button, 18.)]),
            FlowBand::new(771., 787., &[(muted, 16.), (warning, 16.)]),
            FlowBand::new(805., 821., &[(muted, 16.)]),
        ];
        for axis in 0..6 {
            let r = slider_rect(axis);
            bands.push(FlowBand::new(
                r.y,
                r.y + r.h,
                &[(slider, if axis < 3 { 18. } else { 15. })],
            ));
        }
        let content_height = flow_y(843., &bands);
        let scale = ((width - 24.) / 610.)
            .min((height - 24.) / content_height)
            .clamp(0.1 * 843. / content_height, 1.);
        Self {
            origin: vec2(
                (width - 610. * scale) * 0.5,
                (height - content_height * scale) * 0.5,
            ),
            scale,
            bands,
            viewport: vec2(width, height),
        }
    }
    fn point(&self, point: Vec2) -> Vec2 {
        self.origin + vec2(point.x, flow_y(point.y, &self.bands)) * self.scale
    }
    fn rect(&self, rect: Rect) -> Rect {
        let top = self.point(vec2(rect.x, rect.y));
        Rect::new(
            top.x,
            top.y,
            rect.w * self.scale,
            (flow_y(rect.y + rect.h, &self.bands) - flow_y(rect.y, &self.bands)) * self.scale,
        )
    }
    fn text(&self, class: UiClass, value: &str, point: Vec2, size: f32, color: Color, width: f32) {
        let style = text_style(class, color);
        let value = if style.font_size.is_some() {
            style.fit_text(value, size, width)
        } else {
            value.to_owned()
        };
        let point = self.point(point);
        style.text_scaled(&value, point.x, point.y, size, color, self.scale);
    }
}
const RESUME: Rect = Rect::new(32., 99., 546., 45.);
const POSITION_RESET: Rect = Rect::new(350., 497., 228., 28.);
const RESET: Rect = Rect::new(350., 720., 228., 34.);
const SAVE: Rect = Rect::new(32., 720., 260., 34.);
fn slider_rect(axis: usize) -> Rect {
    let y = if axis < 3 {
        578. + axis as f32 * 43.
    } else {
        381. + (axis - 3) as f32 * 43.
    };
    Rect::new(190., y, 292., 28.)
}

#[derive(Default)]
pub struct PauseMenu {
    dragging: Option<usize>,
    dirty: bool,
    focus: Option<usize>,
    persistence: Option<String>,
    save_failed: bool,
}
#[derive(Default)]
pub struct MenuKeys {
    pub next: bool,
    pub previous: bool,
    pub increase: bool,
    pub decrease: bool,
    pub minimum: bool,
    pub maximum: bool,
    pub activate: bool,
}
#[derive(Default, Debug)]
pub struct MenuAction {
    pub resume: bool,
    pub save: bool,
}
impl PauseMenu {
    pub fn has_keyboard_focus(&self) -> bool {
        self.focus.is_some()
    }
    pub fn save_result(&mut self, result: std::io::Result<()>) -> String {
        self.save_failed = result.is_err();
        let text = match result {
            Ok(()) => "Saved viewmodel and walking settings".into(),
            Err(error) => format!("Save failed; changes are unsaved. F5 retries: {error}"),
        };
        self.persistence = Some(text.clone());
        text
    }
    pub fn reloaded(&mut self) {
        self.save_failed = false;
        self.persistence = Some("Reloaded saved values; unsaved changes discarded".into());
    }
    pub fn changed(&mut self) {
        if !self.save_failed {
            self.persistence = Some("Unsaved changes. F5 saves the preset".into());
        }
    }
    fn status<'a>(&'a self, transient: Option<&'a str>) -> Option<&'a str> {
        self.persistence.as_deref().or(transient)
    }
    pub fn keyboard(
        &mut self,
        cfg: &mut Settings,
        weapon: &str,
        keys: MenuKeys,
        enabled: bool,
    ) -> MenuAction {
        if !enabled {
            self.focus = None;
            return MenuAction::default();
        }
        if keys.next {
            self.focus = Some(self.focus.map_or(0, |i| (i + 1) % 10));
        }
        if keys.previous {
            self.focus = Some(self.focus.map_or(9, |i| (i + 9) % 10));
        }
        let mut action = MenuAction::default();
        let Some(focus) = self.focus else {
            return action;
        };
        let axis = match focus {
            1..=3 => Some(focus + 2),
            5..=7 => Some(focus - 5),
            _ => None,
        };
        if let Some(axis) = axis {
            if keys.increase || keys.decrease || keys.minimum || keys.maximum {
                let delta = f32::from(u8::from(keys.increase)) - f32::from(u8::from(keys.decrease));
                let mut value = if axis < 3 {
                    cfg.walking_translation(weapon).0[axis]
                } else {
                    [cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z][axis - 3]
                        / Settings::VIEWMODEL_OFFSET_LIMIT
                };
                value = if keys.minimum {
                    -1.
                } else if keys.maximum {
                    1.
                } else {
                    value
                        + delta
                            * if axis < 3 {
                                0.05
                            } else {
                                Settings::VIEWMODEL_NUDGE / Settings::VIEWMODEL_OFFSET_LIMIT
                            }
                };
                if axis < 3 {
                    let mut values = cfg.walking_translation(weapon);
                    values.0[axis] = value;
                    cfg.set_walking_translation(weapon, values);
                } else {
                    let value = value * Settings::VIEWMODEL_OFFSET_LIMIT;
                    match axis {
                        3 => cfg.set_viewmodel(value, cfg.viewmodel_y),
                        4 => cfg.set_viewmodel(cfg.viewmodel_x, value),
                        _ => cfg.set_viewmodel_z(value),
                    }
                }
                self.changed();
                action.save = true;
            }
        } else if keys.activate {
            match focus {
                0 => action.resume = true,
                4 => {
                    cfg.reset_viewmodel();
                    action.save = true;
                }
                8 => {
                    cfg.set_walking_translation(weapon, WalkTranslation::default());
                    action.save = true;
                }
                9 => action.save = true,
                _ => {}
            }
        }
        action
    }
    /// `enabled` requires a paused, focused window with no update overlay.
    /// A drag is owned until release, including outside the panel.
    pub fn input(
        &mut self,
        cfg: &mut Settings,
        weapon: &str,
        size: Vec2,
        pointer: Vec2,
        buttons: (bool, bool),
        enabled: bool,
    ) -> MenuAction {
        let (pressed, down) = buttons;
        if !enabled {
            self.dragging = None;
            self.focus = None;
            return MenuAction {
                save: std::mem::take(&mut self.dirty),
                ..Default::default()
            };
        }
        let layout = Layout::new(size.x, size.y);
        let point = pointer;
        let mut action = MenuAction::default();
        if pressed && self.dragging.is_none() {
            if layout.rect(RESET).contains(point) {
                self.focus = Some(8);
                cfg.set_walking_translation(weapon, WalkTranslation::default());
                action.save = true;
            } else if layout.rect(POSITION_RESET).contains(point) {
                self.focus = Some(4);
                cfg.reset_viewmodel();
                action.save = true;
            } else if layout.rect(RESUME).contains(point) {
                self.focus = Some(0);
                action.resume = true;
            } else if layout.rect(SAVE).contains(point) {
                self.focus = Some(9);
                action.save = true;
            } else {
                self.dragging = (0..6).find(|axis| layout.rect(slider_rect(*axis)).contains(point));
                if let Some(axis) = self.dragging {
                    self.focus = Some(if axis < 3 { axis + 5 } else { axis - 2 });
                }
            }
        }
        if let Some(axis) = self.dragging {
            if down || pressed {
                let track = layout.rect(slider_rect(axis));
                let normalized = ((point.x - track.x) / track.w * 2. - 1.).clamp(-1., 1.);
                let normalized = if normalized < -0.999999 {
                    -1.
                } else if normalized > 0.999999 {
                    1.
                } else {
                    normalized
                };
                if axis < 3 {
                    let mut value = cfg.walking_translation(weapon);
                    value.0[axis] = normalized;
                    cfg.set_walking_translation(weapon, value);
                } else if axis == 3 {
                    cfg.set_viewmodel(
                        normalized * Settings::VIEWMODEL_OFFSET_LIMIT,
                        cfg.viewmodel_y,
                    );
                } else if axis == 4 {
                    cfg.set_viewmodel(
                        cfg.viewmodel_x,
                        normalized * Settings::VIEWMODEL_OFFSET_LIMIT,
                    );
                }
                if axis == 5 {
                    cfg.set_viewmodel_z(normalized * Settings::VIEWMODEL_OFFSET_LIMIT);
                }
                self.dirty = true;
                self.changed();
            } else {
                self.dragging = None;
                action.save = std::mem::take(&mut self.dirty);
            }
        }
        action
    }
    pub fn draw(
        &self,
        cfg: &Settings,
        weapon: &str,
        initial: bool,
        mode: ControlMode,
        status: Option<&str>,
    ) {
        self.draw_with_layout(
            cfg,
            weapon,
            initial,
            mode,
            status,
            Layout::new(screen_width(), screen_height()),
        );
    }
    fn draw_with_layout(
        &self,
        cfg: &Settings,
        weapon: &str,
        initial: bool,
        mode: ControlMode,
        status: Option<&str>,
        layout: Layout,
    ) {
        let ink = Color::new(0.035, 0.057, 0.074, 0.97);
        let accent = ACCENT;
        let muted = MUTED;
        let rect = |r: Rect, color: Color| {
            let r = layout.rect(r);
            draw_rectangle(r.x, r.y, r.w, r.h, color);
        };
        let text = |value: &str, x: f32, y: f32, size: f32, color: Color| {
            layout.text(UiClass::Label, value, vec2(x, y), size, color, 578. - x);
        };
        let button_text = |value: &str, x: f32, y: f32, size: f32, color: Color, width: f32| {
            layout.text(UiClass::Button, value, vec2(x, y), size, color, width);
        };
        let slider_text = |value: &str, x: f32, y: f32, size: f32, color: Color, width: f32| {
            layout.text(UiClass::Slider, value, vec2(x, y), size, color, width);
        };
        let button = |r: Rect| {
            ui_theme::style(UiScope::PauseMenu, &[UiClass::Button]).rect(
                layout.rect(r),
                Color::new(0.13, 0.21, 0.25, 1.),
                accent,
                layout.scale,
            );
        };
        draw_rectangle(
            0.,
            0.,
            layout.viewport.x,
            layout.viewport.y,
            Color::new(0.015, 0.025, 0.035, 0.80),
        );
        ui_theme::style(UiScope::PauseMenu, &[UiClass::Panel]).rect(
            layout.rect(Rect::new(0., 0., 610., 843.)),
            ink,
            accent,
            layout.scale,
        );
        rect(
            Rect::new(0., 0., 610., 3.),
            ui_theme::style(UiScope::PauseMenu, &[UiClass::Accent]).tint(accent),
        );
        text("VECTOR RANGE", 32., 52., 34., WHITE);
        text(vector_range::BUILD_LABEL, 33., 77., 16., muted);
        button(RESUME);
        button_text(
            if initial { "ENTER THE RANGE" } else { "RESUME" },
            48.,
            129.,
            23.,
            accent,
            374.,
        );
        button_text("Enter / Esc", 438., 127., 17., muted, 124.);
        let stance = if mode == ControlMode::Hold {
            "Hold ADS / crouch / prone"
        } else {
            "Toggle ADS / crouch / prone"
        };
        for (i, line) in [
            "WASD  Move     MOUSE  Look     LEFT CLICK  Fire",
            "RIGHT CLICK  ADS    SHIFT  Sprint    CTRL/C  Crouch",
            "SPACE  Jump    R  Reload    Z  Prone    M  Mute",
            stance,
        ]
        .iter()
        .enumerate()
        {
            text(line, 32., 179. + i as f32 * 24., 17., muted);
        }
        text(
            &format!("[ / ]  Sensitivity   {:.2} deg/pixel", cfg.sensitivity),
            32.,
            297.,
            18.,
            WHITE,
        );
        text(
            &format!("- / =  Horizontal FOV   {:.0} degrees", cfg.fov),
            32.,
            325.,
            18.,
            WHITE,
        );
        text("VIEWMODEL POSITION", 32., 366., 20., accent);
        for (axis, label, value) in [
            (3, "X  Left / right", cfg.viewmodel_x),
            (4, "Y  Up / down", cfg.viewmodel_y),
            (5, "Z  Depth", cfg.viewmodel_z),
        ] {
            let r = slider_rect(axis);
            slider_text(label, 32., r.y + 20., 18., WHITE, 146.);
            let style = ui_theme::style(UiScope::PauseMenu, &[UiClass::Slider]);
            // The track spans exactly the same x interval as pointer normalization.
            style.rect(
                layout.rect(Rect::new(r.x, r.y + 11., r.w, 5.)),
                Color::new(0.19, 0.28, 0.31, 1.),
                accent,
                layout.scale,
            );
            rect(
                Rect::new(r.x + r.w * 0.5 - 1., r.y + 5., 2., 18.),
                style.apply_opacity(muted),
            );
            let x = r.x + (value / Settings::VIEWMODEL_OFFSET_LIMIT + 1.) * 0.5 * r.w;
            rect(Rect::new(x - 5., r.y + 3., 10., 22.), style.tint(accent));
            slider_text(&format!("{value:+.3} m"), 501., r.y + 20., 15., WHITE, 77.);
        }
        text("Absolute placement: +/- 0.20 m", 32., 515., 15., muted);
        button(POSITION_RESET);
        button_text(
            "Reset position",
            POSITION_RESET.x + 15.,
            POSITION_RESET.y + 20.,
            16.,
            WHITE,
            POSITION_RESET.w - 30.,
        );
        text(
            &format!("WALKING MOTION  /  {weapon}"),
            32.,
            545.,
            20.,
            accent,
        );
        text(
            "Translation only.  -1 = none   0 = current   +1 = double",
            32.,
            567.,
            15.,
            muted,
        );
        let value = cfg.walking_translation(weapon);
        for (axis, label) in ["X  Sideways", "Y  Up / down", "Z  Depth"]
            .iter()
            .enumerate()
        {
            let r = slider_rect(axis);
            slider_text(label, 32., r.y + 20., 18., WHITE, 146.);
            let style = ui_theme::style(UiScope::PauseMenu, &[UiClass::Slider]);
            // The track spans exactly the same x interval as pointer normalization.
            style.rect(
                layout.rect(Rect::new(r.x, r.y + 11., r.w, 5.)),
                Color::new(0.19, 0.28, 0.31, 1.),
                accent,
                layout.scale,
            );
            rect(
                Rect::new(r.x + r.w * 0.5 - 1., r.y + 5., 2., 18.),
                style.apply_opacity(muted),
            );
            let x = r.x + (value.0[axis] + 1.) * 0.5 * r.w;
            rect(Rect::new(x - 5., r.y + 3., 10., 22.), style.tint(accent));
            slider_text(
                &format!("{:+.2}", value.0[axis]),
                507.,
                r.y + 20.,
                18.,
                WHITE,
                71.,
            );
        }
        button(RESET);
        button_text(
            "Reset walking",
            RESET.x + 15.,
            RESET.y + 23.,
            18.,
            WHITE,
            RESET.w - 30.,
        );
        button(SAVE);
        button_text(
            "Save / retry",
            SAVE.x + 15.,
            SAVE.y + 23.,
            18.,
            WHITE,
            SAVE.w - 30.,
        );
        if let Some(focus) = self.focus {
            let r = match focus {
                0 => RESUME,
                1..=3 => slider_rect(focus + 2),
                4 => POSITION_RESET,
                5..=7 => slider_rect(focus - 5),
                8 => RESET,
                _ => SAVE,
            };
            let r = layout.rect(r);
            draw_rectangle_lines(r.x - 3., r.y - 3., r.w + 6., r.h + 6., 2., accent);
        }
        let status = self.status(status);
        layout.text(
            if self.save_failed {
                UiClass::Warning
            } else {
                UiClass::Label
            },
            &status
                .unwrap_or("Adjustments save on release. Tab selects; arrows adjust.")
                .chars()
                .take(72)
                .collect::<String>(),
            vec2(32., 787.),
            16.,
            muted,
            546.,
        );
        text(
            "F5 Save   F6 Discard / reload   Enter activates   F10 Quit",
            32.,
            821.,
            16.,
            muted,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn keyboard_navigation_adjusts_one_axis_and_consumes_reset_activation() {
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        cfg.set_walking_translation("other", WalkTranslation([0.3, 0.4, 0.5]));
        for _ in 0..6 {
            menu.keyboard(
                &mut cfg,
                "rifle",
                MenuKeys {
                    next: true,
                    ..Default::default()
                },
                true,
            );
        }
        let action = menu.keyboard(
            &mut cfg,
            "rifle",
            MenuKeys {
                increase: true,
                ..Default::default()
            },
            true,
        );
        assert!(action.save && !action.resume);
        assert_eq!(cfg.walking_translation("rifle").0, [0.05, 0., 0.]);
        assert_eq!(
            [cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z],
            [0., 0., 0.]
        );
        for _ in 0..3 {
            menu.keyboard(
                &mut cfg,
                "rifle",
                MenuKeys {
                    next: true,
                    ..Default::default()
                },
                true,
            );
        }
        let action = menu.keyboard(
            &mut cfg,
            "rifle",
            MenuKeys {
                activate: true,
                ..Default::default()
            },
            true,
        );
        assert!(action.save && !action.resume);
        assert_eq!(cfg.walking_translation("rifle"), WalkTranslation::default());
        assert_eq!(cfg.walking_translation("other").0, [0.3, 0.4, 0.5]);
        menu.keyboard(&mut cfg, "rifle", MenuKeys::default(), false);
        assert!(!menu.has_keyboard_focus());
    }
    #[test]
    fn failed_save_survives_time_independent_menu_changes_until_saved_or_discarded() {
        let mut menu = PauseMenu::default();
        let text = menu.save_result(Err(std::io::Error::other("read only destination")));
        assert!(text.contains("unsaved"));
        assert!(menu.save_failed);
        menu.changed();
        let mut cfg = Settings::default();
        menu.keyboard(&mut cfg, "rifle", MenuKeys::default(), false);
        assert_eq!(menu.persistence.as_deref(), Some(text.as_str()));
        assert!(menu.save_failed);
        menu.save_result(Ok(()));
        assert!(!menu.save_failed);
        menu.changed();
        assert!(menu.persistence.as_ref().unwrap().contains("Unsaved"));
        menu.reloaded();
        assert!(menu.persistence.as_ref().unwrap().contains("discarded"));
    }
    #[test]
    fn new_edit_overrides_unexpired_success_notice_immediately() {
        let mut menu = PauseMenu::default();
        let saved = menu.save_result(Ok(()));
        menu.changed();
        assert!(menu.status(Some(&saved)).unwrap().starts_with("Unsaved"));
        assert!(menu.status(None).unwrap().starts_with("Unsaved"));
    }
    fn point(x: f32, y: f32) -> Vec2 {
        {
            let layout = Layout::new(1000., 800.);
            layout.point(vec2(x, y))
        }
    }
    #[test]
    fn sliders_consume_drag_and_save_once_without_resuming() {
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        let size = vec2(1000., 800.);
        for axis in 0..3 {
            let r = slider_rect(axis);
            let a = menu.input(
                &mut cfg,
                "hk416a5",
                size,
                point(r.x, r.y + 10.),
                (true, true),
                true,
            );
            assert!(!a.resume && !a.save);
            assert_eq!(cfg.walking_translation("hk416a5").0[axis], -1.);
            let a = menu.input(
                &mut cfg,
                "hk416a5",
                size,
                point(900., r.y),
                (false, true),
                true,
            );
            assert!(!a.resume && !a.save);
            assert_eq!(cfg.walking_translation("hk416a5").0[axis], 1.);
            assert!(
                menu.input(
                    &mut cfg,
                    "hk416a5",
                    size,
                    point(900., r.y),
                    (false, false),
                    true
                )
                .save
            );
            assert!(
                !menu
                    .input(
                        &mut cfg,
                        "hk416a5",
                        size,
                        point(900., r.y),
                        (false, false),
                        true
                    )
                    .save
            );
        }
        assert_eq!(cfg.walking_translation("other"), WalkTranslation::default());
    }
    #[test]
    fn focus_loss_cancels_drag_and_reset_only_changes_selected_weapon() {
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        cfg.set_viewmodel(0.08, -0.04);
        cfg.set_walking_translation("other", WalkTranslation([0.2, 0.3, 0.4]));
        let size = vec2(1000., 800.);
        menu.input(
            &mut cfg,
            "hk416a5",
            size,
            point(slider_rect(0).x, slider_rect(0).y + 10.),
            (true, true),
            true,
        );
        assert!(
            menu.input(
                &mut cfg,
                "hk416a5",
                size,
                point(0., 0.),
                (false, true),
                false
            )
            .save
        );
        assert!(
            !menu
                .input(
                    &mut cfg,
                    "hk416a5",
                    size,
                    point(slider_rect(0).x + slider_rect(0).w, slider_rect(0).y + 10.),
                    (false, true),
                    true
                )
                .resume
        );
        assert_eq!(cfg.walking_translation("hk416a5").0[0], -1.);
        let action = menu.input(
            &mut cfg,
            "hk416a5",
            size,
            point(RESET.x + 5., RESET.y + 5.),
            (true, true),
            true,
        );
        assert!(action.save && !action.resume);
        assert_eq!(
            cfg.walking_translation("hk416a5"),
            WalkTranslation::default()
        );
        assert_eq!(
            cfg.walking_translation("other"),
            WalkTranslation([0.2, 0.3, 0.4])
        );
        assert_eq!((cfg.viewmodel_x, cfg.viewmodel_y), (0.08, -0.04));
    }

    #[test]
    fn absolute_position_sliders_do_not_modify_walking_gains_or_resume() {
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        cfg.set_walking_translation("hk416a5", WalkTranslation([-0.5, 0.25, 1.]));
        let size = vec2(1000., 800.);
        for axis in [3, 4, 5] {
            let r = slider_rect(axis);
            let action = menu.input(
                &mut cfg,
                "hk416a5",
                size,
                point(r.x, r.y + 10.),
                (true, true),
                true,
            );
            assert!(!action.resume);
            assert!(
                menu.input(
                    &mut cfg,
                    "hk416a5",
                    size,
                    point(r.x, r.y + 10.),
                    (false, false),
                    true
                )
                .save
            );
        }
        assert_eq!((cfg.viewmodel_x, cfg.viewmodel_y), (-0.20, -0.20));
        assert_eq!(cfg.viewmodel_z, -0.20);
        assert_eq!(
            cfg.walking_translation("hk416a5"),
            WalkTranslation([-0.5, 0.25, 1.])
        );
        let action = menu.input(
            &mut cfg,
            "hk416a5",
            size,
            point(POSITION_RESET.x + 5., POSITION_RESET.y + 5.),
            (true, true),
            true,
        );
        assert!(action.save && !action.resume);
        assert_eq!(
            (cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z),
            (0., 0., 0.)
        );
        assert_eq!(
            cfg.walking_translation("hk416a5"),
            WalkTranslation([-0.5, 0.25, 1.])
        );
    }
    struct ThemeReset;
    impl Drop for ThemeReset {
        fn drop(&mut self) {
            ui_theme::set_theme(ui_theme::UiTheme::default());
        }
    }
    #[test]
    fn default_layout_keeps_original_native_coordinates() {
        let _reset = ThemeReset;
        ui_theme::set_theme(ui_theme::UiTheme::default());
        let layout = Layout::new(1000., 800.);
        let scale = 776. / 843.;
        assert_eq!(layout.scale, scale);
        let expected = Rect::new(
            (1000. - 610. * scale) / 2. + 32. * scale,
            12. + 99. * scale,
            546. * scale,
            45. * scale,
        );
        let actual = layout.rect(RESUME);
        for (a, b) in [
            (actual.x, expected.x),
            (actual.y, expected.y),
            (actual.w, expected.w),
            (actual.h, expected.h),
        ] {
            assert!((a - b).abs() < 0.001);
        }
    }
    #[test]
    fn styled_pause_button_uses_identical_painted_and_clickable_bounds() {
        use vector_range::draw::Command;
        let _reset = ThemeReset;
        ui_theme::set_theme(
            ui_theme::UiTheme::parse(
                "test.css",
                "#pause-menu .button {font-size:48px;background-color:#123456;border-width:8px}",
            )
            .unwrap(),
        );
        let size = vec2(1000., 800.);
        let layout = Layout::new(size.x, size.y);
        let expected = layout.rect(RESUME);
        begin_frame(1000, 800, 1.).unwrap();
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        menu.draw_with_layout(&cfg, "rifle", false, ControlMode::Hold, None, layout);
        let list = take_draw_list().unwrap();
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Rect { rect, color } if *rect == expected && *color == Color::new(18./255., 52./255., 86./255., 1.))));
        let inside = vec2(expected.x + expected.w * 0.5, expected.y + expected.h - 0.1);
        assert!(
            menu.input(&mut cfg, "rifle", size, inside, (true, true), true)
                .resume
        );
        let outside = vec2(expected.x + expected.w + 0.1, expected.y + expected.h * 0.5);
        assert!(
            !menu
                .input(&mut cfg, "rifle", size, outside, (true, true), true)
                .resume
        );
    }
    #[test]
    fn styled_sliders_share_drawn_track_endpoints_and_release_ownership() {
        let _reset = ThemeReset;
        ui_theme::set_theme(
            ui_theme::UiTheme::parse("test.css", "#pause-menu .slider {font-size:48px}").unwrap(),
        );
        let size = vec2(1000., 800.);
        let layout = Layout::new(size.x, size.y);
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        for axis in 0..6 {
            let local = slider_rect(axis);
            let hitbox = layout.rect(local);
            let track = layout.rect(Rect::new(local.x, local.y + 11., local.w, 5.));
            assert_eq!(hitbox.x, track.x);
            assert_eq!(hitbox.w, track.w);
            let pointer = vec2(track.x + track.w, hitbox.y + hitbox.h - 0.1);
            let action = menu.input(&mut cfg, "rifle", size, pointer, (true, true), true);
            assert!(!action.resume && !action.save);
            if axis < 3 {
                assert_eq!(cfg.walking_translation("rifle").0[axis], 1.);
            } else {
                assert_eq!(
                    [cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z][axis - 3],
                    Settings::VIEWMODEL_OFFSET_LIMIT
                );
            }
            assert!(
                menu.input(&mut cfg, "rifle", size, pointer, (false, false), true)
                    .save
            );
            assert!(
                !menu
                    .input(&mut cfg, "rifle", size, pointer, (false, false), true)
                    .save
            );
        }
        let reset = layout.rect(POSITION_RESET);
        assert!(layout.rect(slider_rect(5)).y + layout.rect(slider_rect(5)).h < reset.y);
    }
}
