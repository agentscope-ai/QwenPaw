//! Input synthesis, focus, and the guards around them on macOS.
//!
//! Mirrors the Windows `input.rs` leaf: every path that moves the pointer,
//! presses a key, or takes focus, plus the checks that refuse to do so when the
//! target is no longer what was observed or the user has just intervened.

use accessibility::{AXAttribute, AXUIElement};
use accessibility_sys::kAXRaiseAction;
use core_foundation::base::{CFType, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::number::CFNumber;
use core_foundation::string::CFString;
use core_graphics::event::{
    CGEvent, CGEventFlags, CGEventTapLocation, CGEventType, CGMouseButton, KeyCode, ScrollEventUnit,
};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
use core_graphics::geometry::CGPoint;
use core_graphics::window::{
    copy_window_info, kCGNullWindowID, kCGWindowLayer, kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly, kCGWindowNumber,
};
use serde_json::{json, Map, Value};

use super::super::state::{map_point, ServerState, Snapshot, WindowInfo};
use super::accessibility_tree::find_ax_window;
use super::{
    bounds_from_dict, dict_i64, integer_param, window_bounds, window_owner_pid,
    CGEventSourceSecondsSinceLastEventType, CGSessionCopyCurrentDictionary,
    _AXUIElementGetWindow,
};

/// How long to wait for a raised window to actually hold focus before
/// refusing to inject input.
const FOCUS_POLL_ATTEMPTS: u32 = 20;
const FOCUS_POLL_INTERVAL_MS: u64 = 25;

const EVENT_SOURCE_STATE_COMBINED_SESSION: u32 = 1;
const ANY_INPUT_EVENT_TYPE: u32 = 0xFFFF_FFFF;

/// What the login session says about the lock screen.
enum LockState {
    Locked,
    Unlocked,
    /// The session could not be read, so nothing is known either way.
    Unknown,
}

/// Read the current login-session dictionary and report the lock flag.
fn session_lock_state() -> LockState {
    unsafe {
        let dict_ref = CGSessionCopyCurrentDictionary();
        if dict_ref.is_null() {
            // No session dictionary at all: there may be no GUI session here.
            return LockState::Unknown;
        }
        let dict: CFDictionary<CFString, CFType> =
            CFDictionary::wrap_under_create_rule(dict_ref);
        let key = CFString::from_static_string("CGSSessionScreenIsLocked");
        let Some(value) = dict.find(&key) else {
            // The key is only present while the screen is locked, so its
            // absence is a definite unlocked -- not a failure to tell. Reading
            // it as unknown would refuse every action on a normal desktop.
            return LockState::Unlocked;
        };
        match value.downcast::<CFNumber>().and_then(|number| number.to_i64()) {
            Some(0) => LockState::Unlocked,
            Some(_) => LockState::Locked,
            // Present but not a number the session is describing something
            // this code does not understand.
            None => LockState::Unknown,
        }
    }
}

/// Report whether the login session is currently locked. A locked session
/// must not receive synthesized input.
///
/// Anything other than a definite unlocked counts as locked. This guard exists
/// to keep synthesized input off a secure screen, so being unable to read the
/// session is not a reason to proceed -- it is the case where proceeding would
/// be least defensible.
pub(crate) fn desktop_locked() -> bool {
    !matches!(session_lock_state(), LockState::Unlocked)
}

/// Milliseconds since the last keyboard or mouse event anywhere on the desktop.
///
/// The decision about what age is too recent, and the exemption that follows an
/// approval, belong to the shared input guard; this reports the measurement and
/// nothing else.
pub(crate) fn last_input_age_ms() -> Option<u32> {
    let idle_seconds = unsafe {
        CGEventSourceSecondsSinceLastEventType(
            EVENT_SOURCE_STATE_COMBINED_SESSION,
            ANY_INPUT_EVENT_TYPE,
        )
    };
    // A machine idle for weeks would overflow; saturating is correct because
    // anything past the grace window is equally "long ago".
    Some((idle_seconds * 1000.0).clamp(0.0, f64::from(u32::MAX)) as u32)
}

pub(crate) fn click(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let point = resolve_point(state, window, params, "x", "y")?;
    set_focus(window)?;
    let button = params.get("button").and_then(Value::as_str).unwrap_or("left");
    let count = params
        .get("count")
        .and_then(Value::as_i64)
        .unwrap_or(1)
        .clamp(1, 3);
    let (down, up, mouse_button) = match button {
        "right" => (
            CGEventType::RightMouseDown,
            CGEventType::RightMouseUp,
            CGMouseButton::Right,
        ),
        _ => (
            CGEventType::LeftMouseDown,
            CGEventType::LeftMouseUp,
            CGMouseButton::Left,
        ),
    };
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, point, CGMouseButton::Left)?;
    for _ in 0..count {
        post_mouse(&source, down, point, mouse_button)?;
        post_mouse(&source, up, point, mouse_button)?;
    }
    Ok(json!({"applied": true}))
}

