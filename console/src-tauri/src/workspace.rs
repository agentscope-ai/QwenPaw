//! Tauri command for opening an agent workspace in the file manager.

use std::path::{Path, PathBuf};

use tauri_plugin_shell::ShellExt;

use crate::workspace_resolver::{
    get_agent_workspace_directory, resolve_agent_artifact_file_path,
};

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
    agent_id: String,
    file_path: String,
    root: Option<String>,
) -> Result<(), String> {
    let artifact = resolve_artifact_path(agent_id, file_path, root).await?;
    open_with_shell(app, artifact).await
}

#[tauri::command]
pub(crate) async fn reveal_workspace_artifact(
    agent_id: String,
    file_path: String,
    root: Option<String>,
) -> Result<(), String> {
    let artifact = resolve_artifact_path(agent_id, file_path, root).await?;
    tauri::async_runtime::spawn_blocking(move || reveal_file(&artifact))
        .await
        .map_err(|err| format!("artifact reveal task failed: {err}"))?
}

async fn resolve_artifact_path(
    agent_id: String,
    file_path: String,
    root: Option<String>,
) -> Result<PathBuf, String> {
    let artifact_root = root.unwrap_or_else(|| "workspace".into());
    tauri::async_runtime::spawn_blocking(move || {
        resolve_agent_artifact_file_path(
            &file_path,
            &agent_id,
            &artifact_root,
        )
    })
    .await
    .map_err(|err| format!("artifact resolver task failed: {err}"))?
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

    use tempfile::tempdir;

    use super::validate_workspace_directory;

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
