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
    CGEvent, CGEventFlags, CGEventTapLocation, CGEventType, CGMouseButton, EventField, KeyCode,
    ScrollEventUnit,
};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
use core_graphics::geometry::CGPoint;
use core_graphics::window::{
    copy_window_info, kCGNullWindowID, kCGWindowLayer, kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionOnScreenOnly, kCGWindowNumber,
};
use objc2_app_kit::{
    NSApplicationActivationOptions, NSRunningApplication, NSWorkspace, NSWorkspaceOpenConfiguration,
};
use serde_json::{json, Map, Value};

use super::super::state::{map_point, Observation, PendingAction, WindowInfo};
use super::accessibility_tree::{
    element_point, element_point_by_id, find_ax_window, interactive_window_at_point,
    invoke_accessibility_element, show_accessibility_menu,
};
use super::{
    bounds_from_dict, dict_i64, integer_param, window_bounds,
    CGEventSourceSecondsSinceLastEventType, CGSessionCopyCurrentDictionary, HostFocusLease,
};

/// How long to wait for a raised window to actually hold focus before
/// refusing to inject input.
const FOCUS_POLL_ATTEMPTS: u32 = 20;
const FOCUS_POLL_INTERVAL_MS: u64 = 25;
const MULTI_CLICK_INTERVAL_MS: u64 = 50;
const TEXT_INPUT_INTERVAL_MS: u64 = 8;
const EVENT_SOURCE_STATE_HID_SYSTEM: u32 = 1;
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
        let dict: CFDictionary<CFString, CFType> = CFDictionary::wrap_under_create_rule(dict_ref);
        let key = CFString::from_static_string("CGSSessionScreenIsLocked");
        let Some(value) = dict.find(&key) else {
            // The key is only present while the screen is locked, so its
            // absence is a definite unlocked -- not a failure to tell. Reading
            // it as unknown would refuse every action on a normal desktop.
            return LockState::Unlocked;
        };
        match value
            .downcast::<CFNumber>()
            .and_then(|number| number.to_i64())
        {
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

/// Milliseconds since the last hardware keyboard or mouse event.
///
/// The decision about what age is too recent, and the exemption that follows an
/// approval, belong to the shared input guard; this reports the measurement and
/// nothing else.
pub(crate) fn last_input_age_ms() -> Option<u32> {
    let idle_seconds = unsafe {
        CGEventSourceSecondsSinceLastEventType(EVENT_SOURCE_STATE_HID_SYSTEM, ANY_INPUT_EVENT_TYPE)
    };
    // A machine idle for weeks would overflow; saturating is correct because
    // anything past the grace window is equally "long ago".
    Some((idle_seconds * 1000.0).clamp(0.0, f64::from(u32::MAX)) as u32)
}

pub(crate) fn click(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let button = params
        .get("button")
        .and_then(Value::as_str)
        .unwrap_or("left");
    if params.contains_key("element_id") && button == "right" {
        ensure_observed_geometry(observation)?;
        let _focus_lease = set_focus(&observation.window)?;
        ensure_observed_geometry(observation)?;
        if let Some(result) = show_accessibility_menu(observation, params)? {
            return Ok(result);
        }
    }
    let (point, _focus_lease) = if params.contains_key("element_id") {
        prepare_element_point(observation, params)?
    } else {
        prepare_point(observation, params, "x", "y")?
    };
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
    for click_state in 1..=count {
        post_mouse_click(&source, down, point, mouse_button, click_state)?;
        post_mouse_click(&source, up, point, mouse_button, click_state)?;
        if click_state < count {
            std::thread::sleep(std::time::Duration::from_millis(MULTI_CLICK_INTERVAL_MS));
        }
    }
    Ok(json!({"applied": true}))
}

pub(crate) fn invoke_element(
    observation: &Observation,
    params: &Map<String, Value>,
    pending: Option<&PendingAction>,
) -> Result<Value, (&'static str, String)> {
    // Menu items use AXPick when the application exposes it. Unlike a pointer
    // fallback, the semantic action also works when the command intentionally
    // has no persistent on-screen rectangle.
    invoke_accessibility_element(observation, params, pending)
}

pub(crate) fn scroll(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let (point, _focus_lease) = prepare_point(observation, params, "x", "y")?;
    let delta_y = integer_param(params, "delta_y")? as i32;
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, point, CGMouseButton::Left)?;
    let event = CGEvent::new_scroll_event(source, ScrollEventUnit::PIXEL, 1, -delta_y, 0, 0)
        .map_err(|_| {
            (
                "input_failed",
                "Could not create the scroll event.".to_string(),
            )
        })?;
    event.post(CGEventTapLocation::HID);
    Ok(json!({"applied": true}))
}

