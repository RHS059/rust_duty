//! Ledge catch/hang, pull-up, drop and hanging-sidearm contracts.
use macroquad::math::{vec2, vec3, Vec3};
use vector_range::{
    action::{ActionEventKind, ActionSlot, HandOwner, Loadout, Rejection, SidearmSpec},
    clock::FixedClock,
    settings::Settings,
    sim::{
        Aabb, Action, Block, HangPhase, HangState, Input, PistolPhase, Simulation, Target,
        FIXED_DT, RADIUS,
    },
};

fn block(min: Vec3, max: Vec3) -> Block {
    Block {
        bounds: Aabb { min, max },
        kind: 2,
    }
}
const LEDGE: f32 = 2.7;
fn wall() -> Block {
    block(vec3(-2., 0., -4.), vec3(2., LEDGE, -2.))
}
fn fixture() -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![block(vec3(-20., -1., -20.), vec3(20., 0., 20.)), wall()];
    s.ramps.clear();
    s.targets.clear();
    s.player.position = vec3(0., 0., -2. + RADIUS + 0.3);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    s
}
fn cfg() -> Settings {
    Settings::default()
}
fn forward() -> Input {
    Input {
        movement: vec2(0., 1.),
        ..Input::default()
    }
}
fn tick(s: &mut Simulation, input: Input) {
    s.update(input, &cfg(), FIXED_DT);
    let bounds = s.player.bounds_at(s.player.position);
    for b in &s.blocks {
        assert!(!bounds.overlaps(b.bounds), "penetrated {:?}", b.bounds);
    }
}
fn run(s: &mut Simulation, input: Input, n: usize) {
    for _ in 0..n {
        tick(s, input);
    }
}
fn drain(s: &mut Simulation) -> Vec<ActionEventKind> {
    s.action_events.drain(..).map(|e| e.kind).collect()
}
fn hang(s: &Simulation) -> HangState {
    match s.player.action {
        Action::Hang(h) => h,
        other => panic!("expected hang, got {other:?}"),
    }
}
/// Jump forward at the wall; returns whether a catch happened within 1.5 s.
fn jump_catch(s: &mut Simulation) -> bool {
    tick(
        s,
        Input {
            jump: true,
            ..forward()
        },
    );
    for _ in 0..180 {
        tick(s, forward());
        if matches!(s.player.action, Action::Hang(_)) {
            return true;
        }
    }
    false
}
/// Catch and wait until the hands are planted.
fn hanging() -> Simulation {
    let mut s = fixture();
    assert!(jump_catch(&mut s));
    run(&mut s, Input::default(), 60);
    drain(&mut s);
    s
}
fn pistol() -> Loadout {
    Loadout {
        sidearm: Some(SidearmSpec {
            magazine: 12,
            rpm: 400.,
            body_damage: 25.,
            head_damage: 50.,
            recoil_scale: 0.8,
            hang_eligible: true,
        }),
        sidearm_ammo: 12,
    }
}

#[test]
fn jump_catch_holds_a_validated_stable_hang() {
    let mut s = fixture();
    assert!(jump_catch(&mut s));
    assert!(drain(&mut s).contains(&ActionEventKind::LedgeCaught));
    let h = hang(&s);
    let t = cfg().action;
    assert_eq!(h.phase, HangPhase::Catch);
    assert_eq!(h.normal, Vec3::Z);
    assert!((h.position.y - (LEDGE - t.hang_hand_height)).abs() < 1e-5);
    for hand in h.hands {
        assert_eq!(hand.y, LEDGE);
        assert!(hand.z < -2. && hand.z > -4., "hand on the top: {hand:?}");
    }
    assert!(((h.hands[0] - h.hands[1]).length() - t.hang_hand_spacing).abs() < 1e-5);
    for rel in h.ledge_relative_hands() {
        assert!(
            rel.y.abs() < 1e-5 && (rel.z - t.hang_hand_inset).abs() < 1e-4,
            "{rel:?}"
        );
    }
    // Gravity and locomotion are transferred to the ledge.
    let pos = s.player.position;
    run(&mut s, forward(), 240);
    assert_eq!(s.player.position, pos);
    assert_eq!(s.player.velocity, Vec3::ZERO);
    let pose = s.action_pose();
    assert_eq!(pose.slot, Some(ActionSlot::LedgeHold));
    assert_eq!(pose.contacts.left_owner, HandOwner::Ledge);
    assert_eq!(pose.contacts.right_owner, HandOwner::Ledge);
    assert_eq!(pose.contacts.left_hand, Some(h.hands[0]));
    assert_eq!(pose.contacts.right_hand, Some(h.hands[1]));
    assert_eq!(pose.contacts.body_facing, -Vec3::Z);
}

