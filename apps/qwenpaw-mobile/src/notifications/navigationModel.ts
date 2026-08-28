import type { MobileNotificationData } from "@qwenpaw/api-contract";

export type NotificationDestination =
  | { kind: "approval" }
  | { kind: "chat"; chatId: string }
  | { kind: "workbench" };

export function notificationDestination(
  data: MobileNotificationData,
): NotificationDestination {
  if (data.kind === "approval_required") return { kind: "approval" };
  if (data.chat_id) return { kind: "chat", chatId: data.chat_id };
  return { kind: "workbench" };
}
