//! Tactical sprint, slide and dolphin-dive gameplay contracts. Everything is
//! driven through `Simulation::update`; presentation never moves the player.
use macroquad::math::{vec2, vec3, Vec3};
use vector_range::{
    action::{ActionEventKind, ActionPhase, ActionSlot, Rejection},
    clock::FixedClock,
    settings::Settings,
    sim::{
        Aabb, Action, Block, DivePhase, Input, Ramp, Simulation, SlidePhase, FIXED_DT, PRONE_HEIGHT,
    },
};

fn block(min: Vec3, max: Vec3) -> Block {
    Block {
        bounds: Aabb { min, max },
        kind: 2,
    }
}
fn flat() -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![block(vec3(-60., -1., -60.), vec3(60., 0., 60.))];
    s.ramps.clear();
    s.targets.clear();
    s.player.position = vec3(0., 0., 40.);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    s
}
fn cfg() -> Settings {
    Settings::default()
}
fn sprint() -> Input {
    Input {
        movement: vec2(0., 1.),
        sprint: true,
        ..Input::default()
    }
}
fn tick(s: &mut Simulation, input: Input) {
    s.update(input, &cfg(), FIXED_DT);
    assert_clear(s);
}
fn run(s: &mut Simulation, input: Input, n: usize) {
    for _ in 0..n {
        tick(s, input);
    }
}
fn assert_clear(s: &Simulation) {
    let bounds = s.player.bounds_at(s.player.position);
    for b in &s.blocks {
        assert!(
            !bounds.overlaps(b.bounds),
            "player {:?} (h {}) penetrated {:?}",
            s.player.position,
            s.player.height(),
            b.bounds
        );
    }
}
fn drain(s: &mut Simulation) -> Vec<ActionEventKind> {
    s.action_events.drain(..).map(|e| e.kind).collect()
}
fn sprint_up(s: &mut Simulation) {
    run(s, sprint(), 60);
    assert!(s.player.sprinting);
    drain(s);
}
fn tac(s: &mut Simulation) {
    tick(
        s,
        Input {
            tactical_sprint: true,
            ..sprint()
        },
    );
}

// ---------------------------------------------------------------- tactical sprint

#[test]
fn tactical_sprint_enters_from_sprint_and_replaces_sprint_speed() {
    let mut s = flat();
    sprint_up(&mut s);
    tac(&mut s);
    assert!(s.player.tac_sprint.is_some());
    assert_eq!(drain(&mut s), vec![ActionEventKind::TacSprintStarted]);
    run(&mut s, sprint(), 60);
    let t = cfg().action;
    assert!(s.player.speed() > cfg().sprint_speed + 0.5);
    assert!(s.player.speed() <= t.tac_sprint_speed + 1e-4, "no stacking");
    let pose = s.action_pose();
    assert_eq!(pose.slot, Some(ActionSlot::TacSprintLoop));
    assert!(pose.placeholder);
}

#[test]
fn tactical_sprint_rejects_ineligible_states_without_changing_movement() {
    for setup in 0..4 {
        let mut s = flat();
        let mut control = flat();
        let input = match setup {
            // Walking, not sprinting.
            0 => Input {
                movement: vec2(0., 1.),
                ..Input::default()
            },
            // Strafing sprint.
            1 => Input {
                movement: vec2(1., 0.),
                sprint: true,
                ..Input::default()
            },
            // Aiming.
            2 => Input {
                ads: true,
                ..sprint()
            },
            // Crouched.
            _ => Input {
                crouch: true,
                ..sprint()
            },
        };
        run(&mut s, input, 40);
        run(&mut control, input, 40);
        tick(
            &mut s,
            Input {
                tactical_sprint: true,
                ..input
            },
        );
        tick(&mut control, input);
        assert!(s.player.tac_sprint.is_none(), "setup {setup}");
        assert_eq!(s.player.position, control.player.position, "setup {setup}");
        assert_eq!(s.player.velocity, control.player.velocity, "setup {setup}");
    }
}

#[test]
fn tactical_sprint_resource_drains_then_falls_back_to_sprint_without_residual_speed() {
    let mut s = flat();
    sprint_up(&mut s);
    tac(&mut s);
    let duration = cfg().action.tac_sprint_duration;
    let mut ticks = 0;
    while s.player.tac_sprint.is_some() {
        tick(&mut s, sprint());
        ticks += 1;
        assert!(ticks < 500);
    }
    assert!((ticks as f32 * FIXED_DT - duration).abs() < 0.03);
    assert!(drain(&mut s).contains(&ActionEventKind::TacSprintEnded));
    assert!(s.player.sprinting, "normal sprint continues");
    run(&mut s, sprint(), 12);
    assert!(s.player.speed() <= cfg().sprint_speed + 1e-3);
    // A new request is rejected until the charge recovers past the minimum.
    tac(&mut s);
    assert!(s.player.tac_sprint.is_none());
}

