//! Exact companion-backed loader/draw parity. Diagnostic overview, not gameplay framing.
#![allow(dead_code)]
#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[path = "../src/weapon_model.rs"]
mod weapon_model;

use glam::{Mat4, Quat, Vec3};
use rust_duty_launcher::bytes_hash;
use serde_json::{json, Value};
#[cfg(feature = "wgpu-runtime")]
use std::path::PathBuf;
use std::{collections::HashSet, fs, path::Path};
use vector_range::{
    animation_manifest::AnimationManifest,
    draw::{facade, Color, Command, DrawList, TextureSource, Vertex},
    scene_lighting::SceneLighting,
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
    viewmodel_animation::AnimationSet,
};
const WIDTH: u32 = 960;
const HEIGHT: u32 = 540;
const SCHEMA: &str = "rust-duty-authored-loader-contract/v1";
const BACKGROUND: Color = Color::new(0.03125, 0.0625, 0.09375, 1.);

fn require(ok: bool, message: &str) -> Result<(), String> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn bits(matrix: Mat4) -> [u32; 16] {
    matrix.to_cols_array().map(f32::to_bits)
}
fn vertex_bytes(v: Vertex) -> Result<[u8; 40], String> {
    require(
        v.position.is_finite() && v.uv.is_finite() && v.normal.is_finite(),
        "nonfinite output vertex",
    )?;
    let mut out = [0; 40];
    for (slot, value) in out[..20]
        .as_chunks_mut::<4>()
        .0
        .iter_mut()
        .zip(v.position.to_array().into_iter().chain(v.uv.to_array()))
    {
        *slot = value.to_le_bytes();
    }
    out[20..24].copy_from_slice(&v.color);
    for (slot, value) in out[24..]
        .as_chunks_mut::<4>()
        .0
        .iter_mut()
        .zip(v.normal.to_array())
    {
        *slot = value.to_le_bytes();
    }
    Ok(out)
}
fn commands(list: &DrawList) -> Result<(Vec<Value>, Vec<Vec3>), String> {
    let mut rows = Vec::new();
    let mut points = Vec::new();
    for command in &list.commands {
        let Command::Mesh { mesh, model, blend } = command else {
            require(
                matches!(command, Command::Camera(_)),
                "unexpected loader draw command",
            )?;
            continue;
        };
        require(
            model.is_finite()
                && !mesh.indices.is_empty()
                && mesh.indices.len() <= 4998
                && mesh.indices.len().is_multiple_of(3),
            "invalid loader transform or triangle chunk",
        )?;
        let mut expanded = Vec::with_capacity(mesh.indices.len() * 40);
        for &index in &mesh.indices {
            let vertex = *mesh
                .vertices
                .get(usize::from(index))
                .ok_or("index outside loader mesh")?;
            expanded.extend(vertex_bytes(vertex)?);
            let point = model.transform_point3(vertex.position);
            require(point.is_finite(), "nonfinite world corner")?;
            points.push(point);
        }
        let texture = match &mesh.texture {
            None => Value::Null,
            Some(texture) => {
                let TextureSource::Rgba8(rgba) = &texture.source else {
                    return Err("unexpected target texture".into());
                };
                json!({"width":texture.width,"height":texture.height,
                    "filter":format!("{:?}",texture.sampler.filter),
                    "wrap_x":format!("{:?}",texture.sampler.wrap_x),"wrap_y":format!("{:?}",texture.sampler.wrap_y),
                    "rgba_sha256":bytes_hash(rgba)})
            }
        };
        rows.push(
            json!({"model_bits":bits(*model),"blend":format!("{blend:?}"),"texture":texture,
            "stored_vertices":mesh.vertices.len(),"indices":mesh.indices.len(),
            "expanded_sha256":bytes_hash(&expanded)}),
        );
    }
    require(
        !rows.is_empty() && rows.len() <= 2048 && points.len() <= 4_000_000,
        "unbounded or empty loader draws",
    )?;
    Ok((rows, points))
}
fn key_words(values: impl IntoIterator<Item = f32>) -> Vec<u32> {
    values.into_iter().map(f32::to_bits).collect()
}
fn counts(indices: &[u32], keys: &[Vec<u32>]) -> (usize, usize, usize) {
    let mut old = 0;
    let mut new = 0;
    for chunk in indices.chunks(4998) {
        old += chunk.iter().copied().collect::<HashSet<_>>().len();
        new += chunk
            .iter()
            .map(|&i| &keys[i as usize])
            .collect::<HashSet<_>>()
            .len();
    }
    (old, new, indices.len())
}
fn source_counts(path: &Path) -> Result<Value, String> {
    let (_, skin, rigid) = AnimationSet::load_with_companions(path).map_err(|e| e.to_string())?;
    let skins: Vec<_> = skin
        .meshes
        .iter()
        .map(|m| {
            let keys: Vec<_> = m
                .vertices
                .iter()
                .map(|v| {
                    let mut key = key_words(v.position.into_iter().chain(v.normal).chain(v.uv));
                    key.extend(v.joints.map(u32::from));
                    key.extend(v.weights.map(f32::to_bits));
                    key
                })
                .collect();
            let (old, new, indices) = counts(&m.indices, &keys);
            json!({"old_vertices":old,"deduplicated_vertices":new,"indices":indices})
        })
        .collect();
    let rigids: Vec<_> = rigid
        .meshes
        .iter()
        .map(|m| {
            let keys: Vec<_> = m
                .vertices
                .iter()
                .map(|v| key_words(v.position.into_iter().chain(v.normal).chain(v.uv)))
                .collect();
            let (old, new, indices) = counts(&m.indices, &keys);
            json!({"old_vertices":old,"deduplicated_vertices":new,"indices":indices})
        })
        .collect();
    Ok(json!({"skin":skins,"rigid":rigids}))
}
struct Case {
    name: String,
    list: DrawList,
    metadata: Value,
    commands: Vec<Value>,
}
fn save_case(cases: &mut Vec<Case>, name: String, metadata: Value) -> Result<(), String> {
    let list = facade::take_draw_list()?;
    let (commands, _) = commands(&list)?;
    cases.push(Case {
        name,
        list,
        metadata,
        commands,
    });
    Ok(())
}
fn fixture(manifest_path: &Path) -> Result<(Vec<Case>, Value), String> {
    let manifest = AnimationManifest::load(manifest_path)?;
    let walk = manifest
        .regular_walk
        .as_ref()
        .ok_or("missing original walk")?;
    let ads = manifest.ads.as_ref().ok_or("missing original ADS")?;
    let clips = [
        (
            &manifest.locomotion_asset,
            &manifest.locomotion.ready_clip,
            "ready",
        ),
        (&walk.asset, &walk.clip, "walk"),
        (&ads.asset, &ads.entry_clip, "ads"),
        (&manifest.tactical.asset, &manifest.tactical.clip, "reload"),
    ];
    let mut cases = Vec::new();
    let mut sources = serde_json::Map::new();
    for (path, clip, label) in clips {
        let animation = AnimationSet::load(path).map_err(|e| e.to_string())?;
        let duration = animation
            .clips()
            .iter()
            .find(|c| &c.name == clip)
            .ok_or("missing requested clip")?
            .duration();
        require(
            duration.is_finite() && duration > 0.,
            "clip has no duration",
        )?;
        sources.insert(label.into(), source_counts(path)?);
        let mut model = authored_viewmodel::AuthoredViewmodel::load(
            path.to_str().ok_or("asset path is not Unicode")?,
            clip,
            None,
        )?;
        for (ordinal, fraction) in [0., 0.5, 0.9, 0.].into_iter().enumerate() {
            let time = duration * fraction;
            facade::begin_frame(WIDTH, HEIGHT, 1.)?;
            // Same public draw route and same loaded mutable meshes are reused.
            model.draw(f64::from(time), SceneLighting::range(), Mat4::IDENTITY);
            require(model.error().is_none(), "authored draw failed")?;
            save_case(
                &mut cases,
                format!("{label}-{ordinal}"),
                json!({"route":"load/draw","clip":clip,
                "time_bits":time.to_bits(),"fraction_tenths":([0,5,9,0][ordinal]),"duration_bits":duration.to_bits(),"cant_bits":0}),
            )?;
        }
        // Revisit must be exactly equal even within one source variant.
        let n = cases.len();
        require(
            cases[n - 4].commands == cases[n - 1].commands,
            "return-to-start changed loaded mesh output",
        )?;
    }
    let mut model = authored_viewmodel::AuthoredViewmodel::load_manifest(manifest_path)?;
    require(model.error().is_none(), "manifest route failed to load")?;
    let mut sim = Simulation::new();
    let settings = Settings::default();
    for frame in 0..=24 {
        if frame > 0 {
            let start = sim.time;
            sim.update(Input::default(), &settings, FIXED_DT);
            model.committed_step(start, &sim);
        }
        if [0, 12, 24].contains(&frame) {
            facade::begin_frame(WIDTH, HEIGHT, 1.)?;
            model.draw(sim.time, SceneLighting::range(), Mat4::IDENTITY);
            require(model.error().is_none(), "manifest/controller draw failed")?;
            save_case(
                &mut cases,
                format!("manifest-{frame}"),
                json!({"route":"load_manifest/committed_step/draw",
                "fixed_steps":frame,"simulation_time_bits":sim.time.to_bits(),"warning":model.warning()}),
            )?;
        }
    }
    // Exercise rigid alpha and nonuniform normal transforms on original material data.
    let (_, _, rigid) = AnimationSet::load_with_companions(&manifest.locomotion_asset)
        .map_err(|e| e.to_string())?;
    let part_count = rigid.meshes.len();
    let mut model = weapon_model::WeaponModel::from_asset(rigid);
    let transforms = vec![
        Mat4::from_scale_rotation_translation(
            Vec3::new(1.1, 0.9, 1.),
            Quat::from_rotation_y(0.2),
            Vec3::ZERO
        );
        part_count
    ];
    for (ordinal, alpha) in [0.5, 0.25, 0.5].into_iter().enumerate() {
        facade::begin_frame(WIDTH, HEIGHT, 1.)?;
        model.draw_authored_parts(
            &transforms,
            &vec![true; part_count],
            &vec![alpha; part_count],
            SceneLighting::range(),
        );
        save_case(
            &mut cases,
            format!("rigid-alpha-{ordinal}"),
            json!({"route":"draw_authored_parts","alpha":alpha}),
        )?;
    }
    let n = cases.len();
    require(
        cases[n - 3].commands == cases[n - 1].commands,
        "rigid alpha revisit changed output",
    )?;
    require(cases.len() == 22, "fixture case count changed")?;
    Ok((cases, Value::Object(sources)))
}
fn overview(cases: &[Case]) -> Result<Mat4, String> {
    let mut low = Vec3::splat(f32::INFINITY);
    let mut high = Vec3::splat(f32::NEG_INFINITY);
    for case in cases {
        for point in commands(&case.list)?.1 {
            low = low.min(point);
            high = high.max(point);
        }
    }
    let center = (low + high) * 0.5;
    let radius = (high - low).length() * 0.6;
    require(
        center.is_finite() && radius.is_finite() && radius > 0.001 && radius < 100.,
        "invalid diagnostic bounds",
    )?;
    let view = Mat4::look_at_rh(
        center + Vec3::new(0.6, 0.3, 2.).normalize() * radius * 3.,
        center,
        Vec3::Y,
    );
    Ok(Mat4::orthographic_rh_gl(
        -radius * WIDTH as f32 / HEIGHT as f32,
        radius * WIDTH as f32 / HEIGHT as f32,
        -radius,
        radius,
        0.01,
        radius * 6.,
    ) * view)
}
fn camera_from_json(value: &Value) -> Result<Mat4, String> {
    let values = value["view_projection_bits"]
        .as_array()
        .ok_or("camera bits missing")?;
    require(values.len() == 16, "camera needs16 words")?;
    let mut out = [0.; 16];
    for (slot, value) in out.iter_mut().zip(values) {
        *slot = f32::from_bits(
            u32::try_from(value.as_u64().ok_or("camera word invalid")?)
                .map_err(|e| e.to_string())?,
        );
    }
    let result = Mat4::from_cols_array(&out);
    require(
        result.is_finite() && result.determinant() != 0.,
        "invalid camera",
    )?;
    Ok(result)
}
fn write(path: &Path, value: &Value) -> Result<(), String> {
    fs::write(
        path,
        serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())
}
#[cfg(feature = "wgpu-runtime")]
fn run() -> Result<(), String> {
    use vector_range::{
        draw::{Camera, Renderer},
        render::{BackendSelection, WgpuRenderer},
    };
    let mut args = std::env::args_os().skip(1);
    require(
        args.next().as_deref() == Some(std::ffi::OsStr::new("--manifest")),
        "expected --manifest",
    )?;
    let manifest = PathBuf::from(args.next().ok_or("missing manifest")?);
    require(
        args.next().as_deref() == Some(std::ffi::OsStr::new("--output-dir")),
        "expected --output-dir",
    )?;
    let output = PathBuf::from(args.next().ok_or("missing output directory")?);
    let camera_input = match args.next() {
        Some(flag) if flag == "--camera" => {
            Some(PathBuf::from(args.next().ok_or("missing camera file")?))
        }
        None => None,
        _ => return Err("unexpected argument".into()),
    };
    require(args.next().is_none(), "unexpected trailing argument")?;
    fs::create_dir(&output).map_err(|e| e.to_string())?;
    let (cases, sources) = fixture(&manifest)?;
    let camera = if let Some(path) = &camera_input {
        camera_from_json(
            &serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?,
        )?
    } else {
        overview(&cases)?
    };
    let camera_report = json!({"view_projection_bits":bits(camera),"extent":[WIDTH,HEIGHT],"derivation":"baseline-only union bounds; fixed overview orientation; no gameplay-framing verdict"});
    write(&output.join("camera.json"), &camera_report)?;
    let mut renderer = if camera_input.is_some() {
        require(cfg!(target_os = "windows"), "native Windows DX12 required")?;
        let renderer = pollster::block_on(WgpuRenderer::new_headless(
            WIDTH,
            HEIGHT,
            BackendSelection::Dx12,
            true,
        ))?;
        require(
            renderer.info().backend == "Dx12"
                && renderer.info().adapter == "Microsoft Basic Render Driver"
                && renderer.info().requested == "dx12",
            "expected actual DX12 WARP",
        )?;
        Some(renderer)
    } else {
        None
    };
    let mut rows = Vec::new();
    for case in cases {
        let mut list = DrawList::new(WIDTH, HEIGHT);
        list.camera(Camera {
            view_projection: camera,
            target: None,
            depth_test: true,
            depth_range: [0., 1.],
        });
        list.clear(BACKGROUND);
        list.commands.extend(
            case.list
                .commands
                .into_iter()
                .filter(|c| matches!(c, Command::Mesh { .. })),
        );
        let mut expanded = Vec::new();
        for command in &list.commands {
            if let Command::Mesh { mesh, .. } = command {
                for &index in &mesh.indices {
                    expanded.extend(vertex_bytes(mesh.vertices[usize::from(index)])?);
                }
            }
        }
        fs::write(output.join(format!("{}.corners.bin", case.name)), expanded)
            .map_err(|e| e.to_string())?;
        if let Some(renderer) = &mut renderer {
            let path = output.join(format!("{}.png", case.name));
            list.capture_png(None, &path);
            require(
                renderer.submit(&list)?.captures == [path],
                "capture path mismatch",
            )?;
        }
        rows.push(json!({"name":case.name,"metadata":case.metadata,"commands":case.commands}));
    }
    write(
        &output.join("report.json"),
        &json!({"schema":SCHEMA,"source_receipt_sha256":option_env!("PASS_SUBMISSION_SOURCE_SHA256").unwrap_or("unbound"),
        "camera":camera_report,"source_counts":sources,"cases":rows,"native_images":renderer.is_some(),
        "scope":"original companion loader/draw and idle manifest/controller parity; diagnostic overview only"}),
    )
}
fn main() {
    #[cfg(feature = "wgpu-runtime")]
    if let Err(error) = run() {
        eprintln!("authored-loader-contract: {error}");
        std::process::exit(1);
    }
    #[cfg(not(feature = "wgpu-runtime"))]
    {
        eprintln!("requires wgpu-runtime");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_corners_ignore_storage_order_but_retain_index_order() {
        let a = Vertex::new(0., 0., 0., 0., 0., Color::WHITE);
        let b = Vertex::new(1., 0., 0., 0., 0., Color::WHITE);
        let mesh = |vertices, indices| vector_range::draw::Mesh {
            vertices,
            indices,
            texture: None,
        };
        let list = |mesh| {
            let mut l = DrawList::new(WIDTH, HEIGHT);
            l.draw_mesh(&mesh, Mat4::IDENTITY, vector_range::draw::BlendMode::Alpha);
            l
        };
        let x = commands(&list(mesh(vec![a, b, a], vec![0, 1, 2])))
            .unwrap()
            .0;
        let mut y = commands(&list(mesh(vec![a, b], vec![0, 1, 0]))).unwrap().0;
        y[0]["stored_vertices"] = json!(3);
        assert_eq!(x, y);
        let z = commands(&list(mesh(vec![a, b], vec![1, 0, 0]))).unwrap().0;
        assert_ne!(x[0]["expanded_sha256"], z[0]["expanded_sha256"]);
    }
    #[test]
    fn canonical_bytes_preserve_signed_zero_and_reject_nonfinite() {
        let v = Vertex::new(-0., 1., 2., 3., 4., Color::WHITE);
        let raw = vertex_bytes(v).unwrap();
        assert_eq!(&raw[..4], &(-0_f32).to_le_bytes());
        let mut invalid = v;
        invalid.normal.x = f32::NAN;
        assert!(vertex_bytes(invalid).is_err());
    }
    #[test]
    fn common_camera_roundtrips_exact_bits() {
        let matrix = Mat4::perspective_rh_gl(1., 1.7, 0.1, 100.);
        assert_eq!(
            bits(camera_from_json(&json!({"view_projection_bits":bits(matrix)})).unwrap()),
            bits(matrix)
        );
    }
}
