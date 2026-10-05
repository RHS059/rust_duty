use macroquad::prelude::*;
use vector_range::{sim::Simulation, settings::Settings, body_presentation::{BodyFrame, BodyPose}};
use vector_range::scene_lighting::SceneLighting;
use crate::hud::{INK, CYAN, ACCENT, MUTED};
use crate::viewmodel_draw::h_fov_to_v;
pub(crate) fn grid_texture() -> Texture2D {
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
pub(crate) fn supply_focus(
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
pub(crate) fn register_supply(sim: &mut Simulation, supply: &vector_range::ammo_supply::AmmoSupply) {
    sim.blocks.push(vector_range::sim::Block {
        bounds: supply.bounds(),
        kind: 4,
    });
}
pub(crate) fn world(sim: &Simulation, tex: &Texture2D) {
    let lighting = SceneLighting::range();
    for b in &sim.blocks {
        let color = match b.kind {
            0 => Color::new(0.31, 0.38, 0.40, 1.),
            1 => Color::new(0.49, 0.60, 0.64, 1.),
            2 => Color::new(0.77, 0.54, 0.30, 1.),
            4 => Color::new(0.22, 0.26, 0.28, 1.),
            _ => Color::new(0.43, 0.64, 0.66, 1.),
        };
        lighting.draw_cube(b.bounds.center(), b.bounds.size(), Some(tex), color);
        if b.kind == 4 {
            // Original geometric interaction fixture while reference art is pending.
            for x in [-0.26, 0.26] {
                lighting.draw_cube(
                    b.bounds.center() + vec3(x, 0.257, 0.),
                    vec3(0.06, 0.025, 0.51),
                    None,
                    ACCENT,
                );
            }
            lighting.draw_cube(
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
        lighting.draw_cube(vec3(x, 0.01, -9.), vec3(0.07, 0.015, 44.), None, ACCENT);
    }
    for z in [7., -3., -13., -23., -33.] {
        lighting.draw_cube(vec3(0., 0.014, z), vec3(6.6, 0.018, 0.10), None, CYAN);
    }
    for z in [-30., -18., -6., 6.] {
        for x in [-15.4, 15.4] {
            lighting.draw_cube(vec3(x, 3., z), vec3(0.35, 6., 0.35), None, INK);
            lighting.draw_cube(vec3(x * 0.96, 3.9, z), vec3(0.10, 0.10, 3.4), None, CYAN);
        }
        lighting.draw_cube(
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
            // Match the existing outward triangle winding.
            let normal = (points[face[1]] - points[face[0]])
                .cross(points[face[2]] - points[face[0]])
                .normalize();
            for index in face {
                indices.push(vertices.len() as u16);
                let point = points[index];
                vertices.push(Vertex::new(
                    point.x,
                    point.y,
                    point.z,
                    point.x,
                    point.z,
                    lighting.shade(color, normal),
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
        lighting.draw_cube(vec3(c.x, 0.18, c.z), vec3(1.2, 0.36, 0.65), None, INK);
        lighting.draw_cube(
            vec3(c.x, 1.10, c.z + 0.18),
            vec3(0.09, 2., 0.09),
            None,
            MUTED,
        );
        if t.health <= 0. {
            continue;
        }
        lighting.draw_cube(
            c,
            t.bounds.size(),
            Some(tex),
            if t.flash > 0. { WHITE } else { ACCENT },
        );
        lighting.draw_cube(
            vec3(c.x, c.y - 0.05, c.z + 0.135),
            vec3(0.28, 0.42, 0.018),
            None,
            INK,
        );
        lighting.draw_cube(
            vec3(c.x, c.y + 0.64, c.z + 0.135),
            vec3(0.34, 0.30, 0.018),
            None,
            INK,
        );
        draw_cube_wires(c, t.bounds.size() + Vec3::splat(0.008), INK);
    }
}
pub(crate) fn draw_body_placeholder(frame: &BodyFrame) {
    if frame.pose == BodyPose::Dead {
        return;
    }
    let color = Color::new(0.30, 0.34, 0.30, 1.);
    let forward = vec3(frame.yaw.cos(), 0., frame.yaw.sin());
    let right = forward.cross(Vec3::Y);
    for (i, side) in [-1_f32, 1.].into_iter().enumerate() {
        let hip = frame.pelvis + right * side * 0.1;
        let foot = frame.feet[i];
        let knee = (hip + foot) * 0.5 + forward * 0.12;
        for (a, b) in [(hip, knee), (knee, foot)] {
            for k in 0..6 {
                let t = (k as f32 + 0.5) / 6.;
                draw_cube(a.lerp(b, t), Vec3::splat(0.1), None, color);
            }
        }
    }
}
