//! Give development processes their own real bundle identity before AppKit starts.

use std::{
    ffi::OsStr,
    fs,
    os::unix::process::CommandExt,
    path::{Path, PathBuf},
    process::Command,
};

fn bundle_root(executable: &Path) -> Option<&Path> {
    let macos = executable.parent()?;
    let contents = macos.parent()?;
    let bundle = contents.parent()?;
    (macos.file_name() == Some(OsStr::new("MacOS"))
        && contents.file_name() == Some(OsStr::new("Contents"))
        && bundle.extension() == Some(OsStr::new("app")))
    .then_some(bundle)
}

fn xml(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn info_plist(identifier: &str, name: &str, executable: &str, version: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIdentifier</key><string>{}</string>
<key>CFBundleName</key><string>{}</string>
<key>CFBundleDisplayName</key><string>{}</string>
<key>CFBundleExecutable</key><string>{}</string>
<key>CFBundleVersion</key><string>{}</string>
<key>CFBundleShortVersionString</key><string>{}</string>
<key>CFBundleIconFile</key><string>icon.icns</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSPrincipalClass</key><string>NSApplication</string>
</dict></plist>
"#,
        xml(identifier),
        xml(name),
        xml(name),
        xml(executable),
        xml(version),
        xml(version)
    )
}

fn checked(command: &mut Command, operation: &str) -> Result<(), String> {
    let output = command
        .output()
        .map_err(|error| format!("{operation}: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "{operation}: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ))
    }
}

/// Re-exec, retaining the PID and pipes owned by the Tauri development watcher.
pub(crate) fn relaunch_if_needed(
    identifier: &str,
    name: &str,
    version: &str,
) -> Result<(), String> {
    let source = std::env::current_exe().map_err(|error| error.to_string())?;
    if bundle_root(&source).is_some() {
        return Ok(());
    }
    let file_name = source
        .file_name()
        .ok_or("Missing development executable name")?;
    let bundle = source
        .parent()
        .ok_or("Missing executable directory")?
        .join("dev-bundle")
        .join(format!("{name}.app"));
    let contents = bundle.join("Contents");
    let macos = contents.join("MacOS");
    let resources = contents.join("Resources");
    fs::create_dir_all(&macos).map_err(|error| error.to_string())?;
    fs::create_dir_all(&resources).map_err(|error| error.to_string())?;
    let binary = macos.join(file_name);
    let temporary = macos.join(format!(".{}", uuid::Uuid::new_v4()));
    fs::copy(&source, &temporary).map_err(|error| error.to_string())?;
    fs::rename(&temporary, &binary).map_err(|error| error.to_string())?;
    let plist = info_plist(identifier, name, &file_name.to_string_lossy(), version);
    fs::write(contents.join("Info.plist"), plist).map_err(|error| error.to_string())?;
    let icon =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../scripts/pack/assets/icon.icns");
    if icon.is_file() {
        fs::copy(icon, resources.join("icon.icns")).map_err(|error| error.to_string())?;
    }
    checked(
        Command::new("/usr/bin/codesign")
            .args([
                "--force",
                "--sign",
                "-",
                "--timestamp=none",
                "--identifier",
                identifier,
            ])
            .arg(&bundle),
        "Sign development app bundle",
    )?;
    checked(Command::new("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
        .arg("-f").arg(&bundle), "Register development app bundle")?;
    eprintln!(
        "[desktop] starting development app from {}",
        bundle.display()
    );
    let error = Command::new(binary)
        .args(std::env::args_os().skip(1))
        .exec();
    Err(format!("Start development app bundle: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_bundled_executables_with_spaces_and_unicode() {
        let path = Path::new("/tmp/测试 App.app/Contents/MacOS/qwenpaw-desktop");
        assert_eq!(bundle_root(path), Some(Path::new("/tmp/测试 App.app")));
        assert!(bundle_root(Path::new("/tmp/target/debug/qwenpaw-desktop")).is_none());
        assert!(bundle_root(Path::new("/tmp/App.appish/Contents/MacOS/app")).is_none());
    }

    #[test]
    fn declares_the_app_identity_and_escapes_its_display_name() {
        let plist = info_plist(
            "io.agentscope.qwenpaw.desktop",
            "Qwen & Paw",
            "qwenpaw-desktop",
            "0.1.0",
        );
        assert!(plist.contains("<string>io.agentscope.qwenpaw.desktop</string>"));
        assert!(plist.contains("Qwen &amp; Paw"));
        assert!(plist.contains("<key>NSPrincipalClass</key><string>NSApplication</string>"));
        assert!(plist.contains("<key>CFBundleExecutable</key><string>qwenpaw-desktop</string>"));
        assert!(!plist.contains("com.apple.Terminal"));
    }
}
