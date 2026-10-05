//! Layered first-person weapon offsets. Presentation only: nothing here feeds
//! gameplay, aim, or the camera.
//!
//! Layer order (each bounded, then summed into one rigid viewmodel transform so
//! hand/weapon contacts are preserved):
//! 1. Look sway: this module, driven by view angular velocity.
//! 2. Locomotion bob/sprint: owned by `locomotion_presentation` and the authored
//!    walk layers; unchanged here.
//! 3. Recoil: owned by the simulation (`recoil`, `shot_kick`) and weapon animation.
//! 4. Action: this module, from `Simulation::action_pose`, obstruction and mount.
use crate::action::{ActionPose, ActionSlot};
use crate::sim::{Obstruction, Player};
use macroquad::math::{vec3, EulerRot, Mat4, Quat, Vec2, Vec3};

/// Tuning for the look-sway spring. Angles in degrees, distances in meters.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SwayTuning {
    /// Degrees of weapon lag per radian/second of view rotation.
    pub lag_per_rad_s: f32,
    /// Maximum lag rotation on each axis (degrees).
    pub max_angle: f32,
    /// Lateral/vertical translation per degree of lag (meters).
    pub shift_per_degree: f32,
    /// Roll per degree of yaw lag.
    pub roll_per_yaw: f32,
    /// Spring angular frequency (rad/s); critically damped.
    pub stiffness: f32,
}
impl Default for SwayTuning {
    fn default() -> Self {
        Self {
            lag_per_rad_s: 0.9,
            max_angle: 4.0,
            shift_per_degree: 0.0025,
            roll_per_yaw: 0.6,
            stiffness: 14.,
        }
    }
}

/// A bounded camera-space offset: translation in meters, rotation as
/// (pitch, yaw, roll) radians.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct LayerOffset {
    pub translation: Vec3,
    pub rotation: Vec3,
}
impl LayerOffset {
    pub fn clamped(self, max_translation: f32, max_rotation: f32) -> Self {
        Self {
            translation: self
                .translation
                .clamp(Vec3::splat(-max_translation), Vec3::splat(max_translation)),
            rotation: self
                .rotation
                .clamp(Vec3::splat(-max_rotation), Vec3::splat(max_rotation)),
        }
    }
}

/// Per-layer bounds. A layer can never exceed these regardless of input.
pub const LOOK_MAX_TRANSLATION: f32 = 0.02;
pub const ACTION_MAX_TRANSLATION: f32 = 0.45;
pub const ACTION_MAX_ROTATION: f32 = 0.9;

/// Critically damped look-lag spring, integrated in closed form so any frame
/// partition of the same piecewise-constant input gives the same trajectory.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct LookSway {
    /// (yaw, pitch) lag in degrees.
    angle: Vec2,
    velocity: Vec2,
}
impl LookSway {
    pub fn reset(&mut self) {
        *self = Self::default();
    }
    /// `view_delta` is the actual view rotation applied this frame (yaw, pitch
    /// radians) after sensitivity, so sensitivity never changes the response to
    /// the same on-screen motion. `dt` is the render delta in seconds.
    pub fn update(&mut self, view_delta: Vec2, dt: f32, t: &SwayTuning) {
        if dt.is_nan() || dt <= 0. || !view_delta.is_finite() {
            return;
        }
        let rate = view_delta / dt;
        // The weapon lags opposite the turn.
        let target =
            (-rate * t.lag_per_rad_s).clamp(Vec2::splat(-t.max_angle), Vec2::splat(t.max_angle));
        let w = t.stiffness;
        let x0 = self.angle - target;
        let v0 = self.velocity;
        let decay = (-w * dt).exp();
        let c = v0 + x0 * w;
        let x = (x0 + c * dt) * decay;
        self.velocity = (c - (x0 + c * dt) * w) * decay;
        self.angle = (target + x).clamp(Vec2::splat(-t.max_angle), Vec2::splat(t.max_angle));
        if self.angle.length() < 1e-5 && self.velocity.length() < 1e-4 {
            self.angle = Vec2::ZERO;
            self.velocity = Vec2::ZERO;
        }
    }
    pub fn angle_degrees(&self) -> Vec2 {
        self.angle
    }
    pub fn offset(&self, t: &SwayTuning) -> LayerOffset {
        let yaw = self.angle.x;
        let pitch = self.angle.y;
        LayerOffset {
            translation: vec3(yaw * t.shift_per_degree, pitch * t.shift_per_degree, 0.),
            rotation: vec3(pitch, yaw, yaw * t.roll_per_yaw) * std::f32::consts::PI / 180.,
        }
        .clamped(LOOK_MAX_TRANSLATION, t.max_angle.to_radians() * 1.5)
    }
}

