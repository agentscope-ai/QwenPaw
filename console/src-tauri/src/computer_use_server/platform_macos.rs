//! macOS Computer Use leaf: window discovery, capture, UI automation, and
//! input.
//!
//! The RPC server, framing, transport, session/turn lifecycle, and app
//! approval are shared with Windows (see `mod.rs`). Only these OS-touching
//! leaves are platform specific: window discovery uses the CoreGraphics window
//! list, capture uses CGWindowListCreateImage (dev-tier; ScreenCaptureKit is
//! the shippable path), accessibility uses AXUIElement, and input uses CGEvent.

use accessibility::{AXAttribute, AXUIElement};
use accessibility_sys::{kAXPressAction, kAXRaiseAction, AXError, AXUIElementRef};
use base64::Engine;
use core_foundation::base::{CFType, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::number::CFNumber;
use core_foundation::string::{CFString, CFStringRef};
use core_graphics::event::{
    CGEvent, CGEventFlags, CGEventTapLocation, CGEventType, CGMouseButton, KeyCode, ScrollEventUnit,
};
use core_graphics::event_source::{CGEventSource, CGEventSourceStateID};
use core_graphics::geometry::{CGPoint, CGRect, CGSize};
use core_graphics::window::{
    copy_window_info, create_image, kCGNullWindowID, kCGWindowBounds,
    kCGWindowImageBoundsIgnoreFraming, kCGWindowLayer, kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionIncludingWindow, kCGWindowListOptionOnScreenOnly, kCGWindowName,
    kCGWindowNumber, kCGWindowOwnerName, kCGWindowOwnerPID, CGWindowID,
};
use jpeg_encoder::{ColorType, Encoder};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

use super::{
    element_line, map_point, merge_app_list, next_id, truncate_document_text,
    AccessibilitySnapshot, InstalledApp, ServerState, Snapshot, WindowInfo,
    SCREENSHOT_JPEG_QUALITY, SCREENSHOT_MAX_EDGE, USER_INTERVENTION_GRACE_MS,
};

/// How long to wait for a raised window to actually hold focus before
/// refusing to inject input.
const FOCUS_POLL_ATTEMPTS: u32 = 20;
const FOCUS_POLL_INTERVAL_MS: u64 = 25;

/// Directories a macOS application bundle is normally installed into.
///
/// Only one level is scanned, plus the Utilities folders Apple ships, because
/// a full recursive walk would pick up the many nested helper bundles inside
/// each application.
const APP_SEARCH_DIRS: [&str; 4] = [
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
];

// Private ApplicationServices API mapping an accessibility window element to
// its CoreGraphics window id. It is the reliable way to match a CGWindowID
// (the id carried by the shared protocol) to the app's AX window subtree.
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn _AXUIElementGetWindow(element: AXUIElementRef, out: *mut u32) -> AXError;
}

const EVENT_SOURCE_STATE_COMBINED_SESSION: u32 = 1;
const ANY_INPUT_EVENT_TYPE: u32 = 0xFFFF_FFFF;

// A close request is asynchronous: wait briefly for the window to go away
// before reporting that it is still open (usually a save prompt).
const CLOSE_POLL_ATTEMPTS: u32 = 40;
const CLOSE_POLL_INTERVAL_MS: u64 = 50;

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventSourceSecondsSinceLastEventType(state_id: u32, event_type: u32) -> f64;
    fn CGSessionCopyCurrentDictionary() -> CFDictionaryRef;
}

/// Read the current login-session dictionary and report the lock flag.
/// Returns `None` when the session dictionary is unavailable (for example
/// no active GUI session), which callers treat as "not known to be locked".
fn session_screen_is_locked() -> Option<bool> {
    unsafe {
        let dict_ref = CGSessionCopyCurrentDictionary();
        if dict_ref.is_null() {
            return None;
        }
        let dict: CFDictionary<CFString, CFType> =
            CFDictionary::wrap_under_create_rule(dict_ref);
        let key = CFString::from_static_string("CGSSessionScreenIsLocked");
        let value = dict.find(&key)?;
        let number = value.downcast::<CFNumber>()?;
        Some(number.to_i64().unwrap_or(0) != 0)
    }
}

/// Native accessibility element handle for the shared snapshot store.
pub(super) struct AxElement {
    element: AXUIElement,
}

