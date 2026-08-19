//! macOS Computer Use leaves.
//!
//! The RPC server, framing, transport, session/turn lifecycle, and app approval
//! are shared with Windows (see the parent `mod.rs`). Only the OS-touching
//! leaves below are platform specific, split the way the Windows side is:
//! window discovery over the CoreGraphics window list, capture through
//! CGWindowListCreateImage (dev-tier; ScreenCaptureKit is the shippable path),
//! accessibility over AXUIElement, and input over CGEvent.
//!
//! Helpers used by more than one leaf live here, so the leaves depend on this
//! module rather than on each other.

use accessibility_sys::{AXError, AXUIElementRef};
use core_foundation::base::{CFType, TCFType};
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::number::CFNumber;
use core_foundation::string::{CFString, CFStringRef};
use core_graphics::geometry::CGPoint;
use core_graphics::window::{
    copy_window_info, kCGNullWindowID, kCGWindowBounds, kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionIncludingWindow, kCGWindowListOptionOnScreenOnly, kCGWindowNumber,
    kCGWindowOwnerPID, CGWindowID,
};
use objc2_app_kit::NSWorkspace;
use serde_json::{Map, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

mod accessibility_tree;
mod capture;
mod input;
mod permissions;
mod window;

pub(super) use accessibility_tree::{
    element_is_transient_menu_item, element_requires_frontmost, set_value, validate_observation,
    AxElement,
};
pub(super) use capture::observe_window;
pub(super) use input::{
    click, desktop_locked, drag, input_sequence, invoke_element, last_input_age_ms, press_key,
    scroll, type_text,
};
pub(super) use permissions::ensure_for as ensure_permissions;
pub(super) use window::{
    active_window, app_id_from_bundle_path, close_window, is_forbidden, list_apps, list_windows,
    resolve_window,
};

/// How long to wait on a single accessibility request before giving up.
///
/// An unresponsive application would otherwise block the helper indefinitely,
/// since these calls are synchronous round trips into that process.
const AX_MESSAGING_TIMEOUT_SECONDS: f32 = 2.0;
const CONTROL_MAX_MESSAGE_BYTES: usize = 4096;
const CONTROL_TIMEOUT: Duration = Duration::from_secs(2);
static NEXT_FOCUS_LEASE_ID: AtomicU64 = AtomicU64::new(1);

/// Whether physical user input would currently target this window's app.
pub(super) fn target_is_frontmost(window: &super::state::WindowInfo) -> bool {
    NSWorkspace::sharedWorkspace()
        .frontmostApplication()
        .is_some_and(|application| application.processIdentifier() == window.owner_pid)
}

/// A host-owned assertion that keeps the desktop UI from taking foreground.
///
/// The server state owns one assertion for the whole Computer Use turn. Drop
/// therefore has a real lifecycle boundary: end_turn, connection loss, user
/// intervention, or helper exit, rather than a guessed delay between actions.
pub(super) struct HostFocusLease {
    id: String,
}

impl HostFocusLease {
    pub(super) fn begin() -> Result<Self, (&'static str, String)> {
        let id = format!(
            "{}-{}",
            std::process::id(),
            NEXT_FOCUS_LEASE_ID.fetch_add(1, Ordering::Relaxed)
        );
        let response = host_control_request("begin_focus", Some(&id))?;
        let issued_id = response
            .get("lease_id")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .ok_or((
                "focus_failed",
                "Desktop host did not issue a foreground lease.".to_string(),
            ))?;
        if issued_id != id {
            return Err((
                "focus_failed",
                "Desktop host issued an invalid foreground lease.".to_string(),
            ));
        }
        Ok(Self { id })
    }
}

impl Drop for HostFocusLease {
    fn drop(&mut self) {
        let _ = host_control_request("end_focus", Some(&self.id));
    }
}

fn host_control_request(
    action: &str,
    lease_id: Option<&str>,
) -> Result<Value, (&'static str, String)> {
    let host = std::env::var("QWENPAW_COMPUTER_USE_CONTROL_HOST").unwrap_or_default();
    let token = std::env::var("QWENPAW_COMPUTER_USE_CONTROL_TOKEN").unwrap_or_default();
    let port = std::env::var("QWENPAW_COMPUTER_USE_CONTROL_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok());
    if host != "127.0.0.1" || token.is_empty() || port.is_none() {
        return Err((
            "runtime_unavailable",
            "Desktop host control is unavailable.".to_string(),
        ));
    }
    let request = serde_json::json!({
        "token": token,
        "action": action,
        "helper_pid": std::process::id(),
        "lease_id": lease_id,
    });
    let payload = serde_json::to_vec(&request).map_err(|error| {
        (
            "runtime_unavailable",
            format!("Could not encode desktop host control request: {error}"),
        )
    })?;
    let response = host_control_round_trip(&host, port.unwrap(), &payload)
        .or_else(|_| host_control_round_trip(&host, port.unwrap(), &payload))?;
    if response.get("ok").and_then(Value::as_bool) != Some(true) {
        let code = match response.get("error").and_then(Value::as_str) {
            Some("desktop_busy") => "desktop_busy",
            Some("stale_helper") => "runtime_unavailable",
            _ => "focus_failed",
        };
        return Err((
            code,
            "Desktop host refused the foreground lease.".to_string(),
        ));
    }
    Ok(response)
}

fn host_control_round_trip(
    host: &str,
    port: u16,
    payload: &[u8],
) -> Result<Value, (&'static str, String)> {
    let mut stream = TcpStream::connect((host, port)).map_err(|error| {
        (
            "runtime_unavailable",
            format!("Could not reach desktop host control: {error}"),
        )
    })?;
    stream.set_read_timeout(Some(CONTROL_TIMEOUT)).ok();
    stream.set_write_timeout(Some(CONTROL_TIMEOUT)).ok();
    stream
        .write_all(payload)
        .and_then(|_| stream.write_all(b"\n"))
        .and_then(|_| stream.flush())
        .map_err(|error| {
            (
                "runtime_unavailable",
                format!("Could not send desktop host control request: {error}"),
            )
        })?;
    let mut payload = Vec::new();
    BufReader::new(stream)
        .take((CONTROL_MAX_MESSAGE_BYTES + 1) as u64)
        .read_until(b'\n', &mut payload)
        .map_err(|error| {
            (
                "runtime_unavailable",
                format!("Could not read desktop host control response: {error}"),
            )
        })?;
    if payload.is_empty() || payload.len() > CONTROL_MAX_MESSAGE_BYTES || !payload.ends_with(b"\n")
    {
        return Err((
            "runtime_unavailable",
            "Desktop host returned an invalid control response.".to_string(),
        ));
    }
    let response: Value = serde_json::from_slice(&payload).map_err(|error| {
        (
            "runtime_unavailable",
            format!("Could not decode desktop host control response: {error}"),
        )
    })?;
    Ok(response)
}

// Private ApplicationServices API mapping an accessibility window element to
// its CoreGraphics window id. It is the reliable way to match a CGWindowID
// (the id carried by the shared protocol) to the app's AX window subtree.
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn _AXUIElementGetWindow(element: AXUIElementRef, out: *mut u32) -> AXError;
}

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventSourceSecondsSinceLastEventType(state_id: u32, event_type: u32) -> f64;
    fn CGSessionCopyCurrentDictionary() -> CFDictionaryRef;
}

