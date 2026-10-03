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
