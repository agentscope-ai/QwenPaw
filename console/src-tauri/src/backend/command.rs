//! Backend command construction for development and packaged builds.

use std::path::{Path, PathBuf};
// StdCommand/Stdio are used by `command_exists` (dev) and
// `resolve_login_shell_path` (packaged macOS).
#[cfg(any(debug_assertions, target_os = "macos"))]
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
    let backend = packaged_backend_executable(app)?;
    let backend_dir = backend
        .parent()
        .ok_or_else(|| format!("backend executable has no parent: {}", backend.display()))?
        .to_path_buf();
    log::info!(
        "[backend] packaged command: {} cwd={}",
        backend.display(),
        backend_dir.display(),
    );
    let mut command = app
        .shell()
        .command(backend)
        .current_dir(&backend_dir)
        .env(path_env_key(), path_with_backend_dir(&backend_dir)?);
    // Bundled standalone Python used by the backend to install third-party
    // plugin dependencies (sys.executable is the frozen backend, not Python).
    if let Some(python) = packaged_python_runtime(app) {
        log::info!("[backend] bundled python runtime: {}", python.display());
        command = command.env(
            "QWENPAW_DESKTOP_PY_RUNTIME",
            python.to_string_lossy().to_string(),
        );
    } else {
        log::warn!(
            "[backend] bundled python runtime not found; plugin dependency \
             installation will be unavailable"
        );
    }
    if let Some(node_runtime) = packaged_node_runtime(app) {
        log::info!("[backend] bundled node runtime: {}", node_runtime.display());
        command = command.env(
            "QWENPAW_DESKTOP_NODE_RUNTIME",
            node_runtime.to_string_lossy().to_string(),
        );
    } else {
        log::warn!("[backend] bundled node runtime not found");
    }
    Ok(command)
}

#[cfg(not(debug_assertions))]
fn packaged_python_runtime(app: &tauri::AppHandle) -> Option<PathBuf> {
    let base = app
        .path()
        .resource_dir()
        .ok()?
        .join("binaries")
        .join("python-runtime")
        .join("python");
    let candidates = if cfg!(windows) {
        vec![base.join("python.exe")]
    } else {
        vec![
            base.join("bin").join("python3"),
            base.join("bin").join("python"),
        ]
    };
    candidates.into_iter().find(|path| path.is_file())
}

#[cfg(not(debug_assertions))]
fn packaged_node_runtime(app: &tauri::AppHandle) -> Option<PathBuf> {
    let root = app
        .path()
        .resource_dir()
        .ok()?
        .join("binaries")
        .join("node-runtime");
    let node = if cfg!(windows) {
        root.join("node.exe")
    } else {
        root.join("bin").join("node")
    };
    node.is_file().then_some(root)
}

#[cfg(not(debug_assertions))]
fn packaged_backend_executable(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let executable_name = if cfg!(windows) {
        "qwenpaw-backend.exe"
    } else {
        "qwenpaw-backend"
    };
    let path = app
        .path()
        .resource_dir()
        .map_err(|err| format!("failed to resolve resource directory: {err}"))?
        .join("binaries")
        .join("qwenpaw-backend")
        .join(executable_name);

    if path.is_file() {
        Ok(path)
    } else {
        Err(format!(
            "backend executable not found at {}",
            path.display()
        ))
    }
}

#[cfg(not(debug_assertions))]
fn path_with_backend_dir(backend_dir: &Path) -> Result<String, String> {
    let mut paths: Vec<PathBuf> = vec![backend_dir.to_path_buf()];
    // GUI apps on macOS inherit launchd's minimal PATH and skip the login
    // shell, so user-installed version managers (Homebrew, nvm, mise, pyenv,
    // asdf — usually exported in ~/.zshrc) are missing. Resolve the PATH a
    // login+interactive shell would produce and prefer it over our own env.
    #[cfg(target_os = "macos")]
    if let Some(login) = resolve_login_shell_path() {
        paths.extend(std::env::split_paths(&login));
    }
    if let Some(existing) = std::env::var_os(path_env_key()) {
        paths.extend(std::env::split_paths(&existing));
    }

    std::env::join_paths(paths)
        .map_err(|err| format!("failed to join backend PATH entries: {err}"))?
        .into_string()
        .map_err(|_| "backend PATH contains non-Unicode data".to_string())
}

