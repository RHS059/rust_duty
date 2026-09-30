//! Independently authored, bounded VRMESH01 decoder. This is a layout, not encryption.
use std::{fmt, fs::File, io::Read, path::Path};
pub const MAX_FILE: usize = 128 * 1024 * 1024;
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
type Result<T> = std::result::Result<T, AssetError>;
fn error(s: &str) -> AssetError {
    AssetError(s.into())
}
#[derive(Debug, Clone)]
pub struct AssetVertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
}
#[derive(Debug, Clone)]
pub struct AssetMesh {
    pub base_color: [f32; 4],
    pub metallic: f32,
    pub roughness: f32,
    pub texture_width: u32,
    pub texture_height: u32,
    pub rgba: Vec<u8>,
    pub vertices: Vec<AssetVertex>,
    pub indices: Vec<u32>,
}
#[derive(Debug, Clone)]
pub struct WeaponAsset {
    pub meshes: Vec<AssetMesh>,
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
    fn u32(&mut self) -> Result<u32> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
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
}
/// IEEE CRC-32; detects accidental corruption, not malicious modification.
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
impl WeaponAsset {
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
        if r.take(8)? != b"VRMESH01" {
            return Err(error("wrong asset magic"));
        }
        if r.u32()? != 1 {
            return Err(error("unsupported asset version"));
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
        let count = r.u32()? as usize;
        if !(1..=256).contains(&count) {
            return Err(error("mesh count outside 1..256"));
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
            // Prove record storage exists before allocating vectors.
            if vc * 32 + ic * 4 > bytes.len() - r.pos {
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
                vertices.push(AssetVertex {
                    position,
                    normal,
                    uv,
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
            meshes.push(AssetMesh {
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
        Ok(Self { meshes })
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> Vec<u8> {
        let mut p = Vec::new();
        p.extend(1u32.to_le_bytes());
        for v in [1f32, 0.5, 0.2, 1., 0., 0.7] {
            p.extend(v.to_le_bytes());
        }
        for v in [0u32, 0, 0, 3, 3] {
            p.extend(v.to_le_bytes());
        }
        for pos in [[0f32, 0., 0.], [1., 0., 0.], [0., 1., 0.]] {
            for v in pos.into_iter().chain([0., 0., 1., 0., 0.]) {
                p.extend(v.to_le_bytes());
            }
        }
        for i in [0u32, 1, 2] {
            p.extend(i.to_le_bytes());
        }
        let mut b = b"VRMESH01".to_vec();
        for x in [1, p.len() as u32, crc32(&p), 0] {
            b.extend(x.to_le_bytes());
        }
        b.extend(p);
        b
    }
    fn rehash(b: &mut [u8]) {
        let crc = crc32(&b[24..]);
        b[16..20].copy_from_slice(&crc.to_le_bytes());
    }
    #[test]
    fn decode_original_triangle() {
        let a = WeaponAsset::decode(&fixture()).unwrap();
        assert_eq!(a.meshes[0].indices, [0, 1, 2]);
    }
    #[test]
    fn crc_standard_vector() {
        assert_eq!(crc32(b"123456789"), 0xcbf43926);
    }
    #[test]
    fn rejects_every_truncation() {
        let b = fixture();
        for n in 0..b.len() {
            assert!(WeaponAsset::decode(&b[..n]).is_err());
        }
    }
    #[test]
    fn rejects_header_corruption() {
        for at in [0, 8, 12, 16, 20] {
            let mut b = fixture();
            b[at] ^= 1;
            assert!(WeaponAsset::decode(&b).is_err());
        }
    }
    #[test]
    fn rejects_nan_and_nonunit_normal() {
        for at in [28, 72, 84] {
            let mut b = fixture();
            b[at..at + 4].copy_from_slice(&f32::NAN.to_le_bytes());
            rehash(&mut b);
            assert!(WeaponAsset::decode(&b).is_err());
        }
    }
    #[test]
    fn rejects_out_of_range_index() {
        let mut b = fixture();
        let n = b.len();
        b[n - 4..].copy_from_slice(&3u32.to_le_bytes());
        rehash(&mut b);
        assert!(WeaponAsset::decode(&b).is_err());
    }
    #[test]
    fn rejects_huge_count_without_allocating() {
        let mut b = fixture();
        b[64..68].copy_from_slice(&u32::MAX.to_le_bytes());
        rehash(&mut b);
        assert!(WeaponAsset::decode(&b).is_err());
    }
    #[test]
    fn arbitrary_bytes_never_panic() {
        let mut seed = 0xabcdu32;
        for len in 0..512 {
            let mut b = vec![0u8; len];
            for x in &mut b {
                seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
                *x = (seed >> 24) as u8;
            }
            assert!(WeaponAsset::decode(&b).is_err());
        }
    }
}
