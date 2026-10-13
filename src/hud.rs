//! In-game HUD on the FIELD design system (RHS059/game_pd_ui, Operator theme):
//! title-safe clusters on feathered scrim shades, a haloed reticle, and FIELD type tokens.
use crate::action::ActionPhase;
use crate::draw::facade::*;
use crate::field_ui::{self as field, size, type_px};
use crate::platform::runtime::{get_fps, screen_height, screen_width};
use crate::ui_theme::{self, UiClass, UiScope, UiStyle};
use crate::{
    settings::Settings,
    sim::{Simulation, MAGAZINE, SPRINT_DURATION},
};
use glam::{vec3, Mat4, Vec3};
/// World-space marker colours used outside the HUD (impact spheres).
pub const INK: Color = Color::new(0.035, 0.055, 0.072, 1.);
pub const CYAN: Color = Color::new(0.33, 0.84, 0.87, 1.);
/// HUD roles, kept as public names for callers outside this module.
pub const ACCENT: Color = field::ACCENT;
pub const MUTED: Color = field::TEXT2;
/// HUD text, snapped to whole pixels so the bundled pixel font stays crisp.
pub fn label(text: &str, x: f32, y: f32, size: f32, color: Color) {
    label_style(color).text(text, x.round(), y.round(), size, color);
}
/// Raised menu-style panel (debug readouts, warnings), FIELD surface + hairline.
pub fn panel(x: f32, y: f32, w: f32, h: f32) {
    ui_theme::style(UiScope::Hud, &[UiClass::Panel]).rect(
        Rect::new(x, y, w, h),
        Color::new(
            field::SURFACE.r,
            field::SURFACE.g,
            field::SURFACE.b,
            field::SCRIM_ALPHA,
        ),
        field::TEXT3,
        1.,
    );
}
fn label_style(color: Color) -> UiStyle {
    let class = if color == MUTED || color == field::TEXT3 {
        UiClass::Muted
    } else if color == YELLOW || color == field::WARNING || color == field::CRITICAL {
        UiClass::Warning
    } else if color == ACCENT || color == CYAN {
        UiClass::Accent
    } else {
        UiClass::Label
    };
    ui_theme::style(UiScope::Hud, &[UiClass::Label, class])
}
fn hud_rectangle(x: f32, y: f32, w: f32, h: f32, color: Color) {
    let class = if color == ACCENT || color == CYAN {
        UiClass::Accent
    } else {
        UiClass::Muted
    };
    draw_rectangle(
        x,
        y,
        w,
        h,
        ui_theme::style(UiScope::Hud, &[class]).tint(color),
    );
}
/// Text on a FIELD tag plate. Returns the plate.
fn plated(text: &str, x: f32, baseline: f32, px: f32, color: Color, s: f32) -> Rect {
    let style = label_style(color);
    let dims = style.measure(text, px);
    let (x, baseline) = (x.round(), baseline.round());
    let plate = field::tag_plate(x, baseline, dims, s);
    style.text(text, x, baseline, px, color);
    plate
}
fn centered_plated(text: &str, cx: f32, baseline: f32, px: f32, color: Color, s: f32) {
    let width = label_style(color).measure(text, px).width;
    plated(text, cx - width * 0.5, baseline, px, color, s);
}
/// FIELD notification (§7.10): left column, mid-height, on a scrim plate.
fn draw_notice(notice: &str, screen_width: f32, screen_height: f32) {
    let s = field::scale(screen_height);
    let (inset_x, _) = field::safe_inset(screen_width, screen_height);
    let px = type_px(size::LABEL, s);
    let baseline = screen_height * 0.42;
    let plate = plated(notice, inset_x, baseline, px, field::TEXT, s);
    // Category rule on the leading edge (FIELD `.h-notes`: objective tone).
    hud_rectangle(
        plate.x,
        plate.y,
        (4. * s).max(1.),
        plate.h,
        field::OBJECTIVE,
    );
}

pub fn telemetry_indicator(status: &str) {
    draw_telemetry_indicator(status, screen_width(), screen_height());
}
fn draw_telemetry_indicator(status: &str, width: f32, height: f32) {
    if status.is_empty() || width <= 0. || height <= 0. {
        return;
    }
    let margin_x = 16_f32.min(width * 0.25);
    let margin_y = 8_f32.min(height * 0.25);
    let panel_width = width - 2. * margin_x;
    let inset = 10_f32.min(panel_width * 0.25);
    let style = label_style(ACCENT);
    let text = style.fit_text(status, 16., panel_width - 2. * inset);
    let metrics = style.measure(&text, 16.);
    let natural_height = metrics.height.max(20.) + 16.;
    let scale = ((height - 2. * margin_y) / natural_height).min(1.);
    let panel_height = natural_height * scale;
    let y = height - margin_y - panel_height;
    panel(margin_x, y, panel_width, panel_height);
    style.text_scaled(
        &text,
        margin_x + inset,
        y + (8. + metrics.offset_y) * scale,
        16.,
        ACCENT,
        scale,
    );
}

