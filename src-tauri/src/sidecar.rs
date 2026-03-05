//! CoPaw Desktop App - Sidecar Management

use std::io::{BufRead, BufReader};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use tauri::Manager;
use tauri_plugin_shell::{process::CommandChild, ShellExt};
use tokio::time::sleep;

static SIDECAR_RUNNING: AtomicBool = AtomicBool::new(false);
const VERSION_ENDPOINT: &str = "http://127.0.0.1:8088/api/version";
const HEALTH_ENDPOINT: &str = "http://127.0.0.1:8088/api/health";
const CHAT_ENDPOINT: &str = "http://127.0.0.1:8088/chat";
const SHUTDOWN_ENDPOINT: &str = "http://127.0.0.1:8088/api/console/shutdown";

/// Manages the Python backend sidecar process
pub struct SidecarManager {
    child: Option<BackendChild>,
    first_boot_like_startup: bool,
}

enum BackendChild {
    Shell(CommandChild),
    Native(Child),
}

struct PreparedSidecar {
    path: PathBuf,
    did_sync: bool,
}

impl SidecarManager {
    pub fn new() -> Self {
        Self {
            child: None,
            first_boot_like_startup: false,
        }
    }

    /// Start the Python backend sidecar
    pub async fn start(&mut self, app_handle: &tauri::AppHandle) -> Result<(), String> {
        let t0 = std::time::Instant::now();
        log::warn!("SidecarManager::start entered");
        self.update_splash(app_handle, 2, "Checking backend status...");

        if SIDECAR_RUNNING.load(Ordering::SeqCst) {
            log::warn!("Sidecar already running");
            self.update_splash(app_handle, 100, "Backend is already running.");
            return Ok(());
        }

        // If another CoPaw backend is already listening, reuse it instead of starting
        // a new one. This allows multiple app windows to share the same backend.
        if self.is_backend_ready().await {
            log::warn!("Detected existing backend on port 8088, reusing it");
            self.update_splash(
                app_handle,
                50,
                "Connecting to existing backend...",
            );
            // Mark as running without spawning a new process
            SIDECAR_RUNNING.store(true, Ordering::SeqCst);
            self.child = None; // No child process to manage (owned by another instance)
            log::info!("Reusing existing backend on port 8088");
            self.update_splash(app_handle, 100, "Connected to existing backend. Opening CoPaw...");
            return Ok(());
        }

        // Port is occupied but not by CoPaw backend - need to clear it
        if self.is_port_occupied() {
            log::warn!("Port 8088 is occupied by a non-CoPaw process, force-killing it");
            self.update_splash(app_handle, 12, "Clearing occupied port 8088...");
            if !self.force_kill_backend_port().await {
                return Err(
                    "Port 8088 is occupied by another process and cannot be cleared".to_string(),
                );
            }
            log::info!("Occupied port 8088 cleared successfully");
        }

        log::info!("Starting CoPaw backend sidecar...");
        self.update_splash(app_handle, 24, "Launching backend process...");

        let spawn_t0 = std::time::Instant::now();
        self.first_boot_like_startup = false;
        if self.use_source_backend_mode() {
            log::info!("Source backend mode enabled");
            self.spawn_source_backend()?;
        } else if let Err(native_err) = self.spawn_native_sidecar(app_handle) {
            log::warn!(
                "Direct backend launch failed: {}. Trying Tauri sidecar fallback.",
                native_err
            );
            self.spawn_shell_sidecar(app_handle)?;
        }
        log::info!("Backend process spawn finished in {} ms", spawn_t0.elapsed().as_millis());

        // Wait for backend to be ready
        let wait_t0 = std::time::Instant::now();
        if let Err(e) = self.wait_for_backend(app_handle).await {
            self.kill_child();
            SIDECAR_RUNNING.store(false, Ordering::SeqCst);
            return Err(e);
        }
        log::info!("Backend readiness wait finished in {} ms", wait_t0.elapsed().as_millis());

        log::info!("CoPaw backend started successfully");
        log::info!("Desktop startup total elapsed: {} ms", t0.elapsed().as_millis());
        self.update_splash(app_handle, 100, "Backend ready. Opening CoPaw...");
        Ok(())
    }

