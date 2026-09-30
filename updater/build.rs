fn main() {
    println!(
        "cargo:rustc-env=UPDATER_TARGET={}",
        std::env::var("TARGET").unwrap()
    );
    println!("cargo:rerun-if-env-changed=RUST_DUTY_UPDATE_PUBLIC_KEY");
}
