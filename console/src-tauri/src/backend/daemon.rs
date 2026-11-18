//! Lightweight native supervisor; desktop windows are clients, never owners.

use fs2::FileExt;
use std::{
    fs::File,
    path::PathBuf,
    process::{Command, Stdio},
    time::{Duration, Instant},
};

pub(crate) fn run() -> Result<(), String> {
    let directory = PathBuf::from(
        std::env::var_os("QWENPAW_DESKTOP_DAEMON_DIR").ok_or("Missing daemon directory")?,
    );
    let mut arguments = std::env::args_os().skip(2);
    let program = arguments.next().ok_or("Missing backend executable")?;
    let arguments: Vec<_> = arguments.collect();
    let lock = File::options()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(directory.join("daemon.lock"))
        .map_err(|err| err.to_string())?;
    match lock.try_lock_exclusive() {
        Ok(()) => {}
        Err(err) if err.raw_os_error() == fs2::lock_contended_error().raw_os_error() => {
            return Ok(())
        }
        Err(err) => return Err(err.to_string()),
    }
    let stop_request = directory.join("stop-request");
    if stop_request.exists() {
        std::fs::remove_file(&stop_request).map_err(|err| err.to_string())?;
    }
    let installation = PathBuf::from(
        std::env::var_os("QWENPAW_DESKTOP_INSTALLATION_DIR")
            .ok_or("Missing desktop installation directory")?,
    );
    let _registration =
        crate::updates::coordination::register(&installation, directory.clone(), true)?;
    let mut failures = 0u32;
    loop {
        while crate::updates::coordination::maintenance(&installation)? {
            if stop_request.exists() {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let started = Instant::now();
        let mut command = Command::new(&program);
        command.args(&arguments).stdin(Stdio::null());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000 | 0x00000200);
        }
        let mut child = command.spawn().map_err(|err| err.to_string())?;
        let status = child.wait().map_err(|err| err.to_string())?;
        if stop_request.exists() {
            return Ok(());
        }
        // Do not turn a broken installation into an endless restart loop.
        failures = if started.elapsed() >= Duration::from_secs(60) {
            1
        } else {
            failures + 1
        };
        if failures >= 5 {
            return Err(format!(
                "Backend repeatedly exited ({status}); automatic restart stopped"
            ));
        }
        eprintln!("[agent-host] backend exited ({status}); restarting, attempt {failures}");
        std::thread::sleep(Duration::from_secs(1 << (failures - 1)));
        if stop_request.exists() {
            return Ok(());
        }
    }
}
