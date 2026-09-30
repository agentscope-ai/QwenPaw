//! Process-wide EventStream recording engine.
//!
//! One authenticated EventStream connection owns the active session. Native
//! callbacks enqueue fixed primitives, a dedicated worker enriches and writes
//! privacy-minimized JSONL, and stop returns only sealed artifact references.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};
use tokio::sync::mpsc;

use super::device_coordinator::{DeviceCoordinator, RecordingLease};
use super::event_stream_native::{self as native, NativeInputEvent, NativeInputSource};
use super::indicator::Activity;
use super::permission_broker::{PermissionBroker, PermissionStatus};
use super::staging::{StagedArtifact, StagedRecordingWriter, StagingStore};

const NATIVE_QUEUE_LIMIT: usize = 1024;
const MAINTENANCE_INTERVAL: Duration = Duration::from_millis(250);
const ARTIFACT_RETENTION: Duration = Duration::from_secs(60 * 60);
const MAX_TERMINAL_FAILURES: usize = 128;
static EMERGENCY_RECORDER: OnceLock<Mutex<Weak<EventStreamRecorder>>> = OnceLock::new();

// Artifact retention must advance while a Mac is asleep. std::time::Instant
// uses mach_absolute_time there, which pauses during sleep. Keep capture
// durations on Instant, but use the OS continuous monotonic clock for expiry.
#[cfg(target_os = "macos")]
fn retention_now() -> Duration {
    #[repr(C)]
    struct Timebase {
        numer: u32,
        denom: u32,
    }
    extern "C" {
        fn mach_continuous_time() -> u64;
        fn mach_timebase_info(info: *mut Timebase) -> i32;
    }
    static TIMEBASE: OnceLock<Timebase> = OnceLock::new();
    let scale = TIMEBASE.get_or_init(|| {
        let mut info = Timebase { numer: 0, denom: 0 };
        // Valid non-null storage for the two fields defined by mach_time.h.
        assert_eq!(unsafe { mach_timebase_info(&mut info) }, 0);
        assert!(info.numer > 0 && info.denom > 0);
        info
    });
    // Available since macOS 10.12, below this app's macOS 14 minimum. The
    // intermediate is wide enough for the full u64 ticks * u32 numerator.
    let nanos = u128::from(unsafe { mach_continuous_time() }) * u128::from(scale.numer)
        / u128::from(scale.denom);
    Duration::new(
        u64::try_from(nanos / 1_000_000_000).expect("retention clock exceeds Duration range"),
        (nanos % 1_000_000_000) as u32,
    )
}

#[cfg(not(target_os = "macos"))]
fn retention_now() -> Duration {
    static EPOCH: OnceLock<Instant> = OnceLock::new();
    EPOCH.get_or_init(Instant::now).elapsed()
}

type NativeResult<T> = Result<T, (&'static str, String)>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RecordingPhase {
    Recording,
    Paused,
}

impl RecordingPhase {
    fn as_str(self) -> &'static str {
        match self {
            Self::Recording => "recording",
            Self::Paused => "paused",
        }
    }
}

#[derive(Default)]
struct Progress {
    event_count: u64,
    dropped_event_count: u64,
    last_seq: Option<u64>,
    failure: Option<String>,
    interruption: Option<&'static str>,
}

struct WorkerResult {
    writer: StagedRecordingWriter,
    failure: Option<String>,
}

struct ActiveRecording {
    owner: u64,
    recording_id: String,
    phase: RecordingPhase,
    started: Instant,
    capture_generation: u64,
    next_seq: Arc<AtomicU64>,
    progress: Arc<Mutex<Progress>>,
    source: Option<NativeInputSource>,
    worker: Option<JoinHandle<WorkerResult>>,
    draining: Option<Arc<AtomicBool>>,
    writer: Option<StagedRecordingWriter>,
    _lease: RecordingLease,
}

struct RecorderState {
    active: Option<ActiveRecording>,
    sealed: HashMap<String, SealedRecording>,
    cleanup_pending: HashSet<String>,
    failures: VecDeque<(String, &'static str)>,
    next_orphan_sweep: Duration,
}

struct SealedRecording {
    artifact: StagedArtifact,
    expires_at: Duration,
}

pub(super) struct EventStreamRecorder {
    state: Mutex<RecorderState>,
    devices: Arc<DeviceCoordinator>,
    staging: Arc<StagingStore>,
    native_available: bool,
    native_error: Option<String>,
    maintenance_started: Mutex<bool>,
}

impl EventStreamRecorder {
    pub(super) fn prepare(
        devices: Arc<DeviceCoordinator>,
        staging: Arc<StagingStore>,
    ) -> Arc<Self> {
        let native_result = native::load();
        let recorder = Arc::new(Self {
            state: Mutex::new(RecorderState {
                active: None,
                sealed: HashMap::new(),
                cleanup_pending: HashSet::new(),
                failures: VecDeque::new(),
                next_orphan_sweep: retention_now(),
            }),
            devices,
            staging,
            native_available: native_result.is_ok(),
            native_error: native_result.err(),
            maintenance_started: Mutex::new(false),
        });
        *EMERGENCY_RECORDER
            .get_or_init(|| Mutex::new(Weak::new()))
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Arc::downgrade(&recorder);
        recorder
    }

    pub(super) fn is_available(&self) -> bool {
        self.native_available
    }

    pub(super) fn artifact_root(&self) -> &std::path::Path {
        self.staging.root()
    }

    pub(super) fn permission_status(&self) -> PermissionStatus {
        PermissionBroker::recording_status()
    }

    pub(super) fn request_permissions(&self) -> NativeResult<Value> {
        if !self.native_available {
            return Err((
                "native_runtime_unavailable",
                self.native_error
                    .clone()
                    .unwrap_or_else(|| "EventStream native runtime is unavailable.".to_string()),
            ));
        }
        PermissionBroker.request_recording();
        Ok(permission_json(PermissionBroker::recording_status()))
    }

