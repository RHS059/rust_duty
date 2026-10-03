//! Pause-only controls. Pointer gestures are consumed before resume input.
use macroquad::prelude::*;
use vector_range::{
    control::ControlMode,
    settings::{Settings, WalkTranslation},
};

#[derive(Clone, Copy)]
struct Layout {
    origin: Vec2,
    scale: f32,
}
impl Layout {
    fn new(width: f32, height: f32) -> Self {
        let scale = ((width - 24.) / 610.)
            .min((height - 24.) / 660.)
            .clamp(0.1, 1.);
        Self {
            origin: vec2((width - 610. * scale) * 0.5, (height - 660. * scale) * 0.5),
            scale,
        }
    }
    fn local(self, point: Vec2) -> Vec2 {
        (point - self.origin) / self.scale
    }
    fn rect(self, rect: Rect) -> Rect {
        Rect::new(
            self.origin.x + rect.x * self.scale,
            self.origin.y + rect.y * self.scale,
            rect.w * self.scale,
            rect.h * self.scale,
        )
    }
}
const RESUME: Rect = Rect::new(32., 99., 546., 45.);
const RESET: Rect = Rect::new(350., 540., 228., 34.);
fn slider(axis: usize) -> Rect {
    Rect::new(190., 405. + axis as f32 * 43., 292., 28.)
}

#[derive(Default)]
pub struct PauseMenu {
    dragging: Option<usize>,
    dirty: bool,
}
#[derive(Default, Debug)]
pub struct MenuAction {
    pub resume: bool,
    pub save: bool,
}
impl PauseMenu {
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
            return MenuAction {
                save: std::mem::take(&mut self.dirty),
                ..Default::default()
            };
        }
        let point = Layout::new(size.x, size.y).local(pointer);
        let mut action = MenuAction::default();
        if pressed && self.dragging.is_none() {
            if RESET.contains(point) {
                cfg.set_walking_translation(weapon, WalkTranslation::default());
                action.save = true;
            } else if RESUME.contains(point) {
                action.resume = true;
            } else {
                self.dragging = (0..3).find(|axis| slider(*axis).contains(point));
            }
        }
        if let Some(axis) = self.dragging {
            if down || pressed {
                let track = slider(axis);
                let mut value = cfg.walking_translation(weapon);
                value.0[axis] = ((point.x - track.x) / track.w * 2. - 1.).clamp(-1., 1.);
                cfg.set_walking_translation(weapon, value);
                self.dirty = true;
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
        let layout = Layout::new(screen_width(), screen_height());
        let ink = Color::new(0.035, 0.057, 0.074, 0.97);
        let accent = Color::new(0.98, 0.62, 0.22, 1.);
        let muted = Color::new(0.62, 0.69, 0.72, 1.);
        let rect = |r: Rect, color: Color| {
            let r = layout.rect(r);
            draw_rectangle(r.x, r.y, r.w, r.h, color);
        };
        let text = |value: &str, x: f32, y: f32, size: f32, color: Color| {
            draw_text(
                value,
                layout.origin.x + x * layout.scale,
                layout.origin.y + y * layout.scale,
                size * layout.scale,
                color,
            );
        };
        draw_rectangle(
            0.,
            0.,
            screen_width(),
            screen_height(),
            Color::new(0.015, 0.025, 0.035, 0.80),
        );
        rect(Rect::new(0., 0., 610., 660.), ink);
        rect(Rect::new(0., 0., 610., 3.), accent);
        text("VECTOR RANGE", 32., 52., 34., WHITE);
        text("MOVEMENT + GUNPLAY LABORATORY", 33., 77., 16., muted);
        rect(RESUME, Color::new(0.13, 0.21, 0.25, 1.));
        text(
            if initial { "ENTER THE RANGE" } else { "RESUME" },
            48.,
            129.,
            23.,
            accent,
        );
        text("Enter / Esc", 438., 127., 17., muted);
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
        text(
            &format!("WALKING MOTION  /  {weapon}"),
            32.,
            372.,
            20.,
            accent,
        );
        text(
            "Translation only.  -1 = none   0 = current   +1 = double",
            32.,
            394.,
            15.,
            muted,
        );
        let value = cfg.walking_translation(weapon);
        for (axis, label) in ["X  Sideways", "Y  Up / down", "Z  Depth"]
            .iter()
            .enumerate()
        {
            let r = slider(axis);
            text(label, 32., r.y + 20., 18., WHITE);
            rect(
                Rect::new(r.x, r.y + 11., r.w, 5.),
                Color::new(0.19, 0.28, 0.31, 1.),
            );
            rect(Rect::new(r.x + r.w * 0.5 - 1., r.y + 5., 2., 18.), muted);
            let x = r.x + (value.0[axis] + 1.) * 0.5 * r.w;
            rect(Rect::new(x - 5., r.y + 3., 10., 22.), accent);
            text(
                &format!("{:+.2}", value.0[axis]),
                507.,
                r.y + 20.,
                18.,
                WHITE,
            );
        }
        rect(RESET, Color::new(0.13, 0.21, 0.25, 1.));
        text(
            "Reset this weapon",
            RESET.x + 15.,
            RESET.y + 23.,
            18.,
            WHITE,
        );
        text(
            &status
                .unwrap_or("Saved automatically after adjustment")
                .chars()
                .take(72)
                .collect::<String>(),
            32.,
            601.,
            16.,
            muted,
        );
        text(
            "F5 Save preset    F6 Reload preset    F10 Quit",
            32.,
            633.,
            16.,
            muted,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn point(x: f32, y: f32) -> Vec2 {
        Layout::new(1000., 800.).origin + vec2(x, y)
    }
    #[test]
    fn sliders_consume_drag_and_save_once_without_resuming() {
        let mut menu = PauseMenu::default();
        let mut cfg = Settings::default();
        let size = vec2(1000., 800.);
        for axis in 0..3 {
            let r = slider(axis);
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
        cfg.set_walking_translation("other", WalkTranslation([0.2, 0.3, 0.4]));
        let size = vec2(1000., 800.);
        menu.input(
            &mut cfg,
            "hk416a5",
            size,
            point(190., 415.),
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
                    point(480., 415.),
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
    }
}
