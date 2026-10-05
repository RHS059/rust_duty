//! Physically based outdoor light model shared by the GPU world renderer and
//! the CPU-lit viewmodel, following the structure of Unreal's default outdoor
//! setup: a directional sun, a sky light (hemispherical ambient), cascaded
//! shadow maps, exponential height fog, ACES filmic tonemapping with manual
//! exposure, screen-space ambient occlusion and bloom.
//!
//! Values are in "pre-exposed" linear units: `exposure` scales scene radiance
//! before the tonemap, as in UE's manual exposure. Albedo inputs are the
//! project's existing display (sRGB) colors and are linearized for shading.
//! This is not Lumen or baked global illumination; bounce light is
//! approximated by the sky light's ground term.
use macroquad::math::{vec3, Mat4, Vec3, Vec4Swizzles};

/// Every tunable lighting value. Loaded from settings.cfg like other tuning.
#[derive(Clone, Debug, PartialEq)]
pub struct LightingTuning {
    /// Sun elevation above the horizon and azimuth (degrees). Azimuth 0 is +X,
    /// 90 is +Z.
    pub sun_elevation: f32,
    pub sun_azimuth: f32,
    /// A white Lambert surface facing the sun receives `sun_intensity`.
    pub sun_intensity: f32,
    /// Sun color temperature (K).
    pub sun_temperature: f32,
    pub sky_intensity: f32,
    pub ground_bounce: f32,
    pub exposure: f32,
    pub shadow_distance: f32,
    pub shadow_resolution: f32,
    pub shadow_softness: f32,
    pub fog_density: f32,
    pub fog_falloff: f32,
    pub fog_height: f32,
    pub fog_max_opacity: f32,
    pub ao_radius: f32,
    pub ao_strength: f32,
    pub bloom_threshold: f32,
    pub bloom_intensity: f32,
    pub specular_roughness: f32,
    /// 0 (default) keeps the established legacy key light everywhere. 1 enables
    /// the physical model: the GPU world pipeline when its shaders compile,
    /// otherwise CPU vertex lighting with the same model (no shadows).
    pub physical_lighting: f32,
}
impl Default for LightingTuning {
    fn default() -> Self {
        // Clear midday. The direction equals the long-standing range key light
        // (-0.3, 0.8, 0.5) normalized, so existing lighting contracts hold.
        let d = vec3(-0.3, 0.8, 0.5).normalize();
        Self {
            sun_elevation: d.y.asin().to_degrees(),
            sun_azimuth: d.z.atan2(d.x).to_degrees(),
            sun_intensity: 3.2,
            sun_temperature: 5600.,
            sky_intensity: 0.9,
            ground_bounce: 0.25,
            exposure: 0.85,
            shadow_distance: 60.,
            shadow_resolution: 2048.,
            shadow_softness: 1.5,
            fog_density: 0.004,
            fog_falloff: 0.18,
            fog_height: 0.,
            fog_max_opacity: 0.85,
            ao_radius: 0.6,
            ao_strength: 1.0,
            bloom_threshold: 1.2,
            bloom_intensity: 0.35,
            specular_roughness: 0.55,
            physical_lighting: 0.,
        }
    }
}
impl LightingTuning {
    pub fn fields_mut(&mut self) -> Vec<(&'static str, &mut f32, f32, f32)> {
        vec![
            ("sun_elevation", &mut self.sun_elevation, 1., 90.),
            ("sun_azimuth", &mut self.sun_azimuth, -360., 360.),
            ("sun_intensity", &mut self.sun_intensity, 0., 20.),
            ("sun_temperature", &mut self.sun_temperature, 1500., 12000.),
            ("sky_intensity", &mut self.sky_intensity, 0., 10.),
            ("ground_bounce", &mut self.ground_bounce, 0., 1.),
            ("exposure", &mut self.exposure, 0.05, 16.),
            ("shadow_distance", &mut self.shadow_distance, 5., 200.),
            (
                "shadow_resolution",
                &mut self.shadow_resolution,
                256.,
                4096.,
            ),
            ("shadow_softness", &mut self.shadow_softness, 0., 4.),
            ("fog_density", &mut self.fog_density, 0., 1.),
            ("fog_falloff", &mut self.fog_falloff, 0.001, 2.),
            ("fog_height", &mut self.fog_height, -50., 50.),
            ("fog_max_opacity", &mut self.fog_max_opacity, 0., 1.),
            ("ao_radius", &mut self.ao_radius, 0.05, 3.),
            ("ao_strength", &mut self.ao_strength, 0., 2.),
            ("bloom_threshold", &mut self.bloom_threshold, 0., 16.),
            ("bloom_intensity", &mut self.bloom_intensity, 0., 4.),
            ("specular_roughness", &mut self.specular_roughness, 0.05, 1.),
            ("physical_lighting", &mut self.physical_lighting, 0., 1.),
        ]
    }
}