    pub(super) fn start(self: &Arc<Self>, owner: u64, recording_id: &str) -> NativeResult<Value> {
        if !self.native_available {
            return Err((
                "native_runtime_unavailable",
                self.native_error
                    .clone()
                    .unwrap_or_else(|| "EventStream native runtime is unavailable.".to_string()),
            ));
        }
        PermissionBroker.ensure_recording()?;
        let capture_generation = native::capture_guard().map_err(native_error)?;
        self.ensure_maintenance()?;
        self.maintain(retention_now());
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if state.active.is_some() {
            return Err((
                "recording_active",
                "Another EventStream recording is active.".to_string(),
            ));
        }
        if state.sealed.contains_key(recording_id) {
            return Err((
                "recording_exists",
                "This recording already has a sealed staging artifact.".to_string(),
            ));
        }
        if state.failures.iter().any(|(id, _)| id == recording_id) {
            return Err(("recording_exists", "Use a new recording id.".to_string()));
        }
        if !state.cleanup_pending.is_empty() {
            return Err((
                "staging_cleanup_pending",
                "Staging cleanup must recover before recording.".to_string(),
            ));
        }
        let lease = self.devices.try_recording(recording_id)?;
        let writer = self
            .staging
            .create_recording(recording_id)
            .map_err(|message| ("staging_failed", message))?;
        let progress = Arc::new(Mutex::new(Progress::default()));
        let mut active = ActiveRecording {
            owner,
            recording_id: recording_id.to_string(),
            phase: RecordingPhase::Recording,
            started: Instant::now(),
            capture_generation,
            next_seq: Arc::new(AtomicU64::new(0)),
            progress,
            source: None,
            worker: None,
            draining: None,
            writer: Some(writer),
            _lease: lease,
        };
        if let Err(error) = active.start_segment() {
            drop(active);
            self.release_or_schedule(&mut state, recording_id);
            return Err(error);
        }
        let result = json!({
            "recording_id": recording_id,
            "state": "recording",
        });
        state.active = Some(active);
        Ok(result)
    }

    pub(super) fn status(&self) -> Value {
        self.recording_status(None)
    }

    pub(super) fn recording_status(&self, recording_id: Option<&str>) -> Value {
        let state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let permissions = permission_json(self.permission_status());
        if let Some(id) = recording_id {
            if let Some((_, code)) = state.failures.iter().find(|(failed_id, _)| failed_id == id) {
                return json!({
                    "available": self.native_available, "native_error": self.native_error,
                    "state": "failed", "recording_id": id, "failure": code,
                    "permissions": permissions, "cleanup_pending": state.cleanup_pending.len(),
                });
            }
        }
        let active = state
            .active
            .as_ref()
            .filter(|active| {
                recording_id.map_or(true, |id| id == active.recording_id)
            });
        let Some(active) = active else {
            return json!({
                "available": self.native_available,
                "native_error": self.native_error,
                "state": "idle",
                "permissions": permissions,
                "cleanup_pending": state.cleanup_pending.len(),
            });
        };
        let progress = active
            .progress
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        json!({
            "available": self.native_available,
            "native_error": self.native_error,
            "state": active.phase.as_str(),
            "recording_id": active.recording_id,
            "duration_ms": active.started.elapsed().as_millis() as u64,
            "event_count": progress.event_count,
            "dropped_event_count": progress.dropped_event_count,
            "last_seq": progress.last_seq.map_or(-1, |value| value as i64),
            "failure": progress.failure.as_ref().map(|_| "staging_failed"),
            "permissions": permissions,
            "cleanup_pending": state.cleanup_pending.len(),
        })
    }

    pub(super) fn pause(&self, owner: u64, recording_id: &str) -> NativeResult<Value> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut active = take_owned_active(&mut state, owner, recording_id)?;
        if active.phase != RecordingPhase::Recording {
            state.active = Some(active);
            return Err((
                "recording_not_active",
                "The EventStream recording is not active.".to_string(),
            ));
        }
        if let Err(error) = active.finish_segment() {
            remember_failure(&mut state, recording_id, error.0);
            self.cancel_active(&mut state, active);
            return Err(error);
        }
        active.phase = RecordingPhase::Paused;
        let result = active.snapshot();
        state.active = Some(active);
        Ok(result)
    }

