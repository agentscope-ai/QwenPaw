//! Window/app enumeration, resolution, and identity.

use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;
use windows::core::{BOOL, PWSTR};
use windows::Win32::Foundation::{CloseHandle, HWND, LPARAM, RECT, WPARAM};
use windows::Win32::Graphics::Dwm::{DwmGetWindowAttribute, DWMWA_EXTENDED_FRAME_BOUNDS};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetAncestor, GetClassNameW, GetForegroundWindow, GetWindowLongPtrW, GetWindowRect,
    GetWindowTextW, GetWindowThreadProcessId, IsWindow, IsWindowVisible, PostMessageW, GA_ROOT,
    GA_ROOTOWNER, GWL_STYLE, WM_CLOSE, WS_POPUP,
};

use super::super::app_identity::app_id_from_path;
use super::super::state::merge_app_list;
use super::super::state::WindowInfo;

// A close request is asynchronous: wait briefly for the window to go away
// before reporting that it is still open (usually a save prompt).
const CLOSE_POLL_ATTEMPTS: u32 = 40;
const CLOSE_POLL_INTERVAL_MS: u64 = 50;
const MAX_RELATED_WINDOWS: usize = 3;

/// Visible top-level surfaces that belong to one stable target window.
/// Related windows are ordered back to front for monotonically increasing
/// screenshot z-index values; `input_hwnd` identifies the frontmost surface.
pub(super) struct ObservationWindows {
    pub(super) input_hwnd: isize,
    pub(super) related: Vec<isize>,
}

pub(super) fn observation_windows(window: &WindowInfo) -> ObservationWindows {
    let target = HWND(window.hwnd as _);
    let target_thread = unsafe { GetWindowThreadProcessId(target, None) };
    struct EnumData {
        target: HWND,
        target_thread: u32,
        related: Vec<isize>,
    }

    unsafe extern "system" fn callback(hwnd: HWND, data: LPARAM) -> BOOL {
        let data = unsafe { &mut *(data.0 as *mut EnumData) };
        if hwnd == data.target {
            return BOOL(0);
        }
        if data.related.len() >= MAX_RELATED_WINDOWS {
            return BOOL(0);
        }
        if unsafe { IsWindowVisible(hwnd).as_bool() }
            && matches_target_window_with_thread(data.target, hwnd, data.target_thread)
            && get_visible_window_rect(hwnd).is_ok()
        {
            data.related.push(hwnd.0 as isize);
        }
        BOOL(1)
    }

    let mut data = EnumData {
        target,
        target_thread,
        related: Vec::new(),
    };
    unsafe {
        let _ = EnumWindows(Some(callback), LPARAM(&mut data as *mut EnumData as isize));
    }
    let input_hwnd = data.related.first().copied().unwrap_or(window.hwnd);
    data.related.reverse();
    ObservationWindows {
        input_hwnd,
        related: data.related,
    }
}

/// Accept the selected window, its children/owned windows, and visible popup
/// surfaces created by the same UI thread. The latter covers native menus and
/// drop-downs that intentionally have no owner HWND.
pub(super) fn matches_target_window(target: HWND, candidate: HWND) -> bool {
    let target_thread = unsafe { GetWindowThreadProcessId(target, None) };
    matches_target_window_with_thread(target, candidate, target_thread)
}

/// Return whether `candidate` is the surface itself or one of its child HWNDs.
/// Coordinate input is bound to a captured surface, not merely to any popup
/// created by the same application thread.
pub(super) fn matches_observed_surface(surface: HWND, candidate: HWND) -> bool {
    !candidate.0.is_null() && unsafe { GetAncestor(candidate, GA_ROOT) == surface }
}

fn matches_target_window_with_thread(target: HWND, candidate: HWND, target_thread: u32) -> bool {
    if candidate.0.is_null() {
        return false;
    }
    unsafe {
        let candidate_root = GetAncestor(candidate, GA_ROOT);
        window_relation_matches(
            target,
            candidate_root,
            GetAncestor(target, GA_ROOTOWNER),
            GetAncestor(candidate, GA_ROOTOWNER),
        ) || same_thread_popup(candidate_root, target_thread)
    }
}

