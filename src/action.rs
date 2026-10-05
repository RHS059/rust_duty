//! Traversal and weapon-action vocabulary shared by gameplay and presentation.
//!
//! Gameplay (`sim`) owns movement, collision and eligibility. Presentation reads
//! the state exposed here; it never moves the player or grants an action.
//! Action timing comes from clip durations and named normalized events, never
//! frame counts. Until a real clip is bound in `assets/animations.cfg`, every
//! slot uses a labeled placeholder timing (see `ClipTiming::placeholder`).
use macroquad::math::Vec3;

/// Every new animation slot. Names are the manifest keys: `action.<name>`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ActionSlot {
    TacSprintEnter,
    TacSprintLoop,
    TacSprintExit,
    SlideEnter,
    SlideLoop,
    SlideRecover,
    SlideInterrupt,
    DiveLaunch,
    DiveAir,
    DiveImpact,
    DiveRecover,
    MountEnter,
    MountHold,
    MountExit,
    LedgeCatch,
    LedgeHold,
    LedgeLost,
    PistolDraw,
    PistolReady,
    PistolAim,
    PistolFire,
    PistolStow,
    PullUp,
    HangDrop,
}
impl ActionSlot {
    pub const ALL: [ActionSlot; 24] = [
        Self::TacSprintEnter,
        Self::TacSprintLoop,
        Self::TacSprintExit,
        Self::SlideEnter,
        Self::SlideLoop,
        Self::SlideRecover,
        Self::SlideInterrupt,
        Self::DiveLaunch,
        Self::DiveAir,
        Self::DiveImpact,
        Self::DiveRecover,
        Self::MountEnter,
        Self::MountHold,
        Self::MountExit,
        Self::LedgeCatch,
        Self::LedgeHold,
        Self::LedgeLost,
        Self::PistolDraw,
        Self::PistolReady,
        Self::PistolAim,
        Self::PistolFire,
        Self::PistolStow,
        Self::PullUp,
        Self::HangDrop,
    ];
    pub fn name(self) -> &'static str {
        match self {
            Self::TacSprintEnter => "tac_sprint_enter",
            Self::TacSprintLoop => "tac_sprint_loop",
            Self::TacSprintExit => "tac_sprint_exit",
            Self::SlideEnter => "slide_enter",
            Self::SlideLoop => "slide_loop",
            Self::SlideRecover => "slide_recover",
            Self::SlideInterrupt => "slide_interrupt",
            Self::DiveLaunch => "dive_launch",
            Self::DiveAir => "dive_air",
            Self::DiveImpact => "dive_impact",
            Self::DiveRecover => "dive_recover",
            Self::MountEnter => "mount_enter",
            Self::MountHold => "mount_hold",
            Self::MountExit => "mount_exit",
            Self::LedgeCatch => "ledge_catch",
            Self::LedgeHold => "ledge_hold",
            Self::LedgeLost => "ledge_lost",
            Self::PistolDraw => "pistol_draw",
            Self::PistolReady => "pistol_ready",
            Self::PistolAim => "pistol_aim",
            Self::PistolFire => "pistol_fire",
            Self::PistolStow => "pistol_stow",
            Self::PullUp => "pull_up",
            Self::HangDrop => "hang_drop",
        }
    }
    pub fn looping(self) -> bool {
        matches!(
            self,
            Self::TacSprintLoop
                | Self::SlideLoop
                | Self::DiveAir
                | Self::MountHold
                | Self::LedgeHold
                | Self::PistolReady
        )
    }
}

/// Duration plus named events at normalized clip time (0..=1).
#[derive(Clone, Debug, PartialEq)]
pub struct ClipTiming {
    pub duration: f32,
    pub events: Vec<(String, f32)>,
    /// True until a real authored clip supplied the duration.
    pub placeholder: bool,
}
impl ClipTiming {
    fn placeholder(duration: f32, events: &[(&str, f32)]) -> Self {
        Self {
            duration,
            events: events.iter().map(|(n, t)| ((*n).into(), *t)).collect(),
            placeholder: true,
        }
    }
    /// Normalized time of a named event. Missing events fall back to the clip end
    /// so a renamed event can only delay, never skip, a gameplay gate.
    pub fn event(&self, name: &str) -> f32 {
        self.events
            .iter()
            .find(|(n, _)| n == name)
            .map_or(1., |(_, t)| *t)
    }
    /// Seconds from clip start to a named event.
    pub fn event_seconds(&self, name: &str) -> f32 {
        self.duration * self.event(name)
    }
}