    pub(super) fn resume(&self, owner: u64, recording_id: &str) -> NativeResult<Value> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let mut active = take_owned_active(&mut state, owner, recording_id)?;
        if active.phase != RecordingPhase::Paused {
            state.active = Some(active);
            return Err((
                "recording_not_paused",
                "The EventStream recording is not paused.".to_string(),
            ));
        }
        if let Err(code) = capture_check(active.capture_generation) {
            remember_failure(&mut state, recording_id, code);
            self.cancel_active(&mut state, active);
            return Err(native_error(code));
        }
        if let Err(error) = active.start_segment() {
            remember_failure(&mut state, recording_id, error.0);
            self.cancel_active(&mut state, active);
            return Err(error);
        }
        active.phase = RecordingPhase::Recording;
        let result = active.snapshot();
        state.active = Some(active);
        Ok(result)
    }

    pub(super) fn stop(&self, owner: u64, recording_id: &str) -> NativeResult<Value> {
        self.maintain(retention_now());
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        // A response can be lost after seal but before the client receives
        // it. The sealed artifact is process-owned, so a re-authenticated
        // backend connection may recover the same result by recording id.
        if let Some(artifact) = state.sealed.get(recording_id) {
            return Ok(artifact.artifact.to_json());
        }
        if let Some((_, code)) = state.failures.iter().find(|(id, _)| id == recording_id) {
            return Err((*code, "Recording is no longer available.".to_string()));
        }
        let Some(mut active) = state.active.take() else {
            return Err((
                "recording_not_found",
                "No EventStream recording is active.".to_string(),
            ));
        };
        if active.owner != owner || active.recording_id != recording_id {
            state.active = Some(active);
            return Err((
                "recording_not_owned",
                "The active EventStream recording belongs to another connection.".to_string(),
            ));
        }
        if active.phase == RecordingPhase::Recording {
            if let Err(error) = active.finish_segment() {
                remember_failure(&mut state, recording_id, error.0);
                self.cancel_active(&mut state, active);
                return Err(error);
            }
        }
        if let Err(code) = capture_check(active.capture_generation) {
            remember_failure(&mut state, recording_id, code);
            self.cancel_active(&mut state, active);
            return Err(native_error(code));
        }
        let Some(writer) = active.writer.take() else {
            remember_failure(&mut state, recording_id, "recording_failed");
            self.cancel_active(&mut state, active);
            return Err((
                "recording_failed",
                "The EventStream writer is unavailable.".to_string(),
            ));
        };
        let artifact = match writer.seal("completed") {
            Ok(artifact) => artifact,
            Err(message) => {
                drop(active);
                remember_failure(&mut state, recording_id, "staging_failed");
                self.release_or_schedule(&mut state, recording_id);
                return Err(("staging_failed", message));
            }
        };
        let result = artifact.to_json();
        state.sealed.insert(
            artifact.recording_id.clone(),
            SealedRecording {
                artifact,
                expires_at: retention_now() + ARTIFACT_RETENTION,
            },
        );
        // Dropping active releases the long Record lease only after native
        // callbacks have stopped and the file has crossed its flush barrier.
        drop(active);
        Ok(result)
    }

    pub(super) fn cancel(&self, owner: u64, recording_id: &str) -> NativeResult<Value> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(active) = state.active.take() else {
            return Ok(json!({"recording_id": recording_id, "cancelled": false}));
        };
        if active.owner != owner || active.recording_id != recording_id {
            state.active = Some(active);
            return Err((
                "recording_not_owned",
                "The active EventStream recording belongs to another connection.".to_string(),
            ));
        }
        self.cancel_active(&mut state, active);
        Ok(json!({"recording_id": recording_id, "cancelled": true}))
    }

    pub(super) fn release(&self, events_ref: &str) -> NativeResult<Value> {
        let recording_id = events_ref.split('/').next().unwrap_or_default();
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if !state.sealed.contains_key(recording_id) && !state.cleanup_pending.contains(recording_id)
        {
            return Ok(json!({"released": false}));
        }
        if format!("{recording_id}/events.jsonl") != events_ref {
            return Err((
                "invalid_artifact_ref",
                "The artifact reference does not match a sealed recording.".to_string(),
            ));
        }
        // Release revokes logical access even when filesystem deletion fails.
        state.sealed.remove(recording_id);
        match self.staging.release(events_ref) {
            Ok(released) => {
                state.cleanup_pending.remove(recording_id);
                Ok(json!({"released": released}))
            }
            Err(_) => {
                state.cleanup_pending.insert(recording_id.to_string());
                Err((
                    "staging_cleanup_pending",
                    "Staging deletion will be retried.".to_string(),
                ))
            }
        }
    }

    pub(super) fn disconnect(&self, owner: u64) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(active) = state.active.take() else {
            return;
        };
        if active.owner == owner {
            self.cancel_active(&mut state, active);
        } else {
            state.active = Some(active);
        }
    }

    fn emergency_stop(&self) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(active) = state.active.take() else {
            return false;
        };
        // Stop the native source and cross its callback/flush barriers before
        // the RAII lease can return the device to Computer Use.
        self.cancel_active(&mut state, active);
        true
    }

    fn cancel_active(&self, state: &mut RecorderState, mut active: ActiveRecording) {
        if active.source.is_some() {
            let _ = active.finish_segment();
        }
        let recording_id = active.recording_id.clone();
        drop(active);
        self.release_or_schedule(state, &recording_id);
    }

    fn release_or_schedule(&self, state: &mut RecorderState, recording_id: &str) {
        if self
            .staging
            .release(&format!("{recording_id}/events.jsonl"))
            .is_err()
        {
            state.cleanup_pending.insert(recording_id.to_string());
        } else {
            state.cleanup_pending.remove(recording_id);
        }
    }

    fn ensure_maintenance(self: &Arc<Self>) -> NativeResult<()> {
        let mut started = self
            .maintenance_started
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if *started {
            return Ok(());
        }
        let weak = Arc::downgrade(self);
        if thread::Builder::new()
            .name("event-stream-lifecycle".to_string())
            .spawn(move || loop {
                thread::sleep(MAINTENANCE_INTERVAL);
                let Some(recorder) = weak.upgrade() else {
                    break;
                };
                recorder.maintain(retention_now());
            })
            .is_err()
        {
            return Err((
                "recording_failed",
                "Failed to start recording lifecycle maintenance.".to_string(),
            ));
        }
        *started = true;
        Ok(())
    }

    fn maintain(&self, now: Duration) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let failure = state.active.as_ref().and_then(|active| {
            // Both active and paused sessions lose their lease on revocation.
            // This read-only check must not request TCC access or depend on UI
            // polling. Stop uses this same barrier before sealing evidence.
            if let Err(code) = capture_check(active.capture_generation) {
                return Some(code);
            }
            let progress = active
                .progress
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if let Some(code) = progress.interruption {
                Some(code)
            } else if progress.failure.is_some() {
                Some("staging_failed")
            } else if active.worker.as_ref().is_some_and(JoinHandle::is_finished) {
                Some("recording_failed")
            } else {
                None
            }
        });
        if let Some(code) = failure {
            let active = state
                .active
                .take()
                .expect("failure requires an active recording");
            remember_failure(&mut state, &active.recording_id, code);
            // This is not the writer thread: joining it cannot self-deadlock.
            // Keep the state lock until capture and its lease are both gone.
            self.cancel_active(&mut state, active);
        }
        let expired: Vec<String> = state
            .sealed
            .iter()
            .filter(|(_, sealed)| sealed.expires_at <= now)
            .map(|(id, _)| id.clone())
            .collect();
        for id in expired {
            state.sealed.remove(&id);
            remember_failure(&mut state, &id, "recording_expired");
            state.cleanup_pending.insert(id);
        }
        for id in state.cleanup_pending.clone() {
            self.release_or_schedule(&mut state, &id);
        }
        if now >= state.next_orphan_sweep {
            // A long-lived Helper also collects roots orphaned after its own
            // first initialize; live foreign leases remain protected.
            let _ = self.staging.sweep_orphans();
            state.next_orphan_sweep = now + Duration::from_secs(60);
        }
    }
}

fn remember_failure(state: &mut RecorderState, id: &str, code: &'static str) {
    state.failures.retain(|(existing, _)| existing != id);
    state.failures.push_back((id.to_string(), code));
    if state.failures.len() > MAX_TERMINAL_FAILURES {
        state.failures.pop_front();
    }
}

pub(super) fn native_activity_presenter(activity: Activity) {
    native::set_activity_indicator(activity as u32, Some(native_emergency_stop));
}

unsafe extern "C" fn native_emergency_stop() {
    let recorder = EMERGENCY_RECORDER.get().and_then(|target| {
        target
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .upgrade()
    });
    if let Some(recorder) = recorder {
        recorder.emergency_stop();
    }
}

