//! Combined optional-route contracts using original, source-free synthetic packs.
//! High mantle remains production-gated until independently reviewed pins exist.
//! CPU pose/clock evidence only; no native rendering or source-art claim.
#![allow(dead_code)]
#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[path = "../src/weapon_model.rs"]
mod weapon_model;
use authored_viewmodel::AuthoredViewmodel;
use glam::{vec2, vec3, Mat4, Quat};
use serde_json::json;
use std::{
    fs,
    path::PathBuf,
    sync::{
        atomic::{AtomicUsize, Ordering},
        OnceLock,
    },
};
use vector_range::{
    authored_low_vault::POLICY,
    authored_pose_return::canonical_to_reload_actor_basis,
    authored_prone::{
        ENTRY_SECONDS, R15_CAMERA_ACTION, R15_CAMERA_FINGERPRINT, R15_EQUIVALENCE_CONTRACT,
        R15_RIG_ACTION, R15_RIG_FINGERPRINT, REMOVAL_POLICY,
    },
    clock::FixedClock,
    layered_locomotion::AnchoredPoseBlend,
    settings::Settings,
    sim::{Aabb, Action, Block, Input, Simulation, FIXED_DT, RADIUS},
    skinned_asset::crc32,
    viewmodel_animation::{AnimationSet, Transform, ViewmodelPose},
};

fn words(out: &mut Vec<u8>, values: &[u32]) {
    out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
}
fn floats(out: &mut Vec<u8>, values: &[f32]) {
    out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
}
fn name(out: &mut Vec<u8>, text: &str) {
    out.extend((text.len() as u16).to_le_bytes());
    out.extend(text.as_bytes());
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
    let mut skin = Vec::new();
    words(&mut skin, &[1]);
    name(&mut skin, "fixture");
    words(&mut skin, &[u32::MAX]);
    floats(&mut skin, &Mat4::IDENTITY.to_cols_array());
    floats(&mut skin, &Mat4::IDENTITY.to_cols_array());
    mesh(&mut skin, true);
    let mut rigid = Vec::new();
    mesh(&mut rigid, false);
    (
        container(b"VRSKIN02", 2, skin),
        container(b"VRMESH01", 1, rigid),
    )
}
fn transform(matrix: Mat4) -> Transform {
    let (scale, rotation, translation) = matrix.to_scale_rotation_translation();
    Transform {
        scale,
        rotation: rotation.normalize(),
        translation,
    }
}
fn emit_transform(out: &mut Vec<u8>, value: Transform) {
    floats(out, &value.translation.to_array());
    floats(out, &value.rotation.to_array());
    floats(out, &value.scale.to_array());
}
fn canonical_pose(x: f32) -> Mat4 {
    Mat4::from_rotation_translation(
        Quat::from_rotation_y(0.31) * Quat::from_rotation_z(-0.22),
        vec3(x, 0.17, -0.83),
    )
}
#[derive(Clone, Copy)]
struct Clip<'a> {
    name: &'a str,
    looping: bool,
    frames: usize,
    seconds: f32,
    from_x: f32,
    to_x: f32,
}
fn animation(clips: &[Clip<'_>], actor_names: &[&str], basis: Mat4) -> Vec<u8> {
    let (skin, rigid) = companions();
    let mut out = Vec::new();
    words(&mut out, &[crc32(&skin), crc32(&rigid), 1]);
    name(&mut out, "fixture");
    words(&mut out, &[u32::MAX, actor_names.len() as u32]);
    for (i, actor) in actor_names.iter().enumerate() {
        name(&mut out, actor);
        if i == 0 {
            words(&mut out, &[1, 0]);
        } else {
            words(&mut out, &[0]);
        }
        floats(&mut out, &Mat4::IDENTITY.to_cols_array());
    }
    words(&mut out, &[clips.len() as u32]);
    for clip in clips {
        name(&mut out, clip.name);
        words(&mut out, &[u32::from(clip.looping), clip.frames as u32]);
        for frame in 0..clip.frames {
            let u = frame as f32 / (clip.frames - 1) as f32;
            floats(&mut out, &[u * clip.seconds]);
            let canonical = canonical_pose(clip.from_x + u * (clip.to_x - clip.from_x));
            emit_transform(
                &mut out,
                transform(canonical * Mat4::from_translation(vec3(0.03, 0.02, 0.))),
            );
            for _ in actor_names {
                emit_transform(&mut out, transform(canonical * basis));
            }
            out.extend(std::iter::repeat_n(1, actor_names.len()));
        }
    }
    container(b"VRANIM01", 1, out)
}

const LOW: u8 = 1;
const PRONE: u8 = 2;
const HIGH: u8 = 4;
const LOW_RETURN: f64 = 0.8;
const BASE_MANIFEST: &str = "schema=rust-duty-animation-slots/v1\nlocomotion.asset=base.vra\nlayers.anchor_actor=hk416_weapon\nready.clip=ready\nsprint.entry.clip=entry\nsprint.loop.clip=loop\nsprint.bridges=bridge0,bridge1\nsprint.exit.clip=exit\nsprint.settle.clip=settle\nsprint.response_seconds=0.05\nsprint.residual_seconds=0.03\nregular_walk.asset=walk.vra\nregular_walk.clip=walk\nregular_walk.anchor_actor=hk416_weapon\nreload.tactical.asset=reload.vra\nreload.tactical.clip=reload\nreload.empty=unavailable\nreload.route=anchored_crossfade\nreload.clock=native_complete\nads.asset=ads.vra\nads.entry.clip=ads_entry\nads.hold.clip=ads_hold\nads.exit.clip=ads_exit\nads.clock=native_reversible\nfire=unavailable\nmantle=unavailable\n";

fn clip(name: &str, looping: bool, seconds: f32, from_x: f32, to_x: f32) -> Clip<'_> {
    Clip {
        name,
        looping,
        frames: 2,
        seconds,
        from_x,
        to_x,
    }
}

