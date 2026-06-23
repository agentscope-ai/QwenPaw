//! Backend sidecar lifecycle for the Tauri desktop app.

use std::sync::{
    atomic::{AtomicU64, Ordering},
    Mutex,
};

use tauri::Manager;
use tauri_plugin_log::{Target, TargetKind};
use tauri_plugin_shell::process::CommandChild;

mod command;
mod events;

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

    fn port(&self) -> Option<u16> {
        self.with_inner(|inner| inner.port)
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

    fn set_port_if_current(&self, generation: u64, port: u16) {
        if self.is_current(generation) {
            self.with_inner(|inner| {
                inner.port = Some(port);
                inner.error = None;
            });
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
pub(crate) fn backend_port(state: tauri::State<'_, BackendState>) -> Option<u16> {
    state.port()
}

/// Returns startup failures consumed by the bootstrap gate.
///
/// This is not a long-lived backend health signal after the WebView navigates to
/// the backend-hosted console.
#[tauri::command]
pub(crate) fn backend_startup_error(state: tauri::State<'_, BackendState>) -> Option<String> {
    state.error()
}

/// Stops the current sidecar, starts a fresh one, and returns its API port.
#[tauri::command]
pub(crate) fn restart_backend(app: tauri::AppHandle) -> Result<(), String> {
    stop(&app);
    start(&app);

    let state = app.state::<BackendState>();
    match state.error() {
        Some(err) => Err(err),
        None => Ok(()),
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
                    file_name: Some("qwenpaw-desktop".into()),
                }),
            ])
            .level(log::LevelFilter::Info)
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
    .env("QWENPAW_DESKTOP_APP", "1");

    log::info!("[backend] starting generation={generation}");

    let (rx, child) = match command.spawn() {
        Ok(child) => child,
        Err(err) => {
            state.set_error(format!("failed to spawn backend: {err}"));
            return;
        }
    };

    let child_pid = child.pid();
    log::info!("[backend] spawned generation={generation} pid={child_pid}");
    state.with_inner(|inner| {
        inner.child = Some(child);
    });
    events::watch(app.clone(), generation, rx);
}