pub(crate) fn scroll(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let point = resolve_point(state, window, params, "x", "y")?;
    set_focus(window)?;
    let delta_y = integer_param(params, "delta_y")? as i32;
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, point, CGMouseButton::Left)?;
    let event = CGEvent::new_scroll_event(source, ScrollEventUnit::PIXEL, 1, -delta_y, 0, 0)
        .map_err(|_| ("input_failed", "Could not create the scroll event.".to_string()))?;
    event.post(CGEventTapLocation::HID);
    Ok(json!({"applied": true}))
}

pub(crate) fn drag(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let start = resolve_point(state, window, params, "start_x", "start_y")?;
    let end = resolve_point(state, window, params, "end_x", "end_y")?;
    set_focus(window)?;
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, start, CGMouseButton::Left)?;
    post_mouse(&source, CGEventType::LeftMouseDown, start, CGMouseButton::Left)?;
    post_mouse(&source, CGEventType::LeftMouseDragged, end, CGMouseButton::Left)?;
    post_mouse(&source, CGEventType::LeftMouseUp, end, CGMouseButton::Left)?;
    Ok(json!({"applied": true}))
}

pub(crate) fn type_text(
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let text = params
        .get("text")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "text is required.".to_string()))?;
    set_focus(window)?;
    let source = event_source()?;
    let event = CGEvent::new_keyboard_event(source, 0, true)
        .map_err(|_| ("input_failed", "Could not create the keyboard event.".to_string()))?;
    event.set_string(text);
    event.post(CGEventTapLocation::HID);
    Ok(json!({"applied": true}))
}

pub(crate) fn press_key(
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let key = params
        .get("key")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "key is required.".to_string()))?;
    let (keycode, flags) =
        parse_key(key).ok_or(("invalid_request", format!("Unsupported key: {key}")))?;
    set_focus(window)?;
    let source = event_source()?;
    let down = CGEvent::new_keyboard_event(source.clone(), keycode, true)
        .map_err(|_| ("input_failed", "Could not create the key event.".to_string()))?;
    down.set_flags(flags);
    down.post(CGEventTapLocation::HID);
    let up = CGEvent::new_keyboard_event(source, keycode, false)
        .map_err(|_| ("input_failed", "Could not create the key event.".to_string()))?;
    up.set_flags(flags);
    up.post(CGEventTapLocation::HID);
    Ok(json!({"applied": true}))
}

/// Parse a key spec such as "cmd+shift+a" or "Return" into a virtual key code
/// plus modifier flags. Base keys accept named special keys and US-layout
/// letters/digits.
fn parse_key(key: &str) -> Option<(u16, CGEventFlags)> {
    let parts: Vec<&str> = key
        .split('+')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .collect();
    let (modifiers, base) = parts.split_at(parts.len().checked_sub(1)?);
    let base = base.first()?;
    let mut flags = CGEventFlags::CGEventFlagNull;
    for modifier in modifiers {
        flags |= match modifier.to_ascii_lowercase().as_str() {
            "cmd" | "command" | "meta" | "super" | "win" => CGEventFlags::CGEventFlagCommand,
            "shift" => CGEventFlags::CGEventFlagShift,
            "ctrl" | "control" => CGEventFlags::CGEventFlagControl,
            "alt" | "option" | "opt" => CGEventFlags::CGEventFlagAlternate,
            _ => return None,
        };
    }
    Some((keycode_for(base)?, flags))
}

