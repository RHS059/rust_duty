//! Optional, hash-pinned one-hand HIGH-ONTO presentation. No payload is enabled.
//! Only accepted ordinary high mantles use this clock; low and hang paths do not.
use crate::{asset::WeaponAsset, skinned_asset::SkinnedAsset, viewmodel_animation::AnimationSet};
use serde_json::Value;
use std::{io::Read, path::Path};

pub const POLICY: &str = "high_onto_onehand_v6_native";
pub const ACTION: &str = "aella_mantle_onehand_r6_camera_reconstructed_v6";
pub const SOURCE_SHA256: &str = "b5cae854b1e5e21c44e60a0672dd18c26e7b38acb239f4730b681482bc409d77";
pub const ACTION_FINGERPRINT: &str =
    "c7ca6383364e055afe1d0246f443d33689ce86c56677570ba694a924c983ea01";
pub const GRID_SHA256: &str = "a521b1e779e45f85948d94b8b9aa9f9cad41d935783ba5fcbda34decb6aec08f";
pub const NATIVE_SECONDS: f64 = 95. / 60.;
pub const SUBDIVISIONS: usize = 256;
pub const SAMPLE_HZ: usize = 60 * SUBDIVISIONS;
pub const SAMPLE_COUNT: usize = 95 * SUBDIVISIONS + 1;
pub const ANCHOR: &str = "hk416_weapon";
const MAX_RECEIPT: usize = 32_768;

/// These are release-reviewed, independently established identities, never
/// values learned from an untrusted receipt. Fill only after native verification.
#[derive(Clone, Copy)]
struct RuntimePins<'a> {
    receipt: &'a str,
    fbx: &'a str,
    vra: &'a str,
    vrs: &'a str,
    vrm: &'a str,
    proof: &'a str,
}
const APPROVED_RUNTIME_PINS: Option<RuntimePins<'static>> = None;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HighMantleBinding {
    receipt_sha256: String,
    asset_sha256: String,
    return_seconds_bits: u64,
}

fn require(condition: bool, reason: &str) -> Result<(), String> {
    if condition {
        Ok(())
    } else {
        Err(reason.into())
    }
}
pub fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}
fn bounded(path: &Path, limit: usize) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .map_err(|e| format!("one-hand {}: {e}", path.display()))?
        .take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    require(bytes.len() <= limit, "one-hand file exceeds bound")?;
    Ok(bytes)
}

