//! Sidecar process event handling and stderr capture.

use serde::Deserialize;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandEvent, TerminatedPayload};

use super::BackendState;

const MAX_CAPTURED_STDERR_CHARS: usize = 4000;
const STDERR_TRUNCATION_MARKER: &str = "\n[...stderr truncated...]\n";
const BACKEND_READY_PREFIX: &str = "QWENPAW_BACKEND_READY ";

#[derive(Deserialize)]
struct BackendReadyPayload {
    port: u16,
}

/// Watches sidecar output and reports failures for the current process generation.
pub(super) fn watch(
    app: tauri::AppHandle,
    generation: u64,
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
) {
    tauri::async_runtime::spawn(async move {
        let mut last_stderr = String::new();
        log::info!("[backend] watching process generation={generation}");
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line);
                    log::info!("[backend:{generation}] stdout: {}", text.trim_end());
                    if let Some(port) = ready_port_from_stdout(&text) {
                        log::info!("[backend:{generation}] ready port={port}");
                        app.state::<BackendState>()
                            .set_port_if_current(generation, port);
                    }
                }
                CommandEvent::Stderr(line) => {
                    record_stderr(generation, &mut last_stderr, &line);
                }
                CommandEvent::Error(message) => {
                    log::error!("[backend:{generation}] process event error: {message}");
                    app.state::<BackendState>().set_error_if_current(
                        generation,
                        format!("backend process error: {message}"),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let message = termination_message(payload, &last_stderr);
                    log::warn!("[backend:{generation}] {message}");
                    app.state::<BackendState>()
                        .set_error_if_current(generation, message);
                }
                _ => {}
            }
        }

        log::warn!("[backend:{generation}] process event stream closed");
        app.state::<BackendState>()
            .clear_child_if_current(generation);
    });
}

fn ready_port_from_stdout(text: &str) -> Option<u16> {
    text.lines().find_map(|line| {
        let payload = line.trim().strip_prefix(BACKEND_READY_PREFIX)?;
        serde_json::from_str::<BackendReadyPayload>(payload)
            .ok()
            .map(|ready| ready.port)
    })
}

fn record_stderr(generation: u64, buffer: &mut String, line: &[u8]) {
    let text = String::from_utf8_lossy(line).to_string();
    log::error!("[backend:{generation}] stderr: {text}");
    buffer.push_str(&text);
    trim_captured_stderr(buffer);
}

fn trim_captured_stderr(text: &mut String) {
    let total = text.chars().count();
    if total <= MAX_CAPTURED_STDERR_CHARS {
        return;
    }

    let marker_len = STDERR_TRUNCATION_MARKER.chars().count();
    let keep_chars = MAX_CAPTURED_STDERR_CHARS.saturating_sub(marker_len);
    let head_chars = keep_chars / 2;
    let tail_chars = keep_chars - head_chars;
    let head = first_chars(text, head_chars);
    let tail = last_chars(text, tail_chars);
    *text = format!("{head}{STDERR_TRUNCATION_MARKER}{tail}");
}

fn first_chars(text: &str, count: usize) -> String {
    text.chars().take(count).collect()
}

fn last_chars(text: &str, count: usize) -> String {
    let mut chars = text.chars().rev().take(count).collect::<Vec<_>>();
    chars.reverse();
    chars.into_iter().collect()
}

fn termination_message(payload: TerminatedPayload, last_stderr: &str) -> String {
    let mut message = match (payload.code, payload.signal) {
        (Some(code), _) => format!("backend process exited unexpectedly with code {code}"),
        (_, Some(signal)) => format!("backend process exited unexpectedly by signal {signal}"),
        _ => "backend process exited unexpectedly".to_string(),
    };

    let stderr = last_stderr.trim();
    if !stderr.is_empty() {
        message.push_str("\n\nLast stderr:\n");
        message.push_str(stderr);
    }

    message
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trim_captured_stderr_preserves_head_and_tail() {
        let mut text = format!("{}middle{}", "head".repeat(1200), "tail".repeat(1200));

        trim_captured_stderr(&mut text);

        assert!(text.chars().count() <= MAX_CAPTURED_STDERR_CHARS);
        assert!(text.starts_with("head"));
        assert!(text.contains(STDERR_TRUNCATION_MARKER));
        assert!(text.ends_with("tail"));
        assert!(!text.contains("middle"));
    }

    #[test]
    fn ready_port_from_stdout_parses_protocol_line() {
        let text = "INFO before\nQWENPAW_BACKEND_READY {\"port\":54321}\n";

        assert_eq!(ready_port_from_stdout(text), Some(54321));
    }

    #[test]
    fn ready_port_from_stdout_ignores_other_output() {
        assert_eq!(ready_port_from_stdout("QWENPAW_BACKEND_READY nope"), None);
        assert_eq!(ready_port_from_stdout("ordinary stdout"), None);
    }
}