    fn use_source_backend_mode(&self) -> bool {
        std::env::var("COPAW_USE_SOURCE_BACKEND")
            .ok()
            .map(|v| matches!(v.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
            .unwrap_or(false)
    }

    fn spawn_shell_sidecar(&mut self, app_handle: &tauri::AppHandle) -> Result<(), String> {
        // Use shell plugin to spawn sidecar
        let sidecar_command = app_handle
            .shell()
            .sidecar("copaw-backend")
            .map_err(|e| format!("Failed to create sidecar command: {}", e))?
            .args(["app", "--host", "127.0.0.1", "--port", "8088"]);

        let (mut rx, child) = sidecar_command
            .spawn()
            .map_err(|e| format!("Failed to spawn sidecar: {}", e))?;

        let pid = child.pid();
        self.child = Some(BackendChild::Shell(child));
        SIDECAR_RUNNING.store(true, Ordering::SeqCst);
        log::info!("Spawned CoPaw backend sidecar (pid: {})", pid);
        self.update_splash(app_handle, 34, "Backend process started. Initializing...");

        // Spawn task to handle sidecar output
        tauri::async_runtime::spawn(async move {
            use tauri_plugin_shell::process::CommandEvent;
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => {
                        log::info!("[Backend] {}", String::from_utf8_lossy(&line));
                    }
                    CommandEvent::Stderr(line) => {
                        log::info!("[Backend] {}", String::from_utf8_lossy(&line));
                    }
                    CommandEvent::Error(err) => {
                        log::error!("[Backend Error] {}", err);
                        SIDECAR_RUNNING.store(false, Ordering::SeqCst);
                    }
                    CommandEvent::Terminated(payload) => {
                        log::warn!("[Backend] Process terminated with code: {:?}", payload.code);
                        SIDECAR_RUNNING.store(false, Ordering::SeqCst);
                    }
                    _ => {}
                }
            }
        });

        Ok(())
    }