/// Timing for every slot. Gameplay gates read these, so swapping in an authored
/// clip with a different duration retimes gameplay consistently.
#[derive(Clone, Debug, PartialEq)]
pub struct ActionTimings {
    clips: Vec<ClipTiming>,
}
impl Default for ActionTimings {
    fn default() -> Self {
        use ActionSlot::*;
        let clips = ActionSlot::ALL
            .iter()
            .map(|slot| match slot {
                TacSprintEnter => ClipTiming::placeholder(0.18, &[("speed_reached", 1.)]),
                TacSprintLoop => ClipTiming::placeholder(0.60, &[]),
                TacSprintExit => ClipTiming::placeholder(0.22, &[("weapon_ready", 0.8)]),
                SlideEnter => {
                    ClipTiming::placeholder(0.20, &[("capsule_low", 0.5), ("weapon_free", 1.)])
                }
                SlideLoop => ClipTiming::placeholder(0.50, &[]),
                SlideRecover => ClipTiming::placeholder(0.30, &[("weapon_ready", 0.6)]),
                SlideInterrupt => ClipTiming::placeholder(0.15, &[]),
                DiveLaunch => ClipTiming::placeholder(0.25, &[("steer_allowed", 0.4)]),
                DiveAir => ClipTiming::placeholder(0.50, &[]),
                DiveImpact => ClipTiming::placeholder(0.30, &[("impact", 0.)]),
                DiveRecover => {
                    ClipTiming::placeholder(0.45, &[("cancel_allowed", 0.4), ("weapon_ready", 0.7)])
                }
                MountEnter => ClipTiming::placeholder(0.15, &[("supported", 1.)]),
                MountHold => ClipTiming::placeholder(1.00, &[]),
                MountExit => ClipTiming::placeholder(0.15, &[]),
                LedgeCatch => ClipTiming::placeholder(0.25, &[("hands_planted", 0.4)]),
                LedgeHold => ClipTiming::placeholder(1.00, &[]),
                LedgeLost => ClipTiming::placeholder(0.20, &[]),
                PistolDraw => ClipTiming::placeholder(
                    0.55,
                    &[
                        ("release_grip", 0.15),
                        ("pistol_in_hand", 0.55),
                        ("ready", 1.),
                    ],
                ),
                PistolReady => ClipTiming::placeholder(1.00, &[]),
                PistolAim => ClipTiming::placeholder(0.20, &[]),
                PistolFire => ClipTiming::placeholder(0.12, &[]),
                PistolStow => {
                    ClipTiming::placeholder(0.50, &[("pistol_holstered", 0.6), ("regrip", 1.)])
                }
                PullUp => ClipTiming::placeholder(
                    1.00,
                    &[("rise_end", 0.55), ("over_lip", 0.90), ("complete", 1.)],
                ),
                HangDrop => ClipTiming::placeholder(0.20, &[("weapon_ready", 1.)]),
            })
            .collect();
        Self { clips }
    }
}
impl ActionTimings {
    pub fn get(&self, slot: ActionSlot) -> &ClipTiming {
        &self.clips[slot as usize]
    }
    /// Replace a placeholder with an authored clip's duration and events.
    /// Rejects nonpositive durations and events outside 0..=1.
    pub fn bind(
        &mut self,
        slot: ActionSlot,
        duration: f32,
        events: Vec<(String, f32)>,
    ) -> Result<(), String> {
        if !duration.is_finite() || duration <= 0. {
            return Err(format!("{} needs a positive duration", slot.name()));
        }
        if events
            .iter()
            .any(|(_, t)| !t.is_finite() || !(0. ..=1.).contains(t))
        {
            return Err(format!("{} events must be normalized 0..1", slot.name()));
        }
        self.clips[slot as usize] = ClipTiming {
            duration,
            events,
            placeholder: false,
        };
        Ok(())
    }
}

