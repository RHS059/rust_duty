//! Original, source-free fixtures. No soldier assets, authored rig data or supplied
//! camera JSON are embedded here. Both companions are exercised through from_pair.
use glam::{vec2, vec3, Mat3, Mat4, Quat, Vec3};
use serde_json::{json, Value};
use std::{
    path::Path,
    sync::{Arc, OnceLock},
};
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_prone::{
        camera_axes, ProneCameraTrack, ProneSample, CAMERA_ACTION, ENTRY_SECONDS, PRONE_EYE_HEIGHT,
        REMOVAL_POLICY, RIG_ACTION,
    },
    clock::FixedClock,
    settings::Settings,
    sim::{Aabb, Action, Block, Input, Simulation, FIXED_DT, PRONE_HEIGHT},
    skinned_asset::crc32,
    viewmodel_animation::AnimationSet,
};

#[derive(Clone)]
struct PairFixture {
    asset: Vec<u8>,
    camera: Value,
    receipt: Value,
}

fn matrix_json(matrix: Mat4) -> Value {
    json!((0..4)
        .map(|row| matrix.row(row).to_array())
        .collect::<Vec<_>>())
}

fn initial_camera() -> Mat4 {
    // A nonidentity source basis catches treating world rotation as camera-local.
    Mat4::from_rotation_translation(
        Quat::from_rotation_x(1.2) * Quat::from_rotation_z(0.2),
        vec3(2., -3., 1.75),
    )
}

fn depth_at(frame: f64) -> f32 {
    if frame <= 11. {
        0.
    } else if frame <= 35. {
        ((frame - 11.) / 24. * (65. / 63.)) as f32
    } else {
        (1. + (69. - frame) / 34. * (2. / 63.)) as f32
    }
}

fn orientation_at(frame: f64) -> Quat {
    if frame <= 11. || frame >= 69. {
        Quat::IDENTITY
    } else {
        let weight = (((frame - 11.) / 58.) * std::f64::consts::PI).sin() as f32;
        Quat::from_rotation_x(0.07 * weight) * Quat::from_rotation_z(-0.05 * weight)
    }
}

fn replace_row_pose(row: &mut Value, depth: f32, orientation: Quat) {
    let initial = initial_camera();
    let rotation = Quat::from_mat3(&Mat3::from_mat4(initial));
    let camera = Mat4::from_rotation_translation(
        rotation * orientation,
        initial.w_axis.truncate() - Vec3::Z * (1.26 * depth),
    );
    row["camera_world"] = matrix_json(camera);
    row["common_world_delta"] = matrix_json(camera * initial.inverse());
    row["normalized_depth_fraction"] = json!(depth);
}

fn word(bytes: &mut Vec<u8>, value: u32) {
    bytes.extend(value.to_le_bytes());
}

fn name(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend((value.len() as u16).to_le_bytes());
    bytes.extend(value.as_bytes());
}

fn floats(bytes: &mut Vec<u8>, values: &[f32]) {
    for value in values {
        bytes.extend(value.to_le_bytes());
    }
}

fn synthetic_animation() -> Vec<u8> {
    // A valid one-bone clip whose X translation is its native playback time.
    // This makes camera/viewmodel clock agreement observable without source poses.
    let mut payload = Vec::new();
    word(&mut payload, crc32(b"original synthetic skin"));
    word(&mut payload, crc32(b"original synthetic mesh"));
    word(&mut payload, 1);
    name(&mut payload, "synthetic_root");
    payload.extend((-1_i32).to_le_bytes());
    word(&mut payload, 0); // No rigid actors.
    word(&mut payload, 1);
    name(&mut payload, RIG_ACTION);
    word(&mut payload, 0); // Explicitly nonlooping.
    word(&mut payload, 2);
    for seconds in [0., ENTRY_SECONDS as f32] {
        floats(&mut payload, &[seconds]);
        floats(&mut payload, &[seconds, 0., 0.]);
        floats(&mut payload, &[0., 0., 0., 1.]);
        floats(&mut payload, &[1., 1., 1.]);
    }
    let mut bytes = b"VRANIM01".to_vec();
    word(&mut bytes, 1);
    word(&mut bytes, payload.len() as u32);
    word(&mut bytes, crc32(&payload));
    word(&mut bytes, 0);
    bytes.extend(payload);
    bytes
}

