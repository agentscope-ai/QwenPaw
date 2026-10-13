//! Private append-only artifact staging owned by the automation helper.
//!
//! Callers receive relative opaque references only. The root comes from the
//! authenticated EventStream hello and is never accepted back as a request
//! parameter. Final Workspace ownership remains in Python's RecordingStore.

use std::fs::{self, File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, SystemTime};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

const STAGING_PREFIX: &str = ".qwenpaw-automation-staging-";
const STALE_TTL: Duration = Duration::from_secs(60 * 60);
const ARTIFACT_SCHEMA_VERSION: u64 = 1;

pub(super) struct StagingStore {
    root: PathBuf,
    // The open, exclusively locked file proves this process still owns the
    // root. A different Helper may sweep old roots only after this lock is
    // released by orderly shutdown or process death.
    lease: Mutex<Option<File>>,
}

#[derive(Clone, Debug)]
pub(super) struct StagedArtifact {
    pub(super) recording_id: String,
    pub(super) events_ref: String,
    pub(super) metadata_ref: String,
    pub(super) event_count: u64,
    pub(super) dropped_event_count: u64,
    pub(super) last_seq: Option<u64>,
    pub(super) sha256: String,
}

impl StagedArtifact {
    pub(super) fn to_json(&self) -> Value {
        json!({
            "recording_id": self.recording_id,
            "events_ref": self.events_ref,
            "metadata_ref": self.metadata_ref,
            "last_seq": self.last_seq.map_or(-1, |value| value as i64),
            "event_count": self.event_count,
            "dropped_event_count": self.dropped_event_count,
            "sha256": self.sha256,
        })
    }
}

pub(super) struct StagedRecordingWriter {
    directory: PathBuf,
    recording_id: String,
    events_ref: String,
    metadata_ref: String,
    events: BufWriter<File>,
    hasher: Sha256,
    event_count: u64,
    dropped_event_count: u64,
    last_seq: Option<u64>,
}

impl StagingStore {
    pub(super) fn prepare(endpoint: &str) -> Result<Self, String> {
        let parent = staging_parent(endpoint)?;
        fs::create_dir_all(&parent)
            .map_err(|error| format!("failed to create automation staging parent: {error}"))?;
        secure_directory(&parent)?;
        let root = parent.join(format!(
            "{STAGING_PREFIX}{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4(),
        ));
        Ok(Self {
            root,
            lease: Mutex::new(None),
        })
    }

    /// The authenticated client binds this root once during hello. Artifact
    /// requests contain only refs relative to it.
    pub(super) fn root(&self) -> &Path {
        &self.root
    }

    /// Materialize the private root when the first recording starts.
    pub(super) fn initialize(&self) -> Result<&Path, String> {
        let mut lease = self
            .lease
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if lease.is_some() {
            return Ok(&self.root);
        }
        self.cleanup_stale_roots(STALE_TTL)?;
        fs::create_dir(&self.root)
            .map_err(|error| format!("failed to create automation staging root: {error}"))?;
        if let Err(error) = secure_directory(&self.root) {
            let _ = fs::remove_dir(&self.root);
            return Err(error);
        }
        let lease_path = self.root.join(".lease");
        let lease_file = match create_private_file(&lease_path).and_then(lock_staging_root) {
            Ok(file) => file,
            Err(error) => {
                let _ = fs::remove_dir_all(&self.root);
                return Err(error);
            }
        };
        *lease = Some(lease_file);
        Ok(&self.root)
    }

    pub(super) fn create_recording(
        &self,
        recording_id: &str,
    ) -> Result<StagedRecordingWriter, String> {
        let normalized = normalize_recording_id(recording_id)?;
        self.initialize()?;
        let directory = self.root.join(&normalized);
        fs::create_dir(&directory)
            .map_err(|error| format!("failed to create recording staging directory: {error}"))?;
        if let Err(error) = secure_directory(&directory) {
            let _ = fs::remove_dir(&directory);
            return Err(error);
        }
        let events_path = directory.join("events.jsonl");
        let events = match create_private_file(&events_path) {
            Ok(file) => BufWriter::new(file),
            Err(error) => {
                let _ = fs::remove_dir(&directory);
                return Err(error);
            }
        };
        Ok(StagedRecordingWriter {
            directory,
            recording_id: normalized.clone(),
            events_ref: format!("{normalized}/events.jsonl"),
            metadata_ref: format!("{normalized}/metadata.json"),
            events,
            hasher: Sha256::new(),
            event_count: 0,
            dropped_event_count: 0,
            last_seq: None,
        })
    }

