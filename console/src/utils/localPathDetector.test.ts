// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock Tauri APIs before importing the module under test.
import { invoke, isTauri } from "../test/tauri-mock";

import {
  findLocalPaths,
  isLocalPath,
  normalizeLocalPath,
  openInExplorer,
} from "./localPathDetector";

describe("isLocalPath", () => {
  it("recognizes Windows drive paths", () => {
    expect(isLocalPath("C:\\Users\\alice\\file.txt")).toBe(true);
    expect(isLocalPath("D:/projects/src")).toBe(true);
    expect(isLocalPath("c:\\temp")).toBe(true);
  });

  it("recognizes Unix absolute paths", () => {
    expect(isLocalPath("/home/alice/file.txt")).toBe(true);
    expect(isLocalPath("/usr/local/bin/node")).toBe(true);
    expect(isLocalPath("/tmp")).toBe(true);
  });

  it("recognizes home-directory shorthand", () => {
    expect(isLocalPath("~/Documents/report.pdf")).toBe(true);
    expect(isLocalPath("~/.config/settings.json")).toBe(true);
  });

  it("rejects URLs with schemes", () => {
    expect(isLocalPath("https://example.com/path")).toBe(false);
    expect(isLocalPath("http://localhost:3000")).toBe(false);
    expect(isLocalPath("ftp://files.example.com/data")).toBe(false);
  });

  it("rejects relative paths", () => {
    expect(isLocalPath("foo/bar")).toBe(false);
    expect(isLocalPath("./src/main.ts")).toBe(false);
    expect(isLocalPath("../config.json")).toBe(false);
  });

  it("rejects empty or whitespace-only strings", () => {
    expect(isLocalPath("")).toBe(false);
    expect(isLocalPath("   ")).toBe(false);
  });
});

describe("findLocalPaths", () => {
  it("finds Windows paths in mixed text", () => {
    const text = "Saved to C:\\Users\\alice\\output.txt and also D:/backup.zip";
    const results = findLocalPaths(text);
    expect(results).toHaveLength(2);
    expect(results[0].path).toBe("C:\\Users\\alice\\output.txt");
    expect(results[1].path).toBe("D:/backup.zip");
  });

  it("finds Unix paths in mixed text", () => {
    const text = "The config is at /etc/nginx/nginx.conf for details.";
    const results = findLocalPaths(text);
    expect(results.length).toBeGreaterThanOrEqual(1);
    expect(results[0].path).toBe("/etc/nginx/nginx.conf");
  });

  it("finds ~/ paths", () => {
    const text = "You can find it in ~/Downloads/file.tar.gz.";
    const results = findLocalPaths(text);
    expect(results).toHaveLength(1);
    expect(results[0].path).toBe("~/Downloads/file.tar.gz");
  });

  it("strips trailing punctuation from detected paths", () => {
    const text = "Check /home/user/report.pdf.";
    const results = findLocalPaths(text);
    expect(results).toHaveLength(1);
    // Trailing period should be stripped.
    expect(results[0].path).not.toMatch(/\.$/);
  });

  it("returns empty array for text without paths", () => {
    expect(findLocalPaths("Hello world")).toEqual([]);
    expect(findLocalPaths("https://example.com")).toEqual([]);
  });

  it("finds multiple paths in a single string", () => {
    const text = "First: /home/a.txt, Second: C:\\b.txt, Third: ~/c.txt";
    const results = findLocalPaths(text);
    expect(results.length).toBeGreaterThanOrEqual(3);
  });

  it("does not treat prose slashes as Unix paths", () => {
    expect(findLocalPaths("IMAP/SMTP protocol")).toEqual([]);
    expect(findLocalPaths("CI/CD pipeline")).toEqual([]);
    expect(findLocalPaths("Terraform/OpenTofu tools")).toEqual([]);
    expect(findLocalPaths("使用 IMAP/SMTP 管理邮件")).toEqual([]);
    expect(findLocalPaths("频道/会话发送消息")).toEqual([]);
    expect(findLocalPaths("定时/周期性任务管理")).toEqual([]);
  });

  it("still detects real Unix paths after whitespace", () => {
    const results = findLocalPaths("see /tmp/file.txt and /home/user/doc");
    expect(results).toHaveLength(2);
    expect(results[0].path).toBe("/tmp/file.txt");
    expect(results[1].path).toBe("/home/user/doc");
  });
});

