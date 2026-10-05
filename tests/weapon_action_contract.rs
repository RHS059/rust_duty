//! Weapon mounting, wall obstruction, death/respawn and cross-feature
//! permission conflicts.
use macroquad::math::{vec2, vec3, Vec3};
use vector_range::{
    action::{ActionEventKind, ActionSlot, Rejection, WeaponPermissions},
    settings::Settings,
    sim::{Aabb, Action, Block, Input, Ramp, Simulation, Target, FIXED_DT, RADIUS},
};

fn block(min: Vec3, max: Vec3) -> Block {
    Block {
        bounds: Aabb { min, max },
        kind: 2,
    }
}
fn cfg() -> Settings {
    Settings::default()
}
fn cover(top: f32) -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![
        block(vec3(-30., -1., -30.), vec3(30., 0., 30.)),
        block(vec3(-2., 0., -3.), vec3(2., top, -2.5)),
    ];
    s.ramps.clear();
    s.targets.clear();
    s.player.position = vec3(0., 0., -2.5 + RADIUS + 0.1);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    s
}
fn tick(s: &mut Simulation, input: Input) {
    s.update(input, &cfg(), FIXED_DT);
}
fn run(s: &mut Simulation, input: Input, n: usize) {
    for _ in 0..n {
        tick(s, input);
    }
}
fn drain(s: &mut Simulation) -> Vec<ActionEventKind> {
    s.action_events.drain(..).map(|e| e.kind).collect()
}
fn press_mount(s: &mut Simulation) {
    tick(
        s,
        Input {
            mount: true,
            ..Input::default()
        },
    );
}

// ------------------------------------------------------------------------ mount

#[test]
fn mount_press_rests_the_weapon_on_a_valid_top() {
    let mut s = cover(1.2);
    press_mount(&mut s);
    let m = s.player.mount.expect("mounted");
    assert_eq!(drain(&mut s), vec![ActionEventKind::MountStarted]);
    assert!((m.support - vec3(0., 1.2, -2.5)).length() < 1e-4);
    assert_eq!(m.normal, Vec3::Y);
    assert_eq!(s.action_pose().slot, Some(ActionSlot::MountEnter));
    run(&mut s, Input::default(), 30);
    let m = s.player.mount.unwrap();
    assert_eq!(m.weight, 1.);
    assert_eq!(s.action_pose().slot, Some(ActionSlot::MountHold));
    // Stable support: aiming never moves the support point.
    s.player.yaw += 0.2;
    run(&mut s, Input::default(), 10);
    assert_eq!(s.player.mount.unwrap().support, m.support);
}

#[test]
fn crouched_mount_uses_crouch_eye_height() {
    let mut s = cover(0.8);
    run(
        &mut s,
        Input {
            crouch: true,
            ..Input::default()
        },
        40,
    );
    tick(
        &mut s,
        Input {
            crouch: true,
            mount: true,
            ..Input::default()
        },
    );
    assert!(s.player.mount.is_some_and(|m| m.crouched));
}

#[test]
fn auto_mount_follows_ads_after_its_delay_and_ends_with_ads() {
    let mut s = cover(1.2);
    let aim = Input {
        ads: true,
        ..Input::default()
    };
    let delay = (cfg().action.mount_auto_delay / FIXED_DT).ceil() as usize;
    run(&mut s, aim, delay);
    assert!(s.player.mount.is_none());
    run(&mut s, aim, 2);
    assert!(s.player.mount.is_some_and(|m| m.via_ads));
    run(&mut s, aim, 30);
    assert!(s.player.ads > 0.9, "ADS allowed while mounted");
    tick(&mut s, Input::default());
    assert!(s.player.mount.is_none());
    assert!(drain(&mut s).contains(&ActionEventKind::MountEnded));
    assert_eq!(s.action_pose().slot, Some(ActionSlot::MountExit));
}

