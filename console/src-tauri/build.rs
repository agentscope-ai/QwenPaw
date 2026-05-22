fn main() {
    // `cargo check`/`cargo test` validate Tauri resources before the packaging
    // scripts have generated the PyInstaller sidecar. Keep release builds strict
    // while allowing local Rust checks to run in a clean checkout.
    if std::env::var("PROFILE").as_deref() != Ok("release") {
        let _ = std::fs::create_dir_all("binaries/qwenpaw-backend");
    }

    tauri_build::build()
}