impl ActiveRecording {
    fn start_segment(&mut self) -> NativeResult<()> {
        capture_check(self.capture_generation).map_err(native_error)?;
        let writer = self.writer.take().ok_or((
            "recording_failed",
            "The EventStream writer is unavailable.".to_string(),
        ))?;
        let (sender, receiver) = mpsc::channel(NATIVE_QUEUE_LIMIT);
        let mut source =
            NativeInputSource::create(sender, Arc::clone(&self.next_seq)).map_err(native_error)?;
        source.start().map_err(native_error)?;
        let next_seq = Arc::clone(&self.next_seq);
        let progress = Arc::clone(&self.progress);
        let draining = Arc::new(AtomicBool::new(false));
        let worker_draining = Arc::clone(&draining);
        let capture_generation = self.capture_generation;
        let worker = thread::Builder::new()
            .name("event-stream-writer".to_string())
            .spawn(move || {
                run_worker(
                    receiver,
                    next_seq,
                    progress,
                    worker_draining,
                    writer,
                    capture_generation,
                )
            })
            .map_err(|error| {
                let _ = source.stop();
                (
                    "recording_failed",
                    format!("failed to start EventStream writer: {error}"),
                )
            })?;
        self.source = Some(source);
        self.worker = Some(worker);
        self.draining = Some(draining);
        Ok(())
    }

    fn finish_segment(&mut self) -> NativeResult<()> {
        if let Some(draining) = self.draining.take() {
            // At most the currently-running AX enrichment may still block.
            // Queued events without a verified app become anonymous privacy
            // gaps, keeping stop bounded without persisting unclassified input.
            draining.store(true, Ordering::Release);
        }
        let mut source = self.source.take().ok_or((
            "recording_failed",
            "The EventStream native source is unavailable.".to_string(),
        ))?;
        let stop_result = source.stop().map_err(native_error);
        drop(source);
        let worker = self.worker.take().ok_or((
            "recording_failed",
            "The EventStream writer worker is unavailable.".to_string(),
        ))?;
        let result = worker.join().map_err(|_| {
            (
                "recording_failed",
                "The EventStream writer worker panicked.".to_string(),
            )
        })?;
        self.writer = Some(result.writer);
        stop_result?;
        if let Some(code) = self
            .progress
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .interruption
        {
            return Err(native_error(code));
        }
        if let Some(failure) = result.failure {
            return Err(("staging_failed", failure));
        }
        self.writer
            .as_mut()
            .expect("writer restored after worker join")
            .flush_barrier()
            .map_err(|message| ("staging_failed", message))
    }

    fn snapshot(&self) -> Value {
        let progress = self
            .progress
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        json!({
            "recording_id": self.recording_id,
            "state": self.phase.as_str(),
            "event_count": progress.event_count,
            "dropped_event_count": progress.dropped_event_count,
            "last_seq": progress.last_seq.map_or(-1, |value| value as i64),
        })
    }
}

fn take_owned_active(
    state: &mut RecorderState,
    owner: u64,
    recording_id: &str,
) -> NativeResult<ActiveRecording> {
    let active = state.active.take().ok_or((
        "recording_not_found",
        "No EventStream recording is active.".to_string(),
    ))?;
    if active.owner != owner || active.recording_id != recording_id {
        state.active = Some(active);
        return Err((
            "recording_not_owned",
            "The active EventStream recording belongs to another connection.".to_string(),
        ));
    }
    Ok(active)
}

fn run_worker(
    mut receiver: mpsc::Receiver<NativeInputEvent>,
    next_seq: Arc<AtomicU64>,
    progress: Arc<Mutex<Progress>>,
    draining: Arc<AtomicBool>,
    mut writer: StagedRecordingWriter,
    capture_generation: u64,
) -> WorkerResult {
    let mut expected_seq = writer.counters().2.map_or(0, |last| last.saturating_add(1));
    let mut failure = None;
    while let Some(event) = receiver.blocking_recv() {
        if let Err(code) = capture_check(capture_generation) {
            progress
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .interruption = Some(code);
            break;
        }
        if event.seq < expected_seq {
            failure = Some("native event sequence moved backwards".to_string());
            break;
        }
        if event.seq > expected_seq {
            if let Err(error) = writer.append_drop(expected_seq, event.seq - 1) {
                failure = Some(error);
                break;
            }
        }
        let value = event_to_json(&event, !draining.load(Ordering::Acquire));
        // AX enrichment can outlive a permission/desktop transition. Reject
        // its result before raw staging, not only during Python import.
        if let Err(code) = capture_check(capture_generation) {
            progress
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .interruption = Some(code);
            break;
        }
        let written = match value {
            Some(value) => writer.append_event(&value),
            None => writer.append_filtered(event.seq, event.seq),
        };
        if let Err(error) = written {
            failure = Some(error);
            break;
        }
        expected_seq = event.seq + 1;
        update_progress(&progress, &writer, None);
    }
    let assigned = next_seq.load(Ordering::Acquire);
    if failure.is_none() && expected_seq < assigned {
        if let Err(error) = writer.append_drop(expected_seq, assigned - 1) {
            failure = Some(error);
        }
    }
    update_progress(&progress, &writer, failure.as_deref());
    WorkerResult { writer, failure }
}

fn capture_check(expected_generation: u64) -> Result<(), &'static str> {
    if !PermissionBroker::recording_granted() {
        return Err("recording_permission_revoked");
    }
    let generation = native::capture_guard()?;
    if generation != expected_generation {
        return Err("recording_environment_changed");
    }
    Ok(())
}

fn update_progress(
    progress: &Mutex<Progress>,
    writer: &StagedRecordingWriter,
    failure: Option<&str>,
) {
    let (event_count, dropped_event_count, last_seq) = writer.counters();
    let mut progress = progress
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    progress.event_count = event_count;
    progress.dropped_event_count = dropped_event_count;
    progress.last_seq = last_seq;
    if let Some(failure) = failure {
        progress.failure = Some(failure.to_string());
    }
}

fn event_to_json(event: &NativeInputEvent, enrich: bool) -> Option<Value> {
    if !enrich {
        return None;
    }
    let enrichment = native::enrich_event(event).ok()?;
    project_recordable_event(event, &enrichment)
}

fn recordable_app(value: Option<&Value>) -> bool {
    let Some(app) = project_object(value, &["bundle_id", "name", "pid"]) else {
        return false;
    };
    let Some(id) = app.get("bundle_id").and_then(Value::as_str) else {
        return false;
    };
    if id.is_empty()
        || !id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b".-_".contains(&b))
    {
        return false;
    }
    let id = id.to_ascii_lowercase();
    ![
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.bitwarden.desktop",
        "com.lastpass.lastpass",
    ]
    .iter()
    .any(|root| {
        id == *root
            || id
                .strip_prefix(root)
                .is_some_and(|suffix| suffix.starts_with('.'))
    })
}

