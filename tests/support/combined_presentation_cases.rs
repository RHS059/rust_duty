// Included inside authored_viewmodel::tests. Original one-bone fixtures only.
// These exercise production pose composition without opening high-mantle admission.

fn combined_install_low(
    model: &mut AuthoredViewmodel,
) -> vector_range::authored_low_vault::LowVaultBinding {
    use vector_range::authored_low_vault::{LowVaultBinding, POLICY};
    fn words(out: &mut Vec<u8>, values: &[u32]) {
        out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
    }
    fn floats(out: &mut Vec<u8>, values: &[f32]) {
        out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
    }
    fn name(out: &mut Vec<u8>, value: &str) {
        out.extend((value.len() as u16).to_le_bytes());
        out.extend(value.as_bytes());
    }
    let mut payload = Vec::new();
    words(&mut payload, &[0, 0, 1]);
    name(&mut payload, "fixture_hand");
    words(&mut payload, &[u32::MAX, 1]);
    name(&mut payload, "fixture_prop");
    words(&mut payload, &[1, 0]);
    floats(
        &mut payload,
        &Mat4::from_translation(vec3(-2., 0., 0.)).to_cols_array(),
    );
    words(&mut payload, &[1]);
    name(&mut payload, "native_low");
    words(&mut payload, &[0, 64]);
    for i in 0..64 {
        let seconds = i as f32 / 60.;
        floats(&mut payload, &[seconds]);
        for _ in 0..2 {
            floats(
                &mut payload,
                &[2. + seconds, 0., 0., 0., 0., 0., 1., 1., 1., 1.],
            );
        }
        payload.push(1);
    }
    let mut asset = b"VRANIM01".to_vec();
    words(&mut asset, &[1, payload.len() as u32, crc32(&payload), 0]);
    asset.extend(payload);
    let receipt=serde_json::to_vec(&serde_json::json!({
        "schema":"rust-duty-low-vault-runtime/v1","presentation_policy":POLICY,"clip_name":"native_low",
        "source_action":"original_synthetic_combined_presentation","export_take":"synthetic_take",
        "return_seconds":0.8,"actor_basis":"canonical","anchor_actor":"fixture_prop",
        "candidate_sha256":"1".repeat(64),"source_action_fingerprint":"2".repeat(64),
        "source_fbx_sha256":"3".repeat(64),"asset_vra_sha256":rust_duty_launcher::bytes_hash(&asset),
        "candidate_frame_range":[1,64],"reference_frame_range_half_open":[7284,7348],
        "native_fps":[60,1],"native_crop":[0,63],"imported_frame_offset":1,"subdivisions":1
    })).unwrap();
    let binding = LowVaultBinding::from_bytes(
        &asset,
        &receipt,
        &rust_duty_launcher::bytes_hash(&receipt),
        "native_low",
    )
    .unwrap();
    let mut renderer = contact_fixture();
    renderer.animation = AnimationSet::decode(&asset).unwrap();
    renderer.clip = "native_low".into();
    renderer.return_map = Some(
        PoseReturnMap::new(
            &model.animation,
            &model.skin,
            &renderer.animation,
            &renderer.skin,
            Mat4::IDENTITY,
        )
        .unwrap(),
    );
    renderer.return_blend =
        Some(AnchoredPoseBlend::new(&renderer.animation, "fixture_prop").unwrap());
    model.low_vault_reload_maps = model
        .reload_renderers
        .iter()
        .map(|source| {
            Some(
                PoseReturnMap::new(
                    &source.animation,
                    &source.skin,
                    &renderer.animation,
                    &renderer.skin,
                    Mat4::IDENTITY,
                )
                .unwrap(),
            )
        })
        .collect();
    model.low_vault = Some((binding.clone(), Box::new(renderer)));
    binding
}

