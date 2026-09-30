//! Public-API contract tests for the original Kestrel-30 weapon simulation.
//! Event timestamps describe the beginning of an update; post-update state is
//! observed at its end. No tests call private methods or depend on RNG seeds.
use macroquad::math::{vec2, Vec2, Vec3};
use vector_range::{
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT, MAGAZINE},
};

const EPS: f64 = 2e-6;
const TICK: f64 = FIXED_DT as f64;
const SHOT_INTERVAL: f64 = 0.090;

fn fire() -> Input {
    Input {
        fire: true,
        ..Input::default()
    }
}
fn sprint() -> Input {
    Input {
        sprint: true,
        movement: vec2(0., 1.),
        ..Input::default()
    }
}
fn ads() -> Input {
    Input {
        ads: true,
        ..Input::default()
    }
}
fn ticks(s: &mut Simulation, cfg: &Settings, input: Input, count: usize) {
    for _ in 0..count {
        s.update(input, cfg, FIXED_DT);
    }
}
fn before_tick(s: &mut Simulation, cfg: &Settings, input: Input, tick: usize) {
    let wanted = tick as f64 * TICK;
    assert!(
        s.time <= wanted + EPS,
        "fixture already beyond tick {tick}: {}",
        s.time
    );
    while s.time + EPS < wanted {
        s.update(input, cfg, FIXED_DT);
    }
    assert!((s.time - wanted).abs() < EPS);
}
fn reload_fixture(ammo: u32, reserve: u32) -> (Simulation, Settings) {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    s.player.ammo = ammo;
    s.player.reserve = reserve;
    s.update(
        Input {
            reload: true,
            ..Input::default()
        },
        &cfg,
        FIXED_DT,
    );
    assert!(s.player.reload_left > 0., "reload did not begin");
    (s, cfg)
}
fn approximately(actual: f32, expected: f32, epsilon: f32, context: &str) {
    assert!(
        (actual - expected).abs() <= epsilon,
        "{context}: got {actual}, expected {expected} ± {epsilon}"
    );
}

#[test]
fn authored_weapon_defaults_are_exact() {
    let s = Simulation::new();
    let c = Settings::default();
    assert_eq!(MAGAZINE, 30);
    assert_eq!((s.player.ammo, s.player.reserve), (30, 90));
    assert!((TICK - 1. / 120.).abs() < 1e-9);
    assert!((60. / c.fire_rpm as f64 - SHOT_INTERVAL).abs() < 1e-7);
    for (actual, expected, context) in [
        (c.reload_credit, 1.350, "tactical credit"),
        (c.reload_time, 1.950, "tactical ready"),
        (c.empty_reload_credit, 1.800, "empty credit"),
        (c.empty_reload_time, 2.550, "empty ready"),
        (c.sprint_out_time, 0.200, "sprint-out"),
        (c.ads_time, 0.220, "ADS-in"),
        (c.ads_out_time, 0.160, "ADS-out"),
    ] {
        approximately(actual, expected, 1e-7, context);
    }
}

#[test]
fn continuous_fire_stays_on_absolute_90ms_schedule_for_whole_magazine() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    ticks(&mut s, &cfg, fire(), 315); // Includes shot 30 (2.610 s), before empty auto-reload.
    assert_eq!(s.events.len(), 30);
    assert_eq!((s.player.ammo, s.player.reserve), (0, 90));
    for (index, shot) in s.events.iter().enumerate() {
        let deadline = index as f64 * SHOT_INTERVAL;
        assert!(
            shot.time >= deadline - EPS,
            "shot {} early: {} < {deadline}",
            index + 1,
            shot.time
        );
        assert!(
            shot.time < deadline + TICK + EPS,
            "shot {} accumulates cadence drift: {} >= {}",
            index + 1,
            shot.time,
            deadline + TICK
        );
    }
    assert_eq!(s.stats.shots, 30);
}

