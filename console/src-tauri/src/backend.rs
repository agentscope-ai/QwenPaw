//! Backend sidecar lifecycle for the Tauri desktop app.

use std::{
    net::TcpListener,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
};

use tauri::Manager;
use tauri_plugin_log::RotationStrategy;
use tauri_plugin_shell::process::CommandChild;

mod command;
mod events;

/// Shared sidecar process state managed by Tauri.
#[derive(Default)]
pub(crate) struct BackendState {
    child: Mutex<Option<CommandChild>>,
    port: Mutex<Option<u16>>,
    error: Mutex<Option<String>>,
    generation: AtomicU64,
}

impl BackendState {
    fn next_generation(&self) -> u64 {
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }

    fn is_current(&self, generation: u64) -> bool {
        self.generation.load(Ordering::SeqCst) == generation
    }

    fn port(&self) -> Result<u16, String> {
        self.port
            .lock()
            .expect("backend port poisoned")
            .ok_or_else(|| "backend port was not initialized".to_string())
    }

    fn error(&self) -> Option<String> {
        self.error.lock().expect("backend error poisoned").clone()
    }

    fn set_error(&self, message: String) {
        *self.error.lock().expect("backend error poisoned") = Some(message);
    }

    fn set_error_if_current(&self, generation: u64, message: String) {
        if self.is_current(generation) {
            self.set_error(message);
        }
    }

    fn clear_startup_state(&self) {
        self.port.lock().expect("backend port poisoned").take();
        self.error.lock().expect("backend error poisoned").take();
    }

    fn clear_child_if_current(&self, generation: u64) {
        if self.is_current(generation) {
            self.child.lock().expect("backend child poisoned").take();
        }
    }

    fn stop(&self) {
        self.next_generation();
        let child = self.child.lock().expect("backend child poisoned").take();
        if let Some(child) = child {
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
    state.error().map_or_else(|| state.port(), Err)
}

/// Installs backend-related plugins and starts the sidecar during app setup.
pub(crate) fn setup(app: &mut tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    app.handle().plugin(
        tauri_plugin_log::Builder::default()
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
    .env("QWENPAW_DESKTOP_APP", "1")
    .env("QWENPAW_DESKTOP_PORT", port.to_string());

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
    *state.child.lock().expect("backend child poisoned") = Some(child);
    *state.port.lock().expect("backend port poisoned") = Some(port);
    events::watch(app.clone(), generation, rx);
}

/// Reserves a backend port, preferring the legacy desktop range for continuity.
fn pick_port() -> std::io::Result<(u16, TcpListener)> {
    for port in 8088..8188 {
        if let Ok(listener) = TcpListener::bind(("127.0.0.1", port)) {
            return Ok((port, listener));
        }
    }

    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok((listener.local_addr()?.port(), listener))
}