fn combined_low_sim(
    binding: vector_range::authored_low_vault::LowVaultBinding,
) -> vector_range::sim::Simulation {
    use vector_range::sim::{Aabb, Block, Input, Simulation, FIXED_DT};
    let mut sim = Simulation::new();
    sim.blocks = vec![
        Block {
            bounds: Aabb {
                min: vec3(-20., -1., -20.),
                max: vec3(20., 0., 20.),
            },
            kind: 2,
        },
        Block {
            bounds: Aabb {
                min: vec3(-2., 0., -4.),
                max: vec3(2., 0.6, 0.),
            },
            kind: 2,
        },
    ];
    sim.ramps.clear();
    sim.targets.clear();
    sim.player.position = vec3(0., 0., 1.);
    sim.player.yaw = -std::f32::consts::FRAC_PI_2;
    sim.set_low_vault_binding(Some(binding)).unwrap();
    sim.update(
        Input {
            movement: vec2(0., 1.),
            jump: true,
            ..Input::default()
        },
        &vector_range::settings::Settings::default(),
        FIXED_DT,
    );
    assert!(sim.low_vault_sample().is_some());
    sim
}

#[test]
fn combined_low_return_multiplies_live_prone_opacity_ads_and_root_weights() {
    let (mut model, _) = high_mantle_fixture();
    let prone = contact_fixture_frames(true);
    model.prone_index = Some(model.reload_renderers.len());
    model.reload_renderers.push(prone);
    let binding = combined_install_low(&mut model);
    let mut sim = combined_low_sim(binding);
    model.update_low_vault(&sim).unwrap();
    let frozen = model.low_vault_pose.clone().unwrap();
    sim.cancel_mantle();
    let began = sim.time;
    for step in 0..=8 {
        let u = step as f32 / 8.;
        sim.time = began + 0.8 * step as f64 / 8.;
        let index = model.prone_index.unwrap();
        let target = model.reload_renderers[index]
            .animation
            .sample_clamped("contact", 0.2 + u * 0.5)
            .unwrap();
        let target_alpha = 0.2 + 0.5 * u;
        let root_weight = 0.1 + 0.6 * u;
        model.prone_pose = Some(target.clone());
        model.prone_opacity = Some(vec![target_alpha]);
        model.prone_procedural_weight = root_weight;
        model.prone_visible_ads = 0.4 * root_weight;
        model.update_low_vault(&sim).unwrap();
        let weight = model.low_vault_return_weight().unwrap_or(1.);
        let snapshot = model
            .source_pose_snapshot(sim.time, Mat4::IDENTITY)
            .unwrap();
        let (_, renderer) = model.low_vault.as_ref().unwrap();
        let expected = renderer
            .return_blend
            .as_ref()
            .unwrap()
            .blend(&renderer.animation, &frozen, &target, weight)
            .unwrap();
        for (a, b) in snapshot
            .pose
            .bone_locals
            .iter()
            .chain(&snapshot.pose.actor_globals)
            .zip(expected.bone_locals.iter().chain(&expected.actor_globals))
        {
            assert!(a.matrix().abs_diff_eq(b.matrix(), 1e-5));
        }
        assert!(
            (snapshot.actor_opacity.as_ref().unwrap()[0] - ((1. - weight) + weight * target_alpha))
                .abs()
                < 1e-6
        );
        assert!((model.authored_procedural_weight() - weight * root_weight).abs() < 1e-6);
        assert!((model.visual_ads_amount() - weight * 0.4 * root_weight).abs() < 1e-6);
        let before = model
            .source_pose_snapshot(sim.time, Mat4::IDENTITY)
            .unwrap()
            .pose;
        model.update_low_vault(&sim).unwrap();
        assert_eq!(
            model
                .source_pose_snapshot(999., Mat4::IDENTITY)
                .unwrap()
                .pose,
            before
        );
    }
    assert!(!model.low_vault_active());
    assert_eq!(model.presentation_route(), "prone.entry_hold");
}