fn regenerated_prone_pair(asset: &[u8]) -> (Vec<u8>, Vec<u8>) {
    // The camera evidence is synthetic, while the pinned source-equivalence schema
    // is the production one. It certifies validator behavior, never real poses.
    static CAMERA: OnceLock<Vec<u8>> = OnceLock::new();
    let generated = "a".repeat(64);
    let mut proof: serde_json::Value = serde_json::from_str(R15_EQUIVALENCE_CONTRACT).unwrap();
    proof["generated_source_sha256"] = json!(generated);
    proof["source_equivalence_sha256"] = json!("b".repeat(64));
    proof["regenerated_witness_sha256"] = json!("c".repeat(64));
    proof["replay_receipt_sha256"] = json!("d".repeat(64));
    let fingerprints =
        json!({ R15_RIG_ACTION:R15_RIG_FINGERPRINT, R15_CAMERA_ACTION:R15_CAMERA_FINGERPRINT });
    let camera = CAMERA.get_or_init(|| {
        let rows: Vec<_> = (0..4353).map(|i| {
            let frame = 1. + i as f64 / 64.;
            let depth = ((frame - 11.) / 58.).clamp(0., 1.);
            let matrix = json!([[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,-1.26*depth],[0.,0.,0.,1.]]);
            json!({"candidate_frame":frame,"time_seconds":i as f64 / 3840.,
                "normalized_depth_fraction":depth,"camera_world":matrix,"common_world_delta":matrix})
        }).collect();
        serde_json::to_vec(&json!({
            "schema":"prone-entry-r15-camera-motion/v2","sample_hz":3840,"fps":60,
            "units":"metres and radians; Blender world +Z up","camera_local_axes":"+X right, +Y up, -Z forward",
            "duration_key_span_seconds":ENTRY_SECONDS,"candidate_sha256":generated,
            "action_fingerprints":fingerprints,"source_equivalence":proof,
            "initial_camera_world":[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]],
            "height_contract":{"mode":"replace_stance_height_during_clip","allow_impact_overshoot":true,
                "source_endpoint_descent_m":1.26,"runtime_target_prone_eye_height_m":0.2794},"rows":rows
        })).unwrap()
    }).clone();
    let receipt = serde_json::to_vec(&json!({
        "schema":"rust-duty-prone-camera-pair/v3","clip_name":R15_RIG_ACTION,
        "candidate_sha256":generated,"action_fingerprints":fingerprints,"source_equivalence":proof,
        "source_rig_action":R15_RIG_ACTION,"source_camera_action":R15_CAMERA_ACTION,
        "camera_sample_hz":3840,"common_motion_removal":REMOVAL_POLICY,
        "native_fps":[60,1],"native_crop":[0,68],"candidate_frame_offset":1,
        "imported_frame_offset":1.0,"candidate_frame_range":[1,69],"canonical_rest_frame":1,
        "source_fbx_sha256":"e".repeat(64),"asset_vra_sha256":rust_duty_launcher::bytes_hash(asset),
        "camera_sidecar_sha256":rust_duty_launcher::bytes_hash(&camera)
    }))
    .unwrap();
    (camera, receipt)
}

