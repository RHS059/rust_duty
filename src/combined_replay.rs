//! Bounded committed-Input route. Only the initial fixture may set feet/yaw.
//! This driver reads gameplay state and can fail; it cannot accept a mantle,
//! install a binding, advance a clock, or change a pose/camera/velocity.
use crate::sim::{Input, MantleKind, Simulation};
use glam::{vec2, vec3, Vec3};

pub const SEQUENCE: &str = "gameplay-combined";
pub const MAX_SECONDS: f32 = 60.;
pub fn start() -> (Vec3, f32) {
    (vec3(-8.6, 0., -3.), std::f32::consts::PI)
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    PrimeShot,
    HighRequest,
    HighRide,
    HighReloadTail,
    ReloadSettle,
    ProneFull,
    ProneAds,
    Stand,
    SecondShot,
    ProneShort,
    ProneReload,
    ReloadStand,
    EastToLow,
    SouthLane,
    LowApproach,
    LowRequest,
    LowRide,
    LowAdsTail,
    EastRepeatLow,
    RepeatLowApproach,
    RepeatLowRequest,
    RepeatLowRide,
    RepeatLowAdsTail,
    EastToHigh,
    NorthLane,
    HighApproach,
    RepeatHighRequest,
    RepeatHighRide,
    HighAdsTail,
    Clear,
    Done,
}
#[derive(Clone, Copy, Debug)]
pub struct Observed {
    pub time: f64,
    pub position: [f32; 3],
    pub speed: f32,
    pub grounded: bool,
    pub standing: bool,
    pub mantle: Option<MantleKind>,
    pub high_completed: bool,
    pub low_endpoint: bool,
    pub prone_seconds: Option<f64>,
    pub prone_return: bool,
    pub reload_left: f32,
    pub ads: f32,
    pub shots: u32,
    pub dead: bool,
}
impl Observed {
    pub fn from_sim(s: &Simulation) -> Self {
        Self {
            time: s.time,
            position: s.player.position.to_array(),
            speed: s.player.speed(),
            grounded: s.player.grounded,
            standing: !s.player.crouched && !s.player.prone && s.player.stance_progress >= 1.,
            mantle: s.player.mantle.map(|m| m.kind),
            high_completed: s
                .high_mantle_presentation()
                .and_then(|h| h.outgoing)
                .is_some_and(|r| r.completed),
            low_endpoint: s.low_vault_sample().is_some_and(|v| {
                (v.seconds - crate::authored_low_vault::KEY_SPAN_SECONDS).abs() < 1e-6
            }),
            prone_seconds: s.prone_sample().map(|v| v.seconds),
            prone_return: s.prone_return().is_some(),
            reload_left: s.player.reload_left,
            ads: s.player.ads,
            shots: s.stats.shots,
            dead: s.player.dead(),
        }
    }
}
pub struct Replay {
    phase: Phase,
    began: f64,
    ticks: u32,
    request_at: Option<f64>,
    high: u32,
    low: u32,
    prone: u32,
}
impl Default for Replay {
    fn default() -> Self {
        Self {
            phase: Phase::PrimeShot,
            began: 0.,
            ticks: 0,
            request_at: None,
            high: 0,
            low: 0,
            prone: 0,
        }
    }
}
impl Replay {
    pub fn phase(&self) -> Phase {
        self.phase
    }
    pub fn done(&self) -> bool {
        self.phase == Phase::Done
    }
    pub fn counts(&self) -> [u32; 3] {
        [self.high, self.low, self.prone]
    }
    fn advance(&mut self, next: Phase, time: f64) {
        self.phase = next;
        self.began = time;
        self.ticks = 0;
        self.request_at = None;
    }
    /// Returns only ordinary input. Progression requires actual observed state.
    pub fn input(&mut self, s: Observed) -> Result<Input, String> {
        use Phase::*;
        if s.dead || !s.time.is_finite() || s.position.iter().any(|v| !v.is_finite()) {
            return Err("combined replay encountered death/nonfinite state".into());
        }
        if s.time > f64::from(MAX_SECONDS) || s.time - self.began > 12. {
            return Err(format!(
                "combined route timed out in {:?}; accepted {:?}",
                self.phase,
                self.counts()
            ));
        }
        // All lane movement must stay east of the middle block's expanded face.
        if matches!(self.phase, SouthLane | NorthLane) && s.position[0] < -8.50 {
            return Err("combined route left the open east lane".into());
        }
        let age = s.time - self.began;
        let mut i = Input::default();
        match self.phase {
            PrimeShot | SecondShot => {
                i.fire = self.ticks == 0;
                let needed = if self.phase == PrimeShot { 1 } else { 2 };
                if age >= 0.30 && s.shots >= needed {
                    self.advance(
                        if self.phase == PrimeShot {
                            HighRequest
                        } else {
                            ProneShort
                        },
                        s.time,
                    );
                    return self.input(s);
                }
                if age > 0.5 && s.shots < needed {
                    return Err("ordinary priming shot was rejected".into());
                }
            }
            HighRequest | LowRequest | RepeatLowRequest | RepeatHighRequest => {
                let high = matches!(self.phase, HighRequest | RepeatHighRequest);
                let kind = if high {
                    MantleKind::High
                } else {
                    MantleKind::Low
                };
                if self.request_at.is_none() {
                    // Both native spans are 2 mod 4 fixed ticks. A request at
                    // tick 2 mod 4 exposes the endpoint on 30/60 Hz grids.
                    if ((s.time / f64::from(crate::sim::FIXED_DT)).round() as u64) % 4 != 2 {
                        self.ticks += 1;
                        return Ok(i);
                    }
                    if !s.grounded || !s.standing || s.mantle.is_some() {
                        return Err(
                            "ordinary traversal request requires settled standing support".into(),
                        );
                    }
                    i.movement = vec2(0., 1.);
                    i.jump = true;
                    self.request_at = Some(s.time);
                } else {
                    if s.mantle != Some(kind) {
                        return Err(format!("ordinary {:?} request was rejected", kind));
                    }
                    let next = match self.phase {
                        HighRequest => HighRide,
                        LowRequest => LowRide,
                        RepeatLowRequest => RepeatLowRide,
                        _ => RepeatHighRide,
                    };
                    if high {
                        self.high += 1;
                    } else {
                        self.low += 1;
                    }
                    self.advance(next, s.time);
                    return self.input(s);
                }
            }
            HighRide | LowRide | RepeatLowRide | RepeatHighRide => {
                let high = matches!(self.phase, HighRide | RepeatHighRide);
                i.ads = true;
                if s.mantle.is_none() {
                    if !(if high {
                        s.high_completed
                    } else {
                        s.low_endpoint
                    }) {
                        return Err("traversal ended without the committed native endpoint".into());
                    }
                    let next = match self.phase {
                        HighRide => HighReloadTail,
                        LowRide => LowAdsTail,
                        RepeatLowRide => RepeatLowAdsTail,
                        _ => HighAdsTail,
                    };
                    self.advance(next, s.time);
                    return self.input(s);
                }
            }
            HighReloadTail | LowAdsTail | RepeatLowAdsTail | HighAdsTail => {
                i.movement = vec2(0., 1.);
                i.ads = self.phase != HighReloadTail;
                i.reload = self.phase == HighReloadTail && self.ticks == 0;
                if self.phase == HighReloadTail && self.ticks > 1 && s.reload_left <= 0. {
                    return Err("ordinary high-tail reload was rejected".into());
                }
                if age >= 0.20 {
                    let next = match self.phase {
                        HighReloadTail => ReloadSettle,
                        LowAdsTail => EastRepeatLow,
                        RepeatLowAdsTail => EastToHigh,
                        _ => Clear,
                    };
                    self.advance(next, s.time);
                    return self.input(s);
                }
            }
            ReloadSettle | ReloadStand => {
                if age >= 0.40 && s.reload_left <= 0. && s.ads == 0. && s.standing && s.speed < 0.05
                {
                    self.advance(
                        if self.phase == ReloadSettle {
                            ProneFull
                        } else {
                            EastToLow
                        },
                        s.time,
                    );
                    return self.input(s);
                }
            }
            ProneFull | ProneShort => {
                i.prone = true;
                if let Some(seconds) = s.prone_seconds {
                    let end = if self.phase == ProneFull {
                        crate::authored_prone::ENTRY_SECONDS
                    } else {
                        0.30
                    };
                    if seconds + 1e-6 >= end {
                        self.prone += 1;
                        self.advance(
                            if self.phase == ProneFull {
                                ProneAds
                            } else {
                                ProneReload
                            },
                            s.time,
                        );
                        return self.input(s);
                    }
                }
            }
            ProneAds | ProneReload => {
                i.prone = true;
                i.ads = self.phase == ProneAds;
                i.reload = self.phase == ProneReload && self.ticks == 0;
                if self.ticks == 1 && !s.prone_return {
                    return Err("paired prone interruption did not begin return".into());
                }
                if self.phase == ProneReload && self.ticks > 1 && s.reload_left <= 0. {
                    return Err("ordinary prone reload was rejected".into());
                }
                if age >= 0.35 {
                    self.advance(
                        if self.phase == ProneAds {
                            Stand
                        } else {
                            ReloadStand
                        },
                        s.time,
                    );
                    return self.input(s);
                }
            }
            Stand => {
                if age >= 0.8 && s.standing && s.ads == 0. && s.speed < 0.05 {
                    self.advance(SecondShot, s.time);
                    return self.input(s);
                }
            }
            EastToLow | EastRepeatLow | EastToHigh => {
                if s.position[0] < -8.0 {
                    i.movement = vec2(0., -1.);
                } else if s.grounded && s.speed < 0.05 && s.position[1].abs() < 0.02 {
                    let next = match self.phase {
                        EastToLow => SouthLane,
                        EastRepeatLow => RepeatLowApproach,
                        _ => NorthLane,
                    };
                    self.advance(next, s.time);
                    return self.input(s);
                }
            }
            SouthLane | NorthLane => {
                let target = if self.phase == SouthLane { 3. } else { -3. };
                let delta = target - s.position[2];
                if delta.abs() < 0.18 && s.speed < 0.05 && s.grounded {
                    self.advance(
                        if self.phase == SouthLane {
                            LowApproach
                        } else {
                            HighApproach
                        },
                        s.time,
                    );
                    return self.input(s);
                }
                // Continuous coarse travel, then short ordinary button pulses.
                // Input magnitude is not treated as a speed control by Simulation.
                if (delta.abs() > 0.8
                    || (s.speed < 0.05 && delta.abs() >= 0.18)
                    || self.ticks % 24 < 3)
                    && delta.abs() >= 0.18
                {
                    i.movement = vec2(-delta.signum(), 0.);
                }
            }
            LowApproach | RepeatLowApproach | HighApproach => {
                if s.position[0] > -8.56 {
                    i.movement = vec2(0., 1.);
                } else if s.speed < 0.05 && s.grounded && s.standing {
                    self.advance(
                        match self.phase {
                            LowApproach => LowRequest,
                            RepeatLowApproach => RepeatLowRequest,
                            _ => RepeatHighRequest,
                        },
                        s.time,
                    );
                    return self.input(s);
                }
            }
            Clear => {
                if age >= 0.6
                    && s.mantle.is_none()
                    && !s.high_completed
                    && s.standing
                    && s.speed < 0.05
                {
                    if self.counts() != [2, 2, 2] {
                        return Err("combined accepted action count mismatch".into());
                    }
                    self.advance(Done, s.time);
                }
            }
            Done => {}
        }
        self.ticks += 1;
        Ok(i)
    }
}
/// Committed mantle, high/low endpoints, prone presence/endpoint/return, and phase.
type CadenceSignature = (Option<MantleKind>, bool, bool, bool, bool, bool, Phase);

