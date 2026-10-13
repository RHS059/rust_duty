//! Actual loader legacy-resident versus coalesced-resident ordered-stream and strict image contract.
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
use std::{
    collections::{HashMap, HashSet},
    fs,
    path::Path,
};
use vector_range::draw::{
    resident::{ResidentMesh, Vertices},
    ResourceId,
};
use vector_range::{
    animation_manifest::AnimationManifest,
    draw::{facade, Color, Command, DrawList, TextureSource, Vertex},
    scene_lighting::SceneLighting,
    settings::Settings,
    sim::{Input, Simulation, FIXED_DT},
    viewmodel_animation::AnimationSet,
};
use weapon_model::{ResidentBatching, ResidentSourceGroup};
const WIDTH: u32 = 960;
const HEIGHT: u32 = 540;
const SCHEMA: &str = "rust-duty-resident-coalesced-authored-contract/v1";
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
fn append_source_corner(out: &mut Vec<u8>, mesh: &ResidentMesh, index: u16) -> Result<(), String> {
    let float = |out: &mut Vec<u8>, values: &[f32]| {
        for value in values {
            out.extend(value.to_le_bytes());
        }
    };
    match mesh.vertices() {
        Vertices::Rigid(vertices) => {
            let v = vertices
                .get(usize::from(index))
                .ok_or("resident source index out of bounds")?;
            float(out, &v.position);
            float(out, &v.normal);
            float(out, &v.uv);
        }
        Vertices::Skin { vertices, .. } => {
            let v = vertices
                .get(usize::from(index))
                .ok_or("resident source index out of bounds")?;
            float(out, &v.vertex.position);
            float(out, &v.vertex.normal);
            float(out, &v.vertex.uv);
            for joint in v.joints {
                out.extend(joint.to_le_bytes());
            }
            float(out, &v.weights);
        }
    }
    Ok(())
}
fn source_kind(mesh: &ResidentMesh) -> Value {
    match mesh.vertices() {
        Vertices::Rigid(_) => json!({"kind":"rigid"}),
        Vertices::Skin { bones, .. } => json!({"kind":"skin","bones":bones}),
    }
}
type SourceLayout = (HashMap<ResourceId, String>, Vec<u8>, Vec<Value>);
fn source_layout(groups: &[ResidentSourceGroup], legacy: bool) -> Result<SourceLayout, String> {
    require(
        !groups.is_empty() && groups.len() <= 8192,
        "empty or unbounded resident layout",
    )?;
    let mut cursors: HashMap<(String, String), (usize, usize)> = HashMap::new();
    let mut labels = HashMap::new();
    let mut bytes = Vec::new();
    let mut corners = 0usize;
    let mut records = Vec::new();
    for group in groups {
        require(
            matches!(group.kind, "skin" | "rigid")
                && group.source_chunks > 0
                && group.source_chunks <= 8192,
            "invalid source group kind/count",
        )?;
        let entry = cursors
            .entry((group.model_key.clone(), group.kind.into()))
            .or_insert((0, group.source_chunks));
        require(
            entry.1 == group.source_chunks
                && group.sources.start == entry.0
                && group.sources.end > group.sources.start
                && group.sources.end <= group.source_chunks,
            "source ranges skip, overlap, reorder or exceed original chunks",
        )?;
        require(
            group.source_parts.len() == group.sources.len()
                && group
                    .source_parts
                    .iter()
                    .all(|part| *part == group.source_parts[0]),
            "resident group crosses an original source part",
        )?;
        require(
            !legacy || group.sources.len() == 1,
            "legacy policy did not retain original chunk boundaries",
        )?;
        entry.0 = group.sources.end;
        let mesh = group
            .mesh
            .as_ref()
            .ok_or("resident source group has fallback geometry")?;
        require(
            !mesh.indices().is_empty()
                && mesh.indices().len() <= 65_535
                && mesh.indices().len().is_multiple_of(3)
                && mesh.vertex_count() <= 65_536,
            "resident group exceeds existing bounds",
        )?;
        require(
            (group.kind == "skin") == matches!(mesh.vertices(), Vertices::Skin { .. }),
            "source group vertex kind differs",
        )?;
        let label = format!(
            "{}/{}/{}",
            group.model_key, group.kind, group.source_parts[0]
        );
        require(
            labels.insert(mesh.id(), label.clone()).is_none(),
            "one geometry resource assigned to multiple source groups",
        )?;
        let tag=bytes_hash(&serde_json::to_vec(&json!({"part":label,"layout":source_kind(mesh),"texture":texture_state(mesh.texture())?})).map_err(|e|e.to_string())?);
        records.push(json!({"model_key":group.model_key,"kind":group.kind,"source_chunks":group.source_chunks,"sources":[group.sources.start,group.sources.end],"source_parts":group.source_parts,"part":label,"layout":source_kind(mesh),"texture":texture_state(mesh.texture())?,"vertices":mesh.vertex_count(),"indices":mesh.indices().len()}));
        corners = corners
            .checked_add(mesh.indices().len())
            .ok_or("source corner count overflow")?;
        require(corners <= 4_000_000, "source layout corner bound exceeded")?;
        for triangle in mesh.indices().as_chunks::<3>().0 {
            bytes.extend(tag.as_bytes());
            for &index in triangle {
                append_source_corner(&mut bytes, mesh, index)?;
            }
        }
    }
    require(
        cursors.values().all(|(end, total)| end == total),
        "source layout omits trailing original chunks",
    )?;
    Ok((labels, bytes, records))
}
std::thread_local! {
    static TEXTURE_STATES: std::cell::RefCell<HashMap<ResourceId,(vector_range::draw::Texture,Value)>> = std::cell::RefCell::new(HashMap::new());
}
fn texture_state(texture: Option<&vector_range::draw::Texture>) -> Result<Value, String> {
    let Some(texture) = texture else {
        return Ok(Value::Null);
    };
    let TextureSource::Rgba8(rgba) = &texture.source else {
        return Err("unexpected target material".into());
    };
    TEXTURE_STATES.with(|cache| {
        let mut cache=cache.borrow_mut();
        if let Some((old,state))=cache.get(&texture.id) {
            let TextureSource::Rgba8(old_rgba)=&old.source else {return Err("cached material kind changed".into())};
            require(old.width==texture.width && old.height==texture.height && old.sampler.filter==texture.sampler.filter && old.sampler.wrap_x==texture.sampler.wrap_x && old.sampler.wrap_y==texture.sampler.wrap_y && std::sync::Arc::ptr_eq(old_rgba,rgba),"immutable texture identity changed")?;
            return Ok(state.clone());
        }
        require(cache.len()<8192,"material cache bound exceeded")?;
        let state=json!({"width":texture.width,"height":texture.height,"filter":format!("{:?}",texture.sampler.filter),"wrap_x":format!("{:?}",texture.sampler.wrap_x),"wrap_y":format!("{:?}",texture.sampler.wrap_y),"rgba_sha256":bytes_hash(rgba.as_ref())});
        cache.insert(texture.id,(texture.clone(),state.clone()));Ok(state)
    })
}
type OrderedCommands = (Vec<Value>, Vec<u8>, Vec<Vec3>);
fn ordered_commands(
    list: &DrawList,
    labels: &HashMap<ResourceId, String>,
) -> Result<OrderedCommands, String> {
    let mut rows = Vec::new();
    let mut bytes = Vec::new();
    let mut points = Vec::new();
    for command in &list.commands {
        let (draw, model, blend) = match command {
            Command::Resident { draw, model, blend } => (draw, model, blend),
            Command::Camera(_) => continue,
            _ => return Err("actual-loader contract requires only resident geometry".into()),
        };
        let mesh = draw.mesh();
        let part = labels
            .get(&mesh.id())
            .ok_or("draw geometry missing original source-part provenance")?;
        let light = draw.lighting();
        let albedo = draw.albedo();
        let albedo_bits = [albedo.r, albedo.g, albedo.b, albedo.a].map(f32::to_bits);
        let state = json!({"part":part,"layout":source_kind(mesh),"model":bits(*model),"root":bits(draw.root()),"normal":bits(draw.normal_transform()),"blend":format!("{blend:?}"),"texture":texture_state(mesh.texture())?,"light_direction":light.direction_to_light.to_array().map(f32::to_bits),"ambient":light.ambient.to_bits(),"diffuse":light.diffuse.to_bits(),"albedo":albedo_bits,"alpha":draw.alpha().to_bits(),"palette":draw.palette().map(|p|json!({"positions":p.positions().iter().copied().map(bits).collect::<Vec<_>>(),"normals":p.normals().iter().copied().map(bits).collect::<Vec<_>>()}))});
        let tag = bytes_hash(&serde_json::to_vec(&state).map_err(|e| e.to_string())?);
        let reference = draw.reference_mesh();
        require(
            model.is_finite()
                && reference.indices.as_slice() == mesh.indices()
                && !reference.indices.is_empty()
                && reference.indices.len() <= 65_535
                && reference.indices.len().is_multiple_of(3),
            "invalid resident/reference geometry",
        )?;
        require(
            points
                .len()
                .checked_add(reference.indices.len())
                .is_some_and(|n| n <= 4_000_000),
            "ordered draw corner bound exceeded",
        )?;
        for triangle in reference.indices.as_chunks::<3>().0 {
            bytes.extend(tag.as_bytes());
            for &index in triangle {
                append_source_corner(&mut bytes, mesh, index)?;
                let mut vertex = *reference
                    .vertices
                    .get(usize::from(index))
                    .ok_or("reference corner out of bounds")?;
                vertex.position = model.transform_point3(vertex.position);
                vertex.normal = glam::Vec4::ZERO;
                points.push(vertex.position);
                bytes.extend(vertex_bytes(vertex)?);
            }
        }
        rows.push(
            json!({"state":state,"vertices":mesh.vertex_count(),"indices":mesh.indices().len()}),
        );
    }
    require(
        !rows.is_empty() && rows.len() <= 2048,
        "empty/unbounded actual loader draw list",
    )?;
    Ok((rows, bytes, points))
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
    ordered: Vec<u8>,
    layout: Vec<u8>,
    layout_groups: Vec<Value>,
    points: Vec<Vec3>,
}
fn save_case(
    cases: &mut Vec<Case>,
    name: String,
    metadata: Value,
    groups: Vec<ResidentSourceGroup>,
    policy: ResidentBatching,
) -> Result<(), String> {
    let list = facade::take_draw_list()?;
    let (labels, layout, layout_groups) =
        source_layout(&groups, matches!(policy, ResidentBatching::LegacyChunks))?;
    let (commands, ordered, points) = ordered_commands(&list, &labels)?;
    cases.push(Case {
        name,
        list,
        metadata,
        commands,
        ordered,
        layout,
        layout_groups,
        points,
    });
    Ok(())
}
fn begin_recording(renderer: Option<&dyn vector_range::draw::Renderer>) -> Result<(), String> {
    match renderer {
        Some(renderer) => facade::begin_frame_with_renderer(WIDTH, HEIGHT, 1., renderer),
        None => facade::begin_frame(WIDTH, HEIGHT, 1.),
    }
}
fn fixture(
    manifest_path: &Path,
    renderer: Option<&dyn vector_range::draw::Renderer>,
    policy: ResidentBatching,
) -> Result<(Vec<Case>, Value), String> {
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
        let mut model = authored_viewmodel::AuthoredViewmodel::load_with_batching(
            path.to_str().ok_or("asset path is not Unicode")?,
            clip,
            None,
            policy,
        )?;
        for (ordinal, fraction) in [0., 0.5, 0.9, 0.].into_iter().enumerate() {
            let time = duration * fraction;
            begin_recording(renderer)?;
            // Same public draw route and same loaded mutable meshes are reused.
            model.draw(f64::from(time), SceneLighting::range(), Mat4::IDENTITY);
            require(model.error().is_none(), "authored draw failed")?;
            save_case(
                &mut cases,
                format!("{label}-{ordinal}"),
                json!({"route":"load/draw","clip":clip,
                "time_bits":time.to_bits(),"fraction_tenths":([0,5,9,0][ordinal]),"duration_bits":duration.to_bits(),"cant_bits":0}),
                model.resident_source_groups(label),
                policy,
            )?;
        }
        // Revisit must be exactly equal even within one source variant.
        let n = cases.len();
        require(
            cases[n - 4].ordered == cases[n - 1].ordered,
            "return-to-start changed loaded mesh output",
        )?;
    }
    let mut model =
        authored_viewmodel::AuthoredViewmodel::load_manifest_with_batching(manifest_path, policy)?;
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
            begin_recording(renderer)?;
            model.draw(sim.time, SceneLighting::range(), Mat4::IDENTITY);
            require(model.error().is_none(), "manifest/controller draw failed")?;
            save_case(
                &mut cases,
                format!("manifest-{frame}"),
                json!({"route":"load_manifest/committed_step/draw",
                "fixed_steps":frame,"simulation_time_bits":sim.time.to_bits(),"warning":model.warning()}),
                model.resident_source_groups("manifest"),
                policy,
            )?;
        }
    }
    // Exercise rigid alpha and nonuniform normal transforms on original material data.
    let (_, _, rigid) = AnimationSet::load_with_companions(&manifest.locomotion_asset)
        .map_err(|e| e.to_string())?;
    let part_count = rigid.meshes.len();
    let mut model = weapon_model::WeaponModel::from_asset_with_batching(rigid, policy);
    let transforms = vec![
        Mat4::from_scale_rotation_translation(
            Vec3::new(1.1, 0.9, 1.),
            Quat::from_rotation_y(0.2),
            Vec3::ZERO
        );
        part_count
    ];
    for (ordinal, alpha) in [0.5, 0.25, 0.5].into_iter().enumerate() {
        begin_recording(renderer)?;
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
            model.resident_source_groups("rigid-alpha"),
            policy,
        )?;
    }
    let n = cases.len();
    require(
        cases[n - 3].ordered == cases[n - 1].ordered,
        "rigid alpha revisit changed output",
    )?;
    require(cases.len() == 22, "fixture case count changed")?;
    Ok((cases, Value::Object(sources)))
}
fn overview(cases: &[Case]) -> Result<Mat4, String> {
    let mut low = Vec3::splat(f32::INFINITY);
    let mut high = Vec3::splat(f32::NEG_INFINITY);
    for case in cases {
        for &point in &case.points {
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
fn path_counts(list: &DrawList) -> [u64; 3] {
    let mut counts = [0; 3];
    for command in &list.commands {
        match command {
            Command::Mesh { .. } => counts[0] += 1,
            Command::Resident { draw, .. } if draw.palette().is_some() => counts[2] += 1,
            Command::Resident { .. } => counts[1] += 1,
            _ => (),
        }
    }
    counts
}
fn stats_json(stats: vector_range::draw::ResidentFrameStats) -> Value {
    json!({"draws":stats.draws,"rigid_draws":stats.rigid_draws,"skinned_draws":stats.skinned_draws,
        "vertex_bytes_uploaded":stats.vertex_bytes_uploaded,"index_bytes_uploaded":stats.index_bytes_uploaded,
        "uniform_bytes_uploaded":stats.uniform_bytes_uploaded,"cache_hits":stats.cache_hits,
        "cache_misses":stats.cache_misses,"transient_meshes":stats.transient_meshes,
        "buffer_allocations":stats.buffer_allocations,"binding_allocations":stats.binding_allocations})
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
    require(args.next().is_none(), "unexpected trailing argument")?;
    fs::create_dir(&output).map_err(|e| e.to_string())?;
    let (backend, fallback) = if cfg!(target_os = "windows") {
        (BackendSelection::Dx12, true)
    } else if cfg!(target_os = "linux") {
        (BackendSelection::Vulkan, false)
    } else {
        return Err("unsupported native host".into());
    };
    let mut renderer =
        pollster::block_on(WgpuRenderer::new_headless(WIDTH, HEIGHT, backend, fallback))?;
    require(
        renderer.supports_resident_meshes(),
        "native resident policy/capability is disabled",
    )?;
    if cfg!(target_os = "windows") {
        require(
            renderer.info().backend == "Dx12"
                && renderer.info().adapter == "Microsoft Basic Render Driver",
            "expected actual DX12 WARP",
        )?;
    } else {
        require(
            renderer.info().backend == "Vulkan"
                && renderer.info().adapter == "NVIDIA A100-SXM4-40GB",
            "expected actual A100 Vulkan",
        )?;
    }
    let (cpu_cases, sources) = fixture(&manifest, Some(&renderer), ResidentBatching::LegacyChunks)?;
    let (gpu_cases, gpu_sources) =
        fixture(&manifest, Some(&renderer), ResidentBatching::CoalescedParts)?;
    require(
        sources == gpu_sources,
        "loaded companion source counts changed",
    )?;
    require(
        cpu_cases.len() == 22 && gpu_cases.len() == 22,
        "expected both 22-case cohorts",
    )?;
    let camera = overview(&cpu_cases)?;
    let camera_report = json!({"view_projection_bits":bits(camera),"extent":[WIDTH,HEIGHT],"derivation":"Legacy-resident union bounds; same overview for both policies"});
    write(&output.join("camera.json"), &camera_report)?;
    let mut rows = Vec::new();
    let mut all_pass = true;
    let mut saw_reduction = false;
    for (cpu, gpu) in cpu_cases.iter().zip(&gpu_cases) {
        require(
            cpu.name == gpu.name && cpu.metadata == gpu.metadata,
            "pose sequence or metadata differs",
        )?;
        let cpu_paths = path_counts(&cpu.list);
        let gpu_paths = path_counts(&gpu.list);
        require(
            cpu_paths[0] == 0 && gpu_paths[0] == 0,
            "both policies must use resident geometry without CPU fallback",
        )?;
        require(
            cpu_paths[1] > 0
                && gpu_paths[1] > 0
                && (cpu.name.starts_with("rigid-alpha-") || (cpu_paths[2] > 0 && gpu_paths[2] > 0)),
            "skin/rigid resident routes missing",
        )?;
        require(
            gpu_paths[1] <= cpu_paths[1] && gpu_paths[2] <= cpu_paths[2],
            "coalescing increased resident draw count",
        )?;
        saw_reduction |= gpu_paths[1] + gpu_paths[2] < cpu_paths[1] + cpu_paths[2];
        let corner_equal = cpu.ordered == gpu.ordered && cpu.layout == gpu.layout;
        for case in [cpu, gpu] {
            let path = output.join(format!("layout-{}.bin", bytes_hash(&case.layout)));
            if path.exists() {
                require(
                    fs::read(&path).map_err(|e| e.to_string())? == case.layout,
                    "source layout digest collision",
                )?;
            } else {
                fs::write(path, &case.layout).map_err(|e| e.to_string())?;
            }
        }
        for case in [cpu, gpu] {
            let path = output.join(format!("ordered-{}.bin", bytes_hash(&case.ordered)));
            if path.exists() {
                require(
                    fs::read(&path).map_err(|e| e.to_string())? == case.ordered,
                    "ordered stream digest collision",
                )?;
            } else {
                fs::write(path, &case.ordered).map_err(|e| e.to_string())?;
            }
        }
        let mut stats = Vec::new();
        for (label, case) in [("legacy", &cpu), ("coalesced", &gpu)] {
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
                    .iter()
                    .filter(|c| matches!(c, Command::Mesh { .. } | Command::Resident { .. }))
                    .cloned(),
            );
            let path = output.join(format!("{}-{label}.png", case.name));
            list.capture_png(None, &path);
            let result = renderer.submit(&list)?;
            require(result.captures == [path], "capture path mismatch")?;
            let paths = if label == "legacy" {
                cpu_paths
            } else {
                gpu_paths
            };
            let expected = paths[1] + paths[2];
            require(
                result.resident.draws == expected
                    && result.resident.rigid_draws == paths[1]
                    && result.resident.skinned_draws == paths[2]
                    && result.resident.transient_meshes == 0,
                "native submission did not execute the recorded resident route",
            )?;
            stats.push(stats_json(result.resident));
        }
        let a = image::open(output.join(format!("{}-legacy.png", cpu.name)))
            .map_err(|e| e.to_string())?
            .to_rgba8();
        let b = image::open(output.join(format!("{}-coalesced.png", cpu.name)))
            .map_err(|e| e.to_string())?
            .to_rgba8();
        require(
            a.dimensions() == (WIDTH, HEIGHT) && b.dimensions() == a.dimensions(),
            "capture extent differs",
        )?;
        let differing = a.pixels().zip(b.pixels()).filter(|(x, y)| x != y).count();
        let max_delta = a
            .as_raw()
            .iter()
            .zip(b.as_raw())
            .map(|(&x, &y)| x.abs_diff(y))
            .max()
            .unwrap_or(0);
        let foreground = a
            .pixels()
            .filter(|p| {
                p.0[..3]
                    .iter()
                    .zip([8u8, 16, 24])
                    .any(|(&x, y)| x.abs_diff(y) > 4)
            })
            .count();
        all_pass &= corner_equal && differing == 0 && foreground > 100;
        rows.push(json!({"name":cpu.name,"metadata":cpu.metadata,"legacy_paths":cpu_paths,"coalesced_paths":gpu_paths,
            "legacy_commands":cpu.commands,"coalesced_commands":gpu.commands,"ordered_source_state_and_corners_equal":corner_equal,
            "legacy_ordered_sha256":bytes_hash(&cpu.ordered),"coalesced_ordered_sha256":bytes_hash(&gpu.ordered),
            "legacy_layout_sha256":bytes_hash(&cpu.layout),"coalesced_layout_sha256":bytes_hash(&gpu.layout),
            "legacy_layout_groups":cpu.layout_groups,"coalesced_layout_groups":gpu.layout_groups,
            "legacy_stats":stats[0],"coalesced_stats":stats[1],"differing_pixels":differing,"maximum_channel_delta":max_delta,"foreground_pixels":foreground}));
    }
    all_pass &= saw_reduction;
    write(
        &output.join("report.json"),
        &json!({"schema":SCHEMA,"source_receipt_sha256":option_env!("PASS_SUBMISSION_SOURCE_SHA256").unwrap_or("unbound"),
        "camera":camera_report,"source_counts":sources,"cases":rows,"passed":all_pass,"draw_reduction_observed":saw_reduction,
        "backend":{"requested":renderer.info().requested,"backend":renderer.info().backend,"adapter":renderer.info().adapter},
        "scope":"actual original-loader legacy resident versus coalesced resident; exact original source-part/material/pose and ordered immutable/expanded corner stream plus strict full RGBA images; diagnostic overview, no performance or gameplay-framing verdict"}),
    )?;
    require(
        all_pass,
        "resident coalescing source/state/order/image contract failed; evidence retained",
    )
}
fn main() {
    #[cfg(feature = "wgpu-runtime")]
    if let Err(error) = run() {
        eprintln!("resident-coalesced-authored-contract: {error}");
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
    fn triangle(offset: f32) -> ResidentMesh {
        use vector_range::draw::resident::RigidVertex;
        ResidentMesh::new(
            Vertices::Rigid(vec![
                RigidVertex {
                    position: [offset, 0., 0.],
                    normal: [0., 1., 0.],
                    uv: [0., 0.],
                },
                RigidVertex {
                    position: [offset + 1., 0., 0.],
                    normal: [0., 1., 0.],
                    uv: [1., 0.],
                },
                RigidVertex {
                    position: [offset, 1., 0.],
                    normal: [0., 1., 0.],
                    uv: [0., 1.],
                },
            ]),
            vec![0, 1, 2],
            None,
        )
        .unwrap()
    }
    fn group(
        mesh: ResidentMesh,
        range: std::ops::Range<usize>,
        parts: Vec<usize>,
    ) -> ResidentSourceGroup {
        ResidentSourceGroup {
            model_key: "fixture".into(),
            kind: "rigid",
            source_chunks: 2,
            sources: range,
            source_parts: parts,
            mesh: Some(mesh),
        }
    }
    fn recorded(meshes: &[ResidentMesh], alpha: f32) -> DrawList {
        use vector_range::draw::{resident::ResidentDraw, BlendMode};
        let mut list = DrawList::new(WIDTH, HEIGHT);
        for mesh in meshes {
            list.draw_resident(
                ResidentDraw::new(
                    mesh.clone(),
                    Mat4::IDENTITY,
                    SceneLighting::range(),
                    Color::WHITE,
                    alpha,
                    None,
                )
                .unwrap(),
                Mat4::IDENTITY,
                BlendMode::Alpha,
            );
        }
        list
    }
    #[test]
    fn canonical_stream_accepts_only_boundary_preserving_concatenation() {
        let a = triangle(0.);
        let b = triangle(2.);
        let legacy = vec![
            group(a.clone(), 0..1, vec![7]),
            group(b.clone(), 1..2, vec![7]),
        ];
        let merged = ResidentMesh::coalesce(&[a.clone(), b.clone()]).unwrap();
        let coalesced = vec![group(merged.clone(), 0..2, vec![7, 7])];
        let (old_ids, old_layout, _) = source_layout(&legacy, true).unwrap();
        let (new_ids, new_layout, _) = source_layout(&coalesced, false).unwrap();
        assert_eq!(old_layout, new_layout);
        let (old_rows, old_bytes, _) = ordered_commands(&recorded(&[a, b], 1.), &old_ids).unwrap();
        let (new_rows, new_bytes, _) =
            ordered_commands(&recorded(std::slice::from_ref(&merged), 1.), &new_ids).unwrap();
        assert_eq!((old_rows.len(), new_rows.len()), (2, 1));
        assert_eq!(old_bytes, new_bytes);
        assert_ne!(
            new_bytes,
            ordered_commands(&recorded(&[merged], 0.5), &new_ids)
                .unwrap()
                .1
        );
    }
    #[test]
    fn source_layout_rejects_cross_part_missing_overlapping_and_nonlegacy_groups() {
        let mesh = ResidentMesh::coalesce(&[triangle(0.), triangle(2.)]).unwrap();
        assert!(source_layout(&[group(mesh.clone(), 0..2, vec![7, 8])], false).is_err());
        assert!(source_layout(&[group(mesh.clone(), 0..2, vec![7, 7])], true).is_err());
        assert!(source_layout(&[group(triangle(0.), 0..1, vec![7])], true).is_err());
        assert!(source_layout(
            &[
                group(triangle(0.), 0..1, vec![7]),
                group(triangle(2.), 0..1, vec![7])
            ],
            true
        )
        .is_err());
        assert!(source_layout(&[group(mesh, 0..2, vec![])], false).is_err());
    }
    #[test]
    fn ordered_source_triangle_and_part_identity_are_not_normalized_away() {
        let a = triangle(0.);
        let b = triangle(2.);
        let one = source_layout(
            &[group(
                ResidentMesh::coalesce(&[a.clone(), b.clone()]).unwrap(),
                0..2,
                vec![7, 7],
            )],
            false,
        )
        .unwrap()
        .1;
        let reverse = source_layout(
            &[group(
                ResidentMesh::coalesce(&[b, a]).unwrap(),
                0..2,
                vec![7, 7],
            )],
            false,
        )
        .unwrap()
        .1;
        assert_ne!(one, reverse);
        let different_part = source_layout(
            &[group(
                ResidentMesh::coalesce(&[triangle(0.), triangle(2.)]).unwrap(),
                0..2,
                vec![8, 8],
            )],
            false,
        )
        .unwrap()
        .1;
        assert_ne!(one, different_part);
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