#[test]
fn combined_low_return_uses_live_reload_actor_opacity_without_resetting_target() {
    let (mut model, _) = high_mantle_fixture();
    let binding = combined_install_low(&mut model);
    let mut sim = combined_low_sim(binding);
    model.update_low_vault(&sim).unwrap();
    let frozen = model.low_vault_pose.clone().unwrap();
    sim.cancel_mantle();
    let began = sim.time;
    for step in 0..=8 {
        let u = step as f32 / 8.;
        sim.time = began + 0.8 * step as f64 / 8.;
        let mut target = model.reload_renderers[0]
            .animation
            .sample_clamped("contact", 0.)
            .unwrap();
        target.bone_locals[0].translation.x += u;
        target.actor_globals[0].translation.x += u;
        let alpha = 1. - 0.75 * u;
        model.reload_presentation = Some(ReloadPresentation {
            index: 0,
            pose: target.clone(),
            opacity: vec![alpha],
            fade: None,
            outgoing: true,
            from_ads: 0.,
            visible_ads: 0.5 * u,
            weight: 1.,
        });
        model.update_low_vault(&sim).unwrap();
        let weight = model.low_vault_return_weight().unwrap_or(1.);
        let output = model
            .source_pose_snapshot(sim.time, Mat4::IDENTITY)
            .unwrap();
        let (_, renderer) = model.low_vault.as_ref().unwrap();
        let expected = renderer
            .return_blend
            .as_ref()
            .unwrap()
            .blend(&renderer.animation, &frozen, &target, weight)
            .unwrap();
        for (a, b) in output
            .pose
            .bone_locals
            .iter()
            .chain(&output.pose.actor_globals)
            .zip(expected.bone_locals.iter().chain(&expected.actor_globals))
        {
            assert!(a.matrix().abs_diff_eq(b.matrix(), 1e-5));
        }
        assert!((output.actor_opacity.unwrap()[0] - (1. - weight + weight * alpha)).abs() < 1e-6);
        assert!((model.visual_ads_amount() - weight * 0.5 * u).abs() < 1e-6);
    }
    assert!(!model.low_vault_active());
    assert!(model.presentation_route().starts_with("reload."));
}

#[test]
fn combined_high_return_tracks_live_prone_with_low_binding_present_and_clears_on_new_low() {
    let (mut model, mut high) = high_mantle_fixture();
    let prone = contact_fixture_frames(true);
    let index = model.reload_renderers.len();
    high.target_maps.push((
        index,
        PoseReturnMap::new(
            &prone.animation,
            &prone.skin,
            &model.reload_renderers[high.index].animation,
            &model.reload_renderers[high.index].skin,
            Mat4::IDENTITY,
        )
        .unwrap(),
    ));
    model.prone_index = Some(index);
    model.reload_renderers.push(prone);
    let binding = combined_install_low(&mut model);
    let mut clock = high_clock(0.4);
    model
        .update_high_mantle_visual(&mut high, clock, 2.)
        .unwrap();
    let frozen = high.pose.clone().unwrap();
    clock.outgoing = Some(vector_range::authored_high_mantle::HighMantleReturn {
        sample: clock.sample,
        began: 2.,
        duration: 0.8,
        completed: false,
    });
    for step in 0..8 {
        let u = step as f32 / 8.;
        let time = 2. + step as f64 * 0.1;
        let pose = model.reload_renderers[index]
            .animation
            .sample_clamped("contact", 0.2 + 0.5 * u)
            .unwrap();
        model.prone_pose = Some(pose.clone());
        model.prone_opacity = Some(vec![0.2 + u * 0.5]);
        model.prone_procedural_weight = u;
        model.prone_visible_ads = 0.3 * u;
        model
            .update_high_mantle_visual(&mut high, clock, time)
            .unwrap();
        let weight = high.return_weight;
        let renderer = &model.reload_renderers[high.index];
        let expected = renderer
            .return_blend
            .as_ref()
            .unwrap()
            .blend(&renderer.animation, &frozen, &pose, weight)
            .unwrap();
        for (a, b) in high
            .pose
            .as_ref()
            .unwrap()
            .bone_locals
            .iter()
            .chain(&high.pose.as_ref().unwrap().actor_globals)
            .zip(expected.bone_locals.iter().chain(&expected.actor_globals))
        {
            assert!(a.matrix().abs_diff_eq(b.matrix(), 1e-5));
        }
        assert!((high.procedural_weight - weight * u).abs() < 1e-6);
        assert!((high.visible_ads - weight * 0.3 * u).abs() < 1e-6);
        assert!(!model.low_vault_active());
    }
    model.high_mantle = Some(high);
    let sim = combined_low_sim(binding);
    model.synchronize_traversal_presentation(&sim);
    assert!(model.high_mantle.as_ref().unwrap().pose.is_none());
    assert!(model.low_vault_active());
    assert_eq!(model.low_vault_return_weight(), None);
    assert_eq!(
        model.presentation_route(),
        "low_vault.low_mantle_native_wip"
    );
    assert!(model.error().is_none());
}

