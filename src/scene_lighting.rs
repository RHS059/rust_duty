//! Shared directional range lighting, evaluated in the renderer's coordinate frame.
//!
//! We deliberately shade vertex albedo on the CPU for both level geometry and
//! viewmodels, then let the renderer multiply it by the texture. Never store a
//! pre-lit weapon albedo.
use crate::draw::facade::*;

#[derive(Clone, Copy, Debug)]
pub struct SceneLighting {
    /// Unit direction *toward* the light, in the same frame as shaded normals.
    pub direction_to_light: Vec3,
    pub ambient: f32,
    pub diffuse: f32,
}

impl SceneLighting {
    /// A single world-fixed key light for the test range, with readable fill.
    /// The cyan fixture strips remain decorative; this is not a shadow system.
    pub fn range() -> Self {
        Self {
            direction_to_light: vec3(-0.3, 0.8, 0.5).normalize(),
            ambient: 0.35,
            diffuse: 0.65,
        }
    }

    /// The offscreen viewmodel camera stays at the origin looking down -Z.
    /// Rotate the world light into that frame, using the *actual* world camera
    /// direction (including pitch and camera recoil), without changing geometry.
    pub fn in_view(self, forward: Vec3) -> Self {
        let forward = forward.normalize();
        let right = forward.cross(Vec3::Y).normalize();
        let up = right.cross(forward);
        Self {
            direction_to_light: vec3(
                self.direction_to_light.dot(right),
                self.direction_to_light.dot(up),
                self.direction_to_light.dot(-forward),
            ),
            ..self
        }
    }

    pub fn irradiance(self, normal: Vec3) -> f32 {
        let normal = normal.try_normalize().unwrap_or(Vec3::Y);
        self.ambient + self.diffuse * normal.dot(self.direction_to_light).max(0.)
    }

    pub fn shade(self, albedo: Color, normal: Vec3) -> Color {
        let shade = self.irradiance(normal);
        Color::new(
            albedo.r * shade,
            albedo.g * shade,
            albedo.b * shade,
            albedo.a,
        )
    }

    /// Re-light an immutable-normal rigid mesh after its current actor transform.
    /// The inverse transpose is necessary for the authored nonuniform scale.
    pub fn shade_rigid(self, mesh: &mut Mesh, albedo: Color, transform: Mat4) {
        let normal_matrix = transform.inverse().transpose();
        for vertex in &mut mesh.vertices {
            vertex.color = self
                .shade(
                    albedo,
                    normal_matrix.transform_vector3(vertex.normal.truncate()),
                )
                .into();
        }
    }

    /// Unlit primitive cubes have zero normals and a single flat color.
    /// Use explicit outward normals so the level and held model share the light.
    pub fn cube_mesh(self, position: Vec3, size: Vec3, color: Color) -> Mesh {
        let mut vertices = Vec::with_capacity(24);
        let mut indices = Vec::with_capacity(36);
        let faces = [
            (Vec3::Z, Vec3::X, Vec3::Y),
            (-Vec3::Z, Vec3::X, Vec3::Y),
            (Vec3::Y, Vec3::Z, Vec3::X),
            (-Vec3::Y, Vec3::Z, Vec3::X),
            (Vec3::X, Vec3::Y, Vec3::Z),
            (-Vec3::X, Vec3::Y, Vec3::Z),
        ];
        for (normal, u, v) in faces {
            let start = vertices.len() as u16;
            for (a, b) in [(-1., -1.), (1., -1.), (1., 1.), (-1., 1.)] {
                let point = position + (normal + a * u + b * v) * size * 0.5;
                let mut vertex = Vertex::new2(
                    point,
                    vec2((a + 1.) * 0.5, (b + 1.) * 0.5),
                    self.shade(color, normal),
                );
                vertex.normal = normal.extend(0.);
                vertices.push(vertex);
            }
            indices.extend([start, start + 1, start + 2, start, start + 2, start + 3]);
        }
        Mesh {
            vertices,
            indices,
            texture: None,
        }
    }

