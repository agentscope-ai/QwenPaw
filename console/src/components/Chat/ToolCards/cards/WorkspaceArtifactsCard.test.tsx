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

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

vi.mock("../../../../tauri/backendRuntime", () => ({
  isTauriRuntime: () => false,
}));

vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: mocks.messageError } }),
}));

vi.mock("../../../../api/authHeaders", () => ({
  buildAuthHeaders: () => mocks.authHeaders,
}));

vi.mock("../../../../api/modules/workspace", () => ({
  workspaceApi: {
    getArtifactFileUrl: (agentId: string, path: string) =>
      `/artifacts/${agentId}/${path}`,
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
    artifacts: [
      {
        path: "first.txt",
        name: "first.txt",
        extension: ".txt",
        mime_type: "text/plain",
        size: 5,
        change: "created",
        preview: "text",
      },
      {
        path: "second.txt",
        name: "second.txt",
        extension: ".txt",
        mime_type: "text/plain",
        size: 6,
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
    vi.unstubAllGlobals();
  });

  it("accepts the version 1 manifest wrapped in tool output", () => {
    const manifest = JSON.parse(manifestResult());

    expect(parseManifest(JSON.stringify(manifest))).toEqual(manifest);
    expect(parseManifest(JSON.stringify({ manifest }))).toEqual(manifest);
  });

  it("rejects unknown versions, preview kinds, and malformed output", () => {
    expect(parseManifest(JSON.stringify({ version: 2, artifacts: [] }))).toBe(
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
        "/artifacts/analyst/first.txt",
        "first.txt",
        {
          headers: mocks.authHeaders,
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
});
