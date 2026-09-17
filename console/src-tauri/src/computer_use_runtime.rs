//! Desktop-owned lifecycle for the native Computer Use helper.
//!
//! The authenticated localhost control endpoint and capability handoff are
//! platform neutral; only the kill-on-close Job Object and the console-window
//! spawn flag remain Windows specific (macOS relies on the helper's own
//! parent-death watch for reaping).

#[cfg(target_os = "macos")]
use std::collections::HashSet;
use std::path::Path;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
use std::process::{ChildStderr, ChildStdout};
#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
use std::sync::mpsc;
use std::sync::Mutex;

#[cfg(windows)]
use std::os::windows::{io::AsRawHandle, process::CommandExt};
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::{Ipv4Addr, TcpListener, TcpStream},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

use rand::RngCore;
use serde::{Deserialize, Serialize};
use tauri::Manager;

use crate::computer_use_protocol::VERSION as PROTOCOL_VERSION;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
// The helper reads the capability secret from this variable. Kept in step with
// the same name in computer_use_server::parse_arguments, which is a separate
// binary and cannot share the constant.
const CAPABILITY_ENV: &str = "QWENPAW_CU_CAPABILITY";
#[cfg(all(not(debug_assertions), target_os = "macos"))]
const HELPER_HOST_PID_ENV: &str = "QWENPAW_CU_HOST_PID";
const CONTROL_HOST_ENV: &str = "QWENPAW_COMPUTER_USE_CONTROL_HOST";
const CONTROL_PORT_ENV: &str = "QWENPAW_COMPUTER_USE_CONTROL_PORT";
const CONTROL_TOKEN_ENV: &str = "QWENPAW_COMPUTER_USE_CONTROL_TOKEN";
const CONTROL_MAX_MESSAGE_BYTES: usize = 4096;
// This is emitted by the direct helper child after it has created an endpoint
// that the Python client can connect to. Keep it in step with the helper's
// `computer_use_server::connection::HELPER_READY_PREFIX` constant.
#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
const HELPER_READY_PREFIX: &str = "QWENPAW_COMPUTER_USE_READY ";
const HELPER_READY_TIMEOUT: Duration = Duration::from_secs(8);
const CONTROL_CONNECTION_TIMEOUT: Duration = Duration::from_secs(2);
#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
const MAX_CAPTURED_HELPER_STDERR_CHARS: usize = 4096;

#[derive(Default)]
pub(crate) struct ComputerUseRuntimeState {
    inner: Mutex<RuntimeInner>,
    control: Mutex<Option<ControlEndpoint>>,
    // Raw HANDLE (as isize) of a Job Object configured with
    // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The helper process is assigned to it
    // so the OS terminates the helper whenever this desktop process exits —
    // including crashes or force-kills that never reach the graceful `stop`
    // path. Stored as isize to keep the state Send + Sync.
    #[cfg(windows)]
    job: Mutex<Option<isize>>,
}

#[derive(Default)]
struct RuntimeInner {
    child: Option<Child>,
    capability: Option<RuntimeCapability>,
    helper_pid: Option<u32>,
    #[cfg(target_os = "macos")]
    focus_leases: HashSet<String>,
    #[cfg(target_os = "macos")]
    restore_host_after_focus: bool,
}

#[derive(Clone)]
struct RuntimeCapability {
    pipe_name: String,
    secret: String,
}

struct ControlEndpoint {
    port: u16,
    token: String,
    stop: Arc<AtomicBool>,
    thread: JoinHandle<()>,
}

#[derive(Deserialize)]
struct ControlRequest {
    token: String,
    action: String,
    #[serde(default)]
    helper_pid: Option<u32>,
    #[serde(default)]
    lease_id: Option<String>,
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
#[derive(Deserialize)]
struct HelperReadyPayload {
    protocol_version: u64,
}

#[derive(Serialize)]
struct ControlResponse {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pipe_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    capability: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    lease_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<&'static str>,
}

impl ControlResponse {
    fn capability(capability: RuntimeCapability) -> Self {
        Self {
            ok: true,
            pipe_name: Some(capability.pipe_name),
            capability: Some(capability.secret),
            lease_id: None,
            error: None,
        }
    }

    fn success() -> Self {
        Self {
            ok: true,
            pipe_name: None,
            capability: None,
            lease_id: None,
            error: None,
        }
    }

    fn lease(lease_id: String) -> Self {
        Self {
            lease_id: Some(lease_id),
            ..Self::success()
        }
    }

