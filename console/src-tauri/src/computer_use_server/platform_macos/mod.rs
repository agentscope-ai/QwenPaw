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
use core_graphics::window::{
    copy_window_info, kCGWindowBounds, kCGWindowListOptionIncludingWindow, kCGWindowNumber,
    kCGWindowOwnerPID, CGWindowID,
};
use serde_json::{Map, Value};

mod accessibility_tree;
mod capture;
mod input;
mod window;

pub(super) use accessibility_tree::{invoke_element, set_value, AxElement};
pub(super) use capture::observe_window;
pub(super) use input::{
    click, desktop_locked, drag, last_input_age_ms, press_key, scroll, type_text,
};
pub(super) use window::{
    app_id_from_bundle_path, close_window, is_forbidden, list_apps, list_windows, resolve_window,
};

/// How long to wait on a single accessibility request before giving up.
///
/// An unresponsive application would otherwise block the helper indefinitely,
/// since these calls are synchronous round trips into that process.
const AX_MESSAGING_TIMEOUT_SECONDS: f32 = 2.0;

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

fn window_owner_pid(window_id: i64) -> Option<i32> {
    let list = copy_window_info(kCGWindowListOptionIncludingWindow, window_id as CGWindowID)?;
    for item in list.iter() {
        let dict_ref = (*item) as CFDictionaryRef;
        if dict_ref.is_null() {
            continue;
        }
        let dict = unsafe { CFDictionary::<CFString, CFType>::wrap_under_get_rule(dict_ref) };
        if dict_i64(&dict, unsafe { kCGWindowNumber }) == Some(window_id) {
            return dict_i64(&dict, unsafe { kCGWindowOwnerPID }).map(|pid| pid as i32);
        }
    }
    None
}

fn integer_param(params: &Map<String, Value>, key: &str) -> Result<i64, (&'static str, String)> {
    params
        .get(key)
        .and_then(Value::as_i64)
        .ok_or_else(|| ("invalid_request", format!("{key} is required.")))
}

/// Exit the helper when the desktop parent process dies. macOS has no Job
/// Object equivalent, so a background thread watches the parent pid via a
/// kqueue `EVFILT_PROC`/`NOTE_EXIT` filter and terminates the helper when the
/// parent exits, preventing orphaned helpers.
pub(super) fn spawn_parent_death_watch() {
    let parent = unsafe { libc::getppid() };
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