struct Files {
    dir: PathBuf,
    low_basis: Mat4,
    low_hash: String,
}
impl Files {
    fn new(reload_basis: bool) -> Self {
        static ID: AtomicUsize = AtomicUsize::new(0);
        let dir = std::env::temp_dir().join(format!(
            "rust-duty-combined-{}-{}",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&dir).unwrap();
        let actors = ["hk416_weapon"];
        let base_clips: Vec<_> = [
            "ready", "entry", "loop", "bridge0", "bridge1", "exit", "settle",
        ]
        .into_iter()
        .map(|name| clip(name, name == "loop", 0.5, 0.2, 0.2))
        .collect();
        let base = animation(&base_clips, &actors, Mat4::IDENTITY);
        let walk = animation(
            &[clip("walk", true, 0.5, 0.2, 0.9)],
            &actors,
            Mat4::IDENTITY,
        );
        let ads = animation(
            &[
                clip("ads_entry", false, 0.3, 0.2, 0.7),
                clip("ads_hold", true, 0.3, 0.7, 0.7),
                clip("ads_exit", false, 0.3, 0.7, 0.2),
            ],
            &actors,
            Mat4::IDENTITY,
        );
        let reload = animation(
            &[clip("reload", false, 1.5, 0.4, 1.9)],
            &actors,
            canonical_to_reload_actor_basis(),
        );
        let prone = animation(
            &[clip(R15_RIG_ACTION, false, ENTRY_SECONDS as f32, 0.2, -1.8)],
            &actors,
            canonical_to_reload_actor_basis(),
        );
        let low_basis = if reload_basis {
            canonical_to_reload_actor_basis()
        } else {
            Mat4::IDENTITY
        };
        let low = animation(
            &[Clip {
                frames: 64,
                ..clip("native_low", false, 1.05, -0.4, -1.45)
            }],
            &actors,
            low_basis,
        );
        let (camera, prone_receipt) = regenerated_prone_pair(&prone);
        let receipt = serde_json::to_vec(&json!({
            "schema":"rust-duty-low-vault-runtime/v1","presentation_policy":POLICY,"clip_name":"native_low",
            "source_action":"original_synthetic_combined_fixture","export_take":"synthetic_fbx_stack",
            "return_seconds":LOW_RETURN,"actor_basis":if reload_basis {"reload_mesh_local"} else {"canonical"},
            "anchor_actor":"hk416_weapon","candidate_sha256":"1".repeat(64),"source_action_fingerprint":"2".repeat(64),
            "source_fbx_sha256":"3".repeat(64),"asset_vra_sha256":rust_duty_launcher::bytes_hash(&low),
            "candidate_frame_range":[1,64],"reference_frame_range_half_open":[7284,7348],"native_fps":[60,1],
            "native_crop":[0,63],"imported_frame_offset":1,"subdivisions":1
        })).unwrap();
        let (skin, rigid) = companions();
        for (stem, bytes) in [
            ("base", base),
            ("walk", walk),
            ("ads", ads),
            ("reload", reload),
            ("prone", prone),
            ("low", low),
        ] {
            fs::write(dir.join(format!("{stem}.vra")), bytes).unwrap();
            fs::write(dir.join(format!("{stem}.vrs")), &skin).unwrap();
            fs::write(dir.join(format!("{stem}.vrm")), &rigid).unwrap();
        }
        fs::write(dir.join("prone.camera.json"), camera).unwrap();
        fs::write(dir.join("prone.receipt.json"), prone_receipt).unwrap();
        fs::write(dir.join("low.receipt.json"), &receipt).unwrap();
        Self {
            dir,
            low_basis,
            low_hash: rust_duty_launcher::bytes_hash(&receipt),
        }
    }
    fn manifest(&self, mask: u8) -> PathBuf {
        let mut text = BASE_MANIFEST.to_owned();
        if mask & LOW != 0 {
            text += &format!("low_vault.policy={POLICY}\nlow_vault.asset=low.vra\nlow_vault.clip=native_low\nlow_vault.receipt=low.receipt.json\nlow_vault.receipt_sha256={}\n",self.low_hash);
        }
        if mask & PRONE != 0 {
            text += &format!("prone_entry.policy=paired_r15_wip\nprone_entry.asset=prone.vra\nprone_entry.clip={R15_RIG_ACTION}\nprone_entry.camera=prone.camera.json\nprone_entry.receipt=prone.receipt.json\n");
        }
        // Deliberately unresolved: production pins are pending, so high must not
        // read or admit even apparently valid file references in this contract.
        if mask & HIGH != 0 {
            text += &format!("high_mantle.policy={}\nhigh_mantle.asset=high.vra\nhigh_mantle.clip={}\nhigh_mantle.receipt=high.receipt.json\nhigh_mantle.receipt_sha256={}\n",vector_range::authored_high_mantle::POLICY,vector_range::authored_high_mantle::ACTION,"1".repeat(64));
        }
        let path = self.dir.join(format!("combined-{mask}.cfg"));
        fs::write(&path, text).unwrap();
        path
    }
    fn model(&self, mask: u8) -> AuthoredViewmodel {
        AuthoredViewmodel::load_manifest(&self.manifest(mask)).unwrap()
    }
}
impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}

