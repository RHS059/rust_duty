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
//! Compatibility: the one-argument sampler and input fields are unchanged.
//! The output now adds left_hand_blend; exhaustive output literals/patterns and
//! renderer cancellation blends must include it. The earlier credit-anchored
//! insertion and authored bolt-pull behavior are intentionally replaced. Insertion
//! follows visual windows; reload_credit_fraction does not drive the pose. Update
//! the companion contract tests with this file.

pub const ADS_SECONDS: f64 = 0.250;
pub const SPRINT_OUT_SECONDS: f64 = 0.300;
pub const TACTICAL_RELOAD_SECONDS: f64 = 2.029;
pub const EMPTY_RELOAD_SECONDS: f64 = 2.359;
pub const RIGHT_GRIP: [f32; 3] = [0.037, -0.095, 0.153];
pub const LEFT_GRIP: [f32; 3] = [-0.068, -0.112, -0.205];

const HAND_SUPPORT: [f32; 4] = [1.0, 0.0, 0.0, 0.0];
const HAND_MAGAZINE: [f32; 4] = [0.0, 1.0, 0.0, 0.0];
const HAND_RECEIVER: [f32; 4] = [0.0, 0.0, 1.0, 0.0];
const HAND_OPEN: [f32; 4] = [0.0, 0.0, 0.0, 1.0];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AnimationInput {
    /// None means inactive; Some values use the presentation duration, independently of gameplay ready/credit.
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
/// Tactical release windows stage the replacement actor; the initial support
/// release is keyed separately against observed source contact/open/drop poses.
/// Tactical ignores the receiver window; keeping it ordered simplifies
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
    /// newer-era clip windows. The tactical hand leaves support after 8.1081 s;
    /// its release keys interpolate within these earlier actor staging windows.
    pub fn for_reload(empty: bool) -> Self {
        if empty {
            Self {
                release_start: 0.14,
                release_end: 0.18,
                insert_start: 1.0484 / 2.2,
                insert_end: 1.2152 / 2.2,
                receiver_start: 1.6823 / 2.2,
                receiver_end: 1.7824 / 2.2,
            }
        } else {
            Self {
                // Preserve observed absolute windows while recovery lasts2.21s.
                release_start: 0.24 / 2.21,
                release_end: 0.50 / 2.21,
                insert_start: 0.9421 / 2.21,
                insert_end: 1.10 / 2.21,
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
    /// Rotation around the fitted magazine-hand seat pivot, in weapon-local YXZ.
    pub magazine_euler_yxz: [f32; 3],
    pub magazine_orientation_xyzw: Option<[f32; 4]>,
    /// Independent old/seated magazine actor; the primary transform follows the held replacement.
    pub seated_magazine_translation: [f32; 3],
    pub seated_magazine_euler_yxz: [f32; 3],
    pub seated_magazine_orientation_xyzw: Option<[f32; 4]>,
    /// [old/seated actor, held replacement actor]. Reuse the same original mesh.
    pub magazine_visibility: [bool; 2],
    pub right_grip: [f32; 3],
    pub left_grip: [f32; 3],
    /// Finger-pose weights [support, magazine, receiver, open], each in [0,1]
    /// with total one. These do not move the absolute wrist target. The caller
    /// must interpolate them during cancellation, alongside the grip target.
    /// Phase staging is authored; finger geometry awaits actual frame fitting.
    pub left_hand_blend: [f32; 4],
    /// Extra wrist orientation before the hand-mode basis; kept zero for held props.
    pub left_hand_euler_yxz: [f32; 3],
    /// Effective weapon-local wrist frame. Blended once, independently of finger modes.
    pub left_hand_orientation_xyzw: Option<[f32; 4]>,
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
            magazine_euler_yxz: [0.0; 3],
            magazine_orientation_xyzw: None,
            seated_magazine_translation: [0.; 3],
            seated_magazine_euler_yxz: [0.; 3],
            seated_magazine_orientation_xyzw: None,
            magazine_visibility: [true, false],
            right_grip: RIGHT_GRIP,
            left_grip: LEFT_GRIP,
            left_hand_blend: HAND_SUPPORT,
            left_hand_euler_yxz: [0.; 3],
            left_hand_orientation_xyzw: None,
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
    // Legacy standalone root output; the game adapter replaces it with the
    // fitted reference_motion track before composing live recoil.
    let envelope = smooth(t / 0.16) * (1.0 - smooth((t - 0.78) / 0.22));
    pose.weapon_translation = add(
        pose.weapon_translation,
        scale([0.100, 0.030, -0.150], envelope),
    );
    pose.weapon_euler_yxz = add(
        pose.weapon_euler_yxz,
        scale([0.600, 0.200, -0.200], envelope),
    );

    // Original retargeted key poses fit to visible source landmarks, with
    // occluded wrist positions constrained by the supplied rig and contact.
    let seat = [-0.046, -0.150, 0.010];
    let out = [-0.015, -0.140, 0.025];
    let pouch = [-0.2102921, 0.0567516, -0.001798799];
    let ready = [-0.010, -0.110, 0.010];
    let fetch_span = timing.insert_start - timing.release_end;
    let fetch_mid = timing.release_end + fetch_span * (0.2085 / 0.4421);
    let settle_end = timing.insert_end + (1.0 - timing.insert_end) * 0.27;
    let support_arrival = settle_end + (1.0 - settle_end) * 0.5785923;
    // Source onset 7.8 s, duration 2.21 s: contact through 8.1081, open and
    // detached left at 8.2082, then dropping below-left at 8.3083. Retiming
    // preserves their order without changing the later fitted fetch/return keys.
    let release_span = timing.release_end - timing.release_start;
    let support_departure = timing.release_start + release_span * (0.0681 / 0.26);
    let support_open = timing.release_start + release_span * (0.1682 / 0.26);
    let support_drop = timing.release_end + fetch_span * (0.0083 / 0.4421);
    let tactical_pickup = timing.release_end + fetch_span * (0.20 / 0.4421);
    let tactical = [
        Key::new(0.0, LEFT_GRIP, [0.0; 3], [0.0; 3], HAND_SUPPORT),
        Key::new(
            support_departure,
            LEFT_GRIP,
            [0.0; 3],
            [0.0; 3],
            HAND_SUPPORT,
        ),
        Key::new(
            support_open,
            [-0.2242266, -0.1193251, -0.0608502],
            [0.0; 3],
            [0.0; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([-0.60, 0.0, 0.80]),
        Key::new(
            support_drop,
            [-0.2535706, -0.2340475, -0.0312067],
            out,
            [0.0; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([-0.60, 0.0, 0.80]),
        // Replacement is first observed in the hand at 8.50 s. Reach the same
        // rigid wrist/prop frame before revealing it, then retain the later
        // fitted 8.5085 s key and every subsequent fitted pose unchanged.
        Key::new(
            tactical_pickup,
            add(seat, pouch),
            pouch,
            [0.0; 3],
            HAND_MAGAZINE,
        )
        .with_rotation([-0.9909131, -0.1274992, -1.198773]),
        Key::new(fetch_mid, add(seat, pouch), pouch, [0.0; 3], HAND_MAGAZINE)
            .with_rotation([-0.9909131, -0.1274992, -1.198773]),
        Key::new(
            timing.insert_start,
            add(seat, ready),
            ready,
            [0.0; 3],
            HAND_MAGAZINE,
        ),
        Key::new(timing.insert_end, seat, [0.0; 3], [0.0; 3], HAND_MAGAZINE),
        Key::new(settle_end, seat, [0.0; 3], [0.0; 3], HAND_MAGAZINE),
        Key::new(
            settle_end + (support_arrival - settle_end) * 0.6441522,
            [0.02250327, -0.3215141, -0.1958535],
            [0.; 3],
            [0.; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([1.44868, 0.1921157, 0.8075417]),
        Key::new(
            settle_end + (support_arrival - settle_end) * 0.8576609,
            [-0.05842122, -0.1850402, -0.2121435],
            [0.; 3],
            [0.; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([1.370396, 0.7523709, 0.5980197]),
        Key::new(support_arrival, LEFT_GRIP, [0.0; 3], [0.0; 3], HAND_SUPPORT),
        Key::new(1.0, LEFT_GRIP, [0.0; 3], [0.0; 3], HAND_SUPPORT),
    ];
    // Separate old and replacement actors preserve the observed visible swap.
    // Absolute grip targets and effective wrist frames are fitted key poses.
    let empty = [
        Key::new(0., LEFT_GRIP, [0.; 3], [0.; 3], HAND_SUPPORT),
        Key::new(
            timing.release_start,
            LEFT_GRIP,
            [0.; 3],
            [0.; 3],
            HAND_SUPPORT,
        ),
        Key::new(
            timing.release_end,
            [-0.07967767, -0.08977185, -0.1718748],
            [-0.3354909, -0.0564401, -0.2270969],
            [0.; 3],
            HAND_OPEN,
        )
        .with_rotation([0.8709892, -1.17017, -0.9843334])
        .with_hand_rotation([0.283653, 0.1228121, 0.5662988]),
        Key::new(
            timing.release_end + fetch_span * 0.30,
            add(seat, [-0.8, -0.8, 0.1]),
            [-0.8, -0.8, 0.1],
            [0.; 3],
            HAND_OPEN,
        ),
        Key::new(
            timing.release_end + fetch_span * 0.60,
            add(seat, [-0.08, -0.8, 0.1]),
            [-0.08, -0.8, 0.1],
            [0.; 3],
            HAND_MAGAZINE,
        ),
        Key::new(
            timing.release_end + fetch_span * 0.7953709,
            add(seat, [-0.1755163, -0.02868889, 0.02202]),
            [-0.1755163, -0.02868889, 0.02202],
            [0.; 3],
            HAND_MAGAZINE,
        )
        .with_rotation([-0.9563038, 0.4077038, -0.5455456]),
        Key::new(
            timing.release_end + fetch_span * 0.8465665,
            add(seat, [-0.1351976, -0.05454565, -0.0148891]),
            [-0.1351976, -0.05454565, -0.0148891],
            [0.; 3],
            HAND_MAGAZINE,
        )
        .with_rotation([-0.5853829, 0.1728094, -0.469801]),
        Key::new(
            timing.release_end + fetch_span * 0.9488044,
            add(seat, [-0.09893919, -0.06177868, -0.01328]),
            [-0.09893919, -0.06177868, -0.01328],
            [0.; 3],
            HAND_MAGAZINE,
        )
        .with_rotation([-0.3803292, 0.1589167, -0.1800977]),
        Key::new(
            timing.insert_start,
            add(seat, [-0.0953433, -0.05707473, -0.01230924]),
            [-0.0953433, -0.05707473, -0.01230924],
            [0.; 3],
            HAND_MAGAZINE,
        )
        .with_rotation([-0.3803292, 0.1589167, -0.1800977]),
        Key::new(timing.insert_end, seat, [0.; 3], [0.; 3], HAND_MAGAZINE),
        Key::new(
            timing.insert_end + (timing.receiver_start - timing.insert_end) * 0.4598587,
            seat,
            [0.; 3],
            [0.; 3],
            HAND_MAGAZINE,
        ),
        Key::new(
            timing.insert_end + (timing.receiver_start - timing.insert_end) * 0.642903,
            [-0.1982517, -0.2964604, -0.1023912],
            [0.; 3],
            [0.; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([-2.565155, 0.6045232, 2.641883]),
        Key::new(
            timing.insert_end + (timing.receiver_start - timing.insert_end) * 0.857204,
            [-0.2743893, -0.2751755, -0.1283193],
            [0.; 3],
            [0.; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([-2.669128, 0.894006, 2.10392]),
        Key::new(
            timing.receiver_start,
            add([-0.05519356, -0.1048773, -0.03914053], [-0.01, -0.005, 0.]),
            [0.; 3],
            [0.; 3],
            HAND_RECEIVER,
        )
        .with_hand_rotation([0.389694, -0.6009996, 0.1587382]),
        Key::new(
            timing.receiver_start + (timing.receiver_end - timing.receiver_start) * 0.3336663,
            [-0.05519356, -0.1048773, -0.03914053],
            [0.; 3],
            [0.; 3],
            HAND_RECEIVER,
        )
        .with_hand_rotation([0.389694, -0.6009996, 0.1587382]),
        Key::new(
            timing.receiver_end,
            add([-0.05519356, -0.1048773, -0.03914053], [-0.01, -0.005, 0.]),
            [0.; 3],
            [0.; 3],
            HAND_RECEIVER,
        )
        .with_hand_rotation([0.389694, -0.6009996, 0.1587382]),
        Key::new(
            timing.receiver_end + (1. - timing.receiver_end) * 0.07998084,
            [-0.1106553, -0.1424106, -0.1261478],
            [0.; 3],
            [0.; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([-1.699249, 0.4557036, 2.224915]),
        Key::new(
            timing.receiver_end + (1. - timing.receiver_end) * 0.3196839,
            [-0.1176575, -0.1762422, -0.1851158],
            [0.; 3],
            [0.; 3],
            HAND_OPEN,
        )
        .with_hand_rotation([-1.850241, 0.3645821, 2.301355]),
        Key::new(
            timing.receiver_end + (1. - timing.receiver_end) * 0.762931,
            LEFT_GRIP,
            [0.; 3],
            [0.; 3],
            HAND_SUPPORT,
        ),
        Key::new(1., LEFT_GRIP, [0.; 3], [0.; 3], HAND_SUPPORT),
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
            pose.left_hand_blend = blend_hand_modes(start.hand_blend, end.hand_blend, alpha);
            pose.left_hand_euler_yxz = lerp(start.hand_rotation, end.hand_rotation, alpha);
            pose.left_hand_orientation_xyzw = Some(slerp_orientation(
                key_hand_orientation(start),
                key_hand_orientation(end),
                alpha,
            ));
            pose.magazine_translation = lerp(start.magazine, end.magazine, alpha);
            pose.magazine_euler_yxz = lerp(start.magazine_rotation, end.magazine_rotation, alpha);
            pose.magazine_orientation_xyzw = Some(slerp_orientation(
                orientation_from_yxz(start.magazine_rotation),
                orientation_from_yxz(end.magazine_rotation),
                alpha,
            ));
            pose.bolt_translation = lerp(start.bolt, end.bolt, alpha);
            break;
        }
    }
    // Two actors are required by the visible tactical swap: the replacement
    // enters the hand before the old magazine leaves the weapon. The empty
    // reload likewise keeps its falling old prop separate from the pickup.
    if input.empty_reload {
        let swap = timing.release_end + fetch_span * 0.30;
        pose.magazine_visibility = [t < swap, t >= swap];
        if t < swap {
            pose.seated_magazine_translation = pose.magazine_translation;
            pose.seated_magazine_euler_yxz = pose.magazine_euler_yxz;
            pose.seated_magazine_orientation_xyzw = pose.magazine_orientation_xyzw;
        }
    } else {
        let drop_start = timing.release_end + fetch_span * (0.2419 / 0.4421);
        let drop_end = timing.release_end + fetch_span * (0.3586 / 0.4421);
        // Source timestamp subtraction and normalized phase rounding can differ
        // by a few f32 ulps; this tolerance is less than three microseconds.
        pose.magazine_visibility = [t < drop_end, t + 1e-6 >= tactical_pickup];
        let fall = ((t - drop_start) / (drop_end - drop_start)).clamp(0., 1.);
        pose.seated_magazine_translation = scale([-0.16, -0.58, 0.04], fall * fall);
        pose.seated_magazine_euler_yxz = scale([0.15, 0.10, -0.45], fall);
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
    magazine_rotation: [f32; 3],
    bolt: [f32; 3],
    hand_blend: [f32; 4],
    hand_rotation: [f32; 3],
}

impl Key {
    const fn with_hand_rotation(mut self, rotation: [f32; 3]) -> Self {
        self.hand_rotation = rotation;
        self
    }
    const fn with_rotation(mut self, rotation: [f32; 3]) -> Self {
        self.magazine_rotation = rotation;
        self
    }
    const fn new(
        at: f32,
        hand: [f32; 3],
        magazine: [f32; 3],
        bolt: [f32; 3],
        hand_blend: [f32; 4],
    ) -> Self {
        Self {
            at,
            hand,
            magazine,
            magazine_rotation: [0.; 3],
            bolt,
            hand_blend,
            hand_rotation: [0.; 3],
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

fn blend_hand_modes(a: [f32; 4], b: [f32; 4], t: f32) -> [f32; 4] {
    let mut weights: [f32; 4] = std::array::from_fn(|i| unit(a[i] + (b[i] - a[i]) * t));
    let total: f32 = weights.iter().sum();
    if total > 0.0 {
        for weight in &mut weights {
            *weight /= total;
        }
        weights
    } else {
        HAND_SUPPORT
    }
}

/// Canonical authored mode frames shared with the skin adapter. XYZW order.
pub const HAND_MODE_ORIENTATIONS: [[f32; 4]; 4] = [
    [0.70147073, 0.089098096, -0.089098096, 0.70147073],
    [
        std::f32::consts::FRAC_1_SQRT_2,
        0.,
        -std::f32::consts::FRAC_1_SQRT_2,
        0.,
    ],
    [0.5, 0.5, -0.5, -0.5],
    [0.9054489, -0.05399779, -0.3869094, 0.1659749],
];
fn normalize_orientation(q: [f32; 4]) -> [f32; 4] {
    let n = q.iter().map(|v| v * v).sum::<f32>().sqrt();
    if !n.is_finite() || n < 1e-8 {
        return [0., 0., 0., 1.];
    }
    q.map(|v| v / n)
}
fn orientation_product(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    [
        a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
        a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
        a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
        a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
    ]
}
fn orientation_from_yxz(r: [f32; 3]) -> [f32; 4] {
    let (sy, cy) = (r[0] * 0.5).sin_cos();
    let (sx, cx) = (r[1] * 0.5).sin_cos();
    let (sz, cz) = (r[2] * 0.5).sin_cos();
    normalize_orientation(orientation_product(
        orientation_product([0., sy, 0., cy], [sx, 0., 0., cx]),
        [0., 0., sz, cz],
    ))
}
pub fn slerp_orientation(a: [f32; 4], b: [f32; 4], t: f32) -> [f32; 4] {
    let a = normalize_orientation(a);
    let mut b = normalize_orientation(b);
    let t = unit(t);
    let mut dot = (0..4).map(|i| a[i] * b[i]).sum::<f32>();
    if dot < 0. {
        b = b.map(|v| -v);
        dot = -dot;
    }
    if dot > 0.9995 {
        return normalize_orientation(std::array::from_fn(|i| a[i] + (b[i] - a[i]) * t));
    }
    let angle = dot.clamp(-1., 1.).acos();
    let divisor = angle.sin();
    normalize_orientation(std::array::from_fn(|i| {
        (a[i] * ((1. - t) * angle).sin() + b[i] * (t * angle).sin()) / divisor
    }))
}
pub fn effective_hand_orientation(p: &WeaponAnimationPose) -> [f32; 4] {
    if let Some(q) = p.left_hand_orientation_xyzw {
        return normalize_orientation(q);
    }
    let weights = blend_hand_modes(p.left_hand_blend, p.left_hand_blend, 0.);
    let reference = HAND_MODE_ORIENTATIONS[0];
    let mut base = [0.; 4];
    for (q, w) in HAND_MODE_ORIENTATIONS.into_iter().zip(weights) {
        let sign = if (0..4).map(|i| reference[i] * q[i]).sum::<f32>() < 0. {
            -1.
        } else {
            1.
        };
        for i in 0..4 {
            base[i] += q[i] * w * sign;
        }
    }
    let mag = slerp_orientation(
        [0., 0., 0., 1.],
        effective_magazine_orientation(p),
        weights[1],
    );
    normalize_orientation(orientation_product(
        orientation_product(orientation_from_yxz(p.left_hand_euler_yxz), mag),
        normalize_orientation(base),
    ))
}
fn key_hand_orientation(key: Key) -> [f32; 4] {
    effective_hand_orientation(&WeaponAnimationPose {
        left_hand_blend: key.hand_blend,
        left_hand_euler_yxz: key.hand_rotation,
        magazine_euler_yxz: key.magazine_rotation,
        ..Default::default()
    })
}

pub fn effective_magazine_orientation(p: &WeaponAnimationPose) -> [f32; 4] {
    p.magazine_orientation_xyzw
        .map(normalize_orientation)
        .unwrap_or_else(|| orientation_from_yxz(p.magazine_euler_yxz))
}
