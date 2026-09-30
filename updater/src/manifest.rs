use crate::{invalid, Error, Result, MAX_ASSET, MAX_MANIFEST, REPOSITORY};
use ed25519_dalek::{Signature, VerifyingKey};
use semver::Version;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Asset {
    pub name: String,
    pub size: u64,
    pub sha256: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Delta {
    pub base_version: Version,
    pub base_sha256: String,
    pub asset: Asset,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub schema: u32,
    pub repository: String,
    pub version: Version,
    pub sequence: u64,
    pub target: String,
    pub entrypoint: String,
    pub bundle: Asset,
    pub deltas: Vec<Delta>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Envelope {
    pub payload: String,
    pub signature: String,
}
#[derive(Clone)]
pub struct Trust(VerifyingKey);
impl Trust {
    pub fn production() -> Result<Self> {
        let value = option_env!("RUST_DUTY_UPDATE_PUBLIC_KEY").ok_or(Error::Unconfigured)?;
        if value.is_empty() {
            return Err(Error::Unconfigured);
        }
        Self::from_hex(value)
    }
    fn from_hex(value: &str) -> Result<Self> {
        let bytes: [u8; 32] = hex::decode(value)
            .map_err(|_| invalid("invalid pinned public key"))?
            .try_into()
            .map_err(|_| invalid("invalid pinned public key length"))?;
        let key =
            VerifyingKey::from_bytes(&bytes).map_err(|_| invalid("invalid pinned public key"))?;
        if key.is_weak() {
            return Err(invalid("weak pinned public key"));
        }
        Ok(Self(key))
    }
    #[cfg(test)]
    pub(crate) fn fixture(key: &VerifyingKey) -> Self {
        Self(*key)
    }
    pub fn verify(&self, bytes: &[u8], target: &str) -> Result<Manifest> {
        if bytes.len() as u64 > MAX_MANIFEST {
            return Err(invalid("oversized manifest"));
        }
        let envelope: Envelope = serde_json::from_slice(bytes)?;
        let signature =
            hex::decode(&envelope.signature).map_err(|_| invalid("malformed signature"))?;
        let signature =
            Signature::from_slice(&signature).map_err(|_| invalid("malformed signature"))?;
        self.0
            .verify_strict(envelope.payload.as_bytes(), &signature)
            .map_err(|_| invalid("manifest signature verification failed"))?;
        let manifest: Manifest = serde_json::from_str(&envelope.payload)?;
        manifest.validate(target)?;
        Ok(manifest)
    }
}
pub fn valid_hash(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub fn safe_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 150
        && s != "."
        && s != ".."
        && !s.starts_with('.')
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
}
impl Asset {
    pub fn validate(&self) -> Result<()> {
        if !safe_name(&self.name)
            || self.size == 0
            || self.size > MAX_ASSET
            || !valid_hash(&self.sha256)
        {
            return Err(invalid("invalid asset name, size or hash"));
        }
        Ok(())
    }
}
impl Manifest {
    pub fn validate(&self, target: &str) -> Result<()> {
        if self.schema != 1
            || self.repository != REPOSITORY
            || self.target != target
            || self.sequence == 0
        {
            return Err(invalid(
                "wrong manifest schema, repository, target or sequence",
            ));
        }
        if !self.version.pre.is_empty() || !self.version.build.is_empty() {
            return Err(invalid("only stable versions are supported"));
        }
        crate::bundle::safe_path(&self.entrypoint)?;
        self.bundle.validate()?;
        if self.deltas.len() > 32 {
            return Err(invalid("too many deltas"));
        }
        let mut bases = HashSet::new();
        for delta in &self.deltas {
            delta.asset.validate()?;
            if delta.base_version >= self.version
                || !valid_hash(&delta.base_sha256)
                || !bases.insert((delta.base_version.clone(), delta.base_sha256.clone()))
            {
                return Err(invalid("invalid or repeated delta base"));
            }
        }
        Ok(())
    }
}
