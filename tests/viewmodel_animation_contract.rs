//! Original synthetic data only. No soldier meshes, rigs, actions or pose data.
use glam::{Mat4, Quat, Vec3};
use vector_range::{
    skinned_asset::{crc32, Bone},
    viewmodel_animation::{
        game_model_root, AnimationSet, Transform, MAX_ACTORS, MAX_BONES, MAX_CLIPS, MAX_FRAMES,
    },
};

#[derive(Clone)]
struct Actor {
    name: String,
    meshes: Vec<u32>,
    inverse_rest: [f32; 16],
}
#[derive(Clone)]
struct Frame {
    time: f32,
    bones: Vec<Transform>,
    actors: Vec<Transform>,
    visible: Vec<u8>,
}
#[derive(Clone)]
struct Clip {
    name: String,
    flags: u32,
    frames: Vec<Frame>,
}
#[derive(Clone)]
struct Fixture {
    bones: Vec<(String, i32)>,
    actors: Vec<Actor>,
    clips: Vec<Clip>,
}
fn translation(x: f32, y: f32, z: f32) -> Transform {
    Transform {
        translation: Vec3::new(x, y, z),
        ..Transform::IDENTITY
    }
}
fn fixture() -> Fixture {
    Fixture {
        // Child first deliberately tests arbitrary skeleton ordering.
        bones: vec![("child".into(), 1), ("root".into(), -1)],
        actors: vec![Actor {
            name: "prop".into(),
            meshes: vec![0],
            inverse_rest: Mat4::from_translation(Vec3::new(-3., 0., 0.)).to_cols_array(),
        }],
        clips: vec![Clip {
            name: "move".into(),
            flags: 0,
            frames: vec![
                Frame {
                    time: 0.,
                    bones: vec![translation(1., 0., 0.), translation(0., 2., 0.)],
                    actors: vec![translation(3., 0., 0.)],
                    visible: vec![1],
                },
                Frame {
                    time: 1.,
                    bones: vec![translation(3., 0., 0.), translation(0., 4., 0.)],
                    actors: vec![translation(5., 0., 0.)],
                    visible: vec![0],
                },
            ],
        }],
    }
}
fn u32v(out: &mut Vec<u8>, value: u32) {
    out.extend(value.to_le_bytes());
}
fn floats(out: &mut Vec<u8>, values: &[f32]) {
    for value in values {
        out.extend(value.to_le_bytes());
    }
}
fn name(out: &mut Vec<u8>, value: &str) {
    out.extend((value.len() as u16).to_le_bytes());
    out.extend(value.as_bytes());
}
fn transform(out: &mut Vec<u8>, value: Transform) {
    floats(out, &value.translation.to_array());
    floats(out, &value.rotation.to_array());
    floats(out, &value.scale.to_array());
}
fn wrapped(payload: &[u8]) -> Vec<u8> {
    let mut out = b"VRANIM01".to_vec();
    u32v(&mut out, 1);
    u32v(&mut out, payload.len() as u32);
    u32v(&mut out, crc32(payload));
    u32v(&mut out, 0);
    out.extend(payload);
    out
}
fn encode(f: &Fixture) -> Vec<u8> {
    let mut out = Vec::new();
    u32v(&mut out, crc32(b"skin"));
    u32v(&mut out, crc32(b"mesh"));
    u32v(&mut out, f.bones.len() as u32);
    for (n, parent) in &f.bones {
        name(&mut out, n);
        out.extend(parent.to_le_bytes());
    }
    u32v(&mut out, f.actors.len() as u32);
    for a in &f.actors {
        name(&mut out, &a.name);
        u32v(&mut out, a.meshes.len() as u32);
        for mesh in &a.meshes {
            u32v(&mut out, *mesh);
        }
        floats(&mut out, &a.inverse_rest);
    }
    u32v(&mut out, f.clips.len() as u32);
    for c in &f.clips {
        name(&mut out, &c.name);
        u32v(&mut out, c.flags);
        u32v(&mut out, c.frames.len() as u32);
        for frame in &c.frames {
            floats(&mut out, &[frame.time]);
            for t in &frame.bones {
                transform(&mut out, *t);
            }
            for t in &frame.actors {
                transform(&mut out, *t);
            }
            out.extend(&frame.visible);
        }
    }
    wrapped(&out)
}
fn decode(f: &Fixture) -> AnimationSet {
    AnimationSet::decode(&encode(f)).unwrap()
}
fn reject(f: &Fixture, message: &str) {
    let error = AnimationSet::decode(&encode(f)).unwrap_err().to_string();
    assert!(
        error.contains(message),
        "expected {message:?}, got {error:?}"
    );
}
fn bones() -> Vec<Bone> {
    vec![
        Bone {
            name: "child".into(),
            parent: Some(1),
            rest_local: translation(1., 0., 0.).matrix().to_cols_array(),
            inverse_bind: translation(-1., -2., 0.).matrix().to_cols_array(),
        },
        Bone {
            name: "root".into(),
            parent: None,
            rest_local: translation(0., 2., 0.).matrix().to_cols_array(),
            inverse_bind: translation(0., -2., 0.).matrix().to_cols_array(),
        },
    ]
}
fn close(a: Vec3, b: Vec3) {
    assert!((a - b).abs().max_element() < 2e-5, "{a:?} != {b:?}");
}

