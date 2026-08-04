import { describe, expect, it } from "vitest";
import { parseManifest } from "./workspaceArtifacts";

describe("WorkspaceArtifactsCard manifest parsing", () => {
  it("accepts the version 1 manifest wrapped in tool output", () => {
    const manifest = {
      version: 1,
      agent_id: "analyst",
      chat_id: "chat-1",
      turn_id: "turn-1",
      artifacts: [],
      changes: [],
      truncated: false,
    };

    expect(parseManifest(JSON.stringify(manifest))).toEqual(manifest);
    expect(parseManifest(JSON.stringify({ manifest }))).toEqual(manifest);
  });

  it("rejects unknown manifest versions and malformed output", () => {
    expect(parseManifest(JSON.stringify({ version: 2, artifacts: [] }))).toBe(
      null,
    );
    expect(parseManifest("not-json")).toBeNull();
  });
});