fn keycode_for(key: &str) -> Option<u16> {
    Some(match key.to_ascii_lowercase().as_str() {
        "return" | "enter" => KeyCode::RETURN,
        "tab" => KeyCode::TAB,
        "space" => KeyCode::SPACE,
        "delete" | "backspace" => KeyCode::DELETE,
        "escape" | "esc" => KeyCode::ESCAPE,
        "home" => KeyCode::HOME,
        "end" => KeyCode::END,
        "pageup" => KeyCode::PAGE_UP,
        "pagedown" => KeyCode::PAGE_DOWN,
        "left" | "leftarrow" => KeyCode::LEFT_ARROW,
        "right" | "rightarrow" => KeyCode::RIGHT_ARROW,
        "up" | "uparrow" => KeyCode::UP_ARROW,
        "down" | "downarrow" => KeyCode::DOWN_ARROW,
        "a" => 0,
        "b" => 11,
        "c" => 8,
        "d" => 2,
        "e" => 14,
        "f" => 3,
        "g" => 5,
        "h" => 4,
        "i" => 34,
        "j" => 38,
        "k" => 40,
        "l" => 37,
        "m" => 46,
        "n" => 45,
        "o" => 31,
        "p" => 35,
        "q" => 12,
        "r" => 15,
        "s" => 1,
        "t" => 17,
        "u" => 32,
        "v" => 9,
        "w" => 13,
        "x" => 7,
        "y" => 16,
        "z" => 6,
        "0" => 29,
        "1" => 18,
        "2" => 19,
        "3" => 20,
        "4" => 21,
        "5" => 23,
        "6" => 22,
        "7" => 26,
        "8" => 28,
        "9" => 25,
        "f1" => 122,
        "f2" => 120,
        "f3" => 99,
        "f4" => 118,
        "f5" => 96,
        "f6" => 97,
        "f7" => 98,
        "f8" => 100,
        "f9" => 101,
        "f10" => 109,
        "f11" => 103,
        "f12" => 111,
        "f13" => 105,
        "f14" => 107,
        "f15" => 113,
        "f16" => 106,
        "f17" => 64,
        "f18" => 79,
        "f19" => 80,
        "f20" => 90,
        "numpad0" => 82,
        "numpad1" => 83,
        "numpad2" => 84,
        "numpad3" => 85,
        "numpad4" => 86,
        "numpad5" => 87,
        "numpad6" => 88,
        "numpad7" => 89,
        "numpad8" => 91,
        "numpad9" => 92,
        "decimal" => 65,
        "multiply" => 67,
        "add" => 69,
        "subtract" => 78,
        "divide" => 75,
        "insert" | "ins" | "help" => 114,
        _ => return None,
    })
}

pub(crate) fn set_focus(window: &WindowInfo) -> Result<(), (&'static str, String)> {
    let pid = window_owner_pid(window.hwnd as i64).ok_or((
        "window_not_found",
        "Could not resolve the window's process.".to_string(),
    ))?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(super::AX_MESSAGING_TIMEOUT_SECONDS);
    let ax_window = find_ax_window(&app, window.hwnd as u32).ok_or((
        "window_not_found",
        "Accessibility could not locate the window.".to_string(),
    ))?;
    ax_window
        .perform_action(&CFString::from_static_string(kAXRaiseAction))
        .map_err(|_| {
            (
                "focus_failed",
                "The window did not accept being brought forward.".to_string(),
            )
        })?;
    // Raising is asynchronous, so wait for the window to actually hold focus.
    // Reporting success without it would let keyboard input land in whatever
    // application happens to be in front -- one this session may never have
    // been approved for.
    for _ in 0..FOCUS_POLL_ATTEMPTS {
        if window_holds_focus(&app, window.hwnd as u32) {
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_millis(
            FOCUS_POLL_INTERVAL_MS,
        ));
    }
    Err((
        "focus_failed",
        "The window did not take focus; it may be blocked by another window."
            .to_string(),
    ))
}

/// Whether the target window is the one that would receive keyboard input:
/// its application is frontmost and the window is that application's focused
/// window.
fn window_holds_focus(app: &AXUIElement, target: u32) -> bool {
    let frontmost = app
        .attribute(&AXAttribute::new(&CFString::from_static_string(
            "AXFrontmost",
        )))
        .ok()
        .and_then(|value: CFType| value.downcast::<CFBoolean>())
        .map(bool::from)
        .unwrap_or(false);
    if !frontmost {
        return false;
    }
    let Ok(focused) = app.attribute(&AXAttribute::new(
        &CFString::from_static_string("AXFocusedWindow"),
    )) else {
        return false;
    };
    let Some(element) = focused.downcast_into::<AXUIElement>() else {
        return false;
    };
    let mut id: u32 = 0;
    let status = unsafe { _AXUIElementGetWindow(element.as_concrete_TypeRef(), &mut id) };
    status == 0 && id == target
}