fn scene(height: f32) -> Simulation {
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
    sim.targets.clear();
    sim.ramps.clear();
    sim.player.position = vec3(0., 0., 1.);
    sim.player.yaw = -std::f32::consts::FRAC_PI_2;
    sim
}
fn request() -> Input {
    Input {
        movement: vec2(0., 1.),
        jump: true,
        ..Input::default()
    }
}
fn bind(sim: &mut Simulation, model: &AuthoredViewmodel) {
    sim.set_low_vault_binding(model.low_vault_binding().cloned())
        .unwrap();
    sim.set_prone_camera_track(model.prone_camera_track());
    sim.set_high_mantle_binding(model.high_mantle_binding());
    sim.set_prone_return_seconds(1.).unwrap();
}
fn tick(sim: &mut Simulation, model: &mut AuthoredViewmodel, input: Input) {
    let start = sim.time;
    sim.update(input, &Settings::default(), FIXED_DT);
    model.committed_step(start, sim);
    assert!(model.error().is_none(), "{:?}", model.error());
}
fn assert_pose(actual: &ViewmodelPose, expected: &ViewmodelPose) {
    assert_eq!(actual.bone_locals.len(), expected.bone_locals.len());
    assert_eq!(actual.actor_globals.len(), expected.actor_globals.len());
    assert_eq!(actual.actor_visible, expected.actor_visible);
    for (a, b) in actual
        .bone_locals
        .iter()
        .chain(&actual.actor_globals)
        .zip(expected.bone_locals.iter().chain(&expected.actor_globals))
    {
        assert!(
            a.matrix().abs_diff_eq(b.matrix(), 4e-5),
            "actual {a:?}, expected {b:?}"
        );
    }
}
fn snapshot(model: &AuthoredViewmodel, time: f64) -> ViewmodelPose {
    model
        .source_pose_snapshot(time, Mat4::IDENTITY)
        .unwrap()
        .pose
}

