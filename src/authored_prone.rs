//! Opt-in paired prone entry. The simulation commits one clock for camera and weapon.
//! Numerical validity is not artistic approval. No authored assets are enabled here.
use glam::{Mat3, Mat4, Quat, Vec3, Vec4};
use serde_json::Value;
use std::{io::Read, path::Path};

pub const PRONE_EYE_HEIGHT: f32 = 0.2794;
pub const ENTRY_SECONDS: f64 = 68. / 60.;
pub const RIG_ACTION: &str = "prone_crawl_enter_r6";
pub const CAMERA_ACTION: &str = "prone_crawl_enter_camera_r6";
pub const R15_RIG_ACTION: &str = "aella_prone_crawl_enter_r15_roll_v1";
pub const R15_CAMERA_ACTION: &str = "aella_prone_crawl_enter_camera_r9_viewray_v3";
pub const R15_SOURCE_SHA: &str = "cbed3051bb8c4bbdb78f72a49a7a51bd585db33636ddc5312dde38b05a2a86c4";
pub const R15_RIG_FINGERPRINT: &str =
    "93ffbed2bd91d33bb2d6e1788ce3c3d95f915c228b8ce7f3c17af05b265c9640";
pub const R15_CAMERA_FINGERPRINT: &str =
    "6872ef8f4301690dfd340ec9479f4a533fba743f1dc23b6a3691cd85c9e08844";
/// Hash-only evidence for one reviewed source recipe and its exact full-motion
/// witness. Regenerated BLEND serialization is never labelled as the original.
pub const R15_EQUIVALENCE_CONTRACT: &str =
    include_str!("../tools/prone_r15_equivalence_contract.json");
pub const DEFAULT_RETURN_SECONDS: f64 = 0.20;
const MAX_R15_CAMERA_BYTES: usize = 16 * 1024 * 1024;
pub const REMOVAL_POLICY: &str =
    "inverse(C(t)*inverse(C0))*evaluated_global_before_blender_to_gltf";

#[derive(Clone, Copy, Debug)]
struct CameraKey {
    depth: f32,
    orientation: Quat,
}

#[derive(Clone, Debug)]
pub struct ProneCameraTrack {
    keys: Vec<CameraKey>,
    sample_hz: f64,
    binding_identity: Value,
}

/// Immutable presentation values committed by Simulation, never render time.
#[derive(Clone, Copy, Debug)]
pub struct ProneSample {
    pub seconds: f64,
    pub frame: f64,
    pub eye_height: f32,
    /// Camera-local rotation: +X right, +Y up, -Z forward.
    pub orientation: Quat,
}

/// One committed outgoing clock for the camera, weapon and procedural layers.
#[derive(Clone, Copy, Debug)]
pub struct ProneReturn {
    pub sample: ProneSample,
    pub began: f64,
    pub duration: f64,
}
impl ProneReturn {
    pub fn weight(self, time: f64) -> f32 {
        let t = ((time - self.began) / self.duration).clamp(0., 1.);
        (t * t * (3. - 2. * t)) as f32
    }
}

fn number(value: &Value) -> Result<f64, String> {
    value
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or("non-finite or missing prone number".into())
}

fn check(condition: bool, message: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}

fn digest(value: &Value) -> Result<&str, String> {
    let text = value.as_str().ok_or("missing prone fingerprint")?;
    check(
        text.len() == 64
            && text
                .bytes()
                .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase()),
        "invalid prone fingerprint",
    )?;
    Ok(text)
}

