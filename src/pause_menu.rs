//! Pause-only controls. Pointer gestures are consumed before resume input.
use crate::draw::facade::*;
use crate::graphics_device::{self, Preference};
use crate::platform::runtime::{screen_height, screen_width};
use crate::ui_theme::{self, flow_y, FlowBand, UiClass, UiScope, UiStyle};
use crate::{
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
            FlowBand::new(257., 273., &[(muted, 15.)]),
            FlowBand::new(279., 325., &[(label, 18.)]),
            FlowBand::new(346., 366., &[(accent, 20.)]),
            FlowBand::new(497., 525., &[(button, 16.), (muted, 15.)]),
            FlowBand::new(525., 545., &[(accent, 20.)]),
            FlowBand::new(552., 567., &[(muted, 15.)]),
            FlowBand::new(720., 754., &[(button, 18.)]),
            FlowBand::new(771., 787., &[(muted, 16.), (warning, 16.)]),
            FlowBand::new(805., 839., &[(button, 18.)]),
            FlowBand::new(855., 889., &[(button, 18.)]),
        ];
        for axis in 0..6 {
            let r = slider_rect(axis);
            bands.push(FlowBand::new(
                r.y,
                r.y + r.h,
                &[(slider, if axis < 3 { 18. } else { 15. })],
            ));
        }
        Self::with_bands(width, height, bands)
    }
    fn graphics(width: f32, height: f32) -> Self {
        let label = text_style(UiClass::Label, WHITE);
        let muted = text_style(UiClass::Label, MUTED);
        let accent = text_style(UiClass::Label, ACCENT);
        let button = text_style(UiClass::Button, WHITE);
        let mut bands = vec![
            FlowBand::new(18., 80., &[(accent, 30.), (muted, 16.)]),
            FlowBand::new(99., 144., &[(button, 18.)]),
            FlowBand::new(381., 415., &[(button, 18.)]),
            FlowBand::new(497., 531., &[(button, 18.)]),
        ];
        for (baseline, size, style) in [
            (179., 18., accent),
            (205., 18., label),
            (231., 16., muted),
            (297., 18., accent),
            (325., 18., label),
            (366., 16., muted),
            (455., 16., muted),
            (567., 15., accent),
            (610., 16., label),
            (653., 15., muted),
            (696., 15., muted),
            (739., 15., muted),
            (782., 15., muted),
            (825., 15., muted),
            (873., 15., muted),
        ] {
            bands.push(FlowBand::new(
                baseline - size,
                baseline + 4.,
                &[(style, size)],
            ));
        }
        Self::with_bands(width, height, bands)
    }
    fn with_bands(width: f32, height: f32, bands: Vec<FlowBand>) -> Self {
        let content_height = flow_y(909., &bands);
        let available_width = (width - 24.).max(1.).min(width);
        let available_height = (height - 24.).max(1.).min(height);
        let scale = (available_width / 610.)
            .min(available_height / content_height)
            .min(1.);
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
const TELEMETRY: Rect = Rect::new(32., 805., 546., 34.);
const GRAPHICS: Rect = Rect::new(32., 855., 546., 34.);
const GPU_PREVIOUS: Rect = Rect::new(32., 381., 260., 34.);
const GPU_NEXT: Rect = Rect::new(318., 381., 260., 34.);
const GPU_SAVE: Rect = Rect::new(32., 497., 546., 34.);
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
    telemetry_recording: bool,
    telemetry_stopping: bool,
    graphics_open: bool,
    graphics_choices: Vec<Preference>,
    graphics_choice: usize,
    graphics_focus: Option<usize>,
    graphics_status: Option<String>,
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
    pub telemetry: bool,
}
impl PauseMenu {
    pub fn telemetry_state(&mut self, recording: bool, stopping: bool) {
        self.telemetry_recording = recording;
        self.telemetry_stopping = stopping;
    }
    pub fn has_keyboard_focus(&self) -> bool {
        self.graphics_open || self.focus.is_some()
    }
    /// Escape closes the subpage before the gameplay session can resume.
    pub fn graphics_escape(&mut self, pressed: bool) -> bool {
        if pressed && self.graphics_open {
            self.graphics_open = false;
            self.focus = Some(11);
            true
        } else {
            false
        }
    }
    fn open_graphics(&mut self) {
        graphics_device::ensure_catalog();
        let state = graphics_device::snapshot();
        self.graphics_choices = vec![Preference::Auto];
        for candidate in &state.candidates {
            if graphics_device::exact_match(&candidate.id, &state.candidates).is_ok()
                && matches!(candidate.id.backend.as_str(), "dx12" | "vulkan" | "metal")
            {
                self.graphics_choices
                    .push(Preference::Adapter(candidate.id.clone()));
            }
        }
        self.graphics_choices[1..].sort_by_key(Preference::label);
        self.graphics_choice = self
            .graphics_choices
            .iter()
            .position(|p| *p == state.preference)
            .unwrap_or(0);
        self.graphics_status = if state.forced_fallback {
            Some("Forced software validation: saved GPU choices are ignored.".into())
        } else {
            state.catalog_error.or_else(|| {
                let excluded = state.candidates.len() + 1 - self.graphics_choices.len();
                if excluded > 0 {
                    Some(format!("{excluded} device entries are ambiguous or unsupported; unavailable for selection."))
                } else if self.graphics_choices.len() == 1 {
                    Some("No compatible native graphics devices were found.".into())
                } else { None }
            })
        };
        self.graphics_focus = Some(0);
        self.graphics_open = true;
        self.dragging = None;
    }
    fn cycle_graphics(&mut self, forward: bool) {
        let count = self.graphics_choices.len();
        if count != 0 {
            self.graphics_choice =
                (self.graphics_choice + if forward { 1 } else { count - 1 }) % count;
            self.graphics_status =
                Some("Preview choice only. Save to apply after restarting.".into());
        }
    }
    fn graphics_activate(&mut self, index: usize) {
        self.graphics_focus = Some(index);
        match index {
            0 => {
                self.graphics_open = false;
                self.focus = Some(11);
            }
            1 => self.cycle_graphics(false),
            2 => self.cycle_graphics(true),
            3 => {
                if let Some(choice) = self.graphics_choices.get(self.graphics_choice) {
                    self.graphics_status =
                        Some(match graphics_device::save_choice(choice.clone()) {
                            Ok(()) => {
                                "Saved. Restart the game to apply this graphics choice.".into()
                            }
                            Err(error) => format!("Not saved: {error}"),
                        });
                }
            }
            _ => {}
        }
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
            self.graphics_focus = None;
            return MenuAction::default();
        }
        if self.graphics_open {
            if keys.next {
                self.graphics_focus = Some(self.graphics_focus.map_or(0, |i| (i + 1) % 4));
            }
            if keys.previous {
                self.graphics_focus = Some(self.graphics_focus.map_or(3, |i| (i + 3) % 4));
            }
            if keys.increase {
                self.cycle_graphics(true);
            }
            if keys.decrease {
                self.cycle_graphics(false);
            }
            if keys.activate {
                if let Some(focus) = self.graphics_focus {
                    self.graphics_activate(focus);
                }
            }
            return MenuAction::default();
        }
        if keys.next {
            self.focus = Some(self.focus.map_or(0, |i| (i + 1) % 12));
        }
        if keys.previous {
            self.focus = Some(self.focus.map_or(11, |i| (i + 11) % 12));
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
                10 => action.telemetry = !self.telemetry_stopping,
                11 => self.open_graphics(),
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
            self.graphics_focus = None;
            return MenuAction {
                save: std::mem::take(&mut self.dirty),
                ..Default::default()
            };
        }
        let layout = Layout::new(size.x, size.y);
        let point = pointer;
        if self.graphics_open {
            let layout = Layout::graphics(size.x, size.y);
            if pressed {
                if let Some(index) = [RESUME, GPU_PREVIOUS, GPU_NEXT, GPU_SAVE]
                    .iter()
                    .position(|r| layout.rect(*r).contains(point))
                {
                    self.graphics_activate(index);
                }
            }
            return MenuAction::default();
        }
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
            } else if layout.rect(TELEMETRY).contains(point) {
                self.focus = Some(10);
                action.telemetry = !self.telemetry_stopping;
            } else if layout.rect(GRAPHICS).contains(point) {
                self.focus = Some(11);
                self.open_graphics();
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
        if self.graphics_open {
            self.draw_graphics(&Layout::graphics(layout.viewport.x, layout.viewport.y));
            return;
        }
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
            layout.rect(Rect::new(0., 0., 610., 909.)),
            ink,
            accent,
            layout.scale,
        );
        rect(
            Rect::new(0., 0., 610., 3.),
            ui_theme::style(UiScope::PauseMenu, &[UiClass::Accent]).tint(accent),
        );
        text("VECTOR RANGE", 32., 52., 34., WHITE);
        text(crate::BUILD_LABEL, 33., 77., 16., muted);
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
        button(TELEMETRY);
        button_text(
            if self.telemetry_stopping {
                "Stopping telemetry; awaiting final present"
            } else if self.telemetry_recording {
                "Stop telemetry / save local session (F8)"
            } else {
                "Record telemetry (F8)"
            },
            TELEMETRY.x + 15.,
            TELEMETRY.y + 23.,
            18.,
            WHITE,
            TELEMETRY.w - 30.,
        );
        button(GRAPHICS);
        button_text(
            "Graphics device / GPU (restart to apply)",
            GRAPHICS.x + 15.,
            GRAPHICS.y + 23.,
            18.,
            WHITE,
            GRAPHICS.w - 30.,
        );
        if let Some(focus) = self.focus {
            let r = match focus {
                0 => RESUME,
                1..=3 => slider_rect(focus + 2),
                4 => POSITION_RESET,
                5..=7 => slider_rect(focus - 5),
                8 => RESET,
                9 => SAVE,
                10 => TELEMETRY,
                _ => GRAPHICS,
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
            "F5 Save   F6 Reload   Tab / Enter Menu   F10 Quit",
            32.,
            273.,
            15.,
            muted,
        );
    }
    fn draw_graphics(&self, layout: &Layout) {
        let state = graphics_device::snapshot();
        draw_rectangle(
            0.,
            0.,
            layout.viewport.x,
            layout.viewport.y,
            Color::new(0.015, 0.025, 0.035, 0.80),
        );
        ui_theme::style(UiScope::PauseMenu, &[UiClass::Panel]).rect(
            layout.rect(Rect::new(0., 0., 610., 909.)),
            Color::new(0.035, 0.057, 0.074, 0.97),
            ACCENT,
            layout.scale,
        );
        let text = |value: &str, y: f32, size: f32, color: Color| {
            let fitted = text_style(UiClass::Label, color).fit_text(value, size, 546.);
            layout.text(UiClass::Label, &fitted, vec2(32., y), size, color, 546.);
        };
        text("GRAPHICS DEVICE", 52., 30., ACCENT);
        text(
            "Changes take effect after restarting the game",
            77.,
            16.,
            MUTED,
        );
        for (index, rect, label) in [
            (0, RESUME, "Back to pause menu (Esc)"),
            (1, GPU_PREVIOUS, "Previous device"),
            (2, GPU_NEXT, "Next device"),
            (3, GPU_SAVE, "Save device for next launch"),
        ] {
            let painted = layout.rect(rect);
            ui_theme::style(UiScope::PauseMenu, &[UiClass::Button]).rect(
                painted,
                Color::new(0.13, 0.21, 0.25, 1.),
                ACCENT,
                layout.scale,
            );
            layout.text(
                UiClass::Button,
                label,
                vec2(rect.x + 15., rect.y + 23.),
                18.,
                WHITE,
                rect.w - 30.,
            );
            if self.graphics_focus == Some(index) {
                draw_rectangle_lines(
                    painted.x - 3.,
                    painted.y - 3.,
                    painted.w + 6.,
                    painted.h + 6.,
                    2.,
                    ACCENT,
                );
            }
        }
        text("RUNNING NOW", 179., 18., ACCENT);
        if let Some(info) = &state.actual {
            text(&info.adapter, 205., 18., WHITE);
            text(&format!("Backend: {}", info.backend), 231., 16., MUTED);
        } else {
            text(
                "Actual device unavailable in this runtime",
                205.,
                16.,
                MUTED,
            );
        }
        text(
            &format!(
                "DEVICE FOR NEXT LAUNCH ({}/{})",
                self.graphics_choice + 1,
                self.graphics_choices.len()
            ),
            297.,
            18.,
            ACCENT,
        );
        if let Some(choice) = self.graphics_choices.get(self.graphics_choice) {
            text(&choice.label(), 325., 18., WHITE);
            if let Preference::Adapter(id) = choice {
                text(
                    &format!(
                        "{} | vendor {:04X} / device {:04X}",
                        id.device_type, id.vendor, id.device
                    ),
                    366.,
                    16.,
                    MUTED,
                );
            } else {
                text(
                    "Keeps existing default and explicit renderer behavior",
                    366.,
                    16.,
                    MUTED,
                );
            }
        }
        text(
            &format!("Saved: {}", state.preference.label()),
            455.,
            16.,
            MUTED,
        );
        text(
            self.graphics_status
                .as_deref()
                .unwrap_or("Choose a device, then save. Current rendering continues."),
            567.,
            15.,
            ACCENT,
        );
        text(
            if state.preference != state.startup_preference {
                "RESTART REQUIRED: the saved choice is not active yet."
            } else {
                "Current device remains active until you restart."
            },
            610.,
            16.,
            WHITE,
        );
        if let Some(renderer) = &state.renderer_override {
            text(
                &format!("Explicit launch backend: {renderer}; incompatible choices fail."),
                653.,
                15.,
                MUTED,
            );
        }
        text(
            "Identical fingerprints or unsupported devices cannot be selected.",
            696.,
            15.,
            MUTED,
        );
        text(
            "Device names are best-effort IDs, not physical-card serial numbers.",
            739.,
            15.,
            MUTED,
        );
        text(
            "Legacy discovery validates window compatibility on next launch.",
            782.,
            15.,
            MUTED,
        );
        text(
            "Missing device? Start with --graphics-device=auto to recover.",
            825.,
            15.,
            MUTED,
        );
        text(
            "Tab selects controls; arrows choose; Enter activates; Esc goes back.",
            873.,
            15.,
            MUTED,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct GraphicsFixture {
        previous: graphics_device::Session,
        path: std::path::PathBuf,
    }
    impl GraphicsFixture {
        fn new() -> Self {
            static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
            let path = std::env::temp_dir().join(format!(
                "gpu-menu-{}-{}.json",
                std::process::id(),
                NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
            ));
            let previous = graphics_device::snapshot();
            graphics_device::initialize(graphics_device::Session {
                path: path.clone(),
                catalog_ready: true,
                actual: Some(BackendInfo {
                    requested: "dx12".into(),
                    backend: "Dx12".into(),
                    adapter: "NVIDIA GeForce RTX 3080 Ti".into(),
                }),
                candidates: vec![graphics_device::Candidate {
                    id: graphics_device::Fingerprint {
                        backend: "dx12".into(),
                        name: "NVIDIA GeForce RTX 3080 Ti".into(),
                        vendor: 0x10de,
                        device: 0x2208,
                        device_type: "DiscreteGpu".into(),
                    },
                    surface_supported: true,
                }],
                ..Default::default()
            });
            Self { previous, path }
        }
    }
    impl Drop for GraphicsFixture {
        fn drop(&mut self) {
            graphics_device::initialize(self.previous.clone());
            let _ = std::fs::remove_file(&self.path);
        }
    }
    #[test]
    fn graphics_menu_selection_requires_save_and_preserves_running_device() {
        let fixture = GraphicsFixture::new();
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        let size = vec2(1000., 1000.);
        let layout = Layout::new(size.x, size.y);
        let point = layout.point(vec2(GRAPHICS.x + 20., GRAPHICS.y + 15.));
        let action = menu.input(&mut cfg, "rifle", size, point, (true, true), true);
        assert!(!action.resume && !action.save && !action.telemetry);
        assert!(menu.graphics_open && menu.has_keyboard_focus());
        menu.keyboard(
            &mut cfg,
            "rifle",
            MenuKeys {
                increase: true,
                ..Default::default()
            },
            true,
        );
        assert_eq!(menu.graphics_choice, 1);
        assert!(!fixture.path.exists());
        menu.graphics_focus = Some(3);
        let action = menu.keyboard(
            &mut cfg,
            "rifle",
            MenuKeys {
                activate: true,
                ..Default::default()
            },
            true,
        );
        assert!(!action.resume && !action.save && !action.telemetry);
        let state = graphics_device::snapshot();
        assert_eq!(Preference::load(&fixture.path).unwrap(), state.preference);
        assert_eq!(state.startup_preference, Preference::Auto);
        assert_eq!(state.actual.unwrap().adapter, "NVIDIA GeForce RTX 3080 Ti");
        assert!(menu.graphics_status.as_ref().unwrap().contains("Restart"));
        assert!(menu.graphics_escape(true));
        assert!(!menu.graphics_open);
        menu.keyboard(
            &mut cfg,
            "rifle",
            MenuKeys {
                activate: true,
                ..Default::default()
            },
            true,
        );
        assert!(menu.graphics_open);
        assert_eq!(
            menu.graphics_choice, 1,
            "reopening must show the saved choice"
        );
    }
    #[test]
    fn graphics_pointer_hold_focus_loss_back_and_escape_do_not_resume_or_save() {
        let _fixture = GraphicsFixture::new();
        let mut menu = PauseMenu::default();
        menu.open_graphics();
        let mut cfg = Settings::default();
        let size = vec2(1000., 1000.);
        let layout = Layout::graphics(size.x, size.y);
        let point = layout.point(vec2(GPU_NEXT.x + 20., GPU_NEXT.y + 15.));
        menu.input(&mut cfg, "rifle", size, point, (true, true), true);
        assert_eq!(menu.graphics_choice, 1);
        menu.input(&mut cfg, "rifle", size, point, (false, true), true);
        assert_eq!(menu.graphics_choice, 1);
        menu.input(&mut cfg, "rifle", size, point, (false, true), false);
        let action = menu.keyboard(
            &mut cfg,
            "rifle",
            MenuKeys {
                activate: true,
                ..Default::default()
            },
            true,
        );
        assert!(!action.resume && !action.save);
        assert_eq!(graphics_device::snapshot().preference, Preference::Auto);
        let mut session = crate::session::SessionController::default();
        let consumed = menu.graphics_escape(true);
        assert!(
            !session
                .step(crate::session::SessionInput {
                    esc_pressed: true,
                    esc_down: true,
                    blocked: consumed,
                    ..Default::default()
                })
                .active
        );
        assert!(
            !session
                .step(crate::session::SessionInput {
                    esc_down: true,
                    ..Default::default()
                })
                .active
        );
        session.step(crate::session::SessionInput::default());
        assert!(
            session
                .step(crate::session::SessionInput {
                    esc_pressed: true,
                    esc_down: true,
                    ..Default::default()
                })
                .resumed
        );
    }
    #[test]
    fn graphics_duplicate_candidates_are_disabled_and_save_failure_keeps_last_preference() {
        let fixture = GraphicsFixture::new();
        let mut state = graphics_device::snapshot();
        state.candidates.push(state.candidates[0].clone());
        graphics_device::initialize(state);
        let mut menu = PauseMenu::default();
        menu.open_graphics();
        assert_eq!(menu.graphics_choices, vec![Preference::Auto]);
        assert!(menu.graphics_status.as_ref().unwrap().contains("ambiguous"));
        let mut state = graphics_device::snapshot();
        state.candidates.pop();
        state.path = fixture.path.join("missing-parent.json");
        graphics_device::initialize(state);
        menu.open_graphics();
        menu.cycle_graphics(true);
        menu.graphics_activate(3);
        assert!(menu
            .graphics_status
            .as_ref()
            .unwrap()
            .starts_with("Not saved:"));
        assert_eq!(graphics_device::snapshot().preference, Preference::Auto);
    }
    #[test]
    fn graphics_draw_shows_actual_adapter_backend_and_restart_required() {
        use crate::draw::Command;
        let _fixture = GraphicsFixture::new();
        let mut menu = PauseMenu::default();
        menu.open_graphics();
        menu.cycle_graphics(true);
        menu.graphics_activate(3);
        begin_frame(1400, 1000, 1.).unwrap();
        menu.draw_with_layout(
            &Settings::default(),
            "rifle",
            false,
            ControlMode::Hold,
            None,
            Layout::new(1400., 1000.),
        );
        let list = take_draw_list().unwrap();
        let texts: Vec<_> = list
            .commands
            .iter()
            .filter_map(|c| {
                if let Command::Text { text, .. } = c {
                    Some(text.as_str())
                } else {
                    None
                }
            })
            .collect();
        assert!(texts.contains(&"NVIDIA GeForce RTX 3080 Ti"));
        assert!(texts.contains(&"Backend: Dx12"));
        assert!(texts.iter().any(|s| s.starts_with("RESTART REQUIRED")));
        assert!(texts.contains(&"Save device for next launch"));
    }
    #[test]
    fn graphics_controls_match_painted_hitboxes_across_fractional_dpi_and_themes() {
        use crate::draw::Command;
        let _fixture = GraphicsFixture::new();
        let _reset = ThemeReset;
        for css in ["", "#pause-menu {font-size:48px}"] {
            ui_theme::set_theme(ui_theme::UiTheme::parse("graphics.css", css).unwrap());
            for dpi in [1., 1.25, 1.5, 1.75, 2.] {
                let size = vec2(1400. / dpi, 1000. / dpi);
                let mut menu = PauseMenu::default();
                menu.open_graphics();
                begin_frame(1400, 1000, dpi as f64).unwrap();
                menu.draw_with_layout(
                    &Settings::default(),
                    "rifle",
                    false,
                    ControlMode::Hold,
                    None,
                    Layout::new(size.x, size.y),
                );
                let list = take_draw_list().unwrap();
                let buttons: Vec<_> = list
                    .commands
                    .iter()
                    .filter_map(|c| match c {
                        Command::Rect { rect, color }
                            if *color == Color::new(0.13, 0.21, 0.25, 1.) =>
                        {
                            Some(*rect)
                        }
                        _ => None,
                    })
                    .collect();
                assert_eq!(buttons.len(), 4);
                for (index, button) in buttons.iter().enumerate() {
                    assert!(
                        button.x >= 0.
                            && button.y >= 0.
                            && button.x + button.w <= 1400.01
                            && button.y + button.h <= 1000.01
                    );
                    let pointer = vec2(button.x + button.w / 2., button.y + button.h - 0.25) / dpi;
                    let mut menu = PauseMenu::default();
                    menu.open_graphics();
                    let action = menu.input(
                        &mut Settings::default(),
                        "rifle",
                        size,
                        pointer,
                        (true, true),
                        true,
                    );
                    assert!(!action.resume && !action.save && !action.telemetry);
                    assert_eq!(menu.graphics_open, index != 0);
                    assert_eq!(menu.graphics_focus, Some(index));
                    if index == 1 || index == 2 {
                        assert_eq!(menu.graphics_choice, 1);
                    }
                }
            }
        }
    }

    #[test]
    fn telemetry_toggle_owns_pointer_and_keyboard_without_resuming_or_saving() {
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        let size = vec2(1000., 1000.);
        let layout = Layout::new(size.x, size.y);
        let point = layout.point(vec2(TELEMETRY.x + 20., TELEMETRY.y + 15.));
        let action = menu.input(&mut cfg, "rifle", size, point, (true, true), true);
        assert!(action.telemetry && !action.resume && !action.save);
        assert_eq!(menu.focus, Some(10));
        assert!(
            !menu
                .input(&mut cfg, "rifle", size, point, (false, true), true)
                .telemetry
        );
        assert!(
            menu.keyboard(
                &mut cfg,
                "rifle",
                MenuKeys {
                    activate: true,
                    ..Default::default()
                },
                true
            )
            .telemetry
        );
        menu.telemetry_state(false, true);
        assert!(
            !menu
                .keyboard(
                    &mut cfg,
                    "rifle",
                    MenuKeys {
                        activate: true,
                        ..Default::default()
                    },
                    true
                )
                .telemetry
        );
        assert!(
            !menu
                .input(&mut cfg, "rifle", size, point, (true, true), true)
                .telemetry
        );
        menu.telemetry_state(false, false);
        assert!(
            !menu
                .input(&mut cfg, "rifle", size, point, (true, true), false)
                .telemetry
        );
    }

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
        let scale = 776. / 909.;
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
        use crate::draw::Command;
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

#[cfg(test)]
mod dpi_geometry_tests {
    use super::*;
    use crate::draw::Command;

    struct ThemeReset;
    impl Drop for ThemeReset {
        fn drop(&mut self) {
            ui_theme::set_theme(ui_theme::UiTheme::default());
        }
    }

    fn theme() {
        ui_theme::set_theme(
            ui_theme::UiTheme::parse(
                "fractional.css",
                "#pause-menu .button {font-size:25.5px;background-color:#123456;border-width:3.25px}\n\
                 #pause-menu .slider {font-size:21.5px;background-color:#654321;border-width:1.25px}",
            )
            .unwrap(),
        );
    }

    fn draw(menu: &PauseMenu, cfg: &Settings, size: Vec2, dpi: f64) -> Vec<Command> {
        begin_frame(1400, 1000, dpi).unwrap();
        menu.draw_with_layout(
            cfg,
            "rifle",
            false,
            ControlMode::Hold,
            None,
            Layout::new(size.x, size.y),
        );
        take_draw_list().unwrap().commands
    }

    fn painted(commands: &[Command], color: Color) -> Vec<Rect> {
        commands
            .iter()
            .filter_map(|command| match command {
                Command::Rect {
                    rect,
                    color: actual,
                } if *actual == color => Some(*rect),
                _ => None,
            })
            .collect()
    }

    #[test]
    fn pause_panel_and_controls_fit_nonzero_sub_margin_viewports() {
        let _reset = ThemeReset;
        for css in ["", "#pause-menu {font-size:96px;border-width:16px}"] {
            ui_theme::set_theme(ui_theme::UiTheme::parse("tiny.css", css).unwrap());
            for dpi in [1., 1.25, 1.5, 1.75, 2.] {
                for (width, height) in
                    [(1., 1.), (16., 800.), (800., 16.), (32., 32.), (200., 800.)]
                {
                    let viewport = Rect::new(0., 0., width / dpi, height / dpi);
                    let layout = Layout::new(viewport.w, viewport.h);
                    for local in [
                        Rect::new(0., 0., 610., 909.),
                        RESUME,
                        POSITION_RESET,
                        RESET,
                        SAVE,
                    ]
                    .into_iter()
                    .chain((0..6).map(slider_rect))
                    {
                        let rect = layout.rect(local);
                        // Allow only floating-point arithmetic error, far below
                        // one pixel even in the smallest valid native frame.
                        assert!(rect.x >= -0.001 && rect.y >= -0.001, "{dpi}x {rect:?}");
                        assert!(rect.x + rect.w <= viewport.w + 0.001, "{dpi}x {rect:?}");
                        assert!(rect.y + rect.h <= viewport.h + 0.001, "{dpi}x {rect:?}");
                    }
                }
            }
        }
    }

    #[test]
    fn fractional_dpi_pause_button_paint_drives_the_real_input_actions() {
        let _reset = ThemeReset;
        theme();
        for dpi in [1., 1.25, 1.5, 1.75, 2.] {
            let scale = dpi as f32;
            let size = vec2(1400. / scale, 1000. / scale);
            let commands = draw(&PauseMenu::default(), &Settings::default(), size, dpi);
            let buttons = painted(
                &commands,
                Color::new(18. / 255., 52. / 255., 86. / 255., 1.),
            );
            assert_eq!(buttons.len(), 6);
            // Draw order: resume, position reset, walking reset, save, telemetry, graphics.
            for (index, button) in buttons.iter().enumerate() {
                let mut menu = PauseMenu::default();
                let mut cfg = Settings::default();
                cfg.set_viewmodel(0.1, -0.1);
                cfg.set_walking_translation("rifle", WalkTranslation([0.3, 0.4, 0.5]));
                // Read the physical painted box, then apply the native pointer's
                // physical-to-logical conversion. No second copy of layout math.
                let pointer = vec2(button.x + button.w / 2., button.y + button.h - 0.25) / scale;
                let action = menu.input(&mut cfg, "rifle", size, pointer, (true, true), true);
                assert_eq!(action.resume, index == 0, "{dpi}x button {index}");
                assert_eq!(
                    action.save,
                    (1..=3).contains(&index),
                    "{dpi}x button {index}"
                );
                assert_eq!(action.telemetry, index == 4, "{dpi}x button {index}");
                assert_eq!(menu.focus, Some([0, 4, 8, 9, 10, 11][index]));
                assert_eq!(
                    (cfg.viewmodel_x, cfg.viewmodel_y),
                    if index == 1 { (0., 0.) } else { (0.1, -0.1) }
                );
                assert_eq!(
                    cfg.walking_translation("rifle").0,
                    if index == 2 { [0.; 3] } else { [0.3, 0.4, 0.5] }
                );

                let mut menu = PauseMenu::default();
                let pointer = vec2(button.x + button.w + 0.25, button.y + button.h / 2.) / scale;
                let action = menu.input(&mut cfg, "rifle", size, pointer, (true, true), true);
                assert!(
                    !action.resume && !action.save && !action.telemetry,
                    "{dpi}x button {index}: exterior click"
                );
                assert_eq!(menu.focus, None);
            }
        }
    }

    #[test]
    fn fractional_dpi_painted_slider_endpoints_preserve_drag_and_focus_ownership() {
        let _reset = ThemeReset;
        theme();
        for dpi in [1., 1.25, 1.5, 1.75, 2.] {
            let scale = dpi as f32;
            let size = vec2(1400. / scale, 1000. / scale);
            let commands = draw(&PauseMenu::default(), &Settings::default(), size, dpi);
            let tracks = painted(
                &commands,
                Color::new(101. / 255., 67. / 255., 33. / 255., 1.),
            );
            assert_eq!(tracks.len(), 6);
            for (axis, track) in [3, 4, 5, 0, 1, 2].into_iter().zip(tracks) {
                let mut menu = PauseMenu::default();
                let mut cfg = Settings::default();
                let center = vec2(track.x + track.w / 2., track.y + track.h / 2.) / scale;
                let action = menu.input(&mut cfg, "rifle", size, center, (true, true), true);
                assert!(!action.resume && !action.save);
                assert_eq!(menu.dragging, Some(axis));
                for (x, expected) in [(track.x, -1.), (track.x + track.w, 1.)] {
                    let action = menu.input(
                        &mut cfg,
                        "rifle",
                        size,
                        vec2(x, track.y) / scale,
                        (false, true),
                        true,
                    );
                    assert!(!action.resume && !action.save);
                    let actual = if axis < 3 {
                        cfg.walking_translation("rifle").0[axis]
                    } else {
                        [cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z][axis - 3]
                            / Settings::VIEWMODEL_OFFSET_LIMIT
                    };
                    assert_eq!(actual, expected, "{dpi}x axis {axis}");
                }
                // Focus loss finalizes this edit once and releases both owners.
                assert!(
                    menu.input(&mut cfg, "rifle", size, center, (false, true), false)
                        .save
                );
                assert_eq!(menu.dragging, None);
                assert!(!menu.has_keyboard_focus());
                assert!(
                    !menu
                        .input(&mut cfg, "rifle", size, center, (false, true), true)
                        .save
                );
                assert_eq!(menu.dragging, None, "a stale held button cannot recapture");
            }
        }
    }
}