pub(super) fn list_windows() -> Vec<Value> {
    enumerate_windows()
        .into_iter()
        .map(|window| window.to_json())
        .collect()
}

pub(super) fn list_apps() -> Vec<Value> {
    merge_app_list(installed_apps(), enumerate_windows())
}

/// Applications installed in the usual locations, whether running or not.
///
/// Discovery matters because launching an application is only useful when it
/// is not already open, and a window-derived list can never name those.
fn installed_apps() -> Vec<InstalledApp> {
    let mut apps = Vec::new();
    let mut roots: Vec<PathBuf> = APP_SEARCH_DIRS.iter().map(PathBuf::from).collect();
    if let Some(home) = std::env::var_os("HOME") {
        roots.push(PathBuf::from(home).join("Applications"));
    }
    for root in roots {
        let Ok(entries) = std::fs::read_dir(&root) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if !path
                .extension()
                .is_some_and(|value| value.eq_ignore_ascii_case("app"))
            {
                continue;
            }
            let Some(display_name) = path.file_stem().and_then(|value| value.to_str()) else {
                continue;
            };
            apps.push(InstalledApp {
                app_id: app_id_from_bundle_path(&path),
                display_name: display_name.to_string(),
            });
        }
    }
    apps
}

pub(super) fn resolve_window(value: &str) -> Result<WindowInfo, (&'static str, String)> {
    let id = value
        .parse::<i64>()
        .map_err(|_| ("invalid_request", "window_id is invalid.".to_string()))?;
    enumerate_windows()
        .into_iter()
        .find(|window| window.hwnd as i64 == id)
        .ok_or((
            "window_not_found",
            "Target window was not found.".to_string(),
        ))
}

pub(super) fn is_forbidden(window: &WindowInfo) -> bool {
    let title = window.title.to_ascii_lowercase();
    let name = window.display_name.to_ascii_lowercase();
    title.contains("password")
        || title.contains("credential")
        || title.contains("keychain")
        || title.contains("qwenpaw")
        || name.contains("keychain access")
}

/// Enumerate on-screen, normal-layer application windows via the CoreGraphics
/// window list. Titles require Screen Recording permission; without it the
/// window still lists but its title may be empty.
fn enumerate_windows() -> Vec<WindowInfo> {
    let option = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements;
    let Some(list) = copy_window_info(option, kCGNullWindowID) else {
        return Vec::new();
    };
    let mut windows = Vec::new();
    for item in list.iter() {
        let dict_ref = (*item) as CFDictionaryRef;
        if dict_ref.is_null() {
            continue;
        }
        let dict = unsafe { CFDictionary::<CFString, CFType>::wrap_under_get_rule(dict_ref) };
        // Layer 0 is the normal application window layer; skip the menu bar,
        // Dock, and other system/desktop layers.
        if dict_i64(&dict, unsafe { kCGWindowLayer }).unwrap_or(1) != 0 {
            continue;
        }
        let Some(number) = dict_i64(&dict, unsafe { kCGWindowNumber }) else {
            continue;
        };
        let owner = dict_string(&dict, unsafe { kCGWindowOwnerName }).unwrap_or_default();
        if owner.is_empty() {
            continue;
        }
        let pid = dict_i64(&dict, unsafe { kCGWindowOwnerPID }).unwrap_or(0);
        let title = dict_string(&dict, unsafe { kCGWindowName }).unwrap_or_default();
        windows.push(WindowInfo {
            hwnd: number as isize,
            app_id: app_id_for_pid(pid as i32, &owner),
            display_name: owner.clone(),
            title,
            class_name: owner,
        });
    }
    windows
}

/// Canonical identifier for the application owning a window.
///
/// The bundle path is preferred because it is stable and can be launched
/// again later, mirroring the process path Windows uses. When it cannot be
/// read -- a system-protected process, for instance -- fall back to the owner
/// name so the window stays addressable, accepting that such an application
/// cannot be launched by id.
fn app_id_for_pid(pid: i32, owner: &str) -> String {
    bundle_path_for_pid(pid)
        .map(|path| app_id_from_bundle_path(&path))
        .unwrap_or_else(|| format!("app:{}", owner.to_lowercase()))
}

