//! Original authored traversal contracts. Inputs and outcomes use public APIs;
//! rendering never drives mantle time or collision checks.
use macroquad::math::{vec2, vec3, Vec3};
use vector_range::{
    clock::FixedClock,
    settings::Settings,
    sim::{
        Aabb, Block, Input, MantleKind, Ramp, Simulation, FIXED_DT, MANTLE_LOW_HEIGHT,
        MANTLE_MAX_HEIGHT, MANTLE_MIN_HEIGHT, RADIUS,
    },
};

fn block(min: Vec3, max: Vec3) -> Block {
    Block {
        bounds: Aabb { min, max },
        kind: 2,
    }
}
fn fixture(height: f32) -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![
        block(vec3(-20., -1., -20.), vec3(20., 0., 20.)),
        block(vec3(-2., 0., -4.), vec3(2., height, 0.)),
    ];
    s.ramps.clear();
    s.targets.clear();
    s.player.position = vec3(0., 0., 1.);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    s
}
fn request() -> Input {
    Input {
        movement: vec2(0., 1.),
        jump: true,
        ..Input::default()
    }
}
fn tick(s: &mut Simulation, input: Input) {
    s.update(input, &Settings::default(), FIXED_DT);
}
fn ticks(s: &mut Simulation, input: Input, count: usize) {
    for _ in 0..count {
        tick(s, input);
    }
}
fn assert_clear(s: &Simulation) {
    let bounds = s.player.bounds_at(s.player.position);
    for b in &s.blocks {
        assert!(
            !bounds.overlaps(b.bounds),
            "player {:?} penetrated {:?}",
            s.player.position,
            b.bounds
        );
    }
}
fn complete(s: &mut Simulation, input: Input) -> usize {
    let mut count = 0;
    while s.player.mantle.is_some() {
        tick(s, input);
        assert_clear(s);
        count += 1;
        assert!(count < 130, "mantle did not finish");
    }
    count
}

#[test]
fn low_and_high_land_on_real_top_with_full_standing_footprint() {
    for (height, kind) in [
        (0.6, MantleKind::Low),
        (1.2, MantleKind::Low),
        (1.8, MantleKind::High),
    ] {
        let mut s = fixture(height);
        tick(&mut s, request());
        let state = s.player.mantle.expect("eligible ledge");
        assert_eq!(state.kind, kind);
        assert!(state.progress() > 0. && state.progress() < 1.);
        assert_eq!(s.player.velocity, Vec3::ZERO);
        assert!(!s.player.grounded);
        complete(&mut s, Input::default());
        assert_eq!(s.player.position, state.landing);
        assert_eq!(s.player.position.y, height);
        assert!(s.player.grounded);
        let bounds = s.player.bounds_at(s.player.position);
        let top = s.blocks[1].bounds;
        assert!(bounds.min.x > top.min.x && bounds.max.x < top.max.x);
        assert!(bounds.min.z > top.min.z && bounds.max.z < top.max.z);
        assert_clear(&s);
    }
}

#[test]
fn height_limits_are_inclusive_and_low_high_split_is_authored() {
    for (height, expected) in [
        (MANTLE_MIN_HEIGHT - 0.001, None),
        (MANTLE_MIN_HEIGHT, Some(MantleKind::Low)),
        (MANTLE_LOW_HEIGHT, Some(MantleKind::Low)),
        (MANTLE_LOW_HEIGHT + 0.001, Some(MantleKind::High)),
        (MANTLE_MAX_HEIGHT, Some(MantleKind::High)),
        (MANTLE_MAX_HEIGHT + 0.001, None),
    ] {
        let mut s = fixture(height);
        tick(&mut s, request());
        assert_eq!(s.player.mantle.map(|m| m.kind), expected, "height {height}");
        if expected.is_none() {
            assert!(s.player.velocity.y > 0., "normal jump remains available");
        }
    }
}

#[test]
fn too_high_ledge_keeps_normal_jump() {
    let mut s = fixture(2.4);
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert!(s.player.velocity.y > 0.);
    assert!(s.player.position.y > 0.);
}

#[test]
fn no_ledge_and_out_of_reach_keep_normal_jump() {
    for z in [2., 4.] {
        let mut s = fixture(1.2);
        s.player.position.z = z;
        tick(&mut s, request());
        assert!(s.player.mantle.is_none());
        assert!(s.player.velocity.y > 0.);
    }
    let mut s = fixture(1.2);
    s.blocks.pop();
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert!(s.player.velocity.y > 0.);
}

