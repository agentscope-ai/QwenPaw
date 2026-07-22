//! Tauri commands for desktop auto-updates via tauri-plugin-updater.

mod cache;
mod events;
mod guard;
mod remote;
mod signature;
mod version;

use serde::Serialize;
use tauri::AppHandle;

use crate::backend;

use cache::{
    cached_artifact_path, cached_update_dir, ensure_current_platform, has_cached_update_meta,
    persist_cached_update, read_cached_update_meta, remove_cached_update, supports_cached_updates,
};
use events::{emit, emit_error, emit_updater_error};
use guard::begin_update;
use remote::{check_and_download, check_installable_update};
use signature::verify_cached_update;
use version::version_lte;

pub(crate) use version::is_remote_update_newer;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct DesktopUpdate {
    version: String,
    body: Option<String>,
    supports_later_install: bool,
}

#[tauri::command]
pub(crate) async fn check_desktop_update(app: AppHandle) -> Result<Option<DesktopUpdate>, String> {
    let update = check_installable_update(&app)
        .await
        .map_err(|e| e.to_string())?;

    Ok(update.map(|u| DesktopUpdate {
        version: u.version,
        body: u.body,
        supports_later_install: supports_cached_updates(),
    }))
}

#[tauri::command]
pub(crate) fn install_desktop_update(app: AppHandle) -> Result<(), String> {
    let guard = begin_update()?;
    tauri::async_runtime::spawn(async move {
        let _guard = guard;
        run_install(app).await;
    });
    Ok(())
}

async fn run_install(app: AppHandle) {
    let Some((update, bytes)) = check_and_download(&app).await else {
        return;
    };

    log::info!(
        "[updates] installing desktop update version={}",
        update.version
    );
    emit(&app, "update:install-start", &serde_json::json!({}));

    if let Err(err) = update.install(bytes) {
        return emit_updater_error(&app, "install", &err);
    }

    backend::stop(&app);
    app.restart();
}

#[tauri::command]
pub(crate) fn download_desktop_update(app: AppHandle) -> Result<(), String> {
    if !supports_cached_updates() {
        return Err("background update download is not supported on this platform".into());
    }

    let guard = begin_update()?;
    tauri::async_runtime::spawn(async move {
        let _guard = guard;
        run_background_download(app).await;
    });
    Ok(())
}

async fn run_background_download(app: AppHandle) {
    let Some((update, bytes)) = check_and_download(&app).await else {
        return;
    };

    if let Err(err) = persist_cached_update(&app, &update, &bytes) {
        return emit_error(&app, "download", &err);
    }

    log::info!(
        "[updates] background download ready: version={}",
        update.version
    );
    emit(
        &app,
        "update:download-done",
        &serde_json::json!({ "version": update.version }),
    );
}

#[tauri::command]
pub(crate) fn install_downloaded_update(app: AppHandle) -> Result<(), String> {
    if !supports_cached_updates() {
        return Err("cached updates are not supported on this platform".into());
    }

    let guard = begin_update()?;
    tauri::async_runtime::spawn(async move {
        let _guard = guard;
        run_cached_install(app).await;
    });
    Ok(())
}