/// Canonical identifier for an application bundle or executable path.
///
/// Both discovery routes -- scanning the install directories and reading a
/// running process -- pass through here, and both resolve symlinks first, so
/// one application cannot end up with two identifiers and be approved twice.
pub(super) fn app_id_from_bundle_path(path: &Path) -> String {
    let resolved = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    format!("app:{}", resolved.to_string_lossy().to_lowercase())
}

/// Resolve the application bundle that owns a process.
///
/// `proc_pidpath` yields the executable inside the bundle, so walk up to the
/// nearest `.app` ancestor. The nearest one is deliberate: a nested bundle
/// such as Instruments inside Xcode is its own application as far as its
/// windows and authorisation are concerned.
fn bundle_path_for_pid(pid: i32) -> Option<PathBuf> {
    if pid <= 0 {
        return None;
    }
    let mut buffer = vec![0u8; libc::PROC_PIDPATHINFO_MAXSIZE as usize];
    let written = unsafe {
        libc::proc_pidpath(
            pid,
            buffer.as_mut_ptr() as *mut libc::c_void,
            buffer.len() as u32,
        )
    };
    if written <= 0 {
        return None;
    }
    buffer.truncate(written as usize);
    let executable = PathBuf::from(String::from_utf8(buffer).ok()?);
    bundle_root(&executable).or(Some(executable))
}

/// The nearest `.app` ancestor of a path, if it sits inside a bundle.
fn bundle_root(path: &Path) -> Option<PathBuf> {
    path.ancestors()
        .find(|ancestor| {
            ancestor
                .extension()
                .is_some_and(|value| value.eq_ignore_ascii_case("app"))
        })
        .map(Path::to_path_buf)
}

fn dict_i64(dict: &CFDictionary<CFString, CFType>, key: CFStringRef) -> Option<i64> {
    let key = unsafe { CFString::wrap_under_get_rule(key) };
    let value = dict.find(&key)?;
    value.downcast::<CFNumber>().and_then(|number| number.to_i64())
}

fn dict_string(dict: &CFDictionary<CFString, CFType>, key: CFStringRef) -> Option<String> {
    let key = unsafe { CFString::wrap_under_get_rule(key) };
    let value = dict.find(&key)?;
    value.downcast::<CFString>().map(|string| string.to_string())
}

