use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

use super::signature::sha256_hex;

const CACHED_UPDATE_DIR: &str = "cached-update";
const UPDATE_META_FILE: &str = "update-meta.json";

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(super) struct UpdateMeta {
    pub(super) version: String,
    pub(super) artifact_file: String,
    #[serde(default)]
    pub(super) platform: String,
    #[serde(default)]
    pub(super) target: String,
    /// Base64 minisign signature string from the update manifest (same value
    /// `tauri-plugin-updater` verifies at download time). Re-verified before a
    /// cached update is installed.
    #[serde(default)]
    pub(super) signature: String,
    /// Hex SHA-256 of the persisted update bytes, for a fast corruption
    /// check before the (more expensive) signature verification.
    #[serde(default)]
    pub(super) sha256: String,
}

pub(super) fn supports_cached_updates() -> bool {
    current_platform().is_some()
}

pub(super) fn current_platform() -> Option<&'static str> {
    if cfg!(windows) {
        Some("windows")
    } else if cfg!(target_os = "macos") {
        Some("macos")
    } else {
        None
    }
}

pub(super) fn cached_update_dir(app: &AppHandle) -> Option<PathBuf> {
    app.path()
        .app_local_data_dir()
        .ok()
        .map(|p| p.join(CACHED_UPDATE_DIR))
}

pub(super) fn has_cached_update_meta(cache_dir: &Path) -> bool {
    cache_dir.join(UPDATE_META_FILE).exists()
}

pub(super) fn read_cached_update_meta(cache_dir: &Path) -> Result<UpdateMeta, String> {
    let meta_str = std::fs::read_to_string(cache_dir.join(UPDATE_META_FILE))
        .map_err(|e| format!("no cached update found: {e}"))?;
    let meta: UpdateMeta =
        serde_json::from_str(&meta_str).map_err(|e| format!("invalid update meta: {e}"))?;
    validate_artifact_file(&meta.artifact_file)?;
    Ok(meta)
}

pub(super) fn remove_cached_update(cache_dir: &Path) {
    let _ = std::fs::remove_dir_all(cache_dir);
}

/// Persist the downloaded update artifact plus its metadata so a later
/// "Update Now" only needs to verify and install it.
pub(super) fn persist_cached_update(
    app: &AppHandle,
    update: &tauri_plugin_updater::Update,
    bytes: &[u8],
) -> Result<(), String> {
    let platform = current_platform().ok_or("cached updates are not supported on this platform")?;
    validate_artifact(platform, bytes)?;

    let cache_dir = cached_update_dir(app).ok_or("cannot determine app data directory")?;
    if cache_dir.exists() {
        std::fs::remove_dir_all(&cache_dir).map_err(|e| e.to_string())?;
    }
    std::fs::create_dir_all(&cache_dir).map_err(|e| e.to_string())?;

    let artifact_path = write_artifact(platform, bytes, &cache_dir, &update.version)?;
    let artifact_file = artifact_path
        .strip_prefix(&cache_dir)
        .ok()
        .and_then(|p| p.to_str())
        .ok_or("cached update path is invalid")?
        .to_string();

    let meta = UpdateMeta {
        version: update.version.clone(),
        artifact_file,
        platform: platform.to_string(),
        target: update.target.clone(),
        signature: update.signature.clone(),
        sha256: sha256_hex(bytes),
    };
    let meta_json = serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?;
    std::fs::write(cache_dir.join(UPDATE_META_FILE), meta_json).map_err(|e| e.to_string())
}

pub(super) fn ensure_current_platform(meta: &UpdateMeta) -> Result<(), String> {
    let Some(platform) = current_platform() else {
        return Err("cached updates are not supported on this platform".into());
    };
    if meta.platform != platform {
        return Err("cached update is for a different platform - please download again".into());
    }
    Ok(())
}

pub(super) fn validate_artifact(platform: &str, bytes: &[u8]) -> Result<(), String> {
    match platform {
        "windows" if !bytes.starts_with(b"MZ") => {
            Err("downloaded update is not a Windows installer executable".into())
        }
        "macos" if !bytes.starts_with(&[0x1f, 0x8b]) => {
            Err("downloaded update is not a macOS app archive".into())
        }
        "windows" | "macos" => Ok(()),
        _ => Err("cached updates are not supported on this platform".into()),
    }
}

fn write_artifact(
    platform: &str,
    bytes: &[u8],
    dest_dir: &Path,
    version: &str,
) -> Result<PathBuf, String> {
    let file_name = match platform {
        "windows" => format!("QwenPaw-Desktop_{version}_x64-setup.exe"),
        "macos" => format!("QwenPaw-Desktop_{version}_macos.app.tar.gz"),
        _ => return Err("cached updates are not supported on this platform".into()),
    };
    let path = dest_dir.join(file_name);
    std::fs::write(&path, bytes).map_err(|e| e.to_string())?;
    Ok(path)
}

pub(super) fn cached_artifact_path(cache_dir: &Path, meta: &UpdateMeta) -> PathBuf {
    cache_dir.join(&meta.artifact_file)
}

fn validate_artifact_file(file: &str) -> Result<(), String> {
    let is_single_file = !file.is_empty()
        && !file.contains('/')
        && !file.contains('\\')
        && Path::new(file)
            .components()
            .all(|part| matches!(part, std::path::Component::Normal(_)));
    if is_single_file {
        Ok(())
    } else {
        Err("cached update artifact path is invalid".into())
    }
}
