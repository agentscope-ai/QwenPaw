use base64::Engine;
use minisign_verify::{PublicKey, Signature};
use sha2::{Digest, Sha256};
use tauri::AppHandle;

use super::cache::UpdateMeta;

pub(super) fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest {
        use std::fmt::Write;
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// Read the updater public key from the (build-injected) Tauri config so we can
/// verify cached updates with the exact key the plugin uses.
fn updater_pubkey(app: &AppHandle) -> Option<String> {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|cfg| cfg.get("pubkey"))
        .and_then(|val| val.as_str())
        .map(|s| s.to_string())
}

/// Verify `data` against a base64-encoded minisign signature and public key,
/// mirroring `tauri-plugin-updater`'s own `verify_signature`.
fn verify_minisign(data: &[u8], signature_b64: &str, pubkey_b64: &str) -> Result<(), String> {
    let pubkey_text = base64_to_string(pubkey_b64)?;
    let public_key = PublicKey::decode(pubkey_text.trim()).map_err(|e| e.to_string())?;

    let signature_text = base64_to_string(signature_b64)?;
    let signature = Signature::decode(signature_text.trim()).map_err(|e| e.to_string())?;

    public_key
        .verify(data, &signature, true)
        .map_err(|e| e.to_string())
}

fn base64_to_string(value: &str) -> Result<String, String> {
    let decoded = base64::engine::general_purpose::STANDARD
        .decode(value.trim())
        .map_err(|e| e.to_string())?;
    String::from_utf8(decoded).map_err(|e| e.to_string())
}

/// Pre-install integrity + authenticity gate for a previously downloaded
/// update artifact. Cheap SHA-256 corruption check first, then the
/// cryptographic signature check that closes the "user-writable cache" gap.
pub(super) fn verify_cached_update(
    app: &AppHandle,
    meta: &UpdateMeta,
    bytes: &[u8],
) -> Result<(), String> {
    if !meta.sha256.is_empty() && sha256_hex(bytes) != meta.sha256 {
        return Err("cached update is corrupted - please download again".into());
    }
    if meta.signature.trim().is_empty() {
        return Err("cached update has no signature - please download again".into());
    }
    let pubkey = updater_pubkey(app).ok_or("cannot read updater public key from config")?;
    verify_minisign(bytes, &meta.signature, &pubkey)
        .map_err(|err| format!("cached update signature invalid: {err}"))
}
