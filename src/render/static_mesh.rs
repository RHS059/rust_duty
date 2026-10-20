//! Append-only static atlas pages. Each immutable mesh owns a disjoint range;
//! visibility selects ranges without copying or rewriting geometry each frame.
use super::arena::GpuVertex;
use crate::draw::{ResourceId, StaticMesh, StaticMeshData};
use std::{
    collections::HashMap,
    ops::Range,
    sync::{Arc, Weak},
};

pub(super) struct AtlasPage {
    pub vertices: wgpu::Buffer,
    pub indices: wgpu::Buffer,
}
pub(super) struct StaticGeometry {
    pub page: Arc<AtlasPage>,
    pub index_range: Range<u32>,
    pub base_vertex: u32,
    pub vertex_bytes: u64,
    pub index_bytes: u64,
    /// Exact byte payloads written into this atlas range, retained for receipts.
    pub receipt_bytes: Option<(Vec<u8>, Vec<u8>)>,
}
struct CachedMesh {
    owner: Weak<StaticMeshData>,
    geometry: Arc<StaticGeometry>,
}
#[derive(Default, Clone, Debug, PartialEq, Eq)]
struct AtlasOffsets {
    vertices: u64,
    indices: u64,
}
impl AtlasOffsets {
    fn reserve(
        &mut self,
        vertices: u64,
        indices: u64,
        vertex_limit: u64,
        index_limit: u64,
    ) -> Option<(Range<u64>, Range<u64>)> {
        let vertex_end = self.vertices.checked_add(vertices)?;
        let index_end = self.indices.checked_add(indices)?;
        if vertex_end > vertex_limit
            || index_end > index_limit
            || vertex_end / GpuVertex::STRIDE > u64::from(u32::MAX)
            || index_end / 4 > u64::from(u32::MAX)
        {
            return None;
        }
        let ranges = (self.vertices..vertex_end, self.indices..index_end);
        self.vertices = vertex_end;
        self.indices = index_end;
        Some(ranges)
    }
}
struct OpenPage {
    page: Weak<AtlasPage>,
    offsets: AtlasOffsets,
}
#[derive(Default)]
pub(super) struct StaticMeshCache {
    meshes: HashMap<ResourceId, CachedMesh>,
    open: Option<OpenPage>,
    #[cfg(test)]
    page_limits: Option<(u64, u64)>,
}
impl StaticMeshCache {
    pub fn retire_unused(&mut self) {
        self.meshes.retain(|_, mesh| mesh.owner.strong_count() != 0);
        if self
            .open
            .as_ref()
            .is_some_and(|open| open.page.strong_count() == 0)
        {
            self.open = None;
        }
    }
    /// Pages are shared but occupied bytes are never rewritten. WGPU keeps
    /// in-flight buffers alive after the final mesh/page owner has disappeared.
    pub fn resolve(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        mesh: &StaticMesh,
        receipt: bool,
    ) -> Result<(Arc<StaticGeometry>, bool), String> {
        if let Some(cached) = self.meshes.get(&mesh.id()) {
            if !receipt || cached.geometry.receipt_bytes.is_some() {
                return Ok((cached.geometry.clone(), false));
            }
        }
        let limit = device.limits().max_buffer_size;
        let (vertex_bytes, index_bytes) = sizes(mesh, limit)?;
        let existing = self.open.as_mut().and_then(|open| {
            let page = open.page.upgrade()?;
            let ranges = open.offsets.reserve(
                vertex_bytes,
                index_bytes,
                page.vertices.size(),
                page.indices.size(),
            )?;
            Some((page, ranges))
        });
        let (page, (vertices_range, indices_range)) = match existing {
            Some(allocation) => allocation,
            None => {
                let page_limits = (8 * 1024 * 1024_u64, 2 * 1024 * 1024_u64);
                #[cfg(test)]
                let page_limits = self.page_limits.unwrap_or(page_limits);
                let vertex_capacity = (page_limits.0.min(limit) / GpuVertex::STRIDE
                    * GpuVertex::STRIDE)
                    .max(vertex_bytes);
                let index_capacity = (page_limits.1.min(limit) / 4 * 4).max(index_bytes);
                let page = Arc::new(AtlasPage {
                    vertices: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("persistent static atlas vertices"),
                        size: vertex_capacity,
                        usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                        mapped_at_creation: false,
                    }),
                    indices: device.create_buffer(&wgpu::BufferDescriptor {
                        label: Some("persistent static atlas u32 indices"),
                        size: index_capacity,
                        usage: wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST,
                        mapped_at_creation: false,
                    }),
                });
                let mut offsets = AtlasOffsets::default();
                let ranges = offsets
                    .reserve(vertex_bytes, index_bytes, vertex_capacity, index_capacity)
                    .ok_or("static atlas range exceeds u32 addressing")?;
                self.open = Some(OpenPage {
                    page: Arc::downgrade(&page),
                    offsets,
                });
                (page, ranges)
            }
        };
        let base_vertex = u32::try_from(vertices_range.start / GpuVertex::STRIDE)
            .map_err(|_| "static atlas base vertex exceeds u32")?;
        let (vertices, indices) = pack_at(mesh, limit, base_vertex)?;
        queue.write_buffer(&page.vertices, vertices_range.start, &vertices);
        queue.write_buffer(&page.indices, indices_range.start, &indices);
        let geometry = Arc::new(StaticGeometry {
            page,
            index_range: (indices_range.start / 4) as u32..(indices_range.end / 4) as u32,
            base_vertex,
            vertex_bytes,
            index_bytes,
            receipt_bytes: receipt.then_some((vertices, indices)),
        });
        self.meshes.insert(
            mesh.id(),
            CachedMesh {
                owner: mesh.downgrade(),
                geometry: geometry.clone(),
            },
        );
        Ok((geometry, true))
    }
}
fn sizes(mesh: &StaticMesh, max_buffer_size: u64) -> Result<(u64, u64), String> {
    let vertices = (mesh.vertices().len() as u64)
        .checked_mul(GpuVertex::STRIDE)
        .ok_or("static vertex buffer size overflow")?;
    let indices = (mesh.indices().len() as u64)
        .checked_mul(4)
        .ok_or("static index buffer size overflow")?;
    if vertices == 0 || indices == 0 || vertices > max_buffer_size || indices > max_buffer_size {
        return Err("static mesh is empty or exceeds adapter buffer limit".into());
    }
    Ok((vertices, indices))
}
fn pack_at(
    mesh: &StaticMesh,
    max_buffer_size: u64,
    base_vertex: u32,
) -> Result<(Vec<u8>, Vec<u8>), String> {
    let (vertex_bytes, index_bytes) = sizes(mesh, max_buffer_size)?;
    let mut vertices = Vec::new();
    vertices
        .try_reserve_exact(
            usize::try_from(vertex_bytes).map_err(|_| "static vertices exceed address space")?,
        )
        .map_err(|_| "cannot reserve static vertices")?;
    for vertex in mesh.vertices() {
        GpuVertex::from(*vertex).append_bytes(&mut vertices);
    }
    let mut indices = Vec::new();
    indices
        .try_reserve_exact(
            usize::try_from(index_bytes).map_err(|_| "static indices exceed address space")?,
        )
        .map_err(|_| "cannot reserve static indices")?;
    for index in mesh.indices() {
        indices.extend(
            index
                .checked_add(base_vertex)
                .ok_or("static atlas index exceeds u32")?
                .to_le_bytes(),
        );
    }
    Ok((vertices, indices))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::{BlendMode, Color, DrawList, Renderer, Vertex};
    use glam::{Mat4, Vec2, Vec3};
    fn fixture() -> StaticMesh {
        let mut vertices = vec![Vertex::new2(Vec3::ZERO, Vec2::ZERO, Color::WHITE); 65_539];
        for (i, position) in [
            Vec3::new(4., 4., 0.),
            Vec3::new(28., 4., 0.),
            Vec3::new(4., 28., 0.),
        ]
        .into_iter()
        .enumerate()
        {
            vertices[65_536 + i].position = position;
        }
        StaticMesh::new(vertices, vec![65_536, 65_537, 65_538], None).unwrap()
    }
    #[test]
    fn static_pack_preserves_high_indices_and_receipt_triangle() {
        let mesh = fixture();
        let (vertices, indices) = pack_at(&mesh, 4 * 1024 * 1024, 0).unwrap();
        assert_eq!(vertices.len(), mesh.vertices().len() * 40);
        assert_eq!(
            indices,
            [65_536_u32, 65_537, 65_538]
                .into_iter()
                .flat_map(u32::to_le_bytes)
                .collect::<Vec<_>>()
        );
        let hashes =
            crate::draw::visibility_receipt::packed_triangle_hashes_u32(&vertices, &indices, 40)
                .unwrap();
        assert_eq!(
            hashes,
            vec![crate::draw::visibility_receipt::triangle_sha256(&[
                mesh.vertices()[65_536],
                mesh.vertices()[65_537],
                mesh.vertices()[65_538]
            ])]
        );
        assert!(crate::draw::visibility_receipt::packed_triangle_hashes_u32(
            &vertices,
            &indices[..8],
            40
        )
        .is_err());
        assert!(crate::draw::visibility_receipt::packed_triangle_hashes_u32(
            &vertices, &[255; 12], 40
        )
        .is_err());
        assert!(pack_at(&mesh, 256, 0).is_err());
    }
    #[test]
    fn atlas_reservation_is_atomic_and_bounded() {
        let mut offsets = AtlasOffsets::default();
        assert_eq!(offsets.reserve(120, 12, 240, 24), Some((0..120, 0..12)));
        let before = offsets.clone();
        assert_eq!(offsets.reserve(120, 16, 240, 24), None);
        assert_eq!(offsets, before);
        assert_eq!(offsets.reserve(u64::MAX, 12, u64::MAX, 24), None);
        assert_eq!(offsets, before);
        assert_eq!(offsets.reserve(120, 12, 240, 24), Some((120..240, 12..24)));
        assert_eq!(offsets.reserve(40, 4, 240, 24), None);
        let mut too_large = AtlasOffsets::default();
        assert_eq!(
            too_large.reserve((u64::from(u32::MAX) + 1) * 40, 12, u64::MAX, u64::MAX),
            None
        );
        assert_eq!(
            too_large.reserve(120, (u64::from(u32::MAX) + 1) * 4, u64::MAX, u64::MAX),
            None
        );
        assert_eq!(too_large, AtlasOffsets::default());
    }

    #[test]
    fn atlas_rebasing_preserves_receipt_identity_and_rejects_overflow() {
        let mesh = fixture();
        let (vertices, indices) = pack_at(&mesh, 4 * 1024 * 1024, 91).unwrap();
        assert_eq!(u32::from_le_bytes(indices[..4].try_into().unwrap()), 65_627);
        let hashes = crate::draw::visibility_receipt::packed_triangle_hashes_u32_at(
            &vertices, &indices, 40, 91,
        )
        .unwrap();
        assert_eq!(
            hashes,
            vec![crate::draw::visibility_receipt::triangle_sha256(&[
                mesh.vertices()[65_536],
                mesh.vertices()[65_537],
                mesh.vertices()[65_538]
            ])]
        );
        assert!(
            crate::draw::visibility_receipt::packed_triangle_hashes_u32_at(
                &vertices, &indices, 40, 65_628
            )
            .is_err()
        );
        assert!(pack_at(&mesh, 4 * 1024 * 1024, u32::MAX - 65_537).is_err());
    }

    fn small_mesh(x: f32, color: Color) -> StaticMesh {
        StaticMesh::new(
            [
                Vec3::new(x, 2., 0.),
                Vec3::new(x + 8., 2., 0.),
                Vec3::new(x, 10., 0.),
            ]
            .map(|position| Vertex::new2(position, Vec2::ZERO, color))
            .to_vec(),
            vec![0, 1, 2],
            None,
        )
        .unwrap()
    }
    fn dynamic_copy(mesh: &StaticMesh) -> crate::draw::Mesh {
        crate::draw::Mesh {
            vertices: mesh.vertices().to_vec(),
            indices: mesh
                .indices()
                .iter()
                .map(|&i| u16::try_from(i).unwrap())
                .collect(),
            texture: mesh.texture().cloned(),
        }
    }
    fn capture_parity(
        renderer: &mut crate::render::WgpuRenderer,
        mut list: DrawList,
        expected_draws: u64,
        expected_triangles: u64,
    ) -> (image::RgbaImage, crate::render::FrameMetrics) {
        let path = std::env::temp_dir().join(format!("rust-duty-atlas-{}.png", std::process::id()));
        list.capture_png(None, &path);
        // Capture and check the static output first; dynamic geometry cannot
        // cover up a broken atlas draw in the output under test.
        renderer.submit(&list).unwrap();
        let metrics = renderer.last_frame_metrics().unwrap().clone();
        assert_eq!(
            (metrics.draw_calls, metrics.triangles),
            (expected_draws, expected_triangles)
        );
        let actual = image::open(&path).unwrap().to_rgba8();
        for command in &mut list.commands {
            if let crate::draw::Command::StaticMesh { mesh, model, blend } = command {
                *command = crate::draw::Command::Mesh {
                    mesh: dynamic_copy(mesh),
                    model: *model,
                    blend: *blend,
                };
            }
        }
        renderer.submit(&list).unwrap();
        assert_eq!(
            renderer.last_frame_metrics().unwrap().triangles,
            expected_triangles
        );
        assert_eq!(actual, image::open(&path).unwrap().to_rgba8());
        std::fs::remove_file(path).unwrap();
        (actual, metrics)
    }
    fn visible_list(meshes: &[StaticMesh], visible: &[usize]) -> DrawList {
        let mut list = DrawList::new(32, 32);
        list.clear(Color::new(0., 0., 0., 1.));
        for &index in visible {
            list.draw_static_mesh(&meshes[index], Mat4::IDENTITY, BlendMode::Opaque);
        }
        list
    }
    #[test]
    #[ignore = "requires a Vulkan adapter; run explicitly for native atlas validation"]
    fn native_atlas_pixel_count_visibility_state_page_and_lifetime_parity() {
        let mut renderer = pollster::block_on(crate::render::WgpuRenderer::new_headless(
            32,
            32,
            crate::render::BackendSelection::Vulkan,
            true,
        ))
        .unwrap();
        renderer.enable_metrics();
        let meshes = [
            small_mesh(2., Color::new(1., 0., 0., 1.)),
            small_mesh(12., Color::new(0., 1., 0., 1.)),
            small_mesh(22., Color::new(0., 0., 1., 1.)),
        ];
        let (pixels, first) =
            capture_parity(&mut renderer, visible_list(&meshes, &[0, 1, 2]), 1, 3);
        assert_eq!(pixels.get_pixel(3, 3).0, [255, 0, 0, 255]);
        assert_eq!(pixels.get_pixel(13, 3).0, [0, 255, 0, 255]);
        assert_eq!(pixels.get_pixel(23, 3).0, [0, 0, 255, 255]);
        assert_eq!(
            (
                first.vertex_upload_bytes,
                first.index_upload_bytes,
                first.uniform_upload_bytes
            ),
            (360, 36, 64)
        );
        let (_, warm) = capture_parity(&mut renderer, visible_list(&meshes, &[0, 1, 2]), 1, 3);
        assert_eq!(
            (
                warm.vertex_upload_bytes,
                warm.index_upload_bytes,
                warm.uniform_upload_bytes
            ),
            (0, 0, 64)
        );
        let (hole, _) = capture_parity(&mut renderer, visible_list(&meshes, &[0, 2]), 2, 2);
        assert_eq!(hole.get_pixel(13, 3).0, [0, 0, 0, 255]);
        capture_parity(&mut renderer, visible_list(&meshes, &[2, 0]), 2, 2);
        capture_parity(&mut renderer, visible_list(&meshes, &[0, 0, 1]), 2, 3);

        let mut list = visible_list(&meshes, &[0]);
        list.draw_static_mesh(
            &meshes[1],
            Mat4::from_translation(Vec3::Y * 12.),
            BlendMode::Opaque,
        );
        list.draw_static_mesh(&meshes[2], Mat4::IDENTITY, BlendMode::Opaque);
        capture_parity(&mut renderer, list, 3, 3);
        let mut list = visible_list(&meshes, &[0]);
        list.draw_static_mesh(&meshes[1], Mat4::IDENTITY, BlendMode::Alpha);
        list.draw_static_mesh(&meshes[2], Mat4::IDENTITY, BlendMode::Opaque);
        capture_parity(&mut renderer, list, 3, 3);
        let mut list = visible_list(&meshes, &[0]);
        list.draw_mesh(
            &dynamic_copy(&meshes[2]),
            Mat4::from_translation(Vec3::Y * 12.),
            BlendMode::Opaque,
        );
        list.draw_static_mesh(&meshes[1], Mat4::IDENTITY, BlendMode::Opaque);
        capture_parity(&mut renderer, list, 3, 3);
        let mut list = visible_list(&meshes, &[0]);
        list.camera(crate::draw::Camera::screen(32, 32));
        list.draw_static_mesh(&meshes[1], Mat4::IDENTITY, BlendMode::Opaque);
        capture_parity(&mut renderer, list, 2, 2);

        let mut list = visible_list(&meshes, &[0]);
        list.clear(Color::new(0., 0., 0., 1.));
        list.draw_static_mesh(&meshes[1], Mat4::IDENTITY, BlendMode::Opaque);
        let (cleared, _) = capture_parity(&mut renderer, list, 2, 2);
        assert_eq!(cleared.get_pixel(3, 3).0, [0, 0, 0, 255]);
        assert_eq!(cleared.get_pixel(13, 3).0, [0, 255, 0, 255]);
        let checkpoint = std::env::temp_dir().join(format!(
            "rust-duty-atlas-checkpoint-{}.png",
            std::process::id()
        ));
        let mut list = visible_list(&meshes, &[0]);
        list.capture_png(None, &checkpoint);
        list.draw_static_mesh(&meshes[1], Mat4::IDENTITY, BlendMode::Opaque);
        renderer.submit(&list).unwrap();
        assert_eq!(renderer.last_frame_metrics().unwrap().draw_calls, 2);
        let before_second = image::open(&checkpoint).unwrap().to_rgba8();
        assert_eq!(before_second.get_pixel(3, 3).0, [255, 0, 0, 255]);
        assert_eq!(before_second.get_pixel(13, 3).0, [0, 0, 0, 255]);
        capture_parity(&mut renderer, list, 2, 2);
        std::fs::remove_file(checkpoint).unwrap();

        let texture =
            crate::draw::Texture::rgba8(1, 1, &[255; 4], crate::draw::Sampler::default()).unwrap();
        let textured =
            StaticMesh::new(meshes[1].vertices().to_vec(), vec![0, 1, 2], Some(texture)).unwrap();
        let mut list = visible_list(&meshes, &[0]);
        list.draw_static_mesh(&textured, Mat4::IDENTITY, BlendMode::Opaque);
        list.draw_static_mesh(&meshes[2], Mat4::IDENTITY, BlendMode::Opaque);
        capture_parity(&mut renderer, list, 3, 3);
        drop(textured);

        renderer.static_meshes = StaticMeshCache {
            page_limits: Some((240, 24)),
            ..Default::default()
        };
        let (_, pages) = capture_parity(&mut renderer, visible_list(&meshes, &[0, 1, 2]), 2, 3);
        assert_eq!(
            (pages.vertex_upload_bytes, pages.index_upload_bytes),
            (360, 36)
        );
        let first_page =
            Arc::downgrade(&renderer.static_meshes.meshes[&meshes[0].id()].geometry.page);
        let second_page =
            Arc::downgrade(&renderer.static_meshes.meshes[&meshes[2].id()].geometry.page);
        assert!(!Weak::ptr_eq(&first_page, &second_page));
        renderer.static_meshes.retire_unused();
        assert!(first_page.upgrade().is_some());
        assert!(second_page.upgrade().is_some());
        drop(meshes);
        renderer.submit(&DrawList::new(32, 32)).unwrap();
        assert!(renderer.static_meshes.meshes.is_empty());
        assert!(renderer.static_meshes.open.is_none());
        assert!(first_page.upgrade().is_none());
        assert!(second_page.upgrade().is_none());
        renderer.gpu.check_errors().unwrap();
    }

    #[test]
    #[ignore = "requires a Vulkan adapter; run explicitly for native static-buffer validation"]
    fn native_static_u32_reuse_capture_and_eviction() {
        let mut renderer = pollster::block_on(crate::render::WgpuRenderer::new_headless(
            32,
            32,
            crate::render::BackendSelection::Vulkan,
            true,
        ))
        .unwrap();
        renderer.enable_metrics();
        let alignment = u64::from(
            renderer
                .gpu
                .device
                .limits()
                .min_uniform_buffer_offset_alignment,
        );
        let matrix_step = 64_u64.div_ceil(alignment) * alignment;
        let mesh = fixture();
        let id = mesh.id();
        let mut list = DrawList::new(32, 32);
        list.clear(Color::new(0., 0., 0., 1.));
        list.draw_static_mesh(&mesh, Mat4::IDENTITY, BlendMode::Opaque);
        list.draw_static_mesh(&mesh, Mat4::IDENTITY, BlendMode::Opaque);
        renderer.submit(&list).unwrap();
        let metrics = renderer.last_frame_metrics().unwrap();
        assert_eq!((metrics.draw_calls, metrics.triangles), (2, 2));
        assert_eq!(
            metrics.vertex_upload_bytes,
            mesh.vertices().len() as u64 * 40
        );
        assert_eq!(metrics.index_upload_bytes, 12);
        assert_eq!(metrics.uniform_upload_bytes, 64);
        let first = renderer.static_meshes.meshes[&id].geometry.clone();
        let (_, uploaded) = renderer
            .static_meshes
            .resolve(&renderer.gpu.device, &renderer.gpu.queue, &mesh, false)
            .unwrap();
        assert!(!uploaded);
        renderer.submit(&list).unwrap();
        let metrics = renderer.last_frame_metrics().unwrap();
        assert_eq!((metrics.draw_calls, metrics.triangles), (2, 2));
        assert_eq!(
            (
                metrics.vertex_upload_bytes,
                metrics.index_upload_bytes,
                metrics.uniform_upload_bytes
            ),
            (0, 0, 64)
        );
        assert!(Arc::ptr_eq(
            &first,
            &renderer.static_meshes.meshes[&id].geometry
        ));
        assert!(first.receipt_bytes.is_none());
        let (captured, uploaded) = renderer
            .static_meshes
            .resolve(&renderer.gpu.device, &renderer.gpu.queue, &mesh, true)
            .unwrap();
        assert!(uploaded);
        assert!(captured.receipt_bytes.is_some());
        let (_, uploaded) = renderer
            .static_meshes
            .resolve(&renderer.gpu.device, &renderer.gpu.queue, &mesh, true)
            .unwrap();
        assert!(!uploaded);
        let path =
            std::env::temp_dir().join(format!("rust-duty-static-u32-{}.png", std::process::id()));
        // Prove the high-u32 path before any dynamic geometry is submitted.
        // An overlapping dynamic triangle would mask a missing static draw.
        assert!(list
            .commands
            .iter()
            .all(|command| !matches!(command, crate::draw::Command::Mesh { .. })));
        list.capture_png(None, &path);
        renderer.submit(&list).unwrap();
        let pixels = image::open(&path).unwrap().to_rgba8();
        assert_eq!(pixels.get_pixel(8, 8).0, [255; 4]);
        assert_eq!(pixels.get_pixel(30, 30).0, [0, 0, 0, 255]);
        std::fs::remove_file(&path).unwrap();
        assert!(matches!(
            list.commands.pop(),
            Some(crate::draw::Command::Capture { .. })
        ));
        list.draw_mesh(
            &crate::draw::Mesh {
                vertices: mesh.vertices()[65_536..].to_vec(),
                indices: vec![0, 1, 2],
                texture: None,
            },
            Mat4::IDENTITY,
            BlendMode::Opaque,
        );
        renderer.submit(&list).unwrap();
        let metrics = renderer.last_frame_metrics().unwrap();
        assert_eq!((metrics.draw_calls, metrics.triangles), (3, 3));
        assert_eq!(
            (
                metrics.vertex_upload_bytes,
                metrics.index_upload_bytes,
                metrics.uniform_upload_bytes
            ),
            (120, 6, matrix_step + 64)
        );
        drop(mesh);
        renderer.static_meshes.retire_unused();
        assert!(renderer.static_meshes.meshes.contains_key(&id));
        drop(list);
        renderer.submit(&DrawList::new(32, 32)).unwrap();
        assert!(!renderer.static_meshes.meshes.contains_key(&id));
        // Old externally held buffers and submitted GPU work remain valid.
        assert!(first.page.vertices.size() > 0);
        renderer.gpu.check_errors().unwrap();
    }
}
