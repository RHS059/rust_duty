//! One presentation burst per committed shot: a procedural muzzle flash, a
//! point light, smoke leaving the muzzle, and a casing from the ejection port.
//!
//! The flash is generated as triangle geometry. It does not sample a sprite or
//! texture. Shape, brightness and flicker come from the shot seed and age.
//! Size, intensity, duration and light strength scale from the bore diameter.
//!
//! Shells are cosmetic. They never feed the shot ray. They collide with the
//! same static blocks and ramps the player walks on, and they are removed five
//! seconds after ejection.

use crate::sim::{Block, Ramp, Shot};
use macroquad::math::{vec3, Vec3};
use macroquad::prelude::*;

pub const SHELL_LIFE: f32 = 5.;
/// 5.56 mm is the reference bore. Its flash profile is the unit scale.
pub const REFERENCE_CALIBER_MM: f32 = 5.56;
const SMOKE_LIFE: f32 = 1.15;
const SHELL_RADIUS: f32 = 0.012;
const GRAVITY: f32 = 9.81;
const RESTITUTION: f32 = 0.38;
const FRICTION: f32 = 0.55;
const PORT_BACK: f32 = 0.42;
const PORT_RIGHT: f32 = 0.036;
const PORT_UP: f32 = 0.012;
const SUBSTEP: f32 = 1. / 240.;
const PETALS: usize = 11;
const PLUME_RINGS: usize = 5;
const RING_POINTS: usize = 8;

const SMOKE_TINT: Color = Color::new(0.58, 0.62, 0.64, 1.);
const BRASS: Color = Color::new(0.76, 0.55, 0.24, 1.);
const LIGHT_COLOR: [f32; 3] = [1., 0.74, 0.34];

/// How a bore diameter turns into the four flash controls.
#[derive(Clone, Copy, Debug)]
pub struct FlashProfile {
    /// Axial and radial size, 1 at 5.56 mm.
    pub size: f32,
    /// Vertex brightness, 1 at 5.56 mm.
    pub intensity: f32,
    /// Seconds the flash remains visible.
    pub duration: f32,
    /// Point-light strength, 1 at 5.56 mm.
    pub light: f32,
}

impl FlashProfile {
    pub fn from_millimeters(mm: f32) -> Self {
        let mm = if mm.is_finite() {
            mm.clamp(2., 20.)
        } else {
            REFERENCE_CALIBER_MM
        };
        let ratio = mm / REFERENCE_CALIBER_MM;
        Self {
            size: ratio.powf(0.85),
            intensity: ratio.powf(1.15),
            duration: 0.05 * ratio.powf(0.55),
            light: ratio.powf(1.45),
        }
    }
}

/// Point light carried by a live muzzle flash.
#[derive(Clone, Copy)]
pub struct MuzzleLight {
    pub position: Vec3,
    pub color: [f32; 3],
    pub intensity: f32,
    pub range: f32,
}

/// Textureless triangle soup for one flash. Built in code, drawn with no image.
#[derive(Clone, Debug)]
pub struct ProceduralFlash {
    pub positions: Vec<Vec3>,
    pub colors: Vec<[f32; 4]>,
    pub indices: Vec<u16>,
}

struct Burst {
    age: f32,
    position: Vec3,
    forward: Vec3,
    profile: FlashProfile,
    seed: u32,
}

struct Smoke {
    position: Vec3,
    velocity: Vec3,
    age: f32,
    size: f32,
}

struct Shell {
    position: Vec3,
    velocity: Vec3,
    axis: Vec3,
    spin: f32,
    spin_rate: f32,
    age: f32,
    asleep: bool,
}

pub struct MuzzleFx {
    caliber_mm: f32,
    bursts: Vec<Burst>,
    smoke: Vec<Smoke>,
    shells: Vec<Shell>,
    flash_material: Option<Material>,
    material_failed: bool,
}

impl Default for MuzzleFx {
    fn default() -> Self {
        Self {
            caliber_mm: REFERENCE_CALIBER_MM,
            bursts: Vec::new(),
            smoke: Vec::new(),
            shells: Vec::new(),
            flash_material: None,
            material_failed: false,
        }
    }
}

impl MuzzleFx {
    pub fn clear(&mut self) {
        self.bursts.clear();
        self.smoke.clear();
        self.shells.clear();
    }

    /// Bore diameter in millimetres. The next shot uses the scaled flash profile.
    pub fn set_caliber_mm(&mut self, mm: f32) {
        self.caliber_mm = if mm.is_finite() {
            mm.clamp(2., 20.)
        } else {
            REFERENCE_CALIBER_MM
        };
    }

    pub fn caliber_mm(&self) -> f32 {
        self.caliber_mm
    }

