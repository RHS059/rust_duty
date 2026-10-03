//! Complementary public-API regressions for VRMESH01's multiple-record boundary.
//! Original synthetic geometry and pixels only; no third-party model data.
//! Reviewed against game commit 620f3b86e109319277169b77be5e38b04e35213f.
//! Existing single-record and resource-budget contracts remain in asset_contract.rs.

use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};
use vector_range::asset::{AssetMesh, AssetVertex, WeaponAsset};

const HEADER: usize = 24;
const VERTEX_BYTES: usize = 32;

#[derive(Clone, Copy)]
struct Offsets {
    material: usize,
    texture: usize,
    counts: usize,
    vertices: usize,
    indices: usize,
}

struct Fixture {
    bytes: Vec<u8>,
    records: Vec<Offsets>,
}

// Independent MSB-first reference, using reflected input/output. Production uses
// a reflected LSB-first loop. A fixture must not use the decoder's own checksum
// helper to conceal a defect in that helper.
fn fixture_crc(bytes: &[u8]) -> u32 {
    let mut state = u32::MAX;
    for byte in bytes {
        state ^= u32::from(byte.reverse_bits()) << 24;
        for _ in 0..8 {
            let polynomial = if state & 0x8000_0000 == 0 {
                0
            } else {
                0x04c1_1db7
            };
            state = (state << 1) ^ polynomial;
        }
    }
    !state.reverse_bits()
}

fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn write_float(bytes: &mut [u8], offset: usize, value: f32) {
    write_u32(bytes, offset, value.to_bits());
}

fn repair_frame(bytes: &mut [u8]) {
    assert!(bytes.len() >= HEADER);
    let length = u32::try_from(bytes.len() - HEADER).unwrap();
    let checksum = fixture_crc(&bytes[HEADER..]);
    write_u32(bytes, 12, length);
    write_u32(bytes, 16, checksum);
}

// This only serializes explicit test data in the documented layout. Every
// acceptance/rejection decision is made by the real WeaponAsset public API.
fn encode(meshes: &[AssetMesh]) -> Fixture {
    assert_eq!(fixture_crc(b"123456789"), 0xcbf4_3926);
    let mut bytes = b"VRMESH01".to_vec();
    for value in [1u32, 0, 0, 0, u32::try_from(meshes.len()).unwrap()] {
        bytes.extend(value.to_le_bytes());
    }
    let mut records = Vec::new();
    for mesh in meshes {
        let material = bytes.len();
        for value in mesh
            .base_color
            .into_iter()
            .chain([mesh.metallic, mesh.roughness])
        {
            bytes.extend(value.to_le_bytes());
        }
        let texture = bytes.len();
        for value in [
            mesh.texture_width,
            mesh.texture_height,
            u32::try_from(mesh.rgba.len()).unwrap(),
        ] {
            bytes.extend(value.to_le_bytes());
        }
        bytes.extend_from_slice(&mesh.rgba);
        let counts = bytes.len();
        for value in [mesh.vertices.len(), mesh.indices.len()] {
            bytes.extend(u32::try_from(value).unwrap().to_le_bytes());
        }
        let vertices = bytes.len();
        for vertex in &mesh.vertices {
            for value in vertex
                .position
                .into_iter()
                .chain(vertex.normal)
                .chain(vertex.uv)
            {
                bytes.extend(value.to_le_bytes());
            }
        }
        let indices = bytes.len();
        for index in &mesh.indices {
            bytes.extend(index.to_le_bytes());
        }
        records.push(Offsets {
            material,
            texture,
            counts,
            vertices,
            indices,
        });
    }
    repair_frame(&mut bytes);
    Fixture { bytes, records }
}

fn vertex(position: [f32; 3], normal: [f32; 3], uv: [f32; 2]) -> AssetVertex {
    AssetVertex {
        position,
        normal,
        uv,
    }
}