    fn error(error: &'static str) -> Self {
        Self {
            ok: false,
            pipe_name: None,
            capability: None,
            lease_id: None,
            error: Some(error),
        }
    }
}

/// Prepare the authenticated local control endpoint before the Python sidecar starts.
/// It does not start the Computer Use helper.
pub(crate) fn prepare(app: &tauri::AppHandle) -> Result<(), String> {
    {
        let state = app.state::<ComputerUseRuntimeState>();
        let mut control = state
            .control
            .lock()
            .map_err(|_| "computer use control state poisoned")?;
        if control.is_some() {
            return Ok(());
        }

        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .map_err(|err| format!("failed to bind Computer Use control endpoint: {err}"))?;
        listener
            .set_nonblocking(true)
            .map_err(|err| format!("failed to configure Computer Use control endpoint: {err}"))?;
        let port = listener
            .local_addr()
            .map_err(|err| format!("failed to inspect Computer Use control endpoint: {err}"))?
            .port();
        let token = random_hex(32);
        let stop = Arc::new(AtomicBool::new(false));
        let app_handle = app.clone();
        let thread_stop = Arc::clone(&stop);
        let thread_token = token.clone();
        let thread = thread::Builder::new()
            .name("computer-use-control".to_string())
            .spawn(move || serve_control(listener, app_handle, thread_token, thread_stop))
            .map_err(|err| format!("failed to start Computer Use control endpoint: {err}"))?;
        *control = Some(ControlEndpoint {
            port,
            token,
            stop,
            thread,
        });
    }
    Ok(())
}

/// Start the host-owned native helper when its packaged artifact is available.
pub(crate) fn ensure(app: &tauri::AppHandle) -> Result<(), String> {
    let (control_port, control_token) = helper_control_environment(app)?;
    let state = app.state::<ComputerUseRuntimeState>();
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "computer use runtime state poisoned")?;
    if let Some(child) = inner.child.as_mut() {
        match child.try_wait() {
            Ok(None) => return Ok(()),
            Ok(Some(status)) => {
                log::warn!("[computer-use] helper exited before next acquire: {status}");
                inner.helper_pid.take();
                #[cfg(target_os = "macos")]
                if clear_focus_leases(&mut inner) {
                    show_host_window(app);
                }
            }
            Err(error) => {
                return Err(format!("failed to inspect Computer Use helper: {error}"));
            }
        }
    }
    inner.child.take();
    if let Some(capability) = inner.capability.take() {
        cleanup_endpoint(&capability.pipe_name);
    }

    #[cfg(all(not(debug_assertions), target_os = "macos"))]
    let helper = crate::computer_use_helper::installed_bundle(app)?;
    #[cfg(not(all(not(debug_assertions), target_os = "macos")))]
    let helper = helper_path(app)?;
    let capability = RuntimeCapability {
        pipe_name: endpoint_address()?,
        secret: random_hex(32),
    };
    let mut command = helper_command(&helper, &capability);
    command
        .env(CONTROL_HOST_ENV, Ipv4Addr::LOCALHOST.to_string())
        .env(CONTROL_PORT_ENV, control_port.to_string())
        .env(CONTROL_TOKEN_ENV, control_token);
    #[cfg(all(not(debug_assertions), target_os = "macos"))]
    command.stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(not(all(not(debug_assertions), target_os = "macos")))]
    command.stdout(Stdio::piped()).stderr(Stdio::piped());

    let mut child = command
        .spawn()
        .map_err(|err| format!("failed to start Computer Use helper: {err}"))?;
    log::info!(
        "[computer-use] started helper pid={} path={}",
        child.id(),
        helper.display()
    );
    #[cfg(all(not(debug_assertions), target_os = "macos"))]
    {
        let helper_pid = match wait_for_macos_helper_ready(&mut child, &capability.pipe_name) {
            Ok(pid) => pid,
            Err(error) => {
                log::warn!("[computer-use] helper did not become ready: {error}");
                stop_unready_helper(&mut child);
                cleanup_endpoint(&capability.pipe_name);
                return Err(error);
            }
        };
        inner.child = Some(child);
        inner.capability = Some(capability);
        inner.helper_pid = Some(helper_pid);
        return Ok(());
    }
    #[cfg(not(all(not(debug_assertions), target_os = "macos")))]
    {
        let (ready, captured_stderr) = match observe_helper_output(&mut child) {
            Ok(output) => output,
            Err(error) => {
                stop_unready_helper(&mut child);
                cleanup_endpoint(&capability.pipe_name);
                return Err(error);
            }
        };
        if let Err(error) = wait_for_helper_ready(&mut child, &ready, &captured_stderr) {
            log::warn!("[computer-use] helper did not become ready: {error}");
            stop_unready_helper(&mut child);
            cleanup_endpoint(&capability.pipe_name);
            return Err(error);
        }
        #[cfg(windows)]
        assign_helper_to_job(&state, &child);
        inner.helper_pid = Some(child.id());
        inner.child = Some(child);
        inner.capability = Some(capability);
        Ok(())
    }
}

#[cfg(all(not(debug_assertions), target_os = "macos"))]
fn helper_command(helper: &Path, capability: &RuntimeCapability) -> Command {
    let mut command = Command::new("/usr/bin/open");
    command
        .args(["-n", "-W"])
        .arg(helper)
        .arg("--args")
        .args(["serve", "--pipe", &capability.pipe_name])
        // `open` carries this environment into the launched application. The
        // capability therefore remains out of argv while LaunchServices owns
        // the helper process identity.
        .env(CAPABILITY_ENV, &capability.secret)
        .env(HELPER_HOST_PID_ENV, std::process::id().to_string());
    command
}

