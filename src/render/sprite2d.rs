//! Screen-space quads share the CPU-lit mesh shader and top-left texture convention.
use crate::draw::{Color, Mesh, Rect, Texture, Vertex};
use glam::{Vec2, Vec3};
pub(crate) fn quad(rect: Rect, color: Color, texture: Option<Texture>) -> Mesh {
    Mesh {
        vertices: vec![
            Vertex::new2(Vec3::new(rect.x, rect.y, 0.), Vec2::new(0., 0.), color),
            Vertex::new2(
                Vec3::new(rect.x + rect.w, rect.y, 0.),
                Vec2::new(1., 0.),
                color,
            ),
            Vertex::new2(
                Vec3::new(rect.x + rect.w, rect.y + rect.h, 0.),
                Vec2::new(1., 1.),
                color,
            ),
            Vertex::new2(
                Vec3::new(rect.x, rect.y + rect.h, 0.),
                Vec2::new(0., 1.),
                color,
            ),
        ],
        indices: vec![0, 1, 2, 0, 2, 3],
        texture,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn sprite_uvs_start_at_top_left_without_legacy_flip() {
        let mesh = quad(Rect::new(10., 20., 30., 40.), Color::WHITE, None);
        assert_eq!(mesh.vertices[0].uv, Vec2::ZERO);
        assert_eq!(mesh.vertices[2].position, Vec3::new(40., 60., 0.));
        assert_eq!(mesh.vertices[2].uv, Vec2::ONE);
    }
}