#[test]
fn invalid_mount_positions_are_rejected() {
    type Setup = Box<dyn Fn(&mut Simulation)>;
    let cases: Vec<(&str, Setup)> = vec![
        ("too high", Box::new(|s| s.blocks[1].bounds.max.y = 1.5)),
        ("too low", Box::new(|s| s.blocks[1].bounds.max.y = 0.5)),
        ("out of reach", Box::new(|s| s.player.position.z += 1.)),
        (
            "overhang blocks the weapon",
            Box::new(|s| {
                s.blocks
                    .push(block(vec3(-2., 1.25, -3.), vec3(2., 1.6, -2.3)))
            }),
        ),
        (
            "moving",
            Box::new(|s| s.player.velocity = vec3(0., 0., -2.)),
        ),
        (
            "prone",
            Box::new(|s| {
                s.player.prone = true;
                s.player.crouched = true;
            }),
        ),
        (
            "steep ramp",
            Box::new(|s| {
                s.blocks.truncate(1);
                s.ramps.push(Ramp {
                    x: 0.,
                    z: -2.2,
                    width: 3.,
                    length: 2.,
                    height: 2. * 30_f32.to_radians().tan(),
                });
                s.player.position.z = -1.6;
            }),
        ),
    ];
    for (name, setup) in cases {
        let mut s = cover(1.2);
        setup(&mut s);
        press_mount(&mut s);
        assert!(s.player.mount.is_none(), "{name}");
        let events = drain(&mut s);
        assert!(
            events
                .iter()
                .any(|e| matches!(e, ActionEventKind::MountRejected(_))),
            "{name}: {events:?}"
        );
    }
}

#[test]
fn surface_angle_limit_is_what_rejects_a_steep_ramp() {
    let ramp = |s: &mut Simulation| {
        s.blocks.truncate(1);
        s.ramps.push(Ramp {
            x: 0.,
            z: -2.,
            width: 3.,
            length: 1.,
            height: 75_f32.to_radians().tan(),
        });
        s.player.position.z = -2. + RADIUS + 0.01;
    };
    let mut s = cover(1.2);
    ramp(&mut s);
    press_mount(&mut s);
    assert!(drain(&mut s).contains(&ActionEventKind::MountRejected(Rejection::Steep)));
    // Same geometry with an 80 degree limit: never rejected for its angle.
    let mut wide = cfg();
    wide.action.mount_max_angle = 80.;
    let mut s = cover(1.2);
    ramp(&mut s);
    s.update(
        Input {
            mount: true,
            ..Input::default()
        },
        &wide,
        FIXED_DT,
    );
    assert!(!drain(&mut s).contains(&ActionEventKind::MountRejected(Rejection::Steep)));
}

#[test]
fn mounted_aim_is_limited_and_recoil_is_reduced() {
    let mut s = cover(1.2);
    press_mount(&mut s);
    let center = s.player.mount.unwrap().yaw_center;
    s.player.yaw = center + 2.;
    s.player.pitch = 1.2;
    s.clamp_look(&cfg());
    let t = cfg().action;
    assert!((s.player.yaw - center - t.mount_yaw_limit.to_radians()).abs() < 1e-4);
    assert!((s.player.pitch - t.mount_pitch_up.to_radians()).abs() < 1e-5);
    s.player.yaw = center;
    s.player.pitch = 0.2;
    let mut free = cover(1.2);
    free.player.pitch = 0.2;
    for sim in [&mut s, &mut free] {
        sim.update(
            Input {
                fire: true,
                ..Input::default()
            },
            &cfg(),
            FIXED_DT,
        );
        assert_eq!(sim.stats.shots, 1);
    }
    let ratio = s.player.recoil.x / free.player.recoil.x;
    assert!((ratio - t.mount_recoil_scale).abs() < 1e-3, "{ratio}");
    // Reload keeps the mount.
    s.player.ammo = 5;
    run(
        &mut s,
        Input {
            reload: true,
            ..Input::default()
        },
        2,
    );
    assert!(s.player.reload_left > 0. && s.player.mount.is_some());
}