fn helper_control_environment(app: &tauri::AppHandle) -> Result<(u16, String), String> {
    let state = app.state::<ComputerUseRuntimeState>();
    let control = state
        .control
        .lock()
        .map_err(|_| "computer use control state poisoned")?;
    let control = control
        .as_ref()
        .ok_or_else(|| "Computer Use control endpoint is unavailable".to_string())?;
    Ok((control.port, control.token.clone()))
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn helper_command(helper: &Path, capability: &RuntimeCapability) -> Command {
    let mut command = Command::new(helper);
    command.args(["serve", "--pipe", &capability.pipe_name]);
    // The secret travels in the environment, not on the command line: argv is
    // readable by any same-user process through `ps` / GetCommandLine, whereas
    // the environment is not exposed there. This matches how the backend
    // sidecar passes its shutdown token.
    command.env(CAPABILITY_ENV, &capability.secret);
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
    command
}

#[cfg(all(not(debug_assertions), target_os = "macos"))]
fn wait_for_macos_helper_ready(child: &mut Child, endpoint: &str) -> Result<u32, String> {
    use std::os::unix::fs::FileTypeExt;

    let deadline = Instant::now() + HELPER_READY_TIMEOUT;
    let pid_path = helper_pid_path(endpoint);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return Err(format!(
                    "Computer Use helper exited before readiness with {status}"
                ));
            }
            Ok(None) => {}
            Err(error) => {
                return Err(format!(
                    "failed while waiting for Computer Use helper readiness: {error}"
                ));
            }
        }

        let socket_ready = match std::fs::symlink_metadata(endpoint) {
            Ok(metadata) if metadata.file_type().is_socket() => true,
            Ok(_) => {
                return Err("Computer Use helper endpoint is not a Unix socket".to_string());
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
            Err(error) => {
                return Err(format!(
                    "failed to inspect Computer Use helper endpoint: {error}"
                ));
            }
        };
        if socket_ready {
            match std::fs::read_to_string(&pid_path) {
                Ok(value) => match value.trim().parse::<u32>() {
                    Ok(pid) if pid > 0 => {
                        log::info!("[computer-use] helper announced readiness pid={pid}");
                        return Ok(pid);
                    }
                    Ok(_) | Err(_) => {}
                },
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => {
                    return Err(format!(
                        "failed to inspect Computer Use helper pid marker: {error}"
                    ));
                }
            }
        }

        if Instant::now() >= deadline {
            return Err(format!(
                "timed out after {} seconds waiting for Computer Use helper readiness",
                HELPER_READY_TIMEOUT.as_secs()
            ));
        }
        thread::sleep(Duration::from_millis(100));
    }
}