#[test]
fn shipped_range_fixture_is_catchable() {
    let mut s = Simulation::new();
    s.player.position = vec3(-24., 0., 5. + RADIUS + 0.3);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    assert!(jump_catch(&mut s));
}

#[test]
fn invalid_ledges_and_inputs_do_not_catch() {
    type Setup = Box<dyn Fn(&mut Simulation) -> Input>;
    let cases: Vec<(&str, Setup)> = vec![
        (
            "too high",
            Box::new(|s| {
                s.blocks[1].bounds.max.y = 4.;
                forward()
            }),
        ),
        (
            "too low to hang",
            Box::new(|s| {
                s.blocks[1].bounds.max.y = 2.2;
                forward()
            }),
        ),
        (
            "no hand room on a thin top",
            Box::new(|s| {
                s.blocks[1].bounds.min.z = -2.05;
                forward()
            }),
        ),
        (
            "ceiling over the lip",
            Box::new(|s| {
                s.blocks
                    .push(block(vec3(-2., LEDGE + 0.05, -4.), vec3(2., 4., -1.9)));
                forward()
            }),
        ),
        ("no forward intent", Box::new(|_| Input::default())),
        (
            "facing along the wall",
            Box::new(|s| {
                s.player.yaw = 0.;
                forward()
            }),
        ),
    ];
    for (name, setup) in cases {
        let mut s = fixture();
        let input = setup(&mut s);
        tick(
            &mut s,
            Input {
                jump: true,
                ..input
            },
        );
        for _ in 0..180 {
            tick(&mut s, input);
            assert!(!matches!(s.player.action, Action::Hang(_)), "{name}");
        }
        assert!(s.player.grounded, "{name}: movement restored");
    }
}

#[test]
fn look_is_limited_while_hanging() {
    let mut s = hanging();
    let t = cfg().action;
    let center = hang(&s).yaw_center;
    s.player.yaw = center + 3.;
    s.player.pitch = -1.4;
    s.clamp_look(&cfg());
    assert!((s.player.yaw - (center + t.hang_yaw_limit.to_radians())).abs() < 1e-4);
    assert!((s.player.pitch + t.hang_pitch_down.to_radians()).abs() < 1e-5);
}

#[test]
fn weapons_are_unavailable_while_both_hands_hold_the_ledge() {
    let mut s = hanging();
    s.player.ammo = 10;
    let perms = s.weapon_permissions();
    assert!(!perms.fire && !perms.ads && !perms.reload);
    run(
        &mut s,
        Input {
            fire: true,
            ads: true,
            reload: true,
            ..Input::default()
        },
        30,
    );
    assert_eq!(s.stats.shots, 0);
    assert_eq!(s.player.ads, 0.);
    assert_eq!(s.player.reload_left, 0.);
}

#[test]
fn drop_releases_once_restores_falling_and_blocks_recatch() {
    let mut s = hanging();
    tick(
        &mut s,
        Input {
            crouch: true,
            ..forward()
        },
    );
    assert!(matches!(s.player.action, Action::None));
    assert_eq!(drain(&mut s), vec![ActionEventKind::HangDropped]);
    assert!(s.player.velocity.z > 0., "pushed away from the wall");
    assert_eq!(s.action_pose().slot, Some(ActionSlot::HangDrop));
    // Held forward + crouch: never recatch the same ledge, and the drop
    // press does not crouch the player.
    let mut landed = false;
    for _ in 0..240 {
        tick(
            &mut s,
            Input {
                crouch: true,
                ..forward()
            },
        );
        assert!(!matches!(s.player.action, Action::Hang(_)));
        landed |= s.player.grounded;
    }
    assert!(landed);
    assert!(!s.player.crouched);
    assert!(!drain(&mut s).contains(&ActionEventKind::HangDropped));
}

#[test]
fn losing_support_releases_immediately() {
    for change in 0..3 {
        let mut s = hanging();
        match change {
            0 => {
                s.blocks.remove(1);
            }
            1 => s.blocks[1].bounds.max.y += 0.2,
            _ => s
                .blocks
                .push(block(vec3(-0.5, LEDGE, -2.3), vec3(0.5, LEDGE + 0.1, -2.1))),
        }
        tick(&mut s, Input::default());
        assert!(matches!(s.player.action, Action::None), "change {change}");
        assert!(drain(&mut s).contains(&ActionEventKind::LedgeLost));
        assert_eq!(
            s.action_pose().phase,
            vector_range::action::ActionPhase::Interrupted
        );
        let y = s.player.position.y;
        run(&mut s, Input::default(), 10);
        assert!(s.player.position.y < y, "falls under ordinary gravity");
    }
}

