use serde::Serialize;
use tauri::{AppHandle, Emitter};

pub(super) fn emit<S: Serialize>(app: &AppHandle, name: &str, payload: &S) {
    if let Err(err) = app.emit(name, payload) {
        log::warn!("[updates] failed to emit {name}: {err}");
    }
}

pub(super) fn emit_error(app: &AppHandle, stage: &'static str, err: &dyn std::fmt::Display) {
    emit_error_kind(app, stage, "other", &err.to_string());
}

/// Emit an update error whose `kind` is derived from the concrete
/// `tauri-plugin-updater` error variant rather than fragile string matching on
/// the (library-/locale-dependent) message text.
pub(super) fn emit_updater_error(
    app: &AppHandle,
    stage: &'static str,
    err: &tauri_plugin_updater::Error,
) {
    emit_error_kind(app, stage, classify_updater_error(err), &err.to_string());
}

fn emit_error_kind(app: &AppHandle, stage: &'static str, kind: &'static str, message: &str) {
    log::warn!("[updates] error stage={stage} kind={kind} message={message}");
    let _ = app.emit(
        "update:error",
        serde_json::json!({
            "stage": stage,
            "kind": kind,
            "message": message,
        }),
    );
}

fn classify_updater_error(err: &tauri_plugin_updater::Error) -> &'static str {
    use tauri_plugin_updater::Error as E;
    match err {
        E::Reqwest(_)
        | E::Network(_)
        | E::Http(_)
        | E::ReleaseNotFound
        | E::EmptyEndpoints
        | E::InsecureTransportProtocol
        | E::UrlParse(_) => "network",
        E::Minisign(_) | E::SignatureUtf8(_) | E::Base64(_) => "signature",
        _ if cfg!(target_os = "macos") && is_read_only_filesystem_error(err) => "appLocation",
        _ => "other",
    }
}

fn is_read_only_filesystem_error(err: &tauri_plugin_updater::Error) -> bool {
    let message = err.to_string();
    message.contains("read-only file system") || message.contains("os error: 30")
}
