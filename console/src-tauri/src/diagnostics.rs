//! Desktop diagnostics: log directory access and lightweight resource monitoring.
//!
//! These commands let the frontend surface technical details (log path, CPU/RAM
//! pressure, backend process health) to users and to the Tauri log file itself,
//! making it easier to diagnose "the desktop app gets slower over time" reports.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use sysinfo::{Pid, System};
use tauri::Manager;

use crate::backend::BackendState;

const RESOURCE_LOG_INTERVAL: Duration = Duration::from_secs(30);
const MEMORY_PRESSURE_PERCENT: f32 = 85.0;
const CPU_PRESSURE_PERCENT: f32 = 80.0;

#[derive(Serialize, Clone, Debug)]
pub struct DiagnosticsSnapshot {
    /// Tauri application log directory where `qwenpaw-desktop*.log` files live.
    pub log_dir: Option<String>,
    /// Total system memory in bytes.
    pub total_memory_bytes: u64,
    /// Used system memory in bytes.
    pub used_memory_bytes: u64,
    /// Approximate overall CPU usage percentage (0-100).
    pub cpu_usage_percent: f32,
    /// Memory usage percentage (0-100).
    pub memory_usage_percent: f32,
    /// Resource consumption of the backend sidecar process, if it is running.
    pub backend_process: Option<ProcessSnapshot>,
}

#[derive(Serialize, Clone, Debug)]
pub struct ProcessSnapshot {
    pub pid: u32,
    /// Resident memory in bytes.
    pub memory_bytes: u64,
    /// Process CPU usage percentage relative to one core (0-100 * core_count).
    pub cpu_usage_percent: f32,
    pub name: String,
}

pub struct DiagnosticsState {
    /// Whether the background resource monitor has already been started.
    monitor_started: AtomicBool,
    /// Cached system object so the monitor can refresh it incrementally.
    system: Mutex<System>,
}

impl Default for DiagnosticsState {
    fn default() -> Self {
        Self {
            monitor_started: AtomicBool::new(false),
            system: Mutex::new(System::new_all()),
        }
    }
}

impl DiagnosticsState {
    fn with_system<R>(&self, f: impl FnOnce(&mut System) -> R) -> R {
        let mut system = self.system.lock().expect("diagnostics state poisoned");
        f(&mut system)
    }
}

/// Returns the Tauri log directory and current system resource usage.
#[tauri::command]
pub fn get_system_diagnostics(
    app: tauri::AppHandle,
    state: tauri::State<'_, DiagnosticsState>,
) -> DiagnosticsSnapshot {
    state.with_system(|system| {
        system.refresh_memory();
        system.refresh_cpu_usage();

        let total_memory = system.total_memory();
        let used_memory = system.used_memory();
        let memory_percent = if total_memory > 0 {
            (used_memory as f32 / total_memory as f32) * 100.0
        } else {
            0.0
        };

        let cpu_usage = system
            .cpus()
            .iter()
            .map(|cpu| cpu.cpu_usage())
            .fold(0.0, |sum, usage| sum + usage)
            / system.cpus().len().max(1) as f32;

        let backend_process = backend_process_snapshot(app.clone(), system);

        DiagnosticsSnapshot {
            log_dir: app.path().app_log_dir().ok().map(|p| p.display().to_string()),
            total_memory_bytes: total_memory,
            used_memory_bytes: used_memory,
            cpu_usage_percent: cpu_usage,
            memory_usage_percent: memory_percent,
            backend_process,
        }
    })
}

fn backend_process_snapshot(
    app: tauri::AppHandle,
    system: &mut System,
) -> Option<ProcessSnapshot> {
    let pid = app.state::<BackendState>().backend_pid()?;

    // Refresh only the process list; this is cheaper than refresh_all.
    let pid = Pid::from_u32(pid);
    system.refresh_processes(sysinfo::ProcessesToUpdate::Some(&[pid]), true);

    let process = system.process(pid)?;
    Some(ProcessSnapshot {
        pid: pid.as_u32(),
        memory_bytes: process.memory(),
        cpu_usage_percent: process.cpu_usage(),
        name: process.name().to_string_lossy().into_owned(),
    })
}

/// Spawns a background task that logs resource pressure every 30 seconds.
/// Safe to call multiple times; only the first call starts the monitor.
pub fn start_resource_monitoring(app: &tauri::App) {
    let state = app.state::<DiagnosticsState>();
    if state
        .monitor_started
        .swap(true, Ordering::SeqCst)
    {
        return;
    }

    let handle = app.handle().clone();
    tauri::async_runtime::spawn(async move {
        let mut interval = tokio::time::interval(RESOURCE_LOG_INTERVAL);
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

        loop {
            interval.tick().await;

            let snapshot = {
                let state = handle.state::<DiagnosticsState>();
                state.with_system(|system| {
                    system.refresh_memory();
                    system.refresh_cpu_usage();

                    let total_memory = system.total_memory();
                    let used_memory = system.used_memory();
                    let memory_percent = if total_memory > 0 {
                        (used_memory as f32 / total_memory as f32) * 100.0
                    } else {
                        0.0
                    };

                    let cpu_usage = system
                        .cpus()
                        .iter()
                        .map(|cpu| cpu.cpu_usage())
                        .fold(0.0, |sum, usage| sum + usage)
                        / system.cpus().len().max(1) as f32;

                    let backend_process = backend_process_snapshot(handle.clone(), system);

                    DiagnosticsSnapshot {
                        log_dir: handle
                            .path()
                            .app_log_dir()
                            .ok()
                            .map(|p| p.display().to_string()),
                        total_memory_bytes: total_memory,
                        used_memory_bytes: used_memory,
                        cpu_usage_percent: cpu_usage,
                        memory_usage_percent: memory_percent,
                        backend_process,
                    }
                })
            };

            log::info!(
                "[diagnostics] cpu={:.1}% memory={:.1}% backend={:?}",
                snapshot.cpu_usage_percent,
                snapshot.memory_usage_percent,
                snapshot.backend_process.as_ref().map(|p| {
                    format!(
                        "pid={} mem={:.1}MB cpu={:.1}%",
                        p.pid,
                        p.memory_bytes as f32 / 1_048_576.0,
                        p.cpu_usage_percent
                    )
                }),
            );

            if snapshot.memory_usage_percent >= MEMORY_PRESSURE_PERCENT {
                log::warn!(
                    "[diagnostics] high memory pressure: {:.1}%",
                    snapshot.memory_usage_percent
                );
            }
            if snapshot.cpu_usage_percent >= CPU_PRESSURE_PERCENT {
                log::warn!(
                    "[diagnostics] high CPU pressure: {:.1}%",
                    snapshot.cpu_usage_percent
                );
            }
        }
    });
}
