//! CPU draw adapter for the authorized test model and optional local overrides.
use vector_range::draw::facade::*;
use vector_range::{
    asset::{AssetVertex, WeaponAsset},
    scene_lighting::SceneLighting,
};

use vector_range::draw::resident::{ResidentDraw, ResidentMesh, RigidVertex, Vertices};

pub struct WeaponModel {
    meshes: Vec<(usize, Mesh, Color)>,
    resident_meshes: Vec<ResidentBatch>,
    hk416_rig: bool,
    pub muzzle: Vec3,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ResidentBatching {
    LegacyChunks,
    CoalescedParts,
}

/// Read-only source layout for the separately bound coalescing contract.
/// Original chunk/part membership is retained independently of draw attributes.
#[allow(dead_code)]
pub(crate) struct ResidentSourceGroup {
    pub model_key: String,
    pub kind: &'static str,
    pub source_chunks: usize,
    pub sources: std::ops::Range<usize>,
    pub source_parts: Vec<usize>,
    pub mesh: Option<ResidentMesh>,
}

impl WeaponModel {
    pub fn from_asset(asset: WeaponAsset) -> Self {
        Self::from_asset_with_batching(asset, ResidentBatching::LegacyChunks)
    }

    pub(crate) fn from_asset_with_batching(asset: WeaponAsset, batching: ResidentBatching) -> Self {
        let hk416_rig = asset.payload_crc32 == 0xfc786964;
        let front = asset
            .meshes
            .iter()
            .flat_map(|m| &m.vertices)
            .map(|v| v.position[2])
            .fold(f32::INFINITY, f32::min);
        let mut low = Vec3::splat(f32::INFINITY);
        let mut high = Vec3::splat(f32::NEG_INFINITY);
        for vertex in asset
            .meshes
            .iter()
            .flat_map(|m| &m.vertices)
            .filter(|v| v.position[2] <= front + 0.005)
        {
            let p = Vec3::from_array(vertex.position);
            low = low.min(p);
            high = high.max(p);
        }
        let muzzle = vec3((low.x + high.x) * 0.5, (low.y + high.y) * 0.5, front - 0.01);
        let mut meshes = Vec::new();
        for (part_index, part) in asset.meshes.into_iter().enumerate() {
            let texture = if part.rgba.is_empty() {
                None
            } else {
                let mut opaque_rgba = part.rgba.clone();
                for alpha in opaque_rgba.iter_mut().skip(3).step_by(4) {
                    *alpha = 255;
                }
                let texture = Texture::rgba8(
                    part.texture_width,
                    part.texture_height,
                    &opaque_rgba,
                    Sampler {
                        filter: FilterMode::Linear,
                        wrap_x: WrapMode::Repeat,
                        wrap_y: WrapMode::Repeat,
                    },
                )
                .expect("validated weapon asset texture must match its RGBA8 extent");
                Some(texture)
            };
            // Keep the established u16 batches, splitting triangle lists
            // without index truncation or dropped triangles.
            for (source_vertices, indices) in partition_triangles(&part.indices, |index| {
                rigid_vertex_key(&part.vertices[index as usize])
            }) {
                let vertices = source_vertices
                    .iter()
                    .map(|&index| {
                        let v = &part.vertices[index as usize];
                        let normal = Vec3::from_array(v.normal);
                        let mut vertex = Vertex::new2(
                            Vec3::from_array(v.position),
                            Vec2::from_array(v.uv),
                            Color::new(
                                part.base_color[0],
                                part.base_color[1],
                                part.base_color[2],
                                1.,
                            ),
                        );
                        vertex.normal = normal.extend(0.);
                        vertex
                    })
                    .collect::<Vec<_>>();
                meshes.push((
                    part_index,
                    Mesh {
                        vertices,
                        indices,
                        texture: texture.clone(),
                    },
                    Color::new(
                        part.base_color[0],
                        part.base_color[1],
                        part.base_color[2],
                        1.,
                    ),
                ));
            }
        }
        let resident_meshes = coalesce_resident_batches(
            meshes
                .iter()
                .map(|(part, mesh, _)| {
                    (
                        *part,
                        ResidentMesh::new(
                            Vertices::Rigid(
                                mesh.vertices
                                    .iter()
                                    .map(|v| RigidVertex {
                                        position: v.position.to_array(),
                                        uv: v.uv.to_array(),
                                        normal: v.normal.truncate().to_array(),
                                    })
                                    .collect(),
                            ),
                            mesh.indices.clone(),
                            mesh.texture.clone(),
                        )
                        .ok(),
                    )
                })
                .collect(),
            batching,
        );
        Self {
            meshes,
            resident_meshes,
            muzzle,
            hk416_rig,
        }
    }
    #[allow(dead_code)]
    pub(crate) fn resident_source_groups(&self, prefix: &str) -> Vec<ResidentSourceGroup> {
        self.resident_meshes
            .iter()
            .map(|batch| ResidentSourceGroup {
                model_key: prefix.to_owned(),
                kind: "rigid",
                source_chunks: self.meshes.len(),
                sources: batch.sources.clone(),
                source_parts: self
                    .meshes
                    .get(batch.sources.clone())
                    .unwrap_or(&[])
                    .iter()
                    .map(|(part, _, _)| *part)
                    .collect(),
                mesh: batch.mesh.clone(),
            })
            .collect()
    }

