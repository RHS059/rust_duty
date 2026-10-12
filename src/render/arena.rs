//! CPU packing for one bounded immutable upload chunk. No cross-frame reuse.
use crate::draw::Vertex;
use glam::{Mat4, Vec4};
use std::ops::Range;

pub(crate) const MATRIX_BYTES: u64 = 64;

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

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct DrawSlice {
    pub vertices: Range<u64>,
    pub indices: Range<u64>,
    pub matrix_offset: u32,
    pub count: u32,
}

pub(crate) struct FrameArena {
    vertices: Vec<u8>,
    indices: Vec<u8>,
    matrices: Vec<u8>,
    matrix_alignment: u64,
    max_buffer_size: u64,
    draws: usize,
}
impl FrameArena {
    pub fn new(matrix_alignment: u32, max_buffer_size: u64) -> Result<Self, String> {
        if matrix_alignment == 0 || max_buffer_size < MATRIX_BYTES {
            return Err("frame upload requires nonzero alignment and matrix-sized buffers".into());
        }
        Ok(Self {
            vertices: Vec::new(),
            indices: Vec::new(),
            matrices: Vec::new(),
            matrix_alignment: u64::from(matrix_alignment),
            max_buffer_size,
            draws: 0,
        })
    }

    /// Every draw keeps its original local indices and its own vertex slice.
    /// Validate every extent before changing any recorded byte or draw count.
    /// Ok(None) means this draw needs a new chunk; it never mutates this chunk.
    pub fn try_append(
        &mut self,
        vertices: &[Vertex],
        indices: &[u16],
        transform: Mat4,
    ) -> Result<Option<DrawSlice>, String> {
        if indices.is_empty() || vertices.is_empty() {
            return Err("cannot append empty frame geometry".into());
        }
        if !transform.is_finite() || indices.iter().any(|&i| usize::from(i) >= vertices.len()) {
            return Err("invalid frame geometry transform or index".into());
        }
        let vertex_start = self.vertices.len() as u64;
        let index_start = self.indices.len() as u64;
        let vertex_end = checked_end(vertex_start, vertices.len(), GpuVertex::STRIDE)?;
        let index_end = checked_end(index_start, indices.len(), 2)?;
        let Some((matrix_offset, matrix_end)) =
            matrix_slot(self.matrices.len() as u64, self.matrix_alignment)
        else {
            return Ok(None);
        };
        let matrix_start = u64::from(matrix_offset);
        let count =
            u32::try_from(indices.len()).map_err(|_| "frame draw index count exceeds u32")?;
        // create_buffer_init pads payloads to four bytes. Include that padding
        // in the limit check, especially for an odd number of u16 indices.
        for end in [vertex_end, index_end, matrix_end] {
            if align_up(end, 4)? > self.max_buffer_size || usize::try_from(end).is_err() {
                return Ok(None);
            }
        }
        let next_draws = self
            .draws
            .checked_add(1)
            .ok_or("frame draw count overflow")?;
        self.vertices
            .try_reserve(vertex_end as usize - self.vertices.len())
            .map_err(|_| "cannot reserve frame vertices")?;
        self.indices
            .try_reserve(index_end as usize - self.indices.len())
            .map_err(|_| "cannot reserve frame indices")?;
        self.matrices
            .try_reserve(matrix_end as usize - self.matrices.len())
            .map_err(|_| "cannot reserve frame matrices")?;
        for vertex in vertices {
            GpuVertex::from(*vertex).append_bytes(&mut self.vertices);
        }
        for index in indices {
            self.indices.extend(index.to_le_bytes());
        }
        self.matrices.resize(matrix_start as usize, 0);
        for value in transform.to_cols_array() {
            self.matrices.extend(value.to_le_bytes());
        }
        self.draws = next_draws;
        Ok(Some(DrawSlice {
            vertices: vertex_start..vertex_end,
            indices: index_start..index_end,
            matrix_offset,
            count,
        }))
    }

    #[cfg(test)]
    fn append(
        &mut self,
        vertices: &[Vertex],
        indices: &[u16],
        transform: Mat4,
    ) -> Result<DrawSlice, String> {
        self.try_append(vertices, indices, transform)?
            .ok_or_else(|| "draw requires a new arena".into())
    }