#[test]
fn release_and_repress_cannot_bypass_next_shot_deadline() {
    let cfg = Settings::default();
    for release_tick in 1..=10 {
        for repress_tick in (release_tick + 1)..=12 {
            let mut s = Simulation::new();
            s.update(fire(), &cfg, FIXED_DT);
            before_tick(&mut s, &cfg, fire(), release_tick);
            before_tick(&mut s, &cfg, Input::default(), repress_tick);
            s.update(fire(), &cfg, FIXED_DT);
            before_tick(&mut s, &cfg, fire(), 14);
            assert!(
                s.events.len() >= 2,
                "no second shot at release {release_tick}, repress {repress_tick}"
            );
            let first_eligible = (repress_tick as f64 * TICK).max(SHOT_INTERVAL);
            let second = s.events[1].time;
            assert!(second >= first_eligible - EPS && second < first_eligible + TICK + EPS,
                "release {release_tick}, repress {repress_tick}: second shot {second}, earliest legal {first_eligible}");
        }
    }
}

#[test]
fn repeated_trigger_tapping_never_exceeds_90ms_cadence_beyond_one_tick() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    for tick in 0..240 {
        s.update(
            Input {
                fire: tick % 2 == 0,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
    }
    assert!(s.events.len() >= 18);
    for shots in s.events.windows(2) {
        assert!(
            shots[1].time - shots[0].time + EPS >= SHOT_INTERVAL - TICK,
            "trigger taps bypassed cadence: {} -> {}",
            shots[0].time,
            shots[1].time
        );
    }
    for (index, shot) in s.events.iter().enumerate() {
        assert!(
            shot.time + TICK + EPS >= index as f64 * SHOT_INTERVAL,
            "cumulative trigger-tapping fire rate is too fast at shot {index}"
        );
    }
}

#[test]
fn tactical_reload_credits_at_1350ms_and_fires_at_1950ms() {
    let (mut s, cfg) = reload_fixture(7, 90);
    before_tick(&mut s, &cfg, fire(), 162);
    assert_eq!(
        (s.player.ammo, s.player.reserve),
        (7, 90),
        "credit occurred before 1.350 s"
    );
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(
        (s.player.ammo, s.player.reserve),
        (30, 67),
        "credit missing at 1.350 s"
    );
    assert!(s.player.reload_left > 0.);
    assert!(s.events.is_empty());
    before_tick(&mut s, &cfg, fire(), 234);
    assert!(s.events.is_empty(), "fired before 1.950 s ready milestone");
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(
        s.events.len(),
        1,
        "ready milestone did not precede fire input"
    );
    assert!((s.events[0].time - 1.950).abs() < EPS);
    assert_eq!((s.player.ammo, s.player.reserve), (29, 67));
}

#[test]
fn empty_reload_credits_at_1800ms_and_fires_at_2550ms() {
    let (mut s, cfg) = reload_fixture(0, 90);
    before_tick(&mut s, &cfg, fire(), 216);
    assert_eq!(
        (s.player.ammo, s.player.reserve),
        (0, 90),
        "credit occurred before 1.800 s"
    );
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(
        (s.player.ammo, s.player.reserve),
        (30, 60),
        "credit missing at 1.800 s"
    );
    assert!(s.player.reload_left > 0.);
    before_tick(&mut s, &cfg, fire(), 306);
    assert!(s.events.is_empty(), "empty reload fired before 2.550 s");
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(
        s.events.len(),
        1,
        "empty-ready milestone did not precede fire input"
    );
    assert!((s.events[0].time - 2.550).abs() < EPS);
    assert_eq!((s.player.ammo, s.player.reserve), (29, 60));
}

#[test]
fn tactical_sprint_cancel_before_at_and_after_credit_conserves_ammo_exactly_once() {
    for (cancel_tick, expected_ammo, expected_reserve) in
        [(161, 7, 90), (162, 30, 67), (163, 30, 67)]
    {
        let (mut s, cfg) = reload_fixture(7, 90);
        before_tick(&mut s, &cfg, Input::default(), cancel_tick);
        s.update(sprint(), &cfg, FIXED_DT);
        assert_eq!(
            s.player.reload_left, 0.,
            "reload not cancelled at tick {cancel_tick}"
        );
        assert!(
            s.player.sprinting,
            "sprint did not begin at tick {cancel_tick}"
        );
        assert_eq!(
            (s.player.ammo, s.player.reserve),
            (expected_ammo, expected_reserve),
            "wrong credit order at cancel tick {cancel_tick}"
        );
        ticks(&mut s, &cfg, Input::default(), 360);
        assert_eq!(
            (s.player.ammo, s.player.reserve),
            (expected_ammo, expected_reserve),
            "cancelled reload credited later/twice at tick {cancel_tick}"
        );
        assert_eq!(s.player.ammo + s.player.reserve, 97);
    }
}

#[test]
fn cancelling_tactical_reload_then_reloading_cannot_duplicate_ammo() {
    for cancel_tick in [161, 162, 163] {
        let (mut s, cfg) = reload_fixture(7, 90);
        before_tick(&mut s, &cfg, Input::default(), cancel_tick);
        s.update(sprint(), &cfg, FIXED_DT);
        s.update(
            Input {
                reload: true,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
        ticks(&mut s, &cfg, Input::default(), 350);
        assert_eq!(
            (s.player.ammo, s.player.reserve),
            (30, 67),
            "restart after cancellation at {cancel_tick} changed total ammunition"
        );
    }
}

#[test]
fn empty_reload_cannot_be_interrupted_before_at_or_after_credit() {
    for attempt_tick in [1, 100, 215, 216, 217, 305] {
        let (mut s, cfg) = reload_fixture(0, 90);
        before_tick(&mut s, &cfg, Input::default(), attempt_tick);
        s.update(sprint(), &cfg, FIXED_DT);
        assert!(
            !s.player.sprinting,
            "empty reload interrupted at tick {attempt_tick}"
        );
        assert!(
            s.player.reload_left > 0.,
            "empty reload ended before ready at {attempt_tick}"
        );
        before_tick(&mut s, &cfg, sprint(), 306);
        assert!(!s.player.sprinting);
        s.update(sprint(), &cfg, FIXED_DT);
        assert!(
            s.player.sprinting,
            "sprint blocked after empty reload completion"
        );
        assert_eq!(s.player.reload_left, 0.);
        assert_eq!((s.player.ammo, s.player.reserve), (30, 60));
    }
}

#[test]
fn due_credit_is_processed_before_simultaneous_sprint_and_new_reload_request() {
    let (mut s, cfg) = reload_fixture(7, 90);
    before_tick(&mut s, &cfg, Input::default(), 162);
    s.update(
        Input {
            reload: true,
            ..sprint()
        },
        &cfg,
        FIXED_DT,
    );
    assert_eq!((s.player.ammo, s.player.reserve), (30, 67));
    assert_eq!(
        s.player.reload_left, 0.,
        "new reload restarted before due ammo credit was applied"
    );
    assert!(s.player.sprinting);
}

#[test]
fn due_ready_is_processed_before_simultaneous_fire_and_reload_request() {
    for (ammo, ready_tick) in [(7, 234), (0, 306)] {
        let (mut s, cfg) = reload_fixture(ammo, 90);
        before_tick(&mut s, &cfg, Input::default(), ready_tick);
        s.update(
            Input {
                reload: true,
                ..fire()
            },
            &cfg,
            FIXED_DT,
        );
        assert_eq!(
            s.events.len(),
            1,
            "ready tick {ready_tick} did not accept fire"
        );
        assert_eq!(s.player.ammo, 29);
        assert_eq!(s.player.reload_left, 0.);
    }
}

#[test]
fn partial_reserve_reload_transfers_only_available_rounds() {
    for (ammo, reserve, expected) in [(7, 10, 17), (0, 10, 10), (29, 1, 30)] {
        let (mut s, cfg) = reload_fixture(ammo, reserve);
        ticks(
            &mut s,
            &cfg,
            Input {
                reload: true,
                ..Input::default()
            },
            700,
        );
        assert_eq!((s.player.ammo, s.player.reserve), (expected, 0));
        assert_eq!(s.player.reload_left, 0.);
    }
}

#[test]
fn full_magazine_and_zero_reserve_reject_reload_without_blocking_fire() {
    for (ammo, reserve) in [(30, 90), (7, 0)] {
        let mut s = Simulation::new();
        let cfg = Settings::default();
        s.player.ammo = ammo;
        s.player.reserve = reserve;
        s.update(
            Input {
                reload: true,
                ..fire()
            },
            &cfg,
            FIXED_DT,
        );
        assert_eq!(s.events.len(), 1);
        assert_eq!(s.player.ammo, ammo - 1);
        assert_eq!(s.player.reload_left, 0.);
    }
}

#[test]
fn sprint_to_fire_is_blocked_for_200ms_then_fires_on_due_tick() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    ticks(&mut s, &cfg, sprint(), 40);
    assert!(s.player.sprinting);
    let release = s.time;
    let input = Input {
        fire: true,
        ..sprint()
    };
    ticks(&mut s, &cfg, input, 24);
    assert!(s.events.is_empty(), "weapon fired before 200 ms sprint-out");
    s.update(input, &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 1, "weapon not ready at 200 ms sprint-out");
    assert!((s.events[0].time - release - 0.200).abs() < EPS);
}

#[test]
fn fire_release_repress_does_not_cancel_sprint_out() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    ticks(&mut s, &cfg, sprint(), 10);
    let release = s.time;
    for tick in 0..24 {
        s.update(
            Input {
                fire: tick % 2 == 0,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
        assert!(
            s.events.is_empty(),
            "repress bypassed sprint-out at tick {tick}"
        );
    }
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 1);
    assert!((s.events[0].time - release - 0.200).abs() < EPS);
}

#[test]
fn ads_in_220ms_and_out_160ms_have_one_tick_quantization_only() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    for tick in 1..=27 {
        s.update(ads(), &cfg, FIXED_DT);
        approximately(
            s.player.ads,
            ((tick as f32 * FIXED_DT) / 0.220).min(1.),
            2e-6,
            "ADS-in progression",
        );
        if tick <= 26 {
            assert!(s.player.ads < 1.);
        }
    }
    assert_eq!(s.player.ads, 1.);
    for tick in 1..=20 {
        s.update(Input::default(), &cfg, FIXED_DT);
        approximately(
            s.player.ads,
            (1. - tick as f32 * FIXED_DT / 0.160).max(0.),
            2e-6,
            "ADS-out progression",
        );
        if tick <= 19 {
            assert!(s.player.ads > 0.);
        }
    }
    assert_eq!(s.player.ads, 0.);
}

#[test]
fn ads_reversal_preserves_progress_without_snapping() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    ticks(&mut s, &cfg, ads(), 12);
    let progress = s.player.ads;
    s.update(Input::default(), &cfg, FIXED_DT);
    approximately(
        s.player.ads,
        progress - FIXED_DT / 0.160,
        2e-6,
        "ADS reversal out",
    );
    let reversed = s.player.ads;
    s.update(ads(), &cfg, FIXED_DT);
    approximately(
        s.player.ads,
        reversed + FIXED_DT / 0.220,
        2e-6,
        "ADS reversal in",
    );
}

