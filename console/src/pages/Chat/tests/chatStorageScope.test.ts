import { beforeEach, describe, expect, it } from "vitest";
import { approvalLevelStorageKey } from "../components/ApprovalLevelToggle";
import { harnessApprovalStorageKey } from "../components/HarnessApprovalToggle";

describe("chat user-scoped preferences", () => {
  beforeEach(() => localStorage.clear());

  it("isolates approval preferences for the same conversation id", () => {
    localStorage.setItem("qwenpaw_authenticated_user_id", "user-a");
    const userA = approvalLevelStorageKey("same-chat");
    const userAHarness = harnessApprovalStorageKey("codex", "same-chat");

    localStorage.setItem("qwenpaw_authenticated_user_id", "user-b");
    const userB = approvalLevelStorageKey("same-chat");
    const userBHarness = harnessApprovalStorageKey("codex", "same-chat");

    expect(userA).toBe("approval_level-same-chat:user:user-a");
    expect(userB).toBe("approval_level-same-chat:user:user-b");
    expect(userAHarness).toBe(
      "harness-approval-codex-same-chat:user:user-a",
    );
    expect(userBHarness).toBe(
      "harness-approval-codex-same-chat:user:user-b",
    );
  });
});