impl PairFixture {
    fn new() -> Self {
        let mut rows = Vec::with_capacity(545);
        for index in 0..545 {
            let frame = 1. + index as f64 / 8.;
            let mut row = json!({
                "candidate_frame": frame,
                "time_seconds": index as f64 / 480.,
            });
            replace_row_pose(&mut row, depth_at(frame), orientation_at(frame));
            rows.push(row);
        }
        let fingerprints = json!({
            RIG_ACTION: rust_duty_launcher::bytes_hash(b"original synthetic rig Action"),
            CAMERA_ACTION: rust_duty_launcher::bytes_hash(b"original synthetic camera Action"),
        });
        let candidate = rust_duty_launcher::bytes_hash(b"original synthetic candidate");
        let camera = json!({
            "schema": "prone-entry-r6-camera-motion/v1",
            "sample_hz": 480,
            "fps": 60,
            "units": "metres and radians; Blender world +Z up",
            "camera_local_axes": "+X right, +Y up, -Z forward",
            "duration_key_span_seconds": ENTRY_SECONDS,
            "candidate_sha256": candidate,
            "action_fingerprints": fingerprints,
            "initial_camera_world": matrix_json(initial_camera()),
            "height_contract": {
                "mode": "replace_stance_height_during_clip",
                "allow_impact_overshoot": true,
                "source_endpoint_descent_m": 1.26,
                "runtime_target_prone_eye_height_m": 0.2794,
            },
            "rows": rows,
        });
        let receipt = json!({
            "schema": "rust-duty-prone-camera-pair/v1",
            "candidate_sha256": candidate,
            "action_fingerprints": fingerprints,
            "clip_name": RIG_ACTION,
            "common_motion_removal": REMOVAL_POLICY,
            "native_fps": [60, 1],
            "source_fbx_sha256": rust_duty_launcher::bytes_hash(b"original synthetic source export"),
            "native_crop": [18, 86],
            "candidate_frame_offset": -17,
            "candidate_frame_range": [1, 69],
            "canonical_rest_frame": 1,
        });
        Self {
            asset: synthetic_animation(),
            camera,
            receipt,
        }
    }

    fn encoded(&self) -> (Vec<u8>, Vec<u8>) {
        let camera = serde_json::to_vec(&self.camera).unwrap();
        let mut receipt = self.receipt.clone();
        receipt["asset_vra_sha256"] = json!(rust_duty_launcher::bytes_hash(&self.asset));
        receipt["camera_sidecar_sha256"] = json!(rust_duty_launcher::bytes_hash(&camera));
        (camera, serde_json::to_vec(&receipt).unwrap())
    }

    fn parse(&self) -> Result<ProneCameraTrack, String> {
        let (camera, receipt) = self.encoded();
        ProneCameraTrack::from_pair(&self.asset, &camera, &receipt, RIG_ACTION)
    }

    fn reject(&self, expected: &str) {
        // Recompute the sidecar hash so semantic tests really reach validation.
        let error = self.parse().unwrap_err();
        assert!(
            error.contains(expected),
            "expected {expected:?}, got {error:?}"
        );
    }
}

fn track() -> Arc<ProneCameraTrack> {
    static TRACK: OnceLock<Arc<ProneCameraTrack>> = OnceLock::new();
    Arc::clone(TRACK.get_or_init(|| Arc::new(PairFixture::new().parse().unwrap())))
}

fn close(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "actual {actual:.12}, expected {expected:.12}, tolerance {tolerance}"
    );
}

fn flat() -> Simulation {
    let mut sim = Simulation::new();
    sim.blocks = vec![Block {
        bounds: Aabb {
            min: vec3(-60., -1., -60.),
            max: vec3(60., 0., 60.),
        },
        kind: 0,
    }];
    sim.ramps.clear();
    sim.targets.clear();
    sim
}

fn configured() -> Simulation {
    let mut sim = flat();
    sim.set_prone_camera_track(Some(track()));
    sim
}

fn prone() -> Input {
    Input {
        prone: true,
        ..Input::default()
    }
}

fn crouch() -> Input {
    Input {
        crouch: true,
        ..Input::default()
    }
}

fn tick(sim: &mut Simulation, input: Input) {
    sim.update(input, &Settings::default(), FIXED_DT);
}

fn ticks(sim: &mut Simulation, input: Input, count: usize) {
    for _ in 0..count {
        tick(sim, input);
    }
}

fn enter(sim: &mut Simulation) -> f32 {
    ticks(sim, crouch(), 30);
    assert!(sim.player.crouched && !sim.player.prone);
    assert!(sim.prone_sample().is_none());
    let entry_height = sim.player.eye_height;
    tick(sim, prone());
    assert!(sim.player.prone);
    let sample = sim.prone_sample().expect("accepted crouch-to-prone entry");
    assert_eq!(sample.seconds, 0.);
    assert_eq!(sample.frame, 1.);
    assert_eq!(sample.eye_height, entry_height);
    entry_height
}

fn mid_entry() -> Simulation {
    let mut sim = configured();
    enter(&mut sim);
    ticks(&mut sim, prone(), 48);
    assert!(sim.prone_sample().unwrap().frame > 24.);
    sim
}

