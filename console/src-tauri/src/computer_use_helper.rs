//! Install the macOS Computer Use helper outside the updatable desktop bundle.
//!
//! Screen Recording and Accessibility decisions are associated with the code
//! requesting them. The desktop bundle is replaced on update, so its bundled
//! helper seeds this standalone app on first use and refreshes it when the
//! packaged native code changes. It lives in the user's Applications directory
//! so LaunchServices and TCC recognize it as an application when it requests
//! system permissions.

use core_foundation::base::TCFType;
use core_foundation::url::CFURL;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use tauri::AppHandle;

const HELPER_BUNDLE_NAME: &str = "QwenPaw Computer Use.app";
const HELPER_BUNDLE_ID: &str = "io.agentscope.qwenpaw.computer-use.v1";
const HELPER_EXECUTABLE_NAME: &str = "qwenpaw-computer-use-helper";
const HELPER_BACKUP_NAME: &str = ".qwenpaw-computer-use-backup";
const HELPER_INFO_PLIST: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>QwenPaw Computer Use</string>
    <key>CFBundleExecutable</key>
    <string>qwenpaw-computer-use-helper</string>
    <key>CFBundleIdentifier</key>
    <string>io.agentscope.qwenpaw.computer-use.v1</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>QwenPaw Computer Use</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
"#;

pub(crate) fn installed_bundle(_app: &AppHandle) -> Result<PathBuf, String> {
    let seed = seed_executable()?;
    let bundle = installed_bundle_path()?;
    let parent = bundle
        .parent()
        .ok_or_else(|| "Computer Use helper destination has no parent".to_string())?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "failed to create Computer Use helper directory {}: {error}",
            parent.display()
        )
    })?;
    let backup = parent.join(HELPER_BACKUP_NAME);
    recover_installation(&bundle, &backup)?;

    let staged = parent.join(format!(".computer-use-install-{}", std::process::id()));
    stage_bundle(&seed, &staged)?;
    if bundles_match(&staged, &bundle) {
        fs::remove_dir_all(&staged)
            .map_err(|error| format!("failed to clear staged Computer Use helper: {error}"))?;
    } else {
        if bundle.exists() {
            reset_privacy_decisions()?;
        }
        activate_bundle(&staged, &bundle, &backup)?;
    }

    register_bundle(&bundle)?;
    let executable = bundle_executable(&bundle);
    executable
        .is_file()
        .then_some(bundle.clone())
        .ok_or_else(|| {
            format!(
                "Computer Use helper installation is missing {}.",
                executable.display()
            )
        })
}

fn seed_executable() -> Result<PathBuf, String> {
    let desktop = std::env::current_exe()
        .map_err(|error| format!("failed to resolve desktop executable: {error}"))?;
    let directory = desktop.parent().ok_or_else(|| {
        format!(
            "desktop executable has no containing directory: {}",
            desktop.display()
        )
    })?;
    let helper = directory.join(HELPER_EXECUTABLE_NAME);
    helper.is_file().then_some(helper.clone()).ok_or_else(|| {
        format!(
            "Computer Use helper is missing next to the desktop executable at {}.",
            helper.display()
        )
    })
}

fn installed_bundle_path() -> Result<PathBuf, String> {
    dirs::home_dir()
        .map(|directory| directory.join("Applications").join(HELPER_BUNDLE_NAME))
        .ok_or_else(|| "failed to resolve the user's Applications directory".to_string())
}

fn bundle_executable(bundle: &Path) -> PathBuf {
    bundle
        .join("Contents")
        .join("MacOS")
        .join(HELPER_EXECUTABLE_NAME)
}

