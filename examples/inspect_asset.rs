//! Headless decoder check, including embedded-build inspection.
use vector_range::{asset::WeaponAsset, EMBEDDED_WEAPON};
fn main() {
    let asset = if let Some(path) = std::env::args().nth(1) {
        WeaponAsset::load(path).expect("asset rejected")
    } else {
        WeaponAsset::decode(EMBEDDED_WEAPON.expect("no embedded asset"))
            .expect("embedded asset rejected")
    };
    println!(
        "{} parts, {} vertices, {} triangles",
        asset.meshes.len(),
        asset.meshes.iter().map(|m| m.vertices.len()).sum::<usize>(),
        asset
            .meshes
            .iter()
            .map(|m| m.indices.len() / 3)
            .sum::<usize>()
    );
}
