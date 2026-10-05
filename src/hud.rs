use vector_range::action::ActionPhase;
use vector_range::draw::facade::*;
use vector_range::platform::runtime::{get_fps, screen_height, screen_width};
use vector_range::ui_theme::{self, UiClass, UiScope, UiStyle};
use vector_range::{
    settings::Settings,
    sim::{Simulation, SPRINT_DURATION},
};
pub(crate) const INK: Color = Color::new(0.035, 0.055, 0.072, 1.);
pub(crate) const ACCENT: Color = Color::new(0.98, 0.62, 0.22, 1.);
pub(crate) const CYAN: Color = Color::new(0.33, 0.84, 0.87, 1.);
pub(crate) const MUTED: Color = Color::new(0.62, 0.69, 0.72, 1.);
pub(crate) fn label(text: &str, x: f32, y: f32, size: f32, color: Color) {
    label_style(color).text(text, x, y, size, color);
}
pub(crate) fn panel(x: f32, y: f32, w: f32, h: f32) {
    ui_theme::style(UiScope::Hud, &[UiClass::Panel]).rect(
        Rect::new(x, y, w, h),
        Color::new(0.025, 0.042, 0.058, 0.88),
        MUTED,
        1.,
    );
}
fn label_style(color: Color) -> UiStyle {
    let class = if color == MUTED {
        UiClass::Muted
    } else if color == YELLOW {
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
/// Grow around the resolved glyph ascent/descent, keeping the original 20px
/// notice padding and coordinates when the theme does not enlarge the text.
fn draw_notice(notice: &str, screen_width: f32) {
    let style = label_style(CYAN);
    let metrics = style.measure(notice, 20.);
    let original = UiStyle::default().measure(notice, 20.);
    let top_padding = (27. - original.offset_y).max(0.);
    let bottom_padding = (15. - (original.height - original.offset_y)).max(0.);
    let baseline = 139_f32.max(112. + top_padding + metrics.offset_y);
    let height = 42_f32.max(baseline - 112. + metrics.height - metrics.offset_y + bottom_padding);
    let x = screen_width * 0.5 - metrics.width * 0.5;
    panel(x - 18., 112., metrics.width + 36., height);
    style.text(notice, x, baseline, 20., CYAN);
}

/// Action state readout. Visuals are placeholders until authored clips pass review.
pub(crate) fn action_hud(sim: &Simulation, w: f32, h: f32) {
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
            24.,
            h - 118.,
            15.,
            YELLOW,
        );
    }
    let hint = match p.action {
        vector_range::sim::Action::Hang(_) => Some("SPACE PULL UP / CTRL DROP / 2 SIDEARM"),
        _ if p.mount.is_some() => Some("MOUNTED: V OR MOVE TO RELEASE"),
        _ => None,
    };
    if let Some(hint) = hint {
        let width = label_style(CYAN).measure(hint, 18.).width;
        label(hint, w * 0.5 - width * 0.5, h * 0.5 + 80., 18., CYAN);
    }
    if p.obstruction.fire_blocked {
        label("WEAPON BLOCKED", w * 0.5 - 60., h * 0.5 + 54., 16., ACCENT);
    }
    if let Some(since) = p.dead_since {
        hud_rectangle(0., 0., w, h, Color::new(0.3, 0., 0., 0.35));
        let text = format!("DOWN  {:.1}", (sim.time - since).max(0.));
        let width = label_style(WHITE).measure(&text, 40.).width;
        label(&text, w * 0.5 - width * 0.5, h * 0.5, 40., WHITE);
    }
}
#[allow(clippy::too_many_arguments)]
pub(crate) fn hud(
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
    let p = &sim.player;
    panel(24., 24., 288., 81.);
    hud_rectangle(24., 24., 4., 81., ACCENT);
    label("VECTOR / RANGE 01", 43., 54., 25., WHITE);
    label("ORIGINAL RUST FEEL LAB", 43., 80., 15., MUTED);
    let acc = if sim.stats.shots > 0 {
        sim.stats.hits as f32 / sim.stats.shots as f32 * 100.
    } else {
        0.
    };
    panel(w - 275., 24., 251., 81.);
    label(
        &format!(
            "{:02} TARGETS   {:03} HITS",
            sim.stats.kills, sim.stats.hits
        ),
        w - 255.,
        55.,
        19.,
        WHITE,
    );
    label(
        &format!("ACCURACY  {:05.1}%", acc),
        w - 255.,
        82.,
        17.,
        CYAN,
    );
    let (x, y) = (w * 0.5, h * 0.5);
    if p.ads < 0.95 {
        let fov = cfg.fov
            + (cfg.ads_fov - cfg.fov) * vector_range::reference_motion::visual_world_ads(p.ads);
        let gap = (sim.spread_degrees(cfg).to_radians().tan() * w
            / (2. * (fov.to_radians() * 0.5).tan()))
        .max(2.);
        let c = ui_theme::style(UiScope::Hud, &[UiClass::Accent]).tint(Color::new(
            1.,
            1.,
            1.,
            1. - p.ads,
        ));
        for (a, b) in [
            (vec2(x - gap - 7., y), vec2(x - gap, y)),
            (vec2(x + gap, y), vec2(x + gap + 7., y)),
            (vec2(x, y - gap - 7.), vec2(x, y - gap)),
            (vec2(x, y + gap), vec2(x, y + gap + 7.)),
        ] {
            draw_line(a.x, a.y, b.x, b.y, 1.5, c);
        }
        draw_circle(x, y, 1.5, c);
    }
    if hit_timer > 0. {
        let c = ui_theme::style(UiScope::Hud, &[UiClass::Accent]).tint(if head {
            ACCENT
        } else {
            WHITE
        });
        for (dx, dy) in [(-1., -1.), (1., -1.), (-1., 1.), (1., 1.)] {
            draw_line(x + dx * 7., y + dy * 7., x + dx * 13., y + dy * 13., 2., c);
        }
    }
    panel(w - 250., h - 125., 226., 101.);
    label(weapon_label, w - 231., h - 101., 16., MUTED);
    label(
        &format!("{:02}", p.ammo),
        w - 232.,
        h - 55.,
        47.,
        if p.ammo < 8 { ACCENT } else { WHITE },
    );
    label(
        &format!("/ {:03}", p.reserve),
        w - 158.,
        h - 57.,
        23.,
        MUTED,
    );
    label(
        if p.mantle.is_some() {
            "MANTLING"
        } else if p.reload_left > 0. {
            "RELOADING"
        } else if p.sprint_out > 0. {
            "RAISING WEAPON"
        } else {
            "PROVISIONAL PRESET"
        },
        w - 231.,
        h - 35.,
        13.,
        CYAN,
    );
    if let Some(mantle) = p.mantle {
        hud_rectangle(w - 232., h - 20., 190. * mantle.progress(), 3., CYAN);
    } else if p.reload_left > 0. {
        hud_rectangle(
            w - 232.,
            h - 20.,
            190. * (1. - p.reload_left / p.reload_total),
            3.,
            ACCENT,
        );
    }
    panel(24., h - 105., 248., 81.);
    let stance = if p.dead() {
        "DOWN"
    } else if p.mantle.is_some_and(|m| m.from_hang) {
        "PULLING UP"
    } else if matches!(p.action, vector_range::sim::Action::Hang(_)) {
        "HANGING"
    } else if matches!(p.action, vector_range::sim::Action::Slide(_)) {
        "SLIDING"
    } else if matches!(p.action, vector_range::sim::Action::Dive(_)) {
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
    label(stance, 43., h - 77., 17., WHITE);
    label(&format!("{:04.1} m/s", p.speed()), 173., h - 77., 17., CYAN);
    hud_rectangle(43., h - 58., 210., 4., Color::new(0.19, 0.25, 0.28, 1.));
    hud_rectangle(43., h - 58., 210. * p.stamina / SPRINT_DURATION, 4., ACCENT);
    hud_rectangle(
        43.,
        h - 52.,
        210. * (p.tac_charge / cfg.action.tac_sprint_duration.max(1e-3)).min(1.),
        2.,
        CYAN,
    );
    action_hud(sim, w, h);
    label(
        "SHIFT SPRINT / CTRL CROUCH / Z PRONE",
        43.,
        h - 37.,
        12.,
        MUTED,
    );
    label(
        "ESC PAUSE / SETTINGS    F1 TELEMETRY    F2 RESET",
        w * 0.5 - 195.,
        h - 27.,
        13.,
        MUTED,
    );
    if notice_timer > 0. {
        draw_notice(notice, w);
    }
    if debug {
        panel(24., 119., 310., 207.);
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
        for (i, row) in rows.iter().enumerate() {
            label(
                row,
                40.,
                145. + i as f32 * 23.,
                16.,
                if i == 7 && recording { ACCENT } else { MUTED },
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
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
            vector_range::draw::Command::Text {text, size, color, ..} if text == "Telemetry"
                && *size == 21.5 && *color == Color::new(18./255., 52./255., 86./255., 0.5))));
    }
    struct ThemeReset;
    impl Drop for ThemeReset {
        fn drop(&mut self) {
            ui_theme::set_theme(ui_theme::UiTheme::default());
        }
    }
    #[test]
    fn default_notice_preserves_original_panel_and_baseline() {
        use vector_range::draw::Command;
        let _reset = ThemeReset;
        ui_theme::set_theme(ui_theme::UiTheme::default());
        let notice = "Theme reloaded: Gy_pq!";
        let width = measure_text(notice, None, 20, 1.).width;
        begin_frame(1920, 1080, 1.).unwrap();
        draw_notice(notice, 1920.);
        let list = take_draw_list().unwrap();
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Rect {rect, ..} if *rect == Rect::new(960. - width * 0.5 - 18., 112., width + 36., 42.))));
        assert!(list.commands.iter().any(|command| matches!(command,
            Command::Text {baseline, size, ..} if *baseline == vec2(960. - width * 0.5, 139.) && *size == 20.)));
    }
    #[test]
    fn themed_notice_panel_contains_actual_cpu_glyph_quads_at_accepted_sizes() {
        use vector_range::{draw::Command, render::text::TextRenderer};
        let _reset = ThemeReset;
        let mut renderer = TextRenderer::new().unwrap();
        for size in [6., 20., 21.5, 48., 96.] {
            ui_theme::set_theme(
                ui_theme::UiTheme::parse(
                    "test.css",
                    &format!("#hud .accent {{font-size:{size}px}}"),
                )
                .unwrap(),
            );
            begin_frame(1920, 1080, 1.).unwrap();
            draw_notice("Theme reloaded: Gy_pq!", 1920.);
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
