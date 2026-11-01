//! Hold update admission across the handoff from the app to NSIS.

use std::{os::windows::ffi::OsStrExt, path::Path};

use serde::{Deserialize, Serialize};
use windows::{
    core::{PCWSTR, PWSTR},
    Win32::{
        Foundation::{CloseHandle, ERROR_INVALID_PARAMETER, FILETIME, HANDLE, WAIT_TIMEOUT},
        System::Threading::{
            CreateProcessW, GetProcessTimes, OpenProcess, ResumeThread, TerminateProcess,
            WaitForSingleObject, CREATE_SUSPENDED, PROCESS_INFORMATION,
            PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, STARTUPINFOW,
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
            Err(e) => return Err(e.to_string()),
        };
        let result = creation_time(process).map(|created| {
            created == self.created && unsafe { WaitForSingleObject(process, 0) } == WAIT_TIMEOUT
        });
        let _ = unsafe { CloseHandle(process) };
        result
    }
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