pub(crate) fn drag(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let (start, end, _focus_lease) = drag_points(observation, params)?;
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, start, CGMouseButton::Left)?;
    post_mouse(
        &source,
        CGEventType::LeftMouseDown,
        start,
        CGMouseButton::Left,
    )?;
    std::thread::sleep(std::time::Duration::from_millis(80));
    for step in 1..=12 {
        let ratio = f64::from(step) / 12.0;
        let point = CGPoint {
            x: start.x + (end.x - start.x) * ratio,
            y: start.y + (end.y - start.y) * ratio,
        };
        post_mouse(
            &source,
            CGEventType::LeftMouseDragged,
            point,
            CGMouseButton::Left,
        )?;
        std::thread::sleep(std::time::Duration::from_millis(16));
    }
    std::thread::sleep(std::time::Duration::from_millis(80));
    post_mouse(&source, CGEventType::LeftMouseUp, end, CGMouseButton::Left)?;
    Ok(json!({"applied": true}))
}

fn drag_points(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<(CGPoint, CGPoint, HostFocusLease), (&'static str, String)> {
    let source_id = params.get("source_element_id").and_then(Value::as_str);
    let target_id = params.get("target_element_id").and_then(Value::as_str);
    match (source_id, target_id) {
        (Some(source_id), Some(target_id)) => {
            element_point_unchecked(observation, source_id)?;
            element_point_unchecked(observation, target_id)?;
            let focus_lease = set_focus(&observation.window)?;
            Ok((
                resolve_element_point_by_id(observation, source_id)?,
                resolve_element_point_by_id(observation, target_id)?,
                focus_lease,
            ))
        }
        (None, None) => {
            resolve_point(observation, params, "start_x", "start_y")?;
            resolve_point(observation, params, "end_x", "end_y")?;
            let focus_lease = set_focus(&observation.window)?;
            Ok((
                resolve_target_point(observation, params, "start_x", "start_y")?,
                resolve_target_point(observation, params, "end_x", "end_y")?,
                focus_lease,
            ))
        }
        _ => Err((
            "invalid_request",
            "Both source_element_id and target_element_id are required for an element drag."
                .to_string(),
        )),
    }
}

pub(crate) fn type_text(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let text = params
        .get("text")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "text is required.".to_string()))?;
    let _focus_lease = set_focus(&observation.window)?;
    let source = event_source()?;
    // Some field editors ignore a multi-character Unicode payload on one key
    // event. Pace complete key pairs so those editors receive normal text
    // input without overwhelming controls that process events asynchronously.
    for character in text.chars() {
        let value = character.to_string();
        post_text_event(&source, &value, true)?;
        post_text_event(&source, "", false)?;
        std::thread::sleep(std::time::Duration::from_millis(TEXT_INPUT_INTERVAL_MS));
    }
    Ok(json!({"applied": true, "text_length": text.chars().count()}))
}

fn post_text_event(
    source: &CGEventSource,
    value: &str,
    key_down: bool,
) -> Result<(), (&'static str, String)> {
    let event = CGEvent::new_keyboard_event(source.clone(), 0, key_down).map_err(|_| {
        (
            "input_failed",
            "Could not create the keyboard event.".to_string(),
        )
    })?;
    if !value.is_empty() {
        event.set_string(value);
    }
    event.post(CGEventTapLocation::HID);
    Ok(())
}

pub(crate) fn press_key(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let key = params
        .get("key")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "key is required.".to_string()))?;
    let (keycode, flags) =
        parse_key(key).ok_or(("invalid_request", format!("Unsupported key: {key}")))?;
    let _focus_lease = set_focus(&observation.window)?;
    let source = event_source()?;
    let down = CGEvent::new_keyboard_event(source.clone(), keycode, true).map_err(|_| {
        (
            "input_failed",
            "Could not create the key event.".to_string(),
        )
    })?;
    down.set_flags(flags);
    down.post(CGEventTapLocation::HID);
    let up = CGEvent::new_keyboard_event(source, keycode, false).map_err(|_| {
        (
            "input_failed",
            "Could not create the key event.".to_string(),
        )
    })?;
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