#[test]
fn combined_pause_sync_clears_all_stale_optional_presentations_after_death() {
    let (mut model, mut high) = high_mantle_fixture();
    model
        .update_high_mantle_visual(&mut high, high_clock(0.3), 1.)
        .unwrap();
    model.high_mantle = Some(high);
    let binding = combined_install_low(&mut model);
    let mut sim = combined_low_sim(binding);
    model.update_low_vault(&sim).unwrap();
    sim.cancel_mantle();
    model.update_low_vault(&sim).unwrap();
    model.prone_index = Some(0);
    model.prone_pose = Some(
        model.reload_renderers[0]
            .animation
            .sample_clamped("contact", 0.)
            .unwrap(),
    );
    model.prone_opacity = Some(vec![0.5]);
    model.prone_procedural_weight = 0.2;
    sim.kill();
    let time = sim.time;
    for _ in 0..5 {
        model.synchronize_traversal_presentation(&sim);
        assert_eq!(sim.time, time);
        assert!(model.high_mantle.as_ref().unwrap().pose.is_none());
        assert!(!model.low_vault_active());
        assert!(model.prone_pose.is_none());
        assert_eq!(model.low_vault_return_weight(), None);
        assert_eq!(model.high_mantle_return_weight(), None);
        assert_eq!(model.authored_procedural_weight(), 1.);
        assert!(model.error().is_none());
    }
}

fn combined_prone_track() -> std::sync::Arc<vector_range::authored_prone::ProneCameraTrack> {
    use serde_json::json;
    use vector_range::authored_prone::{
        ProneCameraTrack, CAMERA_ACTION, ENTRY_SECONDS, REMOVAL_POLICY, RIG_ACTION,
    };
    static TRACK: std::sync::OnceLock<std::sync::Arc<ProneCameraTrack>> =
        std::sync::OnceLock::new();
    TRACK.get_or_init(|| {
        let asset=b"original source-free paired-camera test identity";
        let fingerprints=json!({ RIG_ACTION:"2".repeat(64), CAMERA_ACTION:"3".repeat(64) });
        let rows:Vec<_>=(0..545).map(|i| {
            let frame=1.+i as f64/8.; let depth=((frame-11.)/58.).clamp(0.,1.);
            let matrix=json!([[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,-1.26*depth],[0.,0.,0.,1.]]);
            json!({"candidate_frame":frame,"time_seconds":i as f64/480.,"normalized_depth_fraction":depth,"camera_world":matrix,"common_world_delta":matrix})
        }).collect();
        let camera=serde_json::to_vec(&json!({
            "schema":"prone-entry-r6-camera-motion/v1","sample_hz":480,"fps":60,
            "units":"metres and radians; Blender world +Z up","camera_local_axes":"+X right, +Y up, -Z forward",
            "duration_key_span_seconds":ENTRY_SECONDS,"candidate_sha256":"1".repeat(64),"action_fingerprints":fingerprints,
            "initial_camera_world":[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]],
            "height_contract":{"mode":"replace_stance_height_during_clip","allow_impact_overshoot":true,"source_endpoint_descent_m":1.26,"runtime_target_prone_eye_height_m":0.2794},"rows":rows
        })).unwrap();
        let receipt=serde_json::to_vec(&json!({
            "schema":"rust-duty-prone-camera-pair/v1","candidate_sha256":"1".repeat(64),"action_fingerprints":fingerprints,
            "clip_name":RIG_ACTION,"common_motion_removal":REMOVAL_POLICY,"native_fps":[60,1],
            "source_fbx_sha256":"4".repeat(64),"native_crop":[18,86],"candidate_frame_offset":-17,
            "candidate_frame_range":[1,69],"canonical_rest_frame":1,
            "asset_vra_sha256":rust_duty_launcher::bytes_hash(asset),"camera_sidecar_sha256":rust_duty_launcher::bytes_hash(&camera)
        })).unwrap();
        std::sync::Arc::new(ProneCameraTrack::from_pair(asset,&camera,&receipt,RIG_ACTION).unwrap())
    }).clone()
}