fn sample_signature(sample: Option<ProneSample>) -> Option<(f64, f64, f32, [f32; 4])> {
    sample.map(|s| (s.seconds, s.frame, s.eye_height, s.orientation.to_array()))
}

#[test]
fn generated_pair_has_all_545_rows_and_a_real_original_animation_companion() {
    let fixture = PairFixture::new();
    assert_eq!(fixture.camera["rows"].as_array().unwrap().len(), 545);
    let animation = AnimationSet::decode(&fixture.asset).unwrap();
    assert_eq!(animation.clips()[0].name, RIG_ACTION);
    assert!(!animation.clips()[0].looping);
    close(animation.clips()[0].duration() as f64, ENTRY_SECONDS, 1e-7);
    fixture.parse().unwrap();
}

#[test]
fn missing_companions_or_changed_exact_bytes_fail_closed() {
    let fixture = PairFixture::new();
    let (camera, receipt) = fixture.encoded();
    for (asset, sidecar, pair) in [
        (&[][..], camera.as_slice(), receipt.as_slice()),
        (fixture.asset.as_slice(), &[][..], receipt.as_slice()),
        (fixture.asset.as_slice(), camera.as_slice(), &[][..]),
    ] {
        assert!(ProneCameraTrack::from_pair(asset, sidecar, pair, RIG_ACTION).is_err());
    }
    let mut changed_asset = fixture.asset.clone();
    changed_asset.push(0);
    assert!(
        ProneCameraTrack::from_pair(&changed_asset, &camera, &receipt, RIG_ACTION)
            .unwrap_err()
            .contains("VRA fingerprint mismatch")
    );
    let mut changed_camera = camera.clone();
    changed_camera.push(b' '); // Semantically identical JSON is still another file.
    assert!(
        ProneCameraTrack::from_pair(&fixture.asset, &changed_camera, &receipt, RIG_ACTION)
            .unwrap_err()
            .contains("camera fingerprint mismatch")
    );
    assert!(
        ProneCameraTrack::from_pair(&fixture.asset, &camera, &receipt, "another_clip")
            .unwrap_err()
            .contains("clip mismatch")
    );
}

#[test]
fn candidate_and_both_action_fingerprints_are_pinned() {
    let mut fixture = PairFixture::new();
    fixture.receipt["candidate_sha256"] = json!("0".repeat(64));
    fixture.reject("candidate fingerprint mismatch");
    for action in [RIG_ACTION, CAMERA_ACTION] {
        let mut fixture = PairFixture::new();
        fixture.receipt["action_fingerprints"][action] = json!("0".repeat(64));
        fixture.reject("Action fingerprint mismatch");
        fixture.receipt["action_fingerprints"][action] = Value::Null;
        fixture.reject("missing prone fingerprint");
    }
    for invalid in ["ABCDEF".repeat(10), "A".repeat(64), "g".repeat(64)] {
        let mut fixture = PairFixture::new();
        fixture.receipt["candidate_sha256"] = json!(invalid);
        fixture.reject("invalid prone fingerprint");
    }
}

#[test]
fn pair_requires_native_clock_rest_and_common_motion_removal() {
    for (key, value, message) in [
        ("schema", json!("unknown"), "unsupported prone pair receipt"),
        ("clip_name", json!("wrong"), "clip mismatch"),
        (
            "common_motion_removal",
            Value::Null,
            "co-motion removal is missing",
        ),
        ("native_fps", json!([30, 1]), "clock/rest mismatch"),
        (
            "native_crop",
            json!([18, 87]),
            "native crop/mapping mismatch",
        ),
        (
            "candidate_frame_offset",
            json!(-16),
            "native crop/mapping mismatch",
        ),
        (
            "candidate_frame_range",
            json!([1, 70]),
            "clock/rest mismatch",
        ),
        ("canonical_rest_frame", json!(2), "clock/rest mismatch"),
    ] {
        let mut fixture = PairFixture::new();
        fixture.receipt[key] = value;
        fixture.reject(message);
    }
}

#[test]
fn sample_clock_rejects_missing_rows_retiming_or_non_native_duration() {
    for (key, value, message) in [
        ("schema", json!("unknown"), "unsupported prone camera clock"),
        ("sample_hz", json!(240), "unsupported prone camera clock"),
        ("fps", json!(30), "unsupported prone camera clock"),
        (
            "duration_key_span_seconds",
            json!(69. / 60.),
            "68/60 key span",
        ),
    ] {
        let mut fixture = PairFixture::new();
        fixture.camera[key] = value;
        fixture.reject(message);
    }
    let mut fixture = PairFixture::new();
    fixture.camera["rows"].as_array_mut().unwrap().pop();
    fixture.reject("all 545 samples");
    for key in ["candidate_frame", "time_seconds"] {
        let mut fixture = PairFixture::new();
        fixture.camera["rows"][200][key] = json!(0.);
        fixture.reject("missing or retimed");
    }
}