pub(super) fn observe_window(
    state: &mut ServerState,
    window: &WindowInfo,
) -> Result<Value, (&'static str, String)> {
    // Dev-tier capture uses the synchronous CGWindowListCreateImage. A null
    // screen rect with kCGWindowListOptionIncludingWindow captures just this
    // window at its own bounds. Migrate to ScreenCaptureKit for the shippable
    // (background-capable) build.
    let null_rect = CGRect {
        origin: CGPoint {
            x: f64::INFINITY,
            y: f64::INFINITY,
        },
        size: CGSize {
            width: 0.0,
            height: 0.0,
        },
    };
    let image = create_image(
        null_rect,
        kCGWindowListOptionIncludingWindow,
        window.hwnd as CGWindowID,
        kCGWindowImageBoundsIgnoreFraming,
    )
    .ok_or(("capture_failed", "Could not capture the window.".to_string()))?;

    let width = image.width();
    let height = image.height();
    let bytes_per_row = image.bytes_per_row();
    let pixel_bytes = image.bits_per_pixel() / 8;
    if width == 0 || height == 0 || pixel_bytes < 3 {
        return Err((
            "capture_failed",
            "Captured window had no pixels.".to_string(),
        ));
    }
    let data = image.data();
    let raw = data.bytes();

    // Bound the longest edge to keep the payload and image-token cost small,
    // matching the Windows leaf. Nearest-neighbor is adequate for on-screen
    // text/control legibility at this scale.
    let longest = width.max(height) as u32;
    let (display_width, display_height) = if longest > SCREENSHOT_MAX_EDGE {
        let scale = SCREENSHOT_MAX_EDGE as f64 / longest as f64;
        (
            ((width as f64 * scale).round() as usize).max(1),
            ((height as f64 * scale).round() as usize).max(1),
        )
    } else {
        (width, height)
    };

    // CGWindowListCreateImage yields 32-bit BGRA (premultiplied). Repack into
    // tight RGB for the JPEG encoder.
    let mut rgb = Vec::with_capacity(display_width * display_height * 3);
    for out_y in 0..display_height {
        let src_y = (out_y * height / display_height).min(height - 1);
        let row = src_y * bytes_per_row;
        for out_x in 0..display_width {
            let src_x = (out_x * width / display_width).min(width - 1);
            let offset = row + src_x * pixel_bytes;
            rgb.push(raw[offset + 2]);
            rgb.push(raw[offset + 1]);
            rgb.push(raw[offset]);
        }
    }

    let mut jpeg = Vec::new();
    let quality = (SCREENSHOT_JPEG_QUALITY * 100.0).round().clamp(1.0, 100.0) as u8;
    Encoder::new(&mut jpeg, quality)
        .encode(
            &rgb,
            display_width as u16,
            display_height as u16,
            ColorType::Rgb,
        )
        .map_err(|error| ("capture_failed", format!("JPEG encoding failed: {error}")))?;

    let capture_id = next_id("screenshot");
    let snapshot_id = next_id("snapshot");
    // Store the window's on-screen bounds in points so coordinate input can map
    // display-space fractions back to the global point coordinates CGEvent uses.
    let point_bounds = window_bounds(window.hwnd as i64)
        .map(|(x, y, w, h)| [x as i32, y as i32, w as i32, h as i32])
        .unwrap_or([0, 0, width as i32, height as i32]);
    state.snapshots.insert(
        snapshot_id.clone(),
        Snapshot {
            window: window.clone(),
            bounds: point_bounds,
            screenshot_id: capture_id.clone(),
            display_width: display_width as u32,
            display_height: display_height as u32,
        },
    );

    let (accessibility_revision, accessibility) = match collect_accessibility(window) {
        Ok((revision, description, elements)) => {
            state.accessibility.insert(
                revision.clone(),
                AccessibilitySnapshot {
                    window_hwnd: window.hwnd,
                    elements,
                },
            );
            (revision, description)
        }
        Err(reason) => (
            String::new(),
            json!({"available": false, "reason": reason, "elements": []}),
        ),
    };

    Ok(json!({
        "snapshot_id": snapshot_id,
        "geometry_revision": next_id("geometry"),
        "accessibility_revision": accessibility_revision,
        "window": window.to_json(),
        "accessibility": accessibility,
        "screenshots": [{
            "id": capture_id,
            "url": format!(
                "data:image/jpeg;base64,{}",
                base64::engine::general_purpose::STANDARD.encode(&jpeg),
            ),
        }],
    }))
}

pub(super) fn invoke_element(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let element = accessibility_element(state, window, params)?;
    reject_recent_user_intervention()?;
    element
        .element
        .perform_action(&CFString::from_static_string(kAXPressAction))
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility press failed: {error:?}"),
            )
        })?;
    Ok(json!({"applied": true}))
}

pub(super) fn set_value(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let value = params
        .get("value")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "value is required.".to_string()))?;
    let element = accessibility_element(state, window, params)?;
    reject_recent_user_intervention()?;
    element
        .element
        .set_attribute(&AXAttribute::value(), CFString::new(value).as_CFType())
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility value update failed: {error:?}"),
            )
        })?;
    Ok(json!({"applied": true}))
}

fn accessibility_element<'a>(
    state: &'a ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<&'a AxElement, (&'static str, String)> {
    let revision = params
        .get("accessibility_revision")
        .and_then(Value::as_str)
        .ok_or((
            "stale_accessibility",
            "accessibility_revision is required.".to_string(),
        ))?;
    let element_id = params
        .get("element_id")
        .and_then(Value::as_str)
        .ok_or(("invalid_request", "element_id is required.".to_string()))?;
    let snapshot = state.accessibility.get(revision).ok_or((
        "stale_accessibility",
        "Accessibility state is no longer available; observe the window again.".to_string(),
    ))?;
    if snapshot.window_hwnd != window.hwnd {
        return Err((
            "stale_accessibility",
            "Element does not belong to this window.".to_string(),
        ));
    }
    snapshot.elements.get(element_id).ok_or((
        "element_not_found",
        "Element is not available in this accessibility revision.".to_string(),
    ))
}