/// Pipe child output into desktop logs and wait for its explicit readiness
/// signal. A successful process spawn is deliberately not considered ready:
/// macOS has yet to bind its Unix socket and Windows has yet to create the
/// first named-pipe instance at that point.
#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn observe_helper_output(
    child: &mut Child,
) -> Result<(mpsc::Receiver<Result<(), String>>, Arc<Mutex<String>>), String> {
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Computer Use helper stdout was not captured".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "Computer Use helper stderr was not captured".to_string())?;
    let (ready_sender, ready_receiver) = mpsc::channel();
    let captured_stderr = Arc::new(Mutex::new(String::new()));

    thread::Builder::new()
        .name("computer-use-helper-stdout".to_string())
        .spawn(move || watch_helper_stdout(stdout, ready_sender))
        .map_err(|error| format!("failed to watch Computer Use helper stdout: {error}"))?;

    let stderr_buffer = Arc::clone(&captured_stderr);
    thread::Builder::new()
        .name("computer-use-helper-stderr".to_string())
        .spawn(move || watch_helper_stderr(stderr, stderr_buffer))
        .map_err(|error| format!("failed to watch Computer Use helper stderr: {error}"))?;

    Ok((ready_receiver, captured_stderr))
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn watch_helper_stdout(stdout: ChildStdout, readiness: mpsc::Sender<Result<(), String>>) {
    let mut readiness_sent = false;
    for line in BufReader::new(stdout).lines() {
        match line {
            Ok(line) => match parse_helper_ready_line(&line) {
                Ok(Some(())) if !readiness_sent => {
                    readiness_sent = true;
                    let _ = readiness.send(Ok(()));
                    log::info!("[computer-use] helper announced readiness");
                }
                Ok(Some(())) => {
                    log::warn!("[computer-use] helper announced readiness more than once");
                }
                Ok(None) => {
                    log::info!("[computer-use] helper stdout: {line}");
                }
                Err(error) if !readiness_sent => {
                    readiness_sent = true;
                    let _ = readiness.send(Err(error));
                }
                Err(error) => {
                    log::warn!("[computer-use] ignoring invalid later readiness line: {error}");
                }
            },
            Err(error) => {
                if !readiness_sent {
                    readiness_sent = true;
                    let _ = readiness.send(Err(format!(
                        "failed to read Computer Use helper stdout: {error}"
                    )));
                }
                break;
            }
        }
    }

    if !readiness_sent {
        let _ = readiness.send(Err(
            "Computer Use helper closed stdout before announcing readiness".to_string(),
        ));
    }
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn watch_helper_stderr(stderr: ChildStderr, captured_stderr: Arc<Mutex<String>>) {
    for line in BufReader::new(stderr).lines() {
        match line {
            Ok(line) => {
                log::error!("[computer-use] helper stderr: {line}");
                if let Ok(mut buffer) = captured_stderr.lock() {
                    append_captured_stderr(&mut buffer, &line);
                }
            }
            Err(error) => {
                log::warn!("[computer-use] failed to read helper stderr: {error}");
                break;
            }
        }
    }
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn parse_helper_ready_line(line: &str) -> Result<Option<()>, String> {
    let Some(payload) = line.strip_prefix(HELPER_READY_PREFIX) else {
        return Ok(None);
    };
    let ready: HelperReadyPayload = serde_json::from_str(payload)
        .map_err(|error| format!("Computer Use helper emitted invalid readiness JSON: {error}"))?;
    if ready.protocol_version != PROTOCOL_VERSION {
        return Err(format!(
            "Computer Use helper protocol {} is incompatible with host protocol {}",
            ready.protocol_version, PROTOCOL_VERSION
        ));
    }
    Ok(Some(()))
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn wait_for_helper_ready(
    child: &mut Child,
    readiness: &mpsc::Receiver<Result<(), String>>,
    captured_stderr: &Arc<Mutex<String>>,
) -> Result<(), String> {
    let deadline = Instant::now() + HELPER_READY_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return Err(format!(
                    "Computer Use helper exited before readiness with {status}{}",
                    captured_stderr_suffix(captured_stderr)
                ));
            }
            Ok(None) => {}
            Err(error) => {
                return Err(format!(
                    "failed while waiting for Computer Use helper readiness: {error}{}",
                    captured_stderr_suffix(captured_stderr)
                ));
            }
        }

        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(format!(
                "timed out after {} seconds waiting for Computer Use helper readiness{}",
                HELPER_READY_TIMEOUT.as_secs(),
                captured_stderr_suffix(captured_stderr)
            ));
        }
        match readiness.recv_timeout(remaining.min(Duration::from_millis(100))) {
            Ok(Ok(())) => match child.try_wait() {
                Ok(None) => return Ok(()),
                Ok(Some(status)) => {
                    return Err(format!(
                        "Computer Use helper exited immediately after readiness with {status}{}",
                        captured_stderr_suffix(captured_stderr)
                    ));
                }
                Err(error) => {
                    return Err(format!(
                        "failed to inspect Computer Use helper after readiness: {error}{}",
                        captured_stderr_suffix(captured_stderr)
                    ));
                }
            },
            Ok(Err(error)) => {
                return Err(format!(
                    "{error}{}",
                    captured_stderr_suffix(captured_stderr)
                ));
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err(format!(
                    "Computer Use helper output watcher stopped before readiness{}",
                    captured_stderr_suffix(captured_stderr)
                ));
            }
        }
    }
}

fn stop_unready_helper(child: &mut Child) {
    if let Err(error) = child.kill() {
        if error.kind() != std::io::ErrorKind::InvalidInput {
            log::warn!("[computer-use] failed to stop unready helper: {error}");
        }
    }
    if let Err(error) = child.wait() {
        log::warn!("[computer-use] failed to reap unready helper: {error}");
    }
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn append_captured_stderr(buffer: &mut String, line: &str) {
    buffer.push_str(line);
    buffer.push('\n');
    let excess = buffer
        .chars()
        .count()
        .saturating_sub(MAX_CAPTURED_HELPER_STDERR_CHARS);
    if excess > 0 {
        *buffer = buffer.chars().skip(excess).collect();
    }
}

#[cfg(not(all(not(debug_assertions), target_os = "macos")))]
fn captured_stderr_suffix(captured_stderr: &Arc<Mutex<String>>) -> String {
    let Ok(captured_stderr) = captured_stderr.lock() else {
        return String::new();
    };
    let stderr = captured_stderr.trim();
    if stderr.is_empty() {
        String::new()
    } else {
        format!("; helper stderr: {stderr}")
    }
}

/// Bind the helper to a kill-on-close Job Object so the OS reaps it whenever
/// this desktop process goes away — even on crashes or force-kills that never
/// reach the graceful `stop` path. Best-effort: any failure is logged and the
/// helper still runs (falling back to the explicit `child.kill()` in `stop`).
#[cfg(windows)]
fn assign_helper_to_job(state: &ComputerUseRuntimeState, child: &Child) {
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{CloseHandle, HANDLE};
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    let mut job_guard = match state.job.lock() {
        Ok(guard) => guard,
        Err(_) => {
            log::warn!("[computer-use] job object state poisoned");
            return;
        }
    };

    if job_guard.is_none() {
        let handle = match unsafe { CreateJobObjectW(None, PCWSTR::null()) } {
            Ok(handle) if !handle.is_invalid() => handle,
            Ok(_) => {
                log::warn!("[computer-use] CreateJobObjectW returned invalid handle");
                return;
            }
            Err(err) => {
                log::warn!("[computer-use] CreateJobObjectW failed: {err}");
                return;
            }
        };
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if let Err(err) = unsafe {
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const core::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            )
        } {
            log::warn!("[computer-use] SetInformationJobObject failed: {err}");
            let _ = unsafe { CloseHandle(handle) };
            return;
        }
        *job_guard = Some(handle.0 as isize);
    }

    if let Some(raw) = *job_guard {
        let job = HANDLE(raw as *mut core::ffi::c_void);
        let process = HANDLE(child.as_raw_handle() as *mut core::ffi::c_void);
        if let Err(err) = unsafe { AssignProcessToJobObject(job, process) } {
            log::warn!("[computer-use] AssignProcessToJobObject failed: {err}");
        }
    }
}

