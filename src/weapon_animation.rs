//! Original procedural viewmodel animation, with no renderer dependencies.
//!
//! Metres, weapon-local +X right, +Y up, barrel along -Z. Root outputs are
//! ADDITIVE AFTER existing hip/ADS placement; this module never aligns sights.
//! Euler output is [yaw about Y, pitch about X, roll about Z], in radians,
//! composed with the renderer's YXZ convention. Hand targets are ABSOLUTE local
//! points and must follow the SAME animated weapon root. Other translations
//! are local deltas from the corresponding asset part's bind pose.
//!
//! The caller supplies authoritative simulation progress. Sampling is pure,
//! deterministic and independent of render cadence or evaluation order. It
//! never transfers ammo, decides firing gates, or mutates gameplay state.
//! Remove reload_progress on cancellation; any cancellation crossfade belongs
//! to the caller. Recoil is cosmetic only: never add this to the shot ray.
//!
//! Durations below are published M4A1 candidate values, not measured retail
//! animation data. Spatial trajectories remain original procedural placeholders.
//! Visual default windows use SECONDHAND observations supplied by integrator
//! Aella from a newer-era BETA M4 clip (~59.94 fps), not original 2009 footage.
//! This module's author did not inspect those frames. No parity is claimed.
//! Tactical: ~7.8-9.8 s overall, insertion ~8.7-8.9 s, no bolt gesture reported.
//! Empty: ~14.0-16.2 s overall, left discard ~14.3-14.4 s, insertion ~15.0-15.3 s,
//! receiver-area gesture ~15.5-15.7 s. Windows are normalized to each observed
//! total; they do not replace the caller's gameplay duration or firing gates.
//! HUD observations are NOT used to infer ammo capacity or ammo-credit timing.
//! Receiver hand movement does not establish visible bolt travel, so the default
//! bolt delta is zero. The single-magazine contract approximates old/new mags by
//! routing one mesh leftward then below view; it cannot model separate magazines
//! or magazine rotation. Left-hand spatial paths await direct frame comparison.
//!
//! Compatibility: input/output fields and the one-argument sampler are unchanged,
//! but the earlier credit-anchored insertion and authored bolt-pull behavior are
//! intentionally replaced. Insertion follows visual windows; reload_credit_fraction
//! does not drive the pose. Update the companion contract tests with this file.

pub const ADS_SECONDS: f64 = 0.250;
pub const SPRINT_OUT_SECONDS: f64 = 0.300;
pub const TACTICAL_RELOAD_SECONDS: f64 = 2.029;
pub const EMPTY_RELOAD_SECONDS: f64 = 2.359;
pub const RIGHT_GRIP: [f32; 3] = [0.025, -0.115, 0.035];
pub const LEFT_GRIP: [f32; 3] = [-0.025, -0.120, -0.150];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AnimationInput {
    /// None means inactive; Some values are normalized by gameplay duration.
    pub reload_progress: Option<f32>,
    /// Retained for source compatibility as authoritative gameplay metadata.
    /// Intentionally NOT used to position any mesh. Visual timing is separate
    /// in ReloadVisualTiming, including for empty reloads. Never credit ammo
    /// from an animation output. The empty-credit assumption remains caller-owned.
    pub reload_credit_fraction: f32,
    pub empty_reload: bool,
    /// Existing gameplay ADS fraction. Only attenuates cosmetic recoil here.
    pub ads: f32,
    /// Existing visual recoil envelope, normalized to [0, 1].
    pub recoil: f32,
    /// Visual lowering amount, 0 ready and 1 sprint pose. Not a firing gate.
    pub sprint: f32,
}

impl Default for AnimationInput {
    fn default() -> Self {
        Self {
            reload_progress: None,
            reload_credit_fraction: (1.100 / TACTICAL_RELOAD_SECONDS) as f32,
            empty_reload: false,
            ads: 0.0,
            recoil: 0.0,
            sprint: 0.0,
        }
    }
}

/// Normalized VISUAL windows only. All six fields must be finite and strictly
/// ordered within (0, 1), or the whole profile falls back to its per-kind default.
/// Tactical release is an authored placeholder because no release interval was
/// supplied. Tactical ignores the receiver window; keeping it ordered simplifies
/// validation and lets the same public profile work with either reload kind.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ReloadVisualTiming {
    pub release_start: f32,
    pub release_end: f32,
    pub insert_start: f32,
    pub insert_end: f32,
    pub receiver_start: f32,
    pub receiver_end: f32,
}

impl ReloadVisualTiming {
    /// Default authored staging, approximately normalized from the observed
    /// newer-era clip windows. Tactical release has no observed timing yet.
    pub fn for_reload(empty: bool) -> Self {
        if empty {
            Self {
                release_start: 0.14,
                release_end: 0.18,
                insert_start: 0.455,
                insert_end: 0.591,
                receiver_start: 0.682,
                receiver_end: 0.773,
            }
        } else {
            Self {
                release_start: 0.12,
                release_end: 0.25,
                insert_start: 0.45,
                insert_end: 0.55,
                receiver_start: 0.682,
                receiver_end: 0.773,
            }
        }
    }

