import { useSyncExternalStore } from "react";
import { isDesktopApp } from "../tauri/backendRuntime";

const STORAGE_KEY = "qwenpaw.approvalNotifications.enabled";
const CHANGE_EVENT = "qwenpaw:approval-notifications-change";

export type NotificationPermissionState =
  | NotificationPermission
  | "native"
  | "checking"
  | "unavailable"
  | "unsupported"
  | "insecure";

export function getNotificationPermission(): NotificationPermissionState {
  if (isDesktopApp()) return "checking";
  if (typeof window.Notification !== "function") return "unsupported";
  if (!window.isSecureContext) return "insecure";
  return Notification.permission;
}

export function notificationsEnabled(): boolean {
  return localStorage.getItem(STORAGE_KEY) === "true";
}

export function setNotificationsEnabled(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, String(enabled));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === null) onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useApprovalNotificationsEnabled(): boolean {
  return useSyncExternalStore(subscribe, notificationsEnabled, () => false);
}
