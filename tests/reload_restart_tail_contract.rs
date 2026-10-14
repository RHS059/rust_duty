//! Exercise the presentation adapter and actual CPU arm solver across reload
//! restarts and the live-fire tail, independently of private art or a GPU.
use glam::{vec2, EulerRot, Mat4, Quat, Vec3};
use vector_range::{
    arms::ArmModel,
    reference_motion::visual_duration,
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
    skinned_asset::{Bone, SkinnedAsset},
    view_animation::{ViewAnimation, WeaponFrame},
    weapon_animation::{AnimationInput, WeaponAnimationPose},
};

fn arms() -> ArmModel {
    let mut bones = Vec::new();
    for (side, shoulder_x) in [("l", 0.2), ("r", -0.2)] {
        let start = bones.len();
        for (segment, name) in ["upperarm", "lowerarm", "hand"].into_iter().enumerate() {
            bones.push(Bone {
                name: format!("{name}_{side}"),
                parent: (segment > 0).then_some(start + segment.saturating_sub(1)),
                rest_local: Mat4::from_translation(if segment == 0 {
                    Vec3::new(shoulder_x, 1.4, 0.1)
                } else {
                    Vec3::X * 0.35
                })
                .to_cols_array(),
                inverse_bind: Mat4::IDENTITY.to_cols_array(),
            });
        }
    }
    ArmModel::new(SkinnedAsset {
        bones,
        meshes: Vec::new(),
    })
    .unwrap()
}

fn body() -> Mat4 {
    Mat4::from_rotation_translation(
        Quat::from_euler(EulerRot::YXZ, 0.04118, -0.01252, 0.),
        Vec3::new(0.05930, -0.04831, -0.30806),
    )
}

fn solved(
    state: &ViewAnimation,
    pose: &WeaponAnimationPose,
    extra: Mat4,
) -> (Vec<Mat4>, Mat4, vector_range::weapon_ik::WeaponIkTargets) {
    let live = extra * body() * WeaponFrame::new(Vec3::ZERO, pose).matrix;
    let hand = state.hand_presentation();
    let route = hand.frames(body(), live);
    let globals = arms().posed_globals_with_weapon_ik(
        &route.targets,
        route.free_frame,
        pose,
        route.free_hands,
        route.influences,
        pose.left_hand_blend,
    );
    (
        globals,
        hand.held_magazine_matrix(body(), live),
        route.targets,
    )
}

fn assert_transform_close(a: Mat4, b: Mat4, label: &str) {
    let (_, ar, ap) = a.to_scale_rotation_translation();
    let (_, br, bp) = b.to_scale_rotation_translation();
    assert!(
        ap.distance(bp) < 0.0001,
        "{label}: jump {} mm",
        ap.distance(bp) * 1000.
    );
    assert!(
        1. - ar.dot(br).abs() < 0.000001,
        "{label}: orientation jumped"
    );
}

fn observe(state: &mut ViewAnimation, sim: &Simulation) -> (Option<f32>, WeaponAnimationPose) {
    let p = &sim.player;
    let progress = (p.reload_left > 0. && p.reload_total > 0.)
        .then(|| (1. - p.reload_left / p.reload_total).clamp(0., 1.));
    let completed =
        progress.is_none() && p.reload_ready_at > 0. && sim.time + 1e-6 >= p.reload_ready_at;
    let phase = state.presentation_progress(
        progress,
        p.reload_total,
        p.reload_empty,
        completed,
        sim.time,
    );
    let pose = state.sample_input(
        AnimationInput {
            reload_progress: phase,
            empty_reload: p.reload_empty,
            recoil: p.shot_kick,
            ads: p.ads,
            ..Default::default()
        },
        completed,
        sim.time,
    );
    (phase, pose)
}

