import { describe, expect, it } from "vitest";

import { requiresQwenPawModel, supportsAgentAttachments } from "./agentBackend";

describe("requiresQwenPawModel", () => {
  it("requires a configured model for native QwenPaw agents", () => {
    expect(requiresQwenPawModel("qwenpaw")).toBe(true);
  });

  it("does not inspect QwenPaw models for Codex agents", () => {
    expect(requiresQwenPawModel("codex")).toBe(false);
  });
});

describe("supportsAgentAttachments", () => {
  it("keeps attachments enabled for native agents", () => {
    expect(supportsAgentAttachments("qwenpaw")).toBe(true);
  });

  it("enables sender drop handling when Codex declares attachments", () => {
    expect(
      supportsAgentAttachments("codex", {
        attachments: true,
      }),
    ).toBe(true);
  });

  it("enables sender drop handling when Qoder declares attachments", () => {
    expect(
      supportsAgentAttachments("qoder", {
        attachments: true,
      }),
    ).toBe(true);
  });

  it("keeps attachments hidden for backends without the capability", () => {
    expect(supportsAgentAttachments("qoder", {})).toBe(false);
  });
});
