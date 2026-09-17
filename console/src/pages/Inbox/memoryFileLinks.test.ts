import { describe, expect, it } from "vitest";
import {
  memoryLocatorsFromInboxPayload,
  sourceConversationIdFromInboxPayload,
} from "./memoryFileLinks";

describe("memoryLocatorsFromInboxPayload", () => {
  it("keeps only valid managed memory locators", () => {
    expect(memoryLocatorsFromInboxPayload({ memory_files: [
      {
        path: "2026-09-16/qingdao.md",
        scope: "private",
        section: "daily",
      },
      {
        path: "../secret.md",
        scope: "private",
        section: "daily",
      },
    ] }, "agent-a")).toEqual([{
      category: "memory",
      agentId: "agent-a",
      relativePath: "2026-09-16/qingdao.md",
      memoryScope: "private",
      memorySection: "daily",
    }]);
  });

  it("accepts only UUID source conversation ids", () => {
    expect(sourceConversationIdFromInboxPayload({
      source_conversation_id: "de307e1e-a799-4323-8fbb-4699dea2990c",
    })).toBe("de307e1e-a799-4323-8fbb-4699dea2990c");
    expect(sourceConversationIdFromInboxPayload({
      source_conversation_id: "../../other-chat",
    })).toBeNull();
  });
});