#[test]
fn recoil_never_changes_raw_look_and_settles_below_point02_degrees_in_450ms() {
    for use_ads in [false, true] {
        let mut s = Simulation::new();
        let cfg = Settings::default();
        s.player.yaw = -0.83;
        s.player.pitch = 0.17;
        let input = Input {
            ads: use_ads,
            ..Input::default()
        };
        ticks(&mut s, &cfg, input, 30);
        let look = (s.player.yaw, s.player.pitch);
        s.update(
            Input {
                fire: true,
                ..input
            },
            &cfg,
            FIXED_DT,
        );
        let shot_time = s.events[0].time;
        assert!(
            s.player.recoil.length() > 0.001,
            "shot did not apply visible recoil"
        );
        assert_eq!((s.player.yaw, s.player.pitch), look);
        while s.time - shot_time + EPS < 0.450 {
            s.update(input, &cfg, FIXED_DT);
        }
        assert!(
            s.player.recoil.length().to_degrees() < 0.02,
            "ADS={use_ads}: recoil {} degrees after {:.6}s",
            s.player.recoil.length().to_degrees(),
            s.time - shot_time
        );
        assert_eq!(
            (s.player.yaw, s.player.pitch),
            look,
            "return changed raw look"
        );
    }
}

#[test]
fn sustained_fire_has_finite_bounded_recoil_separate_from_look() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    let look = (s.player.yaw, s.player.pitch);
    ticks(&mut s, &cfg, fire(), 315);
    assert_eq!((s.player.yaw, s.player.pitch), look);
    assert!(s.player.recoil.is_finite());
    assert!(s.player.recoil.x.to_degrees() <= 6. + 1e-5);
    assert!(s.player.recoil.y.to_degrees().abs() <= 2. + 1e-5);
    ticks(&mut s, &cfg, Input::default(), 60);
    assert!(s.player.recoil.length().to_degrees() < 0.02);
}