#[test]
fn tactical_sprint_recharges_after_its_delay() {
    let mut s = flat();
    sprint_up(&mut s);
    tac(&mut s);
    run(&mut s, sprint(), 60);
    run(&mut s, Input::default(), 1);
    let after = s.player.tac_charge;
    run(&mut s, Input::default(), 100);
    assert_eq!(s.player.tac_charge, after, "delay holds the charge");
    run(&mut s, Input::default(), 60);
    assert!(s.player.tac_charge > after + 0.3);
}

#[test]
fn tactical_sprint_exits_on_release_ads_fire_reload_and_jump() {
    for case in 0..5 {
        let mut s = flat();
        s.player.ammo = 10;
        sprint_up(&mut s);
        tac(&mut s);
        run(&mut s, sprint(), 10);
        let input = match case {
            0 => Input {
                movement: vec2(0., 1.),
                ..Input::default()
            },
            1 => Input {
                ads: true,
                ..sprint()
            },
            2 => Input {
                fire: true,
                ..sprint()
            },
            3 => Input {
                reload: true,
                ..sprint()
            },
            _ => Input {
                jump: true,
                ..sprint()
            },
        };
        tick(&mut s, input);
        assert!(s.player.tac_sprint.is_none(), "case {case}");
        assert!(drain(&mut s).contains(&ActionEventKind::TacSprintEnded));
        if case == 3 {
            assert!(
                s.player.reload_left > 0.,
                "reload wins over tactical sprint"
            );
        }
        if case < 4 {
            run(&mut s, Input { ..input }, 20);
            assert!(s.player.speed() <= cfg().sprint_speed + 1e-3, "case {case}");
        }
        assert_eq!(s.action_pose().slot, Some(ActionSlot::TacSprintExit));
    }
}

// ------------------------------------------------------------------------ slide

fn slide_input() -> Input {
    Input {
        crouch: true,
        ..sprint()
    }
}

#[test]
fn slide_enters_from_sprint_with_one_capped_boost_and_low_capsule() {
    let mut s = flat();
    sprint_up(&mut s);
    let before = s.player.speed();
    tick(&mut s, slide_input());
    let Action::Slide(slide) = s.player.action else {
        panic!("slide expected");
    };
    let t = cfg().action;
    assert_eq!(slide.phase, SlidePhase::Entry);
    assert_eq!(s.player.height(), t.slide_height);
    assert!(s.player.speed() <= (before + t.slide_boost).min(t.slide_max_speed) + 1e-3);
    assert!(s.player.speed() > before);
    assert!(!s.player.sprinting && !s.player.crouched);
    assert_eq!(drain(&mut s), vec![ActionEventKind::SlideStarted]);
    // Tactical sprint + slide is capped at the slide maximum.
    let mut s = flat();
    sprint_up(&mut s);
    tac(&mut s);
    run(&mut s, sprint(), 60);
    tick(&mut s, slide_input());
    assert!(s.player.speed() <= t.slide_max_speed + 1e-4);
    assert!(s.player.tac_sprint.is_none());
}

#[test]
fn rejected_slide_leaves_ordinary_crouch_movement() {
    // Walking crouch press: no slide, normal crouch, still moving.
    let mut s = flat();
    run(
        &mut s,
        Input {
            movement: vec2(0., 1.),
            ..Input::default()
        },
        40,
    );
    run(
        &mut s,
        Input {
            movement: vec2(0., 1.),
            crouch: true,
            ..Input::default()
        },
        40,
    );
    assert!(matches!(s.player.action, Action::None));
    assert!(s.player.crouched);
    assert!((s.player.speed() - cfg().crouch_speed).abs() < 0.05);
    // Cooldown: an immediate second slide is rejected as ineligible.
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, slide_input());
    tick(
        &mut s,
        Input {
            jump: true,
            ..sprint()
        },
    );
    assert!(matches!(s.player.action, Action::None));
    run(&mut s, sprint(), 1);
    drain(&mut s);
    s.player.grounded = true;
    s.player.sprinting = true;
    tick(&mut s, slide_input());
    assert!(!matches!(s.player.action, Action::Slide(_)));
    assert!(drain(&mut s).contains(&ActionEventKind::SlideRejected(Rejection::Ineligible)));
}

