//! Bounded VRSKIN02 decoder. Matrices are glTF-style column-major.
//! Vertices preserve eight influences; this local container is not encryption.
use std::{fmt, fs::File, io::Read, path::Path};
pub const MAX_FILE: usize = 128 * 1024 * 1024;
pub const MAX_BONES: usize = 128;
pub const MAX_MESHES: usize = 128;
pub const MAX_VERTICES: usize = 1_000_000;
pub const MAX_INDICES: usize = 3_000_000;
pub const MAX_TEXTURE_BYTES: usize = 64 * 1024 * 1024;
#[derive(Debug, Clone)]
pub struct AssetError(pub String);
impl fmt::Display for AssetError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for AssetError {}
pub type Result<T> = std::result::Result<T, AssetError>;
fn error(s: &str) -> AssetError {
    AssetError(s.into())
}
#[derive(Debug, Clone)]
pub struct Bone {
    pub name: String,
    pub parent: Option<usize>,
    pub rest_local: [f32; 16],
    pub inverse_bind: [f32; 16],
}
#[derive(Debug, Clone)]
pub struct SkinVertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    pub joints: [u16; 8],
    pub weights: [f32; 8],
}
#[derive(Debug, Clone)]
pub struct SkinMesh {
    pub base_color: [f32; 4],
    pub metallic: f32,
    pub roughness: f32,
    pub texture_width: u32,
    pub texture_height: u32,
    pub rgba: Vec<u8>,
    pub vertices: Vec<SkinVertex>,
    pub indices: Vec<u32>,
}
#[derive(Debug, Clone)]
pub struct SkinnedAsset {
    pub bones: Vec<Bone>,
    pub meshes: Vec<SkinMesh>,
}
struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self
            .pos
            .checked_add(n)
            .ok_or_else(|| error("offset overflow"))?;
        let out = self
            .bytes
            .get(self.pos..end)
            .ok_or_else(|| error("truncated asset"))?;
        self.pos = end;
        Ok(out)
    }
    fn u16(&mut self) -> Result<u16> {
        let a = self.take(2)?;
        Ok(u16::from_le_bytes([a[0], a[1]]))
    }
    fn u32(&mut self) -> Result<u32> {
        let a = self.take(4)?;
        Ok(u32::from_le_bytes([a[0], a[1], a[2], a[3]]))
    }
    fn i32(&mut self) -> Result<i32> {
        Ok(self.u32()? as i32)
    }
    fn float(&mut self) -> Result<f32> {
        let x = f32::from_bits(self.u32()?);
        if !x.is_finite() {
            return Err(error("non-finite float"));
        }
        Ok(x)
    }
    fn floats<const N: usize>(&mut self) -> Result<[f32; N]> {
        let mut a = [0.; N];
        for x in &mut a {
            *x = self.float()?;
        }
        Ok(a)
    }
    fn matrix(&mut self) -> Result<[f32; 16]> {
        let m = self.floats::<16>()?;
        if m[3] != 0. || m[7] != 0. || m[11] != 0. || m[15] != 1. {
            return Err(error("matrix is not affine"));
        }
        // Compute in f64 so valid f32 matrices do not overflow this validation.
        let [a, b, c, d, e, f, g, h, i] =
            [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]].map(f64::from);
        let det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
        if det == 0. {
            return Err(error("matrix is singular"));
        }
        Ok(m)
    }
}
/// IEEE CRC-32; catches corruption, provides no authenticity or encryption.
pub fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = !0u32;
    for &byte in bytes {
        crc ^= byte as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xedb88320u32 & (0u32.wrapping_sub(crc & 1)));
        }
    }
    !crc
}
impl SkinnedAsset {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let f = File::open(path).map_err(|e| AssetError(e.to_string()))?;
        let mut bytes = Vec::new();
        f.take((MAX_FILE + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|e| AssetError(e.to_string()))?;
        Self::decode(&bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        if bytes.len() > MAX_FILE {
            return Err(error("asset exceeds 128 MiB"));
        }
        let mut r = Reader { bytes, pos: 0 };
        if r.take(8)? != b"VRSKIN02" {
            return Err(error("wrong skinned asset magic"));
        }
        if r.u32()? != 2 {
            return Err(error("unsupported skinned asset version"));
        }
        let length = r.u32()? as usize;
        let checksum = r.u32()?;
        if r.u32()? != 0 {
            return Err(error("reserved header flags must be zero"));
        }
        if length != bytes.len() - r.pos {
            return Err(error("payload length mismatch"));
        }
        if crc32(&bytes[r.pos..]) != checksum {
            return Err(error("payload checksum mismatch"));
        }
        let bc = r.u32()? as usize;
        if !(1..=MAX_BONES).contains(&bc) {
            return Err(error("bone count outside 1..128"));
        }
        let mut bones = Vec::with_capacity(bc);
        for _ in 0..bc {
            let size = r.u16()? as usize;
            if !(1..=64).contains(&size) {
                return Err(error("bone name must have 1..64 UTF-8 bytes"));
            }
            let name =
                std::str::from_utf8(r.take(size)?).map_err(|_| error("invalid UTF-8 bone name"))?;
            if name.contains('\0') {
                return Err(error("NUL in bone name"));
            }
            let parent = r.i32()?;
            if parent < -1 || parent >= bc as i32 {
                return Err(error("bone parent outside skeleton"));
            }
            let rest_local = r.matrix()?;
            let inverse_bind = r.matrix()?;
            bones.push(Bone {
                name: name.into(),
                parent: if parent == -1 {
                    None
                } else {
                    Some(parent as usize)
                },
                rest_local,
                inverse_bind,
            });
        }
        // Parent order is arbitrary. Every chain must terminate within bc steps.
        for start in 0..bc {
            let mut at = Some(start);
            for _ in 0..bc {
                at = at.and_then(|j| bones[j].parent);
            }
            if at.is_some() {
                return Err(error("cycle in bone hierarchy"));
            }
        }
        let count = r.u32()? as usize;
        if !(1..=MAX_MESHES).contains(&count) {
            return Err(error("mesh count outside 1..128"));
        }
        let mut meshes = Vec::with_capacity(count);
        let (mut total_v, mut total_i, mut total_t) = (0usize, 0usize, 0usize);
        for _ in 0..count {
            let base_color = r.floats::<4>()?;
            let metallic = r.float()?;
            let roughness = r.float()?;
            if base_color
                .iter()
                .chain([metallic, roughness].iter())
                .any(|x| !(0.0..=1.0).contains(x))
            {
                return Err(error("material factors outside 0..1"));
            }
            let texture_width = r.u32()?;
            let texture_height = r.u32()?;
            let size = r.u32()? as usize;
            if texture_width > 2048 || texture_height > 2048 {
                return Err(error("texture dimensions exceed 2048"));
            }
            if (size == 0 && (texture_width != 0 || texture_height != 0))
                || (size != 0 && (texture_width == 0 || texture_height == 0))
                || size != texture_width as usize * texture_height as usize * 4
            {
                return Err(error("invalid RGBA dimensions"));
            }
            total_t += size;
            if total_t > MAX_TEXTURE_BYTES {
                return Err(error("aggregate texture budget exceeded"));
            }
            let rgba = r.take(size)?.to_vec();
            let vc = r.u32()? as usize;
            let ic = r.u32()? as usize;
            if vc == 0 || vc > MAX_VERTICES || ic == 0 || ic > MAX_INDICES || !ic.is_multiple_of(3)
            {
                return Err(error("invalid vertex or triangle count"));
            }
            total_v += vc;
            total_i += ic;
            if total_v > MAX_VERTICES || total_i > MAX_INDICES {
                return Err(error("aggregate geometry budget exceeded"));
            }
            // Counts are individually bounded before multiplication/allocation.
            if vc * 80 + ic * 4 > bytes.len() - r.pos {
                return Err(error("truncated geometry"));
            }
            let mut vertices = Vec::with_capacity(vc);
            for _ in 0..vc {
                let position = r.floats::<3>()?;
                let normal = r.floats::<3>()?;
                let uv = r.floats::<2>()?;
                if position.iter().any(|v| v.abs() > 10_000.)
                    || uv.iter().any(|v| v.abs() > 1_000_000.)
                {
                    return Err(error("vertex coordinates exceed bounds"));
                }
                let n2: f32 = normal.iter().map(|x| x * x).sum();
                if !(0.98..=1.02).contains(&n2) {
                    return Err(error("normal is not unit length"));
                }
                let mut joints = [0u16; 8];
                for j in &mut joints {
                    *j = r.u16()?;
                    if *j as usize >= bc {
                        return Err(error("vertex joint outside skeleton"));
                    }
                }
                let weights = r.floats::<8>()?;
                let sum: f32 = weights.iter().sum();
                if weights.iter().any(|x| !(0.0..=1.0).contains(x))
                    || !(0.9999..=1.0001).contains(&sum)
                {
                    return Err(error("weights must be nonnegative and normalized"));
                }
                vertices.push(SkinVertex {
                    position,
                    normal,
                    uv,
                    joints,
                    weights,
                });
            }
            let mut indices = Vec::with_capacity(ic);
            for _ in 0..ic {
                let i = r.u32()?;
                if i as usize >= vc {
                    return Err(error("index outside vertex array"));
                }
                indices.push(i);
            }
            meshes.push(SkinMesh {
                base_color,
                metallic,
                roughness,
                texture_width,
                texture_height,
                rgba,
                vertices,
                indices,
            });
        }
        if r.pos != bytes.len() {
            return Err(error("unexpected trailing data"));
        }
        Ok(Self { bones, meshes })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const FIXTURE: &[u8] = include_bytes!("../tests/fixtures/two_bone_triangle.vrs");
    fn rehash(b: &mut [u8]) {
        let checksum = crc32(&b[24..]);
        b[16..20].copy_from_slice(&checksum.to_le_bytes());
    }
    fn reject_patch(offset: usize, value: &[u8]) {
        let mut b = FIXTURE.to_vec();
        b[offset..offset + value.len()].copy_from_slice(value);
        rehash(&mut b);
        assert!(
            SkinnedAsset::decode(&b).is_err(),
            "accepted invalid patch at {offset}"
        );
    }
    #[test]
    fn decodes_original_fixture_with_forward_parent_and_baked_helpers() {
        let a = SkinnedAsset::decode(FIXTURE).unwrap();
        assert_eq!(a.bones.len(), 2);
        assert_eq!(a.bones[0].name, "tip");
        assert_eq!(a.bones[0].parent, Some(1));
        assert_eq!(&a.bones[0].rest_local[12..15], &[0., 3., 4.]);
        assert_eq!(&a.bones[1].rest_local[12..15], &[2., 0., 0.]);
        assert_eq!(&a.bones[0].inverse_bind[12..15], &[-2., -3., -4.]);
        assert_eq!(a.meshes[0].indices, [0, 1, 2]);
        assert_eq!(
            a.meshes[0].vertices[0].weights,
            [0.75, 0.25, 0., 0., 0., 0., 0., 0.]
        );
    }
    #[test]
    fn standard_crc() {
        assert_eq!(crc32(b"123456789"), 0xcbf43926);
    }
    #[test]
    fn rejects_every_truncation() {
        for end in 0..FIXTURE.len() {
            assert!(SkinnedAsset::decode(&FIXTURE[..end]).is_err());
        }
    }
    #[test]
    fn rejects_bad_headers() {
        for offset in [0, 8, 12, 16, 20] {
            let mut b = FIXTURE.to_vec();
            b[offset] ^= 1;
            assert!(SkinnedAsset::decode(&b).is_err());
        }
    }
    #[test]
    fn rejects_invalid_parents_and_cycles() {
        for parent in [-2i32, 0, 2, i32::MAX] {
            reject_patch(33, &parent.to_le_bytes());
        }
        // tip->root->tip two-bone cycle.
        reject_patch(171, &0i32.to_le_bytes());
    }
    #[test]
    fn rejects_invalid_names() {
        for size in [0u16, 65, u16::MAX] {
            reject_patch(28, &size.to_le_bytes());
        }
        reject_patch(30, &[0xff]);
        reject_patch(30, &[0]);
    }
    #[test]
    fn rejects_invalid_matrices() {
        for x in [f32::NAN, f32::INFINITY, 0.] {
            reject_patch(37, &x.to_le_bytes());
        }
        reject_patch(37 + 3 * 4, &1f32.to_le_bytes());
        reject_patch(37 + 15 * 4, &2f32.to_le_bytes());
        reject_patch(101, &f32::NAN.to_le_bytes());
    }
    #[test]
    fn rejects_invalid_counts_before_large_allocations() {
        for offset in [24, 303, 343, 347] {
            reject_patch(offset, &u32::MAX.to_le_bytes());
            reject_patch(offset, &0u32.to_le_bytes());
        }
        reject_patch(347, &4u32.to_le_bytes());
    }
    #[test]
    fn rejects_invalid_material_and_texture() {
        for x in [f32::NAN, -1., 2.] {
            reject_patch(307, &x.to_le_bytes());
        }
        reject_patch(331, &2049u32.to_le_bytes());
        reject_patch(335, &1u32.to_le_bytes());
        reject_patch(339, &4u32.to_le_bytes());
    }
    #[test]
    fn rejects_invalid_vertex_attributes() {
        reject_patch(351, &10001f32.to_le_bytes());
        reject_patch(351, &f32::NAN.to_le_bytes());
        reject_patch(351 + 20, &0f32.to_le_bytes());
        reject_patch(351 + 24, &1_000_001f32.to_le_bytes());
        reject_patch(351 + 32, &2u16.to_le_bytes());
        reject_patch(351 + 46, &u16::MAX.to_le_bytes());
        for x in [0f32, -0.5, 2., f32::NAN, f32::INFINITY] {
            reject_patch(351 + 48, &x.to_le_bytes());
        }
        reject_patch(351 + 76, &0.25f32.to_le_bytes());
    }
    #[test]
    fn supports_eighth_weight_without_truncating_it() {
        let mut b = FIXTURE.to_vec();
        b[351 + 48..351 + 52].copy_from_slice(&0.5f32.to_le_bytes());
        b[351 + 46..351 + 48].copy_from_slice(&1u16.to_le_bytes());
        b[351 + 76..351 + 80].copy_from_slice(&0.25f32.to_le_bytes());
        rehash(&mut b);
        let a = SkinnedAsset::decode(&b).unwrap();
        assert_eq!(a.meshes[0].vertices[0].weights[7], 0.25);
        assert_eq!(a.meshes[0].vertices[0].joints[7], 1);
    }
    #[test]
    fn rejects_index_out_of_bounds() {
        reject_patch(591, &3u32.to_le_bytes());
    }
    #[test]
    fn rejects_trailing_payload() {
        let mut b = FIXTURE.to_vec();
        b.push(0);
        let len = (b.len() - 24) as u32;
        b[12..16].copy_from_slice(&len.to_le_bytes());
        rehash(&mut b);
        assert!(SkinnedAsset::decode(&b).is_err());
    }
    #[test]
    fn malformed_mutations_never_panic() {
        let mut seed = 0xabcdu32;
        for _ in 0..2000 {
            seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
            let offset = 24 + (seed as usize % (FIXTURE.len() - 24));
            let mut b = FIXTURE.to_vec();
            b[offset] ^= ((seed >> 24) as u8) | 1;
            rehash(&mut b);
            let _ = SkinnedAsset::decode(&b);
        }
        for len in 0..512 {
            let mut b = vec![0u8; len];
            for x in &mut b {
                seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
                *x = (seed >> 24) as u8;
            }
            assert!(SkinnedAsset::decode(&b).is_err());
        }
    }
}