    /// Spawn the whole burst from a simulation shot. One call, one shot.
    pub fn spawn_shot(&mut self, shot: &Shot) {
        let mut seed = (shot.time.to_bits() as u32)
            ^ shot.spread_degrees.to_bits()
            ^ self.caliber_mm.to_bits()
            ^ 0x9e37_79b9;
        let forward = unit_or(shot.barrel_forward, -Vec3::Z);
        let right = unit_or(shot.barrel_right, Vec3::X);
        let up = unit_or(shot.barrel_up, Vec3::Y);
        let muzzle = shot.muzzle;
        self.bursts.push(Burst {
            age: 0.,
            position: muzzle,
            forward,
            profile: FlashProfile::from_millimeters(self.caliber_mm),
            seed,
        });
        for i in 0..7 {
            let along = 0.35 + unit(&mut seed) * 1.15;
            let side = (unit(&mut seed) - 0.5) * 0.55;
            let rise = (unit(&mut seed) - 0.15) * 0.45;
            self.smoke.push(Smoke {
                position: muzzle + forward * (0.02 + i as f32 * 0.004),
                velocity: shot.carrier_velocity * 0.15
                    + forward * along
                    + right * side
                    + up * rise
                    + Vec3::Y * 0.25,
                age: 0.,
                size: 0.02 + unit(&mut seed) * 0.018,
            });
        }
        let port = muzzle - forward * PORT_BACK + right * PORT_RIGHT + up * PORT_UP;
        let toss = right * (2.15 + unit(&mut seed) * 0.55) + up * (1.55 + unit(&mut seed) * 0.7)
            - forward * (0.35 + unit(&mut seed) * 0.25);
        let axis = unit_or(
            right * (unit(&mut seed) - 0.5) + up * (unit(&mut seed) - 0.5) + forward,
            Vec3::X,
        );
        self.shells.push(Shell {
            position: port,
            velocity: toss + shot.carrier_velocity,
            axis,
            spin: unit(&mut seed) * std::f32::consts::TAU,
            spin_rate: 18. + unit(&mut seed) * 22.,
            age: 0.,
            asleep: false,
        });
    }

    pub fn update(&mut self, dt: f32, blocks: &[Block], ramps: &[Ramp]) {
        if !dt.is_finite() || dt <= 0. {
            return;
        }
        // Age uses the full step so a five-second lifetime is exact. Physics is
        // substepped and capped so a hitch cannot tunnel a casing through the floor.
        let dt = dt.min(8.);
        let physics_dt = dt.min(0.25);
        for burst in &mut self.bursts {
            burst.age += dt;
        }
        self.bursts
            .retain(|burst| burst.age < burst.profile.duration);
        for puff in &mut self.smoke {
            puff.age += dt;
            puff.velocity.y += 0.35 * dt;
            puff.velocity *= 1. - (1.6 * dt).min(0.5);
            puff.position += puff.velocity * dt;
            puff.size += dt * 0.09;
        }
        self.smoke.retain(|puff| puff.age < SMOKE_LIFE);
        let steps = ((physics_dt / SUBSTEP).ceil() as u32).clamp(1, 64);
        let h = physics_dt / steps as f32;
        for shell in &mut self.shells {
            shell.age += dt;
            if shell.age >= SHELL_LIFE {
                continue;
            }
            shell.spin += shell.spin_rate * dt;
            if shell.asleep {
                continue;
            }
            for _ in 0..steps {
                if shell.asleep {
                    break;
                }
                shell.velocity.y -= GRAVITY * h;
                shell.position += shell.velocity * h;
                let mut supported = false;
                for _ in 0..3 {
                    if resolve_blocks(shell, blocks) {
                        supported = true;
                    }
                    if resolve_ramps(shell, ramps) {
                        supported = true;
                    }
                }
                if supported
                    && shell.velocity.y.abs() < 0.35
                    && vec3(shell.velocity.x, 0., shell.velocity.z).length() < 0.2
                {
                    shell.velocity = Vec3::ZERO;
                    shell.asleep = true;
                    break;
                }
            }
        }
        self.shells.retain(|shell| shell.age < SHELL_LIFE);
    }

    pub fn shell_count(&self) -> usize {
        self.shells.len()
    }

    pub fn smoke_count(&self) -> usize {
        self.smoke.len()
    }

    pub fn flash_intensity(&self) -> f32 {
        self.bursts.iter().map(burst_brightness).fold(0., f32::max)
    }

