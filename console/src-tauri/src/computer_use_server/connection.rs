//! Accepting a host connection and serving requests on it.
//!
//! The transport differs per platform -- a named pipe on Windows, a Unix domain
//! socket on macOS -- but what happens on an accepted connection does not: one
//! authentication handshake, then requests served in order against state that
//! belongs to that connection alone.
//!
//! Serving in order is deliberate. The helper synthesizes input into a shared
//! desktop, so two actions overlapping would race each other's focus and
//! cursor. Concurrency lives one level up instead: each connection gets its own
//! thread, so one session waiting on an approval never stalls another.

use std::io::{Read, Write};
use std::thread;

use super::dispatch::dispatch_request;
use super::framing::{read_message, request_id, write_error, write_result};
use super::state::ServerState;
use super::PROTOCOL_VERSION;

use serde_json::{json, Value};

// This line is consumed only by the desktop process that spawned the helper:
// stdout is a direct child-process pipe, not a user-visible protocol channel.
// Keep its prefix in step with `computer_use_runtime::HELPER_READY_PREFIX`.
const HELPER_READY_PREFIX: &str = "QWENPAW_COMPUTER_USE_READY ";

// Windows named-pipe server primitives. The macOS build listens on a Unix
// domain socket instead (see the platform_macos leaf and the cfg-split run).
#[cfg(windows)]
use std::fs::File;
#[cfg(windows)]
use std::os::windows::io::FromRawHandle;
#[cfg(windows)]
use windows::core::PCWSTR;
#[cfg(windows)]
use windows::Win32::Foundation::{GetLastError, ERROR_PIPE_CONNECTED, INVALID_HANDLE_VALUE};
#[cfg(windows)]
use windows::Win32::Storage::FileSystem::PIPE_ACCESS_DUPLEX;
#[cfg(windows)]
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};
#[cfg(windows)]
use windows::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, PIPE_READMODE_BYTE, PIPE_TYPE_BYTE,
    PIPE_UNLIMITED_INSTANCES, PIPE_WAIT,
};

#[cfg(windows)]
pub(crate) fn run(args: &[String]) -> Result<(), String> {
    let (pipe_name, capability) = parse_arguments(args)?;
    let result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
    if result.is_err() {
        return Err(format!("CoInitializeEx failed: {result}"));
    }
    let pipe_path = format!(r"\\.\pipe\{pipe_name}");
    let mut ready_sent = false;
    loop {
        let mut connection = accept_connection(&pipe_path, &mut ready_sent)?;
        let worker_capability = capability.clone();
        let worker = thread::Builder::new()
            .name("computer-use-conn".to_string())
            .spawn(move || {
                let com_result = unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) };
                if com_result.is_err() {
                    eprintln!("Computer Use worker CoInitializeEx failed: {com_result}");
                    return;
                }
                if let Err(error) = serve_connection(&mut connection, &worker_capability) {
                    eprintln!("Computer Use pipe connection ended: {error}");
                }
            });
        if let Err(error) = worker {
            eprintln!("Computer Use worker thread spawn failed: {error}");
        }
    }
}

#[cfg(target_os = "macos")]
pub(crate) fn run(args: &[String]) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixListener;
    let (socket_path, capability) = parse_arguments(args)?;
    // Fresh bind: clear any stale socket file left by a previous run.
    let _ = std::fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path)
        .map_err(|error| format!("failed to bind Computer Use socket: {error}"))?;
    std::fs::set_permissions(&socket_path, std::fs::Permissions::from_mode(0o600))
        .map_err(|error| format!("failed to secure Computer Use socket: {error}"))?;
    let pid_path = std::path::Path::new(&socket_path).with_extension("pid");
    std::fs::write(&pid_path, std::process::id().to_string())
        .map_err(|error| format!("failed to publish Computer Use helper pid: {error}"))?;
    std::fs::set_permissions(&pid_path, std::fs::Permissions::from_mode(0o600))
        .map_err(|error| format!("failed to secure Computer Use helper pid: {error}"))?;
    // macOS has no Job Object; exit when the desktop parent goes away so the
    // helper is reaped on host crash or force-quit.
    super::platform_macos::spawn_parent_death_watch();
    emit_ready()?;
    for stream in listener.incoming() {
        let mut connection = match stream {
            Ok(stream) => stream,
            Err(error) => {
                eprintln!("Computer Use socket accept failed: {error}");
                continue;
            }
        };
        let worker_capability = capability.clone();
        let worker = thread::Builder::new()
            .name("computer-use-conn".to_string())
            .spawn(move || {
                if let Err(error) = serve_connection(&mut connection, &worker_capability) {
                    eprintln!("Computer Use socket connection ended: {error}");
                }
            });
        if let Err(error) = worker {
            eprintln!("Computer Use worker thread spawn failed: {error}");
        }
    }
    Ok(())
}

