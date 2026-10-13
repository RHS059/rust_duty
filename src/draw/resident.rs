//! Immutable authored geometry and owned per-draw deformation state.
//!
//! Geometry is validated once, before receiving a resource identity. Recorded
//! poses are independent snapshots: sharing a mesh never shares mutable bones.
use super::{resource_id, Color, Mesh, ResourceId, Texture, Vertex};
use crate::scene_lighting::SceneLighting;
use glam::{Mat4, Vec2, Vec3};
use std::sync::Arc;

pub const MAX_BONES: usize = crate::skinned_asset::MAX_BONES;
const MAX_VERTICES: usize = u16::MAX as usize + 1;
const MAX_INDICES: usize = u16::MAX as usize;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RigidVertex {
    pub position: [f32; 3],
    pub uv: [f32; 2],
    pub normal: [f32; 3],
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SkinVertex {
    pub vertex: RigidVertex,
    pub joints: [u16; 8],
    pub weights: [f32; 8],
}

#[derive(Debug)]
pub enum Vertices {
    Rigid(Vec<RigidVertex>),
    Skin {
        vertices: Vec<SkinVertex>,
        bones: usize,
    },
}

#[derive(Debug)]
struct Geometry {
    id: ResourceId,
    vertices: Vertices,
    indices: Vec<u16>,
    texture: Option<Texture>,
    position_bound: [f64; 3],
}

/// Clones retain the same immutable source and never copy its vertex payload.
#[derive(Clone, Debug)]
pub struct ResidentMesh(Arc<Geometry>);

impl ResidentMesh {
    pub fn new(
        vertices: Vertices,
        indices: Vec<u16>,
        texture: Option<Texture>,
    ) -> Result<Self, String> {
        let (count, valid) = match &vertices {
            Vertices::Rigid(vertices) => (vertices.len(), vertices.iter().all(valid_vertex)),
            Vertices::Skin { vertices, bones } => (
                vertices.len(),
                (1..=MAX_BONES).contains(bones)
                    && vertices.iter().all(|v| {
                        valid_vertex(&v.vertex)
                            && v.joints.iter().all(|&j| usize::from(j) < *bones)
                            && v.weights.iter().all(|w| (0.0..=1.0).contains(w))
                            && (0.9999..=1.0001).contains(&v.weights.iter().sum::<f32>())
                    }),
            ),
        };
        if !valid
            || count > MAX_VERTICES
            || indices.len() > MAX_INDICES
            || !indices.len().is_multiple_of(3)
            || indices.iter().any(|&index| usize::from(index) >= count)
        {
            return Err("invalid or unbounded resident geometry".into());
        }
        if let Some(texture) = &texture {
            match &texture.source {
                super::TextureSource::Rgba8(bytes)
                    if texture.width > 0
                        && texture.height > 0
                        && texture
                            .width
                            .checked_mul(texture.height)
                            .and_then(|n| n.checked_mul(4))
                            == u32::try_from(bytes.len()).ok() => {}
                _ => return Err("resident geometry requires immutable RGBA8 texture data".into()),
            }
        }
        let mut position_bound = [0_f64; 3];
        let mut include = |v: &RigidVertex| {
            for (bound, value) in position_bound.iter_mut().zip(v.position) {
                *bound = bound.max(f64::from(value).abs());
            }
        };
        match &vertices {
            Vertices::Rigid(values) => values.iter().for_each(&mut include),
            Vertices::Skin { vertices, .. } => vertices.iter().for_each(|v| include(&v.vertex)),
        }
        Ok(Self(Arc::new(Geometry {
            id: resource_id(),
            vertices,
            indices,
            texture,
            position_bound,
        })))
    }

    /// Concatenate immutable chunks without changing any vertex word or index
    /// order. Callers must keep actor, pose, material and render-state boundaries;
    /// this only checks the geometry-owned texture, kind, palette size and bounds.
    pub fn coalesce(meshes: &[Self]) -> Result<Self, String> {
        let first = meshes.first().ok_or("no resident chunks to coalesce")?;
        let mut vertices = 0usize;
        let mut indices = 0usize;
        for mesh in meshes {
            vertices = vertices
                .checked_add(mesh.vertex_count())
                .ok_or("resident vertex overflow")?;
            indices = indices
                .checked_add(mesh.indices().len())
                .ok_or("resident index overflow")?;
            if vertices > MAX_VERTICES || indices > MAX_INDICES {
                return Err("coalesced resident geometry exceeds existing bounds".into());
            }
            if mesh.texture().map(|t| t.id) != first.texture().map(|t| t.id) {
                return Err("resident chunks have different textures".into());
            }
            match (first.vertices(), mesh.vertices()) {
                (Vertices::Rigid(_), Vertices::Rigid(_)) => {}
                (Vertices::Skin { bones: a, .. }, Vertices::Skin { bones: b, .. }) if a == b => {}
                _ => return Err("resident chunks have different vertex or palette layouts".into()),
            }
        }
        if meshes.len() == 1 {
            return Ok(first.clone());
        }
        let mut local_indices = Vec::with_capacity(indices);
        let mut offset = 0usize;
        for mesh in meshes {
            for &index in mesh.indices() {
                local_indices.push(
                    u16::try_from(offset + usize::from(index))
                        .map_err(|_| "coalesced resident index overflow")?,
                );
            }
            offset += mesh.vertex_count();
        }
        let vertices = match first.vertices() {
            Vertices::Rigid(_) => {
                let mut combined = Vec::with_capacity(vertices);
                for mesh in meshes {
                    let Vertices::Rigid(values) = mesh.vertices() else {
                        unreachable!()
                    };
                    combined.extend_from_slice(values);
                }
                Vertices::Rigid(combined)
            }
            Vertices::Skin { bones, .. } => {
                let mut combined = Vec::with_capacity(vertices);
                for mesh in meshes {
                    let Vertices::Skin { vertices, .. } = mesh.vertices() else {
                        unreachable!()
                    };
                    combined.extend_from_slice(vertices);
                }
                Vertices::Skin {
                    vertices: combined,
                    bones: *bones,
                }
            }
        };
        Self::new(vertices, local_indices, first.texture().cloned())
    }

    pub fn id(&self) -> ResourceId {
        self.0.id
    }
    pub fn vertices(&self) -> &Vertices {
        &self.0.vertices
    }
    pub fn indices(&self) -> &[u16] {
        &self.0.indices
    }
    pub fn texture(&self) -> Option<&Texture> {
        self.0.texture.as_ref()
    }
    pub fn vertex_count(&self) -> usize {
        match self.vertices() {
            Vertices::Rigid(v) => v.len(),
            Vertices::Skin { vertices, .. } => vertices.len(),
        }
    }
}

fn valid_vertex(vertex: &RigidVertex) -> bool {
    vertex
        .position
        .iter()
        .chain(&vertex.uv)
        .chain(&vertex.normal)
        .all(|v| v.is_finite())
}

#[derive(Debug)]
struct PaletteData {
    id: ResourceId,
    positions: Vec<Mat4>,
    normals: Vec<Mat4>,
    position_bounds: [[f64; 4]; 3],
}

/// One immutable palette may serve several batches in the same recorded pose.
#[derive(Clone, Debug)]
pub struct SkinPalette(Arc<PaletteData>);
impl SkinPalette {
    pub fn new(positions: Vec<Mat4>) -> Result<Self, String> {
        if !(1..=MAX_BONES).contains(&positions.len()) || positions.iter().any(|m| !m.is_finite()) {
            return Err("invalid resident bone palette".into());
        }
        let normals: Vec<_> = positions.iter().map(|m| m.inverse().transpose()).collect();
        if normals.iter().any(|m| !m.is_finite()) {
            return Err("resident bone normal transform is singular".into());
        }
        let mut position_bounds = [[0_f64; 4]; 3];
        for matrix in &positions {
            let cols = matrix.to_cols_array_2d();
            for (row, bounds) in position_bounds.iter_mut().enumerate() {
                for (column, bound) in bounds.iter_mut().enumerate() {
                    *bound = bound.max(f64::from(cols[column][row]).abs());
                }
            }
        }
        Ok(Self(Arc::new(PaletteData {
            id: resource_id(),
            positions,
            normals,
            position_bounds,
        })))
    }
    pub fn id(&self) -> ResourceId {
        self.0.id
    }
    pub fn positions(&self) -> &[Mat4] {
        &self.0.positions
    }
    pub fn normals(&self) -> &[Mat4] {
        &self.0.normals
    }
}

/// All per-draw values are owned. A later pose cannot rewrite this snapshot.
#[derive(Clone, Debug)]
pub struct ResidentDraw {
    mesh: ResidentMesh,
    root: Mat4,
    normal: Mat4,
    lighting: SceneLighting,
    albedo: Color,
    alpha: f32,
    palette: Option<SkinPalette>,
}
impl ResidentDraw {
    pub fn new(
        mesh: ResidentMesh,
        root: Mat4,
        lighting: SceneLighting,
        albedo: Color,
        alpha: f32,
        palette: Option<SkinPalette>,
    ) -> Result<Self, String> {
        if !root.is_finite()
            || !lighting.direction_to_light.is_finite()
            || ![
                lighting.ambient,
                lighting.diffuse,
                albedo.r,
                albedo.g,
                albedo.b,
                albedo.a,
                alpha,
            ]
            .iter()
            .all(|x| x.is_finite())
        {
            return Err("nonfinite resident draw state".into());
        }
        // Conservative O(bones + batches) bounds keep invalid transformed
        // geometry on the existing CPU/error path without revisiting vertices.
        let mut bound = mesh.0.position_bound;
        if let Some(palette) = &palette {
            bound = palette.0.position_bounds.map(|row| {
                (row[0] * bound[0] + row[1] * bound[1] + row[2] * bound[2] + row[3]) * 1.001
            });
            // Bone multiplication precedes influence weighting and root. A
            // later small weight or root cannot make an intermediate Inf safe.
            // Absolute row bounds also cover partial sums without cancellation.
            if bound
                .iter()
                .any(|value| !value.is_finite() || *value > f64::from(f32::MAX))
            {
                return Err(
                    "resident bone-space position could overflow; use CPU reference".into(),
                );
            }
        }
        for row in root.transpose().to_cols_array_2d().into_iter().take(3) {
            let world = f64::from(row[0]).abs() * bound[0]
                + f64::from(row[1]).abs() * bound[1]
                + f64::from(row[2]).abs() * bound[2]
                + f64::from(row[3]).abs();
            if !world.is_finite() || world > f64::from(f32::MAX) {
                return Err(
                    "resident transformed position could overflow; use CPU reference".into(),
                );
            }
        }
        let normal = match (mesh.vertices(), &palette) {
            (Vertices::Rigid(_), None) => {
                if root.x_axis.w != 0.
                    || root.y_axis.w != 0.
                    || root.z_axis.w != 0.
                    || root.w_axis.w != 1.
                {
                    return Err("resident rigid root must be affine".into());
                }
                root.inverse().transpose()
            }
            (Vertices::Skin { bones, .. }, Some(palette))
                if *bones == palette.positions().len() =>
            {
                root
            }
            _ => return Err("resident geometry and palette differ".into()),
        };
        if !normal.is_finite() {
            return Err("resident rigid normal transform is singular".into());
        }
        Ok(Self {
            mesh,
            root,
            normal,
            lighting,
            albedo,
            alpha: alpha.clamp(0., 1.),
            palette,
        })
    }
    pub fn mesh(&self) -> &ResidentMesh {
        &self.mesh
    }
    pub fn root(&self) -> Mat4 {
        self.root
    }
    pub fn normal_transform(&self) -> Mat4 {
        self.normal
    }
    pub fn lighting(&self) -> SceneLighting {
        self.lighting
    }
    pub fn albedo(&self) -> Color {
        self.albedo
    }
    pub fn alpha(&self) -> f32 {
        self.alpha
    }
    pub fn palette(&self) -> Option<&SkinPalette> {
        self.palette.as_ref()
    }

    /// CPU reference only. Native resident rendering must not call this method.
    /// Preserve current vertex-stage RGBA8 quantization before interpolation.
    pub fn reference_mesh(&self) -> Mesh {
        let shade = |source: &RigidVertex, position: Vec3, normal: Vec3, skin: bool| {
            // The current skin loop normalizes once before irradiance does
            // its own normalization; rigid lighting only normalizes inside
            // irradiance. Preserve that distinction even in the CPU oracle.
            let shade_normal = if skin {
                normal.try_normalize().unwrap_or(Vec3::Y)
            } else {
                normal
            };
            let mut color: [u8; 4] = self.lighting.shade(self.albedo, shade_normal).into();
            color[3] = if skin {
                255
            } else {
                (self.alpha * 255.).round() as u8
            };
            Vertex {
                position,
                uv: Vec2::from_array(source.uv),
                color,
                normal: normal.try_normalize().unwrap_or(Vec3::Y).extend(0.),
            }
        };
        let vertices = match self.mesh.vertices() {
            Vertices::Rigid(vertices) => vertices
                .iter()
                .map(|v| {
                    shade(
                        v,
                        self.root.transform_point3(Vec3::from_array(v.position)),
                        self.normal.transform_vector3(Vec3::from_array(v.normal)),
                        false,
                    )
                })
                .collect(),
            Vertices::Skin { vertices, .. } => {
                let palette = self
                    .palette
                    .as_ref()
                    .expect("validated skin draw owns its palette");
                vertices
                    .iter()
                    .map(|v| {
                        let mut position = Vec3::ZERO;
                        let mut normal = Vec3::ZERO;
                        for (&joint, &weight) in v.joints.iter().zip(&v.weights) {
                            if weight > 0. {
                                position += palette.positions()[usize::from(joint)]
                                    .transform_point3(Vec3::from_array(v.vertex.position))
                                    * weight;
                                normal += palette.normals()[usize::from(joint)]
                                    .transform_vector3(Vec3::from_array(v.vertex.normal))
                                    * weight;
                            }
                        }
                        shade(
                            &v.vertex,
                            self.root.transform_point3(position),
                            self.root.transform_vector3(normal),
                            true,
                        )
                    })
                    .collect()
            }
        };
        Mesh {
            vertices,
            indices: self.mesh.indices().to_vec(),
            texture: self.mesh.texture().cloned(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn vertex() -> RigidVertex {
        RigidVertex {
            position: [1., 2., 3.],
            uv: [0.25, 0.75],
            normal: [1., 1., 0.],
        }
    }
    fn mesh() -> ResidentMesh {
        ResidentMesh::new(Vertices::Rigid(vec![vertex(); 3]), vec![0, 1, 2], None).unwrap()
    }
    fn record_words(mesh: &ResidentMesh) -> Vec<Vec<u32>> {
        let rigid = |v: &RigidVertex| {
            v.position
                .iter()
                .chain(&v.normal)
                .chain(&v.uv)
                .map(|v| v.to_bits())
                .collect::<Vec<_>>()
        };
        mesh.indices()
            .iter()
            .map(|&i| match mesh.vertices() {
                Vertices::Rigid(vertices) => rigid(&vertices[i as usize]),
                Vertices::Skin { vertices, .. } => {
                    let v = &vertices[i as usize];
                    let mut words = rigid(&v.vertex);
                    words.extend(v.joints.map(u32::from));
                    words.extend(v.weights.map(f32::to_bits));
                    words
                }
            })
            .collect()
    }

    #[test]
    fn coalescing_preserves_all_ordered_source_words_and_chunk_duplicates() {
        for skin in [false, true] {
            let chunks: Vec<_> = (0..4)
                .map(|chunk| {
                    let vertices: Vec<_> = (0..3)
                        .map(|index| RigidVertex {
                            position: [chunk as f32, index as f32, -0.0],
                            normal: [0.0, -0.0, 1.0],
                            uv: [f32::from_bits(1), -0.0],
                        })
                        .collect();
                    ResidentMesh::new(
                        if skin {
                            Vertices::Skin {
                                vertices: vertices
                                    .into_iter()
                                    .map(|vertex| SkinVertex {
                                        vertex,
                                        joints: [0, 1, 2, 3, 4, 5, 6, 127],
                                        weights: [0.125; 8],
                                    })
                                    .collect(),
                                bones: 128,
                            }
                        } else {
                            Vertices::Rigid(vertices)
                        },
                        vec![2, 0, 1, 1, 0, 2],
                        None,
                    )
                    .unwrap()
                })
                .collect();
            let combined = ResidentMesh::coalesce(&chunks).unwrap();
            assert_eq!(combined.vertex_count(), 12);
            assert_eq!(
                combined.indices(),
                &[2, 0, 1, 1, 0, 2, 5, 3, 4, 4, 3, 5, 8, 6, 7, 7, 6, 8, 11, 9, 10, 10, 9, 11]
            );
            assert_eq!(
                record_words(&combined),
                chunks.iter().flat_map(record_words).collect::<Vec<_>>()
            );
            assert_eq!(
                ResidentMesh::coalesce(&chunks[..1]).unwrap().id(),
                chunks[0].id()
            );
        }
    }

    #[test]
    fn coalescing_rejects_layout_texture_and_existing_bound_violations() {
        assert!(ResidentMesh::coalesce(&[]).is_err());
        let rigid = mesh();
        let skin = |bones| {
            ResidentMesh::new(
                Vertices::Skin {
                    vertices: vec![
                        SkinVertex {
                            vertex: vertex(),
                            joints: [0; 8],
                            weights: [1., 0., 0., 0., 0., 0., 0., 0.]
                        };
                        3
                    ],
                    bones,
                },
                vec![0, 1, 2],
                None,
            )
            .unwrap()
        };
        assert!(ResidentMesh::coalesce(&[rigid.clone(), skin(1)]).is_err());
        assert!(ResidentMesh::coalesce(&[skin(1), skin(2)]).is_err());
        let texture = Texture::rgba8(1, 1, &[255; 4], super::super::Sampler::default()).unwrap();
        let textured = ResidentMesh::new(
            Vertices::Rigid(vec![vertex(); 3]),
            vec![0, 1, 2],
            Some(texture),
        )
        .unwrap();
        assert!(ResidentMesh::coalesce(&[rigid.clone(), textured.clone()]).is_err());
        assert!(ResidentMesh::coalesce(&[textured.clone(), textured]).is_ok());
        let indices =
            ResidentMesh::new(Vertices::Rigid(vec![vertex(); 3]), vec![0; 65_535], None).unwrap();
        assert!(ResidentMesh::coalesce(std::slice::from_ref(&indices)).is_ok());
        assert!(ResidentMesh::coalesce(&[indices, rigid.clone()]).is_err());
        let vertices = ResidentMesh::new(
            Vertices::Rigid(vec![vertex(); 65_533]),
            vec![65_532; 3],
            None,
        )
        .unwrap();
        let at_limit = ResidentMesh::coalesce(&[vertices.clone(), rigid.clone()]).unwrap();
        assert_eq!(at_limit.vertex_count(), 65_536);
        assert_eq!(&at_limit.indices()[3..], &[65_533, 65_534, 65_535]);
        assert!(ResidentMesh::coalesce(&[vertices, rigid.clone(), rigid]).is_err());
    }

    #[test]
    fn singular_state_falls_back_and_extreme_normals_keep_cpu_y_fallback() {
        assert!(SkinPalette::new(vec![Mat4::ZERO]).is_err());
        for normal in [[0., 0., 0.], [1e30, 0., 0.], [1e-30, 0., 0.]] {
            let mesh = ResidentMesh::new(
                Vertices::Rigid(vec![
                    RigidVertex {
                        position: [0.; 3],
                        uv: [0.; 2],
                        normal
                    };
                    3
                ]),
                vec![0, 1, 2],
                None,
            )
            .unwrap();
            let light = SceneLighting {
                direction_to_light: Vec3::Y,
                ambient: 0.,
                diffuse: 1.,
            };
            assert!(
                ResidentDraw::new(mesh.clone(), Mat4::ZERO, light, Color::WHITE, 1., None).is_err()
            );
            let draw =
                ResidentDraw::new(mesh, Mat4::IDENTITY, light, Color::WHITE, 1., None).unwrap();
            assert_eq!(draw.reference_mesh().vertices[0].color, [255; 4]);
        }
    }

    #[test]
    fn rigid_projective_root_is_rejected_before_recording() {
        let mesh = ResidentMesh::new(
            Vertices::Rigid(vec![
                RigidVertex {
                    position: [1.; 3],
                    uv: [0.; 2],
                    normal: [0., 1., 0.]
                };
                3
            ]),
            vec![0, 1, 2],
            None,
        )
        .unwrap();
        let mut root = Mat4::IDENTITY;
        root.x_axis.w = 0.25;
        assert!(
            ResidentDraw::new(mesh, root, SceneLighting::range(), Color::WHITE, 1., None)
                .unwrap_err()
                .contains("affine")
        );
    }

    #[test]
    fn clones_share_immutable_geometry_and_draws_own_state() {
        let mesh = mesh();
        let other = mesh.clone();
        assert_eq!(mesh.id(), other.id());
        assert!(std::ptr::eq(
            mesh.indices().as_ptr(),
            other.indices().as_ptr()
        ));
        let first = ResidentDraw::new(
            mesh,
            Mat4::IDENTITY,
            SceneLighting::range(),
            Color::WHITE,
            0.5,
            None,
        )
        .unwrap();
        let old = first.reference_mesh();
        let second = ResidentDraw::new(
            other,
            Mat4::from_translation(Vec3::X),
            SceneLighting::range(),
            Color::WHITE,
            0.25,
            None,
        )
        .unwrap();
        assert_eq!(first.reference_mesh().vertices, old.vertices);
        assert_ne!(second.reference_mesh().vertices, old.vertices);
        assert_eq!(old.vertices[0].color[3], 128);
        assert_eq!(second.reference_mesh().vertices[0].color[3], 64);
    }
    #[test]
    fn rigid_reference_matches_existing_inverse_transpose_lighting() {
        let root = Mat4::from_scale_rotation_translation(
            Vec3::new(2., 0.5, 3.),
            glam::Quat::from_rotation_y(0.7),
            Vec3::new(1., 2., 3.),
        );
        let albedo = Color::new(0.73, 0.52, 0.21, 0.2);
        let lighting = SceneLighting::range();
        let draw = ResidentDraw::new(mesh(), root, lighting, albedo, 0.5, None).unwrap();
        let mut reference = Mesh {
            vertices: vec![
                Vertex {
                    position: Vec3::from_array(vertex().position),
                    uv: Vec2::from_array(vertex().uv),
                    color: [0; 4],
                    normal: Vec3::from_array(vertex().normal).extend(0.)
                };
                3
            ],
            indices: vec![0, 1, 2],
            texture: None,
        };
        lighting.shade_rigid(&mut reference, albedo, root);
        let output = draw.reference_mesh();
        assert_eq!(
            output.vertices[0].color[..3],
            reference.vertices[0].color[..3]
        );
        assert_eq!(
            output.vertices[0].position,
            root.transform_point3(reference.vertices[0].position)
        );
    }
    #[test]
    fn every_skin_influence_is_ordered_and_later_palettes_do_not_mutate_it() {
        let v = SkinVertex {
            vertex: vertex(),
            joints: [0, 1, 2, 3, 4, 5, 6, 7],
            weights: [0., 0., 0., 0., 0.1, 0.2, 0.3, 0.4],
        };
        let positions: Vec<_> = (0..8)
            .map(|i| Mat4::from_translation(Vec3::X * i as f32))
            .collect();
        let original = positions.clone();
        let mesh = ResidentMesh::new(
            Vertices::Skin {
                vertices: vec![v; 3],
                bones: 8,
            },
            vec![0, 1, 2],
            None,
        )
        .unwrap();
        let palette = SkinPalette::new(positions).unwrap();
        let draw = ResidentDraw::new(
            mesh.clone(),
            Mat4::IDENTITY,
            SceneLighting::range(),
            Color::WHITE,
            0.,
            Some(palette.clone()),
        )
        .unwrap();
        let later = SkinPalette::new(vec![Mat4::IDENTITY; 8]).unwrap();
        assert_ne!(palette.id(), later.id());
        let mut expected = Vec3::ZERO;
        for (&joint, &weight) in v.joints.iter().zip(&v.weights) {
            if weight > 0. {
                expected += original[usize::from(joint)]
                    .transform_point3(Vec3::from_array(v.vertex.position))
                    * weight;
            }
        }
        assert_eq!(draw.reference_mesh().vertices[0].position, expected);
        assert_eq!(draw.reference_mesh().vertices[0].color[3], 255);
        assert!(ResidentDraw::new(
            mesh,
            Mat4::IDENTITY,
            SceneLighting::range(),
            Color::WHITE,
            1.,
            None
        )
        .is_err());
    }

    #[test]
    fn skin_intermediate_overflow_cannot_be_hidden_by_root_or_weight() {
        let source = RigidVertex {
            position: [10_000., 0., 0.],
            normal: [0., 1., 0.],
            uv: [0.; 2],
        };
        for (weight, root) in [
            (1., Mat4::from_rotation_z(std::f32::consts::FRAC_PI_4)),
            (0.0001, Mat4::from_scale(Vec3::splat(0.25))),
        ] {
            let mut weights = [0.; 8];
            weights[0] = weight;
            weights[1] = 1. - weight;
            let skin = SkinVertex {
                vertex: source,
                joints: [0, 1, 1, 1, 1, 1, 1, 1],
                weights,
            };
            let mesh = ResidentMesh::new(
                Vertices::Skin {
                    vertices: vec![skin; 3],
                    bones: 2,
                },
                vec![0, 1, 2],
                None,
            )
            .unwrap();
            // The CPU path multiplies by each bone before weighting and root.
            // A finite final f64 bound cannot undo this intermediate f32 Inf.
            let overflowing = Mat4::from_scale(Vec3::new(4e34, 1., 1.));
            let intermediate = overflowing.transform_point3(Vec3::from_array(source.position));
            assert!(!intermediate.is_finite());
            let mathematical_skin_x =
                4e38_f64 * f64::from(weight) + 10_000. * f64::from(1. - weight);
            let world_x = f64::from(root.x_axis.x).abs() * mathematical_skin_x;
            assert!(world_x < f64::from(f32::MAX));
            let palette = SkinPalette::new(vec![overflowing, Mat4::IDENTITY]).unwrap();
            assert!(ResidentDraw::new(
                mesh.clone(),
                root,
                SceneLighting::range(),
                Color::WHITE,
                1.,
                Some(palette)
            )
            .is_err());

            let finite = Mat4::from_scale(Vec3::new(3e34, 1., 1.));
            let palette = SkinPalette::new(vec![finite, Mat4::IDENTITY]).unwrap();
            let draw = ResidentDraw::new(
                mesh,
                root,
                SceneLighting::range(),
                Color::WHITE,
                1.,
                Some(palette),
            )
            .unwrap();
            assert!(draw
                .reference_mesh()
                .vertices
                .iter()
                .all(|v| v.position.is_finite()));
        }
    }

    #[test]
    fn invalid_geometry_palette_and_zero_weight_joint_are_rejected() {
        assert!(ResidentMesh::new(Vertices::Rigid(vec![vertex()]), vec![0, 1, 2], None).is_err());
        assert!(ResidentMesh::new(Vertices::Rigid(vec![vertex()]), vec![0], None).is_err());
        let mut bad = vertex();
        bad.normal[0] = f32::NAN;
        assert!(ResidentMesh::new(Vertices::Rigid(vec![bad]), vec![], None).is_err());
        let mut skin = SkinVertex {
            vertex: vertex(),
            joints: [0; 8],
            weights: [1., 0., 0., 0., 0., 0., 0., 0.],
        };
        assert!(ResidentMesh::new(
            Vertices::Skin {
                vertices: vec![skin],
                bones: 1
            },
            vec![0, 0, 0],
            None
        )
        .is_ok());
        skin.joints[7] = 1;
        assert!(ResidentMesh::new(
            Vertices::Skin {
                vertices: vec![skin],
                bones: 1
            },
            vec![0, 0, 0],
            None
        )
        .is_err());
        assert!(SkinPalette::new(vec![]).is_err());
        assert!(SkinPalette::new(vec![Mat4::ZERO]).is_err());
        assert!(SkinPalette::new(vec![Mat4::IDENTITY; MAX_BONES + 1]).is_err());
    }
}
