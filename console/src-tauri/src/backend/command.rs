//! Backend command construction for development and packaged builds.

use std::path::{Path, PathBuf};
#[cfg(debug_assertions)]
use std::process::{Command as StdCommand, Stdio};

#[cfg(not(debug_assertions))]
use tauri::Manager;
use tauri_plugin_shell::{process::Command, ShellExt};

/// Builds the command used to start the Python backend sidecar.
#[cfg(debug_assertions)]
pub(super) fn create(app: &tauri::AppHandle) -> Result<Command, String> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source_path = repo_root.join("src");
    let command = if command_exists("uv") {
        log::info!(
            "[backend] dev command: uv run python -m qwenpaw tauri-backend cwd={}",
            repo_root.display(),
        );
        app.shell()
            .command("uv")
            .args(["run", "python", "-m", "qwenpaw", "tauri-backend"])
            .current_dir(repo_root)
            .env("PYTHONPATH", source_path.display().to_string())
    } else {
        let (python, prefix_args) = python_command(&repo_root);
        let mut args = prefix_args;
        args.extend(["-m", "qwenpaw", "tauri-backend"]);
        log::info!(
            "[backend] dev command: {} {} cwd={}",
            python,
            args.join(" "),
            repo_root.display(),
        );
        app.shell()
            .command(python)
            .args(args)
            .current_dir(repo_root)
            .env("PYTHONPATH", source_path.display().to_string())
    };
    Ok(command)
}

/// Builds the command used to start the packaged Python backend sidecar.
#[cfg(not(debug_assertions))]
pub(super) fn create(app: &tauri::AppHandle) -> Result<Command, String> {
    let python = packaged_backend_python(app)?;
    let backend_dir = python_env_root(&python)?;
    log::info!(
        "[backend] packaged command: {} -u -m qwenpaw tauri-backend cwd={}",
        python.display(),
        backend_dir.display(),
    );
    let command = app
        .shell()
        .command(python)
        .args(["-u", "-m", "qwenpaw", "tauri-backend"])
        .current_dir(&backend_dir)
        .env("PYTHONNOUSERSITE", "1")
        .env(path_env_key(), path_with_backend_env(&backend_dir)?);

    #[cfg(not(windows))]
    let command = command.env("PYTHONHOME", backend_dir.display().to_string());

    Ok(command)
}

#[cfg(not(debug_assertions))]
fn packaged_backend_python(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let backend_dir = app
        .path()
        .resource_dir()
        .map_err(|err| format!("failed to resolve resource directory: {err}"))?
        .join("binaries")
        .join("qwenpaw-backend");

    let path = if cfg!(windows) {
        backend_dir.join("python.exe")
    } else {
        backend_dir.join("bin").join("python")
    };

    if path.is_file() {
        Ok(path)
    } else {
        Err(format!("backend Python not found at {}", path.display()))
    }
}

#[cfg(not(debug_assertions))]
fn python_env_root(python: &Path) -> Result<PathBuf, String> {
    let parent = python
        .parent()
        .ok_or_else(|| format!("backend Python has no parent: {}", python.display()))?;
    if parent
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| matches!(name.to_ascii_lowercase().as_str(), "bin" | "scripts"))
    {
        parent
            .parent()
            .map(Path::to_path_buf)
            .ok_or_else(|| format!("backend Python env root missing: {}", python.display()))
    } else {
        Ok(parent.to_path_buf())
    }
}

#[cfg(not(debug_assertions))]
fn path_with_backend_env(backend_dir: &Path) -> Result<String, String> {
    let mut paths = backend_path_entries(backend_dir);
    if let Some(existing) = std::env::var_os(path_env_key()) {
        paths.extend(std::env::split_paths(&existing));
    }

    std::env::join_paths(paths)
        .map_err(|err| format!("failed to join backend PATH entries: {err}"))?
        .into_string()
        .map_err(|_| "backend PATH contains non-Unicode data".to_string())
}

#[cfg(all(not(debug_assertions), windows))]
fn backend_path_entries(backend_dir: &Path) -> Vec<PathBuf> {
    vec![
        backend_dir.to_path_buf(),
        backend_dir.join("Scripts"),
        backend_dir.join("Library").join("bin"),
    ]
}

#[cfg(all(not(debug_assertions), not(windows)))]
fn backend_path_entries(backend_dir: &Path) -> Vec<PathBuf> {
    vec![backend_dir.join("bin"), backend_dir.to_path_buf()]
}

#[cfg(all(not(debug_assertions), windows))]
fn path_env_key() -> &'static str {
    "Path"
}

#[cfg(all(not(debug_assertions), not(windows)))]
fn path_env_key() -> &'static str {
    "PATH"
}

#[cfg(debug_assertions)]
fn command_exists(command: &str) -> bool {
    StdCommand::new(command)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| status.success())
}

#[cfg(debug_assertions)]
fn local_python(repo_root: &Path) -> Option<String> {
    let candidates = if cfg!(windows) {
        vec![
            repo_root.join(".venv/Scripts/python.exe"),
            repo_root.join("venv/Scripts/python.exe"),
        ]
    } else {
        vec![
            repo_root.join(".venv/bin/python"),
            repo_root.join("venv/bin/python"),
        ]
    };

    candidates
        .into_iter()
        .find(|path| path.is_file())
        .map(|path| path.display().to_string())
}

#[cfg(debug_assertions)]
fn python_command(repo_root: &Path) -> (String, Vec<&'static str>) {
    if let Some(local) = local_python(repo_root) {
        return (local, vec![]);
    }
    #[cfg(windows)]
    {
        if command_exists("py") {
            return ("py".to_string(), vec!["-3"]);
        }
    }
    if command_exists("python3") {
        ("python3".to_string(), vec![])
    } else {
        ("python".to_string(), vec![])
    }
}