#[test]
fn slide_decelerates_by_friction_and_ends_crouched_with_weapon_raise() {
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, slide_input());
    let mut last = s.player.speed();
    let mut ticks = 0;
    while matches!(s.player.action, Action::Slide(_)) {
        tick(&mut s, slide_input());
        assert!(
            s.player.speed() <= last + 1e-4,
            "monotonic friction on flat ground"
        );
        last = s.player.speed();
        ticks += 1;
        assert!(ticks < 400);
    }
    assert!(ticks as f32 * FIXED_DT <= cfg().action.slide_max_time + FIXED_DT);
    assert!(
        s.player.crouched && !s.player.prone,
        "toggle crouch intent kept"
    );
    let events = drain(&mut s);
    assert!(events.contains(&ActionEventKind::SlideEnded));
    let pose = s.action_pose();
    assert_eq!(pose.slot, Some(ActionSlot::SlideRecover));
    assert_eq!(pose.phase, ActionPhase::Exit);
    assert!(!s.weapon_permissions().fire, "recovery raise");
    run(&mut s, Input::default(), 60);
    assert!(s.weapon_permissions().fire);
}

#[test]
fn slide_entry_blocks_weapons_then_active_allows_ads_and_fire() {
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, slide_input());
    let p = s.weapon_permissions();
    assert!(!p.fire && !p.ads && !p.reload);
    run(&mut s, slide_input(), 30);
    let Action::Slide(slide) = s.player.action else {
        panic!()
    };
    assert_eq!(slide.phase, SlidePhase::Active);
    let p = s.weapon_permissions();
    assert!(p.fire && p.ads && p.reload && !p.sprint);
    let shots = s.stats.shots;
    run(
        &mut s,
        Input {
            fire: true,
            ..slide_input()
        },
        10,
    );
    assert!(s.stats.shots > shots);
}

#[test]
fn slide_steering_is_rate_limited() {
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, slide_input());
    let before = vec2(s.player.velocity.x, s.player.velocity.z).normalize();
    let steer = Input {
        movement: vec2(1., 0.),
        crouch: true,
        ..Input::default()
    };
    run(&mut s, steer, 24);
    let after = vec2(s.player.velocity.x, s.player.velocity.z).normalize();
    let turned = before.angle_between(after).abs().to_degrees();
    let limit = cfg().action.slide_steer_rate * 24. * FIXED_DT;
    assert!(
        turned > 1. && turned <= limit + 0.1,
        "turned {turned}, limit {limit}"
    );
}

#[test]
fn slide_slope_response_adds_speed_downhill() {
    let ramp = Ramp {
        x: 0.,
        z: 20.,
        width: 6.,
        length: 30.,
        height: 30. * 15_f32.to_radians().tan(),
    };
    let mut downhill = flat();
    downhill.ramps = vec![ramp];
    // Start uphill on the ramp, facing +Z (downhill).
    downhill.player.position = vec3(0., ramp.surface(0., 0.).unwrap(), 0.);
    downhill.player.yaw = std::f32::consts::FRAC_PI_2;
    let mut level = flat();
    level.player.yaw = std::f32::consts::FRAC_PI_2;
    level.player.position = vec3(0., 0., -40.);
    for s in [&mut downhill, &mut level] {
        sprint_up(s);
        tick(s, slide_input());
        run(s, slide_input(), 40);
    }
    assert!(matches!(downhill.player.action, Action::Slide(_)));
    assert!(downhill.player.speed() > level.player.speed() + 0.5);
}

#[test]
fn slide_never_stands_through_a_low_ceiling() {
    let mut s = flat();
    // A 1.0 m slot: the slide capsule fits, crouch does not.
    s.blocks.push(block(vec3(-3., 1.0, 0.), vec3(3., 3., 33.)));
    s.player.position = vec3(0., 0., 39.);
    sprint_up(&mut s);
    let release = Input {
        movement: vec2(0., 1.),
        ..Input::default()
    };
    tick(&mut s, slide_input());
    let mut ticks = 0;
    while matches!(s.player.action, Action::Slide(_)) {
        // Standing intent throughout (hold-mode release).
        tick(
            &mut s,
            Input {
                crouch: true,
                ..release
            },
        );
        ticks += 1;
        assert!(ticks < 400);
    }
    assert!(s.player.position.z < 33. - 0.4, "slid under the slot");
    assert!(s.player.prone, "only prone fits under the slot");
    assert_eq!(s.player.height(), PRONE_HEIGHT);
    // Standing stays requested but cannot happen under the ceiling.
    run(&mut s, Input::default(), 120);
    assert!(s.player.prone);
}

