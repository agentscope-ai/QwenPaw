//! Tauri command for opening an agent workspace in the file manager.

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    time::Duration,
};

use reqwest::Url;
use serde::Deserialize;
use tauri_plugin_shell::ShellExt;

use crate::backend_download::{parse_headers, parse_local_backend_url};
use crate::workspace_resolver::get_agent_workspace_directory;

const ARTIFACT_RESOLVER_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Deserialize)]
struct ArtifactFileUriResponse {
    uri: String,
}

/// Open a validated workspace directory through the operating system shell.
#[tauri::command]
pub(crate) async fn open_workspace_directory(
    app: tauri::AppHandle,
    agent_id: String,
) -> Result<(), String> {
    let workspace_path = tauri::async_runtime::spawn_blocking(move || {
        let path = get_agent_workspace_directory(&agent_id)?;
        validate_workspace_directory(&path)
    })
    .await
    .map_err(|err| format!("workspace resolver task failed: {err}"))?
    .map_err(|err| {
        log::warn!("[workspace] command rejected: {err}");
        err
    })?;

    open_with_shell(app, workspace_path).await
}

#[tauri::command]
pub(crate) async fn open_workspace_artifact(
    app: tauri::AppHandle,
    url: String,
    headers: Option<HashMap<String, String>>,
) -> Result<(), String> {
    let artifact = resolve_artifact_path(url, headers).await?;
    open_with_shell(app, artifact).await
}

#[tauri::command]
pub(crate) async fn reveal_workspace_artifact(
    url: String,
    headers: Option<HashMap<String, String>>,
) -> Result<(), String> {
    let artifact = resolve_artifact_path(url, headers).await?;
    tauri::async_runtime::spawn_blocking(move || reveal_file(&artifact))
        .await
        .map_err(|err| format!("artifact reveal task failed: {err}"))?
}

async fn resolve_artifact_path(
    url: String,
    headers: Option<HashMap<String, String>>,
) -> Result<PathBuf, String> {
    let resolver_url = parse_local_backend_url(&url)?;
    validate_artifact_resolver_url(&resolver_url)?;
    let request_headers = parse_headers(headers.unwrap_or_default())?;
    let response = reqwest::Client::builder()
        .no_proxy()
        .timeout(ARTIFACT_RESOLVER_TIMEOUT)
        .build()
        .map_err(|err| format!("failed to create artifact resolver client: {err}"))?
        .get(resolver_url)
        .headers(request_headers)
        .send()
        .await
        .map_err(|err| format!("artifact resolver request failed: {err}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "artifact resolver request failed with status code {}",
            response.status()
        ));
    }
    let response_body = response
        .bytes()
        .await
        .map_err(|err| format!("failed to read artifact resolver response: {err}"))?;
    let payload = serde_json::from_slice::<ArtifactFileUriResponse>(&response_body)
        .map_err(|err| format!("invalid artifact resolver response: {err}"))?;
    let artifact = parse_artifact_file_uri(&payload.uri)?;
    tauri::async_runtime::spawn_blocking(move || validate_artifact_file(&artifact))
        .await
        .map_err(|err| format!("artifact resolver task failed: {err}"))?
}

fn validate_artifact_resolver_url(url: &Url) -> Result<(), String> {
    let segments = url
        .path_segments()
        .ok_or("artifact resolver URL is not supported")?
        .collect::<Vec<_>>();
    if segments.len() < 6
        || segments[0] != "api"
        || segments[1] != "agents"
        || segments[2].is_empty()
        || segments[3] != "workspace"
        || segments[4] != "artifact-file-uri"
        || segments[5].is_empty()
    {
        return Err("artifact resolver URL is not supported".into());
    }
    Ok(())
}

fn parse_artifact_file_uri(uri: &str) -> Result<PathBuf, String> {
    let artifact_url =
        Url::parse(uri).map_err(|err| format!("invalid artifact file URI: {err}"))?;
    if artifact_url.scheme() != "file" {
        return Err("artifact resolver did not return a file URI".into());
    }
    artifact_url
        .to_file_path()
        .map_err(|_| "artifact file URI is invalid".to_string())
}

fn validate_artifact_file(path: &Path) -> Result<PathBuf, String> {
    let canonical = path
        .canonicalize()
        .map_err(|err| format!("failed to resolve artifact path: {err}"))?;
    if !canonical.is_file() {
        return Err("artifact path is not a file".into());
    }
    Ok(path.to_path_buf())
}

async fn open_with_shell(
    app: tauri::AppHandle,
    path: PathBuf,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        #[allow(deprecated)]
        app.shell()
            .open(path.to_string_lossy().into_owned(), None)
            .map_err(|err| err.to_string())
    })
    .await
    .map_err(|err| format!("workspace open task failed: {err}"))?
    .map_err(|err| {
        log::warn!("[workspace] open failed: {err}");
        err
    })
}

