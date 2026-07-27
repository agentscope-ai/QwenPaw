import { describe, expect, it } from "vitest";
import {
  parseInternalFileLink,
  filePathFromPreviewUrl,
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
});