#[test]
fn pull_up_reuses_mantle_rules_and_lands_on_the_top() {
    let mut s = hanging();
    tick(
        &mut s,
        Input {
            jump: true,
            ..Input::default()
        },
    );
    let m = s.player.mantle.expect("pull-up");
    assert!(m.from_hang);
    assert!((m.duration() - s.timings.get(ActionSlot::PullUp).duration).abs() < 1e-6);
    assert_eq!(drain(&mut s), vec![ActionEventKind::PullUpStarted]);
    assert_eq!(s.action_pose().slot, Some(ActionSlot::PullUp));
    assert!(!s.weapon_permissions().fire);
    let mut ticks = 0;
    while s.player.mantle.is_some() {
        tick(&mut s, Input::default());
        ticks += 1;
        assert!(ticks < 200);
    }
    assert!(drain(&mut s).contains(&ActionEventKind::PullUpCompleted));
    assert!(s.player.grounded);
    assert_eq!(s.player.position.y, LEDGE);
    assert!(s.player.position.z < -2. - RADIUS && s.player.position.z > -4. + RADIUS);
}

#[test]
fn blocked_top_keeps_hanging_without_teleporting() {
    for blocker in 0..2 {
        let mut s = hanging();
        let pos = s.player.position;
        if blocker == 0 {
            // Crouch-height overhang over the top: no standing landing.
            s.blocks.push(block(
                vec3(-2., LEDGE + 1.3, -4.),
                vec3(2., LEDGE + 2., -2.25),
            ));
        } else {
            // A tall box leaves only a hand-width strip: no landing footprint.
            s.blocks
                .push(block(vec3(-2., LEDGE, -4.), vec3(2., LEDGE + 2., -2.3)));
        }
        tick(
            &mut s,
            Input {
                jump: true,
                ..Input::default()
            },
        );
        assert!(
            matches!(s.player.action, Action::Hang(_)),
            "blocker {blocker}"
        );
        assert!(s.player.mantle.is_none());
        assert!(drain(&mut s).contains(&ActionEventKind::PullUpRejected(Rejection::Blocked)));
        assert_eq!(s.player.position, pos);
    }
}

#[test]
fn unsupported_loadout_fails_safely() {
    let mut s = hanging();
    let before = hang(&s);
    tick(
        &mut s,
        Input {
            sidearm: true,
            ..Input::default()
        },
    );
    assert_eq!(
        drain(&mut s),
        vec![ActionEventKind::SidearmRejected(Rejection::NoSidearm)]
    );
    assert_eq!(hang(&s).pistol, PistolPhase::Holstered);
    assert_eq!(hang(&s).hands, before.hands);
    // Ineligible sidearm is also rejected.
    s.loadout = pistol();
    s.loadout.sidearm.as_mut().unwrap().hang_eligible = false;
    tick(
        &mut s,
        Input {
            sidearm: true,
            ..Input::default()
        },
    );
    assert_eq!(hang(&s).pistol, PistolPhase::Holstered);
}

#[test]
fn sidearm_draw_fire_and_stow_keep_grip_ownership_consistent() {
    let mut s = hanging();
    s.loadout = pistol();
    s.targets = vec![Target {
        bounds: Aabb::from_center(s.player.eye() + vec3(0., 0., -6.), vec3(1., 1., 0.2)),
        health: 100.,
        respawn: 0.,
        flash: 0.,
    }];
    // The wall is in front; aim over it by looking up a little.
    s.player.pitch = 0.;
    tick(
        &mut s,
        Input {
            sidearm: true,
            ..Input::default()
        },
    );
    assert_eq!(drain(&mut s), vec![ActionEventKind::PistolDrawStarted]);
    let draw = s.timings.get(ActionSlot::PistolDraw).clone();
    let mut owners = Vec::new();
    while hang(&s).pistol == PistolPhase::Drawing {
        let pose = s.action_pose();
        assert_eq!(pose.contacts.left_owner, HandOwner::Ledge, "support hand");
        owners.push(pose.contacts.right_owner);
        tick(&mut s, Input::default());
        assert!(owners.len() < 200);
    }
    owners.dedup();
    assert_eq!(
        owners,
        vec![HandOwner::Ledge, HandOwner::Free, HandOwner::Pistol]
    );
    assert!((owners.len() as f32) > 0. && draw.duration > 0.);
    assert!(drain(&mut s).contains(&ActionEventKind::PistolReady));
    let rifle = (s.player.ammo, s.player.reserve);
    let perms = s.weapon_permissions();
    assert!(perms.fire && perms.ads && !perms.reload);
    run(
        &mut s,
        Input {
            fire: true,
            reload: true,
            ..Input::default()
        },
        30,
    );
    assert!(s.stats.shots > 0);
    assert_eq!(s.loadout.sidearm_ammo, 12 - s.stats.shots);
    assert_eq!(
        (s.player.ammo, s.player.reserve),
        rifle,
        "rifle ammo untouched"
    );
    assert_eq!(s.player.reload_left, 0.);
    // Pull-up is rejected while the pistol is out.
    tick(
        &mut s,
        Input {
            jump: true,
            ..Input::default()
        },
    );
    assert!(drain(&mut s).contains(&ActionEventKind::PullUpRejected(Rejection::PistolOut)));
    tick(
        &mut s,
        Input {
            sidearm: true,
            ..Input::default()
        },
    );
    assert_eq!(hang(&s).pistol, PistolPhase::Stowing);
    let mut ticks = 0;
    while hang(&s).pistol == PistolPhase::Stowing {
        tick(&mut s, Input::default());
        ticks += 1;
        assert!(ticks < 200);
    }
    assert_eq!(s.action_pose().contacts.right_owner, HandOwner::Ledge);
    assert!(drain(&mut s).contains(&ActionEventKind::PistolHolstered));
}

