//! Hold update admission across the handoff from the app to NSIS.

use std::{os::windows::ffi::OsStrExt, path::Path, time::Duration};

use serde::{Deserialize, Serialize};
use windows::{
    core::{PCWSTR, PWSTR},
    Win32::{
        Foundation::{
            CloseHandle, ERROR_INVALID_PARAMETER, FILETIME, HANDLE, HWND, LPARAM, WAIT_TIMEOUT,
        },
        System::Diagnostics::ToolHelp::{
            CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
            TH32CS_SNAPPROCESS,
        },
        System::Threading::{
            CreateProcessW, GetProcessTimes, OpenProcess, ResumeThread, TerminateProcess,
            WaitForSingleObject, CREATE_SUSPENDED, PROCESS_INFORMATION,
            PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, STARTUPINFOW,
        },
        UI::WindowsAndMessaging::{
            EnumWindows, FlashWindowEx, GetForegroundWindow, GetLastActivePopup,
            GetWindowThreadProcessId, IsIconic, IsWindowVisible, SetForegroundWindow,
            ShowWindowAsync, FLASHWINFO, FLASHW_TRAY, SW_RESTORE,
        },
    },
};

#[derive(Deserialize, Serialize)]
pub(super) struct Installer {
    pid: u32,
    created: u64,
}

fn creation_time(process: HANDLE) -> Result<u64, String> {
    let mut created = FILETIME::default();
    let mut exited = FILETIME::default();
    let mut kernel = FILETIME::default();
    let mut user = FILETIME::default();
    unsafe { GetProcessTimes(process, &mut created, &mut exited, &mut kernel, &mut user) }
        .map_err(|e| e.to_string())?;
    Ok((u64::from(created.dwHighDateTime) << 32) | u64::from(created.dwLowDateTime))
}

impl Installer {
    pub(super) fn running(&self) -> Result<bool, String> {
        let process = match unsafe {
            OpenProcess(
                PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                false,
                self.pid,
            )
        } {
            Ok(process) => process,
            Err(e) if e.code() == ERROR_INVALID_PARAMETER.to_hresult() => return Ok(false),
            Err(e) => {
                return Err(format!(
                    "Cannot query installer process PID {}: {e}",
                    self.pid
                ))
            }
        };
        let result = creation_time(process)
            .map_err(|e| {
                format!(
                    "Cannot read installer creation time for PID {}: {e}",
                    self.pid
                )
            })
            .map(|created| {
                created == self.created
                    && unsafe { WaitForSingleObject(process, 0) } == WAIT_TIMEOUT
            });
        let _ = unsafe { CloseHandle(process) };
        result
    }
}

pub(super) struct InstallerAttention {
    next_probe: Duration,
    requested: bool,
}

impl Default for InstallerAttention {
    fn default() -> Self {
        Self {
            next_probe: Duration::from_secs(2),
            requested: false,
        }
    }
}

impl InstallerAttention {
    pub(super) fn poll(&mut self, elapsed: Duration, directory: &Path) {
        self.poll_with(elapsed, || request_installer_attention(directory));
    }

    fn poll_with(&mut self, elapsed: Duration, mut request: impl FnMut() -> Result<bool, String>) {
        if self.requested || elapsed < self.next_probe {
            return;
        }
        // Avoid interrupting NSIS's brief /R handoff. If no window exists yet,
        // retry once per second rather than enumerate processes every 200 ms.
        self.next_probe = elapsed + Duration::from_secs(1);
        match request() {
            Ok(requested) => self.requested = requested,
            Err(error) => {
                // Feedback failure must not replace an installation error or
                // change the wait condition. Log it once and keep waiting.
                self.requested = true;
                crate::startup_diagnostics::record("Installer attention unavailable", error);
            }
        }
    }
}