#[test]
fn same_tick_sprint_cancel_and_reload_preserves_the_last_rendered_pose() {
    let cfg = Settings::m4_candidate();
    let mut sim = Simulation::new();
    sim.player.ammo = 15;
    sim.update(
        Input {
            reload: true,
            ..Default::default()
        },
        &cfg,
        FIXED_DT,
    );
    let mut state = ViewAnimation::default();
    observe(&mut state, &sim);
    for _ in 0..60 {
        sim.update(Input::default(), &cfg, FIXED_DT);
    }
    let (phase, before) = observe(&mut state, &sim);
    assert!(phase.unwrap() > 0.2);
    let (old_hands, _, _) = solved(&state, &before, Mat4::IDENTITY);
    sim.update(
        Input {
            movement: vec2(0., 1.),
            sprint: true,
            reload: true,
            ..Default::default()
        },
        &cfg,
        FIXED_DT,
    );
    assert_eq!(sim.player.reload_left, cfg.reload_time);
    let (phase, after) = observe(&mut state, &sim);
    assert_eq!(phase, Some(0.));
    let (new_hands, _, _) = solved(&state, &after, Mat4::IDENTITY);
    for hand in [2, 5] {
        assert_transform_close(old_hands[hand], new_hands[hand], "Some→Some wrist");
    }
    assert_transform_close(
        WeaponFrame::new(Vec3::ZERO, &before).matrix,
        WeaponFrame::new(Vec3::ZERO, &after).matrix,
        "Some→Some weapon",
    );
    assert_eq!(before.left_hand_blend, after.left_hand_blend);
}

#[test]
fn some_to_some_restart_preserves_carried_prop_and_settles_to_the_new_clip() {
    for (empty, phase, duration) in [(false, 0.316742, 2.029), (true, 0.45, 2.359)] {
        let mut state = ViewAnimation::default();
        let now = 50.;
        let old_phase = state.presentation_progress(
            Some(phase * visual_duration(empty) / duration),
            duration,
            empty,
            false,
            now,
        );
        let before = state.sample_input(
            AnimationInput {
                reload_progress: old_phase,
                empty_reload: empty,
                ..Default::default()
            },
            false,
            now,
        );
        let (old_hands, old_prop, _) = solved(&state, &before, Mat4::IDENTITY);
        let next = now + 1e-7;
        let phase = state.presentation_progress(Some(0.), duration, empty, false, next);
        let after = state.sample_input(
            AnimationInput {
                reload_progress: phase,
                empty_reload: empty,
                ..Default::default()
            },
            false,
            next,
        );
        let (new_hands, new_prop, _) = solved(&state, &after, Mat4::IDENTITY);
        assert!(before.magazine_visibility[1] && after.magazine_visibility[1]);
        assert_transform_close(old_hands[2], new_hands[2], "carried wrist restart");
        assert_transform_close(old_prop, new_prop, "carried magazine restart");
        let later = next + 0.141;
        let phase =
            state.presentation_progress(Some(0.141 / duration), duration, empty, false, later);
        let input = AnimationInput {
            reload_progress: phase,
            empty_reload: empty,
            ..Default::default()
        };
        let settled = state.sample_input(input, false, later);
        let mut fresh = ViewAnimation::default();
        let expected = fresh.sample_input(input, false, later);
        assert_eq!(
            settled, expected,
            "restart must settle after the existing 140 ms blend"
        );
        let (actual, _, _) = solved(&state, &settled, Mat4::IDENTITY);
        let (expected, _, _) = solved(&fresh, &expected, Mat4::IDENTITY);
        assert_transform_close(actual[2], expected[2], "settled wrist");
    }
}

#[test]
fn a_render_gap_restart_is_detected_even_when_its_new_phase_is_greater() {
    let mut state = ViewAnimation::default();
    let phase =
        state.presentation_progress(Some(0.316742 * 2.21 / 2.029), 2.029, false, false, 50.);
    let before = state.sample_input(
        AnimationInput {
            reload_progress: phase,
            ..Default::default()
        },
        false,
        50.,
    );
    let (old_hands, old_prop, _) = solved(&state, &before, Mat4::IDENTITY);
    let fresh = state.presentation_progress(Some(0.45 * 2.21 / 2.029), 2.029, false, false, 51.5);
    assert!(fresh.unwrap() > phase.unwrap());
    let after = state.sample_input(
        AnimationInput {
            reload_progress: fresh,
            ..Default::default()
        },
        false,
        51.5,
    );
    let (new_hands, new_prop, _) = solved(&state, &after, Mat4::IDENTITY);
    assert_transform_close(old_hands[2], new_hands[2], "render-gap wrist restart");
    assert_transform_close(old_prop, new_prop, "render-gap carried prop restart");
}