#[test]
fn movement_jump_stance_release_and_lost_support_unmount_cleanly() {
    let inputs = [
        Input {
            movement: vec2(0.5, 0.),
            ..Input::default()
        },
        Input {
            jump: true,
            ..Input::default()
        },
        Input {
            crouch: true,
            ..Input::default()
        },
        Input {
            mount: true,
            ..Input::default()
        },
    ];
    for (i, input) in inputs.into_iter().enumerate() {
        let mut s = cover(1.2);
        press_mount(&mut s);
        run(&mut s, Input::default(), 5);
        drain(&mut s);
        tick(&mut s, input);
        assert!(s.player.mount.is_none(), "case {i}");
        assert!(drain(&mut s).contains(&ActionEventKind::MountEnded));
    }
    let mut s = cover(1.2);
    press_mount(&mut s);
    s.blocks.remove(1);
    tick(&mut s, Input::default());
    assert!(s.player.mount.is_none(), "support removed");
    // Moving cover (changed top height) also releases.
    let mut s = cover(1.2);
    press_mount(&mut s);
    s.blocks[1].bounds.max.y = 1.0;
    tick(&mut s, Input::default());
    assert!(s.player.mount.is_none(), "support moved");
}

// ------------------------------------------------------------------ obstruction

fn facing_wall(gap: f32) -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![
        block(vec3(-30., -1., -30.), vec3(30., 0., 30.)),
        block(vec3(-3., 0., -6.), vec3(3., 3., -5.)),
    ];
    s.ramps.clear();
    s.targets.clear();
    // Eye-to-wall distance `gap`.
    s.player.position = vec3(0., 0., -5. + gap);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    s
}

#[test]
fn weapon_retracts_smoothly_and_lowers_against_a_close_wall() {
    let mut s = facing_wall(RADIUS + 0.02);
    let t = cfg().action;
    let mut last = 0.;
    for _ in 0..60 {
        tick(&mut s, Input::default());
        let a = s.player.obstruction.amount;
        assert!(
            a - last <= t.obstruct_rate_in * FIXED_DT + 1e-5,
            "rate limited"
        );
        last = a;
    }
    let o = s.player.obstruction;
    assert_eq!(o.amount, 1.);
    assert!(o.fire_blocked && o.ads_blocked);
    assert_eq!(o.direction, Vec3::Z, "wall normal toward the player");
    let perms = s.weapon_permissions();
    assert!(!perms.fire && !perms.ads);
    run(
        &mut s,
        Input {
            fire: true,
            ads: true,
            ..Input::default()
        },
        20,
    );
    assert_eq!(s.stats.shots, 0);
    assert_eq!(s.player.ads, 0.);
}

#[test]
fn partial_retraction_fires_from_in_front_of_the_wall() {
    let mut s = facing_wall(0.6);
    run(&mut s, Input::default(), 60);
    let o = s.player.obstruction;
    assert!(o.amount > 0.2 && o.amount < 0.85, "{}", o.amount);
    assert!(!o.fire_blocked && o.ads_blocked);
    tick(
        &mut s,
        Input {
            fire: true,
            ..Input::default()
        },
    );
    let shot = s.events.last().expect("shot");
    assert!(
        shot.muzzle.z > -5.,
        "muzzle {:?} beyond the wall",
        shot.muzzle
    );
    assert!(shot.end.z >= -5. - 1e-3, "bullet stops at the wall");
}

#[test]
fn off_center_obstruction_is_detected_along_the_weapon_not_the_eye_ray() {
    let mut s = Simulation::new();
    s.blocks = vec![
        block(vec3(-30., -1., -30.), vec3(30., 0., 30.)),
        // A thin post right of the eye line, at the hip weapon's height.
        block(vec3(0.09, 1.2, -0.6), vec3(0.3, 1.5, -0.5)),
    ];
    s.ramps.clear();
    s.targets.clear();
    s.player.position = Vec3::ZERO;
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    let eye = s.player.eye();
    assert!(
        s.blocks[1].bounds.ray(eye, -Vec3::Z, 2.).is_none(),
        "eye ray clear"
    );
    run(&mut s, Input::default(), 30);
    assert!(s.player.obstruction.raw > 0.);
    assert!(s.player.obstruction.amount > 0.);
}

