mod sound;
use macroquad::prelude::*;
use std::{fs::File, io::Write};
use vector_range::control::IntentLatch;
use vector_range::{
    settings::Settings,
    sim::{Input, Shot, Simulation, FIXED_DT, SPRINT_DURATION},
};
const INK: Color = Color::new(0.035, 0.055, 0.072, 1.);
const ACCENT: Color = Color::new(0.98, 0.62, 0.22, 1.);
const CYAN: Color = Color::new(0.33, 0.84, 0.87, 1.);
const MUTED: Color = Color::new(0.62, 0.69, 0.72, 1.);
fn config() -> Conf {
    Conf {
        window_title: "VECTOR RANGE | Original Rust FPS laboratory".into(),
        window_width: 1440,
        window_height: 900,
        high_dpi: true,
        sample_count: 4,
        ..Default::default()
    }
}
struct Trace {
    shot: Shot,
    life: f32,
}
struct Impact {
    point: Vec3,
    life: f32,
    target: bool,
}
fn label(text: &str, x: f32, y: f32, size: f32, color: Color) {
    draw_text(text, x, y, size, color);
}
fn panel(x: f32, y: f32, w: f32, h: f32) {
    draw_rectangle(x, y, w, h, Color::new(0.025, 0.042, 0.058, 0.88));
}
fn h_fov_to_v(h: f32, aspect: f32) -> f32 {
    2. * ((h.to_radians() * 0.5).tan() / aspect).atan()
}
fn grid_texture() -> Texture2D {
    let mut im = Image::gen_image_color(256, 256, WHITE);
    for y in 0..256 {
        for x in 0..256 {
            let check = if (x / 32 + y / 32) % 2 == 0 {
                0.88
            } else {
                0.96
            };
            let value = if x < 3 || y < 3 || x > 252 || y > 252 {
                0.46
            } else if x % 32 < 1 || y % 32 < 1 {
                0.66
            } else {
                check
            };
            im.set_pixel(x, y, Color::new(value, value, value, 1.));
        }
    }
    let tex = Texture2D::from_image(&im);
    tex.set_filter(FilterMode::Linear);
    tex
}
fn world(sim: &Simulation, tex: &Texture2D) {
    for b in &sim.blocks {
        let color = match b.kind {
            0 => Color::new(0.31, 0.38, 0.40, 1.),
            1 => Color::new(0.49, 0.60, 0.64, 1.),
            2 => Color::new(0.77, 0.54, 0.30, 1.),
            _ => Color::new(0.43, 0.64, 0.66, 1.),
        };
        draw_cube(b.bounds.center(), b.bounds.size(), Some(tex), color);
        draw_cube_wires(
            b.bounds.center(),
            b.bounds.size(),
            Color::new(0.19, 0.26, 0.29, 1.),
        );
    }
    for x in -31..32 {
        draw_line_3d(
            vec3(x as f32, 0.006, -53.5),
            vec3(x as f32, 0.006, 13.5),
            Color::new(0.42, 0.48, 0.49, 1.),
        );
    }
    for z in -53..14 {
        draw_line_3d(
            vec3(-31.5, 0.006, z as f32),
            vec3(31.5, 0.006, z as f32),
            Color::new(0.42, 0.48, 0.49, 1.),
        );
    }
    for x in [-13., -3.5, 3.5, 13.] {
        draw_cube(vec3(x, 0.01, -9.), vec3(0.07, 0.015, 44.), None, ACCENT);
    }
    for z in [7., -3., -13., -23., -33.] {
        draw_cube(vec3(0., 0.014, z), vec3(6.6, 0.018, 0.10), None, CYAN);
    }
    for z in [-30., -18., -6., 6.] {
        for x in [-15.4, 15.4] {
            draw_cube(vec3(x, 3., z), vec3(0.35, 6., 0.35), None, INK);
            draw_cube(vec3(x * 0.96, 3.9, z), vec3(0.10, 0.10, 3.4), None, CYAN);
        }
        draw_cube(
            vec3(0., 5.8, z),
            vec3(31., 0.22, 0.25),
            None,
            Color::new(0.22, 0.30, 0.34, 1.),
        );
    }
    for ramp in &sim.ramps {
        let x = ramp.x;
        let w = ramp.width * 0.5;
        let z = ramp.z;
        let back = z - ramp.length;
        let height = ramp.height;
        let points = [
            vec3(x - w, 0., z),
            vec3(x + w, 0., z),
            vec3(x - w, height, back),
            vec3(x + w, height, back),
            vec3(x - w, 0., back),
            vec3(x + w, 0., back),
        ];
        let faces = [
            [0, 1, 2],
            [1, 3, 2],
            [0, 2, 4],
            [1, 5, 3],
            [2, 3, 4],
            [3, 5, 4],
        ];
        let color = if ramp.slope() > 1.001 { ACCENT } else { CYAN };
        let mut vertices = Vec::new();
        let mut indices = Vec::new();
        for face in faces {
            for index in face {
                indices.push(vertices.len() as u16);
                let point = points[index];
                vertices.push(Vertex::new(
                    point.x, point.y, point.z, point.x, point.z, color,
                ));
            }
        }
        draw_mesh(&Mesh {
            vertices,
            indices,
            texture: Some(tex.clone()),
        });
        for i in 0..=10 {
            let t = i as f32 / 10.;
            draw_line_3d(
                vec3(x - w, height * t + 0.005, z - ramp.length * t),
                vec3(x + w, height * t + 0.005, z - ramp.length * t),
                INK,
            );
        }
    }
    for t in &sim.targets {
        let c = t.bounds.center();
        draw_cube(vec3(c.x, 0.18, c.z), vec3(1.2, 0.36, 0.65), None, INK);
        draw_cube(
            vec3(c.x, 1.10, c.z + 0.18),
            vec3(0.09, 2., 0.09),
            None,
            MUTED,
        );
        if t.health <= 0. {
            continue;
        }
        draw_cube(
            c,
            t.bounds.size(),
            Some(tex),
            if t.flash > 0. { WHITE } else { ACCENT },
        );
        draw_cube(
            vec3(c.x, c.y - 0.05, c.z + 0.135),
            vec3(0.28, 0.42, 0.018),
            None,
            INK,
        );
        draw_cube(
            vec3(c.x, c.y + 0.64, c.z + 0.135),
            vec3(0.34, 0.30, 0.018),
            None,
            INK,
        );
        draw_cube_wires(c, t.bounds.size() + Vec3::splat(0.008), INK);
    }
}
fn weapon(sim: &Simulation, rt: &RenderTarget, aspect: f32, time: f32) {
    set_camera(&Camera3D {
        position: Vec3::ZERO,
        target: vec3(0., 0., -1.),
        up: Vec3::Y,
        fovy: h_fov_to_v(76., aspect),
        render_target: Some(rt.clone()),
        aspect: Some(aspect),
        z_near: 0.01,
        z_far: 5.,
        ..Default::default()
    });
    clear_background(Color::new(0., 0., 0., 0.));
    let p = &sim.player;
    let bob = (time * 10.).sin() * (p.speed() / 7.2) * 0.010 * (1. - p.ads);
    let reload = if p.reload_left > 0. {
        (p.reload_left * 2.5).sin().abs() * 0.15 + 0.12
    } else {
        0.
    };
    let o = vec3(
        0.25 * (1. - p.ads),
        -0.25 * (1. - p.ads) - 0.041 * p.ads + bob - reload - p.sprinting as u8 as f32 * 0.13,
        -0.32 + p.shot_kick * 0.045,
    );
    let dark = Color::new(0.105, 0.14, 0.16, 1.);
    let steel = Color::new(0.25, 0.31, 0.33, 1.);
    let parts = [
        (vec3(0., -0.026, -0.27), vec3(0.115, 0.12, 0.43), dark),
        (vec3(0., -0.020, -0.59), vec3(0.094, 0.088, 0.24), steel),
        (vec3(0., 0.010, -0.82), vec3(0.029, 0.029, 0.26), dark),
        (vec3(0., 0.009, -0.96), vec3(0.049, 0.049, 0.07), steel),
        (vec3(0., -0.078, -0.04), vec3(0.094, 0.11, 0.16), steel),
        (vec3(0., -0.169, -0.21), vec3(0.070, 0.21, 0.12), dark),
        (vec3(0., -0.125, -0.04), vec3(0.064, 0.14, 0.07), dark),
        (vec3(0.061, -0.025, -0.25), vec3(0.004, 0.045, 0.13), ACCENT),
        (vec3(0., 0.040, -0.38), vec3(0.065, 0.010, 0.28), steel),
        (vec3(-0.027, 0.048, -0.20), vec3(0.014, 0.04, 0.019), dark),
        (vec3(0.027, 0.048, -0.20), vec3(0.014, 0.04, 0.019), dark),
        (vec3(0., 0.045, -0.77), vec3(0.008, 0.05, 0.014), INK),
        (
            vec3(-0.012, -0.123, -0.49),
            vec3(0.11, 0.07, 0.16),
            Color::new(0.48, 0.40, 0.30, 1.),
        ),
        (
            vec3(0.055, -0.18, 0.005),
            vec3(0.09, 0.13, 0.11),
            Color::new(0.48, 0.40, 0.30, 1.),
        ),
    ];
    for (pos, size, color) in parts {
        draw_cube(o + pos, size, None, color);
        draw_cube_wires(o + pos, size, Color::new(0.035, 0.05, 0.06, 1.));
    }
    for i in 0..6 {
        draw_cube(
            o + vec3(0., 0.047, -0.28 - i as f32 * 0.038),
            vec3(0.073, 0.012, 0.014),
            None,
            dark,
        );
    }
    if p.shot_kick > 0.65 {
        draw_sphere(
            o + vec3(0., 0.01, -1.04),
            0.035 + p.shot_kick * 0.025,
            None,
            Color::new(1., 0.80, 0.32, 1.),
        );
    }
    set_default_camera();
    draw_texture_ex(
        &rt.texture,
        0.,
        0.,
        WHITE,
        DrawTextureParams {
            dest_size: Some(vec2(screen_width(), screen_height())),
            flip_y: true,
            ..Default::default()
        },
    );
}
#[allow(clippy::too_many_arguments)]
fn hud(
    sim: &Simulation,
    cfg: &Settings,
    hit_timer: f32,
    head: bool,
    debug: bool,
    recording: bool,
    notice: &str,
    notice_timer: f32,
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
        let fov = cfg.fov + (cfg.ads_fov - cfg.fov) * p.ads;
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
    label("KESTREL-30 / AUTO", w - 231., h - 101., 16., MUTED);
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
        if p.reload_left > 0. {
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
    if p.reload_left > 0. {
        draw_rectangle(
            w - 232.,
            h - 20.,
            190. * (1. - p.reload_left / p.reload_total),
            3.,
            ACCENT,
        );
    }
    panel(24., h - 105., 248., 81.);
    let stance = if !p.grounded {
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
fn pause_screen(cfg: &Settings, initial: bool) {
    let (w, h) = (screen_width(), screen_height());
    draw_rectangle(0., 0., w, h, Color::new(0.015, 0.025, 0.035, 0.78));
    let x = w * 0.5 - 270.;
    let y = (h * 0.5 - 250.).max(30.);
    draw_rectangle(x, y, 540., 500., Color::new(0.035, 0.057, 0.074, 0.97));
    draw_rectangle(x, y, 540., 3., ACCENT);
    label("VECTOR", x + 36., y + 68., 48., WHITE);
    label(
        "A MOVEMENT + GUNPLAY LABORATORY",
        x + 39.,
        y + 98.,
        16.,
        CYAN,
    );
    label(
        if initial {
            "CLICK OR ENTER TO ENTER THE RANGE"
        } else {
            "CLICK OR ESC TO RESUME"
        },
        x + 38.,
        y + 149.,
        20.,
        ACCENT,
    );
    let controls = [
        "W A S D     Move          MOUSE     Look",
        "LEFT CLICK  Fire         RIGHT     Hold ADS",
        "SHIFT       Sprint       CTRL / C  Hold crouch",
        "SPACE       Jump         R         Reload",
        "Z           Hold prone   M         Mute audio",
    ];
    for (i, s) in controls.iter().enumerate() {
        label(s, x + 38., y + 192. + i as f32 * 27., 17., MUTED);
    }
    label(
        &format!("[ / ]  SENSITIVITY      {:.2} deg/pixel", cfg.sensitivity),
        x + 38.,
        y + 355.,
        18.,
        WHITE,
    );
    label(
        &format!("- / =  HORIZONTAL FOV   {:.0} degrees", cfg.fov),
        x + 38.,
        y + 384.,
        18.,
        WHITE,
    );
    label(
        "F5 SAVE PRESET    F6 RELOAD PRESET    F10 QUIT",
        x + 38.,
        y + 428.,
        15.,
        CYAN,
    );
    label(
        "Provisional tuning. No original-game code or assets.",
        x + 38.,
        y + 464.,
        14.,
        MUTED,
    );
}
#[macroquad::main(config)]
async fn main() {
    let mut cfg = Settings::load("settings.cfg");
    let mut audio = sound::SoundBank::new().await;
    let mut step_distance = 0.;
    let mut was_reloading = false;
    let mut sim = Simulation::new();
    let texture = grid_texture();
    let target = render_target(1440, 900);
    target.texture.set_filter(FilterMode::Linear);
    let mut active = false;
    let mut initial = true;
    let mut debug = false;
    let mut fullscreen = false;
    let mut accumulator = 0.;
    let mut traces: Vec<Trace> = Vec::new();
    let mut impacts: Vec<Impact> = Vec::new();
    let mut hit_timer = 0.;
    let mut head = false;
    let mut notice = String::new();
    let mut notice_timer = 0.;
    let mut recording: Option<File> = None;
    let mut record_clock = 0.;
    let mut intents = IntentLatch::default();
    let args: Vec<String> = std::env::args().collect();
    let capture = args.iter().any(|s| s.starts_with("--capture"));
    let capture_ads = args.iter().any(|s| s == "--capture-ads");
    let capture_fixtures = args.iter().any(|s| s == "--capture-fixtures");
    let output = args
        .iter()
        .find_map(|s| s.strip_prefix("--output="))
        .unwrap_or("capture.png");
    if capture_fixtures {
        sim.player.position = vec3(-18., 0., -12.);
        sim.player.yaw = -std::f32::consts::FRAC_PI_2;
    }
    if capture_ads {
        sim.player.ads = 1.;
    }
    let demo = args.iter().any(|s| s == "--demo");
    let mut frames = 0;
    if capture || demo {
        active = true;
        initial = false;
        debug = true;
    }
    loop {
        let raw_dt = get_frame_time();
        let dt = raw_dt.min(0.25);
        frames += 1;
        if active
            && frames > 8
            && (raw_dt > 0.25
                || is_key_down(KeyCode::LeftAlt)
                || is_key_down(KeyCode::RightAlt)
                || is_key_down(KeyCode::LeftSuper)
                || is_key_down(KeyCode::RightSuper))
        {
            active = false;
            set_cursor_grab(false);
            show_mouse(true);
            accumulator = 0.;
            intents.clear();
            sim.player.firing_sequence = false;
            notice = "Paused after focus shortcut or a long frame hitch".into();
            notice_timer = 4.;
        }
        let mut just_resumed = false;
        if is_key_pressed(KeyCode::F10) {
            break;
        }
        if is_key_pressed(KeyCode::Escape) {
            active = !active;
            just_resumed = active;
            intents.clear();
            sim.player.firing_sequence = false;

            initial = false;
            set_cursor_grab(active);
            show_mouse(!active);
            accumulator = 0.;
        }
        if !active && (is_mouse_button_pressed(MouseButton::Left) || is_key_pressed(KeyCode::Enter))
        {
            active = true;
            just_resumed = true;
            intents.clear();
            sim.player.firing_sequence = false;

            initial = false;
            set_cursor_grab(true);
            show_mouse(false);
            accumulator = 0.;
        }
        if is_key_pressed(KeyCode::M) {
            audio.muted = !audio.muted;
            notice = if audio.muted {
                "Audio muted".into()
            } else {
                "Audio on".into()
            };
            notice_timer = 2.;
        }
        if is_key_pressed(KeyCode::F1) {
            debug = !debug;
        }
        if is_key_pressed(KeyCode::F2) {
            sim.reset();
            intents.clear();
            accumulator = 0.;
            just_resumed = true;
            traces.clear();
            impacts.clear();
            notice = "Range reset. Fresh magazine, clean telemetry.".into();
            notice_timer = 3.;
        }
        if is_key_pressed(KeyCode::F11) {
            fullscreen = !fullscreen;
            set_fullscreen(fullscreen);
        }
        if is_key_pressed(KeyCode::LeftBracket) {
            cfg.sensitivity = (cfg.sensitivity - 0.01).max(0.01);
        }
        if is_key_pressed(KeyCode::RightBracket) {
            cfg.sensitivity = (cfg.sensitivity + 0.01).min(1.);
        }
        if is_key_pressed(KeyCode::Minus) {
            cfg.fov = (cfg.fov - 2.).max(65.);
        }
        if is_key_pressed(KeyCode::Equal) {
            cfg.fov = (cfg.fov + 2.).min(120.);
        }
        if is_key_pressed(KeyCode::F5) {
            notice = match cfg.save("settings.cfg") {
                Ok(_) => "Saved settings.cfg".into(),
                Err(e) => format!("Could not save preset: {e}"),
            };
            notice_timer = 4.;
        }
        if is_key_pressed(KeyCode::F6) {
            cfg = Settings::load("settings.cfg");
            notice = "Loaded settings.cfg (missing values use defaults)".into();
            notice_timer = 4.;
        }
        if is_key_pressed(KeyCode::F8) {
            if recording.is_some() {
                recording = None;
                notice = "Telemetry saved: telemetry.csv".into();
            } else {
                match File::create("telemetry.csv") {
                    Ok(mut f) => {
                        let _=writeln!(f,"time,x,y,z,speed,grounded,crouched,sprinting,ads,recoil_pitch_deg,ammo,shots,hits,kills,render_fps");
                        recording = Some(f);
                        notice = "Recording telemetry.csv (overwrites earlier recording)".into();
                    }
                    Err(e) => notice = format!("Could not record: {e}"),
                };
            }
            notice_timer = 4.;
        }
        if active {
            let mouse = if just_resumed {
                Vec2::ZERO
            } else {
                mouse_delta_position()
            };
            // Normalized screen coordinates from Macroquad have a reversed delta sign.
            sim.player.yaw -= mouse.x
                * screen_width()
                * 0.5
                * cfg.sensitivity.to_radians()
                * (1. - sim.player.ads * 0.35);
            sim.player.pitch = (sim.player.pitch
                + mouse.y
                    * screen_height()
                    * 0.5
                    * cfg.sensitivity.to_radians()
                    * (1. - sim.player.ads * 0.35))
                .clamp(-1.48, 1.48);
            intents.sample(
                is_key_pressed(KeyCode::Space),
                is_key_pressed(KeyCode::R),
                is_mouse_button_pressed(MouseButton::Left),
                is_mouse_button_down(MouseButton::Left),
                !just_resumed,
            );
            let mut input = Input {
                movement: vec2(
                    (is_key_down(KeyCode::D) || is_key_pressed(KeyCode::D)) as u8 as f32
                        - (is_key_down(KeyCode::A) || is_key_pressed(KeyCode::A)) as u8 as f32,
                    (is_key_down(KeyCode::W) || is_key_pressed(KeyCode::W)) as u8 as f32
                        - (is_key_down(KeyCode::S) || is_key_pressed(KeyCode::S)) as u8 as f32,
                ),
                jump: false,
                reload: false,
                crouch: is_key_down(KeyCode::LeftControl) || is_key_down(KeyCode::C),
                prone: is_key_down(KeyCode::Z),
                sprint: is_key_down(KeyCode::LeftShift),
                ads: is_mouse_button_down(MouseButton::Right),
                fire: false,
            };
            if capture_ads {
                input.ads = true;
            }
            if demo {
                input.ads = true;
                input.fire = true;
                sim.player.yaw = -std::f32::consts::FRAC_PI_2;
                sim.player.pitch = 0.;
            }
            accumulator += dt;
            while accumulator >= FIXED_DT {
                let step = intents.take(is_mouse_button_down(MouseButton::Left));
                input.jump = step.jump;
                input.reload = step.reload;
                input.fire = demo || step.fire;
                sim.update(input, &cfg, FIXED_DT);
                accumulator -= FIXED_DT;
            }
            if sim.player.reload_left > 0. && !was_reloading {
                audio.play(3);
            }
            was_reloading = sim.player.reload_left > 0.;
            step_distance += sim.player.speed() * dt;
            if sim.player.grounded && step_distance > if sim.player.sprinting { 2.5 } else { 1.8 } {
                audio.play(2);
                step_distance = 0.;
            }
            for shot in sim.events.drain(..) {
                audio.play(0);
                if shot.hit_target {
                    audio.play(1);
                    hit_timer = 0.13;
                    head = shot.headshot;
                }
                traces.push(Trace { shot, life: 0.045 });
                impacts.push(Impact {
                    point: shot.end,
                    life: 5.,
                    target: shot.hit_target,
                });
            }
            if impacts.len() > 96 {
                impacts.drain(0..impacts.len() - 96);
            }
            hit_timer = (hit_timer - dt).max(0.);
            for t in &mut traces {
                t.life -= dt;
            }
            traces.retain(|t| t.life > 0.);
            for i in &mut impacts {
                i.life -= dt;
            }
            impacts.retain(|i| i.life > 0.);
            record_clock += dt;
            if record_clock >= 0.1 {
                record_clock = 0.;
                if let Some(f) = &mut recording {
                    let p = &sim.player;
                    let _ = writeln!(
                        f,
                        "{:.4},{:.4},{:.4},{:.4},{:.4},{},{},{},{:.4},{:.4},{},{},{},{},{}",
                        sim.time,
                        p.position.x,
                        p.position.y,
                        p.position.z,
                        p.speed(),
                        p.grounded,
                        p.crouched,
                        p.sprinting,
                        p.ads,
                        p.recoil.x.to_degrees(),
                        p.ammo,
                        sim.stats.shots,
                        sim.stats.hits,
                        sim.stats.kills,
                        get_fps()
                    );
                }
            }
        }
        notice_timer = (notice_timer - dt).max(0.);
        clear_background(Color::new(0.66, 0.76, 0.78, 1.));
        let aspect = screen_width() / screen_height();
        let eye = sim.player.eye();
        let forward = sim.player.direction();
        let fov = cfg.fov + (cfg.ads_fov - cfg.fov) * sim.player.ads;
        set_camera(&Camera3D {
            position: eye,
            target: eye + forward,
            up: Vec3::Y,
            fovy: h_fov_to_v(fov, aspect),
            z_near: 0.035,
            z_far: 200.,
            ..Default::default()
        });
        world(&sim, &texture);
        for t in &traces {
            draw_line_3d(
                t.shot.start + forward * 0.6,
                t.shot.end,
                Color::new(1., 0.84, 0.5, 0.8),
            );
        }
        for i in &impacts {
            draw_sphere(i.point, 0.022, None, if i.target { CYAN } else { INK });
        }
        weapon(&sim, &target, aspect, sim.time as f32);
        hud(
            &sim,
            &cfg,
            hit_timer,
            head,
            debug,
            recording.is_some(),
            &notice,
            notice_timer,
        );
        if !active {
            pause_screen(&cfg, initial);
        }
        if capture && frames == 8 {
            get_screen_data().export_png(output);
            break;
        }
        next_frame().await;
    }
}
