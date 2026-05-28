use tauri_plugin_shell::ShellExt;

// Keep in sync with console/src/utils/openExternalLink.ts.
const SUPPORTED_EXTERNAL_PREFIXES: [&str; 4] = ["http://", "https://", "mailto:", "tel:"];

#[tauri::command]
pub(crate) fn open_external_link(app: tauri::AppHandle, url: String) -> Result<(), String> {
    let url_for_log = external_url_for_log(&url);
    log::info!("[external-link] command requested url={url_for_log}");
    if let Err(err) = validate_external_url(&url) {
        log::warn!("[external-link] command rejected url={url_for_log}: {err}");
        return Err(err);
    }

    #[allow(deprecated)]
    let open_result = app.shell().open(url.clone(), None);

    match open_result {
        Ok(()) => {
            log::info!("[external-link] command succeeded url={url_for_log}");
            Ok(())
        }
        Err(err) => {
            log::warn!("[external-link] open failed url={url_for_log}: {err}");
            Err(err.to_string())
        }
    }
}

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

fn external_url_for_log(url: &str) -> String {
    let Some((scheme, rest)) = url.split_once(':') else {
        return "<missing-scheme>".into();
    };

    let redacted_rest = rest
        .split(['?', '#'])
        .next()
        .unwrap_or_default()
        .chars()
        .take(240)
        .collect::<String>();
    format!("{scheme}:{redacted_rest}")
}