    pub fn lights(&self) -> Vec<MuzzleLight> {
        self.bursts
            .iter()
            .map(|burst| {
                let env = flash_envelope(burst.age / burst.profile.duration);
                let flick = flicker(burst.seed, burst.age, 0);
                MuzzleLight {
                    position: burst.position,
                    color: LIGHT_COLOR,
                    intensity: env * burst.profile.light * flick,
                    range: (0.55 + 2.6 * env) * burst.profile.light.sqrt(),
                }
            })
            .collect()
    }

    /// Current procedural flashes, in the order they were fired. No texture data.
    pub fn procedural_flashes(&self, muzzle: Vec3, barrel: Vec3) -> Vec<ProceduralFlash> {
        self.bursts
            .iter()
            .map(|burst| build_procedural_flash(muzzle, barrel, burst))
            .collect()
    }

    /// Flash drawn in the viewmodel camera, on the live barrel tip.
    pub fn draw_barrel(&mut self, muzzle: Vec3, barrel: Vec3) {
        if !muzzle.is_finite() {
            return;
        }
        let flashes = self.procedural_flashes(muzzle, barrel);
        for flash in &flashes {
            self.draw_flash_mesh(flash);
        }
    }

    /// World-space light, smoke, shells, and (when the viewmodel is not drawing it) the flash core.
    pub fn draw_world(&mut self, eye: Vec3, draw_flash_core: bool) {
        let lights = self.lights();
        for light in &lights {
            self.draw_ground_pool(light);
            self.draw_light_halo(light, eye);
        }
        if draw_flash_core {
            let flashes: Vec<_> = self
                .bursts
                .iter()
                .map(|burst| build_procedural_flash(burst.position, burst.forward, burst))
                .collect();
            for flash in &flashes {
                self.draw_flash_mesh(flash);
            }
        }
        for puff in &self.smoke {
            let fade = (1. - puff.age / SMOKE_LIFE).clamp(0., 1.);
            let color = illuminate(
                puff.position,
                Color::new(SMOKE_TINT.r, SMOKE_TINT.g, SMOKE_TINT.b, 0.22 * fade),
                &lights,
            );
            draw_sphere(
                puff.position,
                puff.size * (0.85 + puff.age * 0.9),
                None,
                color,
            );
        }
        for shell in &self.shells {
            let fade = if shell.age > SHELL_LIFE - 0.35 {
                ((SHELL_LIFE - shell.age) / 0.35).clamp(0., 1.)
            } else {
                1.
            };
            let color = illuminate(
                shell.position,
                Color::new(BRASS.r, BRASS.g, BRASS.b, fade),
                &lights,
            );
            let rotation = Quat::from_axis_angle(shell.axis, shell.spin);
            let matrix = Mat4::from_scale_rotation_translation(
                vec3(0.009, 0.009, 0.034),
                rotation,
                shell.position,
            );
            unsafe {
                get_internal_gl().quad_gl.push_model_matrix(matrix);
            }
            draw_cube(Vec3::ZERO, Vec3::ONE, None, color);
            unsafe {
                get_internal_gl().quad_gl.pop_model_matrix();
            }
        }
    }

    fn draw_flash_mesh(&mut self, flash: &ProceduralFlash) {
        if flash.indices.len() < 3 {
            return;
        }
        let vertices = flash
            .positions
            .iter()
            .zip(&flash.colors)
            .map(|(p, c)| Vertex::new(p.x, p.y, p.z, 0., 0., Color::new(c[0], c[1], c[2], c[3])))
            .collect();
        let mesh = Mesh {
            vertices,
            indices: flash.indices.clone(),
            texture: None,
        };
        if let Some(material) = self.additive_material() {
            gl_use_material(material);
            draw_mesh(&mesh);
            gl_use_default_material();
        } else {
            draw_mesh(&mesh);
        }
    }

    fn additive_material(&mut self) -> Option<&Material> {
        if self.flash_material.is_none() && !self.material_failed {
            match load_material(
                ShaderSource::Glsl {
                    vertex: FLASH_VERTEX,
                    fragment: FLASH_FRAGMENT,
                },
                MaterialParams {
                    pipeline_params: PipelineParams {
                        cull_face: macroquad::miniquad::CullFace::Nothing,
                        depth_test: macroquad::miniquad::Comparison::LessOrEqual,
                        depth_write: false,
                        color_blend: Some(macroquad::miniquad::BlendState::new(
                            macroquad::miniquad::Equation::Add,
                            macroquad::miniquad::BlendFactor::Value(
                                macroquad::miniquad::BlendValue::SourceAlpha,
                            ),
                            macroquad::miniquad::BlendFactor::One,
                        )),
                        alpha_blend: Some(macroquad::miniquad::BlendState::new(
                            macroquad::miniquad::Equation::Add,
                            macroquad::miniquad::BlendFactor::Zero,
                            macroquad::miniquad::BlendFactor::One,
                        )),
                        ..Default::default()
                    },
                    ..Default::default()
                },
            ) {
                Ok(material) => self.flash_material = Some(material),
                Err(error) => {
                    eprintln!("Procedural muzzle flash material failed: {error}");
                    self.material_failed = true;
                }
            }
        }
        self.flash_material.as_ref()
    }