/// Return the sidecar-only environment used by the controlled client.
pub(crate) fn backend_environment(app: &tauri::AppHandle) -> Vec<(String, String)> {
    let mut environment = Vec::new();
    if let Ok(control) = app.state::<ComputerUseRuntimeState>().control.lock() {
        if let Some(control) = control.as_ref() {
            environment.extend([
                (
                    "QWENPAW_COMPUTER_USE_CONTROL_HOST".to_string(),
                    Ipv4Addr::LOCALHOST.to_string(),
                ),
                (
                    "QWENPAW_COMPUTER_USE_CONTROL_PORT".to_string(),
                    control.port.to_string(),
                ),
                (
                    "QWENPAW_COMPUTER_USE_CONTROL_TOKEN".to_string(),
                    control.token.clone(),
                ),
            ]);
        }
    }

    let state = app.state::<ComputerUseRuntimeState>();
    if let Ok(inner) = state.inner.lock() {
        if let Some(capability) = inner.capability.as_ref() {
            environment.extend([
                (
                    "QWENPAW_COMPUTER_USE_PIPE".to_string(),
                    capability.pipe_name.clone(),
                ),
                (
                    "QWENPAW_COMPUTER_USE_CAPABILITY".to_string(),
                    capability.secret.clone(),
                ),
                (
                    "QWENPAW_COMPUTER_USE_PROTOCOL".to_string(),
                    PROTOCOL_VERSION.to_string(),
                ),
            ]);
        }
    }
    environment
}

/// Stop the helper when the desktop host exits.
pub(crate) fn stop(app: &tauri::AppHandle) {
    let state = app.state::<ComputerUseRuntimeState>();
    if let Some(control) = state
        .control
        .lock()
        .ok()
        .and_then(|mut control| control.take())
    {
        control.stop.store(true, Ordering::Release);
        if control.thread.join().is_err() {
            log::warn!("[computer-use] control endpoint stopped unexpectedly");
        }
    }
    if let Err(error) = stop_helper(app) {
        log::warn!("[computer-use] failed to stop helper: {error}");
    }
}

/// Terminate the managed helper as part of desktop-host shutdown.
fn stop_helper(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<ComputerUseRuntimeState>();
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "computer use runtime state poisoned")?;
    let child = inner.child.take();
    let capability = inner.capability.take();
    let helper_pid = inner.helper_pid.take();
    #[cfg(target_os = "macos")]
    let restore_host = clear_focus_leases(&mut inner);
    drop(inner);

    #[cfg(target_os = "macos")]
    if restore_host {
        show_host_window(app);
    }

    if let Some(mut child) = child {
        stop_managed_child(&mut child, helper_pid)?;
    }
    if let Some(capability) = capability {
        cleanup_endpoint(&capability.pipe_name);
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn stop_managed_child(child: &mut Child, helper_pid: Option<u32>) -> Result<(), String> {
    if let Some(pid) = helper_pid.and_then(|pid| i32::try_from(pid).ok()) {
        let result = unsafe { libc::kill(pid, libc::SIGTERM) };
        if result != 0 {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() != Some(libc::ESRCH) {
                return Err(format!(
                    "failed to terminate Computer Use helper {pid}: {error}"
                ));
            }
        }
        let deadline = Instant::now() + Duration::from_secs(1);
        while Instant::now() < deadline {
            if unsafe { libc::kill(pid, 0) } != 0
                && std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH)
            {
                break;
            }
            thread::sleep(Duration::from_millis(20));
        }
        if unsafe { libc::kill(pid, 0) } == 0 {
            let _ = unsafe { libc::kill(pid, libc::SIGKILL) };
        }
    } else if let Err(error) = child.kill() {
        if error.kind() != std::io::ErrorKind::InvalidInput {
            return Err(format!("failed to stop Computer Use launcher: {error}"));
        }
    }

    // The release build is started through `open -W`, so `child` is the
    // launcher rather than the helper itself. Do not let a broken launcher
    // turn cancellation or app shutdown into an unbounded wait.
    let deadline = Instant::now() + Duration::from_secs(1);
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return Ok(()),
            Ok(None) => thread::sleep(Duration::from_millis(20)),
            Err(error) => {
                return Err(format!("failed to inspect Computer Use launcher: {error}"));
            }
        }
    }
    if let Err(error) = child.kill() {
        if error.kind() != std::io::ErrorKind::InvalidInput {
            return Err(format!("failed to stop Computer Use launcher: {error}"));
        }
    }
    child
        .wait()
        .map(|_| ())
        .map_err(|error| format!("failed to reap Computer Use launcher: {error}"))
}

