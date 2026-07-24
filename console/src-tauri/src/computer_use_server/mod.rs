use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;

// Windows named-pipe server primitives. The macOS build listens on a Unix
// domain socket instead (see the platform_macos leaf and the cfg-split run).
#[cfg(windows)]
use std::fs::File;
#[cfg(windows)]
use std::os::windows::io::FromRawHandle;
#[cfg(windows)]
use windows::core::PCWSTR;
#[cfg(windows)]
use windows::Win32::Foundation::{GetLastError, ERROR_PIPE_CONNECTED, INVALID_HANDLE_VALUE};
#[cfg(windows)]
use windows::Win32::Storage::FileSystem::PIPE_ACCESS_DUPLEX;
#[cfg(windows)]
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};
#[cfg(windows)]
use windows::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE,
    PIPE_UNLIMITED_INSTANCES, PIPE_WAIT,
};

mod framing;
use framing::{read_message, request_id, write_error, write_message, write_result};

// Platform leaves expose the same function surface (window discovery, capture,
// UI automation, input); only the implementation differs. The shared dispatch
// core below never names a platform-specific type directly.
#[cfg(windows)]
mod window;
#[cfg(windows)]
mod capture;
#[cfg(windows)]
mod uia;
#[cfg(windows)]
mod input;
#[cfg(windows)]
use capture::observe_window;
#[cfg(windows)]
use input::{
    click, drag, press_key, reject_recent_user_intervention, scroll, set_focus, type_text,
};
#[cfg(windows)]
use uia::{collect_accessibility, invoke_element, set_value};
#[cfg(windows)]
use window::{is_forbidden, list_apps, list_windows, resolve_window};

#[cfg(target_os = "macos")]
mod platform_macos;
#[cfg(target_os = "macos")]
use platform_macos::{
    click, drag, invoke_element, is_forbidden, list_apps, list_windows, observe_window, press_key,
    resolve_window, scroll, set_focus, set_value, type_text,
};

/// Native accessibility element handle stored in an accessibility snapshot.
/// Windows uses a UI Automation element; macOS uses an AXUIElement wrapper.
#[cfg(windows)]
type NativeElement = windows::Win32::UI::Accessibility::IUIAutomationElement;
#[cfg(target_os = "macos")]
type NativeElement = platform_macos::AxElement;

const PROTOCOL_VERSION: u64 = 1;
const MAX_FRAME_BYTES: usize = 64 * 1024 * 1024;
const USER_INTERVENTION_GRACE_MS: u32 = 750;
// Raw window captures are 32bpp bitmaps; re-encode them as JPEG so a
// single screenshot costs hundreds of kilobytes instead of tens of
// megabytes once it is base64-encoded into the response payload.
const SCREENSHOT_JPEG_QUALITY: f32 = 0.8;
// Cap the longest edge of a delivered screenshot. High-resolution
// displays (for example 4K) would otherwise produce multi-megabyte
// base64 payloads that inflate the response and the model's image cost.
// Downscaling to a bounded edge keeps the payload small while leaving
// enough detail for reading on-screen text and controls.
const SCREENSHOT_MAX_EDGE: u32 = 1600;
const BMP_HEADER_BYTES: usize = 54;
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
struct WindowInfo {
    hwnd: isize,
    app_id: String,
    display_name: String,
    title: String,
    class_name: String,
}

struct Snapshot {
    window: WindowInfo,
    bounds: [i32; 4],
    screenshot_id: String,
    // Pixel size of the delivered (possibly downscaled) screenshot. Model
    // coordinates are expressed in this space and mapped back to physical
    // window pixels before input is injected.
    display_width: u32,
    display_height: u32,
}

struct AccessibilitySnapshot {
    window_hwnd: isize,
    elements: HashMap<String, NativeElement>,
}

#[derive(Default)]
struct ServerState {
    snapshots: HashMap<String, Snapshot>,
    accessibility: HashMap<String, AccessibilitySnapshot>,
    stopped_turn: Option<String>,
}

#[cfg(windows)]
pub(super) fn run(args: &[String]) -> Result<(), String> {
    let (pipe_name, capability) = parse_arguments(args)?;
    let result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
    if result.is_err() {
        return Err(format!("CoInitializeEx failed: {result}"));
    }
    let pipe_path = format!(r"\\.\pipe\{pipe_name}");
    loop {
        let mut connection = accept_connection(&pipe_path)?;
        let worker_capability = capability.clone();
        let worker = thread::Builder::new()
            .name("computer-use-conn".to_string())
            .spawn(move || {
                let com_result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
                if com_result.is_err() {
                    eprintln!("Computer Use worker CoInitializeEx failed: {com_result}");
                    return;
                }
                if let Err(error) = serve_connection(&mut connection, &worker_capability) {
                    eprintln!("Computer Use pipe connection ended: {error}");
                }
            });
        if let Err(error) = worker {
            eprintln!("Computer Use worker thread spawn failed: {error}");
        }
    }
}