fn stage_bundle(seed: &Path, staged: &Path) -> Result<(), String> {
    if staged.exists() {
        fs::remove_dir_all(staged).map_err(|error| {
            format!(
                "failed to clear incomplete Computer Use helper installation {}: {error}",
                staged.display()
            )
        })?;
    }

    let staged_executable = bundle_executable(staged);
    let install_result = (|| {
        let macos_directory = staged_executable.parent().ok_or_else(|| {
            format!(
                "Computer Use helper has invalid executable path: {}",
                staged_executable.display()
            )
        })?;
        let contents_directory = macos_directory.parent().ok_or_else(|| {
            format!(
                "Computer Use helper has invalid contents path: {}",
                macos_directory.display()
            )
        })?;
        fs::create_dir_all(macos_directory)
            .map_err(|error| format!("failed to stage Computer Use helper bundle: {error}"))?;
        fs::copy(seed, &staged_executable)
            .map_err(|error| format!("failed to copy Computer Use helper: {error}"))?;
        fs::set_permissions(&staged_executable, fs::Permissions::from_mode(0o755))
            .map_err(|error| format!("failed to make Computer Use helper executable: {error}"))?;
        fs::write(contents_directory.join("Info.plist"), HELPER_INFO_PLIST)
            .map_err(|error| format!("failed to write Computer Use helper metadata: {error}"))?;
        sign_bundle(staged)
    })();
    if install_result.is_err() {
        let _ = fs::remove_dir_all(staged);
    }
    install_result
}

fn bundles_match(staged: &Path, installed: &Path) -> bool {
    let same_metadata = fs::read(installed.join("Contents/Info.plist"))
        .is_ok_and(|value| value == HELPER_INFO_PLIST.as_bytes());
    let staged_executable = fs::read(bundle_executable(staged));
    let installed_executable = fs::read(bundle_executable(installed));
    same_metadata
        && matches!(
            (staged_executable, installed_executable),
            (Ok(staged), Ok(installed)) if staged == installed
        )
}

fn activate_bundle(staged: &Path, destination: &Path, backup: &Path) -> Result<(), String> {
    if destination.exists() {
        fs::rename(destination, backup)
            .map_err(|error| format!("failed to preserve old Computer Use helper: {error}"))?;
    }
    if let Err(error) = fs::rename(staged, destination) {
        let _ = fs::rename(backup, destination);
        return Err(format!("failed to activate Computer Use helper: {error}"));
    }
    if backup.exists() {
        fs::remove_dir_all(backup)
            .map_err(|error| format!("failed to remove old Computer Use helper: {error}"))?;
    }
    Ok(())
}

fn recover_installation(destination: &Path, backup: &Path) -> Result<(), String> {
    if !backup.exists() {
        return Ok(());
    }
    if destination.exists() {
        fs::remove_dir_all(backup)
            .map_err(|error| format!("failed to clear old Computer Use helper: {error}"))
    } else {
        fs::rename(backup, destination)
            .map_err(|error| format!("failed to recover Computer Use helper: {error}"))
    }
}

fn reset_privacy_decisions() -> Result<(), String> {
    for service in ["ScreenCapture", "Accessibility"] {
        let status = Command::new("/usr/bin/tccutil")
            .args(["reset", service, HELPER_BUNDLE_ID])
            .status()
            .map_err(|error| format!("failed to reset {service} access: {error}"))?;
        if !status.success() {
            return Err(format!(
                "failed to reset {service} access: tccutil exited with {status}"
            ));
        }
    }
    Ok(())
}

fn sign_bundle(bundle: &Path) -> Result<(), String> {
    let status = Command::new("/usr/bin/codesign")
        .args(["--force", "--sign", "-", "--timestamp=none"])
        .arg(bundle)
        .status()
        .map_err(|error| format!("failed to sign Computer Use helper: {error}"))?;
    status
        .success()
        .then_some(())
        .ok_or_else(|| format!("failed to sign Computer Use helper: codesign exited with {status}"))
}

fn register_bundle(bundle: &Path) -> Result<(), String> {
    let url = CFURL::from_path(bundle, true).ok_or_else(|| {
        format!(
            "failed to create a LaunchServices URL for Computer Use helper at {}",
            bundle.display()
        )
    })?;
    let status = unsafe { LSRegisterURL(url.as_concrete_TypeRef(), 1) };
    (status == 0).then_some(()).ok_or_else(|| {
        format!("failed to register Computer Use helper with LaunchServices (status {status})")
    })
}

#[link(name = "CoreServices", kind = "framework")]
unsafe extern "C" {
    fn LSRegisterURL(url: core_foundation::url::CFURLRef, update: u8) -> i32;
}