fn validate_r15_equivalence_descriptor(proof: &Value, candidate: &Value) -> Result<(), String> {
    let contract: Value = serde_json::from_str(R15_EQUIVALENCE_CONTRACT)
        .map_err(|_| "invalid compiled r15 equivalence contract")?;
    let contract = contract
        .as_object()
        .ok_or("invalid compiled r15 equivalence contract")?;
    let fields = proof
        .as_object()
        .ok_or("missing r15 source equivalence descriptor")?;
    let dynamic = [
        "generated_source_sha256",
        "source_equivalence_sha256",
        "regenerated_witness_sha256",
        "replay_receipt_sha256",
    ];
    check(
        fields.len() == contract.len() + dynamic.len(),
        "unsupported r15 source equivalence descriptor fields",
    )?;
    for (key, expected) in contract {
        check(
            fields.get(key) == Some(expected),
            &format!("r15 source equivalence contract mismatch: {key}"),
        )?;
    }
    for key in dynamic {
        digest(&proof[key])?;
    }
    let candidate = digest(candidate)?;
    check(
        candidate != R15_SOURCE_SHA && candidate != contract["base_sha256"].as_str().unwrap_or(""),
        "regenerated source identity must be distinct from original and base",
    )?;
    check(
        digest(&proof["generated_source_sha256"])? == candidate,
        "r15 source equivalence generated source mismatch",
    )?;
    check(
        proof["regenerated_witness_sha256"] != proof["approved_witness_sha256"],
        "r15 source equivalence reuses the original witness",
    )
}

fn matrix(value: &Value) -> Result<Mat4, String> {
    let rows = value.as_array().ok_or("missing prone matrix")?;
    check(rows.len() == 4, "prone matrix requires four rows")?;
    let mut columns = [0.; 16];
    for (r, row) in rows.iter().enumerate() {
        let row = row.as_array().ok_or("invalid prone matrix row")?;
        check(row.len() == 4, "prone matrix requires four columns")?;
        for (c, value) in row.iter().enumerate() {
            columns[c * 4 + r] = number(value)? as f32;
        }
    }
    let m = Mat4::from_cols_array(&columns);
    check(m.is_finite(), "non-finite prone matrix")?;
    check(
        (m.row(3) - Vec4::W).abs().max_element() < 0.00002,
        "non-affine prone matrix",
    )?;
    let r = Mat3::from_mat4(m);
    check(
        (r.transpose() * r - Mat3::IDENTITY)
            .to_cols_array()
            .iter()
            .all(|v| v.abs() < 0.00002)
            && (r.determinant() - 1.).abs() < 0.00002,
        "prone matrix must be rigid and right-handed",
    )?;
    Ok(m)
}

impl ProneCameraTrack {
    /// Both artifacts and the import receipt are mandatory. The receipt pins actual
    /// VRA bytes, exact camera bytes, candidate and both source Action fingerprints.
    pub fn load(asset: &Path, camera: &Path, receipt: &Path, clip: &str) -> Result<Self, String> {
        let read = |path: &Path, limit: usize| {
            let file = std::fs::File::open(path)
                .map_err(|e| format!("prone pair {}: {e}", path.display()))?;
            let mut bytes = Vec::new();
            file.take(limit as u64 + 1)
                .read_to_end(&mut bytes)
                .map_err(|e| e.to_string())?;
            check(bytes.len() <= limit, "prone pair exceeds file bound")?;
            Ok::<_, String>(bytes)
        };
        Self::from_pair(
            &read(asset, crate::viewmodel_animation::MAX_FILE)?,
            &read(
                camera,
                if clip == R15_RIG_ACTION {
                    MAX_R15_CAMERA_BYTES
                } else {
                    2_000_000
                },
            )?,
            &read(receipt, 32_768)?,
            clip,
        )
    }

