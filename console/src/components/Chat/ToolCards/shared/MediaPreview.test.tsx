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
import userEvent from "@testing-library/user-event";

vi.mock("@agentscope-ai/chat", () => ({
  Attachments: {
    FileCard: ({ item }: { item: { name: string } }) => (
      <div data-testid="file-card">{item.name}</div>
    ),
  },
}));

vi.mock("@agentscope-ai/design", () => ({
  Audio: () => (
    <div data-testid="audio">
      <div className="spark-media-player-controller">
        <button type="button" data-testid="play-button">
          play
        </button>
        <button type="button" data-testid="volume-button">
          volume
        </button>
        <span>00:00</span>
        <div className="spark-media-progress-container" />
        <span>00:00</span>
      </div>
    </div>
  ),
  Video: () => <div data-testid="video" />,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) =>
      opts && "defaultValue" in opts ? opts.defaultValue ?? "" : key,
  }),
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

describe("MediaPreview error state", () => {
  it("shows a download action for audio previews", () => {
    render(
      <MediaPreview
        media={{
          url: "/api/files/preview/media.audio",
          name: "media.audio",
          type: "audio",
        }}
      />,
    );

    expect(
      screen.getByRole("button", { name: "common.download" }),
    ).toBeInTheDocument();
  });

  it.each(["image", "video"] as const)(
    "does not show a download action for %s previews",
    (type) => {
      render(
        <MediaPreview
          media={{
            url: `/api/files/preview/media.${type}`,
            name: `media.${type}`,
            type,
          }}
        />,
      );

      expect(
        screen.queryByRole("button", { name: "common.download" }),
      ).not.toBeInTheDocument();
    },
  );

  it("keeps the failure compact until its details are opened", async () => {
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

    const trigger = await screen.findByRole("button", { name: /file1.txt/ });
    const details = screen.getByText("preview.error.NOT_FOUND");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("preview.unavailable")).toBeVisible();
    expect(details).not.toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(details).toBeVisible();
    expect(
      document.getElementById(trigger.getAttribute("aria-controls")!),
    ).toContainElement(details);

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(details).not.toBeVisible();
  });

  it("supports keyboard activation and a hover hint", async () => {
    const user = userEvent.setup();
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

    const trigger = await screen.findByRole("button", { name: /file1.txt/ });
    await user.hover(trigger);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      "preview.showDetails",
    );
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.unhover(trigger);
    await user.tab();
    expect(trigger).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("preview.error.NOT_FOUND")).toBeVisible();
    await user.keyboard(" ");
    expect(screen.getByText("preview.error.NOT_FOUND")).not.toBeVisible();
  });

  it("shows the full filename inside the expanded details", async () => {
    const filename = "很长的文件名_browser_screenshot_2815ac68.png";
    mockFetchByUrl({ "/api/files/preview/missing.png": 404 });
    render(
      <MediaPreview
        media={{
          url: "/api/files/preview/missing.png",
          name: filename,
          type: "file",
        }}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: new RegExp(filename) }),
    );
    expect(screen.getAllByText(filename)).toHaveLength(2);
    expect(screen.getAllByText(filename)[1]).toBeVisible();
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
    fireEvent.click(screen.getByRole("button", { name: /file1.txt/ }));
    expect(screen.getByText("preview.error.NOT_FOUND")).toBeVisible();

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

    rerender(
      <MediaPreview
        media={{
          url: "/api/files/preview/file1.txt",
          name: "file1.txt",
          type: "file",
        }}
      />,
    );
    expect(
      await screen.findByRole("button", { name: /file1.txt/ }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("preview.error.NOT_FOUND")).not.toBeVisible();
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
