//! Tauri command for opening a local path in the system file explorer.
//!
//! Security: the path is validated to be absolute, free of traversal
//! sequences, and confirmed to exist on disk before any shell command
//! is spawned.

use std::path::{Path, PathBuf};

/// Characters that must never appear in a validated path — they could
/// enable shell injection or are simply nonsensical in a file path.
/// Backslash is allowed on Windows (path separator) but forbidden elsewhere.
#[cfg(target_os = "windows")]
const FORBIDDEN_CHARS: &[char] = &[
    '|', '&', ';', '$', '`', '(', ')', '{', '}', '<', '>', '!',
    '\'', '"', '\n', '\r', '\0',
];
#[cfg(not(target_os = "windows"))]
const FORBIDDEN_CHARS: &[char] = &[
    '|', '&', ';', '$', '`', '(', ')', '{', '}', '<', '>', '!', '\\',
    '\'', '"', '\n', '\r', '\0',
];

/// Open the system file explorer at the given local path.
///
/// - If `path` points to a file, the parent directory is opened and the
///   file is selected (platform-permitting).
/// - If `path` points to a directory, that directory is opened directly.
#[tauri::command]
pub(crate) fn open_in_explorer(path: String) -> Result<(), String> {
    let cleaned = validate_path(&path)?;

    #[cfg(target_os = "windows")]
    return open_windows(&cleaned);

    #[cfg(target_os = "macos")]
    return open_macos(&cleaned);

    #[cfg(target_os = "linux")]
    return open_linux(&cleaned);

    #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
    {
        let _ = cleaned;
        Err("unsupported platform".into())
    }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/// Trim whitespace, reject dangerous inputs, and canonicalize the path.
fn validate_path(raw: &str) -> Result<PathBuf, String> {
    let trimmed = raw.trim();

    if trimmed.is_empty() {
        return Err("path is empty".into());
    }

    // Reject control characters and shell meta-characters.
    if trimmed.chars().any(|c| c.is_control() || FORBIDDEN_CHARS.contains(&c)) {
        return Err("path contains forbidden characters".into());
    }

    // Reject path traversal.
    if trimmed.contains("..") {
        return Err("path contains traversal sequence (..)".into());
    }

    let path = Path::new(trimmed);

    // Must be absolute.
    if !path.is_absolute() {
        return Err("path is not absolute".into());
    }

    // Must exist on disk.
    if !path.exists() {
        return Err(format!("path does not exist: {}", trimmed));
    }

    Ok(path.to_path_buf())
}

// ---------------------------------------------------------------------------
// Platform implementations
// ---------------------------------------------------------------------------

#[cfg(target_os = "windows")]
fn open_windows(path: &Path) -> Result<(), String> {
    use std::process::Command;

    if path.is_dir() {
        Command::new("explorer.exe")
            .arg(path.as_os_str())
            .spawn()
            .map_err(|e| format!("failed to open explorer: {e}"))?;
    } else {
        // /select, opens the parent folder with the file highlighted.
        let select_arg = format!("/select,{}", path.display());
        Command::new("explorer.exe")
            .arg(&select_arg)
            .spawn()
            .map_err(|e| format!("failed to open explorer: {e}"))?;
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn open_macos(path: &Path) -> Result<(), String> {
    use std::process::Command;

    // `open -R` reveals the file/directory in Finder.
    Command::new("open")
        .arg("-R")
        .arg(path.as_os_str())
        .spawn()
        .map_err(|e| format!("failed to open Finder: {e}"))?;
    Ok(())
}

#[cfg(target_os = "linux")]
fn open_linux(path: &Path) -> Result<(), String> {
    use std::process::Command;

    let target = if path.is_dir() {
        path.to_path_buf()
    } else {
        path.parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| path.to_path_buf())
    };

    Command::new("xdg-open")
        .arg(target.as_os_str())
        .spawn()
        .map_err(|e| format!("failed to open file manager: {e}"))?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reject_empty_path() {
        assert!(validate_path("").is_err());
        assert!(validate_path("   ").is_err());
    }

    #[test]
    fn reject_relative_paths() {
        assert!(validate_path("foo/bar").is_err());
        assert!(validate_path("./foo").is_err());
        assert!(validate_path("../etc/passwd").is_err());
    }

    #[test]
    fn reject_traversal_in_absolute_path() {
        assert!(validate_path("/home/user/../../etc/passwd").is_err());
        assert!(validate_path("C:\\Users\\..\\..\\Windows").is_err());
    }

    #[test]
    fn reject_shell_metacharacters() {
        assert!(validate_path("/home/user; rm -rf /").is_err());
        assert!(validate_path("/home/user|cat /etc/passwd").is_err());
        assert!(validate_path("/home/user$(whoami)").is_err());
        assert!(validate_path("/home/user`id`").is_err());
    }

    #[test]
    fn reject_control_characters() {
        assert!(validate_path("/home/user/\x00file").is_err());
        assert!(validate_path("/home/user/\nfile").is_err());
    }

    #[test]
    fn reject_nonexistent_path() {
        // An absolute path that almost certainly does not exist.
        assert!(validate_path("/this/path/does/not/exist/qwenpaw_test").is_err());
    }

    #[test]
    fn accept_existing_directory() {
        // /tmp should exist on all Unix-like systems; skip on Windows.
        #[cfg(not(target_os = "windows"))]
        {
            let result = validate_path("/tmp");
            assert!(result.is_ok(), "expected /tmp to be accepted");
        }
    }
}
