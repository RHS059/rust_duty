fn main() {
    println!(
        "cargo:rustc-env=UPDATER_TARGET={}",
        std::env::var("TARGET").unwrap()
    );
    let notices = std::path::Path::new("notices/THIRD_PARTY_UPDATER_LICENSES.txt");
    println!("cargo:rerun-if-changed={}", notices.display());
    let text = std::fs::read_to_string(notices).unwrap_or_else(|_| {
        "DEVELOPMENT BUILD: dependency notices have not been generated.".into()
    });
    let destination =
        std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("UPDATER_LICENSES.txt");
    std::fs::write(destination, text).unwrap();
}
