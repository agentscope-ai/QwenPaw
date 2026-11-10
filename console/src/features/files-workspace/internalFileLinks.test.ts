import { describe, expect, it } from "vitest";
import {
  parseInternalFileLink,
  parseAbsoluteWorkspaceFileLink,
  filePathFromPreviewUrl,
  rootForFileReference,
  toProjectRelativePath,
} from "./internalFileLinks";

describe("parseInternalFileLink", () => {
  it("parses relative paths and line locations", () => {
    expect(parseInternalFileLink("src/app.py#L120C4")).toEqual({
      source: "workspace",
      path: "src/app.py",
      line: 120,
      column: 4,
    });
  });

  it.each([
    "https://example.com/file.py",
    "mailto:team@example.com",
    "/etc/passwd",
    "../secret",
    "src/../secret",
    "C:/secret",
    "\\\\server\\share",
  ])("leaves unsafe or external target untouched: %s", (href) => {
    expect(parseInternalFileLink(href)).toBeNull();
  });

  it("maps absolute project files to safe relative paths", () => {
    expect(
      toProjectRelativePath(
        "/Users/demo/project/src/app.ts",
        "/Users/demo/project",
      ),
    ).toBe("src/app.ts");
    expect(
      toProjectRelativePath(
        "C:\\Work\\Project\\src\\app.ts",
        "c:\\work\\project",
      ),
    ).toBe("src/app.ts");
  });

  it("does not map files outside the selected project", () => {
    expect(
      toProjectRelativePath("/Users/demo/other/app.ts", "/Users/demo/project"),
    ).toBeNull();
  });

  it("extracts the real absolute path from a preview URL", () => {
    expect(
      filePathFromPreviewUrl(
        "/api/files/preview/Users/demo/project/hello.txt?token=test",
      ),
    ).toBe("/Users/demo/project/hello.txt");
    expect(
      filePathFromPreviewUrl("/api/files/preview/C%3A/Work/Project/hello.txt"),
    ).toBe("C:/Work/Project/hello.txt");
  });

  it("resolves absolute references against project and workspace roots", () => {
    expect(
      rootForFileReference(
        "/Users/demo/project/src/app.ts",
        "/Users/demo/project",
        "/Users/demo/workspace",
      ),
    ).toBe("project");
    expect(
      rootForFileReference(
        "/Users/demo/workspace/PROFILE.md",
        "/Users/demo/project",
        "/Users/demo/workspace",
      ),
    ).toBe("workspace");
    expect(
      rootForFileReference(
        "C:\\Users\\demo\\workspace\\PROFILE.md",
        "C:\\Users\\demo\\project",
        "c:\\users\\demo\\workspace",
      ),
    ).toBe("workspace");
    expect(
      rootForFileReference(
        "src/app.ts",
        "/Users/demo/project",
        "/Users/demo/workspace",
      ),
    ).toBe("project");
  });
});

describe("parseAbsoluteWorkspaceFileLink", () => {
  it("recognizes generated files with Chinese names and encoded spaces", () => {
    const path = "/workspace/workspaces/default/outputs/回填最终版.xlsx";
    expect(parseAbsoluteWorkspaceFileLink(path)).toBe(path);
    expect(
      parseAbsoluteWorkspaceFileLink(
        "/workspace/workspaces/default/outputs/price%20list.xlsx#L10",
      ),
    ).toBe("/workspace/workspaces/default/outputs/price list.xlsx");
  });

  it.each([
    "outputs/report.xlsx",
    "/workspace-other/report.xlsx",
    "/etc/passwd",
    "/api/workspace/files",
    "https://example.com/workspace/report.xlsx",
    "//example.com/workspace/report.xlsx",
    "/workspace/../secret",
    "/workspace/%2e%2e/secret",
  ])("leaves other links and traversal paths untouched: %s", (href) => {
    expect(parseAbsoluteWorkspaceFileLink(href)).toBeNull();
  });
});
