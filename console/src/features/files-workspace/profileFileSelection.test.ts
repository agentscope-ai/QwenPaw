import { describe, expect, it } from "vitest";
import { selectProfileFiles } from "./profileFileSelection";
import type { DirectoryEntry } from "./types";

const file = (path: string): DirectoryEntry => ({
  name: path,
  path,
  kind: "file",
  size: 0,
  modified_at: "2026-01-01T00:00:00Z",
  preview_kind: "text",
});

describe("selectProfileFiles", () => {
  it("keeps the profile list limited to defaults and enabled custom files", () => {
    const files = [
      file("notes.md"),
      file("SOUL.md"),
      file("custom-prompt.md"),
      file("AGENTS.md"),
    ];

    expect(selectProfileFiles(files, ["custom-prompt.md"])).toEqual([
      file("custom-prompt.md"),
      file("AGENTS.md"),
      file("SOUL.md"),
    ]);
  });

  it("removes a disabled custom file without hiding workspace candidates", () => {
    const files = [file("AGENTS.md"), file("custom-prompt.md")];

    expect(selectProfileFiles(files, [])).toEqual([file("AGENTS.md")]);
    expect(files).toEqual([file("AGENTS.md"), file("custom-prompt.md")]);
  });
});