/// Nonuniform native presentation budget. Every simulation tick is still
/// committed and journaled. Sources: 10 Hz; travel: 5 Hz; returns: 30/60 Hz.
/// An actual committed ownership/endpoint/phase boundary forces a render.
pub struct Cadence {
    dense_hz: u32,
    stride: u64,
    signature: Option<CadenceSignature>,
    boundary: bool,
}
impl Cadence {
    pub fn new(dense_hz: u32) -> Self {
        assert!([30, 60].contains(&dense_hz));
        Self {
            dense_hz,
            stride: 24,
            signature: None,
            boundary: false,
        }
    }
    pub fn stride(&self) -> u64 {
        self.stride
    }
    pub fn boundary(&self) -> bool {
        self.boundary
    }
    pub fn commit(&mut self, s: Observed, phase: Phase, low_return: bool) {
        let signature = (
            s.mantle,
            s.high_completed,
            s.low_endpoint,
            s.prone_seconds.is_some(),
            s.prone_seconds
                .is_some_and(|t| t + 1e-6 >= crate::authored_prone::ENTRY_SECONDS),
            s.prone_return,
            phase,
        );
        self.boundary = self.signature.is_some_and(|old| old != signature);
        self.signature = Some(signature);
        self.stride = if s.high_completed
            || s.prone_return
            || low_return
            || matches!(phase, Phase::LowAdsTail | Phase::RepeatLowAdsTail)
        {
            120 / u64::from(self.dense_hz)
        } else if s.mantle.is_some() || s.prone_seconds.is_some() {
            12
        } else {
            24
        };
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn state(t: f64) -> Observed {
        Observed {
            time: t,
            position: [-8.6, 0., -3.],
            speed: 0.,
            grounded: true,
            standing: true,
            mantle: None,
            high_completed: false,
            low_endpoint: false,
            prone_seconds: None,
            prone_return: false,
            reload_left: 0.,
            ads: 0.,
            shots: 1,
            dead: false,
        }
    }
    #[test]
    fn route_emits_fresh_jump_and_rejects_unaccepted_request() {
        let mut r = Replay::default();
        assert!(r.input(state(0.)).unwrap().fire);
        assert!(!r.input(state(0.30)).unwrap().jump);
        let i = r.input(state(38. / 120.)).unwrap();
        assert!(i.jump && i.movement.y == 1.);
        assert!(r
            .input(state(39. / 120.))
            .err()
            .unwrap()
            .contains("rejected"));
    }
    #[test]
    fn endpoint_is_required_and_does_not_advance_clock() {
        let mut r = Replay {
            phase: Phase::HighRide,
            ..Replay::default()
        };
        assert!(r.input(state(1.)).is_err());
        let mut s = state(1.);
        s.high_completed = true;
        let i = r.input(s).unwrap();
        assert!(i.reload);
        assert_eq!(r.phase(), Phase::HighReloadTail);
        assert_eq!(s.time, 1.);
    }
    #[test]
    fn route_does_not_walk_through_middle_collider() {
        let mut r = Replay {
            phase: Phase::SouthLane,
            ..Replay::default()
        };
        assert!(r.input(state(0.)).err().unwrap().contains("east lane"));
    }
    #[test]
    fn timeout_and_death_are_failures() {
        assert!(Replay::default().input(state(61.)).is_err());
        let mut s = state(0.);
        s.dead = true;
        assert!(Replay::default().input(s).is_err());
    }
    #[test]
    fn only_native_prone_endpoint_finishes_full_entry() {
        let mut r = Replay {
            phase: Phase::ProneFull,
            ..Replay::default()
        };
        let mut s = state(1.);
        s.prone_seconds = Some(0.5);
        assert!(r.input(s).unwrap().prone);
        assert_eq!(r.phase(), Phase::ProneFull);
        s.prone_seconds = Some(crate::authored_prone::ENTRY_SECONDS);
        assert!(r.input(s).unwrap().ads);
        assert_eq!(r.counts(), [0, 0, 1]);
    }
    fn fixture_state(s: &Simulation) -> serde_json::Value {
        let mut row = crate::combined_observer::state("source_free_cpu_fixture", s);
        row.as_object_mut().unwrap().retain(|k, _| {
            [
                "simulation_time",
                "position",
                "speed",
                "grounded",
                "crouched",
                "prone",
                "stance_progress",
                "mantle",
                "high",
                "low",
                "prone_sample",
                "prone_return",
                "reload_left",
                "simulation_ads",
                "shots",
                "dead",
            ]
            .contains(&k.as_str())
        });
        row
    }
    #[test]
    fn combined_replay_source_free_shipped_range_route_completes() {
        // Original synthetic binding data only. This is CPU gameplay reachability,
        // not a loaded production package, native rendering, or art acceptance.
        let mut s = crate::authored_viewmodel::combined_replay_sim();
        let (position, yaw) = start();
        s.player.position = position;
        s.player.yaw = yaw;
        let mut r = Replay::default();
        let cfg = crate::settings::Settings::default();
        let mut last = Phase::Done;
        let mut fixture = vec![fixture_state(&s)];
        while !r.done() {
            let input = r.input(Observed::from_sim(&s)).unwrap_or_else(|e| {
                panic!(
                    "{e}; time {} pos {:?} speed {}",
                    s.time,
                    s.player.position,
                    s.player.speed()
                )
            });
            if r.phase() != last {
                eprintln!(
                    "{:?} t={:.3} pos={:?}",
                    r.phase(),
                    s.time,
                    s.player.position
                );
                last = r.phase();
            }
            s.update(input, &cfg, crate::sim::FIXED_DT);
            let mut row = fixture_state(&s);
            row["phase"] = serde_json::json!(format!("{:?}", r.phase()));
            row["input"] = serde_json::json!({"movement":input.movement.to_array(),"jump":input.jump,"ads":input.ads,"fire":input.fire,"reload":input.reload,"crouch":input.crouch,"prone":input.prone,"sprint":input.sprint,"tactical_sprint":input.tactical_sprint,"sidearm":input.sidearm,"mount":input.mount,"cant":input.cant,"lean":input.lean});
            fixture.push(row);
        }
        if let Some(path) = std::env::var_os("COMBINED_SOURCE_FREE_TEST_TRACE") {
            use std::io::Write;
            let mut file = std::fs::OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(path)
                .unwrap();
            file.write_all(&serde_json::to_vec(&serde_json::json!({"schema":"source-free-combined-route-test/v1","native_capture":false,"rows":fixture})).unwrap()).unwrap();
        }
        assert_eq!(r.counts(), [2, 2, 2]);
        assert!(s.time < f64::from(MAX_SECONDS));
    }
    #[test]
    fn combined_replay_sparse_cadence_retains_boundaries_and_dense_returns() {
        for hz in [30, 60] {
            let mut s = crate::authored_viewmodel::combined_replay_sim();
            let (p, y) = start();
            s.player.position = p;
            s.player.yaw = y;
            let cfg = crate::settings::Settings::default();
            let mut r = Replay::default();
            let mut c = Cadence::new(hz);
            let (mut tick, mut frames, mut endpoints) = (0u64, 0u64, 0u64);
            while !r.done() {
                let target = tick + c.stride();
                while tick < target && !r.done() {
                    let i = r.input(Observed::from_sim(&s)).unwrap();
                    s.update(i, &cfg, crate::sim::FIXED_DT);
                    tick += 1;
                    let snapshot = Observed::from_sim(&s);
                    c.commit(snapshot, r.phase(), false);
                    if c.boundary() {
                        break;
                    }
                }
                frames += 1;
                endpoints += u64::from(
                    s.low_vault_sample().is_some_and(|v| v.source_frame == 64.)
                        || s.high_mantle_presentation()
                            .and_then(|v| v.outgoing)
                            .is_some_and(|v| v.completed && v.weight(s.time) < 1e-6),
                );
            }
            eprintln!("dense_hz={hz} sparse_native_frames={frames} simulation_ticks={tick} native_endpoints_renderable={endpoints}");
            assert!(frames < 300);
            assert_eq!(endpoints, 4);
        }
    }
}
