//! Persisted desktop settings stored as JSON under the app config directory.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::Manager;

const SETTINGS_FILE: &str = "settings.json";

/// What to do when the user closes the main window.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum CloseAction {
    MinimizeToTray,
    Quit,
}

#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopSettings {
    #[serde(skip_serializing_if = "Option::is_none", default)]
    close_window_action: Option<CloseAction>,
}

fn settings_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_config_dir().map_err(|err| err.to_string())?;
    Ok(dir.join(SETTINGS_FILE))
}

fn load(app: &tauri::AppHandle) -> DesktopSettings {
    settings_path(app)
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

/// Returns the remembered close action, if the user previously chose one.
pub(crate) fn remembered_close_action(app: &tauri::AppHandle) -> Option<CloseAction> {
    load(app).close_window_action
}

/// Persists the user's close action choice to `settings.json`.
pub(crate) fn remember_close_action(
    app: &tauri::AppHandle,
    action: CloseAction,
) -> Result<(), String> {
    let path = settings_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| err.to_string())?;
    }

    let mut settings = load(app);
    settings.close_window_action = Some(action);

    let text = serde_json::to_string_pretty(&settings).map_err(|err| err.to_string())?;
    fs::write(&path, text).map_err(|err| err.to_string())?;
    Ok(())
}