    /// Draw exact exported actor transforms. This opt-in path never uses the
    /// legacy weapon CRC, magazine indices, bolt offsets, or procedural pose.
    pub fn draw_authored_parts(
        &mut self,
        transforms: &[Mat4],
        visible: &[bool],
        opacity: &[f32],
        lighting: SceneLighting,
    ) {
        for batch in &self.resident_meshes {
            let (part, _, albedo) = &self.meshes[batch.sources.start];
            if visible.get(*part).copied().unwrap_or(false) {
                if let Some(&matrix) = transforms.get(*part) {
                    let alpha = opacity.get(*part).copied().unwrap_or(1.).clamp(0., 1.);
                    if resident_meshes_enabled() {
                        if let Some(resident) = &batch.mesh {
                            if let Ok(draw) = ResidentDraw::new(
                                resident.clone(),
                                matrix,
                                lighting,
                                *albedo,
                                alpha,
                                None,
                            ) {
                                draw_resident(draw, BlendMode::Alpha);
                                continue;
                            }
                        }
                    }
                    // Failure falls back for this entire group, before any of
                    // its triangles were submitted. Keep legacy chunk order.
                    for (_, mesh, albedo) in &mut self.meshes[batch.sources.clone()] {
                        lighting.shade_rigid(mesh, *albedo, matrix);
                        for vertex in &mut mesh.vertices {
                            vertex.color[3] = (alpha * 255.).round() as u8;
                        }
                        draw_mesh_transformed(mesh, matrix, BlendMode::Alpha);
                    }
                }
            }
        }
    }

