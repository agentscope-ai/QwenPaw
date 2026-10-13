//! Shared process runtime behind the versioned automation contracts.
//!
//! Process-wide resources live outside both contract dispatchers, so Record
//! and Act share one permission identity and one physical-device coordinator.

use std::sync::Arc;

use super::device_coordinator::DeviceCoordinator;
use super::event_stream_recorder::{native_activity_presenter, EventStreamRecorder};
use super::indicator::ActivityIndicator;
use super::permission_broker::PermissionBroker;
use super::staging::StagingStore;

pub(super) struct DesktopAutomationService {
    devices: Arc<DeviceCoordinator>,
    permissions: PermissionBroker,
    event_stream: Arc<EventStreamRecorder>,
}

impl DesktopAutomationService {
    pub(super) fn prepare(endpoint: &str) -> Result<Arc<Self>, String> {
        let indicator = Arc::new(ActivityIndicator::with_presenter(native_activity_presenter));
        let devices = Arc::new(DeviceCoordinator::new(Arc::clone(&indicator)));
        let staging = Arc::new(StagingStore::prepare(endpoint)?);
        let event_stream = EventStreamRecorder::prepare(Arc::clone(&devices), Arc::clone(&staging));
        Ok(Arc::new(Self {
            devices,
            permissions: PermissionBroker,
            event_stream,
        }))
    }

    pub(super) fn devices(&self) -> &Arc<DeviceCoordinator> {
        &self.devices
    }

    pub(super) fn permissions(&self) -> &PermissionBroker {
        &self.permissions
    }

    pub(super) fn event_stream(&self) -> &Arc<EventStreamRecorder> {
        &self.event_stream
    }

    #[cfg(test)]
    pub(super) fn current_activity(&self) -> super::indicator::Activity {
        self.devices.current_activity()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::computer_use_server::indicator::Activity;

    #[test]
    fn one_service_owns_all_process_wide_resources() {
        let endpoint_dir = tempfile::tempdir().unwrap();
        let endpoint = endpoint_dir.path().join("helper.sock");
        let service = DesktopAutomationService::prepare(endpoint.to_str().unwrap()).unwrap();

        assert_eq!(service.current_activity(), Activity::Idle);
        assert!(!service.event_stream().artifact_root().exists());
        assert!(PermissionBroker::computer_use_requirements("list_apps").is_empty());
    }
}