#[cfg(not(target_os = "macos"))]
fn stop_managed_child(child: &mut Child, _helper_pid: Option<u32>) -> Result<(), String> {
    if let Err(error) = child.kill() {
        if error.kind() != std::io::ErrorKind::InvalidInput {
            return Err(format!("failed to stop Computer Use helper: {error}"));
        }
    }
    child
        .wait()
        .map(|_| ())
        .map_err(|error| format!("failed to reap Computer Use helper: {error}"))
}

fn random_hex(byte_count: usize) -> String {
    let mut bytes = vec![0_u8; byte_count];
    rand::rng().fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Build the endpoint the helper listens on: a Windows named pipe name, or a
/// private Unix domain socket path on other platforms. The value is passed to
/// the helper via `--pipe` and returned to the Python sidecar as the opaque
/// capability endpoint, so both transports read it from the same field.
#[cfg(windows)]
fn endpoint_address() -> Result<String, String> {
    // A named pipe needs no backing directory, so this cannot fail; it returns
    // Result only to share one signature with the Unix path, whose directory
    // creation can.
    Ok(format!(
        "qwenpaw-computer-use-{}-{}",
        std::process::id(),
        random_hex(12),
    ))
}

#[cfg(not(windows))]
fn endpoint_address() -> Result<String, String> {
    // The directory name is random rather than derived from the pid: a
    // predictable name in a world-writable /tmp can be pre-created by another
    // user, and everything placed inside it afterwards would then live in
    // space they control. Creating it with the mode already set closes the
    // window where it exists world-readable, and refusing to create it
    // recursively means an existing path is an error rather than something we
    // silently adopt.
    //
    // That last guarantee only holds if the error is surfaced: swallowing it
    // would let a pre-existing, possibly attacker-owned directory be adopted
    // anyway, and would also leave the later socket bind failing from inside a
    // directory that was never created. The helper targets macOS here, so the
    // unix builder is the only path; there is no non-unix fallback to weaken.
    use std::os::unix::fs::DirBuilderExt;
    // macOS's `temp_dir()` is normally a long per-user path below
    // `/var/folders/.../T`. A Unix-domain socket has a platform-defined,
    // small `sun_path` buffer (104 bytes on Darwin), so a secure random
    // directory below that root can already make the final socket name too
    // long to bind. `/tmp` is the system-owned short alias for `/private/tmp`;
    // the unique 0700 child directory below keeps the socket private even
    // though the root itself is shared.
    let socket_root = if cfg!(target_os = "macos") {
        PathBuf::from("/tmp")
    } else {
        std::env::temp_dir()
    };
    let dir = socket_root.join(format!("qwenpaw-cu-{}", random_hex(16)));
    std::fs::DirBuilder::new()
        .recursive(false)
        .mode(0o700)
        .create(&dir)
        .map_err(|error| format!("failed to create socket directory: {error}"))?;
    Ok(dir
        .join(format!("{}.sock", random_hex(8)))
        .to_string_lossy()
        .into_owned())
}

#[cfg(windows)]
fn cleanup_endpoint(_endpoint: &str) {
    // Named-pipe instances disappear when their helper process exits.
}

#[cfg(not(windows))]
fn helper_pid_path(endpoint: &str) -> PathBuf {
    Path::new(endpoint).with_extension("pid")
}

#[cfg(not(windows))]
fn cleanup_endpoint(endpoint: &str) {
    let path = Path::new(endpoint);
    match std::fs::remove_file(path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => log::warn!(
            "[computer-use] failed to remove helper socket {}: {error}",
            path.display()
        ),
    }
    let pid_path = helper_pid_path(endpoint);
    match std::fs::remove_file(&pid_path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => log::warn!(
            "[computer-use] failed to remove helper pid marker {}: {error}",
            pid_path.display()
        ),
    }

    let Some(directory) = path.parent() else {
        return;
    };
    let is_ours = directory
        .file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.starts_with("qwenpaw-cu-"));
    if !is_ours {
        log::warn!(
            "[computer-use] refusing to remove unexpected helper socket directory {}",
            directory.display()
        );
        return;
    }
    match std::fs::remove_dir(directory) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => log::debug!(
            "[computer-use] failed to remove helper socket directory {}: {error}",
            directory.display()
        ),
    }
}