fn window_bounds(window_id: i64) -> Option<(f64, f64, f64, f64)> {
    let list = copy_window_info(kCGWindowListOptionIncludingWindow, window_id as CGWindowID)?;
    for item in list.iter() {
        let dict_ref = (*item) as CFDictionaryRef;
        if dict_ref.is_null() {
            continue;
        }
        let dict = unsafe { CFDictionary::<CFString, CFType>::wrap_under_get_rule(dict_ref) };
        if dict_i64(&dict, unsafe { kCGWindowNumber }) != Some(window_id) {
            continue;
        }
        return bounds_from_dict(&dict);
    }
    None
}

/// Read a window's on-screen bounds out of an already-obtained window dict.
fn bounds_from_dict(dict: &CFDictionary<CFString, CFType>) -> Option<(f64, f64, f64, f64)> {
    let key = unsafe { CFString::wrap_under_get_rule(kCGWindowBounds) };
    // Only the untyped dictionary implements ConcreteCFType, so downcast to
    // that and then re-describe the same reference with the key and value
    // types this window dictionary actually holds.
    let untyped = dict.find(&key)?.downcast::<CFDictionary>()?;
    let bounds = unsafe {
        CFDictionary::<CFString, CFType>::wrap_under_get_rule(untyped.as_concrete_TypeRef())
    };
    Some((
        dict_f64(&bounds, "X")?,
        dict_f64(&bounds, "Y")?,
        dict_f64(&bounds, "Width")?,
        dict_f64(&bounds, "Height")?,
    ))
}

