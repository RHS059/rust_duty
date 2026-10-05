use macroquad::prelude::*;
use vector_range::action::ActionPhase;
use vector_range::platform::runtime::{get_fps, screen_height, screen_width};
use vector_range::{
    settings::Settings,
    sim::{Simulation, SPRINT_DURATION},
};
pub(crate) const INK: Color = Color::new(0.035, 0.055, 0.072, 1.);
pub(crate) const ACCENT: Color = Color::new(0.98, 0.62, 0.22, 1.);
pub(crate) const CYAN: Color = Color::new(0.33, 0.84, 0.87, 1.);
pub(crate) const MUTED: Color = Color::new(0.62, 0.69, 0.72, 1.);
pub(crate) fn label(text: &str, x: f32, y: f32, size: f32, color: Color) {
    draw_text(text, x, y, size, color);
}
pub(crate) fn panel(x: f32, y: f32, w: f32, h: f32) {
    draw_rectangle(x, y, w, h, Color::new(0.025, 0.042, 0.058, 0.88));
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
        let width = measure_text(hint, None, 18, 1.).width;
        label(hint, w * 0.5 - width * 0.5, h * 0.5 + 80., 18., CYAN);
    }
    if p.obstruction.fire_blocked {
        label("WEAPON BLOCKED", w * 0.5 - 60., h * 0.5 + 54., 16., ACCENT);
    }
    if let Some(since) = p.dead_since {
        draw_rectangle(0., 0., w, h, Color::new(0.3, 0., 0., 0.35));
        let text = format!("DOWN  {:.1}", (sim.time - since).max(0.));
        let width = measure_text(&text, None, 40, 1.).width;
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
    draw_rectangle(24., 24., 4., 81., ACCENT);
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
        let c = Color::new(1., 1., 1., 1. - p.ads);
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
        let c = if head { ACCENT } else { WHITE };
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
        draw_rectangle(w - 232., h - 20., 190. * mantle.progress(), 3., CYAN);
    } else if p.reload_left > 0. {
        draw_rectangle(
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
    draw_rectangle(43., h - 58., 210., 4., Color::new(0.19, 0.25, 0.28, 1.));
    draw_rectangle(43., h - 58., 210. * p.stamina / SPRINT_DURATION, 4., ACCENT);
    draw_rectangle(
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
        let width = measure_text(notice, None, 20, 1.).width;
        panel(w * 0.5 - width * 0.5 - 18., 112., width + 36., 42.);
        label(notice, w * 0.5 - width * 0.5, 139., 20., CYAN);
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
