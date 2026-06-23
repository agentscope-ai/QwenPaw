//! Backend sidecar lifecycle for the Tauri desktop app.

use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use tauri::Manager;
use tauri_plugin_log::{Target, TargetKind};
use tauri_plugin_shell::process::CommandChild;

mod command;
mod events;

const DESKTOP_SHUTDOWN_TOKEN_ENV: &str = "QWENPAW_DESKTOP_SHUTDOWN_TOKEN";
const DESKTOP_SHUTDOWN_TOKEN_HEADER: &str = "X-QwenPaw-Desktop-Token";
const DESKTOP_SHUTDOWN_PATH: &str = "/api/desktop/shutdown";
const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(20);
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
    shutdown_token: Option<String>,
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
            inner.shutdown_token = None;
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

    fn take_for_stop(&self) -> (Option<CommandChild>, Option<u16>, Option<String>) {
        self.next_generation();
        self.with_inner(|inner| {
            inner.error = None;
            (
                inner.child.take(),
                inner.port.take(),
                inner.shutdown_token.take(),
            )
        })
    }

    async fn stop(&self) {
        let (child, port, shutdown_token) = self.take_for_stop();
        let Some(child) = child else {
            return;
        };

        let pid = child.pid();
        log::info!("[backend] stopping process pid={pid}");
        if let (Some(port), Some(shutdown_token)) = (port, shutdown_token) {
            match request_graceful_shutdown(port, &shutdown_token).await {
                Ok(()) => {
                    log::info!("[backend] graceful shutdown completed pid={pid}");
                    return;
                }
                Err(err) => {
                    log::warn!(
                        "[backend] graceful shutdown failed pid={pid}: {err}; killing process"
                    );
                }
            }
        } else {
            log::warn!("[backend] missing shutdown state for pid={pid}; killing process");
        }

        if let Err(err) = child.kill() {
            log::warn!("[backend] failed to stop process: {err}");
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
            .level(log::LevelFilter::Info)
            .build(),
    )?;

    start(app.handle());
    Ok(())
}

/// Terminates the current sidecar process, if one is running.
pub(crate) async fn stop(app: &tauri::AppHandle) {
    app.state::<BackendState>().stop().await;
}

/// Starts the sidecar and records startup failures for the frontend retry UI.
fn start(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    let generation = state.next_generation();
    let shutdown_token = make_shutdown_token(generation);
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
    .env("QWENPAW_DESKTOP_APP", "1")
    .env(DESKTOP_SHUTDOWN_TOKEN_ENV, &shutdown_token);

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
        inner.shutdown_token = Some(shutdown_token);
    });
    events::watch(app.clone(), generation, rx);
}

fn make_shutdown_token(generation: u64) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!(
        "{:016x}{:032x}{:08x}",
        generation,
        nanos,
        std::process::id()
    )
}

async fn request_graceful_shutdown(port: u16, token: &str) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}{DESKTOP_SHUTDOWN_PATH}");
    let client = reqwest::Client::builder()
        .timeout(GRACEFUL_SHUTDOWN_TIMEOUT)
        .build()
        .map_err(|err| format!("failed to create shutdown HTTP client: {err}"))?;

    let response = client
        .post(url)
        .header(DESKTOP_SHUTDOWN_TOKEN_HEADER, token)
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