fn project_recordable_event(event: &NativeInputEvent, enrichment: &Value) -> Option<Value> {
    // capture_app is transient evidence, never part of an on-disk event.
    if !recordable_app(enrichment.get("capture_app")) || !recordable_app(enrichment.get("app")) {
        return None;
    }
    let mut payload = primitive_event_to_json(event);
    merge_allowlisted_enrichment(&mut payload, enrichment);
    Some(payload)
}

fn primitive_event_to_json(event: &NativeInputEvent) -> Value {
    // Source PID is used by the callback to exclude Helper-generated input but
    // is deliberately not persisted in the artifact event.
    let _source_pid = event.source_pid;
    let (event_type, input, redacted) = match event.event_type {
        1 | 3 | 25 => (
            "pointer_down",
            json!({
                "button": button_name(event.button),
                "click_count": event.click_count.max(0),
                "modifiers": modifier_names(event.flags),
                "phase": "down",
                "x": event.x,
                "y": event.y,
            }),
            false,
        ),
        2 | 4 | 26 => (
            "pointer_up",
            json!({
                "button": button_name(event.button),
                "click_count": event.click_count.max(0),
                "modifiers": modifier_names(event.flags),
                "phase": "up",
                "x": event.x,
                "y": event.y,
            }),
            false,
        ),
        6 | 7 | 27 => (
            "drag",
            json!({
                "button": button_name(event.button),
                "modifiers": modifier_names(event.flags),
                "phase": "update",
                "x": event.x,
                "y": event.y,
            }),
            false,
        ),
        10 | 11 => {
            let (key_class, length) = key_class(event.key_code);
            (
                if event.event_type == 10 {
                    "key_down"
                } else {
                    "key_up"
                },
                json!({
                    "key_class": key_class,
                    "length": length,
                    "modifiers": modifier_names(event.flags),
                    "phase": if event.event_type == 10 { "down" } else { "up" },
                }),
                true,
            )
        }
        12 => (
            "modifier_change",
            json!({
                "key_class": "modifier",
                "length": 0,
                "modifiers": modifier_names(event.flags),
                "phase": "change",
            }),
            true,
        ),
        22 => (
            "scroll",
            json!({
                "delta_x": event.scroll_x,
                "delta_y": event.scroll_y,
                "modifiers": modifier_names(event.flags),
                "x": event.x,
                "y": event.y,
            }),
            false,
        ),
        _ => ("unknown", json!({}), true),
    };
    json!({
        "event_schema_version": 1,
        "seq": event.seq,
        "t_monotonic_ms": event.monotonic_ns / 1_000_000,
        "type": event_type,
        "input": input,
        "redaction": {
            "redacted": redacted,
            "reasons": if redacted { vec!["native_text_minimized"] } else { Vec::<&str>::new() },
        },
    })
}

fn merge_allowlisted_enrichment(payload: &mut Value, enrichment: &Value) {
    let Some(source) = enrichment.as_object() else {
        set_enrichment_unavailable(payload, "native_enrichment_invalid_contract");
        return;
    };
    let Some(destination) = payload.as_object_mut() else {
        return;
    };
    if let Some(app) = project_object(source.get("app"), &["bundle_id", "name", "pid"]) {
        destination.insert("app".to_string(), Value::Object(app));
    }
    if let Some(window) = project_object(source.get("window"), &["bounds", "role", "title"]) {
        destination.insert("window".to_string(), Value::Object(window));
    }
    if let Some(mut target) = project_object(
        source.get("target"),
        &["bounds", "identifier", "name", "role", "secure", "subrole"],
    ) {
        let secure = target.get("secure").and_then(Value::as_bool) == Some(true)
            || ["role", "subrole"]
                .iter()
                .any(|key| target.get(*key).and_then(Value::as_str) == Some("AXSecureTextField"));
        if secure {
            target.insert("secure".to_string(), Value::Bool(true));
            target.remove("name");
            mark_redacted(destination, "secure_field");
        }
        destination.insert("target".to_string(), Value::Object(target));
    }
    if let Some(details) = project_object(
        source.get("enrichment"),
        &[
            "app_status",
            "duration_ms",
            "queue_delay_ms",
            "reason",
            "status",
            "total_latency_ms",
        ],
    ) {
        destination.insert("enrichment".to_string(), Value::Object(details));
    } else {
        destination.insert(
            "enrichment".to_string(),
            json!({"status": "unavailable", "reason": "native_enrichment_invalid_contract"}),
        );
    }
    // Minimize known credential-shaped semantic labels BEFORE raw JSONL is
    // written. This is not arbitrary PII detection; Python repeats the guard.
    let mut scrubbed = false;
    for key in ["app", "window", "target"] {
        if let Some(object) = destination.get_mut(key).and_then(Value::as_object_mut) {
            for value in object.values_mut() {
                if value.as_str().is_some_and(credential_label) {
                    *value = Value::String("[REDACTED]".to_string());
                    scrubbed = true;
                }
            }
        }
    }
    if scrubbed {
        mark_redacted(destination, "credential_label");
    }
}

fn credential_label(value: &str) -> bool {
    static PATTERN: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    PATTERN.get_or_init(|| regex::Regex::new(
        r#"(?i)(?:api[_ -]?key|access[_ -]?token|password|secret)["']?\s*[:=]\s*\S+|\b(?:(?:sk|ghp|xox[baprs])-|gh[pousr]_|github_pat_)[A-Za-z0-9_-]{8,}\b"#
    ).expect("static credential pattern")).is_match(value)
}

fn project_object(value: Option<&Value>, keys: &[&str]) -> Option<Map<String, Value>> {
    let source = value?.as_object()?;
    let mut projected = Map::new();
    for key in keys {
        if let Some(value) = source.get(*key) {
            // Unknown keys are discarded, but an invalid known field makes
            // this optional enrichment object unusable. Never clone arbitrary
            // nested objects merely because their parent key is allowlisted.
            projected.insert((*key).to_string(), project_field(key, value)?);
        }
    }
    Some(projected)
}

fn project_field(key: &str, value: &Value) -> Option<Value> {
    match key {
        "bounds" => {
            let source = value.as_object()?;
            let mut bounds = Map::new();
            for coordinate in ["x", "y", "width", "height"] {
                if let Some(number) = source.get(coordinate) {
                    if !number.as_f64()?.is_finite() {
                        return None;
                    }
                    bounds.insert(coordinate.to_string(), number.clone());
                }
            }
            Some(Value::Object(bounds))
        }
        "pid" if value.as_u64().is_some() => Some(value.clone()),
        "secure" if value.is_boolean() => Some(value.clone()),
        "duration_ms" | "queue_delay_ms" | "total_latency_ms"
            if value.as_f64().is_some_and(f64::is_finite) =>
        {
            Some(value.clone())
        }
        "bundle_id" | "name" | "role" | "title" | "identifier" | "subrole" | "app_status"
        | "reason" | "status"
            if value.is_string() =>
        {
            Some(value.clone())
        }
        // New allowlist keys also require an explicit type here.
        _ => None,
    }
}