#[test]
fn camera_owns_height_and_requires_explicit_overshoot_contract() {
    for (key, value) in [
        ("mode", json!("additive_stance_height")),
        ("allow_impact_overshoot", json!(false)),
        ("source_endpoint_descent_m", json!(1.30)),
        ("runtime_target_prone_eye_height_m", json!(0.30)),
    ] {
        let mut fixture = PairFixture::new();
        fixture.camera["height_contract"][key] = value;
        fixture.reject("unsupported prone height ownership");
    }
}

#[test]
fn explicit_source_axes_and_a_valid_source_export_fingerprint_are_required() {
    for key in ["units", "camera_local_axes"] {
        let mut fixture = PairFixture::new();
        fixture.camera[key] = Value::Null;
        fixture.reject("unsupported prone camera axes");
    }
    let mut fixture = PairFixture::new();
    fixture.receipt["source_fbx_sha256"] = Value::Null;
    fixture.reject("missing prone fingerprint");
    fixture.receipt["source_fbx_sha256"] = json!("invalid");
    fixture.reject("invalid prone fingerprint");
}

#[test]
fn paired_metadata_is_bounded_before_deserialization() {
    let fixture = PairFixture::new();
    let (camera, receipt) = fixture.encoded();
    assert!(ProneCameraTrack::from_pair(
        &fixture.asset,
        &vec![b' '; 2_000_001],
        &receipt,
        RIG_ACTION
    )
    .unwrap_err()
    .contains("metadata exceeds bounds"));
    assert!(
        ProneCameraTrack::from_pair(&fixture.asset, &camera, &vec![b' '; 32_769], RIG_ACTION)
            .unwrap_err()
            .contains("metadata exceeds bounds")
    );
}

#[test]
fn matrices_must_be_finite_affine_rigid_and_right_handed() {
    for matrix_key in ["camera_world", "common_world_delta"] {
        for (row, col, value, expected) in [
            (0, 0, json!(1e100), "non-finite prone matrix"),
            (3, 0, json!(0.1), "non-affine prone matrix"),
            (0, 0, json!(2.), "rigid and right-handed"),
            (1, 2, Value::Null, "non-finite or missing prone number"),
        ] {
            let mut fixture = PairFixture::new();
            fixture.camera["rows"][272][matrix_key][row][col] = value;
            fixture.reject(expected);
        }
        let mut fixture = PairFixture::new();
        fixture.camera["rows"][272][matrix_key] = matrix_json(Mat4::from_scale(vec3(-1., 1., 1.)));
        fixture.reject("rigid and right-handed");
    }
    let mut fixture = PairFixture::new();
    fixture.camera["initial_camera_world"][0][0] = json!(1e100);
    fixture.reject("non-finite prone matrix");
}

#[test]
fn common_motion_and_normalized_depth_must_match_evaluated_camera() {
    let mut fixture = PairFixture::new();
    fixture.camera["rows"][272]["common_world_delta"][0][3] = json!(25.);
    fixture.reject("common motion differs");
    let mut fixture = PairFixture::new();
    fixture.camera["rows"][272]["normalized_depth_fraction"] = json!(0.5);
    fixture.reject("normalized height differs");
    for invalid_depth in [-0.1, 1.2] {
        let mut fixture = PairFixture::new();
        replace_row_pose(
            &mut fixture.camera["rows"][272],
            invalid_depth,
            orientation_at(35.),
        );
        fixture.reject("normalized height differs");
    }
}

#[test]
fn protected_entry_and_endpoint_have_identity_orientation_and_exact_depth() {
    for index in [0, 40, 80, 544] {
        let mut fixture = PairFixture::new();
        let frame = 1. + index as f64 / 8.;
        replace_row_pose(
            &mut fixture.camera["rows"][index],
            depth_at(frame),
            Quat::from_rotation_x(0.1),
        );
        fixture.reject("protected prone camera orientation changed");
    }
    for index in [0, 40, 80] {
        let mut fixture = PairFixture::new();
        replace_row_pose(&mut fixture.camera["rows"][index], 0.1, Quat::IDENTITY);
        fixture.reject("protected prone entry height changed");
    }
    let mut fixture = PairFixture::new();
    replace_row_pose(&mut fixture.camera["rows"][544], 0.99, Quat::IDENTITY);
    fixture.reject("endpoint height mismatch");
}

