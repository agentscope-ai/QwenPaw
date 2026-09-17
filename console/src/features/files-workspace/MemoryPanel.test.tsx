import { renderWithProviders } from "@/test/common_setup";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { agentApi } from "../../api/modules/agent";
import { workspaceApi } from "../../api/modules/workspace";
import type { FileLocator } from "./fileLocator";
import MemoryPanel from "./MemoryPanel";

vi.mock("../../api/modules/agent", () => ({
  agentApi: { getMemoryScopes: vi.fn() },
}));
vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    listMemoryFiles: vi.fn(),
    loadMemoryFile: vi.fn(),
  },
}));

const publicScope = {
  scope: "public" as const,
  can_read: true,
  can_edit: false,
  status: "active" as const,
  index_state: "ready" as const,
  index_version: 1,
};
const privateScope = {
  ...publicScope,
  scope: "private" as const,
  index_state: "reindex_failed" as const,
};

describe("MemoryPanel", () => {
  beforeEach(() => {
    vi.mocked(agentApi.getMemoryScopes).mockReset();
    vi.mocked(workspaceApi.listMemoryFiles).mockReset();
    vi.mocked(workspaceApi.loadMemoryFile).mockReset();
    vi.mocked(agentApi.getMemoryScopes).mockResolvedValue({
      agent_id: "agent-a",
      scopes: [publicScope, privateScope],
    });
    vi.mocked(workspaceApi.listMemoryFiles).mockResolvedValue([
      {
        filename: "2026-09-15/topic.md",
        path: "memory/2026-09-15/topic.md",
        size: 12,
        created_time: "2026-09-15T23:21:19Z",
        modified_time: "2026-09-15T23:21:19Z",
      },
    ]);
    vi.mocked(workspaceApi.loadMemoryFile).mockResolvedValue({
      content: "记忆正文",
    });
  });

  it("labels scope and memory type as two distinct filter groups", async () => {
    renderWithProviders(
      <MemoryPanel
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    expect(
      screen.getByText("files.fileCenter.memoryScopeLabel"),
    ).toBeVisible();
    expect(
      screen.getByText("files.fileCenter.memoryTypeLabel"),
    ).toBeVisible();
    expect(
      screen.getByRole("group", {
        name: "files.fileCenter.memoryScopeLabel",
      }),
    ).toContainElement(
      screen.getByRole("tablist", {
        name: "files.fileCenter.memoryScopeLabel",
      }),
    );
    expect(
      screen.getByRole("group", {
        name: "files.fileCenter.memoryTypeLabel",
      }),
    ).toContainElement(
      screen.getByRole("tablist", {
        name: "files.fileCenter.memoryTypeLabel",
      }),
    );
  });

  it("defaults to my private memory and lists nested daily notes despite index failure", async () => {
    renderWithProviders(
      <MemoryPanel
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    expect(await screen.findByRole("button", { name: "topic.md" })).toBeVisible();
    expect(workspaceApi.listMemoryFiles).toHaveBeenCalledWith(
      "daily",
      "private",
      { agentId: "agent-a" },
    );
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("opens a memory file with its complete relative path", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <MemoryPanel
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
        onOpen={onOpen}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "topic.md" }));
    await waitFor(() =>
      expect(onOpen).toHaveBeenCalledWith({
        category: "memory",
        agentId: "agent-a",
        relativePath: "2026-09-15/topic.md",
        memoryScope: "private",
        memorySection: "daily",
      }),
    );
    expect(await screen.findByText("记忆正文")).toBeVisible();
  });

  it("does not reload scopes or content when the parent stores the emitted locator", async () => {
    function ControlledMemoryPanel() {
      const [locator, setLocator] = useState<FileLocator>({
        category: "memory" as const,
        agentId: "agent-a",
        relativePath: "2026-09-15/topic.md",
        memoryScope: "private" as const,
        memorySection: "daily" as const,
      });
      return (
        <MemoryPanel
          agentId="agent-a"
          requestContext={{ agentId: "agent-a" }}
          initialLocator={locator}
          onOpen={setLocator}
        />
      );
    }

    renderWithProviders(<ControlledMemoryPanel />);

    expect(await screen.findByText("记忆正文")).toBeVisible();
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 80));
    });
    expect(agentApi.getMemoryScopes).toHaveBeenCalledTimes(1);
    expect(workspaceApi.listMemoryFiles).toHaveBeenCalledTimes(1);
    expect(workspaceApi.loadMemoryFile).toHaveBeenCalledTimes(1);
  });

  it("keeps the newest preview when an older request fails later", async () => {
    const user = userEvent.setup();
    let rejectOlder: ((reason?: unknown) => void) | undefined;
    vi.mocked(workspaceApi.listMemoryFiles).mockResolvedValue([
      {
        filename: "older.md",
        path: "memory/older.md",
        size: 12,
        created_time: "2026-09-15T23:21:19Z",
        modified_time: "2026-09-15T23:21:19Z",
      },
      {
        filename: "newer.md",
        path: "memory/newer.md",
        size: 12,
        created_time: "2026-09-16T23:21:19Z",
        modified_time: "2026-09-16T23:21:19Z",
      },
    ]);
    vi.mocked(workspaceApi.loadMemoryFile).mockImplementation((path) => {
      if (path === "older.md") {
        return new Promise((_, reject) => {
          rejectOlder = reject;
        });
      }
      return Promise.resolve({ content: "最新记忆正文" });
    });

    renderWithProviders(
      <MemoryPanel
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "older.md" }));
    await user.click(screen.getByRole("button", { name: "newer.md" }));
    expect(await screen.findByText("最新记忆正文")).toBeVisible();
    await act(async () => {
      rejectOlder?.(new Error("stale request"));
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    expect(screen.getByText("最新记忆正文")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a friendly index notice without exposing the internal state value", async () => {
    renderWithProviders(
      <MemoryPanel
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "files.fileCenter.memoryIndexNotice.reindex_failed",
    );
    expect(screen.queryByText(/needs_reindex/)).not.toBeInTheDocument();
  });

  it("previews both daily journals and long-term memories", async () => {
    const user = userEvent.setup();
    vi.mocked(workspaceApi.listMemoryFiles).mockImplementation((section) =>
      Promise.resolve([
        {
          filename: section === "daily" ? "2026-09-16.md" : "travel/topic.md",
          path:
            section === "daily"
              ? "memory/2026-09-16.md"
              : "digest/travel/topic.md",
          size: 12,
          created_time: "2026-09-16T23:21:19Z",
          modified_time: "2026-09-16T23:21:19Z",
        },
      ]),
    );
    vi.mocked(workspaceApi.loadMemoryFile).mockImplementation(
      (path, section) =>
        Promise.resolve({
          content:
            section === "daily" ? `日记：${path}` : `长期记忆：${path}`,
        }),
    );

    renderWithProviders(
      <MemoryPanel
        agentId="agent-a"
        requestContext={{ agentId: "agent-a" }}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: "2026-09-16.md" }),
    );
    expect(await screen.findByText("日记：2026-09-16.md")).toBeVisible();

    await user.click(
      screen.getByRole("tab", {
        name: "files.fileCenter.distilledMemory",
      }),
    );
    await user.click(await screen.findByRole("button", { name: "topic.md" }));
    expect(await screen.findByText("长期记忆：travel/topic.md")).toBeVisible();
    expect(workspaceApi.loadMemoryFile).toHaveBeenLastCalledWith(
      "travel/topic.md",
      "digest",
      "private",
      { agentId: "agent-a" },
    );
  });
});
