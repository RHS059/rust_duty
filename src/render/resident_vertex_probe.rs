//! Explicit diagnostic only: read actual vertex-stage values as integer pixels.
//! The production vertex function body is reused, but probe outputs/entry points
//! can alter backend optimization. This is not a production-binary trace or a
//! substitute for the unchanged full-image parity gate.
use super::{resident, WgpuRenderer};
use crate::draw::resident::{ResidentDraw, Vertices};
use glam::Mat4;
use std::{sync::mpsc, time::Duration};
use wgpu::util::DeviceExt;

pub const MAX_VERTICES: usize = 384;
const CURRENT: &str = "let reciprocal = 1.0 / sqrt(length_squared);";
const HISTORICAL: &str = "let reciprocal = inverseSqrt(length_squared);";
const UNWRITTEN: u32 = u32::MAX;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Arithmetic {
    Current,
    HistoricalInverseSqrt,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct VertexSample {
    pub source_vertex: u32,
    pub clip_bits: [u32; 4],
    pub color_bits: [u32; 4],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SkinStageSample {
    pub source_vertex: u32,
    pub skin_position_bits: [u32; 4],
    pub world_position_bits: [u32; 4],
    pub skin_route_clip_bits: [u32; 4],
    pub world_route_clip_bits: [u32; 4],
}

/// Exact inputs and outputs of the instrumented skin-stage shader. Exposing
/// intermediate values can change optimization; these are not production traces.
#[derive(Debug)]
pub struct SkinStageCapture {
    pub shader_source: String,
    pub vertex_bytes: Vec<u8>,
    pub draw_uniform_bytes: Vec<u8>,
    pub palette_bytes: Vec<u8>,
    pub bone_count: usize,
    pub samples: Vec<SkinStageSample>,
}

fn decode_samples(mapped: &[u8], row: usize, indices: &[u32]) -> Result<Vec<VertexSample>, String> {
    if mapped.len() != row * 2 || indices.len() * 16 > row {
        return Err("resident probe readback extent differs".into());
    }
    let words = |offset: usize| {
        std::array::from_fn(|j| {
            u32::from_le_bytes(
                mapped[offset + j * 4..offset + j * 4 + 4]
                    .try_into()
                    .unwrap(),
            )
        })
    };
    indices
        .iter()
        .enumerate()
        .map(|(i, &source_vertex)| {
            let color_bits = words(row + i * 16);
            // Every source route emits a finite alpha in [0,1]. Preserve arbitrary
            // clip/RGB nonfinite bits, while detecting a point that never wrote.
            if color_bits == [UNWRITTEN; 4] {
                return Err(format!("resident probe point {i} was not written"));
            }
            Ok(VertexSample {
                source_vertex,
                clip_bits: words(i * 16),
                color_bits,
            })
        })
        .collect()
}

#[derive(Clone, Copy)]
enum Kind {
    Cpu,
    Rigid,
    Skin,
}

pub fn shader_source(mode: Arithmetic, skin: bool, count: usize) -> Result<String, String> {
    make_shader(mode, if skin { Kind::Skin } else { Kind::Rigid }, count)
}

pub fn cpu_shader_source(count: usize) -> Result<String, String> {
    make_shader(Arithmetic::Current, Kind::Cpu, count)
}

/// `count` is the number of selected source vertices, each invoked twice in
/// one pass. Both invocations retain the shader's final clip-position result.
pub fn skin_stage_shader_source(count: usize) -> Result<String, String> {
    make_skin_stage_shader(
        include_str!("resident.wgsl"),
        include_str!("resident_vertex_probe.wgsl"),
        count,
    )
}

fn skin_stage_count(count: usize) -> Result<(), String> {
    if count == 0 || count > MAX_VERTICES / 2 {
        return Err("resident skin-stage probe count is outside 1..=192".into());
    }
    Ok(())
}

fn replace_unique(source: &str, anchor: &str, replacement: &str) -> Result<String, String> {
    if source.matches(anchor).count() != 1 {
        return Err(format!(
            "resident skin-stage probe source anchor is not unique: {anchor:?}"
        ));
    }
    Ok(source.replacen(anchor, replacement, 1))
}

const SKIN_STAGE_FIELDS: &str = "struct VertexOutput {\n    @location(2) skin_position: vec4<f32>,\n    @location(3) world_position: vec4<f32>,\n";
const SKIN_STAGE_POSITION: &str =
    "    let world_position = (draw.root * vec4<f32>(position, 1.0)).xyz;";
const SKIN_STAGE_VALUES: &str = "    let world_position = (draw.root * vec4<f32>(position, 1.0)).xyz;\n    output.skin_position = vec4<f32>(position, 1.0);\n    output.world_position = vec4<f32>(world_position, 1.0);";
const SKIN_STAGE_ROUTE: &str =
    "    output.color = select(actual.skin_position, actual.world_position, (index & 1u) != 0u);";

fn make_skin_stage_shader(original: &str, template: &str, count: usize) -> Result<String, String> {
    skin_stage_count(count)?;
    let source = replace_unique(original, "struct VertexOutput {\n", SKIN_STAGE_FIELDS)?;
    let source = replace_unique(&source, SKIN_STAGE_POSITION, SKIN_STAGE_VALUES)?;
    let source = replace_unique(&source, "@vertex fn vs_rigid(", "fn original_vs_rigid(")?;
    let source = replace_unique(&source, "@vertex fn vs_skin(", "fn original_vs_skin(")?;
    // Preserve the original final clip expression and the wrapper's clip output.
    // Only the second four-word target selects the observable intermediate.
    let suffix = replace_unique(template, "__INPUT__", "SkinInput")?;
    let suffix = replace_unique(&suffix, "__ENTRY__", "original_vs_skin")?;
    let suffix = replace_unique(&suffix, "__COUNT__", &(count * 2).to_string())?;
    let suffix = replace_unique(
        &suffix,
        "    output.color = actual.color;",
        SKIN_STAGE_ROUTE,
    )?;
    Ok(format!("{source}\n{suffix}"))
}

fn make_shader(mode: Arithmetic, kind: Kind, count: usize) -> Result<String, String> {
    if count == 0 || count > MAX_VERTICES {
        return Err("resident vertex probe count is outside 1..=384".into());
    }
    let original = include_str!("resident.wgsl");
    if original.matches(CURRENT).count() != 1 || original.contains(HISTORICAL) {
        return Err(
            "resident probe normalization source no longer matches its exact control".into(),
        );
    }
    let source = match mode {
        Arithmetic::Current => original.to_owned(),
        Arithmetic::HistoricalInverseSqrt => original.replacen(CURRENT, HISTORICAL, 1),
    };
    let source = if matches!(kind, Kind::Cpu) {
        include_str!("mesh.wgsl").replace("@vertex fn vs_main", "fn original_vs_main")
    } else {
        source
            .replace("@vertex fn vs_rigid", "fn original_vs_rigid")
            .replace("@vertex fn vs_skin", "fn original_vs_skin")
    };
    let (input, entry) = match kind {
        Kind::Cpu => ("VertexInput", "original_vs_main"),
        Kind::Skin => ("SkinInput", "original_vs_skin"),
        Kind::Rigid => ("RigidInput", "original_vs_rigid"),
    };
    let template = include_str!("resident_vertex_probe.wgsl");
    let suffix = template
        .replace("__INPUT__", input)
        .replace("__ENTRY__", entry)
        .replace("__COUNT__", &count.to_string());
    Ok(format!("{source}\n{suffix}"))
}

fn selected_bytes(draw: &ResidentDraw, indices: &[u32]) -> Result<(Vec<u8>, bool), String> {
    if indices.is_empty() || indices.len() > MAX_VERTICES {
        return Err("resident vertex probe count is outside 1..=384".into());
    }
    if indices
        .iter()
        .any(|&i| i as usize >= draw.mesh().vertex_count())
    {
        return Err("resident vertex probe index is outside its mesh".into());
    }
    let skin = matches!(draw.mesh().vertices(), Vertices::Skin { .. });
    let stride = if skin { 80 } else { 32 };
    let all = resident::vertices(draw.mesh());
    let mut selected = Vec::with_capacity(indices.len() * stride);
    for &index in indices {
        let start = index as usize * stride;
        selected.extend_from_slice(&all[start..start + stride]);
    }
    Ok((selected, skin))
}

fn selected_skin_stage_bytes(
    draw: &ResidentDraw,
    indices: &[u32],
) -> Result<(Vec<u8>, usize), String> {
    skin_stage_count(indices.len())?;
    let bone_count = match (draw.mesh().vertices(), draw.palette()) {
        (Vertices::Skin { bones, .. }, Some(palette)) if *bones == palette.positions().len() => {
            *bones
        }
        _ => return Err("resident skin-stage probe requires skin geometry and palette".into()),
    };
    let (selected, _) = selected_bytes(draw, indices)?;
    let mut duplicated = Vec::with_capacity(selected.len() * 2);
    for vertex in selected.as_chunks::<80>().0 {
        duplicated.extend_from_slice(vertex);
        duplicated.extend_from_slice(vertex);
    }
    Ok((duplicated, bone_count))
}

fn skin_stage_samples(
    samples: &[VertexSample],
    indices: &[u32],
) -> Result<Vec<SkinStageSample>, String> {
    skin_stage_count(indices.len())?;
    if samples.len() != indices.len() * 2 {
        return Err("resident skin-stage probe sample count differs".into());
    }
    samples
        .as_chunks::<2>()
        .0
        .iter()
        .zip(indices)
        .map(|(pair, &source_vertex)| {
            if pair
                .iter()
                .any(|sample| sample.source_vertex != source_vertex)
            {
                return Err("resident skin-stage probe sample ordering differs".into());
            }
            Ok(SkinStageSample {
                source_vertex,
                skin_position_bits: pair[0].color_bits,
                world_position_bits: pair[1].color_bits,
                skin_route_clip_bits: pair[0].clip_bits,
                world_route_clip_bits: pair[1].clip_bits,
            })
        })
        .collect()
}

/// One bounded diagnostic pass using the existing two integer render targets.
/// The returned upload contains adjacent skin/world duplicates of each selected
/// vertex. Intermediate exposure may alter compilation, so compare both route
/// clip results with the original probe before interpreting stage differences.
pub fn capture_skin_stages(
    renderer: &mut WgpuRenderer,
    draw: &ResidentDraw,
    projection: Mat4,
    indices: &[u32],
) -> Result<SkinStageCapture, String> {
    let (vertex_bytes, bone_count) = selected_skin_stage_bytes(draw, indices)?;
    let shader_source = skin_stage_shader_source(indices.len())?;
    let draw_uniform_bytes = resident::draw_bytes(draw, projection)?;
    let palette_bytes = resident::palette_bytes(draw.palette());
    let duplicated_indices: Vec<_> = indices.iter().flat_map(|&index| [index, index]).collect();
    let raw_samples = capture_prepared(
        renderer,
        &vertex_bytes,
        Kind::Skin,
        &draw_uniform_bytes,
        &palette_bytes,
        &duplicated_indices,
        shader_source.clone(),
    )?;
    Ok(SkinStageCapture {
        shader_source,
        vertex_bytes,
        draw_uniform_bytes,
        palette_bytes,
        bone_count,
        samples: skin_stage_samples(&raw_samples, indices)?,
    })
}

/// Blocks for one small explicit readback. Never called by normal rendering.
/// `projection` is the same already depth-remapped matrix used by FramePlan.
pub fn capture(
    renderer: &mut WgpuRenderer,
    draw: &ResidentDraw,
    projection: Mat4,
    indices: &[u32],
    mode: Arithmetic,
) -> Result<Vec<VertexSample>, String> {
    let (bytes, skin) = selected_bytes(draw, indices)?;
    let source = shader_source(mode, skin, indices.len())?;
    let draw_bytes = resident::draw_bytes(draw, projection)?;
    let palette = resident::palette_bytes(draw.palette());
    capture_prepared(
        renderer,
        &bytes,
        if skin { Kind::Skin } else { Kind::Rigid },
        &draw_bytes,
        &palette,
        indices,
        source,
    )
}

/// The real CPU-lit GPU vertex route, using the caller's original loader mesh.
/// This is deliberately independent of ResidentDraw::reference_mesh().
pub fn capture_cpu_reference(
    renderer: &mut WgpuRenderer,
    mesh: &crate::draw::Mesh,
    projection: Mat4,
    indices: &[u32],
) -> Result<Vec<VertexSample>, String> {
    if !projection.is_finite()
        || indices.is_empty()
        || indices.len() > MAX_VERTICES
        || indices.iter().any(|&i| i as usize >= mesh.vertices.len())
    {
        return Err("invalid CPU vertex probe input".into());
    }
    let mut bytes = Vec::with_capacity(indices.len() * 40);
    for &index in indices {
        super::arena::GpuVertex::from(mesh.vertices[index as usize]).append_bytes(&mut bytes);
    }
    let draw_bytes: Vec<_> = projection
        .to_cols_array()
        .into_iter()
        .flat_map(f32::to_le_bytes)
        .collect();
    let source = make_shader(Arithmetic::Current, Kind::Cpu, indices.len())?;
    capture_prepared(
        renderer,
        &bytes,
        Kind::Cpu,
        &draw_bytes,
        &resident::palette_bytes(None),
        indices,
        source,
    )
}

fn capture_prepared(
    renderer: &mut WgpuRenderer,
    bytes: &[u8],
    kind: Kind,
    draw_bytes: &[u8],
    palette: &[u8],
    indices: &[u32],
    source: String,
) -> Result<Vec<VertexSample>, String> {
    if renderer.gpu.surface.is_some() || renderer.prepared.is_some() {
        return Err("resident vertex probe requires an idle headless renderer".into());
    }
    let device = &renderer.gpu.device;
    let queue = &renderer.gpu.queue;
    renderer.gpu.check_errors()?;
    let scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let result = (|| {
        let layout = |label, size| {
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some(label),
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: wgpu::BufferSize::new(size),
                    },
                    count: None,
                }],
            })
        };
        let draw_layout = layout("probe draw", draw_bytes.len() as u64);
        let palette_layout = layout("probe palette", 16384);
        let empty = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("probe unused texture slot"),
            entries: &[],
        });
        let binding = |label, bytes: &[u8], layout: &wgpu::BindGroupLayout| {
            let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: bytes,
                usage: wgpu::BufferUsages::UNIFORM,
            });
            device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some(label),
                layout,
                entries: &[wgpu::BindGroupEntry {
                    binding: 0,
                    resource: buffer.as_entire_binding(),
                }],
            })
        };
        let draws = binding("probe immutable draw", draw_bytes, &draw_layout);
        let palettes = binding("probe immutable palette", palette, &palette_layout);
        let empty_binding = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("probe empty binding"),
            layout: &empty,
            entries: &[],
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("instrumented resident vertex-stage probe"),
            source: wgpu::ShaderSource::Wgsl(source.into()),
        });
        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("probe pipeline"),
            bind_group_layouts: &[Some(&draw_layout), Some(&empty), Some(&palette_layout)],
            immediate_size: 0,
        });
        let rigid_attributes = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Float32x3];
        let skin_attributes = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Float32x3,3=>Uint16x4,4=>Uint16x4,5=>Float32x4,6=>Float32x4];
        let cpu_attributes = super::arena::GpuVertex::ATTRIBUTES;
        let (stride, attributes): (u64, &[wgpu::VertexAttribute]) = match kind {
            Kind::Cpu => (40, &cpu_attributes),
            Kind::Rigid => (32, &rigid_attributes),
            Kind::Skin => (80, &skin_attributes),
        };
        let target = Some(wgpu::ColorTargetState {
            format: wgpu::TextureFormat::Rgba32Uint,
            blend: None,
            write_mask: wgpu::ColorWrites::ALL,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("resident diagnostic points"),
            layout: Some(&pipeline_layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("probe_vertex"),
                compilation_options: Default::default(),
                buffers: &[Some(wgpu::VertexBufferLayout {
                    array_stride: stride,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes,
                })],
            },
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::PointList,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: Default::default(),
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("probe_fragment"),
                compilation_options: Default::default(),
                targets: &[target.clone(), target],
            }),
            multiview_mask: None,
            cache: None,
        });
        let vertices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("selected probe vertices"),
            contents: bytes,
            usage: wgpu::BufferUsages::VERTEX,
        });
        let width = indices.len() as u32;
        let extent = wgpu::Extent3d {
            width,
            height: 1,
            depth_or_array_layers: 1,
        };
        let texture = || {
            device.create_texture(&wgpu::TextureDescriptor {
                label: Some("probe integer words"),
                size: extent,
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Rgba32Uint,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
                view_formats: &[],
            })
        };
        let textures = [texture(), texture()];
        let views = textures
            .each_ref()
            .map(|t| t.create_view(&Default::default()));
        let row = (width * 16).div_ceil(256) * 256;
        let readback = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("probe readback"),
            size: u64::from(row) * 2,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut encoder = device.create_command_encoder(&Default::default());
        {
            let attachments = views.each_ref().map(|view| {
                Some(wgpu::RenderPassColorAttachment {
                    view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color {
                            r: f64::from(UNWRITTEN),
                            g: f64::from(UNWRITTEN),
                            b: f64::from(UNWRITTEN),
                            a: f64::from(UNWRITTEN),
                        }),
                        store: wgpu::StoreOp::Store,
                    },
                })
            });
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("resident vertex words"),
                color_attachments: &attachments,
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&pipeline);
            pass.set_bind_group(0, &draws, &[]);
            pass.set_bind_group(1, &empty_binding, &[]);
            pass.set_bind_group(2, &palettes, &[]);
            pass.set_vertex_buffer(0, vertices.slice(..));
            pass.draw(0..width, 0..1);
        }
        for (i, texture) in textures.iter().enumerate() {
            encoder.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo {
                    texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                wgpu::TexelCopyBufferInfo {
                    buffer: &readback,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: i as u64 * u64::from(row),
                        bytes_per_row: Some(row),
                        rows_per_image: Some(1),
                    },
                },
                extent,
            );
        }
        let submitted = queue.submit([encoder.finish()]);
        let (tx, rx) = mpsc::sync_channel(1);
        readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = tx.send(result);
            });
        device
            .poll(wgpu::PollType::Wait {
                submission_index: Some(submitted),
                timeout: Some(Duration::from_secs(30)),
            })
            .map_err(|e| format!("resident probe wait: {e}"))?;
        rx.recv_timeout(Duration::from_secs(1))
            .map_err(|e| format!("resident probe callback: {e}"))?
            .map_err(|e| format!("resident probe map: {e}"))?;
        let mapped = readback
            .slice(..)
            .get_mapped_range()
            .map_err(|e| format!("resident probe bytes: {e}"))?;
        let output = decode_samples(&mapped, row as usize, indices);
        drop(mapped);
        readback.unmap();
        output
    })();
    let validation = pollster::block_on(scope.pop());
    if let Some(error) = validation {
        return Err(format!(
            "resident probe validation: {error}; prior: {result:?}"
        ));
    }
    renderer.gpu.check_errors()?;
    result
}

