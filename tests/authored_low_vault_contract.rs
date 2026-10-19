//! Original synthetic fixtures. These prove binding/clock/render routing, not real r8 art/export.
#![allow(dead_code)]
#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[path = "../src/viewmodel_draw.rs"]
mod viewmodel_draw;
#[path = "../src/weapon_model.rs"]
mod weapon_model;
#[path = "../src/world_draw.rs"]
mod world_draw;
use glam::{vec2, vec3, Mat4};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicUsize, Ordering},
};
use vector_range::{
    animation_manifest::{AnimationManifest, LowVaultReference},
    authored_low_vault::{LowVaultBinding, KEY_SPAN_SECONDS, POLICY},
    settings::Settings,
    sim::{Aabb, Block, Input, Simulation, FIXED_DT},
    skinned_asset::crc32,
    viewmodel_animation::AnimationSet,
};
fn words(out: &mut Vec<u8>, values: &[u32]) {
    out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
}
fn floats(out: &mut Vec<u8>, values: &[f32]) {
    out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
}
fn name(out: &mut Vec<u8>, s: &str) {
    out.extend((s.len() as u16).to_le_bytes());
    out.extend(s.as_bytes());
}
fn container(magic: &[u8; 8], version: u32, payload: Vec<u8>) -> Vec<u8> {
    let mut out = magic.to_vec();
    words(
        &mut out,
        &[version, payload.len() as u32, crc32(&payload), 0],
    );
    out.extend(payload);
    out
}
fn mesh(out: &mut Vec<u8>, skin: bool) {
    words(out, &[1]);
    floats(out, &[0.8, 0.6, 0.4, 1., 0., 1.]);
    words(out, &[0, 0, 0, 3, 3]);
    for position in [[0., 0., -1.], [0.1, 0., -1.], [0., 0.1, -1.]] {
        floats(out, &position);
        floats(out, &[0., 0., 1., 0., 0.]);
        if skin {
            out.extend([0u8; 16]);
            floats(out, &[1., 0., 0., 0., 0., 0., 0., 0.]);
        }
    }
    words(out, &[0, 1, 2]);
}
fn companions() -> (Vec<u8>, Vec<u8>) {
    let mut s = Vec::new();
    words(&mut s, &[1]);
    name(&mut s, "fixture");
    words(&mut s, &[u32::MAX]);
    floats(&mut s, &Mat4::IDENTITY.to_cols_array());
    floats(&mut s, &Mat4::IDENTITY.to_cols_array());
    mesh(&mut s, true);
    let mut m = Vec::new();
    mesh(&mut m, false);
    (container(b"VRSKIN02", 2, s), container(b"VRMESH01", 1, m))
}
fn animation(subdivisions: usize, looping: bool, scale: f32, frames: usize) -> Vec<u8> {
    let (vrs, vrm) = companions();
    let mut a = Vec::new();
    words(&mut a, &[crc32(&vrs), crc32(&vrm), 1]);
    name(&mut a, "fixture");
    words(&mut a, &[u32::MAX, 1]);
    name(&mut a, "hk416_weapon");
    words(&mut a, &[1, 0]);
    floats(&mut a, &Mat4::IDENTITY.to_cols_array());
    words(&mut a, &[1]);
    name(&mut a, "native_low");
    words(&mut a, &[u32::from(looping), frames as u32]);
    for i in 0..frames {
        let t = i as f32 / (60 * subdivisions) as f32 * scale;
        floats(&mut a, &[t]);
        for _ in 0..2 {
            floats(&mut a, &[t, 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
        }
        a.push(1);
    }
    container(b"VRANIM01", 1, a)
}
fn receipt(vra: &[u8], subdivisions: usize) -> Value {
    json!({"schema":"rust-duty-low-vault-runtime/v1","presentation_policy":POLICY,
        "clip_name":"native_low","source_action":"synthetic_test_action","export_take":"synthetic_fbx_stack",
        "return_seconds":0.2,"actor_basis":"canonical","anchor_actor":"hk416_weapon",
        "candidate_sha256":"1".repeat(64),"source_action_fingerprint":"2".repeat(64),
        "source_fbx_sha256":"3".repeat(64),"asset_vra_sha256":rust_duty_launcher::bytes_hash(vra),
        "candidate_frame_range":[1,64],"reference_frame_range_half_open":[7284,7348],
        "native_fps":[60,1],"native_crop":[0,63],"imported_frame_offset":1,"subdivisions":subdivisions})
}
fn bind(vra: &[u8], receipt: &Value) -> Result<LowVaultBinding, String> {
    let bytes = serde_json::to_vec(receipt).unwrap();
    LowVaultBinding::from_bytes(
        vra,
        &bytes,
        &rust_duty_launcher::bytes_hash(&bytes),
        "native_low",
    )
}
fn binding() -> LowVaultBinding {
    let v = animation(8, false, 1., 505);
    bind(&v, &receipt(&v, 8)).unwrap()
}
fn scene(height: f32) -> Simulation {
    let mut s = Simulation::new();
    s.blocks = vec![
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
    s.targets.clear();
    s.ramps.clear();
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

#[test]
fn exact_native_integer_and_subframe_grids_are_accepted() {
    for n in [1, 2, 4, 8] {
        let v = animation(n, false, 1., 63 * n + 1);
        let b = bind(&v, &receipt(&v, n)).unwrap();
        assert_eq!(b.sample(0.).unwrap().source_frame, 1.);
        assert_eq!(b.sample(KEY_SPAN_SECONDS as f32).unwrap().source_frame, 64.);
        assert_eq!(
            b.sample(KEY_SPAN_SECONDS as f32).unwrap().reference_frame,
            7347.
        );
        let sample = b.sample(45. / 60.).unwrap();
        assert!((sample.source_frame - 46.).abs() < 1e-5);
        assert!(b.sample(f32::NAN).is_err());
        assert!(b.sample(-1.).is_err());
        assert!(b.sample(1.1).is_err());
    }
}
#[test]
fn retime_loop_missing_endpoint_and_missing_half_frame_are_rejected_after_valid_crc_and_hash() {
    for (n, looping, scale, count) in [
        (1, true, 1., 64),
        (1, false, 0.6 / 1.05, 64),
        (1, false, 1., 63),
        (8, false, 1., 504),
    ] {
        let v = animation(n, looping, scale, count);
        assert!(AnimationSet::decode(&v).is_ok());
        assert!(bind(&v, &receipt(&v, n)).is_err());
    }
}
#[test]
fn receipt_identity_and_every_clock_pin_fail_closed() {
    let v = animation(1, false, 1., 64);
    let valid = receipt(&v, 1);
    for (key, value) in [
        ("schema", json!("other")),
        ("presentation_policy", json!("vault_over")),
        ("candidate_frame_range", json!([0, 63])),
        ("reference_frame_range_half_open", json!([7284, 7347])),
        ("native_fps", json!([30, 1])),
        ("native_crop", json!([1, 64])),
        ("imported_frame_offset", json!(0)),
        ("subdivisions", json!(16)),
        ("source_action", json!("")),
        ("export_take", json!("")),
        ("return_seconds", json!(0.)),
        ("actor_basis", json!("guess")),
        ("anchor_actor", json!("")),
        ("candidate_sha256", json!("bad")),
        ("source_action_fingerprint", json!("A".repeat(64))),
        ("source_fbx_sha256", Value::Null),
        ("asset_vra_sha256", json!("0".repeat(64))),
        ("clip_name", json!("wrong")),
    ] {
        let mut invalid = valid.clone();
        invalid[key] = value;
        assert!(bind(&v, &invalid).is_err(), "{key}");
    }
    let bytes = serde_json::to_vec(&valid).unwrap();
    assert!(LowVaultBinding::from_bytes(&v, &bytes, &"0".repeat(64), "native_low").is_err());
    assert!(
        LowVaultBinding::from_bytes(&v, &vec![b' '; 32769], &"0".repeat(64), "native_low").is_err()
    );
}
#[test]
fn omitted_low_vault_stays_inactive_and_partial_or_unsafe_opt_in_is_rejected() {
    let inactive = include_str!("../assets/animations.cfg")
        .lines()
        .filter(|line| !line.starts_with("low_vault."))
        .collect::<Vec<_>>()
        .join("\n");
    assert!(AnimationManifest::parse(&inactive, Path::new("assets"))
        .unwrap()
        .low_vault
        .is_none());
    let good=format!("{inactive}\nlow_vault.policy={POLICY}\nlow_vault.asset=low/asset.vra\nlow_vault.clip=native_low\nlow_vault.receipt=low/receipt.json\nlow_vault.receipt_sha256={}\n","0".repeat(64));
    assert!(AnimationManifest::parse(&good, Path::new("assets"))
        .unwrap()
        .low_vault
        .is_some());
    for text in [
        good.replace("low/asset.vra", "../asset.vra"),
        good.replace(POLICY, "vault_over"),
        good.replace("low_vault.receipt=low/receipt.json\n", ""),
        format!("{inactive}\nlow_vault.clip=native_low\n"),
    ] {
        assert!(AnimationManifest::parse(&text, Path::new("assets")).is_err());
    }
}
#[test]
fn inactive_low_mantle_remains_point_six_seconds_and_high_is_unchanged() {
    for (height, opt_in, expected) in [(0.6, false, 0.60), (1.8, false, 0.85), (1.8, true, 0.85)] {
        let mut s = scene(height);
        if opt_in {
            s.set_low_vault_binding(Some(binding())).unwrap();
        }
        tick(&mut s, request());
        assert_eq!(s.player.mantle.unwrap().duration(), expected);
        assert!(s.low_vault_sample().is_none());
    }
}
#[test]
fn accepted_native_clock_runs_126_ticks_without_stretching_and_holds_endpoint_for_final_tick() {
    let mut s = scene(0.6);
    s.set_low_vault_binding(Some(binding())).unwrap();
    for n in 1..=126 {
        tick(&mut s, request());
        let sample = s.low_vault_sample().expect("accepted native clock");
        assert!((sample.seconds - n as f64 / 120.).abs() < 2e-6);
        assert!((sample.source_frame - (1. + n as f64 / 2.)).abs() < 0.0002);
        let bounds = s.player.bounds_at(s.player.position);
        assert!(!s.blocks.iter().any(|b| bounds.overlaps(b.bounds)));
        if n < 126 {
            assert!(s.player.mantle.is_some());
        }
    }
    assert!(s.player.mantle.is_none());
    assert_eq!(s.player.position.y, 0.6);
    assert_eq!(s.low_vault_sample().unwrap().source_frame, 64.);
    tick(&mut s, request());
    assert!(s.low_vault_sample().is_none());
    assert!(s.player.mantle.is_none());
}
#[test]
fn rejected_request_and_interrupted_or_reset_traversal_cannot_replay_a_stale_clock() {
    let mut rejected = scene(2.4);
    rejected.set_low_vault_binding(Some(binding())).unwrap();
    tick(&mut rejected, request());
    assert!(rejected.low_vault_sample().is_none());
    for mode in 0..4 {
        let mut s = scene(0.6);
        s.set_low_vault_binding(Some(binding())).unwrap();
        tick(&mut s, request());
        match mode {
            0 => s.cancel_mantle(),
            1 => s.reset(),
            2 => s.kill(),
            _ => {
                s.blocks.remove(1);
                tick(&mut s, Input::default());
            }
        }
        assert!(s.low_vault_sample().is_none());
        if mode != 1 {
            tick(&mut s, request());
            assert!(s.low_vault_sample().is_none());
        }
        if mode == 1 {
            assert!(s.low_vault_binding().is_some());
        }
    }
}
#[test]
fn binding_replacement_is_atomic_and_disabling_keeps_an_accepted_collision_path() {
    let mut s = scene(0.6);
    s.set_low_vault_binding(Some(binding())).unwrap();
    tick(&mut s, request());
    let prior = s.low_vault_sample();
    assert!(s.set_low_vault_binding(Some(binding())).is_err());
    assert_eq!(s.low_vault_sample(), prior);
    let duration = s.player.mantle.unwrap().duration();
    s.set_low_vault_binding(None).unwrap();
    assert!(s.low_vault_sample().is_none());
    assert_eq!(s.player.mantle.unwrap().duration(), duration);
}

struct Files {
    dir: PathBuf,
    reference: LowVaultReference,
}
impl Files {
    fn new() -> Self {
        static ID: AtomicUsize = AtomicUsize::new(0);
        let dir = std::env::temp_dir().join(format!(
            "rust-duty-low-vault-{}-{}",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&dir).unwrap();
        let v = animation(8, false, 1., 505);
        let (s, m) = companions();
        let r = serde_json::to_vec(&receipt(&v, 8)).unwrap();
        for (p, data) in [
            ("asset.vra", &v),
            ("asset.vrs", &s),
            ("asset.vrm", &m),
            ("receipt.json", &r),
        ] {
            fs::write(dir.join(p), data).unwrap();
        }
        let reference = LowVaultReference {
            asset: dir.join("asset.vra"),
            clip: "native_low".into(),
            receipt: dir.join("receipt.json"),
            receipt_sha256: rust_duty_launcher::bytes_hash(&r),
        };
        Self { dir, reference }
    }
    fn model(&self) -> authored_viewmodel::AuthoredViewmodel {
        let mut m = authored_viewmodel::AuthoredViewmodel::load(
            self.reference.asset.to_str().unwrap(),
            "native_low",
            Some(0.),
        )
        .unwrap();
        m.bind_low_vault(&self.reference).unwrap();
        m
    }
}
impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}
#[test]
fn actual_renderer_samples_native_phase_then_preserves_cancel_pose_while_paused() {
    use vector_range::draw::{facade::*, Command};
    let f = Files::new();
    let mut m = f.model();
    let mut s = scene(0.6);
    s.set_low_vault_binding(m.low_vault_binding().cloned())
        .unwrap();
    for _ in 0..40 {
        tick(&mut s, request());
    }
    m.synchronize_low_vault(&s);
    assert!(m.low_vault_active());
    assert_eq!(m.visual_ads_amount(), 0.);
    let expected = s.low_vault_sample().unwrap().seconds as f32;
    for render_time in [0., 1., 100.] {
        let p = m.source_pose_snapshot(render_time, Mat4::IDENTITY).unwrap();
        assert_eq!(p.pose.sample_time, expected);
        assert!((p.pose.bone_locals[0].translation.x - expected).abs() < 1e-6);
        begin_frame(960, 540, 1.).unwrap();
        m.draw(
            render_time,
            vector_range::scene_lighting::SceneLighting::range(),
            Mat4::IDENTITY,
        );
        assert!(m.error().is_none());
        assert!(take_draw_list()
            .unwrap()
            .commands
            .iter()
            .any(|c| matches!(c, Command::Mesh { .. })));
    }
    let before = m.source_pose_snapshot(s.time, Mat4::IDENTITY).unwrap().pose;
    s.cancel_mantle();
    assert!(s.low_vault_sample().is_none());
    for _ in 0..5 {
        m.synchronize_low_vault(&s);
        assert_eq!(m.low_vault_return_weight(), Some(0.));
        assert_eq!(m.presentation_route(), "low_vault.return");
        assert_eq!(
            m.source_pose_snapshot(s.time, Mat4::IDENTITY)
                .unwrap()
                .pose
                .bone_locals[0],
            before.bone_locals[0]
        );
    }
}
#[test]
fn missing_companion_or_mismatched_renderer_identity_cannot_activate() {
    let f = Files::new();
    let mut m = f.model();
    fs::remove_file(f.dir.join("asset.vrs")).unwrap();
    assert!(m.bind_low_vault(&f.reference).is_err());
    let mut s = scene(0.6);
    s.set_low_vault_binding(Some(binding())).unwrap();
    tick(&mut s, request());
    // The synthetic fixture has identical VRA bytes, so change a pinned source identity.
    let v = animation(8, false, 1., 505);
    let mut r = receipt(&v, 8);
    r["candidate_sha256"] = json!("4".repeat(64));
    s.cancel_mantle();
    s.set_low_vault_binding(Some(bind(&v, &r).unwrap()))
        .unwrap();
    s.reset();
    s.player.position = vec3(0., 0., 1.);
    s.player.yaw = -std::f32::consts::FRAC_PI_2;
    s.blocks = scene(0.6).blocks;
    s.ramps.clear();
    tick(&mut s, request());
    m.synchronize_low_vault(&s);
    assert!(!m.low_vault_active());
    assert!(m.error().is_none());
    assert!(m.low_vault_binding().is_none());
    assert!(m.warning().unwrap().contains("low vault inactive"));
}

#[test]
fn native_phase_and_collision_trace_match_every_render_partition() {
    let mut baseline = None;
    for fps in [15, 30, 60, 144, 240] {
        let mut s = scene(0.6);
        s.set_low_vault_binding(Some(binding())).unwrap();
        let mut clock = vector_range::clock::FixedClock::default();
        let mut trace = Vec::new();
        for _ in 0..fps * 2 {
            for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                let input = if trace.is_empty() {
                    request()
                } else {
                    Input::default()
                };
                tick(&mut s, input);
                trace.push((s.player.position, s.player.grounded, s.low_vault_sample()));
            }
        }
        assert_eq!(trace.len(), 240);
        if let Some(expected) = &baseline {
            assert_eq!(&trace, expected, "{fps} FPS");
        } else {
            baseline = Some(trace);
        }
    }
}

#[test]
fn native_clip_keeps_weapon_lockout_through_its_accepted_final_tick() {
    let mut s = scene(0.6);
    s.set_low_vault_binding(Some(binding())).unwrap();
    let input = Input {
        fire: true,
        reload: true,
        ads: true,
        ..request()
    };
    for _ in 0..126 {
        tick(&mut s, input);
        assert_eq!(s.stats.shots, 0);
        assert_eq!(s.player.reload_left, 0.);
    }
    assert!(s.player.mantle.is_none());
    tick(&mut s, input);
    assert!(s.stats.shots > 0);
    assert!(s.low_vault_sample().is_none());
}

fn presented_tick(s: &mut Simulation, m: &mut authored_viewmodel::AuthoredViewmodel, input: Input) {
    let start = s.time;
    tick(s, input);
    m.committed_step(start, s);
    assert!(m.error().is_none(), "{:?}", m.error());
}
#[test]
fn completion_preserves_frame_64_then_returns_smoothly_to_live_base() {
    let f = Files::new();
    let mut m = f.model();
    let mut s = scene(0.6);
    s.set_low_vault_binding(m.low_vault_binding().cloned())
        .unwrap();
    for _ in 0..126 {
        presented_tick(&mut s, &mut m, request());
    }
    let x = |m: &authored_viewmodel::AuthoredViewmodel, t| {
        m.source_pose_snapshot(t, Mat4::IDENTITY)
            .unwrap()
            .pose
            .bone_locals[0]
            .translation
            .x
    };
    assert!((x(&m, s.time) - 1.05).abs() < 1e-6);
    assert_eq!(m.low_vault_return_weight(), None);
    presented_tick(&mut s, &mut m, Input::default());
    assert_eq!(m.low_vault_return_weight(), Some(0.));
    assert!((x(&m, s.time) - 1.05).abs() < 1e-6);
    for n in 1..=25 {
        presented_tick(&mut s, &mut m, Input::default());
        let t = (n as f32 / 24.).min(1.);
        let weight = t * t * (3. - 2. * t);
        assert!((m.low_vault_underlying_weight() - weight).abs() < 2e-6);
        assert!((x(&m, s.time) - 1.05 * (1. - weight)).abs() < 3e-6);
    }
    assert!(!m.low_vault_active());
    assert_eq!(m.low_vault_return_weight(), None);
}
#[test]
fn configurable_return_tracks_a_moving_target_and_death_reset_clear_it() {
    for duration in [0.1, 0.4] {
        let mut f = Files::new();
        let mut r: Value =
            serde_json::from_slice(&fs::read(&f.reference.receipt).unwrap()).unwrap();
        r["return_seconds"] = json!(duration);
        let bytes = serde_json::to_vec(&r).unwrap();
        fs::write(&f.reference.receipt, &bytes).unwrap();
        f.reference.receipt_sha256 = rust_duty_launcher::bytes_hash(&bytes);
        let mut m = authored_viewmodel::AuthoredViewmodel::load(
            f.reference.asset.to_str().unwrap(),
            "native_low",
            None,
        )
        .unwrap();
        m.bind_low_vault(&f.reference).unwrap();
        let mut s = scene(0.6);
        s.set_low_vault_binding(m.low_vault_binding().cloned())
            .unwrap();
        for _ in 0..20 {
            presented_tick(&mut s, &mut m, request());
        }
        let from = s.low_vault_sample().unwrap().seconds as f32;
        s.cancel_mantle();
        m.synchronize_low_vault(&s);
        let begin = s.time;
        for _ in 0..(duration * 120.) as usize / 2 {
            presented_tick(&mut s, &mut m, Input::default());
            let t = ((s.time - begin) / duration) as f32;
            let weight = t * t * (3. - 2. * t);
            let actual = m.source_pose_snapshot(s.time, Mat4::IDENTITY).unwrap().pose;
            let expected = from + (s.time as f32 - from) * weight;
            assert!((actual.bone_locals[0].translation.x - expected).abs() < 2e-6);
        }
        assert!((m.low_vault_underlying_weight() - 0.5).abs() < 2e-6);
        s.kill();
        m.synchronize_low_vault(&s);
        assert!(!m.low_vault_active());
        assert!(m.low_vault_return_weight().is_none());
        s.reset();
        m.reset(s.time);
        m.synchronize_low_vault(&s);
        assert!(!m.low_vault_active());
    }
}
#[test]
fn actual_viewmodel_route_restores_cant_and_sway_with_the_committed_return_weight() {
    use vector_range::draw::{facade::*, Command};
    use vector_range::weapon_sway::{compose, LayerOffset};
    let f = Files::new();
    let mut m = f.model();
    let mut s = scene(0.6);
    s.set_low_vault_binding(m.low_vault_binding().cloned())
        .unwrap();
    for _ in 0..40 {
        presented_tick(&mut s, &mut m, request());
    }
    s.player.cant = 0.7;
    let cfg = Settings::default();
    let target = RenderTarget::new(960, 540, true).unwrap();
    let layer = LayerOffset {
        translation: vec3(0.1, -0.2, 0.3),
        rotation: vec3(0.2, 0.1, -0.3),
    };
    let meshes = |commands: Vec<Command>| {
        commands
            .into_iter()
            .filter_map(|command| {
                if let Command::Mesh { mesh, model, .. } = command {
                    Some((
                        mesh.vertices.iter().map(|v| v.position).collect::<Vec<_>>(),
                        model,
                    ))
                } else {
                    None
                }
            })
            .collect::<Vec<_>>()
    };
    for phase in 0..3 {
        if phase == 1 {
            s.cancel_mantle();
            m.synchronize_low_vault(&s);
            for _ in 0..12 {
                presented_tick(&mut s, &mut m, Input::default());
            }
        }
        if phase == 2 {
            for _ in 0..13 {
                presented_tick(&mut s, &mut m, Input::default());
            }
        }
        let weight = m.low_vault_underlying_weight();
        assert!((weight - [0., 0.5, 1.][phase]).abs() < 2e-6);
        begin_frame(960, 540, 1.).unwrap();
        viewmodel_draw::weapon(
            &s,
            &target,
            960. / 540.,
            &mut Default::default(),
            None,
            Some(&mut m),
            None,
            &mut Default::default(),
            &cfg,
            Default::default(),
            viewmodel_draw::ViewmodelFraming::from_args(&[]),
            None,
            &mut Default::default(),
            false,
            &[layer],
        );
        let actual = meshes(take_draw_list().unwrap().commands);
        // The current renderer has one rigid root interpolation. Weighting
        // individual Euler offsets (the older PR68 path) is not equivalent.
        let base = cfg.viewmodel_offset(m.visual_ads_amount());
        let live = compose(base, &[layer]);
        let (_, rotation, translation) = live.to_scale_rotation_translation();
        let root = if weight == 0. {
            Mat4::from_translation(base)
        } else if weight == 1. {
            live
        } else {
            Mat4::from_rotation_translation(
                glam::Quat::IDENTITY.slerp(rotation, weight).normalize(),
                base.lerp(translation, weight),
            )
        };
        // Cant is weighted exactly once by the selected authored renderer.
        m.set_cant(s.player.cant_visual() * cfg.action.cant_angle.to_radians());
        begin_frame(960, 540, 1.).unwrap();
        m.draw(
            s.time,
            vector_range::scene_lighting::SceneLighting::at(s.player.eye(), &s.blocks)
                .in_view(s.player.direction()),
            root,
        );
        let expected = meshes(take_draw_list().unwrap().commands);
        assert!(!actual.is_empty());
        assert_eq!(actual, expected);
    }
}
