//! Original, fixed-step ammunition resupply interaction.
//!
//! The renderer is only a consumer: aiming, visibility, time, and ammunition
//! changes live here and can be exercised without a window or graphics context.
use crate::sim::{Aabb, Player, Simulation, MAGAZINE};
use macroquad::math::{vec2, vec3, Mat4, Vec2, Vec3};

pub const DEFAULT_HOLD_SECONDS: f32 = 1.5;
pub const DEFAULT_SUPPLY_RANGE: f32 = 2.25;
pub const DEFAULT_RESERVE_CAPACITY: u32 = 90;
/// A stalled render frame must never count as an uninterrupted hold. Normal
/// callers pass FIXED_DT; a longer gap cancels rather than awarding free time.
pub const MAX_HOLD_STEP_SECONDS: f32 = 0.1;
pub const SUPPLY_FLOOR_CENTER: Vec3 = vec3(0., 0., 13.45);
pub const SUPPLY_HALF_EXTENTS: Vec3 = vec3(0.4, 0.25, 0.25);
const LOS_EPSILON: f32 = 0.001;

#[derive(Debug, Clone, Copy)]
pub struct SupplyConfig {
    pub hold_seconds: f32,
    pub range: f32,
    pub reserve_capacity: u32,
}
impl Default for SupplyConfig {
    fn default() -> Self {
        Self {
            hold_seconds: DEFAULT_HOLD_SECONDS,
            range: DEFAULT_SUPPLY_RANGE,
            reserve_capacity: DEFAULT_RESERVE_CAPACITY,
        }
    }
}
impl SupplyConfig {
    /// Invalid tuning values use safe defaults; finite positive durations are
    /// otherwise preserved, including deliberately short interaction timings.
    pub fn sanitized(self) -> Self {
        Self {
            hold_seconds: if self.hold_seconds.is_finite() && self.hold_seconds > 0. {
                self.hold_seconds
            } else {
                DEFAULT_HOLD_SECONDS
            },
            range: if self.range.is_finite() && self.range > 0. {
                self.range
            } else {
                DEFAULT_SUPPLY_RANGE
            },
            reserve_capacity: self.reserve_capacity,
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct SupplyView {
    pub eye: Vec3,
    pub direction: Vec3,
    pub view_projection: Mat4,
    pub viewport: Vec2,
}
impl SupplyView {
    /// Same right-handed, OpenGL-depth perspective used by the range camera.
    /// `vertical_fov_radians` must already account for horizontal FOV/aspect.
    pub fn perspective(
        eye: Vec3,
        direction: Vec3,
        vertical_fov_radians: f32,
        viewport: Vec2,
    ) -> Option<Self> {
        if !eye.is_finite()
            || !direction.is_finite()
            || direction.length_squared() < 1e-10
            || !valid_viewport(viewport)
            || !vertical_fov_radians.is_finite()
            || !(0.001..std::f32::consts::PI - 0.001).contains(&vertical_fov_radians)
        {
            return None;
        }
        let direction = direction.normalize();
        if direction.cross(Vec3::Y).length_squared() < 1e-8 {
            return None;
        }
        let view_projection =
            Mat4::perspective_rh_gl(vertical_fov_radians, viewport.x / viewport.y, 0.035, 200.)
                * Mat4::look_at_rh(eye, eye + direction, Vec3::Y);
        Some(Self {
            eye,
            direction,
            view_projection,
            viewport,
        })
    }
}

fn valid_viewport(viewport: Vec2) -> bool {
    viewport.is_finite() && viewport.x > 0. && viewport.y > 0.
}

/// Projects a world anchor to top-left-origin screen pixels. A point behind
/// the camera, outside any clip plane, or in an invalid viewport has no hint.
pub fn project_world(point: Vec3, view_projection: Mat4, viewport: Vec2) -> Option<Vec2> {
    if !point.is_finite() || !view_projection.is_finite() || !valid_viewport(viewport) {
        return None;
    }
    let clip = view_projection * point.extend(1.);
    if !clip.is_finite() || clip.w <= 1e-6 {
        return None;
    }
    let ndc = clip.truncate() / clip.w;
    if ndc.x.abs() > 1. || ndc.y.abs() > 1. || ndc.z.abs() > 1. {
        return None;
    }
    Some(vec2(
        (ndc.x * 0.5 + 0.5) * viewport.x,
        (0.5 - ndc.y * 0.5) * viewport.y,
    ))
}

#[derive(Debug, Clone, Copy)]
pub struct SupplyFocus {
    pub screen_anchor: Vec2,
    pub world_anchor: Vec3,
    /// Distance along the normalized crosshair ray to the crate's surface.
    pub distance: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SupplyEvent {
    None,
    Refilled,
}

#[derive(Debug, Clone)]
pub struct AmmoSupply {
    /// Footprint center, not the center of the 3D bounding box.
    pub floor_center: Vec3,
    /// Match these to the authored crate so aiming and collision agree.
    pub half_extents: Vec3,
    pub config: SupplyConfig,
    elapsed: f64,
    completed_this_hold: bool,
}
impl Default for AmmoSupply {
    fn default() -> Self {
        Self::new(
            SUPPLY_FLOOR_CENTER,
            SUPPLY_HALF_EXTENTS,
            SupplyConfig::default(),
        )
    }
}
impl AmmoSupply {
    pub fn new(floor_center: Vec3, half_extents: Vec3, config: SupplyConfig) -> Self {
        Self {
            floor_center,
            half_extents,
            config: config.sanitized(),
            elapsed: 0.,
            completed_this_hold: false,
        }
    }

    pub fn bounds(&self) -> Aabb {
        Aabb::from_center(
            self.floor_center + Vec3::Y * self.half_extents.y,
            self.half_extents * 2.,
        )
    }

    /// Fixed to the crate, slightly above its lid, rather than to screen center.
    pub fn hint_anchor(&self) -> Vec3 {
        self.floor_center + Vec3::Y * (self.half_extents.y * 2. + 0.18)
    }

    pub fn ammo_full(&self, player: &Player) -> bool {
        player.ammo >= MAGAZINE && player.reserve >= self.config.reserve_capacity
    }

    /// Strict AND gate: active + nearby + crosshair actually intersects the
    /// crate + no nearer solid geometry + the world anchor is in the viewport.
    /// Includes ramps and live targets; the wall behind the crate cannot block
    /// it. A matching crate collider may be included in `sim.blocks` safely.
    pub fn focus(&self, sim: &Simulation, view: SupplyView, active: bool) -> Option<SupplyFocus> {
        if !active
            || !self.floor_center.is_finite()
            || !self.half_extents.is_finite()
            || self.half_extents.min_element() <= 0.
            || !view.eye.is_finite()
            || !view.direction.is_finite()
            || view.direction.length_squared() < 1e-10
        {
            return None;
        }
        let direction = view.direction.normalize();
        let range = self.config.sanitized().range;
        let distance = self.bounds().ray(view.eye, direction, range)?;
        // A camera inside the crate should never gain an interaction through it.
        if distance <= LOS_EPSILON || distance > range {
            return None;
        }
        let blocked = |hit: Option<f32>| hit.is_some_and(|t| t < distance - LOS_EPSILON);
        if sim
            .blocks
            .iter()
            .any(|b| blocked(b.bounds.ray(view.eye, direction, distance)))
            || sim
                .ramps
                .iter()
                .any(|r| blocked(r.ray(view.eye, direction, distance)))
            || sim.targets.iter().any(|target| {
                target.health > 0. && blocked(target.bounds.ray(view.eye, direction, distance))
            })
        {
            return None;
        }
        let world_anchor = self.hint_anchor();
        let screen_anchor = project_world(world_anchor, view.view_projection, view.viewport)?;
        // Also test the hint anchor itself. An overhanging obstacle must not
        // let a floating UI label appear through a wall above a visible crate.
        let delta = world_anchor - view.eye;
        let anchor_distance = delta.length();
        if anchor_distance <= LOS_EPSILON {
            return None;
        }
        let anchor_direction = delta / anchor_distance;
        let anchor_blocked =
            |hit: Option<f32>| hit.is_some_and(|t| t < anchor_distance - LOS_EPSILON);
        if sim.blocks.iter().any(|b| {
            // Its own crate collider is not an occluder of its own label.
            let bounds = self.bounds();
            let own_collider = (b.bounds.min - bounds.min).length_squared() < 1e-8
                && (b.bounds.max - bounds.max).length_squared() < 1e-8;
            !own_collider
                && anchor_blocked(b.bounds.ray(view.eye, anchor_direction, anchor_distance))
        }) || sim
            .ramps
            .iter()
            .any(|r| anchor_blocked(r.ray(view.eye, anchor_direction, anchor_distance)))
            || sim.targets.iter().any(|t| {
                t.health > 0.
                    && anchor_blocked(t.bounds.ray(view.eye, anchor_direction, anchor_distance))
            })
        {
            return None;
        }
        Some(SupplyFocus {
            screen_anchor,
            world_anchor,
            distance,
        })
    }

    pub fn progress(&self) -> f32 {
        (self.elapsed / self.config.sanitized().hold_seconds as f64).clamp(0., 1.) as f32
    }

    /// Call immediately for release, look-away, lost range, pause, or reset,
    /// even on render frames that contain no fixed simulation step.
    pub fn cancel(&mut self) {
        self.elapsed = 0.;
        self.completed_this_hold = false;
    }

    pub fn reset(&mut self) {
        self.cancel();
    }

    /// Advance only by simulation time. `focus` must be recomputed after the
    /// current fixed movement step; a stale render-time focus is not sufficient.
    /// No body, movement, health, or statistics fields are changed.
    pub fn tick(
        &mut self,
        player: &mut Player,
        focus: Option<SupplyFocus>,
        held_f: bool,
        active: bool,
        dt: f32,
    ) -> SupplyEvent {
        if !active
            || !held_f
            || focus.is_none()
            || !dt.is_finite()
            || dt < 0.
            || dt > MAX_HOLD_STEP_SECONDS
        {
            self.cancel();
            return SupplyEvent::None;
        }
        if self.ammo_full(player) || self.completed_this_hold {
            self.elapsed = 0.;
            return SupplyEvent::None;
        }
        if dt == 0. {
            return SupplyEvent::None;
        }
        self.elapsed += dt as f64;
        let duration = self.config.sanitized().hold_seconds as f64;
        let rounding_tolerance = 1e-7_f64.min(duration * 1e-6);
        if self.elapsed + rounding_tolerance < duration {
            return SupplyEvent::None;
        }
        player.ammo = MAGAZINE;
        player.reserve = self.config.reserve_capacity;
        // Finish a pending reload so it cannot later remove the refill's
        // reserve rounds or keep a now-full weapon unnecessarily unavailable.
        player.reload_left = 0.;
        player.reload_total = 0.;
        player.reload_credit_at = 0.;
        player.reload_ready_at = 0.;
        player.reload_credited = false;
        player.reload_empty = false;
        self.elapsed = 0.;
        self.completed_this_hold = true;
        SupplyEvent::Refilled
    }
}