/// Action state readout and interaction prompts (§7.9: below centre, outside the
/// 120 ref-px reticle clear zone).
pub fn action_hud(sim: &Simulation, w: f32, h: f32) {
    let s = field::scale(h);
    let (inset_x, inset_y) = field::safe_inset(w, h);
    let p = &sim.player;
    let pose = sim.action_pose();
    if let Some(slot) = pose.slot {
        let phase = match pose.phase {
            ActionPhase::Entry => "entry",
            ActionPhase::Active => "active",
            ActionPhase::Exit => "exit",
            ActionPhase::Interrupted => "interrupted",
        };
        label(
            &format!(
                "{} / {} {:.2}{}",
                slot.name(),
                phase,
                pose.normalized,
                if pose.placeholder {
                    "  [PLACEHOLDER ANIM]"
                } else {
                    ""
                }
            ),
            inset_x,
            h - inset_y - 200. * s,
            type_px(size::SMALL, s),
            field::WARNING,
        );
    }
    let hint = match p.action {
        crate::sim::Action::Hang(_) => Some("[Space] Pull up   [Ctrl] Drop   [2] Sidearm"),
        _ if p.mount.is_some() => Some("[V] Release mount"),
        _ => None,
    };
    if let Some(hint) = hint {
        centered_plated(
            hint,
            w * 0.5,
            h * 0.62,
            type_px(size::LABEL, s),
            field::TEXT,
            s,
        );
    }
    if p.obstruction.fire_blocked {
        centered_plated(
            "WEAPON BLOCKED",
            w * 0.5,
            h * 0.5 + 160. * s,
            type_px(size::LABEL, s),
            field::WARNING,
            s,
        );
    }
    if let Some(since) = p.dead_since {
        // Meta layer: capped tint, never the only cue (§7.4).
        hud_rectangle(
            0.,
            0.,
            w,
            h,
            Color::new(
                field::CRITICAL.r,
                field::CRITICAL.g,
                field::CRITICAL.b,
                0.25,
            ),
        );
        centered_plated(
            &format!("DOWN  {:.1}", (sim.time - since).max(0.)),
            w * 0.5,
            h * 0.5 - 160. * s,
            type_px(size::H1, s),
            field::TEXT,
            s,
        );
    }
}
/// FIELD showcase type size: a reference-px token at this screen scale, with the
/// legibility floor. (The showcase sizes its HUD at 1:1 reference px.)
fn fpx(token: f32, s: f32) -> f32 {
    (token * s).max(field::MIN_TEXT_PX)
}
/// HUD shape colour under the HUD scope's theme opacity.
fn shade_of(color: Color) -> Color {
    ui_theme::style(UiScope::Hud, &[]).apply_opacity(color)
}
/// Down-pointing enemy chevron with a halo, its top edge centred on `top`.
fn chevron(cx: f32, top: f32, width: f32, height: f32, color: Color, s: f32) {
    let halo = (2. * s).max(1.);
    draw_triangle(
        vec2(cx - width * 0.5 - halo * 1.5, top - halo),
        vec2(cx + width * 0.5 + halo * 1.5, top - halo),
        vec2(cx, top + height + halo * 2.),
        shade_of(Color::new(
            field::HALO.r,
            field::HALO.g,
            field::HALO.b,
            color.a,
        )),
    );
    draw_triangle(
        vec2(cx - width * 0.5, top),
        vec2(cx + width * 0.5, top),
        vec2(cx, top + height),
        shade_of(color),
    );
}
/// Keyboard glyph (FIELD `.glyph`): key text in a 2 ref-px box of its colour.
fn key_glyph(key: &str, cx: f32, top: f32, px: f32, color: Color, s: f32) -> f32 {
    let dims = label_style(color).measure(key, px);
    let pad = 5. * s;
    let bw = (dims.width + 2. * pad).max(px * 1.4);
    let bh = dims.height + 2. * pad;
    let x = cx - bw * 0.5;
    draw_rectangle_lines(x, top, bw, bh, (2. * s).max(1.), shade_of(color));
    label(
        key,
        cx - dims.width * 0.5,
        top + pad + dims.offset_y,
        px,
        color,
    );
    bh
}
/// Compass heading in degrees clockwise from north (-Z), 0..360.
fn heading_degrees(yaw: f32) -> f32 {
    (yaw.to_degrees() + 90.).rem_euclid(360.)
}
/// Bearing from `from` to `to` in the same frame as `heading_degrees`.
fn bearing_degrees(from: Vec3, to: Vec3) -> f32 {
    (to.x - from.x)
        .atan2(-(to.z - from.z))
        .to_degrees()
        .rem_euclid(360.)
}
fn live_targets(sim: &Simulation) -> impl Iterator<Item = (usize, &crate::sim::Target)> {
    sim.targets
        .iter()
        .enumerate()
        .filter(|(_, t)| t.health > 0. && t.respawn <= 0.)
}