    pub fn from_pair(
        asset: &[u8],
        camera: &[u8],
        receipt: &[u8],
        clip: &str,
    ) -> Result<Self, String> {
        let r15 = clip == R15_RIG_ACTION;
        check(
            camera.len() <= if r15 { MAX_R15_CAMERA_BYTES } else { 2_000_000 }
                && receipt.len() <= 32_768,
            "prone pair metadata exceeds bounds",
        )?;
        let sidecar: Value = serde_json::from_slice(camera).map_err(|e| e.to_string())?;
        let receipt: Value = serde_json::from_slice(receipt).map_err(|e| e.to_string())?;
        let regenerated = r15 && receipt["schema"] == "rust-duty-prone-camera-pair/v3";
        check(
            regenerated
                || receipt["schema"]
                    == if r15 {
                        "rust-duty-prone-camera-pair/v2"
                    } else {
                        "rust-duty-prone-camera-pair/v1"
                    },
            "unsupported prone pair receipt",
        )?;
        check(
            digest(&receipt["asset_vra_sha256"])? == rust_duty_launcher::bytes_hash(asset),
            "prone VRA fingerprint mismatch",
        )?;
        check(
            digest(&receipt["camera_sidecar_sha256"])? == rust_duty_launcher::bytes_hash(camera),
            "prone camera fingerprint mismatch",
        )?;
        check(
            digest(&receipt["candidate_sha256"])? == digest(&sidecar["candidate_sha256"])?,
            "prone candidate fingerprint mismatch",
        )?;
        for action in if r15 {
            [R15_RIG_ACTION, R15_CAMERA_ACTION]
        } else {
            [RIG_ACTION, CAMERA_ACTION]
        } {
            check(
                digest(&receipt["action_fingerprints"][action])?
                    == digest(&sidecar["action_fingerprints"][action])?,
                "prone Action fingerprint mismatch",
            )?;
        }
        if r15 {
            check(
                digest(&sidecar["action_fingerprints"][R15_RIG_ACTION])? == R15_RIG_FINGERPRINT
                    && digest(&sidecar["action_fingerprints"][R15_CAMERA_ACTION])?
                        == R15_CAMERA_FINGERPRINT,
                "r15 requires the exact approved source and paired Actions",
            )?;
            if regenerated {
                validate_r15_equivalence_descriptor(
                    &sidecar["source_equivalence"],
                    &sidecar["candidate_sha256"],
                )?;
                check(
                    receipt["source_equivalence"] == sidecar["source_equivalence"],
                    "r15 receipt/sidecar source equivalence mismatch",
                )?;
            } else {
                check(
                    digest(&sidecar["candidate_sha256"])? == R15_SOURCE_SHA
                        && sidecar.get("source_equivalence").is_none()
                        && receipt.get("source_equivalence").is_none(),
                    "r15 requires the exact approved source and paired Actions",
                )?;
            }
            check(
                sidecar["action_fingerprints"]
                    .as_object()
                    .is_some_and(|v| v.len() == 2)
                    && receipt["action_fingerprints"]
                        .as_object()
                        .is_some_and(|v| v.len() == 2),
                "r15 requires exactly the two paired Actions",
            )?;
            check(
                receipt["camera_sample_hz"] == 3840
                    && receipt["source_rig_action"] == R15_RIG_ACTION
                    && receipt["source_camera_action"] == R15_CAMERA_ACTION,
                "r15 pair Action/clock identity mismatch",
            )?;
        }
        check(
            (clip == RIG_ACTION || r15) && receipt["clip_name"] == clip,
            "prone clip mismatch",
        )?;
        check(
            receipt["common_motion_removal"] == REMOVAL_POLICY,
            "prone co-motion removal is missing",
        )?;
        check(
            receipt["native_fps"] == serde_json::json!([60, 1])
                && receipt["candidate_frame_range"] == serde_json::json!([1, 69])
                && receipt["canonical_rest_frame"] == 1,
            "prone pair clock/rest mismatch",
        )?;
        digest(&receipt["source_fbx_sha256"])?;
        let crop = receipt["native_crop"]
            .as_array()
            .ok_or("missing prone native crop")?;
        check(crop.len() == 2, "invalid prone native crop")?;
        let start = crop[0].as_i64().ok_or("invalid prone crop start")?;
        let end = crop[1].as_i64().ok_or("invalid prone crop end")?;
        let offset = receipt["candidate_frame_offset"]
            .as_i64()
            .ok_or("missing prone frame mapping")?;
        check(
            start >= 0
                && start.checked_add(offset) == Some(1)
                && end.checked_add(offset) == Some(69),
            "prone native crop/mapping mismatch",
        )?;
        if r15 {
            check(
                start == 0
                    && end == 68
                    && offset == 1
                    && number(&receipt["imported_frame_offset"])? == 1.,
                "r15 requires native crop 0..68 and imported/source offset 1",
            )?;
        }
        let mut track = Self::parse_camera(&sidecar, r15, regenerated)?;
        // Cache only identities measured/validated by this successful complete load.
        track.binding_identity = serde_json::json!({
            "schema": "rust-duty-prone-loaded-binding/v1",
            "clip_name": clip,
            "candidate_sha256": receipt["candidate_sha256"],
            "source_fbx_sha256": receipt["source_fbx_sha256"],
            "asset_vra_sha256": rust_duty_launcher::bytes_hash(asset),
            "camera_sidecar_sha256": rust_duty_launcher::bytes_hash(camera),
            "action_fingerprints": receipt["action_fingerprints"],
            "source_rig_action": if r15 { R15_RIG_ACTION } else { RIG_ACTION },
            "source_camera_action": if r15 { R15_CAMERA_ACTION } else { CAMERA_ACTION },
            "camera_sample_hz": track.sample_hz as u32,
            "sidecar_schema": sidecar["schema"],
            "receipt_schema": receipt["schema"],
            "common_motion_removal": receipt["common_motion_removal"],
            "native_crop": receipt["native_crop"],
            "candidate_frame_offset": receipt["candidate_frame_offset"],
        });
        if regenerated {
            // Preserve the validated actual/original identity and all proof pins
            // in telemetry. Do not re-read an unvalidated report at render time.
            track.binding_identity["source_equivalence"] = sidecar["source_equivalence"].clone();
        }
        Ok(track)
    }
    pub fn binding_identity(&self) -> Value {
        self.binding_identity.clone()
    }

