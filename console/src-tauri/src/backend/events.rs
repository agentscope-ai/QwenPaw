//! Sidecar process event handling and stderr capture.

use tauri::Manager;
use tauri_plugin_shell::process::{CommandEvent, TerminatedPayload};

use super::BackendState;

const MAX_CAPTURED_STDERR_CHARS: usize = 4000;

/// Watches sidecar output and reports failures for the current process generation.
pub(super) fn watch(
    app: tauri::AppHandle,
    generation: u64,
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
) {
    tauri::async_runtime::spawn(async move {
        let mut last_stderr = String::new();
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::info!("[backend] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Stderr(line) => record_stderr(&mut last_stderr, &line),
                CommandEvent::Error(message) => {
                    log::error!("[backend] process event error: {message}");
                    app.state::<BackendState>().set_error_if_current(
                        generation,
                        format!("backend process error: {message}"),
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let message = termination_message(payload, &last_stderr);
                    log::warn!("[backend] {message}");
                    app.state::<BackendState>()
                        .set_error_if_current(generation, message);
                }
                _ => {}
            }
        }

        log::warn!("[backend] process exited");
        app.state::<BackendState>()
            .clear_child_if_current(generation);
    });
}

fn record_stderr(buffer: &mut String, line: &[u8]) {
    let text = String::from_utf8_lossy(line).to_string();
    log::error!("[backend] {text}");
    buffer.push_str(&text);
    trim_to_last_chars(buffer);
}

fn trim_to_last_chars(text: &mut String) {
    let total = text.chars().count();
    if total > MAX_CAPTURED_STDERR_CHARS {
        let drop_chars = total - MAX_CAPTURED_STDERR_CHARS;
        let byte_idx = text
            .char_indices()
            .nth(drop_chars)
            .map(|(idx, _)| idx)
            .unwrap_or(text.len());
        text.drain(..byte_idx);
    }
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
