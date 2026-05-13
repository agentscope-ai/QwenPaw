use std::net::TcpListener;
#[cfg(debug_assertions)]
use std::path::{Path, PathBuf};
#[cfg(debug_assertions)]
use std::process::{Command as StdCommand, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_log::RotationStrategy;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

#[derive(Default)]
struct BackendProcess(Mutex<Option<CommandChild>>);

#[derive(Default)]
struct BackendPort(Mutex<Option<u16>>);

#[derive(Default)]
struct BackendStartupError(Mutex<Option<String>>);

impl BackendProcess {
    fn set(&self, child: CommandChild) {
        *self.0.lock().expect("backend process lock poisoned") = Some(child);
    }

    fn clear(&self) {
        self.0
            .lock()
            .expect("backend process lock poisoned")
            .take();
    }

    fn kill(&self) {
        let child = self
            .0
            .lock()
            .expect("backend process lock poisoned")
            .take();
        if let Some(child) = child {
            if let Err(err) = child.kill() {
                log::warn!("[backend] failed to stop process: {err}");
            }
        }
    }
}

impl BackendPort {
    fn set(&self, port: u16) {
        *self.0.lock().expect("backend port lock poisoned") = Some(port);
    }

    fn get(&self) -> Option<u16> {
        *self.0.lock().expect("backend port lock poisoned")
    }
}

impl BackendStartupError {
    fn set(&self, message: String) {
        *self
            .0
            .lock()
            .expect("backend startup error lock poisoned") = Some(message);
    }

    fn clear(&self) {
        self.0
            .lock()
            .expect("backend startup error lock poisoned")
            .take();
    }

    fn get(&self) -> Option<String> {
        self.0
            .lock()
            .expect("backend startup error lock poisoned")
            .clone()
    }
}

#[tauri::command]
fn backend_port(port: tauri::State<'_, BackendPort>) -> Result<u16, String> {
    port.get()
        .ok_or_else(|| "backend port was not initialized".to_string())
}

#[tauri::command]
fn backend_startup_error(
    error: tauri::State<'_, BackendStartupError>,
) -> Option<String> {
    error.get()
}

fn pick_backend_port() -> std::io::Result<(u16, TcpListener)> {
    for port in 8088..8188 {
        if let Ok(listener) = TcpListener::bind(("127.0.0.1", port)) {
            return Ok((port, listener));
        }
    }

    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok((listener.local_addr()?.port(), listener))
}

#[cfg(debug_assertions)]
fn command_exists(command: &str) -> bool {
    StdCommand::new(command)
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
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

/// Returns `(command, extra_prefix_args)`. On Windows, prefer `py -3` to
/// avoid triggering the Microsoft Store stub that installs on `python.exe`.
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

fn setup_backend(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    app.handle().plugin(
        tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .max_file_size(5 * 1024 * 1024)
            .rotation_strategy(RotationStrategy::KeepSome(3))
            .build(),
    )?;

    app.state::<BackendStartupError>().clear();

    let (backend_port, port_guard) = match pick_backend_port() {
        Ok(port) => port,
        Err(err) => {
            let message = format!("failed to reserve backend port: {err}");
            log::error!("[backend] {message}");
            app.state::<BackendStartupError>().set(message);
            return Ok(());
        }
    };
    app.state::<BackendPort>().set(backend_port);

    #[cfg(debug_assertions)]
    let command = {
        let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let source_path = repo_root.join("src");
        if command_exists("uv") {
            app.shell()
                .command("uv")
                .args(["run", "python", "-m", "qwenpaw.desktop_entry"])
                .current_dir(repo_root)
                .env("PYTHONPATH", source_path.display().to_string())
        } else {
            let (python, prefix_args) = python_command(&repo_root);
            let mut args: Vec<&str> = prefix_args;
            args.extend(["-m", "qwenpaw.desktop_entry"]);
            app.shell()
                .command(python)
                .args(args)
                .current_dir(repo_root)
                .env("PYTHONPATH", source_path.display().to_string())
        }
    };
    #[cfg(not(debug_assertions))]
    let command = match app.shell().sidecar("qwenpaw-backend") {
        Ok(command) => command,
        Err(err) => {
            let message = format!("failed to find sidecar binary: {err}");
            log::error!("[backend] {message}");
            app.state::<BackendStartupError>().set(message);
            return Ok(());
        }
    };

    let command = command
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("QWENPAW_DESKTOP_APP", "1")
        .env("QWENPAW_DESKTOP_PORT", backend_port.to_string());

    let (mut rx, child) = match command.spawn() {
        Ok(child) => child,
        Err(err) => {
            let message = format!("failed to spawn backend: {err}");
            log::error!("[backend] {message}");
            app.state::<BackendStartupError>().set(message);
            return Ok(());
        }
    };

    // Best-effort: holding the TcpListener until spawn() reduces (but does not
    // eliminate) the race between drop and the child binding the port.  There
    // is still a window between drop() here and the Python uvicorn bind() call
    // (seconds for PyInstaller cold-start).  The frontend BackendReadyGate
    // polls /api/version to recover transparently when the child fails to bind.
    drop(port_guard);

    app.state::<BackendProcess>().set(child);

    // Log backend output
    let app_handle = app.handle().clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::info!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => {
                    log::error!("[backend] {}", String::from_utf8_lossy(&line));
                }
                _ => {}
            }
        }
        log::warn!("[backend] process exited");
        app_handle.state::<BackendProcess>().clear();
    });

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let build_result = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            backend_port,
            backend_startup_error,
        ])
        .manage(BackendProcess::default())
        .manage(BackendPort::default())
        .manage(BackendStartupError::default())
        .setup(|app| setup_backend(app))
        .on_window_event(|window, event| {
            // The app currently has a single "main" window, so closing it
            // is equivalent to quitting.  If a menu-bar / multi-window mode
            // is introduced later, move the kill() call to RunEvent::Exit
            // instead so the backend stays alive while other windows exist.
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                window.state::<BackendProcess>().kill();
            }
        })
        .build(tauri::generate_context!());

    match build_result {
        Ok(app) => {
            app.run(|app_handle, event| {
                if let RunEvent::ExitRequested { .. } = event {
                    app_handle.state::<BackendProcess>().kill();
                }
            });
        }
        Err(e) => {
            eprintln!("[QwenPaw Desktop] Fatal startup error: {e}");
            std::process::exit(1);
        }
    }
}
