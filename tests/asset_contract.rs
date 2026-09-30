//! Public decoder and local-build contract tests for the original VRMESH01 layout.
//! Fixtures here contain newly authored triangles, never third-party model data.
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    sync::atomic::{AtomicU64, Ordering},
};
use vector_range::asset::{
    crc32, WeaponAsset, MAX_FILE, MAX_INDICES, MAX_TEXTURE_BYTES, MAX_VERTICES,
};

const HEADER: usize = 24;
const MATERIAL: usize = 28;
const WIDTH: usize = 52;
const HEIGHT: usize = 56;
const TEXTURE_SIZE: usize = 60;
const VERTEX_COUNT: usize = 64;
const INDEX_COUNT: usize = 68;
const VERTEX: usize = 72;
const INDEX: usize = 168;

// Independent, table-based reference implementation: malformed fixtures do not
// rely on the decoder's own checksum function to become checksum-correct.
fn reference_crc(bytes: &[u8]) -> u32 {
    let mut table = [0u32; 256];
    for (n, entry) in table.iter_mut().enumerate() {
        let mut c = n as u32;
        for _ in 0..8 {
            c = if c & 1 == 1 {
                0xedb8_8320 ^ (c >> 1)
            } else {
                c >> 1
            };
        }
        *entry = c;
    }
    let mut c = !0u32;
    for byte in bytes {
        c = table[((c ^ *byte as u32) & 255) as usize] ^ (c >> 8);
    }
    !c
}

