//! Hold update admission across the handoff from the app to NSIS.

use std::{
    os::windows::ffi::OsStrExt,
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread::{self, JoinHandle},
    time::Duration,
};

use serde::{Deserialize, Serialize};
use windows::{
    core::{s, w, BOOL, HRESULT, PCWSTR, PWSTR},
    Win32::{
        Foundation::{
            CloseHandle, FreeLibrary, ERROR_INVALID_PARAMETER, FILETIME, HANDLE, HWND, LPARAM,
            WAIT_TIMEOUT, WPARAM,
        },
        System::Diagnostics::ToolHelp::{
            CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
            TH32CS_SNAPPROCESS,
        },
        System::LibraryLoader::{GetProcAddress, LoadLibraryExW, LOAD_LIBRARY_SEARCH_SYSTEM32},
        System::Threading::{
            CreateProcessW, GetProcessTimes, OpenProcess, ResumeThread, TerminateProcess,
            WaitForSingleObject, CREATE_SUSPENDED, PROCESS_INFORMATION,
            PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, STARTUPINFOW,
        },
        UI::{
            Controls::{
                TASKDIALOGCONFIG, TASKDIALOGCONFIG_0, TASKDIALOG_BUTTON, TASKDIALOG_NOTIFICATIONS,
                TDF_ALLOW_DIALOG_CANCELLATION, TDF_CALLBACK_TIMER, TDM_CLICK_BUTTON, TDN_CREATED,
                TDN_TIMER, TD_INFORMATION_ICON,
            },
            WindowsAndMessaging::{
                EnumWindows, FlashWindowEx, GetForegroundWindow, GetLastActivePopup,
                GetWindowThreadProcessId, IsIconic, IsWindowVisible, PostMessageW,
                SetForegroundWindow, ShowWindowAsync, FLASHWINFO, FLASHW_TRAY, SW_RESTORE,
            },
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum InstallerFeedback {
    Unavailable,
    WindowUnfocused,
    Foregrounded,
    Finished,
}

pub(super) struct InstallerAttention {
    next_probe: Duration,
    feedback: InstallerFeedback,
    error_logged: bool,
    flash_requested: bool,
    notice_attempted: bool,
    notice: Option<UpdateNotice>,
}

impl Default for InstallerAttention {
    fn default() -> Self {
        Self {
            next_probe: Duration::from_secs(2),
            feedback: InstallerFeedback::Unavailable,
            error_logged: false,
            flash_requested: false,
            notice_attempted: false,
            notice: None,
        }
    }
}

impl InstallerAttention {
    pub(super) fn poll(&mut self, elapsed: Duration, directory: &Path) {
        let show_notice = self.poll_with(elapsed, |flash| {
            request_installer_attention(directory, flash)
        });
        if matches!(
            self.feedback,
            InstallerFeedback::Foregrounded | InstallerFeedback::Finished
        ) {
            self.close_notice();
        } else if show_notice {
            match UpdateNotice::start() {
                Ok(notice) => {
                    crate::startup_diagnostics::record("Update waiting notice", "requested");
                    self.notice = Some(notice);
                }
                Err(error) => crate::startup_diagnostics::record(
                    "Update waiting notice unavailable",
                    error.to_string(),
                ),
            }
        }
        if let Some(notice) = &mut self.notice {
            notice.log_if_shown();
        }
    }

    fn poll_with(
        &mut self,
        elapsed: Duration,
        mut request: impl FnMut(bool) -> Result<InstallerFeedback, String>,
    ) -> bool {
        if matches!(
            self.feedback,
            InstallerFeedback::Foregrounded | InstallerFeedback::Finished
        ) {
            return false;
        }
        if elapsed >= self.next_probe {
            // Keep retrying after missing windows or probe errors. A transient
            // failure must not be treated as completed user feedback.
            self.next_probe = elapsed + Duration::from_secs(1);
            match request(!self.flash_requested) {
                Ok(feedback) => {
                    self.feedback = feedback;
                    self.flash_requested |= feedback == InstallerFeedback::WindowUnfocused;
                }
                Err(error) => {
                    self.feedback = InstallerFeedback::Unavailable;
                    if !self.error_logged {
                        self.error_logged = true;
                        crate::startup_diagnostics::record(
                            "Installer attention unavailable",
                            error,
                        );
                    }
                }
            }
        }
        // This is a feedback delay, not an installation timeout. The caller
        // still checks the same live installer every 200 ms and never bypasses it.
        if elapsed >= Duration::from_secs(5)
            && !self.notice_attempted
            && matches!(
                self.feedback,
                InstallerFeedback::Unavailable | InstallerFeedback::WindowUnfocused
            )
        {
            self.notice_attempted = true;
            return true;
        }
        false
    }

    fn close_notice(&mut self) {
        if let Some(notice) = self.notice.take() {
            drop(notice);
        }
    }
}

#[derive(Default)]
struct NoticeState {
    cancelled: AtomicBool,
    shown: AtomicBool,
}

struct UpdateNotice {
    state: Arc<NoticeState>,
    worker: Option<JoinHandle<()>>,
    shown_logged: bool,
}

impl UpdateNotice {
    fn start() -> std::io::Result<Self> {
        let state = Arc::new(NoticeState::default());
        let worker_state = state.clone();
        let worker = thread::Builder::new()
            .name("update-wait-notice".into())
            .spawn(move || {
                if let Err(error) = show_waiting_notice(&worker_state) {
                    crate::startup_diagnostics::record("Update waiting notice unavailable", error);
                }
            })?;
        Ok(Self {
            state,
            worker: Some(worker),
            shown_logged: false,
        })
    }

    fn log_if_shown(&mut self) {
        if !self.shown_logged && self.state.shown.load(Ordering::Acquire) {
            self.shown_logged = true;
            crate::startup_diagnostics::record(
                "Update waiting notice shown",
                "Information only; update continues",
            );
        }
    }
}

impl Drop for UpdateNotice {
    fn drop(&mut self) {
        self.state.cancelled.store(true, Ordering::Release);
        // The UI timer closes the dialog without user interaction. Wait for
        // its thread to exit so no late dialog can appear over the main window.
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
        self.log_if_shown();
        if self.shown_logged {
            crate::startup_diagnostics::record(
                "Update waiting notice closed",
                "Installation guard unchanged",
            );
        }
    }
}

const CLOSE_NOTICE: i32 = 100;

fn show_waiting_notice(state: &NoticeState) -> Result<(), String> {
    if state.cancelled.load(Ordering::Acquire) {
        return Ok(());
    }
    let wide = |text: &str| text.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
    let title = wide("QwenPaw Desktop - Updating");
    let instruction = wide("QwenPaw is updating. Please wait.");
    let content = wide("It will open automatically when the update finishes.\n\nClosing this message does not cancel the update.");
    let button_text = wide("Close message");
    let button = TASKDIALOG_BUTTON {
        nButtonID: CLOSE_NOTICE,
        pszButtonText: PCWSTR(button_text.as_ptr()),
    };
    let config = TASKDIALOGCONFIG {
        cbSize: std::mem::size_of::<TASKDIALOGCONFIG>() as u32,
        dwFlags: TDF_CALLBACK_TIMER | TDF_ALLOW_DIALOG_CANCELLATION,
        pszWindowTitle: PCWSTR(title.as_ptr()),
        Anonymous1: TASKDIALOGCONFIG_0 {
            pszMainIcon: TD_INFORMATION_ICON,
        },
        pszMainInstruction: PCWSTR(instruction.as_ptr()),
        pszContent: PCWSTR(content.as_ptr()),
        cButtons: 1,
        pButtons: &button,
        nDefaultButton: CLOSE_NOTICE,
        pfCallback: Some(waiting_notice_callback),
        lpCallbackData: state as *const NoticeState as isize,
        ..Default::default()
    };
    // Only the UI thread blocks. TaskDialog supplies a callback timer and its
    // own HWND, avoiding global window searches or races with reused handles.
    // Resolve the v6-only function lazily. Test binaries have no Tauri v6
    // manifest; a static import would prevent even non-UI tests from loading.
    let library = unsafe { LoadLibraryExW(w!("comctl32.dll"), None, LOAD_LIBRARY_SEARCH_SYSTEM32) }
        .map_err(|e| e.to_string())?;
    let function = unsafe { GetProcAddress(library, s!("TaskDialogIndirect")) };
    let result = if let Some(function) = function {
        type TaskDialog = unsafe extern "system" fn(
            *const TASKDIALOGCONFIG,
            *mut i32,
            *mut i32,
            *mut BOOL,
        ) -> HRESULT;
        // GetProcAddress returned the documented TaskDialogIndirect export.
        let show: TaskDialog = unsafe { std::mem::transmute(function) };
        unsafe {
            show(
                &config,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        }
        .ok()
        .map_err(|e| e.to_string())
    } else {
        Err(format!(
            "TaskDialogIndirect is unavailable: {}",
            std::io::Error::last_os_error()
        ))
    };
    let _ = unsafe { FreeLibrary(library) };
    result
}

unsafe extern "system" fn waiting_notice_callback(
    window: HWND,
    notification: TASKDIALOG_NOTIFICATIONS,
    _wparam: WPARAM,
    _lparam: LPARAM,
    data: isize,
) -> HRESULT {
    // TaskDialogIndirect is synchronous; the state remains owned by the UI
    // thread until the final callback returns. Never unwind through this FFI.
    let state = unsafe { &*(data as *const NoticeState) };
    if notification == TDN_TIMER && unsafe { IsWindowVisible(window).as_bool() } {
        state.shown.store(true, Ordering::Release);
    }
    if (notification == TDN_CREATED || notification == TDN_TIMER)
        && state.cancelled.load(Ordering::Acquire)
    {
        let _ = unsafe {
            PostMessageW(
                Some(window),
                TDM_CLICK_BUTTON.0 as u32,
                WPARAM(CLOSE_NOTICE as usize),
                LPARAM(0),
            )
        };
    }
    HRESULT(0)
}

/// Request attention for the live installer, including its NSIS GUI child.
/// Only confirmed foreground activation completes the feedback request.
pub(super) fn request_installer_attention(
    directory: &Path,
    flash: bool,
) -> Result<InstallerFeedback, String> {
    let path = directory.join("installer");
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Ok(InstallerFeedback::Finished)
        }
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
        return Ok(InstallerFeedback::Finished);
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
        return Ok(InstallerFeedback::Unavailable);
    };
    // A window/process may disappear or be reused after enumeration.
    if !installer.running()? {
        return Ok(InstallerFeedback::Finished);
    }
    if !(Installer { pid, created }).running()? {
        return Ok(InstallerFeedback::Unavailable);
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
    if !foreground && flash {
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
            installer.pid,
            !foreground && flash
        ),
    );
    Ok(if foreground {
        InstallerFeedback::Foregrounded
    } else {
        InstallerFeedback::WindowUnfocused
    })
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
    fn attention_waits_two_seconds_and_does_not_repeat_after_foregrounding() {
        let mut attention = InstallerAttention::default();
        let mut calls = 0;
        for milliseconds in [0, 1999, 2000, 3000, 9000] {
            let notice = attention.poll_with(Duration::from_millis(milliseconds), |_| {
                calls += 1;
                Ok(InstallerFeedback::Foregrounded)
            });
            assert!(!notice);
            assert_eq!(calls, usize::from(milliseconds >= 2000));
        }
    }

    #[test]
    fn attention_retries_late_windows_at_most_once_per_second() {
        let mut attention = InstallerAttention::default();
        let mut calls = 0;
        for milliseconds in [2000, 2200, 2800, 3000] {
            assert!(
                !attention.poll_with(Duration::from_millis(milliseconds), |_| {
                    calls += 1;
                    Ok(if calls == 2 {
                        InstallerFeedback::Foregrounded
                    } else {
                        InstallerFeedback::Unavailable
                    })
                })
            );
        }
        assert_eq!(calls, 2);
        assert_eq!(attention.feedback, InstallerFeedback::Foregrounded);
    }

    #[test]
    fn missing_window_requests_one_notice_after_five_seconds_and_keeps_retrying() {
        let mut attention = InstallerAttention::default();
        let mut notices = 0;
        let mut probes = 0;
        for seconds in 0..20 {
            let notice = attention.poll_with(Duration::from_secs(seconds), |_| {
                probes += 1;
                Ok(InstallerFeedback::Unavailable)
            });
            assert_eq!(notice, seconds == 5);
            notices += usize::from(notice);
        }
        assert_eq!(notices, 1);
        assert_eq!(probes, 18);
        assert_ne!(attention.feedback, InstallerFeedback::Foregrounded);
    }

    #[test]
    fn probe_errors_request_a_notice_and_do_not_stop_later_probes() {
        let mut attention = InstallerAttention::default();
        let mut calls = 0;
        for seconds in [2, 3, 5, 10] {
            let notice = attention.poll_with(Duration::from_secs(seconds), |_| {
                calls += 1;
                Err("Cannot query windows".into())
            });
            assert_eq!(notice, seconds == 5);
        }
        assert_eq!(calls, 4);
        assert!(attention.error_logged);
        assert_ne!(attention.feedback, InstallerFeedback::Foregrounded);
    }

    #[test]
    fn transient_error_then_foreground_success_never_requests_notice() {
        let mut attention = InstallerAttention::default();
        assert!(!attention.poll_with(Duration::from_secs(2), |_| Err("Transient error".into())));
        assert!(!attention.poll_with(Duration::from_secs(3), |_| Ok(
            InstallerFeedback::Foregrounded
        )));
        assert!(!attention.poll_with(Duration::from_secs(10), |_| panic!("Unexpected retry")));
        assert!(!attention.notice_attempted);
    }

    #[test]
    fn flashing_is_not_foreground_success_and_is_requested_only_once() {
        let mut attention = InstallerAttention::default();
        let mut flash_requests = Vec::new();
        for seconds in [2, 3, 5, 6] {
            let notice = attention.poll_with(Duration::from_secs(seconds), |flash| {
                flash_requests.push(flash);
                Ok(InstallerFeedback::WindowUnfocused)
            });
            assert_eq!(notice, seconds == 5);
        }
        assert_eq!(flash_requests, [true, false, false, false]);
        assert_eq!(attention.feedback, InstallerFeedback::WindowUnfocused);
    }

    #[test]
    fn finished_installer_never_requests_a_late_notice() {
        let mut attention = InstallerAttention::default();
        assert!(!attention.poll_with(Duration::from_secs(4), |_| Ok(InstallerFeedback::Finished)));
        assert!(!attention.poll_with(Duration::from_secs(8), |_| panic!("Unexpected retry")));
        assert!(!attention.notice_attempted);
    }

    #[test]
    fn cancelled_notice_is_not_created_late() {
        let state = NoticeState::default();
        state.cancelled.store(true, Ordering::Release);
        assert!(show_waiting_notice(&state).is_ok());
        assert!(!state.shown.load(Ordering::Acquire));
    }

    #[test]
    fn notice_drop_cancels_and_joins_its_worker_without_user_interaction() {
        let state = Arc::new(NoticeState::default());
        let worker_state = state.clone();
        let worker = thread::spawn(move || {
            while !worker_state.cancelled.load(Ordering::Acquire) {
                thread::yield_now();
            }
        });
        drop(UpdateNotice {
            state: state.clone(),
            worker: Some(worker),
            shown_logged: false,
        });
        assert!(state.cancelled.load(Ordering::Acquire));
    }

    #[test]
    fn confirmed_installer_feedback_closes_an_active_notice() {
        let state = Arc::new(NoticeState::default());
        let worker_state = state.clone();
        let worker = thread::spawn(move || {
            while !worker_state.cancelled.load(Ordering::Acquire) {
                thread::yield_now();
            }
        });
        let mut attention = InstallerAttention {
            feedback: InstallerFeedback::Foregrounded,
            notice: Some(UpdateNotice {
                state: state.clone(),
                worker: Some(worker),
                shown_logged: false,
            }),
            ..Default::default()
        };
        let directory = crate::test_support::TestDirectory::new();
        attention.poll(Duration::from_secs(6), &directory.0);
        assert!(attention.notice.is_none());
        assert!(state.cancelled.load(Ordering::Acquire));
    }

    #[test]
    fn attention_ignores_missing_or_reused_installer_record() {
        let directory = crate::test_support::TestDirectory::new();
        assert_eq!(
            request_installer_attention(&directory.0, true).unwrap(),
            InstallerFeedback::Finished
        );
        std::fs::write(
            directory.child("installer"),
            serde_json::json!({"pid": std::process::id(), "created": 0}).to_string(),
        )
        .unwrap();
        assert_eq!(
            request_installer_attention(&directory.0, true).unwrap(),
            InstallerFeedback::Finished
        );
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