    pub fn draw_cube(self, position: Vec3, size: Vec3, texture: Option<&Texture2D>, color: Color) {
        let mut mesh = self.cube_mesh(position, size, color);
        mesh.texture = texture.cloned();
        draw_mesh(&mesh);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::direction;
    use std::f32::consts::{FRAC_PI_2, PI};

    #[test]
    fn view_light_changes_with_yaw_and_pitch_but_world_light_does_not() {
        let world = SceneLighting::range();
        let front = world.in_view(direction(-FRAC_PI_2, 0.));
        let back = world.in_view(direction(FRAC_PI_2, 0.));
        assert!((front.irradiance(Vec3::Z) - back.irradiance(Vec3::Z)).abs() > 0.3);
        assert!((front.irradiance(Vec3::Y) - back.irradiance(Vec3::Y)).abs() < 1e-6);
        let up = world.in_view(direction(-FRAC_PI_2, 0.6));
        let down = world.in_view(direction(-FRAC_PI_2, -0.6));
        assert!((up.irradiance(Vec3::Z) - down.irradiance(Vec3::Z)).abs() > 0.4);
    }

    #[test]
    fn view_and_world_normals_agree_for_every_yaw_and_pitch() {
        let light = SceneLighting::range();
        for yaw in [-PI, -FRAC_PI_2, 0., FRAC_PI_2, PI] {
            for pitch in [-1.4, -0.6, 0., 0.6, 1.4] {
                let forward = direction(yaw, pitch);
                let right = forward.cross(Vec3::Y).normalize();
                let up = right.cross(forward);
                for view_normal in [Vec3::X, Vec3::Y, Vec3::Z, vec3(1., 2., -3.).normalize()] {
                    let world_normal =
                        right * view_normal.x + up * view_normal.y - forward * view_normal.z;
                    assert!(
                        (light.irradiance(world_normal)
                            - light.in_view(forward).irradiance(view_normal))
                        .abs()
                            < 1e-6
                    );
                }
            }
        }
    }

    #[test]
    fn rigid_actor_inverse_transpose_preserves_albedo_and_handles_rotation_scale() {
        let light = SceneLighting::range();
        let normal = vec3(1., 1., 0.).normalize();
        let mut vertex = Vertex::new2(Vec3::ZERO, Vec2::ZERO, WHITE);
        vertex.normal = normal.extend(0.);
        let mut mesh = Mesh {
            vertices: vec![vertex],
            indices: vec![],
            texture: None,
        };
        let albedo = Color::new(0.8, 0.6, 0.4, 1.);
        let transform = Mat4::from_scale_rotation_translation(
            vec3(2., 0.5, 3.),
            Quat::from_rotation_y(FRAC_PI_2),
            vec3(10., 20., 30.),
        );
        light.shade_rigid(&mut mesh, albedo, transform);
        let expected_normal =
            Quat::from_rotation_y(FRAC_PI_2) * vec3(normal.x / 2., normal.y / 0.5, normal.z / 3.);
        assert_eq!(
            mesh.vertices[0].color,
            Into::<[u8; 4]>::into(light.shade(albedo, expected_normal))
        );
        let lit = mesh.vertices[0].color;
        light.shade_rigid(&mut mesh, albedo, transform);
        assert_eq!(
            mesh.vertices[0].color, lit,
            "must not compound previous lighting"
        );
        light.shade_rigid(&mut mesh, albedo, Mat4::IDENTITY);
        assert_ne!(
            mesh.vertices[0].color, lit,
            "actor motion must relight rigid normals"
        );
        assert_eq!(mesh.vertices[0].normal, normal.extend(0.));
    }

    #[test]
    fn range_cube_has_outward_normals_and_matching_face_shades() {
        let light = SceneLighting::range();
        let mesh = light.cube_mesh(Vec3::ZERO, Vec3::splat(2.), WHITE);
        assert_eq!((mesh.vertices.len(), mesh.indices.len()), (24, 36));
        for vertex in mesh.vertices {
            let normal = vertex.normal.truncate();
            assert_eq!(normal.length(), 1.);
            assert!((normal.dot(vertex.position) - 1.).abs() < 1e-6);
            assert_eq!(
                vertex.color,
                Into::<[u8; 4]>::into(light.shade(WHITE, normal))
            );
        }
    }
}
