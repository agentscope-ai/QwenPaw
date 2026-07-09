//! Native downloads for files served by the bundled local backend.

use std::{collections::HashMap, net::IpAddr, path::PathBuf, time::Duration};

use futures_util::TryStreamExt;
use reqwest::{
    header::{HeaderMap, HeaderName, HeaderValue},
    Url,
};
use serde::Deserialize;
use tokio::{
    fs::File,
    io::{AsyncReadExt, AsyncWriteExt, BufWriter},
};

const BACKEND_DOWNLOAD_CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const BACKEND_DOWNLOAD_TOTAL_TIMEOUT: Duration = Duration::from_secs(30 * 60);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DownloadBackendFileRequest {
    url: String,
    file_path: String,
    headers: Option<HashMap<String, String>>,
}

/// Stream a local backend response to the user-selected file path without using system proxies.
#[tauri::command]
pub(crate) async fn download_backend_file(
    request: DownloadBackendFileRequest,
) -> Result<(), String> {
    let url = parse_local_backend_url(&request.url)?;
    let file_path = parse_file_path(&request.file_path)?;
    let headers = parse_headers(request.headers.unwrap_or_default())?;

    let response = reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(BACKEND_DOWNLOAD_CONNECT_TIMEOUT)
        .timeout(BACKEND_DOWNLOAD_TOTAL_TIMEOUT)
        .build()
        .map_err(|err| format!("failed to create download client: {err}"))?
        .get(url)
        .headers(headers)
        .send()
        .await
        .map_err(|err| format!("download request failed: {err}"))?;

    if !response.status().is_success() {
        return Err(format!(
            "download request failed with status code {}",
            response.status()
        ));
    }

    let mut file = BufWriter::new(
        File::create(&file_path)
            .await
            .map_err(|err| format!("failed to create file: {err}"))?,
    );
    let mut stream = response.bytes_stream();

    while let Some(chunk) = stream
        .try_next()
        .await
        .map_err(|err| format!("failed to read response stream: {err}"))?
    {
        file.write_all(&chunk)
            .await
            .map_err(|err| format!("failed to write file: {err}"))?;
    }

    file.flush()
        .await
        .map_err(|err| format!("failed to flush file: {err}"))
}

fn parse_local_backend_url(url: &str) -> Result<Url, String> {
    let parsed = Url::parse(url).map_err(|err| format!("invalid download URL: {err}"))?;
    if parsed.scheme() != "http" {
        return Err("download URL protocol is not supported".into());
    }
    if !is_loopback_host(&parsed) {
        return Err("download URL must target the local backend".into());
    }
    Ok(parsed)
}

fn is_loopback_host(url: &Url) -> bool {
    match url.host_str() {
        Some(host) if host.eq_ignore_ascii_case("localhost") => true,
        Some(host) => host
            .trim_matches(['[', ']'])
            .parse::<IpAddr>()
            .map(|ip| ip.is_loopback())
            .unwrap_or(false),
        None => false,
    }
}

fn parse_file_path(file_path: &str) -> Result<PathBuf, String> {
    if file_path.trim().is_empty() {
        return Err("download file path is empty".into());
    }
    Ok(PathBuf::from(file_path))
}

fn parse_headers(headers: HashMap<String, String>) -> Result<HeaderMap, String> {
    let mut header_map = HeaderMap::new();
    for (name, value) in headers {
        let header_name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|err| format!("invalid download header name: {err}"))?;
        let header_value = HeaderValue::from_str(&value)
            .map_err(|err| format!("invalid download header value: {err}"))?;
        header_map.insert(header_name, header_value);
    }
    Ok(header_map)
}

#[cfg(test)]
mod tests {
    use super::parse_local_backend_url;

    #[test]
    fn accepts_loopback_backend_urls() {
        assert!(parse_local_backend_url("http://127.0.0.1:54377/api/backups/id/export").is_ok());
        assert!(parse_local_backend_url("http://localhost:54377/api/workspace/download").is_ok());
        assert!(parse_local_backend_url("http://[::1]:54377/api/workspace/download").is_ok());
    }

    #[test]
    fn rejects_remote_download_urls() {
        assert!(parse_local_backend_url("https://example.com/file.zip").is_err());
        assert!(parse_local_backend_url("http://192.168.1.20/file.zip").is_err());
    }

    #[test]
    fn rejects_non_http_download_urls() {
        assert!(parse_local_backend_url("file:///C:/tmp/backup.zip").is_err());
        assert!(parse_local_backend_url("mailto:support@example.com").is_err());
    }
}

// ---------------------------------------------------------------------------
// Local file reading for offline binary file preview
// ---------------------------------------------------------------------------

