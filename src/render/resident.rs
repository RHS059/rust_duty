//! GPU-resident authored meshes, with explicit portable wire layouts.
use crate::draw::resident::{ResidentDraw, ResidentMesh, SkinPalette, Vertices, MAX_BONES};
use glam::Mat4;

const RIGID_STRIDE: usize = 32;
const SKIN_STRIDE: usize = 80;
const DRAW_BYTES: usize = 240;
const MATRIX_BYTES: usize = 64;
const NORMAL_PALETTE_OFFSET: usize = MAX_BONES * MATRIX_BYTES;
const PALETTE_BYTES: usize = NORMAL_PALETTE_OFFSET * 2;

fn floats(output: &mut Vec<u8>, values: impl IntoIterator<Item = f32>) {
    for value in values {
        output.extend_from_slice(&value.to_le_bytes());
    }
}

pub(super) fn vertices(mesh: &ResidentMesh) -> Vec<u8> {
    let mut output = Vec::with_capacity(
        mesh.vertex_count()
            * match mesh.vertices() {
                Vertices::Rigid(_) => RIGID_STRIDE,
                Vertices::Skin { .. } => SKIN_STRIDE,
            },
    );
    match mesh.vertices() {
        Vertices::Rigid(vertices) => {
            for vertex in vertices {
                floats(&mut output, vertex.position);
                floats(&mut output, vertex.uv);
                floats(&mut output, vertex.normal);
            }
        }
        Vertices::Skin { vertices, .. } => {
            for vertex in vertices {
                floats(&mut output, vertex.vertex.position);
                floats(&mut output, vertex.vertex.uv);
                floats(&mut output, vertex.vertex.normal);
                for joint in vertex.joints {
                    output.extend_from_slice(&joint.to_le_bytes());
                }
                floats(&mut output, vertex.weights);
            }
        }
    }
    output
}

fn indices(mesh: &ResidentMesh) -> Vec<u8> {
    let mut output = Vec::with_capacity((mesh.indices().len() * 2 + 3) & !3);
    for index in mesh.indices() {
        output.extend_from_slice(&index.to_le_bytes());
    }
    while !output.len().is_multiple_of(4) {
        output.push(0);
    }
    output
}

pub(super) fn palette_bytes(palette: Option<&SkinPalette>) -> Vec<u8> {
    // Fixed WGSL arrays: a 72-bone skeleton still starts normals at byte8192.
    let mut output = Vec::with_capacity(PALETTE_BYTES);
    for normal in [false, true] {
        for index in 0..MAX_BONES {
            let matrix = palette
                .and_then(|p| {
                    if normal {
                        p.normals().get(index)
                    } else {
                        p.positions().get(index)
                    }
                })
                .copied()
                .unwrap_or(Mat4::IDENTITY);
            floats(&mut output, matrix.to_cols_array());
        }
    }
    output
}

pub(super) fn draw_bytes(draw: &ResidentDraw, view_projection: Mat4) -> Result<Vec<u8>, String> {
    if !view_projection.is_finite() || !(view_projection * draw.root()).is_finite() {
        return Err("nonfinite resident view-projection".into());
    }
    let mut output = Vec::with_capacity(DRAW_BYTES);
    let vertex_transform = if matches!(draw.mesh().vertices(), Vertices::Rigid(_)) {
        view_projection * draw.root()
    } else {
        view_projection
    };
    for matrix in [vertex_transform, draw.root(), draw.normal_transform()] {
        floats(&mut output, matrix.to_cols_array());
    }
    let light = draw.lighting();
    let albedo = draw.albedo();
    floats(
        &mut output,
        [
            light.direction_to_light.x,
            light.direction_to_light.y,
            light.direction_to_light.z,
            light.ambient,
        ],
    );
    floats(&mut output, [albedo.r, albedo.g, albedo.b, light.diffuse]);
    floats(
        &mut output,
        [(draw.alpha() * 255.).round() / 255., 0., 0., 0.],
    );
    Ok(output)
}