fn same_thread_popup(candidate: HWND, target_thread: u32) -> bool {
    popup_relation_matches(
        target_thread,
        unsafe { GetWindowThreadProcessId(candidate, None) },
        unsafe { GetWindowLongPtrW(candidate, GWL_STYLE) } as u32,
    )
}

fn popup_relation_matches(target_thread: u32, candidate_thread: u32, style: u32) -> bool {
    target_thread != 0 && candidate_thread == target_thread && style & WS_POPUP.0 != 0
}

pub(super) fn window_relation_matches(
    target: HWND,
    candidate_root: HWND,
    target_root_owner: HWND,
    candidate_root_owner: HWND,
) -> bool {
    candidate_root == target || (target_root_owner == target && candidate_root_owner == target)
}

pub(crate) fn list_windows(app: Option<&str>) -> Vec<Value> {
    enumerate_windows()
        .into_iter()
        .filter(|window| app.is_none_or(|value| window.matches_app(value)))
        .map(|window| window.to_json())
        .collect()
}

pub(crate) fn list_apps() -> Vec<Value> {
    // Windows discovery is limited to applications that own a window, so no
    // installed-only entries are contributed here.
    merge_app_list(Vec::new(), enumerate_windows())
}

pub(crate) fn active_window() -> Option<WindowInfo> {
    window_info(unsafe { GetForegroundWindow() })
}

fn enumerate_windows() -> Vec<WindowInfo> {
    let mut windows = Vec::new();
    unsafe extern "system" fn callback(hwnd: HWND, data: LPARAM) -> BOOL {
        let windows = unsafe { &mut *(data.0 as *mut Vec<WindowInfo>) };
        if let Some(window) = window_info(hwnd) {
            windows.push(window);
        }
        BOOL(1)
    }
    unsafe {
        let pointer = &mut windows as *mut Vec<WindowInfo> as isize;
        let _ = EnumWindows(Some(callback), LPARAM(pointer));
    }
    windows
}

pub(crate) fn resolve_window(value: &str) -> Result<WindowInfo, (&'static str, String)> {
    let hwnd = value
        .parse::<isize>()
        .map_err(|_| ("invalid_request", "window_id is invalid.".to_string()))?;
    window_info(HWND(hwnd as _)).ok_or((
        "window_not_found",
        "Target window was not found.".to_string(),
    ))
}

fn window_info(hwnd: HWND) -> Option<WindowInfo> {
    if !unsafe { IsWindow(Some(hwnd)).as_bool() } || !unsafe { IsWindowVisible(hwnd).as_bool() } {
        return None;
    }
    let mut title = [0_u16; 512];
    let length = unsafe { GetWindowTextW(hwnd, &mut title) };
    if length == 0 {
        return None;
    }
    let mut class_name = [0_u16; 256];
    let class_length = unsafe { GetClassNameW(hwnd, &mut class_name) };
    let mut pid = 0_u32;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
    let process_path = process_image_path(pid)?;
    let display_name = String::from_utf16_lossy(&title[..length as usize]);
    Some(WindowInfo {
        hwnd: hwnd.0 as isize,
        app_id: app_id_from_path(Path::new(&process_path)),
        display_name: PathBuf::from(&process_path)
            .file_stem()
            .and_then(|value| value.to_str())
            .unwrap_or(&display_name)
            .to_string(),
        title: display_name,
        class_name: String::from_utf16_lossy(&class_name[..class_length as usize]),
    })
}

fn process_image_path(pid: u32) -> Option<String> {
    let process = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()? };
    let mut buffer = vec![0_u16; 32_768];
    let mut length = buffer.len() as u32;
    let result = unsafe {
        QueryFullProcessImageNameW(
            process,
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &mut length,
        )
    };
    let _ = unsafe { CloseHandle(process) };
    result.ok()?;
    Some(String::from_utf16_lossy(&buffer[..length as usize]))
}

