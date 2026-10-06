//! Bounded later DX12/WARP corroboration of source-declared sample sets.
//!
//! No candidate capture is read. Required/possible masks must equal the pinned
//! original source JSONL before a GPU is initialized. This does not change any
//! original diagnostic flag or establish universal shader/raster correctness.
use super::{
    arena::{clip_matrix, DrawSlice, FrameArena, GpuVertex},
    device::{BackendSelection, Gpu},
    mesh::{FragmentKind, FrameGeometry, Pipelines},
    target::{GpuTexture, COLOR_FORMAT},
};
use crate::{
    asset::WeaponAsset,
    draw::{BlendMode, RenderTarget, Sampler, Texture, Vertex},
};
use glam::{Mat4, Vec2, Vec3, Vec4};
use rust_duty_launcher::{bytes_hash, file_hash};
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    sync::mpsc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

pub(super) const COVERAGE_SHADER: &str =
    "@fragment fn fs_coverage() -> @location(0) vec4<f32> { return vec4<f32>(1.0); }";
const WIDTH: u32 = 960;
const HEIGHT: u32 = 540;
const PIXELS: usize = WIDTH as usize * HEIGHT as usize;
const ORIGINAL: &str = "cba85f192290beb1686c35b11bc923b1eeb4a1ca2c855f71c273e62c1d9aa896";
const RECEIPT: &str = "241bb21d23bb711daaff9dac33b75b504e1c69104fa0949099b38f0f86453370";
const BATCH: usize = 128;
// The reviewed fallback set, not all visible animation states. Its membership
// was fixed by the original capture's ordinary checks before this probe existed.
const FINITE_FRAMES: [usize; 50] = [
    17, 18, 19, 20, 58, 59, 60, 61, 77, 78, 79, 80, 81, 82, 83, 84, 85, 163, 164, 165, 170, 171,
    172, 173, 174, 175, 176, 177, 178, 179, 216, 217, 258, 259, 315, 316, 317, 318, 319, 320, 321,
    322, 414, 415, 467, 468, 469, 517, 518, 519,
];