#[test]
fn decodes_metadata_and_companion_identity() {
    let set = decode(&fixture());
    assert_eq!(set.bones()[0].name, "child");
    assert_eq!(set.bones()[0].parent, Some(1));
    assert_eq!(set.actors()[0].mesh_indices, vec![0]);
    assert_eq!(set.clips()[0].frame_count(), 2);
    assert_eq!(set.clips()[0].times(), &[0., 1.]);
    assert_eq!(set.clips()[0].duration(), 1.);
    assert_eq!(set.companion_checksums(), (crc32(b"skin"), crc32(b"mesh")));
    set.validate_companions(b"skin", b"mesh", &bones(), 1)
        .unwrap();
}
#[test]
fn sampling_is_linear_deterministic_and_clamped() {
    let set = decode(&fixture());
    let pose = set.sample("move", 0.5).unwrap();
    close(pose.bone_locals[0].translation, Vec3::new(2., 0., 0.));
    close(pose.bone_locals[1].translation, Vec3::new(0., 3., 0.));
    close(pose.actor_globals[0].translation, Vec3::new(4., 0., 0.));
    assert_eq!(pose, set.sample("move", 0.5).unwrap());
    assert_eq!(
        set.sample("move", -20.).unwrap(),
        set.sample("move", 0.).unwrap()
    );
    assert_eq!(
        set.sample("move", 20.).unwrap(),
        set.sample("move", 1.).unwrap()
    );
}
#[test]
fn arbitrary_parent_order_and_inverse_bind_reconstruct_vertices() {
    let set = decode(&fixture());
    let pose = set.sample("move", 0.5).unwrap();
    let globals = set.bone_globals(&pose, Mat4::IDENTITY).unwrap();
    close(
        globals[0].transform_point3(Vec3::ZERO),
        Vec3::new(2., 3., 0.),
    );
    let palette = set.skin_palette(&pose, &bones(), Mat4::IDENTITY).unwrap();
    close(
        palette[0].transform_point3(Vec3::new(1., 2., 0.)),
        Vec3::new(2., 3., 0.),
    );
    let matrices = set.actor_matrices(&pose, Mat4::IDENTITY).unwrap();
    close(
        matrices[0].transform_point3(Vec3::new(3., 0., 0.)),
        Vec3::new(4., 0., 0.),
    );
}
#[test]
fn axis_conversion_occurs_once_at_model_root() {
    let set = decode(&fixture());
    let pose = set.sample("move", 0.5).unwrap();
    let globals = set.bone_globals(&pose, game_model_root()).unwrap();
    close(
        globals[0].transform_point3(Vec3::new(0., 0., 2.)),
        Vec3::new(-2., 3., -2.),
    );
    let matrices = set.actor_matrices(&pose, game_model_root()).unwrap();
    close(
        matrices[0].transform_point3(Vec3::new(3., 0., 2.)),
        Vec3::new(-4., 0., -2.),
    );
}
#[test]
fn loops_wrap_exact_endpoint_negative_time_and_clamp_for_parity() {
    let mut f = fixture();
    f.clips[0].flags = 1;
    let set = decode(&f);
    assert_eq!(
        set.sample("move", 1.).unwrap(),
        set.sample("move", 0.).unwrap()
    );
    assert_eq!(
        set.sample("move", 2.).unwrap(),
        set.sample("move", 0.).unwrap()
    );
    assert_eq!(
        set.sample("move", -0.25).unwrap(),
        set.sample("move", 0.75).unwrap()
    );
    assert_eq!(set.sample_clamped("move", 1.).unwrap().sample_time, 1.);
    close(
        set.sample_clamped("move", 1.).unwrap().bone_locals[0].translation,
        Vec3::new(3., 0., 0.),
    );
}
#[test]
fn visibility_is_step_at_keys_and_final_endpoint() {
    let set = decode(&fixture());
    assert!(set.sample("move", 0.999).unwrap().actor_visible[0]);
    assert!(!set.sample("move", 1.).unwrap().actor_visible[0]);
    let mut f = fixture();
    f.clips[0].flags = 1;
    let looping = decode(&f);
    assert!(looping.sample("move", 1.).unwrap().actor_visible[0]);
    assert!(!looping.sample_clamped("move", 1.).unwrap().actor_visible[0]);
}
#[test]
fn one_frame_neutral_holds_at_all_finite_times() {
    let mut f = fixture();
    f.clips[0].frames.truncate(1);
    f.clips[0].flags = 1;
    let set = decode(&f);
    let expected = set.sample("move", 0.).unwrap();
    for time in [-f32::MAX, -1., 0., 1., f32::MAX] {
        assert_eq!(set.sample("move", time).unwrap(), expected);
    }
}
#[test]
fn rotation_uses_shortest_spherical_path_and_scale_lerp() {
    let mut f = fixture();
    f.clips[0].frames[1].bones[0].rotation = Quat::from_rotation_z(270f32.to_radians());
    f.clips[0].frames[1].bones[0].scale = Vec3::new(3., 5., 7.);
    let set = decode(&f);
    let pose = set.sample("move", 0.5).unwrap();
    close(
        pose.bone_locals[0].rotation * Vec3::X,
        Vec3::new(0.5f32.sqrt(), -0.5f32.sqrt(), 0.),
    );
    close(pose.bone_locals[0].scale, Vec3::new(2., 3., 4.));
}
#[test]
fn antipodal_quaternions_do_not_spin_or_produce_nan() {
    let mut f = fixture();
    f.clips[0].frames[1].bones[0].rotation = -Quat::IDENTITY;
    let pose = decode(&f).sample("move", 0.5).unwrap();
    close(pose.bone_locals[0].rotation * Vec3::X, Vec3::X);
}
#[test]
fn nearly_unit_quaternions_are_normalized() {
    let mut f = fixture();
    f.clips[0].frames[0].bones[0].rotation = Quat::from_xyzw(0., 0., 0., 1.00005);
    assert_eq!(
        decode(&f).sample("move", 0.).unwrap().bone_locals[0].rotation,
        Quat::IDENTITY
    );
}
#[test]
fn pure_pose_blending_preserves_endpoints_and_validates_inputs() {
    let set = decode(&fixture());
    let a = set.sample("move", 0.).unwrap();
    let b = set.sample("move", 1.).unwrap();
    assert_eq!(set.blend_poses(&a, &b, 0.).unwrap(), a);
    assert_eq!(set.blend_poses(&a, &b, 1.).unwrap(), b);
    let mixed = set.blend_poses(&a, &b, 0.5).unwrap();
    close(mixed.bone_locals[0].translation, Vec3::new(2., 0., 0.));
    assert!(!mixed.actor_visible[0]);
    for weight in [-1., 1.1, f32::NAN, f32::INFINITY] {
        assert!(set.blend_poses(&a, &b, weight).is_err());
    }
    let mut malformed = a.clone();
    malformed.bone_locals.clear();
    assert!(set.blend_poses(&malformed, &b, 0.5).is_err());
}
#[test]
fn sockets_without_meshes_and_no_actor_animations_are_valid() {
    let mut f = fixture();
    f.actors[0].meshes.clear();
    let set = decode(&f);
    assert!(set.actors()[0].mesh_indices.is_empty());
    set.validate_companions(b"skin", b"mesh", &bones(), 0)
        .unwrap();
    f.actors.clear();
    for frame in &mut f.clips[0].frames {
        frame.actors.clear();
        frame.visible.clear();
    }
    let set = decode(&f);
    let pose = set.sample("move", 0.5).unwrap();
    assert!(pose.actor_globals.is_empty());
    assert!(set
        .actor_matrices(&pose, Mat4::IDENTITY)
        .unwrap()
        .is_empty());
}
#[test]
fn multiple_roots_are_allowed_but_cycles_and_invalid_parents_are_not() {
    let mut f = fixture();
    f.bones[0].1 = -1;
    decode(&f);
    for parent in [-2, 2, i32::MAX] {
        f.bones[0].1 = parent;
        reject(&f, "parent");
    }
    f = fixture();
    f.bones[0].1 = 0;
    reject(&f, "cycle");
    f = fixture();
    f.bones[1].1 = 0;
    reject(&f, "cycle");
}
#[test]
fn duplicate_and_invalid_names_are_rejected() {
    let mut f = fixture();
    f.bones[1].0 = "child".into();
    reject(&f, "duplicate bone");
    f = fixture();
    f.actors.push(f.actors[0].clone());
    reject(&f, "duplicate actor");
    f = fixture();
    f.clips.push(f.clips[0].clone());
    reject(&f, "duplicate clip");
    for invalid in [String::new(), "x\0y".into(), "a".repeat(129)] {
        f = fixture();
        f.bones[0].0 = invalid;
        assert!(AnimationSet::decode(&encode(&f)).is_err());
    }
    let mut encoded = encode(&fixture());
    encoded[38] = 255;
    let fixed = wrapped(&encoded[24..]);
    assert!(AnimationSet::decode(&fixed)
        .unwrap_err()
        .to_string()
        .contains("UTF-8"));
}
#[test]
fn header_length_crc_version_flags_and_trailing_data_are_rejected() {
    let valid = encode(&fixture());
    for (offset, byte) in [(0, b'X'), (8, 2), (12, 0), (16, 0), (20, 1)] {
        let mut malformed = valid.clone();
        malformed[offset] = byte;
        assert!(AnimationSet::decode(&malformed).is_err(), "offset {offset}");
    }
    let mut payload = valid[24..].to_vec();
    payload.push(0);
    assert!(AnimationSet::decode(&wrapped(&payload))
        .unwrap_err()
        .to_string()
        .contains("trailing"));
}
#[test]
fn every_truncation_is_rejected_without_panicking() {
    let valid = encode(&fixture());
    for length in 0..valid.len() {
        assert!(
            AnimationSet::decode(&valid[..length]).is_err(),
            "length {length}"
        );
    }
    // Also test truncations whose length/CRC headers have been repaired.
    for length in 0..valid.len() - 24 {
        assert!(
            AnimationSet::decode(&wrapped(&valid[24..24 + length])).is_err(),
            "payload length {length}"
        );
    }
}
#[test]
fn frame_times_must_start_at_zero_and_strictly_increase() {
    let mut f = fixture();
    for bad in [0.1, -1., f32::NAN, f32::INFINITY] {
        f.clips[0].frames[0].time = bad;
        assert!(AnimationSet::decode(&encode(&f)).is_err());
    }
    for bad in [0., -1., f32::NAN, f32::INFINITY] {
        f = fixture();
        f.clips[0].frames[1].time = bad;
        assert!(AnimationSet::decode(&encode(&f)).is_err());
    }
}
#[test]
fn finite_bounded_positive_trs_and_unit_quaternions_are_required() {
    for bad in [f32::NAN, f32::INFINITY, 10_001., -10_001.] {
        let mut f = fixture();
        f.clips[0].frames[0].bones[0].translation.x = bad;
        assert!(AnimationSet::decode(&encode(&f)).is_err());
    }
    for bad in [f32::NAN, f32::INFINITY, 0., -1., 1e-8, 10_001.] {
        let mut f = fixture();
        f.clips[0].frames[0].actors[0].scale.x = bad;
        assert!(AnimationSet::decode(&encode(&f)).is_err());
    }
    for bad in [
        Quat::from_xyzw(0., 0., 0., 0.),
        Quat::from_xyzw(0., 0., 0., 1.01),
        Quat::from_xyzw(f32::NAN, 0., 0., 1.),
    ] {
        let mut f = fixture();
        f.clips[0].frames[0].bones[0].rotation = bad;
        assert!(AnimationSet::decode(&encode(&f)).is_err());
    }
}
#[test]
fn actor_inverse_rest_must_be_finite_affine_and_nonsingular() {
    for (index, value) in [
        (3, 0.1),
        (7, 1.),
        (11, 1.),
        (15, 0.),
        (0, 0.),
        (12, f32::NAN),
        (12, f32::INFINITY),
    ] {
        let mut f = fixture();
        f.actors[0].inverse_rest[index] = value;
        reject(
            &f,
            if !value.is_finite() {
                "finite"
            } else if index == 0 {
                "singular"
            } else {
                "affine"
            },
        );
    }
}
#[test]
fn rigid_bindings_cannot_overlap_or_escape_companion() {
    let mut f = fixture();
    f.actors[0].meshes = vec![0, 0];
    reject(&f, "duplicate rigid");
    f = fixture();
    let mut duplicate = f.actors[0].clone();
    duplicate.name = "other".into();
    f.actors.push(duplicate);
    reject(&f, "duplicate rigid");
    f = fixture();
    f.actors[0].meshes = vec![256];
    reject(&f, "mesh index");
    f = fixture();
    f.actors[0].meshes = vec![1];
    let set = decode(&f);
    assert!(set
        .validate_companions(b"skin", b"mesh", &bones(), 1)
        .unwrap_err()
        .to_string()
        .contains("outside"));
    assert!(set
        .validate_companions(b"skin", b"mesh", &bones(), 2)
        .unwrap_err()
        .to_string()
        .contains("unbound"));
}
#[test]
fn companion_crc_skeleton_order_names_and_parents_must_match() {
    let set = decode(&fixture());
    assert!(set
        .validate_companions(b"different", b"mesh", &bones(), 1)
        .is_err());
    assert!(set
        .validate_companions(b"skin", b"different", &bones(), 1)
        .is_err());
    assert!(set
        .validate_companions(b"skin", b"mesh", &bones()[..1], 1)
        .is_err());
    let mut different = bones();
    different.swap(0, 1);
    assert!(set
        .validate_companions(b"skin", b"mesh", &different, 1)
        .is_err());
    different = bones();
    different[0].name = "other".into();
    assert!(set
        .validate_companions(b"skin", b"mesh", &different, 1)
        .is_err());
    different = bones();
    different[0].parent = None;
    assert!(set
        .validate_companions(b"skin", b"mesh", &different, 1)
        .is_err());
    assert!(set
        .validate_companions(b"skin", b"mesh", &bones(), 257)
        .is_err());
}
#[test]
fn unknown_clips_nonfinite_times_and_malformed_public_poses_fail_cleanly() {
    let set = decode(&fixture());
    assert!(set.sample("missing", 0.).is_err());
    for time in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
        assert!(set.sample("move", time).is_err());
        assert!(set.sample_clamped("move", time).is_err());
    }
    let mut pose = set.sample("move", 0.).unwrap();
    pose.actor_visible.clear();
    assert!(set.actor_matrices(&pose, Mat4::IDENTITY).is_err());
    pose = set.sample("move", 0.).unwrap();
    pose.bone_locals[0].scale = Vec3::ZERO;
    assert!(set.bone_globals(&pose, Mat4::IDENTITY).is_err());
    pose = set.sample("move", 0.).unwrap();
    assert!(set.bone_globals(&pose, Mat4::ZERO).is_err());
    let mut wrong_bones = bones();
    wrong_bones[0].inverse_bind[0] = f32::NAN;
    assert!(set
        .skin_palette(&pose, &wrong_bones, Mat4::IDENTITY)
        .is_err());
}
#[test]
fn visibility_and_clip_flags_reject_unknown_values() {
    let mut f = fixture();
    f.clips[0].frames[0].visible[0] = 2;
    reject(&f, "visibility");
    for flags in [2, u32::MAX] {
        f = fixture();
        f.clips[0].flags = flags;
        reject(&f, "flags");
    }
}
#[test]
fn count_caps_reject_before_large_allocations() {
    // Minimal payload with deliberately huge counts and no corresponding storage.
    for count in [0, (MAX_BONES + 1) as u32, u32::MAX] {
        let mut p = vec![0; 8];
        u32v(&mut p, count);
        assert!(AnimationSet::decode(&wrapped(&p))
            .unwrap_err()
            .to_string()
            .contains("bone count"));
    }
    let mut p = vec![0; 8];
    u32v(&mut p, 1);
    name(&mut p, "root");
    u32v(&mut p, u32::MAX);
    let skeleton = p.clone();
    for count in [(MAX_ACTORS + 1) as u32, u32::MAX] {
        let mut p = skeleton.clone();
        u32v(&mut p, count);
        assert!(AnimationSet::decode(&wrapped(&p))
            .unwrap_err()
            .to_string()
            .contains("actor count"));
    }
    u32v(&mut p, 0);
    let actors = p.clone();
    for count in [0, (MAX_CLIPS + 1) as u32, u32::MAX] {
        let mut p = actors.clone();
        u32v(&mut p, count);
        assert!(AnimationSet::decode(&wrapped(&p))
            .unwrap_err()
            .to_string()
            .contains("clip count"));
    }
    u32v(&mut p, 1);
    name(&mut p, "clip");
    u32v(&mut p, 0);
    let clip = p.clone();
    for count in [0, (MAX_FRAMES + 1) as u32, u32::MAX] {
        let mut p = clip.clone();
        u32v(&mut p, count);
        assert!(AnimationSet::decode(&wrapped(&p))
            .unwrap_err()
            .to_string()
            .contains("frame count"));
    }
    u32v(&mut p, MAX_FRAMES as u32);
    assert!(AnimationSet::decode(&wrapped(&p))
        .unwrap_err()
        .to_string()
        .contains("truncated animation frames"));
}
#[test]
fn aggregate_transform_budget_rejects_before_allocating_tracks() {
    let mut p = vec![0; 8];
    u32v(&mut p, 128);
    for index in 0..128 {
        name(&mut p, &format!("bone{index}"));
        u32v(&mut p, u32::MAX);
    }
    u32v(&mut p, 0);
    u32v(&mut p, 1);
    name(&mut p, "large");
    u32v(&mut p, 0);
    u32v(&mut p, 65_536);
    assert!(AnimationSet::decode(&wrapped(&p))
        .unwrap_err()
        .to_string()
        .contains("transform budget"));
}
#[test]
fn composed_transform_overflow_is_an_error_instead_of_nan_output() {
    let mut f = fixture();
    f.bones = (0..20)
        .map(|i| (format!("bone{i}"), if i == 0 { -1 } else { i - 1 }))
        .collect();
    for frame in &mut f.clips[0].frames {
        frame.bones = vec![
            Transform {
                scale: Vec3::splat(10_000.),
                ..Transform::IDENTITY
            };
            20
        ];
    }
    let set = decode(&f);
    let pose = set.sample("move", 0.).unwrap();
    assert!(set.bone_globals(&pose, Mat4::IDENTITY).is_err());
}

