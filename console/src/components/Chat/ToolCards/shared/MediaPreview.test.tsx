/**
 * Tests for MediaPreview error handling.
 *
 * Covers the streaming race where the preview is first probed with a
 * relative param path (404) and the tool result later provides an
 * absolute URL — the stale error must be cleared.
 */
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("@agentscope-ai/chat", () => ({
  Attachments: {
    FileCard: ({ item }: { item: { name: string } }) => (
      <div data-testid="file-card">{item.name}</div>
    ),
  },
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

vi.mock("../../../../utils/openExternalLink", () => ({
  openExternalLink: vi.fn(),
}));

import MediaPreview from "./MediaPreview";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

function mockFetchByUrl(responses: Record<string, number>) {
  fetchMock.mockImplementation(async (url: string) => {
    const status = responses[url] ?? 200;
    return {
      ok: status === 200,
      status,
      json: async () => ({ detail: status === 404 ? "NOT_FOUND" : "" }),
    };
  });
}

describe("MediaPreview file probe", () => {
  it("probes file URLs with HEAD and dedupes concurrent probes", async () => {
    mockFetchByUrl({});
    const media = {
      url: "/api/files/preview/probe-head.txt",
      name: "probe-head.txt",
      type: "file" as const,
    };

    render(
      <>
        <MediaPreview media={media} />
        <MediaPreview media={media} />
      </>,
    );

    await waitFor(() => {
      expect(screen.getAllByTestId("file-card")).toHaveLength(2);
    });
    // Two previews of the same URL share a single HEAD request.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(media.url, { method: "HEAD" });
  });

  it("treats 405 (HEAD not allowed) as accessible without a GET fallback", async () => {
    mockFetchByUrl({ "/api/files/preview/probe-405.txt": 405 });

    render(
      <MediaPreview
        media={{
          url: "/api/files/preview/probe-405.txt",
          name: "probe-405.txt",
          type: "file",
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-card")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/preview\.error/)).not.toBeInTheDocument();
  });

  it("falls back to GET for the error detail when HEAD fails", async () => {
    mockFetchByUrl({ "/api/files/preview/probe-404.txt": 404 });

    render(
      <MediaPreview
        media={{
          url: "/api/files/preview/probe-404.txt",
          name: "probe-404.txt",
          type: "file",
        }}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("preview.error.NOT_FOUND")).toBeInTheDocument();
    });
    // HEAD probe first, then a GET fallback for the detail code. Failed
    // probes are not cached, so exact call counts vary under StrictMode's
    // double effect invocation — assert on the call shapes instead.
    const calls = fetchMock.mock.calls;
    expect(calls[0]).toEqual([
      "/api/files/preview/probe-404.txt",
      { method: "HEAD" },
    ]);
    expect(
      calls.some(
        (c) =>
          c[0] === "/api/files/preview/probe-404.txt" && c[1] === undefined,
      ),
    ).toBe(true);
  });
});

describe("MediaPreview error state", () => {
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
});
