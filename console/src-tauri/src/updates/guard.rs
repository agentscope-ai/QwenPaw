use std::sync::atomic::{AtomicBool, Ordering};

/// Guards against concurrent update operations (check/download/install). Each
/// of the public commands acquires this before spawning work and releases it
/// when the work finishes, so repeated clicks can't race on the cache dir.
static UPDATE_IN_FLIGHT: AtomicBool = AtomicBool::new(false);

/// RAII token: holding it means an update operation is in flight; dropping it
/// (including on early returns / errors) clears the flag.
pub(super) struct InFlightGuard;

impl InFlightGuard {
    fn try_acquire() -> Option<Self> {
        UPDATE_IN_FLIGHT
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .ok()
            .map(|_| InFlightGuard)
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        UPDATE_IN_FLIGHT.store(false, Ordering::Release);
    }
}

pub(super) fn begin_update() -> Result<InFlightGuard, String> {
    InFlightGuard::try_acquire()
        .ok_or_else(|| "an update operation is already in progress".to_string())
}