/// Request attention for the live installer, including its NSIS GUI child.
/// Return false when its window is not ready; the caller can retry later.
pub(super) fn request_installer_attention(directory: &Path) -> Result<bool, String> {
    let path = directory.join("installer");
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(e) => {
            return Err(format!(
                "Cannot read installer record {}: {e}",
                path.display()
            ))
        }
    };
    let installer: Installer = serde_json::from_slice(&bytes)
        .map_err(|e| format!("Cannot parse installer record {}: {e}", path.display()))?;
    if !installer.running()? {
        return Ok(false);
    }
    let processes = installer_processes(&installer)?;
    let mut search = InstallerWindows {
        processes,
        found: None,
    };
    unsafe {
        EnumWindows(
            Some(find_installer_window),
            LPARAM(&mut search as *mut _ as isize),
        )
        .map_err(|e| e.to_string())?;
    }
    let Some((window, pid, created)) = search.found else {
        return Ok(false);
    };
    // A window/process may disappear or be reused after enumeration.
    if !installer.running()? || !(Installer { pid, created }).running()? {
        return Ok(false);
    }
    let popup = unsafe { GetLastActivePopup(window) };
    let mut popup_pid = 0;
    unsafe { GetWindowThreadProcessId(popup, Some(&mut popup_pid)) };
    let window = if popup_pid == pid && unsafe { IsWindowVisible(popup).as_bool() } {
        popup
    } else {
        window
    };
    unsafe {
        if IsIconic(window).as_bool() {
            // Do not block our startup thread on another process's UI thread.
            let _ = ShowWindowAsync(window, SW_RESTORE);
        }
        let _ = SetForegroundWindow(window);
    }
    let foreground = unsafe { GetForegroundWindow() } == window;
    if !foreground {
        // FlashWindowEx returns the previous active state, not success. Only
        // report that flashing was requested; never claim focus was granted.
        let flash = FLASHWINFO {
            cbSize: std::mem::size_of::<FLASHWINFO>() as u32,
            hwnd: window,
            dwFlags: FLASHW_TRAY,
            uCount: 3,
            dwTimeout: 0,
        };
        let _ = unsafe { FlashWindowEx(&flash) };
    }
    crate::startup_diagnostics::record(
        "Installer attention",
        format!(
            "installer_pid={} window_pid={pid} foreground={foreground} flash_requested={}",
            installer.pid, !foreground
        ),
    );
    Ok(true)
}

struct InstallerWindows {
    processes: Vec<Installer>,
    found: Option<(HWND, u32, u64)>,
}

unsafe extern "system" fn find_installer_window(window: HWND, data: LPARAM) -> windows::core::BOOL {
    let search = unsafe { &mut *(data.0 as *mut InstallerWindows) };
    if search.found.is_none() && unsafe { IsWindowVisible(window).as_bool() } {
        let mut pid = 0;
        unsafe { GetWindowThreadProcessId(window, Some(&mut pid)) };
        if let Some(process) = search.processes.iter().find(|p| p.pid == pid) {
            search.found = Some((window, pid, process.created));
        }
    }
    true.into()
}

fn installer_processes(installer: &Installer) -> Result<Vec<Installer>, String> {
    let snapshot =
        unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) }.map_err(|e| e.to_string())?;
    let mut entries = Vec::new();
    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    if unsafe { Process32FirstW(snapshot, &mut entry) }.is_ok() {
        loop {
            entries.push((entry.th32ProcessID, entry.th32ParentProcessID));
            if unsafe { Process32NextW(snapshot, &mut entry) }.is_err() {
                break;
            }
        }
    }
    let _ = unsafe { CloseHandle(snapshot) };
    let mut processes = vec![Installer {
        pid: installer.pid,
        created: installer.created,
    }];
    let mut index = 0;
    while index < processes.len() {
        let parent = &processes[index];
        let (parent_pid, parent_created) = (parent.pid, parent.created);
        for &(pid, parent) in &entries {
            if parent != parent_pid || processes.iter().any(|p| p.pid == pid) {
                continue;
            }
            if let Ok(handle) =
                unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) }
            {
                let created = creation_time(handle);
                let _ = unsafe { CloseHandle(handle) };
                if let Ok(created) = created {
                    // A recycled parent PID must not make an unrelated window
                    // look like the installer. Real children start afterwards.
                    if created >= parent_created {
                        processes.push(Installer { pid, created });
                    }
                }
            }
        }
        index += 1;
    }
    Ok(processes)
}