pub(crate) fn is_forbidden(window: &WindowInfo) -> bool {
    let class_name = window.class_name.to_ascii_lowercase();
    let title = window.title.to_ascii_lowercase();
    // Matched on the owning process name, not only the title: the self-ban must
    // hold even for a window whose title is empty or unexpected, so that the
    // agent can never drive QwenPaw's own UI -- the approval prompt above all.
    // The process image name is always available.
    let name = window.display_name.to_ascii_lowercase();
    class_name.contains("credential")
        || title.contains("windows security")
        || title.contains("credential")
        || name.contains("qwenpaw")
}

/// Ask a window to close the same way its own title-bar button would.
///
/// `WM_CLOSE` is a request, not a kill: the application runs its normal
/// shutdown path and may answer with a "save changes?" prompt instead of
/// exiting. A still-open window is therefore a legitimate outcome rather than
/// a failure, so the caller reports `closed: false` and lets the model observe
/// whatever dialog appeared. The process is never terminated.
pub(crate) fn close_window(window: &WindowInfo) -> Result<Value, (&'static str, String)> {
    let hwnd = HWND(window.hwnd as _);
    if !unsafe { IsWindow(Some(hwnd)).as_bool() } {
        return Err((
            "window_not_found",
            "Target window no longer exists.".to_string(),
        ));
    }
    unsafe { PostMessageW(Some(hwnd), WM_CLOSE, WPARAM(0), LPARAM(0)) }
        .map_err(|error| ("input_failed", error.to_string()))?;
    for _ in 0..CLOSE_POLL_ATTEMPTS {
        if !unsafe { IsWindow(Some(hwnd)).as_bool() } {
            return Ok(json!({"closed": true}));
        }
        thread::sleep(Duration::from_millis(CLOSE_POLL_INTERVAL_MS));
    }
    Ok(json!({"closed": false}))
}

/// The window rectangle as the user sees it.
///
/// The extended frame bounds exclude the invisible resize border Windows
/// reports through GetWindowRect, so a coordinate mapped against this lands
/// where the pixels are.
pub(super) fn get_visible_window_rect(hwnd: HWND) -> Result<RECT, String> {
    let mut rect = RECT::default();
    let dwm_result = unsafe {
        DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            &mut rect as *mut RECT as *mut _,
            std::mem::size_of::<RECT>() as u32,
        )
    };
    if dwm_result.is_ok() && rect.right > rect.left && rect.bottom > rect.top {
        return Ok(rect);
    }

    unsafe {
        GetWindowRect(hwnd, &mut rect).map_err(|err| format!("GetWindowRect failed: {err}"))?;
    }
    if rect.right <= rect.left || rect.bottom <= rect.top {
        return Err("window rect has zero area".to_string());
    }
    Ok(rect)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::computer_use_server::state::WindowInfo;

    fn window(title: &str, display_name: &str, class_name: &str) -> WindowInfo {
        WindowInfo {
            hwnd: 1,
            app_id: String::new(),
            display_name: display_name.to_string(),
            title: title.to_string(),
            class_name: class_name.to_string(),
        }
    }

    #[test]
    fn a_qwenpaw_window_is_forbidden_even_with_an_empty_title() {
        // The self-ban must not hinge on the title: it can be absent, and a ban
        // that lapsed when the title was empty would let the agent reach
        // QwenPaw's own approval prompt.
        let win = window("", "qwenpaw-desktop", "Chrome_WidgetWin_1");
        assert!(is_forbidden(&win));
    }

    #[test]
    fn credential_dialogs_stay_forbidden() {
        assert!(is_forbidden(&window(
            "Windows Security",
            "svc",
            "Credential"
        )));
        assert!(is_forbidden(&window("Sign in", "svc", "CredentialDialog")));
    }

    #[test]
    fn an_ordinary_window_is_allowed() {
        assert!(!is_forbidden(&window(
            "Untitled - Notepad",
            "notepad",
            "Notepad"
        )));
    }

    #[test]
    fn only_same_thread_popup_styles_extend_the_target_surface() {
        assert!(popup_relation_matches(7, 7, WS_POPUP.0));
        assert!(!popup_relation_matches(7, 8, WS_POPUP.0));
        assert!(!popup_relation_matches(7, 7, 0));
        assert!(!popup_relation_matches(0, 0, WS_POPUP.0));
    }
}