#[allow(clippy::too_many_arguments)]
pub fn hud(
    sim: &Simulation,
    cfg: &Settings,
    hit_timer: f32,
    head: bool,
    debug: bool,
    recording: bool,
    notice: &str,
    notice_timer: f32,
    weapon_label: &str,
) {
    let (w, h) = (screen_width(), screen_height());
    let s = field::scale(h);
    let (inset_x, inset_y) = field::safe_inset(w, h);
    let p = &sim.player;

    draw_markers(sim, cfg, w, h, s);
    draw_minimap(sim, inset_x, inset_y, s);
    draw_compass(sim, w, inset_y, s);
    draw_score(sim, w, inset_x, inset_y, s);
    draw_feed(sim, w, inset_x, inset_y + 76. * s, s);

    // Centre: reticle (§7.1) and hit feedback (§7.2), showcase geometry.
    let (x, y) = (w * 0.5, h * 0.5);
    if p.ads < 0.95 {
        let fov =
            cfg.fov + (cfg.ads_fov - cfg.fov) * crate::reference_motion::visual_world_ads(p.ads);
        let spread = (sim.spread_degrees(cfg).to_radians().tan() * w
            / (2. * (fov.to_radians() * 0.5).tan()))
        .max(12. * s);
        let arm = 12. * s;
        let stroke = (2. * s).max(1.);
        let c = ui_theme::style(UiScope::Hud, &[UiClass::Accent]).tint(Color::new(
            field::TEXT.r,
            field::TEXT.g,
            field::TEXT.b,
            1. - p.ads,
        ));
        for (a, b) in [
            (vec2(x - spread - arm, y), vec2(x - spread, y)),
            (vec2(x + spread, y), vec2(x + spread + arm, y)),
            (vec2(x, y - spread - arm), vec2(x, y - spread)),
            (vec2(x, y + spread), vec2(x, y + spread + arm)),
        ] {
            field::halo_line(a, b, stroke, c, s);
        }
        field::halo_dot(vec2(x, y), (2. * s).max(1.), c, s);
    }
    if hit_timer > 0. {
        // Headshot: longer bars and the warning tone.
        let (len, c) = if head {
            (20. * s, field::WARNING)
        } else {
            (14. * s, field::TEXT)
        };
        let c = ui_theme::style(UiScope::Hud, &[UiClass::Accent]).tint(c);
        let inner = 20. * s - len * 0.5;
        for (dx, dy) in [(-1., -1.), (1., -1.), (-1., 1.), (1., 1.)] {
            let d = vec2(dx, dy).normalize();
            field::halo_line(
                vec2(x, y) + d * inner,
                vec2(x, y) + d * (inner + len),
                (3. * s).max(1.),
                c,
                s,
            );
        }
    }

    draw_bottom_clusters(sim, cfg, w, h, weapon_label);

    action_hud(sim, w, h);

    // Footer: input reminders, quiet text on a plate below the clusters' line.
    centered_plated(
        "[Esc] Pause   [F1] Telemetry   [F2] Reset",
        w * 0.5,
        h - inset_y,
        fpx(20., s),
        MUTED,
        s,
    );
    if notice_timer > 0. {
        draw_notice(notice, w, h);
    }
    if debug {
        let px = fpx(20., s);
        let row = px * 1.25;
        // Below the minimap.
        let top = inset_y + 290. * s;
        let rows = [
            format!("SIM 120 Hz   RENDER {} fps", get_fps()),
            format!(
                "TIME {:7.2} s   DIST {:6.1} m",
                sim.time, sim.stats.distance
            ),
            format!(
                "POS {:5.2} {:5.2} {:5.2}",
                p.position.x, p.position.y, p.position.z
            ),
            format!(
                "VEL {:5.2} {:5.2} {:5.2}",
                p.velocity.x, p.velocity.y, p.velocity.z
            ),
            format!(
                "ADS {:4.2}   FOV {:3.0}/{:3.0}",
                p.ads, cfg.fov, cfg.ads_fov
            ),
            format!(
                "RECOIL {:5.2} / {:5.2} deg",
                p.recoil.x.to_degrees(),
                p.recoil.y.to_degrees()
            ),
            format!(
                "SHOTS {}   HEADSHOTS {}",
                sim.stats.shots, sim.stats.headshots
            ),
            format!("F8 CSV   {}", if recording { "RECORDING" } else { "OFF" }),
        ];
        let width = rows
            .iter()
            .map(|r| label_style(MUTED).measure(r, px).width)
            .fold(0., f32::max);
        let gap = 8. * s;
        field::cluster_shade(
            Rect::new(
                inset_x - gap,
                top - gap,
                width + 2. * gap,
                row * rows.len() as f32 + 2. * gap,
            ),
            s,
        );
        for (i, text) in rows.iter().enumerate() {
            label(
                text,
                inset_x,
                top + px + i as f32 * row,
                px,
                if i == 7 && recording { ACCENT } else { MUTED },
            );
        }
    }
}

/// The world pass camera, lean roll included, so markers stay on their targets.
fn world_view_projection(sim: &Simulation, cfg: &Settings, w: f32, h: f32) -> Mat4 {
    let p = &sim.player;
    let fov = cfg.fov + (cfg.ads_fov - cfg.fov) * crate::reference_motion::visual_world_ads(p.ads);
    let aspect = w / h;
    let eye = p.eye();
    Mat4::perspective_rh_gl(
        2. * ((fov.to_radians() * 0.5).tan() / aspect).atan(),
        aspect,
        0.035,
        200.,
    ) * Mat4::look_at_rh(eye, eye + p.direction(), p.camera_up(cfg.action.lean_roll))
}
/// Spatial markers (§7.6): an enemy chevron and range tag over each live target.
fn draw_markers(sim: &Simulation, cfg: &Settings, w: f32, h: f32, s: f32) {
    let p = &sim.player;
    let alpha = 1. - p.ads;
    if alpha <= 0.05 || w <= 0. || h <= 0. {
        return;
    }
    let eye = p.eye();
    let view_projection = world_view_projection(sim, cfg, w, h);
    let px = fpx(26., s);
    let color = Color::new(field::ENEMY.r, field::ENEMY.g, field::ENEMY.b, alpha);
    for (_, t) in live_targets(sim) {
        let anchor = vec3(
            (t.bounds.min.x + t.bounds.max.x) * 0.5,
            t.bounds.max.y + 0.2,
            (t.bounds.min.z + t.bounds.max.z) * 0.5,
        );
        let clip = view_projection * anchor.extend(1.);
        if clip.w <= 0.035 {
            continue;
        }
        let ndc = clip.truncate() / clip.w;
        let (sx, sy) = ((ndc.x * 0.5 + 0.5) * w, (0.5 - ndc.y * 0.5) * h);
        if !(0. ..=w).contains(&sx) || !(0. ..=h).contains(&sy) {
            continue;
        }
        // Keep the 120 ref-px reticle clear zone (§7.1): fade out approaching it.
        let clear = 120. * s;
        let fade = ((vec2(sx - w * 0.5, sy - h * 0.5).length() - clear) / clear).clamp(0., 1.);
        if fade <= 0. {
            continue;
        }
        let color = Color::new(color.r, color.g, color.b, alpha * fade);
        let text = format!("{:.0} m", (anchor - eye).length());
        let dims = label_style(color).measure(&text, px);
        let baseline = (sy - dims.height + dims.offset_y).round();
        let (pad_x, pad_y) = (8. * s, 4. * s);
        let plate = Rect::new(
            (sx - dims.width * 0.5).round() - pad_x,
            baseline - dims.offset_y - pad_y,
            dims.width + 2. * pad_x,
            dims.height + 2. * pad_y,
        );
        // Tag plate (§3.3) that fades with its marker.
        draw_rectangle(
            plate.x,
            plate.y,
            plate.w,
            plate.h,
            ui_theme::style(UiScope::Hud, &[UiClass::Panel]).background(Color::new(
                field::SCRIM.r,
                field::SCRIM.g,
                field::SCRIM.b,
                field::SCRIM_ALPHA * color.a,
            )),
        );
        label(&text, (sx - dims.width * 0.5).round(), baseline, px, color);
        chevron(sx, plate.y - 26. * s, 24. * s, 20. * s, color, s);
    }
}