/// Action layer from gameplay state. Placeholder poses until authored clips exist.
pub fn action_offset(player: &Player, pose: &ActionPose, max_retract: f32) -> LayerOffset {
    let mut out = obstruction_offset(&player.obstruction, max_retract);
    let w = pose.weight;
    match pose.slot {
        // Rifle lowered out of view while both hands hold a ledge.
        Some(
            ActionSlot::LedgeCatch
            | ActionSlot::LedgeHold
            | ActionSlot::LedgeLost
            | ActionSlot::PullUp
            | ActionSlot::HangDrop
            | ActionSlot::PistolDraw
            | ActionSlot::PistolReady
            | ActionSlot::PistolAim
            | ActionSlot::PistolFire
            | ActionSlot::PistolStow,
        ) => {
            out.translation += vec3(0., -0.4, 0.1) * w;
            out.rotation.x -= 0.6 * w;
        }
        Some(
            ActionSlot::SlideEnter
            | ActionSlot::SlideLoop
            | ActionSlot::SlideRecover
            | ActionSlot::SlideInterrupt,
        ) => {
            out.rotation.z += 0.18 * w;
            out.translation.x -= 0.02 * w;
        }
        Some(
            ActionSlot::DiveLaunch
            | ActionSlot::DiveAir
            | ActionSlot::DiveImpact
            | ActionSlot::DiveRecover,
        ) => {
            out.rotation.z += 0.25 * w;
            out.translation.y -= 0.04 * w;
        }
        Some(
            ActionSlot::TacSprintEnter | ActionSlot::TacSprintLoop | ActionSlot::TacSprintExit,
        ) => {
            // Tactical sprint raises the muzzle.
            out.rotation.x += 0.35 * w;
            out.translation.y -= 0.03 * w;
        }
        Some(ActionSlot::MountEnter | ActionSlot::MountHold | ActionSlot::MountExit) => {
            out.translation.y -= 0.01 * w;
        }
        None => {}
    }
    out.clamped(ACTION_MAX_TRANSLATION, ACTION_MAX_ROTATION)
}

/// Retract along the barrel and lower the muzzle. `Obstruction::direction`
/// (world surface normal) is exposed separately for authored blends.
pub fn obstruction_offset(o: &Obstruction, max_retract: f32) -> LayerOffset {
    let a = o.amount;
    LayerOffset {
        translation: vec3(0., -0.06 * a, max_retract * a),
        rotation: vec3(-0.5 * a, 0., 0.),
    }
}

/// Compose bounded layers into one rigid camera-space root transform.
pub fn compose(base_translation: Vec3, layers: &[LayerOffset]) -> Mat4 {
    let mut translation = base_translation;
    let mut rotation = Vec3::ZERO;
    for layer in layers {
        translation += layer.translation;
        rotation += layer.rotation;
    }
    Mat4::from_rotation_translation(
        Quat::from_euler(EulerRot::YXZ, rotation.y, rotation.x, rotation.z),
        translation,
    )
}

/// Cant: rotate the weapon about its own bore line. `weapon` maps weapon-mesh
/// space (barrel along -Z) to camera space; `mesh_muzzle` is a point on the
/// bore. Positive `angle` rolls the top of the weapon to the viewer's left.
/// The result is applied to the weapon and, through the shared root, to the
/// whole arm chain in weapon space, so the hands stay on the grips.
pub fn cant_about_bore(weapon: Mat4, mesh_muzzle: Vec3, angle: f32) -> Mat4 {
    let bore = weapon.transform_vector3(-Vec3::Z);
    if angle == 0. || bore.length_squared() < 1e-12 {
        return Mat4::IDENTITY;
    }
    let pivot = weapon.transform_point3(mesh_muzzle);
    Mat4::from_translation(pivot)
        * Mat4::from_quat(Quat::from_axis_angle(-bore.normalize(), angle))
        * Mat4::from_translation(-pivot)
}