#[test]
fn native_sampling_preserves_protected_entry_impact_overshoot_and_frame_69_hold() {
    let track = track();
    for height in [0.83, 1.016, 1.524] {
        for frame in [1., 1.125, 5., 11.] {
            let sample = track.sample((frame - 1.) / 60., height);
            close(sample.frame, frame, 1e-10);
            close(sample.eye_height as f64, height as f64, 1e-6);
            assert!(sample.orientation.angle_between(Quat::IDENTITY) < 0.0002);
        }
        let impact = track.sample(34. / 60., height);
        let expected = height + (65. / 63.) * (PRONE_EYE_HEIGHT - height);
        close(impact.eye_height as f64, expected as f64, 1e-6);
        assert!(
            impact.eye_height < PRONE_EYE_HEIGHT,
            "impact overshoot must not be clamped"
        );
        for time in [ENTRY_SECONDS, ENTRY_SECONDS + 0.5, 1_000.] {
            let held = track.sample(time, height);
            assert_eq!(held.seconds, ENTRY_SECONDS);
            assert_eq!(held.frame, 69.);
            close(held.eye_height as f64, PRONE_EYE_HEIGHT as f64, 1e-7);
            assert_eq!(held.orientation, Quat::IDENTITY);
        }
    }
}

#[test]
fn fractional_sampling_interpolates_the_native_480_hz_data() {
    let track = track();
    let entry_height = 0.91;
    for row in [81, 137, 271, 273, 503, 543] {
        let a = track.sample(row as f64 / 480., entry_height);
        let b = track.sample((row + 1) as f64 / 480., entry_height);
        let halfway = track.sample((row as f64 + 0.5) / 480., entry_height);
        close(
            halfway.eye_height as f64,
            ((a.eye_height + b.eye_height) * 0.5) as f64,
            1e-6,
        );
        assert!(
            halfway
                .orientation
                .angle_between(a.orientation.slerp(b.orientation, 0.5))
                < 0.0007
        );
    }
    for time in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -10.] {
        let sample = track.sample(time, entry_height);
        assert_eq!(sample.seconds, 0.);
        assert_eq!(sample.eye_height, entry_height);
        assert_eq!(sample.orientation, Quat::IDENTITY);
    }
}

#[test]
fn cosmetic_camera_axes_use_camera_local_rotation_without_mutating_gameplay_aim() {
    let mut sim = configured();
    sim.player.yaw = 0.63;
    sim.player.pitch = -0.17;
    let gameplay_direction = sim.player.direction();
    let gameplay_up = sim.player.camera_up(12.);
    let sample = track().sample(34. / 60., 1.016);
    let (forward, up) = camera_axes(gameplay_direction, gameplay_up, Some(sample));
    assert!(forward.distance(gameplay_direction) > 0.01);
    assert!(up.distance(gameplay_up) > 0.01);
    close(forward.length() as f64, 1., 1e-6);
    close(up.length() as f64, 1., 1e-6);
    close(forward.dot(up) as f64, 0., 1e-6);
    assert_eq!(sim.player.direction(), gameplay_direction);
    assert_eq!(sim.player.camera_up(12.), gameplay_up);
    assert_eq!(
        camera_axes(gameplay_direction, gameplay_up, None),
        (gameplay_direction, gameplay_up)
    );
    let local_pitch = ProneSample {
        orientation: Quat::from_rotation_x(0.2),
        ..sample
    };
    let (forward, _) = camera_axes(-Vec3::Z, Vec3::Y, Some(local_pitch));
    assert!(forward.y > 0., "positive local pitch should look upward");
}

#[test]
fn standing_request_first_crouches_and_starts_only_on_accepted_prone_transition() {
    let mut sim = configured();
    tick(&mut sim, prone());
    assert!(sim.player.crouched && !sim.player.prone);
    assert!(sim.prone_sample().is_none());
    let mut accepted = false;
    for _ in 0..40 {
        let before = sim.player.eye_height;
        tick(&mut sim, prone());
        if sim.player.prone {
            let sample = sim.prone_sample().unwrap();
            assert_eq!(sample.frame, 1.);
            assert_eq!(sample.seconds, 0.);
            assert_eq!(sample.eye_height, before);
            accepted = true;
            break;
        }
        assert!(sim.prone_sample().is_none());
    }
    assert!(accepted);
}

#[test]
fn accepted_entry_freezes_actual_pre_ease_height_instead_of_a_stance_constant() {
    let mut sim = configured();
    ticks(&mut sim, crouch(), 30);
    sim.player.eye_height = 0.83;
    tick(&mut sim, prone());
    assert_eq!(sim.prone_sample().unwrap().eye_height, 0.83);
    assert_eq!(sim.player.eye_height, 0.83);
    ticks(&mut sim, prone(), 20); // f11, protected source interval.
    close(sim.player.eye_height as f64, 0.83, 1e-6);
    ticks(&mut sim, prone(), 48); // f35 at native time.
    let expected = 0.83 + (65. / 63.) * (PRONE_EYE_HEIGHT - 0.83);
    close(sim.player.eye_height as f64, expected as f64, 1e-6);
}