pub(super) fn launch_installer(
    path: &Path,
    installation: &super::coordination::Installation,
) -> Result<(), String> {
    let executable: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let mut command: Vec<u16> = format!("\"{}\" /P /R /UPDATE /NO_QWENPAW_PATH", path.display())
        .encode_utf16()
        .chain(Some(0))
        .collect();
    let startup = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        ..Default::default()
    };
    let mut process = PROCESS_INFORMATION::default();
    // Publish the installer identity before it can replace files. Do not
    // inherit the desktop's lock handles or leave an orphaned suspended child.
    unsafe {
        CreateProcessW(
            PCWSTR(executable.as_ptr()),
            Some(PWSTR(command.as_mut_ptr())),
            None,
            None,
            false,
            CREATE_SUSPENDED,
            None,
            PCWSTR::null(),
            &startup,
            &mut process,
        )
    }
    .map_err(|e| e.to_string())?;
    let result = (|| {
        let installer = Installer {
            pid: process.dwProcessId,
            created: creation_time(process.hProcess)?,
        };
        installation.handoff(&installer)?;
        if unsafe { ResumeThread(process.hThread) } == u32::MAX {
            return Err(std::io::Error::last_os_error().to_string());
        }
        Ok(())
    })();
    if result.is_err() {
        let _ = unsafe { TerminateProcess(process.hProcess, 1) };
        let _ = unsafe { WaitForSingleObject(process.hProcess, 5000) };
    }
    let _ = unsafe { CloseHandle(process.hThread) };
    let _ = unsafe { CloseHandle(process.hProcess) };
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::System::Threading::GetCurrentProcess;

    #[test]
    fn attention_waits_two_seconds_and_is_requested_only_once() {
        let mut attention = InstallerAttention::default();
        let mut calls = 0;
        for milliseconds in [0, 1999, 2000, 3000, 9000] {
            attention.poll_with(Duration::from_millis(milliseconds), || {
                calls += 1;
                Ok(true)
            });
            assert_eq!(calls, usize::from(milliseconds >= 2000));
        }
    }

    #[test]
    fn attention_retries_late_windows_at_most_once_per_second() {
        let mut attention = InstallerAttention::default();
        let mut calls = 0;
        for milliseconds in [2000, 2200, 2800, 3000] {
            attention.poll_with(Duration::from_millis(milliseconds), || {
                calls += 1;
                Ok(calls == 2)
            });
        }
        assert_eq!(calls, 2);
        assert!(attention.requested);
    }

    #[test]
    fn attention_error_does_not_repeat_or_escape_the_wait() {
        let mut attention = InstallerAttention::default();
        attention.poll_with(
            Duration::from_secs(2),
            || Err("Cannot query windows".into()),
        );
        attention.poll_with(Duration::from_secs(10), || panic!("Unexpected retry"));
        assert!(attention.requested);
    }

    #[test]
    fn attention_ignores_missing_or_reused_installer_record() {
        let directory = crate::test_support::TestDirectory::new();
        assert!(!request_installer_attention(&directory.0).unwrap());
        std::fs::write(
            directory.child("installer"),
            serde_json::json!({"pid": std::process::id(), "created": 0}).to_string(),
        )
        .unwrap();
        assert!(!request_installer_attention(&directory.0).unwrap());
    }

    #[test]
    fn matching_live_process_keeps_installation_guard_active() {
        let installer = Installer {
            pid: std::process::id(),
            created: creation_time(unsafe { GetCurrentProcess() }).unwrap(),
        };
        assert!(installer.running().unwrap());
    }

    #[test]
    fn mismatched_creation_time_does_not_keep_installation_guard_active() {
        let installer = Installer {
            pid: std::process::id(),
            created: 0,
        };
        assert!(!installer.running().unwrap());
    }
}
