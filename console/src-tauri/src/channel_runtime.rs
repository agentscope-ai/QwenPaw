//! Trusted readable channel support paths for the packaged Python backend.

#[cfg(not(debug_assertions))]
use tauri::Manager;

#[cfg(debug_assertions)]
pub(crate) fn backend_environment(_app: &tauri::AppHandle) -> Vec<(String, String)> {
    Vec::new()
}

#[cfg(not(debug_assertions))]
pub(crate) fn backend_environment(app: &tauri::AppHandle) -> Vec<(String, String)> {
    let root = match app.path().resource_dir() {
        Ok(root) => root.join("binaries").join("channel-runtime"),
        Err(error) => {
            log::error!("[channel-runtime] resource directory unavailable: {error}");
            return Vec::new();
        }
    };
    let site = root.join("site").to_string_lossy().to_string();
    vec![
        (
            "QWENPAW_CHANNEL_RUNTIME_MANIFEST".into(),
            root.join("runtime.json").to_string_lossy().to_string(),
        ),
        ("QWENPAW_CHANNEL_SUPPORT_ROOT".into(), site.clone()),
        (
            "QWENPAW_CHANNEL_DEPENDENCY_PATHS".into(),
            serde_json::json!([site]).to_string(),
        ),
    ]
}
