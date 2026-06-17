// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The vite.config.ts aliases @tauri-apps/api/core and @tauri-apps/plugin-dialog
// to src/test/tauri-mock.ts, which exports vi.fn() instances we can control directly.
import { invoke, isTauri, save } from "../test/tauri-mock";

import {
  DownloadCancelledError,
  downloadFileFromUrl,
} from "./downloadFileFromUrl";
import { openExternalLink } from "./openExternalLink";

describe("openExternalLink", () => {
  const windowOpen = vi.fn();
  const fetchMock = vi.fn();

  beforeEach(() => {
    invoke.mockReset();
    isTauri.mockReturnValue(false);
    invoke.mockResolvedValue(undefined);
    save.mockReset();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:download"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    windowOpen.mockReset();
    vi.spyOn(window, "open").mockImplementation(windowOpen);
    delete (window as any).pywebview;
    delete (window as any).__TAURI_INTERNALS__;
    localStorage.clear();
    (globalThis as any).VITE_API_BASE_URL = "";
    (globalThis as any).TOKEN = "";
    window.history.replaceState(null, "", "/");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("uses the pywebview bridge for the legacy desktop app", () => {
    const openExternal = vi.fn();
    (window as any).pywebview = {
      api: {
        open_external_link: openExternal,
      },
    };
    isTauri.mockReturnValue(true);

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");

    expect(openExternal).toHaveBeenCalledWith(
      "https://github.com/agentscope-ai/QwenPaw",
    );
    expect(invoke).not.toHaveBeenCalled();
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("does not send non-HTTP links to the legacy pywebview bridge", () => {
    const openExternal = vi.fn();
    (window as any).pywebview = {
      api: {
        open_external_link: openExternal,
      },
    };

    openExternalLink("mailto:support@example.com");

    expect(openExternal).not.toHaveBeenCalled();
    expect(windowOpen).toHaveBeenCalledWith(
      "mailto:support@example.com",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("ignores unsafe or fragment-only links", () => {
    openExternalLink("javascript:alert(1)");
    openExternalLink("#");

    expect(invoke).not.toHaveBeenCalled();
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("rejects ambiguous HTTP links without slashes before opening", () => {
    isTauri.mockReturnValue(true);

    openExternalLink("http:example.com");

    expect(invoke).not.toHaveBeenCalled();
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses the Tauri external link command for supported non-HTTP schemes", () => {
    isTauri.mockReturnValue(true);

    openExternalLink("mailto:support@example.com");

    expect(invoke).toHaveBeenCalledWith("open_external_link", {
      url: "mailto:support@example.com",
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses the Tauri external link command in the Tauri desktop app", () => {
    isTauri.mockReturnValue(true);

    openExternalLink("https://qwenpaw.agentscope.io/docs/intro?lang=zh");

    expect(invoke).toHaveBeenCalledWith("open_external_link", {
      url: "https://qwenpaw.agentscope.io/docs/intro?lang=zh",
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses injected Tauri internals when isTauri is false", () => {
    (window as any).__TAURI_INTERNALS__ = {
      invoke: vi.fn(),
    };

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");

    expect(invoke).toHaveBeenCalledWith("open_external_link", {
      url: "https://github.com/agentscope-ai/QwenPaw",
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("logs Tauri external link failures without falling back to window.open", async () => {
    isTauri.mockReturnValue(true);
    invoke.mockRejectedValue(new Error("permission denied"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");
    await Promise.resolve();
    await Promise.resolve();

    expect(windowOpen).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
  });

  it("falls back to window.open in the web console", () => {
    openExternalLink("https://qwenpaw.agentscope.io/docs/intro?lang=en");

    expect(windowOpen).toHaveBeenCalledWith(
      "https://qwenpaw.agentscope.io/docs/intro?lang=en",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("uses the Tauri command from backend-hosted Tauri consoles", () => {
    (window as any).__TAURI_INTERNALS__ = {
      invoke: vi.fn(),
    };
    window.history.replaceState(null, "", "/console/inbox");

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");

    expect(invoke).toHaveBeenCalledWith("open_external_link", {
      url: "https://github.com/agentscope-ai/QwenPaw",
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses window.open for backend-hosted browser consoles", () => {
    window.history.replaceState(null, "", "/console/inbox");

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(windowOpen).toHaveBeenCalledWith(
      "https://github.com/agentscope-ai/QwenPaw",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("does not add auth query parameters to generic external links", () => {
    localStorage.setItem("qwenpaw_auth_token", "tok");

    openExternalLink("https://evil.example/api/foo");

    expect(windowOpen).toHaveBeenCalledWith(
      "https://evil.example/api/foo",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("resolves relative links before passing them to desktop bridges", () => {
    isTauri.mockReturnValue(true);

    openExternalLink("/docs/faq");

    expect(invoke).toHaveBeenCalledWith("open_external_link", {
      url: "http://localhost:3000/docs/faq",
    });
  });

  it("downloads Tauri files with headers through the native backend command", async () => {
    isTauri.mockReturnValue(true);
    save.mockResolvedValue("C:\\Downloads\\server.zip");
    localStorage.setItem("qwenpaw_auth_token", "tok");

    await expect(
      downloadFileFromUrl("/api/workspace/download", "workspace.zip", {
        headers: { "X-Agent-Id": "agent-a" },
        preferResponseFilename: true,
      }),
    ).resolves.toBeUndefined();

    expect(save).toHaveBeenCalledWith({
      defaultPath: "workspace.zip",
    });
    expect(invoke).toHaveBeenCalledWith("download_backend_file", {
      request: {
        url: "http://localhost:3000/api/workspace/download",
        filePath: "C:\\Downloads\\server.zip",
        headers: { "X-Agent-Id": "agent-a" },
      },
    });
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(
      invoke.mock.invocationCallOrder[0],
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(
      invoke.mock.calls.some(([command]) => command === "open_external_link"),
    ).toBe(false);
  });

  it("uses the pywebview save bridge for legacy desktop downloads", async () => {
    const saveFile = vi.fn().mockResolvedValue(true);
    (window as any).pywebview = {
      api: {
        save_file: saveFile,
      },
    };

    await expect(
      downloadFileFromUrl(
        "/api/backups/abc/export",
        "Backup 2026-05-22 14:13.zip",
        {
          headers: { Authorization: "Bearer tok" },
          errorMessage: "Export failed",
        },
      ),
    ).resolves.toBeUndefined();

    expect(saveFile).toHaveBeenCalledWith(
      "http://localhost:3000/api/backups/abc/export",
      "Backup 2026-05-22 14_13.zip",
      { Authorization: "Bearer tok" },
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(save).not.toHaveBeenCalled();
  });

  it("keeps legacy pywebview downloads backward-compatible without headers", async () => {
    const saveFile = vi.fn().mockResolvedValue(true);
    (window as any).pywebview = {
      api: {
        save_file: saveFile,
      },
    };

    await expect(
      downloadFileFromUrl("/api/backups/abc/export", "backup.zip"),
    ).resolves.toBeUndefined();

    expect(saveFile).toHaveBeenCalledWith(
      "http://localhost:3000/api/backups/abc/export",
      "backup.zip",
    );
  });

  it("sanitizes Tauri save dialog filenames for Windows", async () => {
    isTauri.mockReturnValue(true);
    save.mockResolvedValue("C:\\Downloads\\backup.zip");

    await expect(
      downloadFileFromUrl(
        "/api/backups/abc/export",
        "Backup 2026-05-22 14:13.zip",
      ),
    ).resolves.toBeUndefined();

    expect(save).toHaveBeenCalledWith({
      defaultPath: "Backup 2026-05-22 14_13.zip",
    });
    expect(invoke).toHaveBeenCalledWith(
      "download_backend_file",
      expect.objectContaining({
        request: expect.objectContaining({
          filePath: "C:\\Downloads\\backup.zip",
        }),
      }),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reports Tauri download cancellation before starting the native download", async () => {
    isTauri.mockReturnValue(true);
    save.mockResolvedValue(null);
    fetchMock.mockResolvedValue(new Response("zip"));

    await expect(
      downloadFileFromUrl("/api/workspace/download", "workspace.zip", {
        headers: { "X-Agent-Id": "agent-a" },
      }),
    ).rejects.toBeInstanceOf(DownloadCancelledError);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalledWith(
      "download_backend_file",
      expect.anything(),
    );
  });

  it("surfaces Tauri native download failures with the caller's message", async () => {
    isTauri.mockReturnValue(true);
    save.mockResolvedValue("C:\\Downloads\\server.zip");
    invoke.mockRejectedValue(new Error("HTTP 500"));

    await expect(
      downloadFileFromUrl("/api/workspace/download", "workspace.zip", {
        errorMessage: "Export failed",
      }),
    ).rejects.toThrow("Export failed");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not add auth query parameters to external API-shaped downloads", async () => {
    localStorage.setItem("qwenpaw_auth_token", "tok");
    fetchMock.mockResolvedValue(new Response("zip"));

    await expect(
      downloadFileFromUrl("https://evil.example/api/export", "backup.zip", {
        headers: { "X-Agent-Id": "agent-a" },
      }),
    ).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith("https://evil.example/api/export", {
      headers: { "X-Agent-Id": "agent-a" },
    });
  });

  it("rejects non-HTTP URLs before selecting a download runtime", async () => {
    isTauri.mockReturnValue(true);
    save.mockResolvedValue("C:\\Downloads\\mail.zip");

    await expect(
      downloadFileFromUrl("mailto:support@example.com", "mail.zip"),
    ).rejects.toThrow("Download URL is invalid");

    expect(save).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalledWith(
      "download_backend_file",
      expect.anything(),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects ambiguous HTTP downloads without slashes", async () => {
    await expect(
      downloadFileFromUrl("http:example.com/export.zip", "backup.zip"),
    ).rejects.toThrow("Download URL is invalid");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(invoke).not.toHaveBeenCalledWith(
      "download_backend_file",
      expect.anything(),
    );
  });

  it("uses browser downloads outside Tauri", async () => {
    fetchMock.mockResolvedValue(
      new Response("zip", {
        headers: {
          "Content-Disposition": "attachment; filename*=UTF-8''server.zip",
        },
      }),
    );
    const click = vi.fn();
    const createElement = vi.spyOn(document, "createElement");
    createElement.mockImplementation((tagName: string) => {
      const element = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tagName,
      ) as HTMLElement;
      if (tagName === "a") {
        element.click = click;
      }
      return element;
    });

    await expect(
      downloadFileFromUrl("/api/backups/abc/export", "backup.zip", {
        preferResponseFilename: true,
      }),
    ).resolves.toBeUndefined();

    expect(click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith("blob:download");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:download");
  });
});
