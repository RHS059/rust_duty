//! Original reload-root curves fitted to observed screen landmarks in the
//! supplied newer-era BETA clip. These are authored transforms for our HK416,
//! not recovered COD animation data. Hand/magazine paths remain separate.
#[derive(Clone, Copy, Debug, Default)]
pub struct ReloadRoot {
    pub translation: [f32; 3],
    pub euler_yxz: [f32; 3],
}
#[derive(Clone, Copy)]
struct Key(f32, [f32; 6]);
// Balanced fits include aperture/receiver scale, not sight centers alone.
const TACTICAL: &[Key] = &[
    Key(0., [0.; 6]),
    Key(
        0.090498,
        [
            0.01021066,
            -0.01310738,
            0.01420827,
            0.02533121,
            0.1314058,
            -0.06293551,
        ],
    ),
    Key(
        0.316742,
        [
            0.04293284,
            0.03065394,
            0.05098383,
            -0.01914571,
            0.4841925,
            -0.2216614,
        ],
    ),
    Key(
        0.542986,
        [
            0.02181468, -0.0116178, 0.05485653, 0.00663904, 0.4579043, -0.6978842,
        ],
    ),
    Key(
        0.769231,
        [
            0.02484996, 0.02548077, 0.04736457, 0.05145404, 0.4044548, -0.454354,
        ],
    ),
    Key(
        0.8641176,
        [
            0.006873285,
            -0.01645715,
            7.711935e-05,
            -0.002323407,
            0.01073153,
            0.01370927,
        ],
    ),
    Key(
        0.9094118,
        [
            0.006204886,
            -0.02509872,
            -5.864076e-05,
            0.0249203,
            -0.01662064,
            0.009618787,
        ],
    ),
    Key(
        0.9547059,
        [
            -0.0004313151,
            -0.006976185,
            -0.0001051354,
            0.01411202,
            -0.003509336,
            0.005051632,
        ],
    ),
    Key(1., [0.; 6]),
];
const EMPTY: &[Key] = &[
    Key(0., [0.; 6]),
    Key(
        0.181818,
        [
            0.07828275,
            -0.01418221,
            -0.09053904,
            0.2804264,
            0.6397632,
            -0.3281155,
        ],
    ),
    Key(
        0.545455,
        [
            0.05913559,
            -0.01259443,
            0.004088132,
            0.1227654,
            0.4883175,
            -0.8546188,
        ],
    ),
    Key(
        0.727273,
        [
            0.06273893,
            0.003508408,
            -0.01712769,
            0.09514572,
            0.2945178,
            -0.365554,
        ],
    ),
    Key(1., [0.; 6]),
];
// Shape-preserving cubic interpolation: no overshoot between measured keys.
// The endpoint tangents are zero so enter/return join the idle pose smoothly.
fn tangent(keys: &[Key], i: usize, axis: usize) -> f32 {
    if i == 0 || i + 1 == keys.len() {
        return 0.;
    }
    let left = (keys[i].1[axis] - keys[i - 1].1[axis]) / (keys[i].0 - keys[i - 1].0);
    let right = (keys[i + 1].1[axis] - keys[i].1[axis]) / (keys[i + 1].0 - keys[i].0);
    if left * right <= 0. {
        return 0.;
    }
    let a = keys[i].0 - keys[i - 1].0;
    let b = keys[i + 1].0 - keys[i].0;
    let w1 = 2. * b + a;
    let w2 = b + 2. * a;
    (w1 + w2) / (w1 / left + w2 / right)
}
pub fn sample_reload_root(phase: f32, empty: bool) -> ReloadRoot {
    if !phase.is_finite() || phase <= 0. || phase >= 1. {
        return ReloadRoot::default();
    }
    let keys = if empty { EMPTY } else { TACTICAL };
    let i = keys
        .windows(2)
        .position(|w| phase <= w[1].0)
        .unwrap_or(keys.len() - 2);
    let a = keys[i];
    let b = keys[i + 1];
    let span = b.0 - a.0;
    let t = (phase - a.0) / span;
    let values: [f32; 6] = std::array::from_fn(|axis| {
        (2. * t * t * t - 3. * t * t + 1.) * a.1[axis]
            + (t * t * t - 2. * t * t + t) * span * tangent(keys, i, axis)
            + (-2. * t * t * t + 3. * t * t) * b.1[axis]
            + (t * t * t - t * t) * span * tangent(keys, i + 1, axis)
    });
    ReloadRoot {
        translation: [values[0], values[1], values[2]],
        euler_yxz: [values[3], values[4], values[5]],
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn endpoints_and_bad_inputs_return_idle() {
        for phase in [-1., 0., 1., 2., f32::NAN, f32::INFINITY] {
            for empty in [false, true] {
                let r = sample_reload_root(phase, empty);
                assert_eq!(r.translation, [0.; 3]);
                assert_eq!(r.euler_yxz, [0.; 3]);
            }
        }
    }
    #[test]
    fn fitted_anchors_are_preserved_and_curves_do_not_overshoot() {
        for (empty, keys) in [(false, TACTICAL), (true, EMPTY)] {
            for pair in keys.windows(2) {
                for step in 0..=100 {
                    let phase = pair[0].0 + (pair[1].0 - pair[0].0) * step as f32 / 100.;
                    let root = sample_reload_root(phase, empty);
                    let v = [
                        root.translation[0],
                        root.translation[1],
                        root.translation[2],
                        root.euler_yxz[0],
                        root.euler_yxz[1],
                        root.euler_yxz[2],
                    ];
                    for (i, value) in v.iter().enumerate() {
                        assert!(*value >= pair[0].1[i].min(pair[1].1[i]) - 1e-5);
                        assert!(*value <= pair[0].1[i].max(pair[1].1[i]) + 1e-5);
                        if step == 0 {
                            assert!((*value - pair[0].1[i]).abs() < 1e-5);
                        }
                    }
                }
            }
        }
    }
}

/// Observed presentation duration includes the late tactical recovery. Gameplay
/// credit/ready deadlines remain in the simulation settings.
pub fn visual_duration(empty: bool) -> f32 {
    if empty {
        2.2
    } else {
        2.21
    }
}
#[derive(Default)]
pub struct ReloadVisualClock {
    start: Option<f64>,
    empty: bool,
    was_active: bool,
}
impl ReloadVisualClock {
    pub fn phase(
        &mut self,
        simulation_phase: Option<f32>,
        simulation_duration: f32,
        empty: bool,
        completed: bool,
        now: f64,
    ) -> Option<f32> {
        if let Some(phase) = simulation_phase {
            let observed_start = now - (phase * simulation_duration) as f64;
            // A cancel/restart may occur between renders with Some at both ends.
            // Simulation ticks are 8.33ms; 1ms tolerates f32 remainder noise.
            let restarted = self
                .start
                .is_some_and(|start| (observed_start - start).abs() > 0.001);
            if !self.was_active || restarted || empty != self.empty {
                self.start = Some(observed_start);
                self.empty = empty;
            }
            self.was_active = true;
        } else {
            self.was_active = false;
            if !completed {
                self.start = None;
            }
        }
        let start = self.start?;
        let phase = ((now - start) as f32 / visual_duration(self.empty)).max(0.);
        if phase >= 1. && simulation_phase.is_none() {
            self.start = None;
            None
        } else {
            Some(phase.min(1.))
        }
    }
}
#[cfg(test)]
mod clock_tests {
    use super::*;
    #[test]
    fn natural_completion_keeps_visual_recovery_but_cancel_does_not() {
        let mut c = ReloadVisualClock::default();
        assert_eq!(c.phase(Some(0.), 2.029, false, false, 10.), Some(0.));
        assert!(c.phase(None, 2.029, false, true, 12.029).unwrap() < 1.);
        assert!(c.phase(None, 2.029, false, true, 12.211).is_none());
        assert_eq!(c.phase(Some(0.), 2.029, false, false, 20.), Some(0.));
        assert!(c.phase(None, 2.029, false, false, 20.5).is_none());
        assert!(c.phase(None, 2.029, false, true, 22.1).is_none());
    }
    #[test]
    fn different_render_partitions_share_elapsed_presentation_phase() {
        for fps in [30., 60., 144.] {
            let mut c = ReloadVisualClock::default();
            c.phase(Some(0.), 2.029, false, false, 0.);
            for n in 1..(fps as usize) {
                c.phase(
                    Some(n as f32 / fps / 2.029),
                    2.029,
                    false,
                    false,
                    n as f64 / fps as f64,
                );
            }
            let phase = c.phase(Some(1. / 2.029), 2.029, false, false, 1.).unwrap();
            assert!((phase - 1. / 2.21).abs() < 1e-6);
        }
    }
}

/// Original visual ADS easing fitted to dense rear-sight measurements. The
/// simulation's 250ms aim/spread/movement transition remains unchanged.
pub fn visual_ads(progress: f32) -> f32 {
    let t = if progress.is_finite() {
        progress.clamp(0., 1.)
    } else {
        0.
    };
    t * t * (3. - 2. * t)
}

/// Observed world zoom follows the weapon raise by roughly43ms. Absolute input
/// onset is unknown; this is a conditional presentation fit, not engine timing.
pub fn visual_world_ads(progress: f32) -> f32 {
    visual_ads((progress * 0.250 - 0.043) / 0.186)
}
