//! Original small presentation primitives; no simulation state is advanced here.
use super::{Color, Line, Mesh, Texture, Vertex};
use glam::{Vec2, Vec3};
pub fn wire_box(center: Vec3, size: Vec3, color: Color) -> [Line; 12] {
    let half = size * 0.5;
    let points: [Vec3; 8] = std::array::from_fn(|i| {
        center
            + half
                * Vec3::new(
                    if i & 1 == 0 { -1. } else { 1. },
                    if i & 2 == 0 { -1. } else { 1. },
                    if i & 4 == 0 { -1. } else { 1. },
                )
    });
    [
        (0, 1),
        (2, 3),
        (4, 5),
        (6, 7),
        (0, 2),
        (1, 3),
        (4, 6),
        (5, 7),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    .map(|(a, b)| Line {
        start: points[a],
        end: points[b],
        color,
    })
}
pub fn cube(center: Vec3, size: Vec3, texture: Option<Texture>, color: Color) -> Mesh {
    let mut mesh = Mesh {
        texture,
        ..Mesh::default()
    };
    for (normal, u, v) in [
        (Vec3::Z, Vec3::X, Vec3::Y),
        (-Vec3::Z, -Vec3::X, Vec3::Y),
        (Vec3::Y, Vec3::X, -Vec3::Z),
        (-Vec3::Y, Vec3::X, Vec3::Z),
        (Vec3::X, -Vec3::Z, Vec3::Y),
        (-Vec3::X, Vec3::Z, Vec3::Y),
    ] {
        let start = mesh.vertices.len() as u16;
        for (a, b) in [(-1., -1.), (1., -1.), (1., 1.), (-1., 1.)] {
            let mut vertex = Vertex::new2(
                center + (normal + u * a + v * b) * size * 0.5,
                Vec2::new((a + 1.) * 0.5, (b + 1.) * 0.5),
                color,
            );
            vertex.normal = normal.extend(0.);
            mesh.vertices.push(vertex);
        }
        mesh.indices
            .extend([start, start + 1, start + 2, start, start + 2, start + 3]);
    }
    mesh
}
pub fn sphere(
    center: Vec3,
    radius: f32,
    slices: u16,
    stacks: u16,
    color: Color,
) -> Result<Mesh, String> {
    if !center.is_finite() || !radius.is_finite() || radius <= 0. || slices < 3 || stacks < 2 {
        return Err("invalid sphere parameters".into());
    }
    let count = (u32::from(slices) + 1)
        .checked_mul(u32::from(stacks) + 1)
        .ok_or("sphere vertex count overflow")?;
    if count > u32::from(u16::MAX) + 1 {
        return Err("sphere exceeds u16 vertex capacity".into());
    }
    let mut mesh = Mesh {
        vertices: Vec::with_capacity(count as usize),
        ..Mesh::default()
    };
    for j in 0..=stacks {
        let v = f32::from(j) / f32::from(stacks);
        let phi = v * std::f32::consts::PI;
        for i in 0..=slices {
            let u = f32::from(i) / f32::from(slices);
            let theta = u * std::f32::consts::TAU;
            let normal = Vec3::new(phi.sin() * theta.cos(), phi.cos(), phi.sin() * theta.sin());
            let mut vertex = Vertex::new2(center + normal * radius, Vec2::new(u, v), color);
            vertex.normal = normal.extend(0.);
            mesh.vertices.push(vertex);
        }
    }
    let row = u32::from(slices) + 1;
    for j in 0..u32::from(stacks) {
        for i in 0..u32::from(slices) {
            let a = j * row + i;
            let b = a + row;
            mesh.indices.extend([
                a as u16,
                (a + 1) as u16,
                b as u16,
                (a + 1) as u16,
                (b + 1) as u16,
                b as u16,
            ]);
        }
    }
    Ok(mesh)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn box_has_twelve_unique_axis_edges() {
        let lines = wire_box(Vec3::ZERO, Vec3::splat(2.), Color::WHITE);
        for line in lines {
            assert_eq!(line.start.distance(line.end), 2.);
        }
        for (i, a) in lines.iter().enumerate() {
            for b in &lines[i + 1..] {
                assert!(!(a.start == b.start && a.end == b.end));
            }
        }
    }
    #[test]
    fn cube_normals_match_triangle_winding() {
        let mesh = cube(Vec3::ZERO, Vec3::ONE, None, Color::WHITE);
        assert_eq!(mesh.vertices.len(), 24);
        assert_eq!(mesh.indices.len(), 36);
        for tri in mesh.indices.as_chunks::<3>().0 {
            let [a, b, c] = [
                mesh.vertices[tri[0] as usize],
                mesh.vertices[tri[1] as usize],
                mesh.vertices[tri[2] as usize],
            ];
            assert!(
                (b.position - a.position)
                    .cross(c.position - a.position)
                    .dot(a.normal.truncate())
                    > 0.
            );
        }
    }
    #[test]
    fn sphere_is_finite_and_index_bounds_are_valid() {
        let mesh = sphere(Vec3::ZERO, 0.022, 12, 8, Color::WHITE).unwrap();
        mesh.validate().unwrap();
        assert!(mesh
            .vertices
            .iter()
            .all(|v| (v.position.length() - 0.022).abs() < 1e-6));
        assert!(sphere(Vec3::ZERO, 1., u16::MAX, u16::MAX, Color::WHITE).is_err());
        assert!(sphere(Vec3::ZERO, f32::NAN, 12, 8, Color::WHITE).is_err());
    }
}