fn set_focus(window: &WindowInfo) -> Result<HostFocusLease, (&'static str, String)> {
    let pid = (window.owner_pid > 0).then_some(window.owner_pid).ok_or((
        "window_not_found",
        "Could not resolve the window's process.".to_string(),
    ))?;
    let focus_lease = HostFocusLease::begin(pid)?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(super::AX_MESSAGING_TIMEOUT_SECONDS);
    let ax_window = find_ax_window(&app, window.hwnd as u32).ok_or((
        "window_not_found",
        "Accessibility could not locate the window.".to_string(),
    ))?;
    if window_holds_focus(&app, &ax_window) {
        return Ok(focus_lease);
    }
    let running_app =
        NSRunningApplication::runningApplicationWithProcessIdentifier(pid).ok_or((
            "focus_failed",
            "Could not resolve the target application.".to_string(),
        ))?;
    let _ = running_app.unhide();
    if let Some(bundle_url) = running_app.bundleURL() {
        let configuration = NSWorkspaceOpenConfiguration::configuration();
        configuration.setActivates(true);
        configuration.setAddsToRecentItems(false);
        configuration.setPromptsUserIfNeeded(false);
        NSWorkspace::sharedWorkspace().openApplicationAtURL_configuration_completionHandler(
            &bundle_url,
            &configuration,
            None,
        );
    }
    let _ = running_app.activateWithOptions(NSApplicationActivationOptions::empty());
    // Sheets commonly reject AXRaise even while their text field already owns
    // input. Treat raising as a best-effort request and verify the actual
    // focused element below instead of failing on that implementation detail.
    let _ = ax_window.perform_action(&CFString::from_static_string(kAXRaiseAction));
    // Raising is asynchronous, so wait for the window to actually hold focus.
    // Reporting success without it would let keyboard input land in whatever
    // application happens to be in front -- one this session may never have
    // been approved for.
    for _ in 0..FOCUS_POLL_ATTEMPTS {
        if window_holds_focus(&app, &ax_window) {
            return Ok(focus_lease);
        }
        std::thread::sleep(std::time::Duration::from_millis(FOCUS_POLL_INTERVAL_MS));
    }
    Err((
        "focus_failed",
        "The window did not take focus; it may be blocked by another window.".to_string(),
    ))
}

/// Whether keyboard input belongs to this window or one of its descendants.
///
/// A modal sheet is represented as a descendant of its owner rather than as
/// the application's `AXFocusedWindow` on several macOS apps. Checking the
/// focused element's parent chain covers that normal sheet shape.
fn window_holds_focus(app: &AXUIElement, target: &AXUIElement) -> bool {
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
    for attribute in ["AXFocusedUIElement", "AXFocusedWindow"] {
        let Ok(value) = app.attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        else {
            continue;
        };
        let Some(element) = value.downcast_into::<AXUIElement>() else {
            continue;
        };
        if is_descendant_of(&element, target) {
            return true;
        }
    }
    false
}

fn is_descendant_of(element: &AXUIElement, ancestor: &AXUIElement) -> bool {
    let mut current = element.clone();
    for _ in 0..64 {
        // AX may return a new reference for the same accessibility object.
        // Pointer identity therefore produces false negatives after a window
        // has successfully taken focus; CFEqual compares the AX objects.
        if current.as_CFType() == ancestor.as_CFType() {
            return true;
        }
        let Ok(parent) =
            current.attribute(&AXAttribute::new(&CFString::from_static_string("AXParent")))
        else {
            return false;
        };
        let Some(parent) = parent.downcast_into::<AXUIElement>() else {
            return false;
        };
        current = parent;
    }
    false
}