fn container(magic: &[u8; 8], version: u32, payload: &[u8]) -> Vec<u8> {
    let mut out = magic.to_vec();
    u32v(&mut out, version);
    u32v(&mut out, payload.len() as u32);
    u32v(&mut out, crc32(payload));
    u32v(&mut out, 0);
    out.extend(payload);
    out
}
fn companion_fixture() -> (Vec<u8>, Vec<u8>, Vec<u8>) {
    let mut skin = Vec::new();
    u32v(&mut skin, 2);
    for bone in bones() {
        name(&mut skin, &bone.name);
        u32v(&mut skin, bone.parent.map_or(u32::MAX, |p| p as u32));
        floats(&mut skin, &bone.rest_local);
        floats(&mut skin, &bone.inverse_bind);
    }
    u32v(&mut skin, 1);
    let mut mesh = Vec::new();
    u32v(&mut mesh, 1);
    for (out, skinned) in [(&mut skin, true), (&mut mesh, false)] {
        floats(out, &[1., 1., 1., 1., 0., 0.8]); // Material
        for _ in 0..3 {
            u32v(out, 0);
        } // No texture
        u32v(out, 3);
        u32v(out, 3);
        for position in if skinned {
            [[1., 2., 0.], [2., 2., 0.], [1., 3., 0.]]
        } else {
            [[3., 0., 0.], [4., 0., 0.], [3., 1., 0.]]
        } {
            floats(out, &position);
            floats(out, &[0., 0., 1.]);
            floats(out, &[0., 0.]);
            if skinned {
                out.extend([0u8; 16]);
                floats(out, &[1., 0., 0., 0., 0., 0., 0., 0.]);
            }
        }
        for index in 0..3 {
            u32v(out, index);
        }
    }
    let skin = container(b"VRSKIN02", 2, &skin);
    let mesh = container(b"VRMESH01", 1, &mesh);
    let mut payload = encode(&fixture())[24..].to_vec();
    payload[..4].copy_from_slice(&crc32(&skin).to_le_bytes());
    payload[4..8].copy_from_slice(&crc32(&mesh).to_le_bytes());
    (wrapped(&payload), skin, mesh)
}
struct TemporaryDirectory(std::path::PathBuf);
impl TemporaryDirectory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
        let sequence = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "rust-duty-original-animation-test-{}-{now}-{sequence}",
            std::process::id()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for TemporaryDirectory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