#[test]
fn sidearm_runs_dry_without_reloading() {
    let mut s = hanging();
    s.loadout = pistol();
    s.loadout.sidearm_ammo = 2;
    tick(
        &mut s,
        Input {
            sidearm: true,
            ..Input::default()
        },
    );
    run(&mut s, Input::default(), 80);
    run(
        &mut s,
        Input {
            fire: true,
            ..Input::default()
        },
        120,
    );
    assert_eq!(s.stats.shots, 2);
    assert_eq!(s.loadout.sidearm_ammo, 0);
}

#[test]
fn interruptions_mid_grip_transfer_leave_consistent_ownership() {
    for interruption in 0..3 {
        let mut s = hanging();
        s.loadout = pistol();
        tick(
            &mut s,
            Input {
                sidearm: true,
                ..Input::default()
            },
        );
        run(&mut s, Input::default(), 30);
        assert_eq!(hang(&s).pistol, PistolPhase::Drawing);
        match interruption {
            0 => tick(
                &mut s,
                Input {
                    crouch: true,
                    ..Input::default()
                },
            ),
            1 => {
                s.blocks.remove(1);
                tick(&mut s, Input::default());
            }
            _ => s.kill(),
        }
        assert!(matches!(s.player.action, Action::None));
        assert!(drain(&mut s).contains(&ActionEventKind::PistolInterrupted));
        // Nothing holds a pistol any more; the rifle owns both hands.
        let pose = s.action_pose();
        assert_eq!(pose.contacts.right_owner, HandOwner::Rifle);
        assert_eq!(pose.contacts.left_owner, HandOwner::Rifle);
        assert_eq!(s.loadout.sidearm_ammo, 12);
    }
}

#[test]
fn hang_and_pull_up_ticks_are_independent_of_render_rate() {
    let mut traces = Vec::new();
    for fps in [15_u32, 30, 60, 144, 240] {
        let mut s = fixture();
        let mut clock = FixedClock::default();
        let mut index = 0;
        let mut trace = Vec::new();
        for _ in 0..fps * 3 {
            for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                let input = Input {
                    jump: index == 0 || index == 200,
                    ..forward()
                };
                s.update(input, &cfg(), FIXED_DT);
                trace.push((
                    s.player.position,
                    s.player.action,
                    s.player.mantle.is_some(),
                ));
                index += 1;
            }
        }
        traces.push(trace);
    }
    assert!(traces.windows(2).all(|w| w[0] == w[1]));
    assert!(traces[0]
        .iter()
        .any(|(_, a, _)| matches!(a, Action::Hang(_))));
    assert!(traces[0].iter().any(|(_, _, m)| *m), "pull-up ran");
}

#[test]
fn sidearm_hits_use_the_shared_damage_path() {
    let mut s = fixture();
    s.blocks[1].bounds.min.x = -0.6;
    s.blocks[1].bounds.max.x = 0.6;
    assert!(jump_catch(&mut s));
    run(&mut s, Input::default(), 60);
    s.loadout = pistol();
    tick(
        &mut s,
        Input {
            sidearm: true,
            ..Input::default()
        },
    );
    run(&mut s, Input::default(), 80);
    let center = hang(&s).yaw_center;
    s.player.yaw = center + 60_f32.to_radians();
    s.player.pitch = 0.;
    let aim = s.player.direction();
    s.targets = vec![Target {
        bounds: Aabb::from_center(s.player.eye() + aim * 5., vec3(1.2, 1.2, 1.2)),
        health: 100.,
        respawn: 0.,
        flash: 0.,
    }];
    let cfg = Settings {
        hip_spread: 0.,
        ads_spread: 0.,
        ..Settings::default()
    };
    s.update(
        Input {
            fire: true,
            ..Input::default()
        },
        &cfg,
        FIXED_DT,
    );
    assert_eq!(s.stats.shots, 1);
    assert_eq!(s.stats.hits, 1);
    let hit = s.events.last().unwrap();
    let expected = if hit.headshot { 50. } else { 25. };
    assert_eq!(s.targets[0].health, 100. - expected);
}