    pub fn draw_pose_with_free_frame(
        &mut self,
        pose: Mat4,
        held_magazine_matrix: Mat4,
        animation: &vector_range::weapon_animation::WeaponAnimationPose,
        lighting: SceneLighting,
    ) {
        let draw = |mesh: &mut Mesh, albedo: Color, root: Mat4, local: Mat4| {
            lighting.shade_rigid(mesh, albedo, root * local);
            draw_mesh_transformed(mesh, root * local, BlendMode::Alpha);
        };
        for (part, mesh, albedo) in &mut self.meshes {
            if self.hk416_rig && (22..=25).contains(part) {
                let transforms = [
                    (
                        animation.seated_magazine_translation,
                        animation.seated_magazine_euler_yxz,
                        animation.seated_magazine_orientation_xyzw,
                    ),
                    (
                        animation.magazine_translation,
                        animation.magazine_euler_yxz,
                        animation.magazine_orientation_xyzw,
                    ),
                ];
                for (i, (offset, rotation, orientation)) in transforms.into_iter().enumerate() {
                    if animation.magazine_visibility[i] {
                        if i == 1 {
                            draw(mesh, *albedo, held_magazine_matrix, Mat4::IDENTITY);
                            continue;
                        }
                        let local = if let Some(q) = orientation {
                            vector_range::view_animation::magazine_frame_with_orientation(
                                Mat4::IDENTITY,
                                Vec3::from_array(offset),
                                Quat::from_array(q),
                            )
                        } else {
                            vector_range::view_animation::magazine_frame(
                                Mat4::IDENTITY,
                                Vec3::from_array(offset),
                                Vec3::from_array(rotation),
                            )
                        };
                        draw(mesh, *albedo, pose, local);
                    }
                }
            } else {
                let local = if self.hk416_rig && *part == 5 {
                    Mat4::from_translation(Vec3::from_array(animation.bolt_translation))
                } else {
                    Mat4::IDENTITY
                };
                draw(mesh, *albedo, pose, local);
            }
        }
    }
}

pub(crate) struct ResidentBatch {
    pub sources: std::ops::Range<usize>,
    pub mesh: Option<ResidentMesh>,
}

// Input order is draw order. Part identity retains actor/material/pose ownership;
// geometry concatenation separately validates texture, vertex kind and bones.
// Never deduplicate across old chunks, reorder triangles or change their cap.
pub(crate) fn coalesce_resident_batches(
    chunks: Vec<(usize, Option<ResidentMesh>)>,
    batching: ResidentBatching,
) -> Vec<ResidentBatch> {
    let mut batches = Vec::new();
    let mut start = 0;
    while start < chunks.len() {
        let (part, first) = &chunks[start];
        let mut end = start + 1;
        if batching == ResidentBatching::CoalescedParts {
            if let Some(first) = first {
                let mut vertices = first.vertex_count();
                let mut indices = first.indices().len();
                while let Some((next_part, Some(next))) = chunks.get(end) {
                    if next_part != part
                        || vertices + next.vertex_count() > u16::MAX as usize + 1
                        || indices + next.indices().len() > u16::MAX as usize
                    {
                        break;
                    }
                    vertices += next.vertex_count();
                    indices += next.indices().len();
                    end += 1;
                }
            }
        }
        let meshes: Option<Vec<_>> = chunks[start..end]
            .iter()
            .map(|(_, mesh)| mesh.clone())
            .collect();
        batches.push(ResidentBatch {
            sources: start..end,
            mesh: meshes.and_then(|meshes| ResidentMesh::coalesce(&meshes).ok()),
        });
        start = end;
    }
    batches
}

// Preserve every source float bit, including signed zero. Material/texture and
// actor identity are kept outside this key: each part is partitioned separately.
fn rigid_vertex_key(vertex: &AssetVertex) -> [u32; 8] {
    let [x, y, z] = vertex.position;
    let [nx, ny, nz] = vertex.normal;
    let [u, v] = vertex.uv;
    [x, y, z, nx, ny, nz, u, v].map(f32::to_bits)
}

// Keep original triangle order and 4,998-index boundaries. First occurrence
// wins within each chunk; HashMap iteration order never determines output.
// Callers use complete immutable source-vertex keys after asset validation.
// No vertices are merged across chunks, materials, actors or pose providers.
pub(crate) fn partition_triangles<K: Eq + std::hash::Hash>(
    indices: &[u32],
    vertex_key: impl Fn(u32) -> K,
) -> Vec<(Vec<u32>, Vec<u16>)> {
    indices
        .chunks(4_998)
        .map(|chunk| {
            let mut map = std::collections::HashMap::new();
            let mut sources = Vec::new();
            let local = chunk
                .iter()
                .map(|&source| {
                    *map.entry(vertex_key(source)).or_insert_with(|| {
                        let index = sources.len() as u16;
                        sources.push(source);
                        index
                    })
                })
                .collect();
            (sources, local)
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resident_groups_keep_parts_bounds_and_invalid_fallback_ranges() {
        let source = |count| {
            ResidentMesh::new(
                Vertices::Rigid(vec![
                    RigidVertex {
                        position: [0.; 3],
                        uv: [0.; 2],
                        normal: [0., 0., 1.],
                    };
                    3
                ]),
                vec![0; count],
                None,
            )
            .unwrap()
        };
        let mut chunks = vec![(0, Some(source(4_998))); 14];
        chunks.extend([
            (1, Some(source(3))),
            (1, None),
            (1, Some(source(3))),
            (0, Some(source(3))),
        ]);
        let groups = coalesce_resident_batches(chunks, ResidentBatching::CoalescedParts);
        assert_eq!(
            groups.iter().map(|g| g.sources.clone()).collect::<Vec<_>>(),
            [0..13, 13..14, 14..15, 15..16, 16..17, 17..18]
        );
        assert_eq!(groups[0].mesh.as_ref().unwrap().indices().len(), 64_974);
        assert_eq!(groups[0].mesh.as_ref().unwrap().vertex_count(), 39);
        assert!(groups[3].mesh.is_none());
    }

    #[test]
    fn resident_rigid_groups_preserve_legacy_chunks_and_part_materials() {
        let mut asset = textured_asset();
        asset.meshes[0].indices = [0, 1, 2].repeat(4_000);
        let mut second = asset.meshes[0].clone();
        second.base_color = [0.25, 0.5, 0.75, 1.];
        asset.meshes.push(second);
        let legacy = WeaponModel::from_asset(asset.clone());
        assert_eq!(legacy.resident_meshes.len(), 6);
        let model = WeaponModel::from_asset_with_batching(asset, ResidentBatching::CoalescedParts);
        assert_eq!(model.meshes.len(), 6);
        assert_eq!(model.resident_meshes.len(), 2);
        for (part, group) in model.resident_meshes.iter().enumerate() {
            assert_eq!(group.sources, part * 3..part * 3 + 3);
            let mesh = group.mesh.as_ref().unwrap();
            assert_eq!(mesh.indices().len(), 12_000);
            assert_eq!(mesh.vertex_count(), 9);
            assert_eq!(
                mesh.texture().unwrap().id,
                model.meshes[part * 3].1.texture.as_ref().unwrap().id
            );
        }
        assert_ne!(
            model.resident_meshes[0]
                .mesh
                .as_ref()
                .unwrap()
                .texture()
                .unwrap()
                .id,
            model.resident_meshes[1]
                .mesh
                .as_ref()
                .unwrap()
                .texture()
                .unwrap()
                .id
        );
    }

    #[test]
    fn resident_layout_keeps_original_part_ids_for_identical_materials() {
        let mut asset = textured_asset();
        asset.meshes[0].indices = [0, 1, 2].repeat(4_000);
        asset.meshes.push(asset.meshes[0].clone());
        for batching in [
            ResidentBatching::LegacyChunks,
            ResidentBatching::CoalescedParts,
        ] {
            let model = WeaponModel::from_asset_with_batching(asset.clone(), batching);
            let groups = model.resident_source_groups("root");
            let mut expected_start = 0;
            for group in groups {
                assert_eq!(group.model_key, "root");
                assert_eq!(group.kind, "rigid");
                assert_eq!(group.source_chunks, 6);
                assert_eq!(group.sources.start, expected_start);
                assert_eq!(group.source_parts.len(), group.sources.len());
                assert!(group
                    .source_parts
                    .iter()
                    .all(|part| *part == group.sources.start / 3));
                assert!(group.mesh.is_some());
                if batching == ResidentBatching::LegacyChunks {
                    assert_eq!(group.sources.len(), 1);
                }
                expected_start = group.sources.end;
            }
            assert_eq!(expected_start, 6);
        }
    }

    fn textured_asset() -> WeaponAsset {
        WeaponAsset {
            payload_crc32: 0,
            meshes: vec![vector_range::asset::AssetMesh {
                base_color: [0.8, 0.6, 0.4, 1.],
                metallic: 0.,
                roughness: 1.,
                texture_width: 1,
                texture_height: 2,
                rgba: vec![20, 40, 60, 80, 100, 120, 140, 160],
                vertices: [Vec3::ZERO, Vec3::X, Vec3::Y]
                    .into_iter()
                    .map(|position| vector_range::asset::AssetVertex {
                        position: position.to_array(),
                        normal: Vec3::Z.to_array(),
                        uv: [0., 0.],
                    })
                    .collect(),
                indices: vec![0, 1, 2],
            }],
        }
    }

    fn ambient_lighting() -> SceneLighting {
        SceneLighting {
            direction_to_light: Vec3::Y,
            ambient: 1.,
            diffuse: 0.,
        }
    }

    #[test]
    fn textured_weapon_construction_needs_no_gpu_and_preserves_repeat_sampling() {
        let model = WeaponModel::from_asset(textured_asset());
        let texture = model.meshes[0].1.texture.as_ref().unwrap();
        assert_eq!((texture.width, texture.height), (1, 2));
        assert_eq!(texture.sampler.filter, FilterMode::Linear);
        assert_eq!(texture.sampler.wrap_x, WrapMode::Repeat);
        assert_eq!(texture.sampler.wrap_y, WrapMode::Repeat);
        let vector_range::draw::TextureSource::Rgba8(bytes) = &texture.source else {
            panic!("weapon texture must retain its CPU RGBA8 source");
        };
        assert_eq!(bytes.as_ref(), &[20, 40, 60, 255, 100, 120, 140, 255]);
    }

    #[test]
    fn authored_draw_records_transform_visibility_and_per_actor_alpha() {
        let mut model = WeaponModel::from_asset(textured_asset());
        let parent = Mat4::from_rotation_y(0.3);
        let actor = Mat4::from_scale_rotation_translation(
            vec3(1., 2., 3.),
            Quat::from_rotation_z(0.2),
            vec3(4., 5., 6.),
        );
        begin_frame(640, 480, 1.).unwrap();
        with_model_matrix(parent, || {
            model.draw_authored_parts(&[actor], &[true], &[0.5], ambient_lighting());
        });
        assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
        model.draw_authored_parts(&[actor], &[false], &[1.], ambient_lighting());
        model.draw_authored_parts(&[actor], &[true], &[1.], ambient_lighting());
        let list = take_draw_list().unwrap();
        let meshes: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| match command {
                vector_range::draw::Command::Mesh { mesh, model, blend } => {
                    Some((mesh, *model, *blend))
                }
                _ => None,
            })
            .collect();
        assert_eq!(meshes.len(), 2, "invisible actors must not submit geometry");
        assert_eq!(meshes[0].1, parent * actor);
        assert_eq!(meshes[1].1, actor);
        for (index, expected_alpha) in [128, 255].into_iter().enumerate() {
            assert_eq!(meshes[index].2, BlendMode::Alpha);
            assert_eq!(meshes[index].0.indices, [0, 1, 2]);
            for vertex in &meshes[index].0.vertices {
                assert_eq!(vertex.color, [204, 153, 102, expected_alpha]);
                assert_eq!(vertex.normal, Vec3::Z.extend(0.));
            }
        }
        assert_eq!(meshes[0].0.vertices[1].position, Vec3::X);
    }

    #[test]
    fn procedural_draw_records_the_existing_root_times_local_transform() {
        let mut model = WeaponModel::from_asset(textured_asset());
        model.hk416_rig = true;
        model.meshes[0].0 = 5;
        let pose = Mat4::from_rotation_translation(Quat::from_rotation_x(0.4), Vec3::Y);
        let animation = vector_range::weapon_animation::WeaponAnimationPose {
            bolt_translation: [0.1, 0.2, 0.3],
            ..Default::default()
        };
        begin_frame(640, 480, 1.).unwrap();
        model.draw_pose_with_free_frame(pose, Mat4::IDENTITY, &animation, ambient_lighting());
        assert_eq!(current_model_matrix().unwrap(), Mat4::IDENTITY);
        let list = take_draw_list().unwrap();
        let meshes: Vec<_> = list
            .commands
            .iter()
            .filter_map(|command| match command {
                vector_range::draw::Command::Mesh { model, blend, .. } => Some((*model, *blend)),
                _ => None,
            })
            .collect();
        assert_eq!(
            meshes,
            [(
                pose * Mat4::from_translation(vec3(0.1, 0.2, 0.3)),
                BlendMode::Alpha,
            )]
        );
    }

    #[test]
    fn rigid_key_preserves_every_float_bit() {
        let original = textured_asset().meshes[0].vertices[0].clone();
        let original_key = rigid_vertex_key(&original);
        for component in 0..8 {
            let mut keys = std::collections::HashSet::new();
            for bits in [0, 0x8000_0000, 1, 0x7fc0_0001, 0x7fc0_0002] {
                let mut vertex = original.clone();
                let value = f32::from_bits(bits);
                match component {
                    0..=2 => vertex.position[component] = value,
                    3..=5 => vertex.normal[component - 3] = value,
                    _ => vertex.uv[component - 6] = value,
                }
                let key = rigid_vertex_key(&vertex);
                assert_eq!(key[component], bits);
                for other in 0..8 {
                    if other != component {
                        assert_eq!(key[other], original_key[other]);
                    }
                }
                assert!(keys.insert(key), "must not canonicalize float bits");
            }
        }
    }

    #[test]
    fn construction_reuses_exact_vertices_but_keeps_seams_and_materials() {
        let mut asset = textured_asset();
        let part = &mut asset.meshes[0];
        let original = part.vertices[0].clone();
        part.vertices.push(original.clone());
        part.vertices.push(AssetVertex {
            normal: Vec3::Y.to_array(),
            ..original.clone()
        });
        part.vertices.push(AssetVertex {
            uv: [0.5, 0.75],
            ..original
        });
        part.indices = vec![0, 1, 2, 3, 4, 5];
        let mut other_material = part.clone();
        other_material.base_color[0] = 0.25;
        asset.meshes.push(other_material);
        let model = WeaponModel::from_asset(asset.clone());
        assert_eq!(model.meshes.len(), 2);
        for (part_index, mesh, albedo) in &model.meshes {
            let source = &asset.meshes[*part_index];
            assert_eq!(mesh.vertices.len(), 5);
            assert_eq!(mesh.indices, [0, 1, 2, 0, 3, 4]);
            assert_eq!(albedo.r.to_bits(), source.base_color[0].to_bits());
            for (&input, &output) in source.indices.iter().zip(&mesh.indices) {
                let actual = &mesh.vertices[output as usize];
                let expected = &source.vertices[input as usize];
                assert_eq!(
                    actual.position.to_array().map(f32::to_bits),
                    expected.position.map(f32::to_bits)
                );
                assert_eq!(
                    actual.normal.truncate().to_array().map(f32::to_bits),
                    expected.normal.map(f32::to_bits)
                );
                assert_eq!(
                    actual.uv.to_array().map(f32::to_bits),
                    expected.uv.map(f32::to_bits)
                );
            }
        }
    }

    #[test]
    fn partition_is_deterministic_first_occurrence_and_never_crosses_chunks() {
        let keys = [7, 9, 7, 9, 7, 9];
        let original = [4, 2, 3, 1, 0, 5];
        for _ in 0..8 {
            assert_eq!(
                partition_triangles(&original, |source| keys[source as usize]),
                [(vec![4, 3], vec![0, 0, 1, 1, 0, 1])]
            );
        }
        let original: Vec<u32> = (0..9_996).collect();
        let batches = partition_triangles(&original, |_| 0u8);
        assert_eq!(batches.len(), 2);
        assert_eq!(batches[0], (vec![0], vec![0; 4_998]));
        assert_eq!(batches[1], (vec![4_998], vec![0; 4_998]));
        assert!(partition_triangles::<u32>(&[], |source| source).is_empty());
    }

    #[test]
    #[should_panic]
    fn construction_does_not_hide_invalid_referenced_indices() {
        let mut asset = textured_asset();
        asset.meshes[0].indices = vec![0, 1, u32::MAX];
        // Public asset decoders reject this earlier; manually constructed input
        // still reaches the same checked slice access instead of being merged.
        let _ = WeaponModel::from_asset(asset);
    }

    #[test]
    fn preserves_large_indexed_model_without_u16_truncation() {
        let original: Vec<u32> = (0..90_000).collect();
        let batches = partition_triangles(&original, |source| source);
        let restored: Vec<u32> = batches
            .iter()
            .flat_map(|(vertices, indices)| indices.iter().map(|&i| vertices[i as usize]))
            .collect();
        assert_eq!(restored, original);
        assert!(batches
            .iter()
            .all(|(v, i)| v.len() <= 4_998 && i.len() <= 4_998 && i.len().is_multiple_of(3)));
    }
    #[test]
    fn reuses_vertices_within_batch() {
        let parts = partition_triangles(&[0, 1, 2, 0, 2, 3], |source| source);
        assert_eq!(parts[0].0, [0, 1, 2, 3]);
        assert_eq!(parts[0].1, [0, 1, 2, 0, 2, 3]);
    }
}
