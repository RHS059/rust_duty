use glam::vec2;
use vector_range::{
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
};
fn main() {
    let cfg = Settings::default();
    let mut sim = Simulation::new();
    let forward = Input {
        movement: vec2(0., 1.),
        ..Input::default()
    };
    let mut reach = None;
    for tick in 0..120 {
        sim.update(forward, &cfg, FIXED_DT);
        if reach.is_none() && sim.player.speed() >= cfg.walk_speed * 0.99 {
            reach = Some((tick + 1) as f32 * FIXED_DT);
        }
    }
    let settled = sim.player.speed();
    let mut stop = None;
    for tick in 0..120 {
        sim.update(Input::default(), &cfg, FIXED_DT);
        if stop.is_none() && sim.player.speed() < 0.0254 {
            stop = Some((tick + 1) as f32 * FIXED_DT);
        }
    }
    sim.reset();
    let mut apex: f32 = 0.;
    let mut apex_time = 0.;
    let mut landing = 0.;
    for tick in 0..120 {
        sim.update(
            Input {
                jump: tick == 0,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
        if sim.player.position.y > apex {
            apex = sim.player.position.y;
            apex_time = (tick + 1) as f32 * FIXED_DT;
        }
        if tick > 0 && sim.player.grounded {
            landing = (tick + 1) as f32 * FIXED_DT;
            break;
        }
    }
    sim.reset();
    for _ in 0..108 {
        sim.update(
            Input {
                fire: true,
                ..Input::default()
            },
            &cfg,
            FIXED_DT,
        );
    }
    println!("Vector Range / fixed 120 Hz / deterministic seed\nforward_speed_mps={settled:.6}\ntime_to_99pct_s={:.6}\ntime_to_stop_s={:.6}\njump_apex_m={apex:.6}\njump_apex_time_s={apex_time:.6}\njump_landing_time_s={landing:.6}\nshots_in_0_to_900ms_exclusive={}\nshot_times_s={:?}",reach.unwrap(),stop.unwrap(),sim.stats.shots,sim.events.iter().map(|s|s.time).collect::<Vec<_>>());
    if std::env::args().any(|x| x == "--write-preset") {
        cfg.save("settings.cfg").expect("write settings.cfg");
    }
}