fn combined_admitted_fixture(
    high_binding: vector_range::authored_high_mantle::HighMantleBinding,
    height: f32,
) -> (AuthoredViewmodel, vector_range::sim::Simulation) {
    use vector_range::sim::{Aabb, Block, Simulation};
    let (mut model, mut high) = high_mantle_fixture();
    let mut prone = contact_fixture_frames(true);
    let index = model.reload_renderers.len();
    prone.return_map = Some(
        PoseReturnMap::new(
            &model.animation,
            &model.skin,
            &prone.animation,
            &prone.skin,
            Mat4::IDENTITY,
        )
        .unwrap(),
    );
    prone.return_blend = Some(AnchoredPoseBlend::new(&prone.animation, "fixture_prop").unwrap());
    model.prone_reload_maps.push((
        0,
        PoseReturnMap::new(
            &model.reload_renderers[0].animation,
            &model.reload_renderers[0].skin,
            &prone.animation,
            &prone.skin,
            Mat4::IDENTITY,
        )
        .unwrap(),
    ));
    high.target_maps.push((
        index,
        PoseReturnMap::new(
            &prone.animation,
            &prone.skin,
            &model.reload_renderers[high.index].animation,
            &model.reload_renderers[high.index].skin,
            Mat4::IDENTITY,
        )
        .unwrap(),
    ));
    model.prone_index = Some(index);
    model.prone_camera = Some(combined_prone_track());
    model.reload_renderers.push(prone);
    model.high_mantle_binding = Some(high_binding.clone());
    model.high_mantle = Some(high);
    let low_binding = combined_install_low(&mut model);
    let mut sim = Simulation::new();
    sim.blocks = vec![
        Block {
            bounds: Aabb {
                min: vec3(-20., -1., -20.),
                max: vec3(20., 0., 20.),
            },
            kind: 2,
        },
        Block {
            bounds: Aabb {
                min: vec3(-2., 0., -4.),
                max: vec3(2., height, 0.),
            },
            kind: 2,
        },
    ];
    sim.ramps.clear();
    sim.targets.clear();
    sim.player.position = vec3(0., 0., 1.);
    sim.player.yaw = -std::f32::consts::FRAC_PI_2;
    sim.set_low_vault_binding(Some(low_binding)).unwrap();
    sim.set_high_mantle_binding(Some(high_binding));
    sim.set_prone_camera_track(model.prone_camera_track());
    sim.set_prone_return_seconds(1.).unwrap();
    (model, sim)
}