thread_local! {
    // One-shot exemption armed by the host right after the user resolves an
    // approval prompt, so the following action does not misread that click
    // as the person taking over the machine.
    static INTERVENTION_BYPASS_ONCE: std::cell::Cell<bool> =
        const { std::cell::Cell::new(false) };
}

/// Arm or clear the one-shot recency-guard exemption for this connection.
pub(super) fn set_intervention_bypass_once(value: bool) {
    INTERVENTION_BYPASS_ONCE.with(|cell| cell.set(value));
}

/// Report whether the login session is currently locked. A locked session
/// must not receive synthesized input.
pub(super) fn desktop_locked() -> bool {
    session_screen_is_locked().unwrap_or(false)
}

/// Reject an action if a person used the keyboard or mouse within the grace
/// window, so automated input never races a human.
fn reject_recent_user_intervention() -> Result<(), (&'static str, String)> {
    if INTERVENTION_BYPASS_ONCE.with(|cell| cell.replace(false)) {
        return Ok(());
    }
    let idle_seconds = unsafe {
        CGEventSourceSecondsSinceLastEventType(
            EVENT_SOURCE_STATE_COMBINED_SESSION,
            ANY_INPUT_EVENT_TYPE,
        )
    };
    if idle_seconds * 1000.0 < f64::from(USER_INTERVENTION_GRACE_MS) {
        return Err((
            "user_intervention",
            "A person used the keyboard or mouse very recently; try again.".to_string(),
        ));
    }
    Ok(())
}

fn collect_accessibility(
    window: &WindowInfo,
) -> Result<(String, Value, HashMap<String, AxElement>), String> {
    let pid = window_owner_pid(window.hwnd as i64)
        .ok_or_else(|| "Could not resolve the window's process.".to_string())?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(2.0);
    let root = find_ax_window(&app, window.hwnd as u32)
        .ok_or_else(|| "Accessibility could not locate the window.".to_string())?;
    let revision = next_id("accessibility");
    let mut elements = HashMap::new();
    let mut descriptions = Vec::new();
    // The focused element is picked out of this window's own subtree, so it
    // can never describe another application's UI.
    let mut focused: Option<(String, AXUIElement)> = None;
    walk_accessibility(&root, 0, &mut elements, &mut descriptions, &mut focused);
    // Summary fields are best-effort: a missing one is simply omitted so an
    // observation never fails because a control withheld its text.
    let mut accessibility = serde_json::Map::new();
    accessibility.insert("available".to_string(), json!(true));
    accessibility.insert("revision".to_string(), json!(revision));
    if let Some((line, element)) = focused.as_ref() {
        accessibility.insert("focused_element".to_string(), json!(line));
        if let Some(text) = ax_string(element, "AXValue") {
            accessibility.insert(
                "document_text".to_string(),
                json!(truncate_document_text(text)),
            );
        }
    }
    accessibility.insert("elements".to_string(), json!(descriptions));
    Ok((revision, Value::Object(accessibility), elements))
}

/// Read a string-valued accessibility attribute, if the element exposes one.
fn ax_string(element: &AXUIElement, attribute: &'static str) -> Option<String> {
    let value: CFType = element
        .attribute(&AXAttribute::new(&CFString::from_static_string(attribute)))
        .ok()?;
    let text = value.downcast::<CFString>()?.to_string();
    if text.is_empty() {
        return None;
    }
    Some(text)
}

fn find_ax_window(app: &AXUIElement, target: u32) -> Option<AXUIElement> {
    let windows = app.attribute(&AXAttribute::children()).ok()?;
    for window in windows.iter() {
        let mut id: u32 = 0;
        let status = unsafe { _AXUIElementGetWindow(window.as_concrete_TypeRef(), &mut id) };
        if status == 0 && id == target {
            return Some(window.clone());
        }
    }
    None
}

