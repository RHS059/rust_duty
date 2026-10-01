//! Original two-bone arm IK and CPU skinning for an optional private arm rig.
//! All motion is authored here; no commercial-game animation data is imported.
use crate::skinned_asset::SkinnedAsset;
use macroquad::prelude::*;

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
        for matrix in &globals {
            if !matrix.is_finite() || matrix.determinant().abs() < 1e-10 {
                return Err("arm rig has invalid accumulated transform".into());
            }
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
                t.set_filter(FilterMode::Linear);
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
        let desired = Mat4::from_rotation_translation(hand_rotation, desired_wrist);
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
