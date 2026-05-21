//! Backend sidecar lifecycle for the Tauri desktop app.

use std::{
    net::TcpListener,
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
};

use tauri::Manager;
use tauri_plugin_log::{RotationStrategy, Target, TargetKind};
use tauri_plugin_shell::process::CommandChild;

mod command;
mod events;

const LEGACY_DESKTOP_PORT_START: u16 = 8088;
const LEGACY_DESKTOP_PORT_END_EXCLUSIVE: u16 = 8188;

/// Shared sidecar process state managed by Tauri.
#[derive(Default)]
pub(crate) struct BackendState {
    inner: Mutex<BackendInner>,
    generation: AtomicU64,
}

#[derive(Default)]
struct BackendInner {
    child: Option<CommandChild>,
    port: Option<u16>,
    error: Option<String>,
}

impl BackendState {
    fn with_inner<R>(&self, f: impl FnOnce(&mut BackendInner) -> R) -> R {
        let mut inner = self.inner.lock().expect("backend state poisoned");
        f(&mut inner)
    }

    fn next_generation(&self) -> u64 {
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }

    fn is_current(&self, generation: u64) -> bool {
        self.generation.load(Ordering::SeqCst) == generation
    }

    fn port(&self) -> Result<u16, String> {
        self.with_inner(|inner| {
            inner
                .port
                .ok_or_else(|| "backend port was not initialized".to_string())
        })
    }

    fn error(&self) -> Option<String> {
        self.with_inner(|inner| inner.error.clone())
    }

    fn set_error(&self, message: String) {
        self.with_inner(|inner| {
            inner.error = Some(message);
        });
    }

    fn set_error_if_current(&self, generation: u64, message: String) {
        if self.is_current(generation) {
            self.set_error(message);
        }
    }

    fn clear_startup_state(&self) {
        self.with_inner(|inner| {
            inner.port = None;
            inner.error = None;
        });
    }

    fn clear_child_if_current(&self, generation: u64) {
        if self.is_current(generation) {
            self.with_inner(|inner| {
                inner.child.take();
            });
        }
    }

    fn stop(&self) {
        self.next_generation();
        let child = self.with_inner(|inner| inner.child.take());
        if let Some(child) = child {
            let pid = child.pid();
            log::info!("[backend] stopping process pid={pid}");
            if let Err(err) = child.kill() {
                log::warn!("[backend] failed to stop process: {err}");
            }
        }
    }
}

#[tauri::command]
pub(crate) fn backend_port(state: tauri::State<'_, BackendState>) -> Result<u16, String> {
    state.port()
}

#[tauri::command]
pub(crate) fn backend_startup_error(state: tauri::State<'_, BackendState>) -> Option<String> {
    state.error()
}

/// Stops the current sidecar, starts a fresh one, and returns its API port.
#[tauri::command]
pub(crate) fn restart_backend(app: tauri::AppHandle) -> Result<u16, String> {
    stop(&app);
    start(&app);

    let state = app.state::<BackendState>();
    match state.error() {
        Some(err) => Err(err),
        None => state.port(),
    }
}

/// Installs backend-related plugins and starts the sidecar during app setup.
pub(crate) fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    app.handle().plugin(
        tauri_plugin_log::Builder::default()
            .clear_targets()
            .targets([
                Target::new(TargetKind::Stdout),
                Target::new(TargetKind::LogDir {
                    file_name: Some("qwenpaw-tauri".into()),
                }),
            ])
            .level(log::LevelFilter::Info)
            .max_file_size(5 * 1024 * 1024)
            .rotation_strategy(RotationStrategy::KeepSome(3))
            .build(),
    )?;

    start(app.handle());
    Ok(())
}

/// Terminates the current sidecar process, if one is running.
pub(crate) fn stop(app: &tauri::AppHandle) {
    app.state::<BackendState>().stop();
}

/// Starts the sidecar and records startup failures for the frontend retry UI.
fn start(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    let generation = state.next_generation();
    state.clear_startup_state();

    let (port, port_guard) = match pick_port() {
        Ok(reserved) => reserved,
        Err(err) => {
            state.set_error(format!("failed to reserve backend port: {err}"));
            return;
        }
    };

    let command = match command::create(app) {
        Ok(command) => command,
        Err(message) => {
            state.set_error(message);
            return;
        }
    }
    .env("PYTHONUTF8", "1")
    .env("PYTHONIOENCODING", "utf-8")
    .env("PYTHONUNBUFFERED", "1")
    .env("PYTHONFAULTHANDLER", "1")
    .env("QWENPAW_DESKTOP_APP", "1")
    .env("QWENPAW_DESKTOP_PORT", port.to_string());

    let mut command = command;
    match backend_log_path(app) {
        Ok(log_path) => {
            log::info!(
                "[backend] starting generation={generation} port={port} log={}",
                log_path.display(),
            );
            command = command.env("QWENPAW_TAURI_BACKEND_LOG", log_path.display().to_string());
        }
        Err(err) => {
            log::warn!("[backend] failed to prepare backend log file: {err}");
            log::info!("[backend] starting generation={generation} port={port}");
        }
    }

    let (rx, child) = match command.spawn() {
        Ok(child) => child,
        Err(err) => {
            state.set_error(format!("failed to spawn backend: {err}"));
            return;
        }
    };

    // Hold the listener until after spawn() to shrink the race between
    // reserving the port in Rust and binding it in the Python sidecar.
    drop(port_guard);
    let child_pid = child.pid();
    log::info!("[backend] spawned generation={generation} pid={child_pid} port={port}");
    state.with_inner(|inner| {
        inner.child = Some(child);
        inner.port = Some(port);
    });
    events::watch(app.clone(), generation, rx);
}

fn backend_log_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let log_dir = app
        .path()
        .app_log_dir()
        .map_err(|err| format!("failed to resolve app log directory: {err}"))?;
    std::fs::create_dir_all(&log_dir).map_err(|err| {
        format!(
            "failed to create app log directory {}: {err}",
            log_dir.display()
        )
    })?;
    Ok(log_dir.join("qwenpaw-tauri-backend.log"))
}

/// Reserves a backend port, preferring the legacy desktop range for continuity.
fn pick_port() -> std::io::Result<(u16, TcpListener)> {
    for port in LEGACY_DESKTOP_PORT_START..LEGACY_DESKTOP_PORT_END_EXCLUSIVE {
        if let Ok(listener) = TcpListener::bind(("127.0.0.1", port)) {
            return Ok((port, listener));
        }
    }

    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok((listener.local_addr()?.port(), listener))
}