fn combined_committed_tick(
    model: &mut AuthoredViewmodel,
    sim: &mut vector_range::sim::Simulation,
    input: vector_range::sim::Input,
) {
    model.reconcile_simulation_bindings(sim);
    let start = sim.time;
    sim.update(
        input,
        &vector_range::settings::Settings::default(),
        vector_range::sim::FIXED_DT,
    );
    model.committed_step(start, sim);
    model.reconcile_simulation_bindings(sim);
    assert!(model.error().is_none(), "{:?}", model.error());
}

fn combined_assert_native_owner(
    model: &AuthoredViewmodel,
    sim: &vector_range::sim::Simulation,
    low: bool,
) {
    let snapshot = model
        .source_pose_snapshot(sim.time, Mat4::IDENTITY)
        .unwrap();
    let (renderer, seconds) = if low {
        assert_eq!(
            model.presentation_route(),
            "low_vault.low_mantle_native_wip"
        );
        assert!(model.high_mantle.as_ref().unwrap().pose.is_none());
        assert!(sim.high_mantle_presentation().is_none());
        (
            &*model.low_vault.as_ref().unwrap().1,
            sim.low_vault_sample().unwrap().seconds,
        )
    } else {
        assert_eq!(model.presentation_route(), "high_mantle.native");
        assert!(!model.low_vault_active());
        assert!(sim.low_vault_sample().is_none());
        (
            &model.reload_renderers[model.high_mantle.as_ref().unwrap().index],
            sim.high_mantle_presentation().unwrap().sample.seconds,
        )
    };
    assert!(std::ptr::eq(snapshot.animation, &renderer.animation));
    assert_eq!(
        snapshot.pose,
        renderer
            .animation
            .sample_clamped(&renderer.clip, seconds as f32)
            .unwrap()
    );
    assert_eq!(model.low_vault_return_weight(), None);
    assert_eq!(model.high_mantle_return_weight(), None);
    assert_eq!(model.visual_ads_amount(), 0.);
    assert_eq!(model.authored_procedural_weight(), 0.);
}