fn u32_at(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn float_at(bytes: &mut [u8], offset: usize, value: f32) {
    u32_at(bytes, offset, value.to_bits());
}

fn frame(payload: Vec<u8>) -> Vec<u8> {
    let mut bytes = b"VRMESH01".to_vec();
    for n in [1, payload.len() as u32, reference_crc(&payload), 0] {
        bytes.extend(n.to_le_bytes());
    }
    bytes.extend(payload);
    bytes
}

fn repair_frame(bytes: &mut [u8]) {
    u32_at(bytes, 12, (bytes.len() - HEADER) as u32);
    u32_at(bytes, 16, reference_crc(&bytes[HEADER..]));
}

fn vertex(position: [f32; 3], uv: [f32; 2]) -> Vec<u8> {
    position
        .into_iter()
        .chain([0., 0., 1.])
        .chain(uv)
        .flat_map(f32::to_le_bytes)
        .collect()
}

fn mesh(vertex_count: usize, index_count: usize, width: u32, height: u32) -> Vec<u8> {
    let mut bytes = Vec::new();
    for f in [0.25f32, 0.5, 0.75, 1., 0.125, 0.875] {
        bytes.extend(f.to_le_bytes());
    }
    let texture_size = width as usize * height as usize * 4;
    for n in [width, height, texture_size as u32] {
        bytes.extend(n.to_le_bytes());
    }
    bytes.resize(bytes.len() + texture_size, 255);
    for n in [vertex_count as u32, index_count as u32] {
        bytes.extend(n.to_le_bytes());
    }
    let vertices = [
        vertex([0., 0., 0.], [0., 0.]),
        vertex([1., 0., 0.], [1., 0.]),
        vertex([0., 1., 0.], [0., 1.]),
    ];
    for n in 0..vertex_count {
        bytes.extend(&vertices[n % 3]);
    }
    for n in 0..index_count {
        bytes.extend((n as u32 % 3).to_le_bytes());
    }
    bytes
}

fn asset(meshes: &[Vec<u8>]) -> Vec<u8> {
    let mut payload = (meshes.len() as u32).to_le_bytes().to_vec();
    for mesh in meshes {
        payload.extend(mesh);
    }
    frame(payload)
}

fn fixture() -> Vec<u8> {
    asset(&[mesh(3, 3, 0, 0)])
}

fn reject(bytes: &[u8], reason: &str) {
    let error = WeaponAsset::decode(bytes).expect_err("malformed asset was accepted");
    assert!(
        error.to_string().contains(reason),
        "expected {reason:?}, got {error}"
    );
}

fn mutate_u32(offset: usize, value: u32, reason: &str) {
    let mut bytes = fixture();
    u32_at(&mut bytes, offset, value);
    repair_frame(&mut bytes);
    reject(&bytes, reason);
}

#[test]
fn deterministic_fixture_preserves_every_field() {
    let bytes = fixture();
    assert_eq!(bytes.len(), 180);
    assert_eq!(bytes, fixture());
    assert_eq!(&bytes[..8], b"VRMESH01");
    assert_eq!(u32::from_le_bytes(bytes[12..16].try_into().unwrap()), 156);
    // Independently checked with Python's struct.pack and zlib.crc32.
    assert_eq!(
        u32::from_le_bytes(bytes[16..20].try_into().unwrap()),
        0xbdc1_4178
    );
    let decoded = WeaponAsset::decode(&bytes).unwrap();
    assert_eq!(decoded.meshes.len(), 1);
    let mesh = &decoded.meshes[0];
    assert_eq!(mesh.base_color, [0.25, 0.5, 0.75, 1.]);
    assert_eq!((mesh.metallic, mesh.roughness), (0.125, 0.875));
    assert_eq!((mesh.texture_width, mesh.texture_height), (0, 0));
    assert!(mesh.rgba.is_empty());
    assert_eq!(mesh.vertices.len(), 3);
    assert_eq!(mesh.vertices[0].position, [0., 0., 0.]);
    assert_eq!(mesh.vertices[1].position, [1., 0., 0.]);
    assert_eq!(mesh.vertices[2].position, [0., 1., 0.]);
    assert_eq!(mesh.vertices[0].uv, [0., 0.]);
    assert_eq!(mesh.vertices[1].uv, [1., 0.]);
    assert_eq!(mesh.vertices[2].uv, [0., 1.]);
    assert!(mesh.vertices.iter().all(|v| v.normal == [0., 0., 1.]));
    assert_eq!(mesh.indices, [0, 1, 2]);
}

#[test]
fn python_packer_fixture_matches_independent_rust_bytes_and_decodes() {
    // Generated from an original GLB by tools/test_vrpack.py. The Python suite
    // separately regenerates it and checks that the committed bytes are exact.
    let packed = include_bytes!("fixtures/triangle.vrm");
    let mut expected = fixture();
    for (i, factor) in [0.2, 0.4, 0.8, 1., 0.1, 0.7].into_iter().enumerate() {
        float_at(&mut expected, MATERIAL + 4 * i, factor);
    }
    float_at(&mut expected, VERTEX, -0.5);
    float_at(&mut expected, VERTEX + 32, 0.5);
    float_at(&mut expected, VERTEX + 64 + 24, 0.5);
    repair_frame(&mut expected);
    assert_eq!(packed.as_slice(), expected);
    assert_eq!(
        u32::from_le_bytes(packed[16..20].try_into().unwrap()),
        1_855_289_482
    );
    let decoded = WeaponAsset::decode(packed).unwrap();
    assert_eq!(decoded.meshes.len(), 1);
    let mesh = &decoded.meshes[0];
    assert_eq!(mesh.base_color, [0.2, 0.4, 0.8, 1.]);
    assert_eq!((mesh.metallic, mesh.roughness), (0.1, 0.7));
    assert_eq!((mesh.texture_width, mesh.texture_height), (0, 0));
    assert!(mesh.rgba.is_empty());
    for (i, (position, uv)) in [
        ([-0.5, 0., 0.], [0., 0.]),
        ([0.5, 0., 0.], [1., 0.]),
        ([0., 1., 0.], [0.5, 1.]),
    ]
    .into_iter()
    .enumerate()
    {
        assert_eq!(mesh.vertices[i].position, position);
        assert_eq!(mesh.vertices[i].normal, [0., 0., 1.]);
        assert_eq!(mesh.vertices[i].uv, uv);
    }
    assert_eq!(mesh.indices, [0, 1, 2]);
}

#[test]
fn crc_matches_standard_vectors_and_independent_reference() {
    for (bytes, crc) in [(b"".as_slice(), 0), (b"123456789".as_slice(), 0xcbf4_3926)] {
        assert_eq!(crc32(bytes), crc);
        assert_eq!(reference_crc(bytes), crc);
    }
    let bytes: Vec<u8> = (0..=255).collect();
    assert_eq!(crc32(&bytes), 0x2905_8c73);
    assert_eq!(crc32(&fixture()), reference_crc(&fixture()));
}

#[test]
fn rejects_every_truncation_even_with_repaired_length_and_checksum() {
    let bytes = fixture();
    for end in 0..bytes.len() {
        assert!(
            WeaponAsset::decode(&bytes[..end]).is_err(),
            "accepted prefix {end}"
        );
        if end >= HEADER {
            let mut repaired = bytes[..end].to_vec();
            repair_frame(&mut repaired);
            assert!(
                WeaponAsset::decode(&repaired).is_err(),
                "accepted reframed prefix {end}"
            );
        }
    }
}

#[test]
fn detects_every_single_bit_payload_corruption() {
    let bytes = fixture();
    for offset in HEADER..bytes.len() {
        for bit in 0..8 {
            let mut corrupt = bytes.clone();
            corrupt[offset] ^= 1 << bit;
            reject(&corrupt, "checksum");
        }
    }
}

#[test]
fn rejects_invalid_headers_and_checksum_correct_trailing_data() {
    let mut bytes = fixture();
    bytes[0] ^= 1;
    reject(&bytes, "magic");
    for version in [0, 2, u32::MAX] {
        mutate_u32(8, version, "version");
    }
    for flags in [1, u32::MAX] {
        mutate_u32(20, flags, "flags");
    }
    for length in [0, 155, 157, u32::MAX] {
        let mut bytes = fixture();
        u32_at(&mut bytes, 12, length);
        reject(&bytes, "length mismatch");
    }
    let mut bytes = fixture();
    bytes.push(0);
    repair_frame(&mut bytes);
    reject(&bytes, "trailing data");
}

#[test]
fn mesh_count_is_bounded_but_256_meshes_are_valid() {
    for count in [0, 257, u32::MAX] {
        mutate_u32(HEADER, count, "mesh count");
    }
    let bytes = asset(&vec![mesh(3, 3, 0, 0); 256]);
    assert_eq!(WeaponAsset::decode(&bytes).unwrap().meshes.len(), 256);
}

#[test]
fn all_float_fields_reject_nan_and_infinity() {
    let offsets = (MATERIAL..MATERIAL + 24)
        .step_by(4)
        .chain((VERTEX..INDEX).step_by(4));
    for offset in offsets {
        for value in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
            let mut bytes = fixture();
            float_at(&mut bytes, offset, value);
            repair_frame(&mut bytes);
            reject(&bytes, "non-finite float");
        }
    }
}

