//! Actual bound-pack endpoint, contact, and continuous-composition checks.
use macroquad::math::Mat4;
use vector_range::{
    animation_manifest::AnimationManifest,
    authored_walk::WalkPoseLayer,
    viewmodel_animation::AnimationSet,
};
#[test]
fn bound_walk_layer_preserves_source_endpoints_and_weapon_relative_hand_contacts() {
    let Some(path) = std::env::var_os("RUST_DUTY_ANIMATION_MANIFEST") else { return; };
    let manifest = AnimationManifest::load(std::path::Path::new(&path)).unwrap();
    let reference = manifest.regular_walk.as_ref().unwrap();
    let (set, skin, _) = AnimationSet::load_with_companions(&reference.asset).unwrap();
    let layer = WalkPoseLayer::new(&set, &set, &manifest.locomotion.ready_clip,
        manifest.walk_anchor_actor.as_deref().unwrap()).unwrap();
    let ready = set.sample_clamped(&manifest.locomotion.ready_clip, 0.).unwrap();
    let anchor = set.actors().iter().position(|a| Some(a.name.as_str()) == manifest.walk_anchor_actor.as_deref()).unwrap();
    let wrists: Vec<_> = set.bones().iter().enumerate()
        .filter(|(_, b)| b.name == "hand_l" || b.name == "hand_r")
        .map(|(i, _)| i).collect();
    assert_eq!(wrists.len(), 2);
    let ready_global = set.bone_globals(&ready, Mat4::IDENTITY).unwrap();
    let grip: Vec<_> = wrists.iter().map(|&i| ready.actor_globals[anchor].matrix().inverse() * ready_global[i]).collect();
    let mut max_grip_error = 0_f32;
    for phase in 0..89 {
        let walk = set.sample(&reference.clip, phase as f32 / 120.).unwrap();
        assert_eq!(layer.pose(&set, &ready, &walk, 0., 0.).unwrap(), ready);
        let full = layer.pose(&set, &ready, &walk, 1., 0.).unwrap();
        let expected = set.bone_globals(&walk, Mat4::IDENTITY).unwrap();
        let actual = set.bone_globals(&full, Mat4::IDENTITY).unwrap();
        for (a, b) in actual.iter().zip(&expected) {
            assert!(a.abs_diff_eq(*b, 3e-5), "full hip walk must retain the bound authored pose");
        }
        for (a, b) in full.actor_globals.iter().zip(&walk.actor_globals) {
            assert!(a.matrix().abs_diff_eq(b.matrix(), 3e-5));
        }
        for step in 1..20 {
            let pose = layer.pose(&set, &ready, &walk, step as f32 / 20., 0.).unwrap();
            set.skin_palette(&pose, &skin.bones, Mat4::IDENTITY).unwrap();
            let globals = set.bone_globals(&pose, Mat4::IDENTITY).unwrap();
            for (&index, reference) in wrists.iter().zip(&grip) {
                let contact = pose.actor_globals[anchor].matrix().inverse() * globals[index];
                max_grip_error = max_grip_error.max(contact.w_axis.truncate().distance(reference.w_axis.truncate()));
            }
        }
    }
    assert!(max_grip_error < 0.0001, "walk blending changed grip by {max_grip_error} metres");
    assert!(layer.pose(&set, &ready, &ready, f32::NAN, 0.).is_err());
    assert!(layer.pose(&set, &ready, &ready, 0.5, 1.1).is_err());
    assert!(WalkPoseLayer::new(&set, &set, &manifest.locomotion.ready_clip, "missing").is_err());
    println!("Bound walk endpoint and grip sweep: max wrist translation error {max_grip_error} m");
}
