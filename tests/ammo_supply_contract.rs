//! Headless contracts for the original crate interaction and circle geometry.
//! Path inclusion lets this contract run before the main binary integrates it.
pub use vector_range::sim;
#[path = "../src/ammo_supply.rs"]
#[allow(dead_code)]
mod ammo_supply;
#[path = "../src/ammo_supply_view.rs"]
#[allow(dead_code)]
mod ammo_supply_view;
use ammo_supply::*;
use ammo_supply_view::*;
use macroquad::math::{vec2, vec3, Mat4, Vec2, Vec3};
use sim::{Aabb, Block, Player, Ramp, Simulation, Target, FIXED_DT, MAGAZINE};

fn fixture() -> (AmmoSupply, Simulation, SupplyView) {
    let supply = AmmoSupply::new(
        vec3(0., 0., -2.),
        SUPPLY_HALF_EXTENTS,
        SupplyConfig::default(),
    );
    let mut sim = Simulation::new();
    sim.blocks.clear();
    sim.ramps.clear();
    sim.targets.clear();
    sim.player.position = Vec3::ZERO;
    sim.player.ammo = 3;
    sim.player.reserve = 7;
    let view = looking_at(sim.player.eye(), supply.bounds().center());
    (supply, sim, view)
}
fn looking_at(eye: Vec3, target: Vec3) -> SupplyView {
    SupplyView::perspective(eye, target - eye, 65f32.to_radians(), vec2(1280., 720.)).unwrap()
}
fn obstacle(center: Vec3, size: Vec3) -> Block {
    Block {
        bounds: Aabb::from_center(center, size),
        kind: 2,
    }
}
fn ticks(
    supply: &mut AmmoSupply,
    sim: &mut Simulation,
    view: SupplyView,
    n: usize,
    dt: f32,
) -> usize {
    let mut completions = 0;
    for _ in 0..n {
        let focus = supply.focus(sim, view, true);
        completions +=
            (supply.tick(&mut sim.player, focus, true, true, dt) == SupplyEvent::Refilled) as usize;
    }
    completions
}

#[test]
fn default_crate_is_behind_spawn_inside_rear_wall_and_out_of_range() {
    let supply = AmmoSupply::default();
    let sim = Simulation::new();
    assert!(supply.floor_center.z > sim.player.position.z);
    assert!(supply.bounds().max.z < 13.75);
    assert_eq!(supply.bounds().min.y, 0.);
    let initial = looking_at(sim.player.eye(), sim.player.eye() + sim.player.direction());
    assert!(supply.focus(&sim, initial, true).is_none());
    let turned = looking_at(sim.player.eye(), supply.bounds().center());
    assert!(
        supply.focus(&sim, turned, true).is_none(),
        "turning at spawn is still too far away"
    );
}

#[test]
fn requires_near_and_direct_crosshair_hit_and_active_play() {
    let (supply, mut sim, view) = fixture();
    assert!(supply.focus(&sim, view, true).is_some());
    assert!(supply.focus(&sim, view, false).is_none());
    let look_away = looking_at(view.eye, view.eye + Vec3::X);
    assert!(supply.focus(&sim, look_away, true).is_none());
    let near_miss = looking_at(view.eye, supply.bounds().center() + Vec3::X * 0.60);
    assert!(
        supply.focus(&sim, near_miss, true).is_none(),
        "nearby cone aiming must not substitute for ray hit"
    );
    sim.player.position.z = 2.;
    let far = looking_at(sim.player.eye(), supply.bounds().center());
    assert!(supply.focus(&sim, far, true).is_none());
}

#[test]
fn range_is_distance_to_surface_and_includes_exact_limit() {
    let (mut supply, sim, view) = fixture();
    let distance = supply.focus(&sim, view, true).unwrap().distance;
    supply.config.range = distance;
    assert!(supply.focus(&sim, view, true).is_some());
    supply.config.range = distance - 0.002;
    assert!(supply.focus(&sim, view, true).is_none());
}

#[test]
fn walls_block_but_rear_wall_and_matching_crate_collider_do_not() {
    let (supply, mut sim, view) = fixture();
    sim.blocks
        .push(obstacle(vec3(0., 1., -1.), vec3(2., 2., 0.1)));
    assert!(supply.focus(&sim, view, true).is_none());
    sim.blocks.clear();
    sim.blocks
        .push(obstacle(vec3(0., 1., -2.5), vec3(3., 2., 0.1)));
    sim.blocks.push(Block {
        bounds: supply.bounds(),
        kind: 4,
    });
    assert!(supply.focus(&sim, view, true).is_some());
}

