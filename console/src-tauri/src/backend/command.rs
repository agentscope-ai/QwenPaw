//! Backend command construction for development and packaged builds.

#[cfg(debug_assertions)]
use std::path::{Path, PathBuf};
#[cfg(debug_assertions)]
use std::process::{Command as StdCommand, Stdio};

use tauri_plugin_shell::{process::Command, ShellExt};

/// Builds the command used to start the Python backend sidecar.
#[cfg(debug_assertions)]
pub(super) fn create(app: &tauri::AppHandle) -> Result<Command, String> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let source_path = repo_root.join("src");
    let command = if command_exists("uv") {
        app.shell()
            .command("uv")
            .args(["run", "python", "-m", "qwenpaw.desktop_entry"])
            .current_dir(repo_root)
            .env("PYTHONPATH", source_path.display().to_string())
    } else {
        let (python, prefix_args) = python_command(&repo_root);
        let mut args = prefix_args;
        args.extend(["-m", "qwenpaw.desktop_entry"]);
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
    app.shell()
        .sidecar("qwenpaw-backend")
        .map_err(|err| format!("failed to find sidecar binary: {err}"))
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
