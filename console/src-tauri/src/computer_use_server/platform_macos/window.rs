//! Window and application discovery, identity, and closing on macOS.
//!
//! Mirrors the Windows `window.rs` leaf: everything here answers "what windows
//! and applications exist, which one is this, and may we touch it".

use accessibility::{AXAttribute, AXUIElement};
use accessibility_sys::kAXPressAction;
use core_foundation::base::{CFType, TCFType};
use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
use core_foundation::string::CFString;
use core_graphics::window::{
    copy_window_info, kCGNullWindowID, kCGWindowLayer, kCGWindowListExcludeDesktopElements,
    kCGWindowListOptionAll, kCGWindowName, kCGWindowNumber, kCGWindowOwnerName, kCGWindowOwnerPID,
};
use objc2_app_kit::NSWorkspace;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use super::super::state::{merge_app_list, InstalledApp, WindowInfo};
use super::accessibility_tree::{find_ax_window, focused_window_id};
use super::{dict_i64, dict_string};

/// Directories a macOS application bundle is normally installed into.
///
/// Only one level is scanned, plus the Utilities folders Apple ships, because
/// a full recursive walk would pick up the many nested helper bundles inside
/// each application.
const APP_SEARCH_DIRS: [&str; 5] = [
    "/Applications",
    "/Applications/Utilities",
    "/System/Applications",
    "/System/Applications/Utilities",
    "/System/Library/CoreServices",
];

// A close request is asynchronous: wait briefly for the window to go away
// before reporting that it is still open (usually a save prompt).
const CLOSE_POLL_ATTEMPTS: u32 = 40;
const CLOSE_POLL_INTERVAL_MS: u64 = 50;

pub(crate) fn list_windows(app: Option<&str>) -> Vec<Value> {
    enumerate_windows()
        .into_iter()
        .filter(|window| app.is_none_or(|value| window.matches_app(value)))
        .map(|window| window.to_json())
        .collect()
}

pub(crate) fn list_apps() -> Vec<Value> {
    merge_app_list(installed_apps(), enumerate_windows())
}

/// The focused window of the application macOS currently considers frontmost.
pub(crate) fn active_window() -> Option<WindowInfo> {
    let pid = NSWorkspace::sharedWorkspace()
        .frontmostApplication()?
        .processIdentifier();
    let windows = enumerate_windows();
    let focused = focused_window_id(&AXUIElement::application(pid));
    focused
        .and_then(|id| {
            windows
                .iter()
                .find(|window| window.hwnd == id as isize)
                .cloned()
        })
        .or_else(|| windows.into_iter().find(|window| window.owner_pid == pid))
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

pub(crate) fn resolve_window(value: &str) -> Result<WindowInfo, (&'static str, String)> {
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

pub(crate) fn is_forbidden(window: &WindowInfo) -> bool {
    let title = window.title.to_ascii_lowercase();
    let name = window.display_name.to_ascii_lowercase();
    // The self-ban keeps the agent off QwenPaw's own windows -- above all the
    // approval prompt, which it must never answer for itself. It is matched on
    // the owner name, not the title: the title comes from kCGWindowName, which
    // is empty without Screen Recording permission, and a ban that vanished
    // when a permission was withheld would be no ban at all. The owner name
    // (kCGWindowOwnerName) is always present.
    title.contains("password")
        || title.contains("credential")
        || title.contains("keychain")
        || name.contains("qwenpaw")
        || name.contains("keychain access")
}

/// Enumerate normal-layer application windows across Spaces via CoreGraphics.
/// Titles require Screen Recording permission; without it the window still
/// lists but its title may be empty.
fn enumerate_windows() -> Vec<WindowInfo> {
    let option = kCGWindowListOptionAll | kCGWindowListExcludeDesktopElements;
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
            owner_pid: pid as i32,
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
        // A name, not a path: it is flattened because different APIs may report
        // it with different casing, and it is never used as a launch target --
        // an application identified this way cannot be started by id.
        .unwrap_or_else(|| format!("app:{}", owner.to_lowercase()))
}

/// Canonical identifier for an application bundle or executable path.
///
/// Both discovery routes -- scanning the install directories and reading a
/// running process -- pass through here, and both resolve symlinks first, so
/// one application cannot end up with two identifiers and be approved twice.
///
/// The path keeps the casing the filesystem stores. `launch_app` accepts an
/// identifier from `list_apps` and uses it as a path, so flattening the case
/// here -- as this once did -- made every identifier unlaunchable on a
/// case-sensitive APFS volume.
pub(crate) fn app_id_from_bundle_path(path: &Path) -> String {
    let resolved = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    format!("app:{}", resolved.to_string_lossy())
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

/// Ask a window to close by pressing its own close button.
///
/// This is a request, not a kill: the application runs its normal shutdown
/// path and may answer with a "save changes?" sheet instead of closing. A
/// window that is still present is therefore a legitimate outcome reported as
/// `closed: false`, never an error, and the process is never terminated.
pub(crate) fn close_window(window: &WindowInfo) -> Result<Value, (&'static str, String)> {
    let pid = (window.owner_pid > 0).then_some(window.owner_pid).ok_or((
        "window_not_found",
        "Could not resolve the window's process.".to_string(),
    ))?;
    let app = AXUIElement::application(pid);
    let _ = app.set_messaging_timeout(super::AX_MESSAGING_TIMEOUT_SECONDS);
    let ax_window = find_ax_window(&app, window.hwnd as u32).ok_or((
        "window_not_found",
        "Accessibility could not locate the window.".to_string(),
    ))?;
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
        if resolve_window(&window.hwnd.to_string()).is_err() {
            return Ok(json!({"closed": true}));
        }
        std::thread::sleep(std::time::Duration::from_millis(CLOSE_POLL_INTERVAL_MS));
    }
    Ok(json!({"closed": false}))
}
