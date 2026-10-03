//! Original two-bone arm IK and CPU skinning for an optional private arm rig.
//! All motion is authored here; no commercial-game animation data is imported.
use crate::skinned_asset::SkinnedAsset;
use crate::weapon_ik::{blend_hand_constraint, HandPose, WeaponIkTargets};
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

/// Weapon-local wrist anchors fitted to the HK416 grip surfaces. These are
/// wrist joints, not palm centers; the animation sampler owns their trajectories.
pub const FITTED_RIGHT_WRIST: [f32; 3] = crate::weapon_animation::RIGHT_GRIP;
pub const FITTED_SUPPORT_WRIST: [f32; 3] = crate::weapon_animation::LEFT_GRIP;
pub const FITTED_MAGAZINE_WRIST: [f32; 3] = [-0.046, -0.150, 0.010];
pub const FITTED_RECEIVER_WRIST: [f32; 3] = [-0.041, -0.105, 0.008];

/// Unconstrained animated wrists in an independently authored camera/body clip
/// frame. These channels must precede the weapon-grip constraint; feeding the
/// legacy already-blended grip channels here would apply that blend twice.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ArmFreeHandPose {
    pub left: HandPose,
    pub right: HandPose,
}

impl ArmFreeHandPose {
    fn in_frame(self, frame: Mat4) -> Self {
        let rotation = frame.to_scale_rotation_translation().1;
        let transform = |hand: HandPose| HandPose {
            position: frame.transform_point3(hand.position),
            orientation: rotation * hand.orientation,
        };
        Self {
            left: transform(self.left),
            right: transform(self.right),
        }
    }
}

/// Blend order is support, magazine, receiver, open. Invalid/empty weights
/// select support. Normalizing here keeps the renderer safe during cancellation.
fn normalized_hand_modes(weights: [f32; 4]) -> [f32; 4] {
    let mut clean = weights.map(|v| if v.is_finite() { v.max(0.) } else { 0. });
    let total: f32 = clean.iter().sum();
    if !total.is_finite() || total <= 1e-6 {
        return [1., 0., 0., 0.];
    }
    for value in &mut clean {
        *value /= total;
    }
    clean
}

// Bone-local +X runs wrist-to-knuckle on the left and in the opposite
// direction on the right. The left palm faces -Z; the right palm faces +Z.
// These are rigid, right-handed bases. Finger hinges are calibrated separately
// from each actual bind chain rather than assuming all finger bone rolls match.
fn right_wrist_rotation() -> Quat {
    Quat::from_array(crate::weapon_ik::RIGHT_GRIP_ORIENTATION).normalize()
}
fn left_wrist_rotations() -> [Quat; 4] {
    crate::weapon_animation::HAND_MODE_ORIENTATIONS.map(Quat::from_array)
}

fn blend_wrist_rotation(weights: [f32; 4]) -> Quat {
    let rotations = left_wrist_rotations();
    let reference = rotations[0];
    let mut sum = Vec4::ZERO;
    for (rotation, weight) in rotations.into_iter().zip(normalized_hand_modes(weights)) {
        let sign = if reference.dot(rotation) < 0. {
            -1.
        } else {
            1.
        };
        sum += Vec4::from_array(rotation.to_array()) * (weight * sign);
    }
    Quat::from_array(sum.normalize().to_array())
}

