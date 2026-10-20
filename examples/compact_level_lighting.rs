//! Loss-bounded topology reduction of an already computed lighting bake.
fn main() -> Result<(), String> {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
    let only = std::env::args().nth(1).unwrap_or_default();
    for name in ["range", "cedar_junction"] {
        if !only.is_empty() && only != name {
            continue;
        }
        let dir = root.join("assets/levels").join(name);
        let mut chunks = vector_range::city_level::decode_meshes(
            &std::fs::read(dir.join("lighting.bin")).map_err(|e| e.to_string())?,
        )?;
        let before: usize = chunks.iter().map(|c| c.mesh.indices.len() / 3).sum();
        for c in &mut chunks {
            vector_range::lighting_mesh::simplify(&mut c.mesh);
        }
        let after: usize = chunks.iter().map(|c| c.mesh.indices.len() / 3).sum();
        let vertices: usize = chunks.iter().map(|c| c.mesh.vertices.len()).sum();
        if chunks.iter().any(|c| c.instance.is_some()) {
            let geometry: Vec<_> = chunks
                .into_iter()
                .map(vector_range::city_level::CityGeometry::from_chunk)
                .collect();
            vector_range::city_level::write_geometry(&dir.join("lighting.bin"), &geometry)?;
        } else {
            let meshes: Vec<_> = chunks.into_iter().map(|c| c.mesh).collect();
            vector_range::static_lighting::write_meshes(&dir.join("lighting.bin"), &meshes)?;
        }
        let path = dir.join("lighting.json");
        let mut info: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        info["vertices"] = vertices.into();
        info["triangles"] = after.into();
        info["lighting_sample_error_bound_rgba8"] = 2.into();
        info["topology_optimization"] =
            "coplanar subdivision collapse; no vertex displacement".into();
        std::fs::write(path, serde_json::to_vec_pretty(&info).unwrap())
            .map_err(|e| e.to_string())?;
        eprintln!("{name}: {before} -> {after} triangles");
    }
    Ok(())
}