#[cfg(target_os = "macos")]
fn begin_focus_lease(
    app: &tauri::AppHandle,
    helper_pid: u32,
    lease_id: &str,
) -> Result<String, &'static str> {
    let state = app.state::<ComputerUseRuntimeState>();
    {
        let inner = state.inner.lock().map_err(|_| "runtime_unavailable")?;
        if inner.helper_pid != Some(helper_pid) || inner.child.is_none() {
            return Err("stale_helper");
        }
        // The helper supplies the identifier, so retrying a control request
        // after a lost response cannot create an assertion that no turn owns.
        if inner.focus_leases.contains(lease_id) {
            return Ok(lease_id.to_string());
        }
    }

    let window = app.get_webview_window("main");
    let host_is_visible = window
        .as_ref()
        .and_then(|window| window.is_visible().ok())
        .unwrap_or(false);
    if host_is_visible {
        window
            .as_ref()
            .ok_or("runtime_unavailable")?
            .hide()
            .map_err(|_| "focus_failed")?;
    }

    let restore_uncommitted_host = || {
        if !host_is_visible {
            return;
        }
        let Some(window) = window.as_ref() else {
            return;
        };
        if let Err(error) = window.show() {
            log::warn!("[computer-use] failed to restore host window: {error}");
        }
    };
    let mut inner = match state.inner.lock() {
        Ok(inner) if inner.helper_pid == Some(helper_pid) && inner.child.is_some() => inner,
        Ok(_) => {
            restore_uncommitted_host();
            return Err("stale_helper");
        }
        Err(_) => {
            restore_uncommitted_host();
            return Err("runtime_unavailable");
        }
    };
    inner.restore_host_after_focus |= host_is_visible;
    inner.focus_leases.insert(lease_id.to_string());
    Ok(lease_id.to_string())
}

#[cfg(target_os = "macos")]
fn end_focus_lease(
    app: &tauri::AppHandle,
    helper_pid: u32,
    lease_id: &str,
) -> Result<(), &'static str> {
    let state = app.state::<ComputerUseRuntimeState>();
    let mut inner = state.inner.lock().map_err(|_| "runtime_unavailable")?;
    if inner.helper_pid != Some(helper_pid) || inner.child.is_none() {
        return Err("stale_helper");
    }
    inner.focus_leases.remove(lease_id);
    let restore_host = inner.focus_leases.is_empty() && inner.restore_host_after_focus;
    if restore_host {
        inner.restore_host_after_focus = false;
    }
    drop(inner);
    if restore_host {
        show_host_window(app);
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn clear_focus_leases(inner: &mut RuntimeInner) -> bool {
    inner.focus_leases.clear();
    std::mem::take(&mut inner.restore_host_after_focus)
}

#[cfg(target_os = "macos")]
fn show_host_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if let Err(error) = window.show() {
            log::warn!("[computer-use] failed to restore host window: {error}");
        }
    }
}

fn reap_exited_helper(app: &tauri::AppHandle) {
    let state = app.state::<ComputerUseRuntimeState>();
    let reaped = state.inner.lock().ok().and_then(|mut inner| {
        let exited = inner
            .child
            .as_mut()
            .and_then(|child| child.try_wait().ok().flatten());
        let status = exited?;
        let capability = inner.capability.take();
        inner.child.take();
        inner.helper_pid.take();
        #[cfg(target_os = "macos")]
        let restore_host = clear_focus_leases(&mut inner);
        #[cfg(not(target_os = "macos"))]
        let restore_host = ();
        Some((status, capability, restore_host))
    });
    let Some((status, capability, restore_host)) = reaped else {
        return;
    };
    log::warn!("[computer-use] helper exited: {status}");
    #[cfg(target_os = "macos")]
    if restore_host {
        show_host_window(app);
    }
    #[cfg(not(target_os = "macos"))]
    let _ = restore_host;
    if let Some(capability) = capability {
        cleanup_endpoint(&capability.pipe_name);
    }
}

fn serve_control(
    listener: TcpListener,
    app: tauri::AppHandle,
    token: String,
    stop: Arc<AtomicBool>,
) {
    while !stop.load(Ordering::Acquire) {
        reap_exited_helper(&app);
        match listener.accept() {
            Ok((stream, address)) if address.ip().is_loopback() => {
                if let Err(err) = serve_control_connection(stream, &app, &token) {
                    log::debug!("[computer-use] control connection failed: {err}");
                }
            }
            Ok(_) => {}
            Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(20));
            }
            Err(err) => {
                log::warn!("[computer-use] control endpoint accept failed: {err}");
                thread::sleep(Duration::from_millis(20));
            }
        }
    }
}

