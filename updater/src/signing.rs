//! Release-owner tooling only. The launcher never creates or reads signing keys.
//! Production key generation is intentionally not exercised by automated tests.
use crate::{invalid, manifest::Manifest, Result, MAX_MANIFEST};
use ed25519_dalek::{Signer, SigningKey};
use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    path::Path,
};
use zeroize::Zeroizing;
const KEY_PREFIX: &str = "rust-duty-ed25519-seed-v1:";

fn private_location(path: &Path) -> Result<()> {
    if !path.is_absolute() {
        return Err(invalid(
            "private key path must be absolute and outside every repository",
        ));
    }
    crate::reject_symlink(path)?;
    let parent = path
        .parent()
        .ok_or_else(|| invalid("private key needs a protected parent directory"))?;
    if !parent.is_dir() {
        return Err(invalid(
            "create a protected local key directory before generating a key",
        ));
    }
    for ancestor in parent.ancestors() {
        if ancestor.join(".git").exists() {
            return Err(invalid(
                "refusing to store or read a private signing key inside a repository",
            ));
        }
    }
    Ok(())
}
fn write_new(path: &Path, bytes: &[u8], private: bool) -> Result<()> {
    crate::reject_symlink(path)?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(if private { 0o600 } else { 0o644 });
    }
    #[cfg(not(unix))]
    let _ = private;
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn write_pair(private: &Path, public: &Path, key: &SigningKey) -> Result<()> {
    private_location(private)?;
    if private == public || private.exists() || public.exists() {
        return Err(invalid(
            "key output already exists or paths overlap; no key was replaced",
        ));
    }
    let mut secret = Zeroizing::new(String::from(KEY_PREFIX));
    secret.push_str(&hex::encode(key.to_bytes()));
    secret.push('\n');
    write_new(private, secret.as_bytes(), true)?;
    // If public output fails, keep the private key. `public-key` can safely recreate the public file.
    write_new(
        public,
        format!("{}\n", hex::encode(key.verifying_key().to_bytes())).as_bytes(),
        false,
    )
}
/// Call only from the user's explicitly confirmed local setup command, never from tests/CI.
pub fn generate_local(private: &Path, public: &Path, explicitly_confirmed: bool) -> Result<()> {
    if !explicitly_confirmed {
        return Err(invalid(
            "key creation requires --confirm-create-release-key after owner approval",
        ));
    }
    private_location(private)?;
    if private.exists() || public.exists() {
        return Err(invalid("existing key material will not be overwritten"));
    }
    let mut seed = Zeroizing::new([0u8; 32]);
    getrandom::getrandom(seed.as_mut())
        .map_err(|_| invalid("operating-system secure randomness unavailable; key not created"))?;
    write_pair(private, public, &SigningKey::from_bytes(&seed))
}
pub fn read_private(reader: impl Read) -> Result<SigningKey> {
    let mut encoded = Zeroizing::new(String::new());
    reader.take(1025).read_to_string(&mut encoded)?;
    if encoded.len() > 1024 {
        return Err(invalid("invalid signing key file format"));
    }
    let raw = encoded
        .trim()
        .strip_prefix(KEY_PREFIX)
        .ok_or_else(|| invalid("invalid signing key file format"))?;
    let mut seed = Zeroizing::new([0u8; 32]);
    hex::decode_to_slice(raw, seed.as_mut())
        .map_err(|_| invalid("invalid signing key file format"))?;
    Ok(SigningKey::from_bytes(&seed))
}
pub fn read_private_file(path: &Path) -> Result<SigningKey> {
    private_location(path)?;
    read_private(fs::File::open(path)?)
}
pub fn public_hex(key: &SigningKey) -> String {
    hex::encode(key.verifying_key().to_bytes())
}
pub fn write_public(key: &SigningKey, output: &Path) -> Result<()> {
    write_new(output, format!("{}\n", public_hex(key)).as_bytes(), false)
}
pub fn sign_manifest(key: &SigningKey, payload: &Path, signature: &Path) -> Result<()> {
    let file = fs::File::open(payload)?;
    if file.metadata()?.len() > MAX_MANIFEST {
        return Err(invalid("manifest is too large to sign"));
    }
    let mut bytes = Vec::new();
    file.take(MAX_MANIFEST + 1).read_to_end(&mut bytes)?;
    let manifest: Manifest = serde_json::from_slice(&bytes)?;
    manifest.validate(&manifest.target)?;
    write_new(signature, &key.sign(&bytes).to_bytes(), false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signature, Verifier};
    #[test]
    fn deterministic_in_memory_fixture_roundtrip_and_signing() {
        // NOT a production key. This fixed test seed is public source code.
        let key = SigningKey::from_bytes(&[59; 32]);
        let root = tempfile::tempdir().unwrap();
        let private = root.path().join("fixture.key");
        let public = root.path().join("fixture.public.hex");
        // This environment may intentionally mark all writable roots as repositories.
        // Keep the public deterministic key fixture in memory; no key-generation/storage path is exercised.
        let fixture = format!("{KEY_PREFIX}{}", hex::encode([59u8; 32]));
        let loaded = read_private(fixture.as_bytes()).unwrap();
        write_new(&private, b"non-key fixture bytes", true).unwrap();
        write_public(&loaded, &public).unwrap();
        assert_eq!(public_hex(&loaded), public_hex(&key));
        assert_eq!(
            fs::read_to_string(&public).unwrap().trim(),
            public_hex(&key)
        );
        let payload = br#"{"schema":1,"repository":"RHS059/rust_duty","version":"1.1.0","sequence":2,"target":"test-target","entrypoint":"game","bundle":{"name":"test.rdb","size":1,"sha256":"0000000000000000000000000000000000000000000000000000000000000000"},"deltas":[]}"#;
        fs::write(root.path().join("payload.json"), payload).unwrap();
        sign_manifest(
            &loaded,
            &root.path().join("payload.json"),
            &root.path().join("signature.bin"),
        )
        .unwrap();
        let signature =
            Signature::from_slice(&fs::read(root.path().join("signature.bin")).unwrap()).unwrap();
        key.verifying_key().verify(payload, &signature).unwrap();
        assert!(write_pair(&private, &public, &key).is_err());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&private).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }
    #[test]
    fn blocks_repository_storage_missing_confirmation_and_malformed_keys() {
        let root = tempfile::tempdir().unwrap();
        fs::create_dir(root.path().join(".git")).unwrap();
        assert!(private_location(&root.path().join("private.key")).is_err());
        assert!(generate_local(
            &root.path().join("private.key"),
            &root.path().join("public.hex"),
            false
        )
        .is_err());
        assert!(read_private(b"not a private key".as_slice()).is_err());
        assert!(!root.path().join("private.key").exists());
    }
}
