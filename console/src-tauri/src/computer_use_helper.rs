//! Install the macOS Computer Use helper outside the updatable desktop bundle.
//!
//! Screen Recording and Accessibility decisions are associated with the code
//! requesting them. The desktop bundle is replaced on update, so its bundled
//! helper only seeds this standalone app on first use. The installed copy is
//! deliberately never overwritten by later desktop or plugin updates. It lives
//! in the user's Applications directory so LaunchServices and TCC recognize it
//! as an application when it requests system permissions.

use core_foundation::base::TCFType;
use core_foundation::url::CFURL;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;

use tauri::AppHandle;

const HELPER_BUNDLE_NAME: &str = "QwenPaw Computer Use.app";
const HELPER_EXECUTABLE_NAME: &str = "qwenpaw-computer-use-helper";
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
    let bundle = installed_bundle_path()?;
    let executable = bundle_executable(&bundle);
    if executable.is_file() {
        register_bundle(&bundle)?;
        return Ok(bundle);
    }
    if bundle.exists() {
        return Err(format!(
            "Computer Use helper is incomplete at {}. Remove it and try again.",
            bundle.display()
        ));
    }

    install_bundle(&seed_executable()?, &bundle)?;
    register_bundle(&bundle)?;
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

fn install_bundle(seed: &Path, destination: &Path) -> Result<(), String> {
    let parent = destination.parent().ok_or_else(|| {
        format!(
            "Computer Use helper destination has no parent: {}",
            destination.display()
        )
    })?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "failed to create Computer Use helper directory {}: {error}",
            parent.display()
        )
    })?;

    let temporary = parent.join(format!(".computer-use-install-{}", std::process::id()));
    if temporary.exists() {
        fs::remove_dir_all(&temporary).map_err(|error| {
            format!(
                "failed to clear incomplete Computer Use helper installation {}: {error}",
                temporary.display()
            )
        })?;
    }

    let staged_executable = bundle_executable(&temporary);
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
        sign_bundle(&temporary)?;
        fs::rename(&temporary, destination).map_err(|error| {
            format!(
                "failed to activate Computer Use helper at {}: {error}",
                destination.display()
            )
        })
    })();
    if install_result.is_err() {
        let _ = fs::remove_dir_all(&temporary);
    }
    install_result
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