#[cfg(test)]
fn exact_unorm_probe_shader(count: usize) -> String {
    let mut source = make_shader(Arithmetic::Current, Kind::Rigid, count).unwrap();
    assert_eq!(
        source
            .matches("let actual = original_vs_rigid(input);")
            .count(),
        1
    );
    source = source.replace(
        "let actual = original_vs_rigid(input);",
        "let actual = byte_probe(input);",
    );
    source.push_str(
        "\nfn byte_probe(input: RigidInput) -> VertexOutput {\n\
        var output: VertexOutput;\n\
        let exact = unorm8_exact(u32(input.position.x));\n\
        output.position = vec4<f32>(0.0,0.0,0.0,1.0);\n\
        output.uv = vec2<f32>(0.0);\n\
        output.color = vec4<f32>(exact,color_byte(input.position.y),exact,exact);\n\
        return output;\n}\n",
    );
    source
}

/// Explicit native test only. Compare every byte with the actual Unorm8x4
/// vertex-fetch path, and test the original truncation/saturation boundary.
#[cfg(test)]
pub(super) fn verify_exact_unorm(renderer: &mut WgpuRenderer, output: &std::path::Path) {
    use crate::draw::{Mesh, Vertex};
    use glam::{Vec2, Vec3, Vec4};
    let mut values: Vec<(u8, f32)> = (0u32..=255)
        .map(|byte| (byte as u8, ((f64::from(byte) + 0.25) / 255.0) as f32))
        .collect();
    values.extend([
        (0, -1.),
        (0, f32::NEG_INFINITY),
        (0, f32::NAN),
        (0, -0.),
        (0, f32::from_bits(1)),
        (255, 1.),
        (255, f32::INFINITY),
        (255, 2.),
    ]);
    let mesh = Mesh {
        vertices: values
            .iter()
            .map(|&(byte, value)| Vertex {
                position: Vec3::new(f32::from(byte), value, 0.),
                uv: Vec2::ZERO,
                color: [byte; 4],
                normal: Vec4::ZERO,
            })
            .collect(),
        indices: Vec::new(),
        texture: None,
    };
    let indices: Vec<_> = (0..values.len() as u32).collect();
    let cpu = capture_cpu_reference(renderer, &mesh, Mat4::IDENTITY, &indices).unwrap();
    let source = exact_unorm_probe_shader(indices.len());
    let bytes: Vec<_> = values
        .iter()
        .flat_map(|&(byte, value)| {
            [f32::from(byte), value, 0., 0., 0., 0., 0., 0.]
                .into_iter()
                .flat_map(f32::to_le_bytes)
        })
        .collect();
    let gpu = capture_prepared(
        renderer,
        &bytes,
        Kind::Rigid,
        &[0; 240],
        &resident::palette_bytes(None),
        &indices,
        source.clone(),
    )
    .unwrap();
    let rows: Vec<_> = values
        .iter()
        .zip(&cpu)
        .zip(&gpu)
        .map(|((&(byte, value), cpu), gpu)| {
            let expected = ((f64::from(byte) / 255.0) as f32).to_bits();
            serde_json::json!({"byte":byte,"input_bits":value.to_bits(),"expected_bits":expected,
            "cpu_unorm8x4_bits":cpu.color_bits,"shader_bits":gpu.color_bits})
        })
        .collect();
    std::fs::write(output.join("unorm-byte-report.json"), serde_json::to_vec_pretty(
        &serde_json::json!({"schema":"rust-duty-exact-unorm-byte-contract/v1",
            "production_shader_sha256":rust_duty_launcher::bytes_hash(include_bytes!("resident.wgsl")),
            "probe_shader_sha256":rust_duty_launcher::bytes_hash(source.as_bytes()),
            "byte_count":256,"boundary_count":8,"rows":rows})).unwrap()).unwrap();
    for ((&(byte, _), cpu), gpu) in values.iter().zip(&cpu).zip(&gpu) {
        let expected = [((f64::from(byte) / 255.0) as f32).to_bits(); 4];
        assert_eq!(cpu.color_bits, expected, "actual Unorm8x4 byte {byte}");
        assert_eq!(
            gpu.color_bits, expected,
            "exact shader conversion byte {byte}"
        );
    }
    eprintln!("resident exact UNORM conversion: all 256 vertex-fetch byte values and 8 saturation/truncation boundaries passed");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn skin_stage_draw(skin: bool) -> ResidentDraw {
        use crate::draw::resident::{ResidentMesh, RigidVertex, SkinPalette, SkinVertex};
        let vertices: Vec<_> = (0..4)
            .map(|i| RigidVertex {
                position: [i as f32 + 0.25, -0.0, -2.5],
                uv: [0.125 * i as f32, 0.75],
                normal: [0.0, 1.0, 0.0],
            })
            .collect();
        let geometry = if skin {
            Vertices::Skin {
                vertices: vertices
                    .into_iter()
                    .map(|vertex| SkinVertex {
                        vertex,
                        joints: [1, 0, 1, 0, 1, 0, 1, 0],
                        weights: [0.125; 8],
                    })
                    .collect(),
                bones: 2,
            }
        } else {
            Vertices::Rigid(vertices)
        };
        ResidentDraw::new(
            ResidentMesh::new(geometry, vec![0, 1, 2], None).unwrap(),
            Mat4::IDENTITY,
            crate::scene_lighting::SceneLighting::range(),
            crate::draw::Color::new(1.0, 1.0, 1.0, 1.0),
            1.0,
            skin.then(|| SkinPalette::new(vec![Mat4::IDENTITY; 2]).unwrap()),
        )
        .unwrap()
    }

    #[test]
    fn skin_stage_shaders_validate_and_preserve_original_clip_expressions() {
        for count in [1, 3, MAX_VERTICES / 2] {
            let source = skin_stage_shader_source(count).unwrap();
            let module = wgpu::naga::front::wgsl::parse_str(&source).unwrap();
            wgpu::naga::valid::Validator::new(
                wgpu::naga::valid::ValidationFlags::all(),
                wgpu::naga::valid::Capabilities::all(),
            )
            .validate(&module)
            .unwrap();
            // Reversing only the documented instrumentation restores the exact
            // original current-arithmetic probe with the doubled invocation count.
            let restored = source
                .replace(SKIN_STAGE_FIELDS, "struct VertexOutput {\n")
                .replace(SKIN_STAGE_VALUES, SKIN_STAGE_POSITION)
                .replace(SKIN_STAGE_ROUTE, "    output.color = actual.color;");
            assert_eq!(
                restored,
                shader_source(Arithmetic::Current, true, count * 2).unwrap()
            );
            assert_eq!(source.matches("output.clip = actual.position;").count(), 1);
            assert_eq!(
                source
                    .matches(
                        "output.position = draw.view_projection * vec4<f32>(world_position, 1.0);"
                    )
                    .count(),
                1
            );
            assert_eq!(source.matches(SKIN_STAGE_ROUTE).count(), 1);
        }
        for count in [0, MAX_VERTICES / 2 + 1, MAX_VERTICES, usize::MAX] {
            assert!(skin_stage_shader_source(count).is_err());
        }
    }

    #[test]
    fn skin_stage_shader_rejects_missing_or_ambiguous_substitution_anchors() {
        let original = include_str!("resident.wgsl");
        let template = include_str!("resident_vertex_probe.wgsl");
        for anchor in [
            "struct VertexOutput {\n",
            SKIN_STAGE_POSITION,
            "@vertex fn vs_rigid(",
            "@vertex fn vs_skin(",
        ] {
            for changed in [
                original.replacen(anchor, "", 1),
                format!("{original}\n{anchor}"),
            ] {
                assert!(make_skin_stage_shader(&changed, template, 1).is_err());
            }
        }
        for anchor in [
            "__INPUT__",
            "__ENTRY__",
            "__COUNT__",
            "    output.color = actual.color;",
        ] {
            for changed in [
                template.replacen(anchor, "", 1),
                format!("{template}\n{anchor}"),
            ] {
                assert!(make_skin_stage_shader(original, &changed, 1).is_err());
            }
        }
    }

    #[test]
    fn skin_stage_selection_duplicates_exact_wire_bytes_in_requested_order() {
        let draw = skin_stage_draw(true);
        let indices = [3, 0, 3, 1];
        let (selected, is_skin) = selected_bytes(&draw, &indices).unwrap();
        let (duplicated, bones) = selected_skin_stage_bytes(&draw, &indices).unwrap();
        assert!(is_skin);
        assert_eq!(bones, 2);
        assert_eq!(duplicated.len(), indices.len() * 2 * 80);
        let all = resident::vertices(draw.mesh());
        for (i, &source_vertex) in indices.iter().enumerate() {
            let original = &all[source_vertex as usize * 80..(source_vertex as usize + 1) * 80];
            assert_eq!(&selected[i * 80..(i + 1) * 80], original);
            assert_eq!(&duplicated[i * 160..i * 160 + 80], original);
            assert_eq!(&duplicated[i * 160 + 80..(i + 1) * 160], original);
        }
        // Signed zero, u16 joint order, and all eight weights survive unchanged.
        assert_eq!(&duplicated[4..8], &(-0.0f32).to_le_bytes());
        assert_eq!(
            &duplicated[32..48],
            &[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
        );
        assert_eq!(&duplicated[48..80], &0.125f32.to_le_bytes().repeat(8));
        let (maximum, _) = selected_skin_stage_bytes(&draw, &[0; MAX_VERTICES / 2]).unwrap();
        assert_eq!(maximum.len(), MAX_VERTICES * 80);
    }

    #[test]
    fn skin_stage_selection_rejects_non_skin_unbounded_and_invalid_indices() {
        let draw = skin_stage_draw(true);
        for indices in [
            vec![],
            vec![0; MAX_VERTICES / 2 + 1],
            vec![4],
            vec![u32::MAX],
        ] {
            assert!(selected_skin_stage_bytes(&draw, &indices).is_err());
        }
        assert!(selected_skin_stage_bytes(&skin_stage_draw(false), &[0])
            .unwrap_err()
            .contains("skin geometry and palette"));
    }

    #[test]
    fn skin_stage_samples_keep_both_clip_results_and_reject_bad_pairing() {
        let indices = [3, 0, 3];
        let mut raw: Vec<_> = indices
            .iter()
            .flat_map(|&source_vertex| [source_vertex, source_vertex])
            .enumerate()
            .map(|(i, source_vertex)| VertexSample {
                source_vertex,
                clip_bits: [i as u32, 0x80000000, 0x7fc00001, 0x7f800000],
                color_bits: [i as u32 + 1, 0xffffffff, 0x80000000, 1.0f32.to_bits()],
            })
            .collect();
        let samples = skin_stage_samples(&raw, &indices).unwrap();
        for (i, sample) in samples.iter().enumerate() {
            assert_eq!(sample.source_vertex, indices[i]);
            assert_eq!(sample.skin_position_bits, raw[i * 2].color_bits);
            assert_eq!(sample.world_position_bits, raw[i * 2 + 1].color_bits);
            assert_eq!(sample.skin_route_clip_bits, raw[i * 2].clip_bits);
            assert_eq!(sample.world_route_clip_bits, raw[i * 2 + 1].clip_bits);
            assert_ne!(sample.skin_route_clip_bits, sample.world_route_clip_bits);
        }
        assert!(skin_stage_samples(&raw[..5], &indices).is_err());
        assert!(skin_stage_samples(&raw, &[]).is_err());
        raw[1].source_vertex = 2;
        assert!(skin_stage_samples(&raw, &indices).is_err());
    }

    #[test]
    fn exhaustive_byte_probe_shader_validates_without_a_gpu() {
        let module = wgpu::naga::front::wgsl::parse_str(&exact_unorm_probe_shader(264)).unwrap();
        wgpu::naga::valid::Validator::new(
            wgpu::naga::valid::ValidationFlags::all(),
            wgpu::naga::valid::Capabilities::all(),
        )
        .validate(&module)
        .unwrap();
    }
    #[test]
    fn unwritten_points_are_not_zero_samples_and_nonfinite_bits_are_retained() {
        let mut bytes = vec![255; 512];
        assert!(decode_samples(&bytes, 256, &[7])
            .unwrap_err()
            .contains("not written"));
        bytes[256..272].fill(0);
        let sample = decode_samples(&bytes, 256, &[7]).unwrap();
        assert_eq!(sample[0].clip_bits, [u32::MAX; 4]);
        assert_eq!(sample[0].color_bits, [0; 4]);
        assert_eq!(sample[0].source_vertex, 7);
        assert!(decode_samples(&bytes[..511], 256, &[7]).is_err());
        assert!(decode_samples(&bytes, 256, &[0; 17]).is_err());
    }
    #[test]
    fn all_bounded_probe_shaders_validate_and_control_is_one_operation() {
        for skin in [false, true] {
            for count in [1, 3, MAX_VERTICES] {
                let current = shader_source(Arithmetic::Current, skin, count).unwrap();
                let historical =
                    shader_source(Arithmetic::HistoricalInverseSqrt, skin, count).unwrap();
                assert_eq!(current.replacen(CURRENT, HISTORICAL, 1), historical);
                for source in [current, historical] {
                    let module = wgpu::naga::front::wgsl::parse_str(&source).unwrap();
                    wgpu::naga::valid::Validator::new(
                        wgpu::naga::valid::ValidationFlags::all(),
                        wgpu::naga::valid::Capabilities::all(),
                    )
                    .validate(&module)
                    .unwrap();
                }
            }
        }
        assert!(shader_source(Arithmetic::Current, true, 0).is_err());
        assert!(shader_source(Arithmetic::Current, true, MAX_VERTICES + 1).is_err());
        let cpu = make_shader(Arithmetic::Current, Kind::Cpu, 3).unwrap();
        let module = wgpu::naga::front::wgsl::parse_str(&cpu).unwrap();
        wgpu::naga::valid::Validator::new(
            wgpu::naga::valid::ValidationFlags::all(),
            wgpu::naga::valid::Capabilities::all(),
        )
        .validate(&module)
        .unwrap();
    }
}