#[test]
fn load_bundle_decodes_real_companions_and_detects_stale_or_missing_files() {
    let directory = TemporaryDirectory::new();
    let path = directory.0.join("original.vra");
    let (animation, skin, mesh) = companion_fixture();
    std::fs::write(&path, &animation).unwrap();
    std::fs::write(path.with_extension("vrs"), &skin).unwrap();
    std::fs::write(path.with_extension("vrm"), &mesh).unwrap();
    let (set, skin_decoded, rigid) = AnimationSet::load_with_companions(&path).unwrap();
    assert_eq!(skin_decoded.bones.len(), 2);
    assert_eq!(rigid.meshes.len(), 1);
    let pose = set.sample("move", 0.5).unwrap();
    let palette = set
        .skin_palette(&pose, &skin_decoded.bones, Mat4::IDENTITY)
        .unwrap();
    close(
        palette[0].transform_point3(Vec3::from_array(
            skin_decoded.meshes[0].vertices[0].position,
        )),
        Vec3::new(2., 3., 0.),
    );
    let mut stale = mesh[24..].to_vec();
    stale[4..8].copy_from_slice(&0.5f32.to_le_bytes());
    std::fs::write(
        path.with_extension("vrm"),
        container(b"VRMESH01", 1, &stale),
    )
    .unwrap();
    assert!(AnimationSet::load_with_companions(&path)
        .unwrap_err()
        .to_string()
        .contains("companion checksum"));
    std::fs::remove_file(path.with_extension("vrs")).unwrap();
    assert!(AnimationSet::load_with_companions(&path).is_err());
}
#[test]
fn file_size_bound_is_checked_before_reading_sparse_file() {
    let directory = TemporaryDirectory::new();
    let path = directory.0.join("oversized.vra");
    let file = std::fs::File::create(&path).unwrap();
    file.set_len((vector_range::viewmodel_animation::MAX_FILE + 1) as u64)
        .unwrap();
    assert!(AnimationSet::load(&path)
        .unwrap_err()
        .to_string()
        .contains("128 MiB"));
}