    fn draw_light_halo(&mut self, light: &MuzzleLight, eye: Vec3) {
        if light.intensity <= 0.02 {
            return;
        }
        let to_eye = eye - light.position;
        let forward = unit_or(to_eye, Vec3::Z);
        let right = unit_or(forward.cross(Vec3::Y), Vec3::X);
        let up = unit_or(right.cross(forward), Vec3::Y);
        let radius = (0.06 + 0.16 * light.intensity) * light.range.sqrt().max(0.4);
        let color = [
            light.color[0],
            light.color[1],
            light.color[2],
            0.55 * light.intensity.min(1.4),
        ];
        let flash = radial_disc(light.position, right, up, radius, color, 14);
        self.draw_flash_mesh(&flash);
    }

    fn draw_ground_pool(&mut self, light: &MuzzleLight) {
        let height = light.position.y;
        if !(0. ..light.range).contains(&height) {
            return;
        }
        let reach =
            (1. - height / light.range).max(0.) * light.range * 0.42 * light.intensity.sqrt();
        if reach < 0.04 {
            return;
        }
        let center = vec3(light.position.x, 0.02, light.position.z);
        let color = [
            light.color[0],
            light.color[1],
            light.color[2],
            0.45 * light.intensity.min(1.2),
        ];
        let flash = radial_disc(center, Vec3::X, Vec3::Z, reach, color, 16);
        self.draw_flash_mesh(&flash);
    }
}

const FLASH_VERTEX: &str = r#"#version 100
attribute vec3 position;
attribute vec2 texcoord;
attribute vec4 color0;
attribute vec4 normal;

varying lowp vec4 color;

uniform mat4 Model;
uniform mat4 Projection;
uniform vec4 _Time;

void main() {
    gl_Position = Projection * Model * vec4(position, 1.0);
    color = color0 / 255.0;
}
"#;

const FLASH_FRAGMENT: &str = r#"#version 100
varying lowp vec4 color;

void main() {
    gl_FragColor = vec4(color.rgb, color.a);
}
"#;

fn burst_brightness(burst: &Burst) -> f32 {
    flash_envelope(burst.age / burst.profile.duration) * burst.profile.intensity
}

fn flash_envelope(t: f32) -> f32 {
    let t = t.clamp(0., 1.);
    (1. - t).powf(1.35)
}

/// 1 on the birth frame, then a high-frequency hash so each petal dances.
fn flicker(seed: u32, age: f32, channel: u32) -> f32 {
    if age <= 1e-5 {
        return 1.;
    }
    let bucket = (age * 78.) as u32;
    let n = hash01(seed ^ bucket.wrapping_mul(0x9e37_79b9) ^ channel.wrapping_mul(0x85eb_ca6b));
    let wave = (age * (46. + channel as f32 * 3.5) + (seed as f32) * 0.001).sin() * 0.5 + 0.5;
    0.58 + 0.42 * (0.72 * n + 0.28 * wave)
}

