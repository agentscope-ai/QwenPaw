import { describe, expect, it } from "vitest";
import type { MdFileInfo } from "../../api/types";
import {
  buildWorkspacePathMentionItems,
  extractWorkspacePathMentions,
  formatWorkspacePathMention,
} from "./pathMentions";

function file(path: string): MdFileInfo {
  return {
    filename: path,
    path,
    size: 1,
    created_time: "2026-08-05T00:00:00Z",
    modified_time: "2026-08-05T00:00:00Z",
  };
}

describe("buildWorkspacePathMentionItems", () => {
  it("derives unique parent folders and keeps files", () => {
    expect(
      buildWorkspacePathMentionItems([
        file("src/components/Button.tsx"),
        file("src/components/Input.tsx"),
        file("README.md"),
      ]),
    ).toEqual([
      { value: "src", label: "src", type: "folder" },
      {
        value: "src/components",
        label: "src/components",
        type: "folder",
      },
      { value: "README.md", label: "README.md", type: "file" },
      {
        value: "src/components/Button.tsx",
        label: "src/components/Button.tsx",
        type: "file",
      },
      {
        value: "src/components/Input.tsx",
        label: "src/components/Input.tsx",
        type: "file",
      },
    ]);
  });

  it("normalizes surrounding slashes and ignores empty paths", () => {
    expect(
      buildWorkspacePathMentionItems([
        file("/docs/guide.md/"),
        file(""),
        file("/docs/guide.md/"),
      ]),
    ).toEqual([
      { value: "docs", label: "docs", type: "folder" },
      { value: "docs/guide.md", label: "docs/guide.md", type: "file" },
    ]);
  });
});

describe("formatWorkspacePathMention", () => {
  it("keeps simple file paths readable and marks folders with a slash", () => {
    expect(
      formatWorkspacePathMention({
        value: "src/app.ts",
        type: "file",
      }),
    ).toBe("@ src/app.ts");
    expect(
      formatWorkspacePathMention({
        value: "src/pages",
        type: "folder",
      }),
    ).toBe("@ src/pages/");
  });

  it("quotes paths containing spaces without losing the submitted value", () => {
    expect(
      formatWorkspacePathMention({
        value: 'docs/My Guide/intro "draft".md',
        type: "file",
      }),
    ).toBe('@ "docs/My Guide/intro \\"draft\\".md"');
  });
});

describe("extractWorkspacePathMentions", () => {
  it("extracts serializable file and folder metadata", () => {
    expect(
      extractWorkspacePathMentions('check @ src/app.ts and @ "docs/My Guide/"'),
    ).toEqual([
      { value: "src/app.ts", type: "file" },
      { value: "docs/My Guide", type: "folder" },
    ]);
  });
});
