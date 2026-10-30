import { describe, expect, it } from "vitest";
import { buildApprovalNavigationPath } from "./approvalNavigation";

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
});
