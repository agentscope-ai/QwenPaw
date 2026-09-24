//! Process-local activity state for the desktop automation helper.
//!
//! This is the single source of truth rendered by the optional native
//! presenter. Presentation is best-effort and never owns a device lease.

use std::sync::Mutex;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(super) enum Activity {
    #[default]
    Idle,
    ComputerUse,
    Recording,
}

pub(super) struct ActivityIndicator {
    state: Mutex<Activity>,
    presenter: Option<fn(Activity)>,
}

impl Default for ActivityIndicator {
    fn default() -> Self {
        Self {
            state: Mutex::new(Activity::Idle),
            presenter: None,
        }
    }
}

impl ActivityIndicator {
    pub(super) fn with_presenter(presenter: fn(Activity)) -> Self {
        Self {
            state: Mutex::new(Activity::Idle),
            presenter: Some(presenter),
        }
    }

    pub(super) fn set(&self, activity: Activity) {
        *self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = activity;
        if let Some(presenter) = self.presenter {
            presenter(activity);
        }
    }

    #[cfg(test)]
    pub(super) fn current(&self) -> Activity {
        *self
            .state
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}
