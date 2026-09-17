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
    use std::sync::Mutex;

    use super::{get_coding_directory, parse_local_backend_url};

    /// Serialize tests that mutate process environment variables.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

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

    #[test]
    fn coding_directory_prefers_agent_json_project_dir() {
        let _guard = ENV_LOCK.lock().unwrap();
        let temp = tempfile::tempdir().unwrap();
        let working_dir = temp.path();

        // Root config.json only contains the profile reference.
        std::fs::write(
            working_dir.join("config.json"),
            serde_json::json!({
                "agents": {
                    "active_agent": "test-agent",
                    "profiles": {
                        "test-agent": {
                            "id": "test-agent",
                            "workspace_dir": working_dir.join("workspaces/test-agent").to_str().unwrap(),
                            "enabled": true,
                        }
                    }
                }
            })
            .to_string(),
        )
        .unwrap();

        // Full agent config with a custom coding project dir.
        let workspace_dir = working_dir.join("workspaces/test-agent");
        std::fs::create_dir_all(&workspace_dir).unwrap();
        let project_dir = working_dir.join("custom-project");
        std::fs::create_dir_all(&project_dir).unwrap();
        std::fs::write(
            workspace_dir.join("agent.json"),
            serde_json::json!({
                "id": "test-agent",
                "workspace_dir": workspace_dir.to_str().unwrap(),
                "coding_mode": {
                    "enabled": true,
                    "project_dir": project_dir.to_str().unwrap(),
                }
            })
            .to_string(),
        )
        .unwrap();

        std::env::set_var("QWENPAW_WORKING_DIR", working_dir);
        let result = get_coding_directory(Some("test-agent")).unwrap();
        std::env::remove_var("QWENPAW_WORKING_DIR");

        assert_eq!(result, project_dir);
    }

    #[test]
    fn coding_directory_falls_back_to_workspace_dir() {
        let _guard = ENV_LOCK.lock().unwrap();
        let temp = tempfile::tempdir().unwrap();
        let working_dir = temp.path();

        std::fs::write(
            working_dir.join("config.json"),
            serde_json::json!({
                "agents": {
                    "active_agent": "test-agent",
                    "profiles": {
                        "test-agent": {
                            "id": "test-agent",
                            "workspace_dir": working_dir.join("workspaces/test-agent").to_str().unwrap(),
                            "enabled": true,
                        }
                    }
                }
            })
            .to_string(),
        )
        .unwrap();

        let workspace_dir = working_dir.join("workspaces/test-agent");
        std::fs::create_dir_all(&workspace_dir).unwrap();

        std::env::set_var("QWENPAW_WORKING_DIR", working_dir);
        let result = get_coding_directory(Some("test-agent")).unwrap();
        std::env::remove_var("QWENPAW_WORKING_DIR");

        assert_eq!(result, workspace_dir);
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
/// The `file_path` parameter is a relative path within the coding project directory.
/// The `agent_id` parameter specifies which agent's workspace to use (from frontend state).
#[tauri::command]
pub(crate) async fn read_workspace_binary_file(
    file_path: String,
    agent_id: Option<String>,
) -> Result<tauri::ipc::Response, String> {
    let absolute_path = resolve_workspace_file_path(&file_path, agent_id.as_deref())?;

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

    Ok(tauri::ipc::Response::new(buffer))
}

/// Resolve a relative workspace file path to an absolute path.
///
/// Reads the QwenPaw config to determine the coding project directory (or workspace
/// directory if no custom project is set), then safely joins the relative path to
/// prevent path traversal attacks.
///
/// If `agent_id` is provided, uses that agent's config; otherwise falls back to
/// the active agent in config.json.
fn resolve_workspace_file_path(
    relative_path: &str,
    agent_id: Option<&str>,
) -> Result<PathBuf, String> {
    if relative_path.trim().is_empty() {
        return Err("file path is empty".into());
    }

    let coding_dir = get_coding_directory(agent_id)?;

    // Safe join: resolve the path and ensure it stays within coding directory
    let target = coding_dir.join(relative_path);
    let canonical_target = target.canonicalize().map_err(|err| {
        format!("failed to resolve file path '{}': {err}", target.display())
    })?;

    let canonical_coding_dir = coding_dir.canonicalize().map_err(|err| {
        format!(
            "failed to resolve coding directory '{}': {err}",
            coding_dir.display()
        )
    })?;

    if !canonical_target.starts_with(&canonical_coding_dir) {
        return Err(format!(
            "path traversal detected: '{}' resolves outside coding directory",
            relative_path
        ));
    }

    Ok(canonical_target)
}

/// Get the coding project directory from QwenPaw configuration.
///
/// Resolution order:
/// 1. `QWENPAW_WORKING_DIR` / `COPAW_WORKING_DIR` environment variable
/// 2. `~/.copaw` (legacy installation)
/// 3. `~/.qwenpaw` (default)
///
/// Then reads the agent profile reference from root `config.json` to locate the
/// agent's workspace directory, and loads the full agent configuration from
/// `workspace/agent.json`:
/// - If `coding_mode.project_dir` is set, use it
/// - Otherwise fall back to `workspace_dir`
///
/// If `agent_id` is None, uses the active agent from config.json.
fn get_coding_directory(agent_id: Option<&str>) -> Result<PathBuf, String> {
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

    // Determine which agent to use
    let target_agent = agent_id.unwrap_or_else(|| {
        config
            .get("agents")
            .and_then(|a| a.get("active_agent"))
            .and_then(|a| a.as_str())
            .unwrap_or("default")
    });

    // Get agent profile reference from root config (contains workspace_dir only).
    // The full agent configuration (including coding_mode.project_dir) is stored
    // in workspace/agent.json.
    let agent_profile = config
        .get("agents")
        .and_then(|a| a.get("profiles"))
        .and_then(|p| p.get(target_agent))
        .ok_or_else(|| format!("agent '{}' not found in config", target_agent))?;

    let workspace_dir = agent_profile
        .get("workspace_dir")
        .and_then(|d| d.as_str())
        .map(|d| expand_tilde(d))
        .unwrap_or_else(|| working_dir.join("workspaces").join(target_agent));

    // Load the full agent config from workspace/agent.json to read
    // coding_mode.project_dir. Fall back to workspace_dir if the file is
    // missing or cannot be parsed, matching the Python backend behavior.
    let agent_config_path = workspace_dir.join("agent.json");
    if agent_config_path.is_file() {
        if let Ok(agent_config_content) = std::fs::read_to_string(&agent_config_path) {
            if let Ok(agent_config) = serde_json::from_str::<serde_json::Value>(&agent_config_content) {
                if let Some(project_dir) = agent_config
                    .get("coding_mode")
                    .and_then(|cm| cm.get("project_dir"))
                    .and_then(|d| d.as_str())
                    .map(|d| expand_tilde(d))
                {
                    return Ok(project_dir);
                }
            }
        }
    }

    Ok(workspace_dir)
}

/// Expand `~` at the start of a path to the user's home directory.
fn expand_tilde(path: &str) -> PathBuf {
    if path.starts_with("~/") || path.starts_with("~\\") {
        if let Some(home) = dirs::home_dir() {
            return home.join(&path[2..]);
        }
    }
    PathBuf::from(path)
}
