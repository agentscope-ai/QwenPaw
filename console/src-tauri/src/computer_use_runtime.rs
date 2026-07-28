//! Desktop-owned lifecycle for the native Computer Use helper.
//!
//! The authenticated localhost control endpoint and capability handoff are
//! platform neutral; only the kill-on-close Job Object and the console-window
//! spawn flag remain Windows specific (macOS relies on the helper's own
//! parent-death watch for reaping).

use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use std::{
    io::{BufRead, BufReader, Read, Write},
    net::{Ipv4Addr, TcpListener, TcpStream},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread::{self, JoinHandle},
    time::Duration,
};
#[cfg(windows)]
use std::os::windows::{io::AsRawHandle, process::CommandExt};

use rand::RngCore;
use serde::{Deserialize, Serialize};
use tauri::Manager;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
// The helper reads the capability secret from this variable. Kept in step with
// the same name in computer_use_server::parse_arguments, which is a separate
// binary and cannot share the constant.
const CAPABILITY_ENV: &str = "QWENPAW_CU_CAPABILITY";
const CONTROL_PROTOCOL_VERSION: u8 = 1;
const CONTROL_MAX_MESSAGE_BYTES: usize = 4096;

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
    protocol_version: u8,
    token: String,
    action: String,
}

#[derive(Serialize)]
struct ControlResponse {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pipe_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    capability: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    protocol_version: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<&'static str>,
}

impl ControlResponse {
    fn capability(capability: RuntimeCapability) -> Self {
        Self {
            ok: true,
            pipe_name: Some(capability.pipe_name),
            capability: Some(capability.secret),
            protocol_version: Some(CONTROL_PROTOCOL_VERSION),
            error: None,
        }
    }

    fn error(error: &'static str) -> Self {
        Self {
            ok: false,
            pipe_name: None,
            capability: None,
            protocol_version: None,
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
    let state = app.state::<ComputerUseRuntimeState>();
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "computer use runtime state poisoned")?;
    if inner
        .child
        .as_mut()
        .is_some_and(|child| child.try_wait().ok().flatten().is_none())
    {
        return Ok(());
    }
    inner.child.take();
    inner.capability.take();

    let helper = helper_path(app)?;
    let capability = RuntimeCapability {
        pipe_name: endpoint_address(),
        secret: random_hex(32),
    };
    let mut command = Command::new(&helper);
    command.args(["serve", "--pipe", &capability.pipe_name]);
    // The secret travels in the environment, not on the command line: argv is
    // readable by any same-user process through `ps` / GetCommandLine, whereas
    // the environment is not exposed there. This matches how the backend
    // sidecar passes its shutdown token.
    command.env(CAPABILITY_ENV, &capability.secret);
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    let child = command
        .spawn()
        .map_err(|err| format!("failed to start Computer Use helper: {err}"))?;
    log::info!(
        "[computer-use] started helper pid={} path={}",
        child.id(),
        helper.display()
    );
    #[cfg(windows)]
    assign_helper_to_job(&state, &child);
    inner.child = Some(child);
    inner.capability = Some(capability);
    Ok(())
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
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
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
                (
                    "QWENPAW_COMPUTER_USE_CONTROL_PROTOCOL".to_string(),
                    CONTROL_PROTOCOL_VERSION.to_string(),
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
                ("QWENPAW_COMPUTER_USE_PROTOCOL".to_string(), "1".to_string()),
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
    let child = state.inner.lock().ok().and_then(|mut inner| {
        inner.capability.take();
        inner.child.take()
    });
    if let Some(mut child) = child {
        if let Err(err) = child.kill() {
            log::warn!("[computer-use] failed to stop helper: {err}");
        }
    }
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
fn endpoint_address() -> String {
    format!(
        "qwenpaw-computer-use-{}-{}",
        std::process::id(),
        random_hex(12),
    )
}

#[cfg(not(windows))]
fn endpoint_address() -> String {
    // The directory name is random rather than derived from the pid: a
    // predictable name in a world-writable /tmp can be pre-created by another
    // user, and everything placed inside it afterwards would then live in
    // space they control. Creating it with the mode already set closes the
    // window where it exists world-readable, and refusing to create it
    // recursively means an existing path is an error rather than something we
    // silently adopt.
    let dir = std::env::temp_dir().join(format!("qwenpaw-cu-{}", random_hex(16)));
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        let _ = std::fs::DirBuilder::new()
            .recursive(false)
            .mode(0o700)
            .create(&dir);
    }
    #[cfg(not(unix))]
    {
        let _ = std::fs::create_dir(&dir);
    }
    dir.join(format!("{}.sock", random_hex(8)))
        .to_string_lossy()
        .into_owned()
}

fn serve_control(
    listener: TcpListener,
    app: tauri::AppHandle,
    token: String,
    stop: Arc<AtomicBool>,
) {
    while !stop.load(Ordering::Acquire) {
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
        .set_read_timeout(Some(Duration::from_millis(500)))
        .map_err(|err| err.to_string())?;
    stream
        .set_write_timeout(Some(Duration::from_millis(500)))
        .map_err(|err| err.to_string())?;

    let response = match read_control_request(&stream) {
        Ok(request)
            if request.protocol_version == CONTROL_PROTOCOL_VERSION
                && request.token == token
                && request.action == "acquire" =>
        {
            match ensure(app).and_then(|_| {
                runtime_capability(app)
                    .ok_or_else(|| "Computer Use helper did not expose a capability".to_string())
            }) {
                Ok(capability) => ControlResponse::capability(capability),
                Err(err) => {
                    log::warn!("[computer-use] control acquire failed: {err}");
                    ControlResponse::error("runtime_unavailable")
                }
            }
        }
        Ok(_) => ControlResponse::error("unauthorized"),
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

#[cfg(not(debug_assertions))]
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

fn helper_name() -> &'static str {
    if cfg!(windows) {
        "qwenpaw-computer-use-helper.exe"
    } else {
        "qwenpaw-computer-use-helper"
    }
}