fn assert_prone_route(model: &mut AuthoredViewmodel, admitted: bool) {
    let mut sim = scene(0.6);
    bind(&mut sim, model);
    model.reset(sim.time);
    for _ in 0..80 {
        tick(
            &mut sim,
            model,
            Input {
                prone: true,
                ..Input::default()
            },
        );
    }
    assert!(sim.player.prone);
    assert_eq!(sim.prone_sample().is_some(), admitted);
    assert_eq!(model.presentation_route() == "prone.entry_hold", admitted);
    assert!(!model.low_vault_active());
    assert!(sim.high_mantle_presentation().is_none());
}

struct Harness {
    files: Files,
    model: AuthoredViewmodel,
    oracle: AuthoredViewmodel,
    sim: Simulation,
}
impl Harness {
    fn new(reload_basis: bool) -> Self {
        let files = Files::new(reload_basis);
        let model = files.model(LOW | PRONE | HIGH);
        let oracle = files.model(PRONE);
        let mut sim = scene(0.6);
        bind(&mut sim, &model);
        Self {
            files,
            model,
            oracle,
            sim,
        }
    }
    fn tick(&mut self, input: Input) {
        let start = self.sim.time;
        tick(&mut self.sim, &mut self.model, input);
        self.oracle.committed_step(start, &self.sim);
        assert!(self.oracle.error().is_none(), "{:?}", self.oracle.error());
    }
    fn sync(&mut self) {
        self.model.synchronize_traversal_presentation(&self.sim);
        self.oracle.synchronize_traversal_presentation(&self.sim);
        assert!(self.model.error().is_none(), "{:?}", self.model.error());
    }
    fn start_low(&mut self) {
        self.tick(request());
        assert_eq!(
            self.model.presentation_route(),
            "low_vault.low_mantle_native_wip"
        );
    }
    fn cancel_to_ground(&mut self) {
        self.sim.cancel_mantle();
        self.sim.player.position = vec3(0., 0., 1.);
        self.sim.player.velocity = glam::Vec3::ZERO;
        self.sim.player.grounded = true;
        self.sim.player.previous_grounded = true;
        self.sync();
    }
    fn assert_return(&self, from: &ViewmodelPose) {
        let weight = self.model.low_vault_return_weight().unwrap();
        let target = self
            .oracle
            .source_pose_snapshot(self.sim.time, Mat4::IDENTITY)
            .unwrap();
        let target_is_reload_basis = self.oracle.presentation_route().starts_with("reload.")
            || self.oracle.presentation_route().starts_with("prone.");
        let basis = if target_is_reload_basis {
            canonical_to_reload_actor_basis().inverse() * self.files.low_basis
        } else {
            self.files.low_basis
        };
        let mut mapped = target.pose.clone();
        for actor in &mut mapped.actor_globals {
            *actor = transform(actor.matrix() * basis);
        }
        let set = AnimationSet::load(self.files.dir.join("low.vra")).unwrap();
        let expected = AnchoredPoseBlend::new(&set, "hk416_weapon")
            .unwrap()
            .blend(&set, from, &mapped, weight)
            .unwrap();
        assert_pose(&snapshot(&self.model, self.sim.time), &expected);
        assert!(
            (self.model.visual_ads_amount() - self.oracle.visual_ads_amount() * weight).abs()
                < 1e-6
        );
        assert!(
            (self.model.authored_procedural_weight()
                - self.oracle.authored_procedural_weight() * weight)
                .abs()
                < 1e-6
        );
    }
}

