//! Screen-space presentation for the world-anchored ammunition interaction.
use crate::ammo_supply::SupplyFocus;
use macroquad::prelude::*;

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
    let measure = measure_text(text, None, size, 1.);
    let x = center_x - measure.width * 0.5;
    draw_text(
        text,
        x + 1.,
        baseline_y + 1.,
        size as f32,
        Color::new(0., 0., 0., 0.70),
    );
    draw_text(text, x, baseline_y, size as f32, color);
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
    if hold_circle_visible(progress) {
        draw_circle(center.x, center.y, CIRCLE_RADIUS, HOLD_BACKPLATE);
        for [a, b, c] in clockwise_fill_triangles(center, CIRCLE_RADIUS, progress) {
            draw_triangle(a, b, c, SUPPLY_GOLD);
        }
    }
    // The key stays legible both on translucent black and on the filled gold.
    centered_text("F", center.x, center.y + 7., 23, WHITE);
    centered_text("HOLD TO REFILL AMMO", center.x, center.y + 42., 19, WHITE);
}
