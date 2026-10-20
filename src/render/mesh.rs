//! Trivial CPU-lit mesh pipeline. Never upload the padded public glam vertex directly.
use crate::draw::{BlendMode, TextureSource};

use std::collections::HashMap;
use wgpu::util::DeviceExt;

pub(crate) use super::arena::GpuVertex;
use super::arena::{FrameArena, MATRIX_BYTES};
impl GpuVertex {
    pub const ATTRIBUTES: [wgpu::VertexAttribute; 4] =
        wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Unorm8x4,3=>Float32x4];
}
/// Fragment output representation is part of the pipeline key, not inferred
/// from an RGBA sample's alpha (emissive targets can contain RGB at alpha zero).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) enum FragmentKind {
    Straight,
    AssociateStraight,
    Associated,
    Present,
}
impl FragmentKind {
    pub fn for_source(source: &TextureSource, blend: BlendMode) -> Self {
        match source {
            TextureSource::Rgba8(_) if blend == BlendMode::Opaque => Self::AssociateStraight,
            TextureSource::Rgba8(_) => Self::Straight,
            TextureSource::Target { .. } => Self::Associated,
        }
    }
    fn entry_point(self) -> &'static str {
        match self {
            Self::Straight => "fs_straight",
            Self::AssociateStraight => "fs_associate_straight",
            Self::Associated => "fs_associated",
            Self::Present => "fs_present",
        }
    }
}
fn blend_state(mode: BlendMode, fragment: FragmentKind) -> Option<wgpu::BlendState> {
    let source_color = match fragment {
        FragmentKind::Straight => wgpu::BlendFactor::SrcAlpha,
        FragmentKind::AssociateStraight | FragmentKind::Associated | FragmentKind::Present => {
            wgpu::BlendFactor::One
        }
    };
    match mode {
        BlendMode::Opaque => None,
        BlendMode::Alpha => Some(wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: source_color,
                dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
                operation: wgpu::BlendOperation::Add,
            },
            alpha: wgpu::BlendComponent::OVER,
        }),
        BlendMode::Additive => Some(wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: source_color,
                dst_factor: wgpu::BlendFactor::One,
                operation: wgpu::BlendOperation::Add,
            },
            // Additive muzzle flashes must not change the target's coverage alpha.
            alpha: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::Zero,
                dst_factor: wgpu::BlendFactor::One,
                operation: wgpu::BlendOperation::Add,
            },
        }),
    }
}
fn depth_state(enabled: bool, blend: BlendMode) -> Option<wgpu::DepthStencilState> {
    enabled.then_some(wgpu::DepthStencilState {
        format: super::target::DEPTH_FORMAT,
        // Preserve legacy alpha-mesh depth writes (including actor opacity).
        // Only additive effects are depth-read-only; UI disables depth entirely.
        depth_write_enabled: Some(blend != BlendMode::Additive),
        depth_compare: Some(wgpu::CompareFunction::LessEqual),
        stencil: Default::default(),
        bias: Default::default(),
    })
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
struct PipelineKey {
    format: wgpu::TextureFormat,
    depth: bool,
    lines: bool,
    blend: u8,
    fragment: FragmentKind,
}
/// Capture-only snapshot of the exact descriptor passed to pipeline creation.
/// This is retained beside its existing cache entry, never reconstructed from
/// requested draw flags. Ordinary play does not allocate these snapshots.
#[derive(Clone, Debug, PartialEq)]
struct VisibilityVertexBuffer {
    stride: u64,
    step: wgpu::VertexStepMode,
    attributes: Vec<wgpu::VertexAttribute>,
}
#[derive(Clone, Debug, PartialEq)]
struct VisibilityPipelineDescriptor {
    owned_shader_bound: bool,
    owned_layout_bound: bool,
    vertex_entry: Option<String>,
    vertex_buffers: Vec<Option<VisibilityVertexBuffer>>,
    vertex_constants_empty: bool,
    fragment_constants_empty: bool,
    fragment_entry: Option<String>,
    primitive: wgpu::PrimitiveState,
    depth_stencil: Option<wgpu::DepthStencilState>,
    multisample: wgpu::MultisampleState,
    targets: Vec<Option<wgpu::ColorTargetState>>,
    multiview: bool,
}
impl VisibilityPipelineDescriptor {
    fn capture(
        descriptor: &wgpu::RenderPipelineDescriptor<'_>,
        shader: &wgpu::ShaderModule,
        layout: &wgpu::PipelineLayout,
        shader_source_bound: bool,
    ) -> Self {
        let fragment = descriptor.fragment.as_ref();
        Self {
            owned_shader_bound: shader_source_bound
                && std::ptr::eq(descriptor.vertex.module, shader)
                && fragment.is_some_and(|state| std::ptr::eq(state.module, shader)),
            owned_layout_bound: descriptor
                .layout
                .is_some_and(|bound| std::ptr::eq(bound, layout)),
            vertex_entry: descriptor.vertex.entry_point.map(str::to_owned),
            vertex_buffers: descriptor
                .vertex
                .buffers
                .iter()
                .map(|buffer| {
                    buffer.as_ref().map(|buffer| VisibilityVertexBuffer {
                        stride: buffer.array_stride,
                        step: buffer.step_mode,
                        attributes: buffer.attributes.to_vec(),
                    })
                })
                .collect(),
            vertex_constants_empty: descriptor.vertex.compilation_options.constants.is_empty(),
            fragment_constants_empty: fragment
                .is_some_and(|state| state.compilation_options.constants.is_empty()),
            fragment_entry: fragment
                .and_then(|state| state.entry_point)
                .map(str::to_owned),
            primitive: descriptor.primitive,
            depth_stencil: descriptor.depth_stencil.clone(),
            multisample: descriptor.multisample,
            targets: fragment.map_or_else(Vec::new, |state| state.targets.to_vec()),
            multiview: descriptor.multiview_mask.is_some(),
        }
    }
    fn validate(
        &self,
        depth: bool,
        blend: BlendMode,
        fragment: FragmentKind,
    ) -> Result<(), String> {
        let witness = match (depth, blend, fragment) {
            (true, BlendMode::Alpha, FragmentKind::Straight) => false,
            (false, BlendMode::Opaque, FragmentKind::AssociateStraight) => true,
            _ => return Err("visibility receipt does not support this WGPU draw pipeline".into()),
        };
        // Independent canonical byte layout: do not compare against the same
        // GpuVertex constants whose accidental drift this check must detect.
        let attributes = [
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Float32x3,
                offset: 0,
                shader_location: 0,
            },
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Float32x2,
                offset: 12,
                shader_location: 1,
            },
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Unorm8x4,
                offset: 20,
                shader_location: 2,
            },
            wgpu::VertexAttribute {
                format: wgpu::VertexFormat::Float32x4,
                offset: 24,
                shader_location: 3,
            },
        ];
        let [Some(vertex)] = self.vertex_buffers.as_slice() else {
            return Err("visibility WGPU pipeline requires one vertex buffer".into());
        };
        let [Some(target)] = self.targets.as_slice() else {
            return Err("visibility WGPU pipeline requires one color target".into());
        };
        let expected_depth = (!witness).then_some(wgpu::DepthStencilState {
            format: wgpu::TextureFormat::Depth32Float,
            depth_write_enabled: Some(true),
            depth_compare: Some(wgpu::CompareFunction::LessEqual),
            stencil: Default::default(),
            bias: Default::default(),
        });
        let expected_blend = (!witness).then_some(wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::SrcAlpha,
                dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
                operation: wgpu::BlendOperation::Add,
            },
            alpha: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::One,
                dst_factor: wgpu::BlendFactor::OneMinusSrcAlpha,
                operation: wgpu::BlendOperation::Add,
            },
        });
        if !self.owned_shader_bound
            || !self.owned_layout_bound
            || self.vertex_entry.as_deref() != Some("vs_main")
            || self.fragment_entry.as_deref()
                != Some(if witness {
                    "fs_associate_straight"
                } else {
                    "fs_straight"
                })
            || !self.vertex_constants_empty
            || !self.fragment_constants_empty
            || vertex.stride != 40
            || vertex.step != wgpu::VertexStepMode::Vertex
            || vertex.attributes.as_slice() != attributes
            || self.primitive
                != (wgpu::PrimitiveState {
                    topology: wgpu::PrimitiveTopology::TriangleList,
                    front_face: wgpu::FrontFace::Ccw,
                    cull_mode: None,
                    ..Default::default()
                })
            || self.depth_stencil != expected_depth
            || self.multisample != wgpu::MultisampleState::default()
            || target.format != wgpu::TextureFormat::Rgba8Unorm
            || target.blend != expected_blend
            || target.write_mask != wgpu::ColorWrites::ALL
            || self.multiview
        {
            return Err(
                "visibility WGPU creation descriptor differs from supported submitted state".into(),
            );
        }
        Ok(())
    }
}
struct CachedPipeline {
    pipeline: wgpu::RenderPipeline,
    visibility: Option<Box<VisibilityPipelineDescriptor>>,
}

