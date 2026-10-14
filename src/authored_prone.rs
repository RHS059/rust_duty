//! Opt-in paired prone entry. The simulation commits one clock for camera and weapon.
//! Numerical validity is not artistic approval. No authored assets are enabled here.
use glam::{Mat3, Mat4, Quat, Vec3, Vec4};
use serde_json::Value;
use std::{io::Read, path::Path};

pub const PRONE_EYE_HEIGHT: f32 = 0.2794;
pub const ENTRY_SECONDS: f64 = 68. / 60.;
pub const RIG_ACTION: &str = "prone_crawl_enter_r6";
pub const CAMERA_ACTION: &str = "prone_crawl_enter_camera_r6";
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
            &read(camera, 2_000_000)?,
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
        check(
            camera.len() <= 2_000_000 && receipt.len() <= 32_768,
            "prone pair metadata exceeds bounds",
        )?;
        let sidecar: Value = serde_json::from_slice(camera).map_err(|e| e.to_string())?;
        let receipt: Value = serde_json::from_slice(receipt).map_err(|e| e.to_string())?;
        check(
            receipt["schema"] == "rust-duty-prone-camera-pair/v1",
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
        for action in [RIG_ACTION, CAMERA_ACTION] {
            check(
                digest(&receipt["action_fingerprints"][action])?
                    == digest(&sidecar["action_fingerprints"][action])?,
                "prone Action fingerprint mismatch",
            )?;
        }
        check(
            clip == RIG_ACTION && receipt["clip_name"] == clip,
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
        Self::parse_camera(&sidecar)
    }

    fn parse_camera(source: &Value) -> Result<Self, String> {
        check(
            source["schema"] == "prone-entry-r6-camera-motion/v1"
                && source["sample_hz"] == 480
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
        check(rows.len() == 545, "prone camera needs all 545 samples")?;
        let mut keys = Vec::with_capacity(rows.len());
        for (i, row) in rows.iter().enumerate() {
            let frame = 1. + i as f64 / 8.;
            check(
                (number(&row["candidate_frame"])? - frame).abs() < 1e-8
                    && (number(&row["time_seconds"])? - i as f64 / 480.).abs() < 1e-8,
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
            if frame <= 11. || i == 544 {
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
            (keys[544].depth - 1.).abs() < 0.00002,
            "prone endpoint height mismatch",
        )?;
        // Eliminate tiny source float residue at the exact continuous endpoints.
        keys[0] = CameraKey {
            depth: 0.,
            orientation: Quat::IDENTITY,
        };
        keys[544] = CameraKey {
            depth: 1.,
            orientation: Quat::IDENTITY,
        };
        Ok(Self { keys })
    }

    pub fn sample(&self, seconds: f64, entry_eye_height: f32) -> ProneSample {
        let seconds = if seconds.is_finite() {
            seconds.clamp(0., ENTRY_SECONDS)
        } else {
            0.
        };
        let position = seconds * 480.;
        let lower = (position.floor() as usize).min(544);
        let upper = (lower + 1).min(544);
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
