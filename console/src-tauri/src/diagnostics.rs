//! Temporary desktop diagnostics used to capture native download failures.

use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DownloadFailureContext {
    runtime: String,
    url: String,
    filename: String,
    error: String,
}

#[tauri::command]
pub(crate) fn log_download_failure(context: DownloadFailureContext) {
    log::warn!(
        "[download] failure runtime={} url={} filename={} error={}",
        context.runtime,
        url_for_log(&context.url),
        context.filename,
        context.error,
    );
}

fn url_for_log(url: &str) -> String {
    match url.split_once('?') {
        Some((base, _)) => format!("{base}?<redacted>"),
        None => url.to_string(),
    }
}