fn mark_redacted(destination: &mut Map<String, Value>, reason: &str) {
    let redaction = destination
        .entry("redaction")
        .or_insert_with(|| json!({"redacted": false, "reasons": []}));
    let Some(redaction) = redaction.as_object_mut() else {
        return;
    };
    redaction.insert("redacted".to_string(), Value::Bool(true));
    let reasons = redaction
        .entry("reasons")
        .or_insert_with(|| Value::Array(Vec::new()));
    if let Some(reasons) = reasons.as_array_mut() {
        reasons.push(Value::String(reason.to_string()));
    }
}

fn set_enrichment_unavailable(payload: &mut Value, reason: &'static str) {
    if let Some(destination) = payload.as_object_mut() {
        destination.insert(
            "enrichment".to_string(),
            json!({"status": "unavailable", "reason": reason}),
        );
    }
}

fn native_error(code: &'static str) -> (&'static str, String) {
    (code, format!("EventStream native operation failed: {code}"))
}

fn permission_json(status: PermissionStatus) -> Value {
    json!({
        "input_monitoring": status.input_monitoring,
        "accessibility": status.accessibility,
        "screen_recording": status.screen_recording,
    })
}

fn button_name(button: i64) -> &'static str {
    match button {
        0 => "left",
        1 => "right",
        _ => "other",
    }
}

fn key_class(key_code: u16) -> (&'static str, u8) {
    match key_code {
        36 | 76 => ("enter", 0),
        48 => ("tab", 0),
        49 => ("space", 1),
        51 | 117 => ("delete", 0),
        53 => ("escape", 0),
        123..=126 | 115 | 116 | 119 | 121 => ("navigation", 0),
        122 | 120 | 99 | 118 | 96 | 97 | 98 | 100 | 101 | 109 | 103 | 111 => ("function", 0),
        54..=63 => ("modifier", 0),
        _ => ("printable", 1),
    }
}

