//! Exercise the shipped level through its production loader and player physics.
use glam::{vec2, Vec3};
use serde_json::Value;
use std::path::Path;
use vector_range::{
    city_level::CityLevel,
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
};

fn point(value: &Value) -> Vec3 {
    Vec3::new(
        value[0].as_f64().unwrap() as f32,
        value[1].as_f64().unwrap() as f32,
        value[2].as_f64().unwrap() as f32,
    )
}

fn walk_route(sim: &mut Simulation, cfg: &Settings, route: &Value) {
    let path = route["path"].as_array().expect("authored route path");
    for waypoint in path {
        let target = point(waypoint);
        for tick in 0..2400 {
            let delta = target - sim.player.position;
            if vec2(delta.x, delta.z).length() < 0.065 {
                break;
            }
            assert!(
                tick < 2399,
                "player blocked at {:?}, heading for {:?}",
                sim.player.position,
                target
            );
            sim.player.yaw = delta.z.atan2(delta.x);
            sim.update(
                Input {
                    movement: vec2(0., 1.),
                    ..Input::default()
                },
                cfg,
                FIXED_DT,
            );
            assert!(!sim.player.dead(), "route must remain on supported floors");
        }
        // Release movement at corners, just as a player may pause to turn.
        for _ in 0..24 {
            sim.update(Input::default(), cfg, FIXED_DT);
        }
    }
    let destination = point(path.last().unwrap());
    assert!(
        (sim.player.position.y - destination.y).abs() < 0.035,
        "route ended on wrong floor: {:?}, expected {:?}",
        sim.player.position,
        destination
    );
    let bounds = sim.player.bounds_at(sim.player.position);
    assert!(
        !sim.blocks.iter().any(|block| bounds.overlaps(block.bounds)),
        "route ended inside collision at {:?}",
        sim.player.position
    );
}

#[test]
fn shipped_city_loads_and_player_walks_into_a_shop_and_up_its_stairs() {
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("assets/levels/cedar_junction/level.json");
    let city = CityLevel::load(&path).expect("the shipped city must load without range fallback");
    let metadata: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(city.name, "Cedar Junction");
    assert!(city.chunks.len() > 1, "city uses spatial mesh batches");
    let vertices: usize = city
        .chunks
        .iter()
        .map(|chunk| chunk.mesh.vertices.len())
        .sum();
    assert_eq!(
        vertices as u64,
        metadata["statistics"]["vertices"].as_u64().unwrap()
    );
    let building = &metadata["buildings"][0];
    let entry = building["routes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|route| route["kind"] == "entrance_to_stair")
        .unwrap();
    let upper_room = building["routes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|route| route["kind"] == "stair_to_room" && route["level"] == 1)
        .unwrap();
    let mut sim = Simulation::new();
    city.install(&mut sim);
    assert!(sim.targets.is_empty() && sim.ramps.is_empty());
    let original_colliders = sim.blocks.len();
    sim.player.position = point(&entry["path"][0]);
    let mut cfg = Settings::default();
    cfg.walk_speed = 1.5;
    walk_route(&mut sim, &cfg, entry);
    walk_route(&mut sim, &cfg, &building["stairs"][0]);
    walk_route(&mut sim, &cfg, upper_room);
    assert!(
        sim.player.position.y > 3.,
        "player reached an actual upper-floor room"
    );
    sim.reset();
    assert_eq!(sim.player.position, city.spawn_position);
    assert_eq!(sim.blocks.len(), original_colliders);
}