    pub(super) fn release(&self, reference: &str) -> Result<bool, String> {
        let (recording_id, _) = parse_artifact_ref(reference)?;
        let directory = self.root.join(recording_id);
        // exists() follows symlinks and also hides access errors as false.
        // Only genuine absence completes cleanup; inspection failures must
        // remain retryable and a dangling symlink must not count as deleted.
        let metadata = match fs::symlink_metadata(&directory) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(error) => return Err(format!("failed to inspect staged recording: {error}")),
        };
        if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
            return Err("staged recording is not a safe directory".to_string());
        }
        fs::remove_dir_all(&directory)
            .map_err(|error| format!("failed to release staged recording: {error}"))?;
        Ok(true)
    }

    fn cleanup_stale_roots(&self, ttl: Duration) -> Result<(), String> {
        let Some(parent) = self.root.parent() else {
            return Err("automation staging root has no parent".to_string());
        };
        cleanup_stale_roots(parent, &self.root, ttl, SystemTime::now())
    }

    pub(super) fn sweep_orphans(&self) -> Result<(), String> {
        self.cleanup_stale_roots(STALE_TTL)
    }
}

impl Drop for StagingStore {
    fn drop(&mut self) {
        let lease = self
            .lease
            .get_mut()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .take();
        drop(lease);
        let _ = fs::remove_file(self.root.join(".lease"));
        // Empty roots are disposable. Non-empty roots contain incomplete or
        // sealed artifacts that survive until release or a later TTL sweep.
        let _ = fs::remove_dir(&self.root);
    }
}

impl StagedRecordingWriter {
    pub(super) fn append_event(&mut self, event: &Value) -> Result<(), String> {
        let seq = event
            .get("seq")
            .and_then(Value::as_u64)
            .ok_or_else(|| "staged event has no valid sequence".to_string())?;
        if self.last_seq.is_some_and(|previous| seq <= previous) {
            return Err("staged event sequence is not increasing".to_string());
        }
        self.write_line(&json!({
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "kind": "event",
            "event": event,
        }))?;
        self.event_count += 1;
        self.last_seq = Some(seq);
        Ok(())
    }

    pub(super) fn append_drop(&mut self, first: u64, last: u64) -> Result<(), String> {
        self.append_gap(first, last, "native_queue_full")
    }

    pub(super) fn append_filtered(&mut self, first: u64, last: u64) -> Result<(), String> {
        self.append_gap(first, last, "privacy_filtered")
    }

    fn append_gap(&mut self, first: u64, last: u64, reason: &'static str) -> Result<(), String> {
        if last < first || self.last_seq.is_some_and(|previous| first <= previous) {
            return Err("staged drop range is invalid".to_string());
        }
        self.write_line(&json!({
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "kind": "drop",
            "first_seq": first,
            "last_seq": last,
            "reason": reason,
        }))?;
        self.dropped_event_count += last - first + 1;
        self.last_seq = Some(last);
        Ok(())
    }

    pub(super) fn flush_barrier(&mut self) -> Result<(), String> {
        self.events
            .flush()
            .and_then(|_| self.events.get_ref().sync_data())
            .map_err(|error| format!("failed to flush staged events: {error}"))
    }

    pub(super) fn counters(&self) -> (u64, u64, Option<u64>) {
        (self.event_count, self.dropped_event_count, self.last_seq)
    }

    pub(super) fn seal(mut self, state: &str) -> Result<StagedArtifact, String> {
        self.flush_barrier()?;
        let sha256 = format!("{:x}", self.hasher.finalize());
        let metadata = json!({
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "state": state,
            "event_count": self.event_count,
            "dropped_event_count": self.dropped_event_count,
            "last_seq": self.last_seq.map_or(-1, |value| value as i64),
            "sha256": sha256,
        });
        let temporary = self.directory.join(".metadata.json.tmp");
        let final_path = self.directory.join("metadata.json");
        let mut file = create_private_file(&temporary)?;
        serde_json::to_writer(&mut file, &metadata)
            .map_err(|error| format!("failed to encode staged metadata: {error}"))?;
        file.write_all(b"\n")
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("failed to persist staged metadata: {error}"))?;
        fs::rename(&temporary, &final_path)
            .map_err(|error| format!("failed to publish staged metadata: {error}"))?;
        sync_directory(&self.directory)?;
        Ok(StagedArtifact {
            recording_id: self.recording_id,
            events_ref: self.events_ref,
            metadata_ref: self.metadata_ref,
            event_count: self.event_count,
            dropped_event_count: self.dropped_event_count,
            last_seq: self.last_seq,
            sha256,
        })
    }

    fn write_line(&mut self, value: &Value) -> Result<(), String> {
        let mut payload = serde_json::to_vec(value)
            .map_err(|error| format!("failed to encode staged event: {error}"))?;
        payload.push(b'\n');
        self.events
            .write_all(&payload)
            .map_err(|error| format!("failed to append staged event: {error}"))?;
        self.hasher.update(&payload);
        Ok(())
    }
}

