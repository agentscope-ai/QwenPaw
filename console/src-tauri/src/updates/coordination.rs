//! Coordinate installation across native clients, including disconnected windows.

use std::{
    collections::BTreeSet,
    fs::File,
    path::{Path, PathBuf},
    sync::Mutex,
    time::{Duration, Instant},
};

use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri::{Emitter, Manager};

use crate::backend::{self, runtime::Runtime};

pub(crate) const UPDATING: &str = "QwenPaw is updating. Please wait until the update finishes.";

pub(crate) fn installation(app: &tauri::AppHandle) -> Result<String, String> {
    Ok(installation_directory(&app.config().identifier)?
        .to_string_lossy()
        .into_owned())
}

fn installation_directory(identifier: &str) -> Result<PathBuf, String> {
    let exe = std::env::current_exe()
        .and_then(|path| path.canonicalize())
        .map_err(|e| e.to_string())?;
    let identity = format!("{:x}", Sha256::digest(exe.to_string_lossy().as_bytes()));
    let path = dirs::data_local_dir()
        .ok_or("App data directory unavailable")?
        .join(identifier)
        .join("installations")
        .join(identity);
    std::fs::create_dir_all(&path).map_err(|e| e.to_string())?;
    Ok(path)
}

/// Register before AppKit/WebView construction, which can itself wait on OS UI.
pub(crate) fn register_desktop(identifier: &str) -> Result<Option<Registration>, String> {
    let directory = installation_directory(identifier)?;
    // NSIS can launch the new executable just before its own process exits.
    // No runtime or Computer Use process is started during this handoff.
    while installer_running(&directory)? {
        std::thread::sleep(Duration::from_millis(200));
    }
    match register(&directory, backend::runtime::directory()?, false) {
        Ok(registration) => Ok(Some(registration)),
        Err(error) if error == UPDATING => Ok(None),
        Err(error) => Err(error),
    }
}

pub(super) fn open_lock(path: &Path) -> Result<File, String> {
    File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .map_err(|e| e.to_string())
}

fn exclusive(file: &File) -> Result<bool, String> {
    match file.try_lock_exclusive() {
        Ok(()) => Ok(true),
        Err(e) if e.raw_os_error() == fs2::lock_contended_error().raw_os_error() => Ok(false),
        Err(e) => Err(e.to_string()),
    }
}

fn busy(path: &Path) -> Result<bool, String> {
    // Readers must not exclude new registrations or other status probes.
    match FileExt::try_lock_shared(&open_lock(path)?) {
        Ok(()) => Ok(false),
        Err(e) if e.raw_os_error() == fs2::lock_contended_error().raw_os_error() => Ok(true),
        Err(e) => Err(e.to_string()),
    }
}

#[derive(Deserialize, Serialize)]
struct Member {
    pid: u32,
    runtime: PathBuf,
    daemon: bool,
}

/// The OS releases this lease on crashes; PID files alone cannot establish life.
pub(crate) struct Registration {
    _lease: File,
}

