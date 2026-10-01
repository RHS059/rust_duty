//! Emit current pure reference-root transforms at requested normalized phases.
fn main() {
    let mut args = std::env::args().skip(1);
    let empty = args.next().as_deref() == Some("empty");
    for value in args {
        let phase: f32 = value.parse().expect("phase");
        let r = vector_range::reference_motion::sample_reload_root(phase, empty);
        print!("{phase}");
        for v in r.translation.into_iter().chain(r.euler_yxz) {
            print!(",{v}");
        }
        println!();
    }
}