// Rows: index, middle, ring, pinky, thumb. Columns: MCP/CMC, PIP/MCP, DIP/IP.
// Authored additive radians from this rig's relaxed bind pose, not an extracted
// animation. Independent proximal/distal angles preserve a trigger finger and
// opposing thumb instead of making every digit the same three-joint claw.
const SUPPORT_CURL: [[f32; 3]; 5] = [
    [0.254949, 1.027841, 1.201806],
    [0.492603, 1.070965, 0.528698],
    [0.534569, 0.857938, 1.189056],
    [0.53153, 0.582992, 1.088175],
    [0.315728, 0.612712, 0.220057],
];
const MAGAZINE_CURL: [[f32; 3]; 5] = [
    [0.098, 1.46, 1.40],
    [0.607, 1.229, 1.40],
    [0.595, 1.241, 1.40],
    [0.786, 0.959, 1.40],
    [0.24, 0.38, 0.20],
];
const RECEIVER_CURL: [[f32; 3]; 5] = [
    [0.10, 0.18, 0.08],
    [0.12, 0.22, 0.10],
    [0.18, 0.30, 0.16],
    [0.24, 0.38, 0.22],
    [0.08, 0.20, 0.12],
];
const OPEN_CURL: [[f32; 3]; 5] = [
    [-0.08, 0.02, -0.04],
    [-0.06, 0.02, -0.04],
    [0.00, 0.05, 0.00],
    [0.06, 0.10, 0.04],
    [-0.10, 0.05, 0.02],
];
const PISTOL_CURL: [[f32; 3]; 5] = [
    [-0.7196754, 1.7317524, 0.7871223],
    [-0.10119829, 1.6106945, 0.93029094],
    [0.08151749, 1.2048621, 1.4160256],
    [-0.068384714, 1.064695, 0.69483125],
    [0.18427947, 0.91346943, -0.27630535],
];
fn finger_curls(left: bool, weights: [f32; 4], trigger: f32) -> [[f32; 3]; 5] {
    if !left {
        let mut curls = PISTOL_CURL;
        let trigger = if trigger.is_finite() {
            trigger.clamp(0., 1.)
        } else {
            0.
        };
        curls[0][1] += trigger * 0.18;
        curls[0][2] += trigger * 0.08;
        return curls;
    }
    let mut out = [[0.; 3]; 5];
    for (profile, weight) in [SUPPORT_CURL, MAGAZINE_CURL, RECEIVER_CURL, OPEN_CURL]
        .into_iter()
        .zip(normalized_hand_modes(weights))
    {
        for finger in 0..5 {
            for segment in 0..3 {
                out[finger][segment] += profile[finger][segment] * weight;
            }
        }
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
    finger_hinges: std::collections::HashMap<usize, Vec3>,
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
        let mut finger_hinges = std::collections::HashMap::new();
        for side in ["l", "r"] {
            let hand = names[&format!("hand_{side}")];
            let palm = globals[hand]
                .transform_vector3(if side == "l" { -Vec3::Z } else { Vec3::Z })
                .normalize();
            for finger in ["index", "middle", "ring", "pinky", "thumb"] {
                for segment in 1..=3 {
                    let Some(&joint) = names.get(&format!("{finger}_{segment:02}_{side}")) else {
                        continue;
                    };
                    let forward = globals[joint]
                        .transform_vector3(if side == "l" { Vec3::X } else { -Vec3::X })
                        .normalize();
                    let toward = if finger == "thumb" {
                        names
                            .get(&format!("middle_01_{side}"))
                            .map(|&middle| {
                                globals[middle].w_axis.truncate() - globals[joint].w_axis.truncate()
                            })
                            .unwrap_or(palm)
                    } else {
                        palm
                    };
                    let hinge = forward.cross(toward).try_normalize().unwrap_or(Vec3::Y);
                    let local = globals[joint]
                        .inverse()
                        .transform_vector3(hinge)
                        .normalize();
                    finger_hinges.insert(joint, local);
                }
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
            finger_hinges,
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
        // Align pronation/supination on the main forearm before placing the
        // wrist. Its helper then receives only residual roll, avoiding opposite
        // skinning frames and the half-angle branch flip.
        let axis = (desired_wrist - globals[lower].w_axis.truncate()).normalize();
        let previous_hand = globals[hand].to_scale_rotation_translation().1;
        let delta = hand_rotation * previous_hand.inverse();
        let vector = vec3(delta.x, delta.y, delta.z);
        let projected = axis * vector.dot(axis);
        let twist = Quat::from_xyzw(projected.x, projected.y, projected.z, delta.w);
        if twist.length_squared() > 1e-8 {
            let pivot = globals[lower].w_axis.truncate();
            let aligned = Mat4::from_translation(pivot)
                * Mat4::from_quat(twist.normalize())
                * Mat4::from_translation(-pivot)
                * globals[lower];
            self.set_global(locals, &globals, lower, aligned, root);
            globals = global_matrices(locals, &self.parents, root);
        }
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
        // Distribute wrist roll across the optional forearm helper. The
        // continuous anatomical roll refinement is reviewed separately; applying
        // the entire roll only here collapses linearly blended forearm skin.
        if let Some(&twist) = self
            .names
            .get(&format!("lowerarm_twist_01_{side}"))
            .filter(|&&index| self.parents[index] == Some(lower))
        {
            let axis = (desired_wrist - globals[lower].w_axis.truncate()).normalize();
            let previous = globals[hand].to_scale_rotation_translation().1;
            let delta = hand_rotation * previous.inverse();
            let vector = vec3(delta.x, delta.y, delta.z);
            let projected = axis * vector.dot(axis);
            let candidate = Quat::from_xyzw(projected.x, projected.y, projected.z, delta.w);
            let roll = if candidate.length_squared() > 1e-8 {
                Quat::IDENTITY.slerp(candidate.normalize(), 0.5)
            } else {
                Quat::IDENTITY
            };
            let pivot = globals[twist].w_axis.truncate();
            let desired_twist = Mat4::from_translation(pivot)
                * Mat4::from_quat(roll)
                * Mat4::from_translation(-pivot)
                * globals[twist];
            self.set_global(locals, &globals, twist, desired_twist, root);
        }
    }
    fn posed_globals(
        &self,
        weapon_transform: Mat4,
        pose: &crate::weapon_animation::WeaponAnimationPose,
        left_modes: [f32; 4],
    ) -> Vec<Mat4> {
        let weapon_rotation = weapon_transform.to_scale_rotation_translation().1;
        // The prop rotates about its fitted wrist anchor. Apply the same local
        // rotation to a closed magazine grip so fingers stay on the same faces.
        // Blending out of that grip also releases its added wrist orientation.
        let hr = pose.left_hand_euler_yxz;
        let hand_rotation = Quat::from_euler(EulerRot::YXZ, hr[0], hr[1], hr[2]);
        let mr = pose.magazine_euler_yxz;
        let magazine_rotation = Quat::IDENTITY.slerp(
            Quat::from_euler(EulerRot::YXZ, mr[0], mr[1], mr[2]),
            normalized_hand_modes(left_modes)[1],
        );
        self.posed_globals_for_hands(
            weapon_transform.transform_point3(Vec3::from_array(pose.left_grip)),
            weapon_rotation
                * pose
                    .left_hand_orientation_xyzw
                    .map(Quat::from_array)
                    .unwrap_or(
                        hand_rotation * magazine_rotation * blend_wrist_rotation(left_modes),
                    ),
            weapon_transform.transform_point3(Vec3::from_array(pose.right_grip)),
            weapon_rotation * right_wrist_rotation(),
            pose.trigger_pull,
            left_modes,
        )
    }

    /// Evaluate the post-animation weapon constraints without drawing. The
    /// named rig targets are already in presentation space. The independently
    /// supplied free clip frame must exclude weapon-only recoil and sway, so a
    /// released hand cannot inherit either through the weapon hierarchy.
    ///
    /// Influences are [left, right]; they are independent of finger-mode
    /// weights. At zero the hand follows its free animation, at one it follows
    /// its weapon child, and between those endpoints it blends exactly once.
    /// The legacy grip and orientation fields in `pose` are deliberately unused.
    pub fn posed_globals_with_weapon_ik(
        &self,
        weapon_targets: &WeaponIkTargets,
        free_pose_frame: Mat4,
        pose: &crate::weapon_animation::WeaponAnimationPose,
        free_hands: ArmFreeHandPose,
        influences: [f32; 2],
        left_modes: [f32; 4],
    ) -> Vec<Mat4> {
        let free = free_hands.in_frame(free_pose_frame);
        let left = blend_hand_constraint(free.left, weapon_targets.left, influences[0]);
        let right = blend_hand_constraint(free.right, weapon_targets.right, influences[1]);
        self.posed_globals_for_hands(
            left.position,
            left.orientation,
            right.position,
            right.orientation,
            pose.trigger_pull,
            left_modes,
        )
    }

    /// Solve the final presentation-space wrist targets, then apply finger
    /// articulation separately. Both legacy and constrained entry points use
    /// this path so inherited scale, forearm twist, and contact poses agree.
    fn posed_globals_for_hands(
        &self,
        left_position: Vec3,
        left_rotation: Quat,
        right_position: Vec3,
        right_rotation: Quat,
        trigger_pull: f32,
        left_modes: [f32; 4],
    ) -> Vec<Mat4> {
        // Rotate the whole upper-body mount, preserving shoulder span and
        // sleeve attachment while placing the right elbow behind its grip.
        let body_pivot = vec3(0., -0.1828231, -0.01436418);
        let root = Mat4::from_translation(vec3(0., -0.06, 0.080))
            * Mat4::from_translation(body_pivot)
            * Mat4::from_rotation_y(-55_f32.to_radians())
            * Mat4::from_translation(-body_pivot)
            * Mat4::from_translation(vec3(0., -1.65, -0.11))
            * Mat4::from_rotation_y(std::f32::consts::PI);
        let mut locals = self.rest.clone();
        self.pose_arm(
            &mut locals,
            "r",
            right_position,
            vec3(0.35, -0.25, 0.40),
            right_rotation,
            root,
        );
        self.pose_arm(
            &mut locals,
            "l",
            left_position,
            vec3(-0.30, -0.42, -0.22),
            left_rotation,
            root,
        );
        for side in ["l", "r"] {
            let curls = finger_curls(side == "l", left_modes, trigger_pull);
            for (finger_number, finger) in ["index", "middle", "ring", "pinky", "thumb"]
                .into_iter()
                .enumerate()
            {
                for segment in 1..=3 {
                    let name = format!("{finger}_{segment:02}_{side}");
                    if let Some(&index) = self.names.get(&name) {
                        locals[index] *= Mat4::from_quat(Quat::from_axis_angle(
                            self.finger_hinges[&index],
                            curls[finger_number][segment - 1],
                        ));
                    }
                }
            }
        }
        global_matrices(&locals, &self.parents, root)
    }
    /// Compatibility entry point. Samplers with explicit reload modes should
    /// call draw_with_hand_modes so the support grip opens and opposes the mag.
    pub fn draw(
        &mut self,
        weapon_transform: Mat4,
        pose: &crate::weapon_animation::WeaponAnimationPose,
        lighting: crate::scene_lighting::SceneLighting,
    ) {
        self.draw_with_hand_modes(weapon_transform, pose, [1., 0., 0., 0.], lighting);
    }
    /// Pure presentation input: normalized weights [support, magazine, receiver,
    /// open]. The animation sampler supplies weights and exact wrist targets;
    /// this renderer never infers reload progress or changes gameplay state.
    pub fn draw_with_hand_modes(
        &mut self,
        weapon_transform: Mat4,
        pose: &crate::weapon_animation::WeaponAnimationPose,
        left_modes: [f32; 4],
        lighting: crate::scene_lighting::SceneLighting,
    ) {
        let globals = self.posed_globals(weapon_transform, pose, left_modes);
        self.draw_globals(globals, lighting);
    }

    /// Apply the default weapon grip after free arm animation and locomotion.
    /// Reload clips can lower either influence without changing finger poses.
    #[allow(clippy::too_many_arguments)]
    pub fn draw_with_weapon_ik(
        &mut self,
        weapon_targets: &WeaponIkTargets,
        free_pose_frame: Mat4,
        pose: &crate::weapon_animation::WeaponAnimationPose,
        free_hands: ArmFreeHandPose,
        influences: [f32; 2],
        left_modes: [f32; 4],
        lighting: crate::scene_lighting::SceneLighting,
    ) {
        let globals = self.posed_globals_with_weapon_ik(
            weapon_targets,
            free_pose_frame,
            pose,
            free_hands,
            influences,
            left_modes,
        );
        self.draw_globals(globals, lighting);
    }

    fn draw_globals(&mut self, globals: Vec<Mat4>, lighting: crate::scene_lighting::SceneLighting) {
        let palette: Vec<_> = globals
            .iter()
            .zip(&self.inverse_bind)
            .map(|(g, b)| *g * *b)
            .collect();
        let normals: Vec<_> = palette.iter().map(|m| m.inverse().transpose()).collect();
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
                let shade = lighting.irradiance(normal);
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
                vec3(if index == 0 { 0.2 } else { -0.2 }, 1.4, 0.)
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
    fn hand_modes_normalize_and_never_produce_invalid_rotations() {
        for weights in [
            [0.; 4],
            [f32::NAN, 0., 0., 0.],
            [1., 2., 3., 4.],
            [-2., 0., 1., 0.],
        ] {
            let normalized = normalized_hand_modes(weights);
            assert!((normalized.iter().sum::<f32>() - 1.).abs() < 1e-6);
            assert!(normalized.iter().all(|v| *v >= 0. && v.is_finite()));
            let rotation = blend_wrist_rotation(weights);
            assert!(rotation.is_finite() && (rotation.length() - 1.).abs() < 1e-6);
        }
    }

    #[test]
    fn grips_oppose_palm_surfaces_toward_the_weapon() {
        // Palm normals have opposite anatomical signs in this named rig.
        assert!((right_wrist_rotation() * Vec3::Z).dot(-Vec3::X) > 0.95);
        for mode in 1..3 {
            let mut weights = [0.; 4];
            weights[mode] = 1.;
            assert!((blend_wrist_rotation(weights) * -Vec3::Z).distance(Vec3::X) < 1e-6);
        }
        assert!((blend_wrist_rotation([1., 0., 0., 0.]) * -Vec3::Z).distance(Vec3::Y) < 1e-6);
        const { assert!(FITTED_SUPPORT_WRIST[2] < -0.17) };
    }

    #[test]
    fn held_magazine_rotation_preserves_wrist_and_rotates_hand_surface_with_prop() {
        let model = ArmModel::new(scaled_fixture(0.01)).unwrap();
        let weapon_rotation = Quat::from_euler(EulerRot::YXZ, 0.35, 0.2, -0.1);
        let transform = Mat4::from_rotation_translation(weapon_rotation, vec3(0.05, -0.10, -0.30));
        let mut pose = crate::weapon_animation::WeaponAnimationPose {
            left_grip: FITTED_MAGAZINE_WRIST,
            ..Default::default()
        };
        let hand = model.names["hand_l"];
        let before = model.posed_globals(transform, &pose, [0., 1., 0., 0.]);
        pose.magazine_euler_yxz = [0.64, -2.03, -0.26];
        let after = model.posed_globals(transform, &pose, [0., 1., 0., 0.]);
        let pivot = transform.transform_point3(Vec3::from_array(pose.left_grip));
        assert!(before[hand].w_axis.truncate().distance(pivot) < 1e-5);
        assert!(after[hand].w_axis.truncate().distance(pivot) < 1e-5);
        let delta = weapon_rotation
            * Quat::from_euler(EulerRot::YXZ, 0.64, -2.03, -0.26)
            * weapon_rotation.inverse();
        // Five-centimetre virtual surface probes on the centimetre-scaled rig.
        for probe in [Vec3::X * 5., Vec3::Y * 5., Vec3::Z * 5.] {
            let expected = pivot + delta * (before[hand].transform_point3(probe) - pivot);
            assert!(after[hand].transform_point3(probe).distance(expected) < 1e-5);
        }
        let right = model.names["hand_r"];
        assert!(before[right].abs_diff_eq(after[right], 1e-5));
        let released = model.posed_globals(transform, &pose, [1., 0., 0., 0.]);
        pose.magazine_euler_yxz = [0.; 3];
        let support = model.posed_globals(transform, &pose, [1., 0., 0., 0.]);
        assert!(released[hand].abs_diff_eq(support[hand], 1e-5));
    }

    fn free_hand_fixture() -> ArmFreeHandPose {
        ArmFreeHandPose {
            left: HandPose::new(
                vec3(-0.12, -0.11, 0.03),
                Quat::from_rotation_x(0.41) * blend_wrist_rotation([0., 0., 0., 1.]),
            ),
            right: HandPose::new(
                vec3(0.06, -0.14, 0.11),
                Quat::from_rotation_z(-0.32) * right_wrist_rotation(),
            ),
        }
    }

    #[test]
    fn released_hand_is_independent_of_weapon_root_while_other_hand_stays_anchored() {
        use crate::weapon_ik::WeaponIkRig;
        let model = ArmModel::new(scaled_fixture(0.01)).unwrap();
        let frame =
            Mat4::from_rotation_translation(Quat::from_rotation_y(-0.07), vec3(0.05, -0.10, -0.30));
        let mut rig = WeaponIkRig::new(frame);
        let pose = crate::weapon_animation::WeaponAnimationPose::default();
        let free = free_hand_fixture();
        let before = model.posed_globals_with_weapon_ik(
            &rig.targets(),
            frame,
            &pose,
            free,
            [0., 1.],
            [0., 1., 0., 0.],
        );
        rig.set_root(
            Mat4::from_rotation_translation(
                Quat::from_euler(EulerRot::YXZ, 0.18, -0.15, 0.12),
                vec3(0.08, 0.04, -0.025),
            ) * frame,
        );
        let targets = rig.targets();
        let after = model.posed_globals_with_weapon_ik(
            &targets,
            frame,
            &pose,
            free,
            [0., 1.],
            [0., 1., 0., 0.],
        );
        for name in ["upperarm_l", "lowerarm_l", "hand_l"] {
            let joint = model.names[name];
            assert_eq!(before[joint], after[joint], "released {name} moved");
        }
        let left = model.names["hand_l"];
        let free = free.in_frame(frame);
        assert!(after[left].w_axis.truncate().distance(free.left.position) < 1e-5);
        let right = model.names["hand_r"];
        assert!(
            after[right]
                .w_axis
                .truncate()
                .distance(targets.right.position)
                < 1e-5
        );
        assert!(
            before[right]
                .w_axis
                .truncate()
                .distance(after[right].w_axis.truncate())
                > 0.01
        );
        let expected = Mat4::from_scale_rotation_translation(
            Vec3::splat(0.01),
            targets.right.orientation,
            targets.right.position,
        );
        assert!(after[right].abs_diff_eq(expected, 1e-5));
    }

    #[test]
    fn forearm_roll_preserves_blended_radius_across_half_turn() {
        let mut asset = fixture();
        asset.bones.push(Bone {
            name: "lowerarm_twist_01_l".into(),
            parent: Some(1),
            rest_local: Mat4::from_translation(vec3(0.14, 0., 0.)).to_cols_array(),
            inverse_bind: Mat4::IDENTITY.to_cols_array(),
        });
        let model = ArmModel::new(asset).unwrap();
        let mut previous = None;
        for degrees in [175_f32, 179., 181., 185.] {
            let mut locals = model.rest.clone();
            model.pose_arm(
                &mut locals,
                "l",
                vec3(0.50, 0., 0.),
                vec3(0., -1., 0.),
                Quat::from_rotation_x(degrees.to_radians()),
                Mat4::IDENTITY,
            );
            let g = global_matrices(&locals, &model.parents, Mat4::IDENTITY);
            let lower = g[1];
            let helper = g[6];
            let lower_rotation = lower.to_scale_rotation_translation().1;
            let helper_rotation = helper.to_scale_rotation_translation().1;
            // A representative half/half skin vertex must not collapse toward
            // the axis or jump when the desired roll crosses 180 degrees.
            let radial = (lower_rotation * Vec3::Y + helper_rotation * Vec3::Y) * 0.02;
            assert!(radial.length() > 0.035);
            if let Some(before) = previous {
                assert!(radial.distance(before) < 0.006);
            }
            previous = Some(radial);
        }
    }

    #[test]
    fn full_weapon_constraints_ignore_free_animation_and_preserve_rig_scale() {
        use crate::weapon_ik::WeaponIkRig;
        let frame = Mat4::from_rotation_translation(
            Quat::from_euler(EulerRot::YXZ, -0.18, 0.11, -0.08),
            vec3(0.05, -0.10, -0.30),
        );
        let targets = WeaponIkRig::new(frame).targets();
        let pose = crate::weapon_animation::WeaponAnimationPose::default();
        for scale in [1., 0.5, 0.01] {
            let model = ArmModel::new(scaled_fixture(scale)).unwrap();
            let mut baseline = None;
            for free_frame in [frame, Mat4::from_translation(vec3(4., -6., 5.))] {
                let globals = model.posed_globals_with_weapon_ik(
                    &targets,
                    free_frame,
                    &pose,
                    free_hand_fixture(),
                    [1., 1.],
                    [1., 0., 0., 0.],
                );
                for (side, target) in [("l", targets.left), ("r", targets.right)] {
                    let hand = model.names[&format!("hand_{side}")];
                    let expected = Mat4::from_scale_rotation_translation(
                        Vec3::splat(scale),
                        target.orientation,
                        target.position,
                    );
                    assert!(
                        globals[hand].abs_diff_eq(expected, 1e-5),
                        "side={side} scale={scale} actual={:?} expected={:?}",
                        globals[hand],
                        expected
                    );
                }
                if let Some(before) = &baseline {
                    assert_eq!(before, &globals);
                } else {
                    baseline = Some(globals);
                }
            }
        }
    }

    #[test]
    fn arm_constraint_blends_free_target_once_and_ignores_legacy_grip_channels() {
        use crate::weapon_ik::WeaponIkRig;
        let model = ArmModel::new(scaled_fixture(0.01)).unwrap();
        let frame = Mat4::from_translation(vec3(0.05, -0.10, -0.30));
        let targets = WeaponIkRig::new(frame).targets();
        let free = free_hand_fixture();
        let pose = crate::weapon_animation::WeaponAnimationPose {
            // These finished legacy channels are intentionally unrelated: the
            // explicit free-hand path must never apply them a second time.
            left_grip: [30., -40., 50.],
            right_grip: [-30., 40., -50.],
            left_hand_orientation_xyzw: Some(Quat::from_rotation_z(1.9).to_array()),
            ..Default::default()
        };
        let influences = [0.25, 0.7];
        let globals = model.posed_globals_with_weapon_ik(
            &targets,
            frame,
            &pose,
            free,
            influences,
            [0., 0., 0., 1.],
        );
        let free = free.in_frame(frame);
        for (side, animated, target, alpha) in [
            ("l", free.left, targets.left, influences[0]),
            ("r", free.right, targets.right, influences[1]),
        ] {
            let expected = blend_hand_constraint(animated, target, alpha);
            let double_blended = blend_hand_constraint(expected, target, alpha);
            let hand = globals[model.names[&format!("hand_{side}")]];
            assert!(hand.w_axis.truncate().distance(expected.position) < 1e-5);
            assert!(hand.w_axis.truncate().distance(double_blended.position) > 0.001);
            assert!(hand.abs_diff_eq(
                Mat4::from_scale_rotation_translation(
                    Vec3::splat(0.01),
                    expected.orientation,
                    expected.position,
                ),
                1e-5,
            ));
        }
    }

    #[test]
    fn constraint_influences_do_not_override_independent_finger_contact_modes() {
        use crate::weapon_ik::WeaponIkRig;
        let mut asset = scaled_fixture(0.01);
        for (side, hand, sign) in [("l", 3, 1.), ("r", 6, -1.)] {
            let first = asset.bones.len();
            for segment in 1..=3 {
                asset.bones.push(Bone {
                    name: format!("index_{segment:02}_{side}"),
                    parent: Some(if segment == 1 {
                        hand
                    } else {
                        first + segment - 2
                    }),
                    rest_local: Mat4::from_translation(Vec3::X * sign * 3.5).to_cols_array(),
                    inverse_bind: Mat4::IDENTITY.to_cols_array(),
                });
            }
        }
        let model = ArmModel::new(asset).unwrap();
        let frame = Mat4::from_translation(vec3(0.05, -0.10, -0.30));
        let targets = WeaponIkRig::new(frame).targets();
        let mut pose = crate::weapon_animation::WeaponAnimationPose::default();
        let support = model.posed_globals_with_weapon_ik(
            &targets,
            frame,
            &pose,
            free_hand_fixture(),
            [1., 1.],
            [1., 0., 0., 0.],
        );
        pose.trigger_pull = 1.;
        let open = model.posed_globals_with_weapon_ik(
            &targets,
            frame,
            &pose,
            free_hand_fixture(),
            [1., 1.],
            [0., 0., 0., 1.],
        );
        for side in ["l", "r"] {
            let hand = model.names[&format!("hand_{side}")];
            let fingertip = model.names[&format!("index_03_{side}")];
            assert_eq!(support[hand], open[hand]);
            assert!(!support[fingertip].abs_diff_eq(open[fingertip], 1e-5));
        }
    }

    #[test]
    fn explicit_unconstrained_targets_preserve_legacy_grip_snapshot_matrices() {
        use crate::weapon_ik::WeaponIkRig;
        let model = ArmModel::new(scaled_fixture(0.01)).unwrap();
        let frame = Mat4::from_rotation_translation(
            Quat::from_euler(EulerRot::YXZ, 0.12, -0.16, 0.07),
            vec3(0.05, -0.10, -0.30),
        );
        for (left_grip, modes) in [
            (FITTED_SUPPORT_WRIST, [1., 0., 0., 0.]),
            (FITTED_MAGAZINE_WRIST, [0., 1., 0., 0.]),
            (FITTED_RECEIVER_WRIST, [0., 0., 1., 0.]),
            ([-0.18, -0.17, 0.], [0., 0., 0., 1.]),
        ] {
            let orientation = Quat::from_rotation_x(0.15) * blend_wrist_rotation(modes);
            let pose = crate::weapon_animation::WeaponAnimationPose {
                left_grip,
                left_hand_orientation_xyzw: Some(orientation.to_array()),
                ..Default::default()
            };
            let free = ArmFreeHandPose {
                left: HandPose {
                    position: Vec3::from_array(left_grip),
                    orientation,
                },
                right: HandPose {
                    position: Vec3::from_array(pose.right_grip),
                    orientation: right_wrist_rotation(),
                },
            };
            let legacy = model.posed_globals(frame, &pose, modes);
            let constrained = model.posed_globals_with_weapon_ik(
                &WeaponIkRig::new(frame).targets(),
                frame,
                &pose,
                free,
                [0., 0.],
                modes,
            );
            assert_eq!(legacy, constrained);
        }
    }

    #[test]
    fn fully_anchored_default_pose_preserves_legacy_grip() {
        use crate::weapon_ik::WeaponIkRig;
        let model = ArmModel::new(scaled_fixture(0.01)).unwrap();
        let pose = crate::weapon_animation::WeaponAnimationPose::default();
        for (position, rotation) in [
            (vec3(0.0619, -0.0479, -0.3113), Quat::IDENTITY),
            (vec3(0., -0.03794, -0.2322), Quat::IDENTITY),
            (
                vec3(0.08, -0.07, -0.33),
                Quat::from_euler(EulerRot::YXZ, 0.16, -0.12, 0.21),
            ),
        ] {
            let frame = Mat4::from_rotation_translation(rotation, position);
            let legacy = model.posed_globals(frame, &pose, [1., 0., 0., 0.]);
            let constrained = model.posed_globals_with_weapon_ik(
                &WeaponIkRig::new(frame).targets(),
                Mat4::IDENTITY,
                &pose,
                free_hand_fixture(),
                [1., 1.],
                [1., 0., 0., 0.],
            );
            for (before, after) in legacy.iter().zip(constrained) {
                assert!(before.abs_diff_eq(after, 1e-5));
            }
        }
    }

    #[test]
    fn authored_hand_profiles_have_distinct_contact_and_open_shapes() {
        let support = finger_curls(true, [1., 0., 0., 0.], 0.);
        let magazine = finger_curls(true, [0., 1., 0., 0.], 0.);
        let receiver = finger_curls(true, [0., 0., 1., 0.], 0.);
        let open = finger_curls(true, [0., 0., 0., 1.], 0.);
        assert_ne!(support, magazine);
        assert_ne!(receiver, open);
        for finger in 0..4 {
            assert!(support[finger][1] > receiver[finger][1]);
            assert!(magazine[finger][1] > open[finger][1]);
        }
        let pulled = finger_curls(false, [1., 0., 0., 0.], 1.);
        let released = finger_curls(false, [1., 0., 0., 0.], 0.);
        assert!(pulled[0][1] > released[0][1]);
        assert_eq!(&pulled[1..], &released[1..]);
    }

    #[test]
    fn finger_hinges_are_mirrored_from_bind_geometry() {
        let mut asset = fixture();
        for (side, hand, sign) in [("l", 2, 1.), ("r", 5, -1.)] {
            let first = asset.bones.len();
            for segment in 1..=3 {
                asset.bones.push(Bone {
                    name: format!("index_{segment:02}_{side}"),
                    parent: Some(if segment == 1 {
                        hand
                    } else {
                        first + segment - 2
                    }),
                    rest_local: Mat4::from_translation(Vec3::X * sign * 0.035).to_cols_array(),
                    inverse_bind: Mat4::IDENTITY.to_cols_array(),
                });
            }
        }
        let model = ArmModel::new(asset).unwrap();
        for side in ["l", "r"] {
            let joint = model.names[&format!("index_01_{side}")];
            assert!(model.finger_hinges[&joint].distance(Vec3::Y) < 1e-6);
        }
    }

    #[test]
    fn forearm_twist_preserves_its_pivot_and_inherited_scale() {
        let mut asset = scaled_fixture(0.01);
        let local = Mat4::from_translation(Vec3::X * 14.);
        asset.bones.push(Bone {
            name: "lowerarm_twist_01_l".into(),
            parent: Some(2),
            rest_local: local.to_cols_array(),
            inverse_bind: Mat4::IDENTITY.to_cols_array(),
        });
        let model = ArmModel::new(asset).unwrap();
        let mut locals = model.rest.clone();
        let bind = global_matrices(&locals, &model.parents, Mat4::IDENTITY);
        let shoulder = bind[1].w_axis.truncate();
        model.pose_arm(
            &mut locals,
            "l",
            shoulder + vec3(0.18, -0.12, -0.24),
            shoulder - Vec3::Y,
            Quat::from_rotation_z(1.2),
            Mat4::IDENTITY,
        );
        let posed = global_matrices(&locals, &model.parents, Mat4::IDENTITY);
        let twist = model.names["lowerarm_twist_01_l"];
        let expected_pivot = (posed[2] * local).w_axis.truncate();
        assert!(posed[twist].w_axis.truncate().distance(expected_pivot) < 1e-5);
        assert!((supported_uniform_scale(posed[twist]).unwrap() - 0.01).abs() < 1e-6);
    }

    /// Opt-in local QA only. Never bundles private rig vertices in the source
    /// tree: the caller supplies an absolute input and output directory.
    #[test]
    #[ignore = "requires explicitly supplied private arm asset and output directory"]
    fn export_private_grip_snapshots() {
        use std::fmt::Write;
        let path = std::env::var("VECTOR_RANGE_PRIVATE_ARMS").expect("private arm path");
        let output =
            std::env::var("VECTOR_RANGE_GRIP_SNAPSHOT_DIR").expect("private output directory");
        let mut asset = SkinnedAsset::load(path).unwrap();
        asset.meshes.clear(); // CPU-only skeleton construction: no GPU/context.
        let model = ArmModel::new(asset).unwrap();
        std::fs::create_dir_all(&output).unwrap();
        let camera = std::env::var("VECTOR_RANGE_GRIP_CAMERA").unwrap_or_default();
        let base = match camera.as_str() {
            "ads" => vec3(0., -0.03794, -0.2322),
            "hip" => vec3(0.0619, -0.0479, -0.3113),
            _ => vec3(0.12, -0.02, -0.32),
        };
        let transform = Mat4::from_translation(base);
        for (label, left, modes) in [
            ("support", FITTED_SUPPORT_WRIST, [1., 0., 0., 0.]),
            ("magazine", FITTED_MAGAZINE_WRIST, [0., 1., 0., 0.]),
            ("receiver", FITTED_RECEIVER_WRIST, [0., 0., 1., 0.]),
            ("open", [-0.18, -0.17, 0.0], [0., 0., 0., 1.]),
        ] {
            let pose = crate::weapon_animation::WeaponAnimationPose {
                right_grip: FITTED_RIGHT_WRIST,
                left_grip: left,
                ..Default::default()
            };
            let globals = model.posed_globals(transform, &pose, modes);
            let mut text = format!(
                "{{\"weapon_transform\":{:?},\"joints\":[",
                transform.to_cols_array()
            );
            for (i, global) in globals.iter().enumerate() {
                if i > 0 {
                    text.push(',');
                }
                write!(
                    text,
                    "{{\"name\":\"{}\",\"global\":{:?},\"palette\":{:?}}}",
                    model.asset.bones[i].name,
                    global.to_cols_array(),
                    (*global * model.inverse_bind[i]).to_cols_array()
                )
                .unwrap();
            }
            text.push_str("]}");
            std::fs::write(format!("{output}/{label}.json"), text).unwrap();
            for (side, target) in [("l", left), ("r", FITTED_RIGHT_WRIST)] {
                let actual = globals[model.names[&format!("hand_{side}")]]
                    .w_axis
                    .truncate();
                let error = actual.distance(transform.transform_point3(Vec3::from_array(target)));
                assert!(error < 1e-4, "{label}/{side} wrist error {error}");
                println!("{label}/{side}: wrist target error {:.4} mm", error * 1000.);
            }
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