/// Lifecycle phase common to every feature.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActionPhase {
    Entry,
    Active,
    Exit,
    Interrupted,
}

/// Explicit weapon permissions for the current gameplay state.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WeaponPermissions {
    pub ads: bool,
    pub fire: bool,
    pub reload: bool,
    pub sprint: bool,
}
impl WeaponPermissions {
    pub const ALL: Self = Self {
        ads: true,
        fire: true,
        reload: true,
        sprint: true,
    };
    pub const NONE: Self = Self {
        ads: false,
        fire: false,
        reload: false,
        sprint: false,
    };
}

/// Why an attempted action did not start. Rejections never change movement.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Rejection {
    Ineligible,
    Blocked,
    /// Surface angle above the configured limit.
    Steep,
    PistolOut,
    NoSidearm,
}

/// Gameplay events for presentation, audio and tests. Drained by the caller.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ActionEventKind {
    TacSprintStarted,
    TacSprintEnded,
    SlideStarted,
    SlideRejected(Rejection),
    SlideRecovering,
    SlideEnded,
    SlideInterrupted,
    DiveLaunched,
    DiveRejected(Rejection),
    DiveImpact,
    DiveEnded,
    DiveInterrupted,
    MountStarted,
    MountEnded,
    MountRejected(Rejection),
    LedgeCaught,
    LedgeLost,
    HangDropped,
    PullUpStarted,
    PullUpRejected(Rejection),
    PullUpCompleted,
    PistolDrawStarted,
    PistolReady,
    PistolStowStarted,
    PistolHolstered,
    PistolInterrupted,
    SidearmRejected(Rejection),
    WeaponObstructed,
    WeaponCleared,
    Died,
    Respawned,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ActionEvent {
    pub time: f64,
    pub kind: ActionEventKind,
}

/// Which body part currently owns each hand. Presentation must attach the
/// hand to the named target and never leave it floating.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HandOwner {
    Rifle,
    Ledge,
    Pistol,
    Free,
}

/// Contact targets supplied to the animation layer in world space.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ContactTargets {
    pub left_hand: Option<Vec3>,
    pub right_hand: Option<Vec3>,
    pub left_owner: HandOwner,
    pub right_owner: HandOwner,
    /// Body facing for hang/mount alignment; zero when unconstrained.
    pub body_facing: Vec3,
}
impl Default for ContactTargets {
    fn default() -> Self {
        Self {
            left_hand: None,
            right_hand: None,
            left_owner: HandOwner::Rifle,
            right_owner: HandOwner::Rifle,
            body_facing: Vec3::ZERO,
        }
    }
}

/// One frame of the action animation interface.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ActionPose {
    pub slot: Option<ActionSlot>,
    pub phase: ActionPhase,
    /// Normalized time in the current slot's clip (wrapped for loops).
    pub normalized: f32,
    /// 0..1 layer weight; presentation blends the slot by this.
    pub weight: f32,
    /// Horizontal speed for movement-driven blends (m/s).
    pub speed: f32,
    pub contacts: ContactTargets,
    pub placeholder: bool,
}

