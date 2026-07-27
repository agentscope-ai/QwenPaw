//! Tauri command for opening an agent workspace in the file manager.

use std::path::PathBuf;

use tauri_plugin_shell::ShellExt;

/// Open a validated workspace directory through the operating system shell.
#[tauri::command]
pub(crate) fn open_workspace_directory(
    app: tauri::AppHandle,
    path: String,
) -> Result<(), String> {
    let workspace_path = validate_workspace_directory(&path).map_err(|err| {
        log::warn!("[workspace] command rejected: {err}");
        err
    })?;

    #[allow(deprecated)]
    let open_result = app
        .shell()
        .open(workspace_path.to_string_lossy().into_owned(), None);

    match open_result {
        Ok(()) => Ok(()),
        Err(err) => {
            log::warn!("[workspace] open failed: {err}");
            Err(err.to_string())
        }
    }
}

/// Resolve a safe existing directory before passing it to the OS shell.
fn validate_workspace_directory(path: &str) -> Result<PathBuf, String> {
    let trimmed_path = path.trim();
    if trimmed_path.is_empty() {
        return Err("workspace path is empty".into());
    }
    if trimmed_path != path {
        return Err(
            "workspace path has leading or trailing whitespace".into(),
        );
    }
    if trimmed_path.chars().any(char::is_control) {
        return Err("workspace path contains control characters".into());
    }

    let workspace_path = PathBuf::from(trimmed_path);
    if !workspace_path.is_absolute() {
        return Err("workspace path must be absolute".into());
    }

    let canonical_path = workspace_path
        .canonicalize()
        .map_err(|err| format!("failed to resolve workspace path: {err}"))?;
    if !canonical_path.is_dir() {
        return Err("workspace path is not a directory".into());
    }

    Ok(canonical_path)
}

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::tempdir;

    use super::validate_workspace_directory;

    #[test]
    fn accepts_an_existing_absolute_directory() {
        let workspace = tempdir().expect("create temporary workspace");
        let path = workspace
            .path()
            .to_str()
            .expect("temporary path is UTF-8");

        let result = validate_workspace_directory(path)
            .expect("existing directory should be valid");

        assert_eq!(
            result,
            workspace.path().canonicalize().expect("canonicalize path")
        );
    }

    #[test]
    fn rejects_empty_ambiguous_and_relative_paths() {
        assert_eq!(
            validate_workspace_directory("").unwrap_err(),
            "workspace path is empty"
        );
        assert_eq!(
            validate_workspace_directory(" relative/path").unwrap_err(),
            "workspace path has leading or trailing whitespace"
        );
        assert_eq!(
            validate_workspace_directory("relative/path").unwrap_err(),
            "workspace path must be absolute"
        );
        assert_eq!(
            validate_workspace_directory("relative\npath").unwrap_err(),
            "workspace path contains control characters"
        );
    }

    #[test]
    fn rejects_files_and_missing_directories() {
        let workspace = tempdir().expect("create temporary workspace");
        let file_path = workspace.path().join("artifact.txt");
        fs::write(&file_path, "artifact").expect("create temporary file");

        let file_error = validate_workspace_directory(
            file_path.to_str().expect("file path is UTF-8"),
        )
        .unwrap_err();
        assert_eq!(file_error, "workspace path is not a directory");

        let missing_path = workspace.path().join("missing");
        let missing_error = validate_workspace_directory(
            missing_path.to_str().expect("missing path is UTF-8"),
        )
        .unwrap_err();
        assert!(
            missing_error.starts_with("failed to resolve workspace path:")
        );
    }
}
