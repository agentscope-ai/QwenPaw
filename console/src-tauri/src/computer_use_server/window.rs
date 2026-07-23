//! Window/app enumeration, resolution, and identity.

use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::PathBuf;
use windows::core::{BOOL, PWSTR};
use windows::Win32::Foundation::{CloseHandle, HWND, LPARAM};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::WindowsAndMessaging::{
    EnumWindows, GetClassNameW, GetWindowTextW, GetWindowThreadProcessId,
    IsWindow, IsWindowVisible,
};

use super::WindowInfo;

pub(super) fn list_windows() -> Vec<Value> {
    enumerate_windows()
        .into_iter()
        .map(|window| window.to_json())
        .collect()
}

pub(super) fn list_apps() -> Vec<Value> {
    let mut apps = HashMap::<String, (WindowInfo, Vec<Value>)>::new();
    for window in enumerate_windows() {
        let entry = apps
            .entry(window.app_id.clone())
            .or_insert_with(|| (window.clone(), Vec::new()));
        entry.1.push(window.to_json());
    }
    apps.into_values()
        .map(|(window, windows)| {
            json!({
                "id": window.app_id,
                "display_name": window.display_name,
                "is_running": true,
                "windows": windows,
            })
        })
        .collect()
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

pub(super) fn resolve_window(value: &str) -> Result<WindowInfo, (&'static str, String)> {
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
        app_id: format!("process:{}", process_path.to_ascii_lowercase()),
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

pub(super) fn is_forbidden(window: &WindowInfo) -> bool {
    let class_name = window.class_name.to_ascii_lowercase();
    let title = window.title.to_ascii_lowercase();
    class_name.contains("credential")
        || title.contains("windows security")
        || title.contains("credential")
        || title.contains("qwenpaw")
}