fn append_aligned(
    output: &mut Vec<u8>,
    bytes: &[u8],
    alignment: u32,
    maximum: u64,
) -> Result<u32, String> {
    if alignment == 0 || !alignment.is_power_of_two() {
        return Err("invalid resident uniform alignment".into());
    }
    let alignment = alignment as usize;
    let offset = output
        .len()
        .checked_add(alignment - 1)
        .map(|n| n & !(alignment - 1))
        .ok_or("resident uniform offset overflow")?;
    let end = offset
        .checked_add(bytes.len())
        .ok_or("resident uniform length overflow")?;
    if end as u64 > maximum {
        return Err("resident uniform buffer limit exceeded".into());
    }
    let offset32 = u32::try_from(offset).map_err(|_| "resident dynamic offset exceeds u32")?;
    output
        .try_reserve(end - output.len())
        .map_err(|_| "resident uniform allocation failed")?;
    output.resize(offset, 0);
    output.extend_from_slice(bytes);
    Ok(offset32)
}

use crate::draw::{BlendMode, ResourceId};
use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};
use wgpu::util::DeviceExt;
const CACHE_BYTES: u64 = 256 * 1024 * 1024;
const CACHE_ENTRIES: usize = 512;
const RIGID_ATTRIBUTES: [wgpu::VertexAttribute; 3] =
    wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Float32x3];
const SKIN_ATTRIBUTES: [wgpu::VertexAttribute; 7] = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x2,2=>Float32x3,3=>Uint16x4,4=>Uint16x4,5=>Float32x4,6=>Float32x4];

