import { describe, expect, it } from "vitest";
import {
  safeCommunityDiscussionUrl,
  getCommunityMessageDetail,
} from "./community";
import type { PushMessage } from "../types";

describe("community discussion links", () => {
  it.each([
    "community/articles/post-1",
    "plugins/demo",
    "skills/019f5c27-c57d-7584-8617-9bf93c383950",
  ])("keeps actual platform discussion and resource links: %s", (path) => {
    const url = `https://platform.agentscope.io/${path}#comment-3`;
    expect(safeCommunityDiscussionUrl(url)).toBe(url);
  });
  it.each([
    "javascript:alert(1)",
    "https://platform.agentscope.io.example.com/community/1",
    "https://user:pass@platform.agentscope.io/plugins/1",
    "http://platform.agentscope.io/community/1",
    "https://platform.agentscope.io/community/1\n",
    "https://platform.agentscope.io\\community/1",
    "https://platform.agentscope.io/api/v1/notifications",
  ])("rejects unsafe or unrelated link: %s", (url) => {
    expect(safeCommunityDiscussionUrl(url)).toBeNull();
  });
  it("keeps arrival time separate from event time and shows resource metadata", () => {
    const message = {
      id: "notification-1",
      channelType: "community",
      channelName: "QwenPaw Community",
      title: "A reply",
      content: "Reply text",
      sender: { userId: "member-7", username: "Maintainer" },
      read: false,
      createdAt: new Date(1000),
      metadata: {
        sourceType: "community",
        eventType: "resource_feedback",
        payload: {
          received_at: 10,
          resource_type: "app",
          resource_id: "creator",
          resource_name: "Creator",
          discussion_url: "https://platform.agentscope.io/plugins/creator",
        },
      },
    } as PushMessage;
    const detail = getCommunityMessageDetail(message)!;
    expect(detail.receivedAt.getTime()).toBe(10000);
    expect(detail.resourceType).toBe("app");
    expect(detail.resourceName).toBe("Creator");
    expect(detail.eventLabelKey).toBe("communityInbox.resourceFeedback");
  });
});