/// Maximum file size for binary preview (50 MB, matching the Python backend limit).
const BINARY_FILE_MAX_BYTES: u64 = 50 * 1024 * 1024;

/// Read a binary file from the local workspace for offline preview.
///
/// This command enables the frontend to display images, PDFs, and other binary
/// files in the code editor preview mode when the backend API is unavailable
/// (e.g., offline desktop usage).
///
/// The `file_path` parameter is a relative path within the workspace. This
/// function resolves it to an absolute path by reading the QwenPaw config.
#[tauri::command]
pub(crate) async fn read_workspace_binary_file(file_path: String) -> Result<Vec<u8>, String> {
    let absolute_path = resolve_workspace_file_path(&file_path)?;

    if !absolute_path.is_file() {
        return Err(format!("path is not a file: {}", absolute_path.display()));
    }

    // Enforce size limit to prevent OOM on large files
    let metadata = tokio::fs::metadata(&absolute_path)
        .await
        .map_err(|err| format!("failed to read file metadata: {err}"))?;

    if metadata.len() > BINARY_FILE_MAX_BYTES {
        return Err(format!(
            "file too large for preview ({} MB > {} MB limit)",
            metadata.len() / 1024 / 1024,
            BINARY_FILE_MAX_BYTES / 1024 / 1024,
        ));
    }

    let mut file = File::open(&absolute_path)
        .await
        .map_err(|err| format!("failed to open file: {err}"))?;

    let mut buffer = Vec::with_capacity(metadata.len() as usize);
    file.read_to_end(&mut buffer)
        .await
        .map_err(|err| format!("failed to read file: {err}"))?;

    Ok(buffer)
}

/// Resolve a relative workspace file path to an absolute path.
///
/// Reads the QwenPaw config to determine the workspace directory, then safely
/// joins the relative path to prevent path traversal attacks.
fn resolve_workspace_file_path(relative_path: &str) -> Result<PathBuf, String> {
    if relative_path.trim().is_empty() {
        return Err("file path is empty".into());
    }

    let workspace_dir = get_workspace_directory()?;

    // Safe join: resolve the path and ensure it stays within workspace
    let target = workspace_dir.join(relative_path);
    let canonical_target = target.canonicalize().map_err(|err| {
        format!("failed to resolve file path '{}': {err}", target.display())
    })?;

    let canonical_workspace = workspace_dir.canonicalize().map_err(|err| {
        format!(
            "failed to resolve workspace directory '{}': {err}",
            workspace_dir.display()
        )
    })?;

    if !canonical_target.starts_with(&canonical_workspace) {
        return Err(format!(
            "path traversal detected: '{}' resolves outside workspace",
            relative_path
        ));
    }

    Ok(canonical_target)
}

/// Get the workspace directory from QwenPaw configuration.
///
/// Resolution order:
/// 1. `QWENPAW_WORKING_DIR` / `COPAW_WORKING_DIR` environment variable
/// 2. `~/.copaw` (legacy installation)
/// 3. `~/.qwenpaw` (default)
///
/// Then reads the active agent's `workspace_dir` from `config.json`.
fn get_workspace_directory() -> Result<PathBuf, String> {
    let working_dir = if let Ok(dir) = std::env::var("QWENPAW_WORKING_DIR") {
        PathBuf::from(dir)
    } else if let Ok(dir) = std::env::var("COPAW_WORKING_DIR") {
        PathBuf::from(dir)
    } else {
        let home = dirs::home_dir().ok_or("failed to get home directory")?;
        let copaw_legacy = home.join(".copaw");
        if copaw_legacy.exists() {
            copaw_legacy
        } else {
            home.join(".qwenpaw")
        }
    };

    let config_path = working_dir.join("config.json");
    if !config_path.exists() {
        return Ok(working_dir);
    }

    let config_content = std::fs::read_to_string(&config_path)
        .map_err(|err| format!("failed to read config.json: {err}"))?;

    let config: serde_json::Value = serde_json::from_str(&config_content)
        .map_err(|err| format!("failed to parse config.json: {err}"))?;

    let active_agent = config
        .get("agents")
        .and_then(|a| a.get("active_agent"))
        .and_then(|a| a.as_str())
        .unwrap_or("default");

    let workspace_dir = config
        .get("agents")
        .and_then(|a| a.get("profiles"))
        .and_then(|p| p.get(active_agent))
        .and_then(|a| a.get("workspace_dir"))
        .and_then(|d| d.as_str())
        .map(|d| {
            if d.starts_with("~/") || d.starts_with("~\\") {
                if let Some(home) = dirs::home_dir() {
                    return home.join(&d[2..]);
                }
            }
            PathBuf::from(d)
        })
        .unwrap_or_else(|| working_dir.join("workspaces").join(active_agent));

    Ok(workspace_dir)
}