/// Minimap (§7.7): player-up, 250 ref-px square, live targets as enemy chevrons.
fn draw_minimap(sim: &Simulation, x: f32, y: f32, s: f32) {
    let size = 250. * s;
    let p = &sim.player;
    field::cluster_shade(Rect::new(x, y, size, size), s);
    let grid = shade_of(Color::new(field::TEXT.r, field::TEXT.g, field::TEXT.b, 0.1));
    for i in 1..5 {
        let o = i as f32 * 50. * s;
        draw_rectangle(x + o, y, 1., size, grid);
        draw_rectangle(x, y + o, size, 1., grid);
    }
    draw_rectangle_lines(
        x,
        y,
        size,
        size,
        (2. * s).max(1.),
        shade_of(Color::new(field::TEXT.r, field::TEXT.g, field::TEXT.b, 0.3)),
    );
    let centre = vec2(x + size * 0.5, y + size * 0.5);
    let forward = vec2(p.yaw.cos(), p.yaw.sin());
    let right = vec2(-forward.y, forward.x);
    // 2.5 ref px per metre: the map edge is 50 m out.
    let per_metre = 2.5 * s;
    let pad = 12. * s;
    for (_, t) in live_targets(sim) {
        let c = t.bounds.center();
        let d = vec2(c.x - p.position.x, c.z - p.position.z);
        let local = vec2(d.dot(right), -d.dot(forward)) * per_metre;
        let at =
            (centre + local).clamp(vec2(x + pad, y + pad), vec2(x + size - pad, y + size - pad));
        chevron(at.x, at.y - 8. * s, 18. * s, 16. * s, field::ENEMY, s);
    }
    // Player arrow.
    draw_triangle(
        centre + vec2(0., -14. * s),
        centre + vec2(-10. * s, 6. * s),
        centre + vec2(10. * s, 6. * s),
        shade_of(field::TEXT),
    );
}

/// Compass strip (§7.7): 720 ref px for 180°, cardinal labels, enemy bearings
/// above the line and the numeric heading below.
fn draw_compass(sim: &Simulation, w: f32, top: f32, s: f32) {
    let width = 720. * s;
    let left = w * 0.5 - width * 0.5;
    let line_y = top + 30. * s;
    let px = fpx(26., s);
    let heading = heading_degrees(sim.player.yaw);
    let per_degree = width / 180.;
    let offset = |bearing: f32| (bearing - heading + 540.).rem_euclid(360.) - 180.;
    field::cluster_shade(
        Rect::new(left - 24. * s, top - 26. * s, width + 48. * s, 76. * s),
        s,
    );
    draw_rectangle(
        left,
        line_y,
        width,
        (2. * s).max(1.),
        shade_of(Color::new(field::TEXT.r, field::TEXT.g, field::TEXT.b, 0.7)),
    );
    const CARDINALS: [&str; 8] = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    for i in 0..16 {
        let bearing = i as f32 * 22.5;
        let d = offset(bearing);
        if d.abs() > 88. {
            continue;
        }
        let cx = w * 0.5 + d * per_degree;
        if i % 2 == 0 {
            let text = CARDINALS[i / 2];
            let dims = label_style(field::TEXT).measure(text, px);
            label(
                text,
                (cx - dims.width * 0.5).round(),
                (line_y - 4. * s - dims.height + dims.offset_y).round(),
                px,
                field::TEXT,
            );
        } else {
            draw_rectangle(
                cx - s,
                line_y - 10. * s,
                (2. * s).max(1.),
                10. * s,
                shade_of(field::TEXT2),
            );
        }
    }
    for (_, t) in live_targets(sim) {
        let d = offset(bearing_degrees(sim.player.position, t.bounds.center()));
        if d.abs() <= 88. {
            chevron(
                w * 0.5 + d * per_degree,
                top - 22. * s,
                16. * s,
                14. * s,
                field::ENEMY,
                s,
            );
        }
    }
    // Heading readout, centred under the line: "NW 318°".
    let dir = CARDINALS[((heading + 22.5) / 45.) as usize % 8];
    let value = format!("{:03.0}°", heading.round() % 360.);
    let d1 = label_style(MUTED).measure(dir, px);
    let d2 = label_style(field::TEXT).measure(&value, px);
    let gap = 8. * s;
    let x = w * 0.5 - (d1.width + gap + d2.width) * 0.5;
    let base = (line_y + 10. * s + d1.offset_y.max(d2.offset_y)).round();
    label(dir, x, base, px, MUTED);
    label(&value, x + d1.width + gap, base, px, field::TEXT);
}

