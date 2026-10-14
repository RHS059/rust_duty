//! Bake once in release mode; no renderer or GPU required.
use glam::Vec3;
use vector_range::{
    city_level::decode_meshes_unlit,
    draw::Mesh,
    range_geometry,
    sim::Simulation,
    static_lighting::{subdivide, write_meshes, BakeScene},
};
fn main() -> Result<(), String> {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let only = std::env::args().nth(1).unwrap_or_default();
    for name in ["range", "cedar_junction"] {
        if !only.is_empty() && only != name {
            continue;
        }
        let directory = root.join("assets/levels").join(name);
        std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        let (meshes, lamps): (Vec<Mesh>, Vec<Vec3>) = if name == "range" {
            (
                range_geometry::meshes(&Simulation::new()),
                range_geometry::lamps(),
            )
        } else {
            let bytes = std::fs::read(directory.join("meshes.bin")).map_err(|e| e.to_string())?;
            let doc: serde_json::Value =
                serde_json::from_slice(&std::fs::read(directory.join("level.json")).unwrap())
                    .unwrap();
            let mut lamps = Vec::new();
            for b in doc["buildings"].as_array().unwrap() {
                for room in b["rooms"].as_array().unwrap() {
                    let p = room["center"].as_array().unwrap();
                    lamps.push(Vec3::new(
                        p[0].as_f64().unwrap() as f32,
                        p[1].as_f64().unwrap() as f32 + 2.65,
                        p[2].as_f64().unwrap() as f32,
                    ));
                }
            }
            (
                decode_meshes_unlit(&bytes)?
                    .into_iter()
                    .map(|c| c.mesh)
                    .collect(),
                lamps,
            )
        };
        eprintln!("{name}: building triangle acceleration structure");
        let scene = BakeScene::new(&meshes, lamps);
        let mut output = Vec::new();
        for mesh in &meshes {
            output.extend(subdivide(mesh, if name == "range" { 0.25 } else { 0.65 }));
        }
        drop(meshes);
        for mesh in &mut output {
            vector_range::static_lighting::compact(mesh);
        }
        let vertices: usize = output.iter().map(|m| m.vertices.len()).sum();
        eprintln!(
            "{name}: baking {vertices} vertices in {} chunks",
            output.len()
        );
        let threads = std::thread::available_parallelism()
            .map_or(2, |n| n.get())
            .min(16);
        let batch = output.len().div_ceil(threads);
        std::thread::scope(|scope| {
            for meshes in output.chunks_mut(batch.max(1)) {
                let scene = &scene;
                scope.spawn(move || {
                    for mesh in meshes {
                        scene.bake(mesh);
                        vector_range::static_lighting::compact(mesh);
                    }
                });
            }
        });
        let unlit = vector_range::scene_lighting::SceneLighting {
            ambient: 1.,
            diffuse: 0.,
            ..vector_range::scene_lighting::SceneLighting::range()
        };
        for lamp in &scene.lamps {
            output.push(unlit.cube_mesh(
                *lamp + Vec3::Y * 0.05,
                Vec3::new(0.65, 0.06, 0.65),
                vector_range::draw::Color::new(1., 0.92, 0.76, 1.),
            ));
        }
        let vertices: usize = output.iter().map(|m| m.vertices.len()).sum();
        write_meshes(&directory.join("lighting.bin"), &output)?;
        std::fs::write(directory.join("lighting.json"),serde_json::to_vec_pretty(&serde_json::json!({"schema":"rust-duty-static-lighting/v1","method":"triangle-raytraced vertex irradiance","sun_samples":8,"hemisphere_samples":32,"diffuse_bounces":1,"target_triangle_edge_m":if name=="range"{0.25}else{0.65},"vertical_surface_edge_m":0.25,"vertices":vertices,"chunks":output.len(),"interior_lights":scene.lamps.len(),"sun_direction":[-0.45,0.78,0.43],"tone_map":"ACES fitted curve, sRGB output","limitations":["Static geometry and lights only","No dynamic actor shadows or specular reflections"]})).unwrap()).map_err(|e|e.to_string())?;
        eprintln!("{name}: saved lighting.bin");
    }
    Ok(())
}
