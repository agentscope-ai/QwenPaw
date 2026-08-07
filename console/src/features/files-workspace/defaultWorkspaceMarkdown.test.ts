import { describe, expect, it } from "vitest";
import {
  DEFAULT_WORKSPACE_MARKDOWN_FILENAMES,
  isDefaultWorkspaceMarkdown,
  isWorkspaceMarkdown,
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
      DEFAULT_WORKSPACE_MARKDOWN_FILENAMES.every(isWorkspaceMarkdown),
    ).toBe(true);
    expect(
      DEFAULT_WORKSPACE_MARKDOWN_FILENAMES.every(isDefaultWorkspaceMarkdown),
    ).toBe(true);
  });

  it("isDefaultWorkspaceMarkdown accepts only the built-in set", () => {
    expect(isDefaultWorkspaceMarkdown("AGENTS.md")).toBe(true);
    expect(isDefaultWorkspaceMarkdown("SOUL.md")).toBe(true);
    expect(isDefaultWorkspaceMarkdown("notes.md")).toBe(false);
    expect(isDefaultWorkspaceMarkdown("custom-prompt.md")).toBe(false);
  });

  it("recognizes user-created workspace Markdown files", () => {
    expect(isWorkspaceMarkdown("FILES.md")).toBe(true);
    expect(isWorkspaceMarkdown("WORKFLOW.md")).toBe(true);
  });

  it("rejects non-Markdown files", () => {
    expect(isWorkspaceMarkdown("avatar.png")).toBe(false);
    expect(isWorkspaceMarkdown("notes.txt")).toBe(false);
  });
});
