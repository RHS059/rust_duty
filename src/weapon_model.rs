//! GPU adapter for the authorized test model and optional local overrides.
use macroquad::prelude::*;
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
                let texture = Texture2D::from_rgba8(
                    part.texture_width as u16,
                    part.texture_height as u16,
                    &opaque_rgba,
                );
                texture.set_filter(FilterMode::Linear);
                // Set repeat sampling explicitly to match the supported GLB subset.
                unsafe {
                    get_internal_gl().quad_context.texture_set_wrap(
                        texture.raw_miniquad_id(),
                        macroquad::miniquad::TextureWrap::Repeat,
                        macroquad::miniquad::TextureWrap::Repeat,
                    );
                }
                Some(texture)
            };
            // Macroquad uses u16 indices and a 5,000-index default batch. Split
            // triangle lists without index truncation or dropped triangles.
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
                    unsafe {
                        get_internal_gl().quad_gl.push_model_matrix(matrix);
                    }
                    draw_mesh(mesh);
                    unsafe {
                        get_internal_gl().quad_gl.pop_model_matrix();
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
            unsafe {
                get_internal_gl().quad_gl.push_model_matrix(root * local);
            }
            draw_mesh(mesh);
            unsafe {
                get_internal_gl().quad_gl.pop_model_matrix();
            }
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
