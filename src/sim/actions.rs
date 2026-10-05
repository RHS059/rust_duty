//! Tactical sprint, slide, dive, ledge hang/pull-up/drop, hanging sidearm,
//! weapon mount, wall obstruction and death. Gameplay owns every transition;
//! `Simulation::action_pose` is the read-only animation interface.
use super::*;
use crate::action::{
    smoothstep, ActionPhase, ActionPose, ContactTargets, HandOwner, Rejection, WeaponPermissions,
};

#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub enum Action {
    #[default]
    None,
    Slide(SlideState),
    Dive(DiveState),
    Hang(HangState),
}
impl Action {
    /// Collision height while the action owns the capsule.
    pub fn capsule_height(&self) -> Option<f32> {
        match self {
            Action::Slide(s) => Some(s.height),
            Action::Dive(d) if d.phase != DivePhase::Impact => Some(d.height),
            _ => None,
        }
    }
    pub fn pistol_ready(&self) -> bool {
        matches!(self, Action::Hang(h) if h.pistol == PistolPhase::Ready)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SlidePhase {
    Entry,
    Active,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SlideState {
    pub phase: SlidePhase,
    /// Seconds since the slide started.
    pub elapsed: f32,
    pub height: f32,
    eye_from: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DivePhase {
    Launch,
    Air,
    Impact,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DiveState {
    pub phase: DivePhase,
    /// Seconds since the current phase started.
    pub elapsed: f32,
    pub height: f32,
    eye_from: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HangPhase {
    Catch,
    Hold,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PistolPhase {
    Holstered,
    Drawing,
    Ready,
    Stowing,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HangState {
    pub phase: HangPhase,
    pub elapsed: f32,
    /// The static block being held. Any change to it releases the hang.
    pub support: Aabb,
    /// Outward wall normal (horizontal).
    pub normal: Vec3,
    /// Fixed feet position while hanging.
    pub position: Vec3,
    /// World hand anchors on the ledge top: [left, right].
    pub hands: [Vec3; 2],
    /// Center of the held edge on the ledge top.
    pub lip: Vec3,
    pub pistol: PistolPhase,
    pub pistol_elapsed: f32,
    pub yaw_center: f32,
    eye_from: f32,
}
impl HangState {
    /// Hand anchors relative to the lip center: (along wall, height, inset).
    pub fn ledge_relative_hands(&self) -> [Vec3; 2] {
        let tangent = vec3(-self.normal.z, 0., self.normal.x);
        self.hands.map(|h| {
            let d = h - self.lip;
            vec3(d.dot(tangent), d.y, d.dot(-self.normal))
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MountState {
    /// World point where the weapon rests on cover.
    pub support: Vec3,
    /// Surface normal at the support (up for flat tops).
    pub normal: Vec3,
    pub yaw_center: f32,
    pub position: Vec3,
    pub crouched: bool,
    pub via_ads: bool,
    pub elapsed: f32,
    /// 0..1 blend weight for the mount pose.
    pub weight: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TacSprint {
    pub elapsed: f32,
}

/// Wall-obstruction state for the active weapon.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Obstruction {
    /// Smoothed 0..1 retraction (1 = fully lowered).
    pub amount: f32,
    /// Unsmoothed 0..1 penetration this tick.
    pub raw: f32,
    /// World normal of the blocking surface (zero when clear).
    pub direction: Vec3,
    /// Clear distance along the barrel line from the weapon's rear (m).
    pub clear_length: f32,
    pub ads_blocked: bool,
    pub fire_blocked: bool,
    below_for: f32,
}
impl Default for Obstruction {
    fn default() -> Self {
        Self {
            amount: 0.,
            raw: 0.,
            direction: Vec3::ZERO,
            clear_length: 10.,
            ads_blocked: false,
            fire_blocked: false,
            below_for: 0.,
        }
    }
}

struct MountCandidate {
    support: Vec3,
    normal: Vec3,
    distance: f32,
}

fn horizontal(yaw: f32) -> Vec3 {
    vec3(yaw.cos(), 0., yaw.sin())
}
fn wrap_angle(a: f32) -> f32 {
    let tau = std::f32::consts::TAU;
    (a + std::f32::consts::PI).rem_euclid(tau) - std::f32::consts::PI
}
/// Rotate a horizontal vector toward `target` by at most `max_angle` radians.
fn steer(v: Vec2, target: Vec2, max_angle: f32) -> Vec2 {
    let speed = v.length();
    if speed < 1e-6 || target.length_squared() < 1e-6 {
        return v;
    }
    let from = v.y.atan2(v.x);
    let to = target.y.atan2(target.x);
    let angle = from + wrap_angle(to - from).clamp(-max_angle, max_angle);
    vec2(angle.cos(), angle.sin()) * speed
}
fn stance_height(stance: i32) -> f32 {
    match stance {
        2 => PRONE_HEIGHT,
        1 => CROUCH_HEIGHT,
        _ => STANDING_HEIGHT,
    }
}
/// Face normal of an AABB at a surface point.
fn face_normal(b: Aabb, q: Vec3) -> Vec3 {
    let mut best = (f32::MAX, Vec3::ZERO);
    for axis in 0..3 {
        let mut n = Vec3::ZERO;
        let low = (q[axis] - b.min[axis]).abs();
        let high = (q[axis] - b.max[axis]).abs();
        if low < best.0 {
            n[axis] = -1.;
            best = (low, n);
        }
        let mut n = Vec3::ZERO;
        if high < best.0 {
            n[axis] = 1.;
            best = (high, n);
        }
    }
    best.1
}

impl Simulation {
    /// Apply damage to the player. Reaching zero health kills immediately.
    pub fn damage_player(&mut self, amount: f32) {
        if self.player.dead() || amount <= 0. || !amount.is_finite() {
            return;
        }
        self.player.health -= amount;
        if self.player.health <= 0. {
            self.kill();
        }
    }
    /// Death wins over every action: traversal, mount, reload and sidearm are
    /// cleared without moving the player. Idempotent.
    pub fn kill(&mut self) {
        if self.player.dead() {
            return;
        }
        if matches!(self.player.action, Action::Hang(h) if h.pistol != PistolPhase::Holstered) {
            self.emit(ActionEventKind::PistolInterrupted);
        }
        let p = &mut self.player;
        p.health = 0.;
        p.dead_since = Some(self.time);
        p.mantle = None;
        p.action = Action::None;
        p.mount = None;
        p.tac_sprint = None;
        p.velocity = Vec3::ZERO;
        p.sprinting = false;
        p.ads = 0.;
        p.ads_requested = false;
        p.firing_sequence = false;
        p.reload_left = 0.;
        p.reload_credit_at = 0.;
        p.reload_ready_at = 0.;
        p.reload_total = 0.;
        p.reload_credited = false;
        p.reload_empty = false;
        p.last_exit = None;
        self.emit(ActionEventKind::Died);
    }
    /// Returns true while dead: input is ignored and only the respawn timer runs.
    pub(super) fn step_death(&mut self, cfg: &Settings) -> bool {
        let Some(since) = self.player.dead_since else {
            return false;
        };
        if self.time - since + 1e-7 >= cfg.action.respawn_delay as f64 {
            self.player = Player {
                health: cfg.action.max_health,
                tac_charge: cfg.action.tac_sprint_duration,
                ..Player::default()
            };
            self.emit(ActionEventKind::Respawned);
        }
        true
    }

    /// Clamp view angles to hang/mount limits. Call after applying mouse look;
    /// `update` also calls it so gameplay never sees an out-of-range aim.
    pub fn clamp_look(&mut self, cfg: &Settings) {
        let t = &cfg.action;
        let p = &mut self.player;
        let (center, yaw_limit, up, down) = if let Action::Hang(h) = p.action {
            (
                h.yaw_center,
                t.hang_yaw_limit,
                t.hang_pitch_up,
                t.hang_pitch_down,
            )
        } else if let Some(m) = p.mount {
            (
                m.yaw_center,
                t.mount_yaw_limit,
                t.mount_pitch_up,
                t.mount_pitch_down,
            )
        } else {
            return;
        };
        let offset =
            wrap_angle(p.yaw - center).clamp(-yaw_limit.to_radians(), yaw_limit.to_radians());
        p.yaw = center + offset;
        p.pitch = p.pitch.clamp(-down.to_radians(), up.to_radians());
    }

    /// Explicit weapon permissions for the current state (see docs/TRAVERSAL.md).
    pub fn weapon_permissions(&self) -> WeaponPermissions {
        let p = &self.player;
        if p.dead() || p.mantle.is_some() {
            return WeaponPermissions::NONE;
        }
        let mut perms = match p.action {
            Action::None => WeaponPermissions {
                sprint: p.mount.is_none(),
                ..WeaponPermissions::ALL
            },
            Action::Slide(s) => {
                let free = self
                    .timings
                    .get(ActionSlot::SlideEnter)
                    .event_seconds("weapon_free");
                if s.elapsed + 1e-6 < free {
                    WeaponPermissions::NONE
                } else {
                    WeaponPermissions {
                        sprint: false,
                        ..WeaponPermissions::ALL
                    }
                }
            }
            Action::Dive(d) => WeaponPermissions {
                fire: d.phase == DivePhase::Air,
                ..WeaponPermissions::NONE
            },
            Action::Hang(h) => WeaponPermissions {
                ads: h.pistol == PistolPhase::Ready,
                fire: h.pistol == PistolPhase::Ready,
                ..WeaponPermissions::NONE
            },
        };
        if self.time < p.weapon_lockout_until {
            perms.ads = false;
            perms.fire = false;
            perms.reload = false;
        }
        perms.ads &= !p.obstruction.ads_blocked;
        perms.fire &= !p.obstruction.fire_blocked;
        perms
    }

    /// Edge-triggered action starts, cancels and hang inputs. Runs before
    /// movement so a rejected attempt leaves ordinary movement untouched.
    pub(super) fn begin_actions(&mut self, input: Input, cfg: &Settings, dt: f32) {
        let p = &self.player;
        let jump_edge = input.jump && !p.jump_held;
        let crouch_edge = input.crouch && !p.crouch_was;
        let prone_edge = input.prone && !p.prone_was;
        let stance_changed = input.crouch != p.crouch_was || input.prone != p.prone_was;
        match p.action {
            Action::None if p.mantle.is_none() => {
                self.update_mount(input, cfg, dt, jump_edge);
                if input.tactical_sprint {
                    self.try_tac_sprint(input, cfg);
                }
                if crouch_edge && !prone_edge && self.player.sprinting {
                    self.try_slide(cfg);
                } else if prone_edge && self.player.sprinting {
                    self.try_dive(cfg);
                }
            }
            Action::Slide(_) => {
                if jump_edge {
                    if self.capsule_fits(self.player.position, STANDING_HEIGHT) {
                        // Jump-cancel: stand now; normal movement launches this tick.
                        let p = &mut self.player;
                        p.action = Action::None;
                        p.crouched = false;
                        p.prone = false;
                        p.eye_from = p.eye_height;
                        p.stance_progress = 0.;
                        p.stance_duration = 0.2;
                        p.slide_ready_at = self.time + cfg.action.slide_cooldown as f64;
                        p.last_exit = Some((ActionSlot::SlideInterrupt, self.time));
                        self.emit(ActionEventKind::SlideInterrupted);
                    }
                } else if stance_changed {
                    self.end_slide(input, cfg, true);
                }
            }
            Action::Hang(h) if !self.hang_valid(&h) => {
                // Support changed: release before any hang input can use it.
                self.release_hang(h, cfg, true);
            }
            Action::Hang(h) => {
                let planted = h.elapsed + 1e-6
                    >= self
                        .timings
                        .get(ActionSlot::LedgeCatch)
                        .event_seconds("hands_planted");
                if planted && jump_edge {
                    self.try_pull_up(h);
                } else if planted && crouch_edge {
                    self.release_hang(h, cfg, false);
                } else if planted && input.sidearm {
                    self.toggle_sidearm(h);
                }
            }
            _ => {}
        }
        let p = &mut self.player;
        p.crouch_was = input.crouch;
        p.prone_was = input.prone;
    }

    fn try_tac_sprint(&mut self, input: Input, cfg: &Settings) {
        let t = &cfg.action;
        let p = &self.player;
        let eligible = p.tac_sprint.is_none()
            && p.mount.is_none()
            && input.sprint
            && input.movement.y > 0.83
            && p.grounded
            && !p.crouched
            && !p.prone
            && !input.ads
            && !input.fire
            && p.reload_left <= 0.
            && !p.sprint_exhausted
            && p.stamina > 0.00001
            && p.tac_charge >= t.tac_sprint_min_charge;
        if eligible {
            self.player.tac_sprint = Some(TacSprint { elapsed: 0. });
            self.emit(ActionEventKind::TacSprintStarted);
        }
    }

    fn end_tac_sprint(&mut self, cfg: &Settings) {
        if self.player.tac_sprint.take().is_some() {
            self.player.tac_recharge_wait = cfg.action.tac_sprint_recharge_delay;
            self.player.last_exit = Some((ActionSlot::TacSprintExit, self.time));
            self.emit(ActionEventKind::TacSprintEnded);
        }
    }

    fn try_slide(&mut self, cfg: &Settings) {
        let t = &cfg.action;
        let p = &self.player;
        let eligible = p.grounded
            && p.mount.is_none()
            && !p.crouched
            && !p.prone
            && p.stance_progress >= 1.
            && p.speed() >= t.slide_min_speed
            && self.time >= p.slide_ready_at;
        if !eligible {
            self.emit(ActionEventKind::SlideRejected(Rejection::Ineligible));
            return;
        }
        if !self.capsule_fits(p.position, t.slide_height) {
            self.emit(ActionEventKind::SlideRejected(Rejection::Blocked));
            return;
        }
        self.end_tac_sprint(cfg);
        let p = &mut self.player;
        let horizontal = vec2(p.velocity.x, p.velocity.z);
        // One capped boost: sprint or tactical-sprint speed never stacks past max.
        let speed = (horizontal.length() + t.slide_boost).min(t.slide_max_speed);
        let dir = horizontal.normalize_or_zero();
        p.velocity.x = dir.x * speed;
        p.velocity.z = dir.y * speed;
        p.sprinting = false;
        p.sprint_out = 0.;
        p.firing_sequence = false;
        p.action = Action::Slide(SlideState {
            phase: SlidePhase::Entry,
            elapsed: 0.,
            height: t.slide_height,
            eye_from: p.eye_height,
        });
        self.emit(ActionEventKind::SlideStarted);
    }

    /// In-place fit using the existing stance rule: blocks obstruct, ramps are
    /// floors under the feet.
    fn capsule_fits(&self, pos: Vec3, height: f32) -> bool {
        let bounds = Aabb {
            min: pos - vec3(RADIUS, 0., RADIUS) + Vec3::Y * 0.002,
            max: pos + vec3(RADIUS, height, RADIUS),
        };
        !self.blocks.iter().any(|b| bounds.overlaps(b.bounds))
    }
    /// Settle into the desired stance, or the next lower one that fits.
    fn settle_stance(&mut self, desired: i32) {
        let pos = self.player.position;
        let stance = (desired..=2)
            .find(|s| self.capsule_fits(pos, stance_height(*s)))
            .unwrap_or(2);
        let p = &mut self.player;
        p.crouched = stance > 0;
        p.prone = stance == 2;
        p.eye_from = p.eye_height;
        p.stance_progress = 0.;
        p.stance_duration = if stance == 2 { 0.4 } else { 0.2 };
    }

    fn end_slide(&mut self, input: Input, cfg: &Settings, interrupted: bool) {
        let desired = if input.prone {
            2
        } else if input.crouch {
            1
        } else {
            0
        };
        // Never stand through a ceiling: lower stances are chosen by clearance.
        self.settle_stance(desired);
        let ready = self
            .timings
            .get(ActionSlot::SlideRecover)
            .event_seconds("weapon_ready");
        let p = &mut self.player;
        p.action = Action::None;
        p.slide_ready_at = self.time + cfg.action.slide_cooldown as f64;
        p.weapon_lockout_until = self.time + ready as f64;
        p.last_exit = Some((
            if interrupted {
                ActionSlot::SlideInterrupt
            } else {
                ActionSlot::SlideRecover
            },
            self.time,
        ));
        self.emit(if interrupted {
            ActionEventKind::SlideInterrupted
        } else {
            ActionEventKind::SlideEnded
        });
    }

    fn try_dive(&mut self, cfg: &Settings) {
        let t = &cfg.action;
        let p = &self.player;
        let eligible = p.grounded
            && p.mount.is_none()
            && !p.crouched
            && !p.prone
            && p.stance_progress >= 1.
            && p.speed() >= t.dive_min_speed;
        if !eligible {
            self.emit(ActionEventKind::DiveRejected(Rejection::Ineligible));
            return;
        }
        let forward = vec3(p.velocity.x, 0., p.velocity.z).normalize_or_zero();
        let start = p.position + Vec3::Y * 0.002;
        let raised = start + Vec3::Y * t.dive_min_headroom;
        // The launch arc must have headroom and forward space: no diving into
        // a wall or under a ceiling that the capsule could not occupy.
        if !self.sweep_clear(start, raised, t.dive_height)
            || !self.sweep_clear(
                raised,
                raised + forward * t.dive_min_forward_clearance,
                t.dive_height,
            )
        {
            self.emit(ActionEventKind::DiveRejected(Rejection::Blocked));
            return;
        }
        self.end_tac_sprint(cfg);
        let p = &mut self.player;
        p.velocity = forward * t.dive_forward_speed + Vec3::Y * t.dive_up_speed;
        p.grounded = false;
        p.previous_grounded = false;
        p.last_jump_at = self.time;
        p.air_speed_limit = t.dive_forward_speed;
        p.sprinting = false;
        p.sprint_out = 0.;
        p.firing_sequence = false;
        p.action = Action::Dive(DiveState {
            phase: DivePhase::Launch,
            elapsed: 0.,
            height: t.dive_height,
            eye_from: p.eye_height,
        });
        self.emit(ActionEventKind::DiveLaunched);
    }

    pub(super) fn advance_action(&mut self, input: Input, cfg: &Settings, dt: f32) {
        match self.player.action {
            Action::Slide(s) => self.advance_slide(s, input, cfg, dt),
            Action::Dive(d) => self.advance_dive(d, input, cfg, dt),
            Action::Hang(h) => self.advance_hang(h, input, cfg, dt),
            Action::None => {}
        }
    }

    fn recover_stamina(&mut self, input: Input, dt: f32) {
        let p = &mut self.player;
        p.sprinting = false;
        p.sprint_recovery = (p.sprint_recovery - dt).max(0.);
        if p.sprint_recovery == 0. {
            p.stamina = (p.stamina + dt).min(SPRINT_DURATION);
        }
        if !input.sprint {
            p.sprint_exhausted = false;
        }
    }

    fn advance_slide(&mut self, mut s: SlideState, input: Input, cfg: &Settings, dt: f32) {
        let t = &cfg.action;
        let enter = self.timings.get(ActionSlot::SlideEnter);
        let (enter_duration, lower) = (enter.duration, enter.event_seconds("capsule_low"));
        self.recover_stamina(input, dt);
        let slope_accel = self
            .ramps
            .iter()
            .find_map(|r| {
                let h = r.surface(self.player.position.x, self.player.position.z)?;
                ((self.player.position.y - h).abs() < 0.01 && r.slope() <= 1.0001)
                    .then(|| cfg.gravity * r.slope() / (1. + r.slope() * r.slope()).sqrt())
            })
            .unwrap_or(0.);
        let p = &mut self.player;
        p.jump_held = input.jump;
        s.elapsed += dt;
        if s.phase == SlidePhase::Entry && s.elapsed + 1e-6 >= enter_duration {
            s.phase = SlidePhase::Active;
        }
        p.eye_height =
            s.eye_from + (t.slide_eye - s.eye_from) * smoothstep(s.elapsed / lower.max(1e-3));
        let forward = horizontal(p.yaw);
        let right = forward.cross(Vec3::Y);
        let wish = right * input.movement.x + forward * input.movement.y;
        let mut h = steer(
            vec2(p.velocity.x, p.velocity.z),
            vec2(wish.x, wish.z),
            t.slide_steer_rate.to_radians() * dt,
        );
        // Ramps descend toward +Z: gravity along the slope adds or removes speed.
        h.y += slope_accel * t.slide_slope_scale * dt;
        let speed = (h.length() - t.slide_friction * dt).clamp(0., t.slide_max_speed);
        h = h.normalize_or_zero() * speed;
        p.velocity.x = h.x;
        p.velocity.z = h.y;
        p.action = Action::Slide(s);
        self.integrate(cfg, dt);
        if self.player.dead() {
            return;
        }
        if !self.player.grounded {
            self.end_slide(input, cfg, true);
        } else if self.player.speed() < t.slide_stop_speed || s.elapsed >= t.slide_max_time {
            self.end_slide(input, cfg, false);
        }
    }

    fn advance_dive(&mut self, mut d: DiveState, input: Input, cfg: &Settings, dt: f32) {
        let t = &cfg.action;
        let launch = self.timings.get(ActionSlot::DiveLaunch);
        let (launch_duration, steer_at) = (launch.duration, launch.event_seconds("steer_allowed"));
        let impact_duration = self.timings.get(ActionSlot::DiveImpact).duration;
        let recover = self.timings.get(ActionSlot::DiveRecover);
        let (ready, cancel) = (
            recover.event_seconds("weapon_ready"),
            recover.event_seconds("cancel_allowed"),
        );
        self.recover_stamina(input, dt);
        let p = &mut self.player;
        p.jump_held = input.jump;
        d.elapsed += dt;
        match d.phase {
            DivePhase::Launch | DivePhase::Air => {
                if d.phase == DivePhase::Launch && d.elapsed + 1e-6 >= steer_at {
                    d.phase = DivePhase::Air;
                    d.elapsed = 0.;
                }
                if d.phase == DivePhase::Air {
                    let forward = horizontal(p.yaw);
                    let right = forward.cross(Vec3::Y);
                    let wish = right * input.movement.x + forward * input.movement.y;
                    let h = steer(
                        vec2(p.velocity.x, p.velocity.z),
                        vec2(wish.x, wish.z),
                        t.dive_steer_rate.to_radians() * dt,
                    );
                    p.velocity.x = h.x;
                    p.velocity.z = h.y;
                }
                let blend = if d.phase == DivePhase::Launch {
                    smoothstep(d.elapsed / launch_duration.max(1e-3))
                } else {
                    1.
                };
                p.eye_height = d.eye_from + (t.dive_eye - d.eye_from) * blend;
                p.action = Action::Dive(d);
                self.integrate(cfg, dt);
                if self.player.dead() || !self.player.grounded {
                    return;
                }
                // Impact is triggered by actual ground contact from collision.
                let p = &mut self.player;
                p.prone = true;
                p.crouched = true;
                p.eye_from = p.eye_height;
                p.stance_progress = 0.;
                p.stance_duration = impact_duration.max(1e-3);
                p.velocity.x *= t.dive_landing_speed_scale;
                p.velocity.z *= t.dive_landing_speed_scale;
                p.action = Action::Dive(DiveState {
                    phase: DivePhase::Impact,
                    elapsed: 0.,
                    ..d
                });
                self.emit(ActionEventKind::DiveImpact);
            }
            DivePhase::Impact => {
                let h = vec2(p.velocity.x, p.velocity.z);
                let speed = (h.length() - t.dive_ground_friction * dt).max(0.);
                let h = h.normalize_or_zero() * speed;
                p.velocity.x = h.x;
                p.velocity.z = h.y;
                p.stance_progress = (p.stance_progress + dt / p.stance_duration).min(1.);
                p.eye_height = p.eye_from + (0.2794 - p.eye_from) * smoothstep(p.stance_progress);
                p.action = Action::Dive(d);
                self.integrate(cfg, dt);
                if self.player.dead() || d.elapsed + 1e-6 < impact_duration {
                    return;
                }
                // Hand over to the existing prone system.
                let p = &mut self.player;
                p.action = Action::None;
                p.weapon_lockout_until = self.time + ready as f64;
                p.stance_lock_until = self.time + cancel as f64;
                p.last_exit = Some((ActionSlot::DiveRecover, self.time));
                self.emit(ActionEventKind::DiveEnded);
            }
        }
    }

    fn hand_box(hand: Vec3) -> Aabb {
        Aabb {
            min: hand + vec3(-0.05, 0.001, -0.05),
            max: hand + vec3(0.05, 0.15, 0.05),
        }
    }
    /// True when no block or ramp intersects `a` (open intervals).
    fn aabb_clear(&self, a: Aabb) -> bool {
        if self.blocks.iter().any(|b| a.overlaps(b.bounds)) {
            return false;
        }
        let c = a.center();
        let corners = [
            a.min,
            a.max,
            c,
            vec3(a.min.x, a.min.y, a.max.z),
            vec3(a.max.x, a.min.y, a.min.z),
        ];
        !self.ramps.iter().any(|r| {
            corners
                .iter()
                .any(|q| r.surface(q.x, q.z).is_some_and(|h| q.y < h - 1e-4))
        })
    }

    fn hang_valid(&self, h: &HangState) -> bool {
        self.blocks
            .iter()
            .any(|b| b.bounds.min == h.support.min && b.bounds.max == h.support.max)
            && self.sweep_clear(h.position, h.position, STANDING_HEIGHT)
            && h.hands
                .iter()
                .all(|hand| self.aabb_clear(Self::hand_box(*hand)))
    }

    /// Airborne ledge catch. Static blocks only: anything that changes the
    /// held block releases the hang, so moving supports are rejected.
    fn try_catch_ledge(&mut self, input: Input, cfg: &Settings) {
        let t = &cfg.action;
        let p = &self.player;
        if p.crouched
            || p.prone
            || input.movement.y < 0.5
            || p.velocity.y > t.hang_max_rise_speed
            || self.time < p.recatch_until
        {
            return;
        }
        let forward = horizontal(p.yaw);
        let origin = vec3(p.position.x, 0., p.position.z);
        let hands_y = p.position.y + t.hang_hand_height;
        let mut best: Option<(f32, HangState)> = None;
        for block in &self.blocks {
            let b = block.bounds;
            if p.recatch_support
                .is_some_and(|s| s.min == b.min && s.max == b.max)
            {
                continue;
            }
            let lip = b.max.y - hands_y;
            if !(-t.hang_catch_above..=t.hang_catch_below).contains(&lip) {
                continue;
            }
            let expanded = Aabb {
                min: vec3(b.min.x - RADIUS, -1., b.min.z - RADIUS),
                max: vec3(b.max.x + RADIUS, 1., b.max.z + RADIUS),
            };
            let inside = (0..3)
                .step_by(2)
                .all(|a| origin[a] > expanded.min[a] + 1e-4 && origin[a] < expanded.max[a] - 1e-4);
            if inside {
                continue;
            }
            let Some(distance) = expanded.ray(origin, forward, t.hang_reach) else {
                continue;
            };
            let contact = origin + forward * distance;
            let normal = face_normal(expanded, vec3(contact.x, 0., contact.z));
            if normal.y != 0. || forward.dot(-normal) < 50_f32.to_radians().cos() {
                continue;
            }
            let position =
                vec3(contact.x, b.max.y - t.hang_hand_height, contact.z) + normal * t.hang_wall_gap;
            let tangent = vec3(-normal.z, 0., normal.x);
            let lip_center =
                position - normal * (RADIUS + t.hang_wall_gap) - normal * t.hang_hand_inset;
            let hands = [-0.5, 0.5].map(|side| {
                vec3(lip_center.x, b.max.y, lip_center.z) + tangent * side * t.hang_hand_spacing
            });
            let on_top = hands.iter().all(|h| {
                h.x > b.min.x + 0.01
                    && h.x < b.max.x - 0.01
                    && h.z > b.min.z + 0.01
                    && h.z < b.max.z - 0.01
            });
            let state = HangState {
                phase: HangPhase::Catch,
                elapsed: 0.,
                support: b,
                normal,
                position,
                hands,
                lip: vec3(lip_center.x, b.max.y, lip_center.z) + normal * t.hang_hand_inset,
                pistol: PistolPhase::Holstered,
                pistol_elapsed: 0.,
                yaw_center: (-normal.z).atan2(-normal.x),
                eye_from: p.eye_height,
            };
            let below = Aabb {
                min: position - vec3(RADIUS, t.hang_min_ground_gap, RADIUS),
                max: position + vec3(RADIUS, 0., RADIUS),
            };
            if !on_top
                || !self.hang_valid(&state)
                || !self.sweep_clear(p.position, position, STANDING_HEIGHT)
                || (t.hang_min_ground_gap > 0. && !self.aabb_clear(below))
            {
                continue;
            }
            if best.as_ref().is_none_or(|(d, _)| distance < *d) {
                best = Some((distance, state));
            }
        }
        let Some((_, state)) = best else { return };
        let p = &mut self.player;
        p.action = Action::Hang(state);
        p.position = state.position;
        p.velocity = Vec3::ZERO;
        p.grounded = false;
        p.previous_grounded = false;
        p.sprinting = false;
        p.tac_sprint = None;
        p.firing_sequence = false;
        // Like mantling, both hands leave the rifle: credited rounds stay, an
        // uncredited reload is cancelled and not queued.
        p.reload_left = 0.;
        p.reload_credit_at = 0.;
        p.reload_ready_at = 0.;
        p.reload_total = 0.;
        p.reload_credited = false;
        p.reload_empty = false;
        self.emit(ActionEventKind::LedgeCaught);
    }

    fn advance_hang(&mut self, mut h: HangState, input: Input, cfg: &Settings, dt: f32) {
        let t = &cfg.action;
        let catch = self.timings.get(ActionSlot::LedgeCatch).duration;
        let ready = self
            .timings
            .get(ActionSlot::PistolDraw)
            .event_seconds("ready");
        let regrip = self
            .timings
            .get(ActionSlot::PistolStow)
            .event_seconds("regrip");
        self.recover_stamina(input, dt);
        self.player.jump_held = input.jump;
        if !self.hang_valid(&h) {
            self.release_hang(h, cfg, true);
            return;
        }
        h.elapsed += dt;
        if h.phase == HangPhase::Catch && h.elapsed + 1e-6 >= catch {
            h.phase = HangPhase::Hold;
        }
        h.pistol_elapsed += dt;
        if h.pistol == PistolPhase::Drawing && h.pistol_elapsed + 1e-6 >= ready {
            h.pistol = PistolPhase::Ready;
            self.emit(ActionEventKind::PistolReady);
        } else if h.pistol == PistolPhase::Stowing && h.pistol_elapsed + 1e-6 >= regrip {
            h.pistol = PistolPhase::Holstered;
            self.emit(ActionEventKind::PistolHolstered);
        }
        // Gravity and locomotion are suspended: the ledge owns the body.
        let p = &mut self.player;
        p.position = h.position;
        p.velocity = Vec3::ZERO;
        p.grounded = false;
        p.previous_grounded = false;
        p.eye_height =
            h.eye_from + (t.hang_eye_height - h.eye_from) * smoothstep(h.elapsed / catch.max(1e-3));
        p.action = Action::Hang(h);
    }

    /// Release support exactly once and restore airborne movement immediately.
    fn release_hang(&mut self, h: HangState, cfg: &Settings, lost: bool) {
        let t = &cfg.action;
        if h.pistol != PistolPhase::Holstered {
            self.emit(ActionEventKind::PistolInterrupted);
        }
        let ready = self
            .timings
            .get(ActionSlot::HangDrop)
            .event_seconds("weapon_ready");
        let p = &mut self.player;
        p.action = Action::None;
        p.velocity = if lost {
            Vec3::ZERO
        } else {
            h.normal * t.hang_drop_push
        };
        p.grounded = false;
        p.previous_grounded = false;
        p.air_speed_limit = cfg.walk_speed * 1.05;
        p.recatch_until = self.time + t.hang_recatch_delay as f64;
        p.recatch_support = Some(h.support);
        // The drop press must not also crouch the player.
        p.stance_override = true;
        p.eye_from = p.eye_height;
        p.stance_progress = 0.;
        p.stance_duration = 0.2;
        p.weapon_lockout_until = self.time + ready as f64;
        p.last_exit = Some((
            if lost {
                ActionSlot::LedgeLost
            } else {
                ActionSlot::HangDrop
            },
            self.time,
        ));
        self.emit(if lost {
            ActionEventKind::LedgeLost
        } else {
            ActionEventKind::HangDropped
        });
    }

    fn try_pull_up(&mut self, h: HangState) {
        if h.pistol != PistolPhase::Holstered {
            self.emit(ActionEventKind::PullUpRejected(Rejection::PistolOut));
            return;
        }
        let Some(state) = self.plan_pull_up(&h) else {
            // Documented fallback: stay hanging; no teleport, no partial climb.
            self.emit(ActionEventKind::PullUpRejected(Rejection::Blocked));
            return;
        };
        let p = &mut self.player;
        p.action = Action::None;
        p.mantle = Some(state);
        p.velocity = Vec3::ZERO;
        p.last_jump_at = self.time;
        self.emit(ActionEventKind::PullUpStarted);
    }

    /// Reuse the mantle landing rules: the full standing footprint on the held
    /// top, and every swept leg plus the landing volume clear.
    fn plan_pull_up(&self, h: &HangState) -> Option<MantleState> {
        let b = h.support;
        let into = -h.normal;
        let inset = RADIUS + MANTLE_LANDING_MARGIN;
        let interior = Aabb {
            min: vec3(b.min.x + inset, -1., b.min.z + inset),
            max: vec3(b.max.x - inset, 1., b.max.z - inset),
        };
        if interior.min.x >= interior.max.x || interior.min.z >= interior.max.z {
            return None;
        }
        let origin = vec3(h.position.x, 0., h.position.z);
        let travel = interior.ray(origin, into, MANTLE_MAX_TRAVEL)?;
        let landing = h.position + into * travel;
        let state = MantleState {
            kind: MantleKind::High,
            start: h.position,
            landing: vec3(landing.x, b.max.y, landing.z),
            elapsed: 0.,
            duration: self.timings.get(ActionSlot::PullUp).duration,
            support: b,
            from_hang: true,
        };
        (self.mantle_sweep_clear(state.start, state.raised_start())
            && self.mantle_sweep_clear(state.raised_start(), state.raised_landing())
            && self.mantle_sweep_clear(state.raised_landing(), state.landing)
            && self.mantle_sweep_clear(state.landing, state.landing))
        .then_some(state)
    }

    fn toggle_sidearm(&mut self, mut h: HangState) {
        match h.pistol {
            PistolPhase::Holstered => {
                if !self.loadout.sidearm.is_some_and(|s| s.hang_eligible) {
                    // Unsupported loadout: nothing changes, both hands stay on the ledge.
                    self.emit(ActionEventKind::SidearmRejected(Rejection::NoSidearm));
                    return;
                }
                h.pistol = PistolPhase::Drawing;
                self.emit(ActionEventKind::PistolDrawStarted);
            }
            PistolPhase::Ready => {
                h.pistol = PistolPhase::Stowing;
                self.player.ads_requested = false;
                self.emit(ActionEventKind::PistolStowStarted);
            }
            // Presses during a grip transfer are consumed, not queued.
            PistolPhase::Drawing | PistolPhase::Stowing => return,
        }
        h.pistol_elapsed = 0.;
        self.player.action = Action::Hang(h);
    }

    pub(super) fn fire_sidearm(&mut self, cfg: &Settings) {
        let Some(spec) = self.loadout.sidearm else {
            return;
        };
        self.fire_with(
            cfg,
            FireProfile {
                rpm: spec.rpm,
                body_damage: spec.body_damage,
                head_damage: spec.head_damage,
                recoil_scale: spec.recoil_scale,
                sidearm: true,
            },
        );
    }

    fn find_mount(&self, cfg: &Settings, yaw: f32) -> Result<MountCandidate, Rejection> {
        let t = &cfg.action;
        let p = &self.player;
        if !p.grounded
            || p.prone
            || p.speed() > t.mount_max_speed
            || p.mantle.is_some()
            || !matches!(p.action, Action::None)
        {
            return Err(Rejection::Ineligible);
        }
        let eye = vec3(p.position.x, p.position.y + p.eye_height, p.position.z);
        let forward = horizontal(yaw);
        let origin = vec3(eye.x, 0., eye.z);
        let band = t.mount_min_below_eye..=t.mount_max_below_eye;
        let mut best: Option<MountCandidate> = None;
        let mut rejection = Rejection::Ineligible;
        for block in &self.blocks {
            let b = block.bounds;
            if !band.contains(&(eye.y - b.max.y)) {
                continue;
            }
            let rect = Aabb {
                min: vec3(b.min.x, -1., b.min.z),
                max: vec3(b.max.x, 1., b.max.z),
            };
            let Some(distance) = rect.ray(origin, forward, t.mount_reach) else {
                continue;
            };
            if distance <= 1e-4 {
                continue;
            }
            let support = vec3(
                origin.x + forward.x * distance,
                b.max.y,
                origin.z + forward.z * distance,
            );
            if !self.mount_clear(cfg, eye, support, forward) {
                rejection = Rejection::Blocked;
                continue;
            }
            if best.as_ref().is_none_or(|c| distance < c.distance) {
                best = Some(MountCandidate {
                    support,
                    normal: Vec3::Y,
                    distance,
                });
            }
        }
        // Sloped surfaces: the first ramp point in the height band must be flat enough.
        for ramp in &self.ramps {
            let mut d = 0.05;
            while d <= t.mount_reach {
                let q = origin + forward * d;
                if let Some(height) = ramp.surface(q.x, q.z) {
                    if band.contains(&(eye.y - height)) {
                        if ramp.slope().atan().to_degrees() > t.mount_max_angle {
                            rejection = Rejection::Steep;
                        } else if best.as_ref().is_none_or(|c| d < c.distance) {
                            let support = vec3(q.x, height, q.z);
                            if self.mount_clear(cfg, eye, support, forward) {
                                best = Some(MountCandidate {
                                    support,
                                    normal: vec3(0., 1., ramp.slope()).normalize(),
                                    distance: d,
                                });
                            }
                        }
                        break;
                    }
                }
                d += 0.05;
            }
        }
        best.ok_or(rejection)
    }

    /// The rested weapon volume and the eye-to-support line must be clear.
    fn mount_clear(&self, cfg: &Settings, eye: Vec3, support: Vec3, forward: Vec3) -> bool {
        let t = &cfg.action;
        let back = support - forward * 0.25;
        let front = support + forward * t.weapon_length * 0.6;
        let c = t.mount_clearance;
        let rest = Aabb {
            min: back.min(front) - vec3(c, 0., c) + Vec3::Y * 0.005,
            max: back.max(front) + vec3(c, c + 0.08, c),
        };
        if !self.aabb_clear(rest) {
            return false;
        }
        let target = support + Vec3::Y * 0.02;
        let to = target - eye;
        let length = to.length();
        let dir = to / length;
        !self
            .blocks
            .iter()
            .any(|b| b.bounds.ray(eye, dir, length - 0.01).is_some())
            && !self
                .ramps
                .iter()
                .any(|r| r.ray(eye, dir, length - 0.01).is_some())
    }

    fn update_mount(&mut self, input: Input, cfg: &Settings, dt: f32, jump_edge: bool) {
        let t = &cfg.action;
        if let Some(m) = self.player.mount {
            let p = &self.player;
            let still_supported = self
                .find_mount(cfg, m.yaw_center)
                .is_ok_and(|c| (c.support - m.support).length() < 0.05);
            let voluntary = input.mount
                || input.movement.length() > t.mount_move_deadzone
                || jump_edge
                || (m.via_ads && !input.ads);
            let invalid = input.crouch != m.crouched
                || input.prone
                || p.crouched != m.crouched
                || (p.position - m.position).length() > 0.02
                || !still_supported;
            if voluntary || invalid {
                let p = &mut self.player;
                p.mount = None;
                p.mount_ready_for = 0.;
                p.last_exit = Some((ActionSlot::MountExit, self.time));
                self.emit(ActionEventKind::MountEnded);
            }
            return;
        }
        let wants_auto = input.ads && self.player.ads_requested;
        if !input.mount && !wants_auto {
            self.player.mount_ready_for = 0.;
            return;
        }
        let candidate = self.find_mount(cfg, self.player.yaw);
        let via_ads = !input.mount;
        match candidate {
            Ok(c) => {
                if via_ads {
                    self.player.mount_ready_for += dt;
                    if self.player.mount_ready_for + 1e-6 < t.mount_auto_delay {
                        return;
                    }
                }
                let p = &mut self.player;
                p.mount = Some(MountState {
                    support: c.support,
                    normal: c.normal,
                    yaw_center: p.yaw,
                    position: p.position,
                    crouched: p.crouched,
                    via_ads,
                    elapsed: 0.,
                    weight: 0.,
                });
                p.velocity.x = 0.;
                p.velocity.z = 0.;
                p.mount_ready_for = 0.;
                self.end_tac_sprint(cfg);
                self.emit(ActionEventKind::MountStarted);
            }
            Err(reason) => {
                self.player.mount_ready_for = 0.;
                if input.mount {
                    self.emit(ActionEventKind::MountRejected(reason));
                }
            }
        }
    }

    /// Post-movement upkeep: tactical sprint resource, ledge catch, mount blend
    /// and wall obstruction.
    pub(super) fn after_move(&mut self, input: Input, cfg: &Settings, dt: f32) {
        if self.player.dead() {
            return;
        }
        let t = &cfg.action;
        if self.player.tac_sprint.is_some() && !self.player.sprinting {
            self.end_tac_sprint(cfg);
        }
        if let Some(tac) = &mut self.player.tac_sprint {
            tac.elapsed += dt;
            self.player.tac_charge = (self.player.tac_charge - dt).max(0.);
            if self.player.tac_charge <= 0. {
                self.end_tac_sprint(cfg);
            }
        } else {
            let p = &mut self.player;
            p.tac_recharge_wait = (p.tac_recharge_wait - dt).max(0.);
            if p.tac_recharge_wait == 0. {
                p.tac_charge = (p.tac_charge + dt).min(t.tac_sprint_duration);
            }
        }
        if self.player.grounded {
            self.player.recatch_support = None;
        }
        if matches!(self.player.action, Action::None)
            && self.player.mantle.is_none()
            && !self.player.grounded
        {
            self.try_catch_ledge(input, cfg);
        }
        let enter = self.timings.get(ActionSlot::MountEnter).duration;
        if let Some(m) = &mut self.player.mount {
            m.elapsed += dt;
            m.weight = (m.elapsed / enter.max(1e-3)).min(1.);
        }
        self.update_obstruction(cfg, dt);
    }

    /// Nearest hit along a ray against blocks and ramps, with a surface normal.
    fn cast(&self, origin: Vec3, dir: Vec3, limit: f32) -> Option<(f32, Vec3)> {
        let mut best: Option<(f32, Vec3)> = None;
        for b in &self.blocks {
            if let Some(d) = b.bounds.ray(origin, dir, limit) {
                if best.is_none_or(|(n, _)| d < n) {
                    best = Some((d, face_normal(b.bounds, origin + dir * d)));
                }
            }
        }
        for r in &self.ramps {
            if let Some(d) = r.ray(origin, dir, limit) {
                if best.is_none_or(|(n, _)| d < n) {
                    best = Some((d, -dir));
                }
            }
        }
        best
    }

    /// Penetration of the weapon volume (several lines along its length and
    /// radius, from the weapon's actual hip/ADS offset) into world geometry.
    fn measure_obstruction(&self, cfg: &Settings) -> (f32, f32, Vec3) {
        let t = &cfg.action;
        let p = &self.player;
        let eye = p.eye();
        let forward = p.direction();
        let right = forward.cross(Vec3::Y).normalize();
        let up = right.cross(forward);
        let base = eye + right * 0.14 * (1. - p.ads) - up * 0.15 * (1. - p.ads);
        let to_base = base - eye;
        if to_base.length() > 1e-4 {
            if let Some((_, normal)) = self.cast(eye, to_base.normalize(), to_base.length()) {
                return (1., 0., normal);
            }
        }
        let length = t.weapon_length;
        let r = t.weapon_radius;
        let mut nearest: Option<(f32, Vec3)> = None;
        for offset in [Vec3::ZERO, right * r, -right * r, up * r, -up * r] {
            if let Some((d, n)) = self.cast(base + offset, forward, length) {
                if nearest.is_none_or(|(best, _)| d < best) {
                    nearest = Some((d, n));
                }
            }
        }
        match nearest {
            Some((d, normal)) => (
                ((length - d) / t.obstruct_max_retract).clamp(0., 1.),
                d,
                normal,
            ),
            None => (0., 10., Vec3::ZERO),
        }
    }

    fn update_obstruction(&mut self, cfg: &Settings, dt: f32) {
        let t = &cfg.action;
        let p = &self.player;
        // Mount validation already guarantees the rested weapon volume is clear;
        // traversal states hold no rifle at the hip.
        let (raw, clear, direction) =
            if p.mount.is_some() || p.mantle.is_some() || !matches!(p.action, Action::None) {
                (0., 10., Vec3::ZERO)
            } else {
                self.measure_obstruction(cfg)
            };
        let was_blocked = p.obstruction.fire_blocked;
        let o = &mut self.player.obstruction;
        o.raw = raw;
        o.clear_length = clear;
        if raw > 0. {
            o.direction = direction;
        }
        if raw > o.amount {
            o.amount = (o.amount + t.obstruct_rate_in * dt).min(raw);
            o.below_for = 0.;
        } else if raw < o.amount - t.obstruct_hysteresis || (raw == 0. && o.amount > 0.) {
            // Recover only after the wall has stayed away briefly: no edge jitter.
            o.below_for += dt;
            if o.below_for + 1e-6 >= t.obstruct_recover_delay {
                o.amount = (o.amount - t.obstruct_rate_out * dt).max(raw);
            }
        } else {
            o.below_for = 0.;
        }
        if o.amount == 0. {
            o.direction = Vec3::ZERO;
        }
        if o.amount >= t.obstruct_fire_block {
            o.fire_blocked = true;
        } else if o.amount < t.obstruct_fire_release {
            o.fire_blocked = false;
        }
        if o.amount >= t.obstruct_ads_block {
            o.ads_blocked = true;
        } else if o.amount < t.obstruct_ads_block - t.obstruct_hysteresis {
            o.ads_blocked = false;
        }
        let blocked = o.fire_blocked;
        if blocked != was_blocked {
            self.emit(if blocked {
                ActionEventKind::WeaponObstructed
            } else {
                ActionEventKind::WeaponCleared
            });
        }
    }

    /// Read-only animation interface for the current tick.
    pub fn action_pose(&self) -> ActionPose {
        let p = &self.player;
        let mut contacts = ContactTargets::default();
        let mut phase = ActionPhase::Active;
        let (slot, elapsed) = if p.dead() {
            (None, 0.)
        } else if let Some(m) = p.mantle.filter(|m| m.from_hang) {
            contacts.left_owner = HandOwner::Ledge;
            contacts.right_owner = HandOwner::Ledge;
            (Some(ActionSlot::PullUp), m.elapsed)
        } else {
            match p.action {
                Action::Slide(s) => {
                    if s.phase == SlidePhase::Entry {
                        phase = ActionPhase::Entry;
                        (Some(ActionSlot::SlideEnter), s.elapsed)
                    } else {
                        let enter = self.timings.get(ActionSlot::SlideEnter).duration;
                        (Some(ActionSlot::SlideLoop), s.elapsed - enter)
                    }
                }
                Action::Dive(d) => match d.phase {
                    DivePhase::Launch => {
                        phase = ActionPhase::Entry;
                        (Some(ActionSlot::DiveLaunch), d.elapsed)
                    }
                    DivePhase::Air => (Some(ActionSlot::DiveAir), d.elapsed),
                    DivePhase::Impact => {
                        phase = ActionPhase::Exit;
                        (Some(ActionSlot::DiveImpact), d.elapsed)
                    }
                },
                Action::Hang(h) => {
                    contacts.left_hand = Some(h.hands[0]);
                    contacts.left_owner = HandOwner::Ledge;
                    contacts.body_facing = -h.normal;
                    let (slot, elapsed, right) = self.hang_right_hand(&h);
                    contacts.right_owner = right;
                    contacts.right_hand = (right == HandOwner::Ledge).then_some(h.hands[1]);
                    if slot == ActionSlot::LedgeCatch {
                        phase = ActionPhase::Entry;
                    }
                    (Some(slot), elapsed)
                }
                Action::None => {
                    if let Some(m) = p.mount {
                        contacts.body_facing = horizontal(m.yaw_center);
                        if m.weight < 1. {
                            phase = ActionPhase::Entry;
                            (Some(ActionSlot::MountEnter), m.elapsed)
                        } else {
                            (Some(ActionSlot::MountHold), m.elapsed)
                        }
                    } else if let Some(tac) = p.tac_sprint {
                        let enter = self.timings.get(ActionSlot::TacSprintEnter).duration;
                        if tac.elapsed < enter {
                            phase = ActionPhase::Entry;
                            (Some(ActionSlot::TacSprintEnter), tac.elapsed)
                        } else {
                            (Some(ActionSlot::TacSprintLoop), tac.elapsed - enter)
                        }
                    } else if let Some((slot, start)) = p.last_exit {
                        let elapsed = (self.time - start) as f32;
                        if elapsed < self.timings.get(slot).duration {
                            phase = if matches!(
                                slot,
                                ActionSlot::SlideInterrupt | ActionSlot::LedgeLost
                            ) {
                                ActionPhase::Interrupted
                            } else {
                                ActionPhase::Exit
                            };
                            (Some(slot), elapsed)
                        } else {
                            (None, 0.)
                        }
                    } else {
                        (None, 0.)
                    }
                }
            }
        };
        let (normalized, weight, placeholder) = match slot {
            Some(slot) => {
                let clip = self.timings.get(slot);
                let t = elapsed.max(0.) / clip.duration;
                let normalized = if slot.looping() { t.fract() } else { t.min(1.) };
                let weight = match phase {
                    ActionPhase::Exit | ActionPhase::Interrupted
                        if p.mantle.is_none() && matches!(p.action, Action::None) =>
                    {
                        1. - normalized
                    }
                    _ => p.mount.map_or(1., |m| m.weight.max(1e-3)),
                };
                (normalized, weight, clip.placeholder)
            }
            None => (0., 0., false),
        };
        ActionPose {
            slot,
            phase,
            normalized,
            weight,
            speed: p.speed(),
            contacts,
            placeholder,
        }
    }

    /// Hang slot plus right-hand ownership through the pistol grip transfer.
    fn hang_right_hand(&self, h: &HangState) -> (ActionSlot, f32, HandOwner) {
        let draw = self.timings.get(ActionSlot::PistolDraw);
        let stow = self.timings.get(ActionSlot::PistolStow);
        let e = h.pistol_elapsed;
        match h.pistol {
            PistolPhase::Holstered => {
                let slot = if h.phase == HangPhase::Catch {
                    ActionSlot::LedgeCatch
                } else {
                    ActionSlot::LedgeHold
                };
                (slot, h.elapsed, HandOwner::Ledge)
            }
            PistolPhase::Drawing => {
                let owner = if e < draw.event_seconds("release_grip") {
                    HandOwner::Ledge
                } else if e < draw.event_seconds("pistol_in_hand") {
                    HandOwner::Free
                } else {
                    HandOwner::Pistol
                };
                (ActionSlot::PistolDraw, e, owner)
            }
            PistolPhase::Ready => {
                let slot = if self.time - self.player.last_shot_at
                    < f64::from(self.timings.get(ActionSlot::PistolFire).duration)
                {
                    ActionSlot::PistolFire
                } else if self.player.ads > 0. {
                    ActionSlot::PistolAim
                } else {
                    ActionSlot::PistolReady
                };
                (slot, e, HandOwner::Pistol)
            }
            PistolPhase::Stowing => {
                let owner = if e < stow.event_seconds("pistol_holstered") {
                    HandOwner::Pistol
                } else {
                    HandOwner::Free
                };
                (ActionSlot::PistolStow, e, owner)
            }
        }
    }
}