fn normalize_recording_id(value: &str) -> Result<String, String> {
    let parsed =
        uuid::Uuid::parse_str(value).map_err(|_| "recording_id must be a UUID".to_string())?;
    Ok(parsed.to_string())
}

fn parse_artifact_ref(reference: &str) -> Result<(&str, &str), String> {
    let path = Path::new(reference);
    if path.is_absolute() {
        return Err("artifact reference must be relative".to_string());
    }
    let components = path.components().collect::<Vec<_>>();
    if components.len() != 2
        || components
            .iter()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err("artifact reference has an invalid shape".to_string());
    }
    let recording_id = components[0]
        .as_os_str()
        .to_str()
        .ok_or_else(|| "artifact reference is not UTF-8".to_string())?;
    normalize_recording_id(recording_id)?;
    let name = components[1]
        .as_os_str()
        .to_str()
        .ok_or_else(|| "artifact reference is not UTF-8".to_string())?;
    if !matches!(name, "events.jsonl" | "metadata.json") {
        return Err("artifact reference names an unsupported file".to_string());
    }
    Ok((recording_id, name))
}

fn cleanup_stale_roots(
    parent: &Path,
    current: &Path,
    ttl: Duration,
    now: SystemTime,
) -> Result<(), String> {
    let entries = fs::read_dir(parent)
        .map_err(|error| format!("failed to scan automation staging parent: {error}"))?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path == current
            || !entry
                .file_name()
                .to_string_lossy()
                .starts_with(STAGING_PREFIX)
        {
            continue;
        }
        let Ok(metadata) = fs::symlink_metadata(&path) else {
            continue;
        };
        if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
            continue;
        }
        let stale = metadata
            .modified()
            .ok()
            .and_then(|modified| now.duration_since(modified).ok())
            .is_some_and(|age| age >= ttl);
        if stale && !staging_root_is_live(&path) {
            let _ = fs::remove_dir_all(path);
        }
    }
    Ok(())
}

#[cfg(all(target_os = "macos", test))]
fn staging_parent(endpoint: &str) -> Result<PathBuf, String> {
    Path::new(endpoint)
        .parent()
        .map(Path::to_path_buf)
        .ok_or_else(|| "Computer Use endpoint has no staging parent".to_string())
}

#[cfg(any(windows, all(target_os = "macos", not(test))))]
fn staging_parent(_endpoint: &str) -> Result<PathBuf, String> {
    dirs::data_local_dir()
        .map(|root| root.join("QwenPaw").join("automation-staging"))
        .ok_or_else(|| "local application data directory is unavailable".to_string())
}

#[cfg(unix)]
fn lock_staging_root(file: File) -> Result<File, String> {
    use std::os::fd::AsRawFd;
    let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if result == 0 {
        Ok(file)
    } else {
        Err(format!(
            "failed to lock automation staging root: {}",
            std::io::Error::last_os_error(),
        ))
    }
}

#[cfg(windows)]
fn lock_staging_root(file: File) -> Result<File, String> {
    Ok(file)
}

#[cfg(unix)]
fn staging_root_is_live(path: &Path) -> bool {
    use std::os::fd::AsRawFd;
    use std::os::unix::fs::OpenOptionsExt;
    let Ok(file) = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path.join(".lease"))
    else {
        return false;
    };
    let result = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if result == 0 {
        let _ = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_UN) };
        false
    } else {
        std::io::Error::last_os_error()
            .raw_os_error()
            .is_some_and(|code| code == libc::EWOULDBLOCK || code == libc::EAGAIN)
    }
}

#[cfg(windows)]
fn staging_root_is_live(_path: &Path) -> bool {
    false
}

#[cfg(unix)]
fn create_private_file(path: &Path) -> Result<File, String> {
    use std::os::unix::fs::OpenOptionsExt;
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)
        .map_err(|error| format!("failed to create private staging file: {error}"))
}