#[test]
fn accepted_entry_absorbs_visible_landing_kick_once_without_a_second_height_track() {
    let mut sim = configured();
    ticks(&mut sim, crouch(), 30);
    sim.player.landing_kick = 0.06;
    let visible_height = sim.player.eye().y - sim.player.position.y;
    tick(&mut sim, prone());
    close(
        sim.player.eye().y as f64 - sim.player.position.y as f64,
        visible_height as f64,
        1e-6,
    );
    assert_eq!(sim.player.landing_kick, 0.);
    ticks(&mut sim, prone(), 20);
    close(
        sim.player.eye().y as f64 - sim.player.position.y as f64,
        visible_height as f64,
        1e-6,
    );
}

#[test]
fn simulation_commits_one_native_clock_and_holds_the_endpoint_without_restarting() {
    let mut sim = configured();
    let height = enter(&mut sim);
    for tick_index in 1..=260 {
        tick(&mut sim, prone());
        let sample = sim.prone_sample().unwrap();
        let seconds = (tick_index as f64 * FIXED_DT as f64).min(ENTRY_SECONDS);
        let expected = track().sample(seconds, height);
        close(sample.seconds, seconds, 1e-10);
        close(sample.frame, expected.frame, 1e-8);
        close(sample.eye_height as f64, expected.eye_height as f64, 1e-6);
        assert_eq!(sim.player.eye_height, sample.eye_height);
    }
    assert_eq!(sim.prone_sample().unwrap().frame, 69.);
    assert_eq!(sim.player.height(), PRONE_HEIGHT);
}

#[test]
fn viewmodel_can_sample_the_same_committed_seconds_without_an_independent_clock() {
    let animation = AnimationSet::decode(&PairFixture::new().asset).unwrap();
    let mut sim = configured();
    enter(&mut sim);
    for _ in 0..200 {
        let camera = sim.prone_sample().unwrap();
        let pose = animation
            .sample_clamped(RIG_ACTION, camera.seconds as f32)
            .unwrap();
        close(pose.sample_time as f64, camera.seconds, 1e-7);
        close(
            pose.bone_locals[0].translation.x as f64,
            camera.seconds,
            1e-7,
        );
        tick(&mut sim, prone());
    }
}

#[test]
fn render_observation_pause_and_zero_tick_frames_never_advance_authored_time() {
    let mut sim = mid_entry();
    let before = sample_signature(sim.prone_sample());
    let height = sim.player.eye_height;
    let time = sim.time;
    let mut clock = FixedClock::default();
    for _ in 0..100 {
        assert_eq!(clock.advance(0.).unwrap(), 0);
        let _ = camera_axes(sim.player.direction(), Vec3::Y, sim.prone_sample());
        assert_eq!(sample_signature(sim.prone_sample()), before);
    }
    clock.advance(0.003).unwrap();
    clock.clear(); // App pause discards residual render-frame time.
    assert_eq!(clock.advance(0.).unwrap(), 0);
    assert_eq!(sim.player.eye_height, height);
    assert_eq!(sim.time, time);
    tick(&mut sim, prone());
    close(
        sim.prone_sample().unwrap().seconds,
        before.unwrap().0 + FIXED_DT as f64,
        1e-10,
    );
}

#[test]
fn fixed_clock_render_partitions_produce_identical_camera_samples() {
    let mut baseline = None;
    for fps in [30, 60, 75, 100, 120, 144, 240] {
        let mut sim = configured();
        let mut clock = FixedClock::default();
        let mut committed_ticks = 0;
        for _ in 0..fps {
            for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                tick(&mut sim, prone());
                committed_ticks += 1;
            }
            // Arbitrary presentation observers cannot change the committed sample.
            let _ = camera_axes(sim.player.direction(), Vec3::Y, sim.prone_sample());
        }
        assert_eq!(committed_ticks, 120);
        let result = (
            sample_signature(sim.prone_sample()),
            sim.player.position,
            sim.player.eye_height,
        );
        if let Some(expected) = baseline {
            assert_eq!(result, expected, "{fps} FPS");
        } else {
            baseline = Some(result);
        }
    }
}

#[test]
fn exit_returns_through_generic_stance_easing_from_the_current_visible_height() {
    let mut sim = mid_entry();
    let before = sim.player.eye_height;
    tick(&mut sim, crouch());
    assert!(!sim.player.prone && sim.player.crouched);
    assert!(sim.prone_sample().is_none());
    assert_eq!(sim.player.eye_from, before);
    let progress = FIXED_DT / 0.4;
    let blend = progress * progress * (3. - 2. * progress);
    close(
        sim.player.eye_height as f64,
        (before + (1.016 - before) * blend) as f64,
        1e-6,
    );
    ticks(&mut sim, crouch(), 60);
    close(sim.player.eye_height as f64, 1.016, 1e-6);
    tick(&mut sim, prone());
    assert_eq!(sim.prone_sample().unwrap().frame, 1.);
}

