//! Discover one authenticated runtime per data directory and launch only if absent.

use std::{fs::File, path::PathBuf, process::Stdio, time::Duration};

use fs2::FileExt;
use serde::Deserialize;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

const TOKEN_HEADER: &str = "X-QwenPaw-Control-Token";

#[derive(Clone, Deserialize)]
pub(crate) struct Runtime {
    protocol: u32,
    instance: String,
    token: String,
    pub port: u16,
    mode: String,
    #[serde(skip)]
    client_id: String,
    #[serde(skip)]
    directory: PathBuf,
}

impl Runtime {
    pub async fn other_clients(&self) -> Result<usize, String> {
        #[derive(Deserialize)]
        struct Clients {
            other_clients: usize,
        }
        let clients = client()?
            .get(format!(
                "http://127.0.0.1:{}/api/runtime/clients",
                self.port
            ))
            .header(TOKEN_HEADER, &self.token)
            .header("X-QwenPaw-Client", &self.client_id)
            .timeout(Duration::from_secs(2))
            .send()
            .await
            .map_err(|err| err.to_string())?
            .error_for_status()
            .map_err(|err| err.to_string())?
            .json::<Clients>()
            .await
            .map_err(|err| err.to_string())?;
        Ok(clients.other_clients)
    }

    pub async fn stop(&self) -> Result<File, String> {
        let operation = lock_file(self.directory.join("launch.lock"))?;
        let deadline = std::time::Instant::now();
        while !try_lock(&operation)? {
            if deadline.elapsed() >= Duration::from_secs(5) {
                return Err("Runtime startup is in progress; try stopping again shortly".into());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        let response = client()?
            .post(format!(
                "http://127.0.0.1:{}/api/runtime/shutdown",
                self.port
            ))
            .header(TOKEN_HEADER, &self.token)
            .header("X-QwenPaw-Client", &self.client_id)
            .timeout(Duration::from_secs(3))
            .send()
            .await
            .map_err(|err| err.to_string())?;
        if response.status() == reqwest::StatusCode::CONFLICT {
            return Err(super::OTHER_CLIENTS_ERROR.into());
        }
        response.error_for_status().map_err(|err| err.to_string())?;
        let started = std::time::Instant::now();
        // A supervisor can have exited while Python is still alive. Both
        // leases must be released before replacing the bundled runtime files.
        for name in ["daemon.lock", "runtime.lock"] {
            let lock = lock_file(self.directory.join(name))?;
            while !try_lock(&lock)? {
                if started.elapsed() >= Duration::from_secs(60) {
                    return Err("Runtime did not finish shutting down within 60 seconds".into());
                }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }
        Ok(operation)
    }
}

pub(super) fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .no_proxy()
        .connect_timeout(Duration::from_secs(1))
        .build()
        .map_err(|err| err.to_string())
}

pub(crate) fn directory() -> Result<PathBuf, String> {
    let home = dirs::home_dir().ok_or("Home directory unavailable")?;
    let working = std::env::var("QWENPAW_WORKING_DIR")
        .or_else(|_| std::env::var("COPAW_WORKING_DIR"))
        .ok()
        .filter(|path| !path.is_empty())
        .map(|path| {
            if path == "~" {
                home.clone()
            } else if let Some(rest) = path.strip_prefix("~/") {
                home.join(rest)
            } else {
                PathBuf::from(path)
            }
        })
        .unwrap_or_else(|| {
            let legacy = home.join(".copaw");
            if legacy.exists() {
                legacy
            } else {
                home.join(".qwenpaw")
            }
        });
    std::fs::create_dir_all(&working).map_err(|err| err.to_string())?;
    let directory = working
        .canonicalize()
        .map_err(|err| err.to_string())?
        .join("runtime")
        .join("shared");
    std::fs::create_dir_all(&directory).map_err(|err| err.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
            .map_err(|err| err.to_string())?;
    }
    Ok(directory)
}

fn lock_file(path: PathBuf) -> Result<File, String> {
    File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .map_err(|err| err.to_string())
}

fn try_lock(file: &File) -> Result<bool, String> {
    match file.try_lock_exclusive() {
        Ok(()) => Ok(true),
        Err(err) if err.raw_os_error() == fs2::lock_contended_error().raw_os_error() => Ok(false),
        Err(err) => Err(err.to_string()),
    }
}

pub(super) async fn connect(
    app: &tauri::AppHandle,
) -> Result<(Runtime, reqwest::Response), String> {
    let directory = directory()?;
    let started = std::time::Instant::now();
    // Serializes discovery and startup across desktop processes. The backend
    // separately holds runtime.lock, even if its launching client crashes.
    let launch_lock = lock_file(directory.join("launch.lock"))?;
    while !try_lock(&launch_lock)? {
        if started.elapsed() >= Duration::from_secs(180) {
            return Err("Timed out waiting for runtime startup".into());
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    log::info!(
        "[backend] discovery admitted after {}ms",
        started.elapsed().as_millis()
    );
    crate::updates::coordination::ensure_available(app, &directory)?;
    let mut launched = false;
    let runtime_lock = lock_file(directory.join("daemon.lock"))?;
    if try_lock(&runtime_lock)? {
        FileExt::unlock(&runtime_lock).map_err(|err| err.to_string())?;
        let backend_lock = lock_file(directory.join("runtime.lock"))?;
        if try_lock(&backend_lock)? {
            FileExt::unlock(&backend_lock).map_err(|err| err.to_string())?;
            launch(app, &directory)?;
            launched = true;
        }
    }
    let environment: std::collections::HashMap<_, _> =
        crate::runtime_env::collect(app).into_iter().collect();
    let payload = serde_json::json!({
        "client": "desktop",
        "installation": crate::updates::coordination::installation(app)?,
        "control_port": environment.get("QWENPAW_COMPUTER_USE_CONTROL_PORT").and_then(|port| port.parse::<u16>().ok()),
        "control_token": environment.get("QWENPAW_COMPUTER_USE_CONTROL_TOKEN").cloned().unwrap_or_default(),
    });
    let client = client()?;
    loop {
        if crate::tray::is_quitting(app) {
            return Err("Desktop client is closing".into());
        }
        if started.elapsed() >= Duration::from_secs(180) {
            return Err(format!(
                "Runtime did not become ready; see {}",
                directory.join("launcher.log").display()
            ));
        }
        if let Ok(bytes) = std::fs::read(directory.join("runtime.json")) {
            if let Ok(mut runtime) = serde_json::from_slice::<Runtime>(&bytes) {
                if runtime.protocol != 1 || runtime.mode != "shared" {
                    return Err("The existing runtime cannot accept shared clients".into());
                }
                let request = client
                    .post(format!(
                        "http://127.0.0.1:{}/api/runtime/connect",
                        runtime.port
                    ))
                    .header(TOKEN_HEADER, &runtime.token)
                    .json(&payload);
                if let Ok(Ok(response)) =
                    tokio::time::timeout(Duration::from_secs(2), request.send()).await
                {
                    if response.status().is_success()
                        && response
                            .headers()
                            .get("X-QwenPaw-Instance")
                            .and_then(|value| value.to_str().ok())
                            == Some(runtime.instance.as_str())
                    {
                        runtime.client_id = response
                            .headers()
                            .get("X-QwenPaw-Client")
                            .and_then(|value| value.to_str().ok())
                            .ok_or("Missing desktop client identity")?
                            .to_owned();
                        runtime.directory = directory.clone();
                        log::info!(
                            "[backend] shared runtime connected after {}ms (launched={launched})",
                            started.elapsed().as_millis()
                        );
                        return Ok((runtime, response));
                    }
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

fn launch(app: &tauri::AppHandle, directory: &std::path::Path) -> Result<(), String> {
    let backend = super::command::create(app)?;
    let mut command =
        std::process::Command::new(std::env::current_exe().map_err(|err| err.to_string())?);
    command
        .arg("--agent-host")
        .arg(backend.get_program())
        .args(backend.get_args());
    if let Some(directory) = backend.get_current_dir() {
        command.current_dir(directory);
    }
    for (key, value) in backend.get_envs() {
        if let Some(value) = value {
            command.env(key, value);
        } else {
            command.env_remove(key);
        }
    }
    command.env("QWENPAW_DESKTOP_DAEMON_DIR", directory);
    command.env(
        "QWENPAW_DESKTOP_INSTALLATION_DIR",
        crate::updates::coordination::installation(app)?,
    );
    let log = File::options()
        .create(true)
        .append(true)
        .open(directory.join("launcher.log"))
        .map_err(|err| err.to_string())?;
    command
        .env(
            "QWENPAW_WORKING_DIR",
            directory
                .parent()
                .and_then(|path| path.parent())
                .ok_or("Missing data directory")?,
        )
        .env("QWENPAW_DESKTOP_APP", "1")
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONFAULTHANDLER", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::from(log.try_clone().map_err(|err| err.to_string())?))
        .stderr(Stdio::from(log));
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
    }
    #[cfg(windows)]
    {
        // Detached console and breakaway prevent the launching shell's job or
        // console teardown from terminating a runtime used by other clients.
        command.creation_flags(0x00000008 | 0x00000200 | 0x01000000);
    }
    let child = command.spawn();
    #[cfg(windows)]
    let child = child.or_else(|error| {
        if error.raw_os_error() != Some(5) {
            return Err(error);
        }
        // Some launchers forbid job breakaway. The daemon can still outlive
        // its window, but remains subject to that launcher's job lifetime.
        log::warn!("[backend] detached launch denied; retrying without job breakaway");
        command.creation_flags(0x00000008 | 0x00000200).spawn()
    });
    let mut child = child.map_err(|err| format!("Cannot launch shared runtime: {err}"))?;
    log::info!("[backend] launched shared runtime pid={}", child.id());
    std::thread::spawn(move || {
        if let Err(err) = child.wait() {
            log::warn!("[backend] could not reap runtime launcher: {err}");
        }
    });
    Ok(())
}

impl Runtime {
    pub(crate) fn read(directory: &std::path::Path) -> Result<Option<Self>, String> {
        if try_lock(&lock_file(directory.join("daemon.lock"))?)?
            && try_lock(&lock_file(directory.join("runtime.lock"))?)?
        {
            return Ok(None);
        }
        let bytes = std::fs::read(directory.join("runtime.json")).map_err(|e| e.to_string())?;
        let mut runtime: Self = serde_json::from_slice(&bytes).map_err(|e| e.to_string())?;
        if runtime.mode != "shared" || runtime.protocol != 1 {
            return Err("The existing runtime cannot coordinate an update".into());
        }
        runtime.directory = directory.to_path_buf();
        Ok(Some(runtime))
    }

    pub(crate) fn uses_directory(&self, directory: &std::path::Path) -> bool {
        self.directory == directory
    }

    pub(crate) async fn check_update_clients(&self, installation: &str) -> Result<(), String> {
        #[derive(Deserialize)]
        struct Client {
            client: String,
            installation: String,
        }
        #[derive(Deserialize)]
        struct Clients {
            clients: Vec<Client>,
        }
        let clients: Clients = client()?
            .get(format!(
                "http://127.0.0.1:{}/api/runtime/clients",
                self.port
            ))
            .header(TOKEN_HEADER, &self.token)
            .header("X-QwenPaw-Client", &self.client_id)
            .timeout(Duration::from_secs(3))
            .send()
            .await
            .map_err(|e| e.to_string())?
            .error_for_status()
            .map_err(|e| e.to_string())?
            .json()
            .await
            .map_err(|e| e.to_string())?;
        if clients
            .clients
            .iter()
            .any(|c| c.client != "desktop" || c.installation != installation)
        {
            return Err(
                "QwenPaw is connected to another app. Disconnect it before updating.".into(),
            );
        }
        Ok(())
    }

    #[cfg(windows)]
    pub(crate) fn mark_update(&self, installation: &std::path::Path) -> Result<(), String> {
        std::fs::write(
            self.directory.join("update-installation"),
            installation.to_string_lossy().as_bytes(),
        )
        .map_err(|e| e.to_string())
    }
}