#[test]
fn hysteresis_prevents_jitter_and_recovery_settles_to_zero() {
    let t = cfg().action;
    let mut s = facing_wall(0.55);
    run(&mut s, Input::default(), 60);
    // Wobble 1 cm back and forth at the edge: the lowered/fire flag is stable.
    let mut flips = 0;
    let mut blocked = s.player.obstruction.fire_blocked;
    let mut ads = s.player.obstruction.ads_blocked;
    for i in 0..240 {
        s.player.position.z = -5. + 0.55 + if i % 2 == 0 { 0.01 } else { -0.01 };
        tick(&mut s, Input::default());
        flips += (s.player.obstruction.fire_blocked != blocked) as u32;
        flips += (s.player.obstruction.ads_blocked != ads) as u32;
        blocked = s.player.obstruction.fire_blocked;
        ads = s.player.obstruction.ads_blocked;
    }
    assert_eq!(flips, 0);
    // Step back: hold for the recovery delay, then a monotonic return to zero.
    s.player.position.z = 0.;
    let held = s.player.obstruction.amount;
    let delay = (t.obstruct_recover_delay / FIXED_DT).floor() as usize;
    run(&mut s, Input::default(), delay.saturating_sub(1));
    assert_eq!(s.player.obstruction.amount, held);
    let mut last = held;
    for _ in 0..240 {
        tick(&mut s, Input::default());
        assert!(s.player.obstruction.amount <= last);
        last = s.player.obstruction.amount;
    }
    assert_eq!(last, 0.);
    assert_eq!(s.player.obstruction.direction, Vec3::ZERO);
}

// ---------------------------------------------------------------- death/respawn

#[test]
fn damage_kills_and_respawns_after_the_delay() {
    let mut s = Simulation::new();
    s.damage_player(40.);
    assert_eq!(s.player.health, 60.);
    assert!(!s.player.dead());
    s.damage_player(60.);
    assert!(s.player.dead());
    assert_eq!(drain(&mut s), vec![ActionEventKind::Died]);
    let spot = s.player.position;
    let delay = (cfg().action.respawn_delay / FIXED_DT).round() as usize;
    run(
        &mut s,
        Input {
            movement: vec2(0., 1.),
            fire: true,
            jump: true,
            ..Input::default()
        },
        delay,
    );
    assert!(s.player.dead());
    assert_eq!(s.player.position, spot, "dead players do not move");
    assert_eq!(s.stats.shots, 0, "or shoot");
    tick(&mut s, Input::default());
    assert!(!s.player.dead());
    assert_eq!(s.player.health, cfg().action.max_health);
    assert!(drain(&mut s).contains(&ActionEventKind::Respawned));
    assert_eq!(s.player.position, Simulation::new().player.position);
}

#[test]
fn falling_out_of_the_world_is_a_death() {
    let mut s = Simulation::new();
    s.blocks.clear();
    s.ramps.clear();
    run(&mut s, Input::default(), 240);
    assert!(s.player.dead());
}

fn into_state(state: &str) -> Simulation {
    let mut s = Simulation::new();
    let sprint = Input {
        movement: vec2(0., 1.),
        sprint: true,
        ..Input::default()
    };
    s.player.ammo = 5;
    match state {
        "slide" | "dive" | "tac" => {
            run(&mut s, sprint, 50);
            let input = match state {
                "slide" => Input {
                    crouch: true,
                    ..sprint
                },
                "dive" => Input {
                    prone: true,
                    ..sprint
                },
                _ => Input {
                    tactical_sprint: true,
                    ..sprint
                },
            };
            tick(&mut s, input);
        }
        "hang" => {
            s.player.position = vec3(-24., 0., 5. + RADIUS + 0.3);
            tick(
                &mut s,
                Input {
                    jump: true,
                    movement: vec2(0., 1.),
                    ..Input::default()
                },
            );
            for _ in 0..180 {
                tick(
                    &mut s,
                    Input {
                        movement: vec2(0., 1.),
                        ..Input::default()
                    },
                );
                if matches!(s.player.action, Action::Hang(_)) {
                    break;
                }
            }
        }
        "mount" => {
            s.player.position = vec3(-6., 0., -1.5 + RADIUS + 0.1);
            press_mount(&mut s);
        }
        "mantle" => {
            s.player.position = vec3(-6., 0., -1.5 + RADIUS + 0.1);
            tick(
                &mut s,
                Input {
                    jump: true,
                    movement: vec2(0., 1.),
                    ..Input::default()
                },
            );
        }
        "reload" => tick(
            &mut s,
            Input {
                reload: true,
                ..Input::default()
            },
        ),
        _ => unreachable!(),
    }
    s
}
const STATES: [&str; 7] = ["slide", "dive", "tac", "hang", "mount", "mantle", "reload"];