#[test]
fn hip_bloom_caps_at_2point4_and_recovers_at_4degrees_per_second_after_100ms() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    ticks(&mut s, &cfg, fire(), 90);
    approximately(s.player.bloom, 2.4, 1e-6, "hip bloom cap");
    let last_shot = s.events.last().unwrap().time;
    let initial = s.player.bloom;
    let mut decay_ticks = 0;
    for _ in 0..100 {
        let elapsed_before_update = s.time - last_shot;
        if elapsed_before_update >= 0.100 - EPS {
            decay_ticks += 1;
        }
        s.update(Input::default(), &cfg, FIXED_DT);
        let expected = (initial - decay_ticks as f32 * FIXED_DT * 4.).max(0.);
        approximately(s.player.bloom, expected, 2e-5, "bloom recovery curve");
        assert!((0. ..=2.4).contains(&s.player.bloom));
    }
    assert_eq!(s.player.bloom, 0.);
}

#[test]
fn fully_aimed_fire_does_not_add_hip_bloom() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    ticks(&mut s, &cfg, ads(), 30);
    ticks(
        &mut s,
        &cfg,
        Input {
            fire: true,
            ..ads()
        },
        90,
    );
    assert!(s.events.len() >= 8);
    assert_eq!(s.player.bloom, 0.);
    for shot in &s.events {
        approximately(shot.spread_degrees, 0.08, 2e-6, "fully aimed spread");
    }
}