/// Every configurable traversal/weapon value. Loaded from the settings file
/// alongside the base tuning; units are meters, seconds, degrees and m/s.
#[derive(Clone, Debug, PartialEq)]
pub struct ActionTuning {
    pub tac_sprint_speed: f32,
    pub tac_sprint_duration: f32,
    pub tac_sprint_recharge_delay: f32,
    pub tac_sprint_min_charge: f32,
    pub tac_sprint_double_tap: f32,
    pub slide_min_speed: f32,
    pub slide_boost: f32,
    pub slide_max_speed: f32,
    pub slide_friction: f32,
    pub slide_stop_speed: f32,
    pub slide_max_time: f32,
    pub slide_steer_rate: f32,
    pub slide_slope_scale: f32,
    pub slide_height: f32,
    pub slide_eye: f32,
    pub slide_cooldown: f32,
    pub dive_min_speed: f32,
    pub dive_forward_speed: f32,
    pub dive_up_speed: f32,
    pub dive_steer_rate: f32,
    pub dive_height: f32,
    pub dive_eye: f32,
    pub dive_min_headroom: f32,
    pub dive_min_forward_clearance: f32,
    pub dive_landing_speed_scale: f32,
    pub dive_ground_friction: f32,
    pub hang_hand_height: f32,
    pub hang_catch_below: f32,
    pub hang_catch_above: f32,
    pub hang_reach: f32,
    pub hang_max_rise_speed: f32,
    pub hang_hand_spacing: f32,
    pub hang_hand_inset: f32,
    pub hang_wall_gap: f32,
    pub hang_eye_height: f32,
    pub hang_min_ground_gap: f32,
    pub hang_yaw_limit: f32,
    pub hang_pitch_up: f32,
    pub hang_pitch_down: f32,
    pub hang_recatch_delay: f32,
    pub hang_drop_push: f32,
    pub mount_min_below_eye: f32,
    pub mount_max_below_eye: f32,
    pub mount_reach: f32,
    pub mount_max_angle: f32,
    pub mount_yaw_limit: f32,
    pub mount_pitch_up: f32,
    pub mount_pitch_down: f32,
    pub mount_recoil_scale: f32,
    pub mount_max_speed: f32,
    pub mount_auto_delay: f32,
    pub mount_clearance: f32,
    pub mount_move_deadzone: f32,
    pub weapon_length: f32,
    pub weapon_radius: f32,
    pub obstruct_max_retract: f32,
    pub obstruct_rate_in: f32,
    pub obstruct_rate_out: f32,
    pub obstruct_recover_delay: f32,
    pub obstruct_hysteresis: f32,
    pub obstruct_ads_block: f32,
    pub obstruct_fire_block: f32,
    pub obstruct_fire_release: f32,
    pub max_health: f32,
    pub respawn_delay: f32,
}
impl Default for ActionTuning {
    fn default() -> Self {
        Self {
            tac_sprint_speed: 8.6,
            tac_sprint_duration: 3.0,
            tac_sprint_recharge_delay: 1.0,
            tac_sprint_min_charge: 0.5,
            tac_sprint_double_tap: 0.30,
            slide_min_speed: 5.5,
            slide_boost: 1.5,
            slide_max_speed: 9.5,
            slide_friction: 6.0,
            slide_stop_speed: 2.5,
            slide_max_time: 1.1,
            slide_steer_rate: 70.,
            slide_slope_scale: 1.0,
            slide_height: 0.9,
            slide_eye: 0.70,
            slide_cooldown: 0.4,
            dive_min_speed: 5.0,
            dive_forward_speed: 7.0,
            dive_up_speed: 3.8,
            dive_steer_rate: 45.,
            dive_height: 0.9,
            dive_eye: 0.60,
            dive_min_headroom: 0.5,
            dive_min_forward_clearance: 1.2,
            dive_landing_speed_scale: 0.35,
            dive_ground_friction: 10.,
            hang_hand_height: 1.95,
            hang_catch_below: 0.25,
            hang_catch_above: 0.30,
            hang_reach: 0.35,
            hang_max_rise_speed: 2.0,
            hang_hand_spacing: 0.45,
            hang_hand_inset: 0.06,
            hang_wall_gap: 0.02,
            hang_eye_height: 1.70,
            hang_min_ground_gap: 0.45,
            hang_yaw_limit: 70.,
            hang_pitch_up: 60.,
            hang_pitch_down: 50.,
            hang_recatch_delay: 0.5,
            hang_drop_push: 0.6,
            mount_min_below_eye: 0.10,
            mount_max_below_eye: 0.55,
            mount_reach: 0.75,
            mount_max_angle: 15.,
            mount_yaw_limit: 35.,
            mount_pitch_up: 25.,
            mount_pitch_down: 30.,
            mount_recoil_scale: 0.45,
            mount_max_speed: 0.5,
            mount_auto_delay: 0.15,
            mount_clearance: 0.06,
            mount_move_deadzone: 0.2,
            weapon_length: 0.85,
            weapon_radius: 0.045,
            obstruct_max_retract: 0.40,
            obstruct_rate_in: 6.,
            obstruct_rate_out: 3.,
            obstruct_recover_delay: 0.12,
            obstruct_hysteresis: 0.05,
            obstruct_ads_block: 0.35,
            obstruct_fire_block: 0.85,
            obstruct_fire_release: 0.70,
            max_health: 100.,
            respawn_delay: 3.0,
        }
    }
}
impl ActionTuning {
    /// (key, value, min, max) for every field; used by settings load/save.
    pub fn fields_mut(&mut self) -> Vec<(&'static str, &mut f32, f32, f32)> {
        vec![
            ("tac_sprint_speed", &mut self.tac_sprint_speed, 1., 18.),
            (
                "tac_sprint_duration",
                &mut self.tac_sprint_duration,
                0.,
                20.,
            ),
            (
                "tac_sprint_recharge_delay",
                &mut self.tac_sprint_recharge_delay,
                0.,
                10.,
            ),
            (
                "tac_sprint_min_charge",
                &mut self.tac_sprint_min_charge,
                0.,
                5.,
            ),
            (
                "tac_sprint_double_tap",
                &mut self.tac_sprint_double_tap,
                0.05,
                1.,
            ),
            ("slide_min_speed", &mut self.slide_min_speed, 0., 18.),
            ("slide_boost", &mut self.slide_boost, 0., 6.),
            ("slide_max_speed", &mut self.slide_max_speed, 1., 20.),
            ("slide_friction", &mut self.slide_friction, 0.1, 40.),
            ("slide_stop_speed", &mut self.slide_stop_speed, 0.1, 10.),
            ("slide_max_time", &mut self.slide_max_time, 0.1, 5.),
            ("slide_steer_rate", &mut self.slide_steer_rate, 0., 360.),
            ("slide_slope_scale", &mut self.slide_slope_scale, 0., 2.),
            ("slide_height", &mut self.slide_height, 0.762, 1.27),
            ("slide_eye", &mut self.slide_eye, 0.3, 1.1),
            ("slide_cooldown", &mut self.slide_cooldown, 0., 5.),
            ("dive_min_speed", &mut self.dive_min_speed, 0., 18.),
            ("dive_forward_speed", &mut self.dive_forward_speed, 1., 15.),
            ("dive_up_speed", &mut self.dive_up_speed, 0., 8.),
            ("dive_steer_rate", &mut self.dive_steer_rate, 0., 360.),
            ("dive_height", &mut self.dive_height, 0.762, 1.27),
            ("dive_eye", &mut self.dive_eye, 0.25, 1.1),
            ("dive_min_headroom", &mut self.dive_min_headroom, 0., 2.),
            (
                "dive_min_forward_clearance",
                &mut self.dive_min_forward_clearance,
                0.,
                4.,
            ),
            (
                "dive_landing_speed_scale",
                &mut self.dive_landing_speed_scale,
                0.,
                1.,
            ),
            (
                "dive_ground_friction",
                &mut self.dive_ground_friction,
                0.1,
                40.,
            ),
            ("hang_hand_height", &mut self.hang_hand_height, 1.8, 2.4),
            ("hang_catch_below", &mut self.hang_catch_below, 0., 1.),
            ("hang_catch_above", &mut self.hang_catch_above, 0., 1.),
            ("hang_reach", &mut self.hang_reach, 0.05, 1.),
            (
                "hang_max_rise_speed",
                &mut self.hang_max_rise_speed,
                -5.,
                10.,
            ),
            ("hang_hand_spacing", &mut self.hang_hand_spacing, 0.1, 0.8),
            ("hang_hand_inset", &mut self.hang_hand_inset, 0.01, 0.3),
            ("hang_wall_gap", &mut self.hang_wall_gap, 0.001, 0.2),
            ("hang_eye_height", &mut self.hang_eye_height, 0.5, 1.77),
            ("hang_min_ground_gap", &mut self.hang_min_ground_gap, 0., 2.),
            ("hang_yaw_limit", &mut self.hang_yaw_limit, 0., 180.),
            ("hang_pitch_up", &mut self.hang_pitch_up, 0., 85.),
            ("hang_pitch_down", &mut self.hang_pitch_down, 0., 85.),
            ("hang_recatch_delay", &mut self.hang_recatch_delay, 0., 5.),
            ("hang_drop_push", &mut self.hang_drop_push, 0., 4.),
            ("mount_min_below_eye", &mut self.mount_min_below_eye, 0., 1.),
            (
                "mount_max_below_eye",
                &mut self.mount_max_below_eye,
                0.05,
                1.5,
            ),
            ("mount_reach", &mut self.mount_reach, 0.1, 2.),
            ("mount_max_angle", &mut self.mount_max_angle, 0., 45.),
            ("mount_yaw_limit", &mut self.mount_yaw_limit, 0., 90.),
            ("mount_pitch_up", &mut self.mount_pitch_up, 0., 85.),
            ("mount_pitch_down", &mut self.mount_pitch_down, 0., 85.),
            ("mount_recoil_scale", &mut self.mount_recoil_scale, 0., 1.),
            ("mount_max_speed", &mut self.mount_max_speed, 0., 5.),
            ("mount_auto_delay", &mut self.mount_auto_delay, 0., 2.),
            ("mount_clearance", &mut self.mount_clearance, 0.01, 0.5),
            ("mount_move_deadzone", &mut self.mount_move_deadzone, 0., 1.),
            ("weapon_length", &mut self.weapon_length, 0.3, 1.5),
            ("weapon_radius", &mut self.weapon_radius, 0., 0.2),
            (
                "obstruct_max_retract",
                &mut self.obstruct_max_retract,
                0.05,
                1.,
            ),
            ("obstruct_rate_in", &mut self.obstruct_rate_in, 0.5, 60.),
            ("obstruct_rate_out", &mut self.obstruct_rate_out, 0.5, 60.),
            (
                "obstruct_recover_delay",
                &mut self.obstruct_recover_delay,
                0.,
                1.,
            ),
            (
                "obstruct_hysteresis",
                &mut self.obstruct_hysteresis,
                0.,
                0.5,
            ),
            ("obstruct_ads_block", &mut self.obstruct_ads_block, 0., 1.),
            (
                "obstruct_fire_block",
                &mut self.obstruct_fire_block,
                0.05,
                1.,
            ),
            (
                "obstruct_fire_release",
                &mut self.obstruct_fire_release,
                0.,
                1.,
            ),
            ("max_health", &mut self.max_health, 1., 1000.),
            ("respawn_delay", &mut self.respawn_delay, 0., 30.),
        ]
    }
}