fn build_procedural_flash(muzzle: Vec3, barrel: Vec3, burst: &Burst) -> ProceduralFlash {
    let (forward, right, up) = basis(barrel);
    let profile = burst.profile;
    let age = burst.age;
    let seed = burst.seed;
    let env = flash_envelope(age / profile.duration.max(1e-4));
    let global = flicker(seed, age, 1);
    let brightness = profile.intensity * env;
    let mut flash = ProceduralFlash {
        positions: Vec::new(),
        colors: Vec::new(),
        indices: Vec::new(),
    };
    if env <= 0.001 {
        return flash;
    }

    let core_r = 0.016 * profile.size * (0.85 + 0.15 * global);
    push_octahedron(
        &mut flash,
        muzzle + forward * (0.008 * profile.size),
        core_r,
        scale_tone(1., 0.95 * brightness.min(1.4), brightness),
    );

    let mut ring_starts = [0u16; PLUME_RINGS];
    for (ring, ring_start) in ring_starts.iter_mut().enumerate() {
        let along_t = ring as f32 / (PLUME_RINGS as f32 - 1.);
        let along = (0.012 + along_t * 0.20 * (0.45 + 0.55 * env)) * profile.size * global;
        let radius_curve = (1. - along_t).powf(0.65) * (0.35 + 0.65 * (1. - along_t));
        let radius =
            (0.006 + 0.034 * radius_curve) * profile.size * flicker(seed, age, 20 + ring as u32);
        *ring_start = flash.positions.len() as u16;
        let hot = (1. - along_t).powf(0.8);
        let alpha = (1. - along_t * 0.92) * brightness.min(1.3);
        for point in 0..RING_POINTS {
            let ang = std::f32::consts::TAU * point as f32 / RING_POINTS as f32
                + hash01(seed ^ ring as u32) * 0.4
                + age * 9. * (hash01(seed.wrapping_add(ring as u32)) - 0.5);
            let radial = right * ang.cos() + up * ang.sin();
            flash
                .positions
                .push(muzzle + forward * along + radial * radius);
            flash.colors.push(scale_tone(hot, alpha, brightness));
        }
    }
    for ring in 0..PLUME_RINGS - 1 {
        for point in 0..RING_POINTS {
            let a = ring_starts[ring] + point as u16;
            let b = ring_starts[ring] + ((point + 1) % RING_POINTS) as u16;
            let c = ring_starts[ring + 1] + point as u16;
            let d = ring_starts[ring + 1] + ((point + 1) % RING_POINTS) as u16;
            push_tri(&mut flash, a, c, b);
            push_tri(&mut flash, b, c, d);
        }
    }

    for petal in 0..PETALS {
        let n = hash01(seed.wrapping_mul(13).wrapping_add(petal as u32 * 17));
        let flick = flicker(seed, age, 40 + petal as u32);
        let ang = std::f32::consts::TAU * (petal as f32 + 0.35 * (n - 0.5)) / PETALS as f32
            + age * 11. * (n - 0.5);
        let radial = right * ang.cos() + up * ang.sin();
        let dir = unit_or(
            radial * (0.55 + 0.4 * n) + forward * (0.85 + 0.5 * n),
            forward,
        );
        let side = unit_or(dir.cross(forward), right);
        let length = profile.size * (0.035 + 0.13 * n) * flick * (0.35 + 0.65 * env);
        let width = profile.size * (0.006 + 0.014 * (1. - n)) * flick;
        let base = muzzle + forward * (0.01 * profile.size);
        let mid =
            base + dir * length * 0.42 + side * width * (if petal % 2 == 0 { 0.65 } else { -0.65 });
        let tip = base + dir * length;
        let hot_base = scale_tone(0.92, 0.9 * brightness.min(1.2), brightness);
        let hot_mid = scale_tone(0.55, 0.55 * brightness.min(1.2), brightness);
        let hot_tip = scale_tone(0.15, 0.05 * brightness.min(1.), brightness);
        let i0 = push_vert(&mut flash, base, hot_base);
        let i1 = push_vert(&mut flash, mid, hot_mid);
        let i2 = push_vert(&mut flash, tip, hot_tip);
        let i3 = push_vert(&mut flash, base + side * width * 0.35, hot_base);
        push_tri(&mut flash, i0, i1, i2);
        push_tri(&mut flash, i0, i3, i1);
    }

    flash
}

fn radial_disc(
    center: Vec3,
    right: Vec3,
    up: Vec3,
    radius: f32,
    color: [f32; 4],
    segments: usize,
) -> ProceduralFlash {
    let mut flash = ProceduralFlash {
        positions: vec![center],
        colors: vec![color],
        indices: Vec::new(),
    };
    let rim = [color[0] * 0.7, color[1] * 0.45, color[2] * 0.2, 0.];
    for i in 0..segments {
        let ang = std::f32::consts::TAU * i as f32 / segments as f32;
        flash
            .positions
            .push(center + right * ang.cos() * radius + up * ang.sin() * radius);
        flash.colors.push(rim);
    }
    for i in 0..segments {
        let a = 1 + i as u16;
        let b = 1 + ((i + 1) % segments) as u16;
        push_tri(&mut flash, 0, a, b);
    }
    flash
}

fn basis(barrel: Vec3) -> (Vec3, Vec3, Vec3) {
    let forward = unit_or(barrel, -Vec3::Z);
    let right = unit_or(forward.cross(Vec3::Y), Vec3::X);
    let up = unit_or(right.cross(forward), Vec3::Y);
    (forward, right, up)
}

fn scale_tone(hot: f32, alpha: f32, brightness: f32) -> [f32; 4] {
    let hot = hot.clamp(0., 1.);
    let boost = brightness.max(0.);
    let white = (boost - 1.).max(0.) * 0.35;
    [
        (1. * boost).min(1.),
        ((0.28 + 0.7 * hot + white) * boost).min(1.),
        ((0.05 + 0.9 * hot * hot + white) * boost).min(1.),
        (alpha * boost.min(1.5)).clamp(0., 1.),
    ]
}