#[test]
fn reload_and_ads_cancel_without_a_height_snap_or_restart_while_still_prone() {
    for reload in [false, true] {
        let mut sim = mid_entry();
        sim.player.ammo = 12;
        let before = sim.player.eye_height;
        let input = Input {
            reload,
            ads: !reload,
            ..prone()
        };
        tick(&mut sim, input);
        assert!(sim.prone_sample().is_none());
        assert!(sim.player.prone);
        assert!(
            (sim.player.eye_height - before).abs() < 0.02,
            "{} snapped from {before} to {}",
            if reload { "reload" } else { "ADS" },
            sim.player.eye_height
        );
        ticks(&mut sim, input, 60);
        assert!(sim.prone_sample().is_none());
        close(sim.player.eye_height as f64, PRONE_EYE_HEIGHT as f64, 1e-6);
        ticks(&mut sim, prone(), 10);
        assert!(
            sim.prone_sample().is_none(),
            "ending interruption must not restart an existing stance"
        );
    }
}

#[test]
fn rejected_authored_entries_during_ads_reload_or_stance_lock_have_no_clock() {
    for reason in 0..3 {
        let mut sim = configured();
        ticks(&mut sim, crouch(), 30);
        let mut input = prone();
        match reason {
            0 => input.ads = true,
            1 => {
                sim.player.ammo = 10;
                input.reload = true;
            }
            _ => sim.player.stance_lock_until = sim.time + 1.,
        }
        tick(&mut sim, input);
        assert!(sim.prone_sample().is_none(), "rejection {reason}");
    }
}

#[test]
fn becoming_airborne_cancels_and_landing_does_not_restart_the_existing_stance() {
    let mut sim = mid_entry();
    sim.player.position.y = 1.;
    sim.player.grounded = false;
    sim.player.previous_grounded = false;
    tick(&mut sim, prone());
    assert!(sim.prone_sample().is_none());
    ticks(&mut sim, prone(), 120);
    assert!(sim.player.grounded);
    assert!(sim.prone_sample().is_none());
}

#[test]
fn traversal_cancels_the_prone_camera_owner() {
    let mut donor = flat();
    let sprint = Input {
        movement: vec2(0., 1.),
        sprint: true,
        ..Input::default()
    };
    ticks(&mut donor, sprint, 60);
    tick(
        &mut donor,
        Input {
            crouch: true,
            ..sprint
        },
    );
    assert!(matches!(donor.player.action, Action::Slide(_)));
    let mut sim = mid_entry();
    // Copy a genuine accepted traversal state via public gameplay state. This
    // isolates precedence even though ordinary input cannot slide while prone.
    sim.player.action = donor.player.action;
    tick(&mut sim, prone());
    assert!(sim.prone_sample().is_none());
}

#[test]
fn death_and_reset_cancel_and_reset_preserves_the_configured_pair() {
    let mut sim = mid_entry();
    sim.damage_player(100.);
    tick(&mut sim, prone());
    assert!(sim.player.dead());
    assert!(sim.prone_sample().is_none());
    sim.reset();
    assert_eq!(sim.time, 0.);
    assert!(!sim.player.dead());
    assert!(sim.prone_sample().is_none());
    enter(&mut sim);
    ticks(&mut sim, prone(), 50);
    sim.reset();
    assert!(sim.prone_sample().is_none());
    enter(&mut sim);
    assert_eq!(sim.prone_sample().unwrap().frame, 1.);
}

#[test]
fn removing_a_pair_cancels_without_restarting_or_snapping_the_visible_height() {
    let mut sim = mid_entry();
    let before = sim.player.eye_height;
    sim.set_prone_camera_track(None);
    assert!(sim.prone_sample().is_none());
    assert_eq!(sim.player.eye_height, before);
    tick(&mut sim, prone());
    assert!((sim.player.eye_height - before).abs() < 0.02);
    ticks(&mut sim, prone(), 60);
    close(sim.player.eye_height as f64, PRONE_EYE_HEIGHT as f64, 1e-6);
    sim.set_prone_camera_track(Some(track()));
    tick(&mut sim, prone());
    assert!(
        sim.prone_sample().is_none(),
        "installation must wait for a new accepted entry"
    );
}

