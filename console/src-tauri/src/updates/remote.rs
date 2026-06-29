use std::time::{Duration, Instant};

use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

use crate::backend;

use super::events::{emit, emit_error, emit_updater_error};

/// Shared prologue for both update flows: announce the check, find an
/// installable update and download (and signature-verify) it. Errors are
/// emitted to the frontend; `None` means the caller should stop.
pub(super) async fn check_and_download(
    app: &AppHandle,
) -> Option<(tauri_plugin_updater::Update, Vec<u8>)> {
    emit(app, "update:check-start", &serde_json::json!({}));

    let update = match check_installable_update(app).await {
        Ok(Some(update)) => update,
        Ok(None) => {
            emit_error(app, "check", &"no desktop update available");
            return None;
        }
        Err(err) => {
            emit_updater_error(app, "check", &err);
            return None;
        }
    };

    log::info!(
        "[updates] downloading desktop update version={}",
        update.version
    );
    match download_update(app, &update).await {
        Ok(bytes) => Some((update, bytes)),
        Err(err) => {
            emit_updater_error(app, "download", &err);
            None
        }
    }
}

pub(super) async fn check_installable_update(
    app: &AppHandle,
) -> Result<Option<tauri_plugin_updater::Update>, tauri_plugin_updater::Error> {
    let updater = app
        .updater_builder()
        .on_before_exit({
            let app = app.clone();
            move || {
                backend::stop(&app);
                app.cleanup_before_exit();
            }
        })
        .build()?;

    updater.check().await
}

async fn download_update(
    app: &AppHandle,
    update: &tauri_plugin_updater::Update,
) -> Result<Vec<u8>, tauri_plugin_updater::Error> {
    let mut last_emit: Option<Instant> = None;
    let mut downloaded: u64 = 0;

    let bytes = update
        .download(
            |chunk_len, content_len| {
                downloaded = downloaded.saturating_add(chunk_len as u64);
                let should_emit = last_emit
                    .map(|t| t.elapsed() >= Duration::from_millis(200))
                    .unwrap_or(true);
                if should_emit {
                    emit(
                        app,
                        "update:download-progress",
                        &serde_json::json!({
                            "downloaded": downloaded,
                            "total": content_len,
                        }),
                    );
                    last_emit = Some(Instant::now());
                }
            },
            || {
                log::info!("[updates] desktop update download complete");
            },
        )
        .await?;

    // Final progress frame (forces UI to land on 100%).
    emit(
        app,
        "update:download-progress",
        &serde_json::json!({
            "downloaded": downloaded,
            "total": Some(downloaded),
        }),
    );

    Ok(bytes)
}
