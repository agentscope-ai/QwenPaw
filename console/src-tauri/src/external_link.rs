//! Tauri command for opening vetted external URLs in the system browser.

use tauri_plugin_shell::ShellExt;

// Keep in sync with console/src/utils/openExternalLink.ts.
const SUPPORTED_EXTERNAL_PREFIXES: [&str; 4] = ["http://", "https://", "mailto:", "tel:"];

/// Validate and open an external URL through the OS shell.
#[tauri::command]
pub(crate) fn open_external_link(app: tauri::AppHandle, url: String) -> Result<(), String> {
    if let Err(err) = validate_external_url(&url) {
        log::warn!("[external-link] command rejected: {err}");
        return Err(err);
    }

    #[allow(deprecated)]
    let open_result = app.shell().open(url.clone(), None);

    match open_result {
        Ok(()) => Ok(()),
        Err(err) => {
            log::warn!("[external-link] open failed: {err}");
            Err(err.to_string())
        }
    }
}

/// Reject empty, ambiguous, or unsupported URL inputs before calling shell.open.
fn validate_external_url(url: &str) -> Result<(), String> {
    let trimmed_url = url.trim();
    if trimmed_url.is_empty() {
        return Err("external link is empty".into());
    }
    if trimmed_url != url {
        return Err("external link has leading or trailing whitespace".into());
    }
    if trimmed_url.chars().any(char::is_control) {
        return Err("external link contains control characters".into());
    }

    let lowercase_url = trimmed_url.to_ascii_lowercase();
    if SUPPORTED_EXTERNAL_PREFIXES
        .iter()
        .any(|prefix| lowercase_url.starts_with(prefix))
    {
        return Ok(());
    }

    Err("external link protocol is not supported".into())
}