#[cfg(target_os = "macos")]
pub(super) fn run(args: &[String]) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixListener;
    let (socket_path, capability) = parse_arguments(args)?;
    // Fresh bind: clear any stale socket file left by a previous run.
    let _ = std::fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path)
        .map_err(|error| format!("failed to bind Computer Use socket: {error}"))?;
    let _ = std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600));
    // macOS has no Job Object; exit when the desktop parent goes away so the
    // helper is reaped on host crash or force-quit.
    platform_macos::spawn_parent_death_watch();
    for stream in listener.incoming() {
        let mut connection = match stream {
            Ok(stream) => stream,
            Err(error) => {
                eprintln!("Computer Use socket accept failed: {error}");
                continue;
            }
        };
        let worker_capability = capability.clone();
        let worker = thread::Builder::new()
            .name("computer-use-conn".to_string())
            .spawn(move || {
                if let Err(error) = serve_connection(&mut connection, &worker_capability) {
                    eprintln!("Computer Use socket connection ended: {error}");
                }
            });
        if let Err(error) = worker {
            eprintln!("Computer Use worker thread spawn failed: {error}");
        }
    }
    Ok(())
}

fn parse_arguments(args: &[String]) -> Result<(String, String), String> {
    let mut pipe_name = None;
    let mut capability = None;
    let mut index = 0;
    while index < args.len() {
        let value = &args[index];
        index += 1;
        let target = match value.as_str() {
            "--pipe" => &mut pipe_name,
            "--capability" => &mut capability,
            _ => return Err(format!("unknown argument: {value}")),
        };
        let next = args
            .get(index)
            .ok_or_else(|| format!("{value} requires a value"))?;
        *target = Some(next.clone());
        index += 1;
    }
    let pipe_name = pipe_name.ok_or_else(|| "--pipe is required".to_string())?;
    let capability = capability.ok_or_else(|| "--capability is required".to_string())?;
    if pipe_name.is_empty() || capability.is_empty() {
        return Err("Computer Use pipe configuration is empty".to_string());
    }
    Ok((pipe_name, capability))
}

#[cfg(windows)]
fn accept_connection(pipe_path: &str) -> Result<File, String> {
    let wide = framing::wide_string(pipe_path);
    let handle = unsafe {
        CreateNamedPipeW(
            PCWSTR(wide.as_ptr()),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            64 * 1024,
            64 * 1024,
            0,
            None,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(format!(
            "CreateNamedPipeW failed: {}",
            unsafe { GetLastError() }.0
        ));
    }
    if let Err(error) = unsafe { ConnectNamedPipe(handle, None) } {
        let expected = windows::core::HRESULT::from_win32(ERROR_PIPE_CONNECTED.0);
        if error.code() != expected {
            return Err(format!("ConnectNamedPipe failed: {error}"));
        }
    }
    Ok(unsafe { File::from_raw_handle(handle.0 as _) })
}

fn serve_connection(connection: &mut (impl Read + Write), capability: &str) -> Result<(), String> {
    let hello = read_message(connection)?;
    let hello_id = request_id(&hello)?;
    let secret = hello
        .get("params")
        .and_then(Value::as_object)
        .and_then(|params| params.get("capability"))
        .and_then(Value::as_str)
        .unwrap_or_default();
    if hello.get("method").and_then(Value::as_str) != Some("hello") || secret != capability {
        write_error(
            connection,
            &hello_id,
            "authentication_failed",
            "Invalid Computer Use capability.",
        )?;
        return Err("Computer Use capability authentication failed".to_string());
    }
    write_result(
        connection,
        &hello_id,
        json!({"protocol_version": PROTOCOL_VERSION}),
    )?;

    let mut state = ServerState::default();
    while let Ok(message) = read_message(connection) {
        let id = request_id(&message)?;
        let result = dispatch_request(connection, &mut state, &message);
        match result {
            Ok(value) => write_result(connection, &id, value)?,
            Err((code, message)) => write_error(connection, &id, code, &message)?,
        }
    }
    Ok(())
}

fn dispatch_request(
    connection: &mut (impl Read + Write),
    state: &mut ServerState,
    message: &Value,
) -> Result<Value, (&'static str, String)> {
    if message.get("protocol_version").and_then(Value::as_u64) != Some(PROTOCOL_VERSION) {
        return Err((
            "protocol_mismatch",
            "Unsupported protocol version.".to_string(),
        ));
    }
    let method = message
        .get("method")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "Request method is missing.".to_string()))?;
    let params = message
        .get("params")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let meta = message
        .get("meta")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let turn_id = meta
        .get("turn_id")
        .and_then(Value::as_str)
        .unwrap_or_default();

    if state.stopped_turn.as_deref() == Some(turn_id) && method != "close" {
        return Err((
            "turn_stopped",
            "Computer Use was stopped for this turn.".to_string(),
        ));
    }
    match method {
        "close" => return Ok(json!({})),
        "end_turn" => {
            state.snapshots.clear();
            state.accessibility.clear();
            return Ok(json!({}));
        }
        "stop_turn" => {
            state.snapshots.clear();
            state.accessibility.clear();
            state.stopped_turn = Some(turn_id.to_string());
            return Ok(json!({}));
        }
        "list_apps" => return Ok(json!({"apps": list_apps()})),
        "list_windows" => return Ok(json!({"windows": list_windows()})),
        _ => {}
    }

    let window = if method == "launch_app" {
        None
    } else {
        let value = params
            .get("window_id")
            .and_then(Value::as_str)
            .ok_or(("invalid_request", "window_id is required.".to_string()))?;
        Some(resolve_window(value)?)
    };
    if method == "find_window" {
        return Ok(json!({"window": window.expect("window exists").to_json()}));
    }
    if method == "launch_app" {
        return launch_app(connection, &params, &meta);
    }
    let window = window.expect("window exists");
    request_approval(connection, &window, &meta)?;
    match method {
        "set_focus" => {
            set_focus(&window)?;
            Ok(json!({"window": window.to_json()}))
        }
        "observe_window" => observe_window(state, &window),
        "click" => click(state, &window, &params),
        "scroll" => scroll(state, &window, &params),
        "drag" => drag(state, &window, &params),
        "press_key" => press_key(&window, &params),
        "type_text" => type_text(&window, &params),
        "invoke_element" => invoke_element(state, &window, &params),
        "set_value" => set_value(state, &window, &params),
        "perform_secondary_action" => Err((
            "unsupported_operation",
            format!("{method} is not available in this helper build."),
        )),
        _ => Err((
            "unsupported_operation",
            format!("Unsupported method: {method}"),
        )),
    }
}