fn serve_control_connection(
    mut stream: TcpStream,
    app: &tauri::AppHandle,
    token: &str,
) -> Result<(), String> {
    stream
        .set_read_timeout(Some(CONTROL_CONNECTION_TIMEOUT))
        .map_err(|err| err.to_string())?;
    stream
        .set_write_timeout(Some(CONTROL_CONNECTION_TIMEOUT))
        .map_err(|err| err.to_string())?;

    let response = match read_control_request(&stream) {
        Ok(request) if request.token != token => ControlResponse::error("unauthorized"),
        Ok(request) => match request.action.as_str() {
            "acquire" => match ensure(app).and_then(|_| {
                runtime_capability(app)
                    .ok_or_else(|| "Computer Use helper did not expose a capability".to_string())
            }) {
                Ok(capability) => ControlResponse::capability(capability),
                Err(err) => {
                    log::warn!("[computer-use] control acquire failed: {err}");
                    ControlResponse::error("runtime_unavailable")
                }
            },
            #[cfg(target_os = "macos")]
            "begin_focus" => match (request.helper_pid, request.lease_id.as_deref()) {
                (Some(helper_pid), Some(lease_id)) if !lease_id.is_empty() => {
                    match begin_focus_lease(app, helper_pid, lease_id) {
                        Ok(lease_id) => ControlResponse::lease(lease_id),
                        Err(error) => ControlResponse::error(error),
                    }
                }
                _ => ControlResponse::error("invalid_request"),
            },
            #[cfg(target_os = "macos")]
            "end_focus" => match (request.helper_pid, request.lease_id.as_deref()) {
                (Some(helper_pid), Some(lease_id)) => {
                    match end_focus_lease(app, helper_pid, lease_id) {
                        Ok(()) => ControlResponse::success(),
                        Err(error) => ControlResponse::error(error),
                    }
                }
                _ => ControlResponse::error("invalid_request"),
            },
            _ => ControlResponse::error("invalid_request"),
        },
        Err(_) => ControlResponse::error("invalid_request"),
    };
    let payload = serde_json::to_vec(&response)
        .map_err(|err| format!("failed to encode Computer Use control response: {err}"))?;
    stream
        .write_all(&payload)
        .and_then(|_| stream.write_all(b"\n"))
        .and_then(|_| stream.flush())
        .map_err(|err| err.to_string())
}

fn read_control_request(stream: &TcpStream) -> Result<ControlRequest, String> {
    let reader = stream.try_clone().map_err(|err| err.to_string())?;
    let mut reader = BufReader::new(reader);
    let mut payload = Vec::new();
    let size = reader
        .by_ref()
        .take((CONTROL_MAX_MESSAGE_BYTES + 1) as u64)
        .read_until(b'\n', &mut payload)
        .map_err(|err| err.to_string())?;
    if size == 0 || payload.len() > CONTROL_MAX_MESSAGE_BYTES || !payload.ends_with(b"\n") {
        return Err("invalid control request".to_string());
    }
    serde_json::from_slice(&payload).map_err(|err| err.to_string())
}

fn runtime_capability(app: &tauri::AppHandle) -> Option<RuntimeCapability> {
    app.state::<ComputerUseRuntimeState>()
        .inner
        .lock()
        .ok()?
        .capability
        .clone()
}

#[cfg(debug_assertions)]
fn helper_path(_app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let target_dir = std::env::var_os("CARGO_TARGET_DIR")
        .map(PathBuf::from)
        .map(|path| {
            if path.is_absolute() {
                path
            } else {
                manifest_dir.join(path)
            }
        })
        .unwrap_or_else(|| manifest_dir.join("target"));
    let path = target_dir.join("debug").join(helper_name());
    path.is_file()
        .then_some(path.clone())
        .ok_or_else(|| format!("Computer Use helper not found at {}", path.display()))
}

#[cfg(all(not(debug_assertions), not(target_os = "macos")))]
fn helper_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let path = app
        .path()
        .resource_dir()
        .map_err(|err| format!("failed to resolve resources: {err}"))?
        .join("binaries")
        .join("qwenpaw-backend")
        .join(helper_name());
    path.is_file()
        .then_some(path.clone())
        .ok_or_else(|| format!("Computer Use helper not found at {}", path.display()))
}

#[cfg(any(debug_assertions, not(target_os = "macos")))]
fn helper_name() -> &'static str {
    if cfg!(windows) {
        "qwenpaw-computer-use-helper.exe"
    } else {
        "qwenpaw-computer-use-helper"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_matching_helper_ready_line() {
        let line =
            format!("QWENPAW_COMPUTER_USE_READY {{\"protocol_version\":{PROTOCOL_VERSION}}}");
        assert_eq!(parse_helper_ready_line(&line), Ok(Some(())));
    }

    #[test]
    fn ignores_ordinary_helper_output() {
        assert_eq!(parse_helper_ready_line("ordinary helper log"), Ok(None));
    }

    #[test]
    fn rejects_incompatible_helper_ready_line() {
        let line = format!(
            "QWENPAW_COMPUTER_USE_READY {{\"protocol_version\":{}}}",
            PROTOCOL_VERSION + 1
        );
        let error =
            parse_helper_ready_line(&line).expect_err("protocol mismatch must fail startup");

        assert!(error.contains("incompatible"));
    }

    #[test]
    fn captured_stderr_keeps_the_most_recent_output() {
        let mut buffer = String::new();
        append_captured_stderr(&mut buffer, &"old".repeat(MAX_CAPTURED_HELPER_STDERR_CHARS));
        append_captured_stderr(&mut buffer, "latest");

        assert!(buffer.chars().count() <= MAX_CAPTURED_HELPER_STDERR_CHARS);
        assert!(buffer.ends_with("latest\n"));
    }

    #[test]
    fn control_requests_keep_focus_fields_optional() {
        let request: ControlRequest =
            serde_json::from_str(r#"{"token":"token","action":"acquire"}"#)
                .expect("control request should parse");

        assert!(request.helper_pid.is_none());
        assert!(request.lease_id.is_none());
    }
}
