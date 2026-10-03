use vector_range::authored_walk::AuthoredWalk;
#[test]
fn movement_starts_loop_clock_and_pause_freezes_it() {
    let mut walk = AuthoredWalk::default();
    walk.committed_step(0., 0.25, true, true).unwrap();
    assert_eq!(walk.seconds(), Some(0.25));
    walk.committed_step(0.25, 0.25, true, true).unwrap();
    assert_eq!(walk.seconds(), Some(0.25));
    walk.committed_step(0.25, 0.5, true, true).unwrap();
    assert_eq!(walk.seconds(), Some(0.5));
}
#[test]
fn stopped_sprint_reload_priority_and_reset_remove_walk_owner() {
    let mut walk = AuthoredWalk::default();
    walk.committed_step(0., 1., true, true).unwrap();
    walk.committed_step(1., 2., false, true).unwrap();
    assert!(walk.seconds().is_none());
    walk.committed_step(2., 3., true, true).unwrap();
    assert_eq!(walk.seconds(), Some(1.));
    walk.committed_step(3., 4., true, false).unwrap();
    assert!(walk.seconds().is_none());
    walk.reset(0.);
    walk.committed_step(0., 0.1, true, true).unwrap();
    assert_eq!(walk.seconds(), Some(0.1));
}

#[test]
fn start_stop_are_eased_and_quick_reversal_keeps_the_same_loop_phase() {
    let mut walk = AuthoredWalk::default();
    walk.committed_step(0., 0.08, true, true).unwrap();
    assert!((walk.weight() - 0.5).abs() < 1e-6);
    walk.committed_step(0.08, 0.16, true, true).unwrap();
    assert_eq!(walk.weight(), 1.);
    walk.committed_step(0.16, 0.27, false, true).unwrap();
    assert!((walk.weight() - 0.5).abs() < 1e-6);
    assert_eq!(walk.seconds(), Some(0.27));
    walk.committed_step(0.27, 0.31, true, true).unwrap();
    assert!(walk.weight() > 0.5 && walk.weight() < 1.);
    assert_eq!(walk.seconds(), Some(0.31));
    walk.committed_step(0.31, 0.6, false, true).unwrap();
    assert_eq!(walk.weight(), 0.);
    assert_eq!(walk.seconds(), None);
}

#[test]
fn pause_cannot_change_owner_weight_or_phase_and_bad_ticks_are_atomic() {
    let mut walk = AuthoredWalk::default();
    walk.committed_step(0., 0.08, true, true).unwrap();
    let snapshot = (walk.seconds(), walk.weight());
    walk.committed_step(0.08, 0.08, false, false).unwrap();
    assert_eq!((walk.seconds(), walk.weight()), snapshot);
    assert!(walk.committed_step(0.09, 0.1, false, true).is_err());
    assert!(walk.committed_step(0.08, f64::NAN, true, true).is_err());
    assert_eq!((walk.seconds(), walk.weight()), snapshot);
}

#[test]
fn envelope_is_independent_of_committed_tick_partition() {
    for moving in [true, false] {
        let mut a = AuthoredWalk::default();
        a.committed_step(0., 0.2, true, true).unwrap();
        let mut b = a.clone();
        a.committed_step(0.2, 0.3, moving, true).unwrap();
        b.committed_step(0.2, 0.24, moving, true).unwrap();
        b.committed_step(0.24, 0.3, moving, true).unwrap();
        assert_eq!(a.seconds(), b.seconds());
        assert!((a.weight() - b.weight()).abs() < 1e-6);
    }
}
