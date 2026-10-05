//! Trivial CPU-lit mesh pipeline. Never upload the padded public glam vertex directly.
use crate::draw::{BlendMode, Vertex};
use glam::{Mat4, Vec4};
use std::collections::HashMap;
use wgpu::util::DeviceExt;

#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct GpuVertex {
    pub position: [f32; 3],
    pub uv: [f32; 2],
    pub color: [u8; 4],
    pub normal: [f32; 4],
}
impl From<Vertex> for GpuVertex {
    fn from(v: Vertex) -> Self {
        Self {
            position: v.position.to_array(),
            uv: v.uv.to_array(),
            color: v.color,
            normal: v.normal.to_array(),
        }
    }
}
impl GpuVertex {
    pub const STRIDE: u64 = 40;
    pub const ATTRIBUTES: [wgpu::VertexAttribute; 4] =
        wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Unorm8x4,3=>Float32x4];
    pub fn append_bytes(self, bytes: &mut Vec<u8>) {
        for v in self.position.into_iter().chain(self.uv) {
            bytes.extend(v.to_le_bytes());
        }
        bytes.extend(self.color);
        for v in self.normal {
            bytes.extend(v.to_le_bytes());
        }
    }
}
/// The only OpenGL (-1..1) to WebGPU (0..1) depth conversion in this backend.
pub(crate) fn clip_matrix(view_projection: Mat4, model: Mat4) -> Mat4 {
    let remap = Mat4::from_cols(
        Vec4::X,
        Vec4::Y,
        Vec4::new(0., 0., 0.5, 0.),
        Vec4::new(0., 0., 0.5, 1.),
    );
    remap * view_projection * model
}
fn blend_state(mode: BlendMode) -> Option<wgpu::BlendState> {
    match mode {
        BlendMode::Opaque => None,
        BlendMode::Alpha => Some(wgpu::BlendState::ALPHA_BLENDING),
        BlendMode::Additive => Some(wgpu::BlendState {
            color: wgpu::BlendComponent {
                src_factor: wgpu::BlendFactor::SrcAlpha,
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
}
pub(crate) struct Pipelines {
    pub texture_layout: wgpu::BindGroupLayout,
    transform_layout: wgpu::BindGroupLayout,
    layout: wgpu::PipelineLayout,
    shader: wgpu::ShaderModule,
    pipelines: HashMap<PipelineKey, wgpu::RenderPipeline>,
}
pub(crate) struct Geometry {
    pub vertices: wgpu::Buffer,
    pub indices: wgpu::Buffer,
    pub transform: wgpu::BindGroup,
    pub count: u32,
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
                    has_dynamic_offset: false,
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
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("CPU-lit mesh shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("mesh.wgsl").into()),
        });
        Self {
            texture_layout,
            transform_layout,
            layout,
            shader,
            pipelines: HashMap::new(),
        }
    }
    pub fn pipeline(
        &mut self,
        device: &wgpu::Device,
        format: wgpu::TextureFormat,
        depth: bool,
        lines: bool,
        blend: BlendMode,
    ) -> wgpu::RenderPipeline {
        let key = PipelineKey {
            format,
            depth,
            lines,
            blend: match blend {
                BlendMode::Opaque => 0,
                BlendMode::Alpha => 1,
                BlendMode::Additive => 2,
            },
        };
        self.pipelines
            .entry(key)
            .or_insert_with(|| {
                device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label: Some("CPU-lit mesh pipeline"),
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
                        entry_point: Some("fs_main"),
                        compilation_options: Default::default(),
                        targets: &[Some(wgpu::ColorTargetState {
                            format,
                            blend: blend_state(blend),
                            write_mask: wgpu::ColorWrites::ALL,
                        })],
                    }),
                    multiview_mask: None,
                    cache: None,
                })
            })
            .clone()
    }
    pub fn geometry(
        &self,
        device: &wgpu::Device,
        vertices: &[Vertex],
        indices: &[u16],
        transform: Mat4,
    ) -> Geometry {
        let mut bytes = Vec::with_capacity(vertices.len() * GpuVertex::STRIDE as usize);
        for vertex in vertices {
            GpuVertex::from(*vertex).append_bytes(&mut bytes);
        }
        let vertices = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("dynamic CPU vertices"),
            contents: &bytes,
            usage: wgpu::BufferUsages::VERTEX,
        });
        let indices_bytes: Vec<u8> = indices
            .iter()
            .flat_map(|index| index.to_le_bytes())
            .collect();
        let indices_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("dynamic mesh indices"),
            contents: &indices_bytes,
            usage: wgpu::BufferUsages::INDEX,
        });
        let matrix_bytes: Vec<u8> = transform
            .to_cols_array()
            .into_iter()
            .flat_map(f32::to_le_bytes)
            .collect();
        let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("draw transform"),
            contents: &matrix_bytes,
            usage: wgpu::BufferUsages::UNIFORM,
        });
        let transform = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("draw transform"),
            layout: &self.transform_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform.as_entire_binding(),
            }],
        });
        Geometry {
            vertices,
            indices: indices_buffer,
            transform,
            count: indices.len() as u32,
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use glam::{Vec2, Vec3};
    use std::mem::{offset_of, size_of};
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
        let state = blend_state(BlendMode::Additive).unwrap();
        assert_eq!(state.color.src_factor, wgpu::BlendFactor::SrcAlpha);
        assert_eq!(state.alpha.src_factor, wgpu::BlendFactor::Zero);
        assert_eq!(state.alpha.dst_factor, wgpu::BlendFactor::One);
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
