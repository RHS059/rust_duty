//! GPU adapter for the authorized test model and optional local overrides.
use macroquad::prelude::*;
use vector_range::asset::WeaponAsset;

pub struct WeaponModel {
    meshes: Vec<Mesh>,
    pub muzzle: Vec3,
}
impl WeaponModel {
    pub fn from_asset(asset: WeaponAsset) -> Self {
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
        let light = vec3(-0.3, 0.8, 0.5).normalize();
        for part in asset.meshes {
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
                        let shade = 0.35 + 0.65 * normal.dot(light).max(0.);
                        let mut vertex = Vertex::new2(
                            Vec3::from_array(v.position),
                            Vec2::from_array(v.uv),
                            Color::new(
                                part.base_color[0] * shade,
                                part.base_color[1] * shade,
                                part.base_color[2] * shade,
                                1.,
                            ),
                        );
                        vertex.normal = normal.extend(0.);
                        vertex
                    })
                    .collect::<Vec<_>>();
                meshes.push(Mesh {
                    vertices,
                    indices,
                    texture: texture.clone(),
                });
            }
        }
        Self { meshes, muzzle }
    }
    pub fn draw(&self, offset: Vec3) {
        // Matrix stack changes only the viewmodel draw; no unsafe pointer access.
        unsafe {
            get_internal_gl()
                .quad_gl
                .push_model_matrix(Mat4::from_translation(offset));
        }
        for mesh in &self.meshes {
            draw_mesh(mesh);
        }
        unsafe {
            get_internal_gl().quad_gl.pop_model_matrix();
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