fn push_octahedron(flash: &mut ProceduralFlash, center: Vec3, radius: f32, color: [f32; 4]) {
    let r = radius;
    let verts = [
        center + Vec3::X * r,
        center - Vec3::X * r,
        center + Vec3::Y * r,
        center - Vec3::Y * r,
        center + Vec3::Z * r,
        center - Vec3::Z * r,
    ];
    let base = flash.positions.len() as u16;
    for v in verts {
        push_vert(flash, v, color);
    }
    let faces = [
        [0, 2, 4],
        [2, 1, 4],
        [1, 3, 4],
        [3, 0, 4],
        [2, 0, 5],
        [1, 2, 5],
        [3, 1, 5],
        [0, 3, 5],
    ];
    for face in faces {
        push_tri(flash, base + face[0], base + face[1], base + face[2]);
    }
}

fn push_vert(flash: &mut ProceduralFlash, position: Vec3, color: [f32; 4]) -> u16 {
    let index = flash.positions.len() as u16;
    flash.positions.push(position);
    flash.colors.push(color);
    index
}

fn push_tri(flash: &mut ProceduralFlash, a: u16, b: u16, c: u16) {
    flash.indices.extend_from_slice(&[a, b, c]);
}

fn hash01(mut n: u32) -> f32 {
    n = n.wrapping_mul(747796405).wrapping_add(2891336453);
    n = (n >> 16) ^ n;
    n = n.wrapping_mul(0x7feb_352d);
    n = (n >> 15) ^ n;
    (n >> 8) as f32 / 16_777_216.
}

fn unit(seed: &mut u32) -> f32 {
    *seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
    (*seed >> 8) as f32 / 16_777_216.
}

fn unit_or(v: Vec3, fallback: Vec3) -> Vec3 {
    v.try_normalize().unwrap_or(fallback)
}

fn illuminate(position: Vec3, mut color: Color, lights: &[MuzzleLight]) -> Color {
    for light in lights {
        let distance = position.distance(light.position).max(0.04);
        let falloff = (1. - distance / light.range).max(0.).powi(2) * light.intensity;
        color.r = (color.r + light.color[0] * falloff * 0.85).min(1.5);
        color.g = (color.g + light.color[1] * falloff * 0.85).min(1.5);
        color.b = (color.b + light.color[2] * falloff * 0.85).min(1.5);
    }
    color
}

fn resolve_blocks(shell: &mut Shell, blocks: &[Block]) -> bool {
    let mut supported = false;
    for block in blocks {
        if let Some(normal) = separate(shell, block.bounds.min, block.bounds.max) {
            bounce(shell, normal);
            if normal.y > 0.65 {
                supported = true;
            }
        }
    }
    supported
}

fn resolve_ramps(shell: &mut Shell, ramps: &[Ramp]) -> bool {
    let mut supported = false;
    for ramp in ramps {
        let Some(surface) = ramp.surface(shell.position.x, shell.position.z) else {
            continue;
        };
        let normal = unit_or(vec3(0., 1., ramp.slope()), Vec3::Y);
        let lift = SHELL_RADIUS / normal.y.max(0.2);
        if shell.position.y <= surface + lift && shell.position.y >= surface - 0.25 {
            shell.position.y = surface + lift;
            bounce(shell, normal);
            // A casing should stay on the slope instead of skating off the lip.
            shell.velocity *= 0.45;
            if shell.velocity.length() < 0.75 {
                shell.velocity = Vec3::ZERO;
                shell.asleep = true;
            }
            supported = true;
        }
    }
    supported
}

/// Push a shell out of an AABB. Returns the contact normal when it was overlapping.
fn separate(shell: &mut Shell, min: Vec3, max: Vec3) -> Option<Vec3> {
    let center = shell.position;
    let closest = center.clamp(min, max);
    let delta = center - closest;
    let dist2 = delta.length_squared();
    if dist2 > SHELL_RADIUS * SHELL_RADIUS {
        return None;
    }
    if dist2 > 1e-10 {
        let dist = dist2.sqrt();
        let normal = delta / dist;
        shell.position += normal * (SHELL_RADIUS - dist);
        return Some(normal);
    }
    let candidates = [
        (max.x - center.x, Vec3::X),
        (center.x - min.x, -Vec3::X),
        (max.y - center.y, Vec3::Y),
        (center.y - min.y, -Vec3::Y),
        (max.z - center.z, Vec3::Z),
        (center.z - min.z, -Vec3::Z),
    ];
    let (depth, normal) = candidates
        .into_iter()
        .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal))?;
    if !depth.is_finite() {
        return None;
    }
    shell.position += normal * (depth + SHELL_RADIUS);
    Some(normal)
}