fn dict_i64(dict: &CFDictionary<CFString, CFType>, key: CFStringRef) -> Option<i64> {
    let key = unsafe { CFString::wrap_under_get_rule(key) };
    let value = dict.find(&key)?;
    value
        .downcast::<CFNumber>()
        .and_then(|number| number.to_i64())
}

fn dict_string(dict: &CFDictionary<CFString, CFType>, key: CFStringRef) -> Option<String> {
    let key = unsafe { CFString::wrap_under_get_rule(key) };
    let value = dict.find(&key)?;
    value
        .downcast::<CFString>()
        .map(|string| string.to_string())
}

fn dict_f64(dict: &CFDictionary<CFString, CFType>, key: &str) -> Option<f64> {
    let key = CFString::new(key);
    let value = dict.find(&key)?;
    value
        .downcast::<CFNumber>()
        .and_then(|number| number.to_f64())
}

/// Centers of the target application's on-screen transient surfaces.
///
/// Menus and popovers are separate CoreGraphics windows rather than children
/// of the normal content window. Some applications report those surfaces at
/// the normal window layer, so the owning content window is excluded by id
/// instead of filtering on layer. The list remains front-to-back, allowing
/// accessibility hit testing to prefer the surface a person can act on.
fn transient_surface_points(pid: i32, content_window: i64) -> Vec<CGPoint> {
    let option = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements;
    let Some(list) = copy_window_info(option, kCGNullWindowID) else {
        return Vec::new();
    };
    list.iter()
        .filter_map(|item| {
            let dict_ref = (*item) as CFDictionaryRef;
            if dict_ref.is_null() {
                return None;
            }
            let dict = unsafe { CFDictionary::<CFString, CFType>::wrap_under_get_rule(dict_ref) };
            if dict_i64(&dict, unsafe { kCGWindowOwnerPID }) != Some(i64::from(pid))
                || dict_i64(&dict, unsafe { kCGWindowNumber }) == Some(content_window)
            {
                return None;
            }
            let (x, y, width, height) = bounds_from_dict(&dict)?;
            (width > 0.0 && height > 0.0).then_some(CGPoint {
                x: x + width / 2.0,
                y: y + height / 2.0,
            })
        })
        .collect()
}

fn integer_param(params: &Map<String, Value>, key: &str) -> Result<i64, (&'static str, String)> {
    params
        .get(key)
        .and_then(Value::as_i64)
        .ok_or_else(|| ("invalid_request", format!("{key} is required.")))
}

/// Exit the helper when the desktop host process dies. macOS has no Job Object
/// equivalent, so a background thread watches the host pid via a kqueue
/// `EVFILT_PROC`/`NOTE_EXIT` filter and terminates the helper when the host
/// exits, preventing orphaned helpers.
pub(super) fn spawn_parent_death_watch() {
    let parent = std::env::var("QWENPAW_CU_HOST_PID")
        .ok()
        .and_then(|value| value.parse::<libc::pid_t>().ok())
        .filter(|pid| *pid > 1)
        .unwrap_or_else(|| unsafe { libc::getppid() });
    if parent <= 1 {
        return;
    }
    std::thread::spawn(move || {
        let kq = unsafe { libc::kqueue() };
        if kq < 0 {
            return;
        }
        let change = libc::kevent {
            ident: parent as libc::uintptr_t,
            filter: libc::EVFILT_PROC,
            flags: libc::EV_ADD | libc::EV_ENABLE,
            fflags: libc::NOTE_EXIT,
            data: 0,
            udata: std::ptr::null_mut(),
        };
        let registered =
            unsafe { libc::kevent(kq, &change, 1, std::ptr::null_mut(), 0, std::ptr::null()) };
        if registered < 0 {
            unsafe { libc::close(kq) };
            return;
        }
        let mut event: libc::kevent = unsafe { std::mem::zeroed() };
        let mut parent_exited = false;
        loop {
            let count =
                unsafe { libc::kevent(kq, std::ptr::null(), 0, &mut event, 1, std::ptr::null()) };
            if count < 0 {
                if std::io::Error::last_os_error().raw_os_error() == Some(libc::EINTR) {
                    continue;
                }
                log::warn!(
                    "[computer-use] parent-death watcher failed: {}",
                    std::io::Error::last_os_error()
                );
                break;
            }
            if count > 0 && (event.fflags & libc::NOTE_EXIT) != 0 {
                parent_exited = true;
                break;
            }
        }
        unsafe { libc::close(kq) };
        // A watcher failure must never take down a healthy helper. Only an
        // actual NOTE_EXIT notification means the desktop parent is gone.
        if parent_exited {
            std::process::exit(0);
        }
    });
}
