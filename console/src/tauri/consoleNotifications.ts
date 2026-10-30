import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { buildAuthHeaders } from "../api/authHeaders";
import type { PendingApproval, PushMessage } from "../api/modules/console";

export interface ConsolePushSnapshot {
  messages: PushMessage[];
  pending_approvals: PendingApproval[];
}

export type DesktopNotificationPermission =
  | "default"
  | "granted"
  | "denied"
  | "native";

export function getDesktopNotificationPermission(): Promise<DesktopNotificationPermission> {
  return invoke("get_notification_permission");
}

export function requestDesktopNotificationPermission(): Promise<DesktopNotificationPermission> {
  return invoke("request_notification_permission");
}

interface PushEvent {
  generation: number;
  snapshot: ConsolePushSnapshot;
}

/** Subscribe before starting the native poller so the first snapshot is kept. */
export async function subscribeDesktopConsolePush(
  onSnapshot: (snapshot: ConsolePushSnapshot) => void,
): Promise<() => void> {
  let generation: number | undefined;
  let queued: PushEvent | undefined;
  let active = true;
  const unlisten = await listen<PushEvent>("qwenpaw:console-push", (event) => {
    if (!active) return;
    if (generation === undefined) queued = event.payload;
    else if (event.payload.generation === generation) {
      onSnapshot(event.payload.snapshot);
    }
  });
  try {
    const headers = buildAuthHeaders();
    generation = await invoke<number>("start_console_polling", {
      token: headers.Authorization?.replace(/^Bearer /, "") || "",
      agentId: headers["X-Agent-Id"] || null,
    });
    if (queued?.generation === generation) onSnapshot(queued.snapshot);
    return () => {
      active = false;
      unlisten();
      void invoke("stop_console_polling", { generation }).catch(console.warn);
    };
  } catch (error) {
    active = false;
    unlisten();
    throw error;
  }
}

export function configureDesktopApprovalNotifications(
  enabled: boolean,
  title: string,
  body: string,
): Promise<void> {
  return invoke("configure_approval_notifications", { enabled, title, body });
}

export function sendDesktopTestNotification(
  title: string,
  body: string,
): Promise<void> {
  return invoke("send_test_notification", { title, body });
}