#[cfg(test)]
mod tests {
    #[test]
    fn cant_rolls_about_the_bore_and_keeps_it_fixed() {
        // Weapon at hip, barrel pointing forward (-Z) in camera space.
        let weapon = Mat4::from_translation(vec3(0.15, -0.2, -0.3));
        let muzzle = vec3(0., 0.01, -0.8);
        let c = cant_about_bore(weapon, muzzle, 20_f32.to_radians());
        let tip = weapon.transform_point3(muzzle);
        let rear = weapon.transform_point3(vec3(0., 0.01, 0.2));
        assert!((c.transform_point3(tip) - tip).length() < 1e-5);
        assert!(
            (c.transform_point3(rear) - rear).length() < 1e-5,
            "bore line fixed"
        );
        let sight = weapon.transform_point3(vec3(0., 0.08, -0.2));
        assert!(c.transform_point3(sight).x < sight.x, "top rolls left");
        assert_eq!(cant_about_bore(weapon, muzzle, 0.), Mat4::IDENTITY);
    }

    use super::*;
    use macroquad::math::vec2;

    fn trace(fps: u32, rate: Vec2, seconds: f32) -> Vec<(f32, Vec2)> {
        let t = SwayTuning::default();
        let mut sway = LookSway::default();
        let dt = 1. / fps as f32;
        let mut out = Vec::new();
        let frames = (seconds * fps as f32).round() as u32;
        for i in 0..frames * 4 {
            let input = if i < frames { rate * dt } else { Vec2::ZERO };
            sway.update(input, dt, &t);
            out.push(((i + 1) as f32 * dt, sway.angle_degrees()));
        }
        out
    }
    fn at(trace: &[(f32, Vec2)], time: f32) -> Vec2 {
        trace
            .iter()
            .find(|(t, _)| (*t - time).abs() < 1e-4)
            .expect("sample")
            .1
    }

    #[test]
    fn same_motion_matches_across_frame_rates() {
        let rate = vec2(2.0, -0.7);
        let traces: Vec<_> = [30, 60, 120, 240].map(|fps| trace(fps, rate, 0.5)).into();
        for time in [0.1, 0.2, 0.5, 0.8, 1.0] {
            let reference = at(&traces[3], time);
            for t in &traces {
                assert!((at(t, time) - reference).length() < 1e-3, "t={time}");
            }
        }
    }

    #[test]
    fn same_view_motion_is_sensitivity_independent() {
        // Two sensitivities producing the same view rotation give one response.
        let t = SwayTuning::default();
        let (mut low, mut high) = (LookSway::default(), LookSway::default());
        for _ in 0..30 {
            let counts_low = 40.;
            let counts_high = 10.;
            low.update(vec2(counts_low * 0.0005, 0.), 1. / 60., &t);
            high.update(vec2(counts_high * 0.002, 0.), 1. / 60., &t);
        }
        assert_eq!(low, high);
    }

    #[test]
    fn settles_without_drift_or_snap_and_stays_bounded() {
        let t = SwayTuning::default();
        let tr = trace(60, vec2(50., 50.), 0.5);
        for (_, a) in &tr {
            assert!(a.x.abs() <= t.max_angle && a.y.abs() <= t.max_angle);
        }
        let release = tr.len() / 4;
        // No snap: one frame after release changes by less than the max step.
        let step = (tr[release].1 - tr[release - 1].1).length();
        assert!(step < t.max_angle * 0.5, "step {step}");
        assert_eq!(tr.last().unwrap().1, Vec2::ZERO);
        let offset = LookSway::default().offset(&t);
        assert_eq!(offset, LayerOffset::default());
    }

    #[test]
    fn layers_are_bounded_and_compose_rigidly() {
        let big = LayerOffset {
            translation: Vec3::splat(5.),
            rotation: Vec3::splat(5.),
        }
        .clamped(ACTION_MAX_TRANSLATION, ACTION_MAX_ROTATION);
        assert_eq!(big.translation, Vec3::splat(ACTION_MAX_TRANSLATION));
        let m = compose(Vec3::ZERO, &[big]);
        // Rigid: distances between viewmodel points are preserved (grips stay attached).
        let a = m.transform_point3(vec3(0.1, -0.1, -0.3));
        let b = m.transform_point3(vec3(-0.05, -0.12, -0.6));
        let d = (vec3(0.1, -0.1, -0.3) - vec3(-0.05, -0.12, -0.6)).length();
        assert!(((a - b).length() - d).abs() < 1e-5);
    }
}
