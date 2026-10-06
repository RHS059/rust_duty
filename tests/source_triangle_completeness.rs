//! Original-fixture batching proof, not an authored-capture acceptance gate.
//!
//! The expected mesh/triangle inventory comes from public decoders before either
//! production adapter is constructed. Exact integer UV tokens carry the original
//! mesh and vertex identities through the real adapters without adding runtime
//! metadata. No candidate draw contributes to the expected inventory.
//! This proves the exercised constructors/batching preserve these fixtures. It
//! does not bind real companion assets, evaluated poses or native GPU submission.
//! Intact identity tokens do not certify positions, transforms or materials.
//! Encounter ordinals cannot distinguish two identical repeated source triples;
//! this fixture also does not exercise source vertex indices above 65,535.
//! Negative controls mutate recorded draws to test the comparator, not the
//! production partition functions. No screenshot or raster proof is claimed.
#![allow(dead_code)]

#[path = "../src/authored_viewmodel.rs"]
mod authored_viewmodel;
#[path = "../src/weapon_model.rs"]
mod weapon_model;

use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};
use vector_range::{
    asset::WeaponAsset,
    draw::{facade::*, Command},
    scene_lighting::SceneLighting,
    skinned_asset::{crc32, SkinnedAsset},
    viewmodel_animation::AnimationSet,
};

const MESHES: usize = 2;
const VERTICES: u32 = 10_002;
const SKIN: u32 = 10;
const RIGID: u32 = 20;

fn words(out: &mut Vec<u8>, values: &[u32]) {
    out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
}
fn floats(out: &mut Vec<u8>, values: &[f32]) {
    out.extend(values.iter().flat_map(|v| v.to_le_bytes()));
}
fn name(out: &mut Vec<u8>, value: &str) {
    out.extend((value.len() as u16).to_le_bytes());
    out.extend(value.as_bytes());
}
fn container(magic: &[u8; 8], version: u32, payload: Vec<u8>) -> Vec<u8> {
    let mut out = magic.to_vec();
    words(
        &mut out,
        &[version, payload.len() as u32, crc32(&payload), 0],
    );
    out.extend(payload);
    out
}

fn mesh_payload(out: &mut Vec<u8>, kind: u32) {
    words(out, &[MESHES as u32]);
    for mesh in 0..MESHES {
        floats(out, &[0.8, 0.6, 0.4, 1., 0., 1.]);
        words(out, &[0, 0, 0, VERTICES, VERTICES]);
        for vertex in 0..VERTICES {
            // All token values are exactly representable f32 integers. Geometry
            // is deliberately ordinary: identity lives in UV, not its position.
            floats(
                out,
                &[
                    if vertex % 3 == 1 { 0.01 } else { 0. },
                    (vertex / 3) as f32 * 0.0001 + if vertex % 3 == 2 { 0.01 } else { 0. },
                    -1.,
                    0.,
                    0.,
                    1.,
                    vertex as f32,
                    (kind + mesh as u32) as f32,
                ],
            );
            if kind == SKIN {
                out.extend([0_u8; 16]); // Eight u16 bone indices.
                floats(out, &[1., 0., 0., 0., 0., 0., 0., 0.]);
            }
        }
        // Two equal full batches, then shared/reordered vertices in the tail.
        // Expected values below are decoded from these bytes, not this loop.
        words(out, &(0..VERTICES - 6).collect::<Vec<_>>());
        words(out, &[0, 2, 1, 0, 1, 2]);
    }
}