describe("normalizeLocalPath", () => {
  it("strips trailing periods and commas", () => {
    expect(normalizeLocalPath("/home/user/file.txt.")).toBe(
      "/home/user/file.txt",
    );
    expect(normalizeLocalPath("C:\\Users\\test,")).toBe("C:\\Users\\test");
  });

  it("strips trailing question marks and exclamation marks", () => {
    expect(normalizeLocalPath("~/docs/readme?")).toBe("~/docs/readme");
    expect(normalizeLocalPath("/usr/bin!")).toBe("/usr/bin");
  });

  it("trims whitespace", () => {
    expect(normalizeLocalPath("  /home/user  ")).toBe("/home/user");
  });

  it("preserves internal punctuation", () => {
    expect(normalizeLocalPath("/home/user/my-file_v2.txt")).toBe(
      "/home/user/my-file_v2.txt",
    );
  });
});

describe("openInExplorer", () => {
  beforeEach(() => {
    invoke.mockReset();
    isTauri.mockReturnValue(false);
    invoke.mockResolvedValue(undefined);
    delete (window as any).__TAURI_INTERNALS__;
    delete (window as any).pywebview;
    sessionStorage.clear();
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is a no-op outside the desktop app", async () => {
    await openInExplorer("/home/user/file.txt");
    expect(invoke).not.toHaveBeenCalled();
  });

  it("invokes the Tauri command inside the desktop app", async () => {
    isTauri.mockReturnValue(true);

    await openInExplorer("/home/user/file.txt");

    expect(invoke).toHaveBeenCalledWith("open_in_explorer", {
      path: "/home/user/file.txt",
    });
  });

  it("normalizes the path before invoking", async () => {
    isTauri.mockReturnValue(true);

    await openInExplorer("  C:\\Users\\test.txt.  ");

    expect(invoke).toHaveBeenCalledWith("open_in_explorer", {
      path: "C:\\Users\\test.txt",
    });
  });

  it("logs a warning when the Tauri command fails", async () => {
    isTauri.mockReturnValue(true);
    invoke.mockRejectedValue(new Error("permission denied"));

    await openInExplorer("/home/user/file.txt");

    expect(console.warn).toHaveBeenCalledWith(
      "[local-path] open_in_explorer failed:",
      expect.any(Error),
    );
  });

  it("uses the pywebview bridge when available", async () => {
    const openInExplorerMock = vi.fn().mockResolvedValue(true);
    (window as any).pywebview = {
      api: {
        open_in_explorer: openInExplorerMock,
      },
    };
    // Simulate pywebview desktop detection via URL parameter.
    window.history.replaceState(null, "", "/?desktop=1");

    await openInExplorer("/home/user/file.txt");

    expect(openInExplorerMock).toHaveBeenCalledWith("/home/user/file.txt");
    // Tauri invoke should NOT be called when pywebview bridge handles it.
    expect(invoke).not.toHaveBeenCalled();
  });

  it("falls back to Tauri when pywebview bridge lacks open_in_explorer", async () => {
    (window as any).pywebview = {
      api: {
        // No open_in_explorer method.
        open_external_link: vi.fn(),
      },
    };
    isTauri.mockReturnValue(true);

    await openInExplorer("/home/user/file.txt");

    expect(invoke).toHaveBeenCalledWith("open_in_explorer", {
      path: "/home/user/file.txt",
    });
  });
});
