//! Original two-bone arm IK and CPU skinning for an optional private arm rig.
//! All motion is authored here; no commercial-game animation data is imported.
use crate::skinned_asset::SkinnedAsset;
use macroquad::prelude::*;

// The converter accepts REPEAT sampling, including UVs outside [0, 1]. Keep
// construction and CPU regression checks on the same sampler configuration.
fn texture_sampler() -> (
    FilterMode,
    macroquad::miniquad::TextureWrap,
    macroquad::miniquad::TextureWrap,
) {
    (
        FilterMode::Linear,
        macroquad::miniquad::TextureWrap::Repeat,
        macroquad::miniquad::TextureWrap::Repeat,
    )
}

/// IK replaces joint orientations, so its accumulated transforms must be
/// positive uniform similarities. Decomposing arbitrary affine matrices into
/// scale/rotation would silently discard shear or a reflected basis.
fn supported_uniform_scale(matrix: Mat4) -> Result<f32, &'static str> {
    let determinant = matrix.determinant();
    if !matrix.is_finite() || !determinant.is_finite() || determinant.abs() < 1e-10 {
        return Err("invalid or singular transform");
    }
    let columns = [
        matrix.x_axis.truncate(),
        matrix.y_axis.truncate(),
        matrix.z_axis.truncate(),
    ];
    let lengths = columns.map(Vec3::length);
    if lengths.iter().any(|s| !s.is_finite() || *s <= 0.) {
        return Err("invalid or singular transform");
    }
    let axes = std::array::from_fn::<_, 3, _>(|i| columns[i] / lengths[i]);
    const TOLERANCE: f32 = 1e-4;
    if axes[0].dot(axes[1]).abs() > TOLERANCE
        || axes[0].dot(axes[2]).abs() > TOLERANCE
        || axes[1].dot(axes[2]).abs() > TOLERANCE
    {
        return Err("shear");
    }
    if axes[0].cross(axes[1]).dot(axes[2]) < 0. {
        return Err("reflection");
    }
    let largest = lengths.into_iter().fold(0., f32::max);
    if lengths
        .iter()
        .any(|&s| (s - largest).abs() > largest * TOLERANCE)
    {
        return Err("nonuniform scale");
    }
    Ok(lengths[0])
}

