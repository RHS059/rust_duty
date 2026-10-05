//! Public-API tests for a provisional M4A1-inspired game-behavior profile.
//! These validate this implementation, not equivalence to a retail game.
use glam::vec2;
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};
use vector_range::{
    clock::FixedClock,
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT, MAGAZINE},
};

const EPS: f64 = 2e-6;
const TICK: f64 = FIXED_DT as f64;
const INTERVAL: f64 = 0.070;

fn approximately(actual: f32, expected: f32, tolerance: f32) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "got {actual}, expected {expected} +/- {tolerance}"
    );
}
fn ticks(s: &mut Simulation, cfg: &Settings, input: Input, count: usize) {
    for _ in 0..count {
        s.update(input, cfg, FIXED_DT);
    }
}
fn fire() -> Input {
    Input {
        fire: true,
        ..Input::default()
    }
}
fn ads() -> Input {
    Input {
        ads: true,
        ..Input::default()
    }
}
fn sprint() -> Input {
    Input {
        movement: vec2(0., 1.),
        sprint: true,
        ..Input::default()
    }
}
fn before_tick(s: &mut Simulation, cfg: &Settings, input: Input, target: usize) {
    let wanted = target as f64 * TICK;
    assert!(s.time <= wanted + EPS);
    while s.time + EPS < wanted {
        s.update(input, cfg, FIXED_DT);
    }
    assert!((s.time - wanted).abs() < EPS);
}
fn config_file(contents: &str) -> PathBuf {
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    let path = std::env::temp_dir().join(format!(
        "vector-m4-settings-{}-{}.cfg",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    ));
    fs::write(&path, contents).unwrap();
    path
}
fn reload_fixture(ammo: u32, reserve: u32) -> (Simulation, Settings) {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
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
    assert!(s.player.reload_left > 0.);
    (s, cfg)
}

#[test]
fn candidate_values_are_separate_from_authored_defaults() {
    let c = Settings::m4_candidate();
    let d = Settings::default();
    assert_eq!(MAGAZINE, 30);
    assert!((60. / c.fire_rpm as f64 - INTERVAL).abs() < 1e-8);
    assert!((60. / d.fire_rpm as f64 - 0.090).abs() < 1e-8);
    assert_eq!(c.ads_time, 0.250);
    assert_eq!(c.ads_out_time, 0.250); // Explicit symmetric-transition assumption.
    assert_eq!(c.sprint_out_time, 0.300);
    assert_eq!(c.reload_credit, 1.100);
    assert_eq!(c.reload_time, 2.029);
    assert_eq!(c.empty_reload_time, 2.359);
    assert_eq!(c.empty_reload_credit, 1.800); // Explicit authored fallback.
    assert_eq!(c.ads_move_multiplier, 0.40);
    assert_eq!(d.ads_move_multiplier, 0.50);
    approximately(c.walk_speed, d.walk_speed * 0.95, 1e-6);
    approximately(c.sprint_speed, c.walk_speed * 1.5, 1e-6);
    approximately(c.crouch_speed, c.walk_speed * 0.65, 1e-6);
    assert_eq!(c.hip_spread, d.hip_spread);
    assert_eq!(c.ads_spread, d.ads_spread);
    assert_eq!(c.recoil_pitch, d.recoil_pitch);
    assert_eq!(c.recoil_return, d.recoil_return);
    assert_eq!(c.fov, d.fov);
    assert_eq!(c.ads_fov, d.ads_fov);
    assert_eq!(d.ads_time, 0.220);
    assert_eq!(d.ads_out_time, 0.160);
    assert_eq!(d.reload_time, 1.950);
    assert_eq!(d.empty_reload_time, 2.550);
}

#[test]
fn shipped_profile_matches_constructor() {
    let file = Settings::load(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/profiles/m4a1-candidate.cfg"
    ));
    let mut expected = Settings::m4_candidate();
    // Decimal text and arithmetic may differ by one f32 rounding unit.
    approximately(file.fire_rpm, expected.fire_rpm, 0.0001);
    approximately(file.walk_speed, expected.walk_speed, 1e-6);
    approximately(file.sprint_speed, expected.sprint_speed, 1e-6);
    approximately(file.crouch_speed, expected.crouch_speed, 1e-6);
    expected.fire_rpm = file.fire_rpm;
    expected.walk_speed = file.walk_speed;
    expected.sprint_speed = file.sprint_speed;
    expected.crouch_speed = file.crouch_speed;
    assert_eq!(file, expected);
}

