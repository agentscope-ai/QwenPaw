/**
 * openHtmlFile renders raw HTML previews across three shells:
 * pywebview (legacy desktop), Tauri (desktop), and blob URL (browser).
 * The workspace-backed flag decides whether native openers are used;
 * blob fallback must always carry the content.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(() => Promise.resolve(undefined)),
}));

vi.mock("../api/authHeaders", () => ({
  buildAuthHeaders: () => ({ Authorization: "Bearer test" }),
}));

vi.mock("../api/modules/workspace", () => ({
  workspaceApi: {
    getHtmlFileUriUrl: vi.fn(
      (path: string, root: string) => `/api/html?path=${path}&root=${root}`,
    ),
  },
}));

const mockIsDesktopTauriRuntime = vi.fn(() => false);
vi.mock("./openExternalLink", () => ({
  isDesktopTauriRuntime: () => mockIsDesktopTauriRuntime(),
}));

const mockGetPyWebViewApi = vi.fn(() => undefined);
vi.mock("./pywebview", () => ({
  getPyWebViewApi: () => mockGetPyWebViewApi(),
}));

import { openHtmlFile } from "./openHtmlFile";
import { invoke } from "@tauri-apps/api/core";
import { workspaceApi } from "../api/modules/workspace";

const baseOptions = {
  content: "<h1>hello</h1>",
  filePath: "report.html",
};

describe("openHtmlFile", () => {
  let createObjectURL: unknown;
  let revokeObjectURL: unknown;
  let openSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    createObjectURL = URL.createObjectURL;
    revokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    // jsdom's window.open is a no-op stub; spy on it to observe navigation
    openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mockIsDesktopTauriRuntime.mockReturnValue(false);
    mockGetPyWebViewApi.mockReturnValue(undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as typeof URL.revokeObjectURL;
  });

  it("falls back to a blob URL in the browser (not workspace backed)", () => {
    openHtmlFile({ ...baseOptions });
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(openSpy).toHaveBeenCalledWith(
      "blob:preview",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("falls back to a blob URL when workspace backed but no native shell", () => {
    openHtmlFile({ ...baseOptions, workspaceBacked: true });
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it("uses the pywebview bridge when workspace backed and available", async () => {
    const openWorkspaceHtml = vi.fn(() => Promise.resolve());
    mockGetPyWebViewApi.mockReturnValue({
      open_workspace_html: openWorkspaceHtml,
    } as any);
    openHtmlFile({ ...baseOptions, workspaceBacked: true, chatId: "chat-1" });
    expect(openWorkspaceHtml).toHaveBeenCalledWith(
      "/api/html?path=report.html&root=project",
      expect.objectContaining({
        Authorization: "Bearer test",
        "X-Chat-Id": "chat-1",
      }),
    );
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("passes the project dir header instead of chat id when there is no chat", async () => {
    const openWorkspaceHtml = vi.fn(() => Promise.resolve());
    mockGetPyWebViewApi.mockReturnValue({
      open_workspace_html: openWorkspaceHtml,
    } as any);
    openHtmlFile({
      ...baseOptions,
      workspaceBacked: true,
      projectDirOverride: "/data/proj",
    });
    const call = openWorkspaceHtml.mock.calls[0] as unknown[];
    const headers = call[1] as Record<string, string>;
    expect(headers["X-Session-Project-Dir"]).toBe("/data/proj");
    expect(headers).not.toHaveProperty("X-Chat-Id");
  });

  it("uses the Tauri invoke when workspace backed in a tauri runtime", () => {
    mockIsDesktopTauriRuntime.mockReturnValue(true);
    openHtmlFile({ ...baseOptions, workspaceBacked: true });
    expect(invoke).toHaveBeenCalledWith("open_workspace_html", {
      url: "/api/html?path=report.html&root=project",
      headers: expect.objectContaining({ Authorization: "Bearer test" }),
    });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("honors the workspace root option", () => {
    openHtmlFile({ ...baseOptions, root: "workspace" });
    expect(workspaceApi.getHtmlFileUriUrl).toHaveBeenCalledWith(
      "report.html",
      "workspace",
    );
  });

  it("does not crash when the native opener rejects", async () => {
    const openWorkspaceHtml = vi.fn(() => Promise.reject(new Error("nope")));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    mockGetPyWebViewApi.mockReturnValue({
      open_workspace_html: openWorkspaceHtml,
    } as any);
    openHtmlFile({ ...baseOptions, workspaceBacked: true });
    // Let the rejection settle
    await Promise.resolve();
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});
