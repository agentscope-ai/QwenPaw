//! Native desktop client for a shared, independently owned Agent Host.

use std::{
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex,
    },
    time::Duration,
};

use futures_util::StreamExt;
use tauri::Manager;
use tauri_plugin_log::{Target, TargetKind};

mod command;
pub(crate) mod daemon;
pub(crate) mod runtime;
mod status;

use status::{Phase, Snapshot, Status};

pub(crate) const OTHER_CLIENTS_ERROR: &str =
    "Other clients are still using QwenPaw. Close them before stopping the service.";

#[derive(Default)]
pub(crate) struct BackendState {
    connection: Mutex<Option<tokio::task::JoinHandle<()>>>,
    runtime: Mutex<Option<runtime::Runtime>>,
    generation: AtomicU64,
    stopping: AtomicBool,
    lifecycle: tokio::sync::Mutex<()>,
    status: Status,
}

impl BackendState {
    fn is_current(&self, generation: u64) -> bool {
        self.generation.load(Ordering::SeqCst) == generation
    }

    fn detach(&self) -> u64 {
        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        if let Some(connection) = self
            .connection
            .lock()
            .expect("backend connection poisoned")
            .take()
        {
            connection.abort();
        }
        generation
    }
}

#[tauri::command]
pub(crate) fn agent_host_state(state: tauri::State<'_, BackendState>) -> Snapshot {
    state.status.snapshot()
}

/// Retry means rediscovery, never stopping a healthy shared runtime.
#[tauri::command]
pub(crate) async fn restart_backend(app: tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<BackendState>();
    let _operation = state.lifecycle.lock().await;
    attach(&app).await
}

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
    if let Err(err) = crate::computer_use_runtime::prepare(app.handle()) {
        log::warn!("[computer-use] control endpoint unavailable: {err}");
    }
    let app = app.handle().clone();
    tauri::async_runtime::spawn(async move {
        if let Err(err) = restart_backend(app).await {
            log::error!("[backend] connection failed: {err}");
        }
    });
    Ok(())
}

/// Closing this native client releases its connection, not the shared server.
pub(crate) fn detach(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    let generation = state.detach();
    state
        .status
        .publish(app, generation, Phase::Stopped, None, None);
}

pub(crate) async fn other_clients(app: &tauri::AppHandle) -> Result<usize, String> {
    let runtime = app
        .state::<BackendState>()
        .runtime
        .lock()
        .expect("backend runtime poisoned")
        .clone();
    match runtime {
        Some(runtime) => runtime.other_clients().await,
        None => Ok(0),
    }
}

/// This is an explicit global operation, never part of ordinary client exit.
pub(crate) async fn stop_and_wait(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<BackendState>();
    let _operation = state.lifecycle.lock().await;
    let runtime = state
        .runtime
        .lock()
        .expect("backend runtime poisoned")
        .clone();
    let runtime = runtime.ok_or("No connected runtime to stop")?;
    state.stopping.store(true, Ordering::SeqCst);
    let generation = state.generation.load(Ordering::SeqCst);
    state
        .status
        .publish(app, generation, Phase::Stopping, Some(runtime.port), None);
    let result = runtime.stop().await.map(|_| ());
    state.stopping.store(false, Ordering::SeqCst);
    match &result {
        Ok(()) => detach(app),
        Err(error) if error == OTHER_CLIENTS_ERROR => {
            state
                .status
                .publish(app, generation, Phase::Ready, Some(runtime.port), None)
        }
        Err(error) => {
            state
                .status
                .publish(app, generation, Phase::Failed, None, Some(error.clone()))
        }
    }
    result
}

async fn connect(
    app: &tauri::AppHandle,
    generation: u64,
) -> Result<(runtime::Runtime, reqwest::Response), String> {
    let state = app.state::<BackendState>();
    let mut waiting = false;
    loop {
        if !state.is_current(generation) || crate::tray::is_quitting(app) {
            return Err("Desktop client is closing".into());
        }
        match runtime::connect(app).await {
            Err(error) if error == crate::updates::coordination::UPDATING => {
                if !waiting {
                    state
                        .status
                        .publish(app, generation, Phase::Stopping, None, None);
                    waiting = true;
                }
                // runtime::connect released the launch lock. Cancellation or
                // a failed update can now unblock us without a manual retry.
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
            result => return result,
        }
    }
}

async fn attach(app: &tauri::AppHandle) -> Result<(), String> {
    if crate::tray::is_quitting(app) {
        return Err("Desktop client is closing".into());
    }
    let state = app.state::<BackendState>();
    let generation = state.detach();
    state
        .status
        .publish(app, generation, Phase::Starting, None, None);
    let (runtime, response) = match connect(app, generation).await {
        Ok(connection) => connection,
        Err(message) => {
            if state.is_current(generation) {
                state
                    .status
                    .publish(app, generation, Phase::Failed, None, Some(message.clone()));
            }
            return Err(message);
        }
    };
    if !state.is_current(generation) || crate::tray::is_quitting(app) {
        return Ok(());
    }
    let port = runtime.port;
    *state.runtime.lock().expect("backend runtime poisoned") = Some(runtime);
    state
        .status
        .publish(app, generation, Phase::Ready, Some(port), None);
    let handle = app.clone();
    let connection = tokio::spawn(async move {
        let mut response = response;
        loop {
            let mut stream = response.bytes_stream();
            while let Ok(Some(Ok(_))) =
                tokio::time::timeout(Duration::from_secs(15), stream.next()).await
            {}
            let state = handle.state::<BackendState>();
            if !state.is_current(generation) || state.stopping.load(Ordering::SeqCst) {
                return;
            }
            state
                .status
                .publish(&handle, generation, Phase::Starting, None, None);
            match connect(&handle, generation).await {
                Ok((runtime, connected)) if state.is_current(generation) => {
                    state.status.publish(
                        &handle,
                        generation,
                        Phase::Ready,
                        Some(runtime.port),
                        None,
                    );
                    *state.runtime.lock().expect("backend runtime poisoned") = Some(runtime);
                    response = connected;
                }
                Ok(_) => return,
                Err(error) => {
                    if state.is_current(generation) {
                        state
                            .status
                            .publish(&handle, generation, Phase::Failed, None, Some(error));
                    }
                    return;
                }
            }
        }
    });
    *state
        .connection
        .lock()
        .expect("backend connection poisoned") = Some(connection);
    Ok(())
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

pub(crate) fn runtime_for_update(
    app: &tauri::AppHandle,
    directory: &std::path::Path,
) -> Result<Option<runtime::Runtime>, String> {
    let state = app.state::<BackendState>();
    if let Some(runtime) = state
        .runtime
        .lock()
        .expect("backend runtime poisoned")
        .as_ref()
    {
        if runtime.uses_directory(directory) {
            return Ok(Some(runtime.clone()));
        }
    }
    runtime::Runtime::read(directory)
}

pub(crate) fn suspend_for_update(app: &tauri::AppHandle) {
    app.state::<BackendState>()
        .stopping
        .store(true, Ordering::SeqCst);
}

pub(crate) async fn recover_after_update(app: &tauri::AppHandle) {
    if !app
        .state::<BackendState>()
        .stopping
        .swap(false, Ordering::SeqCst)
    {
        return;
    }
    if let Err(error) = crate::computer_use_runtime::prepare(app) {
        log::warn!("[updates] Computer Use recovery failed: {error}");
    }
    if let Err(error) = restart_backend(app.clone()).await {
        log::warn!("[updates] runtime recovery failed: {error}");
    }
}