#[test]
fn partial_and_missing_files_preserve_selected_profile() {
    let path = config_file("sensitivity = 0.2\nfire_rpm = NaN\nwalk_speed = inf\nunknown = 1\n");
    let mut expected = Settings::m4_candidate();
    expected.sensitivity = 0.2;
    assert_eq!(
        Settings::load_with_base(&path, Settings::m4_candidate()),
        expected
    );
    // The original loader still starts with the Kestrel preset.
    assert_eq!(Settings::load(&path).ads_time, Settings::default().ads_time);
    fs::remove_file(&path).unwrap();
    assert_eq!(
        Settings::load_with_base(&path, Settings::m4_candidate()),
        Settings::m4_candidate()
    );
}

#[test]
fn ads_movement_setting_is_clamped_finite_and_saved() {
    for (text, expected) in [("-5", 0.), ("7", 1.), ("NaN", 0.4), ("inf", 0.4)] {
        let path = config_file(&format!("ads_move_multiplier = {text}\n"));
        let loaded = Settings::load_with_base(&path, Settings::m4_candidate());
        assert_eq!(loaded.ads_move_multiplier, expected);
        fs::remove_file(path).unwrap();
    }
    let path = config_file("");
    Settings::m4_candidate().save(&path).unwrap();
    let saved = fs::read_to_string(&path).unwrap();
    assert!(saved.contains("ads_move_multiplier = 0.4000"));
    let loaded = Settings::load(&path);
    assert_eq!(loaded.ads_move_multiplier, 0.4);
    assert_eq!(loaded.reload_time, 2.029);
    assert!((60. / loaded.fire_rpm as f64 - INTERVAL).abs() < 1e-8);
    fs::remove_file(path).unwrap();
}

#[test]
fn full_magazine_preserves_fractional_70ms_deadlines_at_120hz() {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
    ticks(&mut s, &cfg, fire(), 245);
    assert_eq!(s.events.len(), 30);
    assert_eq!((s.player.ammo, s.player.reserve), (0, 90));
    for (index, shot) in s.events.iter().enumerate() {
        let scheduled = index as f64 * INTERVAL;
        assert!(shot.time >= scheduled - EPS, "shot {index} early");
        assert!(
            shot.time < scheduled + TICK + EPS,
            "shot {index} drifted: {}",
            shot.time
        );
    }
    assert!((s.events[29].time - 2.030).abs() < TICK + EPS);
    // A rounded 9-tick cadence would put the final shot at 2.175 s.
    assert!(s.events[29].time < 2.040);
    assert!(s
        .events
        .windows(2)
        .any(|pair| pair[1].time - pair[0].time < 0.070));
    assert!(s
        .events
        .windows(2)
        .any(|pair| pair[1].time - pair[0].time > 0.070));
}

fn ten_second_trace(fps: usize, replenish: bool) -> Simulation {
    let cfg = Settings::m4_candidate();
    let mut clock = FixedClock::default();
    let mut s = Simulation::new();
    let mut tick_count = 0;
    for _ in 0..fps * 10 {
        // The same f32 frame deltas used by the native frontend.
        for _ in 0..clock.advance((1_f32 / fps as f32) as f64).unwrap() {
            if replenish {
                // Diagnostic supply prevents reload downtime, without bypassing
                // any cadence/trigger gate. A separate test uses real ammo.
                s.player.ammo = MAGAZINE;
            }
            s.update(
                Input {
                    ads: true,
                    ..fire()
                },
                &cfg,
                FIXED_DT,
            );
            tick_count += 1;
        }
    }
    assert_eq!(tick_count, 1200);
    s
}

#[test]
fn ten_seconds_yields_143_shots_without_drift_at_all_render_rates() {
    let baseline = ten_second_trace(30, true);
    assert_eq!(baseline.events.len(), 143); // Deadlines 0, .070, ..., 9.940 in [0, 10).
    for (index, shot) in baseline.events.iter().enumerate() {
        let due = index as f64 * INTERVAL;
        assert!(shot.time >= due - EPS && shot.time < due + TICK + EPS);
    }
    for fps in [60, 120, 144, 240] {
        let s = ten_second_trace(fps, true);
        assert_eq!(s.events.len(), 143, "{fps} FPS");
        assert_eq!(s.time, baseline.time);
        assert_eq!(s.player.recoil, baseline.player.recoil);
        for (shot, original) in s.events.iter().zip(&baseline.events) {
            assert_eq!(shot.time, original.time, "{fps} FPS");
            assert_eq!(shot.direction, original.direction, "{fps} FPS");
            assert_eq!(shot.spread_degrees, original.spread_degrees, "{fps} FPS");
        }
    }
}

