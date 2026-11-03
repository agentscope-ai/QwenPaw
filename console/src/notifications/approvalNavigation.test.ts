import { describe, expect, it } from "vitest";
import { buildApprovalNavigationPath } from "./approvalNavigation";
import { getSessionIdFromPath } from "../utils/sessionRoute";

describe("approval notification navigation", () => {
  it("opens the source chat and preserves the approval request", () => {
    expect(
      buildApprovalNavigationPath({
        rootSessionId: "session-1",
        requestId: "approval/1",
        agentId: "agent-a",
      }),
    ).toBe("/chat/session-1?approval=approval%2F1&agent=agent-a");
  });

  it("falls back to the inbox when no source chat is available", () => {
    expect(buildApprovalNavigationPath({ requestId: "approval-1" })).toBe(
      "/inbox?tab=approvals",
    );
  });

  it.each([
    "session#one",
    "session?one",
    "session/one",
    "session%20one",
    "会话 /?&#1",
  ])("encodes the session ID %s without losing the target", (rootSessionId) => {
    const path = buildApprovalNavigationPath({
      rootSessionId,
      requestId: "approval/1",
      agentId: "agent-a",
    });
    const url = new URL(path, "https://example.test");
    expect(url.pathname).toBe(`/chat/${encodeURIComponent(rootSessionId)}`);
    expect(getSessionIdFromPath(url.pathname)).toBe(rootSessionId);
    expect(url.searchParams.get("approval")).toBe("approval/1");
    expect(url.searchParams.get("agent")).toBe("agent-a");
    expect(url.hash).toBe("");
  });
});