#[cfg(target_os = "windows")]
fn reveal_file(path: &Path) -> Result<(), String> {
    let mut select_argument = std::ffi::OsString::from("/select,");
    select_argument.push(path.as_os_str());
    std::process::Command::new("explorer.exe")
        .arg(select_argument)
        .spawn()
        .map(|_| ())
        .map_err(|err| err.to_string())
}

#[cfg(target_os = "macos")]
fn reveal_file(path: &Path) -> Result<(), String> {
    std::process::Command::new("open")
        .arg("-R")
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|err| err.to_string())
}

#[cfg(all(unix, not(target_os = "macos")))]
fn reveal_file(path: &Path) -> Result<(), String> {
    let parent = path.parent().ok_or("artifact has no parent directory")?;
    std::process::Command::new("xdg-open")
        .arg(parent)
        .spawn()
        .map(|_| ())
        .map_err(|err| err.to_string())
}

/// Resolve a safe existing directory before passing it to the OS shell.
fn validate_workspace_directory(path: &Path) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err("workspace path must be absolute".into());
    }

    let canonical_path = path
        .canonicalize()
        .map_err(|err| format!("failed to resolve workspace path: {err}"))?;
    if !canonical_path.is_dir() {
        return Err("workspace path is not a directory".into());
    }

    Ok(canonical_path)
}

#[cfg(test)]
mod tests {
    use std::{fs, path::Path};

    use reqwest::Url;
    use tempfile::tempdir;

    use super::{
        parse_artifact_file_uri, validate_artifact_file,
        validate_artifact_resolver_url, validate_workspace_directory,
    };

    #[test]
    fn validates_artifact_resolver_route_shape() {
        let valid = Url::parse(
            "http://127.0.0.1:54377/api/agents/\
             QwenPaw_QA_Agent_0.2/workspace/artifact-file-uri/report.txt\
             ?root=workspace",
        )
        .expect("parse valid resolver URL");
        assert!(validate_artifact_resolver_url(&valid).is_ok());

        for invalid in [
            "http://127.0.0.1:54377/api/agents/agent-1/workspace/\
             artifact-file-uri/",
            "http://127.0.0.1:54377/api/agents/agent-1/other/\
             workspace/artifact-file-uri/report.txt",
            "http://127.0.0.1:54377/api/workspace/\
             artifact-file-uri/report.txt",
        ] {
            let url = Url::parse(invalid).expect("parse invalid route URL");
            assert!(validate_artifact_resolver_url(&url).is_err());
        }
    }

    #[test]
    fn parses_only_file_artifact_uris() {
        let workspace = tempdir().expect("create temporary workspace");
        let file_path = workspace.path().join("artifact.txt");
        fs::write(&file_path, "artifact").expect("create temporary file");
        let uri = Url::from_file_path(&file_path)
            .expect("build file URI")
            .to_string();

        assert_eq!(
            parse_artifact_file_uri(&uri).expect("parse file URI"),
            file_path
        );
        assert!(parse_artifact_file_uri("https://example.com/file").is_err());
        assert!(parse_artifact_file_uri("not a URI").is_err());
    }

    #[test]
    fn artifact_validation_accepts_files_only() {
        let workspace = tempdir().expect("create temporary workspace");
        let file_path = workspace.path().join("artifact.txt");
        fs::write(&file_path, "artifact").expect("create temporary file");

        assert_eq!(
            validate_artifact_file(&file_path).expect("validate file"),
            file_path
        );
        assert!(validate_artifact_file(workspace.path()).is_err());
        assert!(
            validate_artifact_file(&workspace.path().join("missing")).is_err()
        );
    }

    #[test]
    fn accepts_an_existing_absolute_directory() {
        let workspace = tempdir().expect("create temporary workspace");
        let path = workspace
            .path()
            .to_str()
            .expect("temporary path is UTF-8");

        let result = validate_workspace_directory(Path::new(path))
            .expect("existing directory should be valid");

        assert_eq!(
            result,
            workspace.path().canonicalize().expect("canonicalize path")
        );
    }

    #[test]
    fn rejects_relative_paths() {
        assert_eq!(
            validate_workspace_directory(Path::new("relative/path"))
                .unwrap_err(),
            "workspace path must be absolute"
        );
    }

    #[test]
    fn rejects_files_and_missing_directories() {
        let workspace = tempdir().expect("create temporary workspace");
        let file_path = workspace.path().join("artifact.txt");
        fs::write(&file_path, "artifact").expect("create temporary file");

        let file_error = validate_workspace_directory(&file_path).unwrap_err();
        assert_eq!(file_error, "workspace path is not a directory");

        let missing_path = workspace.path().join("missing");
        let missing_error =
            validate_workspace_directory(&missing_path).unwrap_err();
        assert!(
            missing_error.starts_with("failed to resolve workspace path:")
        );
    }
}
