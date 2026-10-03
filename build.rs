//! Only the specifically authorized converted test model is embedded by default.
//! Source files and other licensed assets remain local unless separately authorized.
#[allow(dead_code)]
#[path = "src/asset.rs"]
mod asset;
use std::{env, fs, io::Read, path::PathBuf};
fn main() {
    println!("cargo:rerun-if-env-changed=RUST_DUTY_BUILD_VERSION");
    let version = env::var("RUST_DUTY_BUILD_VERSION")
        .unwrap_or_else(|_| env::var("CARGO_PKG_VERSION").expect("Cargo package version"));
    let parts: Vec<_> = version.split('.').collect();
    assert!(
        parts.len() == 3
            && parts.iter().all(|part| {
                !part.is_empty()
                    && (part.len() == 1 || !part.starts_with('0'))
                    && part.bytes().all(|c| c.is_ascii_digit())
                    && part.parse::<u64>().is_ok()
            }),
        "RUST_DUTY_BUILD_VERSION must be a stable MAJOR.MINOR.PATCH version"
    );
    println!("cargo:rustc-env=RUST_DUTY_BUILD_VERSION={version}");
    println!("cargo:rerun-if-env-changed=VR_WEAPON_ASSET");
    println!("cargo:rerun-if-env-changed=CI");
    println!("cargo:rerun-if-changed=src/asset.rs");
    let out = PathBuf::from(env::var_os("OUT_DIR").expect("Cargo OUT_DIR"));
    println!("cargo:rerun-if-changed=assets/weapons/hk416a5.vrm");
    let override_path = env::var_os("VR_WEAPON_ASSET");
    if let Some(path) = &override_path {
        assert!(
            std::path::Path::new(path).is_absolute(),
            "VR_WEAPON_ASSET must be an absolute local .vrm path"
        );
        assert!(
            env::var_os("CI").is_none(),
            "VR_WEAPON_ASSET is prohibited in CI; build licensed models locally"
        );
    }
    let default_path = PathBuf::from("assets/weapons/hk416a5.vrm");
    let selected = override_path
        .map(PathBuf::from)
        .or_else(|| default_path.exists().then_some(default_path));
    let code = if let Some(path) = selected {
        let mut bytes = Vec::new();
        fs::File::open(&path)
            .expect("Open local asset")
            .take((asset::MAX_FILE + 1) as u64)
            .read_to_end(&mut bytes)
            .expect("Read local asset");
        asset::WeaponAsset::decode(&bytes).expect("Invalid VR_WEAPON_ASSET");
        fs::write(out.join("weapon.vrm"), bytes).expect("Stage local asset");
        println!("cargo:rerun-if-changed={}", path.display());
        "pub static EMBEDDED_WEAPON: Option<&[u8]> = Some(include_bytes!(concat!(env!(\"OUT_DIR\"), \"/weapon.vrm\")));\n"
    } else {
        let _ = fs::remove_file(out.join("weapon.vrm"));
        "pub static EMBEDDED_WEAPON: Option<&[u8]> = None;\n"
    };
    fs::write(out.join("weapon_embed.rs"), code).expect("Write embed configuration");
}
