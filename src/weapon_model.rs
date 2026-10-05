//! CPU draw adapter for the authorized test model and optional local overrides.
use vector_range::draw::facade::*;
use vector_range::{asset::WeaponAsset, scene_lighting::SceneLighting};

pub struct WeaponModel {
    meshes: Vec<(usize, Mesh, Color)>,
    hk416_rig: bool,
    pub muzzle: Vec3,
}
impl WeaponModel {
    pub fn from_asset(asset: WeaponAsset) -> Self {
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
            for (source_vertices, indices) in partition_triangles(&part.indices) {
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
        Self {
            meshes,
            muzzle,
            hk416_rig,
        }
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
        for (part, mesh, albedo) in &mut self.meshes {
            if visible.get(*part).copied().unwrap_or(false) {
                if let Some(&matrix) = transforms.get(*part) {
                    lighting.shade_rigid(mesh, *albedo, matrix);
                    let alpha = opacity.get(*part).copied().unwrap_or(1.).clamp(0., 1.);
                    for vertex in &mut mesh.vertices {
                        vertex.color[3] = (alpha * 255.).round() as u8;
                    }
                    draw_mesh_transformed(mesh, matrix, BlendMode::Alpha);
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

// Limit chunks to the engine's default draw capacity, remapping only referenced
// vertices so a detailed model does not upload three vertices per triangle.
fn partition_triangles(indices: &[u32]) -> Vec<(Vec<u32>, Vec<u16>)> {
    indices
        .chunks(4_998)
        .map(|chunk| {
            let mut map = std::collections::HashMap::new();
            let mut sources = Vec::new();
            let local = chunk
                .iter()
                .map(|&source| {
                    *map.entry(source).or_insert_with(|| {
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
    fn preserves_large_indexed_model_without_u16_truncation() {
        let original: Vec<u32> = (0..90_000).collect();
        let batches = partition_triangles(&original);
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
        let parts = partition_triangles(&[0, 1, 2, 0, 2, 3]);
        assert_eq!(parts[0].0, [0, 1, 2, 3]);
        assert_eq!(parts[0].1, [0, 1, 2, 0, 2, 3]);
    }
}