#[test]
fn slide_jump_cancel_stands_and_launches_only_with_clearance() {
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, slide_input());
    run(&mut s, slide_input(), 30);
    tick(
        &mut s,
        Input {
            jump: true,
            ..sprint()
        },
    );
    assert!(matches!(s.player.action, Action::None));
    assert!(!s.player.crouched && s.player.velocity.y > 0.);
    assert!(drain(&mut s).contains(&ActionEventKind::SlideInterrupted));
    assert_eq!(s.action_pose().phase, ActionPhase::Interrupted);

    let mut s = flat();
    s.blocks.push(block(vec3(-3., 1.0, 0.), vec3(3., 3., 33.)));
    s.player.position = vec3(0., 0., 39.);
    sprint_up(&mut s);
    tick(&mut s, slide_input());
    run(&mut s, slide_input(), 60);
    assert!(s.player.position.z < 33. - 0.4);
    tick(
        &mut s,
        Input {
            jump: true,
            ..slide_input()
        },
    );
    assert!(
        matches!(s.player.action, Action::Slide(_)),
        "no stand into ceiling"
    );
    assert!(s.player.velocity.y <= 0.);
}

#[test]
fn slide_into_wall_stops_without_penetration_and_off_ledge_interrupts() {
    let mut s = flat();
    s.blocks.push(block(vec3(-5., 0., 34.), vec3(5., 3., 35.)));
    s.player.position = vec3(0., 0., 39.);
    run(&mut s, sprint(), 40);
    tick(&mut s, slide_input());
    run(&mut s, slide_input(), 120);
    assert!(s.player.position.z >= 35. + 0.38);
    assert!(matches!(s.player.action, Action::None));

    let mut s2 = flat();
    s2.blocks = vec![
        block(vec3(-60., -2., -60.), vec3(60., -1., 60.)),
        block(vec3(-5., -1., 34.), vec3(5., 0., 60.)),
    ];
    s2.player.position = vec3(0., 0., 40.);
    run(&mut s2, sprint(), 50);
    tick(&mut s2, slide_input());
    let mut interrupted = false;
    for _ in 0..200 {
        tick(&mut s2, slide_input());
        interrupted |= drain(&mut s2).contains(&ActionEventKind::SlideInterrupted);
    }
    assert!(interrupted, "leaving the ground interrupts the slide");
    assert!(s2.player.position.y <= -0.99);
}

// ------------------------------------------------------------------------- dive

fn dive_input() -> Input {
    Input {
        prone: true,
        ..sprint()
    }
}
fn dive_to_end(s: &mut Simulation) -> (usize, usize) {
    let mut ticks = 0;
    let mut impact_tick = 0;
    while matches!(s.player.action, Action::Dive(_)) {
        tick(s, dive_input());
        ticks += 1;
        if drain(s).contains(&ActionEventKind::DiveImpact) {
            impact_tick = ticks;
            assert!(s.player.grounded, "impact only on ground contact");
        }
        assert!(ticks < 600);
    }
    (ticks, impact_tick)
}

#[test]
fn dive_launches_lands_on_ground_contact_and_hands_over_to_prone() {
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, dive_input());
    let Action::Dive(d) = s.player.action else {
        panic!("dive expected")
    };
    assert_eq!(d.phase, DivePhase::Launch);
    assert!(s.player.velocity.y > 0. && !s.player.grounded);
    assert_eq!(drain(&mut s), vec![ActionEventKind::DiveLaunched]);
    let start = s.player.position;
    let (_, impact) = dive_to_end(&mut s);
    assert!(impact > 0);
    assert!(s.player.prone && s.player.grounded);
    assert!((s.player.position - start).length() > 2.);
    assert_eq!(s.action_pose().slot, Some(ActionSlot::DiveRecover));
    // Recovery keeps prone until its cancel event, then stance input works.
    let stand = Input::default();
    tick(&mut s, stand);
    assert!(s.player.prone);
    run(&mut s, stand, 120);
    assert!(!s.player.prone);
}

#[test]
fn dive_impact_waits_for_real_ground_contact_after_a_drop() {
    let mut flat_dive = flat();
    sprint_up(&mut flat_dive);
    tick(&mut flat_dive, dive_input());
    let (_, flat_impact) = dive_to_end(&mut flat_dive);

    let mut s = flat();
    s.blocks = vec![
        block(vec3(-60., -3., -60.), vec3(60., -2., 60.)),
        block(vec3(-5., -2., 37.), vec3(5., 0., 60.)),
    ];
    s.player.position = vec3(0., 0., 40.5);
    sprint_up(&mut s);
    tick(&mut s, dive_input());
    let (_, impact) = dive_to_end(&mut s);
    assert!(impact > flat_impact, "{impact} vs {flat_impact}");
    assert!((s.player.position.y + 2.).abs() < 1e-3);
}

