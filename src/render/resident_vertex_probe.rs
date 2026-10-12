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
mod tests {
    use super::*;
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