fn modifier_names(flags: u64) -> Vec<&'static str> {
    const CAPS_LOCK: u64 = 1 << 16;
    const SHIFT: u64 = 1 << 17;
    const CONTROL: u64 = 1 << 18;
    const OPTION: u64 = 1 << 19;
    const COMMAND: u64 = 1 << 20;
    const FN: u64 = 1 << 23;
    [
        (CAPS_LOCK, "caps_lock"),
        (SHIFT, "shift"),
        (CONTROL, "control"),
        (OPTION, "option"),
        (COMMAND, "command"),
        (FN, "fn"),
    ]
    .into_iter()
    .filter_map(|(mask, name)| (flags & mask != 0).then_some(name))
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input_fixture(event_type: u32) -> NativeInputEvent {
        NativeInputEvent {
            seq: 0,
            event_type,
            monotonic_ns: 1_000_000,
            source_pid: 0,
            foreground_pid: 42,
            application_generation: 0,
            x: 123.0,
            y: 456.0,
            scroll_x: 0.0,
            scroll_y: 1.0,
            flags: 0,
            key_code: 0,
            button: 0,
            click_count: 1,
        }
    }

    #[test]
    fn app_policy_fails_closed_and_does_not_overmatch_roots() {
        for id in [
            "com.1password.1password",
            "com.agilebits.onepassword7",
            "COM.BITWARDEN.DESKTOP",
            "com.lastpass.LastPass.extension",
            "",
            "invalid id",
        ] {
            assert!(!recordable_app(Some(&json!({"bundle_id": id}))), "{id}");
        }
        for app in [
            json!(null),
            json!({}),
            json!({"bundle_id": []}),
            json!({"bundle_id": "test.fixture", "name": {"text": "private"}}),
        ] {
            assert!(!recordable_app(Some(&app)));
        }
        for id in [
            "test.fixture",
            "com.bitwarden.desktop-fixture",
            "io.agentscope.qwenpaw.desktop",
        ] {
            assert!(recordable_app(Some(&json!({"bundle_id": id}))));
        }
    }

    #[test]
    fn every_input_phase_requires_capture_and_target_app() {
        let safe = json!({"bundle_id": "test.fixture"});
        for kind in [1, 2, 3, 4, 6, 7, 10, 11, 12, 22, 25, 26, 27] {
            let event = input_fixture(kind);
            assert!(event_to_json(&event, false).is_none());
            let enrichment = json!({"app": safe, "capture_app": safe});
            let projected = project_recordable_event(&event, &enrichment).unwrap();
            assert!(projected.get("capture_app").is_none());
            assert!(projected.get("foreground_pid").is_none());
            for key in ["app", "capture_app"] {
                for invalid in [
                    json!(null),
                    json!({"bundle_id": "com.1password.1password"}),
                    json!({}),
                ] {
                    let mut bad = enrichment.clone();
                    bad[key] = invalid;
                    assert!(
                        project_recordable_event(&event, &bad).is_none(),
                        "{kind}/{key}"
                    );
                }
            }
        }
    }

    #[test]
    fn credential_labels_are_scrubbed_before_raw_staging() {
        for label in [
            "password=FAKE_CANARY",
            r#"{"password": "FAKE_CANARY"}"#,
            "API key: FAKE_CANARY",
            "access-token='FAKE_CANARY'",
            "secret=FAKE_CANARY",
            "ghp_FAKE_CANARY",
            "github_pat_FAKE_CANARY",
            "gho_FAKE_CANARY",
            "ghu_FAKE_CANARY",
            "ghs_FAKE_CANARY",
            "ghr_FAKE_CANARY",
            "sk-FAKE_CANARY",
            "xoxb-FAKE_CANARY",
        ] {
            for (container, field) in [
                ("app", "name"),
                ("window", "title"),
                ("target", "identifier"),
            ] {
                let mut enrichment = json!({});
                enrichment[container] = json!({field: label});
                let mut payload = json!({});
                merge_allowlisted_enrichment(&mut payload, &enrichment);
                assert_eq!(payload[container][field], "[REDACTED]", "{label}");
                assert!(!payload.to_string().contains("FAKE_CANARY"));
                assert_eq!(payload["redaction"]["redacted"], true);
            }
        }
        for label in [
            "Password settings",
            "Secret Santa",
            "Continue",
            "Calculator 2+3",
            "ghp_short",
        ] {
            assert!(!credential_label(label), "{label}");
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn retention_clock_matches_sleep_inclusive_os_clock() {
        // An independent OS API checks both the selected clock and tick
        // conversion. CLOCK_UPTIME_RAW / Instant would exclude sleep.
        fn os_now() -> Duration {
            let mut value = libc::timespec {
                tv_sec: 0,
                tv_nsec: 0,
            };
            assert_eq!(
                unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC_RAW, &mut value) },
                0
            );
            Duration::new(
                value.tv_sec.try_into().unwrap(),
                value.tv_nsec.try_into().unwrap(),
            )
        }
        let before = os_now();
        let actual = retention_now();
        let after = os_now();
        assert!(before <= actual && actual <= after);
    }

    fn fixture() -> (tempfile::TempDir, Arc<EventStreamRecorder>) {
        use super::super::indicator::ActivityIndicator;
        let root = tempfile::tempdir().unwrap();
        let staging = Arc::new(
            StagingStore::prepare(root.path().join("fixture.sock").to_str().unwrap()).unwrap(),
        );
        let devices = Arc::new(DeviceCoordinator::new(Arc::new(
            ActivityIndicator::default(),
        )));
        (root, EventStreamRecorder::prepare(devices, staging))
    }

    fn seal_fixture(recorder: &EventStreamRecorder, expires_at: Duration) -> String {
        let id = uuid::Uuid::new_v4().to_string();
        let mut writer = recorder.staging.create_recording(&id).unwrap();
        writer
            .append_event(&json!({"seq": 0, "type": "scroll"}))
            .unwrap();
        let artifact = writer.seal("completed").unwrap();
        recorder.state.lock().unwrap().sealed.insert(
            id.clone(),
            SealedRecording {
                artifact,
                expires_at,
            },
        );
        id
    }

    #[test]
    fn sealed_ttl_expires_without_touching_unsealed_capture() {
        let (_root, recorder) = fixture();
        let now = retention_now();
        let id = seal_fixture(&recorder, now + ARTIFACT_RETENTION);
        let unsealed_id = uuid::Uuid::new_v4().to_string();
        let _writer = recorder.staging.create_recording(&unsealed_id).unwrap();
        recorder.maintain(now + ARTIFACT_RETENTION - Duration::from_millis(1));
        assert!(recorder.staging.root().join(&id).exists());
        recorder.maintain(now + ARTIFACT_RETENTION);
        assert!(!recorder.staging.root().join(&id).exists());
        assert!(recorder.staging.root().join(&unsealed_id).exists());
        assert_eq!(recorder.stop(1, &id).unwrap_err().0, "recording_expired");
        assert_eq!(
            recorder.recording_status(Some(&id))["failure"],
            "recording_expired"
        );
    }

    #[test]
    fn maintenance_expires_files_without_client_polling() {
        let (_root, recorder) = fixture();
        let id = seal_fixture(&recorder, retention_now() + Duration::from_millis(20));
        recorder.ensure_maintenance().unwrap();
        let began = Instant::now();
        while recorder.staging.root().join(&id).exists() {
            assert!(began.elapsed() < Duration::from_secs(3));
            thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(recorder.recording_status(Some(&id))["state"], "failed");
    }

    #[test]
    fn first_maintenance_after_a_long_pause_expires_all_due_artifacts() {
        let (_root, recorder) = fixture();
        let now = retention_now();
        let due = seal_fixture(&recorder, now + ARTIFACT_RETENTION);
        let future = seal_fixture(&recorder, now + ARTIFACT_RETENTION * 3);
        // No maintenance runs during the simulated suspension. This tests
        // deadline handling, not a real system sleep or accelerated E2E TTL.
        recorder.maintain(now + ARTIFACT_RETENTION * 2);
        assert!(!recorder.staging.root().join(&due).exists());
        assert!(recorder.staging.root().join(&future).exists());
        assert_eq!(recorder.stop(1, &due).unwrap_err().0, "recording_expired");
    }

    #[cfg(unix)]
    #[test]
    fn failed_release_is_revoked_and_retried_without_following_symlinks() {
        use std::os::unix::fs::symlink;
        let (root, recorder) = fixture();
        let id = seal_fixture(&recorder, retention_now() + ARTIFACT_RETENTION);
        let directory = recorder.staging.root().join(&id);
        let held = root.path().join("held-artifact");
        std::fs::rename(&directory, &held).unwrap();
        symlink(&held, &directory).unwrap();
        assert_eq!(
            recorder
                .release(&format!("{id}/events.jsonl"))
                .unwrap_err()
                .0,
            "staging_cleanup_pending"
        );
        assert_eq!(recorder.status()["cleanup_pending"], 1);
        assert!(recorder.stop(1, &id).is_err());
        recorder.maintain(retention_now());
        assert!(held.join("events.jsonl").is_file());
        std::fs::remove_file(&directory).unwrap();
        symlink(root.path().join("missing-target"), &directory).unwrap();
        recorder.maintain(retention_now());
        assert_eq!(recorder.status()["cleanup_pending"], 1);
        assert!(std::fs::symlink_metadata(&directory)
            .unwrap()
            .file_type()
            .is_symlink());
        std::fs::remove_file(&directory).unwrap();
        std::fs::rename(&held, &directory).unwrap();
        recorder.maintain(retention_now());
        assert!(!directory.exists());
        assert_eq!(recorder.status()["cleanup_pending"], 0);
    }

    #[test]
    fn failed_recording_status_is_scoped_and_terminal_history_is_bounded() {
        let (_root, recorder) = fixture();
        let mut state = recorder.state.lock().unwrap();
        remember_failure(&mut state, "failed-recording", "staging_failed");
        drop(state);
        assert_eq!(recorder.status()["state"], "idle");
        assert_eq!(recorder.recording_status(Some("other"))["state"], "idle");
        assert_eq!(
            recorder.recording_status(Some("failed-recording"))["failure"],
            "staging_failed"
        );
        let mut state = recorder.state.lock().unwrap();
        for index in 0..256 {
            remember_failure(&mut state, &format!("id-{index}"), "recording_failed");
        }
        assert_eq!(state.failures.len(), MAX_TERMINAL_FAILURES);
    }

    #[test]
    fn repeated_stop_cannot_replay_an_expired_cached_reference() {
        use super::super::event_stream::EventStreamConnection;
        let (_root, recorder) = fixture();
        let now = retention_now();
        let id = seal_fixture(&recorder, now + ARTIFACT_RETENTION);
        let mut connection = EventStreamConnection::new(Arc::clone(&recorder));
        let request = json!({"protocol_version": 2, "method": "event_stream.stop",
            "params": {"recording_id": id, "operation_id": "stop-fixture"}});
        assert!(connection.dispatch(&request).is_ok());
        recorder.maintain(now + ARTIFACT_RETENTION);
        assert_eq!(
            connection.dispatch(&request).unwrap_err().0,
            "recording_expired"
        );
    }

    #[test]
    fn failed_stop_precondition_remains_retryable() {
        use super::super::event_stream::EventStreamConnection;
        let (_root, recorder) = fixture();
        let mut connection = EventStreamConnection::new(Arc::clone(&recorder));
        let request = json!({"protocol_version": 2, "method": "event_stream.stop",
            "params": {"recording_id": "missing", "operation_id": "failed-stop"}});
        let original = connection.dispatch(&request).unwrap_err();
        assert_eq!(original.0, "recording_not_found");
        remember_failure(
            &mut recorder.state.lock().unwrap(),
            "missing",
            "staging_failed",
        );
        // Failed preconditions are deliberately not cached. Rechecking a
        // successful file reference must preserve this existing contract.
        assert_eq!(
            connection.dispatch(&request).unwrap_err().0,
            "staging_failed"
        );
    }

    #[test]
    fn capture_event_never_persists_key_code_or_plaintext() {
        let event = NativeInputEvent {
            seq: 7,
            event_type: 10,
            monotonic_ns: 9_000_000,
            source_pid: 1,
            foreground_pid: 42,
            application_generation: 0,
            x: 0.0,
            y: 0.0,
            scroll_x: 0.0,
            scroll_y: 0.0,
            flags: 0,
            key_code: 0,
            button: 0,
            click_count: 0,
        };
        assert!(
            event_to_json(&event, false).is_none(),
            "drain must not persist primitives"
        );
        let value = primitive_event_to_json(&event);
        let encoded = serde_json::to_string(&value).unwrap();
        assert!(!encoded.contains("key_code"));
        assert!(!encoded.contains("characters"));
        assert_eq!(value["input"]["key_class"], "printable");
        assert_eq!(value["input"]["length"], 1);
    }

    #[test]
    fn secure_target_name_is_removed_at_capture_time() {
        let mut payload = json!({"redaction": {"redacted": false, "reasons": []}});
        merge_allowlisted_enrichment(
            &mut payload,
            &json!({
                "target": {"role": "AXSecureTextField", "secure": true, "name": "secret"},
                "enrichment": {"status": "ok"},
            }),
        );
        assert!(payload["target"].get("name").is_none());
        assert_eq!(payload["redaction"]["redacted"], true);
    }

    #[test]
    fn secure_role_or_subrole_overrides_a_false_native_flag() {
        for target in [
            json!({"role": "AXTextField", "subrole": "AXSecureTextField", "secure": false, "name": "PRIVATE_CANARY"}),
            json!({"role": "AXTextField", "subrole": "AXSecureTextField", "name": "PRIVATE_CANARY"}),
            json!({"role": "AXSecureTextField", "secure": false, "name": "PRIVATE_CANARY"}),
        ] {
            let mut payload = json!({});
            merge_allowlisted_enrichment(&mut payload, &json!({"target": target}));
            assert_eq!(payload["target"]["secure"], true);
            assert!(payload["target"].get("name").is_none());
            assert_eq!(payload["redaction"]["redacted"], true);
        }
    }

    #[test]
    fn enrichment_bounds_drop_unknown_nested_fields_before_persistence() {
        let mut payload = json!({});
        merge_allowlisted_enrichment(
            &mut payload,
            &json!({
                "window": {"bounds": {"x": -1, "text": "FAKE_PRIVATE"}},
                "target": {"name": "Continue", "bounds": {
                    "x": 1, "y": 2.5, "width": 3, "height": 4,
                    "annotation": {"note": "FAKE_PRIVATE"}, "text": "FAKE_PRIVATE"
                }},
                "enrichment": {"status": "ok", "duration_ms": 1.5},
            }),
        );
        assert_eq!(payload["window"]["bounds"], json!({"x": -1}));
        assert_eq!(
            payload["target"]["bounds"],
            json!({"x": 1, "y": 2.5, "width": 3, "height": 4})
        );
        assert_eq!(payload["target"]["name"], "Continue");
        assert!(!payload.to_string().contains("FAKE_PRIVATE"));
    }

    #[test]
    fn enrichment_rejects_containers_in_scalar_fields() {
        for key in [
            "bundle_id",
            "name",
            "role",
            "title",
            "identifier",
            "subrole",
            "app_status",
            "reason",
            "status",
            "pid",
            "secure",
            "duration_ms",
            "queue_delay_ms",
            "total_latency_ms",
        ] {
            for invalid in [
                json!({"annotation": "FAKE_PRIVATE"}),
                json!(["FAKE_PRIVATE"]),
            ] {
                let input = json!({key: invalid});
                assert!(project_object(Some(&input), &[key]).is_none(), "{key}");
            }
        }
        // Adding an allowlisted field must also require a field-type decision.
        assert!(
            project_object(Some(&json!({"new_field": "FAKE_PRIVATE"})), &["new_field"]).is_none()
        );
    }

    #[test]
    fn enrichment_bounds_and_scalar_types_are_not_coerced() {
        for invalid in [
            json!({"x": true}),
            json!({"x": "1"}),
            json!({"x": {"annotation": "FAKE_PRIVATE"}}),
            json!({"x": null}),
            json!([1, 2, 3, 4]),
        ] {
            assert!(project_object(Some(&json!({"bounds": invalid})), &["bounds"]).is_none());
        }
        for (key, invalid) in [
            ("pid", json!(true)),
            ("pid", json!(1.5)),
            ("secure", json!("true")),
            ("duration_ms", json!(true)),
        ] {
            assert!(project_object(Some(&json!({key: invalid})), &[key]).is_none());
        }
        assert_eq!(
            project_object(
                Some(&json!({"pid": 42, "secure": false, "duration_ms": 2.5})),
                &["pid", "secure", "duration_ms"]
            )
            .unwrap(),
            json!({"pid": 42, "secure": false, "duration_ms": 2.5})
                .as_object()
                .unwrap()
                .clone()
        );
    }
}
