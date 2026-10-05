//! CPU per-vertex lighting for the viewmodel, procedural fallback and the CPU
//! world path. Two models:
//! - `Legacy` (default): the established `0.35 + 0.65 * max(N.L, 0)` key light.
//! - `Physical` (opt-in, `physical_lighting = 1`): the shared physically based
//!   model in `crate::lighting`, also evaluated per pixel by the GPU world pass.
//!
//! Macroquad's default material ignores normals, so these paths shade vertex
//! colors from immutable albedo on every draw. Never store a pre-lit albedo.
use crate::lighting::{srgb_to_linear, LightEnvironment, LightingTuning};
use macroquad::prelude::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LightingModel {
    Legacy,
    Physical,
}

#[derive(Clone, Copy, Debug)]
pub struct SceneLighting {
    pub model: LightingModel,
    /// Legacy model terms.
    pub ambient: f32,
    pub diffuse: f32,
    /// Unit direction *toward* the sun, in the same frame as shaded normals.
    pub direction_to_light: Vec3,
    /// World up in the shading frame (sky-light orientation).
    pub up: Vec3,
    /// Direction toward the viewer in the shading frame, or zero for no
    /// specular. The viewmodel uses a distant-viewer approximation (+Z in view
    /// space) so lighting stays translation invariant.
    pub view: Vec3,
    /// 0 = in shadow, 1 = fully sunlit (the viewmodel samples it at the camera).
    pub shadow: f32,
    pub environment: LightEnvironment,
}

impl SceneLighting {
    /// The established range key light (legacy model).
    pub fn range() -> Self {
        Self::from_tuning(&LightingTuning::default())
    }

    /// Legacy unless `physical_lighting` is enabled. Both share the sun direction.
    pub fn from_tuning(tuning: &LightingTuning) -> Self {
        let environment = LightEnvironment::new(tuning);
        Self {
            model: if tuning.physical_lighting >= 0.5 {
                LightingModel::Physical
            } else {
                LightingModel::Legacy
            },
            ambient: 0.35,
            diffuse: 0.65,
            direction_to_light: environment.sun_direction,
            up: Vec3::Y,
            view: Vec3::ZERO,
            shadow: 1.,
            environment,
        }
    }

    pub fn with_shadow(self, shadow: f32) -> Self {
        Self {
            shadow: shadow.clamp(0., 1.),
            ..self
        }
    }

    /// The offscreen viewmodel camera stays at the origin looking down -Z.
    /// Rotate the world light into that frame, using the *actual* world camera
    /// direction (including pitch and camera recoil), without changing geometry.
    pub fn in_view(self, forward: Vec3) -> Self {
        let forward = forward.normalize();
        let right = forward.cross(Vec3::Y).normalize();
        let up = right.cross(forward);
        let rotate = |v: Vec3| vec3(v.dot(right), v.dot(up), v.dot(-forward));
        Self {
            direction_to_light: rotate(self.direction_to_light),
            up: rotate(self.up),
            view: Vec3::Z,
            ..self
        }
    }

    /// Linear diffuse + sky-light radiance for a white surface (no specular).
    fn physical_diffuse(self, normal: Vec3) -> Vec3 {
        let n = normal.try_normalize().unwrap_or(self.up);
        let e = &self.environment;
        let sky = e.ground_color.lerp(e.sky_color, n.dot(self.up) * 0.5 + 0.5);
        e.sun_color * n.dot(self.direction_to_light).max(0.) * self.shadow + sky
    }

    /// Scalar light reaching a normal (frame invariant). Legacy: the key-light
    /// response; physical: luminance of sun + sky light.
    pub fn irradiance(self, normal: Vec3) -> f32 {
        match self.model {
            LightingModel::Legacy => {
                let normal = normal.try_normalize().unwrap_or(Vec3::Y);
                self.ambient + self.diffuse * normal.dot(self.direction_to_light).max(0.)
            }
            LightingModel::Physical => self
                .physical_diffuse(normal)
                .dot(vec3(0.2126, 0.7152, 0.0722)),
        }
    }

    /// Tonemapped display color: Lambert sun, GGX specular (when a viewer is
    /// set) and sky light, through the shared exposure and ACES curve.
    pub fn shade(self, albedo: Color, normal: Vec3) -> Color {
        if self.model == LightingModel::Legacy {
            let shade = self.irradiance(normal);
            return Color::new(
                albedo.r * shade,
                albedo.g * shade,
                albedo.b * shade,
                albedo.a,
            );
        }
        let n = normal.try_normalize().unwrap_or(self.up);
        let linear_albedo = srgb_to_linear(vec3(albedo.r, albedo.g, albedo.b));
        let mut radiance = linear_albedo * self.physical_diffuse(n);
        if self.view != Vec3::ZERO {
            let e = &self.environment;
            let l = self.direction_to_light;
            radiance += e.sun_color
                * crate::lighting::ggx_specular(n, self.view, l, e.roughness, 0.04)
                * n.dot(l).max(0.)
                * self.shadow;
        }
        let c = self.environment.display(radiance);
        Color::new(c.x, c.y, c.z, albedo.a)
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

    /// Physical model with the given tuning, regardless of the setting (tests,
    /// diagnostics).
    pub fn physical(tuning: &LightingTuning) -> Self {
        Self {
            model: LightingModel::Physical,
            ..Self::from_tuning(tuning)
        }
    }

    /// Macroquad's built-in cubes have zero normals and a single flat color.
    /// Use explicit outward normals so the level and held model share the light.
    pub fn cube_mesh(self, position: Vec3, size: Vec3, color: Color) -> Mesh {
        let mut mesh = albedo_cube_mesh(position, size, color);
        for vertex in &mut mesh.vertices {
            vertex.color = self.shade(color, vertex.normal.truncate()).into();
        }
        mesh
    }

    pub fn draw_cube(self, position: Vec3, size: Vec3, texture: Option<&Texture2D>, color: Color) {
        let mut mesh = self.cube_mesh(position, size, color);
        mesh.texture = texture.cloned();
        draw_mesh(&mesh);
    }
}

/// A cube with outward normals and unlit albedo vertex colors, for the GPU
/// lit pass (which shades per pixel from the normal).
pub fn albedo_cube_mesh(position: Vec3, size: Vec3, color: Color) -> Mesh {
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
            let mut vertex = Vertex::new2(point, vec2((a + 1.) * 0.5, (b + 1.) * 0.5), color);
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

    #[test]
    fn legacy_is_default_and_physical_is_opt_in_with_same_sun() {
        let legacy = SceneLighting::range();
        assert_eq!(legacy.model, LightingModel::Legacy);
        let n = vec3(0.2, 0.9, -0.1);
        assert!(
            (legacy.irradiance(n)
                - (0.35 + 0.65 * n.normalize().dot(legacy.direction_to_light).max(0.)))
            .abs()
                < 1e-6
        );
        let tuning = LightingTuning {
            physical_lighting: 1.,
            ..LightingTuning::default()
        };
        let physical = SceneLighting::from_tuning(&tuning);
        assert_eq!(physical.model, LightingModel::Physical);
        assert_eq!(physical.direction_to_light, legacy.direction_to_light);
        // Shadow darkens physical shading; colors stay displayable.
        let lit = physical.shade(GRAY, physical.direction_to_light);
        let dark = physical
            .with_shadow(0.)
            .shade(GRAY, physical.direction_to_light);
        assert!(lit.r > dark.r && lit.r <= 1.);
    }
}