pub(crate) struct Pipelines {
    pub texture_layout: wgpu::BindGroupLayout,
    transform_layout: wgpu::BindGroupLayout,
    layout: wgpu::PipelineLayout,
    shader: wgpu::ShaderModule,
    pipelines: HashMap<PipelineKey, CachedPipeline>,
    capture_receipts: bool,
    shader_source_bound: bool,
}
pub(crate) struct FrameGeometry {
    pub vertices: Option<wgpu::Buffer>,
    pub indices: Option<wgpu::Buffer>,
    pub transform: wgpu::BindGroup,
}
impl Pipelines {
    pub fn new(device: &wgpu::Device) -> Self {
        let transform_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("mesh transform layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: true,
                    min_binding_size: wgpu::BufferSize::new(64),
                },
                count: None,
            }],
        });
        let texture_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("CPU-lit mesh texture layout"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("CPU-lit mesh pipeline layout"),
            bind_group_layouts: &[Some(&transform_layout), Some(&texture_layout)],
            immediate_size: 0,
        });
        // Capture receipts start after warm-up, so retain creation inputs for
        // explicit witness runs even before their first frame request exists.
        let capture_receipts = cfg!(all(windows, target_arch = "x86_64"))
            && std::env::args().any(|arg| arg.starts_with("--capture-frame-witness="));
        let shader_descriptor = wgpu::ShaderModuleDescriptor {
            label: Some("CPU-lit mesh shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("mesh.wgsl").into()),
        };
        let shader_source_bound = capture_receipts
            && matches!(&shader_descriptor.source,
                wgpu::ShaderSource::Wgsl(source) if source.as_ref() == include_str!("mesh.wgsl"));
        let shader = device.create_shader_module(shader_descriptor);
        Self {
            texture_layout,
            transform_layout,
            layout,
            shader,
            pipelines: HashMap::new(),
            capture_receipts,
            shader_source_bound,
        }
    }
    pub fn pipeline(
        &mut self,
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        depth: bool,
        lines: bool,
        blend: BlendMode,
        fragment: FragmentKind,
    ) -> wgpu::RenderPipeline {
        self.cached_pipeline(device, format, depth, lines, blend, fragment)
            .pipeline
            .clone()
    }
    /// Return the exact cache entry whose actual creation descriptor passed the
    /// capture contract. A missing or unsupported snapshot never emits evidence.
    pub fn visibility_pipeline(
        &mut self,
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        depth: bool,
        lines: bool,
        blend: BlendMode,
        fragment: FragmentKind,
    ) -> Result<wgpu::RenderPipeline, String> {
        let cached = self.cached_pipeline(device, format, depth, lines, blend, fragment);
        cached
            .visibility
            .as_ref()
            .ok_or("visibility pipeline lacks capture-time creation snapshot")?
            .validate(depth, blend, fragment)?;
        Ok(cached.pipeline.clone())
    }
    fn cached_pipeline(
        &mut self,
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        depth: bool,
        lines: bool,
        blend: BlendMode,
        fragment: FragmentKind,
    ) -> &CachedPipeline {
        let key = PipelineKey {
            format,
            depth,
            lines,
            fragment,
            blend: match blend {
                BlendMode::Opaque => 0,
                BlendMode::Alpha => 1,
                BlendMode::Additive => 2,
            },
        };
        self.pipelines.entry(key).or_insert_with(|| {
            let vertex_buffers = [Some(wgpu::VertexBufferLayout {
                array_stride: GpuVertex::STRIDE,
                step_mode: wgpu::VertexStepMode::Vertex,
                attributes: &GpuVertex::ATTRIBUTES,
            })];
            let targets = [Some(wgpu::ColorTargetState {
                format,
                blend: blend_state(blend, fragment),
                write_mask: wgpu::ColorWrites::ALL,
            })];
            let descriptor = wgpu::RenderPipelineDescriptor {
                label: Some("CPU-lit mesh pipeline"),
                layout: Some(&self.layout),
                vertex: wgpu::VertexState {
                    module: &self.shader,
                    entry_point: Some("vs_main"),
                    compilation_options: Default::default(),
                    buffers: &vertex_buffers,
                },
                primitive: wgpu::PrimitiveState {
                    topology: if lines {
                        wgpu::PrimitiveTopology::LineList
                    } else {
                        wgpu::PrimitiveTopology::TriangleList
                    },
                    front_face: wgpu::FrontFace::Ccw,
                    cull_mode: None,
                    ..Default::default()
                },
                depth_stencil: depth_state(depth, blend),
                multisample: Default::default(),
                fragment: Some(wgpu::FragmentState {
                    module: &self.shader,
                    entry_point: Some(fragment.entry_point()),
                    compilation_options: Default::default(),
                    targets: &targets,
                }),
                multiview_mask: None,
                cache: None,
            };
            let visibility = self.capture_receipts.then(|| {
                Box::new(VisibilityPipelineDescriptor::capture(
                    &descriptor,
                    &self.shader,
                    &self.layout,
                    self.shader_source_bound,
                ))
            });
            CachedPipeline {
                pipeline: device.create_render_pipeline(&descriptor),
                visibility,
            }
        })
    }
    /// Later finite corroboration only. Reuse the production VS module, layout,
    /// primitive state and single-sample target; change only the fragment stage
    /// and disable depth/blend so every submitted primitive remains observable.
    pub(super) fn finite_probe_coverage_pipeline(
        &self,
        device: &wgpu::Device,
        source: &str,
        entry: &str,
    ) -> wgpu::RenderPipeline {
        let coverage = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("finite probe coverage-only fragment"),
            source: wgpu::ShaderSource::Wgsl(source.into()),
        });
        device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("later finite coverage corroboration"),
            layout: Some(&self.layout),
            vertex: wgpu::VertexState {
                module: &self.shader,
                entry_point: Some("vs_main"),
                compilation_options: Default::default(),
                buffers: &[Some(wgpu::VertexBufferLayout {
                    array_stride: GpuVertex::STRIDE,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &GpuVertex::ATTRIBUTES,
                })],
            },
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: Default::default(),
            fragment: Some(wgpu::FragmentState {
                module: &coverage,
                entry_point: Some(entry),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: super::target::COLOR_FORMAT,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            multiview_mask: None,
            cache: None,
        })
    }
    /// Up to three immutable buffers and one transform binding per chunk.
    /// Static-only chunks allocate the matrix buffer, never empty geometry.
    /// No storage is shared with a subsequent frame. wgpu retains all buffers
    /// referenced by recorded commands until their submission is finished.
    pub fn upload_geometry(
        &self,
        device: &wgpu::Device,
        arena: &FrameArena,
    ) -> Option<FrameGeometry> {
        let [vertices, indices, matrices] = arena.buffer_contents()?;
        let upload = |label, contents: &[u8], usage| {
            device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents,
                usage,
            })
        };
        let vertices = (!vertices.is_empty())
            .then(|| upload("frame vertices", vertices, wgpu::BufferUsages::VERTEX));
        let indices = (!indices.is_empty())
            .then(|| upload("frame indices", indices, wgpu::BufferUsages::INDEX));
        let uniform = upload("frame transforms", matrices, wgpu::BufferUsages::UNIFORM);
        let transform = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("frame chunk transform slots"),
            layout: &self.transform_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                    buffer: &uniform,
                    offset: 0,
                    // Bind one matrix, not the entire arena: the dynamic offset
                    // chooses each draw without exceeding uniform binding limits.
                    size: wgpu::BufferSize::new(MATRIX_BYTES),
                }),
            }],
        });
        Some(FrameGeometry {
            vertices,
            indices,
            transform,
        })
    }
}
#[cfg(test)]
mod tests {
    use super::super::arena::clip_matrix;
    use super::*;
    use crate::draw::Vertex;
    use glam::{Mat4, Vec2, Vec3, Vec4};
    use std::mem::{offset_of, size_of};
    fn visibility_descriptor(witness: bool) -> VisibilityPipelineDescriptor {
        let blend = if witness {
            BlendMode::Opaque
        } else {
            BlendMode::Alpha
        };
        let fragment = if witness {
            FragmentKind::AssociateStraight
        } else {
            FragmentKind::Straight
        };
        VisibilityPipelineDescriptor {
            owned_shader_bound: true,
            owned_layout_bound: true,
            vertex_entry: Some("vs_main".into()),
            vertex_buffers: vec![Some(VisibilityVertexBuffer {
                stride: GpuVertex::STRIDE,
                step: wgpu::VertexStepMode::Vertex,
                attributes: GpuVertex::ATTRIBUTES.to_vec(),
            })],
            vertex_constants_empty: true,
            fragment_constants_empty: true,
            fragment_entry: Some(fragment.entry_point().into()),
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                front_face: wgpu::FrontFace::Ccw,
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: depth_state(!witness, blend),
            multisample: Default::default(),
            targets: vec![Some(wgpu::ColorTargetState {
                format: super::super::target::COLOR_FORMAT,
                blend: blend_state(blend, fragment),
                write_mask: wgpu::ColorWrites::ALL,
            })],
            multiview: false,
        }
    }
    #[test]
    fn visibility_descriptor_accepts_only_scene_and_witness_contracts() {
        visibility_descriptor(false)
            .validate(true, BlendMode::Alpha, FragmentKind::Straight)
            .unwrap();
        visibility_descriptor(true)
            .validate(false, BlendMode::Opaque, FragmentKind::AssociateStraight)
            .unwrap();
        assert!(visibility_descriptor(false)
            .validate(false, BlendMode::Alpha, FragmentKind::Straight)
            .is_err());
        assert!(visibility_descriptor(false)
            .validate(true, BlendMode::Additive, FragmentKind::Straight)
            .is_err());
        assert!(visibility_descriptor(false)
            .validate(true, BlendMode::Alpha, FragmentKind::Associated)
            .is_err());
        assert!(visibility_descriptor(true)
            .validate(false, BlendMode::Opaque, FragmentKind::Present)
            .is_err());
    }
    #[test]
    fn visibility_descriptor_rejects_creation_layout_shader_and_raster_drift() {
        let mutations: &[fn(&mut VisibilityPipelineDescriptor)] = &[
            |state| state.owned_shader_bound = false,
            |state| state.owned_layout_bound = false,
            |state| state.vertex_entry = Some("other_vertex".into()),
            |state| state.fragment_entry = Some("fs_associated".into()),
            |state| state.vertex_constants_empty = false,
            |state| state.fragment_constants_empty = false,
            |state| state.vertex_buffers[0].as_mut().unwrap().stride = 24,
            |state| state.vertex_buffers[0].as_mut().unwrap().step = wgpu::VertexStepMode::Instance,
            |state| state.vertex_buffers[0].as_mut().unwrap().attributes[0].offset = 4,
            |state| state.vertex_buffers[0].as_mut().unwrap().attributes[2].shader_location = 3,
            |state| {
                state.vertex_buffers[0].as_mut().unwrap().attributes[2].format =
                    wgpu::VertexFormat::Uint8x4;
            },
            |state| state.vertex_buffers.clear(),
            |state| state.primitive.cull_mode = Some(wgpu::Face::Back),
            |state| state.primitive.topology = wgpu::PrimitiveTopology::LineList,
            |state| state.primitive.unclipped_depth = true,
            |state| state.depth_stencil.as_mut().unwrap().depth_write_enabled = Some(false),
            |state| {
                state.depth_stencil.as_mut().unwrap().depth_compare =
                    Some(wgpu::CompareFunction::Always);
            },
            |state| state.depth_stencil.as_mut().unwrap().bias.constant = 1,
            |state| state.targets[0].as_mut().unwrap().format = wgpu::TextureFormat::Bgra8Unorm,
            |state| state.targets[0].as_mut().unwrap().blend = None,
            |state| state.targets[0].as_mut().unwrap().write_mask = wgpu::ColorWrites::empty(),
            |state| state.targets.clear(),
            |state| state.multisample.count = 4,
            |state| state.multisample.mask = 0,
            |state| state.multisample.alpha_to_coverage_enabled = true,
            |state| state.multiview = true,
        ];
        for (index, mutate) in mutations.iter().enumerate() {
            let mut descriptor = visibility_descriptor(false);
            mutate(&mut descriptor);
            assert!(
                descriptor
                    .validate(true, BlendMode::Alpha, FragmentKind::Straight)
                    .is_err(),
                "descriptor mutation {index} unexpectedly accepted"
            );
        }
        let mut witness = visibility_descriptor(true);
        witness.depth_stencil = depth_state(true, BlendMode::Opaque);
        assert!(witness
            .validate(false, BlendMode::Opaque, FragmentKind::AssociateStraight)
            .is_err());
    }
    #[test]
    fn packed_vertex_has_exact_offsets_and_no_glam_padding() {
        assert_eq!(size_of::<GpuVertex>(), 40);
        assert_eq!(
            [
                offset_of!(GpuVertex, position),
                offset_of!(GpuVertex, uv),
                offset_of!(GpuVertex, color),
                offset_of!(GpuVertex, normal)
            ],
            [0, 12, 20, 24]
        );
        let source = Vertex {
            position: Vec3::new(1., 2., 3.),
            uv: Vec2::new(4., 5.),
            color: [6, 7, 8, 9],
            normal: Vec4::new(10., 11., 12., 13.),
        };
        let mut bytes = Vec::new();
        GpuVertex::from(source).append_bytes(&mut bytes);
        assert_eq!(bytes.len(), 40);
        assert_eq!(&bytes[20..24], &[6, 7, 8, 9]);
        assert_eq!(f32::from_le_bytes(bytes[24..28].try_into().unwrap()), 10.);
        assert_eq!(GpuVertex::ATTRIBUTES.map(|a| a.offset), [0, 12, 20, 24]);
    }
    #[test]
    fn depth_remap_preserves_handedness_and_applies_model_once() {
        let matrix = clip_matrix(Mat4::IDENTITY, Mat4::IDENTITY);
        for (z, want) in [(-1., 0.), (0., 0.5), (1., 1.)] {
            assert_eq!(
                matrix.project_point3(Vec3::new(0.25, 0.75, z)),
                Vec3::new(0.25, 0.75, want)
            );
        }
        let matrix = clip_matrix(
            Mat4::orthographic_rh_gl(0., 100., 50., 0., -1., 1.),
            Mat4::from_translation(Vec3::new(10., 5., 0.)),
        );
        assert!(matrix
            .project_point3(Vec3::ZERO)
            .abs_diff_eq(Vec3::new(-0.8, 0.8, 0.5), 1e-6));
    }
    #[test]
    fn additive_preserves_destination_alpha() {
        let state = blend_state(BlendMode::Additive, FragmentKind::Straight).unwrap();
        assert_eq!(state.color.src_factor, wgpu::BlendFactor::SrcAlpha);
        assert_eq!(state.alpha.src_factor, wgpu::BlendFactor::Zero);
        assert_eq!(state.alpha.dst_factor, wgpu::BlendFactor::One);
    }
    // Interpret only the arithmetic expressions actually emitted by our WGSL
    // entry points. This is CPU contract coverage, not a claim of GPU execution.
    // A new shader operation fails explicitly until this evaluator handles it.
    fn shade(fragment: FragmentKind, sample: [f32; 4], tint: [f32; 4]) -> [f32; 4] {
        use wgpu::naga::{self, Expression as E, Statement};
        let module = naga::front::wgsl::parse_str(include_str!("mesh.wgsl")).unwrap();
        naga::valid::Validator::new(
            naga::valid::ValidationFlags::all(),
            naga::valid::Capabilities::all(),
        )
        .validate(&module)
        .unwrap();
        let function = &module
            .entry_points
            .iter()
            .find(|entry| entry.name == fragment.entry_point())
            .unwrap()
            .function;
        fn eval(
            expressions: &naga::Arena<E>,
            expression: naga::Handle<E>,
            sample: [f32; 4],
            tint: [f32; 4],
        ) -> Vec<f32> {
            let recurse = |handle| eval(expressions, handle, sample, tint);
            match &expressions[expression] {
                E::ImageSample { .. } => sample.to_vec(),
                E::Literal(naga::Literal::F32(value)) => vec![*value],
                E::AccessIndex { base, index }
                    if matches!(expressions[*base], E::FunctionArgument(0)) =>
                {
                    assert_eq!(*index, 2, "only VertexOutput.color is fixture input");
                    tint.to_vec()
                }
                E::AccessIndex { base, index } => vec![recurse(*base)[*index as usize]],
                E::Swizzle {
                    size,
                    vector,
                    pattern,
                } => {
                    let values = recurse(*vector);
                    pattern[..*size as usize]
                        .iter()
                        .map(|p| values[*p as usize])
                        .collect()
                }
                E::Compose { components, .. } => {
                    components.iter().flat_map(|c| recurse(*c)).collect()
                }
                E::Binary {
                    op: naga::BinaryOperator::Multiply,
                    left,
                    right,
                } => {
                    let left = recurse(*left);
                    let right = recurse(*right);
                    (0..left.len().max(right.len()))
                        .map(|i| left[i % left.len()] * right[i % right.len()])
                        .collect()
                }
                other => panic!("unhandled shader arithmetic: {other:?}"),
            }
        }
        let result = function
            .body
            .iter()
            .find_map(|statement| match statement {
                Statement::Return { value } => *value,
                Statement::Emit(_) => None,
                other => panic!("unhandled shader statement: {other:?}"),
            })
            .unwrap();
        eval(&function.expressions, result, sample, tint)
            .try_into()
            .unwrap()
    }