fn bounce(shell: &mut Shell, normal: Vec3) {
    let into = shell.velocity.dot(normal);
    if into >= 0. {
        return;
    }
    shell.velocity -= normal * into * (1. + RESTITUTION);
    let tangent = shell.velocity - normal * shell.velocity.dot(normal);
    let speed = tangent.length();
    if speed > 1e-5 {
        let drop = (FRICTION * into.abs()).min(speed);
        shell.velocity -= tangent / speed * drop;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::Settings;
    use crate::sim::{Aabb, Input, Simulation, FIXED_DT};
    use macroquad::math::vec3;

    fn ground() -> Block {
        Block {
            bounds: Aabb::from_center(vec3(0., -0.25, 0.), vec3(40., 0.5, 40.)),
            kind: 0,
        }
    }

    fn fired_shot() -> Shot {
        let mut sim = Simulation::new();
        let input = Input {
            fire: true,
            ..Default::default()
        };
        sim.update(input, &Settings::default(), FIXED_DT);
        sim.events[0]
    }

    fn shot_fx() -> (MuzzleFx, Shot) {
        let shot = fired_shot();
        let mut fx = MuzzleFx::default();
        fx.spawn_shot(&shot);
        (fx, shot)
    }

    fn axial_reach(flash: &ProceduralFlash, muzzle: Vec3, barrel: Vec3) -> f32 {
        let barrel = unit_or(barrel, -Vec3::Z);
        flash
            .positions
            .iter()
            .map(|p| (*p - muzzle).dot(barrel))
            .fold(0., f32::max)
    }

    #[test]
    fn one_shot_spawns_flash_smoke_light_and_one_shell() {
        let (fx, shot) = shot_fx();
        assert_eq!(fx.shell_count(), 1);
        assert_eq!(fx.smoke_count(), 7);
        assert!(fx.flash_intensity() > 0.9);
        let lights = fx.lights();
        assert_eq!(lights.len(), 1);
        assert!(lights[0].position.distance(shot.muzzle) < 1e-4);
        assert!(lights[0].intensity > 0.9);
        assert!(lights[0].range > 1.);
        let shell = &fx.shells[0];
        let port = shot.muzzle - shot.barrel_forward * PORT_BACK
            + shot.barrel_right * PORT_RIGHT
            + shot.barrel_up * PORT_UP;
        assert!(shell.position.distance(port) < 1e-4);
        assert!(shell.position.distance(shot.muzzle) > 0.3);
        let flash = &fx.procedural_flashes(shot.muzzle, shot.barrel_forward)[0];
        assert!(flash.positions.len() > 40);
        assert_eq!(flash.indices.len() % 3, 0);
        assert!(flash
            .indices
            .iter()
            .all(|i| (*i as usize) < flash.positions.len()));
        assert_eq!(flash.positions.len(), flash.colors.len());
    }

    #[test]
    fn flash_is_procedural_and_flickers_without_a_texture() {
        let (fx, shot) = shot_fx();
        let birth = &fx.procedural_flashes(shot.muzzle, shot.barrel_forward)[0];
        let mut later = fx;
        later.update(0.012, &[], &[]);
        let flickered = &later.procedural_flashes(shot.muzzle, shot.barrel_forward)[0];
        assert_ne!(birth.positions, flickered.positions);
        let birth_alpha: f32 =
            birth.colors.iter().map(|c| c[3]).sum::<f32>() / birth.colors.len() as f32;
        let later_alpha: f32 =
            flickered.colors.iter().map(|c| c[3]).sum::<f32>() / flickered.colors.len() as f32;
        assert!(
            (birth_alpha - later_alpha).abs() > 0.01 || birth.positions != flickered.positions,
            "flash should change shape or brightness as it flickers"
        );
        let muzzle = shot.muzzle;
        let (core, tip) = birth.positions.iter().zip(&birth.colors).fold(
            ((0., 0.), (0., 1.)),
            |((near_d, near_b), (far_d, far_b)), (p, c)| {
                let d = (*p - muzzle).length();
                let blue = c[2];
                let near = if d < near_d || near_d == 0. {
                    (d, blue)
                } else {
                    (near_d, near_b)
                };
                let far = if d > far_d { (d, blue) } else { (far_d, far_b) };
                (near, far)
            },
        );
        assert!(
            core.1 > tip.1,
            "core should burn whiter than the petal tips"
        );
    }

    #[test]
    fn caliber_scales_size_intensity_duration_and_light() {
        let shot = fired_shot();
        let small_profile = FlashProfile::from_millimeters(5.56);
        let large_profile = FlashProfile::from_millimeters(12.7);
        assert!(large_profile.size > small_profile.size * 1.5);
        assert!(large_profile.intensity > small_profile.intensity * 1.5);
        assert!(large_profile.duration > small_profile.duration);
        assert!(large_profile.light > large_profile.size);
        assert!((small_profile.size - 1.).abs() < 1e-4);
        assert!((small_profile.intensity - 1.).abs() < 1e-4);
        assert!((small_profile.light - 1.).abs() < 1e-4);

        let mut small = MuzzleFx::default();
        small.set_caliber_mm(5.56);
        small.spawn_shot(&shot);
        let mut large = MuzzleFx::default();
        large.set_caliber_mm(12.7);
        large.spawn_shot(&shot);
        let small_reach = axial_reach(
            &small.procedural_flashes(shot.muzzle, shot.barrel_forward)[0],
            shot.muzzle,
            shot.barrel_forward,
        );
        let large_reach = axial_reach(
            &large.procedural_flashes(shot.muzzle, shot.barrel_forward)[0],
            shot.muzzle,
            shot.barrel_forward,
        );
        assert!(
            large_reach > small_reach * 1.4,
            "{large_reach} vs {small_reach}"
        );
        assert!(large.lights()[0].intensity > small.lights()[0].intensity);
        assert!(large.lights()[0].range > small.lights()[0].range);
        assert!(large.flash_intensity() > small.flash_intensity());

        small.update(small_profile.duration, &[], &[]);
        large.update(small_profile.duration, &[], &[]);
        assert_eq!(small.flash_intensity(), 0.);
        assert!(large.flash_intensity() > 0.);
        assert_eq!(small.shell_count(), 1);
        assert_eq!(large.shell_count(), 1);
    }

    #[test]
    fn shell_despawns_at_five_seconds_and_not_before() {
        let (mut fx, _) = shot_fx();
        fx.update(4.99, &[], &[]);
        assert_eq!(fx.shell_count(), 1);
        assert!(fx.flash_intensity() == 0.);
        assert_eq!(fx.smoke_count(), 0);
        fx.update(0.02, &[], &[]);
        assert_eq!(fx.shell_count(), 0);
        let (mut fx, _) = shot_fx();
        fx.update(SHELL_LIFE, &[], &[]);
        assert_eq!(fx.shell_count(), 0);
    }

    #[test]
    fn shell_lands_on_the_ground_and_does_not_tunnel() {
        let (mut fx, _) = shot_fx();
        let floor = [ground()];
        let mut lowest = f32::MAX;
        for _ in 0..(2. * 120.) as u32 {
            fx.update(FIXED_DT, &floor, &[]);
            lowest = lowest.min(fx.shells[0].position.y);
        }
        let shell = &fx.shells[0];
        assert!(
            lowest >= -0.001,
            "shell tunneled through the floor, lowest y {lowest}"
        );
        assert!(
            (shell.position.y - SHELL_RADIUS).abs() < 0.02,
            "shell should rest on the ground, y {}",
            shell.position.y
        );
        assert!(shell.asleep, "shell should settle after landing");
        assert!(shell.velocity.length() < 1e-4);
    }

    #[test]
    fn shell_bounces_off_a_wall() {
        let (mut fx, _) = shot_fx();
        let shell = &mut fx.shells[0];
        shell.position = vec3(-0.2, 0.4, 0.);
        shell.velocity = vec3(3.5, 0., 0.);
        shell.asleep = false;
        let wall = [Block {
            bounds: Aabb::from_center(vec3(0.4, 0.4, 0.), vec3(0.2, 1.2, 1.2)),
            kind: 1,
        }];
        for _ in 0..40 {
            fx.update(FIXED_DT, &wall, &[]);
        }
        assert!(
            fx.shells[0].velocity.x < 0.,
            "expected the casing to rebound, velocity {:?}",
            fx.shells[0].velocity
        );
        assert!(fx.shells[0].position.x < 0.4);
    }

    #[test]
    fn shell_rests_on_a_ramp_instead_of_falling_through() {
        let (mut fx, _) = shot_fx();
        let shell = &mut fx.shells[0];
        shell.position = vec3(0., 0.55, -1.);
        shell.velocity = Vec3::ZERO;
        shell.asleep = false;
        let ramp = [Ramp {
            x: 0.,
            z: 0.,
            width: 3.,
            length: 4.,
            height: 2.,
        }];
        for _ in 0..(2. * 120.) as u32 {
            fx.update(FIXED_DT, &[], &ramp);
        }
        let shell = &fx.shells[0];
        let surface = ramp[0].surface(shell.position.x, shell.position.z).unwrap();
        assert!(
            shell.position.y >= surface,
            "fell through ramp: y {} surface {surface}",
            shell.position.y
        );
        assert!((shell.position.y - surface) < 0.08);
    }
}