#[test]
fn material_factors_have_inclusive_unit_interval_bounds() {
    for offset in (MATERIAL..MATERIAL + 24).step_by(4) {
        for value in [-0.000_001, 1.000_001] {
            let mut bytes = fixture();
            float_at(&mut bytes, offset, value);
            repair_frame(&mut bytes);
            reject(&bytes, "material factors");
        }
        for value in [0., -0., 1.] {
            let mut bytes = fixture();
            float_at(&mut bytes, offset, value);
            repair_frame(&mut bytes);
            WeaponAsset::decode(&bytes).unwrap();
        }
    }
}

#[test]
fn position_and_uv_bounds_are_inclusive_and_symmetric() {
    for (offset, limit) in [(VERTEX, 10_000f32), (VERTEX + 24, 1_000_000f32)] {
        for sign in [-1., 1.] {
            let mut bytes = fixture();
            float_at(&mut bytes, offset, sign * limit);
            repair_frame(&mut bytes);
            WeaponAsset::decode(&bytes).unwrap();
            float_at(
                &mut bytes,
                offset,
                sign * f32::from_bits(limit.to_bits() + 1),
            );
            repair_frame(&mut bytes);
            reject(&bytes, "coordinates exceed bounds");
        }
    }
}

#[test]
fn normals_must_be_near_unit_length_including_overflow_cases() {
    for z in [0., 0.989, 1.011, 2., f32::MAX] {
        let mut bytes = fixture();
        float_at(&mut bytes, VERTEX + 20, z);
        repair_frame(&mut bytes);
        reject(&bytes, "normal is not unit length");
    }
    for z in [-1., 0.99, 1., 1.009] {
        let mut bytes = fixture();
        float_at(&mut bytes, VERTEX + 20, z);
        repair_frame(&mut bytes);
        WeaponAsset::decode(&bytes).unwrap();
    }
}

