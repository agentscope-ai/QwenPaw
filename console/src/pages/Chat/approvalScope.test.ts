import { describe, expect, it } from "vitest";
import { isApprovalInCurrentScope } from "./approvalScope";

const childApproval = {
  agentId: "child-agent",
  ownerAgentId: "agent-a",
  rootSessionId: "session-a",
};

describe("isApprovalInCurrentScope", () => {
  it("accepts a child approval owned by the selected root agent", () => {
    expect(
      isApprovalInCurrentScope(childApproval, "agent-a", "session-a", false),
    ).toBe(true);
  });

  it("rejects an approval owned by another agent", () => {
    expect(
      isApprovalInCurrentScope(childApproval, "agent-b", "session-a", false),
    ).toBe(false);
  });

  it("rejects an approval from another root session", () => {
    expect(
      isApprovalInCurrentScope(childApproval, "agent-a", "session-b", false),
    ).toBe(false);
  });

  it("rejects approvals during a switch or on a blank session", () => {
    expect(
      isApprovalInCurrentScope(childApproval, "agent-a", "session-a", true),
    ).toBe(false);
    expect(isApprovalInCurrentScope(childApproval, "agent-a", "", false)).toBe(
      false,
    );
  });

  it("falls back to agentId for approval payloads without an owner", () => {
    expect(
      isApprovalInCurrentScope(
        {
          agentId: "agent-a",
          rootSessionId: "session-a",
        },
        "agent-a",
        "session-a",
        false,
      ),
    ).toBe(true);
  });
});
