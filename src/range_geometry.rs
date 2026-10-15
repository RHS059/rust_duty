//! Static range surfaces used by both the offline bake and runtime fallback.
use crate::{
    draw::{Color, Mesh, Vertex},
    scene_lighting::SceneLighting,
    sim::Simulation,
};
use glam::{Vec2, Vec3};
pub fn meshes(sim: &Simulation) -> Vec<Mesh> {
    let mut result = Vec::new();
    let light = SceneLighting {
        ambient: 1.,
        diffuse: 0.,
        ..SceneLighting::range()
    };
    let mut cube = |p, s, c| result.push(light.cube_mesh(p, s, c));
    for b in &sim.blocks {
        let color = match b.kind {
            0 => Color::new(0.31, 0.38, 0.40, 1.),
            1 => Color::new(0.49, 0.60, 0.64, 1.),
            2 => Color::new(0.77, 0.54, 0.30, 1.),
            4 => Color::new(0.22, 0.26, 0.28, 1.),
            _ => Color::new(0.43, 0.64, 0.66, 1.),
        };
        cube(b.bounds.center(), b.bounds.size(), color);
    }
    for x in [-13., -3.5, 3.5, 13.] {
        cube(
            Vec3::new(x, 0.012, -9.),
            Vec3::new(0.07, 0.018, 44.),
            Color::new(0.98, 0.62, 0.22, 1.),
        );
    }
    for z in [7., -3., -13., -23., -33.] {
        cube(
            Vec3::new(0., 0.016, z),
            Vec3::new(6.6, 0.018, 0.10),
            Color::new(0.33, 0.84, 0.87, 1.),
        );
    }
    for z in [-30., -18., -6., 6.] {
        for x in [-15.4, 15.4] {
            cube(
                Vec3::new(x, 3., z),
                Vec3::new(0.35, 6., 0.35),
                Color::new(0.035, 0.055, 0.072, 1.),
            );
            cube(
                Vec3::new(x * 0.96, 3.9, z),
                Vec3::new(0.10, 0.10, 3.4),
                Color::new(0.33, 0.84, 0.87, 1.),
            );
        }
        cube(
            Vec3::new(0., 5.8, z),
            Vec3::new(31., 0.22, 0.25),
            Color::new(0.22, 0.30, 0.34, 1.),
        );
    }
    for ramp in &sim.ramps {
        let x = ramp.x;
        let w = ramp.width * 0.5;
        let z = ramp.z;
        let back = z - ramp.length;
        let h = ramp.height;
        let p = [
            Vec3::new(x - w, 0., z),
            Vec3::new(x + w, 0., z),
            Vec3::new(x - w, h, back),
            Vec3::new(x + w, h, back),
            Vec3::new(x - w, 0., back),
            Vec3::new(x + w, 0., back),
        ];
        let mut mesh = Mesh {
            vertices: Vec::new(),
            indices: Vec::new(),
            texture: None,
        };
        for ids in [
            [0, 1, 2],
            [1, 3, 2],
            [0, 2, 4],
            [1, 5, 3],
            [2, 3, 4],
            [3, 5, 4],
        ] {
            let mut n = (p[ids[1]] - p[ids[0]])
                .cross(p[ids[2]] - p[ids[0]])
                .normalize();
            if (ids == [0, 1, 2] || ids == [1, 3, 2]) && n.y < 0. {
                n = -n;
            }
            for id in ids {
                let mut v = Vertex::new2(p[id], Vec2::ZERO, Color::new(0.33, 0.84, 0.87, 1.));
                v.normal = n.extend(0.);
                mesh.indices.push(mesh.vertices.len() as u16);
                mesh.vertices.push(v);
            }
        }
        result.push(mesh);
    }
    result
}
pub fn lamps() -> Vec<Vec3> {
    [-30., -18., -6., 6.]
        .into_iter()
        .flat_map(|z| [-14.7, 14.7].into_iter().map(move |x| Vec3::new(x, 3.8, z)))
        .collect()
}
