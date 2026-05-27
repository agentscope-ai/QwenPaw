import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tauriMocks = vi.hoisted(() => ({
  invoke: vi.fn(),
  isTauri: vi.fn(() => false),
}));
const dialogMocks = vi.hoisted(() => ({
  save: vi.fn(),
}));
const fsMocks = vi.hoisted(() => ({
  writeFile: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: tauriMocks.invoke,
  isTauri: tauriMocks.isTauri,
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({
  save: dialogMocks.save,
}));
vi.mock("@tauri-apps/plugin-fs", () => ({
  writeFile: fsMocks.writeFile,
}));

import { downloadFileFromUrl } from "./downloadFileFromUrl";
import { openExternalLink } from "./openExternalLink";
import { installTauriExternalLinkInterceptor } from "../tauri/externalLinkInterceptor";

describe("openExternalLink", () => {
  const windowOpen = vi.fn();
  const fetchMock = vi.fn();

  beforeEach(() => {
    tauriMocks.invoke.mockReset();
    tauriMocks.isTauri.mockReturnValue(false);
    tauriMocks.invoke.mockResolvedValue(undefined);
    dialogMocks.save.mockReset();
    fsMocks.writeFile.mockReset();
    fsMocks.writeFile.mockResolvedValue(undefined);
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
    tauriMocks.isTauri.mockReturnValue(true);

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");

    expect(openExternal).toHaveBeenCalledWith(
      "https://github.com/agentscope-ai/QwenPaw",
    );
    expect(tauriMocks.invoke).not.toHaveBeenCalled();
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

    expect(tauriMocks.invoke).not.toHaveBeenCalled();
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses the Tauri external link command for supported non-HTTP schemes", () => {
    tauriMocks.isTauri.mockReturnValue(true);

    openExternalLink("mailto:support@example.com");

    expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
      url: "mailto:support@example.com",
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses the Tauri external link command in the Tauri desktop app", () => {
    tauriMocks.isTauri.mockReturnValue(true);

    openExternalLink("https://qwenpaw.agentscope.io/docs/intro?lang=zh");

    expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
      url: "https://qwenpaw.agentscope.io/docs/intro?lang=zh",
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("uses injected Tauri internals when isTauri is false", () => {
    (window as any).__TAURI_INTERNALS__ = {
      invoke: vi.fn(),
    };

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");

    expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
      url: "https://github.com/agentscope-ai/QwenPaw",
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("logs Tauri external link failures without falling back to window.open", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    tauriMocks.invoke.mockRejectedValue(new Error("permission denied"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");
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

  it("opens backend-hosted desktop links through the desktop backend", async () => {
    window.history.replaceState(null, "", "/console/inbox");
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");
    await Promise.resolve();

    expect(fetchMock).toHaveBeenCalledWith("/api/desktop/open-external-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: "https://github.com/agentscope-ai/QwenPaw",
      }),
    });
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("prefers the desktop backend for backend-hosted Tauri consoles", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    window.history.replaceState(null, "", "/console/inbox");
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");
    await Promise.resolve();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/desktop/open-external-link",
      expect.any(Object),
    );
    expect(tauriMocks.invoke).not.toHaveBeenCalled();
    expect(windowOpen).not.toHaveBeenCalled();
  });

  it("falls back to window.open when the desktop backend is unavailable", async () => {
    window.history.replaceState(null, "", "/console/inbox");
    fetchMock.mockResolvedValue(new Response("nope", { status: 404 }));

    openExternalLink("https://github.com/agentscope-ai/QwenPaw");
    await Promise.resolve();
    await Promise.resolve();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/desktop/open-external-link",
      expect.any(Object),
    );
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
    tauriMocks.isTauri.mockReturnValue(true);

    openExternalLink("/docs/faq");

    expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
      url: "http://localhost:3000/docs/faq",
    });
  });

  it("intercepts Tauri anchor clicks without swallowing other handlers", () => {
    tauriMocks.isTauri.mockReturnValue(true);
    const cleanup = installTauriExternalLinkInterceptor();
    const targetClick = vi.fn();
    const anchor = document.createElement("a");
    anchor.href = "https://example.com/docs";
    anchor.target = "_blank";
    anchor.addEventListener("click", targetClick);
    document.body.appendChild(anchor);

    try {
      const cancelled = !anchor.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          button: 0,
        }),
      );

      expect(cancelled).toBe(true);
      expect(targetClick).toHaveBeenCalledTimes(1);
      expect(targetClick.mock.calls[0]?.[0].defaultPrevented).toBe(true);
      expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
        url: "https://example.com/docs",
      });
      expect(windowOpen).not.toHaveBeenCalled();
    } finally {
      anchor.remove();
      cleanup();
    }
  });

  it("installs the Tauri external link interceptor only once", () => {
    tauriMocks.isTauri.mockReturnValue(true);
    const cleanupA = installTauriExternalLinkInterceptor();
    const cleanupB = installTauriExternalLinkInterceptor();
    const anchor = document.createElement("a");
    anchor.href = "https://example.com/docs";
    anchor.target = "_blank";
    document.body.appendChild(anchor);

    try {
      anchor.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          button: 0,
        }),
      );

      expect(tauriMocks.invoke).toHaveBeenCalledTimes(1);
      expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
        url: "https://example.com/docs",
      });

      cleanupB();
      tauriMocks.invoke.mockClear();

      anchor.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          button: 0,
        }),
      );

      expect(tauriMocks.invoke).toHaveBeenCalledTimes(1);
    } finally {
      anchor.remove();
      cleanupA();
      cleanupB();
    }
  });

  it("does not intercept relative anchor clicks in the Tauri shell", () => {
    tauriMocks.isTauri.mockReturnValue(true);
    const cleanup = installTauriExternalLinkInterceptor();
    const targetClick = vi.fn((event: MouseEvent) => event.preventDefault());
    const anchor = document.createElement("a");
    anchor.href = "/settings";
    anchor.addEventListener("click", targetClick);
    document.body.appendChild(anchor);

    try {
      anchor.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          button: 0,
        }),
      );

      expect(targetClick).toHaveBeenCalled();
      expect(tauriMocks.invoke).not.toHaveBeenCalled();
      expect(windowOpen).not.toHaveBeenCalled();
    } finally {
      anchor.remove();
      cleanup();
    }
  });

  it("routes Tauri window.open calls through the external link command", () => {
    tauriMocks.isTauri.mockReturnValue(true);
    const cleanup = installTauriExternalLinkInterceptor();

    try {
      const result = window.open(
        "https://example.com/search",
        "_blank",
        "noopener",
      );

      expect(result).toBeNull();
      expect(tauriMocks.invoke).toHaveBeenCalledWith("open_external_link", {
        url: "https://example.com/search",
      });
      expect(windowOpen).not.toHaveBeenCalled();
    } finally {
      cleanup();
    }
  });

  it("downloads Tauri files with fetch headers and native file writing", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    dialogMocks.save.mockResolvedValue("C:\\Downloads\\server.zip");
    localStorage.setItem("qwenpaw_auth_token", "tok");
    fetchMock.mockResolvedValue(
      new Response("zip", {
        headers: {
          "Content-Disposition": 'attachment; filename="server.zip"',
        },
      }),
    );

    await expect(
      downloadFileFromUrl("/api/workspace/download", "workspace.zip", {
        headers: { "X-Agent-Id": "agent-a" },
        preferResponseFilename: true,
      }),
    ).resolves.toBe(true);

    expect(dialogMocks.save).toHaveBeenCalledWith({
      defaultPath: "workspace.zip",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:3000/api/workspace/download",
      { headers: { "X-Agent-Id": "agent-a" } },
    );
    expect(dialogMocks.save.mock.invocationCallOrder[0]).toBeLessThan(
      fetchMock.mock.invocationCallOrder[0],
    );
    expect(fsMocks.writeFile).toHaveBeenCalledWith(
      "C:\\Downloads\\server.zip",
      expect.any(Uint8Array),
    );
    expect(tauriMocks.invoke).not.toHaveBeenCalled();
  });

  it("sanitizes Tauri save dialog filenames for Windows", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    dialogMocks.save.mockResolvedValue("C:\\Downloads\\backup.zip");
    fetchMock.mockResolvedValue(new Response("zip"));

    await expect(
      downloadFileFromUrl(
        "/api/backups/abc/export",
        "Backup 2026-05-22 14:13.zip",
      ),
    ).resolves.toBe(true);

    expect(dialogMocks.save).toHaveBeenCalledWith({
      defaultPath: "Backup 2026-05-22 14_13.zip",
    });
    expect(fetchMock).toHaveBeenCalled();
    expect(fsMocks.writeFile).toHaveBeenCalled();
  });

  it("reports Tauri download cancellation without writing a file", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    dialogMocks.save.mockResolvedValue(null);
    fetchMock.mockResolvedValue(new Response("zip"));

    await expect(
      downloadFileFromUrl("/api/workspace/download", "workspace.zip", {
        headers: { "X-Agent-Id": "agent-a" },
      }),
    ).resolves.toBe(false);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(fsMocks.writeFile).not.toHaveBeenCalled();
  });

  it("does not write a Tauri download when fetch fails", async () => {
    tauriMocks.isTauri.mockReturnValue(true);
    dialogMocks.save.mockResolvedValue("C:\\Downloads\\server.zip");
    fetchMock.mockResolvedValue(new Response("nope", { status: 500 }));

    await expect(
      downloadFileFromUrl("/api/workspace/download", "workspace.zip", {
        errorMessage: "Export failed",
      }),
    ).rejects.toThrow("Export failed");

    expect(fsMocks.writeFile).not.toHaveBeenCalled();
  });

  it("does not add auth query parameters to external API-shaped downloads", async () => {
    localStorage.setItem("qwenpaw_auth_token", "tok");
    fetchMock.mockResolvedValue(new Response("zip"));

    await expect(
      downloadFileFromUrl("https://evil.example/api/export", "backup.zip", {
        headers: { "X-Agent-Id": "agent-a" },
      }),
    ).resolves.toBe(true);

    expect(fetchMock).toHaveBeenCalledWith("https://evil.example/api/export", {
      headers: { "X-Agent-Id": "agent-a" },
    });
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
    ).resolves.toBe(true);

    expect(click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith("blob:download");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:download");
  });
});