#[test]
fn texture_byte_length_and_dimensions_must_agree() {
    for (width, height, size) in [
        (0, 0, 4),
        (1, 0, 0),
        (0, 1, 0),
        (1, 1, 0),
        (0, 1, 4),
        (1, 1, 3),
        (1, 1, 5),
    ] {
        let mut bytes = fixture();
        for (offset, value) in [(WIDTH, width), (HEIGHT, height), (TEXTURE_SIZE, size)] {
            u32_at(&mut bytes, offset, value);
        }
        repair_frame(&mut bytes);
        reject(&bytes, "invalid RGBA dimensions");
    }
    for offset in [WIDTH, HEIGHT] {
        for dimension in [2049, u32::MAX] {
            mutate_u32(offset, dimension, "dimensions exceed 2048");
        }
    }
    let mut bytes = asset(&[mesh(3, 3, 2, 1)]);
    bytes[64..72].copy_from_slice(&[255, 0, 0, 255, 0, 128, 255, 32]);
    repair_frame(&mut bytes);
    let decoded = WeaponAsset::decode(&bytes).unwrap();
    let mesh = &decoded.meshes[0];
    assert_eq!((mesh.texture_width, mesh.texture_height), (2, 1));
    assert_eq!(mesh.rgba, [255, 0, 0, 255, 0, 128, 255, 32]);
    assert_eq!(mesh.indices, [0, 1, 2]);
}

#[test]
fn truncated_texture_is_rejected_before_reading_geometry() {
    let mut bytes = asset(&[mesh(3, 3, 2, 1)]);
    bytes.truncate(71);
    repair_frame(&mut bytes);
    reject(&bytes, "truncated asset");
}

#[test]
fn rejects_invalid_geometry_counts_before_allocating_records() {
    for count in [0, MAX_VERTICES as u32 + 1, u32::MAX] {
        mutate_u32(VERTEX_COUNT, count, "invalid vertex or triangle count");
    }
    for count in [0, 1, 2, 4, MAX_INDICES as u32 + 3, u32::MAX] {
        mutate_u32(INDEX_COUNT, count, "invalid vertex or triangle count");
    }
    mutate_u32(VERTEX_COUNT, MAX_VERTICES as u32, "truncated geometry");
    mutate_u32(INDEX_COUNT, MAX_INDICES as u32, "truncated geometry");
}

#[test]
fn all_triangle_indices_are_checked() {
    for offset in [INDEX, INDEX + 4, INDEX + 8] {
        for index in [3, u32::MAX] {
            mutate_u32(offset, index, "index outside vertex array");
        }
    }
}

#[test]
fn aggregate_vertex_budget_cannot_be_bypassed_with_multiple_meshes() {
    let mut payload = 2u32.to_le_bytes().to_vec();
    payload.extend(mesh(MAX_VERTICES, 3, 0, 0));
    // A second individually valid record advertises three vertices. No second
    // vertex storage is needed: the aggregate limit must be checked first.
    payload.extend(&mesh(3, 3, 0, 0)[..44]);
    reject(&frame(payload), "aggregate geometry budget");
}

#[test]
fn aggregate_index_budget_cannot_be_bypassed_with_multiple_meshes() {
    let mut payload = 2u32.to_le_bytes().to_vec();
    payload.extend(mesh(3, MAX_INDICES, 0, 0));
    payload.extend(&mesh(3, 3, 0, 0)[..44]);
    reject(&frame(payload), "aggregate geometry budget");
}

#[test]
fn aggregate_texture_budget_cannot_be_bypassed_with_multiple_meshes() {
    assert_eq!(4 * 2048 * 2048 * 4, MAX_TEXTURE_BYTES);
    let mut payload = 5u32.to_le_bytes().to_vec();
    for _ in 0..4 {
        payload.extend(mesh(3, 3, 2048, 2048));
    }
    // Four maximum-size textures are legal. The fifth mesh must be rejected
    // before taking its absent RGBA bytes or geometry.
    payload.extend(&mesh(3, 3, 1, 1)[..36]);
    reject(&frame(payload), "aggregate texture budget");
}

#[test]
fn file_budget_is_checked_before_parsing() {
    reject(&vec![0; MAX_FILE + 1], "asset exceeds 128 MiB");
}

#[test]
fn checksum_correct_deterministic_mutations_never_panic() {
    let mut state = 0x5a73_093du32;
    for _ in 0..2048 {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        let mut bytes = fixture();
        let offset = HEADER + state as usize % (bytes.len() - HEADER);
        bytes[offset] ^= (state >> 24) as u8 | 1;
        repair_frame(&mut bytes);
        // Mutations may still describe a valid asset, but must never panic.
        let _ = WeaponAsset::decode(&bytes);
    }
}