#[test]
fn mantle_requires_fresh_forward_grounded_intent() {
    for input in [
        Input {
            jump: true,
            ..Input::default()
        },
        Input {
            movement: vec2(0., -1.),
            ..request()
        },
        Input {
            movement: vec2(1., 0.),
            ..request()
        },
        Input {
            movement: vec2(1., 0.2),
            ..request()
        },
        Input {
            jump: false,
            ..request()
        },
    ] {
        let mut s = fixture(1.2);
        tick(&mut s, input);
        assert!(s.player.mantle.is_none());
    }
    let mut held = fixture(1.2);
    held.player.jump_held = true;
    tick(&mut held, request());
    assert!(held.player.mantle.is_none());
    let mut airborne = fixture(1.2);
    airborne.player.grounded = false;
    airborne.player.position.y = 0.1;
    tick(&mut airborne, request());
    assert!(airborne.player.mantle.is_none());
}

#[test]
fn prior_jump_cooldown_is_preserved() {
    let mut s = fixture(1.2);
    s.player.last_jump_at = 0.;
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert_eq!(s.player.position.y, 0.);
    ticks(&mut s, Input::default(), 60);
    tick(&mut s, request());
    assert!(s.player.mantle.is_some());
}

#[test]
fn landing_requires_standing_clearance_even_when_crouch_would_fit() {
    let mut s = fixture(1.2);
    s.blocks
        .push(block(vec3(-2., 2.65, -4.), vec3(2., 2.9, 0.)));
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert!(s.player.velocity.y > 0.);
}

#[test]
fn small_off_center_landing_obstacle_cannot_be_missed_by_center_ray() {
    let mut s = fixture(1.2);
    s.blocks
        .push(block(vec3(0.25, 1.2, -0.7), vec3(0.30, 2.6, -0.2)));
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
}

#[test]
fn overhead_at_start_blocks_vertical_lift() {
    let mut s = fixture(1.2);
    s.blocks
        .push(block(vec3(-1., 2.05, 0.4), vec3(1., 2.1, 1.6)));
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert_clear(&s);
}

#[test]
fn thin_tall_wall_between_player_and_ledge_blocks_traversal() {
    let mut s = fixture(1.2);
    s.blocks
        .push(block(vec3(-2., 0., 0.35), vec3(2., 4., 0.352)));
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert_clear(&s);
}

#[test]
fn thin_rail_and_corner_without_full_support_are_rejected() {
    let mut thin = fixture(1.2);
    thin.blocks[1].bounds.min.z = -0.3;
    tick(&mut thin, request());
    assert!(thin.player.mantle.is_none());
    let mut corner = fixture(1.2);
    corner.player.position.x = 1.8;
    tick(&mut corner, request());
    assert!(corner.player.mantle.is_none());
}

#[test]
fn diagonal_input_does_not_extend_reach_or_change_landing() {
    let mut straight = fixture(1.2);
    let mut diagonal = fixture(1.2);
    tick(&mut straight, request());
    tick(
        &mut diagonal,
        Input {
            movement: vec2(1., 1.),
            ..request()
        },
    );
    assert_eq!(
        straight.player.mantle.unwrap().landing,
        diagonal.player.mantle.unwrap().landing
    );
    complete(&mut straight, Input::default());
    complete(&mut diagonal, Input::default());
    assert_eq!(straight.player.position, diagonal.player.position);
    let mut far = fixture(1.2);
    far.player.position.z = 1.10;
    tick(
        &mut far,
        Input {
            movement: vec2(1., 1.),
            ..request()
        },
    );
    assert!(far.player.mantle.is_none());
}

#[test]
fn diagonal_view_climbs_corner_only_when_full_box_fits() {
    let mut s = fixture(1.2);
    s.blocks[1] = block(vec3(0., 0., -4.), vec3(4., 1.2, 0.));
    s.player.position = vec3(-0.7, 0., 0.7);
    s.player.yaw = -std::f32::consts::FRAC_PI_4;
    tick(&mut s, request());
    assert!(s.player.mantle.is_some());
    complete(&mut s, Input::default());
    assert!(s.player.position.x - RADIUS > 0.);
    assert!(s.player.position.z + RADIUS < 0.);
    assert_clear(&s);
}

#[test]
fn sideways_and_away_view_do_not_find_ledge_behind_player() {
    for yaw in [0., std::f32::consts::FRAC_PI_2, std::f32::consts::PI] {
        let mut s = fixture(1.2);
        s.player.yaw = yaw;
        tick(&mut s, request());
        assert!(s.player.mantle.is_none());
    }
}