fn sample_meshes() -> Vec<AssetMesh> {
    vec![
        AssetMesh {
            base_color: [0.125, 0.25, 0.5, 1.],
            metallic: 0.25,
            roughness: 0.75,
            texture_width: 2,
            texture_height: 2,
            rgba: vec![255, 0, 0, 0, 0, 255, 0, 64, 0, 0, 255, 128, 17, 31, 47, 255],
            vertices: vec![
                vertex([-2., 0., 1.], [0., 0., 1.], [-0.25, 0.]),
                vertex([1., 0., 1.], [0., 0., 1.], [1.25, 0.]),
                vertex([0., 3., 1.], [0., 0., 1.], [0.5, 1.]),
            ],
            indices: vec![2, 0, 1],
        },
        AssetMesh {
            base_color: [0.75, 0.5, 0.25, 0.5],
            metallic: 1.,
            roughness: 0.,
            texture_width: 0,
            texture_height: 0,
            rgba: vec![],
            vertices: vec![
                vertex([10., -2., 0.], [0., -1., 0.], [0., 0.]),
                vertex([12., -2., 0.], [0., -1., 0.], [1., 0.]),
                vertex([12., -2., 3.], [0., -1., 0.], [1., 1.]),
                vertex([10., -2., 3.], [0., -1., 0.], [0., 1.]),
            ],
            indices: vec![3, 1, 0, 3, 2, 1],
        },
        AssetMesh {
            base_color: [1., 0., 0.875, 0.25],
            metallic: 0.,
            roughness: 1.,
            texture_width: 1,
            texture_height: 2,
            rgba: vec![9, 8, 7, 6, 1, 2, 3, 4],
            vertices: vec![
                vertex([-4., 0., 0.], [-1., 0., 0.], [0., 0.]),
                vertex([-4., 2., 0.], [-1., 0., 0.], [1., 0.]),
                vertex([-4., 0., 1.], [-1., 0., 0.], [0., 1.]),
            ],
            indices: vec![1, 2, 0],
        },
    ]
}

fn assert_meshes(actual: &WeaponAsset, expected: &[AssetMesh]) {
    assert_eq!(actual.meshes.len(), expected.len(), "mesh count");
    for (record, (actual, expected)) in actual.meshes.iter().zip(expected).enumerate() {
        assert_eq!(
            actual.base_color, expected.base_color,
            "mesh {record} color"
        );
        assert_eq!(actual.metallic, expected.metallic, "mesh {record} metallic");
        assert_eq!(
            actual.roughness, expected.roughness,
            "mesh {record} roughness"
        );
        assert_eq!(
            (actual.texture_width, actual.texture_height),
            (expected.texture_width, expected.texture_height),
            "mesh {record} texture dimensions"
        );
        assert_eq!(actual.rgba, expected.rgba, "mesh {record} RGBA bytes");
        assert_eq!(
            actual.indices, expected.indices,
            "mesh {record} local indices/winding"
        );
        assert_eq!(
            actual.vertices.len(),
            expected.vertices.len(),
            "mesh {record} vertex count"
        );
        for (index, (actual, expected)) in
            actual.vertices.iter().zip(&expected.vertices).enumerate()
        {
            assert_eq!(
                actual.position, expected.position,
                "mesh {record} vertex {index} position"
            );
            assert_eq!(
                actual.normal, expected.normal,
                "mesh {record} vertex {index} normal"
            );
            assert_eq!(actual.uv, expected.uv, "mesh {record} vertex {index} UV");
        }
    }
}

fn reject(bytes: &[u8], reason: &str, case: &str) {
    let error = WeaponAsset::decode(bytes).expect_err(case);
    assert!(
        error.to_string().contains(reason),
        "{case}: expected {reason:?}, got {error}"
    );
}

#[test]
fn heterogeneous_records_preserve_local_geometry_materials_and_rgba() {
    let expected = sample_meshes();
    let fixture = encode(&expected);
    // Independently cross-checked using Python struct.pack and zlib.crc32.
    assert_eq!(fixture.bytes.len(), 552);
    assert_eq!(
        u32::from_le_bytes(fixture.bytes[16..20].try_into().unwrap()),
        0x6377_1b31
    );
    let actual = WeaponAsset::decode(&fixture.bytes).unwrap();
    assert_meshes(&actual, &expected);
}

#[test]
fn mesh_order_is_preserved_without_cross_record_state() {
    let original = sample_meshes();
    for order in [
        [0, 1, 2],
        [0, 2, 1],
        [1, 0, 2],
        [1, 2, 0],
        [2, 0, 1],
        [2, 1, 0],
    ] {
        let expected: Vec<_> = order
            .into_iter()
            .map(|index| original[index].clone())
            .collect();
        let actual = WeaponAsset::decode(&encode(&expected).bytes).unwrap();
        assert_meshes(&actual, &expected);
    }
}

#[test]
fn later_mesh_indices_are_local_not_global() {
    let expected = sample_meshes();
    let fixture = encode(&expected);
    assert_meshes(&WeaponAsset::decode(&fixture.bytes).unwrap(), &expected);
    let total_vertices: usize = expected.iter().map(|mesh| mesh.vertices.len()).sum();
    for (record, mesh) in expected.iter().enumerate().skip(1) {
        let local_limit = mesh.vertices.len();
        assert!(local_limit < total_vertices);
        for index in 0..mesh.indices.len() {
            let mut bytes = fixture.bytes.clone();
            write_u32(
                &mut bytes,
                fixture.records[record].indices + 4 * index,
                u32::try_from(local_limit).unwrap(),
            );
            repair_frame(&mut bytes);
            reject(
                &bytes,
                "index outside vertex array",
                &format!("mesh {record} index {index}"),
            );
        }
    }
}

