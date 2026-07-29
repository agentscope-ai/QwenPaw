//! Naming an application, and starting one.
//!
//! An application has to be recognisable across observations so an approval
//! granted once is not asked for again, and it has to be startable. Both
//! answers are path-backed but the accepted spellings differ per platform --
//! an executable file on Windows, a bundle directory on macOS -- so each rule
//! is cfg-split here rather than leaking into the dispatch layer.

use serde_json::{json, Map, Value};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use super::approval::request_approval;
use super::state::WindowInfo;

#[cfg(target_os = "macos")]
use super::app_id_from_bundle_path;

pub(super) fn launch_app(
    connection: &mut (impl Read + Write),
    params: &Map<String, Value>,
    meta: &Map<String, Value>,
) -> Result<Value, (&'static str, String)> {
    let app = params
        .get("app")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(("invalid_request", "app is required.".to_string()))?;
    let path = resolve_launch_path(app)?;
    let display_name = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("Application")
        .to_string();
    let target = WindowInfo {
        hwnd: 0,
        app_id: app_id_from_path(&path),
        display_name,
        title: String::new(),
        class_name: String::new(),
    };
    request_approval(connection, &target, meta)?;
    launch_at(&path)?;
    Ok(json!({"launched": true, "app_id": target.app_id}))
}

/// Build the canonical application identifier for a launchable path.
///
/// Windows discovery reports plain drive paths while `canonicalize` returns
/// extended-length (`\\?\`) ones, so the prefix is stripped to keep a single
/// identifier per application; macOS derives the same identifier from the
/// bundle path. Either way an application is approved once per session rather
/// than once per path spelling.
#[cfg(windows)]
pub(super) fn app_id_from_path(path: &Path) -> String {
    let text = path.to_string_lossy();
    let normalized = text.strip_prefix(r"\\?\").unwrap_or(&text);
    format!("process:{}", normalized.to_lowercase())
}

#[cfg(target_os = "macos")]
pub(super) fn app_id_from_path(path: &Path) -> String {
    app_id_from_bundle_path(path)
}

/// Validate what `launch_app` was given and resolve it to something the
/// platform can start.
///
/// The accepted spellings differ by platform -- an executable file on Windows,
/// an application bundle on macOS -- so each leaf owns its own rule.
#[cfg(windows)]
fn resolve_launch_path(app: &str) -> Result<PathBuf, (&'static str, String)> {
    let value = app.strip_prefix("process:").unwrap_or(app);
    let path = PathBuf::from(value);
    if !path.is_absolute()
        || !path.is_file()
        || !path
            .extension()
            .is_some_and(|value| value.eq_ignore_ascii_case("exe"))
    {
        return Err((
            "app_not_found",
            "launch_app accepts an App ID from list_apps or an absolute .exe path.".to_string(),
        ));
    }
    path.canonicalize()
        .map_err(|error| ("app_not_found", error.to_string()))
}

#[cfg(target_os = "macos")]
fn resolve_launch_path(app: &str) -> Result<PathBuf, (&'static str, String)> {
    let value = app.strip_prefix("app:").unwrap_or(app);
    let path = PathBuf::from(value);
    // A bundle is a directory, so accept either that or a plain executable.
    let is_bundle = path.is_dir()
        && path
            .extension()
            .is_some_and(|value| value.eq_ignore_ascii_case("app"));
    if !path.is_absolute() || !(is_bundle || path.is_file()) {
        return Err((
            "app_not_found",
            "launch_app accepts an App ID from list_apps or an absolute path \
             to an application bundle."
                .to_string(),
        ));
    }
    path.canonicalize()
        .map_err(|error| ("app_not_found", error.to_string()))
}

/// Start the application at a resolved path.
#[cfg(windows)]
fn launch_at(path: &Path) -> Result<(), (&'static str, String)> {
    std::process::Command::new(path)
        .spawn()
        .map(|_| ())
        .map_err(|error| {
            (
                "input_failed",
                format!("Could not launch application: {error}"),
            )
        })
}

/// Start the application at a resolved path.
///
/// A bundle is a directory and cannot be executed, so it is handed to `open`
/// with double-click semantics: Launch Services starts the application, or
/// activates it when already running. A plain executable is spawned directly,
/// the way Windows starts one -- it is not registered with Launch Services,
/// so `open` has no notion of it. `open` returns as soon as the request is
/// made, so the caller polls `list_windows` for the new window rather than
/// waiting here.
#[cfg(target_os = "macos")]
fn launch_at(path: &Path) -> Result<(), (&'static str, String)> {
    let is_bundle = path
        .extension()
        .is_some_and(|value| value.eq_ignore_ascii_case("app"));
    let mut command = if is_bundle {
        let mut open = std::process::Command::new("open");
        open.arg(path);
        open
    } else {
        std::process::Command::new(path)
    };
    command.spawn().map(|_| ()).map_err(|error| {
        (
            "input_failed",
            format!("Could not launch application: {error}"),
        )
    })
}