#[test]
fn render_rate_invariance_includes_real_reload_and_ammunition() {
    let baseline = ten_second_trace(30, false);
    assert!(baseline.stats.shots > MAGAZINE * 2);
    assert_eq!(
        baseline.player.ammo + baseline.player.reserve + baseline.stats.shots,
        120
    );
    for fps in [60, 120, 144, 240] {
        let s = ten_second_trace(fps, false);
        assert_eq!(s.stats.shots, baseline.stats.shots);
        assert_eq!(
            (s.player.ammo, s.player.reserve),
            (baseline.player.ammo, baseline.player.reserve)
        );
        assert_eq!(s.player.reload_left, baseline.player.reload_left);
        assert_eq!(s.player.reload_credit_at, baseline.player.reload_credit_at);
        assert_eq!(s.player.reload_ready_at, baseline.player.reload_ready_at);
        for (shot, original) in s.events.iter().zip(&baseline.events) {
            assert_eq!(shot.time, original.time);
            assert_eq!(shot.direction, original.direction);
        }
    }
}

#[test]
fn release_on_first_due_tick_prevents_shot_and_idle_does_not_catch_up() {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
    ticks(&mut s, &cfg, fire(), 9); // Last sampled timestamp 66.667 ms.
    assert_eq!(s.events.len(), 1);
    s.update(Input::default(), &cfg, FIXED_DT); // Release at first eligible 75 ms tick.
    assert_eq!(s.events.len(), 1);
    before_tick(&mut s, &cfg, Input::default(), 120);
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 2);
    assert!((s.events[1].time - 1.).abs() < EPS);
    before_tick(&mut s, &cfg, fire(), 129);
    assert_eq!(s.events.len(), 2);
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 3);
    assert!((s.events[2].time - 1.075).abs() < EPS);
}

#[test]
fn rapid_taps_cannot_bypass_70ms_cooldown() {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
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
    assert!(s.events.len() > 20 && s.events.len() <= 29);
    for pair in s.events.windows(2) {
        assert!(pair[1].time - pair[0].time >= INTERVAL - EPS);
    }
}

#[test]
fn candidate_ads_in_and_symmetric_out_follow_250ms_transitions() {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
    for tick in 1..=30 {
        s.update(ads(), &cfg, FIXED_DT);
        approximately(s.player.ads, (tick as f32 * FIXED_DT / 0.250).min(1.), 2e-6);
        if tick < 30 {
            assert!(s.player.ads < 1.);
        }
    }
    assert_eq!(s.player.ads, 1.);
    for tick in 1..=30 {
        s.update(Input::default(), &cfg, FIXED_DT);
        approximately(
            s.player.ads,
            (1. - tick as f32 * FIXED_DT / 0.250).max(0.),
            2e-6,
        );
    }
    // Float accumulation at the zero endpoint is bounded, never a visible snap.
    s.update(Input::default(), &cfg, FIXED_DT);
    assert_eq!(s.player.ads, 0.);
}

#[test]
fn candidate_ads_reversal_uses_current_progress() {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
    ticks(&mut s, &cfg, ads(), 12);
    let partial = s.player.ads;
    s.update(Input::default(), &cfg, FIXED_DT);
    approximately(s.player.ads, partial - FIXED_DT / 0.250, 1e-6);
    s.update(ads(), &cfg, FIXED_DT);
    approximately(s.player.ads, partial, 1e-6);
}

#[test]
fn candidate_sprint_out_blocks_fire_for_300ms() {
    let mut s = Simulation::new();
    let cfg = Settings::m4_candidate();
    ticks(&mut s, &cfg, sprint(), 40);
    assert!(s.player.sprinting);
    let released = s.time;
    ticks(&mut s, &cfg, fire(), 36);
    assert!(s.events.is_empty());
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 1);
    assert!((s.events[0].time - released - 0.300).abs() < EPS);
}

