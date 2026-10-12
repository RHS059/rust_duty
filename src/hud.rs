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
    // Category rule on the leading edge, same shape language as the clusters.
    hud_rectangle(plate.x, plate.y, (3. * s).max(1.), plate.h, ACCENT);
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
            h * 0.5 + 200. * s,
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
    let label_px = type_px(size::LABEL, s);
    let small_px = type_px(size::SMALL, s);
    let gap = 8. * s;

    // Top centre: objective strip.
    {
        let text = "RANGE 01  ·  CLEAR THE LANE";
        let dims = label_style(field::TEXT).measure(text, label_px);
        let x = w * 0.5 - dims.width * 0.5;
        let baseline = inset_y + dims.offset_y;
        field::cluster_shade(
            Rect::new(
                x - gap,
                inset_y - gap,
                dims.width + 2. * gap,
                dims.height + 2. * gap,
            ),
            s,
        );
        hud_rectangle(
            x - gap,
            inset_y + dims.height + gap - (2. * s).max(1.),
            dims.width + 2. * gap,
            (2. * s).max(1.),
            ACCENT,
        );
        label(text, x, baseline, label_px, field::TEXT);
    }

    // Top right: score cluster.
    {
        let acc = if sim.stats.shots > 0 {
            sim.stats.hits as f32 / sim.stats.shots as f32 * 100.
        } else {
            0.
        };
        let line1 = format!(
            "{:02} TARGETS   {:03} HITS",
            sim.stats.kills, sim.stats.hits
        );
        let line2 = format!("ACCURACY  {:05.1}%", acc);
        let d1 = label_style(field::TEXT).measure(&line1, label_px);
        let d2 = label_style(MUTED).measure(&line2, small_px);
        let width = d1.width.max(d2.width);
        let x = w - inset_x - width;
        let row = label_px * 1.3;
        field::cluster_shade(
            Rect::new(
                x - gap,
                inset_y - gap,
                width + 2. * gap,
                row + d2.height + 2. * gap,
            ),
            s,
        );
        label(
            &line1,
            w - inset_x - d1.width,
            inset_y + d1.offset_y,
            label_px,
            field::TEXT,
        );
        label(
            &line2,
            w - inset_x - d2.width,
            inset_y + row + d2.offset_y,
            small_px,
            MUTED,
        );
    }

    // Centre: reticle (§7.1) and hit feedback (§7.2).
    let (x, y) = (w * 0.5, h * 0.5);
    if p.ads < 0.95 {
        let fov =
            cfg.fov + (cfg.ads_fov - cfg.fov) * crate::reference_motion::visual_world_ads(p.ads);
        let spread = (sim.spread_degrees(cfg).to_radians().tan() * w
            / (2. * (fov.to_radians() * 0.5).tan()))
        .max(2.);
        let arm = 10. * s;
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
        field::halo_dot(vec2(x, y), (1.5 * s).max(1.), c, s);
    }
    if hit_timer > 0. {
        // Headshot: larger and a tone change.
        let (inner, outer, c) = if head {
            (10. * s, 22. * s, field::WARNING)
        } else {
            (8. * s, 16. * s, field::TEXT)
        };
        let c = ui_theme::style(UiScope::Hud, &[UiClass::Accent]).tint(c);
        for (dx, dy) in [(-1., -1.), (1., -1.), (-1., 1.), (1., 1.)] {
            field::halo_line(
                vec2(x + dx * inner, y + dy * inner),
                vec2(x + dx * outer, y + dy * outer),
                (2.5 * s).max(1.),
                c,
                s,
            );
        }
    }

    // Bottom right: ammo and weapon (§7.5).
    {
        let hero_px = type_px(size::NUM_HERO, s);
        let mag = format!("{:02}", p.ammo);
        let reserve = format!("/ {:03}", p.reserve);
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
        let dm = label_style(mag_color).measure(&mag, hero_px);
        let dr = label_style(MUTED).measure(&reserve, label_px);
        let dw = label_style(MUTED).measure(weapon_label, small_px);
        let width = (dm.width + gap + dr.width).max(dw.width).max(200. * s);
        let x = w - inset_x - width;
        let bottom = h - inset_y;
        let bar_y = bottom - 4. * s;
        let mag_base = bar_y - 12. * s;
        let name_base = mag_base - dm.height - gap;
        let top = name_base - dw.offset_y;
        field::cluster_shade(
            Rect::new(
                x - gap,
                top - gap,
                width + 2. * gap,
                bottom - top + 2. * gap,
            ),
            s,
        );
        label(weapon_label, x, name_base, small_px, MUTED);
        label(&mag, x, mag_base, hero_px, mag_color);
        label(&reserve, x + dm.width + gap, mag_base, label_px, MUTED);
        let line = state.map(|t| (t, MUTED)).or(status);
        if let Some((text, color)) = line {
            let dt = label_style(color).measure(text, small_px);
            label(text, w - inset_x - dt.width, mag_base, small_px, color);
        }
        let progress = if let Some(mantle) = p.mantle {
            Some(mantle.progress())
        } else if p.reload_left > 0. {
            Some(1. - p.reload_left / p.reload_total)
        } else {
            None
        };
        if let Some(progress) = progress {
            hud_rectangle(x, bar_y, width, (4. * s).max(1.), field::TRACK);
            hud_rectangle(
                x,
                bar_y,
                width * progress.clamp(0., 1.),
                (4. * s).max(1.),
                ACCENT,
            );
        }
    }

    // Bottom left: stance, speed and stamina (§7.4 segmented meters).
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
        let width = 300. * s;
        let x = inset_x;
        let bottom = h - inset_y;
        let tac_y = bottom - (3. * s).max(1.);
        let bar_h = (8. * s).max(2.);
        let bar_y = tac_y - gap - bar_h;
        let ds = label_style(field::TEXT).measure(stance, label_px);
        let base = bar_y - gap * 1.5;
        let top = base - ds.offset_y;
        field::cluster_shade(
            Rect::new(
                x - gap,
                top - gap,
                width + 2. * gap,
                bottom - top + 2. * gap,
            ),
            s,
        );
        label(stance, x, base, label_px, field::TEXT);
        let speed = format!("{:04.1} m/s", p.speed());
        let dv = label_style(MUTED).measure(&speed, small_px);
        label(&speed, x + width - dv.width, base, small_px, MUTED);
        let stamina = p.stamina / SPRINT_DURATION;
        let fill = if stamina <= 0.25 {
            field::WARNING
        } else {
            field::TEXT2
        };
        field::segmented_bar(Rect::new(x, bar_y, width, bar_h), 4, stamina, fill, s);
        let tac = (p.tac_charge / cfg.action.tac_sprint_duration.max(1e-3)).min(1.);
        hud_rectangle(x, tac_y, width * tac, (3. * s).max(1.), ACCENT);
    }

    action_hud(sim, w, h);

    // Footer: input reminders, quiet text on a plate below the clusters' line.
    centered_plated(
        "[Esc] Pause   [F1] Telemetry   [F2] Reset",
        w * 0.5,
        h - inset_y,
        small_px,
        MUTED,
        s,
    );
    if notice_timer > 0. {
        draw_notice(notice, w, h);
    }
    if debug {
        let px = type_px(size::SMALL, s);
        let row = px * 1.25;
        let top = inset_y + label_px * 2.;
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

#[cfg(test)]
mod tests {
    use super::*;
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