/// Derived light environment.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LightEnvironment {
    /// Unit direction toward the sun (world).
    pub sun_direction: Vec3,
    /// Pre-exposed sun radiance color (linear).
    pub sun_color: Vec3,
    /// Sky light for upward- and downward-facing normals.
    pub sky_color: Vec3,
    pub ground_color: Vec3,
    /// Sky dome horizon color (also the fog base color).
    pub horizon_color: Vec3,
    pub exposure: f32,
    pub roughness: f32,
}

impl LightEnvironment {
    pub fn new(t: &LightingTuning) -> Self {
        let (el, az) = (t.sun_elevation.to_radians(), t.sun_azimuth.to_radians());
        let sun_direction = vec3(el.cos() * az.cos(), el.sin(), el.cos() * az.sin()).normalize();
        // Air mass (Kasten-Young) reddens and dims a low sun.
        let air_mass =
            1. / (el.sin().max(0.02) + 0.50572 * (el.to_degrees() + 6.07995).powf(-1.6364));
        let extinction = vec3(0.10, 0.17, 0.32) * 0.35;
        let transmittance = vec3(
            (-extinction.x * air_mass).exp(),
            (-extinction.y * air_mass).exp(),
            (-extinction.z * air_mass).exp(),
        );
        let sun_color = blackbody(t.sun_temperature) * transmittance * t.sun_intensity;
        let daylight = el.sin().max(0.05).sqrt();
        let sky_color = vec3(0.32, 0.48, 0.78) * t.sky_intensity * daylight;
        let ground_color =
            vec3(0.45, 0.42, 0.38) * t.ground_bounce * sun_color.dot(vec3(0.3, 0.6, 0.1)) * 0.35;
        let horizon_color = vec3(0.62, 0.72, 0.82) * t.sky_intensity * daylight;
        Self {
            sun_direction,
            sun_color,
            sky_color,
            ground_color,
            horizon_color,
            exposure: t.exposure,
            roughness: t.specular_roughness,
        }
    }

    /// Sky-light ambient for a normal (hemispherical lerp, as a 2-term SH).
    pub fn ambient(&self, normal: Vec3) -> Vec3 {
        let up = normal.normalize_or_zero().y * 0.5 + 0.5;
        self.ground_color.lerp(self.sky_color, up)
    }

    /// Linear outgoing radiance: Lambert sun + GGX specular + sky light.
    /// `view` points from the surface toward the camera.
    pub fn radiance(&self, albedo: Vec3, normal: Vec3, view: Vec3, shadow: f32, ao: f32) -> Vec3 {
        let n = normal.try_normalize().unwrap_or(Vec3::Y);
        let l = self.sun_direction;
        let n_dot_l = n.dot(l).max(0.);
        let diffuse = albedo * self.sun_color * n_dot_l * shadow;
        let specular = match view.try_normalize() {
            Some(v) => {
                self.sun_color * ggx_specular(n, v, l, self.roughness, 0.04) * n_dot_l * shadow
            }
            None => Vec3::ZERO,
        };
        diffuse + specular + albedo * self.ambient(n) * ao
    }

    /// Pre-exposed linear radiance to display (gamma 2.2) through ACES.
    pub fn display(&self, linear: Vec3) -> Vec3 {
        let c = aces(linear * self.exposure);
        vec3(c.x.powf(1. / 2.2), c.y.powf(1. / 2.2), c.z.powf(1. / 2.2))
    }
}

/// Narkowicz ACES filmic fit (the same curve the GPU pass uses).
pub fn aces(x: Vec3) -> Vec3 {
    let f = |x: f32| {
        let x = x.max(0.);
        ((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)).clamp(0., 1.)
    };
    vec3(f(x.x), f(x.y), f(x.z))
}