/// Score (top right): targets down in the friendly tone, session clock, accuracy.
fn draw_score(sim: &Simulation, w: f32, inset_x: f32, top: f32, s: f32) {
    let big = fpx(40., s);
    let small = fpx(28., s);
    let acc = if sim.stats.shots > 0 {
        sim.stats.hits as f32 / sim.stats.shots as f32 * 100.
    } else {
        0.
    };
    let secs = sim.time.max(0.) as u64;
    let parts = [
        (format!("{}", sim.stats.kills), big, field::FRIENDLY),
        (
            format!("{:02}:{:02}", secs / 60, secs % 60),
            small,
            field::TEXT,
        ),
        (format!("{acc:.0}%"), big, field::TEXT2),
    ];
    let gap = 16. * s;
    let dims: Vec<_> = parts
        .iter()
        .map(|(t, px, c)| label_style(*c).measure(t, *px))
        .collect();
    let width = dims.iter().map(|d| d.width).sum::<f32>() + gap * 2.;
    let ascent = dims.iter().map(|d| d.offset_y).fold(0., f32::max);
    let descent = dims
        .iter()
        .map(|d| d.height - d.offset_y)
        .fold(0., f32::max);
    let mut x = w - inset_x - width;
    field::cluster_shade(
        Rect::new(
            x - 16. * s,
            top - 10. * s,
            width + 32. * s,
            ascent + descent + 20. * s,
        ),
        s,
    );
    let base = (top + ascent).round();
    for ((text, px, color), d) in parts.iter().zip(&dims) {
        label(text, x, base, *px, *color);
        x += d.width + gap;
    }
}

/// Kill feed (§7.8): recent kills, newest first, while the target is down.
fn draw_feed(sim: &Simulation, w: f32, inset_x: f32, top: f32, s: f32) {
    let px = fpx(26., s);
    let (pad_x, pad_y, row_gap) = (12. * s, 5. * s, 6. * s);
    let mut y = top;
    let mut down: Vec<_> = sim
        .targets
        .iter()
        .enumerate()
        .filter(|(_, t)| t.respawn > 0.)
        .collect();
    // Most recent kill has the most respawn time left.
    down.sort_by(|a, b| b.1.respawn.total_cmp(&a.1.respawn));
    for (i, t) in down.into_iter().take(5) {
        let alpha = (t.respawn / 0.25).clamp(0., 1.);
        let you = Color::new(
            field::FRIENDLY.r,
            field::FRIENDLY.g,
            field::FRIENDLY.b,
            alpha,
        );
        let enemy = Color::new(field::ENEMY.r, field::ENEMY.g, field::ENEMY.b, alpha);
        let victim = format!("TARGET {}", i + 1);
        let d1 = label_style(you).measure("YOU", px);
        let d2 = label_style(enemy).measure(&victim, px);
        let arrow = 22. * s;
        let gap = 8. * s;
        let inner = d1.width + gap + arrow + gap + d2.width;
        let ascent = d1.offset_y.max(d2.offset_y);
        let row_h = ascent + (d1.height - d1.offset_y).max(d2.height - d2.offset_y) + 2. * pad_y;
        let right = w - inset_x;
        let left = right - inner - 2. * pad_x;
        draw_rectangle(
            left,
            y,
            right - left,
            row_h,
            shade_of(Color::new(
                field::SCRIM.r,
                field::SCRIM.g,
                field::SCRIM.b,
                field::SCRIM_ALPHA * alpha,
            )),
        );
        // Your kills carry the accent edge.
        draw_rectangle(
            left,
            y,
            3. * s,
            row_h,
            shade_of(Color::new(
                field::ACCENT.r,
                field::ACCENT.g,
                field::ACCENT.b,
                alpha,
            )),
        );
        let base = (y + pad_y + ascent).round();
        let mut x = left + pad_x;
        label("YOU", x, base, px, you);
        x += d1.width + gap;
        let mid = y + row_h * 0.5;
        let c = shade_of(Color::new(
            field::TEXT2.r,
            field::TEXT2.g,
            field::TEXT2.b,
            alpha,
        ));
        draw_line(x, mid, x + arrow, mid, (2. * s).max(1.), c);
        draw_line(
            x + arrow - 6. * s,
            mid - 5. * s,
            x + arrow,
            mid,
            (2. * s).max(1.),
            c,
        );
        draw_line(
            x + arrow - 6. * s,
            mid + 5. * s,
            x + arrow,
            mid,
            (2. * s).max(1.),
            c,
        );
        x += arrow + gap;
        label(&victim, x, base, px, enemy);
        y += row_h + row_gap;
    }
}