impl HighMantleBinding {
    /// The exact bytes admitted here are returned to the renderer: no path reread.
    pub fn load_with_companions(
        asset: &Path,
        receipt: &Path,
        expected_receipt: &str,
        clip: &str,
    ) -> Result<(Self, AnimationSet, SkinnedAsset, WeaponAsset), String> {
        let pins = APPROVED_RUNTIME_PINS
            .ok_or("one-hand runtime pins pending native verification; binding remains inactive")?;
        let vra = bounded(asset, crate::viewmodel_animation::MAX_FILE)?;
        let vrs = bounded(&asset.with_extension("vrs"), crate::skinned_asset::MAX_FILE)?;
        let vrm = bounded(&asset.with_extension("vrm"), crate::asset::MAX_FILE)?;
        let receipt = bounded(receipt, MAX_RECEIPT)?;
        Self::admit(&vra, &vrs, &vrm, &receipt, expected_receipt, clip, pins)
    }
    fn admit(
        vra: &[u8],
        vrs: &[u8],
        vrm: &[u8],
        receipt: &[u8],
        expected_receipt: &str,
        clip: &str,
        pins: RuntimePins<'_>,
    ) -> Result<(Self, AnimationSet, SkinnedAsset, WeaponAsset), String> {
        require(
            vra.len() <= crate::viewmodel_animation::MAX_FILE
                && vrs.len() <= crate::skinned_asset::MAX_FILE
                && vrm.len() <= crate::asset::MAX_FILE
                && receipt.len() <= MAX_RECEIPT,
            "one-hand inputs exceed bound",
        )?;
        require(
            [
                pins.receipt,
                pins.fbx,
                pins.vra,
                pins.vrs,
                pins.vrm,
                pins.proof,
            ]
            .into_iter()
            .all(valid_digest),
            "invalid one-hand approved pins",
        )?;
        require(
            expected_receipt == pins.receipt
                && rust_duty_launcher::bytes_hash(receipt) == pins.receipt,
            "one-hand receipt identity mismatch",
        )?;
        let value: Value = serde_json::from_slice(receipt).map_err(|e| e.to_string())?;
        require(
            value["schema"] == "rust-duty-high-onto-onehand/v1"
                && value["presentation_policy"] == POLICY,
            "unsupported one-hand receipt or gameplay policy",
        )?;
        require(
            clip == ACTION
                && value["clip_name"] == ACTION
                && value["source_action"] == ACTION
                && value["export_take"] == ACTION
                && value["candidate_sha256"] == SOURCE_SHA256
                && value["source_action_fingerprint"] == ACTION_FINGERPRINT,
            "one-hand source or Action identity mismatch",
        )?;
        for (field, expected, bytes) in [
            ("asset_vra_sha256", pins.vra, vra),
            ("asset_vrs_sha256", pins.vrs, vrs),
            ("asset_vrm_sha256", pins.vrm, vrm),
        ] {
            require(
                value[field] == expected && rust_duty_launcher::bytes_hash(bytes) == expected,
                "one-hand payload fingerprint mismatch",
            )?;
        }
        require(
            value["source_fbx_sha256"] == pins.fbx
                && value["runtime_source_proof_sha256"] == pins.proof
                && value["verification_grid_sha256"] == GRID_SHA256
                && value["verification_sample_count"] == 4240
                && value["skin_vertex_observations"] == 43392160_u64
                && value["native_processes_complete"] == true,
            "one-hand dense/runtime evidence identity mismatch",
        )?;
        require(
            value["candidate_frame_range"] == serde_json::json!([1, 96])
                && value["reference_frame_range_half_open"] == serde_json::json!([7787, 7883])
                && value["native_fps"] == serde_json::json!([60, 1])
                && value["native_crop"] == serde_json::json!([0, 95])
                && value["imported_frame_offset"] == 1
                && value["subdivisions"] == SUBDIVISIONS
                && value["camera_and_rig_basis"] == "static"
                && value["camera_motion_removal"] == "none",
            "one-hand native/static-camera contract mismatch",
        )?;
        require(
            value["actor_basis"] == "reload_mesh_local" && value["anchor_actor"] == ANCHOR,
            "one-hand actor basis or shared anchor mismatch",
        )?;
        let seconds = value["return_seconds"]
            .as_f64()
            .ok_or("missing one-hand return duration")?;
        require(
            seconds.is_finite() && (0.05..=1.).contains(&seconds),
            "invalid one-hand return duration",
        )?;
        let animation = AnimationSet::decode(vra).map_err(|e| e.to_string())?;
        let skin = SkinnedAsset::decode(vrs).map_err(|e| e.to_string())?;
        let mesh = WeaponAsset::decode(vrm).map_err(|e| e.to_string())?;
        animation
            .validate_companions(vrs, vrm, &skin.bones, mesh.meshes.len())
            .map_err(|e| e.to_string())?;
        let binding = Self {
            receipt_sha256: pins.receipt.into(),
            asset_sha256: pins.vra.into(),
            return_seconds_bits: seconds.to_bits(),
        };
        binding.validate_animation(&animation)?;
        Ok((binding, animation, skin, mesh))
    }
    pub fn validate_animation(&self, animation: &AnimationSet) -> Result<(), String> {
        let clip = animation
            .clips()
            .iter()
            .find(|c| c.name == ACTION)
            .ok_or("missing one-hand clip")?;
        require(
            animation.clips().len() == 1
                && !clip.looping
                && clip.frame_count() == SAMPLE_COUNT
                && clip
                    .times()
                    .iter()
                    .enumerate()
                    .all(|(i, &t)| t.to_bits() == ((i as f64 / SAMPLE_HZ as f64) as f32).to_bits()),
            "one-hand requires the complete native nonlooping dense grid",
        )?;
        require(
            [ANCHOR, "hk416_magazine", "hk416_magazine_outgoing"]
                .into_iter()
                .all(|name| animation.actors().iter().any(|a| a.name == name)),
            "missing one-hand rigid actor",
        )
    }
    pub fn return_seconds(&self) -> f64 {
        f64::from_bits(self.return_seconds_bits)
    }
    pub fn receipt_sha256(&self) -> &str {
        &self.receipt_sha256
    }
    pub fn asset_sha256(&self) -> &str {
        &self.asset_sha256
    }
    #[cfg(test)]
    pub(crate) fn synthetic(seconds: f64) -> Self {
        Self {
            receipt_sha256: "test-only".into(),
            asset_sha256: "test-only".into(),
            return_seconds_bits: seconds.to_bits(),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HighMantleSample {
    pub seconds: f64,
    pub source_frame: f64,
    pub reference_frame: f64,
}
impl HighMantleSample {
    fn at(seconds: f64) -> Self {
        let seconds = seconds.clamp(0., NATIVE_SECONDS);
        Self {
            seconds,
            source_frame: 1. + seconds * 60.,
            reference_frame: 7787. + seconds * 60.,
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HighMantleReturn {
    pub sample: HighMantleSample,
    pub began: f64,
    pub duration: f64,
    /// Completion must retain frame 96 even when no render occurred at that tick.
    pub completed: bool,
}
impl HighMantleReturn {
    pub fn weight(self, committed_time: f64) -> f32 {
        let t = ((committed_time - self.began) / self.duration).clamp(0., 1.);
        (t * t * (3. - 2. * t)) as f32
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HighMantlePresentation {
    pub generation: u64,
    pub sample: HighMantleSample,
    pub outgoing: Option<HighMantleReturn>,
}

/// Simulation-owned state. Getters/rendering cannot advance this clock.
#[derive(Default)]
pub(crate) struct HighMantleController {
    binding: Option<HighMantleBinding>,
    began: Option<f64>,
    generation: u64,
    presentation: Option<HighMantlePresentation>,
    last_committed: Option<f64>,
}
impl HighMantleController {
    pub fn binding(&self) -> Option<&HighMantleBinding> {
        self.binding.as_ref()
    }
    pub fn set_binding(&mut self, binding: Option<HighMantleBinding>) {
        if self.binding != binding {
            self.clear();
            self.binding = binding;
        }
    }
    pub fn clear(&mut self) {
        self.began = None;
        self.presentation = None;
        self.last_committed = None;
    }
    pub fn begin(&mut self, time: f64) {
        self.clear();
        if self.binding.is_none() || !time.is_finite() {
            return;
        }
        self.generation = self.generation.wrapping_add(1);
        self.began = Some(time);
        self.last_committed = Some(time);
        self.presentation = Some(HighMantlePresentation {
            generation: self.generation,
            sample: HighMantleSample::at(0.),
            outgoing: None,
        });
    }
    pub fn elapsed_at(&self, time: f64) -> Option<f64> {
        self.began
            .filter(|_| time.is_finite())
            .map(|start| (time - start).clamp(0., NATIVE_SECONDS))
    }
    pub fn commit(&mut self, time: f64, complete: bool) {
        if !time.is_finite() || self.last_committed.is_some_and(|last| time < last) {
            self.clear();
            return;
        }
        self.last_committed = Some(time);
        if let Some(seconds) = self.elapsed_at(time) {
            if let Some(presentation) = &mut self.presentation {
                presentation.sample =
                    HighMantleSample::at(if complete { NATIVE_SECONDS } else { seconds });
            }
            if complete {
                self.cancel(time, true);
            }
        }
        if self
            .presentation
            .and_then(|p| p.outgoing)
            .is_some_and(|r| r.weight(time) >= 1.)
        {
            self.presentation = None;
        }
    }
    pub fn cancel(&mut self, time: f64, completed: bool) {
        if !time.is_finite() {
            self.clear();
            return;
        }
        if self.began.take().is_none() {
            return;
        }
        if let (Some(binding), Some(p)) = (&self.binding, &mut self.presentation) {
            p.outgoing = Some(HighMantleReturn {
                sample: p.sample,
                began: time,
                duration: binding.return_seconds(),
                completed,
            });
        }
    }
    pub fn presentation(&self) -> Option<HighMantlePresentation> {
        self.presentation
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        settings::Settings,
        sim::{Aabb, Block, Input, MantleKind, Simulation, FIXED_DT},
        skinned_asset::crc32,
    };
    use glam::{vec2, vec3, Mat4};
    use serde_json::json;

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
    fn payload(looping: bool, scale: f32, count: usize) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
        payload_at_hz(looping, scale, count, SAMPLE_HZ)
    }
    fn payload_at_hz(
        looping: bool,
        scale: f32,
        count: usize,
        sample_hz: usize,
    ) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
        let mut skin = Vec::new();
        words(&mut skin, &[1]);
        name(&mut skin, "fixture_hand");
        words(&mut skin, &[u32::MAX]);
        floats(&mut skin, &Mat4::IDENTITY.to_cols_array());
        floats(&mut skin, &Mat4::IDENTITY.to_cols_array());
        words(&mut skin, &[1]);
        mesh(&mut skin, true);
        let vrs = container(b"VRSKIN02", 2, skin);
        let mut rigid = Vec::new();
        words(&mut rigid, &[3]);
        for _ in 0..3 {
            mesh(&mut rigid, false);
        }
        let vrm = container(b"VRMESH01", 1, rigid);
        let mut animation = Vec::new();
        words(&mut animation, &[crc32(&vrs), crc32(&vrm), 1]);
        name(&mut animation, "fixture_hand");
        words(&mut animation, &[u32::MAX, 3]);
        for (i, actor) in [ANCHOR, "hk416_magazine", "hk416_magazine_outgoing"]
            .iter()
            .enumerate()
        {
            name(&mut animation, actor);
            words(&mut animation, &[1, i as u32]);
            floats(&mut animation, &Mat4::IDENTITY.to_cols_array());
        }
        words(&mut animation, &[1]);
        name(&mut animation, ACTION);
        words(&mut animation, &[u32::from(looping), count as u32]);
        for i in 0..count {
            let t = (i as f64 / sample_hz as f64) as f32 * scale;
            floats(&mut animation, &[t]);
            for _ in 0..4 {
                floats(&mut animation, &[t, 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
            }
            animation.extend([1, 1, 0]);
        }
        (container(b"VRANIM01", 1, animation), vrs, vrm)
    }
    fn receipt(vra: &[u8], vrs: &[u8], vrm: &[u8]) -> Value {
        json!({"schema":"rust-duty-high-onto-onehand/v1","presentation_policy":POLICY,
            "clip_name":ACTION,"source_action":ACTION,"export_take":ACTION,"candidate_sha256":SOURCE_SHA256,
            "source_action_fingerprint":ACTION_FINGERPRINT,"source_fbx_sha256":"1".repeat(64),
            "asset_vra_sha256":rust_duty_launcher::bytes_hash(vra),"asset_vrs_sha256":rust_duty_launcher::bytes_hash(vrs),
            "asset_vrm_sha256":rust_duty_launcher::bytes_hash(vrm),"runtime_source_proof_sha256":"2".repeat(64),
            "verification_grid_sha256":GRID_SHA256,"verification_sample_count":4240,"skin_vertex_observations":43392160_u64,
            "native_processes_complete":true,"candidate_frame_range":[1,96],"reference_frame_range_half_open":[7787,7883],
            "native_fps":[60,1],"native_crop":[0,95],"imported_frame_offset":1,"subdivisions":SUBDIVISIONS,
            "camera_and_rig_basis":"static","camera_motion_removal":"none","actor_basis":"reload_mesh_local",
            "anchor_actor":ANCHOR,"return_seconds":0.2})
    }
    fn admit_test(
        vra: &[u8],
        vrs: &[u8],
        vrm: &[u8],
        receipt: &Value,
    ) -> Result<HighMantleBinding, String> {
        let bytes = serde_json::to_vec(receipt).unwrap();
        let hash = rust_duty_launcher::bytes_hash(&bytes);
        HighMantleBinding::admit(
            vra,
            vrs,
            vrm,
            &bytes,
            &hash,
            ACTION,
            RuntimePins {
                receipt: &hash,
                fbx: &"1".repeat(64),
                vra: &rust_duty_launcher::bytes_hash(vra),
                vrs: &rust_duty_launcher::bytes_hash(vrs),
                vrm: &rust_duty_launcher::bytes_hash(vrm),
                proof: &"2".repeat(64),
            },
        )
        .map(|v| v.0)
    }
    #[test]
    fn production_admission_stays_closed_without_actual_pins() {
        assert!(HighMantleBinding::load_with_companions(
            Path::new("missing.vra"),
            Path::new("missing.json"),
            &"0".repeat(64),
            ACTION
        )
        .err()
        .unwrap()
        .contains("pending native verification"));
    }
    #[test]
    fn exact_dense_grid_and_same_bytes_companions_are_required() {
        for (looping, scale, count, passes) in [
            (false, 1., SAMPLE_COUNT, true),
            (true, 1., SAMPLE_COUNT, false),
            (false, 0.85 / NATIVE_SECONDS as f32, SAMPLE_COUNT, false),
            (false, 1., SAMPLE_COUNT - 1, false),
            (false, SUBDIVISIONS as f32, 96, false),
        ] {
            let (a, s, m) = payload(looping, scale, count);
            assert_eq!(admit_test(&a, &s, &m, &receipt(&a, &s, &m)).is_ok(), passes);
        }
        let (a, mut s, m) = payload(false, 1., SAMPLE_COUNT);
        let r = receipt(&a, &s, &m);
        let last = s.len() - 1;
        s[last] ^= 1;
        assert!(admit_test(&a, &s, &m, &r).is_err());
    }
    #[test]
    fn native256_full_grid_and_endpoint_match_exact_float32_rational_times() {
        assert_eq!(SUBDIVISIONS, 256);
        assert_eq!(SAMPLE_HZ, 15_360);
        assert_eq!(SAMPLE_COUNT, 24_321);
        let (a, s, m) = payload(false, 1., SAMPLE_COUNT);
        let binding = admit_test(&a, &s, &m, &receipt(&a, &s, &m)).unwrap();
        assert_eq!(binding.return_seconds(), 0.2);
        let animation = AnimationSet::decode(&a).unwrap();
        let times = animation.clips()[0].times();
        assert_eq!(times.len(), 24_321);
        assert_eq!(times[0].to_bits(), 0f32.to_bits());
        for (i, &time) in times.iter().enumerate() {
            assert_eq!(time.to_bits(), ((i as f64 / 15_360.) as f32).to_bits());
        }
        assert!(times.windows(2).all(|pair| pair[0] < pair[1]));
        assert_eq!(
            times.last().unwrap().to_bits(),
            (NATIVE_SECONDS as f32).to_bits()
        );
        let endpoint = HighMantleSample::at(NATIVE_SECONDS);
        assert_eq!(endpoint.source_frame, 96.);
        assert_eq!(endpoint.reference_frame, 7882.);
    }
    #[test]
    fn native64_payload_and_receipt_cannot_be_relabeled_as_native256() {
        let (a, s, m) = payload_at_hz(false, 1., 95 * 64 + 1, 60 * 64);
        let mut r = receipt(&a, &s, &m);
        assert!(admit_test(&a, &s, &m, &r).is_err());
        r["subdivisions"] = json!(64);
        assert!(admit_test(&a, &s, &m, &r).is_err());
        let (a, s, m) = payload(false, 1., SAMPLE_COUNT);
        let mut r = receipt(&a, &s, &m);
        r["subdivisions"] = json!(64);
        assert!(admit_test(&a, &s, &m, &r).is_err());
    }
    #[test]
    fn native256_count_alone_cannot_admit_a_wrong_timestamp_frequency() {
        for hz in [60 * 64, SAMPLE_HZ - 1, SAMPLE_HZ + 1] {
            let (a, s, m) = payload_at_hz(false, 1., SAMPLE_COUNT, hz);
            assert!(admit_test(&a, &s, &m, &receipt(&a, &s, &m)).is_err());
        }
    }
    #[test]
    fn receipt_cannot_change_source_clock_policy_basis_or_proof() {
        let (a, s, m) = payload(false, 1., SAMPLE_COUNT);
        for (field, value) in [
            ("candidate_sha256", json!("9".repeat(64))),
            ("source_action_fingerprint", json!("9".repeat(64))),
            ("export_take", json!("truncated")),
            ("presentation_policy", json!("low_vault")),
            ("source_fbx_sha256", json!("9".repeat(64))),
            ("runtime_source_proof_sha256", json!("9".repeat(64))),
            ("native_processes_complete", json!(false)),
            ("subdivisions", json!(1)),
            ("native_crop", json!([0, 96])),
            ("actor_basis", json!("canonical")),
            ("camera_motion_removal", json!("prone")),
            ("anchor_actor", json!("wrong")),
            ("return_seconds", json!(0.)),
            ("return_seconds", json!(1.01)),
            ("return_seconds", Value::Null),
        ] {
            let mut r = receipt(&a, &s, &m);
            r[field] = value;
            assert!(admit_test(&a, &s, &m, &r).is_err(), "{field}");
        }
    }
    fn scene(height: f32, enabled: bool) -> Simulation {
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
        if enabled {
            s.set_high_mantle_binding(Some(HighMantleBinding::synthetic(0.2)));
        }
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
    fn dense256_preserves_legacy_low_and_native_high_ticks_and_endpoint() {
        for (height, enabled, ticks, duration) in [
            (0.6, false, 72, 0.6),
            (0.6, true, 72, 0.6),
            (1.8, false, 102, 0.85),
            (1.8, true, 190, NATIVE_SECONDS as f32),
        ] {
            let mut s = scene(height, enabled);
            tick(&mut s, request());
            assert_eq!(s.player.mantle.unwrap().duration(), duration);
            assert_eq!(
                s.player.mantle.unwrap().kind,
                if height < 1.2 {
                    MantleKind::Low
                } else {
                    MantleKind::High
                }
            );
            let mut count = 1;
            while s.player.mantle.is_some() {
                tick(&mut s, Input::default());
                count += 1;
                assert!(count < 250);
            }
            assert_eq!(count, ticks);
            assert_eq!(s.player.position.y, height);
            assert!(s.player.grounded);
            if enabled && height > 1.2 {
                let p = s.high_mantle_presentation().unwrap();
                assert_eq!(p.sample.seconds, NATIVE_SECONDS);
                assert_eq!(p.sample.source_frame, 96.);
                assert_eq!(p.sample.reference_frame, 7882.);
                assert_eq!(p.outgoing.unwrap().duration, 0.2);
                assert_eq!(p.outgoing.unwrap().weight(s.time), 0.);
                tick(&mut s, Input::default());
                assert!(
                    s.high_mantle_presentation()
                        .unwrap()
                        .outgoing
                        .unwrap()
                        .weight(s.time)
                        > 0.
                );
            } else {
                assert!(s.high_mantle_presentation().is_none());
            }
        }
    }
    #[test]
    fn high_pause_cancel_and_repeated_readers_do_not_advance_time() {
        let mut s = scene(1.8, true);
        tick(&mut s, request());
        for _ in 0..30 {
            tick(&mut s, Input::default());
        }
        let source = s.high_mantle_presentation().unwrap().sample;
        let position = s.player.position;
        let time = s.time;
        s.cancel_mantle();
        let frozen = s.high_mantle_presentation();
        s.cancel_mantle();
        for _ in 0..100 {
            assert_eq!(s.high_mantle_presentation(), frozen);
        }
        s.update(request(), &Settings::default(), 0.);
        assert_eq!(s.high_mantle_presentation(), frozen);
        assert_eq!(s.time, time);
        assert_eq!(s.player.position, position);
        let fade = frozen.unwrap().outgoing.unwrap();
        assert_eq!(fade.sample, source);
        assert_eq!(fade.weight(time), 0.);
        assert!(!fade.completed);
        for _ in 0..30 {
            tick(&mut s, Input::default());
        }
        assert!(s.high_mantle_presentation().is_none());
    }
    #[test]
    fn high_binding_replacement_death_and_reset_clear_stale_state() {
        for mode in 0..4 {
            let mut s = scene(1.8, true);
            tick(&mut s, request());
            match mode {
                0 => s.set_high_mantle_binding(None),
                1 => s.set_high_mantle_binding(Some(HighMantleBinding::synthetic(0.3))),
                2 => s.kill(),
                _ => s.reset(),
            }
            assert!(s.high_mantle_presentation().is_none());
            assert!(s.player.mantle.is_none());
        }
        let mut c = HighMantleController::default();
        c.set_binding(Some(HighMantleBinding::synthetic(0.2)));
        c.begin(1.);
        c.commit(1.3, false);
        c.cancel(1.3, false);
        let old = c.presentation().unwrap().generation;
        c.begin(1.4);
        let new = c.presentation().unwrap();
        assert_ne!(old, new.generation);
        assert_eq!(new.sample.source_frame, 1.);
        assert!(new.outgoing.is_none());
        c.commit(1.2, false);
        assert!(c.presentation().is_none());
    }
    #[test]
    fn high_path_obstruction_and_support_loss_use_existing_safe_cancel() {
        for removed in [false, true] {
            let mut s = scene(1.8, true);
            tick(&mut s, request());
            for _ in 0..10 {
                tick(&mut s, Input::default());
            }
            let position = s.player.position;
            if removed {
                s.blocks.pop();
            } else {
                s.blocks.push(Block {
                    bounds: Aabb {
                        min: vec3(-1., 1.8, -1.),
                        max: vec3(1., 3.8, 0.),
                    },
                    kind: 2,
                });
            }
            tick(&mut s, Input::default());
            assert!(s.player.mantle.is_none());
            assert_eq!(s.player.position, position);
            assert!(
                !s.high_mantle_presentation()
                    .unwrap()
                    .outgoing
                    .unwrap()
                    .completed
            );
            assert!(!s
                .blocks
                .iter()
                .any(|b| s.player.bounds_at(s.player.position).overlaps(b.bounds)));
        }
    }
    #[test]
    fn high_lockout_and_reload_credit_are_preserved_through_final_tick() {
        for credited in [false, true] {
            let mut s = scene(1.8, true);
            s.player.ammo = 7;
            tick(
                &mut s,
                Input {
                    reload: true,
                    ..Input::default()
                },
            );
            if credited {
                while !s.player.reload_credited {
                    tick(&mut s, Input::default());
                }
            }
            let ammo = (s.player.ammo, s.player.reserve);
            let held = Input {
                ads: true,
                fire: true,
                reload: true,
                ..request()
            };
            tick(&mut s, held);
            while s.player.mantle.is_some() {
                tick(&mut s, held);
            }
            assert_eq!((s.player.ammo, s.player.reserve), ammo);
            assert_eq!(s.stats.shots, 0);
            assert_eq!(s.player.ads, 0.);
            assert_eq!(s.player.reload_left, 0.);
            tick(&mut s, held);
            assert_eq!(s.stats.shots, 1);
        }
    }
    #[test]
    fn rejected_or_nonfresh_requests_never_create_authored_presentation() {
        for mode in 0..5 {
            let mut s = scene(1.8, true);
            match mode {
                0 => s.player.jump_held = true,
                1 => s.player.grounded = false,
                2 => s.player.position.z = 4.,
                3 => s.blocks[1].bounds.max.y = 2.4,
                _ => s.player.prone = true,
            }
            tick(&mut s, request());
            assert!(s.high_mantle_presentation().is_none());
        }
    }
    #[test]
    fn dense256_binding_and_inactive_path_preserve_ledge_hang_pullup() {
        use crate::{
            action::ActionSlot,
            sim::{Action, RADIUS},
        };
        for enabled in [false, true] {
            let mut s = scene(2.7, enabled);
            s.blocks[1].bounds.max.z = -2.;
            s.player.position.z = -2. + RADIUS + 0.3;
            tick(&mut s, request());
            for _ in 0..180 {
                tick(
                    &mut s,
                    Input {
                        movement: vec2(0., 1.),
                        ..Input::default()
                    },
                );
                if matches!(s.player.action, Action::Hang(_)) {
                    break;
                }
            }
            assert!(matches!(s.player.action, Action::Hang(_)));
            for _ in 0..60 {
                tick(&mut s, Input::default());
            }
            tick(
                &mut s,
                Input {
                    jump: true,
                    ..Input::default()
                },
            );
            let state = s.player.mantle.unwrap();
            assert!(state.from_hang);
            assert_eq!(state.duration(), s.timings.get(ActionSlot::PullUp).duration);
            while s.player.mantle.is_some() {
                assert!(s.high_mantle_presentation().is_none());
                tick(&mut s, Input::default());
            }
            assert_eq!(s.player.position.y, 2.7);
            assert!(s.high_mantle_presentation().is_none());
        }
    }
    #[test]
    fn high_committed_trace_is_identical_across_render_partitions() {
        let mut baseline = None;
        for fps in [30, 60, 144, 240] {
            let mut s = scene(1.8, true);
            let mut clock = crate::clock::FixedClock::default();
            let mut count = 0;
            let mut trace = Vec::new();
            for _ in 0..fps * 2 {
                for _ in 0..clock.advance(1. / fps as f64).unwrap() {
                    tick(
                        &mut s,
                        if count == 0 {
                            request()
                        } else {
                            Input::default()
                        },
                    );
                    trace.push((
                        s.time,
                        s.player.position,
                        s.player.mantle.map(|m| m.progress()),
                        s.high_mantle_presentation(),
                    ));
                    count += 1;
                }
                // Any number of presentation reads has no authority to commit a tick.
                let before = s.high_mantle_presentation();
                assert_eq!(before, s.high_mantle_presentation());
            }
            assert_eq!(count, 240);
            if let Some(expected) = &baseline {
                assert_eq!(&trace, expected, "{fps} FPS");
            } else {
                baseline = Some(trace);
            }
        }
    }
}
