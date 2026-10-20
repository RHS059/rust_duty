//! Persistent immutable buffers. CPU owners and queued draw lists control cache
//! residency; WGPU retains recorded buffers until in-flight work completes.
use super::arena::GpuVertex;
use crate::draw::{ResourceId, StaticMesh, StaticMeshData};
use std::{
    collections::HashMap,
    sync::{Arc, Weak},
};
use wgpu::util::DeviceExt;

pub(super) struct StaticGeometry {
    pub vertices: wgpu::Buffer,
    pub indices: wgpu::Buffer,
    /// Only capture sessions retain the exact packed inputs supplied to WGPU.
    /// Ordinary gameplay releases temporary packing immediately after upload.
    pub receipt_bytes: Option<(Vec<u8>, Vec<u8>)>,
}
struct CachedMesh {
    owner: Weak<StaticMeshData>,
    geometry: Arc<StaticGeometry>,
}
#[derive(Default)]
pub(super) struct StaticMeshCache {
    meshes: HashMap<ResourceId, CachedMesh>,
}
impl StaticMeshCache {
    pub fn retire_unused(&mut self) {
        self.meshes.retain(|_, mesh| mesh.owner.strong_count() != 0);
    }
    /// Returns the immutable buffers and whether vertex/index data was uploaded.
    /// Receipts requested after warmup force one fresh upload with retained byte
    /// provenance. This capture-only cost never enters ordinary frame preparation.
    pub fn resolve(
        &mut self,
        device: &wgpu::Device,
        mesh: &StaticMesh,
        receipt: bool,
    ) -> Result<(Arc<StaticGeometry>, bool), String> {
        if let Some(cached) = self.meshes.get(&mesh.id()) {
            if !receipt || cached.geometry.receipt_bytes.is_some() {
                return Ok((cached.geometry.clone(), false));
            }
        }
        let (vertices, indices) = pack(mesh, device.limits().max_buffer_size)?;
        let geometry = Arc::new(StaticGeometry {
            vertices: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("persistent static vertices"),
                contents: &vertices,
                usage: wgpu::BufferUsages::VERTEX,
            }),
            indices: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("persistent static u32 indices"),
                contents: &indices,
                usage: wgpu::BufferUsages::INDEX,
            }),
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
fn pack(mesh: &StaticMesh, max_buffer_size: u64) -> Result<(Vec<u8>, Vec<u8>), String> {
    let vertex_bytes = mesh
        .vertices()
        .len()
        .checked_mul(GpuVertex::STRIDE as usize)
        .ok_or("static vertex buffer size overflow")?;
    let index_bytes = mesh
        .indices()
        .len()
        .checked_mul(4)
        .ok_or("static index buffer size overflow")?;
    if vertex_bytes == 0
        || index_bytes == 0
        || vertex_bytes as u64 > max_buffer_size
        || index_bytes as u64 > max_buffer_size
    {
        return Err("static mesh is empty or exceeds adapter buffer limit".into());
    }
    let mut vertices = Vec::new();
    vertices
        .try_reserve_exact(vertex_bytes)
        .map_err(|_| "cannot reserve static vertices")?;
    for vertex in mesh.vertices() {
        GpuVertex::from(*vertex).append_bytes(&mut vertices);
    }
    let mut indices = Vec::new();
    indices
        .try_reserve_exact(index_bytes)
        .map_err(|_| "cannot reserve static indices")?;
    for index in mesh.indices() {
        indices.extend(index.to_le_bytes());
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
        let (vertices, indices) = pack(&mesh, 4 * 1024 * 1024).unwrap();
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
        assert!(pack(&mesh, 256).is_err());
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
        assert_eq!(metrics.uniform_upload_bytes, matrix_step + 64);
        let first = renderer.static_meshes.meshes[&id].geometry.clone();
        let (_, uploaded) = renderer
            .static_meshes
            .resolve(&renderer.gpu.device, &mesh, false)
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
            (0, 0, matrix_step + 64)
        );
        assert!(Arc::ptr_eq(
            &first,
            &renderer.static_meshes.meshes[&id].geometry
        ));
        assert!(first.receipt_bytes.is_none());
        let (captured, uploaded) = renderer
            .static_meshes
            .resolve(&renderer.gpu.device, &mesh, true)
            .unwrap();
        assert!(uploaded);
        assert!(captured.receipt_bytes.is_some());
        let (_, uploaded) = renderer
            .static_meshes
            .resolve(&renderer.gpu.device, &mesh, true)
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
            (120, 6, matrix_step * 2 + 64)
        );
        drop(mesh);
        renderer.static_meshes.retire_unused();
        assert!(renderer.static_meshes.meshes.contains_key(&id));
        drop(list);
        renderer.submit(&DrawList::new(32, 32)).unwrap();
        assert!(!renderer.static_meshes.meshes.contains_key(&id));
        // Old externally held buffers and submitted GPU work remain valid.
        assert!(first.vertices.size() > 0);
        renderer.gpu.check_errors().unwrap();
    }
}