/// Bottom clusters use measured text extents, including the small-window font floor.
fn draw_bottom_clusters(sim: &Simulation, cfg: &Settings, w: f32, h: f32, weapon_label: &str) {
    let s = field::scale(h);
    let (inset_x, _) = field::safe_inset(w, h);
    let p = &sim.player;
    let bottom = h - 64. * s;
    let lbl_px = fpx(26., s);
    // Bottom right: ability slots, magazine, reserve, status and weapon (§7.5).
    {
        let mag_px = fpx(96., s);
        let mag = format!("{}", p.ammo);
        let reserve = format!("/ {}", p.reserve);
        let (mag_color, status) = if p.ammo == 0 {
            (field::CRITICAL, Some(("RELOAD  [R]", field::CRITICAL)))
        } else if p.ammo * 4 <= MAGAZINE {
            (field::WARNING, Some(("LOW AMMO", field::WARNING)))
        } else {
            (field::TEXT, None)
        };
        let state = if p.mantle.is_some() {
            Some("MANTLING")
        } else if p.reload_left > 0. {
            Some("RELOADING")
        } else if p.sprint_out > 0. {
            Some("RAISING WEAPON")
        } else {
            None
        };
        let line = state.map(|t| (t, MUTED)).or(status);
        let right = w - inset_x;
        let dm = label_style(mag_color).measure(&mag, mag_px);
        let dr = label_style(MUTED).measure(&reserve, lbl_px);
        let dw = label_style(MUTED).measure(weapon_label, lbl_px);
        let ds = line.map(|(t, c)| label_style(c).measure(t, lbl_px));
        let row = |d: &TextDimensions| d.height.max(lbl_px * 0.75) + 4. * s;
        // Stack bottom-up: weapon, status, reserve, magazine, slots.
        let wpn_top = bottom - row(&dw);
        let status_top = ds.as_ref().map_or(wpn_top, |d| wpn_top - row(d));
        let res_top = status_top - row(&dr);
        let mag_top = res_top - dm.height - 4. * s;
        let tac = (p.tac_charge / cfg.action.tac_sprint_duration.max(1e-3)).clamp(0., 1.);
        let slots = [
            ("MOUNT", "V", p.mount.is_some(), 1.),
            ("TAC", "2x", p.tac_sprint.is_some() || tac >= 1., tac),
        ];
        let slot_px = fpx(20., s);
        let pad = 5. * s;
        // 84 ref px, grown to fit its text where the legibility floor applies.
        let slot = slots
            .iter()
            .map(|(name, key, ..)| {
                let dn = label_style(MUTED).measure(name, slot_px);
                let dk = label_style(field::TEXT).measure(key, slot_px);
                (dn.width + 4. * pad)
                    .max(dn.height + dk.height + 8. * pad)
                    .max(dk.width + 6. * pad)
            })
            .fold(84. * s, f32::max);
        let slot_gap = 10. * s;
        let slots_top = mag_top - 12. * s - slot;
        let width = [
            dm.width,
            dr.width,
            dw.width,
            ds.map_or(0., |d| d.width),
            slot * 2. + slot_gap,
        ]
        .into_iter()
        .fold(0., f32::max);
        field::cluster_shade(
            Rect::new(
                right - width - 16. * s,
                slots_top - 10. * s,
                width + 32. * s,
                bottom - slots_top + 20. * s,
            ),
            s,
        );
        for (i, (name, key, ready, charge)) in slots.into_iter().enumerate() {
            let sx = right - slot * (2 - i) as f32 - slot_gap * (1 - i) as f32;
            draw_rectangle(
                sx,
                slots_top,
                slot,
                slot,
                shade_of(Color::new(
                    field::SCRIM.r,
                    field::SCRIM.g,
                    field::SCRIM.b,
                    0.7,
                )),
            );
            // Cooldown fills from the top as the scrim drains.
            if charge < 1. {
                draw_rectangle(
                    sx,
                    slots_top,
                    slot,
                    slot * (1. - charge),
                    shade_of(Color::new(
                        field::SCRIM.r,
                        field::SCRIM.g,
                        field::SCRIM.b,
                        0.75,
                    )),
                );
            }
            let (border, bw) = if ready {
                (field::ACCENT, 3. * s)
            } else {
                (
                    Color::new(field::TEXT.r, field::TEXT.g, field::TEXT.b, 0.35),
                    2. * s,
                )
            };
            draw_rectangle_lines(sx, slots_top, slot, slot, bw.max(1.), shade_of(border));
            let dn = label_style(MUTED).measure(name, slot_px);
            let glyph_h = label_style(field::TEXT).measure(key, slot_px).height + 2. * pad;
            let block = dn.height + 4. * s + glyph_h;
            let t0 = slots_top + (slot - block) * 0.5;
            label(
                name,
                sx + (slot - dn.width) * 0.5,
                t0 + dn.offset_y,
                slot_px,
                MUTED,
            );
            key_glyph(
                key,
                sx + slot * 0.5,
                t0 + dn.height + 4. * s,
                slot_px,
                field::TEXT,
                s,
            );
        }
        label(
            &mag,
            right - dm.width,
            (mag_top + dm.offset_y).round(),
            mag_px,
            mag_color,
        );
        label(
            &reserve,
            right - dr.width,
            (res_top + dr.offset_y).round(),
            lbl_px,
            MUTED,
        );
        if let (Some((text, color)), Some(d)) = (line, ds) {
            label(
                text,
                right - d.width,
                (status_top + d.offset_y).round(),
                lbl_px,
                color,
            );
        }
        label(
            weapon_label,
            right - dw.width,
            (wpn_top + dw.offset_y).round(),
            lbl_px,
            MUTED,
        );
        let progress = if let Some(mantle) = p.mantle {
            Some(mantle.progress())
        } else if p.reload_left > 0. {
            Some(1. - p.reload_left / p.reload_total)
        } else {
            None
        };
        if let Some(progress) = progress {
            let bar_y = res_top - 3. * s;
            let bar_w = width.max(dm.width);
            hud_rectangle(right - bar_w, bar_y, bar_w, (4. * s).max(1.), field::TRACK);
            hud_rectangle(
                right - bar_w,
                bar_y,
                bar_w * progress.clamp(0., 1.),
                (4. * s).max(1.),
                ACCENT,
            );
        }
    }

    // Bottom left: stance + stamina (accent meter) above health (white meter).
    {
        let stance = if p.dead() {
            "DOWN"
        } else if p.mantle.is_some_and(|m| m.from_hang) {
            "PULLING UP"
        } else if matches!(p.action, crate::sim::Action::Hang(_)) {
            "HANGING"
        } else if matches!(p.action, crate::sim::Action::Slide(_)) {
            "SLIDING"
        } else if matches!(p.action, crate::sim::Action::Dive(_)) {
            "DIVING"
        } else if p.mount.is_some() {
            "MOUNTED"
        } else if p.tac_sprint.is_some() {
            "TAC SPRINT"
        } else if p.mantle.is_some() {
            "MANTLING"
        } else if !p.grounded {
            "AIRBORNE"
        } else if p.prone {
            "PRONE"
        } else if p.crouched {
            "CROUCHED"
        } else if p.sprinting {
            "SPRINT"
        } else {
            "STANDING"
        };
        let x = inset_x;
        let seg_w = 78. * s;
        let gap = 5. * s;
        let width = seg_w * 4. + gap * 3.;
        let hp = p.health.clamp(0., 100.);
        let hp_color = if hp <= 25. {
            field::CRITICAL
        } else if hp <= 50. {
            field::WARNING
        } else {
            field::TEXT
        };
        let health = format!("HEALTH {:.0}", hp);
        let speed = format!("{} · {:.1} m/s", stance, p.speed());
        let dh = label_style(MUTED).measure(&health, lbl_px);
        let dsp = label_style(MUTED).measure(&speed, lbl_px);
        let bar_h = 12. * s;
        let hp_bar = bottom - bar_h;
        let hp_top = hp_bar - gap - dh.height;
        let st_bar = hp_top - 8. * s - 8. * s;
        let sp_top = st_bar - gap - dsp.height;
        let critical_px = fpx(28., s);
        let dc = label_style(field::CRITICAL).measure("CRITICAL", critical_px);
        // Reserve room for HEALTH and CRITICAL side by side, so they never overlap.
        let full = width.max(dh.width + 2. * gap + dc.width).max(dsp.width);
        field::cluster_shade(
            Rect::new(
                x - 16. * s,
                sp_top - 10. * s,
                full + 32. * s,
                bottom - sp_top + 20. * s,
            ),
            s,
        );
        label(&speed, x, (sp_top + dsp.offset_y).round(), lbl_px, MUTED);
        let stamina = p.stamina / SPRINT_DURATION;
        let fill = if stamina <= 0.25 {
            field::WARNING
        } else {
            field::ACCENT
        };
        field::segmented_bar(
            Rect::new(x, st_bar, width * 0.75, 8. * s),
            3,
            stamina,
            fill,
            s,
        );
        label(&health, x, (hp_top + dh.offset_y).round(), lbl_px, MUTED);
        field::segmented_bar(
            Rect::new(x, hp_bar, width, bar_h),
            4,
            hp / 100.,
            hp_color,
            s,
        );
        if hp <= 25. && !p.dead() {
            label(
                "CRITICAL",
                x + full - dc.width,
                (hp_top + dc.offset_y).round(),
                critical_px,
                field::CRITICAL,
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bottom_cluster_glyphs_do_not_overlap_across_states_and_viewports() {
        use crate::{draw::Command, render::text::TextRenderer};
        let _reset = ThemeReset;
        let mut renderer = TextRenderer::new().unwrap();
        for css in [
            "",
            include_str!("../ui/examples/high-contrast.css"),
            "#hud .label {font-size:21.5px}",
        ] {
            ui_theme::set_theme(ui_theme::UiTheme::parse("test.css", css).unwrap());
            for (w, h) in [(640, 360), (960, 540), (1920, 1080), (3840, 2160)] {
                for state in 0..6 {
                    let mut sim = Simulation::new();
                    match state {
                        1 => sim.player.ammo = 1,
                        2 => sim.player.ammo = 0,
                        3 => {
                            sim.player.reload_left = 1.;
                            sim.player.reload_total = 2.;
                        }
                        4 => sim.player.sprint_out = 1.,
                        5 => {
                            // Low health while prone: HEALTH and CRITICAL share a row.
                            sim.player.health = 25.;
                            sim.player.prone = true;
                        }
                        _ => {}
                    }
                    begin_frame(w, h, 1.).unwrap();
                    draw_bottom_clusters(&sim, &Settings::default(), w as f32, h as f32, "HK416");
                    let mut bounds = Vec::new();
                    for command in take_draw_list().unwrap().commands {
                        if let Command::Text {
                            text,
                            baseline,
                            size,
                            color,
                        } = command
                        {
                            let mut min = vec2(f32::INFINITY, f32::INFINITY);
                            let mut max = vec2(f32::NEG_INFINITY, f32::NEG_INFINITY);
                            for mesh in renderer.meshes(&text, baseline, size, color).unwrap() {
                                for vertex in mesh.vertices {
                                    min = min.min(vertex.position.truncate());
                                    max = max.max(vertex.position.truncate());
                                }
                            }
                            assert!(
                                min.x >= 0.
                                    && min.y >= 0.
                                    && max.x <= w as f32
                                    && max.y <= h as f32,
                                "{text} outside {w}x{h}: {min:?}..{max:?}"
                            );
                            bounds.push((text, min, max));
                        }
                    }
                    assert_eq!(bounds.len(), if state == 0 { 9 } else { 10 });
                    if state == 5 {
                        assert!(bounds.iter().any(|(text, ..)| text == "CRITICAL"));
                    }
                    for (i, (text, min, max)) in bounds.iter().enumerate() {
                        for (other, omin, omax) in &bounds[i + 1..] {
                            assert!(
                                max.x <= omin.x
                                    || omax.x <= min.x
                                    || max.y <= omin.y
                                    || omax.y <= min.y,
                                "{text} overlaps {other} at {w}x{h}, state {state}, CSS {css}"
                            );
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn markers_project_with_the_lean_rolled_world_camera() {
        let cfg = Settings::default();
        let mut sim = Simulation::new();
        let p = &sim.player;
        let probe = p.eye() + p.direction() * 10. + Vec3::Y;
        let project = |sim: &Simulation| {
            let clip = world_view_projection(sim, &cfg, 1920., 1080.) * probe.extend(1.);
            clip.x / clip.w
        };
        // Straight up from the view centre stays centred without lean...
        assert!(project(&sim).abs() < 1e-4);
        // ...and swings sideways as the world camera rolls with the lean.
        sim.player.lean_fraction = 1.;
        assert!(cfg.action.lean_roll > 0.);
        assert!(project(&sim).abs() > 0.01);
        let up = sim.player.camera_up(cfg.action.lean_roll);
        let p = &sim.player;
        let expected = Mat4::look_at_rh(p.eye(), p.eye() + p.direction(), up);
        let view = Mat4::look_at_rh(p.eye(), p.eye() + p.direction(), Vec3::Y);
        assert_ne!(expected, view);
    }

    #[test]
    fn persistent_telemetry_indicator_stays_inside_tiny_viewports() {
        use crate::draw::Command;
        let _reset = ThemeReset;
        for font in [6., 16., 96.] {
            ui_theme::set_theme(
                ui_theme::UiTheme::parse(
                    "test.css",
                    &format!("#hud .accent {{font-size:{font}px}}"),
                )
                .unwrap(),
            );
            for (width, height) in [
                (1, 1),
                (2, 800),
                (16, 16),
                (32, 800),
                (800, 1),
                (1920, 1080),
            ] {
                begin_frame(width, height, 1.).unwrap();
                draw_telemetry_indicator("RECORDING CSV + CPU trace", width as f32, height as f32);
                let list = take_draw_list().unwrap();
                let panels: Vec<_> = list
                    .commands
                    .iter()
                    .filter_map(|command| {
                        if let Command::Rect { rect, .. } = command {
                            Some(rect)
                        } else {
                            None
                        }
                    })
                    .collect();
                assert!(!panels.is_empty());
                for rect in panels {
                    assert!(rect.x >= 0. && rect.y >= 0. && rect.w >= 0. && rect.h >= 0.);
                    assert!(rect.x + rect.w <= width as f32 + 0.001);
                    assert!(rect.y + rect.h <= height as f32 + 0.001);
                }
            }
        }
    }
    #[test]
    fn themed_hud_label_emits_resolved_size_color_and_opacity() {
        ui_theme::set_theme(
            ui_theme::UiTheme::parse(
                "test.css",
                "#hud .muted {font-size:21.5px;color:#123456;opacity:.5}",
            )
            .unwrap(),
        );
        begin_frame(800, 600, 1.).unwrap();
        label("Telemetry", 10., 30., 16., MUTED);
        let list = take_draw_list().unwrap();
        ui_theme::set_theme(ui_theme::UiTheme::default());
        assert!(list.commands.iter().any(|command| matches!(command,
            crate::draw::Command::Text {text, size, color, ..} if text == "Telemetry"
                && *size == 21.5 && *color == Color::new(18./255., 52./255., 86./255., 0.5))));
    }
    struct ThemeReset;
    impl Drop for ThemeReset {
        fn drop(&mut self) {
            ui_theme::set_theme(ui_theme::UiTheme::default());
        }
    }
    #[test]
    fn default_notice_sits_in_left_column_on_a_scrim_plate() {
        use crate::draw::Command;
        let _reset = ThemeReset;
        ui_theme::set_theme(ui_theme::UiTheme::default());
        begin_frame(1920, 1080, 1.).unwrap();
        draw_notice("Theme reloaded: Gy_pq!", 1920., 1080.);
        let list = take_draw_list().unwrap();
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Rect {rect, color} if *color == field::SCRIM_86 && rect.x < 96. && rect.y < 1080. * 0.42)));
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Text {baseline, size, ..} if *baseline == vec2(96., (1080_f32 * 0.42).round())
                && *size == type_px(size::LABEL, 1.))));
    }
    #[test]
    fn themed_notice_panel_contains_actual_cpu_glyph_quads_at_accepted_sizes() {
        use crate::{draw::Command, render::text::TextRenderer};
        let _reset = ThemeReset;
        let mut renderer = TextRenderer::new().unwrap();
        for size in [6., 20., 21.5, 48., 96.] {
            ui_theme::set_theme(
                ui_theme::UiTheme::parse(
                    "test.css",
                    &format!("#hud .label {{font-size:{size}px}}"),
                )
                .unwrap(),
            );
            begin_frame(1920, 1080, 1.).unwrap();
            draw_notice("Theme reloaded: Gy_pq!", 1920., 1080.);
            let list = take_draw_list().unwrap();
            let panel = list
                .commands
                .iter()
                .find_map(|command| {
                    if let Command::Rect { rect, .. } = command {
                        Some(*rect)
                    } else {
                        None
                    }
                })
                .unwrap();
            let mut glyphs = 0;
            for command in list.commands {
                if let Command::Text {
                    text,
                    baseline,
                    size: actual_size,
                    color,
                } = command
                {
                    assert_eq!(actual_size, size);
                    for mesh in renderer
                        .meshes(&text, baseline, actual_size, color)
                        .unwrap()
                    {
                        for vertex in mesh.vertices {
                            assert!(
                                panel.contains(vertex.position.truncate()),
                                "{size}px glyph vertex {:?} escapes notice panel {panel:?}",
                                vertex.position
                            );
                        }
                        glyphs += 1;
                    }
                }
            }
            assert!(glyphs > 0);
        }
    }
}
