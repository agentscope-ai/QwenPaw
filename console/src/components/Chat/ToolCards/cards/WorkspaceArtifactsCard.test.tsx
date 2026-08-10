// @vitest-environment jsdom
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ToolCallContent } from "../shared/types";
import WorkspaceArtifactsCard from "./WorkspaceArtifactsCard";
import { parseManifest } from "./workspaceArtifacts";
import { DownloadCancelledError } from "../../../../utils/downloadFileFromUrl";

const mocks = vi.hoisted(() => ({
  authHeaders: { Authorization: "Bearer test-token" },
  download: vi.fn(),
  messageError: vi.fn(),
  invoke: vi.fn(),
  desktop: false,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("antd", () => ({
  Drawer: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div>{children}</div> : null,
  Spin: () => <div data-testid="preview-loading" />,
}));

vi.mock("../shared", () => ({
  ToolCardShell: ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));

vi.mock("../../../../tauri/backendRuntime", () => ({
  isTauriRuntime: () => mocks.desktop,
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: mocks.messageError } }),
}));

vi.mock("../../../../api/authHeaders", () => ({
  buildAuthHeaders: () => mocks.authHeaders,
}));

vi.mock("../../../../api/modules/workspace", () => ({
  workspaceApi: {
    getArtifactFileUrl: (
      agentId: string,
      path: string,
      root = "workspace",
      rootRef?: string,
    ) =>
      `/artifacts/${agentId}/${path}?root=${root}${
        rootRef ? `&root_ref=${rootRef}` : ""
      }`,
    getArtifactPreviewUrl: (
      agentId: string,
      path: string,
      root = "workspace",
      rootRef?: string,
    ) =>
      `/artifact-previews/${agentId}/${path}?root=${root}${
        rootRef ? `&root_ref=${rootRef}` : ""
      }`,
    getArtifactFileUriUrl: (
      agentId: string,
      path: string,
      root = "workspace",
      rootRef?: string,
    ) =>
      `/artifact-file-uris/${agentId}/${path}?root=${root}${
        rootRef ? `&root_ref=${rootRef}` : ""
      }`,
  },
}));

vi.mock("../../../../utils/downloadFileFromUrl", () => {
  class DownloadCancelledError extends Error {}
  return {
    DownloadCancelledError,
    downloadFileFromUrl: mocks.download,
  };
});

vi.mock("../../../../pages/Coding/FilePreview", () => ({
  default: ({
    filePath,
    content,
    previewKind,
  }: {
    filePath: string;
    content: string;
    previewKind: string;
  }) => (
    <div data-testid="file-preview">
      {filePath}:{content}:{previewKind}
    </div>
  ),
}));

function manifestResult() {
  return JSON.stringify({
    version: 1,
    agent_id: "analyst",
    chat_id: "chat-1",
    turn_id: "turn-1",
    created_at: "2026-08-06T00:00:00Z",
    artifacts: [
      {
        path: "first.txt",
        name: "first.txt",
        extension: ".txt",
        mime_type: "text/plain",
        size: 5,
        modified_ns: 1,
        change: "created",
        preview: "text",
      },
      {
        path: "second.txt",
        name: "second.txt",
        extension: ".txt",
        mime_type: "text/plain",
        size: 6,
        modified_ns: 2,
        change: "created",
        preview: "text",
      },
    ],
    changes: [],
    truncated: false,
  });
}

function artifactContent(): ToolCallContent {
  return {
    type: "tool_call",
    id: "call-1",
    name: "workspace_artifacts",
    params: {},
    result: manifestResult(),
    status: "done",
  };
}

function responseWithText(text: string): Response {
  return {
    ok: true,
    status: 200,
    text: async () => text,
  } as Response;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("WorkspaceArtifactsCard", () => {
  beforeEach(() => {
    mocks.download.mockReset();
    mocks.download.mockResolvedValue(undefined);
    mocks.messageError.mockReset();
    mocks.invoke.mockReset();
    mocks.invoke.mockResolvedValue(undefined);
    mocks.desktop = false;
    vi.unstubAllGlobals();
  });

  it("accepts the version 1 manifest wrapped in tool output", () => {
    const manifest = JSON.parse(manifestResult());
    const normalized = {
      ...manifest,
      artifacts: manifest.artifacts.map((artifact: object) => ({
        ...artifact,
        root: "workspace",
      })),
      changes: [],
    };

    expect(parseManifest(JSON.stringify(manifest))).toEqual(normalized);
    expect(parseManifest(JSON.stringify({ manifest }))).toEqual(normalized);
  });

  it("accepts version 2 project artifacts", () => {
    const manifest = JSON.parse(manifestResult());
    manifest.version = 2;
    manifest.artifacts = manifest.artifacts.map((artifact: object) => ({
      ...artifact,
      root: "project",
    }));

    expect(parseManifest(JSON.stringify(manifest))).toEqual(manifest);
  });

  it("accepts version 3 pinned project artifacts", () => {
    const manifest = JSON.parse(manifestResult());
    manifest.version = 3;
    manifest.artifacts = manifest.artifacts.map((artifact: object) => ({
      ...artifact,
      root: "project",
      root_ref: "root-pinned",
    }));

    expect(parseManifest(JSON.stringify(manifest))).toEqual(manifest);
  });

  it("rejects unknown versions, preview kinds, and malformed output", () => {
    expect(parseManifest(JSON.stringify({ version: 3, artifacts: [] }))).toBe(
      null,
    );
    expect(
      parseManifest(
        JSON.stringify({
          version: 1,
          artifacts: [{ preview: "unknown" }],
        }),
      ),
    ).toBeNull();
    expect(parseManifest("not-json")).toBeNull();
  });

  it("passes authentication headers to artifact downloads", async () => {
    render(<WorkspaceArtifactsCard content={artifactContent()} />);

    fireEvent.click(screen.getByLabelText("Download first.txt"));

    await waitFor(() => {
      expect(mocks.download).toHaveBeenCalledWith(
        "/artifacts/analyst/first.txt?root=workspace",
        "first.txt",
        {
          headers: {
            ...mocks.authHeaders,
            "X-Chat-Id": "chat-1",
          },
          errorMessage: "Artifact download failed",
        },
      );
    });
  });

  it("shows feedback when an artifact download fails", async () => {
    mocks.download.mockRejectedValueOnce(new Error("401"));
    render(<WorkspaceArtifactsCard content={artifactContent()} />);

    fireEvent.click(screen.getByLabelText("Download first.txt"));

    await waitFor(() => {
      expect(mocks.messageError).toHaveBeenCalledWith(
        "Artifact download failed",
      );
    });
  });

  it("does not report a cancelled artifact download as an error", async () => {
    mocks.download.mockRejectedValueOnce(new DownloadCancelledError());
    render(<WorkspaceArtifactsCard content={artifactContent()} />);

    fireEvent.click(screen.getByLabelText("Download first.txt"));

    await waitFor(() => expect(mocks.download).toHaveBeenCalledOnce());
    expect(mocks.messageError).not.toHaveBeenCalled();
  });

  it("ignores stale preview responses after switching files", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkspaceArtifactsCard content={artifactContent()} />);

    fireEvent.click(screen.getByLabelText("Preview first.txt"));
    const firstSignal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/artifact-previews/analyst/first.txt?root=workspace",
    );
    expect(fetchMock.mock.calls[0][1].headers).toEqual({
      ...mocks.authHeaders,
      "X-Chat-Id": "chat-1",
    });
    fireEvent.click(screen.getByLabelText("Preview second.txt"));

    expect(firstSignal.aborted).toBe(true);
    second.resolve(responseWithText("second content"));
    await waitFor(() => {
      expect(screen.getByTestId("file-preview")).toHaveTextContent(
        "second.txt:second content:text",
      );
    });

    first.resolve(responseWithText("first content"));
    await Promise.resolve();
    expect(screen.getByTestId("file-preview")).toHaveTextContent(
      "second.txt:second content:text",
    );
  });

  it("shows feedback when opening an artifact fails", async () => {
    mocks.desktop = true;
    mocks.invoke.mockRejectedValueOnce(new Error("permission denied"));
    render(<WorkspaceArtifactsCard content={artifactContent()} />);

    fireEvent.click(screen.getByLabelText("Open first.txt"));

    await waitFor(() => {
      expect(mocks.invoke).toHaveBeenCalledWith("open_workspace_artifact", {
        url: new URL(
          "/artifact-file-uris/analyst/first.txt?root=workspace",
          window.location.origin,
        ).toString(),
        headers: {
          ...mocks.authHeaders,
          "X-Chat-Id": "chat-1",
        },
      });
      expect(mocks.messageError).toHaveBeenCalledWith(
        "Could not open workspace artifact",
      );
    });
  });

  it("passes a project root to desktop artifact commands", async () => {
    mocks.desktop = true;
    const manifest = JSON.parse(manifestResult());
    manifest.version = 2;
    manifest.artifacts = manifest.artifacts.map((artifact: object) => ({
      ...artifact,
      root: "project",
    }));
    render(
      <WorkspaceArtifactsCard
        content={{ ...artifactContent(), result: JSON.stringify(manifest) }}
      />,
    );

    fireEvent.click(screen.getByLabelText("Open first.txt"));

    await waitFor(() => {
      expect(mocks.invoke).toHaveBeenCalledWith("open_workspace_artifact", {
        url: new URL(
          "/artifact-file-uris/analyst/first.txt?root=project",
          window.location.origin,
        ).toString(),
        headers: {
          ...mocks.authHeaders,
          "X-Chat-Id": "chat-1",
        },
      });
    });
  });

  it("passes the pinned root reference to desktop commands", async () => {
    mocks.desktop = true;
    const manifest = JSON.parse(manifestResult());
    manifest.version = 3;
    manifest.artifacts = manifest.artifacts.map((artifact: object) => ({
      ...artifact,
      root: "project",
      root_ref: "root-pinned",
    }));
    render(
      <WorkspaceArtifactsCard
        content={{ ...artifactContent(), result: JSON.stringify(manifest) }}
      />,
    );

    fireEvent.click(screen.getByLabelText("Open first.txt"));

    await waitFor(() => {
      expect(mocks.invoke).toHaveBeenCalledWith("open_workspace_artifact", {
        url: new URL(
          "/artifact-file-uris/analyst/first.txt?root=project&root_ref=root-pinned",
          window.location.origin,
        ).toString(),
        headers: {
          ...mocks.authHeaders,
          "X-Chat-Id": "chat-1",
        },
      });
    });
  });

  it("does not fetch text previews over the size limit", () => {
    const result = JSON.parse(manifestResult());
    result.artifacts[0].size = 5 * 1024 * 1024 + 1;
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(
      <WorkspaceArtifactsCard
        content={{ ...artifactContent(), result: JSON.stringify(result) }}
      />,
    );

    fireEvent.click(screen.getByLabelText("Preview first.txt"));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This file is too large to preview",
    );
  });
});
