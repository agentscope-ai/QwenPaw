//! Backend sidecar lifecycle for the Tauri desktop app.

use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    time::Duration,
};

use tauri::Manager;
use tauri_plugin_log::{Target, TargetKind};
use tauri_plugin_shell::process::CommandChild;

mod command;
mod events;

/// Path of the desktop-only graceful shutdown endpoint on the backend.
const DESKTOP_SHUTDOWN_PATH: &str = "/api/desktop/shutdown";
/// Upper bound for the graceful shutdown HTTP request.
const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);
/// Brief delay after a successful shutdown request so the HTTP response can
/// flush before we let the sidecar finish its own lifespan shutdown.
const GRACEFUL_SHUTDOWN_SETTLE: Duration = Duration::from_millis(300);


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

    fn take_child_and_port(&self) -> (Option<CommandChild>, Option<u16>) {
        self.next_generation();
        self.with_inner(|inner| (inner.child.take(), inner.port.take()))
    }

    async fn stop(&self) {
        let (child, port) = self.take_child_and_port();
        let Some(child) = child else {
            return;
        };

        let pid = child.pid();
        log::info!("[backend] stopping process pid={pid}");

        if let Some(port) = port {
            match request_graceful_shutdown(port).await {
                Ok(()) => {
                    // The sidecar (tauri-plugin-shell CommandChild) has no
                    // kill-on-drop, so dropping `child` here does NOT terminate
                    // the process. It keeps running to complete its own lifespan
                    // shutdown (which flushes memory/index) even after the Tauri
                    // shell exits. It then exits on its own.
                    log::info!("[backend] graceful shutdown requested pid={pid}");
                    return;
                }
                Err(err) => {
                    log::warn!(
                        "[backend] graceful shutdown failed pid={pid}: {err}; killing process"
                    );
                }
            }
        } else {
            log::warn!("[backend] no known port for pid={pid}; killing process");
        }

        if let Err(err) = child.kill() {
            log::warn!("[backend] failed to stop process: {err}");
        }
    }
}

/// Requests a graceful shutdown from the desktop-only backend endpoint.
///
/// The endpoint sets uvicorn's `should_exit`, letting the sidecar run its
/// normal lifespan shutdown instead of being force-killed.
async fn request_graceful_shutdown(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}{DESKTOP_SHUTDOWN_PATH}");
    let client = reqwest::Client::builder()
        .timeout(GRACEFUL_SHUTDOWN_TIMEOUT)
        .build()
        .map_err(|err| format!("failed to create shutdown HTTP client: {err}"))?;

    let response = client
        .post(url)
        .send()
        .await
        .map_err(|err| format!("shutdown endpoint request failed: {err}"))?;
    let status = response.status();
    if !status.is_success() {
        return Err(format!("shutdown endpoint returned HTTP {status}"));
    }

    tokio::time::sleep(GRACEFUL_SHUTDOWN_SETTLE).await;
    Ok(())
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
pub(crate) async fn restart_backend(app: tauri::AppHandle) -> Result<(), String> {
    stop(&app).await;
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
            .level(desktop_log_level())
            .build(),
    )?;

    start(app.handle());
    Ok(())
}

/// Terminates the current sidecar process, if one is running.
pub(crate) async fn stop(app: &tauri::AppHandle) {
    app.state::<BackendState>().stop().await;
}

fn desktop_log_level() -> log::LevelFilter {
    if std::env::var("QWENPAW_DESKTOP_DEBUG").is_ok_and(|value| {
        matches!(
            value.to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    }) {
        log::LevelFilter::Debug
    } else {
        log::LevelFilter::Info
    }
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
