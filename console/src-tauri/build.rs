fn main() {
    // The plugin catalog host is baked in at compile time, so a change to it
    // has to invalidate the build; cargo would otherwise reuse a binary
    // carrying the previous value.
    println!("cargo:rerun-if-env-changed=QWENPAW_PLUGIN_CDN");

    // `cargo check`/`cargo test` validate Tauri resources before the packaging
    // scripts have generated the PyInstaller sidecar. Keep release builds strict
    // while allowing local Rust checks to run in a clean checkout.
    if std::env::var("PROFILE").as_deref() != Ok("release") {
        let _ = std::fs::create_dir_all("binaries/qwenpaw-backend");
    }

    tauri_build::build()
}