pub fn srgb_to_linear(c: Vec3) -> Vec3 {
    vec3(
        c.x.max(0.).powf(2.2),
        c.y.max(0.).powf(2.2),
        c.z.max(0.).powf(2.2),
    )
}

/// GGX NDF, Smith-Schlick visibility and Schlick Fresnel (UE's default lit
/// BRDF terms), without the N·L factor.
pub fn ggx_specular(n: Vec3, v: Vec3, l: Vec3, roughness: f32, f0: f32) -> f32 {
    let h = (v + l).normalize_or_zero();
    let a = (roughness * roughness).max(1e-3);
    let a2 = a * a;
    let n_dot_h = n.dot(h).max(0.);
    let n_dot_v = n.dot(v).max(1e-4);
    let n_dot_l = n.dot(l).max(1e-4);
    let d = a2 / (std::f32::consts::PI * (n_dot_h * n_dot_h * (a2 - 1.) + 1.).powi(2));
    let k = a * 0.5;
    let vis = 0.25 / ((n_dot_v * (1. - k) + k) * (n_dot_l * (1. - k) + k));
    let f = f0 + (1. - f0) * (1. - v.dot(h).max(0.)).powi(5);
    d * vis * f
}

/// Blackbody tint normalized to unit luminance (Helland approximation).
pub fn blackbody(kelvin: f32) -> Vec3 {
    let t = kelvin / 100.;
    let r = if t <= 66. {
        1.
    } else {
        (1.292_936 * (t - 60.).powf(-0.133_204_8)).clamp(0., 1.)
    };
    let g = if t <= 66. {
        (0.390_081_6 * t.ln() - 0.631_841_4).clamp(0., 1.)
    } else {
        (1.129_890_9 * (t - 60.).powf(-0.075_514_85)).clamp(0., 1.)
    };
    let b = if t >= 66. {
        1.
    } else if t <= 19. {
        0.
    } else {
        (0.543_206_8 * (t - 10.).ln() - 1.196_254_1).clamp(0., 1.)
    };
    let c = vec3(r, g, b);
    c / c.dot(vec3(0.2126, 0.7152, 0.0722)).max(1e-3)
}

/// Cascade split distances (log/uniform blend). Returns `count + 1` values.
pub fn cascade_splits(near: f32, far: f32, count: usize, lambda: f32) -> Vec<f32> {
    (0..=count)
        .map(|i| {
            let p = i as f32 / count as f32;
            let log = near * (far / near).powf(p);
            let uniform = near + (far - near) * p;
            lambda * log + (1. - lambda) * uniform
        })
        .collect()
}

/// Light view-projection for one cascade: bounding sphere of the camera frustum
/// slice (rotation-stable) with its center snapped to shadow texels, so shadows
/// do not shimmer as the camera moves or turns.
#[allow(clippy::too_many_arguments)]
pub fn fit_cascade(
    eye: Vec3,
    forward: Vec3,
    up: Vec3,
    vertical_fov: f32,
    aspect: f32,
    near: f32,
    far: f32,
    sun_direction: Vec3,
    resolution: f32,
    depth_range: f32,
) -> Mat4 {
    let forward = forward.normalize();
    let right = forward.cross(up).normalize();
    let up = right.cross(forward);
    let th = (vertical_fov * 0.5).tan();
    let mut corners = Vec::with_capacity(8);
    for d in [near, far] {
        for (sx, sy) in [(-1., -1.), (1., -1.), (1., 1.), (-1., 1.)] {
            corners.push(eye + forward * d + right * (sx * th * aspect * d) + up * (sy * th * d));
        }
    }
    let center = corners.iter().fold(Vec3::ZERO, |a, c| a + *c) / 8.;
    let radius = corners
        .iter()
        .map(|c| (*c - center).length())
        .fold(0., f32::max)
        .max(0.5);
    let radius = (radius * 16.).ceil() / 16.;
    let light_up = if sun_direction.y.abs() > 0.99 {
        Vec3::Z
    } else {
        Vec3::Y
    };
    let view = Mat4::look_at_rh(Vec3::ZERO, -sun_direction, light_up);
    let texel = 2. * radius / resolution;
    let mut c = view.transform_point3(center);
    c.x = (c.x / texel).floor() * texel;
    c.y = (c.y / texel).floor() * texel;
    let projection = Mat4::orthographic_rh_gl(
        c.x - radius,
        c.x + radius,
        c.y - radius,
        c.y + radius,
        -c.z - depth_range,
        -c.z + depth_range,
    );
    projection * view
}