    /// The renderer creates exactly these three buffers once, or none for a
    /// clear/capture-only headless frame. There is no per-draw upload operation.
    pub fn buffer_contents(&self) -> Option<[&[u8]; 3]> {
        (self.draws != 0).then_some([&self.vertices, &self.indices, &self.matrices])
    }
}
fn align_up(value: u64, alignment: u64) -> Result<u64, String> {
    let remainder = value % alignment;
    if remainder == 0 {
        Ok(value)
    } else {
        value
            .checked_add(alignment - remainder)
            .ok_or_else(|| "frame alignment overflow".into())
    }
}
fn matrix_slot(length: u64, alignment: u64) -> Option<(u32, u64)> {
    let start = align_up(length, alignment).ok()?;
    Some((u32::try_from(start).ok()?, start.checked_add(MATRIX_BYTES)?))
}
fn checked_end(start: u64, len: usize, stride: u64) -> Result<u64, String> {
    u64::try_from(len)
        .ok()
        .and_then(|len| len.checked_mul(stride))
        .and_then(|bytes| start.checked_add(bytes))
        .ok_or_else(|| "frame geometry size overflow".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::draw::Color;
    use glam::{Vec2, Vec3};
    fn triangle(seed: f32) -> [Vertex; 3] {
        [0., 1., 2.].map(|v| {
            Vertex::new2(
                Vec3::new(seed + v, v, -v),
                Vec2::new(v, seed),
                Color::new(0.2, 0.3, 0.4, 0.5),
            )
        })
    }
    fn matrix_bytes(matrix: Mat4) -> Vec<u8> {
        matrix
            .to_cols_array()
            .into_iter()
            .flat_map(f32::to_le_bytes)
            .collect()
    }
    #[test]
    fn distinct_draws_preserve_bytes_local_indices_and_aligned_matrices() {
        let mut arena = FrameArena::new(256, 4096).unwrap();
        let a = triangle(10.);
        let b = triangle(20.);
        let ma = Mat4::from_translation(Vec3::new(1., 2., 3.));
        let mb = Mat4::from_scale(Vec3::new(4., 5., 6.));
        let first = arena.append(&a, &[2, 0, 1], ma).unwrap();
        let second = arena.append(&b, &[1, 2, 0], mb).unwrap();
        assert_eq!(
            first,
            DrawSlice {
                vertices: 0..120,
                indices: 0..6,
                matrix_offset: 0,
                count: 3
            }
        );
        assert_eq!(
            second,
            DrawSlice {
                vertices: 120..240,
                indices: 6..12,
                matrix_offset: 256,
                count: 3
            }
        );
        let [vertices, indices, matrices] = arena.buffer_contents().unwrap();
        let mut expected = Vec::new();
        for v in a.into_iter().chain(b) {
            GpuVertex::from(v).append_bytes(&mut expected);
        }
        assert_eq!(vertices, expected);
        assert_eq!(indices, [2, 0, 0, 0, 1, 0, 1, 0, 2, 0, 0, 0]);
        assert_eq!(&matrices[..64], matrix_bytes(ma));
        assert!(matrices[64..256].iter().all(|&b| b == 0));
        assert_eq!(&matrices[256..320], matrix_bytes(mb));
    }
    #[test]
    fn upload_count_is_three_for_one_or_hundreds_of_draws() {
        for draws in [1, 177, 336, 580] {
            let mut arena = FrameArena::new(256, 1024 * 1024).unwrap();
            assert!(arena.buffer_contents().is_none());
            for i in 0..draws {
                let slice = arena
                    .append(&triangle(i as f32), &[0, 1, 2], Mat4::IDENTITY)
                    .unwrap();
                assert_eq!(slice.matrix_offset, i * 256);
            }
            assert_eq!(arena.buffer_contents().unwrap().len(), 3);
            assert_eq!(arena.draws, draws as usize);
        }
    }
    #[test]
    fn failed_append_is_atomic_and_includes_upload_padding() {
        let mut arena = FrameArena::new(256, 256).unwrap();
        arena
            .append(&triangle(0.), &[0, 1, 2], Mat4::IDENTITY)
            .unwrap();
        let before = [
            arena.vertices.clone(),
            arena.indices.clone(),
            arena.matrices.clone(),
        ];
        assert!(arena
            .append(&triangle(1.), &[0, 1, 2], Mat4::IDENTITY)
            .is_err());
        assert_eq!([arena.vertices, arena.indices, arena.matrices], before);
        let mut arena = FrameArena::new(1, 123).unwrap();
        // 61 local indices occupy 122 bytes and require a 124-byte GPU buffer.
        assert!(arena
            .append(&triangle(0.), &[0; 61], Mat4::IDENTITY)
            .is_err());
        assert!(arena.buffer_contents().is_none());
    }
    #[test]
    fn invalid_input_and_size_arithmetic_fail_without_uploads() {
        assert!(FrameArena::new(0, 4096).is_err());
        assert!(FrameArena::new(256, 63).is_err());
        let mut arena = FrameArena::new(256, 4096).unwrap();
        assert!(arena.append(&[], &[], Mat4::IDENTITY).is_err());
        assert!(arena.append(&triangle(0.), &[3], Mat4::IDENTITY).is_err());
        assert!(arena
            .append(&triangle(0.), &[0], Mat4::from_cols_array(&[f32::NAN; 16]))
            .is_err());
        assert!(arena.buffer_contents().is_none());
        assert!(align_up(u64::MAX, 256).is_err());
        assert!(checked_end(u64::MAX, 1, 40).is_err());
        assert!(checked_end(0, usize::MAX, 40).is_err());
    }
    #[test]
    fn dynamic_offset_exhaustion_requests_a_new_chunk_without_large_allocations() {
        assert_eq!(matrix_slot(64, 256), Some((256, 320)));
        assert_eq!(matrix_slot(u64::from(u32::MAX) + 1, 256), None);
        assert_eq!(matrix_slot(u64::MAX, 256), None);
    }
    #[test]
    fn independent_frames_never_alias_previous_frame_bytes() {
        let mut first = FrameArena::new(256, 4096).unwrap();
        first
            .append(&triangle(1.), &[0, 1, 2], Mat4::IDENTITY)
            .unwrap();
        let old = first.buffer_contents().unwrap().map(<[u8]>::to_vec);
        let mut next = FrameArena::new(256, 4096).unwrap();
        next.append(&triangle(2.), &[2, 1, 0], Mat4::from_translation(Vec3::X))
            .unwrap();
        assert_eq!(
            first.buffer_contents().unwrap(),
            old.each_ref().map(Vec::as_slice)
        );
        assert_ne!(first.buffer_contents(), next.buffer_contents());
    }
}