/// Analytic two-bone solve with a stable bend plane and reachable endpoint.
pub fn solve_two_bone(
    shoulder: Vec3,
    target: Vec3,
    pole: Vec3,
    upper: f32,
    lower: f32,
) -> (Vec3, Vec3) {
    let delta = target - shoulder;
    let direction = delta.try_normalize().unwrap_or(-Vec3::Z);
    let min = (upper - lower).abs() + 0.0001;
    let max = (upper + lower - 0.0001).max(min);
    let distance = delta.length().clamp(min, max);
    let along = (upper * upper - lower * lower + distance * distance) / (2. * distance);
    let height = (upper * upper - along * along).max(0.).sqrt();
    let raw = pole - shoulder;
    let projected = raw - direction * raw.dot(direction);
    let bend = projected.try_normalize().unwrap_or_else(|| {
        let axis = if direction.y.abs() < 0.9 {
            Vec3::Y
        } else {
            Vec3::X
        };
        direction.cross(axis).normalize()
    });
    (
        shoulder + direction * along + bend * height,
        shoulder + direction * distance,
    )
}
fn global_matrices(locals: &[Mat4], parents: &[Option<usize>], root: Mat4) -> Vec<Mat4> {
    fn resolve(
        i: usize,
        locals: &[Mat4],
        parents: &[Option<usize>],
        root: Mat4,
        out: &mut [Mat4],
        done: &mut [bool],
    ) {
        if done[i] {
            return;
        }
        let parent = if let Some(p) = parents[i] {
            resolve(p, locals, parents, root, out, done);
            out[p]
        } else {
            root
        };
        out[i] = parent * locals[i];
        done[i] = true;
    }
    let mut out = vec![Mat4::IDENTITY; locals.len()];
    let mut done = vec![false; locals.len()];
    for i in 0..locals.len() {
        resolve(i, locals, parents, root, &mut out, &mut done);
    }
    out
}
struct Batch {
    source_mesh: usize,
    source_vertices: Vec<usize>,
    mesh: Mesh,
}
pub struct ArmModel {
    asset: SkinnedAsset,
    parents: Vec<Option<usize>>,
    rest: Vec<Mat4>,
    inverse_bind: Vec<Mat4>,
    batches: Vec<Batch>,
    names: std::collections::HashMap<String, usize>,
}
impl ArmModel {
    /// GPU construction must be called after the window/render context exists.
    pub fn new(asset: SkinnedAsset) -> Result<Self, String> {
        let names = asset
            .bones
            .iter()
            .enumerate()
            .map(|(i, b)| (b.name.clone(), i))
            .collect::<std::collections::HashMap<_, _>>();
        for name in [
            "upperarm_l",
            "lowerarm_l",
            "hand_l",
            "upperarm_r",
            "lowerarm_r",
            "hand_r",
        ] {
            if !names.contains_key(name) {
                return Err(format!("arm rig is missing {name}"));
            }
        }
        if names.len() != asset.bones.len() {
            return Err("arm rig has duplicate bone names".into());
        }
        let parents: Vec<_> = asset.bones.iter().map(|b| b.parent).collect();
        let rest: Vec<_> = asset
            .bones
            .iter()
            .map(|b| Mat4::from_cols_array(&b.rest_local))
            .collect();
        let inverse_bind = asset
            .bones
            .iter()
            .map(|b| Mat4::from_cols_array(&b.inverse_bind))
            .collect();
        let globals = global_matrices(&rest, &parents, Mat4::IDENTITY);
        for (bone, &matrix) in asset.bones.iter().zip(&globals) {
            supported_uniform_scale(matrix).map_err(|reason| {
                format!(
                    "arm rig bone {} has unsupported accumulated {reason}; bake transforms \
                     into the mesh and re-export with orthogonal, positive uniform bone scales",
                    bone.name
                )
            })?;
        }
        for side in ["l", "r"] {
            let upper = names[&format!("upperarm_{side}")];
            let lower = names[&format!("lowerarm_{side}")];
            let hand = names[&format!("hand_{side}")];
            if parents[lower] != Some(upper) || parents[hand] != Some(lower) {
                return Err(format!("unsupported {side} arm hierarchy"));
            }
            let a = globals[upper].w_axis.truncate();
            let b = globals[lower].w_axis.truncate();
            let c = globals[hand].w_axis.truncate();
            if !(0.01..2.0).contains(&a.distance(b)) || !(0.01..2.0).contains(&b.distance(c)) {
                return Err(format!("invalid {side} arm segment lengths"));
            }
        }
        let mut batches = Vec::new();
        for (source_mesh, part) in asset.meshes.iter().enumerate() {
            let texture = if part.rgba.is_empty() {
                None
            } else {
                let mut pixels = part.rgba.clone();
                for alpha in pixels.iter_mut().skip(3).step_by(4) {
                    *alpha = 255;
                }
                let t = Texture2D::from_rgba8(
                    part.texture_width as u16,
                    part.texture_height as u16,
                    &pixels,
                );
                let (filter, wrap_x, wrap_y) = texture_sampler();
                t.set_filter(filter);
                unsafe {
                    get_internal_gl().quad_context.texture_set_wrap(
                        t.raw_miniquad_id(),
                        wrap_x,
                        wrap_y,
                    );
                }
                Some(t)
            };
            for chunk in part.indices.chunks(4998) {
                let mut map = std::collections::HashMap::new();
                let mut source_vertices = Vec::new();
                let indices = chunk
                    .iter()
                    .map(|&v| {
                        *map.entry(v).or_insert_with(|| {
                            let i = source_vertices.len() as u16;
                            source_vertices.push(v as usize);
                            i
                        })
                    })
                    .collect();
                let vertices = source_vertices
                    .iter()
                    .map(|&i| {
                        let v = &part.vertices[i];
                        Vertex::new2(Vec3::from_array(v.position), Vec2::from_array(v.uv), WHITE)
                    })
                    .collect();
                batches.push(Batch {
                    source_mesh,
                    source_vertices,
                    mesh: Mesh {
                        vertices,
                        indices,
                        texture: texture.clone(),
                    },
                });
            }
        }
        Ok(Self {
            asset,
            parents,
            rest,
            inverse_bind,
            batches,
            names,
        })
    }
    fn set_global(
        &self,
        locals: &mut [Mat4],
        globals: &[Mat4],
        index: usize,
        desired: Mat4,
        root: Mat4,
    ) {
        let parent = self.parents[index].map(|p| globals[p]).unwrap_or(root);
        locals[index] = parent.inverse() * desired;
    }
    fn pose_arm(
        &self,
        locals: &mut [Mat4],
        side: &str,
        target: Vec3,
        pole: Vec3,
        hand_rotation: Quat,
        root: Mat4,
    ) {
        let upper = self.names[&format!("upperarm_{side}")];
        let lower = self.names[&format!("lowerarm_{side}")];
        let hand = self.names[&format!("hand_{side}")];
        let mut globals = global_matrices(locals, &self.parents, root);
        let shoulder = globals[upper].w_axis.truncate();
        let elbow = globals[lower].w_axis.truncate();
        let wrist = globals[hand].w_axis.truncate();
        let (desired_elbow, desired_wrist) = solve_two_bone(
            shoulder,
            target,
            pole,
            shoulder.distance(elbow),
            elbow.distance(wrist),
        );
        let rotation = Quat::from_rotation_arc(
            (elbow - shoulder).normalize(),
            (desired_elbow - shoulder).normalize(),
        );
        let desired = Mat4::from_translation(shoulder)
            * Mat4::from_quat(rotation)
            * Mat4::from_translation(-shoulder)
            * globals[upper];
        self.set_global(locals, &globals, upper, desired, root);
        globals = global_matrices(locals, &self.parents, root);
        let elbow = globals[lower].w_axis.truncate();
        let wrist = globals[hand].w_axis.truncate();
        let rotation = Quat::from_rotation_arc(
            (wrist - elbow).normalize(),
            (desired_wrist - elbow).normalize(),
        );
        let desired = Mat4::from_translation(elbow)
            * Mat4::from_quat(rotation)
            * Mat4::from_translation(-elbow)
            * globals[lower];
        self.set_global(locals, &globals, lower, desired, root);
        globals = global_matrices(locals, &self.parents, root);
        // Retain inherited rig units when replacing the wrist orientation. A
        // unit-scale hand would undo e.g. a 0.01 root scale through inverse bind
        // skinning and inflate its vertices by 100x. Construction validates that
        // the basis has only positive uniform scale; IK adds rigid rotations.
        let hand_scale = globals[hand].x_axis.truncate().length();
        let desired = Mat4::from_scale_rotation_translation(
            Vec3::splat(hand_scale),
            hand_rotation,
            desired_wrist,
        );
        self.set_global(locals, &globals, hand, desired, root);
    }
    pub fn draw(
        &mut self,
        weapon_transform: Mat4,
        pose: &crate::weapon_animation::WeaponAnimationPose,
    ) {
        let root = Mat4::from_translation(vec3(0., -1.65, -0.11))
            * Mat4::from_rotation_y(std::f32::consts::PI);
        let mut locals = self.rest.clone();
        let weapon_rotation = weapon_transform.to_scale_rotation_translation().1;
        let right_rotation =
            weapon_rotation * Quat::from_mat3(&Mat3::from_cols(Vec3::Y, -Vec3::Z, -Vec3::X));
        let left_rotation =
            weapon_rotation * Quat::from_mat3(&Mat3::from_cols(-Vec3::Z, Vec3::X, -Vec3::Y));
        self.pose_arm(
            &mut locals,
            "r",
            weapon_transform.transform_point3(Vec3::from_array(pose.right_grip)),
            vec3(0.45, -0.40, 0.02),
            right_rotation,
            root,
        );
        self.pose_arm(
            &mut locals,
            "l",
            weapon_transform.transform_point3(Vec3::from_array(pose.left_grip)),
            vec3(-0.30, -0.42, -0.22),
            left_rotation,
            root,
        );
        for side in ["l", "r"] {
            for finger in ["index", "middle", "ring", "pinky", "thumb"] {
                for segment in 1..=3 {
                    let name = format!("{finger}_{segment:02}_{side}");
                    if let Some(&index) = self.names.get(&name) {
                        let flex = if finger == "thumb" {
                            0.35
                        } else if finger == "index" && side == "r" {
                            0.35 + pose.trigger_pull * 0.16
                        } else {
                            0.75
                        };
                        locals[index] *= Mat4::from_rotation_y(flex);
                    }
                }
            }
        }
        let globals = global_matrices(&locals, &self.parents, root);
        let palette: Vec<_> = globals
            .iter()
            .zip(&self.inverse_bind)
            .map(|(g, b)| *g * *b)
            .collect();
        let normals: Vec<_> = palette.iter().map(|m| m.inverse().transpose()).collect();
        let light = vec3(-0.3, 0.8, 0.5).normalize();
        for batch in &mut self.batches {
            let part = &self.asset.meshes[batch.source_mesh];
            for (vertex, &index) in batch.mesh.vertices.iter_mut().zip(&batch.source_vertices) {
                let source = &part.vertices[index];
                let p = Vec3::from_array(source.position);
                let n = Vec3::from_array(source.normal);
                let mut position = Vec3::ZERO;
                let mut normal = Vec3::ZERO;
                for influence in 0..8 {
                    let weight = source.weights[influence];
                    if weight > 0. {
                        let joint = source.joints[influence] as usize;
                        position += palette[joint].transform_point3(p) * weight;
                        normal += normals[joint].transform_vector3(n) * weight;
                    }
                }
                let normal = normal.try_normalize().unwrap_or(Vec3::Y);
                let shade = 0.35 + 0.65 * normal.dot(light).max(0.);
                vertex.position = position;
                vertex.normal = normal.extend(0.);
                vertex.color = Color::new(
                    part.base_color[0] * shade,
                    part.base_color[1] * shade,
                    part.base_color[2] * shade,
                    1.,
                )
                .into();
            }
            draw_mesh(&batch.mesh);
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::skinned_asset::Bone;

    fn fixture() -> SkinnedAsset {
        let mut bones = Vec::new();
        for side in ["l", "r"] {
            let start = bones.len();
            for (i, name) in ["upperarm", "lowerarm", "hand"].into_iter().enumerate() {
                let matrix = if i == 0 {
                    Mat4::IDENTITY
                } else {
                    Mat4::from_translation(Vec3::X * 0.28)
                };
                bones.push(crate::skinned_asset::Bone {
                    name: format!("{name}_{side}"),
                    parent: (i > 0).then_some(start + i.saturating_sub(1)),
                    rest_local: matrix.to_cols_array(),
                    inverse_bind: Mat4::IDENTITY.to_cols_array(),
                });
            }
        }
        SkinnedAsset {
            bones,
            meshes: Vec::new(),
        }
    }

    // Original synthetic rig: both 0.28 m arm segments inherit the exporter's
    // unit conversion from a shared root. Inverse binds are genuine rest-global
    // inverses, so these tests exercise posed skinning, not just rest lengths.
    fn scaled_fixture(scale: f32) -> SkinnedAsset {
        let mut asset = fixture();
        for (index, bone) in asset.bones.iter_mut().enumerate() {
            bone.parent = Some(bone.parent.map_or(0, |p| p + 1));
            let position = if index % 3 == 0 {
                vec3(if index == 0 { -0.2 } else { 0.2 }, 1.4, 0.)
            } else {
                Vec3::X * 0.28
            };
            bone.rest_local = Mat4::from_translation(position / scale).to_cols_array();
        }
        asset.bones.insert(
            0,
            Bone {
                name: "rig_root".into(),
                parent: None,
                rest_local: Mat4::from_scale_rotation_translation(
                    Vec3::splat(scale),
                    Quat::from_rotation_y(0.31),
                    vec3(0.03, 0.1, -0.02),
                )
                .to_cols_array(),
                inverse_bind: Mat4::IDENTITY.to_cols_array(),
            },
        );
        let locals: Vec<_> = asset
            .bones
            .iter()
            .map(|b| Mat4::from_cols_array(&b.rest_local))
            .collect();
        let parents: Vec<_> = asset.bones.iter().map(|b| b.parent).collect();
        for (bone, global) in
            asset
                .bones
                .iter_mut()
                .zip(global_matrices(&locals, &parents, Mat4::IDENTITY))
        {
            bone.inverse_bind = global.inverse().to_cols_array();
        }
        asset
    }

    fn assert_posed_hand_radius(scale: f32) {
        // An empty mesh list keeps GPU construction out of this CPU-only test.
        let model = ArmModel::new(scaled_fixture(scale)).unwrap();
        let bind = global_matrices(&model.rest, &model.parents, Mat4::IDENTITY);
        let root = Mat4::from_rotation_translation(
            Quat::from_rotation_y(std::f32::consts::PI),
            vec3(0., -1.65, -0.11),
        );
        for side in ["l", "r"] {
            for offset in [vec3(0.28, -0.13, -0.19), vec3(-0.18, 0.15, -0.31)] {
                let mut locals = model.rest.clone();
                let upper = model.names[&format!("upperarm_{side}")];
                let hand = model.names[&format!("hand_{side}")];
                let shoulder = root.transform_point3(bind[upper].w_axis.truncate());
                let target = shoulder + offset;
                let hand_rotation = Quat::from_rotation_x(0.43) * Quat::from_rotation_z(-0.61);
                model.pose_arm(
                    &mut locals,
                    side,
                    target,
                    shoulder + Vec3::NEG_Y,
                    hand_rotation,
                    root,
                );
                let posed = global_matrices(&locals, &model.parents, root);
                let wrist = posed[hand].w_axis.truncate();
                assert!(wrist.distance(target) < 1e-5, "wrist must reach the target");
                let palette = posed[hand] * model.inverse_bind[hand];
                let bind_wrist = bind[hand].w_axis.truncate();
                // Each point represents a vertex with 100% hand influence.
                // Check all axes to catch anisotropic distortion as well.
                for axis in [Vec3::X, Vec3::Y, Vec3::Z] {
                    let source_vertex = bind_wrist + axis * 0.05;
                    let skinned_vertex = palette.transform_point3(source_vertex);
                    let radius = skinned_vertex.distance(wrist);
                    assert!(
                        (radius - 0.05).abs() < 1e-5,
                        "{side} hand at inherited scale {scale}: 0.05 m became {radius} m"
                    );
                }
                let expected = Mat4::from_scale_rotation_translation(
                    Vec3::splat(scale),
                    hand_rotation,
                    target,
                );
                assert!(posed[hand].abs_diff_eq(expected, 1e-5));
            }
        }
    }

    #[test]
    fn posed_hands_preserve_five_centimeter_radius_at_half_scale() {
        assert_posed_hand_radius(0.5);
    }

    #[test]
    fn posed_hands_preserve_five_centimeter_radius_at_centimeter_scale() {
        assert_posed_hand_radius(0.01);
    }

    #[test]
    fn rejects_unsupported_inherited_transforms_with_export_guidance() {
        let shear = Mat4::from_cols(
            Vec3::X.extend(0.),
            vec3(0.2, 1., 0.).extend(0.),
            Vec3::Z.extend(0.),
            Vec4::W,
        );
        for (matrix, reason) in [
            (Mat4::from_scale(vec3(1., 1.1, 1.)), "nonuniform scale"),
            (shear, "shear"),
            (Mat4::from_scale(vec3(-1., 1., 1.)), "reflection"),
        ] {
            let mut asset = scaled_fixture(1.);
            asset.bones[0].rest_local = matrix.to_cols_array();
            let error = ArmModel::new(asset).err().expect("unsupported arm rig");
            assert!(
                error.contains("rig_root") && error.contains(reason),
                "{error}"
            );
            assert!(error.contains("bake transforms") && error.contains("re-export"));
        }
    }

    #[test]
    fn renderer_sampler_is_linear_repeat_on_both_axes() {
        let (filter, wrap_x, wrap_y) = texture_sampler();
        assert_eq!(filter, FilterMode::Linear);
        assert_eq!(wrap_x, macroquad::miniquad::TextureWrap::Repeat);
        assert_eq!(wrap_y, macroquad::miniquad::TextureWrap::Repeat);
    }

    #[test]
    fn named_arm_validation_rejects_bad_chains_lengths_and_duplicate_names() {
        assert!(ArmModel::new(fixture()).is_ok());
        let mut bad = fixture();
        bad.bones[1].parent = None;
        assert!(ArmModel::new(bad).is_err());
        let mut bad = fixture();
        bad.bones[1].rest_local = Mat4::IDENTITY.to_cols_array();
        assert!(ArmModel::new(bad).is_err());
        let mut bad = fixture();
        bad.bones.push(bad.bones[0].clone());
        assert!(ArmModel::new(bad).is_err());
    }
    #[test]
    fn ik_keeps_bone_lengths_for_near_and_far_targets() {
        for target in [vec3(0.2, -0.2, -0.4), Vec3::ZERO, vec3(100., 0., 0.)] {
            let (e, w) = solve_two_bone(Vec3::ZERO, target, vec3(0., -1., 0.), 0.3, 0.28);
            assert!((e.length() - 0.3).abs() < 1e-4);
            assert!((e.distance(w) - 0.28).abs() < 1e-4);
            assert!(e.is_finite() && w.is_finite());
        }
    }
    #[test]
    fn hierarchy_handles_parents_after_children() {
        let locals = [
            Mat4::from_translation(Vec3::X),
            Mat4::from_translation(Vec3::Y),
        ];
        let m = global_matrices(&locals, &[Some(1), None], Mat4::IDENTITY);
        assert_eq!(m[0].w_axis.truncate(), vec3(1., 1., 0.));
    }
}
