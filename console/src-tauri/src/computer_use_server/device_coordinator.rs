//! Process-wide ownership of the physical desktop.
//!
//! Read-only requests do not enter this coordinator.  Computer Use mutations
//! take a short, fail-fast permit. Record takes a long lease retained by the
//! EventStream recorder, so disconnect/drop is the release path and no
//! abandoned request can wake later to inject input.

use std::sync::{Arc, Mutex};

use super::indicator::{Activity, ActivityIndicator};

#[derive(Default)]
struct DeviceState {
    mutation_active: bool,
    recording: Option<RecordingOwner>,
    next_recording_generation: u64,
}

#[derive(Clone)]
struct RecordingOwner {
    generation: u64,
    #[allow(dead_code)]
    session_id: String,
}

pub(super) struct DeviceCoordinator {
    state: Mutex<DeviceState>,
    indicator: Arc<ActivityIndicator>,
}

impl DeviceCoordinator {
    pub(super) fn new(indicator: Arc<ActivityIndicator>) -> Self {
        Self {
            state: Mutex::new(DeviceState::default()),
            indicator,
        }
    }

    /// Acquire the keyboard, pointer and foreground window for one mutation.
    ///
    /// This never waits.  Waiting inside the helper could execute a mutation
    /// after the caller closed its connection or asked the agent to stop.
    pub(super) fn try_computer_use_mutation(
        self: &Arc<Self>,
    ) -> Result<MutationPermit, (&'static str, String)> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if state.mutation_active || state.recording.is_some() {
            return Err((
                "desktop_busy",
                "Another desktop automation session is using the desktop; observe the window again and retry."
                    .to_string(),
            ));
        }
        state.mutation_active = true;
        self.indicator.set(Activity::ComputerUse);
        Ok(MutationPermit {
            coordinator: Arc::clone(self),
        })
    }

    /// Reserve the desktop for one EventStream recording session.
    pub(super) fn try_recording(
        self: &Arc<Self>,
        session_id: &str,
    ) -> Result<RecordingLease, (&'static str, String)> {
        if session_id.is_empty() {
            return Err((
                "invalid_request",
                "Recording session id must not be empty.".to_string(),
            ));
        }
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if state.mutation_active || state.recording.is_some() {
            return Err((
                "desktop_busy",
                "Another desktop automation session is using the desktop.".to_string(),
            ));
        }
        state.next_recording_generation = state.next_recording_generation.wrapping_add(1).max(1);
        let generation = state.next_recording_generation;
        state.recording = Some(RecordingOwner {
            generation,
            session_id: session_id.to_string(),
        });
        self.indicator.set(Activity::Recording);
        Ok(RecordingLease {
            coordinator: Arc::clone(self),
            generation,
        })
    }

    #[cfg(test)]
    fn recording_session(&self) -> Option<String> {
        self.state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .recording
            .as_ref()
            .map(|owner| owner.session_id.clone())
    }

    #[cfg(test)]
    pub(super) fn current_activity(&self) -> Activity {
        self.indicator.current()
    }
}

pub(super) struct MutationPermit {
    coordinator: Arc<DeviceCoordinator>,
}

impl Drop for MutationPermit {
    fn drop(&mut self) {
        let mut state = self
            .coordinator
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        state.mutation_active = false;
        self.coordinator
            .indicator
            .set(if state.recording.is_some() {
                Activity::Recording
            } else {
                Activity::Idle
            });
    }
}

pub(super) struct RecordingLease {
    coordinator: Arc<DeviceCoordinator>,
    generation: u64,
}

impl RecordingLease {
    #[allow(dead_code)]
    pub(super) fn is_active(&self) -> bool {
        self.coordinator
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .recording
            .as_ref()
            .is_some_and(|owner| owner.generation == self.generation)
    }
}

impl Drop for RecordingLease {
    fn drop(&mut self) {
        let mut state = self
            .coordinator
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let owns_lease = state
            .recording
            .as_ref()
            .is_some_and(|owner| owner.generation == self.generation);
        if owns_lease {
            state.recording = None;
            self.coordinator.indicator.set(Activity::Idle);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn coordinator() -> (Arc<DeviceCoordinator>, Arc<ActivityIndicator>) {
        let indicator = Arc::new(ActivityIndicator::default());
        (
            Arc::new(DeviceCoordinator::new(Arc::clone(&indicator))),
            indicator,
        )
    }

    #[test]
    fn mutations_are_fail_fast_and_release_on_drop() {
        let (coordinator, indicator) = coordinator();
        let first = coordinator.try_computer_use_mutation().unwrap();

        assert_eq!(indicator.current(), Activity::ComputerUse);
        assert_eq!(
            coordinator.try_computer_use_mutation().err().unwrap().0,
            "desktop_busy",
        );

        drop(first);
        assert_eq!(indicator.current(), Activity::Idle);
        assert!(coordinator.try_computer_use_mutation().is_ok());
    }

    #[test]
    fn recording_and_mutation_are_mutually_exclusive() {
        let (coordinator, indicator) = coordinator();
        let recording = coordinator.try_recording("recording-1").unwrap();

        assert_eq!(indicator.current(), Activity::Recording);
        assert_eq!(
            coordinator.recording_session().as_deref(),
            Some("recording-1")
        );
        assert_eq!(
            coordinator.try_computer_use_mutation().err().unwrap().0,
            "desktop_busy",
        );

        drop(recording);
        let mutation = coordinator.try_computer_use_mutation().unwrap();
        assert_eq!(
            coordinator.try_recording("recording-2").err().unwrap().0,
            "desktop_busy",
        );
        drop(mutation);
    }

    #[test]
    fn connection_drop_releases_a_recording_lease() {
        let (coordinator, indicator) = coordinator();
        let connection_owned_lease = coordinator.try_recording("recording-1").unwrap();

        drop(connection_owned_lease);

        assert_eq!(indicator.current(), Activity::Idle);
        assert!(coordinator.try_recording("recording-2").is_ok());
    }

    #[test]
    fn a_panicking_mutation_cannot_strand_the_desktop() {
        let (coordinator, _indicator) = coordinator();
        let thread_coordinator = Arc::clone(&coordinator);
        let panicked = std::thread::spawn(move || {
            let _permit = thread_coordinator.try_computer_use_mutation().unwrap();
            panic!("simulated action failure");
        })
        .join();

        assert!(panicked.is_err());
        assert!(coordinator.try_computer_use_mutation().is_ok());
    }
}