struct Fixture {
    directory: PathBuf,
    vrs: Vec<u8>,
    vrm: Vec<u8>,
    vra: Vec<u8>,
}
impl Fixture {
    fn new(visible: [bool; MESHES]) -> Self {
        static SERIAL: AtomicUsize = AtomicUsize::new(0);
        let directory = std::env::temp_dir().join(format!(
            "rust-duty-triangle-completeness-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&directory).unwrap();
        let identity = Mat4::IDENTITY.to_cols_array();
        let mut skin = Vec::new();
        words(&mut skin, &[1]);
        name(&mut skin, "fixture_bone");
        words(&mut skin, &[u32::MAX]);
        floats(&mut skin, &identity);
        floats(&mut skin, &identity);
        mesh_payload(&mut skin, SKIN);
        let vrs = container(b"VRSKIN02", 2, skin);
        let mut rigid = Vec::new();
        mesh_payload(&mut rigid, RIGID);
        let vrm = container(b"VRMESH01", 1, rigid);
        let mut animation = Vec::new();
        words(&mut animation, &[crc32(&vrs), crc32(&vrm), 1]);
        name(&mut animation, "fixture_bone");
        words(&mut animation, &[u32::MAX, MESHES as u32]);
        for mesh in 0..MESHES {
            name(&mut animation, &format!("fixture_actor_{mesh}"));
            words(&mut animation, &[1, mesh as u32]);
            floats(&mut animation, &identity);
        }
        words(&mut animation, &[1]);
        name(&mut animation, "complete");
        words(&mut animation, &[0, 1]);
        floats(&mut animation, &[0.]);
        for _ in 0..=MESHES {
            floats(&mut animation, &[0., 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
        }
        animation.extend(visible.map(u8::from));
        let vra = container(b"VRANIM01", 1, animation);
        for (extension, bytes) in [("vrs", &vrs), ("vrm", &vrm), ("vra", &vra)] {
            fs::write(directory.join(format!("fixture.{extension}")), bytes).unwrap();
        }
        Self {
            directory,
            vrs,
            vrm,
            vra,
        }
    }

    fn source_inventory(&self) -> Vec<Triangle> {
        let skin = SkinnedAsset::decode(&self.vrs).unwrap();
        let rigid = WeaponAsset::decode(&self.vrm).unwrap();
        let animation = AnimationSet::decode(&self.vra).unwrap();
        animation
            .validate_companions(&self.vrs, &self.vrm, &skin.bones, rigid.meshes.len())
            .unwrap();
        let pose = animation.sample_clamped("complete", 0.).unwrap();
        let mut visible = vec![false; rigid.meshes.len()];
        for (actor, is_visible) in animation.actors().iter().zip(pose.actor_visible) {
            for &mesh in &actor.mesh_indices {
                visible[mesh] = is_visible;
            }
        }
        let mut expected = Vec::new();
        for (mesh, source) in skin.meshes.iter().enumerate() {
            append_inventory(&mut expected, SKIN + mesh as u32, &source.indices);
        }
        for (mesh, source) in rigid
            .meshes
            .iter()
            .enumerate()
            .filter(|(mesh, _)| visible[*mesh])
        {
            append_inventory(&mut expected, RIGID + mesh as u32, &source.indices);
        }
        expected
    }

    fn draw(&self) -> Vec<Mesh> {
        let mut model = authored_viewmodel::AuthoredViewmodel::load(
            self.directory.join("fixture.vra").to_str().unwrap(),
            "complete",
            Some(0.),
        )
        .unwrap();
        model.set_cant(0.17);
        begin_frame(960, 540, 1.).unwrap();
        model.draw(
            0.,
            SceneLighting::range(),
            Mat4::from_translation(vec3(0.2, -0.2, 0.2)),
        );
        assert!(model.error().is_none(), "{:?}", model.error());
        take_draw_list()
            .unwrap()
            .commands
            .into_iter()
            .filter_map(|command| {
                if let Command::Mesh { mesh, .. } = command {
                    Some(mesh)
                } else {
                    None
                }
            })
            .collect()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Triangle {
    mesh: u32,
    ordinal: usize,
    indices: [u32; 3],
}
fn append_inventory(out: &mut Vec<Triangle>, mesh: u32, indices: &[u32]) {
    assert!(indices.len().is_multiple_of(3));
    out.extend(
        indices
            .as_chunks::<3>()
            .0
            .iter()
            .enumerate()
            .map(|(ordinal, indices)| Triangle {
                mesh,
                ordinal,
                indices: *indices,
            }),
    );
}
fn token(value: f32) -> Result<u32, String> {
    if !value.is_finite() || value < 0. || value.fract() != 0. || value > 1_000_000. {
        return Err("source identity token was changed".into());
    }
    Ok(value as u32)
}
fn actual_inventory(batches: &[Mesh]) -> Result<Vec<Triangle>, String> {
    let mut result = Vec::new();
    let mut ordinals = std::collections::BTreeMap::<u32, usize>::new();
    for batch in batches {
        batch.validate()?;
        for indices in batch.indices.as_chunks::<3>().0.iter() {
            let vertices: Vec<_> = indices
                .iter()
                .map(|&i| &batch.vertices[i as usize])
                .collect();
            let mesh = token(vertices[0].uv.y)?;
            if vertices.iter().any(|v| token(v.uv.y) != Ok(mesh)) {
                return Err("triangle mixes source mesh identities".into());
            }
            let mut source = [0; 3];
            for (out, vertex) in source.iter_mut().zip(vertices) {
                *out = token(vertex.uv.x)?;
            }
            let ordinal = ordinals.entry(mesh).or_default();
            result.push(Triangle {
                mesh,
                ordinal: *ordinal,
                indices: source,
            });
            *ordinal += 1;
        }
    }
    Ok(result)
}
fn verify_inventory(expected: &[Triangle], batches: &[Mesh]) -> Result<(), String> {
    let actual = actual_inventory(batches)?;
    if actual.len() != expected.len() {
        return Err(format!(
            "source triangle count differs: {} != {}",
            actual.len(),
            expected.len()
        ));
    }
    if let Some((at, (wanted, got))) = expected
        .iter()
        .zip(&actual)
        .enumerate()
        .find(|(_, (a, b))| a != b)
    {
        return Err(format!(
            "source triangle identity differs at {at}: {got:?} != {wanted:?}"
        ));
    }
    Ok(())
}

#[test]
fn source_triangle_completeness_preserves_decoded_inventory_through_skin_and_rigid_batches() {
    let fixture = Fixture::new([true, true]);
    let expected = fixture.source_inventory(); // Must be established before the candidate adapter.
    let batches = fixture.draw();
    assert_eq!(
        batches.len(),
        12,
        "four source meshes, each with two full batches and tail"
    );
    assert_eq!(expected.len(), 4 * VERTICES as usize / 3);
    assert_eq!(verify_inventory(&expected, &batches), Ok(()));
    assert_eq!(
        batches.iter().map(|b| b.indices.len()).collect::<Vec<_>>(),
        [4998, 4998, 6].repeat(4)
    );
}

#[test]
fn source_triangle_completeness_uses_source_actor_visibility_without_erasing_skin() {
    let fixture = Fixture::new([false, true]);
    let expected = fixture.source_inventory();
    let batches = fixture.draw();
    assert_eq!(batches.len(), 9);
    assert!(expected.iter().any(|t| t.mesh == SKIN));
    assert!(expected.iter().all(|t| t.mesh != RIGID));
    assert_eq!(verify_inventory(&expected, &batches), Ok(()));
}

#[test]
fn source_triangle_completeness_rejects_same_count_mesh_delete_duplicate_for_both_kinds() {
    let fixture = Fixture::new([true, true]);
    let expected = fixture.source_inventory();
    let original = fixture.draw();
    for first in [0, 6] {
        let mut changed = original.clone();
        for batch in 0..3 {
            changed[first + 3 + batch] = original[first + batch].clone();
        }
        assert_eq!(actual_inventory(&changed).unwrap().len(), expected.len());
        let error = verify_inventory(&expected, &changed).unwrap_err();
        assert!(
            error.contains("source triangle identity differs"),
            "{error}"
        );
        eprintln!("same-count mesh delete/duplicate at batch {first} rejected: {error}");
    }
}

#[test]
fn source_triangle_completeness_rejects_same_count_batch_delete_duplicate_for_every_mesh() {
    let fixture = Fixture::new([true, true]);
    let expected = fixture.source_inventory();
    let original = fixture.draw();
    for first in [0, 3, 6, 9] {
        let mut changed = original.clone();
        changed[first + 1] = original[first].clone();
        assert_eq!(actual_inventory(&changed).unwrap().len(), expected.len());
        let error = verify_inventory(&expected, &changed).unwrap_err();
        assert!(
            error.contains("source triangle identity differs"),
            "{error}"
        );
        eprintln!("same-count batch delete/duplicate at batch {first} rejected: {error}");
    }
}

#[test]
fn source_triangle_completeness_rejects_tail_omission_reordering_and_changed_identity() {
    let fixture = Fixture::new([true, true]);
    let expected = fixture.source_inventory();
    let original = fixture.draw();
    let mut missing = original.clone();
    missing.remove(2);
    assert!(verify_inventory(&expected, &missing)
        .unwrap_err()
        .contains("count differs"));
    let mut reordered = original.clone();
    reordered[0].indices.swap(0, 1);
    assert!(verify_inventory(&expected, &reordered)
        .unwrap_err()
        .contains("identity differs"));
    let mut duplicate_triangle = original.clone();
    let copied = duplicate_triangle[0].indices[..3].to_vec();
    duplicate_triangle[0].indices[3..6].copy_from_slice(&copied);
    assert_eq!(
        actual_inventory(&duplicate_triangle).unwrap().len(),
        expected.len()
    );
    assert!(verify_inventory(&expected, &duplicate_triangle)
        .unwrap_err()
        .contains("identity differs"));
    let mut bad_index = original.clone();
    bad_index[0].indices[0] = u16::MAX;
    assert!(verify_inventory(&expected, &bad_index)
        .unwrap_err()
        .contains("index out of range"));
    let mut invalid = original;
    invalid[0].vertices[0].uv.x = 0.5;
    assert!(verify_inventory(&expected, &invalid)
        .unwrap_err()
        .contains("token was changed"));
}
