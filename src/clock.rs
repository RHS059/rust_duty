//! The native application's authoritative fixed-step clock, shared by replay tests.
#[derive(Default, Debug)]
pub struct FixedClock {
    remainder: f64,
}
impl FixedClock {
    pub const STEP: f64 = 1.0 / 120.0;
    pub const MAX_FRAME: f64 = 0.250;
    // One microsecond is below timer/input precision on supported native backends.
    // It only reconciles representable frame endpoints, never a whole simulation tick.
    const ENDPOINT_EPSILON: f64 = 1e-6;
    pub fn clear(&mut self) {
        self.remainder = 0.;
    }
    pub fn advance(&mut self, elapsed: f64) -> Option<usize> {
        if !elapsed.is_finite() || !(0.0..=Self::MAX_FRAME).contains(&elapsed) {
            self.clear();
            return None;
        }
        self.remainder += elapsed;
        let ticks = ((self.remainder + Self::ENDPOINT_EPSILON) / Self::STEP).floor() as usize;
        self.remainder -= ticks as f64 * Self::STEP;
        Some(ticks)
    }
    pub fn alpha(&self) -> f32 {
        (self.remainder / Self::STEP).clamp(0., 1.) as f32
    }
}
/// Explicit diagnostic rates are integral divisors of the 120 Hz simulation.
/// Count committed ticks instead of comparing rounded floating frame timestamps.
pub fn capture_tick_target(frame: u64, hz: u32) -> Option<u64> {
    let stride = match hz {
        30 => 4,
        60 => 2,
        _ => return None,
    };
    frame.checked_mul(stride)
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        settings::Settings,
        sim::{Input, Simulation, FIXED_DT},
    };
    use macroquad::math::vec2;
    #[test]
    fn explicit_capture_rates_have_exact_integer_tick_strides() {
        for (hz, stride) in [(30, 4), (60, 2)] {
            for frame in 1..100_000 {
                assert_eq!(
                    capture_tick_target(frame, hz).unwrap()
                        - capture_tick_target(frame - 1, hz).unwrap(),
                    stride
                );
            }
        }
        assert_eq!(capture_tick_target(1, 59), None);
        assert_eq!(capture_tick_target(u64::MAX, 30), None);
    }
    #[test]
    fn native_clock_matches_all_render_endpoints() {
        let mut baseline = None;
        for fps in [30, 60, 75, 100, 120, 144, 165, 240] {
            let mut clock = FixedClock::default();
            let mut sim = Simulation::new();
            let mut ticks = 0;
            for _ in 0..fps * 10 {
                for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                    ticks += 1;
                    sim.update(
                        Input {
                            movement: vec2(0., 1.),
                            fire: true,
                            ..Input::default()
                        },
                        &Settings::default(),
                        FIXED_DT,
                    );
                }
            }
            assert_eq!(ticks, 1200, "{fps} FPS");
            let state = (sim.player.position, sim.stats.shots, sim.player.ammo);
            if let Some(b) = baseline {
                assert_eq!(state, b);
            } else {
                baseline = Some(state);
            }
        }
    }
    #[test]
    fn rounded_frame_deltas_do_not_lose_a_tick_at_ten_seconds() {
        for fps in [30, 60, 75, 100, 120, 144, 165, 240] {
            let mut c = FixedClock::default();
            let mut ticks = 0;
            for _ in 0..fps * 10 {
                ticks += c.advance((1_f32 / fps as f32) as f64).unwrap();
            }
            assert_eq!(ticks, 1200, "{fps} FPS");
        }
    }
    #[test]
    fn hitch_budget_and_reset_do_not_leave_backlog() {
        let mut c = FixedClock::default();
        assert_eq!(c.advance(0.1), Some(12));
        assert_eq!(c.advance(0.4), None);
        assert_eq!(c.advance(FixedClock::STEP), Some(1));
        c.advance(0.003);
        c.clear();
        assert_eq!(c.advance(0.), Some(0));
    }
}
