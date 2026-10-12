//! All-frame source geometry classification only. No candidate pixels are read.
//! Expected-empty results are conditional on the explicit arithmetic profile;
//! positive/ambiguous support remains unresolved, and no capture gate is changed.
#![allow(dead_code)]
#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[path = "../src/weapon_model.rs"]
mod weapon_model;
use serde_json::json;
#[path = "source_visibility_geometry/domain.rs"]
mod geometry_domain;
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};
use vector_range::{
    animation_manifest::AnimationManifest,
    asset::WeaponAsset,
    draw::facade::{Color, Mat4, Vec3, Vec4},
    scene_lighting::SceneLighting,
    settings::Settings,
    sim::{Simulation, FIXED_DT},
    skinned_asset::{crc32, SkinnedAsset},
    viewmodel_animation::{game_model_root, AnimationSet},
    weapon_sway,
};
const U: f64 = 1.0 / 8_388_608.0;
fn gamma(n: f64, u: f64) -> f64 {
    n * u / (1.0 - n * u)
}
#[derive(Clone)]
struct ClipRow {
    coefficient: [f64; 4],
    absolute: [f64; 4],
    steps: f64,
    host_steps: f64,
}
impl ClipRow {
    fn new(projection: Mat4, model: Mat4, row: usize) -> Self {
        let a = projection.to_cols_array();
        let b = model.to_cols_array();
        let mut coefficient = [0.; 4];
        let mut absolute = [0.; 4];
        for k in 0..4 {
            for j in 0..4 {
                let p = f64::from(a[j * 4 + row]) * f64::from(b[k * 4 + j]);
                coefficient[k] += p;
                absolute[k] += p.abs();
            }
        }
        Self {
            coefficient,
            absolute,
            steps: 17.,
            host_steps: 64.,
        }
    }
    fn dx12(projection: Mat4, model: Mat4, row: usize) -> Self {
        // Match the production CPU upload path (remap*projection)*model, then
        // bound its shader dot. Two rounded four-term matrix products plus a
        // four-term dot have <=21 factors on each expanded term path. Gamma24
        // is a fixed conservative envelope, independent of observed coverage.
        let r = dx12_remap().to_cols_array();
        let a = projection.to_cols_array();
        let b = model.to_cols_array();
        let mut coefficient = [0.; 4];
        let mut absolute = [0.; 4];
        for k in 0..4 {
            for j in 0..4 {
                for l in 0..4 {
                    let p = f64::from(r[l * 4 + row])
                        * f64::from(a[j * 4 + l])
                        * f64::from(b[k * 4 + j]);
                    coefficient[k] += p;
                    absolute[k] += p.abs();
                }
            }
        }
        Self {
            coefficient,
            absolute,
            steps: 24.,
            host_steps: 256.,
        }
    }
    fn interval(&self, p: Vec3) -> [f64; 2] {
        let p = [f64::from(p.x), f64::from(p.y), f64::from(p.z), 1.];
        let sum: f64 = self.coefficient.iter().zip(p).map(|(a, b)| a * b).sum();
        let absolute: f64 = self.absolute.iter().zip(p).map(|(a, b)| a * b.abs()).sum();
        let host = gamma(self.host_steps, f64::EPSILON);
        let radius = ((gamma(self.steps, U) + host) * absolute / (1. - host)).next_up();
        [(sum - radius).next_down(), (sum + radius).next_up()]
    }
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum Backend {
    OpenGl,
    Dx12,
}
fn dx12_remap() -> Mat4 {
    Mat4::from_cols(
        Vec4::X,
        Vec4::Y,
        Vec4::new(0., 0., 0.5, 0.),
        Vec4::new(0., 0., 0.5, 1.),
    )
}
// The interval profile is deliberately explicit, not inferred from reported GL
// highp precision. One full 1/256-pixel unit covers either nearest or truncating
// raster-grid conversion. Unsupported near/eye clipping remains unresolved.
const WIDTH: usize = 960;
const HEIGHT: usize = 540;
const COLOR_TOLERANCE: i32 = 8;
const FRAGMENT_BYTE_ERROR: i32 = 3;
#[derive(Clone, Copy, Debug)]
struct Bound {
    lo: f64,
    hi: f64,
}
impl Bound {
    fn new(lo: f64, hi: f64) -> Self {
        Self {
            lo: lo.next_down(),
            hi: hi.next_up(),
        }
    }
    fn point(x: f64) -> Self {
        Self { lo: x, hi: x }
    }
    fn add(self, b: Self) -> Self {
        Self::new(self.lo + b.lo, self.hi + b.hi)
    }
    fn sub(self, b: Self) -> Self {
        Self::new(self.lo - b.hi, self.hi - b.lo)
    }
    fn mul(self, b: Self) -> Self {
        let x = [
            self.lo * b.lo,
            self.lo * b.hi,
            self.hi * b.lo,
            self.hi * b.hi,
        ];
        Self::new(
            x.into_iter().fold(f64::INFINITY, f64::min),
            x.into_iter().fold(f64::NEG_INFINITY, f64::max),
        )
    }
    fn div(self, b: Self) -> Self {
        assert!(b.lo > 0.);
        self.mul(Self::new(1. / b.hi, 1. / b.lo))
    }
    fn expand(self, relative: f64, absolute: f64) -> Self {
        let e = self.lo.abs().max(self.hi.abs()) * relative + absolute;
        Self::new(self.lo - e, self.hi + e)
    }
}
fn screen(c: [Bound; 4]) -> Option<[Bound; 2]> {
    if c[3].lo <= 0. || c[2].add(c[3]).lo <= 0. || c[3].sub(c[2]).lo <= 0. {
        return None;
    }
    Some(std::array::from_fn(|axis| {
        let q = c[axis].div(c[3]).expand(gamma(3., U), 0.);
        let q = if axis == 0 {
            q.add(Bound::point(1.))
        } else {
            Bound::point(1.).sub(q)
        };
        q.expand(U, 0.)
            .mul(Bound::point(if axis == 0 { 480. } else { 270. }))
            .expand(U, 1. / 256.)
    }))
}
fn edge(a: [Bound; 2], b: [Bound; 2], p: [Bound; 2]) -> Bound {
    b[0].sub(a[0])
        .mul(p[1].sub(a[1]))
        .sub(b[1].sub(a[1]).mul(p[0].sub(a[0])))
}
fn runs(mask: &[u8]) -> Vec<[usize; 2]> {
    let mut out = Vec::new();
    let mut index = 0;
    while index < mask.len() {
        if mask[index] == 0 {
            index += 1;
            continue;
        }
        let first = index;
        while index < mask.len() && mask[index] != 0 {
            index += 1;
        }
        out.push([first, index - first]);
    }
    out
}
fn texture_bounds(rgba: &[u8]) -> [[u8; 2]; 3] {
    if rgba.is_empty() {
        return [[255, 255]; 3];
    }
    std::array::from_fn(|c| {
        [
            rgba.iter().skip(c).step_by(4).copied().min().unwrap(),
            rgba.iter().skip(c).step_by(4).copied().max().unwrap(),
        ]
    })
}
fn contrast(colors: [[u8; 4]; 3], texture: [[u8; 2]; 3]) -> bool {
    if colors.iter().any(|c| c[3] != 255) {
        return false;
    }
    let clear = [36_i32, 48, 61];
    (0..3).any(|c| {
        let lo =
            i32::from(colors.iter().map(|v| v[c]).min().unwrap()) * i32::from(texture[c][0]) / 255;
        let hi = (i32::from(colors.iter().map(|v| v[c]).max().unwrap()) * i32::from(texture[c][1])
            + 254)
            / 255;
        clear[c] - hi > COLOR_TOLERANCE + FRAGMENT_BYTE_ERROR
            || lo - clear[c] > COLOR_TOLERANCE + FRAGMENT_BYTE_ERROR
    })
}
struct Samples {
    robust: Vec<u8>,
    possible: Vec<u8>,
    unsafe_color: Vec<u8>,
    unsupported: usize,
}
impl Samples {
    fn new() -> Self {
        Self {
            robust: vec![0; WIDTH * HEIGHT],
            possible: vec![0; WIDTH * HEIGHT],
            unsafe_color: vec![0; WIDTH * HEIGHT],
            unsupported: 0,
        }
    }
    fn triangle(&mut self, c: [[Bound; 4]; 3], safe: bool) {
        // A common strict homogeneous separating plane excludes the entire
        // source triangle, including an otherwise unsupported eye/near case.
        for axis in 0..3 {
            for sign in [-1., 1.] {
                if c.iter()
                    .all(|v| v[3].add(v[axis].mul(Bound::point(sign))).hi < 0.)
                {
                    return;
                }
            }
        }
        let Some(a) = screen(c[0]) else {
            self.unsupported += 1;
            return;
        };
        let Some(b) = screen(c[1]) else {
            self.unsupported += 1;
            return;
        };
        let Some(d) = screen(c[2]) else {
            self.unsupported += 1;
            return;
        };
        let t = [a, b, d];
        let minx = t
            .iter()
            .map(|v| v[0].lo)
            .fold(f64::INFINITY, f64::min)
            .floor()
            .max(0.) as usize;
        let maxx = t
            .iter()
            .map(|v| v[0].hi)
            .fold(f64::NEG_INFINITY, f64::max)
            .ceil()
            .clamp(0., WIDTH as f64) as usize;
        let miny = t
            .iter()
            .map(|v| v[1].lo)
            .fold(f64::INFINITY, f64::min)
            .floor()
            .max(0.) as usize;
        let maxy = t
            .iter()
            .map(|v| v[1].hi)
            .fold(f64::NEG_INFINITY, f64::max)
            .ceil()
            .clamp(0., HEIGHT as f64) as usize;
        for y in miny..maxy {
            for x in minx..maxx {
                if x < 64 && y < 22 {
                    continue;
                } // The independently checked frame witness.
                let p = [Bound::point(x as f64 + 0.5), Bound::point(y as f64 + 0.5)];
                let e = [edge(a, b, p), edge(b, d, p), edge(d, a, p)];
                let possible = e.iter().all(|v| v.hi >= 0.) || e.iter().all(|v| v.lo <= 0.);
                if !possible {
                    continue;
                }
                let i = y * WIDTH + x;
                self.possible[i] = 1;
                if !safe {
                    self.unsafe_color[i] = 1;
                    continue;
                }
                if e.iter().all(|v| v.lo > 0.) || e.iter().all(|v| v.hi < 0.) {
                    self.robust[i] = 1;
                }
            }
        }
    }
    fn required(&self) -> Vec<u8> {
        if self.unsupported != 0 {
            return vec![0; WIDTH * HEIGHT];
        }
        self.robust
            .iter()
            .zip(&self.unsafe_color)
            .map(|(&a, &b)| u8::from(a != 0 && b == 0))
            .collect()
    }
}
struct Source {
    path: PathBuf,
    checksums: (u32, u32),
    skin_bytes: Vec<u8>,
    rigid_bytes: Vec<u8>,
    skin: SkinnedAsset,
    rigid: WeaponAsset,
}
impl Source {
    fn load(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        let (animation, skin, rigid) = AnimationSet::load_with_companions(path)?;
        let skin_bytes = fs::read(path.with_extension("vrs"))?;
        let rigid_bytes = fs::read(path.with_extension("vrm"))?;
        let checksums = animation.companion_checksums();
        assert_eq!(checksums, (crc32(&skin_bytes), crc32(&rigid_bytes)));
        Ok(Self {
            path: path.to_owned(),
            checksums,
            skin_bytes,
            rigid_bytes,
            skin,
            rigid,
        })
    }
}
#[derive(Default)]
struct Inventory {
    geometry_domain: Vec<serde_json::Value>,
    triangle_trace: Vec<serde_json::Value>,
    triangles: usize,
    outside_bottom: usize,
    maximum_bottom_upper: f64,
    meshes: Vec<serde_json::Value>,
    samples: Option<Samples>,
}
impl Inventory {
    fn new() -> Self {
        Self {
            maximum_bottom_upper: f64::NEG_INFINITY,
            samples: Some(Samples::new()),
            ..Self::default()
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn mesh(
        &mut self,
        kind: &str,
        index: usize,
        indices: &[u32],
        positions: &[Vec3],
        colors: &[[u8; 4]],
        texture: [[u8; 2]; 3],
        projection: Mat4,
        model: Mat4,
        backend: Backend,
        visible: bool,
        opacity: f32,
    ) {
        assert!(indices.len().is_multiple_of(3));
        assert!(positions.iter().all(|p| p.is_finite()));
        assert!(opacity.is_finite());
        let count = indices.len() / 3;
        self.triangles += count;
        if !visible {
            self.meshes.push(json!({"kind":kind,"mesh":index,"triangles":count,"state":"source_actor_hidden","opacity":opacity}));
            return;
        }
        self.geometry_domain.push(json!({"kind":kind,"mesh":index,"domain":geometry_domain::check(projection.to_cols_array(), model.to_cols_array(), &positions.iter().map(|p|p.to_array()).collect::<Vec<_>>(), backend == Backend::Dx12)}));
        let clip: Vec<[Bound; 4]> = {
            let rows: [ClipRow; 4] = std::array::from_fn(|r| {
                if backend == Backend::OpenGl {
                    ClipRow::new(projection, model, r)
                } else {
                    ClipRow::dx12(projection, model, r)
                }
            });
            positions
                .iter()
                .map(|&p| {
                    let mut bounds: [Bound; 4] = std::array::from_fn(|r| {
                        let [lo, hi] = rows[r].interval(p);
                        Bound { lo, hi }
                    });
                    // Invert only the depth coordinate for the shared strict GL
                    // near/far-domain guard; retain its outward interval width.
                    if backend == Backend::Dx12 {
                        bounds[2] = bounds[2].mul(Bound::point(2.)).sub(bounds[3]);
                    }
                    bounds
                })
                .collect()
        };
        let upper: Vec<_> = clip.iter().map(|v| v[1].add(v[3]).hi).collect();
        assert!(upper.iter().all(|v| v.is_finite()));
        let mut outside = 0;
        let mut maximum = f64::NEG_INFINITY;
        for (triangle_index, triangle) in indices.as_chunks::<3>().0.iter().enumerate() {
            let value = triangle
                .iter()
                .map(|&i| upper[i as usize])
                .fold(f64::NEG_INFINITY, f64::max);
            outside += usize::from(value < 0.);
            maximum = maximum.max(value);
            if value >= 0. {
                let vertices = triangle.map(|i| clip[i as usize]);
                let colors = triangle.map(|i| colors[i as usize]);
                let screens: Option<Vec<_>> = vertices.iter().copied().map(screen).collect();
                let possible_viewport = screens.as_ref().is_some_and(|t| {
                    t.iter().any(|v| v[0].hi >= 0.)
                        && t.iter().any(|v| v[0].lo <= WIDTH as f64)
                        && t.iter().any(|v| v[1].hi >= 0.)
                        && t.iter().any(|v| v[1].lo <= HEIGHT as f64)
                });
                if !possible_viewport {
                    assert!(
                        (0..3).any(|axis| [-1., 1.].into_iter().any(|sign| vertices
                            .iter()
                            .all(|v| v[3].add(v[axis].mul(Bound::point(sign))).hi < 0.))),
                        "trace viewport cull lacks a strict homogeneous separator"
                    );
                }
                if possible_viewport {
                    self.triangle_trace.push(json!({"kind":kind,"mesh":index,"triangle":triangle_index,"indices":triangle,"clip":vertices.map(|v|v.map(|b|[b.lo,b.hi])),"screen":screens.unwrap().iter().map(|v|v.map(|b|[b.lo,b.hi])).collect::<Vec<_>>(),"colors":colors,"texture_bounds":texture,"safe_contrast":contrast(colors,texture),"projection_bits":projection.to_cols_array().map(f32::to_bits),"model_bits":model.to_cols_array().map(f32::to_bits),"position_bits":triangle.map(|i|positions[i as usize].to_array().map(f32::to_bits))}));
                }
                self.samples
                    .as_mut()
                    .unwrap()
                    .triangle(vertices, contrast(colors, texture));
            }
        }
        self.outside_bottom += outside;
        self.maximum_bottom_upper = self.maximum_bottom_upper.max(maximum);
        self.meshes.push(json!({"kind":kind,"mesh":index,"triangles":count,"state":"enumerated","outside_bottom":outside,"unclassified":count-outside,"maximum_bottom_upper":maximum,"opacity":opacity}));
    }
}
/// Match the existing capture metadata's decimal serialization exactly.
/// These are source replay expectations, not copied native sidecars.
fn native_gameplay_telemetry(
    model: Option<&authored_viewmodel::AuthoredViewmodel>,
    sim: &Simulation,
) -> String {
    let sample = model.and_then(|model| model.ads_sample());
    let native = sample
        .map(|sample| sample.seconds.to_string())
        .unwrap_or_else(|| "null".into());
    let direction = sample.map_or(0, |sample| sample.direction);
    let clip = model.and_then(|model| model.ads_clip()).unwrap_or("");
    let duration = model
        .and_then(|model| model.ads_duration())
        .map(|value| value.to_string())
        .unwrap_or_else(|| "null".into());
    let route = model.map_or("unavailable", |model| model.presentation_route());
    let failed = model.is_none_or(|model| model.error().is_some());
    let segment = vector_range::authored_ads::gameplay_ads_replay_segment(sim.time);
    format!(
                "{{\"simulation_time\":{},\"segment\":\"{}\",\"route\":\"{}\",\"clip\":\"{}\",\"native_clip_seconds\":{},\"clip_duration\":{},\"direction\":{},\"ads_requested\":{},\"simulation_ads\":{},\"speed\":{},\"grounded\":{},\"sprinting\":{},\"mantling\":{},\"ammo\":{},\"reserve\":{},\"shots\":{},\"reload_left\":{},\"reload_credit_at\":{},\"reload_ready_at\":{},\"renderer_failed\":{},\"walk_weight\":{},\"walk_seconds\":{},\"run_weight\":{},\"walk_min_rate\":{}}}",
                sim.time, segment, route, clip, native, duration, direction, sim.player.ads_requested,
                sim.player.ads, sim.player.speed(), sim.player.grounded, sim.player.sprinting,
                sim.player.mantle.is_some(), sim.player.ammo, sim.player.reserve, sim.stats.shots,
                sim.player.reload_left, sim.player.reload_credit_at, sim.player.reload_ready_at, failed,
                model.map_or(0., |m| m.walk_weight()), model.and_then(|m| m.walk_sample()).map_or("null".into(), |v| v.to_string()),
                model.map_or(0., |m| m.run_weight()), model.map_or(1., |m| m.walk_min_rate()))
}
/// Original gameplay-ADS timing, using capture.rs Display semantics as above.
fn native_time_telemetry(frame: u64, cfg: &Settings) -> String {
    let hz = 60000_f32 / 1001.;
    let elapsed = frame as f32 / hz;
    let duration = 9.0_f32;
    let phase = (elapsed / duration).clamp(0., 1.);
    format!("{{\"elapsed_seconds\":{},\"normalized_phase\":{},\"visual_duration_seconds\":{},\"simulation_ready_seconds\":{},\"sampling_hz\":{}}}",elapsed,phase,duration,cfg.ads_time,hz)
}
/// Preserve the native Display numeric tokens verbatim. Parsing may validate
/// JSON syntax, but Value's f64 parser/serializer must never carry these fields.
fn frame_json_with_native_records(
    outer: serde_json::Value,
    gameplay: String,
    time: String,
) -> String {
    serde_json::from_str::<serde_json::Value>(&gameplay).expect("finite source ADS gameplay JSON");
    serde_json::from_str::<serde_json::Value>(&time).expect("finite source ADS time JSON");
    let mut text = outer.to_string();
    assert_eq!(text.pop(), Some('}'));
    text.push_str(",\"native_gameplay\":");
    text.push_str(&gameplay);
    text.push_str(",\"native_time\":");
    text.push_str(&time);
    text.push('}');
    text
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 6 {
        return Err(
            "usage: source_visibility_geometry_probe MANIFEST SETTINGS opengl|dx12 NEW_JSONL_OUTPUT FRAMES_JSON"
                .into(),
        );
    }
    let backend = match args[3].as_str() {
        "opengl" => Backend::OpenGl,
        "dx12" => Backend::Dx12,
        _ => return Err("unsupported backend profile".into()),
    };
    let requested_frames: Vec<u64> = serde_json::from_slice(&fs::read(&args[5])?)?;
    if requested_frames.is_empty() || requested_frames.iter().any(|&frame| frame >= 553) {
        return Err("invalid fallback frame scope".into());
    }
    let manifest_path = Path::new(&args[1]);
    let manifest = AnimationManifest::load(manifest_path)?;
    let cfg = Settings::load_with_base(&args[2], Settings::m4_candidate());
    assert_eq!(
        (cfg.viewmodel_x, cfg.viewmodel_y, cfg.viewmodel_z),
        (0.2, -0.2, 0.2)
    );
    let mut source_paths = vec![
        manifest.locomotion_asset.clone(),
        manifest.tactical.asset.clone(),
    ];
    if let Some(empty) = &manifest.empty {
        source_paths.push(empty.asset.clone());
    }
    source_paths.sort();
    source_paths.dedup();
    let mut sources: Vec<Source> = Vec::new();
    for path in source_paths {
        let source = Source::load(&path)?;
        for other in &sources {
            if source.checksums == other.checksums
                && (source.skin_bytes != other.skin_bytes
                    || source.rigid_bytes != other.rigid_bytes)
            {
                return Err("ambiguous companion CRC match with differing original bytes".into());
            }
        }
        sources.push(source);
    }
    let mut output = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&args[4])?;
    writeln!(
        output,
        "{}",
        json!({"schema":"rust-duty-source-geometry-probe/v1","source_certificate_schema":"rust-duty-source-visibility-certificate-diagnostic/v2","requested_frames":requested_frames,"original_native_observations":false,"backend_profile":if backend==Backend::OpenGl {"opengl: Projection*Model*position; gamma17"} else {"dx12: CPU (remap*Projection)*Model upload then shader MVP*position; gamma24"},"backend_native_upload_identity_verified":false,"raster_profile":"single sample at pixel center; at least 8 subpixel bits, displacement <=1/256 pixel; no culling; opaque depth winner; no alpha discard; x/y clipping produces coverage identical to the interval-bounded unclipped triangle inside the viewport (both interior and possible support)","fragment_profile":"RGB result differs from exact convex vertex/texture interpolation and multiplication by <=3 byte levels per channel; source texture alpha is overwritten to 255 as in adapter","profile_assumptions_independently_established":false,"scenario":"ads-offset","expected_frames":553,"extent":[960,540],"capture_hz":"60000/1001 as f32","profile":"m4a1","weapon_id":"hk416a5","initial_ammo":12,"horizontal_fov_degrees":76,"near":0.01,"far":5.0,"fixed_dt_bits":format!("{:08x}",FIXED_DT.to_bits()),"native_invocation_binding_verified":false,"numeric_profile":"conditional normal-finite or exact-zero operations, no underflow/flush-to-zero/overflow, relative operation error <=2^-23, equivalent-or-tighter FMA; GL two matrix/vector stages or expanded16terms gamma17; DX12 two CPU four-term matrix products then GPU four-term dot gamma24; outward host allowance","profile_native_verified":false,"source_sha_binding":"requires independently verified before/after SHA256 input receipt","acceptance_verdict":null,"sources":sources.iter().map(|s|json!({"vra":s.path,"companion_crc32":s.checksums,"skin_meshes":s.skin.meshes.len(),"rigid_meshes":s.rigid.meshes.len()})).collect::<Vec<_>>()})
    )?;
    let mut model = authored_viewmodel::AuthoredViewmodel::load_manifest(manifest_path)?;
    let mut sim = Simulation::new();
    sim.player.ammo = 12;
    let h = 76_f32.to_radians();
    let aspect = 16_f32 / 9.;
    let fovy = 2. * ((h * 0.5).tan() / aspect).atan();
    let projection = Mat4::perspective_rh_gl(fovy, aspect, 0.01, 5.);
    let hz = 60000_f32 / 1001.;
    let mut ticks = 0_u64;
    for frame in 0..553 {
        model.set_walk_translation(cfg.walking_translation("hk416a5"));
        let elapsed = frame as f32 / hz;
        let target = vector_range::clock::capture_tick_target(frame, hz as u32);
        while target.map_or(
            sim.time + f64::from(FIXED_DT) <= f64::from(elapsed) + 1e-7,
            |target| ticks < target,
        ) {
            let start = sim.time;
            sim.update(
                vector_range::authored_ads::gameplay_ads_replay_input(start),
                &cfg,
                FIXED_DT,
            );
            ticks += 1;
            model.committed_step(start, &sim);
        }
        if let Some(error) = model.error() {
            return Err(error.into());
        }
        if !requested_frames.contains(&frame) {
            continue;
        }
        let root = weapon_sway::compose(
            cfg.viewmodel_offset(model.visual_ads_amount()),
            &[
                weapon_sway::LayerOffset::default(),
                weapon_sway::action_offset(
                    &sim.player,
                    &sim.action_pose(),
                    cfg.action.obstruct_max_retract,
                ),
            ],
        );
        model.set_cant(sim.player.cant_visual() * cfg.action.cant_angle.to_radians());
        let snapshot = model.source_pose_snapshot(sim.time, root)?;
        let source = sources
            .iter()
            .find(|s| s.checksums == snapshot.animation.companion_checksums())
            .ok_or("source companion inventory missing")?;
        let palette = snapshot.animation.skin_palette(
            &snapshot.pose,
            &source.skin.bones,
            game_model_root(),
        )?;
        let matrices = snapshot
            .animation
            .actor_matrices(&snapshot.pose, game_model_root())?;
        let actors = snapshot.animation.actors();
        if let Some(opacity) = &snapshot.actor_opacity {
            if opacity.len() != actors.len() || opacity.iter().any(|v| !v.is_finite()) {
                return Err("invalid source actor opacity".into());
            }
        }
        let lighting = SceneLighting::range().in_view(sim.player.direction());
        let normals: Vec<_> = palette.iter().map(|m| m.inverse().transpose()).collect();
        let mut inventory = Inventory::new();
        for (index, part) in source.skin.meshes.iter().enumerate() {
            let positions: Vec<_> = part
                .vertices
                .iter()
                .map(|vertex| {
                    let mut p = Vec3::ZERO;
                    for (&joint, &weight) in vertex.joints.iter().zip(&vertex.weights) {
                        if weight > 0. {
                            p += palette[joint as usize]
                                .transform_point3(Vec3::from_array(vertex.position))
                                * weight;
                        }
                    }
                    snapshot.root.transform_point3(p)
                })
                .collect();
            let colors: Vec<[u8; 4]> = part
                .vertices
                .iter()
                .map(|vertex| {
                    let mut n = Vec3::ZERO;
                    for (&joint, &weight) in vertex.joints.iter().zip(&vertex.weights) {
                        if weight > 0. {
                            n += normals[joint as usize]
                                .transform_vector3(Vec3::from_array(vertex.normal))
                                * weight;
                        }
                    }
                    n = snapshot
                        .root
                        .transform_vector3(n)
                        .try_normalize()
                        .unwrap_or(Vec3::Y);
                    let shade = lighting.irradiance(n);
                    Color::new(
                        part.base_color[0] * shade,
                        part.base_color[1] * shade,
                        part.base_color[2] * shade,
                        1.,
                    )
                    .into()
                })
                .collect();
            inventory.mesh(
                "skin",
                index,
                &part.indices,
                &positions,
                &colors,
                texture_bounds(&part.rgba),
                projection,
                Mat4::IDENTITY,
                backend,
                true,
                1.,
            );
        }
        let mut ownership = vec![0_u32; source.rigid.meshes.len()];
        let mut hidden_triangles = 0;
        for (actor_index, actor) in actors.iter().enumerate() {
            for &index in &actor.mesh_indices {
                if index >= ownership.len() {
                    return Err("actor source index out of range".into());
                }
                ownership[index] += 1;
                let part = &source.rigid.meshes[index];
                let visible = snapshot.pose.actor_visible[actor_index];
                if !visible {
                    hidden_triangles += part.indices.len() / 3;
                }
                let positions: Vec<_> = part
                    .vertices
                    .iter()
                    .map(|v| Vec3::from_array(v.position))
                    .collect();
                let alpha = snapshot
                    .actor_opacity
                    .as_ref()
                    .map_or(1., |v| v[actor_index])
                    .clamp(0., 1.);
                let normal_matrix = (snapshot.root * matrices[actor_index])
                    .inverse()
                    .transpose();
                let colors: Vec<[u8; 4]> = part
                    .vertices
                    .iter()
                    .map(|v| {
                        let mut color: [u8; 4] = lighting
                            .shade(
                                Color::new(
                                    part.base_color[0],
                                    part.base_color[1],
                                    part.base_color[2],
                                    1.,
                                ),
                                normal_matrix.transform_vector3(Vec3::from_array(v.normal)),
                            )
                            .into();
                        color[3] = (alpha * 255.).round() as u8;
                        color
                    })
                    .collect();
                inventory.mesh(
                    "rigid",
                    index,
                    &part.indices,
                    &positions,
                    &colors,
                    texture_bounds(&part.rgba),
                    projection,
                    snapshot.root * matrices[actor_index],
                    backend,
                    visible,
                    alpha,
                );
            }
        }
        if ownership.iter().any(|&count| count != 1) {
            return Err("source rigid mesh missing or multiply owned".into());
        }
        let expected: usize = source
            .skin
            .meshes
            .iter()
            .map(|m| m.indices.len() / 3)
            .chain(source.rigid.meshes.iter().map(|m| m.indices.len() / 3))
            .sum();
        assert_eq!(inventory.triangles, expected);
        let unresolved = expected - inventory.outside_bottom - hidden_triangles;
        let samples = inventory.samples.as_ref().unwrap();
        let required = samples.required();
        let required_count = required.iter().filter(|&&v| v != 0).count();
        let possible_count = samples.possible.iter().filter(|&&v| v != 0).count();
        writeln!(
            output,
            "{}",
            frame_json_with_native_records(
                json!({"geometry_domain":inventory.geometry_domain,"triangle_trace":inventory.triangle_trace,"original_native_observations":false,"frame":frame,"committed_tick":ticks,"time":sim.time,"route":model.presentation_route(),"visual_ads":model.visual_ads_amount(),"ammo":sim.player.ammo,"shots":sim.stats.shots,"companion_catalog_vra":source.path,"companion_crc32":source.checksums,"source_triangles":expected,"outside_bottom":inventory.outside_bottom,"hidden_source_triangles":hidden_triangles,"unclassified_triangles":unresolved,"classification":if unresolved==0 {"expected_empty_under_profile"}else{"potentially_visible_unresolved"},"maximum_bottom_upper":inventory.maximum_bottom_upper,"meshes":inventory.meshes,"unsupported_clip_triangles":samples.unsupported,"possible_support_complete":samples.unsupported==0,"required_contrast_samples":required_count,"possible_samples":possible_count,"required_contrast_runs":runs(&required),"possible_support_runs":runs(&samples.possible),"acceptance_verdict":null}),
                native_gameplay_telemetry(Some(&model), &sim),
                native_time_telemetry(frame, &cfg)
            )
        )?;
        if frame % 50 == 0 {
            eprintln!(
                "source frame {frame}: {} outside, {unresolved} unclassified, {required_count}/{possible_count} required/possible samples",
                inventory.outside_bottom
            );
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    fn pixel_triangle(points: [[f64; 2]; 3]) -> [[Bound; 4]; 3] {
        points.map(|p| {
            [
                Bound::point(p[0] / 480. - 1.),
                Bound::point(1. - p[1] / 270.),
                Bound::point(0.),
                Bound::point(1.),
            ]
        })
    }
    #[test]
    fn robust_samples_exclude_witness_and_unsafe_occluders() {
        let triangle = pixel_triangle([[100., 100.], [120., 100.], [100., 120.]]);
        let mut samples = Samples::new();
        samples.triangle(triangle, true);
        assert_eq!(samples.required()[105 * WIDTH + 105], 1);
        samples.triangle(triangle, false);
        assert!(samples.required().iter().all(|&v| v == 0));
        let mut witness = Samples::new();
        witness.triangle(pixel_triangle([[0., 0.], [63., 0.], [0., 21.]]), true);
        assert!(witness.required().iter().all(|&v| v == 0));
    }
    #[test]
    fn source_sliver_requires_interior_center_and_no_area_heuristic() {
        let mut samples = Samples::new();
        samples.triangle(
            pixel_triangle([[100., 100.2], [103., 100.2], [101.5, 100.9]]),
            true,
        );
        assert_eq!(samples.required()[100 * WIDTH + 101], 1);
        let mut tiny = Samples::new();
        tiny.triangle(
            pixel_triangle([[100.01, 100.01], [100.1, 100.01], [100.01, 100.1]]),
            true,
        );
        assert!(tiny.required().iter().all(|&v| v == 0));
    }
    #[test]
    fn unsupported_clipping_fails_closed_but_separated_triangles_do_not() {
        let good = pixel_triangle([[100., 100.], [120., 100.], [100., 120.]]);
        let mut samples = Samples::new();
        samples.triangle(good, true);
        let mut crossing = good;
        crossing[0][2] = Bound::point(-2.);
        samples.triangle(crossing, true);
        assert_eq!(samples.unsupported, 1);
        assert!(samples.required().iter().all(|&v| v == 0));
        let mut outside = Samples::new();
        outside.triangle(
            pixel_triangle([[100., 600.], [120., 600.], [100., 620.]]),
            true,
        );
        assert_eq!(outside.unsupported, 0);
        assert!(outside.possible.iter().all(|&v| v == 0));
    }
    #[test]
    fn opaque_color_envelope_requires_the_declared_error_margin() {
        assert!(contrast([[0, 0, 0, 255]; 3], [[255, 255]; 3]));
        assert!(!contrast([[36, 48, 61, 255]; 3], [[255, 255]; 3]));
        assert!(!contrast([[0, 0, 0, 254]; 3], [[255, 255]; 3]));
        assert!(!contrast([[255, 255, 255, 255]; 3], [[0, 255]; 3]));
        assert!(!contrast([[36 + 11, 48, 61, 255]; 3], [[255, 255]; 3]));
        assert!(contrast([[36 + 12, 48, 61, 255]; 3], [[255, 255]; 3]));
    }
    fn number_token<'a>(record: &'a str, key: &str) -> &'a str {
        record
            .split(&format!("\"{key}\":"))
            .nth(1)
            .unwrap()
            .split([',', '}'])
            .next()
            .unwrap()
    }
    #[test]
    fn native_time_uses_original_cadence_and_display_without_rate_rounding() {
        let cfg = Settings::m4_candidate();
        let zero = native_time_telemetry(0, &cfg);
        assert_eq!(number_token(&zero, "elapsed_seconds"), "0");
        assert_eq!(number_token(&zero, "visual_duration_seconds"), "9");
        let record = native_time_telemetry(16, &cfg);
        assert_eq!(
            number_token(&record, "elapsed_seconds"),
            (16_f32 / (60000_f32 / 1001.)).to_string()
        );
        assert_eq!(number_token(&record, "sampling_hz"), "59.94006");
        assert_ne!(
            number_token(&record, "elapsed_seconds"),
            (16_f64 / 60.).to_string()
        );
        assert_eq!(
            number_token(&native_time_telemetry(552, &cfg), "normalized_phase"),
            "1"
        );
    }
    #[test]
    fn native_gameplay_fractional_f32_preserves_emitted_display_tokens() {
        let cfg = Settings::m4_candidate();
        let mut sim = Simulation::new();
        for fraction in [
            0.1_f32,
            0.12345679,
            0.33333334,
            0.99999994,
            0.00000011920929,
        ] {
            sim.player.ads = fraction;
            let wire = frame_json_with_native_records(
                json!({"frame":0}),
                native_gameplay_telemetry(None, &sim),
                native_time_telemetry(0, &cfg),
            );
            assert_eq!(number_token(&wire, "simulation_ads"), fraction.to_string());
        }
    }
    #[test]
    fn emitted_f64_clocks_never_round_trip_through_json_values() {
        let cfg = Settings::m4_candidate();
        let mut sim = Simulation::new();
        for tick in 0..1201 {
            let wire = frame_json_with_native_records(
                json!({"frame":tick}),
                native_gameplay_telemetry(None, &sim),
                native_time_telemetry(tick, &cfg),
            );
            assert_eq!(number_token(&wire, "simulation_time"), sim.time.to_string());
            assert_eq!(
                number_token(&wire, "elapsed_seconds"),
                (tick as f32 / (60000_f32 / 1001.)).to_string()
            );
            serde_json::from_str::<serde_json::Value>(&wire).unwrap();
            if tick == 14 {
                assert_eq!(
                    number_token(&wire, "simulation_time"),
                    "0.11666667275130749"
                );
            }
            if tick == 28 {
                assert_eq!(
                    number_token(&wire, "simulation_time"),
                    "0.23333334550261497"
                );
            }
            sim.time += f64::from(FIXED_DT);
        }
    }
    #[test]
    fn clip_interval_contains_both_matrix_associations_for_bounded_original_inputs() {
        let mut state = 17_u64;
        let mut next = || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
            ((state >> 32) as u32 as f32 / u32::MAX as f32) * 4. - 2.
        };
        for _ in 0..10000 {
            let a = Mat4::from_cols_array(&std::array::from_fn(|_| next()));
            let b = Mat4::from_cols_array(&std::array::from_fn(|_| next()));
            let p = Vec3::new(next(), next(), next());
            let x = ((a * b) * p.extend(1.)).to_array();
            let y = (a * (b * p.extend(1.))).to_array();
            for row in 0..4 {
                let [lo, hi] = ClipRow::new(a, b, row).interval(p);
                for v in [x[row], y[row]] {
                    assert!(lo <= f64::from(v) && f64::from(v) <= hi);
                }
            }
        }
    }
    #[test]
    fn dx12_interval_contains_production_cpu_upload_and_shader_dot() {
        let mut state = 31_u64;
        let mut next = || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
            ((state >> 32) as u32 as f32 / u32::MAX as f32) * 4. - 2.
        };
        for _ in 0..10000 {
            let p = Mat4::from_cols_array(&std::array::from_fn(|_| next()));
            let m = Mat4::from_cols_array(&std::array::from_fn(|_| next()));
            let v = Vec3::new(next(), next(), next());
            let actual = ((dx12_remap() * p * m) * v.extend(1.)).to_array();
            for r in 0..4 {
                let [lo, hi] = ClipRow::dx12(p, m, r).interval(v);
                assert!(lo <= f64::from(actual[r]) && f64::from(actual[r]) <= hi);
            }
        }
    }
    #[test]
    fn strict_bottom_plane_rejects_touching_or_crossing_as_exclusion() {
        let ids = [0, 1, 2];
        let projection = Mat4::IDENTITY;
        for (points, expected) in [
            ([Vec3::new(0., -2., 0.); 3], 1),
            ([Vec3::new(0., -1., 0.); 3], 0),
            (
                [Vec3::new(0., -2., 0.), Vec3::ZERO, Vec3::new(1., -2., 0.)],
                0,
            ),
        ] {
            let mut out = Inventory::new();
            out.mesh(
                "fixture",
                0,
                &ids,
                &points,
                &[[255; 4]; 3],
                [[255; 2]; 3],
                projection,
                Mat4::IDENTITY,
                Backend::OpenGl,
                true,
                1.,
            );
            assert_eq!(out.outside_bottom, expected);
        }
    }
}