#[test]
fn spread_settings_and_extra_spread_queries_do_not_perturb_recoil_sequence() {
    let mut baseline = Simulation::new();
    let mut changed = Simulation::new();
    let a_cfg = Settings::default();
    let b_cfg = Settings {
        hip_spread: 0.,
        ads_spread: 0.,
        ..Settings::default()
    };
    for tick in 0..200 {
        for _ in 0..(tick % 7) {
            let _ = changed.spread_degrees(&b_cfg);
        }
        baseline.update(fire(), &a_cfg, FIXED_DT);
        changed.update(fire(), &b_cfg, FIXED_DT);
        assert_eq!(
            baseline.player.recoil, changed.player.recoil,
            "spread perturbation changed recoil at tick {tick}"
        );
        assert_eq!(baseline.stats.shots, changed.stats.shots);
    }
    assert_ne!(baseline.events[0].direction, changed.events[0].direction);
}

#[test]
fn recoil_settings_do_not_perturb_spread_sequence_when_aim_is_held_constant() {
    let mut baseline = Simulation::new();
    let mut changed = Simulation::new();
    let a_cfg = Settings::default();
    let b_cfg = Settings {
        recoil_pitch: 3.,
        recoil_return: 7.,
        ..Settings::default()
    };
    let mut different_recoil_seen = false;
    for _ in 0..200 {
        // These public fixture edits eliminate aim-direction consequences of
        // recoil while preserving private RNG state and authored firing cadence.
        baseline.player.recoil = Vec2::ZERO;
        changed.player.recoil = Vec2::ZERO;
        baseline.player.recoil_velocity = Vec2::ZERO;
        changed.player.recoil_velocity = Vec2::ZERO;
        baseline.update(fire(), &a_cfg, FIXED_DT);
        changed.update(fire(), &b_cfg, FIXED_DT);
        different_recoil_seen |= baseline.player.recoil != changed.player.recoil;
        assert_eq!(baseline.events.len(), changed.events.len());
        if let (Some(a), Some(b)) = (baseline.events.last(), changed.events.last()) {
            assert_eq!(
                a.direction, b.direction,
                "recoil tuning perturbed independent spread samples"
            );
            assert_eq!(a.spread_degrees, b.spread_degrees);
        }
    }
    assert!(
        different_recoil_seen,
        "fixture did not actually perturb recoil"
    );
}