#[test]
fn ramps_and_live_targets_occlude_dead_targets_do_not() {
    let (supply, mut sim, view) = fixture();
    sim.ramps.push(Ramp {
        x: 0.,
        z: -0.1,
        width: 2.,
        length: 1.5,
        height: 3.,
    });
    assert!(supply.focus(&sim, view, true).is_none());
    sim.ramps.clear();
    sim.targets.push(Target {
        bounds: Aabb::from_center(vec3(0., 1., -1.), vec3(1., 2., 0.15)),
        health: 100.,
        respawn: 0.,
        flash: 0.,
    });
    assert!(supply.focus(&sim, view, true).is_none());
    sim.targets[0].health = 0.;
    assert!(supply.focus(&sim, view, true).is_some());
}

#[test]
fn hidden_hint_anchor_cancels_even_if_crate_is_visible() {
    let (supply, mut sim, view) = fixture();
    // At z=-1 the aim ray is y~0.887, while the hint ray is y~1.10.
    sim.blocks
        .push(obstacle(vec3(0., 1.10, -1.), vec3(0.3, 0.12, 0.08)));
    assert!(supply.focus(&sim, view, true).is_none());
}

#[test]
fn projection_rejects_behind_near_far_and_off_screen_anchors() {
    let view = looking_at(Vec3::ZERO, -Vec3::Z);
    let center = project_world(vec3(0., 0., -2.), view.view_projection, view.viewport).unwrap();
    assert!((center - view.viewport * 0.5).length() < 1e-4);
    for point in [
        vec3(0., 0., 2.),
        vec3(0., 0., -0.01),
        vec3(0., 0., -201.),
        vec3(20., 0., -2.),
        vec3(0., 20., -2.),
    ] {
        assert!(
            project_world(point, view.view_projection, view.viewport).is_none(),
            "{point:?}"
        );
    }
    assert!(project_world(Vec3::ZERO, Mat4::IDENTITY, Vec2::ZERO).is_none());
    assert!(project_world(Vec3::splat(f32::NAN), Mat4::IDENTITY, view.viewport).is_none());
}

#[test]
fn off_screen_projection_prevents_focus_and_world_anchor_tracks_camera() {
    let (supply, sim, view) = fixture();
    let first = supply.focus(&sim, view, true).unwrap();
    let changed = looking_at(
        view.eye + Vec3::X * 0.1,
        supply.bounds().center() + Vec3::X * 0.2,
    );
    let next = supply.focus(&sim, changed, true).unwrap();
    assert_eq!(first.world_anchor, next.world_anchor);
    assert!((first.screen_anchor - next.screen_anchor).length() > 10.);
    let mut hidden = view;
    hidden.view_projection = looking_at(view.eye, view.eye + Vec3::X).view_projection;
    assert!(supply.focus(&sim, hidden, true).is_none());
}

#[test]
fn invalid_view_geometry_or_inside_crate_never_interacts() {
    let (mut supply, sim, mut view) = fixture();
    assert!(SupplyView::perspective(Vec3::ZERO, Vec3::Y, 1., vec2(100., 100.)).is_none());
    assert!(SupplyView::perspective(Vec3::ZERO, -Vec3::Z, f32::NAN, vec2(100., 100.)).is_none());
    view.direction = Vec3::ZERO;
    assert!(supply.focus(&sim, view, true).is_none());
    view = looking_at(supply.bounds().center(), supply.bounds().center() - Vec3::Z);
    assert!(supply.focus(&sim, view, true).is_none());
    supply.half_extents.x = -1.;
    assert!(supply.focus(&sim, view, true).is_none());
}

#[test]
fn completes_at_1_5_seconds_and_only_refills_ammunition() {
    let (mut supply, mut sim, view) = fixture();
    sim.player.velocity = vec3(1., 2., 3.);
    sim.player.stamina = 2.;
    let position = sim.player.position;
    assert_eq!(ticks(&mut supply, &mut sim, view, 179, FIXED_DT), 0);
    assert!(supply.progress() > 0.99 && supply.progress() < 1.);
    assert_eq!((sim.player.ammo, sim.player.reserve), (3, 7));
    assert_eq!(ticks(&mut supply, &mut sim, view, 1, FIXED_DT), 1);
    assert_eq!((sim.player.ammo, sim.player.reserve), (MAGAZINE, 90));
    assert_eq!(sim.player.position, position);
    assert_eq!(sim.player.velocity, vec3(1., 2., 3.));
    assert_eq!(sim.player.stamina, 2.);
    assert_eq!(sim.stats.shots, 0);
    assert_eq!(supply.progress(), 0.);
    assert_eq!(ticks(&mut supply, &mut sim, view, 200, FIXED_DT), 0);
}

