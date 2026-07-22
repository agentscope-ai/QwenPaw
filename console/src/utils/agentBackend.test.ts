import { describe, expect, it } from "vitest";

import { requiresQwenPawModel } from "./agentBackend";

describe("requiresQwenPawModel", () => {
  it("requires a configured model for native QwenPaw agents", () => {
    expect(requiresQwenPawModel("qwenpaw")).toBe(true);
  });

  it("does not inspect QwenPaw models for Codex agents", () => {
    expect(requiresQwenPawModel("codex")).toBe(false);
  });
});