    fn composite(
        blend: BlendMode,
        fragment: FragmentKind,
        source: [f32; 4],
        destination: [f32; 4],
    ) -> [f32; 4] {
        let Some(state) = blend_state(blend, fragment) else {
            return source;
        };
        let factor = |factor| match factor {
            wgpu::BlendFactor::Zero => 0.,
            wgpu::BlendFactor::One => 1.,
            wgpu::BlendFactor::SrcAlpha => source[3],
            wgpu::BlendFactor::OneMinusSrcAlpha => 1. - source[3],
            other => panic!("unhandled blend factor: {other:?}"),
        };
        std::array::from_fn(|i| {
            let component = if i == 3 { state.alpha } else { state.color };
            assert_eq!(component.operation, wgpu::BlendOperation::Add);
            source[i] * factor(component.src_factor) + destination[i] * factor(component.dst_factor)
        })
    }

    #[test]
    fn image_and_glyph_straight_alpha_blending_is_unchanged() {
        let fragment =
            FragmentKind::for_source(&TextureSource::Rgba8(vec![255; 4].into()), BlendMode::Alpha);
        assert_eq!(fragment, FragmentKind::Straight);
        assert_eq!(
            blend_state(BlendMode::Alpha, fragment),
            Some(wgpu::BlendState::ALPHA_BLENDING)
        );
        let source = shade(fragment, [1., 0.5, 0.25, 0.5], [0.5, 1., 1., 0.5]);
        assert_eq!(source, [0.5, 0.5, 0.25, 0.25]);
        assert_eq!(
            composite(BlendMode::Alpha, fragment, source, [0.; 4]),
            [0.125, 0.125, 0.0625, 0.25]
        );
    }