use crate::draw::ResidentFrameStats as Counts;
struct Geometry {
    vertices: wgpu::Buffer,
    indices: wgpu::Buffer,
    bytes: u64,
}
struct DrawBinding {
    geometry: Arc<Geometry>,
    draw_offset: u32,
    palette_offset: u32,
    count: u32,
    skin: bool,
}
pub(crate) struct Frame {
    // Bind groups own the immutable per-submission buffers. Nothing is rewritten
    // by later frames, even while these bindings are still referenced by the GPU.
    draws: wgpu::BindGroup,
    palettes: wgpu::BindGroup,
    bindings: Vec<DrawBinding>,
    pub counts: Counts,
}
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct Key {
    depth: bool,
    blend: u8,
    skin: bool,
}
pub(crate) struct ResidentRenderer {
    draw_layout: wgpu::BindGroupLayout,
    palette_layout: wgpu::BindGroupLayout,
    layout: wgpu::PipelineLayout,
    shader: wgpu::ShaderModule,
    pipelines: HashMap<Key, wgpu::RenderPipeline>,
    meshes: HashMap<ResourceId, Arc<Geometry>>,
    cache_bytes: u64,
    cache_entries: usize,
}
impl ResidentRenderer {
    pub fn new(device: &wgpu::Device, texture_layout: &wgpu::BindGroupLayout) -> Self {
        let uniform_layout = |label, size| {
            device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
                label: Some(label),
                entries: &[wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::VERTEX,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: true,
                        min_binding_size: wgpu::BufferSize::new(size),
                    },
                    count: None,
                }],
            })
        };
        let draw_layout = uniform_layout("resident draw snapshot", DRAW_BYTES as u64);
        let palette_layout = uniform_layout("resident palette snapshot", PALETTE_BYTES as u64);
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("resident mesh layout"),
            bind_group_layouts: &[
                Some(&draw_layout),
                Some(texture_layout),
                Some(&palette_layout),
            ],
            immediate_size: 0,
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("resident skin and rigid lighting"),
            source: wgpu::ShaderSource::Wgsl(include_str!("resident.wgsl").into()),
        });
        Self {
            draw_layout,
            palette_layout,
            layout,
            shader,
            pipelines: HashMap::new(),
            meshes: HashMap::new(),
            cache_bytes: CACHE_BYTES,
            cache_entries: CACHE_ENTRIES,
        }
    }
    #[cfg(test)]
    pub(super) fn disable_retention_for_test(&mut self) {
        self.clear();
        self.cache_bytes = 0;
        self.cache_entries = 0;
    }
    pub fn clear(&mut self) {
        self.meshes.clear();
    }
    pub fn prepare(
        &mut self,
        device: &wgpu::Device,
        draws: &[(ResidentDraw, Mat4)],
    ) -> Result<Option<Frame>, String> {
        let live: HashSet<_> = draws.iter().map(|(d, _)| d.mesh().id()).collect();
        if draws.is_empty() {
            return Ok(None);
        }
        let limits = device.limits();
        if limits.max_uniform_buffer_binding_size < PALETTE_BYTES as u64 {
            return Err("resident palette exceeds uniform binding limit".into());
        }
        let mut retained_bytes: u64 = self.meshes.values().map(|g| g.bytes).sum();
        let mut frame_meshes = HashMap::new();
        let mut draw_data = Vec::new();
        let mut palette_data = Vec::new();
        let mut palette_offsets = HashMap::new();
        let mut bindings = Vec::with_capacity(draws.len());
        let mut counts = Counts::default();
        for (draw, projection) in draws {
            let mesh = draw.mesh();
            let geometry = if let Some(found) = self
                .meshes
                .get(&mesh.id())
                .or_else(|| frame_meshes.get(&mesh.id()))
            {
                counts.cache_hits += 1;
                found.clone()
            } else {
                let vertex_bytes = vertices(mesh);
                let index_bytes = indices(mesh);
                if vertex_bytes.is_empty()
                    || index_bytes.is_empty()
                    || vertex_bytes.len() as u64 > limits.max_buffer_size
                    || index_bytes.len() as u64 > limits.max_buffer_size
                {
                    return Err("resident mesh exceeds GPU buffer bounds".into());
                }
                counts.cache_misses += 1;
                counts.buffer_allocations += 2;
                counts.vertex_bytes_uploaded += vertex_bytes.len() as u64;
                counts.index_bytes_uploaded += index_bytes.len() as u64;
                let geometry = Arc::new(Geometry {
                    vertices: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                        label: Some("immutable resident vertices"),
                        contents: &vertex_bytes,
                        usage: wgpu::BufferUsages::VERTEX,
                    }),
                    indices: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                        label: Some("immutable resident indices"),
                        contents: &index_bytes,
                        usage: wgpu::BufferUsages::INDEX,
                    }),
                    bytes: (vertex_bytes.len() + index_bytes.len()) as u64,
                });
                if self.meshes.len() >= self.cache_entries
                    || retained_bytes + geometry.bytes > self.cache_bytes
                {
                    self.meshes.retain(|id, _| live.contains(id));
                    retained_bytes = self.meshes.values().map(|g| g.bytes).sum();
                }
                if self.meshes.len() < self.cache_entries
                    && retained_bytes + geometry.bytes <= self.cache_bytes
                {
                    retained_bytes += geometry.bytes;
                    self.meshes.insert(mesh.id(), geometry.clone());
                } else {
                    counts.transient_meshes += 1;
                    frame_meshes.insert(mesh.id(), geometry.clone());
                }
                geometry
            };
            let draw_offset = append_aligned(
                &mut draw_data,
                &draw_bytes(draw, *projection)?,
                limits.min_uniform_buffer_offset_alignment,
                limits.max_buffer_size,
            )?;
            let palette_id = draw.palette().map(SkinPalette::id);
            let palette_offset = if let Some(offset) = palette_offsets.get(&palette_id) {
                *offset
            } else {
                let offset = append_aligned(
                    &mut palette_data,
                    &palette_bytes(draw.palette()),
                    limits.min_uniform_buffer_offset_alignment,
                    limits.max_buffer_size,
                )?;
                palette_offsets.insert(palette_id, offset);
                offset
            };
            bindings.push(DrawBinding {
                geometry,
                draw_offset,
                palette_offset,
                count: mesh.indices().len() as u32,
                skin: matches!(mesh.vertices(), Vertices::Skin { .. }),
            });
            counts.draws += 1;
            if matches!(mesh.vertices(), Vertices::Skin { .. }) {
                counts.skinned_draws += 1;
            } else {
                counts.rigid_draws += 1;
            }
        }
        counts.buffer_allocations += 2;
        counts.binding_allocations = 2;
        counts.uniform_bytes_uploaded = (draw_data.len() + palette_data.len()) as u64;
        let binding = |label, bytes: &[u8], layout: &wgpu::BindGroupLayout, size| {
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
                    resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                        buffer: &buffer,
                        offset: 0,
                        size: wgpu::BufferSize::new(size),
                    }),
                }],
            })
        };
        Ok(Some(Frame {
            draws: binding(
                "resident draw snapshots",
                &draw_data,
                &self.draw_layout,
                DRAW_BYTES as u64,
            ),
            palettes: binding(
                "resident pose snapshots",
                &palette_data,
                &self.palette_layout,
                PALETTE_BYTES as u64,
            ),
            bindings,
            counts,
        }))
    }
    pub fn issue(
        &mut self,
        device: &wgpu::Device,
        pass: &mut wgpu::RenderPass<'_>,
        frame: &Frame,
        index: usize,
        state: (bool, BlendMode),
        texture: &wgpu::BindGroup,
    ) {
        let draw = &frame.bindings[index];
        let (depth, blend) = state;
        let key = Key {
            depth,
            blend: match blend {
                BlendMode::Opaque => 0,
                BlendMode::Alpha => 1,
                BlendMode::Additive => 2,
            },
            skin: draw.skin,
        };
        let pipeline = self.pipelines.entry(key).or_insert_with(|| {
            crate::frame_performance_session::add_encode_counter(
                crate::frame_encode_detail::EncodeCounter::PipelineCacheMisses,
                1,
            );
            let fragment = if blend == BlendMode::Opaque {
                super::mesh::FragmentKind::AssociateStraight
            } else {
                super::mesh::FragmentKind::Straight
            };
            device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some("resident authored mesh"),
                layout: Some(&self.layout),
                vertex: wgpu::VertexState {
                    module: &self.shader,
                    entry_point: Some(if draw.skin { "vs_skin" } else { "vs_rigid" }),
                    compilation_options: Default::default(),
                    buffers: &[Some(wgpu::VertexBufferLayout {
                        array_stride: if draw.skin { SKIN_STRIDE } else { RIGID_STRIDE } as u64,
                        step_mode: wgpu::VertexStepMode::Vertex,
                        attributes: if draw.skin {
                            &SKIN_ATTRIBUTES
                        } else {
                            &RIGID_ATTRIBUTES
                        },
                    })],
                },
                primitive: wgpu::PrimitiveState {
                    topology: wgpu::PrimitiveTopology::TriangleList,
                    front_face: wgpu::FrontFace::Ccw,
                    cull_mode: None,
                    ..Default::default()
                },
                depth_stencil: super::mesh::depth_state(depth, blend),
                multisample: Default::default(),
                fragment: Some(wgpu::FragmentState {
                    module: &self.shader,
                    entry_point: Some(if blend == BlendMode::Opaque {
                        "fs_associate_straight"
                    } else {
                        "fs_straight"
                    }),
                    compilation_options: Default::default(),
                    targets: &[Some(wgpu::ColorTargetState {
                        format: super::target::COLOR_FORMAT,
                        blend: super::mesh::blend_state(blend, fragment),
                        write_mask: wgpu::ColorWrites::ALL,
                    })],
                }),
                multiview_mask: None,
                cache: None,
            })
        });
        pass.set_pipeline(pipeline);
        pass.set_bind_group(0, &frame.draws, &[draw.draw_offset]);
        pass.set_bind_group(1, texture, &[]);
        pass.set_bind_group(2, &frame.palettes, &[draw.palette_offset]);
        pass.set_vertex_buffer(0, draw.geometry.vertices.slice(..));
        pass.set_index_buffer(draw.geometry.indices.slice(..), wgpu::IndexFormat::Uint16);
        crate::frame_performance_session::add_encode_counter(
            crate::frame_encode_detail::EncodeCounter::DrawCalls,
            1,
        );
        pass.draw_indexed(0..draw.count, 0, 0..1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        draw::{
            resident::{RigidVertex, SkinVertex},
            Color,
        },
        scene_lighting::SceneLighting,
    };
    fn rigid() -> RigidVertex {
        RigidVertex {
            position: [1., -0., 3.],
            uv: [0.25, 0.75],
            normal: [0., 1., 0.],
        }
    }
    fn word(bytes: &[u8], offset: usize) -> f32 {
        f32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
    }
    #[test]
    fn integer_unorm_conversion_matches_all_correctly_rounded_byte_values() {
        for byte in 0u32..=255 {
            let bits = if byte == 0 {
                0
            } else if byte == 255 {
                1.0f32.to_bits()
            } else {
                let exponent = 31 - byte.leading_zeros();
                let numerator = (u64::from(byte) << (31 - exponent)) + 127;
                assert!(numerator <= u64::from(u32::MAX));
                let significand = numerator as u32 / 255;
                ((exponent + 119) << 23) + (significand - 8388608)
            };
            // Independent double-precision rational oracle. Exhaust all input
            // bytes, including those whose reciprocal product rounds upward.
            let expected = (f64::from(byte) / 255.0) as f32;
            assert_eq!(bits, expected.to_bits(), "byte {byte}");
        }
        assert_ne!(
            (99.0f32 * (1.0f32 / 255.0)).to_bits(),
            (99.0f32 / 255.0).to_bits()
        );
    }
    #[test]
    fn shader_unorm_helper_uses_integer_division_and_bitcast() {
        use wgpu::naga::{Expression, MathFunction, ScalarKind, TypeInner};
        let module = wgpu::naga::front::wgsl::parse_str(include_str!("resident.wgsl")).unwrap();
        let (_, function) = module
            .functions
            .iter()
            .find(|(_, f)| f.name.as_deref() == Some("unorm8_exact"))
            .unwrap();
        assert!(matches!(
            module.types[function.arguments[0].ty].inner,
            TypeInner::Scalar(wgpu::naga::Scalar {
                kind: ScalarKind::Uint,
                width: 4
            })
        ));
        assert!(function.expressions.iter().any(|(_, e)| matches!(
            e,
            Expression::Math {
                fun: MathFunction::CountLeadingZeros,
                ..
            }
        )));
        assert!(function.expressions.iter().any(|(_, e)| matches!(
            e,
            Expression::As {
                kind: ScalarKind::Float,
                convert: None,
                ..
            }
        )));
        let (_, color) = module
            .functions
            .iter()
            .find(|(_, f)| f.name.as_deref() == Some("color_byte"))
            .unwrap();
        assert!(!color.expressions.iter().any(|(_, e)| matches!(
            e,
            Expression::Binary {
                op: wgpu::naga::BinaryOperator::Divide,
                ..
            }
        )));
    }
    #[test]
    fn normalization_uses_cpu_sqrt_then_reciprocal_and_keeps_byte_fences() {
        use wgpu::naga::{BinaryOperator, Expression, MathFunction};
        let module = wgpu::naga::front::wgsl::parse_str(include_str!("resident.wgsl")).unwrap();
        let (_, function) = module
            .functions
            .iter()
            .find(|(_, f)| f.name.as_deref() == Some("normal_or_y"))
            .unwrap();
        assert_eq!(
            function
                .expressions
                .iter()
                .filter(|(_, e)| matches!(
                    e,
                    Expression::Math {
                        fun: MathFunction::Sqrt,
                        ..
                    }
                ))
                .count(),
            1
        );
        assert!(!function.expressions.iter().any(|(_, e)| matches!(
            e,
            Expression::Math {
                fun: MathFunction::InverseSqrt,
                ..
            }
        )));
        assert!(function.expressions.iter().any(|(_, e)| matches!(
            e,
            Expression::Binary {
                op: BinaryOperator::Divide,
                ..
            }
        )));
        // Independently generated float32 boundary inputs. These expectations
        // are the existing CPU oracle, not an assertion about GPU execution.
        for (bits, byte) in [
            ([3213363676, 1066472058, 1057255481], 241),
            ([1071908497, 1070192988, 1069430069], 177),
            ([1071008643, 1050453308, 1069358016], 125),
            ([1061214333, 1053540367, 1072746884], 173),
        ] {
            let normal = glam::Vec3::from_array(bits.map(f32::from_bits));
            let color: [u8; 4] = SceneLighting::range()
                .shade(Color::WHITE, normal.try_normalize().unwrap())
                .into();
            assert_eq!(color, [byte, byte, byte, 255]);
        }
    }
    #[test]
    fn shader_validates_and_uniform_layouts_match_the_explicit_bytes() {
        let module = wgpu::naga::front::wgsl::parse_str(include_str!("resident.wgsl")).unwrap();
        wgpu::naga::valid::Validator::new(
            wgpu::naga::valid::ValidationFlags::all(),
            wgpu::naga::valid::Capabilities::all(),
        )
        .validate(&module)
        .unwrap();
        for (_, ty) in module.types.iter() {
            if let wgpu::naga::TypeInner::Struct { members, span } = &ty.inner {
                match ty.name.as_deref() {
                    Some("DrawState") => assert_eq!(*span, DRAW_BYTES as u32),
                    Some("Palette") => {
                        assert_eq!(*span, PALETTE_BYTES as u32);
                        assert_eq!(members[1].offset, NORMAL_PALETTE_OFFSET as u32);
                    }
                    _ => {}
                }
            }
        }
    }
    #[test]
    fn explicit_vertex_fields_and_odd_indices_have_no_host_padding() {
        let mesh =
            ResidentMesh::new(Vertices::Rigid(vec![rigid(); 3]), vec![0, 1, 2], None).unwrap();
        let bytes = vertices(&mesh);
        assert_eq!(bytes.len(), 3 * RIGID_STRIDE);
        assert_eq!(word(&bytes, 4).to_bits(), (-0.0f32).to_bits());
        assert_eq!(word(&bytes, 12), 0.25);
        assert_eq!(word(&bytes, 24), 1.);
        assert_eq!(indices(&mesh), [0, 0, 1, 0, 2, 0, 0, 0]);
        let skin = SkinVertex {
            vertex: rigid(),
            joints: [0, 1, 2, 3, 4, 5, 6, 7],
            weights: [0., 0., 0., 0., 0.1, 0.2, 0.3, 0.4],
        };
        let mesh = ResidentMesh::new(
            Vertices::Skin {
                vertices: vec![skin; 3],
                bones: 8,
            },
            vec![0, 1, 2],
            None,
        )
        .unwrap();
        let bytes = vertices(&mesh);
        assert_eq!(bytes.len(), 3 * SKIN_STRIDE);
        assert_eq!(
            &bytes[32..48],
            &[0, 0, 1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0, 7, 0]
        );
        assert_eq!(word(&bytes, 64), 0.1);
        assert_eq!(word(&bytes, 76), 0.4);
    }
    #[test]
    fn short_and_full_palettes_keep_fixed_normal_array_offset() {
        for count in [1, 72, 128] {
            let matrices: Vec<_> = (0..count)
                .map(|i| Mat4::from_scale(glam::Vec3::new(i as f32 + 2., 3., 4.)))
                .collect();
            let palette = SkinPalette::new(matrices).unwrap();
            let bytes = palette_bytes(Some(&palette));
            assert_eq!(bytes.len(), 16_384);
            for index in [0, count - 1] {
                assert_eq!(word(&bytes, index * 64), index as f32 + 2.);
                assert_eq!(
                    word(&bytes, 8192 + index * 64),
                    palette.normals()[index].x_axis.x
                );
            }
            if count < 128 {
                assert_eq!(word(&bytes, 127 * 64), 1.);
                assert_eq!(word(&bytes, 8192 + 127 * 64), 1.);
            }
        }
    }
    #[test]
    fn draw_snapshots_use_distinct_aligned_ranges_and_fail_atomically() {
        let mesh =
            ResidentMesh::new(Vertices::Rigid(vec![rigid(); 3]), vec![0, 1, 2], None).unwrap();
        let draw = ResidentDraw::new(
            mesh,
            Mat4::IDENTITY,
            SceneLighting::range(),
            Color::WHITE,
            0.5,
            None,
        )
        .unwrap();
        let bytes = draw_bytes(&draw, Mat4::IDENTITY).unwrap();
        assert_eq!(bytes.len(), 240);
        assert_eq!(word(&bytes, 224), 128. / 255.);
        let mut packed = vec![];
        assert_eq!(append_aligned(&mut packed, &bytes, 256, 496).unwrap(), 0);
        assert_eq!(append_aligned(&mut packed, &bytes, 256, 496).unwrap(), 256);
        assert!(packed[240..256].iter().all(|&x| x == 0));
        let before = packed.clone();
        assert!(append_aligned(&mut packed, &bytes, 256, 496).is_err());
        assert_eq!(packed, before);
        assert!(append_aligned(&mut packed, &bytes, 3, 8192).is_err());
        assert_eq!(packed, before);
    }
}
