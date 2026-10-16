//! Hash-bound native-time low-vault presentation, explicitly opt-in.
//! The current integration is a LOW mantle onto a block, not a vault-over solver.
//! Metadata/decoder validity does not certify source preservation or artistic approval.
use crate::viewmodel_animation::{AnimationSet, MAX_FILE};
use serde_json::Value;
use std::{io::Read, path::Path};

pub const FIRST_FRAME: u32 = 1;
pub const LAST_FRAME: u32 = 64;
pub const FPS: u32 = 60;
pub const KEY_SPAN_SECONDS: f64 = 63. / 60.;
pub const POLICY: &str = "low_mantle_native_wip";
const MAX_RECEIPT: usize = 32_768;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LowVaultBinding {
    clip: String,
    asset_sha256: String,
    receipt_sha256: String,
    candidate_sha256: String,
    subdivisions: usize,
    return_seconds_bits: u64,
    reload_actor_basis: bool,
    anchor_actor: String,
}

/// Read-only values produced by the simulation's accepted traversal, never render delta.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct LowVaultSample {
    pub seconds: f64,
    pub source_frame: f64,
    pub reference_frame: f64,
}

pub fn valid_digest(text: &str) -> bool {
    text.len() == 64
        && text
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
}
fn require(ok: bool, message: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn digest<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value[key]
        .as_str()
        .filter(|s| valid_digest(s))
        .ok_or_else(|| format!("invalid low-vault {key}"))
}
fn bounded(path: &Path, limit: usize) -> Result<Vec<u8>, String> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .map_err(|e| format!("low-vault {}: {e}", path.display()))?
        .take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    require(bytes.len() <= limit, "low-vault file exceeds bound")?;
    Ok(bytes)
}
impl LowVaultBinding {
    /// The receipt hash is an explicit manifest pin, not a hash learned from the receipt.
    pub fn load(
        asset: &Path,
        receipt: &Path,
        receipt_sha256: &str,
        clip: &str,
    ) -> Result<Self, String> {
        Self::from_bytes(
            &bounded(asset, MAX_FILE)?,
            &bounded(receipt, MAX_RECEIPT)?,
            receipt_sha256,
            clip,
        )
    }
    /// Hash and decode the exact same VRA bytes, then verify the exact companion
    /// bytes passed to the renderer. No path reread can change the selected pose.
    pub fn load_with_companions(
        asset: &Path,
        receipt: &Path,
        receipt_sha256: &str,
        clip: &str,
    ) -> Result<
        (
            Self,
            AnimationSet,
            crate::skinned_asset::SkinnedAsset,
            crate::asset::WeaponAsset,
        ),
        String,
    > {
        let bytes = bounded(asset, MAX_FILE)?;
        let binding = Self::from_bytes(
            &bytes,
            &bounded(receipt, MAX_RECEIPT)?,
            receipt_sha256,
            clip,
        )?;
        let animation = AnimationSet::decode(&bytes).map_err(|e| e.to_string())?;
        let skin_bytes = bounded(&asset.with_extension("vrs"), MAX_FILE)?;
        let mesh_bytes = bounded(&asset.with_extension("vrm"), MAX_FILE)?;
        let skin =
            crate::skinned_asset::SkinnedAsset::decode(&skin_bytes).map_err(|e| e.to_string())?;
        let mesh = crate::asset::WeaponAsset::decode(&mesh_bytes).map_err(|e| e.to_string())?;
        animation
            .validate_companions(&skin_bytes, &mesh_bytes, &skin.bones, mesh.meshes.len())
            .map_err(|e| e.to_string())?;
        Ok((binding, animation, skin, mesh))
    }
    pub fn from_bytes(
        asset: &[u8],
        receipt: &[u8],
        expected_receipt: &str,
        clip: &str,
    ) -> Result<Self, String> {
        require(
            asset.len() <= MAX_FILE && receipt.len() <= MAX_RECEIPT,
            "low-vault inputs exceed bounds",
        )?;
        require(
            valid_digest(expected_receipt)
                && rust_duty_launcher::bytes_hash(receipt) == expected_receipt,
            "low-vault receipt fingerprint mismatch",
        )?;
        let value: Value = serde_json::from_slice(receipt).map_err(|e| e.to_string())?;
        require(
            value["schema"] == "rust-duty-low-vault-runtime/v1",
            "unsupported low-vault receipt",
        )?;
        require(
            value["presentation_policy"] == POLICY,
            "unsupported low-vault gameplay policy",
        )?;
        require(
            !clip.is_empty() && clip.len() <= 128 && value["clip_name"] == clip,
            "low-vault clip mismatch",
        )?;
        let action = value["source_action"]
            .as_str()
            .ok_or("missing low-vault source Action")?;
        require(
            !action.is_empty() && action.len() <= 128,
            "invalid low-vault source Action",
        )?;
        require(
            value["export_take"]
                .as_str()
                .is_some_and(|take| !take.is_empty() && take.len() <= 256),
            "missing low-vault export take metadata",
        )?;
        let candidate = digest(&value, "candidate_sha256")?;
        digest(&value, "source_action_fingerprint")?;
        digest(&value, "source_fbx_sha256")?;
        let asset_hash = digest(&value, "asset_vra_sha256")?;
        require(
            asset_hash == rust_duty_launcher::bytes_hash(asset),
            "low-vault VRA fingerprint mismatch",
        )?;
        require(
            value["candidate_frame_range"] == serde_json::json!([FIRST_FRAME, LAST_FRAME])
                && value["reference_frame_range_half_open"] == serde_json::json!([7284, 7348])
                && value["native_fps"] == serde_json::json!([FPS, 1])
                && value["native_crop"] == serde_json::json!([0, 63])
                && value["imported_frame_offset"] == 1,
            "low-vault source/native clock mismatch",
        )?;
        let subdivisions = value["subdivisions"]
            .as_u64()
            .ok_or("missing low-vault subdivisions")?;
        require(
            matches!(subdivisions, 1 | 2 | 4 | 8),
            "unsupported low-vault subdivisions",
        )?;
        let return_seconds = value["return_seconds"]
            .as_f64()
            .ok_or("missing low-vault return duration")?;
        require(
            return_seconds.is_finite() && (0.05..=1.).contains(&return_seconds),
            "invalid low-vault return duration",
        )?;
        let reload_actor_basis = match value["actor_basis"].as_str() {
            Some("canonical") => false,
            Some("reload_mesh_local") => true,
            _ => return Err("unsupported low-vault actor basis".into()),
        };
        let anchor_actor = value["anchor_actor"]
            .as_str()
            .filter(|s| !s.is_empty() && s.len() <= 128)
            .ok_or("invalid low-vault return anchor")?;
        let binding = Self {
            clip: clip.into(),
            asset_sha256: asset_hash.into(),
            receipt_sha256: expected_receipt.into(),
            candidate_sha256: candidate.into(),
            subdivisions: subdivisions as usize,
            return_seconds_bits: return_seconds.to_bits(),
            reload_actor_basis,
            anchor_actor: anchor_actor.into(),
        };
        binding.validate_animation(&AnimationSet::decode(asset).map_err(|e| e.to_string())?)?;
        Ok(binding)
    }
    /// No 0.60-second retime, endpoint repetition or loop can masquerade as the native clip.
    pub fn validate_animation(&self, set: &AnimationSet) -> Result<(), String> {
        let clip = set
            .clips()
            .iter()
            .find(|c| c.name == self.clip)
            .ok_or("missing low-vault clip")?;
        require(
            !clip.looping && clip.frame_count() == 63 * self.subdivisions + 1,
            "low-vault requires the complete non-looping native sample grid",
        )?;
        require(
            clip.times().iter().enumerate().all(|(i, &t)| {
                (f64::from(t) - i as f64 / (FPS as usize * self.subdivisions) as f64).abs() < 1e-6
            }),
            "low-vault animation was retimed or has missing samples",
        )
    }
    pub fn return_seconds(&self) -> f64 {
        f64::from_bits(self.return_seconds_bits)
    }
    pub fn uses_reload_actor_basis(&self) -> bool {
        self.reload_actor_basis
    }
    pub fn anchor_actor(&self) -> &str {
        &self.anchor_actor
    }
    pub fn clip(&self) -> &str {
        &self.clip
    }
    pub fn candidate_sha256(&self) -> &str {
        &self.candidate_sha256
    }
    /// Maps already committed elapsed seconds. It never advances or changes gameplay.
    pub fn sample(&self, elapsed: f32) -> Result<LowVaultSample, String> {
        require(
            elapsed.is_finite() && elapsed >= 0. && f64::from(elapsed) <= KEY_SPAN_SECONDS + 1e-6,
            "invalid committed low-vault time",
        )?;
        let seconds = if (f64::from(elapsed) - KEY_SPAN_SECONDS).abs() < 1e-6 {
            KEY_SPAN_SECONDS
        } else {
            f64::from(elapsed)
        };
        Ok(LowVaultSample {
            seconds,
            source_frame: 1. + seconds * 60.,
            reference_frame: 7284. + seconds * 60.,
        })
    }
}