struct TempDir(PathBuf);
impl TempDir {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "vector-range-asset-contract-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn load_validates_file_contents_and_reports_io_errors() {
    let temp = TempDir::new();
    let file = temp.0.join("original.vrm");
    assert!(WeaponAsset::load(&file).is_err());
    fs::write(&file, fixture()).unwrap();
    assert_eq!(
        WeaponAsset::load(&file).unwrap().meshes[0].indices,
        [0, 1, 2]
    );
    fs::write(&file, b"not an asset").unwrap();
    assert!(WeaponAsset::load(&file).is_err());
}

fn build_command(executable: &Path, out: &Path, asset: Option<&Path>, ci: bool) -> Output {
    let mut command = Command::new(executable);
    command
        .current_dir(out.parent().unwrap())
        .env("OUT_DIR", out)
        .env_remove("VR_WEAPON_ASSET")
        .env_remove("CI");
    if let Some(asset) = asset {
        command.env("VR_WEAPON_ASSET", asset);
    }
    if ci {
        command.env("CI", "true");
    }
    command.output().unwrap()
}

#[test]
fn build_script_checks_default_override_ci_and_stale_data_contracts() {
    let temp = TempDir::new();
    let executable = temp
        .0
        .join(format!("asset-build{}", std::env::consts::EXE_SUFFIX));
    let out = temp.0.join("out");
    fs::create_dir(&out).unwrap();
    let compiler = std::env::var_os("RUSTC").unwrap_or_else(|| "rustc".into());
    let compiled = Command::new(compiler)
        .args(["--edition=2021", "--crate-name", "asset_contract_build"])
        .arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("build.rs"))
        .arg("-o")
        .arg(&executable)
        .output()
        .unwrap();
    assert!(
        compiled.status.success(),
        "{}",
        String::from_utf8_lossy(&compiled.stderr)
    );
    let source = temp.0.join("original.vrm");
    fs::write(&source, fixture()).unwrap();
    let result = build_command(&executable, &out, Some(&source), false);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_eq!(fs::read(out.join("weapon.vrm")).unwrap(), fixture());
    let generated = fs::read_to_string(out.join("weapon_embed.rs")).unwrap();
    assert!(generated.contains("Some(include_bytes!"));
    assert!(String::from_utf8_lossy(&result.stdout)
        .contains(&format!("cargo:rerun-if-changed={}", source.display())));

    // Only the explicitly named, approved default is eligible for public CI.
    // Work in a temporary CWD so no actual model is needed for this contract.
    let default = temp.0.join("assets/weapons/hk416a5.vrm");
    fs::create_dir_all(default.parent().unwrap()).unwrap();
    let mut default_bytes = fixture();
    float_at(&mut default_bytes, MATERIAL, 0.625);
    repair_frame(&mut default_bytes);
    fs::write(&default, &default_bytes).unwrap();
    let approved = build_command(&executable, &out, None, true);
    assert!(
        approved.status.success(),
        "{}",
        String::from_utf8_lossy(&approved.stderr)
    );
    assert_eq!(fs::read(out.join("weapon.vrm")).unwrap(), default_bytes);
    let overridden = build_command(&executable, &out, Some(&source), false);
    assert!(overridden.status.success());
    assert_eq!(fs::read(out.join("weapon.vrm")).unwrap(), fixture());

    let ci = build_command(&executable, &out, Some(&source), true);
    assert!(!ci.status.success());
    assert!(String::from_utf8_lossy(&ci.stderr).contains("prohibited in CI"));
    let relative = build_command(&executable, &out, Some(Path::new("original.vrm")), false);
    assert!(!relative.status.success());
    assert!(String::from_utf8_lossy(&relative.stderr).contains("absolute local"));
    fs::write(&source, b"malformed").unwrap();
    let invalid = build_command(&executable, &out, Some(&source), false);
    assert!(!invalid.status.success());

    fs::write(&default, b"malformed default").unwrap();
    let invalid_default = build_command(&executable, &out, None, true);
    assert!(!invalid_default.status.success());
    fs::remove_file(default).unwrap();

    let fallback = build_command(&executable, &out, None, true);
    assert!(fallback.status.success());
    assert!(!out.join("weapon.vrm").exists());
    assert!(fs::read_to_string(out.join("weapon_embed.rs"))
        .unwrap()
        .contains("= None;"));
}

#[test]
fn configured_embedded_asset_is_decodable() {
    if let Some(bytes) = vector_range::EMBEDDED_WEAPON {
        WeaponAsset::decode(bytes).expect("build embedded an invalid asset");
    }
}