#[test]
fn all_eight_optional_configurations_keep_admitted_routes_and_high_gate_independent() {
    let files = Files::new(false);
    for mask in 0..8 {
        let mut model = files.model(mask);
        assert_eq!(
            model.low_vault_binding().is_some(),
            mask & LOW != 0,
            "mask {mask}"
        );
        assert_eq!(
            model.prone_camera_track().is_some(),
            mask & PRONE != 0,
            "mask {mask}"
        );
        assert!(
            model.high_mantle_binding().is_none(),
            "unreviewed high enabled for mask {mask}"
        );
        assert_eq!(
            model.warning().unwrap().contains("high mantle inactive"),
            mask & HIGH != 0
        );
        let mut sim = scene(0.6);
        bind(&mut sim, &model);
        tick(&mut sim, &mut model, request());
        assert_eq!(
            sim.player.mantle.unwrap().duration(),
            if mask & LOW != 0 { 1.05 } else { 0.6 }
        );
        assert_eq!(model.low_vault_active(), mask & LOW != 0);
        let mut high = scene(1.8);
        bind(&mut high, &model);
        high.update(request(), &Settings::default(), FIXED_DT);
        assert_eq!(high.player.mantle.unwrap().duration(), 0.85);
        assert!(high.high_mantle_presentation().is_none());
        assert_prone_route(&mut model, mask & PRONE != 0);
    }
}

#[test]
fn missing_and_corrupt_optional_payloads_disable_only_their_own_route() {
    for (route, names, warning) in [
        (
            LOW,
            &["low.vra", "low.vrs", "low.vrm", "low.receipt.json"][..],
            "low vault inactive",
        ),
        (
            PRONE,
            &[
                "prone.vra",
                "prone.vrs",
                "prone.vrm",
                "prone.camera.json",
                "prone.receipt.json",
            ][..],
            "prone inactive",
        ),
        (
            HIGH,
            &["high.vra", "high.receipt.json"][..],
            "high mantle inactive",
        ),
    ] {
        for name in names {
            for corrupt in [false, true] {
                let files = Files::new(false);
                let path = files.dir.join(name);
                if corrupt {
                    fs::write(&path, b"corrupt optional payload").unwrap();
                } else if path.exists() {
                    fs::remove_file(&path).unwrap();
                }
                let mut model = files.model(LOW | PRONE | HIGH);
                assert_eq!(
                    model.low_vault_binding().is_some(),
                    route != LOW,
                    "{name}, corrupt={corrupt}"
                );
                assert_eq!(
                    model.prone_camera_track().is_some(),
                    route != PRONE,
                    "{name}, corrupt={corrupt}"
                );
                assert!(model.high_mantle_binding().is_none());
                assert!(
                    model.warning().unwrap().contains(warning),
                    "{}",
                    model.warning().unwrap()
                );
                let mut sim = scene(0.6);
                bind(&mut sim, &model);
                tick(&mut sim, &mut model, request());
                assert_eq!(model.low_vault_active(), route != LOW);
                assert_prone_route(&mut model, route != PRONE);
            }
        }
    }
}

#[test]
fn low_return_tracks_live_ads_walk_reload_and_prone_in_both_actor_bases() {
    for reload_basis in [false, true] {
        for destination in ["ads", "walk", "reload", "prone"] {
            let mut h = Harness::new(reload_basis);
            h.start_low();
            for _ in 0..35 {
                h.tick(Input::default());
            }
            let frozen = snapshot(&h.model, h.sim.time);
            h.cancel_to_ground();
            assert_eq!(h.model.low_vault_return_weight(), Some(0.));
            assert_pose(&snapshot(&h.model, h.sim.time), &frozen);
            h.sim.player.ammo -= 1;
            let input = match destination {
                "ads" => Input {
                    ads: true,
                    ..Input::default()
                },
                "walk" => Input {
                    movement: vec2(1., 0.),
                    ..Input::default()
                },
                "reload" => Input {
                    reload: true,
                    ..Input::default()
                },
                _ => Input {
                    prone: true,
                    ..Input::default()
                },
            };
            for _ in 0..60 {
                h.tick(input);
                h.assert_return(&frozen);
            }
            match destination {
                "ads" => assert!(h.oracle.visual_ads_amount() > 0.),
                "walk" => assert!(h.oracle.walk_weight() > 0.),
                "reload" => assert!(h.oracle.presentation_route().starts_with("reload.")),
                _ => assert_eq!(h.oracle.presentation_route(), "prone.entry_hold"),
            }
            for _ in 0..40 {
                h.tick(input);
            }
            assert!(!h.model.low_vault_active());
            assert_pose(
                &snapshot(&h.model, h.sim.time),
                &snapshot(&h.oracle, h.sim.time),
            );
            assert_eq!(h.model.presentation_route(), h.oracle.presentation_route());
        }
    }
}

