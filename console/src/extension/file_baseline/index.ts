export { IntegrityProtectionFrame } from "./components/IntegrityProtectionFrame";
export { default as FileBaselineDriftAlertNotifier } from "./components/FileBaselineDriftAlertNotifier";
export { default as GlobalOperatorApprovalOverlay } from "./components/GlobalOperatorApprovalOverlay";
export {
  FileBaselineProtectionFileList,
  FileBaselineProtectionProtectedPaths,
  FileBaselineProtectionProvider,
  FileBaselineProtectionSwitchRow,
  useFileBaselineProtectionContext,
} from "./components/FileBaselineProtectionSection";
export { useFileBaselineDriftWatch } from "./hooks/useFileBaselineDriftWatch";
export type {
  FileBaselineAlertResolvedEvent,
  FileBaselineUpdatedEvent,
  FileBaselineDriftEvent,
  FileBaselineProtectionEvent,
} from "./hooks/useFileBaselineDriftWatch";
export {
  fileBaselineApi,
  type FileBaselineProtectionActionResponse,
  type FileBaselineProtectionAlert,
  type FileBaselineProtectionAlertsResponse,
  type FileBaselineProtectionSettings,
  type FileBaselineProtectionSettingsUpdateBody,
} from "./api/client";
export {
  acceptFileBaselineAlert,
  collectUnreadFileBaselineInboxEventIds,
  markFileBaselineInboxEventsAsRead,
  markFileBaselineInboxReadByAlertId,
  FILE_BASELINE_CONFIRM_ACCEPT,
  FILE_BASELINE_CONFIRM_RESTORE,
  restoreFileBaselineAlert,
} from "./lib/alertActions";
export {
  getFileBaselineDriftBody,
  getFileBaselineDriftTitle,
  getFileBaselineProtectionChannelName,
} from "./lib/driftDisplay";
export {
  mapInboxEventsByAlertId,
  mergeAlertItems,
  type FileBaselineDriftAlertCopy,
  type FileBaselineDriftAlertItem,
} from "./lib/driftAlertItems";
export {
  resolveFileBaselineDriftDeepLink,
  resolveFileBaselineDriftNavigation,
} from "./lib/navigation";