#[test]
fn later_records_are_fully_validated_after_a_valid_prefix() {
    let fixture = encode(&sample_meshes());
    for record in 1..fixture.records.len() {
        let offsets = fixture.records[record];
        for (offset, value, reason) in [
            (offsets.material + 16, 1.25f32.to_bits(), "material factors"),
            (
                offsets.material + 20,
                f32::INFINITY.to_bits(),
                "non-finite float",
            ),
            (offsets.texture, 2049, "dimensions exceed 2048"),
            (offsets.counts, 0, "invalid vertex or triangle count"),
            (offsets.counts + 4, 4, "invalid vertex or triangle count"),
        ] {
            let mut bytes = fixture.bytes.clone();
            write_u32(&mut bytes, offset, value);
            repair_frame(&mut bytes);
            reject(&bytes, reason, &format!("mesh {record}, offset {offset}"));
        }
    }
}

#[test]
fn every_later_vertex_coordinate_component_has_its_own_bound() {
    let expected = sample_meshes();
    let fixture = encode(&expected);
    for (record, mesh) in expected.iter().enumerate().skip(1) {
        for vertex in 0..mesh.vertices.len() {
            for (component, limit) in [
                (0, 10_000f32),
                (4, 10_000.),
                (8, 10_000.),
                (24, 1_000_000.),
                (28, 1_000_000.),
            ] {
                let offset = fixture.records[record].vertices + vertex * VERTEX_BYTES + component;
                for sign in [-1f32, 1.] {
                    let mut bytes = fixture.bytes.clone();
                    write_float(&mut bytes, offset, sign * limit);
                    repair_frame(&mut bytes);
                    WeaponAsset::decode(&bytes)
                        .expect("inclusive coordinate bound must remain valid");
                    write_float(
                        &mut bytes,
                        offset,
                        sign * f32::from_bits(limit.to_bits() + 1),
                    );
                    repair_frame(&mut bytes);
                    reject(
                        &bytes,
                        "coordinates exceed bounds",
                        &format!("mesh {record} vertex {vertex} component {component} sign {sign}"),
                    );
                }
            }
        }
    }
}

#[test]
fn diagonal_and_negative_normals_are_preserved_and_checked_as_vectors() {
    let original = sample_meshes();
    for normal in [
        [0.6, 0.8, 0.],
        [-0.6, 0.8, 0.],
        [0., -1., 0.],
        [0., 0., -1.],
        [-1., 0., 0.],
    ] {
        let mut expected = original.clone();
        expected[1].vertices[3].normal = normal;
        let actual = WeaponAsset::decode(&encode(&expected).bytes).unwrap();
        assert_meshes(&actual, &expected);
    }
    for normal in [[0.8, 0.8, 0.], [0.6, 0.6, 0.], [f32::MAX, 1., 0.]] {
        let mut invalid = original.clone();
        invalid[1].vertices[3].normal = normal;
        reject(
            &encode(&invalid).bytes,
            "normal is not unit length",
            &format!("normal {normal:?}"),
        );
    }
}

#[test]
fn checksum_correct_truncations_through_later_meshes_are_rejected() {
    let fixture = encode(&sample_meshes());
    for end in fixture.records[1].material..fixture.bytes.len() {
        let mut truncated = fixture.bytes[..end].to_vec();
        repair_frame(&mut truncated);
        assert!(
            WeaponAsset::decode(&truncated).is_err(),
            "accepted reframed prefix at byte {end}"
        );
    }
    WeaponAsset::decode(&fixture.bytes).expect("complete multi-mesh fixture must decode");
}

struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        loop {
            let path = std::env::temp_dir().join(format!(
                "vector-range-asset-quality-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            match fs::create_dir(&path) {
                Ok(()) => return Self(path),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => panic!("cannot create isolated fixture directory: {error}"),
            }
        }
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn loader_rechecks_replaced_files_and_recovers_after_corruption() {
    let temp = TempDir::new();
    let path = temp.0.join("original-multi-mesh.vrm");
    let original = sample_meshes();
    let fixture = encode(&original);
    fs::write(&path, &fixture.bytes).unwrap();
    assert_meshes(&WeaponAsset::load(&path).unwrap(), &original);

    let mut invalid = fixture.bytes;
    write_u32(&mut invalid, fixture.records[2].indices, 3);
    repair_frame(&mut invalid);
    fs::write(&path, invalid).unwrap();
    let error =
        WeaponAsset::load(&path).expect_err("changed invalid file must not reuse cached success");
    assert!(
        error.to_string().contains("index outside vertex array"),
        "{error}"
    );

    let mut replacement = original;
    replacement.reverse();
    replacement[0].base_color = [0., 0.25, 1., 1.];
    fs::write(&path, encode(&replacement).bytes).unwrap();
    assert_meshes(&WeaponAsset::load(&path).unwrap(), &replacement);
}
