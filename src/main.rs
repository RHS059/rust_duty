mod authored_viewmodel;
mod game_update;
mod sound;
mod weapon_model;
use macroquad::prelude::*;
use std::{fs::File, io::Write};
use vector_range::{
    clock::FixedClock,
    control::{ButtonInput, ControlMode, ControlSample, ControlState, IntentLatch},
};
use vector_range::{
    muzzle_fx::MuzzleFx,
    settings::Settings,
    sim::{Input, Shot, Simulation, FIXED_DT, SPRINT_DURATION},
};
const INK: Color = Color::new(0.035, 0.055, 0.072, 1.);
const ACCENT: Color = Color::new(0.98, 0.62, 0.22, 1.);
const CYAN: Color = Color::new(0.33, 0.84, 0.87, 1.);
const MUTED: Color = Color::new(0.62, 0.69, 0.72, 1.);
fn config() -> Conf {
    if let Some(code) = rust_duty_launcher::game::dispatch_helper() {
        std::process::exit(code);
    }
    if let Some(code) = rust_duty_launcher::game::dispatch_headless(env!("CARGO_PKG_VERSION")) {
        std::process::exit(code);
    }
    let reference = std::env::args().any(|a| a == "--reference-viewport");
    Conf {
        window_title: "VECTOR RANGE | Original Rust FPS laboratory".into(),
        window_width: if reference { 960 } else { 1440 },
        window_height: if reference { 540 } else { 900 },
        high_dpi: !reference,
        sample_count: 4,
        ..Default::default()
    }
}
#[derive(Clone, Copy)]
struct ViewmodelFraming {
    hip: Vec3,
    ads: Vec3,
    hfov: f32,
    hip_rotation: Quat,
    ads_rotation: Quat,
    reference: bool,
    hand_modes: Option<[f32; 4]>,
    left_grip_override: Option<[f32; 3]>,
}
impl ViewmodelFraming {
    fn from_args(args: &[String]) -> Self {
        fn vector(args: &[String], prefix: &str, default: Vec3) -> Vec3 {
            args.iter()
                .find_map(|a| a.strip_prefix(prefix))
                .and_then(|s| {
                    let values = s
                        .split(',')
                        .map(str::parse::<f32>)
                        .collect::<Result<Vec<_>, _>>()
                        .ok()?;
                    (values.len() == 3 && values.iter().all(|v| v.is_finite() && v.abs() <= 5.))
                        .then(|| Vec3::new(values[0], values[1], values[2]))
                })
                .unwrap_or(default)
        }
        let hip_ypr = vector(args, "--viewmodel-hip-ypr=", vec3(0.04118, -0.01252, 0.));
        let ads_ypr = vector(args, "--viewmodel-ads-ypr=", Vec3::ZERO);
        let hand_modes = args
            .iter()
            .find_map(|a| a.strip_prefix("--hand-modes="))
            .and_then(|s| {
                let v = s
                    .split(',')
                    .map(str::parse::<f32>)
                    .collect::<Result<Vec<_>, _>>()
                    .ok()?;
                (v.len() == 4 && v.iter().all(|x| x.is_finite() && (0. ..=1.).contains(x)))
                    .then(|| [v[0], v[1], v[2], v[3]])
            });
        Self {
            reference: args.iter().any(|a| a == "--reference-viewport"),
            hand_modes,
            left_grip_override: args
                .iter()
                .any(|a| a.starts_with("--left-grip="))
                .then(|| vector(args, "--left-grip=", Vec3::ZERO).to_array()),
            hip_rotation: Quat::from_euler(EulerRot::YXZ, hip_ypr.x, hip_ypr.y, hip_ypr.z),
            ads_rotation: Quat::from_euler(EulerRot::YXZ, ads_ypr.x, ads_ypr.y, ads_ypr.z),
            hip: vector(args, "--viewmodel-hip=", vec3(0.05930, -0.04831, -0.30806)),
            ads: vector(args, "--viewmodel-ads=", vec3(0., -0.03794, -0.2322)),
            hfov: args
                .iter()
                .find_map(|a| a.strip_prefix("--viewmodel-fov="))
                .and_then(|s| s.parse::<f32>().ok())
                .filter(|v| v.is_finite() && (45. ..=120.).contains(v))
                .unwrap_or(76.),
        }
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
fn supply_focus(
    sim: &Simulation,
    cfg: &Settings,
    supply: &vector_range::ammo_supply::AmmoSupply,
    active: bool,
) -> Option<vector_range::ammo_supply::SupplyFocus> {
    let viewport = vec2(screen_width(), screen_height());
    let fov = cfg.fov
        + (cfg.ads_fov - cfg.fov)
            * vector_range::reference_motion::visual_world_ads(sim.player.ads);
    vector_range::ammo_supply::SupplyView::perspective(
        sim.player.eye(),
        sim.player.direction(),
        h_fov_to_v(fov, viewport.x / viewport.y),
        viewport,
    )
    .and_then(|view| supply.focus(sim, view, active))
}
fn register_supply(sim: &mut Simulation, supply: &vector_range::ammo_supply::AmmoSupply) {
    sim.blocks.push(vector_range::sim::Block {
        bounds: supply.bounds(),
        kind: 4,
    });
}
fn world(sim: &Simulation, tex: &Texture2D) {
    for b in &sim.blocks {
        let color = match b.kind {
            0 => Color::new(0.31, 0.38, 0.40, 1.),
            1 => Color::new(0.49, 0.60, 0.64, 1.),
            2 => Color::new(0.77, 0.54, 0.30, 1.),
            4 => Color::new(0.22, 0.26, 0.28, 1.),
            _ => Color::new(0.43, 0.64, 0.66, 1.),
        };
        draw_cube(b.bounds.center(), b.bounds.size(), Some(tex), color);
        if b.kind == 4 {
            // Original geometric interaction fixture while reference art is pending.
            for x in [-0.26, 0.26] {
                draw_cube(
                    b.bounds.center() + vec3(x, 0.257, 0.),
                    vec3(0.06, 0.025, 0.51),
                    None,
                    ACCENT,
                );
            }
            draw_cube(
                b.bounds.center() + vec3(0., 0.04, -0.26),
                vec3(0.22, 0.10, 0.025),
                None,
                ACCENT,
            );
        }
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
fn locomotion_input(sim: &Simulation) -> vector_range::locomotion_presentation::LocomotionInput {
    vector_range::locomotion_presentation::LocomotionInput {
        sprint: if sim.player.sprinting || sim.player.mantle.is_some() {
            1.
        } else {
            0.
        },
        speed: sim.player.speed(),
        ads: sim.player.ads,
    }
}
#[allow(clippy::too_many_arguments)]
fn weapon(
    sim: &Simulation,
    rt: &RenderTarget,
    aspect: f32,
    locomotion_state: &mut vector_range::locomotion_presentation::LocomotionPresentation,
    model: Option<&weapon_model::WeaponModel>,
    authored: Option<&mut authored_viewmodel::AuthoredViewmodel>,
    arms: Option<&mut vector_range::arms::ArmModel>,
    animation_state: &mut vector_range::view_animation::ViewAnimation,
    cfg: &Settings,
    framing: ViewmodelFraming,
    presentation_override: Option<f32>,
    muzzle_fx: &mut MuzzleFx,
    barrel_flash: bool,
) {
    set_camera(&Camera3D {
        position: Vec3::ZERO,
        target: vec3(0., 0., -1.),
        up: Vec3::Y,
        fovy: h_fov_to_v(framing.hfov, aspect),
        render_target: Some(rt.clone()),
        aspect: Some(aspect),
        z_near: 0.01,
        z_far: 5.,
        ..Default::default()
    });
    clear_background(if framing.reference {
        Color::new(0.14, 0.19, 0.24, 1.)
    } else {
        Color::new(0., 0., 0., 0.)
    });
    // Saved viewmodel offset: +X right, +Y up. Applied before the gun is drawn.
    let view_offset = vec3(cfg.viewmodel_x, cfg.viewmodel_y, 0.);
    if let Some(authored) = authored {
        authored.draw(sim.time, view_offset);
        composite_viewmodel(rt);
        return;
    }
    let p = &sim.player;
    let motion = locomotion_state.sample(sim.time, locomotion_input(sim));
    let bob = motion.bob;
    let reload = if p.reload_left > 0. {
        (p.reload_left * 2.5).sin().abs() * 0.15 + 0.12
    } else {
        0.
    };
    let o = vec3(
        if model.is_some() { 0.18 } else { 0.25 } * (1. - p.ads),
        (if model.is_some() { -0.19 } else { -0.25 }) * (1. - p.ads) - 0.041 * p.ads + bob
            - reload
            - motion.sprint * 0.13,
        -0.32 + p.shot_kick * 0.045,
    ) + view_offset;
    let mut muzzle_position = o + vec3(0., 0.01, -1.04);
    let mut barrel = -Vec3::Z;
    if let Some(model) = model {
        use vector_range::weapon_animation::AnimationInput;
        let progress = (p.reload_left > 0. && p.reload_total > 0.)
            .then(|| (1. - p.reload_left / p.reload_total).clamp(0., 1.));
        let completed =
            progress.is_none() && p.reload_ready_at > 0. && sim.time + 1e-6 >= p.reload_ready_at;
        let progress = if let Some(phase) = presentation_override {
            Some(phase)
        } else {
            animation_state.presentation_progress(
                progress,
                p.reload_total,
                p.reload_empty,
                completed,
                sim.time,
            )
        };
        let credit = if p.reload_empty {
            cfg.empty_reload_credit
        } else {
            cfg.reload_credit
        };
        let animation_input = AnimationInput {
            reload_progress: progress,
            reload_credit_fraction: if p.reload_total > 0. {
                credit / p.reload_total
            } else {
                0.542
            },
            empty_reload: p.reload_empty,
            ads: p.ads,
            recoil: p.shot_kick,
            sprint: motion.sprint,
        };
        let mut animation = animation_state.sample_input(animation_input, completed, sim.time);
        if let Some(grip) = framing.left_grip_override {
            animation.left_grip = grip;
        }
        if let Some(modes) = framing.hand_modes {
            animation.left_hand_blend = modes;
            animation.left_hand_orientation_xyzw = None;
            animation.left_hand_euler_yxz = [0.; 3];
        }
        let visual_ads = vector_range::reference_motion::visual_ads(p.ads);
        let base = framing.hip.lerp(framing.ads, visual_ads) + vec3(0., bob, 0.) + view_offset;
        let frame = vector_range::view_animation::WeaponFrame::with_orientation(
            base,
            framing.hip_rotation.slerp(framing.ads_rotation, visual_ads),
            &animation,
        );
        let transform = frame.matrix;
        muzzle_position = frame.point(model.muzzle);
        let barrel_local = frame.matrix.transform_vector3(-Vec3::Z);
        if barrel_local.length_squared() > 1e-8 {
            barrel = barrel_local.normalize();
        }
        let body_frame = Mat4::from_rotation_translation(
            framing.hip_rotation.slerp(framing.ads_rotation, visual_ads),
            base,
        );
        let hand_frames = animation_state
            .hand_presentation()
            .frames(body_frame, transform);
        if let Some(arms) = arms {
            if framing.hand_modes.is_some() || framing.left_grip_override.is_some() {
                arms.draw_with_hand_modes(transform, &animation, animation.left_hand_blend);
            } else {
                arms.draw_with_weapon_ik(
                    &hand_frames.targets,
                    hand_frames.free_frame,
                    &animation,
                    hand_frames.free_hands,
                    hand_frames.influences,
                    animation.left_hand_blend,
                );
            }
        }
        model.draw_pose_with_free_frame(
            transform,
            animation_state
                .hand_presentation()
                .held_magazine_matrix(body_frame, transform),
            &animation,
        );
    } else {
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
    }
    if barrel_flash {
        muzzle_fx.draw_barrel(muzzle_position, barrel);
    }
    composite_viewmodel(rt);
}
fn composite_viewmodel(rt: &RenderTarget) {
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
    let stance = if p.mantle.is_some() {
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
fn pause_screen(cfg: &Settings, initial: bool, control_mode: ControlMode) {
    let (w, h) = (screen_width(), screen_height());
    draw_rectangle(0., 0., w, h, Color::new(0.015, 0.025, 0.035, 0.78));
    let x = w * 0.5 - 270.;
    let y = (h * 0.5 - 284.).max(8.);
    draw_rectangle(x, y, 540., 568., Color::new(0.035, 0.057, 0.074, 0.97));
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
    let controls = if control_mode == ControlMode::Hold {
        [
            "W A S D     Move          MOUSE     Look",
            "LEFT CLICK  Fire         RIGHT     Hold ADS",
            "SHIFT       Sprint       CTRL / C  Hold crouch",
            "SPACE       Jump         R         Reload",
            "Z           Hold prone   M         Mute audio",
        ]
    } else {
        [
            "W A S D     Move          MOUSE     Look",
            "LEFT CLICK  Fire         RIGHT     Toggle ADS",
            "SHIFT       Sprint       CTRL / C  Toggle crouch",
            "SPACE       Jump / stand R         Reload",
            "Z           Toggle prone M         Mute audio",
        ]
    };
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
        &format!("LEFT / RIGHT ARROW  VIEWMODEL X  {:+.3} m", cfg.viewmodel_x),
        x + 38.,
        y + 420.,
        17.,
        WHITE,
    );
    label(
        &format!("UP / DOWN ARROW     VIEWMODEL Y  {:+.3} m", cfg.viewmodel_y),
        x + 38.,
        y + 448.,
        17.,
        WHITE,
    );
    label(
        "F5 SAVE PRESET    F6 RELOAD PRESET    F10 QUIT",
        x + 38.,
        y + 486.,
        15.,
        CYAN,
    );
    label(
        "F5 stores the viewmodel offset as the new default.",
        x + 38.,
        y + 512.,
        14.,
        MUTED,
    );
    label(
        "Provisional tuning. No original-game code or assets.",
        x + 38.,
        y + 534.,
        14.,
        MUTED,
    );
}
#[macroquad::main(config)]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    // Deterministic capture jobs never contact the release channel. Ordinary
    // double-click launches always start the background checker automatically.
    let update_enabled = !args
        .iter()
        .any(|arg| arg == "--no-update" || arg == "--demo" || arg.starts_with("--capture"));
    let mut game_update = game_update::UpdatePanel::start(update_enabled);
    // Present the same-window startup screen before audio/assets are loaded,
    // including fast checks that might otherwise finish before the first frame.
    if update_enabled {
        game_update.draw(true);
        next_frame().await;
    }
    let framing = ViewmodelFraming::from_args(&args);
    let control_mode = if args.iter().any(|s| s == "--hold-controls") {
        ControlMode::Hold
    } else {
        ControlMode::Toggle
    };
    let mut controls = ControlState::new(control_mode);
    let profile = args
        .iter()
        .find_map(|s| s.strip_prefix("--profile="))
        .unwrap_or("m4a1");
    let base = match profile {
        "m4a1" => Settings::m4_candidate(),
        "kestrel" => Settings::default(),
        other => {
            eprintln!("Unknown profile {other}; use m4a1 or kestrel");
            return;
        }
    };
    let settings_path = args
        .iter()
        .find_map(|s| s.strip_prefix("--settings="))
        .unwrap_or(if profile == "kestrel" {
            "profiles/kestrel.cfg"
        } else {
            "settings.cfg"
        });
    let weapon_label = if profile == "m4a1" {
        "M4 / CANDIDATE"
    } else {
        "KESTREL-30 / AUTO"
    };
    // Both shipped rifles are 5.56-class. --caliber-mm= retunes the procedural flash.
    let caliber_mm = args
        .iter()
        .find_map(|s| s.strip_prefix("--caliber-mm="))
        .and_then(|s| s.parse::<f32>().ok())
        .filter(|mm| mm.is_finite())
        .unwrap_or(5.56);
    let mut cfg = Settings::load_with_base(settings_path, base.clone());
    let mut audio = sound::SoundBank::new().await;
    let mut step_distance = 0.;
    let mut was_reloading = false;
    let mut animation_state = vector_range::view_animation::ViewAnimation::default();
    let mut locomotion_state =
        vector_range::locomotion_presentation::LocomotionPresentation::default();
    let mut sim = Simulation::new();
    let mut supply = vector_range::ammo_supply::AmmoSupply::default();
    register_supply(&mut sim, &supply);
    let texture = grid_texture();
    let target = render_target_ex(
        if framing.reference { 960 } else { 1440 },
        if framing.reference { 540 } else { 900 },
        RenderTargetParams {
            depth: true,
            ..Default::default()
        },
    );
    target.texture.set_filter(FilterMode::Linear);
    let mut initial = true;
    let mut session = vector_range::session::SessionController::default();
    let mut debug = false;
    let mut fullscreen = false;
    let mut clock = FixedClock::default();
    let mut last_frame = get_time();
    let mut traces: Vec<Trace> = Vec::new();
    let mut impacts: Vec<Impact> = Vec::new();
    let mut muzzle_fx = MuzzleFx::default();
    muzzle_fx.set_caliber_mm(caliber_mm);
    let mut hit_timer = 0.;
    let mut head = false;
    let mut notice = String::new();
    let mut notice_timer = 0.;
    let mut recording: Option<File> = None;
    let mut record_clock = 0.;
    let mut intents = IntentLatch::default();
    let executable =
        std::env::current_exe().unwrap_or_else(|_| std::path::PathBuf::from("vector-range.exe"));
    let explicit = args.iter().find_map(|s| s.strip_prefix("--weapon-asset="));
    let model_source = vector_range::asset_path::resolve_weapon(
        &executable,
        explicit.map(std::path::Path::new),
        args.iter().any(|s| s == "--procedural-weapon"),
        vector_range::EMBEDDED_WEAPON.is_some(),
    );
    let mut model_error = None;
    let explicit_viewmodel = args
        .iter()
        .find_map(|s| s.strip_prefix("--viewmodel-asset="));
    let authored_path = vector_range::asset_path::resolve_viewmodel(
        &executable,
        explicit_viewmodel.map(std::path::Path::new),
        args.iter().any(|s| {
            s == "--procedural-weapon"
                || s.starts_with("--weapon-asset=")
                || s.starts_with("--arms-asset=")
        }),
    );
    let authored_clip = args
        .iter()
        .find_map(|s| s.strip_prefix("--viewmodel-clip="))
        .unwrap_or(if explicit_viewmodel.is_none() {
            "locomotion"
        } else {
            "neutral"
        });
    let authored_time = args
        .iter()
        .find_map(|s| s.strip_prefix("--viewmodel-time="));
    let mut authored = if let Some(path) = authored_path.as_ref() {
        let time = authored_time
            .map(|value| {
                value
                    .parse::<f32>()
                    .map_err(|_| "invalid --viewmodel-time".to_string())
            })
            .transpose();
        match time.and_then(|time| {
            let path = path
                .to_str()
                .ok_or_else(|| "viewmodel path is not valid Unicode".to_string())?;
            authored_viewmodel::AuthoredViewmodel::load(path, authored_clip, time)
        }) {
            Ok(viewmodel) => Some(viewmodel),
            Err(error) => {
                let message = format!("Authored viewmodel could not load: {error}");
                eprintln!("{message}");
                model_error = Some(message);
                None
            }
        }
    } else {
        None
    };
    let model_missing = authored_path.is_none()
        && matches!(
            &model_source,
            vector_range::asset_path::WeaponSource::Missing(_)
        );
    let model = if authored_path.is_some() {
        None
    } else {
        match vector_range::asset_path::load_weapon(&model_source, vector_range::EMBEDDED_WEAPON) {
            Ok(Some(asset)) => {
                eprintln!("Loaded VRMESH01 weapon: {} mesh parts", asset.meshes.len());
                Some(weapon_model::WeaponModel::from_asset(asset))
            }
            Err(error) => {
                let message = format!("Weapon asset could not load: {error}");
                eprintln!("{message}; source: {model_source:?}");
                model_error = Some(message);
                None
            }
            Ok(None) => None,
        }
    };
    let arms_path = if authored_path.is_some() {
        None
    } else {
        args.iter()
            .find_map(|s| s.strip_prefix("--arms-asset="))
            .map(std::path::PathBuf::from)
            .or_else(|| {
                executable
                    .parent()
                    .map(|p| p.join("assets/arms/first-person.vrs"))
                    .filter(|p| p.exists())
            })
    };
    let mut arms = if let Some(path) = arms_path {
        match vector_range::skinned_asset::SkinnedAsset::load(&path)
            .map_err(|error| error.to_string())
            .and_then(vector_range::arms::ArmModel::new)
        {
            Ok(asset) => Some(asset),
            Err(error) => {
                let message = format!("Arm asset could not load: {error}");
                eprintln!("{message}; path: {}", path.display());
                model_error = Some(message);
                None
            }
        }
    } else {
        None
    };
    let capture = args.iter().any(|s| s.starts_with("--capture"));
    let capture_ads = args.iter().any(|s| s == "--capture-ads");
    let capture_supply = args.iter().any(|s| s == "--capture-supply");
    let capture_fire = args.iter().any(|s| s == "--capture-fire");
    let capture_reload = args
        .iter()
        .find_map(|a| a.strip_prefix("--capture-reload="))
        .and_then(|s| s.parse::<f32>().ok())
        .filter(|v| v.is_finite() && (0. ..=1.).contains(v));
    let mut locomotion_capture_tick = 0_u64;
    let capture_sequence = args
        .iter()
        .find_map(|a| a.strip_prefix("--capture-sequence="))
        .filter(|s| matches!(*s, "tactical" | "empty" | "ads" | "locomotion"));
    let capture_empty =
        args.iter().any(|s| s == "--capture-empty") || capture_sequence == Some("empty");
    let sequence_duration = match capture_sequence {
        Some("empty") => vector_range::reference_motion::visual_duration(true),
        Some("tactical") => vector_range::reference_motion::visual_duration(false),
        Some("locomotion") => 3.5,
        _ => cfg.ads_time,
    };
    if capture_sequence.is_some() && !framing.reference {
        eprintln!("--capture-sequence requires --reference-viewport");
        return;
    }
    if capture_sequence.is_some() {
        std::fs::create_dir_all(
            args.iter()
                .find_map(|a| a.strip_prefix("--output="))
                .unwrap_or("capture-sequence"),
        )
        .expect("create capture sequence directory");
    }

    let capture_ads_fraction = args
        .iter()
        .find_map(|a| a.strip_prefix("--capture-ads-fraction="))
        .and_then(|s| s.parse::<f32>().ok())
        .filter(|v| v.is_finite() && (0. ..=1.).contains(v));
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
    if capture_supply {
        sim.player.position = vec3(0., 0., 11.7);
        sim.player.yaw = std::f32::consts::FRAC_PI_2;
        sim.player.pitch = (supply.bounds().center() - sim.player.eye())
            .normalize()
            .y
            .asin();
        sim.player.ammo = 15;
        sim.player.reserve = 30;
    }
    let demo = args.iter().any(|s| s == "--demo");
    let mut frames = 0;
    if capture || demo {
        session.set_active(true);
        initial = false;
        debug = true;
    }
    if model_error.is_none() {
        if let Err(error) = rust_duty_launcher::game::mark_ready(env!("CARGO_PKG_VERSION")) {
            eprintln!("Update startup acknowledgement: {error}");
        }
    }
    loop {
        let now = get_time();
        let raw_dt = now - last_frame;
        last_frame = now;
        let dt = raw_dt.min(FixedClock::MAX_FRAME) as f32;
        frames += 1;
        if is_key_pressed(KeyCode::F10) {
            break;
        }
        let startup_blocked = game_update.startup_blocked();
        let update_pointer = game_update.consumes_pointer(!session.is_active());
        let transition = session.step(vector_range::session::SessionInput {
            esc_pressed: is_key_pressed(KeyCode::Escape),
            esc_down: is_key_down(KeyCode::Escape),
            enter_pressed: is_key_pressed(KeyCode::Enter),
            enter_down: is_key_down(KeyCode::Enter),
            click_pressed: is_mouse_button_pressed(MouseButton::Left)
                && (startup_blocked || !update_pointer),
            click_down: is_mouse_button_down(MouseButton::Left)
                && (startup_blocked || !update_pointer),
            focus_shortcut_pressed: is_key_down(KeyCode::LeftAlt)
                || is_key_down(KeyCode::RightAlt)
                || is_key_down(KeyCode::LeftSuper)
                || is_key_down(KeyCode::RightSuper),
            blocked: model_error.is_some() || startup_blocked,
            dt: raw_dt,
        });
        let active = transition.active;
        let mut just_resumed = transition.resumed;
        if transition.paused {
            // Includes Escape, focus-shortcut, and asset-block interruptions.
            // A render hitch only discards time and must not cancel traversal.
            sim.cancel_mantle();
        }
        if transition.paused || transition.resumed {
            initial = false;
            set_cursor_grab(active);
            show_mouse(!active);
            clock.clear();
            intents.clear();
            controls.clear();
            sim.player.firing_sequence = false;
        }
        if transition.discard_timing {
            clock.clear();
            intents.clear();
            sim.player.firing_sequence = false;
        }
        // While startup owns the screen, no world tick, gameplay hotkey, weapon
        // input, HUD or pause-menu rendering can run. Session edges above are
        // still sampled, so held buttons cannot leak through on completion.
        if startup_blocked {
            set_cursor_grab(false);
            show_mouse(true);
            if game_update.draw(true) {
                break;
            }
            next_frame().await;
            continue;
        }
        let simulation_dt =
            if transition.discard_timing || capture_supply || capture_sequence.is_some() {
                0.
            } else {
                raw_dt.min(FixedClock::MAX_FRAME)
            };
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
            supply.reset();
            register_supply(&mut sim, &supply);
            animation_state = vector_range::view_animation::ViewAnimation::default();
            locomotion_state.reset(sim.time);
            if let Some(viewmodel) = &mut authored {
                viewmodel.update_locomotion(sim.time, sim.time, false);
            }
            intents.clear();
            controls.clear();
            clock.clear();
            just_resumed = true;
            traces.clear();
            impacts.clear();
            muzzle_fx.clear();
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
        // Start menu / pause settings only. Arrows nudge the viewmodel, not the player.
        if !active {
            if is_key_pressed(KeyCode::Left) {
                cfg.nudge_viewmodel(-Settings::VIEWMODEL_NUDGE, 0.);
            }
            if is_key_pressed(KeyCode::Right) {
                cfg.nudge_viewmodel(Settings::VIEWMODEL_NUDGE, 0.);
            }
            if is_key_pressed(KeyCode::Down) {
                cfg.nudge_viewmodel(0., -Settings::VIEWMODEL_NUDGE);
            }
            if is_key_pressed(KeyCode::Up) {
                cfg.nudge_viewmodel(0., Settings::VIEWMODEL_NUDGE);
            }
        }
        if is_key_pressed(KeyCode::F5) {
            notice = match cfg.save(settings_path) {
                Ok(_) => format!("Saved {settings_path}"),
                Err(e) => format!("Could not save preset: {e}"),
            };
            notice_timer = 4.;
        }
        if is_key_pressed(KeyCode::F6) {
            cfg = Settings::load_with_base(settings_path, base.clone());
            notice = format!("Loaded {settings_path} with {profile} defaults");
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
            let mouse = if just_resumed || transition.discard_timing {
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
                !just_resumed && !transition.discard_timing,
            );
            controls.sample(
                ControlSample {
                    ads: ButtonInput {
                        pressed: is_mouse_button_pressed(MouseButton::Right),
                        down: is_mouse_button_down(MouseButton::Right),
                    },
                    crouch: ButtonInput {
                        pressed: is_key_pressed(KeyCode::LeftControl) || is_key_pressed(KeyCode::C),
                        down: is_key_down(KeyCode::LeftControl) || is_key_down(KeyCode::C),
                    },
                    prone: ButtonInput {
                        pressed: is_key_pressed(KeyCode::Z),
                        down: is_key_down(KeyCode::Z),
                    },
                    sprint: ButtonInput {
                        pressed: is_key_pressed(KeyCode::LeftShift),
                        down: is_key_down(KeyCode::LeftShift),
                    },
                },
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
                crouch: false,
                prone: false,
                sprint: is_key_down(KeyCode::LeftShift),
                ads: false,
                fire: false,
            };
            if demo {
                sim.player.yaw = -std::f32::consts::FRAC_PI_2;
                sim.player.pitch = 0.;
            }
            let steps = clock.advance(simulation_dt).unwrap_or(0);
            for _ in 0..steps {
                let step = intents.take(is_mouse_button_down(MouseButton::Left));
                if step.jump {
                    controls.request_jump();
                }
                let control_intent = controls.intent();
                input.ads = capture_ads || demo || control_intent.ads;
                input.crouch = control_intent.crouch();
                input.prone = control_intent.prone();
                input.jump = step.jump;
                input.reload = step.reload;
                input.fire = demo || step.fire;
                let authored_step_start = sim.time;
                sim.update(input, &cfg, FIXED_DT);
                if let Some(viewmodel) = &mut authored {
                    viewmodel.update_locomotion(
                        authored_step_start,
                        sim.time,
                        sim.player.sprinting,
                    );
                }
                // Cosmetic targets receive exact simulation timestamps; input
                // and movement remain fully authoritative and immediate.
                locomotion_state.sample(sim.time, locomotion_input(&sim));
                let focus = supply_focus(&sim, &cfg, &supply, active);
                if supply.tick(
                    &mut sim.player,
                    focus,
                    is_key_down(KeyCode::F),
                    active,
                    FIXED_DT,
                ) == vector_range::ammo_supply::SupplyEvent::Refilled
                {
                    notice = "Ammunition replenished".into();
                    notice_timer = 2.;
                }
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
                muzzle_fx.spawn_shot(&shot);
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
            muzzle_fx.update(dt, &sim.blocks, &sim.ramps);
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
        let focus = supply_focus(&sim, &cfg, &supply, active);
        if !active || transition.discard_timing || !is_key_down(KeyCode::F) || focus.is_none() {
            supply.cancel();
        }
        // Deterministic presentation samples for comparison; only explicit capture flags use these.
        let sequence_elapsed = ((frames - 8).max(0) as f32) / (60000. / 1001.);
        let sequence_phase = (sequence_elapsed / sequence_duration).clamp(0., 1.);
        let presentation_reload = if matches!(capture_sequence, Some("tactical" | "empty")) {
            Some(sequence_phase)
        } else {
            capture_reload
        };
        if capture_sequence.is_some() {
            sim.time = sequence_elapsed as f64;
        }
        if capture_sequence == Some("ads") {
            sim.player.ads = sequence_phase;
        }
        if capture_sequence == Some("locomotion") {
            // Diagnostic presentation only: sample target changes on the same
            // fixed clock used by gameplay, with camera/world movement frozen.
            while locomotion_capture_tick as f64 / 120. <= sim.time {
                let t = locomotion_capture_tick as f64 / 120.;
                sim.player.sprinting = (1. ..2.).contains(&t);
                let speed = if !(0.25..3.).contains(&t) {
                    0.
                } else if sim.player.sprinting {
                    cfg.sprint_speed
                } else {
                    cfg.walk_speed
                };
                sim.player.velocity = vec3(speed, 0., 0.);
                locomotion_state.sample(t, locomotion_input(&sim));
                if let Some(viewmodel) = &mut authored {
                    viewmodel.update_locomotion(t, t, sim.player.sprinting);
                }
                locomotion_capture_tick += 1;
            }
        }
        if let Some(ads) = capture_ads_fraction {
            sim.player.ads = ads;
        }
        if let Some(phase) = presentation_reload {
            sim.player.reload_empty = capture_empty;
            sim.player.reload_total = if capture_empty {
                cfg.empty_reload_time
            } else {
                cfg.reload_time
            };
            sim.player.reload_left = sim.player.reload_total * (1. - phase);
            sim.player.reload_ready_at = sim.time + sim.player.reload_left as f64;
        }
        notice_timer = (notice_timer - dt).max(0.);
        clear_background(Color::new(0.66, 0.76, 0.78, 1.));
        let aspect = if framing.reference {
            16. / 9.
        } else {
            screen_width() / screen_height()
        };
        let eye = sim.player.eye();
        let forward = sim.player.direction();
        let fov = cfg.fov
            + (cfg.ads_fov - cfg.fov)
                * vector_range::reference_motion::visual_world_ads(sim.player.ads);
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
        muzzle_fx.draw_world(eye, authored_path.is_some());
        if capture_fire {
            sim.player.shot_kick = 1.;
        }
        // An explicitly requested invalid authored asset never falls through
        // to the legacy procedural renderer while its startup error is shown.
        if authored_path.is_none() || authored.is_some() {
            weapon(
                &sim,
                &target,
                aspect,
                &mut locomotion_state,
                model.as_ref(),
                authored.as_mut(),
                arms.as_mut(),
                &mut animation_state,
                &cfg,
                framing,
                presentation_reload,
                &mut muzzle_fx,
                authored_path.is_none(),
            );
        }
        if let Some(error) = authored.as_ref().and_then(|viewmodel| viewmodel.error()) {
            if model_error.is_none() {
                model_error = Some(format!("Authored viewmodel: {error}"));
            }
        }
        hud(
            &sim,
            &cfg,
            hit_timer,
            head,
            debug,
            recording.is_some(),
            &notice,
            notice_timer,
            weapon_label,
        );
        if let Some(focus) = focus {
            vector_range::ammo_supply_view::draw_ammo_supply_hint(
                focus,
                if capture_supply {
                    0.5
                } else {
                    supply.progress()
                },
                supply.ammo_full(&sim.player),
            );
        }
        if !active {
            pause_screen(&cfg, initial, controls.mode());
        }
        if game_update.draw(!active) {
            break;
        }
        if let Some(error) = &model_error {
            panel(24., screen_height() - 140., screen_width() - 48., 115.);
            label(
                &error.chars().take(105).collect::<String>(),
                42.,
                screen_height() - 108.,
                19.,
                RED,
            );
            label(
                if authored_path.is_some() {
                    "Check the matching .vra/.vrs/.vrm files and the selected clip name."
                } else {
                    "Re-extract the whole game folder. Expected: assets/weapons/hk416a5.vrm"
                },
                42.,
                screen_height() - 78.,
                16.,
                WHITE,
            );
            label(
                if authored_path.is_some() {
                    "F10 exits. Remove --viewmodel-asset to return to the existing gameplay presentation."
                } else {
                    "F10 exits. --procedural-weapon is an explicit diagnostic bypass."
                },
                42.,
                screen_height() - 48.,
                16.,
                MUTED,
            );
        } else if model_missing {
            label("HK416 asset missing: extract the whole package beside the EXE (procedural fallback active)",24.,screen_height()-155.,16.,YELLOW);
        }
        if capture
            && ((capture_sequence.is_none() && frames == 8)
                || (capture_sequence.is_some() && frames >= 8))
        {
            let sequence_output;
            let output = if capture_sequence.is_some() {
                sequence_output = format!(
                    "{}/{:04}.png",
                    if output == "capture.png" {
                        "capture-sequence"
                    } else {
                        output
                    },
                    frames - 8
                );
                sequence_output.as_str()
            } else {
                output
            };
            if framing.reference {
                unsafe {
                    get_internal_gl().flush();
                }
                target.texture.get_texture_data().export_png(output);
                let _ = std::fs::write(format!("{output}.json"), format!("{{\"capture\":\"native offscreen viewmodel\",\"width\":960,\"height\":540,\"hfov\":{},\"ads\":{},\"reload_phase\":{}}}",framing.hfov,sim.player.ads,presentation_reload.map(|v|v.to_string()).unwrap_or_else(||"null".into())));
            } else {
                get_screen_data().export_png(output);
            }
            if capture_sequence.is_some() {
                let _ = std::fs::write(format!("{output}.time.json"), format!("{{\"elapsed_seconds\":{},\"normalized_phase\":{},\"visual_duration_seconds\":{},\"simulation_ready_seconds\":{},\"sampling_hz\":59.94005994}}", sequence_elapsed, sequence_phase, sequence_duration, if capture_empty { cfg.empty_reload_time } else if capture_sequence == Some("ads") { cfg.ads_time } else { cfg.reload_time }));
            }
            if capture_sequence == Some("locomotion") {
                let motion = locomotion_state.sample(sim.time, locomotion_input(&sim));
                let _ = std::fs::write(format!("{output}.motion.json"), format!(
                    "{{\"elapsed\":{},\"target_sprint\":{},\"cosmetic_sprint\":{},\"bob\":{},\"bob_phase\":{},\"speed\":{}}}",
                    sequence_elapsed, sim.player.sprinting, motion.sprint, motion.bob, motion.phase, sim.player.speed()));
            }
            if capture_sequence.is_none() || sequence_elapsed >= sequence_duration + 0.2 {
                break;
            }
        }
        next_frame().await;
    }
}