#[test]
fn every_state_is_reachable_for_conflict_tests() {
    for state in STATES {
        let s = into_state(state);
        let p = &s.player;
        let reached = match state {
            "slide" => matches!(p.action, Action::Slide(_)),
            "dive" => matches!(p.action, Action::Dive(_)),
            "tac" => p.tac_sprint.is_some(),
            "hang" => matches!(p.action, Action::Hang(_)),
            "mount" => p.mount.is_some(),
            "mantle" => p.mantle.is_some(),
            _ => p.reload_left > 0.,
        };
        assert!(reached, "{state}");
    }
}

#[test]
fn death_and_reset_clear_every_action() {
    for state in STATES {
        let mut s = into_state(state);
        s.kill();
        let p = &s.player;
        assert!(p.dead(), "{state}");
        assert!(matches!(p.action, Action::None));
        assert!(p.mantle.is_none() && p.mount.is_none() && p.tac_sprint.is_none());
        assert_eq!(p.reload_left, 0.);
        assert_eq!(s.weapon_permissions(), WeaponPermissions::NONE);
        assert_eq!(s.action_pose().slot, None);
        let mut s = into_state(state);
        s.loadout.sidearm_ammo = 7;
        s.reset();
        assert!(matches!(s.player.action, Action::None) && s.player.mount.is_none());
        assert_eq!(
            s.loadout.sidearm_ammo, 7,
            "reset keeps the loadout interface"
        );
    }
}

/// The documented permission table (docs/TRAVERSAL.md) as an executable check.
#[test]
fn documented_weapon_permission_table() {
    let p = |ads, fire, reload, sprint| WeaponPermissions {
        ads,
        fire,
        reload,
        sprint,
    };
    let table = [
        ("slide", p(false, false, false, false)), // entry phase
        ("dive", p(false, false, false, false)),  // launch phase
        ("hang", p(false, false, false, false)),  // both hands on the ledge
        ("mount", p(true, true, true, false)),
        ("mantle", p(false, false, false, false)),
        ("tac", p(true, true, true, true)),
    ];
    for (state, expected) in table {
        let s = into_state(state);
        assert_eq!(s.weapon_permissions(), expected, "{state}");
    }
    let mut s = into_state("slide");
    run(
        &mut s,
        Input {
            crouch: true,
            ..Input::default()
        },
        30,
    );
    assert_eq!(
        s.weapon_permissions(),
        p(true, true, true, false),
        "slide active"
    );
}

#[test]
fn targets_unaffected_by_obstruction_refactor_baseline_shot() {
    // Regression: an unobstructed shot still originates at the 0.85 m muzzle.
    let mut s = Simulation::new();
    s.targets = vec![Target {
        bounds: Aabb::from_center(s.player.eye() + vec3(0., 0., -8.), vec3(1., 1., 0.2)),
        health: 100.,
        respawn: 0.,
        flash: 0.,
    }];
    let cfg = Settings {
        hip_spread: 0.,
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
    let shot = s.events[0];
    assert!(((shot.muzzle - shot.start).dot(shot.barrel_forward) - 0.85).abs() < 1e-4);
    assert_eq!(s.targets[0].health, 66.);
}