fn parse_arguments(args: &[String]) -> Result<(String, String), String> {
    let mut pipe_name = None;
    let mut index = 0;
    while index < args.len() {
        let value = &args[index];
        index += 1;
        let target = match value.as_str() {
            "--pipe" => &mut pipe_name,
            _ => return Err(format!("unknown argument: {value}")),
        };
        let next = args
            .get(index)
            .ok_or_else(|| format!("{value} requires a value"))?;
        *target = Some(next.clone());
        index += 1;
    }
    let pipe_name = pipe_name.ok_or_else(|| "--pipe is required".to_string())?;
    // The capability secret arrives in the environment rather than on the
    // command line, so it is not exposed to other processes through argv. The
    // spawning side sets the matching variable in computer_use_runtime.
    let capability = std::env::var("QWENPAW_CU_CAPABILITY")
        .map_err(|_| "QWENPAW_CU_CAPABILITY is required".to_string())?;
    if pipe_name.is_empty() || capability.is_empty() {
        return Err("Computer Use pipe configuration is empty".to_string());
    }
    Ok((pipe_name, capability))
}

#[cfg(windows)]
fn accept_connection(pipe_path: &str, ready_sent: &mut bool) -> Result<File, String> {
    let wide = super::framing::wide_string(pipe_path);
    let handle = unsafe {
        CreateNamedPipeW(
            PCWSTR(wide.as_ptr()),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            64 * 1024,
            64 * 1024,
            0,
            None,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Err(format!(
            "CreateNamedPipeW failed: {}",
            unsafe { GetLastError() }.0
        ));
    }
    // A Windows named pipe becomes connectable as soon as CreateNamedPipeW
    // succeeds. Announce readiness before ConnectNamedPipe blocks waiting for
    // the first client, otherwise the host and client would wait on each
    // other.
    if !*ready_sent {
        emit_ready()?;
        *ready_sent = true;
    }
    if let Err(error) = unsafe { ConnectNamedPipe(handle, None) } {
        let expected = windows::core::HRESULT::from_win32(ERROR_PIPE_CONNECTED.0);
        if error.code() != expected {
            return Err(format!("ConnectNamedPipe failed: {error}"));
        }
    }
    Ok(unsafe { File::from_raw_handle(handle.0 as _) })
}

/// Announce that the platform endpoint has been created and is safe for the
/// desktop host to hand to the Python client. This is deliberately separate
/// from the request/response protocol: only the direct spawning parent reads
/// helper stdout.
fn emit_ready() -> Result<(), String> {
    let line = ready_line()?;
    let stdout = std::io::stdout();
    let mut stdout = stdout.lock();
    writeln!(stdout, "{line}")
        .and_then(|_| stdout.flush())
        .map_err(|error| format!("failed to announce Computer Use readiness: {error}"))
}

fn ready_line() -> Result<String, String> {
    let payload = serde_json::to_string(&json!({"protocol_version": PROTOCOL_VERSION}))
        .map_err(|error| format!("failed to encode Computer Use readiness: {error}"))?;
    Ok(format!("{HELPER_READY_PREFIX}{payload}"))
}

fn serve_connection(connection: &mut (impl Read + Write), capability: &str) -> Result<(), String> {
    let hello = read_message(connection)?;
    let hello_id = request_id(&hello)?;
    let secret = hello
        .get("params")
        .and_then(Value::as_object)
        .and_then(|params| params.get("capability"))
        .and_then(Value::as_str)
        .unwrap_or_default();
    if hello.get("method").and_then(Value::as_str) != Some("hello") || secret != capability {
        write_error(
            connection,
            &hello_id,
            "authentication_failed",
            "Invalid Computer Use capability.",
        )?;
        return Err("Computer Use capability authentication failed".to_string());
    }
    write_result(
        connection,
        &hello_id,
        json!({"protocol_version": PROTOCOL_VERSION}),
    )?;

    let mut state = ServerState::default();
    while let Ok(message) = read_message(connection) {
        let id = request_id(&message)?;
        let result = dispatch_request(connection, &mut state, &message);
        match result {
            Ok(value) => write_result(connection, &id, value)?,
            Err((code, message)) => write_error(connection, &id, code, &message)?,
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ready_line_carries_the_native_protocol_version() {
        let line = ready_line().expect("ready line should serialize");
        let payload = line
            .strip_prefix(HELPER_READY_PREFIX)
            .expect("ready prefix should be present");
        let value: Value = serde_json::from_str(payload).expect("payload should be JSON");

        assert_eq!(
            value.get("protocol_version").and_then(Value::as_u64),
            Some(PROTOCOL_VERSION),
        );
    }
}