async fn run_cached_install(app: AppHandle) {
    let Some(cache_dir) = cached_update_dir(&app) else {
        return emit_error(&app, "install", &"cannot determine app data directory");
    };

    let meta = match read_cached_update_meta(&cache_dir) {
        Ok(meta) => meta,
        Err(err) => {
            remove_cached_update(&cache_dir);
            return emit_error(&app, "install", &err);
        }
    };

    if let Err(err) = ensure_current_platform(&meta) {
        remove_cached_update(&cache_dir);
        return emit_error(&app, "install", &err);
    }

    let artifact_path = cached_artifact_path(&cache_dir, &meta);
    if !artifact_path.is_file() {
        remove_cached_update(&cache_dir);
        return emit_error(
            &app,
            "install",
            &"cached update artifact not found - please download again",
        );
    }

    // The cache lives in a user-writable directory, so "verified at download
    // time" is not enough. Re-verify the on-disk bytes against the configured
    // updater public key right before install.
    let bytes = match std::fs::read(&artifact_path) {
        Ok(bytes) => bytes,
        Err(err) => {
            remove_cached_update(&cache_dir);
            return emit_error(
                &app,
                "install",
                &format!("cannot read cached update: {err}"),
            );
        }
    };
    if let Err(err) = verify_cached_update(&app, &meta, &bytes) {
        remove_cached_update(&cache_dir);
        return emit_error(&app, "install", &err);
    }

    log::info!(
        "[updates] installing cached update version={} artifact={}",
        meta.version,
        artifact_path.display()
    );
    emit(&app, "update:install-start", &serde_json::json!({}));

    match meta.platform.as_str() {
        "windows" => install_cached_windows(&app, &artifact_path),
        "macos" => install_cached_macos(&app, &cache_dir, &meta, bytes).await,
        _ => {
            remove_cached_update(&cache_dir);
            emit_error(&app, "install", &"cached update platform is unsupported");
        }
    }
}

fn install_cached_windows(app: &AppHandle, exe_path: &std::path::Path) {
    backend::stop(app);
    if let Err(err) = std::process::Command::new(exe_path)
        .args(["/P", "/R", "/UPDATE", "/NO_QWENPAW_PATH"])
        .spawn()
    {
        return emit_error(
            app,
            "install",
            &format!("failed to launch installer: {err}"),
        );
    }
    // Mirrors tauri-plugin-updater's Windows path: after NSIS is launched the
    // current process must exit so the installer can replace locked files.
    app.cleanup_before_exit();
    std::process::exit(0);
}

async fn install_cached_macos(
    app: &AppHandle,
    cache_dir: &std::path::Path,
    meta: &cache::UpdateMeta,
    bytes: Vec<u8>,
) {
    let update = match check_installable_update(app).await {
        Ok(Some(update)) => update,
        Ok(None) => {
            remove_cached_update(cache_dir);
            return emit_error(
                app,
                "install",
                &"cached update is no longer available - please download again",
            );
        }
        Err(err) => return emit_updater_error(app, "check", &err),
    };

    if update.version != meta.version
        || update.target != meta.target
        || update.signature != meta.signature
    {
        remove_cached_update(cache_dir);
        return emit_error(
            app,
            "install",
            &"cached update no longer matches the latest release - please download again",
        );
    }

    if let Err(err) = update.install(bytes) {
        return emit_updater_error(app, "install", &err);
    }

    backend::stop(app);
    app.restart();
}

#[tauri::command]
pub(crate) async fn check_cached_update(app: AppHandle) -> Result<Option<String>, String> {
    if !supports_cached_updates() {
        return Ok(None);
    }

    let Some(cache_dir) = cached_update_dir(&app) else {
        return Ok(None);
    };

    if !has_cached_update_meta(&cache_dir) {
        return Ok(None);
    }

    let Ok(meta) = read_cached_update_meta(&cache_dir) else {
        remove_cached_update(&cache_dir);
        return Ok(None);
    };

    if ensure_current_platform(&meta).is_err() {
        remove_cached_update(&cache_dir);
        return Ok(None);
    }

    // Compare with current app version. If cached version <= current, it's stale.
    let current_version = app.config().version.clone().unwrap_or_default();

    if version_lte(&meta.version, &current_version) {
        log::info!(
            "[updates] cleaning stale cached update: cached={} current={}",
            meta.version,
            current_version
        );
        remove_cached_update(&cache_dir);
        return Ok(None);
    }

    if !cached_artifact_path(&cache_dir, &meta).is_file() {
        remove_cached_update(&cache_dir);
        return Ok(None);
    }

    Ok(Some(meta.version))
}
