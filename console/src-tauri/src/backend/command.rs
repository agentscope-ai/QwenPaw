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
            "[backend] dev command: uv run python -m qwenpaw.tauri.entry cwd={}",
            repo_root.display(),
        );
        app.shell()
            .command("uv")
            .args(["run", "python", "-m", "qwenpaw.tauri.entry"])
            .current_dir(repo_root)
            .env("PYTHONPATH", source_path.display().to_string())
    } else {
        let (python, prefix_args) = python_command(&repo_root);
        let mut args = prefix_args;
        args.extend(["-m", "qwenpaw.tauri.entry"]);
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
    let backend = packaged_backend(app)?;
    let backend_path = backend_env_path(&backend.env_dir)?;
    log::info!(
        "[backend] packaged command: {} -u -m qwenpaw.tauri.entry cwd={}",
        backend.python.display(),
        backend.backend_dir.display(),
    );
    Ok(app
        .shell()
        .command(backend.python)
        .args(["-u", "-m", "qwenpaw.tauri.entry"])
        .current_dir(backend.backend_dir)
        .env("PYTHONNOUSERSITE", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("QWENPAW_DESKTOP_APP", "1")
        .env("PATH", backend_path))
}

#[cfg(not(debug_assertions))]
struct PackagedBackend {
    backend_dir: PathBuf,
    env_dir: PathBuf,
    python: PathBuf,
}

#[cfg(not(debug_assertions))]
fn packaged_backend(app: &tauri::AppHandle) -> Result<PackagedBackend, String> {
    let backend_dir = app
        .path()
        .resource_dir()
        .map_err(|err| format!("failed to resolve resource directory: {err}"))?
        .join("binaries")
        .join("qwenpaw-backend");
    let env_dir = backend_dir.join("env");
    let python = if cfg!(windows) {
        env_dir.join("pythonw.exe")
    } else {
        env_dir.join("bin").join("python")
    };

    if python.is_file() {
        Ok(PackagedBackend {
            backend_dir,
            env_dir,
            python,
        })
    } else {
        Err(format!(
            "packaged backend Python not found at {}",
            python.display()
        ))
    }
}

#[cfg(not(debug_assertions))]
fn backend_env_path(env_dir: &Path) -> Result<String, String> {
    let mut paths = Vec::new();
    if cfg!(windows) {
        paths.push(env_dir.to_path_buf());
        paths.push(env_dir.join("Scripts"));
    } else {
        paths.push(env_dir.join("bin"));
    }
    if let Some(existing) = std::env::var_os("PATH") {
        paths.extend(std::env::split_paths(&existing));
    }
    std::env::join_paths(paths)
        .map_err(|err| format!("failed to build backend PATH: {err}"))
        .map(|path| path.to_string_lossy().into_owned())
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