pub(crate) fn register(
    directory: &Path,
    runtime: PathBuf,
    daemon: bool,
) -> Result<Registration, String> {
    let admission = open_lock(&directory.join("admission.lock"))?;
    admission
        .try_lock_shared()
        .map_err(|_| UPDATING.to_string())?;
    if installer_running(directory)? {
        return Err(UPDATING.into());
    }
    let members = directory.join("members");
    std::fs::create_dir_all(&members).map_err(|e| e.to_string())?;
    let path = members.join(format!("{}.lock", uuid::Uuid::new_v4()));
    let lease = open_lock(&path)?;
    lease.lock_exclusive().map_err(|e| e.to_string())?;
    let member = Member {
        pid: std::process::id(),
        runtime,
        daemon,
    };
    // Windows byte-range locks also prohibit reads through another handle.
    // Keep readable metadata separate from the process-lifetime lease.
    std::fs::write(
        path.with_extension("json"),
        serde_json::to_vec(&member).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok(Registration { _lease: lease })
}

fn members(directory: &Path) -> Result<Vec<Member>, String> {
    let mut members = Vec::new();
    for entry in std::fs::read_dir(directory.join("members")).map_err(|e| e.to_string())? {
        let path = entry.map_err(|e| e.to_string())?.path();
        if path.extension().and_then(|ext| ext.to_str()) != Some("lock") {
            continue;
        }
        let lease = open_lock(&path)?;
        if exclusive(&lease)? {
            drop(lease);
            let _ = std::fs::remove_file(path.with_extension("json"));
            let _ = std::fs::remove_file(path);
        } else {
            let bytes = std::fs::read(path.with_extension("json")).map_err(|e| e.to_string())?;
            members.push(serde_json::from_slice(&bytes).map_err(|e| e.to_string())?);
        }
    }
    Ok(members)
}

pub(crate) fn ensure_available(app: &tauri::AppHandle, runtime: &Path) -> Result<(), String> {
    let directory = PathBuf::from(installation(app)?);
    if busy(&directory.join("admission.lock"))? || installer_running(&directory)? {
        return Err(UPDATING.into());
    }
    // A runtime may be reused by another installation. Its install handoff
    // must also prevent that client from starting the old bundled Python.
    if let Ok(owner) = std::fs::read_to_string(runtime.join("update-installation")) {
        let owner = PathBuf::from(owner);
        if busy(&owner.join("admission.lock"))? || installer_running(&owner)? {
            return Err(UPDATING.into());
        }
    }
    Ok(())
}

pub(crate) fn setup(app: &tauri::AppHandle) -> Result<(), String> {
    let directory = PathBuf::from(installation(app)?);
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_millis(250)).await;
            let closing = std::fs::read_to_string(directory.join("closing"))
                .ok()
                .and_then(|s| s.parse::<u32>().ok());
            if closing.is_some_and(|pid| pid != std::process::id())
                && busy(&directory.join("admission.lock")).unwrap_or(false)
            {
                crate::tray::exit_app(&handle, 0);
                return;
            }
        }
    });
    Ok(())
}

#[derive(Default)]
pub(crate) struct Confirmation(Mutex<Option<(String, tokio::sync::oneshot::Sender<bool>)>>);

#[tauri::command]
pub(crate) fn confirm_desktop_update(app: tauri::AppHandle, request_id: String, confirmed: bool) {
    let state = app.state::<Confirmation>();
    let mut pending = state.0.lock().expect("update confirmation poisoned");
    if pending.as_ref().is_some_and(|(id, _)| id == &request_id) {
        if let Some((_, sender)) = pending.take() {
            let _ = sender.send(confirmed);
        }
    }
}

pub(super) struct Installation {
    directory: PathBuf,
    _admission: File,
    runtime_locks: Vec<File>,
    runtimes: Vec<Runtime>,
}

impl Drop for Installation {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(self.directory.join("closing"));
    }
}

