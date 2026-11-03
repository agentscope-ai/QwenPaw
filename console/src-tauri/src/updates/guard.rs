use std::fs::File;

use fs2::FileExt;
use tauri::{AppHandle, Manager};

/// All desktop processes share the cache, including separate app copies.
/// Keep this OS lease across download, confirmation, and installation.
pub(super) struct InFlightGuard {
    _lease: File,
}

pub(super) fn begin_update(app: &AppHandle) -> Result<InFlightGuard, String> {
    let directory = app.path().app_local_data_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let lease = super::coordination::open_lock(&directory.join("update.lock"))?;
    lease
        .try_lock_exclusive()
        .map_err(|_| "Another QwenPaw window is already updating. Please wait.".to_string())?;
    super::coordination::check_installers(&directory)?;
    Ok(InFlightGuard { _lease: lease })
}
