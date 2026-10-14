//! Actual-pack full-pose ownership audit. This is CPU evidence, not native
//! rendering, a reload/ADS implementation, or an integrated visual acceptance.
use glam::{Mat4, Vec2};
use std::error::Error;
use vector_range::{
    authored_locomotion_adapter::{AuthoredLocomotionAdapter, PresentationAction},
    authored_locomotion_path::{AuthoredLocomotionPath, AuthoredLocomotionPathConfig},
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
    viewmodel_animation::{game_model_root, AnimationSet, ViewmodelPose},
};
fn config() -> AuthoredLocomotionPathConfig {
    AuthoredLocomotionPathConfig {
        ready_clip: "normal_ready".into(),
        entry_clip: "normal_entry_connected".into(),
        loop_clip: "normal_loop".into(),
        exit_bridge_clips: (0..35)
            .map(|i| format!("normal_exit_bridge_{i:03}"))
            .collect(),
        exit_clip: "normal_exit".into(),
        settle_clip: "normal_settle".into(),
        rate_response_seconds: 0.05,
        residual_decay_seconds: 0.03,
    }
}
fn same_pose(a: &ViewmodelPose, b: &ViewmodelPose) -> bool {
    a.bone_locals == b.bone_locals
        && a.actor_globals == b.actor_globals
        && a.actor_visible == b.actor_visible
}
fn same_matrices(a: &[Mat4], b: &[Mat4]) -> bool {
    a.len() == b.len() && a.iter().zip(b).all(|(a, b)| a == b)
}
fn main() -> Result<(), Box<dyn Error>> {
    let path = std::env::args()
        .nth(1)
        .ok_or("usage: audit_authored_locomotion_adapter FILE.vra")?;
    let (animation, skin, _) = AnimationSet::load_with_companions(path)?;
    let cfg = Settings::default();
    let mut handoffs = 0_u32;
    let mut comparisons = 0_u32;
    let mut returns = 0_u32;
    let mut authoritative_ticks = 0_u32;
    // Sample rest, entry, loop and the authored exit under both main actions.
    for reason in [PresentationAction::Reload, PresentationAction::Ads] {
        for history in 0..3 {
            for event_tick in (0..=120).step_by(3) {
                let mut simulation = Simulation::new();
                let mut baseline = Simulation::new();
                simulation.player.ammo = 2;
                baseline.player.ammo = 2;
                let mut adapter = AuthoredLocomotionAdapter::new(&animation, config(), 0.)?;
                let mut expected = AuthoredLocomotionPath::new(&animation, config(), 0.)?;
                let mut last_sprint = false;
                let mut event = None;
                for tick in 0..=event_tick {
                    let start = simulation.time;
                    let input = if tick == event_tick {
                        Input {
                            reload: reason == PresentationAction::Reload,
                            ads: reason == PresentationAction::Ads,
                            ..Input::default()
                        }
                    } else {
                        let sprint = match history {
                            0 => true,
                            1 => tick < 40,
                            _ => (tick / 7) % 2 == 0,
                        };
                        Input {
                            sprint,
                            movement: Vec2::Y,
                            ..Input::default()
                        }
                    };
                    // Independently advance the old intent to the action time.
                    expected.update(&animation, start, last_sprint, true)?;
                    simulation.update(input, &cfg, FIXED_DT);
                    baseline.update(input, &cfg, FIXED_DT);
                    let handoff = adapter.committed_step(&animation, start, &simulation)?;
                    if let Some(handoff) = handoff {
                        assert_eq!(tick, event_tick);
                        assert_eq!(handoff.action(), reason);
                        assert_eq!(handoff.simulation_time(), start);
                        assert!(same_pose(handoff.pose(), expected.pose()));
                        handoff.validate_receiver(&animation)?;
                        let a = animation.skin_palette(
                            handoff.pose(),
                            &skin.bones,
                            game_model_root(),
                        )?;
                        let b = animation.skin_palette(
                            expected.pose(),
                            &skin.bones,
                            game_model_root(),
                        )?;
                        assert!(same_matrices(&a, &b));
                        comparisons += a.len() as u32;
                        let a = animation.actor_matrices(handoff.pose(), game_model_root())?;
                        let b = animation.actor_matrices(expected.pose(), game_model_root())?;
                        assert!(same_matrices(&a, &b));
                        comparisons += a.len() as u32;
                        assert!(adapter.pose().is_none());
                        event = Some(handoff);
                        handoffs += 1;
                    } else {
                        last_sprint = simulation.player.sprinting;
                        expected.update(&animation, start, last_sprint, true)?;
                        expected.update(&animation, simulation.time, last_sprint, true)?;
                        assert!(same_pose(adapter.pose().unwrap(), expected.pose()));
                    }
                    assert_eq!(
                        simulation.player.reload_ready_at,
                        baseline.player.reload_ready_at
                    );
                    assert_eq!(
                        simulation.player.reload_credit_at,
                        baseline.player.reload_credit_at
                    );
                    assert_eq!(simulation.player.ads, baseline.player.ads);
                    authoritative_ticks += 1;
                }
                let event = event.ok_or("event did not hand off")?;
                for _ in 0..420 {
                    let start = simulation.time;
                    simulation.update(Input::default(), &cfg, FIXED_DT);
                    baseline.update(Input::default(), &cfg, FIXED_DT);
                    assert!(adapter
                        .committed_step(&animation, start, &simulation)?
                        .is_none());
                    assert!(adapter.pose().is_none());
                    assert_eq!(adapter.pending_handoff().unwrap().pose(), event.pose());
                    assert_eq!(simulation.player.ammo, baseline.player.ammo);
                    assert_eq!(simulation.player.reserve, baseline.player.reserve);
                    assert_eq!(simulation.player.reload_left, baseline.player.reload_left);
                    assert_eq!(simulation.player.ads, baseline.player.ads);
                    authoritative_ticks += 1;
                }
                // This is an endpoint contract only. No reload/ADS return motion
                // is authored or certified by supplying this synthetic return.
                let ready = adapter.ready_pose().clone();
                adapter.return_ready(&animation, event.id(), simulation.time, &ready)?;
                assert!(same_pose(adapter.pose().unwrap(), &ready));
                returns += 1;
            }
        }
    }
    println!(
        "{{\"audit\":\"actual-pack CPU handoff and authoritative timing\",\"handoffs\":{handoffs},\"exact_skin_actor_matrix_comparisons\":{comparisons},\"authoritative_simulation_ticks\":{authoritative_ticks},\"ready_endpoint_returns\":{returns},\"handoff_transform_error\":0,\"gameplay_mismatches\":0,\"native_rendered\":false,\"reload_ads_motion_implemented\":false,\"return_motion_validated\":false}}"
    );
    Ok(())
}