impl Installation {
    pub(super) async fn prepare(app: &tauri::AppHandle) -> Result<Option<Self>, String> {
        let directory = PathBuf::from(installation(app)?);
        // begin_update holds the shared cache lease, so no other update can
        // own this request. Remove a crash remainder before locking admission.
        let _ = std::fs::remove_file(directory.join("closing"));
        let admission = open_lock(&directory.join("admission.lock"))?;
        // Registration and status probes hold short shared leases. Wait for
        // those readers instead of mistaking them for another updater.
        let deadline = Instant::now() + Duration::from_secs(5);
        while !exclusive(&admission)? {
            if Instant::now() >= deadline {
                return Err(UPDATING.into());
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        if installer_running(&directory)? {
            return Err(UPDATING.into());
        }
        let peers = members(&directory)?;
        let paths: BTreeSet<_> = peers.iter().map(|m| m.runtime.clone()).collect();
        let mut session = Self {
            directory,
            _admission: admission,
            runtime_locks: Vec::new(),
            runtimes: Vec::new(),
        };
        for path in paths {
            if let Some(runtime) = backend::runtime_for_update(app, &path)? {
                runtime.check_update_clients(&installation(app)?).await?;
                session.runtimes.push(runtime);
            }
        }
        let count = peers
            .iter()
            .filter(|m| !m.daemon && m.pid != std::process::id())
            .count();
        let id = uuid::Uuid::new_v4().to_string();
        let (sender, receiver) = tokio::sync::oneshot::channel();
        *app.state::<Confirmation>()
            .0
            .lock()
            .expect("update confirmation poisoned") = Some((id.clone(), sender));
        app.emit(
            "update:confirmation",
            serde_json::json!({"requestId": id, "otherWindows": count}),
        )
        .map_err(|e| e.to_string())?;
        let answer = tokio::time::timeout(Duration::from_secs(300), receiver).await;
        app.state::<Confirmation>()
            .0
            .lock()
            .expect("update confirmation poisoned")
            .take();
        if !matches!(answer, Ok(Ok(true))) {
            return Ok(None);
        }
        // Recheck external clients after the user responds and before closing
        // any window. Shutdown also checks again atomically on the server.
        for runtime in &session.runtimes {
            runtime.check_update_clients(&installation(app)?).await?;
        }
        std::fs::write(
            session.directory.join("closing"),
            std::process::id().to_string(),
        )
        .map_err(|e| e.to_string())?;
        session.wait_for_peers(false).await?;
        backend::suspend_for_update(app);
        for runtime in &session.runtimes {
            session.runtime_locks.push(runtime.stop().await?);
        }
        session.wait_for_peers(true).await?;
        let handle = app.clone();
        tauri::async_runtime::spawn_blocking(move || crate::computer_use_runtime::stop(&handle))
            .await
            .map_err(|e| e.to_string())??;
        Ok(Some(session))
    }

    async fn wait_for_peers(&self, include_daemons: bool) -> Result<(), String> {
        let start = Instant::now();
        loop {
            if members(&self.directory)?
                .iter()
                .all(|m| m.pid == std::process::id() || (!include_daemons && m.daemon))
            {
                return Ok(());
            }
            if start.elapsed() > Duration::from_secs(15) {
                return Err(
                    "Some QwenPaw windows could not close. Close them and try updating again."
                        .into(),
                );
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    #[cfg(windows)]
    pub(super) fn handoff(&self, installer: &super::windows::Installer) -> Result<(), String> {
        for runtime in &self.runtimes {
            runtime.mark_update(&self.directory)?;
        }
        let bytes = serde_json::to_vec(installer).map_err(|e| e.to_string())?;
        std::fs::write(self.directory.join("installer"), bytes).map_err(|e| e.to_string())
    }
}

fn installer_running(directory: &Path) -> Result<bool, String> {
    #[cfg(windows)]
    {
        let path = directory.join("installer");
        let bytes = match std::fs::read(&path) {
            Ok(bytes) => bytes,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(e) => return Err(e.to_string()),
        };
        let installer: super::windows::Installer =
            serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        if installer.running()? {
            return Ok(true);
        }
        let _ = std::fs::remove_file(path);
    }
    #[cfg(not(windows))]
    let _ = directory;
    Ok(false)
}

pub(crate) fn maintenance(directory: &Path) -> Result<bool, String> {
    busy(&directory.join("admission.lock"))
}

pub(super) fn check_installers(app_data: &Path) -> Result<(), String> {
    let directories = match std::fs::read_dir(app_data.join("installations")) {
        Ok(directories) => directories,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(e) => return Err(e.to_string()),
    };
    for entry in directories {
        if installer_running(&entry.map_err(|e| e.to_string())?.path())? {
            return Err(UPDATING.into());
        }
    }
    Ok(())
}
