/**
 * Tests for MediaPreview error handling.
 *
 * Covers the streaming race where the preview is first probed with a
 * relative param path (404) and the tool result later provides an
 * absolute URL — the stale error must be cleared.
 */
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@agentscope-ai/chat/lib/Attachments/FileList/FileListCard", () => ({
  default: ({ item }: { item: { name: string } }) => (
    <div data-testid="file-card">{item.name}</div>
  ),
}));

vi.mock("@agentscope-ai/design", () => ({
  Audio: () => <div data-testid="audio" />,
  Video: () => <div data-testid="video" />,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) =>
      opts && "defaultValue" in opts ? opts.defaultValue ?? "" : key,
  }),
}));

import MediaPreview from "./MediaPreview";
import { useAgentStore } from "../../../../stores/agentStore";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function mockFetchByUrl(responses: Record<string, number>) {
  fetchMock.mockImplementation(async (url: string) => {
    const status = responses[url] ?? 200;
    return new Response(
      JSON.stringify({ detail: status === 404 ? "NOT_FOUND" : "" }),
      {
        status,
        headers: { "Content-Type": "application/json" },
      },
    );
  });
}

describe("MediaPreview error state", () => {
  it("checks a private PDF with the current agent header instead of a bare anonymous fetch", async () => {
    useAgentStore.setState({ selectedAgent: "report-agent" });
    fetchMock.mockImplementation(async (_url: string, options: RequestInit) => {
      const allowed =
        new Headers(options.headers).get("X-Agent-Id") === "report-agent";
      return new Response(
        allowed ? "%PDF-owned" : JSON.stringify({ detail: "FORBIDDEN" }),
        { status: allowed ? 200 : 403 },
      );
    });
    render(
      <MediaPreview
        media={{
          url: "/api/console/artifacts/owned/download",
          name: "防水简报.pdf",
          type: "file",
        }}
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        screen.queryByText("preview.error.FORBIDDEN"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("file-card")).toHaveTextContent("防水简报.pdf");
  });
  it("shows a warning when the file preview URL 404s", async () => {
    mockFetchByUrl({ "/api/files/preview/file1.txt": 404 });

    render(
      <MediaPreview
        media={{
          url: "/api/files/preview/file1.txt",
          name: "file1.txt",
          type: "file",
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("preview.error.NOT_FOUND")).toBeInTheDocument();
    });
  });

  it("clears a stale error once the media URL changes to a valid one", async () => {
    mockFetchByUrl({
      "/api/files/preview/file1.txt": 404,
      "/api/files/preview/abs/path/file1.txt": 200,
    });

    const { rerender } = render(
      <MediaPreview
        media={{
          url: "/api/files/preview/file1.txt",
          name: "file1.txt",
          type: "file",
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("preview.error.NOT_FOUND")).toBeInTheDocument();
    });

    // Tool result arrives with the resolved absolute path
    rerender(
      <MediaPreview
        media={{
          url: "/api/files/preview/abs/path/file1.txt",
          name: "file1.txt",
          type: "file",
        }}
      />,
    );

    await waitFor(() => {
      expect(
        screen.queryByText("preview.error.NOT_FOUND"),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("file-card")).toBeInTheDocument();
  });

  it("opens a file card in Preview without downloading it", async () => {
    mockFetchByUrl({ "/api/files/preview/hello.txt": 200 });
    const onFileOpen = vi.fn();

    render(
      <MediaPreview
        media={{
          url: "/api/files/preview/hello.txt",
          name: "hello.txt",
          type: "file",
        }}
        onFileOpen={onFileOpen}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-card")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId("file-card"));
    expect(onFileOpen).toHaveBeenCalledTimes(1);
  });
});
