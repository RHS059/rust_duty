//! Remove redundant baked subdivisions without moving geometry or erasing lighting.
use crate::draw::{Mesh, Vertex};

#[derive(Clone, Copy)]
struct Triangle {
    v: [Vertex; 3],
    error: f32,
}

fn merge(a: Triangle, b: Triangle) -> Option<Triangle> {
    for i in 0..3 {
        for j in 0..3 {
            let [p, m, c] = [a.v[i], a.v[(i + 1) % 3], a.v[(i + 2) % 3]];
            let [n, q, d] = [b.v[j], b.v[(j + 1) % 3], b.v[(j + 2) % 3]];
            // Two children must share exactly the split edge and winding.
            if m.position != n.position
                || c.position != d.position
                || m.color != n.color
                || c.color != d.color
            {
                continue;
            }
            let edge = q.position - p.position;
            let length = edge.length_squared();
            if length < 1e-10 {
                continue;
            }
            let t = (m.position - p.position).dot(edge) / length;
            if !(0.001..0.999).contains(&t)
                || (p.position + edge * t - m.position).length_squared() > 1e-10
            {
                continue;
            }
            let na = (m.position - p.position)
                .cross(c.position - p.position)
                .normalize_or_zero();
            let nb = (q.position - m.position)
                .cross(c.position - m.position)
                .normalize_or_zero();
            if na.dot(nb) < 0.99999 {
                continue;
            }
            let residual = (0..4)
                .map(|k| {
                    (p.color[k] as f32 * (1. - t) + q.color[k] as f32 * t - m.color[k] as f32).abs()
                })
                .fold(0_f32, f32::max);
            // Accumulated bound protects every original sample, not just this edge.
            let error = a.error.max(b.error) + residual;
            if error <= 2.0 {
                return Some(Triangle {
                    v: [p, q, c],
                    error,
                });
            }
        }
    }
    None
}

pub fn simplify(mesh: &mut Mesh) {
    let mut stack: Vec<Triangle> = Vec::new();
    for indices in mesh.indices.as_chunks::<3>().0 {
        stack.push(Triangle {
            v: [
                mesh.vertices[indices[0] as usize],
                mesh.vertices[indices[1] as usize],
                mesh.vertices[indices[2] as usize],
            ],
            error: 0.,
        });
        while stack.len() >= 2 {
            let n = stack.len();
            let Some(joined) = merge(stack[n - 2], stack[n - 1]) else {
                break;
            };
            stack.truncate(n - 2);
            stack.push(joined);
        }
    }
    // All output vertices are existing input vertices; deduplicate their indices.
    let mut ids = std::collections::HashMap::new();
    let mut vertices = Vec::new();
    let mut indices = Vec::with_capacity(stack.len() * 3);
    for triangle in stack {
        for v in triangle.v {
            let key = (v.position.to_array().map(f32::to_bits), v.color);
            indices.push(*ids.entry(key).or_insert_with(|| {
                let id = vertices.len() as u16;
                vertices.push(v);
                id
            }));
        }
    }
    mesh.vertices = vertices;
    mesh.indices = indices;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::Color;
    use glam::{Vec2, Vec3};
    #[test]
    fn merges_linear_light_but_preserves_shadow_and_area() {
        let v = |x, y, c| Vertex::new2(Vec3::new(x, y, 0.), Vec2::ZERO, Color::new(c, c, c, 1.));
        let source = Mesh {
            vertices: vec![
                v(0., 0., 0.2),
                v(1., 0., 0.4),
                v(0., 1., 0.2),
                v(2., 0., 0.6),
            ],
            indices: vec![0, 1, 2, 1, 3, 2],
            texture: None,
        };
        let mut linear = source.clone();
        simplify(&mut linear);
        assert_eq!(linear.indices.len(), 3);
        let p: Vec<_> = linear
            .indices
            .iter()
            .map(|i| linear.vertices[*i as usize].position)
            .collect();
        assert!(((p[1] - p[0]).cross(p[2] - p[0]).length() * 0.5 - 1.).abs() < 1e-6);
        let mut shadow = source;
        shadow.vertices[1].color = [10, 10, 10, 255];
        simplify(&mut shadow);
        assert_eq!(shadow.indices.len(), 6);
    }
}