    fn parse_camera(source: &Value, r15: bool, regenerated: bool) -> Result<Self, String> {
        let subdivisions = if r15 { 64 } else { 8 };
        let sample_hz = 60 * subdivisions;
        let last = 68 * subdivisions;
        check(
            source["schema"]
                == if regenerated {
                    "prone-entry-r15-camera-motion/v2"
                } else if r15 {
                    "prone-entry-r15-camera-motion/v1"
                } else {
                    "prone-entry-r6-camera-motion/v1"
                }
                && source["sample_hz"] == sample_hz
                && source["fps"] == 60,
            "unsupported prone camera clock",
        )?;
        check(
            source["units"] == "metres and radians; Blender world +Z up"
                && source["camera_local_axes"] == "+X right, +Y up, -Z forward",
            "unsupported prone camera axes",
        )?;
        check(
            (number(&source["duration_key_span_seconds"])? - ENTRY_SECONDS).abs() < 1e-8,
            "prone duration must preserve the 68/60 key span",
        )?;
        check(
            source["height_contract"]["mode"] == "replace_stance_height_during_clip"
                && source["height_contract"]["allow_impact_overshoot"] == true
                && (number(&source["height_contract"]["source_endpoint_descent_m"])? - 1.26).abs()
                    < 1e-8
                && (number(&source["height_contract"]["runtime_target_prone_eye_height_m"])?
                    - PRONE_EYE_HEIGHT as f64)
                    .abs()
                    < 1e-7,
            "unsupported prone height ownership",
        )?;
        let initial = matrix(&source["initial_camera_world"])?;
        let initial_rotation = Quat::from_mat3(&Mat3::from_mat4(initial)).normalize();
        let rows = source["rows"]
            .as_array()
            .ok_or("missing prone camera samples")?;
        check(
            rows.len() == last + 1,
            if r15 {
                "prone camera needs all 4353 samples"
            } else {
                "prone camera needs all 545 samples"
            },
        )?;
        let mut keys = Vec::with_capacity(rows.len());
        for (i, row) in rows.iter().enumerate() {
            let frame = 1. + i as f64 / subdivisions as f64;
            check(
                (number(&row["candidate_frame"])? - frame).abs() < 1e-8
                    && (number(&row["time_seconds"])? - i as f64 / sample_hz as f64).abs() < 1e-8,
                "prone sample clock is missing or retimed",
            )?;
            let camera = matrix(&row["camera_world"])?;
            let delta = matrix(&row["common_world_delta"])?;
            check(
                (camera * initial.inverse() - delta)
                    .to_cols_array()
                    .iter()
                    .all(|v| v.abs() < 0.00002),
                "prone common motion differs from evaluated camera",
            )?;
            let depth = number(&row["normalized_depth_fraction"])? as f32;
            check(
                (0. ..=1.1).contains(&depth)
                    && (depth - (initial.w_axis.z - camera.w_axis.z) / 1.26).abs() < 0.00002,
                "prone normalized height differs from camera",
            )?;
            let orientation = (initial_rotation.inverse()
                * Quat::from_mat3(&Mat3::from_mat4(camera)))
            .normalize();
            if frame <= 11. || i == last {
                check(
                    orientation.angle_between(Quat::IDENTITY) < 0.0002,
                    "protected prone camera orientation changed",
                )?;
            }
            if frame <= 11. {
                check(
                    depth.abs() < 0.00002,
                    "protected prone entry height changed",
                )?;
            }
            keys.push(CameraKey { depth, orientation });
        }
        check(
            (keys[last].depth - 1.).abs() < 0.00002,
            "prone endpoint height mismatch",
        )?;
        // Eliminate tiny source float residue at the exact continuous endpoints.
        keys[0] = CameraKey {
            depth: 0.,
            orientation: Quat::IDENTITY,
        };
        keys[last] = CameraKey {
            depth: 1.,
            orientation: Quat::IDENTITY,
        };
        Ok(Self {
            keys,
            sample_hz: sample_hz as f64,
            binding_identity: Value::Null,
        })
    }

