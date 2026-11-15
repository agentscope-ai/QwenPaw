import { useSyncExternalStore } from "react";
import { isDesktopApp } from "../tauri/backendRuntime";

const STORAGE_KEY = "qwenpaw.approvalNotifications.enabled";
const CHANGE_EVENT = "qwenpaw:approval-notifications-change";
const PREFERENCES_KEY = "qwenpaw.systemNotifications";

export type ConversationNotificationMode = "off" | "background" | "always";
export interface NotificationPreferences {
  enabled: boolean;
  conversation: ConversationNotificationMode;
  approval: boolean;
  approvalTiming: "background" | "always";
  cron: boolean;
  heartbeat: boolean;
  mail: boolean;
}

let cachedRaw: string | null | undefined;
let cachedLegacy: string | null | undefined;
let cachedPreferences: NotificationPreferences;

export function getNotificationPreferences(): NotificationPreferences {
  const raw = localStorage.getItem(PREFERENCES_KEY);
  const legacy = localStorage.getItem(STORAGE_KEY);
  if (raw === cachedRaw && legacy === cachedLegacy) return cachedPreferences;
  let saved: Partial<NotificationPreferences> = {};
  try {
    const parsed: unknown = JSON.parse(raw || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
      saved = parsed;
  } catch {
    // Invalid preferences fall back to the existing approval preference.
  }
  const boolean = (value: unknown, fallback = false) =>
    typeof value === "boolean" ? value : fallback;
  cachedRaw = raw;
  cachedLegacy = legacy;
  cachedPreferences = {
    enabled: boolean(saved.enabled, legacy === "true"),
    approval: boolean(saved.approval, legacy === "true"),
    approvalTiming: saved.approvalTiming === "always" ? "always" : "background",
    conversation: ["off", "background", "always"].includes(
      saved.conversation || "",
    )
      ? saved.conversation!
      : "off",
    cron: boolean(saved.cron),
    heartbeat: boolean(saved.heartbeat),
    mail: boolean(saved.mail),
  };
  return cachedPreferences;
}

export function updateNotificationPreferences(
  patch: Partial<NotificationPreferences>,
): void {
  localStorage.setItem(
    PREFERENCES_KEY,
    JSON.stringify({ ...getNotificationPreferences(), ...patch }),
  );
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function useNotificationPreferences(): NotificationPreferences {
  return useSyncExternalStore(subscribe, getNotificationPreferences);
}

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
  const preferences = getNotificationPreferences();
  return preferences.enabled && preferences.approval;
}

export function setNotificationsEnabled(enabled: boolean): void {
  localStorage.setItem(STORAGE_KEY, String(enabled));
  updateNotificationPreferences({
    enabled,
    ...(enabled ? { approval: true } : {}),
  });
}

function subscribe(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if ([STORAGE_KEY, PREFERENCES_KEY, null].includes(event.key)) onChange();
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