    fn valid(self) -> bool {
        let points = [
            0.0,
            self.release_start,
            self.release_end,
            self.insert_start,
            self.insert_end,
            self.receiver_start,
            self.receiver_end,
            1.0,
        ];
        points
            .windows(2)
            .all(|pair| pair[0].is_finite() && pair[0] < pair[1])
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct WeaponAnimationPose {
    pub weapon_translation: [f32; 3],
    /// [yaw Y, pitch X, roll Z], radians. No second hip/ADS positioning.
    pub weapon_euler_yxz: [f32; 3],
    pub magazine_translation: [f32; 3],
    pub right_grip: [f32; 3],
    pub left_grip: [f32; 3],
    pub bolt_translation: [f32; 3],
    /// 0 released, 1 fully pulled; visual only, derived from accepted recoil.
    pub trigger_pull: f32,
}

impl Default for WeaponAnimationPose {
    fn default() -> Self {
        Self {
            weapon_translation: [0.0; 3],
            weapon_euler_yxz: [0.0; 3],
            magazine_translation: [0.0; 3],
            right_grip: RIGHT_GRIP,
            left_grip: LEFT_GRIP,
            bolt_translation: [0.0; 3],
            trigger_pull: 0.0,
        }
    }
}

/// Renderer contract: absolute hand targets, otherwise additive local offsets.
/// Fractions are clamped; NaN means zero. No clocks, allocation, RNG, or assets.
/// Completed/future-start reload poses are idle, allowing endpoint-safe removal.
pub fn sample_weapon_animation(input: AnimationInput) -> WeaponAnimationPose {
    sample_weapon_animation_with_timing(input, ReloadVisualTiming::for_reload(input.empty_reload))
}

/// Optional visual-only override. Changing these windows never changes ammo or
/// duration. The original one-argument sampler remains source-compatible.
/// Only hand/magazine phases are retimed; the authored root-lowering envelope
/// is independent of these phase timings. Extreme profiles need renderer review.
pub fn sample_weapon_animation_with_timing(
    input: AnimationInput,
    timing: ReloadVisualTiming,
) -> WeaponAnimationPose {
    let recoil = unit(input.recoil) * (1.0 - 0.35 * unit(input.ads));
    let sprint = unit(input.sprint);
    let mut pose = WeaponAnimationPose {
        weapon_translation: [0.0, -0.090 * sprint, 0.045 * recoil + 0.040 * sprint],
        weapon_euler_yxz: [
            -0.100 * sprint,
            0.080 * recoil + 0.240 * sprint,
            -0.300 * sprint,
        ],
        trigger_pull: unit(input.recoil),
        ..WeaponAnimationPose::default()
    };
    let Some(t) = input.reload_progress.map(unit) else {
        return pose;
    };
    if t <= 0.0 || t >= 1.0 {
        return pose;
    }
    let timing = if timing.valid() {
        timing
    } else {
        ReloadVisualTiming::for_reload(input.empty_reload)
    };
    // Render-checked authored lift/away motion keeps insertion hands visible.
    let envelope = smooth(t / 0.16) * (1.0 - smooth((t - 0.78) / 0.22));
    pose.weapon_translation = add(
        pose.weapon_translation,
        scale([0.100, 0.030, -0.150], envelope),
    );
    pose.weapon_euler_yxz = add(
        pose.weapon_euler_yxz,
        scale([0.600, 0.200, -0.200], envelope),
    );

    // Spatial keys are original approximations. Only the labeled windows are
    // informed by the integrator's clip observations, not personally measured.
    let seat = [-0.035, -0.175, 0.025];
    let out = [-0.015, -0.140, 0.025];
    let pouch = [-0.160, -0.230, 0.130];
    let ready = [-0.010, -0.110, 0.010];
    let fetch_span = timing.insert_start - timing.release_end;
    let fetch_mid = timing.release_end + fetch_span * 0.50;
    let settle_end = timing.insert_end + (1.0 - timing.insert_end) * 0.12;
    let receiver = [-0.055, -0.025, 0.015];
    let receiver_mid = timing.receiver_start + (timing.receiver_end - timing.receiver_start) * 0.50;
    let tactical = [
        Key::new(0.0, LEFT_GRIP, [0.0; 3], [0.0; 3]),
        Key::new(timing.release_start, seat, [0.0; 3], [0.0; 3]),
        Key::new(timing.release_end, add(seat, out), out, [0.0; 3]),
        Key::new(fetch_mid, add(seat, pouch), pouch, [0.0; 3]),
        Key::new(timing.insert_start, add(seat, ready), ready, [0.0; 3]),
        Key::new(timing.insert_end, seat, [0.0; 3], [0.0; 3]),
        Key::new(settle_end, seat, [0.0; 3], [0.0; 3]),
        Key::new(1.0, LEFT_GRIP, [0.0; 3], [0.0; 3]),
    ];
    // One mesh stands in for discarded and replacement magazines. Travel from
    // far left to the replacement approach is routed below the expected view;
    // validate visibility with the actual FOV/model rather than assuming it.
    let empty = [
        Key::new(0.0, LEFT_GRIP, [0.0; 3], [0.0; 3]),
        Key::new(timing.release_start, seat, [0.0; 3], [0.0; 3]),
        Key::new(
            timing.release_end,
            add(seat, [-0.080, -0.020, -0.010]),
            [-0.600, -0.180, 0.020],
            [0.0; 3],
        ),
        Key::new(
            timing.release_end + fetch_span * 0.30,
            add(seat, [-0.130, -0.140, 0.120]),
            [-0.800, -0.800, 0.100],
            [0.0; 3],
        ),
        Key::new(
            timing.release_end + fetch_span * 0.60,
            add(seat, [-0.080, -0.250, 0.100]),
            [-0.080, -0.800, 0.100],
            [0.0; 3],
        ),
        Key::new(timing.insert_start, add(seat, ready), ready, [0.0; 3]),
        Key::new(timing.insert_end, seat, [0.0; 3], [0.0; 3]),
        Key::new(timing.receiver_start, receiver, [0.0; 3], [0.0; 3]),
        Key::new(
            receiver_mid,
            add(receiver, [0.020, -0.010, 0.0]),
            [0.0; 3],
            [0.0; 3],
        ),
        Key::new(timing.receiver_end, receiver, [0.0; 3], [0.0; 3]),
        Key::new(1.0, LEFT_GRIP, [0.0; 3], [0.0; 3]),
    ];
    let keys: &[Key] = if input.empty_reload {
        &empty
    } else {
        &tactical
    };
    for pair in keys.windows(2) {
        let (start, end) = (pair[0], pair[1]);
        if t <= end.at {
            let alpha = smooth((t - start.at) / (end.at - start.at));
            pose.left_grip = lerp(start.hand, end.hand, alpha);
            pose.magazine_translation = lerp(start.magazine, end.magazine, alpha);
            pose.bolt_translation = lerp(start.bolt, end.bolt, alpha);
            break;
        }
    }
    pose
}

/// Optional adapter for renderers given timestamps instead of normalized state.
/// None for future starts, non-finite times, or a non-positive/non-finite
/// duration; otherwise [0, 1]. The caller still owns state and cancellation.
pub fn reload_progress_at(
    now_seconds: f64,
    started_at_seconds: f64,
    duration_seconds: f64,
) -> Option<f32> {
    if !duration_seconds.is_finite() || duration_seconds <= 0.0 {
        return None;
    }
    elapsed(now_seconds, started_at_seconds)
        .map(|elapsed| (elapsed / duration_seconds).min(1.0) as f32)
}

/// Constant-rate timestamp blend; full 0 -> 1 takes full_duration_seconds.
/// Reversal preserves position: capture the sampled fraction as the new `from`
/// and replace the timestamp once when the target changes, not every frame.
/// Invalid times/future starts return `from`. Invalid duration snaps to `to`.
pub fn sample_transition(
    now_seconds: f64,
    started_at_seconds: f64,
    from: f32,
    to: f32,
    full_duration_seconds: f64,
) -> f32 {
    let from = unit(from);
    let to = unit(to);
    let Some(elapsed) = elapsed(now_seconds, started_at_seconds) else {
        return from;
    };
    if !full_duration_seconds.is_finite() || full_duration_seconds <= 0.0 {
        return to;
    }
    let distance = (to - from).abs();
    let travel = (elapsed / full_duration_seconds).min(f64::from(distance)) as f32;
    from + (to - from).signum() * travel
}

#[derive(Clone, Copy)]
struct Key {
    at: f32,
    hand: [f32; 3],
    magazine: [f32; 3],
    bolt: [f32; 3],
}

impl Key {
    const fn new(at: f32, hand: [f32; 3], magazine: [f32; 3], bolt: [f32; 3]) -> Self {
        Self {
            at,
            hand,
            magazine,
            bolt,
        }
    }
}

fn elapsed(now: f64, start: f64) -> Option<f64> {
    if !now.is_finite() || !start.is_finite() || now < start {
        None
    } else {
        Some(now - start)
    }
}

fn unit(value: f32) -> f32 {
    if value.is_nan() {
        0.0
    } else {
        value.clamp(0.0, 1.0)
    }
}

fn smooth(value: f32) -> f32 {
    let t = unit(value);
    t * t * (3.0 - 2.0 * t)
}

fn scale(value: [f32; 3], amount: f32) -> [f32; 3] {
    [value[0] * amount, value[1] * amount, value[2] * amount]
}

fn add(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

fn lerp(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    ]
}