/// Optional sidearm interface. The default loadout has none, so a hanging
/// pistol draw is rejected safely until a sidearm is supplied.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SidearmSpec {
    pub magazine: u32,
    pub rpm: f32,
    pub body_damage: f32,
    pub head_damage: f32,
    pub recoil_scale: f32,
    pub hang_eligible: bool,
}
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Loadout {
    pub sidearm: Option<SidearmSpec>,
    pub sidearm_ammo: u32,
}

pub(crate) fn smoothstep(t: f32) -> f32 {
    let t = t.clamp(0., 1.);
    t * t * (3. - 2. * t)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_slot_has_timing_and_unique_name() {
        let timings = ActionTimings::default();
        let mut names: Vec<_> = ActionSlot::ALL.iter().map(|s| s.name()).collect();
        names.sort();
        names.dedup();
        assert_eq!(names.len(), ActionSlot::ALL.len());
        for slot in ActionSlot::ALL {
            let clip = timings.get(slot);
            assert!(clip.placeholder && clip.duration > 0., "{}", slot.name());
            assert!(clip.events.iter().all(|(_, t)| (0. ..=1.).contains(t)));
        }
    }
    #[test]
    fn binding_retimes_events_and_rejects_bad_data() {
        let mut timings = ActionTimings::default();
        timings
            .bind(ActionSlot::PistolDraw, 1.1, vec![("ready".into(), 0.5)])
            .unwrap();
        let clip = timings.get(ActionSlot::PistolDraw);
        assert!(!clip.placeholder);
        assert!((clip.event_seconds("ready") - 0.55).abs() < 1e-6);
        assert_eq!(clip.event("missing"), 1.);
        assert!(timings.bind(ActionSlot::PullUp, 0., vec![]).is_err());
        assert!(timings
            .bind(ActionSlot::PullUp, 1., vec![("x".into(), 1.5)])
            .is_err());
    }
}