fn walk_accessibility(
    element: &AXUIElement,
    depth: usize,
    elements: &mut HashMap<String, AxElement>,
    descriptions: &mut Vec<Value>,
    focused: &mut Option<(String, AXUIElement)>,
) {
    if depth > 40 || descriptions.len() >= 300 {
        return;
    }
    let role = element
        .attribute(&AXAttribute::role())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let title = element
        .attribute(&AXAttribute::title())
        .map(|value| value.to_string())
        .unwrap_or_default();
    let value = element
        .attribute(&AXAttribute::value())
        .ok()
        .and_then(|value: CFType| value.downcast::<CFString>().map(|text| text.to_string()))
        .unwrap_or_default();
    if !role.is_empty() && (!title.is_empty() || !value.is_empty()) {
        let element_id = format!("ax-{}", descriptions.len());
        let control_type_name = role_to_control_type_name(&role);
        if focused.is_none()
            && element
                .attribute(&AXAttribute::focused())
                .map(bool::from)
                .unwrap_or(false)
        {
            *focused = Some((
                element_line(&element_id, control_type_name, &title),
                element.clone(),
            ));
        }
        descriptions.push(json!({
            "id": element_id,
            "name": title,
            "value": value,
            "role": role,
            "control_type_name": control_type_name,
        }));
        elements.insert(
            element_id,
            AxElement {
                element: element.clone(),
            },
        );
    }
    if let Ok(children) = element.attribute(&AXAttribute::children()) {
        for child in children.iter() {
            walk_accessibility(&child, depth + 1, elements, descriptions, focused);
        }
    }
}

/// Map an AX role to the same human-readable control-type vocabulary the
/// Windows leaf uses, so the cross-platform SKILL guidance applies uniformly.
fn role_to_control_type_name(role: &str) -> &'static str {
    match role {
        "AXButton" | "AXMenuButton" => "Button",
        "AXTextField" | "AXTextArea" | "AXSearchField" => "Edit",
        "AXStaticText" => "Text",
        "AXCheckBox" => "CheckBox",
        "AXRadioButton" => "RadioButton",
        "AXPopUpButton" | "AXComboBox" => "ComboBox",
        "AXMenuItem" | "AXMenuBarItem" => "MenuItem",
        "AXLink" => "Hyperlink",
        "AXImage" => "Image",
        "AXList" | "AXTable" | "AXOutline" => "List",
        "AXRow" | "AXCell" => "ListItem",
        "AXTabGroup" => "Tab",
        "AXSlider" => "Slider",
        "AXWindow" => "Window",
        "AXGroup" => "Group",
        _ => "Unknown",
    }
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

pub(super) fn click(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let point = resolve_point(state, window, params, "x", "y")?;
    reject_recent_user_intervention()?;
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

pub(super) fn scroll(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let point = resolve_point(state, window, params, "x", "y")?;
    reject_recent_user_intervention()?;
    set_focus(window)?;
    let delta_y = integer_param(params, "delta_y")? as i32;
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, point, CGMouseButton::Left)?;
    let event = CGEvent::new_scroll_event(source, ScrollEventUnit::PIXEL, 1, -delta_y, 0, 0)
        .map_err(|_| ("input_failed", "Could not create the scroll event.".to_string()))?;
    event.post(CGEventTapLocation::HID);
    Ok(json!({"applied": true}))
}

pub(super) fn drag(
    state: &ServerState,
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let start = resolve_point(state, window, params, "start_x", "start_y")?;
    let end = resolve_point(state, window, params, "end_x", "end_y")?;
    reject_recent_user_intervention()?;
    set_focus(window)?;
    let source = event_source()?;
    post_mouse(&source, CGEventType::MouseMoved, start, CGMouseButton::Left)?;
    post_mouse(&source, CGEventType::LeftMouseDown, start, CGMouseButton::Left)?;
    post_mouse(&source, CGEventType::LeftMouseDragged, end, CGMouseButton::Left)?;
    post_mouse(&source, CGEventType::LeftMouseUp, end, CGMouseButton::Left)?;
    Ok(json!({"applied": true}))
}

pub(super) fn type_text(
    window: &WindowInfo,
    params: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let text = params
        .get("text")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "text is required.".to_string()))?;
    reject_recent_user_intervention()?;
    set_focus(window)?;
    let source = event_source()?;
    let event = CGEvent::new_keyboard_event(source, 0, true)
        .map_err(|_| ("input_failed", "Could not create the keyboard event.".to_string()))?;
    event.set_string(text);
    event.post(CGEventTapLocation::HID);
    Ok(json!({"applied": true}))
}