#[test]
fn all_interruptions_discard_partial_progress_immediately() {
    for reason in 0..4 {
        let (mut supply, mut sim, view) = fixture();
        ticks(&mut supply, &mut sim, view, 120, FIXED_DT);
        let focus = supply.focus(&sim, view, true);
        match reason {
            0 => {
                supply.tick(&mut sim.player, focus, false, true, FIXED_DT);
            }
            1 => {
                supply.tick(&mut sim.player, None, true, true, FIXED_DT);
            }
            2 => {
                supply.tick(&mut sim.player, focus, true, false, FIXED_DT);
            }
            _ => supply.cancel(), // render-frame cancellation with zero fixed steps
        }
        assert_eq!(supply.progress(), 0., "reason {reason}");
        assert_eq!(ticks(&mut supply, &mut sim, view, 120, FIXED_DT), 0);
        assert_eq!(sim.player.ammo, 3);
        assert_eq!(ticks(&mut supply, &mut sim, view, 60, FIXED_DT), 1);
    }
}

#[test]
fn physical_look_range_and_occlusion_loss_reset_hold() {
    for reason in 0..3 {
        let (mut supply, mut sim, view) = fixture();
        ticks(&mut supply, &mut sim, view, 120, FIXED_DT);
        let interrupted = match reason {
            0 => looking_at(view.eye, view.eye + Vec3::X),
            1 => looking_at(view.eye + Vec3::Z * 3., supply.bounds().center()),
            _ => {
                sim.blocks
                    .push(obstacle(vec3(0., 1., -1.), vec3(2., 2., 0.2)));
                view
            }
        };
        let focus = supply.focus(&sim, interrupted, true);
        assert!(focus.is_none());
        supply.tick(&mut sim.player, focus, true, true, FIXED_DT);
        assert_eq!(supply.progress(), 0.);
        assert_eq!(sim.player.ammo, 3);
    }
}

#[test]
fn full_ammunition_never_starts_pointless_hold() {
    let (mut supply, mut sim, view) = fixture();
    sim.player.ammo = MAGAZINE;
    sim.player.reserve = 90;
    assert!(supply.ammo_full(&sim.player));
    assert_eq!(ticks(&mut supply, &mut sim, view, 300, FIXED_DT), 0);
    assert_eq!(supply.progress(), 0.);
    sim.player.reserve = 89;
    assert!(!supply.ammo_full(&sim.player));
    assert_eq!(ticks(&mut supply, &mut sim, view, 180, FIXED_DT), 1);
}

#[test]
fn refill_assigns_caps_and_cancels_pending_reload() {
    let (mut supply, mut sim, view) = fixture();
    supply.config.reserve_capacity = 120;
    sim.player.ammo = MAGAZINE + 5;
    sim.player.reserve = 0;
    sim.player.reload_left = 2.;
    sim.player.reload_total = 2.5;
    sim.player.reload_credit_at = 1.;
    sim.player.reload_ready_at = 2.;
    sim.player.reload_empty = true;
    assert_eq!(ticks(&mut supply, &mut sim, view, 180, FIXED_DT), 1);
    assert_eq!((sim.player.ammo, sim.player.reserve), (MAGAZINE, 120));
    assert_eq!(sim.player.reload_left, 0.);
    assert_eq!(sim.player.reload_total, 0.);
    assert_eq!(sim.player.reload_credit_at, 0.);
    assert_eq!(sim.player.reload_ready_at, 0.);
    assert!(!sim.player.reload_empty);
}

#[test]
fn completion_is_latched_until_release_or_a_cancelled_gate() {
    let (mut supply, mut sim, view) = fixture();
    ticks(&mut supply, &mut sim, view, 180, FIXED_DT);
    sim.player.ammo = 0;
    assert_eq!(ticks(&mut supply, &mut sim, view, 180, FIXED_DT), 0);
    assert_eq!(sim.player.ammo, 0);
    supply.cancel();
    assert_eq!(ticks(&mut supply, &mut sim, view, 180, FIXED_DT), 1);
}

