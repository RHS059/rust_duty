//! FIELD design-system tokens and HUD primitives (RHS059/game_pd_ui, Operator theme).
//!
//! Sizes are authored at the 1920x1080 reference and scaled by screen height, using
//! the FIELD desk platform factor (0.8). See game_pd_ui `DESIGN_SYSTEM.md`.
use crate::draw::{facade::*, Rect};

const fn hex(rgb: u32) -> Color {
    Color::new(
        ((rgb >> 16) & 0xff) as f32 / 255.,
        ((rgb >> 8) & 0xff) as f32 / 255.,
        (rgb & 0xff) as f32 / 255.,
        1.,
    )
}
const fn with_alpha(c: Color, a: f32) -> Color {
    Color::new(c.r, c.g, c.b, a)
}

// Operator colour roles (DESIGN_SYSTEM.md §3.2).
pub const SURFACE: Color = hex(0x0D1114);
pub const RAISED: Color = hex(0x161C20);
pub const SCRIM: Color = hex(0x080B0D);
pub const TEXT: Color = hex(0xF2F4F5);
pub const TEXT2: Color = hex(0xB9C1C6);
pub const TEXT3: Color = hex(0x8E989F);
pub const ACCENT: Color = hex(0xF2B33D);
pub const FRIENDLY: Color = hex(0x4AA8FF);
pub const ENEMY: Color = hex(0xFF6A3D);
pub const OBJECTIVE: Color = hex(0xF5D547);
pub const WARNING: Color = hex(0xFFB020);
pub const CRITICAL: Color = hex(0xFF6464);
pub const SUCCESS: Color = hex(0x4FD48D);
pub const FOCUS: Color = hex(0xFFFFFF);
pub const HALO: Color = hex(0x050708);
pub const SCRIM_ALPHA: f32 = 0.86;
/// Scrim at the tested 86 % opacity.
pub const SCRIM_86: Color = with_alpha(SCRIM, SCRIM_ALPHA);
/// Bar track behind segmented meters.
pub const TRACK: Color = with_alpha(TEXT3, 0.35);

/// Type scale tokens in reference px (§4.2).
pub mod size {
    pub const NUM_HERO: f32 = 64.;
    pub const H1: f32 = 56.;
    pub const H2: f32 = 40.;
    pub const BODY: f32 = 32.;
    pub const LABEL: f32 = 28.;
    pub const SMALL: f32 = 26.;
}
/// Desk/monitor platform factor (§4.3).
pub const DESK: f32 = 0.8;

/// Reference-pixel scale for a screen of the given height (1080p = 1.0).
pub fn scale(height: f32) -> f32 {
    (height / 1080.).max(0.)
}
/// Smallest rendered text in physical px (FIELD desk floor is 21 px at 1080p), so
/// small windows stay legible instead of following the 1080p scale below it.
pub const MIN_TEXT_PX: f32 = 16.;
/// Rendered text size for a type token at this screen scale.
pub fn type_px(token: f32, s: f32) -> f32 {
    (token * DESK * s).max(MIN_TEXT_PX)
}

/// Title-safe inset (inner 90 %, §6.2).
pub fn safe_inset(w: f32, h: f32) -> (f32, f32) {
    (w * 0.05, h * 0.05)
}

/// Cluster shade (§3.3): a solid 86 % scrim core under the content, feathered
/// 40 reference px outside it. Drawn outermost first, in four steps.
pub fn cluster_shade(core: Rect, s: f32) {
    let feather = 40. * s;
    for (step, alpha) in [(1.0, 0.10), (0.75, 0.16), (0.5, 0.22), (0.25, 0.30)] {
        let d = feather * step;
        draw_rectangle(
            core.x - d,
            core.y - d,
            core.w + 2. * d,
            core.h + 2. * d,
            with_alpha(SCRIM, alpha),
        );
    }
    draw_rectangle(core.x, core.y, core.w, core.h, SCRIM_86);
}

/// Tag plate (§3.3): single mid-screen label on 86 % scrim, 8 ref-px side padding.
pub fn tag_plate(text_x: f32, baseline: f32, dims: TextDimensions, s: f32) -> Rect {
    let pad_x = 8. * s;
    let pad_y = 4. * s;
    let r = Rect::new(
        text_x - pad_x,
        baseline - dims.offset_y - pad_y,
        dims.width + 2. * pad_x,
        dims.height + 2. * pad_y,
    );
    draw_rectangle(r.x, r.y, r.w, r.h, SCRIM_86);
    r
}

/// Line with a 2 ref-px halo outline: the reticle exception to backing (§3.3).
pub fn halo_line(a: Vec2, b: Vec2, stroke: f32, color: Color, s: f32) {
    let halo = (2. * s).max(1.);
    let dir = (b - a).normalize_or_zero() * halo;
    draw_line(
        a.x - dir.x,
        a.y - dir.y,
        b.x + dir.x,
        b.y + dir.y,
        stroke + 2. * halo,
        with_alpha(HALO, color.a),
    );
    draw_line(a.x, a.y, b.x, b.y, stroke, color);
}

pub fn halo_dot(center: Vec2, radius: f32, color: Color, s: f32) {
    draw_circle(
        center.x,
        center.y,
        radius + (2. * s).max(1.),
        with_alpha(HALO, color.a),
    );
    draw_circle(center.x, center.y, radius, color);
}

/// Segmented meter (§7.4): loss reads at a glance. `fraction` is clamped to 0..=1.
pub fn segmented_bar(r: Rect, segments: u32, fraction: f32, fill: Color, s: f32) {
    let segments = segments.max(1);
    let gap = (4. * s).max(1.);
    let seg_w = (r.w - gap * (segments - 1) as f32) / segments as f32;
    let filled = fraction.clamp(0., 1.) * segments as f32;
    for i in 0..segments {
        let x = r.x + i as f32 * (seg_w + gap);
        draw_rectangle(x, r.y, seg_w, r.h, TRACK);
        let part = (filled - i as f32).clamp(0., 1.);
        if part > 0. {
            draw_rectangle(x, r.y, seg_w * part, r.h, fill);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn operator_tokens_match_game_pd_ui() {
        assert_eq!(ACCENT, Color::new(242. / 255., 179. / 255., 61. / 255., 1.));
        assert_eq!(SCRIM_86.a, 0.86);
        assert_eq!(type_px(size::NUM_HERO, 1.), 51.2);
        assert_eq!(scale(2160.), 2.);
    }

    #[test]
    fn segmented_bar_fills_whole_and_partial_segments_in_order() {
        begin_frame(400, 100, 1.).unwrap();
        segmented_bar(Rect::new(0., 0., 100., 4.), 4, 0.6, ACCENT, 1.);
        let list = take_draw_list().unwrap();
        let fills: Vec<f32> = list
            .commands
            .iter()
            .filter_map(|c| match c {
                crate::draw::Command::Rect { rect, color } if *color == ACCENT => Some(rect.w),
                _ => None,
            })
            .collect();
        let seg = (100. - 3. * 4.) / 4.;
        assert_eq!(fills.len(), 3);
        assert!((fills[0] - seg).abs() < 1e-4 && (fills[1] - seg).abs() < 1e-4);
        assert!((fills[2] - seg * 0.4).abs() < 1e-3);
    }
}
