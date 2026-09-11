import { describe, expect, it } from "vitest";
import {
  DEFAULT_WORKSPACE_MARKDOWN_FILENAMES,
  isDefaultWorkspaceMarkdown,
} from "./defaultWorkspaceMarkdown";

describe("defaultWorkspaceMarkdown", () => {
  it("recognizes every built-in workspace Markdown file", () => {
    expect(DEFAULT_WORKSPACE_MARKDOWN_FILENAMES).toEqual([
      "AGENTS.md",
      "SOUL.md",
      "PROFILE.md",
      "MEMORY.md",
      "HEARTBEAT.md",
      "BOOTSTRAP.md",
    ]);
    expect(
      DEFAULT_WORKSPACE_MARKDOWN_FILENAMES.every(isDefaultWorkspaceMarkdown),
    ).toBe(true);
  });

  it("rejects user-created Markdown files", () => {
    expect(isDefaultWorkspaceMarkdown("analysis.md")).toBe(false);
    expect(isDefaultWorkspaceMarkdown("xiaomi_stock_analysis_2026.md")).toBe(
      false,
    );
  });
});
