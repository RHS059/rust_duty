//! Original synthetic full-manifest fixtures; no private/source animation assets.
//! These exercise observer ordering, basis conversion and outgoing presentation.
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
    sync::atomic::{AtomicUsize, Ordering},
};
use vector_range::{
    authored_low_vault::POLICY,
    authored_pose_return::canonical_to_reload_actor_basis,
    layered_locomotion::AnchoredPoseBlend,
    settings::Settings,
    sim::{Aabb, Block, Input, Simulation, FIXED_DT},
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
struct Files {
    dir: PathBuf,
    low_basis: Mat4,
}
impl Files {
    fn new(reload_basis: bool, receipt_anchor: &str, reload_extra: bool) -> Self {
        static ID: AtomicUsize = AtomicUsize::new(0);
        let dir = std::env::temp_dir().join(format!(
            "rust-duty-low-return-{}-{}",
            std::process::id(),
            ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&dir).unwrap();
        let base_clips: Vec<_> = [
            "ready", "entry", "loop", "bridge0", "bridge1", "exit", "settle",
        ]
        .into_iter()
        .map(|name| Clip {
            name,
            looping: name == "loop",
            frames: 2,
            seconds: 0.5,
            from_x: 0.2,
            to_x: 0.2,
        })
        .collect();
        let base = animation(&base_clips, &["hk416_weapon"], Mat4::IDENTITY);
        let ads = animation(
            &[
                Clip {
                    name: "ads_entry",
                    looping: false,
                    frames: 2,
                    seconds: 0.3,
                    from_x: 0.2,
                    to_x: 0.7,
                },
                Clip {
                    name: "ads_hold",
                    looping: true,
                    frames: 2,
                    seconds: 0.3,
                    from_x: 0.7,
                    to_x: 0.7,
                },
                Clip {
                    name: "ads_exit",
                    looping: false,
                    frames: 2,
                    seconds: 0.3,
                    from_x: 0.7,
                    to_x: 0.2,
                },
            ],
            &["hk416_weapon"],
            Mat4::IDENTITY,
        );
        let reload_actors = if reload_extra {
            vec!["hk416_weapon", "reload_only_prop"]
        } else {
            vec!["hk416_weapon"]
        };
        let reload = animation(
            &[Clip {
                name: "reload",
                looping: false,
                frames: 2,
                seconds: 1.,
                from_x: 0.4,
                to_x: 1.2,
            }],
            &reload_actors,
            canonical_to_reload_actor_basis(),
        );
        let low_basis = if reload_basis {
            canonical_to_reload_actor_basis()
        } else {
            Mat4::IDENTITY
        };
        let low = animation(
            &[Clip {
                name: "native_low",
                looping: false,
                frames: 64,
                seconds: 1.05,
                from_x: -0.4,
                to_x: -1.45,
            }],
            &["hk416_weapon"],
            low_basis,
        );
        let receipt = serde_json::to_vec(&json!({
            "schema":"rust-duty-low-vault-runtime/v1", "presentation_policy":POLICY,
            "clip_name":"native_low", "source_action":"original_synthetic_return_fixture", "export_take":"synthetic_fbx_stack",
            "return_seconds":0.2, "actor_basis":if reload_basis {"reload_mesh_local"} else {"canonical"}, "anchor_actor":receipt_anchor,
            "candidate_sha256":"1".repeat(64), "source_action_fingerprint":"2".repeat(64), "source_fbx_sha256":"3".repeat(64),
            "asset_vra_sha256":rust_duty_launcher::bytes_hash(&low),
            "candidate_frame_range":[1,64], "reference_frame_range_half_open":[7284,7348], "native_fps":[60,1], "native_crop":[0,63], "imported_frame_offset":1, "subdivisions":1
        })).unwrap();
        let (skin, rigid) = companions();
        for (stem, bytes) in [
            ("base", base),
            ("ads", ads),
            ("reload", reload),
            ("low", low),
        ] {
            fs::write(dir.join(format!("{stem}.vra")), bytes).unwrap();
            fs::write(dir.join(format!("{stem}.vrs")), &skin).unwrap();
            fs::write(dir.join(format!("{stem}.vrm")), &rigid).unwrap();
        }
        fs::write(dir.join("receipt.json"), &receipt).unwrap();
        let plain = "schema=rust-duty-animation-slots/v1\nlocomotion.asset=base.vra\nlayers.anchor_actor=hk416_weapon\nready.clip=ready\nsprint.entry.clip=entry\nsprint.loop.clip=loop\nsprint.bridges=bridge0,bridge1\nsprint.exit.clip=exit\nsprint.settle.clip=settle\nsprint.response_seconds=0.05\nsprint.residual_seconds=0.03\nregular_walk=unavailable\nreload.tactical.asset=reload.vra\nreload.tactical.clip=reload\nreload.empty=unavailable\nreload.route=anchored_crossfade\nreload.clock=native_complete\nads.asset=ads.vra\nads.entry.clip=ads_entry\nads.hold.clip=ads_hold\nads.exit.clip=ads_exit\nads.clock=native_reversible\nfire=unavailable\nmantle=unavailable\n";
        fs::write(dir.join("plain.cfg"), plain).unwrap();
        fs::write(dir.join("low.cfg"), format!("{plain}low_vault.policy={POLICY}\nlow_vault.asset=low.vra\nlow_vault.clip=native_low\nlow_vault.receipt=receipt.json\nlow_vault.receipt_sha256={}\n", rust_duty_launcher::bytes_hash(&receipt))).unwrap();
        Self { dir, low_basis }
    }
    fn model(&self, low: bool) -> Result<AuthoredViewmodel, String> {
        AuthoredViewmodel::load_manifest(&self.dir.join(if low { "low.cfg" } else { "plain.cfg" }))
    }
}
impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}
fn scene() -> Simulation {
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
    sim.targets.clear();
    sim.ramps.clear();
    sim.player.position = vec3(0., 0., 1.);
    sim.player.yaw = -std::f32::consts::FRAC_PI_2;
    sim
}
struct Harness {
    files: Files,
    model: AuthoredViewmodel,
    oracle: AuthoredViewmodel,
    sim: Simulation,
    observer: Simulation,
}
impl Harness {
    fn new(reload_basis: bool) -> Self {
        let files = Files::new(reload_basis, "hk416_weapon", false);
        let model = files.model(true).unwrap();
        let oracle = files.model(false).unwrap();
        let mut sim = scene();
        sim.set_low_vault_binding(model.low_vault_binding().cloned())
            .unwrap();
        Self {
            files,
            model,
            oracle,
            sim,
            observer: Simulation::new(),
        }
    }
    fn tick(&mut self, input: Input) {
        let start = self.sim.time;
        self.sim.update(input, &Settings::default(), FIXED_DT);
        self.model.committed_step(start, &self.sim);
        // Feed exactly the same authoritative presentation fields to a second,
        // full-manifest observer with no low-vault layer. It is our live target.
        self.observer.time = self.sim.time;
        let source = &self.sim.player;
        let target = &mut self.observer.player;
        target.reload_left = source.reload_left;
        target.reload_ready_at = source.reload_ready_at;
        target.reload_total = source.reload_total;
        target.reload_empty = source.reload_empty;
        target.ads = source.ads;
        target.ads_requested = source.ads_requested;
        target.sprinting = source.sprinting;
        target.velocity = source.velocity;
        target.grounded = source.grounded;
        target.mantle = source.mantle;
        self.oracle.committed_step(start, &self.observer);
        assert!(self.model.error().is_none(), "{:?}", self.model.error());
        assert!(self.oracle.error().is_none(), "{:?}", self.oracle.error());
    }
    fn start(&mut self) {
        self.tick(Input {
            movement: vec2(0., 1.),
            jump: true,
            ..Input::default()
        });
        assert!(self.model.low_vault_active());
    }
    fn snapshot(&self) -> ViewmodelPose {
        self.model
            .source_pose_snapshot(self.sim.time, Mat4::IDENTITY)
            .unwrap()
            .pose
    }
    fn assert_return_matches_live_target(&self, from: &ViewmodelPose) {
        let weight = self.model.low_vault_return_weight().unwrap();
        let target = self
            .oracle
            .source_pose_snapshot(self.sim.time, Mat4::IDENTITY)
            .unwrap();
        let target_is_reload = self.oracle.presentation_route().starts_with("reload.");
        let basis = if target_is_reload {
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
        assert_pose(&self.snapshot(), &expected);
        assert!(
            (self.model.visual_ads_amount() - self.oracle.visual_ads_amount() * weight).abs()
                < 1e-6
        );
        assert!((self.model.low_vault_underlying_weight() - weight).abs() < 1e-6);
    }
}
fn assert_pose(actual: &ViewmodelPose, expected: &ViewmodelPose) {
    assert_eq!(actual.actor_visible, expected.actor_visible);
    for (a, b) in actual
        .bone_locals
        .iter()
        .chain(&actual.actor_globals)
        .zip(expected.bone_locals.iter().chain(&expected.actor_globals))
    {
        assert!(
            a.matrix().abs_diff_eq(b.matrix(), 3e-5),
            "actual {:?}, expected {:?}",
            a,
            b
        );
    }
}

#[test]
fn full_manifest_native_endpoint_returns_to_live_ads_without_retiming() {
    for reload_basis in [false, true] {
        let mut h = Harness::new(reload_basis);
        h.start();
        for _ in 1..126 {
            h.tick(Input::default());
        }
        assert_eq!(h.sim.low_vault_sample().unwrap().source_frame, 64.);
        assert_eq!(h.model.low_vault_return_weight(), None);
        let endpoint = h.snapshot();
        let source = AnimationSet::load(h.files.dir.join("low.vra"))
            .unwrap()
            .sample_clamped("native_low", 1.05)
            .unwrap();
        assert_pose(&endpoint, &source);
        let aim = Input {
            ads: true,
            ..Input::default()
        };
        h.tick(aim);
        assert_eq!(h.model.low_vault_return_weight(), Some(0.));
        assert_pose(&h.snapshot(), &endpoint);
        for _ in 0..12 {
            h.tick(aim);
            h.assert_return_matches_live_target(&endpoint);
        }
        assert!(h.oracle.ads_sample().is_some());
        assert!(h.model.visual_ads_amount() > 0.);
        for _ in 0..13 {
            h.tick(aim);
        }
        assert!(!h.model.low_vault_active());
        assert_pose(
            &h.snapshot(),
            &h.oracle
                .source_pose_snapshot(h.sim.time, Mat4::IDENTITY)
                .unwrap()
                .pose,
        );
        assert!((h.model.visual_ads_amount() - h.oracle.visual_ads_amount()).abs() < 1e-6);
    }
}

#[test]
fn paused_cancel_freezes_then_returns_to_live_reload_in_each_actor_basis() {
    for reload_basis in [false, true] {
        let mut h = Harness::new(reload_basis);
        h.start();
        for _ in 1..40 {
            h.tick(Input::default());
        }
        let frozen = h.snapshot();
        h.sim.cancel_mantle();
        h.model.synchronize_low_vault(&h.sim);
        assert_eq!(h.model.low_vault_return_weight(), Some(0.));
        for time in [0., 10., 100.] {
            h.model.synchronize_low_vault(&h.sim);
            assert_pose(
                &h.model
                    .source_pose_snapshot(time, Mat4::IDENTITY)
                    .unwrap()
                    .pose,
                &frozen,
            );
            assert_eq!(h.model.low_vault_return_weight(), Some(0.));
        }
        h.sim.player.ammo -= 1;
        h.tick(Input {
            reload: true,
            ..Input::default()
        });
        assert!(h.model.reload_sample().is_some());
        h.assert_return_matches_live_target(&frozen);
        for _ in 0..12 {
            h.tick(Input::default());
            h.assert_return_matches_live_target(&frozen);
        }
        for _ in 0..12 {
            h.tick(Input::default());
        }
        assert!(!h.model.low_vault_active());
        assert!(h.model.presentation_route().starts_with("reload."));
        assert_pose(
            &h.snapshot(),
            &h.oracle
                .source_pose_snapshot(h.sim.time, Mat4::IDENTITY)
                .unwrap()
                .pose,
        );
    }
}

#[test]
fn missing_anchor_and_reload_only_actors_fail_before_full_manifest_activation() {
    for (anchor, extra, message) in [
        ("missing_anchor", false, "shared anchor"),
        ("hk416_weapon", true, "incoming actors"),
    ] {
        let files = Files::new(false, anchor, extra);
        let error = files
            .model(true)
            .err()
            .expect("incompatible return must fail activation");
        assert!(error.contains(message), "{error}");
        assert!(
            files.model(false).is_ok(),
            "ordinary manifest must remain usable"
        );
    }
}

#[test]
fn death_and_reset_clear_an_outgoing_full_manifest_return_immediately() {
    for death in [false, true] {
        let mut h = Harness::new(false);
        h.start();
        h.sim.cancel_mantle();
        h.model.synchronize_low_vault(&h.sim);
        assert_eq!(h.model.low_vault_return_weight(), Some(0.));
        if death {
            h.sim.kill();
            h.model.synchronize_low_vault(&h.sim);
        } else {
            h.sim.reset();
            h.model.reset(h.sim.time);
        }
        assert!(!h.model.low_vault_active());
        assert_eq!(h.model.low_vault_return_weight(), None);
    }
}