    pub fn sample(&self, seconds: f64, entry_eye_height: f32) -> ProneSample {
        let seconds = if seconds.is_finite() {
            seconds.clamp(0., ENTRY_SECONDS)
        } else {
            0.
        };
        let position = seconds * self.sample_hz;
        let last = self.keys.len() - 1;
        let lower = (position.floor() as usize).min(last);
        let upper = (lower + 1).min(last);
        let weight = (position - lower as f64) as f32;
        let a = self.keys[lower];
        let b = self.keys[upper];
        let depth = a.depth + (b.depth - a.depth) * weight;
        ProneSample {
            seconds,
            frame: 1. + 60. * seconds,
            eye_height: entry_eye_height + depth * (PRONE_EYE_HEIGHT - entry_eye_height),
            orientation: a.orientation.slerp(b.orientation, weight).normalize(),
        }
    }
}

/// Apply only cosmetic camera orientation. Gameplay aim/collision never calls this.
pub fn camera_axes(forward: Vec3, up: Vec3, sample: Option<ProneSample>) -> (Vec3, Vec3) {
    let Some(sample) = sample else {
        return (forward, up);
    };
    let right = forward.cross(up).normalize_or_zero();
    let up = right.cross(forward).normalize_or_zero();
    let basis = Mat3::from_cols(right, up, -forward);
    (
        (basis * (sample.orientation * -Vec3::Z)).normalize(),
        (basis * (sample.orientation * Vec3::Y)).normalize(),
    )
}

/// Fade the live procedural root back without adding a second authored motion.
pub fn procedural_root(base: Vec3, live: Mat4, weight: f32) -> Mat4 {
    if weight <= 0. {
        return Mat4::from_translation(base);
    }
    if weight >= 1. {
        return live;
    }
    let (_, rotation, translation) = live.to_scale_rotation_translation();
    Mat4::from_rotation_translation(
        Quat::IDENTITY.slerp(rotation, weight).normalize(),
        base.lerp(translation, weight),
    )
}
