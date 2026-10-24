//! Install the macOS Computer Use helper outside the updatable desktop bundle.
//!
//! Screen Recording and Accessibility decisions are associated with the code
//! requesting them. The desktop bundle is replaced on update, so its bundled
//! pre-signed helper seeds this standalone app on first use and refreshes it
//! by verified, byte-preserving copy. Signing belongs to the build, never the
//! user's runtime. It lives in the user's Applications directory
//! so LaunchServices and TCC recognize it as an application when it requests
//! system permissions.

#[cfg(not(debug_assertions))]
use core_foundation::base::TCFType;
#[cfg(not(debug_assertions))]
use core_foundation::url::CFURL;
#[cfg(any(not(debug_assertions), test))]
use std::fs;
use std::path::{Path, PathBuf};
#[cfg(any(not(debug_assertions), test))]
use std::process::Command;

#[cfg(not(debug_assertions))]
use tauri::AppHandle;

const HELPER_BUNDLE_NAME: &str = "QwenPaw Computer Use.app";
const HELPER_EXECUTABLE_NAME: &str = "qwenpaw-computer-use-helper";
#[cfg(any(not(debug_assertions), test))]
const HELPER_BACKUP_NAME: &str = ".qwenpaw-computer-use-backup";
#[cfg(any(not(debug_assertions), test))]
const HELPER_IDENTIFIER: &str = "io.agentscope.qwenpaw.computer-use.v1";

#[cfg(not(debug_assertions))]
pub(crate) fn installed_bundle(_app: &AppHandle) -> Result<PathBuf, String> {
    let seed = seed_bundle()?;
    verify_bundle(&seed)?;
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
    // Multiple desktop profiles must not race over one installed TCC identity.
    let _lock = installation_lock(parent)?;
    install_verified_bundle(&seed, &bundle)?;

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

#[cfg(not(debug_assertions))]
fn seed_bundle() -> Result<PathBuf, String> {
    let desktop = std::env::current_exe()
        .map_err(|error| format!("failed to resolve desktop executable: {error}"))?;
    let directory = desktop.parent().ok_or_else(|| {
        format!(
            "desktop executable has no containing directory: {}",
            desktop.display()
        )
    })?;
    let contents = directory
        .parent()
        .ok_or("desktop has no Contents directory")?;
    Ok(contents.join("Helpers").join(HELPER_BUNDLE_NAME))
}

#[cfg(not(debug_assertions))]
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

#[cfg(any(not(debug_assertions), test))]
fn installation_lock(parent: &Path) -> Result<fs::File, String> {
    use std::os::{fd::AsRawFd, unix::fs::OpenOptionsExt};
    let file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(parent.join(".qwenpaw-computer-use-install.lock"))
        .map_err(|error| format!("failed to open Helper installation lock: {error}"))?;
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        return Err("Computer Use helper installation is busy; retry later".into());
    }
    // Closing this descriptor releases the advisory lock even after a crash.
    Ok(file)
}

/// The package contains only regular files/directories. Reject links and
/// special files instead of following them outside the signed helper tree.
#[cfg(any(not(debug_assertions), test))]
fn tree_digest(root: &Path) -> Result<Vec<u8>, String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    use std::os::unix::{ffi::OsStrExt, fs::PermissionsExt};
    fn visit(path: &Path, relative: &Path, hash: &mut Sha256) -> Result<(), String> {
        let metadata = fs::symlink_metadata(path).map_err(|e| e.to_string())?;
        let name = relative.as_os_str().as_bytes();
        hash.update((name.len() as u64).to_le_bytes());
        hash.update(name);
        hash.update(metadata.permissions().mode().to_le_bytes());
        if metadata.is_dir() {
            hash.update(b"directory");
            let mut children = fs::read_dir(path)
                .map_err(|e| e.to_string())?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| e.to_string())?;
            children.sort_by_key(|child| child.file_name());
            for child in children {
                visit(&child.path(), &relative.join(child.file_name()), hash)?;
            }
        } else if metadata.is_file() {
            hash.update(b"file");
            hash.update(metadata.len().to_le_bytes());
            let mut file = fs::File::open(path).map_err(|e| e.to_string())?;
            let mut buffer = [0u8; 65536];
            loop {
                let count = file.read(&mut buffer).map_err(|e| e.to_string())?;
                if count == 0 {
                    break;
                }
                hash.update(&buffer[..count]);
            }
        } else {
            return Err("Helper bundle contains a link or special file".into());
        }
        Ok(())
    }
    let mut hash = Sha256::new();
    visit(root, Path::new(""), &mut hash)?;
    Ok(hash.finalize().to_vec())
}