#[test]
fn a_fresh_reload_during_the_visual_tail_preserves_current_live_pose() {
    let mut state = ViewAnimation::default();
    let phase = state.presentation_progress(Some(0.), 2.029, false, false, 0.);
    state.sample_input(
        AnimationInput {
            reload_progress: phase,
            ..Default::default()
        },
        false,
        0.,
    );
    let phase = state.presentation_progress(None, 2.029, false, true, 2.06);
    assert!(phase.is_some_and(|p| p > 0.9 && p < 1.));
    let before = state.sample_input(
        AnimationInput {
            reload_progress: phase,
            recoil: 0.7,
            ..Default::default()
        },
        true,
        2.06,
    );
    let (old_hands, _, _) = solved(&state, &before, Mat4::IDENTITY);
    let fresh = state.presentation_progress(Some(0.), 2.029, false, false, 2.0600001);
    let after = state.sample_input(
        AnimationInput {
            reload_progress: fresh,
            recoil: 0.7,
            ..Default::default()
        },
        false,
        2.0600001,
    );
    let (new_hands, _, _) = solved(&state, &after, Mat4::IDENTITY);
    for hand in [2, 5] {
        assert_transform_close(old_hands[hand], new_hands[hand], "live-tail restart wrist");
    }
    assert_transform_close(
        WeaponFrame::new(Vec3::ZERO, &before).matrix,
        WeaponFrame::new(Vec3::ZERO, &after).matrix,
        "live-tail restart weapon",
    );
    assert_eq!(after.trigger_pull, 0.7);
}

#[test]
fn tactical_live_fire_tail_keeps_actual_wrist_on_the_moving_handguard() {
    for (duration, stride) in [
        (2.029, 1),
        (2.029, 2),
        (2.029, 4),
        (2.029, 8),
        (1.95, 2),
        (2.10, 2),
    ] {
        let mut cfg = Settings::m4_candidate();
        cfg.reload_time = duration;
        let mut sim = Simulation::new();
        sim.player.ammo = 15;
        sim.update(
            Input {
                reload: true,
                ..Default::default()
            },
            &cfg,
            FIXED_DT,
        );
        let mut state = ViewAnimation::default();
        observe(&mut state, &sim);
        let mut witnessed = false;
        for tick in 1..=300 {
            sim.update(
                Input {
                    fire: true,
                    ..Default::default()
                },
                &cfg,
                FIXED_DT,
            );
            if tick % stride != 0 {
                continue;
            }
            let (phase, pose) = observe(&mut state, &sim);
            if sim.stats.shots > 0 && phase.is_some_and(|p| p < 1.) {
                witnessed = true;
                assert_eq!(sim.player.reload_left, 0.);
                assert!(sim.time < visual_duration(false) as f64 + 2. * FIXED_DT as f64);
                // Include external sway/sprint-like motion, beyond live recoil
                // already composed by sample_input.
                let motion = Mat4::from_rotation_translation(
                    Quat::from_euler(EulerRot::YXZ, 0.04, 0.10, -0.08),
                    Vec3::new(0.01, -0.035, 0.02),
                );
                let (hands, _, targets) = solved(&state, &pose, motion);
                assert_transform_close(
                    hands[2],
                    targets.left.transform(),
                    "live tail handguard contact",
                );
            }
        }
        assert!(
            witnessed,
            "duration {duration}, render stride {stride} missed live-fire tail"
        );
    }
}

#[test]
fn arrival_reacquisition_is_continuous_and_keeps_the_released_endpoint_isolated() {
    let motion =
        Mat4::from_rotation_translation(Quat::from_rotation_y(0.25), Vec3::new(0.04, 0.01, 0.02));
    for (empty, arrival) in [(false, 0.8454902), (true, 0.955)] {
        let mut previous = None;
        for phase in [arrival - 0.00001, arrival, arrival + 0.00001] {
            let mut state = ViewAnimation::default();
            let pose = state.sample_input(
                AnimationInput {
                    reload_progress: Some(phase),
                    empty_reload: empty,
                    ..Default::default()
                },
                false,
                10.,
            );
            let (moved, _, _) = solved(&state, &pose, motion);
            if phase <= arrival {
                assert_eq!(state.hand_presentation().influences[0], 0.);
                let (calm, _, _) = solved(&state, &pose, Mat4::IDENTITY);
                assert_transform_close(calm[2], moved[2], "released endpoint isolation");
            }
            if let Some(before) = previous {
                assert_transform_close(before, moved[2], "arrival boundary");
            }
            previous = Some(moved[2]);
        }
    }
}