#[test]
fn ramps_obstruct_full_player_volume_but_are_not_mantle_targets() {
    let mut s = fixture(1.2);
    // A narrow wedge catches the player's right side, clear of the center ray.
    s.ramps.push(Ramp {
        x: 0.35,
        z: 0.7,
        width: 0.15,
        length: 0.8,
        height: 4.,
    });
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    let mut only_ramp = fixture(1.2);
    only_ramp.blocks.pop();
    only_ramp.ramps.push(Ramp {
        x: 0.,
        z: 0.,
        width: 4.,
        length: 3.,
        height: 1.2,
    });
    tick(&mut only_ramp, request());
    assert!(only_ramp.player.mantle.is_none());
    assert!(only_ramp.player.velocity.y > 0.);
}

#[test]
fn low_ramp_below_traversal_does_not_get_a_false_bounding_box_hit() {
    let mut s = fixture(1.2);
    s.ramps.push(Ramp {
        x: 0.,
        z: 0.5,
        width: 2.,
        length: 3.,
        height: 0.5,
    });
    tick(&mut s, request());
    assert!(s.player.mantle.is_some());
    complete(&mut s, Input::default());
    assert_eq!(s.player.position.y, 1.2);
}

#[test]
fn held_jump_cannot_restart_on_a_second_ledge() {
    let mut s = fixture(0.6);
    tick(&mut s, request());
    complete(
        &mut s,
        Input {
            jump: true,
            ..Input::default()
        },
    );
    let landing = s.player.position;
    s.blocks
        .push(block(vec3(-2., 0.6, -5.), vec3(2., 1.8, landing.z - 1.)));
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert!(s.player.grounded);
    tick(&mut s, Input::default());
    tick(&mut s, request());
    assert!(
        s.player.mantle.is_some(),
        "release and repress permits the second ledge"
    );
}

#[test]
fn presses_during_mantle_are_not_queued_as_extra_jumps() {
    let mut s = fixture(1.2);
    tick(&mut s, request());
    ticks(&mut s, Input::default(), 10);
    complete(&mut s, request());
    let y = s.player.position.y;
    tick(
        &mut s,
        Input {
            jump: true,
            ..Input::default()
        },
    );
    assert!(s.player.mantle.is_none());
    assert_eq!(s.player.position.y, y);
    assert!(s.player.grounded);
}

#[test]
fn crouch_and_prone_keep_stand_up_and_clearance_semantics() {
    for prone in [false, true] {
        let mut s = fixture(1.2);
        let stance = Input {
            crouch: !prone,
            prone,
            ..Input::default()
        };
        ticks(&mut s, stance, 120);
        assert!(s.player.crouched);
        tick(
            &mut s,
            Input {
                jump: true,
                movement: vec2(0., 1.),
                ..stance
            },
        );
        assert!(s.player.mantle.is_none());
        assert_eq!(s.player.position.y, 0.);
    }
    let mut low = fixture(1.2);
    ticks(
        &mut low,
        Input {
            crouch: true,
            ..Input::default()
        },
        60,
    );
    low.blocks
        .push(block(vec3(-1., 1.4, 0.4), vec3(1., 1.6, 1.6)));
    tick(
        &mut low,
        Input {
            crouch: true,
            ..request()
        },
    );
    assert!(low.player.crouched);
    assert!(low.player.mantle.is_none());
    assert_clear(&low);
}

#[test]
fn stance_and_sprint_requests_cannot_shrink_or_accelerate_active_mantle() {
    let mut a = fixture(1.8);
    let mut b = fixture(1.8);
    tick(&mut a, request());
    tick(&mut b, request());
    while a.player.mantle.is_some() {
        tick(&mut a, Input::default());
        tick(
            &mut b,
            Input {
                movement: vec2(1., -1.),
                prone: true,
                crouch: true,
                sprint: true,
                ..Input::default()
            },
        );
        assert_eq!(a.player.position, b.player.position);
        assert!(!b.player.crouched && !b.player.prone && !b.player.sprinting);
    }
}

