use vector_range::authored_jump::{AuthoredJump, JumpInput, JumpPhase};

fn jump() -> AuthoredJump {
    AuthoredJump::new(11. / 60., 23. / 60., 28. / 60.).unwrap()
}
fn input(at: f64, grounded: bool) -> JumpInput {
    JumpInput {
        accepted_jump_at: at,
        grounded,
        eligible: true,
    }
}

#[test]
fn accepted_launch_uses_native_time_and_air_endpoint_holds_without_looping() {
    let mut j = jump();
    j.committed_step(0., 0.1, input(0., false)).unwrap();
    let s = j.sample().unwrap();
    assert_eq!(s.phase, JumpPhase::Takeoff);
    assert_eq!(s.seconds, 0.1);
    j.committed_step(0.1, 0.4, input(0., false)).unwrap();
    let s = j.sample().unwrap();
    assert_eq!(s.phase, JumpPhase::Air);
    assert!((s.seconds - (0.4 - 11. / 60.)).abs() < 1e-12);
    j.committed_step(0.4, 8., input(0., false)).unwrap();
    let held = j.sample().unwrap();
    assert_eq!(held.seconds, 23. / 60.);
    assert!(held.holding_air_endpoint);
    j.committed_step(8., 9., input(0., false)).unwrap();
    assert_eq!(j.sample().unwrap().seconds, held.seconds);
}

#[test]
fn actual_early_and_late_ground_contact_start_landing_without_reference_deadline() {
    for contact in [0.08, 0.6245, 4.] {
        let mut j = jump();
        j.committed_step(0., contact / 2., input(0., false))
            .unwrap();
        j.committed_step(contact / 2., contact, input(0., true))
            .unwrap();
        let s = j.sample().unwrap();
        assert_eq!(s.phase, JumpPhase::Land);
        assert_eq!(s.seconds, 0.);
        assert_eq!(s.transition_seconds, 0.);
        j.committed_step(contact, contact + 0.1, input(0., true))
            .unwrap();
        assert!((j.sample().unwrap().seconds - 0.1).abs() < 1e-12);
        j.committed_step(contact + 0.1, contact + 1., input(0., true))
            .unwrap();
        assert!(j.sample().is_none());
    }
}

#[test]
fn falls_rejected_input_and_old_accepted_timestamps_cannot_create_jump() {
    let mut j = jump();
    j.committed_step(0., 0.1, input(-10., true)).unwrap();
    j.committed_step(0.1, 0.2, input(-10., false)).unwrap();
    j.committed_step(0.2, 0.3, input(-10., true)).unwrap();
    assert!(j.sample().is_none());
    j.reset(5.).unwrap();
    j.committed_step(5., 5.1, input(3., false)).unwrap();
    assert!(j.sample().is_none());
}

#[test]
fn repeated_or_held_jump_cannot_restart_but_new_accepted_launch_can() {
    let mut j = jump();
    j.committed_step(0., 0.1, input(0., false)).unwrap();
    let first = j.sample().unwrap().transition_serial;
    j.committed_step(0.1, 0.3, input(0., false)).unwrap();
    assert_eq!(j.sample().unwrap().transition_serial, first);
    j.committed_step(0.3, 0.7, input(0., true)).unwrap();
    j.committed_step(0.7, 0.8, input(0.7, false)).unwrap();
    assert_eq!(j.sample().unwrap().phase, JumpPhase::Takeoff);
    assert!((j.sample().unwrap().seconds - 0.1).abs() < 1e-12);
    assert!(j.sample().unwrap().transition_serial > first);
}

#[test]
fn reload_or_mantle_cancels_and_acknowledges_suppressed_launch() {
    let mut j = jump();
    j.committed_step(0., 0.1, input(0., false)).unwrap();
    j.committed_step(
        0.1,
        0.2,
        JumpInput {
            eligible: false,
            ..input(0.1, false)
        },
    )
    .unwrap();
    assert!(j.sample().is_none());
    j.committed_step(0.2, 0.4, input(0.1, false)).unwrap();
    assert!(j.sample().is_none());
}

#[test]
fn pause_and_invalid_steps_are_atomic() {
    let mut j = jump();
    j.committed_step(0., 0.1, input(0., false)).unwrap();
    let state = j.sample();
    j.committed_step(
        0.1,
        0.1,
        JumpInput {
            eligible: false,
            ..input(0., true)
        },
    )
    .unwrap();
    assert_eq!(j.sample(), state);
    for (start, end, at) in [
        (0.2, 0.3, 0.),
        (0.1, f64::NAN, 0.),
        (0.1, 0.3, 1.),
        (0.1, 0.3, f64::NAN),
    ] {
        assert!(j.committed_step(start, end, input(at, false)).is_err());
        assert_eq!(j.sample(), state);
    }
    assert!(j.reset(f64::NAN).is_err());
    assert_eq!(j.sample(), state);
}

#[test]
fn native_phase_is_independent_of_observer_interval_partition() {
    let mut a = jump();
    let mut b = jump();
    a.committed_step(0., 0.5, input(0., false)).unwrap();
    let mut start = 0.;
    for end in [0.1, 0.2, 0.3, 0.5] {
        b.committed_step(start, end, input(0., false)).unwrap();
        start = end;
    }
    assert_eq!(a.sample(), b.sample());
}

#[test]
fn constructor_rejects_nonpositive_or_nonfinite_durations() {
    for value in [0., -1., f64::NAN, f64::INFINITY, 61.] {
        assert!(AuthoredJump::new(value, 0.2, 0.4).is_err());
        assert!(AuthoredJump::new(0.2, value, 0.4).is_err());
        assert!(AuthoredJump::new(0.2, 0.4, value).is_err());
    }
}