#[test]
fn no_pair_retains_existing_generic_stance_timing_and_gameplay_state() {
    let mut sim = flat();
    let mut explicitly_disabled = flat();
    explicitly_disabled.set_prone_camera_track(None);
    for input in [crouch(), prone(), crouch(), Input::default()] {
        for _ in 0..65 {
            tick(&mut sim, input);
            tick(&mut explicitly_disabled, input);
            assert!(sim.prone_sample().is_none());
            assert!(explicitly_disabled.prone_sample().is_none());
            assert_eq!(sim.player.eye_height, explicitly_disabled.player.eye_height);
            assert_eq!(sim.player.position, explicitly_disabled.player.position);
            assert_eq!(
                sim.player.direction(),
                explicitly_disabled.player.direction()
            );
            assert_eq!(sim.player.height(), explicitly_disabled.player.height());
        }
        let expected = if input.prone {
            PRONE_EYE_HEIGHT
        } else if input.crouch {
            1.016
        } else {
            1.524
        };
        close(sim.player.eye_height as f64, expected as f64, 1e-6);
    }
}

#[test]
fn authored_camera_rotation_leaves_gameplay_aim_capsule_and_shot_direction_unchanged() {
    let mut authored = configured();
    let mut generic = flat();
    for input in [crouch(), prone()] {
        for _ in 0..70 {
            tick(&mut authored, input);
            tick(&mut generic, input);
            assert_eq!(authored.player.direction(), generic.player.direction());
            assert_eq!(authored.player.height(), generic.player.height());
            assert_eq!(authored.player.position, generic.player.position);
            assert_eq!(authored.player.velocity, generic.player.velocity);
            assert_eq!(
                authored.spread_degrees(&Settings::default()),
                generic.spread_degrees(&Settings::default())
            );
        }
    }
    assert!(
        authored
            .prone_sample()
            .unwrap()
            .orientation
            .angle_between(Quat::IDENTITY)
            > 0.01
    );
    let fire = Input {
        fire: true,
        ..prone()
    };
    tick(&mut authored, fire);
    tick(&mut generic, fire);
    assert_eq!(authored.events.len(), 1);
    assert_eq!(authored.events[0].direction, generic.events[0].direction);
    assert_eq!(authored.player.ammo, generic.player.ammo);
}

fn base_manifest() -> String {
    include_str!("../assets/animations.cfg")
        .lines()
        .filter(|line| !line.starts_with("prone_entry."))
        .collect::<Vec<_>>()
        .join("\n")
}

fn configured_manifest() -> String {
    format!("{}\nprone_entry.policy=paired_r6_wip\nprone_entry.asset=prone/asset.vra\nprone_entry.clip={}\nprone_entry.camera=prone/camera.json\nprone_entry.receipt=prone/pair.json\n", base_manifest(), RIG_ACTION)
}

#[test]
fn manifest_omission_keeps_pair_disabled_and_complete_opt_in_is_relative() {
    assert!(
        AnimationManifest::parse(&base_manifest(), Path::new("bundle/assets"))
            .unwrap()
            .prone_entry
            .is_none()
    );
    let manifest =
        AnimationManifest::parse(&configured_manifest(), Path::new("bundle/assets")).unwrap();
    let pair = manifest.prone_entry.unwrap();
    assert_eq!(pair.asset, Path::new("bundle/assets/prone/asset.vra"));
    assert_eq!(pair.camera, Path::new("bundle/assets/prone/camera.json"));
    assert_eq!(pair.receipt, Path::new("bundle/assets/prone/pair.json"));
    assert_eq!(pair.clip, RIG_ACTION);
}

#[test]
fn manifest_partial_pairs_and_wrong_policy_fail_closed() {
    for missing in ["policy", "asset", "clip", "camera", "receipt"] {
        let key = format!("prone_entry.{missing}=");
        let text = configured_manifest()
            .lines()
            .filter(|line| !line.starts_with(&key))
            .collect::<Vec<_>>()
            .join("\n");
        assert!(
            AnimationManifest::parse(&text, Path::new("assets")).is_err(),
            "missing {missing}"
        );
    }
    for text in [
        format!(
            "{}\nprone_entry.camera=prone/camera.json\n",
            base_manifest()
        ),
        configured_manifest().replace("paired_r6_wip", "camera_only"),
        format!(
            "{}\nprone_entry.camera=duplicate.json\n",
            configured_manifest()
        ),
    ] {
        assert!(AnimationManifest::parse(&text, Path::new("assets")).is_err());
    }
}

#[test]
fn manifest_pair_paths_reject_traversal_absolute_paths_and_platform_prefixes() {
    for key in ["asset", "camera", "receipt"] {
        for path in [
            "../outside",
            "/absolute",
            "C:\\outside",
            "https://example.invalid/file",
            "prone/../outside",
        ] {
            let text = configured_manifest()
                .lines()
                .map(|line| {
                    if line.starts_with(&format!("prone_entry.{key}=")) {
                        format!("prone_entry.{key}={path}")
                    } else {
                        line.to_owned()
                    }
                })
                .collect::<Vec<_>>()
                .join("\n");
            assert!(
                AnimationManifest::parse(&text, Path::new("assets")).is_err(),
                "{key}: {path}"
            );
        }
    }
}