/// Is `point` inside the cascade's clip volume (with a small margin)?
pub fn in_cascade(matrix: Mat4, point: Vec3) -> bool {
    let p = matrix * point.extend(1.);
    let ndc = p.xyz() / p.w;
    ndc.x.abs() < 0.98 && ndc.y.abs() < 0.98 && ndc.z.abs() <= 1.
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_sun_matches_the_existing_range_light() {
        let env = LightEnvironment::new(&LightingTuning::default());
        assert!(env.sun_direction.distance(vec3(-0.3, 0.8, 0.5).normalize()) < 1e-5);
        assert!(env.sun_color.min_element() > 0.5 * env.sun_color.max_element());
        assert!(env.sun_color.length() > env.sky_color.length() * 2.);
    }

    #[test]
    fn low_sun_is_warmer_and_dimmer() {
        let mut t = LightingTuning::default();
        let high = LightEnvironment::new(&t);
        t.sun_elevation = 6.;
        let low = LightEnvironment::new(&t);
        assert!(low.sun_color.z / low.sun_color.x < high.sun_color.z / high.sun_color.x);
        assert!(low.sun_color.length() < high.sun_color.length());
    }

    #[test]
    fn aces_is_monotonic_bounded_and_matches_reference_points() {
        let mut last = -1.;
        for i in 0..=400 {
            let y = aces(Vec3::splat(i as f32 * 0.05)).x;
            assert!(y >= last && (0. ..=1.).contains(&y));
            last = y;
        }
        assert!((aces(Vec3::splat(0.18)).x - 0.2671).abs() < 1e-3);
        assert!((aces(Vec3::ONE).x - 0.8038).abs() < 1e-3);
    }

    #[test]
    fn energy_terms_behave() {
        let env = LightEnvironment::new(&LightingTuning::default());
        let albedo = Vec3::splat(0.5);
        let l = env.sun_direction;
        let lit = env.radiance(albedo, l, l, 1., 1.);
        let shadowed = env.radiance(albedo, l, l, 0., 1.);
        assert!(lit.length() > shadowed.length() * 2.);
        assert!(env.radiance(albedo, Vec3::Y, Vec3::Y, 0., 0.).length() < 1e-6);
        assert!(env.ambient(Vec3::Y).length() > env.ambient(-Vec3::Y).length());
        let n = Vec3::Y;
        let mirror = ggx_specular(n, vec3(-l.x, l.y, -l.z), l, 0.3, 0.04);
        let grazing = ggx_specular(n, vec3(l.x, 0.05, l.z).normalize(), l, 0.3, 0.04);
        assert!(mirror.is_finite() && mirror > grazing);
    }

    #[test]
    fn cascades_cover_their_slices_and_are_shimmer_stable() {
        let splits = cascade_splits(0.1, 60., 3, 0.75);
        assert_eq!(splits.len(), 4);
        assert!(splits.windows(2).all(|w| w[0] < w[1]));
        let sun = vec3(-0.3, 0.8, 0.5).normalize();
        let eye = vec3(0., 1.5, 9.);
        let forward = vec3(0., 0., -1.);
        let fit = |eye: Vec3, i: usize| {
            fit_cascade(
                eye,
                forward,
                Vec3::Y,
                1.0,
                16. / 9.,
                splits[i],
                splits[i + 1],
                sun,
                2048.,
                100.,
            )
        };
        let probe = vec3(3., 0., -5.).extend(1.);
        for i in 0..3 {
            let m = fit(eye, i);
            for d in [
                splits[i],
                (splits[i] + splits[i + 1]) * 0.5,
                splits[i + 1] * 0.999,
            ] {
                assert!(
                    in_cascade(m, eye + forward * d),
                    "cascade {i} misses depth {d}"
                );
            }
            // A sub-texel camera move leaves the snapped matrix unchanged; a 1 m move does not.
            assert!(((m * probe) - (fit(eye + Vec3::X * 1e-5, i) * probe)).length() < 1e-5);
            assert!(((m * probe) - (fit(eye + Vec3::X, i) * probe)).length() > 1e-3);
        }
    }
}