    fn spawn_native_sidecar(&mut self, app_handle: &tauri::AppHandle) -> Result<(), String> {
        let exe = std::env::current_exe()
            .map_err(|e| format!("Failed to resolve current executable: {}", e))?;
        let bundled_backend = exe.with_file_name("copaw-backend");
        if !bundled_backend.exists() {
            return Err(format!(
                "Fallback backend binary not found: {}",
                bundled_backend.display()
            ));
        }
        let prepared = self
            .prepare_runtime_sidecar_if_needed(&bundled_backend, app_handle)
            .unwrap_or_else(|e| {
                log::warn!("Runtime sidecar preparation failed, fallback to bundled path: {}", e);
                PreparedSidecar {
                    path: bundled_backend.clone(),
                    did_sync: false,
                }
            });
        let backend = prepared.path;
        self.first_boot_like_startup = prepared.did_sync;

        let mut cmd = Command::new(&backend);
        cmd.args(["app", "--host", "127.0.0.1", "--port", "8088"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        self.configure_frozen_python_env(&mut cmd, &backend);

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("Failed to spawn fallback backend: {}", e))?;

        let pid = child.id();
        if let Some(stdout) = child.stdout.take() {
            std::thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    log::info!("[Backend] {}", line);
                }
            });
        }
        if let Some(stderr) = child.stderr.take() {
            std::thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().map_while(Result::ok) {
                    log::info!("[Backend] {}", line);
                }
            });
        }

        self.child = Some(BackendChild::Native(child));
        SIDECAR_RUNNING.store(true, Ordering::SeqCst);
        log::warn!(
            "Spawned fallback backend process directly (pid: {}, path: {})",
            pid,
            backend.display()
        );
        Ok(())
    }

    fn prepare_runtime_sidecar_if_needed(
        &self,
        bundled_backend: &Path,
        app_handle: &tauri::AppHandle,
    ) -> Result<PreparedSidecar, String> {
        let bundled_dir = bundled_backend
            .parent()
            .ok_or_else(|| "Bundled backend has no parent directory".to_string())?;
        let bundled_internal = bundled_dir.join("_internal");
        if !bundled_internal.exists() {
            return Ok(PreparedSidecar {
                path: bundled_backend.to_path_buf(),
                did_sync: false,
            });
        }

        // Only stage to ~/.copaw/runtime when running from inside .app bundle.
        let path_str = bundled_backend.to_string_lossy();
        if !path_str.contains(".app/Contents/") {
            return Ok(PreparedSidecar {
                path: bundled_backend.to_path_buf(),
                did_sync: false,
            });
        }

        let home = std::env::var("HOME").map_err(|e| format!("HOME is not set: {}", e))?;
        let runtime_dir = PathBuf::from(home).join(".copaw/runtime/sidecar");
        let runtime_backend = runtime_dir.join("copaw-backend");

        let needs_sync = match (bundled_backend.metadata(), runtime_backend.metadata()) {
            (Ok(_src_meta), Ok(_dst_meta)) => {
                // Compare sidecar version markers instead of binary mtime/size
                let bundled_version = bundled_dir.join("_internal/.copaw_sidecar_version");
                let runtime_version = runtime_dir.join("_internal/.copaw_sidecar_version");
                
                match (std::fs::read_to_string(&bundled_version), std::fs::read_to_string(&runtime_version)) {
                    (Ok(src_ver), Ok(dst_ver)) => {
                        let needs = src_ver.trim() != dst_ver.trim();
                        if needs {
                            log::info!(
                                "Sidecar version mismatch: bundled='{}' runtime='{}'",
                                src_ver.trim(),
                                dst_ver.trim()
                            );
                        } else {
                            log::info!("Sidecar version matches, skipping rsync");
                        }
                        needs
                    }
                    _ => {
                        log::warn!("Version marker file missing, forcing rsync");
                        true
                    }
                }
            }
            _ => {
                log::info!("Sidecar binary or runtime dir missing, forcing rsync");
                true
            }
        };

        if needs_sync {
            self.update_splash(app_handle, 15, "Preparing runtime files (first launch)...");
            let sync_start = std::time::Instant::now();
            
            std::fs::create_dir_all(&runtime_dir)
                .map_err(|e| format!("Failed to create runtime sidecar dir: {}", e))?;

            let src = bundled_dir.display().to_string();
            let dst = runtime_dir.display().to_string();
            
            // Get total file count for progress estimation
            let file_count_output = Command::new("sh")
                .args([
                    "-c",
                    &format!("find '{}' -type f | wc -l", src),
                ])
                .output();
            
            let total_files = match file_count_output {
                Ok(output) if output.status.success() => {
                    String::from_utf8_lossy(&output.stdout)
                        .trim()
                        .parse::<usize>()
                        .unwrap_or(0)
                }
                _ => 0,
            };
            
            if total_files > 0 {
                log::info!("Syncing {} files to runtime directory...", total_files);
            }
            
            // Use optimized rsync flags:
            // -a: archive mode (preserves permissions, timestamps, etc.)
            // --delete: delete files in destination not in source
            // -W: copy files whole (faster for first copy, no delta calc)
            // --inplace: update destination files in-place
            // --no-compress: skip compression (local copy, faster)
            // --progress: show progress (for logging)
            let status = Command::new("rsync")
                .args([
                    "-aW",
                    "--delete",
                    "--inplace",
                    "--no-compress",
                    "--stats",
                    &format!("{}/", src),
                    &format!("{}/", dst),
                ])
                .output()
                .map_err(|e| format!("Failed to run rsync for runtime sidecar: {}", e))?;
            
            if !status.status.success() {
                let stderr = String::from_utf8_lossy(&status.stderr);
                return Err(format!(
                    "rsync failed while preparing runtime sidecar (status: {}, stderr: {})",
                    status.status, stderr
                ));
            }
            
            let elapsed_ms = sync_start.elapsed().as_millis();
            let stats = String::from_utf8_lossy(&status.stdout);
            log::info!(
                "Runtime sidecar synced in {} ms: {} -> {}\n{}",
                elapsed_ms,
                bundled_dir.display(),
                runtime_dir.display(),
                stats.lines().take(10).collect::<Vec<_>>().join("\n")  // First 10 lines of stats
            );
            
            self.update_splash(app_handle, 22, "Runtime files ready.");
        }

        if runtime_backend.exists() {
            Ok(PreparedSidecar {
                path: runtime_backend,
                did_sync: needs_sync,
            })
        } else {
            Ok(PreparedSidecar {
                path: bundled_backend.to_path_buf(),
                did_sync: false,
            })
        }
    }

    fn configure_frozen_python_env(&self, cmd: &mut Command, backend: &Path) {
        let exe_dir = backend
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));

        let frameworks_dir = exe_dir
            .parent()
            .map(|p| p.join("Frameworks"))
            .unwrap_or_else(|| exe_dir.join("Frameworks"));

        let internal_candidates = [
            exe_dir.join("_internal"),
            frameworks_dir.join("_internal"),
        ];
        let internal_dir = internal_candidates
            .iter()
            .find(|p| p.exists())
            .cloned()
            .unwrap_or_else(|| exe_dir.join("_internal"));

        let base_lib = internal_dir.join("base_library.zip");
        let mut py_paths: Vec<String> = Vec::new();
        if base_lib.exists() {
            py_paths.push(base_lib.display().to_string());
        }
        if internal_dir.exists() {
            py_paths.push(internal_dir.display().to_string());
        }
        if let Ok(existing) = std::env::var("PYTHONPATH") {
            if !existing.is_empty() {
                py_paths.push(existing);
            }
        }
        if !py_paths.is_empty() {
            cmd.env("PYTHONPATH", py_paths.join(":"));
        }

        if internal_dir.exists() {
            cmd.env("PYTHONHOME", &internal_dir);
        }

        let mut dyld_paths: Vec<String> = Vec::new();
        if internal_dir.exists() {
            dyld_paths.push(internal_dir.display().to_string());
        }
        if frameworks_dir.exists() {
            dyld_paths.push(frameworks_dir.display().to_string());
        }
        if let Ok(existing) = std::env::var("DYLD_LIBRARY_PATH") {
            if !existing.is_empty() {
                dyld_paths.push(existing);
            }
        }
        if !dyld_paths.is_empty() {
            cmd.env("DYLD_LIBRARY_PATH", dyld_paths.join(":"));
        }

        cmd.env("PYTHONNOUSERSITE", "1");
    }

    fn spawn_source_backend(&mut self) -> Result<(), String> {
        let source_root = std::env::var("COPAW_SOURCE_ROOT")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|_| std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from(".")));
        let python_bin = std::env::var("COPAW_PYTHON")
            .unwrap_or_else(|_| "python3".to_string());
        let src_dir = source_root.join("src");

        let mut cmd = Command::new(&python_bin);
        cmd.current_dir(&source_root)
            .args([
                "-m",
                "copaw",
                "app",
                "--host",
                "127.0.0.1",
                "--port",
                "8088",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env("COPAW_DESKTOP_APP", "1")
            .env("COPAW_SOURCE_ROOT", &source_root)
            .env("COPAW_WORKING_DIR", std::env::var("COPAW_WORKING_DIR").unwrap_or_else(|_| "~/.copaw".to_string()));

        if src_dir.exists() {
            let old = std::env::var("PYTHONPATH").unwrap_or_default();
            let py_path = if old.is_empty() {
                src_dir.display().to_string()
            } else {
                format!("{}:{}", src_dir.display(), old)
            };
            cmd.env("PYTHONPATH", py_path);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| format!("Failed to spawn source backend via {}: {}", python_bin, e))?;

        let pid = child.id();
        if let Some(stdout) = child.stdout.take() {
            std::thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    log::info!("[Backend] {}", line);
                }
            });
        }
        if let Some(stderr) = child.stderr.take() {
            std::thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines().map_while(Result::ok) {
                    log::info!("[Backend] {}", line);
                }
            });
        }

        self.child = Some(BackendChild::Native(child));
        SIDECAR_RUNNING.store(true, Ordering::SeqCst);
        log::warn!(
            "Spawned source backend process (pid: {}, python: {}, root: {})",
            pid,
            python_bin,
            source_root.display()
        );
        Ok(())
    }

    /// Wait for backend to be ready (health check)
    /// Uses adaptive polling: fast polling (100ms) for first 5 seconds,
    /// then normal polling (250ms) to balance responsiveness and CPU usage.
    async fn wait_for_backend(&mut self, app_handle: &tauri::AppHandle) -> Result<(), String> {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .map_err(|e| format!("Failed to create HTTP client: {}", e))?;

        // Default timeout is 60 seconds; first boot-like startup uses a longer timeout
        // because PyInstaller onedir may need heavy extraction/loading on first run.
        // Example: COPAW_BACKEND_STARTUP_TIMEOUT_SECS=120
        let default_timeout = if self.first_boot_like_startup { 180 } else { 60 };
        let startup_timeout_secs = std::env::var("COPAW_BACKEND_STARTUP_TIMEOUT_SECS")
            .ok()
            .and_then(|s| s.parse::<u64>().ok())
            .filter(|v| *v >= 10)
            .unwrap_or(default_timeout);
        
        // Adaptive polling intervals (ms)
        const FAST_POLL_MS: u64 = 100;      // First 5 seconds: responsive
        const NORMAL_POLL_MS: u64 = 250;    // After 5s: balanced
        const SLOW_POLL_MS: u64 = 500;      // After 30s: patient
        
        log::info!(
            "Backend startup timeout set to {}s (first_boot_like_startup={}, poll: {}ms/{}ms/{}ms)",
            startup_timeout_secs,
            self.first_boot_like_startup,
            FAST_POLL_MS, NORMAL_POLL_MS, SLOW_POLL_MS
        );
        
        let max_attempts = ((startup_timeout_secs * 1000) / NORMAL_POLL_MS).max(1) as usize;
        let mut attempts = 0;
        let mut ready_streak = 0usize;
        let wait_start = std::time::Instant::now();

        loop {
            if let Some(status) = self.try_poll_native_exit() {
                SIDECAR_RUNNING.store(false, Ordering::SeqCst);
                return Err(format!("Backend process exited early: {}", status));
            }

            if !SIDECAR_RUNNING.load(Ordering::SeqCst) {
                return Err("Backend process terminated before becoming ready".to_string());
            }

            // Ramp progress from 34% to 92% while waiting for backend readiness.
            let progress = 34 + ((attempts * 58) / max_attempts);
            self.update_splash(
                app_handle,
                progress.min(92),
                "Waiting for backend services...",
            );

            match client.get(HEALTH_ENDPOINT).send().await {
                Ok(response) if response.status().is_success() => {
                    ready_streak += 1;
                    self.update_splash(
                        app_handle,
                        95 + ready_streak.min(4),
                        "Backend ready, opening CoPaw...",
                    );
                    if ready_streak >= 1 {
                        let total_wait_ms = wait_start.elapsed().as_millis();
                        log::info!(
                            "Backend readiness check passed (/api/health) after {}ms ({} attempts)",
                            total_wait_ms, attempts
                        );
                        return Ok(());
                    }
                }
                Ok(response) => {
                    ready_streak = 0;
                    log::debug!(
                        "Backend health check returned status: {}",
                        response.status()
                    );
                }
                Err(e) => {
                    ready_streak = 0;
                    log::debug!("Backend health check failed: {}", e);
                }
            }

            attempts += 1;
            if attempts >= max_attempts {
                let total_wait_ms = wait_start.elapsed().as_millis();
                return Err(format!(
                    "Backend failed to start within timeout ({}s, waited {}ms, {} attempts)",
                    startup_timeout_secs, total_wait_ms, attempts
                ));
            }
            
            // Adaptive sleep based on elapsed time
            let elapsed_secs = wait_start.elapsed().as_secs();
            let sleep_ms = if elapsed_secs < 5 {
                FAST_POLL_MS
            } else if elapsed_secs < 30 {
                NORMAL_POLL_MS
            } else {
                SLOW_POLL_MS
            };
            sleep(Duration::from_millis(sleep_ms)).await;
        }
    }

    fn try_poll_native_exit(&mut self) -> Option<String> {
        let BackendChild::Native(child) = self.child.as_mut()? else {
            return None;
        };
        match child.try_wait() {
            Ok(Some(status)) => Some(format!("{:?}", status)),
            Ok(None) => None,
            Err(e) => Some(format!("failed to poll child status: {}", e)),
        }
    }

    fn update_splash(&self, app_handle: &tauri::AppHandle, progress: usize, status: &str) {
        let status_js = match serde_json::to_string(status) {
            Ok(value) => value,
            Err(_) => "\"Starting...\"".to_string(),
        };
        let script = format!(
            "if (window.__COPAW_SPLASH_UPDATE) window.__COPAW_SPLASH_UPDATE({}, {});",
            progress, status_js
        );
        if let Some(main) = app_handle.get_webview_window("main") {
            let _ = main.eval(&script);
        }
    }

    async fn is_health_ready(&self, client: &reqwest::Client) -> bool {
        let response = match client.get(HEALTH_ENDPOINT).send().await {
            Ok(response) => response,
            Err(err) => {
                log::debug!("Health endpoint check failed: {}", err);
                return false;
            }
        };

        if !response.status().is_success() {
            log::debug!(
                "Health endpoint returned non-success status: {}",
                response.status()
            );
            return false;
        }
        true
    }

    async fn is_frontend_ready(&self, client: &reqwest::Client) -> bool {
        let response = match client.get(CHAT_ENDPOINT).send().await {
            Ok(response) => response,
            Err(err) => {
                log::debug!("Frontend endpoint check failed: {}", err);
                return false;
            }
        };

        if !response.status().is_success() {
            log::debug!(
                "Frontend endpoint returned non-success status: {}",
                response.status()
            );
            return false;
        }

        true
    }

    /// Stop the Python backend sidecar gracefully
    /// Note: If this instance is reusing an existing backend (child is None),
    /// we don't stop it - let the owner instance manage the lifecycle.
    pub async fn stop(&mut self) -> Result<(), String> {
        // If we're reusing an existing backend (not the owner), don't stop it
        if self.child.is_none() {
            log::info!("This instance is reusing an existing backend, not stopping it");
            SIDECAR_RUNNING.store(false, Ordering::SeqCst);
            return Ok(());
        }

        if !SIDECAR_RUNNING.load(Ordering::SeqCst) {
            return Ok(());
        }

        log::info!("Stopping CoPaw backend...");
        let mut backend_stopped = false;

        // Try graceful shutdown first via API
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
            .ok();

        if let Some(client) = client {
            if let Err(e) = client.post(SHUTDOWN_ENDPOINT).send().await {
                log::warn!("Graceful shutdown request failed: {}", e);
            } else {
                // Wait up to 4s for graceful shutdown.
                backend_stopped = self.wait_until_backend_stops(Duration::from_secs(4)).await;
                if !backend_stopped {
                    log::warn!("Backend did not stop after graceful shutdown request");
                }
            }
        }

        // Fallback: force kill spawned sidecar process if graceful shutdown failed.
        if !backend_stopped && self.child.is_some() {
            self.kill_child();
        } else {
            self.child = None;
        }

        SIDECAR_RUNNING.store(false, Ordering::SeqCst);
        log::info!("CoPaw backend stopped");
        Ok(())
    }

    async fn stop_existing_backend(&self) -> bool {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(5))
            .build()
        {
            Ok(client) => client,
            Err(_) => return false,
        };

        match client.post(SHUTDOWN_ENDPOINT).send().await {
            Ok(response) if response.status().is_success() => {
                if self.wait_until_backend_stops(Duration::from_secs(6)).await {
                    true
                } else {
                    log::warn!("Graceful shutdown timed out, force-killing port 8088");
                    self.force_kill_backend_port().await
                }
            }
            Ok(response) => {
                log::warn!(
                    "Existing backend shutdown request failed with status {}",
                    response.status()
                );
                self.force_kill_backend_port().await
            }
            Err(err) => {
                log::warn!("Existing backend shutdown request failed: {}", err);
                self.force_kill_backend_port().await
            }
        }
    }

    async fn force_kill_backend_port(&self) -> bool {
        let status = Command::new("sh")
            .args([
                "-c",
                "for pid in $(lsof -ti tcp:8088 2>/dev/null); do kill -9 \"$pid\"; done",
            ])
            .status();

        match status {
            Ok(exit) if exit.success() => {
                sleep(Duration::from_millis(300)).await;
                !self.is_backend_ready().await
            }
            Ok(exit) => {
                log::warn!("Force-kill command exited with non-zero status: {}", exit);
                false
            }
            Err(err) => {
                log::warn!("Failed to execute force-kill command: {}", err);
                false
            }
        }
    }

    async fn is_backend_ready(&self) -> bool {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_millis(800))
            .build()
        {
            Ok(client) => client,
            Err(_) => return false,
        };

        match client.get(VERSION_ENDPOINT).send().await {
            Ok(response) => response.status().is_success(),
            Err(_) => false,
        }
    }

    fn is_port_occupied(&self) -> bool {
        let addr: SocketAddr = match "127.0.0.1:8088".parse() {
            Ok(addr) => addr,
            Err(_) => return false,
        };
        TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok()
    }

    async fn wait_until_backend_stops(&self, timeout: Duration) -> bool {
        let client = match reqwest::Client::builder()
            .timeout(Duration::from_millis(500))
            .build()
        {
            Ok(client) => client,
            Err(_) => return false,
        };

        let check_interval = Duration::from_millis(200);
        let deadline = tokio::time::Instant::now() + timeout;

        while tokio::time::Instant::now() < deadline {
            let alive = client
                .get(VERSION_ENDPOINT)
                .send()
                .await
                .map(|r| r.status().is_success())
                .unwrap_or(false);
            if !alive {
                SIDECAR_RUNNING.store(false, Ordering::SeqCst);
                return true;
            }
            sleep(check_interval).await;
        }

        false
    }

    fn kill_child(&mut self) {
        if let Some(child) = self.child.take() {
            match child {
                BackendChild::Shell(child) => {
                    let pid = child.pid();
                    match child.kill() {
                        Ok(()) => log::warn!("Force-killed sidecar process (pid: {})", pid),
                        Err(e) => {
                            log::warn!("Failed to force-kill sidecar process {}: {}", pid, e)
                        }
                    }
                }
                BackendChild::Native(mut child) => {
                    let pid = child.id();
                    match child.kill() {
                        Ok(()) => log::warn!("Force-killed fallback backend process (pid: {})", pid),
                        Err(e) => {
                            log::warn!(
                                "Failed to force-kill fallback backend process {}: {}",
                                pid,
                                e
                            )
                        }
                    }
                    let _ = child.wait();
                }
            }
        }
    }
}

impl Default for SidecarManager {
    fn default() -> Self {
        Self::new()
    }
}