fn event_source() -> Result<CGEventSource, (&'static str, String)> {
    CGEventSource::new(CGEventSourceStateID::HIDSystemState).map_err(|_| {
        (
            "input_failed",
            "Could not create the input event source.".to_string(),
        )
    })
}

fn post_mouse(
    source: &CGEventSource,
    event_type: CGEventType,
    point: CGPoint,
    button: CGMouseButton,
) -> Result<(), (&'static str, String)> {
    let event = CGEvent::new_mouse_event(source.clone(), event_type, point, button)
        .map_err(|_| ("input_failed", "Could not create the mouse event.".to_string()))?;
    event.post(CGEventTapLocation::HID);
    Ok(())
}

fn resolve_point(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
    x_key: &str,
    y_key: &str,
) -> Result<CGPoint, (&'static str, String)> {
    let snapshot_id = params
        .get("snapshot_id")
        .and_then(Value::as_str)
        .ok_or(("stale_snapshot", "snapshot_id is required.".to_string()))?;
    let screenshot_id = params
        .get("screenshot_id")
        .and_then(Value::as_str)
        .ok_or(("stale_snapshot", "screenshot_id is required.".to_string()))?;
    let snapshot = state.snapshots.get(snapshot_id).ok_or((
        "stale_snapshot",
        "Snapshot is no longer available; observe the window again.".to_string(),
    ))?;
    if snapshot.window.hwnd != window.hwnd {
        return Err((
            "stale_snapshot",
            "Snapshot does not belong to this window.".to_string(),
        ));
    }
    if snapshot.screenshot_id != screenshot_id {
        return Err((
            "stale_snapshot",
            "Screenshot id does not match the snapshot.".to_string(),
        ));
    }
    // The window must still be where it was when the screenshot was taken,
    // or the mapping below would aim at whatever now occupies those pixels.
    let current = window_bounds(window.hwnd as i64).ok_or((
        "stale_window",
        "Window geometry is no longer available.".to_string(),
    ))?;
    let current_bounds = [
        current.0 as i32,
        current.1 as i32,
        current.2 as i32,
        current.3 as i32,
    ];
    if current_bounds != snapshot.bounds {
        return Err((
            "stale_snapshot",
            "Window geometry changed; observe it again.".to_string(),
        ));
    }
    let x = integer_param(params, x_key)?;
    let y = integer_param(params, y_key)?;
    let (x_offset, y_offset) = map_point(snapshot, x, y)?;
    let point = CGPoint {
        x: f64::from(snapshot.bounds[0]) + x_offset,
        y: f64::from(snapshot.bounds[1]) + y_offset,
    };
    // Finally confirm the target still owns that point: another window may
    // sit above it even though the target itself has not moved.
    if !point_belongs_to_window(point, window.hwnd as i64) {
        return Err((
            "target_not_at_point",
            "Target window is no longer at this point.".to_string(),
        ));
    }
    Ok(point)
}

/// Whether the frontmost window covering `point` is the target window.
///
/// The window list is ordered front to back, so the first on-screen window
/// whose bounds contain the point is the one that would receive a click.
fn point_belongs_to_window(point: CGPoint, window_id: i64) -> bool {
    let option = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements;
    let Some(list) = copy_window_info(option, kCGNullWindowID) else {
        return false;
    };
    for item in list.iter() {
        let dict_ref = (*item) as CFDictionaryRef;
        if dict_ref.is_null() {
            continue;
        }
        let dict = unsafe { CFDictionary::<CFString, CFType>::wrap_under_get_rule(dict_ref) };
        if dict_i64(&dict, unsafe { kCGWindowLayer }).unwrap_or(1) != 0 {
            continue;
        }
        let Some(number) = dict_i64(&dict, unsafe { kCGWindowNumber }) else {
            continue;
        };
        let Some((left, top, width, height)) = bounds_from_dict(&dict) else {
            continue;
        };
        let inside = point.x >= left
            && point.y >= top
            && point.x < left + width
            && point.y < top + height;
        if inside {
            return number == window_id;
        }
    }
    false
}