#[test]
fn prone_return_yields_to_new_low_and_returns_to_live_prone_residue() {
    let mut h = Harness::new(true);
    let prone = Input {
        prone: true,
        ..Input::default()
    };
    for _ in 0..100 {
        h.tick(prone);
    }
    assert!(h.sim.prone_sample().is_some());
    // Stand through the ordinary crouch/stand transitions. The long outgoing
    // return remains alive when a fresh low mantle is accepted.
    for _ in 0..78 {
        h.tick(Input::default());
    }
    assert!(!h.sim.player.prone);
    assert!(!h.sim.player.crouched);
    assert!(h.sim.prone_return().is_some());
    h.start_low();
    assert!(h.sim.prone_sample().is_none());
    assert_eq!(
        h.model.presentation_route(),
        "low_vault.low_mantle_native_wip"
    );
    h.cancel_to_ground();
    let frozen = snapshot(&h.model, h.sim.time);
    h.tick(prone);
    h.assert_return(&frozen);
    for _ in 0..100 {
        h.tick(prone);
    }
    assert_eq!(h.model.presentation_route(), "prone.entry_hold");
}

#[test]
fn paused_cancel_freezes_but_death_reset_level_and_binding_changes_clear_returns() {
    for interruption in ["death", "reset", "level", "unbind", "replace"] {
        let mut h = Harness::new(false);
        h.start_low();
        for _ in 0..35 {
            h.tick(Input::default());
        }
        let frozen = snapshot(&h.model, h.sim.time);
        h.cancel_to_ground();
        let time = h.sim.time;
        let low_sample = h.sim.low_vault_sample();
        for display_time in [0., 0.001, 99., 1000.] {
            h.sim.update(request(), &Settings::default(), 0.);
            h.sync();
            assert_eq!(h.sim.time, time);
            assert_eq!(h.sim.low_vault_sample(), low_sample);
            assert_eq!(h.model.low_vault_return_weight(), Some(0.));
            assert_pose(&snapshot(&h.model, display_time), &frozen);
        }
        match interruption {
            "death" => h.sim.kill(),
            "reset" => h.sim.reset(),
            "level" => h
                .sim
                .install_level(vec![h.sim.blocks[0].clone()], vec3(0., 0., 2.), 0.),
            "unbind" => h.sim.set_low_vault_binding(None).unwrap(),
            _ => {
                let replacement = Files::new(true);
                let other = replacement.model(LOW);
                h.sim
                    .set_low_vault_binding(other.low_vault_binding().cloned())
                    .unwrap();
            }
        }
        h.sync();
        assert!(!h.model.low_vault_active(), "{interruption}");
        assert_eq!(h.model.low_vault_return_weight(), None, "{interruption}");
        assert!(h.sim.low_vault_sample().is_none());
        assert!(!h.model.presentation_route().starts_with("prone."));
    }
}