    #[test]
    fn half_alpha_white_survives_target_composite_without_second_alpha() {
        let image =
            FragmentKind::for_source(&TextureSource::Rgba8(vec![255; 4].into()), BlendMode::Alpha);
        let target =
            FragmentKind::for_source(&TextureSource::Target { depth: true }, BlendMode::Alpha);
        let stored = composite(
            BlendMode::Alpha,
            image,
            shade(image, [1.; 4], [1., 1., 1., 0.5]),
            [0.; 4],
        );
        assert_eq!(stored, [0.5; 4]);
        assert_eq!(
            composite(
                BlendMode::Alpha,
                target,
                shade(target, stored, [1.; 4]),
                [0., 0., 0., 1.]
            ),
            [0.5, 0.5, 0.5, 1.]
        );
    }

    #[test]
    fn target_opacity_scales_radiance_and_coverage_once() {
        let target =
            FragmentKind::for_source(&TextureSource::Target { depth: false }, BlendMode::Alpha);
        let source = shade(target, [0.5; 4], [0.5, 0.25, 1., 0.5]);
        assert_eq!(source, [0.125, 0.0625, 0.25, 0.25]);
        assert_eq!(
            composite(BlendMode::Alpha, target, source, [0.25, 0.5, 0.75, 1.]),
            [0.3125, 0.4375, 0.8125, 1.]
        );
    }