#[test]
fn reset_restores_repeatable_shot_and_recoil_sequences() {
    let cfg = Settings::default();
    let mut s = Simulation::new();
    ticks(&mut s, &cfg, fire(), 200);
    let first: Vec<_> = s
        .events
        .iter()
        .map(|e| (e.time, e.direction, e.spread_degrees))
        .collect();
    let first_recoil = s.player.recoil;
    s.reset();
    assert_eq!((s.player.ammo, s.player.reserve), (30, 90));
    assert!(s.events.is_empty());
    assert_eq!(s.time, 0.);
    ticks(&mut s, &cfg, fire(), 200);
    let second: Vec<_> = s
        .events
        .iter()
        .map(|e| (e.time, e.direction, e.spread_degrees))
        .collect();
    assert_eq!(first, second);
    assert_eq!(first_recoil, s.player.recoil);
}

#[test]
fn spread_rays_are_finite_normalized_and_inside_declared_cone() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    for _ in 0..315 {
        let aim = s.player.direction();
        let prior_count = s.events.len();
        s.update(fire(), &cfg, FIXED_DT);
        if s.events.len() > prior_count {
            let shot = s.events.last().unwrap();
            assert!(shot.direction.is_finite());
            approximately(shot.direction.length(), 1., 2e-6, "unit shot direction");
            let angle = aim.dot(shot.direction).clamp(-1., 1.).acos().to_degrees();
            assert!(
                angle <= shot.spread_degrees + 0.005,
                "shot outside cone: {angle} > {}",
                shot.spread_degrees
            );
            assert!(shot.start.is_finite() && shot.end.is_finite());
            assert_ne!(shot.direction, Vec3::ZERO);
        }
    }
}

