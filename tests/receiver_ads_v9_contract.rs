//! Native authored input witnesses. Numerical reproduction is not visual approval.
use macroquad::math::Mat4;
use serde_json::Value;
use vector_range::{
    authored_walk::{receiver_v9_offset, ForwardAdsSamples, WalkLayerInput, WalkPoseLayer},
    viewmodel_animation::{AnimationSet, Transform, ViewmodelPose},
};

fn oracle() -> Value {
    serde_json::from_str(include_str!(
        "../assets/authoring/locomotion_ads/v9/v9_native_runtime_oracle.json"
    ))
    .unwrap()
}
fn matrix(value: &Value) -> Mat4 {
    let mut cols = [0.; 16];
    for row in 0..4 {
        for col in 0..4 {
            cols[col * 4 + row] = value[row][col].as_f64().unwrap() as f32;
        }
    }
    Mat4::from_cols_array(&cols)
}
fn error(a: Mat4, b: Mat4) -> f32 {
    a.to_cols_array()
        .into_iter()
        .zip(b.to_cols_array())
        .map(|(a, b)| (a - b).abs())
        .fold(0., f32::max)
}
fn transform(matrix: Mat4) -> Transform {
    let (scale, rotation, translation) = matrix.to_scale_rotation_translation();
    Transform {
        scale,
        rotation: rotation.normalize(),
        translation,
    }
}
fn pose(set: &AnimationSet, bones: &Value, actors: &Value, oracle: &Value) -> ViewmodelPose {
    let globals: Vec<_> = set
        .bones()
        .iter()
        .map(|bone| {
            let i = oracle["bone_names"]
                .as_array()
                .unwrap()
                .iter()
                .position(|name| name.as_str() == Some(&bone.name))
                .unwrap();
            matrix(&bones[i])
        })
        .collect();
    ViewmodelPose {
        sample_time: 0.,
        bone_locals: set
            .bones()
            .iter()
            .enumerate()
            .map(|(i, b)| {
                transform(
                    b.parent
                        .map_or(globals[i], |parent| globals[parent].inverse() * globals[i]),
                )
            })
            .collect(),
        actor_globals: set
            .actors()
            .iter()
            .map(|actor| {
                let i = oracle["actor_names"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .position(|name| name.as_str() == Some(&actor.name))
                    .unwrap();
                transform(matrix(&actors[i]))
            })
            .collect(),
        actor_visible: vec![true; set.actors().len()],
    }
}
#[test]
fn v9_primary_and_half_period_map_matches_all_native_optical_witnesses() {
    let oracle = oracle();
    let cases = oracle["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 26);
    let mut maximum = 0_f32;
    for case in cases {
        let (rotation, translation) = receiver_v9_offset(
            matrix(&case["primary_delta_asset"]),
            matrix(&case["secondary_delta_asset"]),
        )
        .unwrap();
        let actual = Mat4::from_rotation_translation(rotation, translation);
        maximum = maximum.max(error(actual, matrix(&case["expected_offset_asset"])));
    }
    println!("26 native v9 optical witnesses: max component error {maximum}");
    assert!(maximum < 1e-5);
}
#[test]
#[ignore = "requires separately regenerated complete native pose oracle; see docs/ADS_V9_RUNTIME_WIP.md"]
fn v9_complete_native_pose_reproduction_reports_local_trs_residue() {
    let path = std::env::var_os("RUST_DUTY_V9_POSE_ORACLE")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            "assets/authoring/locomotion_ads/v9/v9_complete_pose_runtime_oracle.json".into()
        });
    let oracle: Value = serde_json::from_slice(
        &std::fs::read(path).expect("regenerate the complete native pose oracle first"),
    )
    .unwrap();
    let set = AnimationSet::load("assets/locomotion/asset.vra").unwrap();
    let names: Vec<_> = set.bones().iter().map(|bone| bone.name.as_str()).collect();
    let expected_names: Vec<_> = oracle["bone_names"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert_eq!(
        names.iter().collect::<std::collections::BTreeSet<_>>(),
        expected_names
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
    );
    let mut layer = WalkPoseLayer::new(&set, &set, "normal_ready", "hk416_weapon").unwrap();
    layer.use_receiver_v4_wip(true);
    let held = pose(
        &set,
        &oracle["held_bone_globals_asset"],
        &oracle["held_actor_globals_asset"],
        &oracle,
    );
    let anchor = set
        .actors()
        .iter()
        .position(|actor| actor.name == "hk416_weapon")
        .unwrap();
    let ready_weapon = matrix(&oracle["ready_weapon_asset"]);
    assert!(set
        .sample_clamped("normal_ready", 0.)
        .unwrap()
        .actor_globals[anchor]
        .matrix()
        .abs_diff_eq(ready_weapon, 1e-5));
    let mut max_bone = 0_f32;
    let mut max_actor = 0_f32;
    for case in oracle["cases"].as_array().unwrap() {
        let primary = pose(
            &set,
            &case["primary_bone_globals_asset"],
            &case["primary_actor_globals_asset"],
            &oracle,
        );
        let mut half = primary.clone();
        half.actor_globals[anchor] =
            transform(matrix(&case["secondary_delta_asset"]) * ready_weapon);
        let result = layer
            .pose_with_input(
                &set,
                &held,
                WalkLayerInput {
                    walk: &primary,
                    weight: 1.,
                    aim: 1.,
                    lateral: 0.,
                    forward_ads: Some(ForwardAdsSamples {
                        primary: &primary,
                        half_period: &half,
                        weight: 1.,
                    }),
                },
            )
            .unwrap();
        for (bone, actual) in set
            .bones()
            .iter()
            .zip(set.bone_globals(&result, Mat4::IDENTITY).unwrap())
        {
            let i = expected_names
                .iter()
                .position(|name| *name == bone.name)
                .unwrap();
            max_bone = max_bone.max(error(
                actual,
                matrix(&case["expected_bone_globals_asset"][i]),
            ));
        }
        for (actor, actual) in set.actors().iter().zip(&result.actor_globals) {
            let i = oracle["actor_names"]
                .as_array()
                .unwrap()
                .iter()
                .position(|name| name.as_str() == Some(&actor.name))
                .unwrap();
            max_actor = max_actor.max(error(
                actual.matrix(),
                matrix(&case["expected_actor_globals_asset"][i]),
            ));
        }
    }
    println!("26 x 72 native v9 bone globals: local TRS reconstruction max {max_bone}; 26 x 2 actors: {max_actor}; strict native source 1e-5 bone criterion satisfied: {}", max_bone < 1e-5);
    // Source globals include small parent-product shear. This is an explicit
    // runtime reconstruction allowance, separate from the unchanged source gate.
    assert!(max_bone < 1e-4);
    assert!(max_actor < 1e-5);
}

#[test]
fn actual_v9_direction_aim_run_interruptions_remain_finite_and_deterministic() {
    use vector_range::{
        animation_manifest::AnimationManifest,
        layered_locomotion::{gameplay_layered_replay_input, LayerSources, LayeredLocomotion},
        settings::{Settings, WalkTranslation},
        sim::{Simulation, FIXED_DT},
    };
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else {
        return;
    };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let set = AnimationSet::load(&manifest.locomotion_asset).unwrap();
    let walk = AnimationSet::load(&manifest.regular_walk.as_ref().unwrap().asset).unwrap();
    let ads = AnimationSet::load(&manifest.ads.as_ref().unwrap().asset).unwrap();
    let sources = LayerSources {
        jump: None,
        locomotion: &set,
        walk: Some(&walk),
        ads: Some(&ads),
    };
    let make = || {
        LayeredLocomotion::new(
            sources,
            manifest.locomotion.clone(),
            Some(&manifest.regular_walk.as_ref().unwrap().clip),
            manifest.ads.clone(),
            &manifest.layer_anchor_actor,
        )
        .unwrap()
        .with_directional_walk(&walk, manifest.directional_walk.clone().unwrap())
        .unwrap()
        .with_ads_wip_policy(true, Some(0.30))
        .unwrap()
        .with_forward_ads_v9_policy(true)
        .unwrap()
    };
    let mut original = make();
    let mut adjusted = make();
    adjusted.set_walk_translation(WalkTranslation([-1., 0.5, 1.]));
    let mut sim = Simulation::new();
    let settings = Settings::m4_candidate();
    let mut max_component = 0_f32;
    let mut max_relative_change = 0_f32;
    let anchor = set
        .actors()
        .iter()
        .position(|actor| actor.name == manifest.layer_anchor_actor)
        .unwrap();
    for tick in 0..1320 {
        let start = sim.time;
        let mut input = gameplay_layered_replay_input(start);
        if (2.75..3.25).contains(&start) {
            input.movement = macroquad::math::Vec2::new(1., 1.).normalize();
        }
        sim.update(input, &settings, FIXED_DT);
        let reload = (7.8..8.0).contains(&start);
        original
            .committed_step(sources, start, &sim, reload)
            .unwrap();
        adjusted
            .committed_step(sources, start, &sim, reload)
            .unwrap();
        assert_eq!(original.walk().seconds(), adjusted.walk().seconds());
        let original_inverse = original.pose().actor_globals[anchor].matrix().inverse();
        let adjusted_inverse = adjusted.pose().actor_globals[anchor].matrix().inverse();
        for (original_global, adjusted_global) in set
            .bone_globals(original.pose(), Mat4::IDENTITY)
            .unwrap()
            .into_iter()
            .zip(set.bone_globals(adjusted.pose(), Mat4::IDENTITY).unwrap())
        {
            max_relative_change = max_relative_change.max(error(
                original_inverse * original_global,
                adjusted_inverse * adjusted_global,
            ));
        }
        for pose in [original.pose(), adjusted.pose()] {
            for global in set.bone_globals(pose, Mat4::IDENTITY).unwrap() {
                assert!(global.is_finite());
                max_component = max_component.max(
                    global
                        .to_cols_array()
                        .into_iter()
                        .map(f32::abs)
                        .fold(0., f32::max),
                );
            }
        }
        if tick % 4 == 0 {
            let before = original.pose_crc32();
            original
                .committed_step(sources, sim.time, &sim, reload)
                .unwrap();
            assert_eq!(before, original.pose_crc32());
        }
    }
    assert!(max_component < 100.);
    assert!(max_relative_change < 5e-5);
    println!("1,320 actual-pack v9 ticks including diagonal, run, reload and ADS interruptions; walk XYZ leaves clocks unchanged; max relative bone/weapon change from XYZ {max_relative_change}");
}
