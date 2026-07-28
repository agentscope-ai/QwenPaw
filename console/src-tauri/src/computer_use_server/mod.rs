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
// core below never names a platform-specific type directly. Each platform keeps
// its leaves in its own directory so the two never mix.
#[cfg(windows)]
mod platform_windows;
#[cfg(windows)]
use platform_windows::{
    click, close_window, desktop_locked, drag, invoke_element, is_forbidden, list_apps,
    list_windows, observe_window, press_key, resolve_window, scroll, set_focus,
    set_intervention_bypass_once, set_value, type_text,
};

#[cfg(target_os = "macos")]
mod platform_macos;
#[cfg(target_os = "macos")]
use platform_macos::{
    app_id_from_bundle_path, click, close_window, desktop_locked, drag, invoke_element,
    is_forbidden, list_apps, list_windows, observe_window, press_key, resolve_window, scroll,
    set_focus, set_intervention_bypass_once, set_value, type_text,
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
// Only the Windows capture path decodes raw bitmaps.
#[cfg(windows)]
const BMP_HEADER_BYTES: usize = 54;
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
struct WindowInfo {
    hwnd: isize,
    app_id: String,
    display_name: String,
    title: String,
    // Windows matches this against its credential-dialog guard. macOS has no
    // equivalent notion of a window class and recognises those dialogs by
    // title and owner instead.
    #[cfg_attr(target_os = "macos", allow(dead_code))]
    class_name: String,
}

struct Snapshot {
    window: WindowInfo,
    /// The window's on-screen rectangle as `[left, top, width, height]`.
    /// Origin plus size is used on both platforms so the meaning of each slot
    /// is unambiguous wherever a snapshot is read.
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
    let mut index = 0;
    while index < args.len() {
        let value = &args[index];
        index += 1;
        let target = match value.as_str() {
            "--pipe" => &mut pipe_name,
            _ => return Err(format!("unknown argument: {value}")),
        };
        let next = args
            .get(index)
            .ok_or_else(|| format!("{value} requires a value"))?;
        *target = Some(next.clone());
        index += 1;
    }
    let pipe_name = pipe_name.ok_or_else(|| "--pipe is required".to_string())?;
    // The capability secret arrives in the environment rather than on the
    // command line, so it is not exposed to other processes through argv. The
    // spawning side sets the matching variable in computer_use_runtime.
    let capability = std::env::var("QWENPAW_CU_CAPABILITY")
        .map_err(|_| "QWENPAW_CU_CAPABILITY is required".to_string())?;
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
    // Actions that synthesize input or change window state must not run
    // against the secure lock screen, and the recency guard is exempted once
    // right after the user resolves an approval prompt in QwenPaw.
    let is_input_method = matches!(
        method,
        "click"
            | "scroll"
            | "drag"
            | "press_key"
            | "type_text"
            | "invoke_element"
            | "set_value"
            | "close_window"
    );
    if is_input_method {
        if desktop_locked() {
            return Err((
                "desktop_locked",
                "The desktop is locked; ask the user to unlock it before continuing."
                    .to_string(),
            ));
        }
        let after_approval = params
            .get("after_approval")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        set_intervention_bypass_once(after_approval);
    }
    match method {
        "set_focus" => {
            set_focus(&window)?;
            Ok(json!({"window": window.to_json()}))
        }
        "observe_window" => observe_window(state, &window),
        "close_window" => {
            let result = close_window(&window)?;
            if result.get("closed").and_then(Value::as_bool) == Some(true) {
                // Observations of a closed window can never be acted on
                // again; drop them so a later action fails fast as stale
                // instead of pointing at a dead handle.
                let hwnd = window.hwnd;
                state
                    .snapshots
                    .retain(|_, snapshot| snapshot.window.hwnd != hwnd);
                state
                    .accessibility
                    .retain(|_, snapshot| snapshot.window_hwnd != hwnd);
            }
            Ok(result)
        }
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
    launch_at(&path)?;
    Ok(json!({"launched": true, "app_id": target.app_id}))
}

/// Build the canonical application identifier for a launchable path.
///
/// Windows discovery reports plain drive paths while `canonicalize` returns
/// extended-length (`\\?\`) ones, so the prefix is stripped to keep a single
/// identifier per application; macOS derives the same identifier from the
/// bundle path. Either way an application is approved once per session rather
/// than once per path spelling.
#[cfg(windows)]
fn app_id_from_path(path: &Path) -> String {
    let text = path.to_string_lossy();
    let normalized = text.strip_prefix(r"\\?\").unwrap_or(&text);
    format!("process:{}", normalized.to_lowercase())
}

#[cfg(target_os = "macos")]
fn app_id_from_path(path: &Path) -> String {
    app_id_from_bundle_path(path)
}

/// Validate what `launch_app` was given and resolve it to something the
/// platform can start.
///
/// The accepted spellings differ by platform -- an executable file on Windows,
/// an application bundle on macOS -- so each leaf owns its own rule.
#[cfg(windows)]
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

#[cfg(target_os = "macos")]
fn resolve_launch_path(app: &str) -> Result<PathBuf, (&'static str, String)> {
    let value = app.strip_prefix("app:").unwrap_or(app);
    let path = PathBuf::from(value);
    // A bundle is a directory, so accept either that or a plain executable.
    let is_bundle = path.is_dir()
        && path
            .extension()
            .is_some_and(|value| value.eq_ignore_ascii_case("app"));
    if !path.is_absolute() || !(is_bundle || path.is_file()) {
        return Err((
            "app_not_found",
            "launch_app accepts an App ID from list_apps or an absolute path \
             to an application bundle."
                .to_string(),
        ));
    }
    path.canonicalize()
        .map_err(|error| ("app_not_found", error.to_string()))
}

/// Start the application at a resolved path.
#[cfg(windows)]
fn launch_at(path: &Path) -> Result<(), (&'static str, String)> {
    std::process::Command::new(path)
        .spawn()
        .map(|_| ())
        .map_err(|error| {
            (
                "input_failed",
                format!("Could not launch application: {error}"),
            )
        })
}

/// Start the application at a resolved path.
///
/// A bundle is a directory and cannot be executed, so it is handed to `open`
/// with double-click semantics: Launch Services starts the application, or
/// activates it when already running. A plain executable is spawned directly,
/// the way Windows starts one -- it is not registered with Launch Services,
/// so `open` has no notion of it. `open` returns as soon as the request is
/// made, so the caller polls `list_windows` for the new window rather than
/// waiting here.
#[cfg(target_os = "macos")]
fn launch_at(path: &Path) -> Result<(), (&'static str, String)> {
    let is_bundle = path
        .extension()
        .is_some_and(|value| value.eq_ignore_ascii_case("app"));
    let mut command = if is_bundle {
        let mut open = std::process::Command::new("open");
        open.arg(path);
        open
    } else {
        std::process::Command::new(path)
    };
    command.spawn().map(|_| ()).map_err(|error| {
        (
            "input_failed",
            format!("Could not launch application: {error}"),
        )
    })
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
    // Identifiers are path-backed on both platforms, under the prefix that
    // names the platform's unit of installation.
    if let Some(path) = window
        .app_id
        .strip_prefix("process:")
        .or_else(|| window.app_id.strip_prefix("app:"))
    {
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

/// Upper bound on the document text handed back with an observation. A large
/// document would otherwise dominate the model's context, and the leading
/// portion is what identifies the current state.
const DOC_TEXT_MAX: usize = 4000;

/// Bound document text by character count, flagging that more remains.
///
/// Counting characters rather than bytes keeps multi-byte text intact.
fn truncate_document_text(text: String) -> String {
    if text.chars().count() <= DOC_TEXT_MAX {
        return text;
    }
    let mut bounded: String = text.chars().take(DOC_TEXT_MAX).collect();
    bounded.push_str("… (truncated)");
    bounded
}

/// Render one accessibility element as a single line.
///
/// The format is part of the observation contract the skill documents, so it
/// lives here rather than in either platform leaf.
fn element_line(element_id: &str, control_type_name: &str, name: &str) -> String {
    format!("{element_id} {control_type_name} \"{name}\"")
}

/// An application discovered on disk but not currently showing a window.
struct InstalledApp {
    app_id: String,
    display_name: String,
}

/// Build the `list_apps` payload from installed applications and open windows.
///
/// An application that owns a window is reported as running and carries those
/// windows; one found only on disk is reported with no windows. Both platforms
/// share this so `is_running` can never mean different things on each.
fn merge_app_list(installed: Vec<InstalledApp>, windows: Vec<WindowInfo>) -> Vec<Value> {
    let mut order: Vec<String> = Vec::new();
    let mut entries: HashMap<String, (String, bool, Vec<Value>)> = HashMap::new();
    for app in installed {
        if !entries.contains_key(&app.app_id) {
            order.push(app.app_id.clone());
        }
        entries
            .entry(app.app_id)
            .or_insert((app.display_name, false, Vec::new()));
    }
    for window in windows {
        let entry = entries.entry(window.app_id.clone()).or_insert_with(|| {
            order.push(window.app_id.clone());
            (window.display_name.clone(), false, Vec::new())
        });
        // A window proves the application is running, and its own display name
        // is the one the user currently sees.
        entry.0 = window.display_name.clone();
        entry.1 = true;
        entry.2.push(window.to_json());
    }
    order
        .into_iter()
        .filter_map(|app_id| {
            let (display_name, is_running, windows) = entries.remove(&app_id)?;
            Some(json!({
                "id": app_id,
                "display_name": display_name,
                "is_running": is_running,
                "windows": windows,
            }))
        })
        .collect()
}

/// Map a coordinate expressed in screenshot space onto the window.
///
/// Returns the offset from the window's origin in physical pixels. Both
/// platforms share the bounds check so a coordinate outside the delivered
/// screenshot can never be extrapolated onto another application's window.
fn map_point(snapshot: &Snapshot, x: i64, y: i64) -> Result<(f64, f64), (&'static str, String)> {
    let display_width = i64::from(snapshot.display_width.max(1));
    let display_height = i64::from(snapshot.display_height.max(1));
    if x < 0 || y < 0 || x >= display_width || y >= display_height {
        return Err((
            "point_outside_viewport",
            "Point is outside the captured viewport.".to_string(),
        ));
    }
    // The screenshot may have been downscaled, so scale back to the window's
    // own pixels. With no downscaling these ratios are 1:1.
    let width = f64::from(snapshot.bounds[2]);
    let height = f64::from(snapshot.bounds[3]);
    Ok((
        x as f64 * width / display_width as f64,
        y as f64 * height / display_height as f64,
    ))
}

fn next_id(prefix: &str) -> String {
    format!("{prefix}-{}", NEXT_ID.fetch_add(1, Ordering::Relaxed))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot(bounds: [i32; 4], display: (u32, u32)) -> Snapshot {
        Snapshot {
            window: WindowInfo {
                hwnd: 1,
                app_id: "app:test".to_string(),
                display_name: "Test".to_string(),
                title: String::new(),
                class_name: String::new(),
            },
            bounds,
            screenshot_id: "screenshot-1".to_string(),
            display_width: display.0,
            display_height: display.1,
        }
    }

    fn window(app_id: &str, display_name: &str, hwnd: isize) -> WindowInfo {
        WindowInfo {
            hwnd,
            app_id: app_id.to_string(),
            display_name: display_name.to_string(),
            title: String::new(),
            class_name: String::new(),
        }
    }

    #[test]
    fn short_document_text_is_returned_unchanged() {
        let text = "hello world".to_string();
        assert_eq!(truncate_document_text(text.clone()), text);
    }

    #[test]
    fn long_document_text_is_bounded_and_flagged() {
        let bounded = truncate_document_text("x".repeat(DOC_TEXT_MAX + 500));
        assert!(bounded.ends_with("… (truncated)"));
        assert_eq!(
            bounded.chars().filter(|value| *value == 'x').count(),
            DOC_TEXT_MAX
        );
    }

    #[test]
    fn truncation_counts_characters_not_bytes() {
        // Multi-byte text must not be cut mid-character.
        let bounded = truncate_document_text("字".repeat(DOC_TEXT_MAX + 10));
        assert_eq!(
            bounded.chars().filter(|value| *value == '字').count(),
            DOC_TEXT_MAX
        );
    }

    #[test]
    fn element_line_matches_the_listing_format() {
        assert_eq!(
            element_line("uia-1", "Edit", "text editor"),
            "uia-1 Edit \"text editor\""
        );
    }

    #[test]
    fn a_point_inside_the_viewport_maps_by_proportion() {
        // A 200x100 window delivered as a 100x50 screenshot is a 2:1 scale.
        let snap = snapshot([10, 20, 200, 100], (100, 50));
        let (x, y) = map_point(&snap, 50, 25).unwrap();
        assert_eq!((x as i32, y as i32), (100, 50));
    }

    #[test]
    fn an_unscaled_screenshot_maps_one_to_one() {
        let snap = snapshot([0, 0, 100, 100], (100, 100));
        let (x, y) = map_point(&snap, 30, 40).unwrap();
        assert_eq!((x as i32, y as i32), (30, 40));
    }

    #[test]
    fn points_outside_the_viewport_are_refused() {
        let snap = snapshot([0, 0, 100, 100], (100, 100));
        for (x, y) in [(-1, 0), (0, -1), (100, 0), (0, 100)] {
            let error = map_point(&snap, x, y).expect_err("must be refused");
            assert_eq!(error.0, "point_outside_viewport");
        }
    }

    #[test]
    fn a_running_application_reports_its_windows() {
        let apps = merge_app_list(
            Vec::new(),
            vec![window("app:editor", "Editor", 1), window("app:editor", "Editor", 2)],
        );
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0]["is_running"], serde_json::json!(true));
        assert_eq!(apps[0]["windows"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn an_installed_application_reports_no_windows() {
        let installed = vec![InstalledApp {
            app_id: "app:/applications/notes.app".to_string(),
            display_name: "Notes".to_string(),
        }];
        let apps = merge_app_list(installed, Vec::new());
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0]["is_running"], serde_json::json!(false));
        assert!(apps[0]["windows"].as_array().unwrap().is_empty());
    }

    #[test]
    fn a_running_application_is_not_duplicated_by_its_installed_entry() {
        let installed = vec![InstalledApp {
            app_id: "app:/applications/editor.app".to_string(),
            // A stale on-disk name must not win over the live window's name.
            display_name: "Editor 1.0".to_string(),
        }];
        let apps = merge_app_list(
            installed,
            vec![window("app:/applications/editor.app", "Editor", 1)],
        );
        assert_eq!(apps.len(), 1);
        assert_eq!(apps[0]["is_running"], serde_json::json!(true));
        assert_eq!(apps[0]["display_name"], serde_json::json!("Editor"));
        assert_eq!(apps[0]["windows"].as_array().unwrap().len(), 1);
    }
}
