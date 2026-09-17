import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesNavigator from "./FilesNavigator";
import i18n from "../../i18n";

const mocks = vi.hoisted(() => ({
  listDirectory: vi.fn(),
  listFiles: vi.fn(),
  getSystemPromptFiles: vi.fn(),
  listMemoryFiles: vi.fn(),
  projectDirectoryGet: vi.fn(),
}));

vi.mock("../../api/modules/workspace", async () => {
  const actual = await vi.importActual<
    typeof import("../../api/modules/workspace")
  >("../../api/modules/workspace");
  return {
    ...actual,
    workspaceApi: {
      ...actual.workspaceApi,
      listDirectory: mocks.listDirectory,
      listFiles: mocks.listFiles,
      getSystemPromptFiles: mocks.getSystemPromptFiles,
      listMemoryFiles: mocks.listMemoryFiles,
    },
  };
});

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: { get: mocks.projectDirectoryGet },
}));

describe("FilesNavigator memory creation", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
    vi.clearAllMocks();
    mocks.listDirectory.mockResolvedValue({
      directory: "",
      entries: [],
      next_cursor: null,
      has_more: false,
    });
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.listMemoryFiles.mockResolvedValue([]);
    mocks.projectDirectoryGet.mockResolvedValue({
      path: "E:/workspace/default",
      workspace_dir: "E:/workspace/default",
    });
  });

  it("lists only the requested logical directory", async () => {
    mocks.projectDirectoryGet.mockResolvedValue({
      path: "E:/working/user_workspaces/user-a/agent-a",
      project_kind: "user_runtime",
      workspace_dir: "E:/working/workspaces/agent-a",
      workspace_kind: "published",
      workspace_read_only: true,
    });

    render(
      <FilesNavigator
        rootDirectory="产物"
        scope={{ kind: "agent", agentId: "agent-a" }}
        selectedPath=""
        onSelect={vi.fn()}
        activeMemoryGraphRoot={null}
        onShowMemoryGraph={vi.fn()}
        onShowFiles={vi.fn()}
        memoryScope="public"
        memoryScopes={[]}
        onMemoryScopeChange={vi.fn()}
        onRebuildMemoryIndex={vi.fn()}
        requestContext={{ agentId: "agent-a" }}
        canEditProjectFiles
        canEditAgentFiles
      />,
    );

    await act(async () => undefined);

    expect(mocks.listDirectory).toHaveBeenCalledWith(
      "产物",
      undefined,
      200,
      undefined,
      "project",
      undefined,
      { agentId: "agent-a" },
    );
    expect(screen.queryByRole("tab", { name: "档案" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "日记" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "知识库" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "切换目录来源" }),
    ).not.toBeInTheDocument();
  });

  it("shows the Agent profile files without requiring a physical profile directory", async () => {
    mocks.listFiles.mockResolvedValue([
      {
        filename: "AGENTS.md",
        size: 128,
        modified_time: "2026-09-03T10:00:00Z",
      },
      {
        filename: "MEMORY.md",
        size: 256,
        modified_time: "2026-09-03T10:01:00Z",
      },
      {
        filename: "爱护环境.md",
        size: 512,
        modified_time: "2026-09-03T10:02:00Z",
      },
    ]);
    mocks.getSystemPromptFiles.mockResolvedValue(["AGENTS.md", "MEMORY.md"]);

    render(
      <FilesNavigator
        profileOnly
        scope={{ kind: "agent", agentId: "agent-a" }}
        selectedPath=""
        onSelect={vi.fn()}
        activeMemoryGraphRoot={null}
        onShowMemoryGraph={vi.fn()}
        onShowFiles={vi.fn()}
        memoryScope="public"
        memoryScopes={[]}
        onMemoryScopeChange={vi.fn()}
        onRebuildMemoryIndex={vi.fn()}
        requestContext={{ agentId: "agent-a" }}
        canEditProjectFiles
        canEditAgentFiles
      />,
    );

    expect(await screen.findByText("AGENTS.md")).toBeVisible();
    expect(screen.getByText("MEMORY.md")).toBeVisible();
    expect(screen.queryByText("爱护环境.md")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "工作区" }),
    ).not.toBeInTheDocument();
  });

  it.each(["日记", "知识库"])(
    "shows an explicit new-memory action in editable private %s",
    async (sourceLabel) => {
      render(
        <FilesNavigator
          scope={{ kind: "agent", agentId: "public-agent" }}
          selectedPath=""
          onSelect={vi.fn()}
          activeMemoryGraphRoot={null}
          onShowMemoryGraph={vi.fn()}
          onShowFiles={vi.fn()}
          memoryScope="private"
          memoryScopes={[
            {
              scope: "public",
              can_read: true,
              can_edit: false,
              status: "active",
              index_state: "ready",
              index_version: 0,
            },
            {
              scope: "private",
              can_read: true,
              can_edit: true,
              status: "active",
              index_state: "needs_reindex",
              index_version: 0,
            },
          ]}
          onMemoryScopeChange={vi.fn()}
          onRebuildMemoryIndex={vi.fn()}
          requestContext={{ agentId: "public-agent" }}
          canEditProjectFiles
          canEditAgentFiles={false}
        />,
      );

      await act(async () =>
        screen.getByRole("tab", { name: sourceLabel }).click(),
      );

      expect(
        await screen.findByRole("button", { name: /新建记忆文件/ }),
      ).toBeVisible();
    },
  );

  it("shows the registered legacy workspace resolution kind", async () => {
    mocks.projectDirectoryGet.mockResolvedValue({
      path: "E:/project/default",
      workspace_dir: "E:/legacy/default",
      workspace_kind: "legacy",
      workspace_key: "E:/legacy/default",
      workspace_read_only: false,
    });

    render(
      <FilesNavigator
        scope={{ kind: "agent", agentId: "default" }}
        selectedPath=""
        onSelect={vi.fn()}
        activeMemoryGraphRoot={null}
        onShowMemoryGraph={vi.fn()}
        onShowFiles={vi.fn()}
        memoryScope="public"
        memoryScopes={[]}
        onMemoryScopeChange={vi.fn()}
        onRebuildMemoryIndex={vi.fn()}
        requestContext={{ agentId: "default" }}
        canEditProjectFiles
        canEditAgentFiles
      />,
    );

    await act(async () =>
      screen.getByRole("button", { name: "切换目录来源" }).click(),
    );
    expect(await screen.findByText("已登记旧目录")).toBeVisible();
  });

  it("shows the personal runtime kind for a use-only project root", async () => {
    mocks.projectDirectoryGet.mockResolvedValue({
      path: "E:/working/user_workspaces/user-a/public-agent",
      project_kind: "user_runtime",
      project_read_only: false,
      workspace_dir: "E:/working/workspaces/public-agent",
      workspace_kind: "draft",
      workspace_read_only: true,
    });

    render(
      <FilesNavigator
        scope={{ kind: "agent", agentId: "public-agent" }}
        selectedPath=""
        onSelect={vi.fn()}
        activeMemoryGraphRoot={null}
        onShowMemoryGraph={vi.fn()}
        onShowFiles={vi.fn()}
        memoryScope="private"
        memoryScopes={[]}
        onMemoryScopeChange={vi.fn()}
        onRebuildMemoryIndex={vi.fn()}
        requestContext={{ agentId: "public-agent" }}
        canEditProjectFiles
        canEditAgentFiles={false}
      />,
    );

    expect(await screen.findByText("个人运行空间")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Agent 项目目录" }),
    ).not.toBeInTheDocument();
  });
});
