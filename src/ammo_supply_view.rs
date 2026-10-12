//! Screen-space presentation for the world-anchored ammunition interaction.
use crate::ammo_supply::SupplyFocus;
use crate::draw::facade::*;
use crate::ui_theme::{self, UiClass, UiScope};

pub const SUPPLY_GOLD: Color = Color::new(1., 0.76, 0.20, 1.);
pub const HOLD_BACKPLATE: Color = Color::new(0., 0., 0., 0.25);
const CIRCLE_RADIUS: f32 = 19.;

/// The idle prompt has no circle. Accepted hold time makes the backplate and
/// gold sweep visible; cancellation/completion remove both immediately.
pub fn hold_circle_visible(progress: f32) -> bool {
    progress.is_finite() && progress > 0.
}

/// Circle boundary in top-left-origin screen coordinates: 0 at twelve o'clock,
/// one quarter at three, one half at six. Kept pure for the rendering contract.
pub fn clockwise_circle_point(center: Vec2, radius: f32, progress: f32) -> Vec2 {
    let angle = progress.clamp(0., 1.) * std::f32::consts::TAU;
    center + vec2(angle.sin(), -angle.cos()) * radius
}

/// Pure fan geometry avoids a flipped winding/angle convention in the HUD.
/// Each returned triangle fills a GOLD sector of the black circular backplate.
pub fn clockwise_fill_triangles(center: Vec2, radius: f32, progress: f32) -> Vec<[Vec2; 3]> {
    if !center.is_finite() || !radius.is_finite() || radius <= 0. || !progress.is_finite() {
        return Vec::new();
    }
    let progress = progress.clamp(0., 1.);
    if progress <= 0. {
        return Vec::new();
    }
    let steps = (progress * 80.).ceil().max(1.) as usize;
    (0..steps)
        .map(|i| {
            [
                center,
                clockwise_circle_point(center, radius, progress * i as f32 / steps as f32),
                clockwise_circle_point(center, radius, progress * (i + 1) as f32 / steps as f32),
            ]
        })
        .collect()
}

fn centered_text(text: &str, center_x: f32, baseline_y: f32, size: u16, color: Color) {
    let class = if text == "AMMO FULL" {
        UiClass::Accent
    } else {
        UiClass::Label
    };
    let style = ui_theme::style(UiScope::AmmoHint, &[UiClass::Label, class]);
    let measure = style.measure(text, size as f32);
    let size = style.size(size as f32);
    let x = center_x - measure.width * 0.5;
    draw_text(
        text,
        x + 1.,
        baseline_y + 1.,
        size,
        style.apply_opacity(Color::new(0., 0., 0., 0.70)),
    );
    draw_text(text, x, baseline_y, size, style.tint(color));
}

/// Call with the default 2D camera, after weapon/HUD rendering. `focus` already
/// contains the exact current-frame world-to-screen projection, so the hint
/// follows camera motion and disappears outside the viewport, without clamping.
pub fn draw_ammo_supply_hint(focus: SupplyFocus, progress: f32, ammo_full: bool) {
    let center = focus.screen_anchor;
    if !center.is_finite() {
        return;
    }
    if ammo_full {
        centered_text(
            "AMMO FULL",
            center.x,
            center.y,
            19,
            Color::new(0.88, 0.93, 0.87, 1.),
        );
        return;
    }
    let label = ui_theme::style(UiScope::AmmoHint, &[UiClass::Label]);
    let key_scale = (label.size(23.) / 23.).max(1.);
    let radius = CIRCLE_RADIUS * key_scale;
    if hold_circle_visible(progress) {
        let panel = ui_theme::style(UiScope::AmmoHint, &[UiClass::Panel]);
        panel.circle(center, radius, HOLD_BACKPLATE, SUPPLY_GOLD);
        let fill_radius = (radius - panel.border_width.unwrap_or(0.)).max(0.);
        let fill = ui_theme::style(UiScope::AmmoHint, &[UiClass::Accent]).tint(SUPPLY_GOLD);
        for [a, b, c] in clockwise_fill_triangles(center, fill_radius, progress) {
            draw_triangle(a, b, c, fill);
        }
    }
    // The key stays legible both on translucent black and on the filled gold.
    centered_text("F", center.x, center.y + 7. * key_scale, 23, WHITE);
    centered_text(
        "HOLD TO REFILL AMMO",
        center.x,
        center.y + radius + label.size(19.) + 4.,
        19,
        WHITE,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::Command;
    struct ThemeReset;
    impl Drop for ThemeReset {
        fn drop(&mut self) {
            ui_theme::set_theme(ui_theme::UiTheme::default());
        }
    }
    #[test]
    fn styled_hint_measures_and_centers_exact_drawn_font() {
        let _reset = ThemeReset;
        ui_theme::set_theme(
            ui_theme::UiTheme::parse(
                "test.css",
                "#ammo-hint .label {font-size:30.5px;opacity:.5}",
            )
            .unwrap(),
        );
        let center = vec2(400., 240.);
        begin_frame(800, 600, 1.).unwrap();
        draw_ammo_supply_hint(
            SupplyFocus {
                screen_anchor: center,
                world_anchor: Vec3::ZERO,
                distance: 1.,
            },
            0.,
            false,
        );
        let list = take_draw_list().unwrap();
        let mut texts = 0;
        for command in list.commands {
            if let Command::Text {
                text,
                baseline,
                size,
                color,
            } = command
            {
                assert_eq!(size, 30.5);
                if color.r == 1. {
                    let width = measure_text(&text, None, 1, size).width;
                    assert!((baseline.x + width * 0.5 - center.x).abs() < 0.001);
                    assert_eq!(color.a, 0.5);
                    texts += 1;
                }
            }
        }
        assert_eq!(texts, 2);
    }
    #[test]
    fn theme_does_not_make_cancelled_or_full_ammo_hold_circle_visible() {
        let _reset = ThemeReset;
        ui_theme::set_theme(
            ui_theme::UiTheme::parse(
                "test.css",
                "#ammo-hint .panel {background-color:#f00;border-width:4px}",
            )
            .unwrap(),
        );
        let focus = SupplyFocus {
            screen_anchor: vec2(400., 240.),
            world_anchor: Vec3::ZERO,
            distance: 1.,
        };
        for (progress, full, expected_texts) in
            [(0., false, 4), (0.5, true, 2), (f32::NAN, false, 4)]
        {
            begin_frame(800, 600, 1.).unwrap();
            draw_ammo_supply_hint(focus, progress, full);
            let list = take_draw_list().unwrap();
            assert!(list
                .commands
                .iter()
                .all(|command| matches!(command, Command::Camera(_) | Command::Text { .. })));
            assert_eq!(
                list.commands
                    .iter()
                    .filter(|command| matches!(command, Command::Text { .. }))
                    .count(),
                expected_texts
            );
        }
    }
}