#[test]
fn render_partitioning_produces_identical_120hz_weapon_replay() {
    fn replay(fps: usize) -> Simulation {
        let mut s = Simulation::new();
        let cfg = Settings::default();
        let mut accumulator = 0_f64;
        let mut step = 0;
        for _ in 0..fps * 4 {
            accumulator += 1. / fps as f64;
            while accumulator + 1e-10 >= 1. / 120. {
                let input = Input {
                    fire: (0..100).contains(&step) || step >= 380,
                    reload: step == 120,
                    ads: step >= 380,
                    ..Input::default()
                };
                s.update(input, &cfg, FIXED_DT);
                accumulator -= 1. / 120.;
                step += 1;
            }
        }
        assert_eq!(step, 480);
        s
    }
    let a = replay(30);
    for fps in [60, 75, 120, 144, 240] {
        let b = replay(fps);
        assert_eq!(a.time, b.time);
        assert_eq!(
            (a.player.ammo, a.player.reserve),
            (b.player.ammo, b.player.reserve)
        );
        assert_eq!(a.player.ads, b.player.ads);
        assert_eq!(a.player.recoil, b.player.recoil);
        assert_eq!(a.player.bloom, b.player.bloom);
        let events = |s: &Simulation| {
            s.events
                .iter()
                .map(|e| (e.time, e.direction, e.spread_degrees))
                .collect::<Vec<_>>()
        };
        assert_eq!(
            events(&a),
            events(&b),
            "render partition {fps} FPS changed simulation"
        );
    }
}

#[test]
fn resuming_fire_after_long_idle_never_catches_up_missed_shots() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    s.update(fire(), &cfg, FIXED_DT);
    before_tick(&mut s, &cfg, Input::default(), 600);
    let resumed_at = s.time;
    ticks(&mut s, &cfg, fire(), 100);
    assert_eq!(s.events[1].time, resumed_at);
    for (index, shot) in s.events.iter().skip(1).enumerate() {
        let deadline = resumed_at + index as f64 * SHOT_INTERVAL;
        assert!(
            shot.time >= deadline - EPS && shot.time < deadline + TICK + EPS,
            "resumed shot {index} timestamp {} differs from {deadline}",
            shot.time
        );
    }
}

#[test]
fn dry_fire_with_zero_reserve_never_reloads_or_creates_rounds() {
    let mut s = Simulation::new();
    let cfg = Settings::default();
    s.player.ammo = 0;
    s.player.reserve = 0;
    for tick in 0..600 {
        s.update(
            Input {
                reload: tick % 2 == 0,
                ..fire()
            },
            &cfg,
            FIXED_DT,
        );
        assert_eq!((s.player.ammo, s.player.reserve), (0, 0));
        assert_eq!(s.player.reload_left, 0.);
        assert_eq!(s.stats.shots, 0);
        assert!(s.events.is_empty());
    }
}

#[test]
fn mixed_reload_sprint_ads_and_fire_inputs_conserve_every_round() {
    for seed in [1_u32, 0x1234abcd, 0xfedc9876] {
        let mut random = seed;
        let mut s = Simulation::new();
        let cfg = Settings::default();
        for tick in 0..5000 {
            // Test-local deterministic input generator, unrelated to the weapon RNG.
            random ^= random << 13;
            random ^= random >> 17;
            random ^= random << 5;
            let input = if tick % 1200 >= 600 {
                // Include uninterrupted windows so the fixture necessarily
                // completes reloads as well as exercising cancellation storms.
                fire()
            } else {
                Input {
                    fire: random & 3 == 0,
                    reload: random & 31 == 1,
                    sprint: random & 7 == 2,
                    ads: random & 15 == 3,
                    movement: if random & 7 == 2 {
                        vec2(0., 1.)
                    } else {
                        Vec2::ZERO
                    },
                    ..Input::default()
                }
            };
            s.update(input, &cfg, FIXED_DT);
            assert!(
                s.player.ammo <= 30,
                "seed {seed}, tick {tick}: overfull magazine"
            );
            assert_eq!(
                s.player.ammo + s.player.reserve + s.stats.shots,
                120,
                "seed {seed}, tick {tick}: rounds duplicated or lost"
            );
            assert_eq!(s.events.len(), s.stats.shots as usize);
        }
        assert!(
            s.stats.shots >= 60,
            "seed {seed}: mixed-input fixture did not exercise multiple magazines"
        );
    }
}