#[test]
fn cancel_is_idempotent_preserves_pose_and_falls_safely() {
    for elapsed in [1, 25, 48, 64] {
        let mut s = fixture(1.2);
        tick(&mut s, request());
        ticks(
            &mut s,
            Input {
                jump: true,
                ..Input::default()
            },
            elapsed,
        );
        assert!(s.player.mantle.is_some());
        let pos = s.player.position;
        s.cancel_mantle();
        s.cancel_mantle();
        assert!(s.player.mantle.is_none());
        assert_eq!(s.player.position, pos);
        assert_eq!(s.player.velocity, Vec3::ZERO);
        assert!(s.player.jump_held);
        for _ in 0..180 {
            tick(
                &mut s,
                Input {
                    jump: true,
                    ..Input::default()
                },
            );
            assert_clear(&s);
            assert!(s.player.mantle.is_none());
        }
        assert!(s.player.grounded);
        assert!(s.player.position.y == 0. || s.player.position.y == 1.2);
    }
}

#[test]
fn cancel_when_idle_does_not_change_existing_jump() {
    let mut s = fixture(1.2);
    tick(
        &mut s,
        Input {
            jump: true,
            ..Input::default()
        },
    );
    let velocity = s.player.velocity;
    s.cancel_mantle();
    assert_eq!(s.player.velocity, velocity);
}

#[test]
fn reset_discards_mantle_state_and_old_landing() {
    let mut s = fixture(1.8);
    tick(&mut s, request());
    assert!(s.player.mantle.is_some());
    s.reset();
    assert!(s.player.mantle.is_none());
    assert_eq!(s.player.position, vec3(0., 0., 9.));
    assert_eq!(s.player.velocity, Vec3::ZERO);
    assert_eq!(s.time, 0.);
}

#[test]
fn newly_blocked_path_aborts_before_thin_wall_without_tunneling() {
    let mut s = fixture(1.2);
    tick(&mut s, request());
    // The wall is outside the current box and outside the landing box.
    let wall = block(vec3(-2., 0., 0.10), vec3(2., 4., 0.101));
    s.blocks.push(wall);
    for _ in 0..100 {
        tick(&mut s, Input::default());
        assert_clear(&s);
        if s.player.mantle.is_none() {
            break;
        }
    }
    assert!(s.player.mantle.is_none());
    assert!(s.player.position.z >= 0.101 + RADIUS);
    assert_eq!(s.player.velocity, Vec3::ZERO);
}

#[test]
fn newly_blocked_landing_and_removed_support_cancel_without_teleporting() {
    for remove in [false, true] {
        let mut s = fixture(1.2);
        tick(&mut s, request());
        ticks(&mut s, Input::default(), 10);
        let pos = s.player.position;
        if remove {
            s.blocks.remove(1);
        } else {
            s.blocks.push(block(vec3(-1., 1.2, -1.), vec3(1., 3., 0.)));
        }
        tick(&mut s, Input::default());
        assert!(s.player.mantle.is_none());
        assert_eq!(s.player.position, pos);
        assert_clear(&s);
    }
}

#[test]
fn weapons_and_ads_are_excluded_through_final_mantle_tick() {
    let mut s = fixture(1.2);
    s.player.ammo = 15;
    s.player.ads = 1.;
    let held = Input {
        ads: true,
        fire: true,
        reload: true,
        ..request()
    };
    tick(&mut s, held);
    assert!(s.player.mantle.is_some());
    assert_eq!(s.stats.shots, 0);
    assert_eq!(s.player.reload_left, 0.);
    complete(&mut s, held);
    assert_eq!(s.stats.shots, 0);
    assert_eq!(s.player.ammo, 15);
    assert_eq!(s.player.ads, 0.);
    tick(&mut s, held);
    assert_eq!(s.stats.shots, 1, "held fire resumes after traversal");
    assert_eq!(s.player.reload_left, 0., "held reload is not queued");
    tick(&mut s, Input::default());
    tick(
        &mut s,
        Input {
            reload: true,
            ..Input::default()
        },
    );
    assert!(s.player.reload_left > 0.);
}

#[test]
fn mantle_cancels_reload_without_fabricating_or_losing_rounds() {
    for credited in [false, true] {
        let mut s = fixture(1.2);
        s.player.ammo = 7;
        tick(
            &mut s,
            Input {
                reload: true,
                ..Input::default()
            },
        );
        if credited {
            while !s.player.reload_credited {
                tick(&mut s, Input::default());
            }
        }
        let ammo = (s.player.ammo, s.player.reserve);
        tick(&mut s, request());
        assert!(s.player.mantle.is_some());
        assert_eq!(s.player.reload_left, 0.);
        complete(&mut s, Input::default());
        assert_eq!((s.player.ammo, s.player.reserve), ammo);
    }
}

