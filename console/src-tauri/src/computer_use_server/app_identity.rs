//! Naming an application, and starting one.
//!
//! An application has to be recognisable across observations so an approval
//! granted once is not asked for again, and it has to be startable. Both
//! answers are path-backed but the accepted spellings differ per platform --
//! an executable file on Windows, a bundle directory on macOS -- so each rule
//! is cfg-split here rather than leaking into the dispatch layer.

use serde_json::{Map, Value};
use std::path::{Path, PathBuf};

use super::state::WindowInfo;

#[cfg(target_os = "macos")]
use super::app_id_from_bundle_path;

/// Work out what a launch request is asking for, without acting on it.
///
/// Split from the launch itself so the caller can put approval and the desktop
/// guard between the two, in the same order every other action follows. Purely a
/// lookup: nothing here starts a process or touches a window.
pub(super) fn resolve_launch_target(
    params: &Map<String, Value>,
) -> Result<(WindowInfo, PathBuf), (&'static str, String)> {
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
    Ok((target, path))
}

/// Build the canonical application identifier for a launchable path.
///
/// `canonicalize` resolves symlinks and reports the casing the filesystem
/// actually stores, so the same executable seen as a running process and as a
/// launch target yields one identifier -- an application is approved once, not
/// once per spelling. The extended-length prefix Windows returns is stripped so
/// the identifier stays a plain readable path.
///
/// The result is deliberately still usable as a path: `launch_app` accepts an
/// identifier from `list_apps`, so mangling the case here -- as this once did --
/// left identifiers that could not be launched on a case-sensitive volume.
#[cfg(windows)]
pub(super) fn app_id_from_path(path: &Path) -> String {
    let resolved = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    let text = resolved.to_string_lossy();
    let normalized = text.strip_prefix(r"\\?\").unwrap_or(&text);
    format!("process:{normalized}")
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
    // An identifier that is not a path came from a running application whose
    // bundle could not be read, so there is nothing to start. Saying so beats
    // reporting it as missing, since the identifier itself was valid.
    if !path.is_absolute() {
        return Err((
            "app_not_found",
            "This application's location could not be determined, so it cannot \
             be started by id."
                .to_string(),
        ));
    }
    // A bundle is a directory, so accept either that or a plain executable.
    let is_bundle = path.is_dir()
        && path
            .extension()
            .is_some_and(|value| value.eq_ignore_ascii_case("app"));
    if !(is_bundle || path.is_file()) {
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
pub(super) fn launch_at(path: &Path) -> Result<(), (&'static str, String)> {
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
pub(super) fn launch_at(path: &Path) -> Result<(), (&'static str, String)> {
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

#[cfg(test)]
mod tests {
    use super::*;

    /// The contract `launch_app` documents: an identifier `list_apps` reported
    /// can be handed straight back to start that application. It only holds if
    /// the identifier preserves the path faithfully, which is what broke when
    /// the case was flattened -- invisibly on a case-insensitive volume, and
    /// fatally on one that is not.
    #[test]
    fn an_identifier_from_discovery_resolves_back_to_the_same_file() {
        let executable = std::env::current_exe().expect("test binary path");
        let app_id = app_id_from_path(&executable);
        let resolved = resolve_launch_path(&app_id).expect("identifier must resolve");
        assert_eq!(
            resolved,
            executable.canonicalize().expect("canonical test binary")
        );
    }

    /// Discovery reports a running process without canonicalizing, while a
    /// launch target is canonicalized; both must arrive at one identifier or
    /// the same application would be approved twice.
    #[test]
    fn one_application_has_one_identifier_however_it_was_found() {
        let executable = std::env::current_exe().expect("test binary path");
        let canonical = executable.canonicalize().expect("canonical test binary");
        assert_eq!(app_id_from_path(&executable), app_id_from_path(&canonical));
    }

    #[test]
    fn an_identifier_is_not_flattened_to_lower_case() {
        // A mixed-case path must survive verbatim; the platform decides whether
        // two spellings are the same file, and it is asked through canonicalize.
        let executable = std::env::current_exe().expect("test binary path");
        let app_id = app_id_from_path(&executable);
        let canonical = executable.canonicalize().expect("canonical test binary");
        let text = canonical.to_string_lossy();
        let expected = text.strip_prefix(r"\\?\").unwrap_or(&text);
        assert!(
            app_id.ends_with(expected.as_ref() as &str),
            "identifier {app_id} must end with the canonical path {expected}"
        );
    }
}