    #[test]
    fn zero_alpha_emission_survives_alpha_and_additive_target_composites() {
        let image =
            FragmentKind::for_source(&TextureSource::Rgba8(vec![255; 4].into()), BlendMode::Alpha);
        let target =
            FragmentKind::for_source(&TextureSource::Target { depth: false }, BlendMode::Alpha);
        let emission = composite(
            BlendMode::Additive,
            image,
            shade(image, [1.; 4], [1., 0., 0., 0.5]),
            [0.; 4],
        );
        assert_eq!(emission, [0.5, 0., 0., 0.]);
        let tinted = shade(target, emission, [1., 1., 1., 0.5]);
        for mode in [BlendMode::Alpha, BlendMode::Additive] {
            assert_eq!(
                composite(mode, target, tinted, [0.125, 0.25, 0.5, 0.75]),
                [0.375, 0.25, 0.5, 0.75]
            );
        }
        assert_eq!(shade(target, emission, [1., 1., 1., 0.]), [0.; 4]);
    }

    #[test]
    fn opaque_replacement_still_stores_associated_straight_sources() {
        let fragment = FragmentKind::for_source(
            &TextureSource::Rgba8(vec![255; 4].into()),
            BlendMode::Opaque,
        );
        let source = shade(fragment, [1., 0.5, 0.25, 0.5], [0.5, 1., 1., 0.5]);
        assert_eq!(source, [0.125, 0.125, 0.0625, 0.25]);
        assert_eq!(
            composite(BlendMode::Opaque, fragment, source, [1.; 4]),
            source
        );
        let target =
            FragmentKind::for_source(&TextureSource::Target { depth: false }, BlendMode::Opaque);
        assert_eq!(shade(target, source, [1.; 4]), source);
    }

    #[test]
    fn presentation_is_opaque_and_keeps_emission() {
        assert_eq!(
            shade(FragmentKind::Present, [0.5, 0.25, 0., 0.], [1.; 4]),
            [0.5, 0.25, 0., 1.]
        );
    }

    #[test]
    fn camera_depth_and_transparency_are_explicit() {
        for blend in [BlendMode::Opaque, BlendMode::Alpha, BlendMode::Additive] {
            assert!(depth_state(false, blend).is_none());
            let state = depth_state(true, blend).unwrap();
            assert_eq!(state.depth_compare, Some(wgpu::CompareFunction::LessEqual));
            assert_eq!(
                state.depth_write_enabled,
                Some(blend != BlendMode::Additive)
            );
        }
    }
}