#[cfg(all(not(debug_assertions), target_os = "macos"))]
fn wait_child_with_timeout(
    child: &mut std::process::Child,
    timeout: std::time::Duration,
) -> Option<std::process::ExitStatus> {
    use std::time::{Duration, Instant};

    let deadline = Instant::now() + timeout;

    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Some(status),
            Ok(None) => {
                if Instant::now() >= deadline {
                    log::warn!("[backend] login shell PATH resolution timed out");
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(err) => {
                log::warn!("[backend] failed to check login shell status: {err}");
                return None;
            }
        }
    }
}

/// Marker pair wrapping the PATH printed by the login-shell probe: rc
/// files may write arbitrary stdout, so only text between them is trusted.
#[cfg(any(test, all(not(debug_assertions), target_os = "macos")))]
const LOGIN_PATH_BEGIN: &str = "__QWENPAW_LOGIN_PATH_BEGIN__";
#[cfg(any(test, all(not(debug_assertions), target_os = "macos")))]
const LOGIN_PATH_END: &str = "__QWENPAW_LOGIN_PATH_END__";

/// Extracts the marked PATH from raw login-shell stdout, ignoring any
/// noise the rc files printed before or after the markers.
#[cfg(any(test, all(not(debug_assertions), target_os = "macos")))]
fn parse_marked_login_path(stdout: &str) -> Option<String> {
    stdout
        .split_once(LOGIN_PATH_BEGIN)
        .and_then(|(_, rest)| rest.split_once(LOGIN_PATH_END))
        .map(|(path, _)| path.trim())
        .filter(|path| !path.is_empty())
        .map(str::to_owned)
}

/// Spawns a login+interactive shell (`$SHELL -l -i`) and captures its PATH.
///
/// `-i` loads interactive rc files where nvm/mise/asdf/pyenv usually add
/// their shims. PATH is wrapped with markers because rc files may write
/// arbitrary stdout. Timeout/failure falls back to inherited PATH.
#[cfg(all(not(debug_assertions), target_os = "macos"))]
fn resolve_login_shell_path() -> Option<String> {
    use std::time::Duration;

    const TIMEOUT: Duration = Duration::from_secs(5);

    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".to_string());
    let cmd = format!("printf '{LOGIN_PATH_BEGIN}%s{LOGIN_PATH_END}' \"$PATH\"");
    let mut child = StdCommand::new(&shell)
        .args(["-l", "-i", "-c", &cmd])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .stdin(Stdio::null())
        .spawn()
        .ok()?;

    let status = wait_child_with_timeout(&mut child, TIMEOUT)?;
    if !status.success() {
        log::warn!("[backend] login shell exited unsuccessfully: {status}");
        return None;
    }

    let stdout = String::from_utf8(child.wait_with_output().ok()?.stdout).ok()?;
    parse_marked_login_path(&stdout)
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

#[cfg(test)]
mod tests {
    use super::{parse_marked_login_path, LOGIN_PATH_BEGIN, LOGIN_PATH_END};

    #[test]
    fn marked_path_is_extracted_with_noise_before_and_after_markers() {
        let stdout = format!(
            "profile-banner-before\n\
             {LOGIN_PATH_BEGIN}/custom/version-manager/bin:/usr/bin:/bin{LOGIN_PATH_END}\n\
             profile-banner-after\n"
        );
        assert_eq!(
            parse_marked_login_path(&stdout).as_deref(),
            Some("/custom/version-manager/bin:/usr/bin:/bin")
        );
    }

    #[test]
    fn marked_path_is_extracted_from_clean_output() {
        let stdout = format!("{LOGIN_PATH_BEGIN}/usr/bin:/bin{LOGIN_PATH_END}");
        assert_eq!(
            parse_marked_login_path(&stdout).as_deref(),
            Some("/usr/bin:/bin")
        );
    }

    #[test]
    fn output_without_markers_is_rejected() {
        assert_eq!(parse_marked_login_path("profile-banner-only\n"), None);
        assert_eq!(parse_marked_login_path(""), None);
    }
}