#[cfg(windows)]
fn create_private_file(path: &Path) -> Result<File, String> {
    OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("failed to create private staging file: {error}"))
}

#[cfg(unix)]
fn secure_directory(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o700))
        .map_err(|error| format!("failed to secure automation staging directory: {error}"))?;
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("failed to inspect automation staging directory: {error}"))?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err("automation staging path is not a private directory".to_string());
    }
    Ok(())
}

#[cfg(windows)]
fn secure_directory(path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("failed to inspect automation staging directory: {error}"))?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err("automation staging path is not a private directory".to_string());
    }
    Ok(())
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), String> {
    File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|error| format!("failed to sync staging directory: {error}"))
}

#[cfg(windows)]
fn sync_directory(_path: &Path) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writer_seals_append_only_events_and_metadata() {
        let endpoint_dir = tempfile::tempdir().unwrap();
        let endpoint = endpoint_dir.path().join("helper.sock");
        let store = StagingStore::prepare(endpoint.to_str().unwrap()).unwrap();
        let recording_id = uuid::Uuid::new_v4().to_string();
        let mut writer = store.create_recording(&recording_id).unwrap();
        writer
            .append_event(&json!({"seq": 0, "type": "click"}))
            .unwrap();
        writer.append_drop(1, 2).unwrap();
        writer
            .append_event(&json!({"seq": 3, "type": "scroll"}))
            .unwrap();
        let artifact = writer.seal("completed").unwrap();

        assert_eq!(artifact.event_count, 2);
        assert_eq!(artifact.dropped_event_count, 2);
        assert_eq!(artifact.last_seq, Some(3));
        assert_eq!(artifact.sha256.len(), 64);
        assert!(store.root().join(&artifact.events_ref).is_file());
        assert!(store.root().join(&artifact.metadata_ref).is_file());
        assert!(store.release(&artifact.events_ref).unwrap());
        assert!(!store.release(&artifact.metadata_ref).unwrap());
    }

    #[test]
    fn invalid_refs_and_sequences_are_rejected() {
        let endpoint_dir = tempfile::tempdir().unwrap();
        let endpoint = endpoint_dir.path().join("helper.sock");
        let store = StagingStore::prepare(endpoint.to_str().unwrap()).unwrap();
        let recording_id = uuid::Uuid::new_v4().to_string();
        let mut writer = store.create_recording(&recording_id).unwrap();
        writer.append_drop(0, 2).unwrap();
        assert!(writer
            .append_event(&json!({"seq": 2, "type": "click"}))
            .is_err());
        assert!(store.release("../events.jsonl").is_err());
        assert!(store
            .release(&format!("{recording_id}/secret.txt"))
            .is_err());
    }

    #[cfg(unix)]
    #[test]
    fn staging_paths_are_owner_only_and_lazy() {
        use std::os::unix::fs::PermissionsExt;
        let endpoint_dir = tempfile::tempdir().unwrap();
        let endpoint = endpoint_dir.path().join("helper.sock");
        let store = StagingStore::prepare(endpoint.to_str().unwrap()).unwrap();
        assert!(!store.root().exists());
        store.initialize().unwrap();
        store.initialize().unwrap();
        let mode = fs::metadata(store.root()).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, 0o700);
    }

    #[test]
    fn stale_helper_roots_are_cleaned_without_following_symlinks() {
        let parent = tempfile::tempdir().unwrap();
        let stale = parent.path().join(format!("{STAGING_PREFIX}stale"));
        fs::create_dir(&stale).unwrap();
        let current = parent.path().join(format!("{STAGING_PREFIX}current"));
        cleanup_stale_roots(parent.path(), &current, Duration::ZERO, SystemTime::now()).unwrap();
        assert!(!stale.exists());
    }

    #[cfg(unix)]
    #[test]
    fn a_live_staging_root_is_never_swept() {
        let parent = tempfile::tempdir().unwrap();
        let live = parent.path().join(format!("{STAGING_PREFIX}live"));
        fs::create_dir(&live).unwrap();
        let lease = lock_staging_root(create_private_file(&live.join(".lease")).unwrap()).unwrap();
        let current = parent.path().join(format!("{STAGING_PREFIX}current"));

        cleanup_stale_roots(parent.path(), &current, Duration::ZERO, SystemTime::now()).unwrap();
        assert!(live.exists());

        drop(lease);
        cleanup_stale_roots(parent.path(), &current, Duration::ZERO, SystemTime::now()).unwrap();
        assert!(!live.exists());
    }
}