pub(super) fn press_key(
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
    reject_recent_user_intervention()?;
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

pub(super) fn set_focus(window: &WindowInfo) -> Result<(), (&'static str, String)> {
    let pid = window_owner_pid(window.hwnd as i64).ok_or((
        "window_not_found",
        "Could not resolve the window's process.".to_string(),
    ))?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(2.0);
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

/// Ask a window to close by pressing its own close button.
///
/// This is a request, not a kill: the application runs its normal shutdown
/// path and may answer with a "save changes?" sheet instead of closing. A
/// window that is still present is therefore a legitimate outcome reported as
/// `closed: false`, never an error, and the process is never terminated.
pub(super) fn close_window(
    window: &WindowInfo,
) -> Result<Value, (&'static str, String)> {
    let pid = window_owner_pid(window.hwnd as i64).ok_or((
        "window_not_found",
        "Could not resolve the window's process.".to_string(),
    ))?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(2.0);
    let ax_window = find_ax_window(&app, window.hwnd as u32).ok_or((
        "window_not_found",
        "Accessibility could not locate the window.".to_string(),
    ))?;
    reject_recent_user_intervention()?;
    let close_button = ax_window
        .attribute(&AXAttribute::new(&CFString::from_static_string(
            "AXCloseButton",
        )))
        .map_err(|_| {
            (
                "unsupported_operation",
                "This window does not expose a close button.".to_string(),
            )
        })?;
    close_button
        .downcast_into::<AXUIElement>()
        .ok_or((
            "unsupported_operation",
            "This window does not expose a close button.".to_string(),
        ))?
        .perform_action(&CFString::from_static_string(kAXPressAction))
        .map_err(|error| {
            (
                "action_failed",
                format!("Accessibility close failed: {error:?}"),
            )
        })?;
    for _ in 0..CLOSE_POLL_ATTEMPTS {
        if window_owner_pid(window.hwnd as i64).is_none() {
            return Ok(json!({"closed": true}));
        }
        std::thread::sleep(std::time::Duration::from_millis(
            CLOSE_POLL_INTERVAL_MS,
        ));
    }
    Ok(json!({"closed": false}))
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

fn dict_f64(dict: &CFDictionary<CFString, CFType>, key: &str) -> Option<f64> {
    let key = CFString::new(key);
    let value = dict.find(&key)?;
    value.downcast::<CFNumber>().and_then(|number| number.to_f64())
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
        loop {
            let count =
                unsafe { libc::kevent(kq, std::ptr::null(), 0, &mut event, 1, std::ptr::null()) };
            if count < 0 {
                if std::io::Error::last_os_error().raw_os_error() == Some(libc::EINTR) {
                    continue;
                }
                break;
            }
            if count > 0 && (event.fflags & libc::NOTE_EXIT) != 0 {
                break;
            }
        }
        unsafe { libc::close(kq) };
        std::process::exit(0);
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bundle_executable_resolves_to_its_bundle() {
        let executable = Path::new("/Applications/Safari.app/Contents/MacOS/Safari");
        assert_eq!(
            bundle_root(executable),
            Some(PathBuf::from("/Applications/Safari.app"))
        );
    }

    #[test]
    fn a_nested_bundle_resolves_to_the_nearest_one() {
        // Instruments owns its windows, so it is its own application even
        // though it ships inside Xcode.
        let executable = Path::new(
            "/Applications/Xcode.app/Contents/Applications/Instruments.app\
             /Contents/MacOS/Instruments",
        );
        assert_eq!(
            bundle_root(executable),
            Some(PathBuf::from(
                "/Applications/Xcode.app/Contents/Applications/Instruments.app"
            ))
        );
    }

    #[test]
    fn a_bare_executable_belongs_to_no_bundle() {
        assert_eq!(bundle_root(Path::new("/usr/bin/vim")), None);
    }

    #[test]
    fn an_identifier_is_lowercased_under_the_app_prefix() {
        // A path that does not exist cannot be canonicalised, which is the
        // case that must still yield a usable identifier.
        assert_eq!(
            app_id_from_bundle_path(Path::new("/Applications/Safari.app")),
            "app:/applications/safari.app"
        );
    }

    #[test]
    fn an_unresolvable_process_falls_back_to_the_owner_name() {
        // pid 0 is never a real process, standing in for a protected one.
        assert_eq!(app_id_for_pid(0, "Some App"), "app:some app");
    }
}