#[test]
fn empty_reload_is_canceled_and_does_not_grant_ammo_during_traversal() {
    let mut s = fixture(1.8);
    s.player.ammo = 0;
    tick(
        &mut s,
        Input {
            reload: true,
            ..Input::default()
        },
    );
    tick(&mut s, request());
    assert!(s.player.mantle.is_some());
    complete(&mut s, Input::default());
    assert_eq!(s.player.ammo, 0);
    assert_eq!(s.player.reserve, 90);
}

#[test]
fn authoritative_fixed_ticks_match_30_60_144_240_render_partitions() {
    for height in [0.6, 1.8] {
        let mut baseline = None;
        for fps in [30, 60, 144, 240] {
            let mut s = fixture(height);
            let mut clock = FixedClock::default();
            let mut tick_index = 0;
            let mut trace = Vec::new();
            for _ in 0..fps * 2 {
                for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                    let input = if tick_index == 0 {
                        request()
                    } else {
                        Input::default()
                    };
                    tick(&mut s, input);
                    trace.push((
                        s.player.position,
                        s.player.velocity,
                        s.player.grounded,
                        s.player.mantle.map(|m| (m.kind, m.progress())),
                        s.player.ammo,
                        s.stats.shots,
                    ));
                    tick_index += 1;
                }
            }
            assert_eq!(tick_index, 240);
            assert_eq!(s.player.position.y, height);
            assert!(s.player.grounded);
            if let Some(expected) = &baseline {
                assert_eq!(&trace, expected, "{fps} FPS, {height} m");
            } else {
                baseline = Some(trace);
            }
        }
    }
}

#[test]
fn authored_durations_end_on_72_and_102_fixed_ticks() {
    for (height, expected_ticks, duration) in [(0.6, 72, 0.60), (1.8, 102, 0.85)] {
        let mut s = fixture(height);
        tick(&mut s, request());
        assert_eq!(s.player.mantle.unwrap().duration(), duration);
        let mut last_progress = s.player.mantle.unwrap().progress();
        let mut total = 1;
        while s.player.mantle.is_some() {
            tick(&mut s, Input::default());
            if let Some(state) = s.player.mantle {
                assert!(state.progress() > last_progress);
                last_progress = state.progress();
            }
            total += 1;
        }
        assert_eq!(total, expected_ticks);
    }
}

#[test]
fn thin_head_obstruction_on_upper_path_is_detected_between_clear_endpoints() {
    let mut s = fixture(1.2);
    s.blocks
        .push(block(vec3(-2., 2.99, 0.1), vec3(2., 2.992, 0.102)));
    tick(&mut s, request());
    assert!(s.player.mantle.is_none());
    assert_clear(&s);
}

#[test]
fn new_overhead_obstruction_stops_lift_without_head_tunneling() {
    let mut s = fixture(1.8);
    tick(&mut s, request());
    s.blocks
        .push(block(vec3(-1., 2.20, 0.5), vec3(1., 2.201, 1.5)));
    for _ in 0..100 {
        tick(&mut s, Input::default());
        assert_clear(&s);
        if s.player.mantle.is_none() {
            break;
        }
    }
    assert!(s.player.mantle.is_none());
    assert!(s.player.position.y + s.player.height() <= 2.20);
}

#[test]
fn render_interpolation_between_fixed_poses_never_cuts_into_the_ledge() {
    for height in [0.5, 0.6, 1.2, 1.8, 1.85] {
        for flush in [false, true] {
            let mut s = fixture(height);
            if flush {
                s.player.position.z = RADIUS;
            }
            let mut previous = s.player.position;
            tick(&mut s, request());
            assert!(s.player.mantle.is_some());
            loop {
                let current = s.player.position;
                for sample in 0..=100 {
                    let interpolated = previous.lerp(current, sample as f32 / 100.);
                    let bounds = s.player.bounds_at(interpolated);
                    assert!(
                        !s.blocks.iter().any(|b| bounds.overlaps(b.bounds)),
                        "interpolated collision at height {height}, flush {flush}, sample {sample}"
                    );
                }
                if s.player.mantle.is_none() {
                    break;
                }
                previous = current;
                tick(&mut s, Input::default());
            }
        }
    }
}

#[test]
fn starting_from_an_elevated_walkable_platform_uses_relative_ledge_height() {
    let mut s = fixture(1.2);
    s.blocks[0].bounds.max.y = 3.;
    s.blocks[1].bounds.max.y = 4.2;
    s.player.position.y = 3.;
    tick(&mut s, request());
    assert!(s.player.mantle.is_some());
    complete(&mut s, Input::default());
    assert_eq!(s.player.position.y, 4.2);
}
