//! Authoritative desktop connection state, independent of any WebView.

use std::sync::Mutex;

use serde::Serialize;
use tauri::Emitter;

pub(super) const EVENT: &str = "qwenpaw-agent-host-state";

#[derive(Clone, Copy, Default, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Phase {
    #[default]
    Starting,
    Ready,
    Failed,
    Stopping,
    Stopped,
}

#[derive(Clone, Default, Serialize)]
pub(crate) struct Snapshot {
    revision: u64,
    generation: u64,
    pub(super) phase: Phase,
    port: Option<u16>,
    error: Option<String>,
}

#[derive(Default)]
pub(super) struct Status(Mutex<Snapshot>);

impl Status {
    pub(super) fn snapshot(&self) -> Snapshot {
        self.0.lock().expect("host status poisoned").clone()
    }

    pub(super) fn publish(
        &self,
        app: &tauri::AppHandle,
        generation: u64,
        phase: Phase,
        port: Option<u16>,
        error: Option<String>,
    ) {
        let mut state = self.0.lock().expect("host status poisoned");
        if generation < state.generation {
            return;
        }
        // A late readiness probe cannot revive a failed/stopped generation.
        if phase == Phase::Ready
            && (generation != state.generation
                || !matches!(state.phase, Phase::Starting | Phase::Stopping))
        {
            return;
        }
        *state = Snapshot {
            revision: state.revision + 1,
            generation,
            phase,
            port,
            error,
        };
        let _ = app.emit(EVENT, state.clone());
    }
}