fn event_source() -> Result<CGEventSource, (&'static str, String)> {
    // Remote-control input must not mutate the hardware state table that the
    // user-intervention guard reads. A private source keeps helper-generated
    // events separate while they still enter the normal HID event tap.
    CGEventSource::new(CGEventSourceStateID::Private).map_err(|_| {
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
    let event =
        CGEvent::new_mouse_event(source.clone(), event_type, point, button).map_err(|_| {
            (
                "input_failed",
                "Could not create the mouse event.".to_string(),
            )
        })?;
    event.post(CGEventTapLocation::HID);
    Ok(())
}

fn post_mouse_click(
    source: &CGEventSource,
    event_type: CGEventType,
    point: CGPoint,
    button: CGMouseButton,
    click_state: i64,
) -> Result<(), (&'static str, String)> {
    let event =
        CGEvent::new_mouse_event(source.clone(), event_type, point, button).map_err(|_| {
            (
                "input_failed",
                "Could not create the mouse event.".to_string(),
            )
        })?;
    event.set_integer_value_field(EventField::MOUSE_EVENT_CLICK_STATE, click_state);
    event.post(CGEventTapLocation::HID);
    Ok(())
}

fn prepare_point(
    observation: &Observation,
    params: &Map<String, Value>,
    x_key: &str,
    y_key: &str,
) -> Result<(CGPoint, HostFocusLease), (&'static str, String)> {
    // Refuse stale geometry before changing focus, then verify it again once
    // activation has completed. The final hit test must happen after focus so
    // a foreground QwenPaw window does not make every background target fail.
    resolve_point(observation, params, x_key, y_key)?;
    let focus_lease = set_focus(&observation.window)?;
    Ok((
        resolve_target_point(observation, params, x_key, y_key)?,
        focus_lease,
    ))
}

fn prepare_element_point(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<(CGPoint, HostFocusLease), (&'static str, String)> {
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    element_point_unchecked(observation, element_id)?;
    let focus_lease = set_focus(&observation.window)?;
    Ok((resolve_element_point(observation, params)?, focus_lease))
}

fn resolve_element_point(
    observation: &Observation,
    params: &Map<String, Value>,
) -> Result<CGPoint, (&'static str, String)> {
    ensure_observed_geometry(observation)?;
    let (x, y) = element_point(observation, params)?;
    let point = CGPoint { x, y };
    verify_target_point(observation, point)
}

fn resolve_element_point_by_id(
    observation: &Observation,
    element_id: &str,
) -> Result<CGPoint, (&'static str, String)> {
    verify_target_point(
        observation,
        element_point_unchecked(observation, element_id)?,
    )
}

fn element_point_unchecked(
    observation: &Observation,
    element_id: &str,
) -> Result<CGPoint, (&'static str, String)> {
    ensure_observed_geometry(observation)?;
    let (x, y) = element_point_by_id(observation, element_id)?;
    Ok(CGPoint { x, y })
}

fn ensure_observed_geometry(observation: &Observation) -> Result<(), (&'static str, String)> {
    let current = window_bounds(observation.window.hwnd as i64).ok_or((
        "stale_window",
        "Window geometry is no longer available.".to_string(),
    ))?;
    let current_bounds = [
        current.0 as i32,
        current.1 as i32,
        current.2 as i32,
        current.3 as i32,
    ];
    if current_bounds != observation.bounds {
        return Err((
            "stale_observation",
            "Window geometry changed; observe it again.".to_string(),
        ));
    }
    Ok(())
}

fn verify_target_point(
    observation: &Observation,
    point: CGPoint,
) -> Result<CGPoint, (&'static str, String)> {
    match interactive_window_at_point(point) {
        Some(window_id) if window_id == observation.window.hwnd as i64 => Ok(point),
        Some(window_id) => Err((
            "target_not_at_point",
            format!(
                "Another window owns the interactive element at the target point ({window_id})."
            ),
        )),
        None => Err((
            "target_not_at_point",
            "No interactive element is available at the target point.".to_string(),
        )),
    }
}

fn resolve_target_point(
    observation: &Observation,
    params: &Map<String, Value>,
    x_key: &str,
    y_key: &str,
) -> Result<CGPoint, (&'static str, String)> {
    let point = resolve_point(observation, params, x_key, y_key)?;
    match frontmost_window_at_point(point) {
        Some(window_id) if window_id == observation.window.hwnd as i64 => Ok(point),
        Some(window_id) => Err((
            "target_not_at_point",
            format!("Target point is covered by window {window_id}."),
        )),
        None => Err((
            "target_not_at_point",
            "Target point is not covered by an on-screen window.".to_string(),
        )),
    }
}

fn resolve_point(
    observation: &Observation,
    params: &Map<String, Value>,
    x_key: &str,
    y_key: &str,
) -> Result<CGPoint, (&'static str, String)> {
    // The window must still be where it was when the observation was taken,
    // or the mapping below would aim at whatever now occupies those pixels.
    ensure_observed_geometry(observation)?;
    let x = integer_param(params, x_key)?;
    let y = integer_param(params, y_key)?;
    let (x_offset, y_offset) = map_point(observation, x, y)?;
    Ok(CGPoint {
        x: f64::from(observation.bounds[0]) + x_offset,
        y: f64::from(observation.bounds[1]) + y_offset,
    })
}

/// The window list is ordered front to back, so the first on-screen window
/// whose bounds contain the point is the one that would receive a click.
fn frontmost_window_at_point(point: CGPoint) -> Option<i64> {
    let option = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements;
    let list = copy_window_info(option, kCGNullWindowID)?;
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
        let inside =
            point.x >= left && point.y >= top && point.x < left + width && point.y < top + height;
        if inside {
            return Some(number);
        }
    }
    None
}