type Result<T> = std::result::Result<T, String>;
fn error<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}
fn ensure(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn hash_file(path: &Path) -> Result<String> {
    file_hash(path).map_err(error)
}
fn json_bytes(value: &Value) -> Result<Vec<u8>> {
    serde_json::to_vec(value).map_err(error)
}
fn usize_at(v: &Value) -> Result<usize> {
    v.as_u64()
        .and_then(|n| n.try_into().ok())
        .ok_or_else(|| "expected nonnegative integer".into())
}
fn array<const N: usize>(v: &Value) -> Result<&[Value; N]> {
    v.as_array()
        .and_then(|a| a.as_slice().try_into().ok())
        .ok_or_else(|| format!("expected array of {N}"))
}
fn bits<const N: usize>(v: &Value) -> Result<[f32; N]> {
    let values = array::<N>(v)?;
    let mut out = [0.; N];
    for (dst, src) in out.iter_mut().zip(values) {
        let n: u32 = usize_at(src)?.try_into().map_err(error)?;
        *dst = f32::from_bits(n);
    }
    ensure(out.iter().all(|v| v.is_finite()), "nonfinite source f32")?;
    Ok(out)
}
fn read_rows(path: &Path) -> Result<Vec<Value>> {
    BufReader::new(File::open(path).map_err(error)?)
        .lines()
        .map(|l| serde_json::from_str(&l.map_err(error)?).map_err(error))
        .collect()
}
fn mask(v: &Value) -> Result<Vec<u8>> {
    let mut result = vec![0; PIXELS];
    let mut previous = 0;
    for run in v.as_array().ok_or("missing mask runs")? {
        let pair = array::<2>(run)?;
        let start = usize_at(&pair[0])?;
        let count = usize_at(&pair[1])?;
        let end = start.checked_add(count).ok_or("mask overflow")?;
        ensure(
            count > 0 && start >= previous && end <= PIXELS,
            "invalid or overlapping mask runs",
        )?;
        result[start..end].fill(1);
        previous = end;
    }
    Ok(result)
}
fn witness(i: usize) -> bool {
    i % (WIDTH as usize) < 64 && i / (WIDTH as usize) < 22
}

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
    fn sub(self, b: Self) -> Self {
        Self::new(self.lo - b.hi, self.hi - b.lo)
    }
    fn mul(self, b: Self) -> Self {
        let a = [
            self.lo * b.lo,
            self.lo * b.hi,
            self.hi * b.lo,
            self.hi * b.hi,
        ];
        Self::new(
            a.into_iter().fold(f64::INFINITY, f64::min),
            a.into_iter().fold(f64::NEG_INFINITY, f64::max),
        )
    }
}
fn edge(a: [Bound; 2], b: [Bound; 2], p: [Bound; 2]) -> Bound {
    b[0].sub(a[0])
        .mul(p[1].sub(a[1]))
        .sub(b[1].sub(a[1]).mul(p[0].sub(a[0])))
}
#[derive(Clone)]
struct Triangle {
    key: [usize; 3], // mesh, original triangle, source inventory ordinal
    vertices: [Vertex; 3],
    transform: Mat4,
    colors: [[u8; 4]; 3],
    possible: Vec<usize>,
    robust: Vec<usize>,
    required: Vec<usize>,
    safe: bool,
    source_sha256: String,
}
fn source_safe(colors: [[u8; 4]; 3]) -> bool {
    colors.iter().all(|c| c[3] == 255)
        && (0..3).any(|c| {
            let lo = i32::from(colors.iter().map(|v| v[c]).min().unwrap());
            let hi = i32::from(colors.iter().map(|v| v[c]).max().unwrap());
            [36, 48, 61][c] - hi > 11 || lo - [36, 48, 61][c] > 11
        })
}
fn triangle(
    value: &Value,
    ordinal: usize,
    asset: &WeaponAsset,
    required: &[u8],
) -> Result<Triangle> {
    ensure(
        value["kind"] == "rigid",
        "finite fixture admits only white-textured rigid triangles",
    )?;
    let mesh_id = usize_at(&value["mesh"])?;
    let triangle_id = usize_at(&value["triangle"])?;
    let mesh = asset.meshes.get(mesh_id).ok_or("source mesh missing")?;
    ensure(
        mesh.rgba.is_empty()
            && value["texture_bounds"] == json!([[255, 255], [255, 255], [255, 255]]),
        "nonwhite source texture outside finite scope",
    )?;
    let source_indices = array::<3>(&value["indices"])?;
    let positions = array::<3>(&value["position_bits"])?;
    let color_values = array::<3>(&value["colors"])?;
    let mut vertices = [Vertex {
        position: Vec3::ZERO,
        uv: Vec2::ZERO,
        color: [0; 4],
        normal: Vec4::ZERO,
    }; 3];
    let mut colors = [[0; 4]; 3];
    for i in 0..3 {
        let index = usize_at(&source_indices[i])?;
        ensure(
            mesh.indices
                .get(
                    triangle_id
                        .checked_mul(3)
                        .ok_or("triangle offset overflow")?
                        + i,
                )
                .copied()
                == Some(index.try_into().map_err(error)?),
            "missing/reordered source triangle index",
        )?;
        let src = mesh.vertices.get(index).ok_or("source vertex missing")?;
        let position = bits::<3>(&positions[i])?;
        ensure(
            position.map(f32::to_bits) == src.position.map(f32::to_bits),
            "source position bits differ from bound VRM",
        )?;
        for (dst, v) in colors[i].iter_mut().zip(array::<4>(&color_values[i])?) {
            *dst = usize_at(v)?.try_into().map_err(error)?;
        }
        vertices[i] = Vertex {
            position: Vec3::from_array(position),
            uv: Vec2::from_array(src.uv),
            color: colors[i],
            normal: Vec3::from_array(src.normal).extend(0.),
        };
    }
    let safe = source_safe(colors);
    ensure(
        value["safe_contrast"] == safe,
        "source contrast declaration differs from exact vertex bytes",
    )?;
    let projection = Mat4::from_cols_array(&bits::<16>(&value["projection_bits"])?);
    let model = Mat4::from_cols_array(&bits::<16>(&value["model_bits"])?);
    let transform = clip_matrix(projection, model);
    ensure(transform.is_finite(), "nonfinite production upload matrix")?;
    let mut screen = [[Bound::point(0.); 2]; 3];
    for (dst, v) in screen.iter_mut().zip(array::<3>(&value["screen"])?) {
        for (dst, v) in dst.iter_mut().zip(array::<2>(v)?) {
            let pair = array::<2>(v)?;
            let lo = pair[0]
                .as_f64()
                .filter(|v| v.is_finite())
                .ok_or("invalid screen lower")?;
            let hi = pair[1]
                .as_f64()
                .filter(|v| v.is_finite())
                .ok_or("invalid screen upper")?;
            ensure(lo <= hi, "inverted source screen interval")?;
            *dst = Bound { lo, hi };
        }
    }
    let bounds = |axis: usize, limit: u32| -> (u32, u32) {
        (
            screen
                .iter()
                .map(|v| v[axis].lo)
                .fold(f64::INFINITY, f64::min)
                .floor()
                .clamp(0., f64::from(limit)) as u32,
            screen
                .iter()
                .map(|v| v[axis].hi)
                .fold(f64::NEG_INFINITY, f64::max)
                .ceil()
                .clamp(0., f64::from(limit)) as u32,
        )
    };
    let (minx, maxx) = bounds(0, WIDTH);
    let (miny, maxy) = bounds(1, HEIGHT);
    let mut possible = Vec::new();
    let mut robust = Vec::new();
    let mut retained = Vec::new();
    for y in miny..maxy {
        for x in minx..maxx {
            let index = (y * WIDTH + x) as usize;
            if witness(index) {
                continue;
            }
            let p = [
                Bound::point(f64::from(x) + 0.5),
                Bound::point(f64::from(y) + 0.5),
            ];
            let e = [
                edge(screen[0], screen[1], p),
                edge(screen[1], screen[2], p),
                edge(screen[2], screen[0], p),
            ];
            if e.iter().all(|v| v.hi >= 0.) || e.iter().all(|v| v.lo <= 0.) {
                possible.push(index);
                if required[index] != 0 {
                    retained.push(index);
                }
                if e.iter().all(|v| v.lo > 0.) || e.iter().all(|v| v.hi < 0.) {
                    robust.push(index);
                }
            }
        }
    }
    Ok(Triangle {
        key: [mesh_id, triangle_id, ordinal],
        vertices,
        transform,
        colors,
        possible,
        robust,
        required: retained,
        safe,
        source_sha256: bytes_hash(&json_bytes(value)?),
    })
}
struct Frame {
    id: usize,
    required: Vec<u8>,
    possible: Vec<u8>,
    triangles: Vec<Triangle>,
    source_sha256: String,
}
fn load_frame(
    trace: &Value,
    original: &Value,
    assets: &BTreeMap<u32, WeaponAsset>,
) -> Result<Frame> {
    for key in [
        "frame",
        "required_contrast_runs",
        "possible_support_runs",
        "required_contrast_samples",
        "possible_samples",
        "committed_tick",
        "visual_ads",
        "ammo",
        "shots",
        "route",
    ] {
        ensure(
            trace[key] == original[key],
            &format!("trace differs from pinned source at {key}"),
        )?;
    }
    ensure(
        trace["possible_support_complete"] == true && trace["unsupported_clip_triangles"] == 0,
        "incomplete source support",
    )?;
    let required = mask(&original["required_contrast_runs"])?;
    let possible = mask(&original["possible_support_runs"])?;
    ensure(
        required.iter().zip(&possible).all(|(&a, &b)| a <= b),
        "required mask exceeds possible",
    )?;
    let crc: u32 = usize_at(&array::<2>(&trace["companion_crc32"])?[1])?
        .try_into()
        .map_err(error)?;
    let asset = assets
        .get(&crc)
        .ok_or("source companion CRC absent from bound VRM set")?;
    let values = trace["triangle_trace"]
        .as_array()
        .ok_or("trace inventory missing")?;
    let triangles = values
        .iter()
        .enumerate()
        .map(|(i, v)| triangle(v, i, asset, &required))
        .collect::<Result<Vec<_>>>()?;
    let mut keys = BTreeSet::new();
    let mut union = vec![0; PIXELS];
    let mut robust = vec![0; PIXELS];
    let mut unsafe_color = vec![0; PIXELS];
    for triangle in &triangles {
        ensure(
            keys.insert((triangle.key[0], triangle.key[1])),
            "duplicate source triangle",
        )?;
        for &i in &triangle.possible {
            union[i] = 1;
            if !triangle.safe {
                unsafe_color[i] = 1;
            }
        }
        if triangle.safe {
            for &i in &triangle.robust {
                robust[i] = 1;
            }
        }
    }
    for (i, v) in robust.iter_mut().enumerate() {
        *v &= 1 - unsafe_color[i];
    }
    ensure(
        union == possible,
        "complete traced triangle support differs from pinned possible mask",
    )?;
    ensure(
        robust == required,
        "complete traced triangle support differs from pinned required mask",
    )?;
    ensure(
        triangles
            .iter()
            .filter(|t| !t.required.is_empty())
            .all(|t| t.safe),
        "unsafe possible winner overlaps required mask",
    )?;
    Ok(Frame {
        id: usize_at(&trace["frame"])?,
        required,
        possible,
        triangles,
        source_sha256: bytes_hash(&json_bytes(trace)?),
    })
}
#[derive(Clone, Copy, Debug)]
struct Rect {
    x: u32,
    y: u32,
    w: u32,
    h: u32,
}
impl Rect {
    fn full() -> Self {
        Self {
            x: 0,
            y: 0,
            w: WIDTH,
            h: HEIGHT,
        }
    }
    fn samples(samples: &[usize]) -> Option<Self> {
        if samples.is_empty() {
            return None;
        }
        let minx = samples.iter().map(|i| (*i % WIDTH as usize) as u32).min()?;
        let maxx = samples.iter().map(|i| (*i % WIDTH as usize) as u32).max()?;
        let miny = samples.iter().map(|i| (*i / WIDTH as usize) as u32).min()?;
        let maxy = samples.iter().map(|i| (*i / WIDTH as usize) as u32).max()?;
        Some(Self {
            x: minx,
            y: miny,
            w: maxx - minx + 1,
            h: maxy - miny + 1,
        })
    }
    fn stride(self) -> u32 {
        (self.w * 4).div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT)
            * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT
    }
    fn bytes(self) -> u64 {
        u64::from(self.stride()) * u64::from(self.h)
    }
    fn offset(self, index: usize) -> usize {
        (index / WIDTH as usize - self.y as usize) * self.stride() as usize
            + (index % WIDTH as usize - self.x as usize) * 4
    }
}
fn verify_coverage(pixels: &[u8], required: &[u8], possible: &[u8]) -> Result<usize> {
    ensure(pixels.len() == PIXELS * 4, "union coverage extent mismatch")?;
    let mut count = 0;
    for (i, &p) in pixels.as_chunks::<4>().0.iter().enumerate() {
        ensure(
            p == [0, 0, 0, 0] || p == [255, 255, 255, 255],
            "coverage-only output is not binary",
        )?;
        if witness(i) {
            continue;
        }
        let covered = p[3] != 0;
        ensure(
            !covered || possible[i] != 0,
            "native coverage escaped predeclared possible mask",
        )?;
        ensure(
            required[i] == 0 || covered,
            "native coverage omitted predeclared required sample",
        )?;
        count += usize::from(covered);
    }
    Ok(count)
}
fn verify_color(t: &Triangle, rect: Rect, coverage: &[u8], color: &[u8]) -> Result<usize> {
    verify_color_with_clear(t, rect, coverage, color, [0, 0, 0, 0])
}
fn verify_color_with_clear(
    t: &Triangle,
    rect: Rect,
    coverage: &[u8],
    color: &[u8],
    clear: [u8; 4],
) -> Result<usize> {
    ensure(
        coverage.len() == rect.bytes() as usize && color.len() == coverage.len(),
        "isolated readback extent mismatch",
    )?;
    let mut count = 0;
    for &sample in &t.required {
        let offset = rect.offset(sample);
        let coverage = &coverage[offset..offset + 4];
        let color = &color[offset..offset + 4];
        ensure(
            coverage == [0, 0, 0, 0] || coverage == [255, 255, 255, 255],
            "isolated coverage is not binary",
        )?;
        if coverage[3] == 0 {
            ensure(
                color == clear,
                "fragment support differs between original and coverage PS",
            )?;
            continue;
        }
        ensure(color[3] == 255, "original fragment output is not opaque")?;
        for c in 0..3 {
            let lo = t
                .colors
                .iter()
                .map(|p| p[c])
                .min()
                .unwrap()
                .saturating_sub(3);
            let hi = t
                .colors
                .iter()
                .map(|p| p[c])
                .max()
                .unwrap()
                .saturating_add(3);
            ensure((lo..=hi).contains(&color[c]),"original fragment output escaped source RGB convex envelope plus/minus three bytes")?;
        }
        count += 1;
    }
    Ok(count)
}
fn verify_inventory(
    expected: &BTreeSet<[usize; 3]>,
    observed: &BTreeSet<[usize; 3]>,
) -> Result<()> {
    ensure(expected == observed, "missing/extra isolated draw receipt")
}
fn draw_digest(t: &Triangle, arena: &FrameArena, slice: &DrawSlice) -> Result<Value> {
    let [vertices, indices, matrices] = arena.buffer_contents().ok_or("empty upload")?;
    let v = &vertices[slice.vertices.start as usize..slice.vertices.end as usize];
    let i = &indices[slice.indices.start as usize..slice.indices.end as usize];
    let m = &matrices[slice.matrix_offset as usize..slice.matrix_offset as usize + 64];
    let mut expected = Vec::new();
    for vertex in t.vertices {
        GpuVertex::from(vertex).append_bytes(&mut expected);
    }
    let matrix = t
        .transform
        .to_cols_array()
        .into_iter()
        .flat_map(f32::to_le_bytes)
        .collect::<Vec<_>>();
    ensure(
        v == expected && i == [0, 0, 1, 0, 2, 0] && m == matrix,
        "diagnostic upload changed source vertices/index remap/matrix",
    )?;
    Ok(
        json!({"key":t.key,"source_triangle_sha256":t.source_sha256,"vertices_sha256":bytes_hash(v),"indices_sha256":bytes_hash(i),"matrix_sha256":bytes_hash(m),"color_sha256":bytes_hash(&t.colors.concat()),"original_native_upload":false,"index_remap":[0,1,2]}),
    )
}
fn geometry(
    frame: &Frame,
    gpu: &Gpu,
    pipelines: &Pipelines,
) -> Result<(FrameGeometry, Vec<DrawSlice>, Vec<Value>)> {
    let limits = gpu.device.limits();
    let mut arena = FrameArena::new(
        limits.min_uniform_buffer_offset_alignment,
        limits.max_buffer_size,
    )?;
    let mut slices = Vec::new();
    let mut receipts = Vec::new();
    for t in &frame.triangles {
        let slice = arena
            .try_append(&t.vertices, &[0, 1, 2], t.transform)?
            .ok_or("finite frame exceeds a production upload chunk")?;
        receipts.push(draw_digest(t, &arena, &slice)?);
        slices.push(slice);
    }
    Ok((
        pipelines
            .upload_geometry(&gpu.device, &arena)
            .ok_or("empty finite geometry")?,
        slices,
        receipts,
    ))
}
fn pass(
    encoder: &mut wgpu::CommandEncoder,
    target: &GpuTexture,
    pipeline: &wgpu::RenderPipeline,
    geometry: &FrameGeometry,
    slices: &[DrawSlice],
    white: &GpuTexture,
    rect: Rect,
) {
    pass_clear(
        encoder,
        target,
        pipeline,
        geometry,
        slices,
        white,
        rect,
        wgpu::Color::TRANSPARENT,
    );
}
// Keep the explicit render-pass state visible at this diagnostic boundary.
#[allow(clippy::too_many_arguments)]
fn pass_clear(
    encoder: &mut wgpu::CommandEncoder,
    target: &GpuTexture,
    pipeline: &wgpu::RenderPipeline,
    geometry: &FrameGeometry,
    slices: &[DrawSlice],
    white: &GpuTexture,
    rect: Rect,
    clear: wgpu::Color,
) {
    let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
        label: Some("later finite isolated triangle"),
        color_attachments: &[Some(wgpu::RenderPassColorAttachment {
            view: &target.view,
            depth_slice: None,
            resolve_target: None,
            ops: wgpu::Operations {
                load: wgpu::LoadOp::Clear(clear),
                store: wgpu::StoreOp::Store,
            },
        })],
        ..Default::default()
    });
    pass.set_pipeline(pipeline);
    pass.set_viewport(0., 0., WIDTH as f32, HEIGHT as f32, 0., 1.);
    // This only restricts observations to source-predetermined sample rectangles;
    // vertex arithmetic and the full-size viewport remain identical.
    pass.set_scissor_rect(rect.x, rect.y, rect.w, rect.h);
    pass.set_bind_group(1, &white.binding, &[]);
    for slice in slices {
        pass.set_bind_group(0, &geometry.transform, &[slice.matrix_offset]);
        pass.set_vertex_buffer(0, geometry.vertices.slice(slice.vertices.clone()));
        pass.set_index_buffer(
            geometry.indices.slice(slice.indices.clone()),
            wgpu::IndexFormat::Uint16,
        );
        pass.draw_indexed(0..slice.count, 0, 0..1);
    }
}
fn copy(
    encoder: &mut wgpu::CommandEncoder,
    texture: &wgpu::Texture,
    buffer: &wgpu::Buffer,
    rect: Rect,
    offset: u64,
) {
    encoder.copy_texture_to_buffer(
        wgpu::TexelCopyTextureInfo {
            texture,
            mip_level: 0,
            origin: wgpu::Origin3d {
                x: rect.x,
                y: rect.y,
                z: 0,
            },
            aspect: wgpu::TextureAspect::All,
        },
        wgpu::TexelCopyBufferInfo {
            buffer,
            layout: wgpu::TexelCopyBufferLayout {
                offset,
                bytes_per_row: Some(rect.stride()),
                rows_per_image: Some(rect.h),
            },
        },
        wgpu::Extent3d {
            width: rect.w,
            height: rect.h,
            depth_or_array_layers: 1,
        },
    );
}
fn buffer(device: &wgpu::Device, size: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("finite compact observations"),
        size,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    })
}
fn read(gpu: &Gpu, buffer: &wgpu::Buffer) -> Result<Vec<u8>> {
    let (tx, rx) = mpsc::sync_channel(1);
    buffer.slice(..).map_async(wgpu::MapMode::Read, move |r| {
        let _ = tx.send(r);
    });
    gpu.device
        .poll(wgpu::PollType::Wait {
            submission_index: None,
            timeout: Some(Duration::from_secs(60)),
        })
        .map_err(error)?;
    rx.recv_timeout(Duration::from_secs(1))
        .map_err(error)?
        .map_err(error)?;
    let view = buffer.slice(..).get_mapped_range().map_err(error)?;
    let result = view.to_vec();
    drop(view);
    buffer.unmap();
    gpu.check_errors()?;
    Ok(result)
}
// The support guard discards ONLY independently allowed samples. Binary native
// occlusion must be zero. It closes the gap that aggregate coverage alone cannot:
// an individual triangle may not escape its own support into another's support.
const GUARD_SHADER: &str = r#"
@group(1) @binding(0) var allowed: texture_2d<f32>;
@fragment fn fs_guard(@builtin(position) position:vec4<f32>) -> @location(0) vec4<f32> {
    let p=vec2<i32>(position.xy);
    if p.x < 64 && p.y < 22 { discard; }
    let packed=vec4<i32>(round(textureLoad(allowed,vec2<i32>(0,0),0)*255.0));
    let origin=vec2<i32>(packed.x+256*packed.y,packed.z+256*packed.w);
    let q=p-origin;
    let size=vec2<i32>(textureDimensions(allowed));
    if q.x>=0 && q.y>=0 && q.x<size.x && q.y+1<size.y {
        if textureLoad(allowed,q+vec2<i32>(0,1),0).r>0.5 { discard; }
    }
    return vec4<f32>(1.0);
}"#;
fn support_mask_bytes(samples: &[usize]) -> (Rect, Vec<u8>) {
    let rect = Rect::samples(samples).unwrap_or(Rect {
        x: 0,
        y: 0,
        w: 1,
        h: 0,
    });
    let mut bytes = vec![0u8; (rect.w * (rect.h + 1) * 4) as usize];
    bytes[..4].copy_from_slice(&[
        rect.x as u8,
        (rect.x >> 8) as u8,
        rect.y as u8,
        (rect.y >> 8) as u8,
    ]);
    for &sample in samples {
        let x = sample % WIDTH as usize - rect.x as usize;
        let y = sample / WIDTH as usize - rect.y as usize;
        bytes[((y + 1) * rect.w as usize + x) * 4] = 255;
    }
    (rect, bytes)
}
fn support_texture(gpu: &Gpu, pipelines: &Pipelines, samples: &[usize]) -> Result<GpuTexture> {
    let (rect, bytes) = support_mask_bytes(samples);
    let descriptor = Texture::rgba8(rect.w, rect.h + 1, &bytes, Sampler::default())?;
    GpuTexture::new(
        &gpu.device,
        &gpu.queue,
        &pipelines.texture_layout,
        &descriptor,
    )
}
fn guard_batch(
    gpu: &Gpu,
    pipelines: &Pipelines,
    pipeline: &wgpu::RenderPipeline,
    target: &GpuTexture,
    geometry: &FrameGeometry,
    triangles: &[Triangle],
    slices: &[DrawSlice],
) -> Result<()> {
    let masks = triangles
        .iter()
        .map(|t| support_texture(gpu, pipelines, &t.possible))
        .collect::<Result<Vec<_>>>()?;
    let count = triangles.len() as u32;
    let query = gpu.device.create_query_set(&wgpu::QuerySetDescriptor {
        label: Some("finite escaped-support binary occlusion"),
        ty: wgpu::QueryType::Occlusion,
        count,
    });
    let resolve = gpu.device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("finite support query resolve"),
        size: u64::from(count) * 8,
        usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    let readback = buffer(&gpu.device, u64::from(count) * 8);
    let mut encoder = gpu
        .device
        .create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
    {
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("finite source complement guard"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: &target.view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                    store: wgpu::StoreOp::Discard,
                },
            })],
            occlusion_query_set: Some(&query),
            ..Default::default()
        });
        pass.set_pipeline(pipeline);
        pass.set_viewport(0., 0., WIDTH as f32, HEIGHT as f32, 0., 1.);
        pass.set_scissor_rect(0, 0, WIDTH, HEIGHT);
        for (i, (slice, mask)) in slices.iter().zip(&masks).enumerate() {
            pass.set_bind_group(0, &geometry.transform, &[slice.matrix_offset]);
            pass.set_bind_group(1, &mask.binding, &[]);
            pass.set_vertex_buffer(0, geometry.vertices.slice(slice.vertices.clone()));
            pass.set_index_buffer(
                geometry.indices.slice(slice.indices.clone()),
                wgpu::IndexFormat::Uint16,
            );
            pass.begin_occlusion_query(i as u32);
            pass.draw_indexed(0..slice.count, 0, 0..1);
            pass.end_occlusion_query();
        }
    }
    encoder.resolve_query_set(&query, 0..count, &resolve, 0);
    encoder.copy_buffer_to_buffer(&resolve, 0, &readback, 0, u64::from(count) * 8);
    gpu.queue.submit([encoder.finish()]);
    let values = read(gpu, &readback)?;
    for (t, &b) in triangles.iter().zip(values.as_chunks::<8>().0.iter()) {
        ensure(
            u64::from_le_bytes(b) == 0,
            &format!(
                "triangle {:?} escaped its independently bounded possible support",
                t.key
            ),
        )?;
    }
    Ok(())
}
fn native_frame(
    frame: &Frame,
    gpu: &Gpu,
    pipelines: &mut Pipelines,
    output: &Path,
) -> Result<Value> {
    let (geometry, slices, receipts) = geometry(frame, gpu, pipelines)?;
    let target = GpuTexture::new(
        &gpu.device,
        &gpu.queue,
        &pipelines.texture_layout,
        &RenderTarget::new(WIDTH, HEIGHT, false)?.texture,
    )?;
    let white = GpuTexture::new(
        &gpu.device,
        &gpu.queue,
        &pipelines.texture_layout,
        &Texture::rgba8(1, 1, &[255; 4], Sampler::default())?,
    )?;
    let coverage =
        pipelines.finite_probe_coverage_pipeline(&gpu.device, COVERAGE_SHADER, "fs_coverage");
    let guard = pipelines.finite_probe_coverage_pipeline(&gpu.device, GUARD_SHADER, "fs_guard");
    // Original PS, original output format; depth/blend disabled for isolation.
    let color = pipelines.pipeline(
        &gpu.device,
        COLOR_FORMAT,
        false,
        false,
        BlendMode::Opaque,
        FragmentKind::Straight,
    );
    let alpha_blend = pipelines.pipeline(
        &gpu.device,
        COLOR_FORMAT,
        false,
        false,
        BlendMode::Alpha,
        FragmentKind::Straight,
    );
    let frame_dir = output.join(format!("frame-{:04}", frame.id));
    fs::create_dir(&frame_dir).map_err(error)?;
    let mut draw_file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(frame_dir.join("draws.jsonl"))
        .map_err(error)?;
    for receipt in &receipts {
        writeln!(draw_file, "{receipt}").map_err(error)?;
    }
    for (triangles, slices) in frame.triangles.chunks(BATCH).zip(slices.chunks(BATCH)) {
        guard_batch(
            gpu, pipelines, &guard, &target, &geometry, triangles, slices,
        )?;
    }
    let mut encoder = gpu
        .device
        .create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
    pass(
        &mut encoder,
        &target,
        &coverage,
        &geometry,
        &slices,
        &white,
        Rect::full(),
    );
    let union_buffer = buffer(&gpu.device, Rect::full().bytes());
    copy(
        &mut encoder,
        &target.texture,
        &union_buffer,
        Rect::full(),
        0,
    );
    gpu.queue.submit([encoder.finish()]);
    let union = read(gpu, &union_buffer)?;
    let union = super::capture::unpack_rows(&union, WIDTH, HEIGHT)?;
    let covered = verify_coverage(&union, &frame.required, &frame.possible)?;
    image::save_buffer_with_format(
        frame_dir.join("coverage.png"),
        &union,
        WIDTH,
        HEIGHT,
        image::ColorType::Rgba8,
        image::ImageFormat::Png,
    )
    .map_err(error)?;
    // Negative masks are derived from observed membership only for falsification;
    // they are never used to select or enlarge an accepted source mask.
    let present = (0..PIXELS)
        .find(|&i| !witness(i) && union[i * 4 + 3] != 0)
        .ok_or("no native coverage for controls")?;
    let absent = (0..PIXELS)
        .find(|&i| !witness(i) && union[i * 4 + 3] == 0)
        .ok_or("no uncovered control sample")?;
    let mut shrunken = frame.possible.clone();
    shrunken[present] = 0;
    ensure(
        verify_coverage(&union, &frame.required, &shrunken).is_err(),
        "shrunken possible negative control was accepted",
    )?;
    let mut enlarged = frame.required.clone();
    enlarged[absent] = 1;
    ensure(
        verify_coverage(&union, &enlarged, &frame.possible).is_err(),
        "enlarged required negative control was accepted",
    )?;
    let mut missing_encoder = gpu
        .device
        .create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
    pass(
        &mut missing_encoder,
        &target,
        &coverage,
        &geometry,
        &[],
        &white,
        Rect::full(),
    );
    let missing = buffer(&gpu.device, Rect::full().bytes());
    copy(
        &mut missing_encoder,
        &target.texture,
        &missing,
        Rect::full(),
        0,
    );
    gpu.queue.submit([missing_encoder.finish()]);
    let missing = super::capture::unpack_rows(&read(gpu, &missing)?, WIDTH, HEIGHT)?;
    ensure(
        verify_coverage(&missing, &frame.required, &frame.possible).is_err(),
        "missing native draws negative control was accepted",
    )?;

    let selected = frame
        .triangles
        .iter()
        .enumerate()
        .filter(|(_, t)| !t.required.is_empty())
        .map(|(i, _)| i)
        .collect::<Vec<_>>();
    let expected = selected
        .iter()
        .map(|&i| frame.triangles[i].key)
        .collect::<BTreeSet<_>>();
    let mut observed = BTreeSet::new();
    let mut observations = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(frame_dir.join("color-observations.jsonl"))
        .map_err(error)?;
    let mut native_samples = 0usize;
    let mut checked_samples = vec![0; PIXELS];
    let mut copied_bytes = 0u64;
    let mut fragment_controls = false;
    for (batch_index, batch) in selected.chunks(BATCH).enumerate() {
        let mut offsets = Vec::new();
        let mut size = 0;
        for &i in batch {
            let rect = Rect::samples(&frame.triangles[i].required).unwrap();
            offsets.push((i, rect, size));
            size += rect.bytes() * 4;
        }
        let readback = buffer(&gpu.device, size);
        let mut encoder = gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        for &(i, rect, offset) in &offsets {
            pass(
                &mut encoder,
                &target,
                &coverage,
                &geometry,
                &slices[i..i + 1],
                &white,
                rect,
            );
            copy(&mut encoder, &target.texture, &readback, rect, offset);
            pass(
                &mut encoder,
                &target,
                &color,
                &geometry,
                &slices[i..i + 1],
                &white,
                rect,
            );
            copy(
                &mut encoder,
                &target.texture,
                &readback,
                rect,
                offset + rect.bytes(),
            );
            for (slot, clear) in [(2, wgpu::Color::BLACK), (3, wgpu::Color::WHITE)] {
                pass_clear(
                    &mut encoder,
                    &target,
                    &alpha_blend,
                    &geometry,
                    &slices[i..i + 1],
                    &white,
                    rect,
                    clear,
                );
                copy(
                    &mut encoder,
                    &target.texture,
                    &readback,
                    rect,
                    offset + rect.bytes() * slot,
                );
            }
        }
        gpu.queue.submit([encoder.finish()]);
        let bytes = read(gpu, &readback)?;
        fs::write(
            frame_dir.join(format!("compact-{batch_index:04}.bin")),
            &bytes,
        )
        .map_err(error)?;
        for (i, rect, offset) in offsets {
            let t = &frame.triangles[i];
            let length = rect.bytes() as usize;
            let start = offset as usize;
            let cov = &bytes[start..start + length];
            let rgb = &bytes[start + length..start + length * 2];
            let black = &bytes[start + length * 2..start + length * 3];
            let white = &bytes[start + length * 3..start + length * 4];
            let checked = verify_color(t, rect, cov, rgb)?;
            ensure(
                verify_color_with_clear(t, rect, cov, black, [0, 0, 0, 255])? == checked
                    && verify_color_with_clear(t, rect, cov, white, [255, 255, 255, 255])?
                        == checked,
                "production blend endpoint sample sets differ",
            )?;
            native_samples += checked;
            for &sample in &t.required {
                if cov[rect.offset(sample) + 3] == 255 {
                    checked_samples[sample] = 1;
                }
            }

            if !fragment_controls && checked > 0 {
                let sample = *t
                    .required
                    .iter()
                    .find(|&&p| cov[rect.offset(p) + 3] == 255)
                    .unwrap();
                let pixel = rect.offset(sample);
                let mut alpha = rgb.to_vec();
                alpha[pixel + 3] = 254;
                ensure(
                    verify_color(t, rect, cov, &alpha).is_err(),
                    "nonopaque alpha negative control was accepted",
                )?;
                let mut shifted = rgb.to_vec();
                let mut injected = false;
                for c in 0..3 {
                    let lo = t.colors.iter().map(|v| v[c]).min().unwrap();
                    let hi = t.colors.iter().map(|v| v[c]).max().unwrap();
                    if hi <= 251 {
                        shifted[pixel + c] = hi + 4;
                        injected = true;
                        break;
                    }
                    if lo >= 4 {
                        shifted[pixel + c] = lo - 4;
                        injected = true;
                        break;
                    }
                }
                ensure(
                    injected && verify_color(t, rect, cov, &shifted).is_err(),
                    "greater-than-three-byte negative control was accepted",
                )?;
                let mut escaped = t.clone();
                escaped.possible.retain(|&p| p != sample);
                let guard_error = guard_batch(
                    gpu,
                    pipelines,
                    &guard,
                    &target,
                    &geometry,
                    &[escaped],
                    &slices[i..i + 1],
                )
                .err()
                .ok_or("one excluded native-covered sample did not produce binary occlusion")?;
                ensure(
                    guard_error.contains("escaped its independently bounded possible support"),
                    "support negative control failed for an unrelated reason",
                )?;
                fragment_controls = true;
            }

            ensure(observed.insert(t.key), "duplicate isolated observation")?;
            writeln!(observations,"{}",json!({"key":t.key,"source_triangle_sha256":t.source_sha256,"rect":[rect.x,rect.y,rect.w,rect.h],"buffer":format!("compact-{batch_index:04}.bin"),"offset":offset,"length":length,"coverage_sha256":bytes_hash(cov),"color_sha256":bytes_hash(rgb),"blend_black_sha256":bytes_hash(black),"blend_white_sha256":bytes_hash(white),"buffer_planes":["coverage","unblended_source","alpha_over_black","alpha_over_white"],"possible_required_samples":t.required.len(),"covered_required_samples":checked,"rgb_byte_error":3,"opaque_alpha_verified":true})).map_err(error)?;
        }
        copied_bytes += size;
    }
    verify_inventory(&expected, &observed)?;
    let mut omitted = observed.clone();
    omitted.pop_first();
    ensure(
        verify_inventory(&expected, &omitted).is_err(),
        "missing triangle receipt negative control was accepted",
    )?;
    ensure(
        fragment_controls,
        "native fragment/support negative controls were not exercised",
    )?;

    let required_count = frame.required.iter().filter(|&&v| v != 0).count();
    ensure(
        checked_samples == frame.required,
        "isolated checked-sample union differs from required mask",
    )?;
    Ok(
        json!({"frame":frame.id,"source_frame_sha256":frame.source_sha256,"source_triangles":frame.triangles.len(),"per_triangle_support_guard_passed":true,"coverage_samples":covered,"required_samples":required_count,"color_probe_triangles":selected.len(),"color_probe_covered_sample_memberships":native_samples,"checked_required_mask_sha256":bytes_hash(&checked_samples),"production_alpha_blend_endpoints_verified":true,"compact_readback_bytes":copied_bytes,"draws_sha256":hash_file(&frame_dir.join("draws.jsonl"))?,"color_observations_sha256":hash_file(&frame_dir.join("color-observations.jsonl"))?,"coverage_sha256":bytes_hash(&union),"negative_controls":{"missing_native_draws":"rejected","missing_triangle_receipt":"rejected","shrunken_possible":"rejected","enlarged_required":"rejected","nonopaque_alpha_readback":"rejected","greater_than_three_byte_readback":"rejected","one_pixel_support_escape_native_occlusion":"rejected"}}),
    )
}
#[cfg(target_os = "windows")]
fn runtime_modules() -> Result<Value> {
    use std::{ffi::c_void, os::windows::ffi::OsStringExt};
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetModuleHandleW(name: *const u16) -> *mut c_void;
        fn GetModuleFileNameW(module: *mut c_void, name: *mut u16, size: u32) -> u32;
    }
    let mut result = serde_json::Map::new();
    for name in [
        "d3d12.dll",
        "D3D12Core.dll",
        "d3d10warp.dll",
        "d3dcompiler_47.dll",
        "dxgi.dll",
    ] {
        let wide = name.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        // Query only this process's already-loaded module. No DLL search/load.
        let handle = unsafe { GetModuleHandleW(wide.as_ptr()) };
        if handle.is_null() {
            ensure(
                name == "D3D12Core.dll",
                &format!("required loaded runtime module missing: {name}"),
            )?;
            result.insert(name.into(), Value::Null);
            continue;
        }
        let mut path = vec![0u16; 32768];
        let n =
            unsafe { GetModuleFileNameW(handle, path.as_mut_ptr(), path.len() as u32) } as usize;
        ensure(
            n > 0 && n < path.len(),
            "cannot identify loaded module path",
        )?;
        let path = PathBuf::from(std::ffi::OsString::from_wide(&path[..n]));
        result.insert(name.into(),json!({"path":path,"sha256":hash_file(&path)?,"bytes":fs::metadata(&path).map_err(error)?.len()}));
    }
    Ok(Value::Object(result))
}
#[cfg(not(target_os = "windows"))]
fn runtime_modules() -> Result<Value> {
    Err("native DX12/WARP corroboration requires Windows".into())
}
#[derive(Debug)]
struct Options {
    trace: PathBuf,
    original: PathBuf,
    receipt: PathBuf,
    source_root: PathBuf,
    output: PathBuf,
    native: bool,
}
impl Options {
    fn parse(args: impl IntoIterator<Item = String>) -> Result<Self> {
        let mut args = args.into_iter();
        let mut options = BTreeMap::new();
        let mut mode = None;
        while let Some(key) = args.next() {
            if key == "--native" || key == "--plan-only" {
                ensure(
                    mode.replace(key == "--native").is_none(),
                    "exactly one explicit mode is required",
                )?;
                continue;
            }
            ensure(
                [
                    "--trace",
                    "--original-jsonl",
                    "--source-receipt",
                    "--source-root",
                    "--output-dir",
                ]
                .contains(&key.as_str()),
                "unknown finite probe argument",
            )?;
            let value = args
                .next()
                .filter(|v| !v.starts_with("--") && !v.is_empty())
                .ok_or("missing option value")?;
            ensure(
                options.insert(key, value).is_none(),
                "duplicate finite probe argument",
            )?;
        }
        let mut path = |key: &str| -> Result<PathBuf> {
            options
                .remove(key)
                .map(PathBuf::from)
                .ok_or_else(|| format!("missing {key}"))
        };
        Ok(Self {
            trace: path("--trace")?,
            original: path("--original-jsonl")?,
            receipt: path("--source-receipt")?,
            source_root: path("--source-root")?,
            output: path("--output-dir")?,
            native: mode.ok_or("specify --native or --plan-only")?,
        })
    }
}
fn validate_layout(stride: u64, attributes: &[wgpu::VertexAttribute]) -> Result<()> {
    let expected = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Unorm8x4,3=>Float32x4];
    ensure(
        stride == 40 && attributes == expected,
        "production input layout differs from source-packed fixture",
    )
}
fn sources(options: &Options, receipt: &Value) -> Result<(BTreeMap<u32, WeaponAsset>, Value)> {
    let mut assets = BTreeMap::new();
    let mut records = Vec::new();
    for relative in ["assets/locomotion/asset.vrm", "assets/reload/asset.vrm"] {
        let path = options.source_root.join(relative);
        let bytes = fs::read(&path).map_err(error)?;
        let sha = bytes_hash(&bytes);
        let before = &receipt["inputs_and_implementation_before"][relative];
        let after = &receipt["inputs_and_implementation_after"][relative];
        ensure(
            before["sha256"] == sha && before["bytes"] == bytes.len() && before == after,
            "VRM bytes differ from original before/after receipt",
        )?;
        let crc = crate::asset::crc32(&bytes);
        let decoded = WeaponAsset::decode(&bytes).map_err(error)?;
        ensure(
            assets.insert(crc, decoded).is_none(),
            "duplicate source CRC",
        )?;
        records
            .push(json!({"relative_path":relative,"sha256":sha,"bytes":bytes.len(),"crc32":crc}));
    }
    Ok((assets, json!(records)))
}
fn verify_production_source(receipt: &Value) -> Result<()> {
    let mesh = include_str!("mesh.rs");
    let start = mesh
        .find("    /// Later finite corroboration only.")
        .ok_or("diagnostic helper start marker missing")?;
    let end = mesh[start..]
        .find("    /// Three immutable buffers")
        .map(|n| n + start)
        .ok_or("diagnostic helper end marker missing")?;
    let restored_mesh = format!("{}{}", &mesh[..start], &mesh[end..]);
    let files: [(&str, &[u8]); 8] = [
        ("Cargo.lock", include_bytes!("../../Cargo.lock")),
        ("Cargo.toml", include_bytes!("../../Cargo.toml")),
        ("src/render/mesh.wgsl", include_bytes!("mesh.wgsl")),
        ("src/render/arena.rs", include_bytes!("arena.rs")),
        ("src/render/target.rs", include_bytes!("target.rs")),
        ("src/render/device.rs", include_bytes!("device.rs")),
        ("src/draw/mod.rs", include_bytes!("../draw/mod.rs")),
        ("src/render/mesh.rs", restored_mesh.as_bytes()),
    ];
    for (name, bytes) in files {
        ensure(
            receipt["inputs_and_implementation_before"][name]["sha256"] == bytes_hash(bytes),
            &format!("compiled production source differs from original receipt: {name}"),
        )?;
    }
    Ok(())
}
fn source_files() -> Value {
    json!({"Cargo.lock":bytes_hash(include_bytes!("../../Cargo.lock")),"production_shader_wgsl":bytes_hash(include_bytes!("mesh.wgsl")),"arena":bytes_hash(include_bytes!("arena.rs")),"mesh_with_diagnostic_helper":bytes_hash(include_bytes!("mesh.rs")),"target":bytes_hash(include_bytes!("target.rs")),"device":bytes_hash(include_bytes!("device.rs")),"probe":bytes_hash(include_bytes!("finite_warp_probe.rs")),"coverage_ps":bytes_hash(COVERAGE_SHADER.as_bytes()),"support_guard_ps":bytes_hash(GUARD_SHADER.as_bytes())})
}
/// Run the explicit CPU plan or later native fixture. Native success is impossible
/// on other operating systems or when the actual adapter is not DX12 CPU WARP.
pub fn run(args: impl IntoIterator<Item = String>) -> Result<()> {
    let options = Options::parse(args)?;
    ensure(
        hash_file(&options.original)? == ORIGINAL,
        "original source JSONL digest mismatch",
    )?;
    ensure(
        hash_file(&options.receipt)? == RECEIPT,
        "original source receipt digest mismatch",
    )?;
    validate_layout(GpuVertex::STRIDE, &GpuVertex::ATTRIBUTES)?;
    let receipt: Value =
        serde_json::from_slice(&fs::read(&options.receipt).map_err(error)?).map_err(error)?;
    verify_production_source(&receipt)?;
    let (assets, asset_receipts) = sources(&options, &receipt)?;
    let originals = read_rows(&options.original)?
        .into_iter()
        .filter(|r| {
            r["frame"]
                .as_u64()
                .is_some_and(|id| FINITE_FRAMES.contains(&(id as usize)))
        })
        .map(|r| Ok((usize_at(&r["frame"])?, r)))
        .collect::<Result<BTreeMap<_, _>>>()?;
    ensure(
        originals.len() == 50,
        "original source does not identify exactly fifty visible states",
    )?;
    ensure(
        !options.output.exists(),
        "output must be a new directory; stale evidence cannot pass",
    )?;
    fs::create_dir_all(&options.output).map_err(error)?;
    let trace_sha256 = hash_file(&options.trace)?;
    let mut rows = BufReader::new(File::open(&options.trace).map_err(error)?).lines();
    let header: Value =
        serde_json::from_str(&rows.next().ok_or("empty trace")?.map_err(error)?).map_err(error)?;
    ensure(
        header["extent"] == json!([WIDTH, HEIGHT])
            && header["backend_profile"]
                .as_str()
                .is_some_and(|s| s.starts_with("dx12:")),
        "trace is not the finite DX12 viewport profile",
    )?;
    let gpu = if options.native {
        ensure(
            cfg!(target_os = "windows"),
            "native probe cannot run outside Windows",
        )?;
        ensure(cfg!(feature="legacy-macroquad") && !cfg!(debug_assertions), "native probe requires original dual legacy-macroquad,wgpu-runtime feature unification and release profile")?;

        let gpu = pollster::block_on(Gpu::new(BackendSelection::Dx12, true, None, WIDTH, HEIGHT))?;
        let info = gpu.device.adapter_info();
        ensure(
            gpu.info.requested == "dx12"
                && info.backend == wgpu::Backend::Dx12
                && info.device_type == wgpu::DeviceType::Cpu
                && info.name == "Microsoft Basic Render Driver",
            "requires actual DX12 CPU Microsoft Basic Render Driver",
        )?;
        Some(gpu)
    } else {
        None
    };
    let mut pipelines = gpu.as_ref().map(|g| Pipelines::new(&g.device));
    let mut frame_ids = BTreeSet::new();
    let mut records = Vec::new();
    let mut triangle_count = 0;
    let mut selected_count = 0;
    let mut transfer_bytes = 0;
    for row in rows {
        let value: Value = serde_json::from_str(&row.map_err(error)?).map_err(error)?;
        let id = usize_at(&value["frame"])?;
        ensure(frame_ids.insert(id), "duplicate finite state")?;
        let frame = load_frame(
            &value,
            originals.get(&id).ok_or("unexpected finite state")?,
            &assets,
        )?;
        let selected = frame
            .triangles
            .iter()
            .filter(|t| !t.required.is_empty())
            .count();
        let transfer = frame
            .triangles
            .iter()
            .filter_map(|t| Rect::samples(&t.required))
            .map(|r| r.bytes() * 4)
            .sum::<u64>();
        triangle_count += frame.triangles.len();
        selected_count += selected;
        transfer_bytes += transfer;
        let record = if let Some(gpu) = &gpu {
            native_frame(&frame, gpu, pipelines.as_mut().unwrap(), &options.output)?
        } else {
            json!({"frame":id,"source_frame_sha256":frame.source_sha256,"triangles":frame.triangles.len(),"color_probe_triangles":selected,"compact_color_readback_bytes":transfer,"required_samples":frame.required.iter().filter(|&&v|v!=0).count(),"possible_samples":frame.possible.iter().filter(|&&v|v!=0).count()})
        };
        eprintln!(
            "finite frame={id} source_triangles={} color_probes={selected} native={}",
            frame.triangles.len(),
            options.native
        );
        records.push(record);
    }
    ensure(
        frame_ids == originals.keys().copied().collect(),
        "missing finite source state",
    )?;
    ensure(
        hash_file(&options.trace)? == trace_sha256
            && hash_file(&options.original)? == ORIGINAL
            && hash_file(&options.receipt)? == RECEIPT,
        "source inputs changed during probe",
    )?;
    let (_, after_assets) = sources(&options, &receipt)?;
    ensure(
        after_assets == asset_receipts,
        "VRM inputs changed during probe",
    )?;
    let native_identity = if let Some(gpu) = &gpu {
        gpu.check_errors()?;
        let info = gpu.device.adapter_info();
        json!({"adapter":info.name,"backend":format!("{:?}",info.backend),"device_type":format!("{:?}",info.device_type),"vendor_id":info.vendor,"device_id":info.device,"driver":info.driver,"driver_info":info.driver_info,"runtime_modules":runtime_modules()?,"compiler":"Fxc","shader_translation":"locked wgpu/naga 30.0.1 WGSL->HLSL->FXC","compiled_shader_hash":null,"compiled_shader_hash_unavailable_reason":"wgpu public production APIs do not expose compiled DXBC bytes"})
    } else {
        Value::Null
    };
    let report = json!({"schema":"rust-duty-finite-warp-corroboration/v1","status":if options.native {"passed"} else {"source_plan_verified"},"native_execution":options.native,"later_corroboration":true,"original_capture_reproduced":false,"original_native_upload_identity_verified":false,"original_profile_flags_modified":false,"universal_profile_verified":false,"acceptance_verdict":null,"created_unix_seconds":SystemTime::now().duration_since(UNIX_EPOCH).map_err(error)?.as_secs(),"source_receipt_sha256":RECEIPT,"original_dx12_jsonl_sha256":ORIGINAL,"trace_sha256":trace_sha256,"source_assets":asset_receipts,"implementation_sha256":source_files(),"executable_sha256":hash_file(&std::env::current_exe().map_err(error)?)?,"build_configuration":{"legacy_macroquad":cfg!(feature="legacy-macroquad"),"wgpu_runtime":cfg!(feature="wgpu-runtime"),"audio":cfg!(feature="audio"),"debug_assertions":cfg!(debug_assertions),"required_rust_toolchain":"1.99.0","compiler_build_provenance":"external build receipt must bind rustc-Vv and this executable digest"},"native_identity":native_identity,"viewport":[0,0,WIDTH,HEIGHT],"target_format":"Rgba8Unorm","sample_count":1,"depth_enabled":false,"blend_modes":["disabled","production_alpha_over_opaque_black","production_alpha_over_opaque_white"],"fragment_entry_point":"fs_straight","required_mask_changed":false,"possible_mask_changed":false,"frame_witness_excluded":[0,0,64,22],"source_triangle_count":triangle_count,"support_guard_draw_count":triangle_count,"color_probe_triangle_count":selected_count,"compact_color_readback_bytes":transfer_bytes,"coverage_union_readback_bytes":50*PIXELS*4,"frames":records,"scope":"finite source-declared triangles and required/possible sample sets only; modified PS/depth/blend isolation is later corroboration, never original native pipeline receipts"});
    fs::write(
        options.output.join("report.json"),
        serde_json::to_vec_pretty(&report).map_err(error)?,
    )
    .map_err(error)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn example() -> Triangle {
        let colors = [[33, 35, 37, 255]; 3];
        Triangle {
            key: [0, 0, 0],
            vertices: [Vertex {
                position: Vec3::ZERO,
                uv: Vec2::ZERO,
                color: colors[0],
                normal: Vec4::ZERO,
            }; 3],
            transform: Mat4::IDENTITY,
            colors,
            possible: vec![1000],
            robust: vec![1000],
            required: vec![1000],
            safe: true,
            source_sha256: "test".into(),
        }
    }
    #[test]
    fn masks_reject_mutations_and_witness_is_explicit() {
        let i = 1100;
        let mut required = vec![0; PIXELS];
        required[i] = 1;
        let possible = required.clone();
        let mut pixels = vec![0; PIXELS * 4];
        pixels[i * 4..i * 4 + 4].fill(255);
        assert_eq!(verify_coverage(&pixels, &required, &possible).unwrap(), 1);
        assert!(verify_coverage(&pixels, &required, &vec![0; PIXELS]).is_err());
        required[2000] = 1;
        assert!(verify_coverage(&pixels, &required, &possible).is_err());
        required[2000] = 0;
        pixels[3000 * 4..3000 * 4 + 4].fill(255);
        assert!(verify_coverage(&pixels, &required, &possible).is_err());
        assert!(mask(&json!([[3, 4], [5, 2]])).is_err());
        assert!(mask(&json!([[PIXELS, 1]])).is_err());
    }
    #[test]
    fn fragment_acceptance_rejects_bad_alpha_and_four_byte_error() {
        let t = example();
        let r = Rect::samples(&t.required).unwrap();
        let mut coverage = vec![0; r.bytes() as usize];
        let mut color = coverage.clone();
        coverage[..4].fill(255);
        color[..4].copy_from_slice(&[33, 35, 37, 255]);
        assert_eq!(verify_color(&t, r, &coverage, &color).unwrap(), 1);
        color[0] = 36;
        assert!(verify_color(&t, r, &coverage, &color).is_ok());
        color[0] = 37;
        assert!(verify_color(&t, r, &coverage, &color).is_err());
        color[0] = 33;
        color[3] = 254;
        assert!(verify_color(&t, r, &coverage, &color).is_err());
        color[3] = 0;
        assert!(verify_color(&t, r, &coverage, &color).is_err());
        coverage[..4].fill(0);
        assert!(verify_color(&t, r, &coverage, &color).is_err());
    }
    #[test]
    fn missing_triangle_or_draw_is_not_hidden_by_union_overlap() {
        let expected = BTreeSet::from([[0, 1, 0], [0, 2, 1]]);
        let observed = BTreeSet::from([[0, 1, 0]]);
        assert!(verify_inventory(&expected, &observed).is_err());
        assert!(verify_inventory(&expected, &expected).is_ok());
    }
    #[test]
    fn wrong_matrix_and_vertex_bytes_fail_before_submission() {
        let t = example();
        let mut arena = FrameArena::new(256, 65536).unwrap();
        let wrong = arena
            .try_append(&t.vertices, &[0, 1, 2], Mat4::ZERO)
            .unwrap()
            .unwrap();
        assert!(draw_digest(&t, &arena, &wrong).is_err());
        let valid = arena
            .try_append(&t.vertices, &[0, 1, 2], t.transform)
            .unwrap()
            .unwrap();
        assert!(draw_digest(&t, &arena, &valid).is_ok());
        let mut mutated = t.vertices;
        mutated[0].position.x = 1.;
        let bad = arena
            .try_append(&mutated, &[0, 1, 2], t.transform)
            .unwrap()
            .unwrap();
        assert!(draw_digest(&t, &arena, &bad).is_err());
        let wrong_index = arena
            .try_append(&t.vertices, &[0, 2, 1], t.transform)
            .unwrap()
            .unwrap();
        assert!(draw_digest(&t, &arena, &wrong_index).is_err());
    }
    #[test]
    fn wrong_layout_is_rejected() {
        assert!(validate_layout(GpuVertex::STRIDE, &GpuVertex::ATTRIBUTES).is_ok());
        assert!(validate_layout(48, &GpuVertex::ATTRIBUTES).is_err());
        let mut attributes = GpuVertex::ATTRIBUTES;
        attributes[2].offset = 24;
        assert!(validate_layout(40, &attributes).is_err());
        attributes = GpuVertex::ATTRIBUTES;
        attributes[2].format = wgpu::VertexFormat::Uint8x4;
        assert!(validate_layout(40, &attributes).is_err());
    }
    #[test]
    fn guard_and_coverage_wgsl_validate_and_guard_uses_late_occlusion_discard() {
        for source in [COVERAGE_SHADER, GUARD_SHADER] {
            let module = wgpu::naga::front::wgsl::parse_str(source).unwrap();
            wgpu::naga::valid::Validator::new(
                wgpu::naga::valid::ValidationFlags::all(),
                wgpu::naga::valid::Capabilities::empty(),
            )
            .validate(&module)
            .unwrap();
        }
        // The pinned DX12 path's binary query observes surviving samples. There
        // is deliberately no early_depth_test declaration on this fragment.
        assert!(!GUARD_SHADER.contains("early_depth_test"));
    }
    #[test]
    fn source_mask_texels_map_absolute_viewport_coordinates_without_filtering() {
        for samples in [
            vec![],
            vec![959, 518399],
            vec![518399],
            vec![0, 63, 64, 21183, 21184],
        ] {
            let (rect, bytes) = support_mask_bytes(&samples);
            let origin = [
                u32::from(bytes[0]) + 256 * u32::from(bytes[1]),
                u32::from(bytes[2]) + 256 * u32::from(bytes[3]),
            ];
            assert_eq!(origin, [rect.x, rect.y]);
            for y in 0..HEIGHT {
                for x in 0..WIDTH {
                    let expected = samples.contains(&((y * WIDTH + x) as usize));
                    let observed = x >= rect.x
                        && y >= rect.y
                        && x < rect.x + rect.w
                        && y < rect.y + rect.h
                        && bytes[(((y - rect.y + 1) * rect.w + x - rect.x) * 4) as usize] == 255;
                    assert_eq!(expected, observed, "sample ({x},{y})");
                }
            }
        }
    }
    #[test]
    fn explicit_native_or_plan_mode_and_fresh_output_are_required() {
        assert!(Options::parse(Vec::<String>::new()).is_err());
        assert!(Options::parse(["--native", "--plan-only"].map(str::to_owned)).is_err());
    }
}