#[cfg(any(not(debug_assertions), test))]
fn copy_tree(source: &Path, target: &Path) -> Result<(), String> {
    tree_digest(source)?;
    match fs::symlink_metadata(target) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        _ => return Err("Helper staging destination already exists or is inaccessible".into()),
    }
    // Plain fs::copy loses macOS extended/resource metadata. ditto preserves
    // it without modifying code, signatures, quarantine or ACLs. No inherited
    // DITTO_* option may turn this into a filtered/metadata-stripping copy.
    let status = Command::new("/usr/bin/ditto")
        .env_clear()
        .args(["--rsrc", "--extattr", "--qtn", "--acl"])
        .arg(source)
        .arg(target)
        .status()
        .map_err(|error| format!("failed to copy pre-signed Helper: {error}"))?;
    if !status.success() {
        return Err("pre-signed Helper copy failed".into());
    }
    Ok(())
}

#[cfg(any(not(debug_assertions), test))]
fn install_verified_bundle(seed: &Path, bundle: &Path) -> Result<(), String> {
    verify_bundle(seed)?;
    let expected = tree_digest(seed)?;
    let parent = bundle.parent().ok_or("Helper destination has no parent")?;
    let backup = parent.join(HELPER_BACKUP_NAME);
    for path in [bundle, &backup] {
        match fs::symlink_metadata(path) {
            Ok(metadata) if metadata.is_dir() => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            _ => return Err("Helper installation/backup path is not a regular directory".into()),
        }
    }
    recover_installation(bundle, &backup)?;
    if bundle.exists() && tree_digest(bundle)? == expected {
        verify_bundle(bundle)?;
        return Ok(());
    }
    let staged = parent.join(format!(".computer-use-install-{}", uuid::Uuid::new_v4()));
    let result = (|| {
        copy_tree(seed, &staged)?;
        verify_bundle(&staged)?;
        if tree_digest(&staged)? != expected {
            return Err("Computer Use helper changed while staging".into());
        }
        activate_bundle(&staged, bundle, &backup)
    })();
    if staged.exists() {
        let _ = fs::remove_dir_all(&staged);
    }
    result
}

#[cfg(any(not(debug_assertions), test))]
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

#[cfg(any(not(debug_assertions), test))]
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

#[cfg(any(not(debug_assertions), test))]
fn verify_bundle(bundle: &Path) -> Result<(), String> {
    // A directory scan first ensures codesign cannot follow external links.
    tree_digest(bundle)?;
    if !bundle_executable(bundle).is_file()
        || !bundle
            .join("Contents/Frameworks/libqwenpaw_record_replay.dylib")
            .is_file()
    {
        return Err("pre-signed Computer Use helper bundle is incomplete".into());
    }
    let status = Command::new("/usr/bin/codesign")
        .args(["--verify", "--deep", "--strict"])
        .arg(bundle)
        .status()
        .map_err(|error| format!("failed to verify Computer Use helper: {error}"))?;
    if !status.success() {
        return Err("pre-signed Computer Use helper signature verification failed".into());
    }
    for (key, expected) in [
        ("CFBundleIdentifier", HELPER_IDENTIFIER),
        ("CFBundleExecutable", HELPER_EXECUTABLE_NAME),
        ("CFBundlePackageType", "APPL"),
        ("LSMinimumSystemVersion", "14.0"),
    ] {
        let value = Command::new("/usr/libexec/PlistBuddy")
            .args(["-c", &format!("Print :{key}")])
            .arg(bundle.join("Contents/Info.plist"))
            .output()
            .map_err(|error| format!("failed to read Helper bundle metadata: {error}"))?;
        if !value.status.success() || String::from_utf8_lossy(&value.stdout).trim() != expected {
            return Err(
                "pre-signed Computer Use helper has unexpected bundle identity or baseline".into(),
            );
        }
    }
    Ok(())
}

#[cfg(not(debug_assertions))]
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