#[test]
fn dive_rejects_walls_ceilings_and_low_speed_leaving_prone_usable() {
    // Wall inside forward clearance.
    let mut s = flat();
    s.blocks.push(block(vec3(-5., 0., 34.), vec3(5., 3., 35.)));
    s.player.position = vec3(0., 0., 40.);
    run(&mut s, sprint(), 50);
    s.player.position.z = 35. + 0.381 + 0.5;
    drain(&mut s);
    tick(&mut s, dive_input());
    assert!(!matches!(s.player.action, Action::Dive(_)));
    assert!(drain(&mut s).contains(&ActionEventKind::DiveRejected(Rejection::Blocked)));
    run(
        &mut s,
        Input {
            prone: true,
            ..Input::default()
        },
        120,
    );
    assert!(s.player.prone, "ordinary prone still works");
    // Low overhang ahead: the launch arc has no forward space under it.
    let mut s = flat();
    s.blocks
        .push(block(vec3(-5., 1.2, -60.), vec3(5., 3., 35.)));
    run(&mut s, sprint(), 50);
    s.player.position.z = 35. + 0.381 + 0.6;
    drain(&mut s);
    tick(&mut s, dive_input());
    assert!(drain(&mut s).contains(&ActionEventKind::DiveRejected(Rejection::Blocked)));
    // Walking pace.
    let mut s = flat();
    run(
        &mut s,
        Input {
            movement: vec2(0., 1.),
            ..Input::default()
        },
        60,
    );
    tick(
        &mut s,
        Input {
            prone: true,
            movement: vec2(0., 1.),
            ..Input::default()
        },
    );
    assert!(!matches!(s.player.action, Action::Dive(_)));
}

#[test]
fn dive_into_a_wall_mid_air_never_penetrates() {
    let mut s = flat();
    s.blocks.push(block(vec3(-5., 0., 30.), vec3(5., 4., 31.)));
    s.player.position = vec3(0., 0., 39.);
    run(&mut s, sprint(), 50);
    tick(&mut s, dive_input());
    assert!(matches!(s.player.action, Action::Dive(_)));
    dive_to_end(&mut s);
    assert!(s.player.position.z >= 31. + 0.38);
    assert!(s.player.prone);
}

#[test]
fn dive_weapon_permissions_and_air_steering() {
    let mut s = flat();
    sprint_up(&mut s);
    tick(&mut s, dive_input());
    assert!(!s.weapon_permissions().fire, "launch");
    run(&mut s, dive_input(), 12);
    let Action::Dive(d) = s.player.action else {
        panic!()
    };
    assert_eq!(d.phase, DivePhase::Air);
    let p = s.weapon_permissions();
    assert!(p.fire && !p.ads && !p.reload);
    let before = vec2(s.player.velocity.x, s.player.velocity.z);
    run(
        &mut s,
        Input {
            prone: true,
            movement: vec2(1., 0.),
            ..Input::default()
        },
        6,
    );
    let after = vec2(s.player.velocity.x, s.player.velocity.z);
    let turned = before.angle_between(after).abs().to_degrees();
    assert!(turned > 0.5 && turned <= cfg().action.dive_steer_rate * 6. * FIXED_DT + 0.1);
    assert!(
        (after.length() - before.length()).abs() < 1e-3,
        "steer never adds speed"
    );
}

// ------------------------------------------------------------- frame-rate stability

#[test]
fn slide_and_dive_ticks_are_independent_of_render_rate() {
    for script in 0..2 {
        let mut traces = Vec::new();
        for fps in [15_u32, 30, 60, 144, 240] {
            let mut s = flat();
            let mut clock = FixedClock::default();
            let mut tick_index = 0;
            let mut trace = Vec::new();
            for _ in 0..fps * 3 {
                for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                    let mut input = sprint();
                    if tick_index >= 60 {
                        if script == 0 {
                            input.crouch = true;
                        } else {
                            input.prone = true;
                        }
                    }
                    s.update(input, &cfg(), FIXED_DT);
                    trace.push((s.player.position, s.player.velocity, s.player.action));
                    tick_index += 1;
                }
            }
            assert_eq!(tick_index, 360);
            traces.push(trace);
        }
        assert!(traces.windows(2).all(|w| w[0] == w[1]), "script {script}");
    }
}