// The caller supplies a cfg(test)-only high binding. There is no production
// constructor or admission bypass, and no actual source/native-art evidence.
pub(super) fn assert_combined_admitted_sync(
    high_binding: vector_range::authored_high_mantle::HighMantleBinding,
) {
    use vector_range::sim::Input;
    let request = Input {
        movement: vec2(0., 1.),
        jump: true,
        ..Input::default()
    };
    for first_low in [false, true] {
        for complete in [false, true] {
            let (mut model, mut sim) =
                combined_admitted_fixture(high_binding.clone(), if first_low { 0.6 } else { 1.8 });
            combined_committed_tick(&mut model, &mut sim, request);
            combined_assert_native_owner(&model, &sim, first_low);
            if complete {
                let mut ticks = 1;
                while sim.player.mantle.is_some() {
                    combined_committed_tick(&mut model, &mut sim, Input::default());
                    ticks += 1;
                    assert!(ticks < 250);
                }
                assert_eq!(ticks, if first_low { 126 } else { 190 });
                if first_low {
                    combined_committed_tick(&mut model, &mut sim, Input::default());
                }
            } else {
                for _ in 0..24 {
                    combined_committed_tick(&mut model, &mut sim, Input::default());
                }
                sim.cancel_mantle();
                model.synchronize_traversal_presentation(&sim);
            }
            assert_eq!(
                model.presentation_route(),
                if first_low {
                    "low_vault.return"
                } else {
                    "high_mantle.return"
                }
            );
            let old_pose = model
                .source_pose_snapshot(sim.time, Mat4::IDENTITY)
                .unwrap()
                .pose;
            for _ in 0..3 {
                model.synchronize_traversal_presentation(&sim);
                assert_eq!(
                    model
                        .source_pose_snapshot(999., Mat4::IDENTITY)
                        .unwrap()
                        .pose,
                    old_pose
                );
            }
            // A fresh obstacle models the next accepted traversal, without making
            // the stale return itself a gameplay movement or collision owner.
            sim.blocks[1].bounds.max.y = if first_low { 1.8 } else { 0.6 };
            sim.player.position = vec3(0., 0., 1.);
            sim.player.velocity = Vec3::ZERO;
            sim.player.grounded = true;
            sim.player.previous_grounded = true;
            while sim.time - sim.player.last_jump_at < 0.5 {
                combined_committed_tick(&mut model, &mut sim, Input::default());
            }
            assert!(!sim.player.jump_held);
            assert_eq!(
                model.presentation_route(),
                if first_low {
                    "low_vault.return"
                } else {
                    "high_mantle.return"
                }
            );
            combined_committed_tick(&mut model, &mut sim, request);
            combined_assert_native_owner(&model, &sim, !first_low);
            let mut ticks = 0;
            while sim.player.mantle.is_some() {
                combined_committed_tick(&mut model, &mut sim, Input::default());
                ticks += 1;
                assert!(ticks < 250);
                if first_low {
                    assert!(!model.low_vault_active());
                } else {
                    assert!(model.high_mantle.as_ref().unwrap().pose.is_none());
                }
            }
            for _ in 0..110 {
                combined_committed_tick(&mut model, &mut sim, Input::default());
            }
            assert!(!model.low_vault_active());
            assert!(model.high_mantle.as_ref().unwrap().pose.is_none());
            assert_eq!(model.low_vault_return_weight(), None);
            assert_eq!(model.high_mantle_return_weight(), None);
            assert_eq!(model.presentation_route(), "ready");
        }
    }
    // A real paired-prone outgoing clock must also yield to accepted high.
    let (mut model, mut sim) = combined_admitted_fixture(high_binding.clone(), 1.8);
    for _ in 0..100 {
        combined_committed_tick(
            &mut model,
            &mut sim,
            Input {
                prone: true,
                ..Input::default()
            },
        );
    }
    assert!(sim.prone_sample().is_some());
    for _ in 0..78 {
        combined_committed_tick(&mut model, &mut sim, Input::default());
    }
    assert!(sim.prone_return().is_some());
    assert_eq!(model.presentation_route(), "prone.return");
    combined_committed_tick(&mut model, &mut sim, request);
    combined_assert_native_owner(&model, &sim, false);
    assert!(sim.prone_return().is_some());

    // Optional rejection is reconciled before fresh input can pick its native
    // duration. Surviving optional bindings remain available independently.
    for failed in ["low", "high", "all"] {
        let (mut model, mut sim) = combined_admitted_fixture(
            high_binding.clone(),
            if failed == "high" { 1.8 } else { 0.6 },
        );
        match failed {
            "low" => model.low_vault = None,
            "high" => {
                model.high_mantle_binding = None;
                model.high_mantle = None;
            }
            _ => {
                for _ in 0..80 {
                    combined_committed_tick(
                        &mut model,
                        &mut sim,
                        Input {
                            prone: true,
                            ..Input::default()
                        },
                    );
                }
                assert!(sim.prone_sample().is_some());
                model.error = Some("synthetic global renderer failure".into());
            }
        }
        model.reconcile_simulation_bindings(&mut sim);
        if failed == "all" {
            assert!(sim.low_vault_binding().is_none());
            assert!(sim.high_mantle_binding().is_none());
            assert!(sim.prone_sample().is_none());
            assert!(sim.prone_return().is_none());
            continue;
        }
        sim.update(
            request,
            &vector_range::settings::Settings::default(),
            vector_range::sim::FIXED_DT,
        );
        assert_eq!(
            sim.player.mantle.unwrap().duration(),
            if failed == "low" { 0.6 } else { 0.85 }
        );
        assert!(model.prone_camera_track().is_some());
        if failed == "low" {
            assert!(sim.low_vault_binding().is_none());
            assert!(sim.high_mantle_binding().is_some());
        } else {
            assert!(sim.high_mantle_binding().is_none());
            assert!(sim.low_vault_binding().is_some());
        }
    }
}