#[test]
fn new_low_during_old_return_uses_fresh_native_frame_and_cannot_resurrect_old_fade() {
    let mut h = Harness::new(false);
    h.start_low();
    for _ in 0..30 {
        h.tick(Input::default());
    }
    h.cancel_to_ground();
    while h.sim.time - h.sim.player.last_jump_at < 0.5 {
        h.tick(Input::default());
    }
    assert!(!h.sim.player.jump_held);
    assert!(h.model.low_vault_return_weight().unwrap() > 0.);
    h.start_low();
    assert_eq!(h.model.low_vault_return_weight(), None);
    assert!(h.sim.low_vault_sample().unwrap().source_frame < 2.);
    h.sim.set_low_vault_binding(None).unwrap();
    h.sync();
    assert!(!h.model.low_vault_active());
}

#[test]
fn combined_pose_and_simulation_trace_are_identical_at_30_60_144_and_240_hz() {
    let files = Files::new(true);
    let mut baseline = None;
    for fps in [30, 60, 144, 240] {
        let mut model = files.model(LOW | PRONE | HIGH);
        let mut sim = scene(0.6);
        bind(&mut sim, &model);
        let mut clock = FixedClock::default();
        let mut count = 0;
        let mut trace = Vec::new();
        for _ in 0..fps * 4 {
            for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                let input = if count == 0 {
                    request()
                } else if count < 260 {
                    Input {
                        prone: true,
                        ..Input::default()
                    }
                } else {
                    Input {
                        ads: true,
                        movement: vec2(1., 0.),
                        ..Input::default()
                    }
                };
                tick(&mut sim, &mut model, input);
                trace.push((
                    sim.time,
                    sim.player.position,
                    sim.low_vault_sample(),
                    sim.prone_sample()
                        .map(|p| (p.seconds, p.frame, p.eye_height, p.orientation)),
                    sim.prone_return()
                        .map(|p| (p.sample.seconds, p.sample.frame, p.began, p.duration)),
                    model.presentation_route().to_owned(),
                    snapshot(&model, sim.time),
                    model.visual_ads_amount(),
                    model.authored_procedural_weight(),
                ));
                count += 1;
            }
            // Paused synchronization and arbitrary draw reads may not become
            // a second clock, including frames with no committed tick.
            model.synchronize_traversal_presentation(&sim);
            let _ = snapshot(&model, sim.time + 0.125);
        }
        assert_eq!(count, 480);
        if let Some(expected) = &baseline {
            assert_eq!(&trace, expected, "{fps} FPS");
        } else {
            baseline = Some(trace);
        }
    }
}

#[test]
fn low_and_prone_bindings_do_not_capture_legacy_high_or_hang_pullup_clocks() {
    let files = Files::new(false);
    for mask in [0, LOW, PRONE, LOW | PRONE | HIGH] {
        let mut model = files.model(mask);
        let mut sim = scene(2.7);
        bind(&mut sim, &model);
        sim.blocks[1].bounds.max.z = -2.;
        sim.player.position.z = -2. + RADIUS + 0.3;
        tick(&mut sim, &mut model, request());
        for _ in 0..180 {
            tick(
                &mut sim,
                &mut model,
                Input {
                    movement: vec2(0., 1.),
                    ..Input::default()
                },
            );
            if matches!(sim.player.action, Action::Hang(_)) {
                break;
            }
        }
        assert!(matches!(sim.player.action, Action::Hang(_)), "mask {mask}");
        for _ in 0..60 {
            tick(&mut sim, &mut model, Input::default());
        }
        tick(
            &mut sim,
            &mut model,
            Input {
                jump: true,
                ..Input::default()
            },
        );
        let state = sim.player.mantle.unwrap();
        assert!(state.from_hang);
        assert_eq!(
            state.duration(),
            sim.timings
                .get(vector_range::action::ActionSlot::PullUp)
                .duration
        );
        let mut ticks = 0;
        while sim.player.mantle.is_some() {
            assert!(!model.low_vault_active());
            assert!(sim.high_mantle_presentation().is_none());
            tick(&mut sim, &mut model, Input::default());
            ticks += 1;
            assert!(ticks < 200);
        }
        assert_eq!(sim.player.position.y, 2.7);
        assert!(sim.player.grounded);
    }
}
