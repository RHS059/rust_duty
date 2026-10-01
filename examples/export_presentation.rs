//! Export the actual integrated renderer-independent presentation adapter.
//! Usage: cargo run --example export_presentation > presentation.csv
use vector_range::{
    reference_motion::visual_duration, view_animation::ViewAnimation,
    weapon_animation::AnimationInput,
};
fn main() {
    println!("kind,elapsed_seconds,simulation_ready_seconds,visual_duration_seconds,visual_phase,root_x,root_y,root_z,yaw,pitch,roll,left_x,left_y,left_z,mag_x,mag_y,mag_z,mag_yaw,mag_pitch,mag_roll,old_mag_x,old_mag_y,old_mag_z,old_mag_yaw,old_mag_pitch,old_mag_roll,hand_yaw,hand_pitch,hand_roll,support,magazine,receiver,open,old_mag_visible,held_mag_visible,wrist_qx,wrist_qy,wrist_qz,wrist_qw,held_qx,held_qy,held_qz,held_qw");
    for empty in [false, true] {
        let ready = if empty { 2.359 } else { 2.029 };
        let mut state = ViewAnimation::default();
        for frame in 0..=160 {
            let now = frame as f64 * 1001. / 60000.;
            let sim_phase = (now < ready).then_some((now / ready) as f32);
            let completed = now >= ready;
            let phase = state.presentation_progress(sim_phase, ready as f32, empty, completed, now);
            let pose = state.sample_input(
                AnimationInput {
                    reload_progress: phase,
                    empty_reload: empty,
                    ..Default::default()
                },
                completed,
                now,
            );
            print!(
                "{},{:.9},{:.6},{:.6},{}",
                if empty { "empty" } else { "tactical" },
                now,
                ready,
                visual_duration(empty),
                phase.map_or_else(|| "".into(), |p| format!("{p:.9}"))
            );
            for values in [
                pose.weapon_translation,
                pose.weapon_euler_yxz,
                pose.left_grip,
                pose.magazine_translation,
                pose.magazine_euler_yxz,
                pose.seated_magazine_translation,
                pose.seated_magazine_euler_yxz,
                pose.left_hand_euler_yxz,
            ] {
                for value in values {
                    print!(",{value:.9}");
                }
            }
            for value in pose.left_hand_blend {
                print!(",{value:.9}");
            }
            print!(
                ",{},{}",
                pose.magazine_visibility[0] as u8, pose.magazine_visibility[1] as u8
            );
            for q in [
                vector_range::weapon_animation::effective_hand_orientation(&pose),
                vector_range::weapon_animation::effective_magazine_orientation(&pose),
            ] {
                for value in q {
                    print!(",{value:.9}");
                }
            }
            println!();
        }
    }
}
