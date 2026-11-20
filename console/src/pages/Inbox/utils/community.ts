import type { PushMessage } from "../types";

export const COMMUNITY_EVENT_LABEL_KEYS: Record<string, string> = {
  interaction: "communityInbox.interaction",
  platform_feedback: "communityInbox.platformFeedback",
  notification: "communityInbox.notification",
  reply: "communityInbox.reply",
  mention: "communityInbox.mention",
  resource_feedback: "communityInbox.resourceFeedback",
};

export function safeCommunityDiscussionUrl(value: unknown): string | null {
  if (
    typeof value !== "string" ||
    Array.from(value).some((character) => {
      const code = character.charCodeAt(0);
      return code <= 32 || code === 127 || character === "\\";
    })
  )
    return null;
  try {
    const url = new URL(value);
    return url.origin === "https://platform.agentscope.io" &&
      ["/community/", "/plugins/", "/skills/", "/notifications"].some(
        (prefix) => url.pathname.startsWith(prefix),
      ) &&
      !url.username &&
      !url.password
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

export function getCommunityMessageDetail(message: PushMessage | null) {
  if (message?.metadata?.sourceType !== "community") return null;
  const payload = message.metadata.payload || {};
  const readString = (key: string) =>
    typeof payload[key] === "string" ? (payload[key] as string) : "";
  const received = payload.received_at;
  const receivedAt =
    typeof received === "number"
      ? new Date(received * 1000)
      : typeof received === "string"
      ? new Date(received)
      : message.createdAt;
  return {
    discussionUrl: safeCommunityDiscussionUrl(payload.discussion_url),
    resourceName: readString("resource_name"),
    resourceType: readString("resource_type"),
    resourceId: readString("resource_id"),
    receivedAt: Number.isNaN(receivedAt.getTime())
      ? message.createdAt
      : receivedAt,
    eventLabelKey:
      COMMUNITY_EVENT_LABEL_KEYS[message.metadata.eventType || ""] ||
      "communityInbox.notification",
  };
}