#[test]
fn candidate_tactical_reload_credits_at_1100ms_once_and_waits_for_2029ms() {
    let (mut s, cfg) = reload_fixture(7, 10);
    before_tick(&mut s, &cfg, fire(), 132);
    assert_eq!((s.player.ammo, s.player.reserve), (7, 10));
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!((s.player.ammo, s.player.reserve), (17, 0));
    assert!(s.player.reload_credited);
    before_tick(&mut s, &cfg, fire(), 244);
    assert!(s.events.is_empty());
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 1);
    let first = s.events[0].time;
    assert!((2.029 - EPS..2.029 + TICK + EPS).contains(&first));
    assert_eq!((s.player.ammo, s.player.reserve), (16, 0));
    ticks(&mut s, &cfg, Input::default(), 300);
    assert_eq!((s.player.ammo, s.player.reserve), (16, 0));
}

#[test]
fn candidate_empty_reload_keeps_declared_1800ms_credit_and_2359ms_ready() {
    let (mut s, cfg) = reload_fixture(0, 40);
    before_tick(&mut s, &cfg, fire(), 216);
    assert_eq!((s.player.ammo, s.player.reserve), (0, 40));
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!((s.player.ammo, s.player.reserve), (30, 10));
    before_tick(&mut s, &cfg, fire(), 284);
    assert!(s.events.is_empty());
    s.update(fire(), &cfg, FIXED_DT);
    assert_eq!(s.events.len(), 1);
    let first = s.events[0].time;
    assert!((2.359 - EPS..2.359 + TICK + EPS).contains(&first));
    assert_eq!((s.player.ammo, s.player.reserve), (29, 10));
}

#[test]
fn tactical_cancel_before_at_after_credit_has_no_stale_or_duplicate_transfer() {
    for cancel_tick in [131, 132, 133] {
        let (mut s, cfg) = reload_fixture(7, 10);
        before_tick(&mut s, &cfg, Input::default(), cancel_tick);
        s.update(sprint(), &cfg, FIXED_DT);
        assert!(s.player.sprinting);
        assert_eq!(s.player.reload_left, 0.);
        let expected = if cancel_tick < 132 { (7, 10) } else { (17, 0) };
        assert_eq!((s.player.ammo, s.player.reserve), expected);
        ticks(&mut s, &cfg, Input::default(), 300);
        assert_eq!((s.player.ammo, s.player.reserve), expected);
        assert_eq!(s.player.ammo + s.player.reserve, 17);
    }
}

#[test]
fn empty_reload_stays_uninterruptible_at_its_authored_credit_boundary() {
    for cancel_tick in [215, 216, 217] {
        let (mut s, cfg) = reload_fixture(0, 40);
        before_tick(&mut s, &cfg, Input::default(), cancel_tick);
        s.update(sprint(), &cfg, FIXED_DT);
        assert!(!s.player.sprinting);
        assert!(s.player.reload_left > 0.);
        before_tick(&mut s, &cfg, sprint(), 284);
        s.update(sprint(), &cfg, FIXED_DT);
        assert!(s.player.sprinting);
        assert_eq!((s.player.ammo, s.player.reserve), (30, 10));
    }
}

#[test]
fn movement_applies_weapon_scale_once_and_ads_is_40_percent_of_normal() {
    let cfg = Settings::m4_candidate();
    let mut speeds = Vec::new();
    for input in [
        Input {
            movement: vec2(0., 1.),
            ..Input::default()
        },
        Input {
            movement: vec2(0., 1.),
            ads: true,
            ..Input::default()
        },
        sprint(),
        Input {
            movement: vec2(0., 1.),
            crouch: true,
            ..Input::default()
        },
    ] {
        let mut s = Simulation::new();
        ticks(&mut s, &cfg, input, 120);
        speeds.push(s.player.speed());
    }
    approximately(speeds[0], 4.826 * 0.95, 1e-5);
    approximately(speeds[1], 4.826 * 0.38, 1e-5);
    approximately(speeds[1] / speeds[0], 0.40, 1e-6);
    approximately(speeds[2] / speeds[0], 1.5, 1e-6);
    approximately(speeds[3] / speeds[0], 0.65, 1e-6);
}

#[test]
fn historical_800rpm_override_remains_a_distinct_comparison() {
    let path = config_file("fire_rpm = 800\n");
    let cfg = Settings::load_with_base(&path, Settings::m4_candidate());
    fs::remove_file(path).unwrap();
    assert_eq!(cfg.ads_time, 0.250);
    let mut s = Simulation::new();
    ticks(&mut s, &cfg, fire(), 263);
    assert_eq!(s.events.len(), 30);
    assert!((s.events[29].time - 2.175).abs() < EPS);
    assert!((60. / cfg.fire_rpm as f64 - 0.075).abs() < EPS);
}