#[test]
fn duration_is_tunable_and_time_partition_is_stable() {
    for (dt, count) in [
        (1. / 30., 45),
        (1. / 60., 90),
        (1. / 120., 180),
        (0.01, 150),
    ] {
        let (mut supply, mut sim, view) = fixture();
        assert_eq!(ticks(&mut supply, &mut sim, view, count - 1, dt), 0);
        assert_eq!(ticks(&mut supply, &mut sim, view, 1, dt), 1);
    }
    let (mut supply, mut sim, view) = fixture();
    supply.config.hold_seconds = 0.5;
    assert_eq!(ticks(&mut supply, &mut sim, view, 59, FIXED_DT), 0);
    assert_eq!(ticks(&mut supply, &mut sim, view, 1, FIXED_DT), 1);
}

#[test]
fn invalid_and_stalled_timesteps_cancel_and_zero_time_does_not_advance() {
    for dt in [
        f32::NAN,
        f32::INFINITY,
        -0.001,
        MAX_HOLD_STEP_SECONDS + 0.01,
        1000.,
    ] {
        let (mut supply, mut sim, view) = fixture();
        ticks(&mut supply, &mut sim, view, 100, FIXED_DT);
        assert_eq!(ticks(&mut supply, &mut sim, view, 1, dt), 0);
        assert_eq!(supply.progress(), 0.);
        assert_eq!(sim.player.ammo, 3);
    }
    let (mut supply, mut sim, view) = fixture();
    ticks(&mut supply, &mut sim, view, 100, FIXED_DT);
    let progress = supply.progress();
    ticks(&mut supply, &mut sim, view, 100, 0.);
    assert_eq!(supply.progress(), progress);
    supply.reset();
    supply.config.hold_seconds = 1e-9;
    assert_eq!(ticks(&mut supply, &mut sim, view, 1, 0.), 0);
    assert_eq!(ticks(&mut supply, &mut sim, view, 1, FIXED_DT), 1);
}

#[test]
fn invalid_tuning_has_defaults_and_zero_reserve_capacity_is_supported() {
    let config = SupplyConfig {
        hold_seconds: -1.,
        range: f32::NAN,
        reserve_capacity: 0,
    }
    .sanitized();
    assert_eq!(config.hold_seconds, 1.5);
    assert_eq!(config.range, 2.25);
    let p = Player {
        reserve: 0,
        ..Player::default()
    };
    let supply = AmmoSupply::new(SUPPLY_FLOOR_CENTER, SUPPLY_HALF_EXTENTS, config);
    assert!(supply.ammo_full(&p));
}

#[test]
fn hold_circle_is_hidden_for_idle_cancelled_or_invalid_progress() {
    for progress in [0., -1., f32::NAN, f32::INFINITY] {
        assert!(!hold_circle_visible(progress));
    }
    for progress in [0.001, 0.5, 1.] {
        assert!(hold_circle_visible(progress));
    }
    let (mut supply, mut sim, view) = fixture();
    assert!(!hold_circle_visible(supply.progress()));
    ticks(&mut supply, &mut sim, view, 1, FIXED_DT);
    assert!(hold_circle_visible(supply.progress()));
    supply.cancel();
    assert!(!hold_circle_visible(supply.progress()));
    ticks(&mut supply, &mut sim, view, 180, FIXED_DT);
    assert!(!hold_circle_visible(supply.progress()));
}

#[test]
fn progress_circle_is_black_25_percent_and_gold_clockwise_from_twelve() {
    assert_eq!(
        (
            HOLD_BACKPLATE.r,
            HOLD_BACKPLATE.g,
            HOLD_BACKPLATE.b,
            HOLD_BACKPLATE.a
        ),
        (0., 0., 0., 0.25)
    );
    assert_eq!(SUPPLY_GOLD.a, 1.);
    let c = vec2(100., 100.);
    for (progress, expected) in [
        (0., vec2(100., 90.)),
        (0.25, vec2(110., 100.)),
        (0.5, vec2(100., 110.)),
        (0.75, vec2(90., 100.)),
        (1., vec2(100., 90.)),
    ] {
        assert!((clockwise_circle_point(c, 10., progress) - expected).length() < 1e-4);
    }
    assert!(clockwise_fill_triangles(c, 10., 0.).is_empty());
    assert!(clockwise_fill_triangles(c, 10., f32::NAN).is_empty());
    let quarter = clockwise_fill_triangles(c, 10., 0.25);
    assert_eq!(quarter.len(), 20);
    assert!((quarter[0][1] - vec2(100., 90.)).length() < 1e-4);
    assert!((quarter.last().unwrap()[2] - vec2(110., 100.)).length() < 1e-4);
    assert_eq!(clockwise_fill_triangles(c, 10., 1.).len(), 80);
}