fn launch_app(
    connection: &mut (impl Read + Write),
    params: &Map<String, Value>,
    meta: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let app = params
        .get("app")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "app is required.".to_string()))?;
    let path = resolve_launch_path(app)?;
    let display_name = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("Application")
        .to_string();
    let target = WindowInfo {
        hwnd: 0,
        app_id: app_id_from_path(&path),
        display_name,
        title: String::new(),
        class_name: String::new(),
    };
    request_approval(connection, &target, meta)?;
    std::process::Command::new(&path).spawn().map_err(|error| {
        (
            "input_failed",
            format!("Could not launch application: {error}"),
        )
    })?;
    Ok(json!({"launched": true, "app_id": target.app_id}))
}

/// Build the canonical application identifier for an executable path.
///
/// `std::fs::canonicalize` returns Windows extended-length (`\\?\`) paths,
/// while window discovery reports plain drive paths. Stripping the prefix
/// keeps a single identifier across both origins so an application is only
/// approved once per session instead of once per path spelling.
fn app_id_from_path(path: &Path) -> String {
    let text = path.to_string_lossy();
    let normalized = text.strip_prefix(r"\\?\").unwrap_or(&text);
    format!("process:{}", normalized.to_lowercase())
}

fn resolve_launch_path(app: &str) -> Result<PathBuf, (&'static str, String)> {
    let value = app.strip_prefix("process:").unwrap_or(app);
    let path = PathBuf::from(value);
    if !path.is_absolute()
        || !path.is_file()
        || !path
            .extension()
            .is_some_and(|value| value.eq_ignore_ascii_case("exe"))
    {
        return Err((
            "app_not_found",
            "launch_app accepts an App ID from list_apps or an absolute .exe path.".to_string(),
        ));
    }
    path.canonicalize()
        .map_err(|error| ("app_not_found", error.to_string()))
}

fn request_approval(
    connection: &mut (impl Read + Write),
    window: &WindowInfo,
    meta: &Map<String, Value>,
) -> Result<(), (&'static str, String)> {
    if is_forbidden(window) {
        return Err((
            "app_forbidden",
            "Computer Use cannot control this application.".to_string(),
        ));
    }
    let request_id = next_id("approval");
    let mut evidence = Map::new();
    if let Some(path) = window.app_id.strip_prefix("process:") {
        evidence.insert("path".to_string(), Value::String(path.to_string()));
    }
    let request = json!({
        "request_id": request_id,
        "method": "request_app_approval",
        "params": {
            "canonical_app_id": window.app_id,
            "display_name": window.display_name,
            "identity_evidence": evidence,
            "risk": "low",
            "warning": "",
        },
        "meta": meta,
        "protocol_version": PROTOCOL_VERSION,
    });
    write_message(connection, &request).map_err(|error| ("runtime_disconnected", error))?;
    let reply = read_message(connection).map_err(|error| ("runtime_disconnected", error))?;
    let allowed = reply
        .get("request_id")
        .and_then(Value::as_str)
        .is_some_and(|value| value == request_id)
        && reply
            .get("result")
            .and_then(Value::as_object)
            .and_then(|result| result.get("decision"))
            .and_then(Value::as_str)
            == Some("allow");
    if allowed {
        Ok(())
    } else {
        Err((
            "app_denied",
            "Application access was not approved.".to_string(),
        ))
    }
}

impl WindowInfo {
    fn to_json(&self) -> Value {
        json!({
            "app_id": self.app_id,
            "id": self.hwnd.to_string(),
            "title": self.title,
        })
    }
}

fn next_id(prefix: &str) -> String {
    format!("{prefix}-{}", NEXT_ID.fetch_add(1, Ordering::Relaxed))
}