#[cfg(not(debug_assertions))]
#[link(name = "CoreServices", kind = "framework")]
unsafe extern "C" {
    fn LSRegisterURL(url: core_foundation::url::CFURLRef, update: u8) -> i32;
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::{symlink, MetadataExt, PermissionsExt};

    fn unsigned_tree(root: &Path) {
        fs::create_dir_all(root.join("Contents/MacOS")).unwrap();
        fs::create_dir(root.join("Contents/Frameworks")).unwrap();
        fs::write(
            root.join("Contents/Info.plist"),
            include_bytes!("../helper-Info.plist"),
        )
        .unwrap();
        fs::write(bundle_executable(root), b"fixture executable").unwrap();
        fs::set_permissions(bundle_executable(root), fs::Permissions::from_mode(0o755)).unwrap();
        fs::write(
            root.join("Contents/Frameworks/libqwenpaw_record_replay.dylib"),
            b"fixture shim",
        )
        .unwrap();
    }

    fn sign_fixture(path: &Path) {
        let output = Command::new("/usr/bin/codesign")
            .args(["--force", "--sign", "-", "--timestamp=none"])
            .arg(path)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    fn signed_tree(root: &Path) {
        unsigned_tree(root);
        // A copied, never-executed test binary makes a genuine signed fixture.
        // This tests installation/signature preservation, not the Helper ABI.
        let test_binary = std::env::current_exe().unwrap();
        let shim = root.join("Contents/Frameworks/libqwenpaw_record_replay.dylib");
        fs::copy(&test_binary, bundle_executable(root)).unwrap();
        fs::copy(&test_binary, &shim).unwrap();
        sign_fixture(&shim);
        sign_fixture(root);
    }

    #[test]
    fn copy_preserves_all_bytes_and_modes() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed");
        let staged = temp.path().join("staged");
        unsigned_tree(&seed);
        assert!(Command::new("/usr/bin/xattr")
            .args(["-w", "com.qwenpaw.install-fixture", "retained"])
            .arg(bundle_executable(&seed))
            .status()
            .unwrap()
            .success());
        copy_tree(&seed, &staged).unwrap();
        assert_eq!(tree_digest(&seed).unwrap(), tree_digest(&staged).unwrap());
        let attribute = Command::new("/usr/bin/xattr")
            .args(["-p", "com.qwenpaw.install-fixture"])
            .arg(bundle_executable(&staged))
            .output()
            .unwrap();
        assert!(attribute.status.success());
        assert_eq!(
            String::from_utf8_lossy(&attribute.stdout).trim(),
            "retained"
        );
        fs::write(staged.join("Contents/extra"), b"extra").unwrap();
        assert_ne!(tree_digest(&seed).unwrap(), tree_digest(&staged).unwrap());
    }

    #[test]
    fn links_are_never_followed() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed");
        unsigned_tree(&seed);
        symlink(temp.path(), seed.join("outside")).unwrap();
        assert!(tree_digest(&seed).is_err());
        assert!(copy_tree(&seed, &temp.path().join("staged")).is_err());
    }

    #[test]
    fn install_lock_excludes_other_profiles_and_releases_on_close() {
        let temp = tempfile::tempdir().unwrap();
        let first = installation_lock(temp.path()).unwrap();
        assert!(installation_lock(temp.path()).is_err());
        drop(first);
        assert!(installation_lock(temp.path()).is_ok());
    }

    #[test]
    fn install_lock_rejects_symlink() {
        let temp = tempfile::tempdir().unwrap();
        let sentinel = temp.path().join("unrelated");
        fs::write(&sentinel, b"unchanged").unwrap();
        symlink(
            &sentinel,
            temp.path().join(".qwenpaw-computer-use-install.lock"),
        )
        .unwrap();
        assert!(installation_lock(temp.path()).is_err());
        assert_eq!(fs::read(sentinel).unwrap(), b"unchanged");
    }

    #[test]
    fn signed_install_is_byte_preserving_and_repeat_does_not_replace() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed.app");
        let target = temp.path().join(HELPER_BUNDLE_NAME);
        signed_tree(&seed);
        let before = tree_digest(&seed).unwrap();
        install_verified_bundle(&seed, &target).unwrap();
        assert_eq!(tree_digest(&target).unwrap(), before);
        let inode = fs::metadata(&target).unwrap().ino();
        install_verified_bundle(&seed, &target).unwrap();
        assert_eq!(fs::metadata(&target).unwrap().ino(), inode);
        assert_eq!(tree_digest(&seed).unwrap(), before);
        verify_bundle(&target).unwrap();
    }

    #[test]
    fn tampered_seed_cannot_replace_existing_installation() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed.app");
        let target = temp.path().join(HELPER_BUNDLE_NAME);
        signed_tree(&seed);
        install_verified_bundle(&seed, &target).unwrap();
        let before = tree_digest(&target).unwrap();
        fs::write(
            seed.join("Contents/Frameworks/libqwenpaw_record_replay.dylib"),
            b"tampered",
        )
        .unwrap();
        assert!(install_verified_bundle(&seed, &target).is_err());
        assert_eq!(tree_digest(&target).unwrap(), before);
    }

    #[test]
    fn valid_signature_with_wrong_bundle_id_is_rejected() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed.app");
        signed_tree(&seed);
        let path = seed.join("Contents/Info.plist");
        let value = fs::read_to_string(&path)
            .unwrap()
            .replace(HELPER_IDENTIFIER, "example.wrong-helper");
        fs::write(path, value).unwrap();
        sign_fixture(&seed);
        assert!(verify_bundle(&seed).unwrap_err().contains("identity"));
    }

    #[test]
    fn valid_signature_with_another_launch_executable_is_rejected() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed.app");
        signed_tree(&seed);
        let path = seed.join("Contents/Info.plist");
        let value = fs::read_to_string(&path)
            .unwrap()
            .replace(HELPER_EXECUTABLE_NAME, "another-launch-target");
        fs::write(path, value).unwrap();
        fs::copy(
            bundle_executable(&seed),
            seed.join("Contents/MacOS/another-launch-target"),
        )
        .unwrap();
        // The old entry is now a standalone nested executable. Remove its
        // obsolete Info.plist binding before sealing the new launch target.
        sign_fixture(&bundle_executable(&seed));
        sign_fixture(&seed);
        assert!(Command::new("/usr/bin/codesign")
            .args(["--verify", "--deep", "--strict"])
            .arg(&seed)
            .status()
            .unwrap()
            .success());
        assert!(verify_bundle(&seed).unwrap_err().contains("identity"));
    }

    #[test]
    fn unsigned_seed_is_rejected_before_destination_changes() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("unsigned.app");
        unsigned_tree(&seed);
        let target = temp.path().join(HELPER_BUNDLE_NAME);
        assert!(install_verified_bundle(&seed, &target).is_err());
        assert!(!target.exists());
    }

    #[test]
    fn unexpected_destination_or_backup_is_not_overwritten() {
        let temp = tempfile::tempdir().unwrap();
        let seed = temp.path().join("seed.app");
        signed_tree(&seed);
        for (index, name) in [HELPER_BUNDLE_NAME, HELPER_BACKUP_NAME].iter().enumerate() {
            let parent = temp.path().join(index.to_string());
            fs::create_dir(&parent).unwrap();
            let unexpected = parent.join(name);
            fs::write(&unexpected, b"unrelated file").unwrap();
            let target = parent.join(HELPER_BUNDLE_NAME);
            assert!(install_verified_bundle(&seed, &target)
                .unwrap_err()
                .contains("regular directory"));
            assert_eq!(fs::read(&unexpected).unwrap(), b"unrelated file");
            fs::remove_file(&unexpected).unwrap();
            let outside = parent.join("outside");
            fs::create_dir(&outside).unwrap();
            fs::write(outside.join("sentinel"), b"untouched").unwrap();
            symlink(&outside, &unexpected).unwrap();
            assert!(install_verified_bundle(&seed, &target)
                .unwrap_err()
                .contains("regular directory"));
            assert_eq!(fs::read(outside.join("sentinel")).unwrap(), b"untouched");
        }
    }

    #[test]
    fn failed_activation_recovers_old_directory() {
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join(HELPER_BUNDLE_NAME);
        let backup = temp.path().join(HELPER_BACKUP_NAME);
        unsigned_tree(&target);
        let before = tree_digest(&target).unwrap();
        assert!(activate_bundle(&temp.path().join("missing"), &target, &backup).is_err());
        assert_eq!(tree_digest(&target).unwrap(), before);
        fs::rename(&target, &backup).unwrap();
        recover_installation(&target, &backup).unwrap();
        assert_eq!(tree_digest(&target).unwrap(), before);
        assert!(!backup.exists());
    }
}
