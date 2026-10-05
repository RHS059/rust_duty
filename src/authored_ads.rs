//! Native, reversible authored ADS playback driven by committed simulation state.
//!
//! No IK, camera offsets, normalized gameplay-phase posing, or synthesized ADS
//! motion. Reversal retraces the currently visible source transition at 1x time.
use crate::{
    animation_manifest::AdsReference,
    authored_locomotion_adapter::PoseBindings,
    sim::Simulation,
    viewmodel_animation::{AnimationError, AnimationSet, Result, ViewmodelPose},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AdsSlot {
    Entry,
    Hold,
    Exit,
}
impl AdsSlot {
    pub fn route(self) -> &'static str {
        match self {
            Self::Entry => "ads.entry",
            Self::Hold => "ads.hold",
            Self::Exit => "ads.exit",
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct AdsSample {
    pub slot: AdsSlot,
    pub seconds: f64,
    /// -1 retraces the current clip; +1 advances its authored timeline.
    pub direction: i8,
}

/// One contiguous cubic smoothstep (constant for hold), in committed tick time.
#[derive(Clone, Copy, Debug)]
struct AimSegment {
    start_seconds: f64,
    duration_seconds: f64,
    from: f64,
    to: f64,
}
impl AimSegment {
    fn exponentially_weighted_integral(self, response_seconds: f64) -> f64 {
        let u = self.from;
        let delta = self.to - u;
        // Smoothstep(u + delta*x), with x in [0, 1]. This also handles
        // reversal and hold without changing source samples or playback state.
        let coefficients = [
            u * u * (3. - 2. * u),
            6. * u * (1. - u) * delta,
            3. * (1. - 2. * u) * delta * delta,
            -2. * delta * delta * delta,
        ];
        let scale = self.duration_seconds / response_seconds;
        let mut moments = [0.; 4];
        if scale < 2. {
            // Integral x^n*exp(-scale*x) dx. At scale < 2, the omitted
            // exponential series tail after 32 terms is < 2^32/32! < 2e-26.
            // Unlike the recurrence, this has no small-scale cancellation.
            let mut term = 1.;
            for power in 0..32 {
                for (degree, moment) in moments.iter_mut().enumerate() {
                    *moment += term / (degree + power + 1) as f64;
                }
                term *= -scale / (power + 1) as f64;
            }
        } else {
            let decay = (-scale).exp();
            moments[0] = -(-scale).exp_m1() / scale;
            for degree in 1..4 {
                moments[degree] = (degree as f64 * moments[degree - 1] - decay) / scale;
            }
        }
        self.duration_seconds
            * (-self.start_seconds / response_seconds).exp()
            * coefficients
                .into_iter()
                .zip(moments)
                .map(|(coefficient, moment)| coefficient * moment)
                .sum::<f64>()
    }
}

#[derive(Clone, Debug)]
pub struct AuthoredAds {
    clips: AdsReference,
    durations: [f64; 3],
    sample: Option<AdsSample>,
    last_time: f64,
    transition_rates: [f64; 3],
    last_aim_integral: f64,
    // A committed tick traverses at most one transition, then a static hold.
    last_aim_segments: [Option<AimSegment>; 2],
}
impl AuthoredAds {
    /// Require complete canonical companion bindings and connected source poses.
    /// Static hold is intentional: release at any point must join exit(0) exactly.
    pub fn new(
        animation: &AnimationSet,
        locomotion: &AnimationSet,
        ready_clip: &str,
        clips: AdsReference,
    ) -> Result<Self> {
        if !PoseBindings::from_animation(locomotion).matches(animation) {
            return Err(AnimationError(
                "ADS requires canonical locomotion companion bindings".into(),
            ));
        }
        let mut durations = [0.; 3];
        for (index, name) in [&clips.entry_clip, &clips.hold_clip, &clips.exit_clip]
            .into_iter()
            .enumerate()
        {
            let clip = animation
                .clips()
                .iter()
                .find(|clip| &clip.name == name)
                .ok_or_else(|| AnimationError(format!("missing required ADS clip: {name}")))?;
            if clip.duration() <= 0. || clip.looping != (index == 1) {
                return Err(AnimationError(format!(
                    "ADS clip {name} needs positive native duration and {} playback",
                    if index == 1 { "looping" } else { "non-looping" }
                )));
            }
            durations[index] = f64::from(clip.duration());
        }
        let ready = locomotion.sample_clamped(ready_clip, 0.)?;
        let entry_start = animation.sample_clamped(&clips.entry_clip, 0.)?;
        let entry_end = animation.sample_clamped(&clips.entry_clip, durations[0] as f32)?;
        let hold = animation.sample_clamped(&clips.hold_clip, 0.)?;
        let exit_start = animation.sample_clamped(&clips.exit_clip, 0.)?;
        let exit_end = animation.sample_clamped(&clips.exit_clip, durations[2] as f32)?;
        for (name, left, right) in [
            ("ready -> entry", &ready, &entry_start),
            ("entry -> hold", &entry_end, &hold),
            ("hold -> exit", &hold, &exit_start),
            ("exit -> ready", &exit_end, &ready),
        ] {
            if !same_pose(left, right) {
                return Err(AnimationError(format!(
                    "disconnected authored ADS seam: {name}"
                )));
            }
        }
        let hold_clip = animation
            .clips()
            .iter()
            .find(|clip| clip.name == clips.hold_clip)
            .unwrap();
        for &time in hold_clip.times() {
            if !same_pose(&hold, &animation.sample_clamped(&clips.hold_clip, time)?) {
                return Err(AnimationError(
                    "ADS hold must preserve the authored hold/exit connection at every frame"
                        .into(),
                ));
            }
        }
        Ok(Self {
            clips,
            durations,
            sample: None,
            last_time: 0.,
            transition_rates: [1.; 3],
            last_aim_integral: 0.,
            last_aim_segments: [None; 2],
        })
    }
    pub fn reset(&mut self, time: f64) {
        self.sample = None;
        self.last_time = time;
        self.last_aim_integral = 0.;
        self.last_aim_segments = [None; 2];
    }
    /// Authored WIP visual retiming; gameplay timers and source sample units stay unchanged.
    pub fn with_visual_transition_seconds(mut self, seconds: f64) -> Result<Self> {
        if !seconds.is_finite() || seconds <= 0. || seconds > 2. || self.last_time != 0. {
            return Err(AnimationError(
                "invalid ADS visual transition duration".into(),
            ));
        }
        self.transition_rates = [self.durations[0] / seconds, 1., self.durations[2] / seconds];
        Ok(self)
    }
    pub fn last_aim_integral(&self) -> f64 {
        self.last_aim_integral
    }
    /// Integrate aim(t) * (target + (start - target) * exp(-t / response))
    /// over the most recent committed tick, without advancing any playback state.
    /// Weights are bounded to [0, 1] (NaN becomes zero). A nonpositive or NaN
    /// response snaps to target; positive infinity preserves the starting weight.
    /// Cubic exponential moments are analytic, apart from the bounded series
    /// documented above; remaining error is ordinary f64 roundoff.
    pub fn last_aim_weighted_integral(
        &self,
        start_weight: f64,
        target_weight: f64,
        response_seconds: f64,
    ) -> f64 {
        let bounded_weight = |value: f64| {
            if value.is_nan() {
                0.
            } else {
                value.clamp(0., 1.)
            }
        };
        let start_weight = bounded_weight(start_weight);
        let target_weight = bounded_weight(target_weight);
        if response_seconds.is_infinite() && response_seconds.is_sign_positive() {
            return start_weight * self.last_aim_integral;
        }
        if response_seconds <= 0. || response_seconds.is_nan() || start_weight == target_weight {
            return target_weight * self.last_aim_integral;
        }
        let exponential_integral = self
            .last_aim_segments
            .iter()
            .flatten()
            .map(|segment| segment.exponentially_weighted_integral(response_seconds))
            .sum::<f64>();
        (target_weight * self.last_aim_integral
            + (start_weight - target_weight) * exponential_integral)
            .clamp(0., self.last_aim_integral.max(0.))
    }
    fn aim_antiderivative(&self, slot: AdsSlot, seconds: f64) -> f64 {
        let duration = self.duration(slot);
        let u = (seconds / duration).clamp(0., 1.);
        let integral = duration * (u.powi(3) - 0.5 * u.powi(4));
        match slot {
            AdsSlot::Entry => integral,
            AdsSlot::Exit => seconds - integral,
            AdsSlot::Hold => seconds,
        }
    }
    pub fn sample(&self) -> Option<AdsSample> {
        self.sample
    }
    /// Native transition progress, continuous through both reversal directions.
    pub fn aim_amount(&self) -> f32 {
        self.sample.map_or(0., |sample| {
            let t = match sample.slot {
                AdsSlot::Entry => sample.seconds / self.duration(AdsSlot::Entry),
                AdsSlot::Hold => 1.,
                AdsSlot::Exit => 1. - sample.seconds / self.duration(AdsSlot::Exit),
            }
            .clamp(0., 1.);
            (t * t * (3. - 2. * t)) as f32
        })
    }
    pub fn duration(&self, slot: AdsSlot) -> f64 {
        self.durations[match slot {
            AdsSlot::Entry => 0,
            AdsSlot::Hold => 1,
            AdsSlot::Exit => 2,
        }]
    }
    pub fn clip(&self, slot: AdsSlot) -> &str {
        match slot {
            AdsSlot::Entry => &self.clips.entry_clip,
            AdsSlot::Hold => &self.clips.hold_clip,
            AdsSlot::Exit => &self.clips.exit_clip,
        }
    }
    pub fn pose(&self, animation: &AnimationSet) -> Result<Option<ViewmodelPose>> {
        self.sample
            .map(|sample| {
                if sample.slot == AdsSlot::Hold {
                    animation.sample(self.clip(sample.slot), sample.seconds as f32)
                } else {
                    animation.sample_clamped(self.clip(sample.slot), sample.seconds as f32)
                }
            })
            .transpose()
    }
    /// Observe exactly once after each fixed Simulation::update. Reload cuts to
    /// its independently validated rig; sprint/mantle return along authored ADS.
    /// A sprint transition must reach ready before a new ADS entry can acquire it.
    pub fn committed_step(
        &mut self,
        start: f64,
        simulation: &Simulation,
        reload_visual_active: bool,
        locomotion_ready: bool,
    ) -> Result<()> {
        let end = simulation.time;
        if !start.is_finite() || !end.is_finite() || start != self.last_time || end < start {
            return Err(AnimationError(
                "ADS observer needs contiguous committed ticks; reset explicitly".into(),
            ));
        }
        self.last_aim_integral = 0.;
        self.last_aim_segments = [None; 2];
        if end == start {
            return Ok(()); // Pause/render calls cannot change direction or ownership.
        }
        self.last_time = end;
        let player = &simulation.player;
        if reload_visual_active || player.reload_left > 0. {
            self.sample = None;
            return Ok(());
        }
        let requested = player.ads_requested && !player.sprinting && player.mantle.is_none();
        if self.sample.is_none() {
            if !requested || !locomotion_ready {
                return Ok(());
            }
            self.sample = Some(AdsSample {
                slot: AdsSlot::Entry,
                seconds: 0.,
                direction: 1,
            });
        }
        let mut remaining = end - start;
        // At most one transition and the hold remain. The loop also handles
        // unusually long valid ticks without dropping native elapsed time.
        while remaining > 0. {
            let Some(mut sample) = self.sample else {
                break;
            };
            match sample.slot {
                AdsSlot::Hold if requested => {
                    self.last_aim_integral += remaining;
                    self.last_aim_segments[1] = Some(AimSegment {
                        start_seconds: self.last_aim_segments[0]
                            .map_or(0., |segment| segment.duration_seconds),
                        duration_seconds: remaining,
                        from: 1.,
                        to: 1.,
                    });
                    sample.seconds += remaining;
                    sample.direction = 1;
                    self.sample = Some(sample);
                    break;
                }
                AdsSlot::Hold => {
                    self.sample = Some(AdsSample {
                        slot: AdsSlot::Exit,
                        seconds: 0.,
                        direction: 1,
                    });
                }
                AdsSlot::Entry | AdsSlot::Exit => {
                    sample.direction = if requested == (sample.slot == AdsSlot::Entry) {
                        1
                    } else {
                        -1
                    };
                    let duration = self.duration(sample.slot);
                    let until_endpoint = if sample.direction > 0 {
                        duration - sample.seconds
                    } else {
                        sample.seconds
                    };
                    let rate =
                        self.transition_rates[if sample.slot == AdsSlot::Entry { 0 } else { 2 }];
                    let before = sample.seconds;
                    let consumed = (remaining * rate).min(until_endpoint.max(0.));
                    sample.seconds = (sample.seconds + consumed * f64::from(sample.direction))
                        .clamp(0., duration);
                    if consumed > 0. {
                        let progress = |seconds| match sample.slot {
                            AdsSlot::Entry => seconds / duration,
                            AdsSlot::Exit => 1. - seconds / duration,
                            AdsSlot::Hold => unreachable!(),
                        };
                        self.last_aim_segments[0] = Some(AimSegment {
                            start_seconds: 0.,
                            duration_seconds: consumed / rate,
                            from: progress(before),
                            to: progress(sample.seconds),
                        });
                    }
                    self.last_aim_integral += (self
                        .aim_antiderivative(sample.slot, sample.seconds)
                        - self.aim_antiderivative(sample.slot, before))
                        / (f64::from(sample.direction) * rate);
                    remaining = (remaining - consumed / rate).max(0.);
                    if consumed < until_endpoint {
                        self.sample = Some(sample);
                        break;
                    }
                    let reached_hold = (sample.slot == AdsSlot::Entry) == (sample.direction > 0);
                    self.sample = reached_hold.then_some(AdsSample {
                        slot: AdsSlot::Hold,
                        seconds: 0.,
                        direction: 1,
                    });
                }
            }
        }
        Ok(())
    }
}

/// Decode-rounding tolerance only, never a pose correction or approval gate.
fn same_pose(a: &ViewmodelPose, b: &ViewmodelPose) -> bool {
    a.actor_visible == b.actor_visible
        && a.bone_locals.len() == b.bone_locals.len()
        && a.actor_globals.len() == b.actor_globals.len()
        && a.bone_locals
            .iter()
            .chain(&a.actor_globals)
            .zip(b.bone_locals.iter().chain(&b.actor_globals))
            .all(|(a, b)| {
                a.translation.abs_diff_eq(b.translation, 1e-5)
                    && a.scale.abs_diff_eq(b.scale, 1e-5)
                    && (a.rotation.abs_diff_eq(b.rotation, 1e-5)
                        || a.rotation.abs_diff_eq(-b.rotation, 1e-5))
            })
}

/// Deterministic input-only native capture replay, shared by runtime and tests.
/// The simulation decides aim, firing, reload acceptance and actual movement.
pub fn gameplay_ads_replay_input(time: f64) -> crate::sim::Input {
    use glam::Vec2;
    crate::sim::Input {
        ads: (0.25..0.75).contains(&time)
            || (1.25..(1. + 1. / 3.)).contains(&time)
            || (1.375..1.9).contains(&time)
            || (2.0..2.5).contains(&time)
            || (2.9..3.5).contains(&time)
            || (4.2..8.4).contains(&time),
        movement: if (2.5..4.2).contains(&time) {
            Vec2::Y
        } else {
            Vec2::ZERO
        },
        sprint: (3.5..4.2).contains(&time),
        fire: (4.8..5.0).contains(&time),
        reload: (5.1..5.15).contains(&time),
        ..crate::sim::Input::default()
    }
}

pub fn gameplay_ads_replay_segment(time: f64) -> &'static str {
    if time < 1.25 {
        "complete_cycle"
    } else if time < 1.9 {
        "entry_reversal"
    } else if time < 2.5 {
        "exit_reversal"
    } else if time < 2.9 {
        "walk"
    } else if time < 3.5 {
        "walk_to_ads"
    } else if time < 4.2 {
        "sprint_interrupt"
    } else if time < 4.8 {
        "sprint_to_ads"
    } else if time < 5.1 {
        "fire_while_aiming"
    } else if time < 8.4 {
        "reload_interrupt_and_return"
    } else {
        "final_exit"
    }
}

#[cfg(test)]
mod weighted_integral_tests {
    use super::*;

    fn fixture() -> (AuthoredAds, Simulation) {
        (
            AuthoredAds {
                clips: AdsReference {
                    asset: "weighted-integral-test".into(),
                    entry_clip: "entry".into(),
                    hold_clip: "hold".into(),
                    exit_clip: "exit".into(),
                },
                durations: [0.25, 1., 0.2],
                sample: None,
                last_time: 0.,
                transition_rates: [1.; 3],
                last_aim_integral: 0.,
                last_aim_segments: [None; 2],
            },
            Simulation::new(),
        )
    }

    fn step(ads: &mut AuthoredAds, sim: &mut Simulation, seconds: f64, requested: bool) {
        let start = sim.time;
        sim.time += seconds;
        sim.player.ads_requested = requested;
        ads.committed_step(start, sim, false, true).unwrap();
    }

    /// Independent Simpson reference, restricted to the first 40 response times.
    /// The omitted positive tail is <= response * exp(-40), since aim <= 1.
    fn reference_exponential(segment: AimSegment, response: f64) -> f64 {
        let duration = segment.duration_seconds.min(40. * response);
        let subdivisions = 16_384;
        let width = duration / subdivisions as f64;
        let evaluate = |t: f64| {
            let u = segment.from + (segment.to - segment.from) * t / segment.duration_seconds;
            u * u * (3. - 2. * u) * (-(segment.start_seconds + t) / response).exp()
        };
        let mut sum = evaluate(0.) + evaluate(duration);
        for index in 1..subdivisions {
            sum += if index % 2 == 0 { 2. } else { 4. } * evaluate(index as f64 * width);
        }
        sum * width / 3.
    }

    #[test]
    fn cubic_moments_match_independent_quadrature_across_response_scales() {
        for (from, to) in [(0., 1.), (1., 0.), (0.23, 0.71), (0.71, 0.23), (1., 1.)] {
            for start_seconds in [0., 0.12] {
                let segment = AimSegment {
                    start_seconds,
                    duration_seconds: 0.3,
                    from,
                    to,
                };
                for response in [1e-6, 1e-3, 0.06, 0.1499, 0.15, 0.1501, 1., 1e8] {
                    let actual = segment.exponentially_weighted_integral(response);
                    let expected = reference_exponential(segment, response);
                    assert!(
                        (actual - expected).abs() < 2e-13,
                        "{segment:?}, response={response}: {actual} != {expected}"
                    );
                }
            }
        }
    }

    #[test]
    fn hold_matches_closed_form_and_queries_do_not_mutate_playback() {
        let (mut ads, mut sim) = fixture();
        step(&mut ads, &mut sim, 0.25, true);
        step(&mut ads, &mut sim, 0.17, true);
        let sample = ads.sample();
        let last_time = ads.last_time;
        let unweighted = ads.last_aim_integral();
        for (start, target) in [(0., 1.), (1., 0.), (0.31, 0.83)] {
            let expected = target * 0.17 + (start - target) * 0.06 * -(-0.17_f64 / 0.06).exp_m1();
            for _ in 0..4 {
                assert!(
                    (ads.last_aim_weighted_integral(start, target, 0.06) - expected).abs() < 1e-14
                );
            }
        }
        assert_eq!(ads.sample(), sample);
        assert_eq!(ads.last_time, last_time);
        assert_eq!(ads.last_aim_integral(), unweighted);
    }

    #[test]
    fn weighted_transition_and_hold_keep_the_same_response_clock() {
        let (mut ads, mut sim) = fixture();
        step(&mut ads, &mut sim, 0.6, true);
        let transition = AimSegment {
            start_seconds: 0.,
            duration_seconds: 0.25,
            from: 0.,
            to: 1.,
        };
        let hold = AimSegment {
            start_seconds: 0.25,
            duration_seconds: 0.35,
            from: 1.,
            to: 1.,
        };
        let expected = reference_exponential(transition, 0.06) + reference_exponential(hold, 0.06);
        assert!((ads.last_aim_weighted_integral(1., 0., 0.06) - expected).abs() < 2e-13);
        assert_eq!(
            ads.last_aim_weighted_integral(1., 1., 0.06),
            ads.last_aim_integral()
        );
        assert_eq!(ads.last_aim_weighted_integral(0., 0., 0.06), 0.);
    }

    #[test]
    fn partitioning_ticks_preserves_native_clock_through_both_reversals() {
        fn run(subdivisions: usize) -> (f64, f64, f64, Option<AdsSample>) {
            let (ads, mut sim) = fixture();
            let mut ads = ads.with_visual_transition_seconds(0.3).unwrap();
            let mut weight = 0.41;
            let mut integral = 0.;
            let mut weighted = 0.;
            let mut native = 0.;
            for (duration, requested, target) in [
                (0.17, true, 1.),
                (0.055, false, 0.),
                (0.035, true, 0.8),
                (0.71, true, 0.1),
                (0.071, false, 1.),
                (0.13, true, 0.4),
                (0.68, true, 1.),
                (0.62, false, 0.),
            ] {
                for _ in 0..subdivisions {
                    let dt = duration / subdivisions as f64;
                    step(&mut ads, &mut sim, dt, requested);
                    let aim = ads.last_aim_integral();
                    let aim_direction = ads.last_aim_weighted_integral(weight, target, 0.06);
                    integral += aim;
                    weighted += aim_direction;
                    native += dt - 0.15 * aim - 0.05 * aim_direction;
                    weight = target + (weight - target) * (-dt / 0.06).exp();
                }
            }
            (integral, weighted, native, ads.sample())
        }
        let expected = run(1);
        for subdivisions in [2, 3, 7, 30, 120, 1000] {
            let actual = run(subdivisions);
            assert!(
                (actual.0 - expected.0).abs() < 1e-11,
                "{subdivisions}: {actual:?}"
            );
            assert!(
                (actual.1 - expected.1).abs() < 1e-11,
                "{subdivisions}: {actual:?}"
            );
            assert!(
                (actual.2 - expected.2).abs() < 1e-11,
                "{subdivisions}: {actual:?}"
            );
            assert_eq!(actual.3, expected.3);
        }
    }

    #[test]
    fn large_tick_retains_the_early_response_and_bounds_storage() {
        let (mut ads, mut sim) = fixture();
        step(&mut ads, &mut sim, 1e6, true);
        let expected = reference_exponential(ads.last_aim_segments[0].unwrap(), 0.06)
            + reference_exponential(ads.last_aim_segments[1].unwrap(), 0.06);
        assert!((ads.last_aim_weighted_integral(1., 0., 0.06) - expected).abs() < 2e-13);
        assert_eq!(ads.last_aim_segments.iter().flatten().count(), 2);
        step(&mut ads, &mut sim, 1e6, false);
        assert!(ads.sample().is_none());
        assert_eq!(ads.last_aim_segments.iter().flatten().count(), 1);
        let weighted = ads.last_aim_weighted_integral(0., 1., 0.06);
        assert!(weighted > 0. && weighted < ads.last_aim_integral());
    }

    #[test]
    fn zero_ticks_reload_reset_and_inactive_ticks_clear_previous_integrals() {
        let (mut ads, mut sim) = fixture();
        step(&mut ads, &mut sim, 0.13, true);
        assert!(ads.last_aim_weighted_integral(1., 0., 0.06) > 0.);
        let sample = ads.sample();
        sim.player.reload_left = 1.;
        step(&mut ads, &mut sim, 0., false);
        assert_eq!(ads.sample(), sample);
        assert_eq!(ads.last_aim_integral(), 0.);
        assert_eq!(ads.last_aim_weighted_integral(1., 0., 0.06), 0.);
        step(&mut ads, &mut sim, 0.01, true);
        assert!(ads.sample().is_none());
        assert_eq!(ads.last_aim_weighted_integral(0.5, 0.8, 0.06), 0.);
        sim.player.reload_left = 0.;
        step(&mut ads, &mut sim, 0.12, true);
        let start = sim.time;
        sim.time += 0.01;
        ads.committed_step(start, &sim, true, true).unwrap();
        assert!(ads.sample().is_none());
        assert_eq!(ads.last_aim_weighted_integral(1., 1., 0.06), 0.);
        step(&mut ads, &mut sim, 0.1, true);
        ads.reset(sim.time);
        assert_eq!(ads.last_aim_weighted_integral(1., 1., 0.06), 0.);
        step(&mut ads, &mut sim, 0.1, false);
        assert_eq!(ads.last_aim_weighted_integral(1., 1., 0.06), 0.);
    }

    #[test]
    fn input_bounds_and_instantaneous_or_unbounded_responses_are_defined() {
        let (mut ads, mut sim) = fixture();
        step(&mut ads, &mut sim, 0.14, true);
        let integral = ads.last_aim_integral();
        for response in [0., -1., f64::NAN, f64::NEG_INFINITY] {
            assert_eq!(
                ads.last_aim_weighted_integral(0.1, 0.7, response),
                0.7 * integral
            );
        }
        assert_eq!(
            ads.last_aim_weighted_integral(0.1, 0.7, f64::INFINITY),
            0.1 * integral
        );
        assert_eq!(ads.last_aim_weighted_integral(-2., f64::NAN, 0.06), 0.);
        assert_eq!(
            ads.last_aim_weighted_integral(2., f64::INFINITY, 0.06),
            integral
        );
        for response in [f64::MIN_POSITIVE, 1e-8, 0.06, 1e8, f64::MAX] {
            for (start, target) in [(0., 1.), (1., 0.)] {
                let weighted = ads.last_aim_weighted_integral(start, target, response);
                assert!(weighted.is_finite() && (0. ..=integral).contains(&weighted));
            }
        }
    }
}
