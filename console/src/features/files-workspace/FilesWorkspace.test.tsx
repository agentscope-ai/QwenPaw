import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesWorkspace from "./FilesWorkspace";
import { notifyProjectDirectoryChanged } from "../project-directory/projectDirectoryChangeEvent";
import type { EditorTab } from "../../stores/codingTabsStore";
import type { FileTarget } from "./types";
import { agentsApi } from "../../api/modules/agents";

const lifecycle = vi.hoisted(() => ({
  clearProjectTabs: vi.fn(),
  closeTab: vi.fn(),
  editorMounted: vi.fn(),
  editorUnmounted: vi.fn(),
  codingMode: false,
  navigatorMounted: vi.fn(),
  navigatorUnmounted: vi.fn(),
  navigatorProps: null as {
    memoryTagsActive?: boolean;
    memoryTagsPanel?: ReactNode;
    onSelect: (target: FileTarget) => void;
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
  } | null,
  memoryGraphProps: null as {
    onOpenFile: (section: "daily" | "digest", path: string) => void;
  } | null,
  getFileMetadata: vi.fn(),
  loadFileText: vi.fn(),
  loadFile: vi.fn(),
  saveFile: vi.fn(),
  loadMemoryFile: vi.fn(),
  loadDailyMemory: vi.fn(),
  saveDailyMemory: vi.fn(),
  openTab: vi.fn(),
  saveFileContent: vi.fn(),
  setTabContent: vi.fn(),
  setTabDirty: vi.fn(),
  setTabEtag: vi.fn(),
  setActiveTab: vi.fn(),
  tabs: [] as EditorTab[],
  activeTabPath: "",
  editorProps: null as {
    onMemoryTagClick?: (tag: string) => void;
    onCloseOtherTabs: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
    onTabClose: (path: string) => void;
    onTabSelect: (path: string) => void;
  } | null,
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: lifecycle.codingMode }),
}));

vi.mock("../../stores/codingTabsStore", () => {
  const useCodingTabsStore = Object.assign(
    () => ({
      clearProjectTabs: lifecycle.clearProjectTabs,
      closeTab: lifecycle.closeTab,
      openTab: lifecycle.openTab,
      setActiveTab: lifecycle.setActiveTab,
      setTabContent: lifecycle.setTabContent,
      setTabDirty: lifecycle.setTabDirty,
      setTabEtag: lifecycle.setTabEtag,
      refreshTab: (
        scopeKey: string,
        path: string,
        content: string,
        etag: string,
      ) => {
        const tab = lifecycle.tabs.find((item) => item.path === path);
        if (tab?.etag !== etag) lifecycle.setTabEtag(scopeKey, path, etag);
        if (tab?.content !== content)
          lifecycle.setTabContent(scopeKey, path, content);
      },
    }),
    {
      getState: () => ({
        diffsByAgent: {},
        tabsByAgent: {
          "agent:agent-a": lifecycle.tabs,
          "session:agent-a:session-a": lifecycle.tabs,
        },
      }),
    },
  );
  return {
    useTabsForScope: () => lifecycle.tabs,
    useActiveTabPathForScope: () => lifecycle.activeTabPath,
    useCodingTabsStore,
  };
});

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    getFileMetadata: lifecycle.getFileMetadata,
    loadFileText: lifecycle.loadFileText,
    loadFile: lifecycle.loadFile,
    saveFile: lifecycle.saveFile,
    loadMemoryFile: lifecycle.loadMemoryFile,
    loadDailyMemory: lifecycle.loadDailyMemory,
    saveDailyMemory: lifecycle.saveDailyMemory,
    saveFileContent: lifecycle.saveFileContent,
  },
}));

vi.mock("./FilesNavigator", () => ({
  default: function MockFilesNavigator(props: {
    memoryTagsActive?: boolean;
    memoryTagsPanel?: ReactNode;
    onSelect: (target: FileTarget) => void;
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
  }) {
    lifecycle.navigatorProps = props;
    useEffect(() => {
      lifecycle.navigatorMounted();
      return () => lifecycle.navigatorUnmounted();
    }, []);
    return (
      <div>navigator{props.memoryTagsActive && props.memoryTagsPanel}</div>
    );
  },
}));

vi.mock("./MemoryGraphView", () => ({
  default: (props: {
    agentId: string;
    root: string;
    onOpenFile: (section: "daily" | "digest", path: string) => void;
  }) => {
    lifecycle.memoryGraphProps = props;
    return (
      <div>
        memory-graph:{props.agentId}:{props.root}
      </div>
    );
  },
}));

vi.mock("../../pages/Coding/TabbedEditor", () => ({
  default: function MockTabbedEditor(props: {
    onMemoryTagClick?: (tag: string) => void;
    onCloseOtherTabs: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
    onTabClose: (path: string) => void;
    onTabSelect: (path: string) => void;
  }) {
    lifecycle.editorProps = props;
    useEffect(() => {
      lifecycle.editorMounted();
      return () => lifecycle.editorUnmounted();
    }, []);
    return <div>editor</div>;
  },
}));

vi.mock("../../pages/Coding/GitPanel", () => ({
  default: () => <div>git</div>,
}));

describe("FilesWorkspace directory changes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(agentsApi, "getAgent").mockResolvedValue({
      id: "agent-a",
      name: "Agent A",
      running: { memory_manager_backend: "remelight" },
    });
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1024,
    });
    lifecycle.codingMode = false;
    lifecycle.tabs = [];
    lifecycle.activeTabPath = "";
    lifecycle.editorProps = null;
    lifecycle.navigatorProps = null;
    lifecycle.memoryGraphProps = null;
    lifecycle.getFileMetadata.mockResolvedValue({
      path: "notes.md",
      size: 5,
      modified_at: "",
      preview_kind: "text",
      etag: "v1",
    });
    lifecycle.loadFileText.mockResolvedValue({ content: "", etag: "v1" });
    lifecycle.loadMemoryFile.mockResolvedValue({ content: "" });
    lifecycle.loadDailyMemory.mockResolvedValue({ content: "" });
  });

  it.each(["adbpg", "powercontext"])(
    "hides tag navigation and preview actions for %s",
    async (backend) => {
      vi.mocked(agentsApi.getAgent).mockResolvedValue({
        id: "agent-a",
        name: "Agent A",
        running: { memory_manager_backend: backend },
      });
      const tags = vi.spyOn(agentsApi, "getMemoryTags");
      const files = vi.spyOn(agentsApi, "getMemoryTagFiles");
      render(
        <FilesWorkspace
          initialMemoryTag="Orion"
          scope={{ kind: "agent", agentId: "agent-a" }}
        />,
      );
      await act(async () => {});
      expect(lifecycle.navigatorProps?.memoryTagsActive).toBe(false);
      expect(lifecycle.navigatorProps?.memoryTagsPanel).toBeUndefined();
      expect(lifecycle.editorProps?.onMemoryTagClick).toBeUndefined();
      expect(tags).not.toHaveBeenCalled();
      expect(files).not.toHaveBeenCalled();
    },
  );

  it.each(["daily", "digest", "memory"] as const)(
    "reuses a dirty %s buffer when opening its Workspace alias",
    async (source) => {
      const directory = source === "digest" ? "digest" : "memory";
      lifecycle.tabs = [
        {
          path: `${source}::note.md`,
          displayPath: "note.md",
          source,
          content: "Unsaved memory",
          dirty: true,
        },
      ];
      lifecycle.activeTabPath = lifecycle.tabs[0].path;
      render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
      act(
        () =>
          lifecycle.navigatorProps?.onSelect({
            source: "workspace",
            path: `${directory}/note.md`,
            root: "workspace",
          }),
      );
      await waitFor(() =>
        expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
          "agent:agent-a",
          `${source}::note.md`,
        ),
      );
      expect(lifecycle.openTab).not.toHaveBeenCalled();
      expect(lifecycle.loadFileText).not.toHaveBeenCalled();
      expect(lifecycle.setTabContent).not.toHaveBeenCalled();
    },
  );

  it("retries config after a failed open without creating a conflicting buffer", async () => {
    vi.mocked(agentsApi.getAgent).mockRejectedValue(new Error("offline"));
    lifecycle.tabs = [
      { path: "daily::note.md", content: "Unsaved", dirty: true },
    ];
    lifecycle.activeTabPath = "daily::note.md";
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await act(async () => {});
    const target: FileTarget = {
      source: "workspace",
      root: "workspace",
      path: "memory/note.md",
    };
    await act(async () => lifecycle.navigatorProps?.onSelect(target));
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    vi.mocked(agentsApi.getAgent).mockResolvedValue({
      id: "agent-a",
      name: "Agent A",
      running: { memory_manager_backend: "remelight" },
    });
    await act(async () => lifecycle.navigatorProps?.onSelect(target));
    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "daily::note.md",
    );
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it("reuses an exact dirty tab when configuration is unavailable", async () => {
    vi.mocked(agentsApi.getAgent).mockRejectedValue(new Error("offline"));
    lifecycle.tabs = [
      {
        path: "workspace-root::notes.md",
        displayPath: "notes.md",
        source: "workspace",
        workspaceRoot: "workspace",
        content: "Unsaved",
        dirty: true,
      },
    ];
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await act(async () => {});
    await act(
      async () =>
        lifecycle.navigatorProps?.onSelect({
          source: "workspace",
          root: "workspace",
          path: "notes.md",
        }),
    );
    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "workspace-root::notes.md",
    );
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it("opens an ordinary Workspace file on a repeated click after config recovers", async () => {
    vi.mocked(agentsApi.getAgent).mockRejectedValue(new Error("offline"));
    lifecycle.tabs = [
      {
        path: "workspace-root::first.md",
        content: "Unsaved first",
        dirty: true,
      },
    ];
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await act(async () => {});
    const target: FileTarget = {
      source: "workspace",
      root: "workspace",
      path: "second.md",
    };
    await act(async () => lifecycle.navigatorProps?.onSelect(target));
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    vi.mocked(agentsApi.getAgent).mockResolvedValue({
      id: "agent-a",
      name: "Agent A",
      running: { memory_manager_backend: "remelight" },
    });
    await act(async () => lifecycle.navigatorProps?.onSelect(target));
    expect(lifecycle.openTab).toHaveBeenCalledWith(
      "agent:agent-a",
      expect.objectContaining({ path: "workspace-root::second.md" }),
    );
    expect(agentsApi.getAgent).toHaveBeenCalledTimes(3);
    expect(lifecycle.tabs[0].content).toBe("Unsaved first");
  });

  it("opens a distinct Windows Daily file without reusing a dirty legacy digest buffer", async () => {
    vi.mocked(agentsApi.getAgent).mockResolvedValue({
      id: "agent-a",
      name: "Agent A",
      running: {
        memory_manager_backend: "remelight",
        reme_light_memory_config: {
          daily_dir: "notes\\daily",
          digest_dir: "notes\\knowledge",
        },
      },
    });
    lifecycle.tabs = [
      {
        path: "memory::knowledge/note.md",
        content: "Unsaved digest",
        dirty: true,
      },
    ];
    lifecycle.activeTabPath = lifecycle.tabs[0].path;
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await act(
      async () =>
        lifecycle.navigatorProps?.onSelect({
          source: "workspace",
          root: "workspace",
          path: "notes/daily/knowledge/note.md",
        }),
    );
    expect(lifecycle.openTab).toHaveBeenCalledWith(
      "agent:agent-a",
      expect.objectContaining({
        path: "workspace-root::notes/daily/knowledge/note.md",
        source: "workspace",
        workspaceRoot: "workspace",
      }),
    );
    expect(lifecycle.setActiveTab).not.toHaveBeenCalledWith(
      "agent:agent-a",
      "memory::knowledge/note.md",
    );
    expect(lifecycle.tabs[0].content).toBe("Unsaved digest");
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it.each([
    {
      daily_dir: "memory",
      digest_dir: "digest",
      legacyPath: "digest/note.md",
      workspacePath: "digest/note.md",
    },
    {
      daily_dir: "notes\\daily",
      digest_dir: "notes\\knowledge",
      legacyPath: "knowledge/note.md",
      workspacePath: "notes/knowledge/note.md",
    },
  ])(
    "saves a reused legacy digest buffer through its original memory route: %j",
    async (config) => {
      vi.mocked(agentsApi.getAgent).mockResolvedValue({
        id: "agent-a",
        name: "Agent A",
        running: {
          memory_manager_backend: "remelight",
          reme_light_memory_config: {
            daily_dir: config.daily_dir,
            digest_dir: config.digest_dir,
          },
        },
      });
      const tabPath = `memory::${config.legacyPath}`;
      lifecycle.tabs = [
        {
          path: tabPath,
          content: "Unsaved digest",
          dirty: true,
        },
      ];
      lifecycle.activeTabPath = lifecycle.tabs[0].path;
      render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
      await act(
        async () =>
          lifecycle.navigatorProps?.onSelect({
            source: "workspace",
            root: "workspace",
            path: config.workspacePath,
          }),
      );
      expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
        "agent:agent-a",
        tabPath,
      );
      await act(
        async () =>
          lifecycle.editorProps?.onSaveFile(tabPath, "Updated digest"),
      );
      expect(lifecycle.saveDailyMemory).toHaveBeenCalledWith(
        config.legacyPath,
        "Updated digest",
      );
      expect(lifecycle.saveFileContent).not.toHaveBeenCalled();
      expect(lifecycle.openTab).not.toHaveBeenCalled();
    },
  );

  it("recognizes persisted memory tab identities without optional metadata", async () => {
    lifecycle.tabs = [
      { path: "memory::note.md", content: "Unsaved memory", dirty: true },
    ];
    lifecycle.activeTabPath = "memory::note.md";
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(
      () =>
        lifecycle.navigatorProps?.onSelect({
          source: "workspace",
          root: "workspace",
          path: "memory/note.md",
        }),
    );
    await waitFor(() =>
      expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
        "agent:agent-a",
        "memory::note.md",
      ),
    );
    expect(lifecycle.openTab).not.toHaveBeenCalled();
  });

  it("waits for memory directories before resolving an initial Workspace alias", async () => {
    let finish!: (
      value: Awaited<ReturnType<typeof agentsApi.getAgent>>,
    ) => void;
    vi.mocked(agentsApi.getAgent).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    lifecycle.tabs = [
      {
        path: "digest::note.md",
        displayPath: "note.md",
        source: "digest",
        content: "Unsaved memory",
        dirty: true,
      },
    ];
    lifecycle.activeTabPath = lifecycle.tabs[0].path;
    render(
      <FilesWorkspace
        initialTarget={{
          source: "workspace",
          root: "workspace",
          path: "custom/digest/note.md",
        }}
        scope={{ kind: "agent", agentId: "agent-a" }}
      />,
    );
    await act(async () => {});
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    await act(async () =>
      finish({
        id: "agent-a",
        name: "Agent A",
        running: {
          memory_manager_backend: "remelight",
          reme_light_memory_config: { digest_dir: "custom/digest" },
        },
      }),
    );
    await waitFor(() =>
      expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
        "agent:agent-a",
        "digest::note.md",
      ),
    );
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    expect(agentsApi.getAgent).toHaveBeenCalledTimes(1);
  });

  it("prefers a dirty memory alias over an existing clean Workspace buffer", async () => {
    lifecycle.tabs = [
      {
        path: "workspace-root::memory/note.md",
        displayPath: "memory/note.md",
        source: "workspace",
        workspaceRoot: "workspace",
        content: "Saved memory",
        dirty: false,
      },
      {
        path: "daily::note.md",
        displayPath: "note.md",
        source: "daily",
        content: "Unsaved memory",
        dirty: true,
      },
    ];
    lifecycle.activeTabPath = "daily::note.md";
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(
      () =>
        lifecycle.navigatorProps?.onSelect({
          source: "workspace",
          path: "memory/note.md",
          root: "workspace",
        }),
    );
    await waitFor(() =>
      expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
        "agent:agent-a",
        "daily::note.md",
      ),
    );
    expect(lifecycle.openTab).not.toHaveBeenCalled();
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it("keeps a dirty document mounted while browsing a tag and opening a result", async () => {
    lifecycle.tabs = [
      {
        path: "daily::note.md",
        displayPath: "note.md",
        source: "daily",
        content: "Unsaved memory",
        dirty: true,
      },
    ];
    lifecycle.activeTabPath = "daily::note.md";
    vi.spyOn(agentsApi, "getMemoryTagFiles").mockResolvedValue({
      tag: "赵六",
      total_files: 1,
      page: 1,
      page_size: 50,
      items: [
        {
          path: "resources/orion.md",
          source: "workspace",
          relative_path: "resources/orion.md",
          name: "Orion owner",
          description: "",
          modified_at: 1700000000,
          memory_tags: ["赵六"],
        },
      ],
    });
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await waitFor(() =>
      expect(lifecycle.editorProps?.onMemoryTagClick).toBeDefined(),
    );
    act(() => lifecycle.editorProps?.onMemoryTagClick?.("赵六"));
    const result = await screen.findByRole("button", { name: /Orion owner/ });
    expect(lifecycle.editorUnmounted).not.toHaveBeenCalled();
    expect(lifecycle.closeTab).not.toHaveBeenCalled();
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
    expect(lifecycle.tabs[0].content).toBe("Unsaved memory");
    fireEvent.click(result);
    await waitFor(() =>
      expect(lifecycle.openTab).toHaveBeenCalledWith(
        "agent:agent-a",
        expect.objectContaining({
          path: "workspace-root::resources/orion.md",
          source: "workspace",
          workspaceRoot: "workspace",
        }),
      ),
    );
    expect(
      screen.getByRole("button", { name: /Orion owner/ }),
    ).toBeInTheDocument();
  });

  it.each([
    { source: "daily", hasCleanAlias: false },
    { source: "digest", hasCleanAlias: false },
    { source: "daily", hasCleanAlias: true },
  ] as const)(
    "reuses a dirty workspace tab when opening a tag result: %j",
    async ({ source, hasCleanAlias }) => {
      vi.mocked(agentsApi.getAgent).mockResolvedValue({
        id: "agent-a",
        name: "Agent A",
        running: {
          memory_manager_backend: "remelight",
          reme_light_memory_config: {
            daily_dir: "custom-daily",
            digest_dir: "custom-digest",
          },
        },
      });
      const path = `custom-${source}/note.md`;
      const existing: EditorTab = {
        path: `workspace-root::${path}`,
        displayPath: path,
        source: "workspace",
        workspaceRoot: "workspace",
        content: "Unsaved memory",
        dirty: true,
      };
      const tabs: EditorTab[] = hasCleanAlias
        ? [
            {
              path: `${source}::note.md`,
              displayPath: "note.md",
              source,
              content: "Saved memory",
              dirty: false,
            },
            existing,
          ]
        : [existing];
      lifecycle.tabs = tabs;
      lifecycle.activeTabPath = existing.path;
      vi.spyOn(agentsApi, "getMemoryTagFiles").mockResolvedValue({
        tag: "赵六",
        total_files: 1,
        page: 1,
        page_size: 50,
        items: [
          {
            path,
            source,
            relative_path: "note.md",
            name: "Tagged memory",
            description: "",
            modified_at: 1700000000,
            memory_tags: ["赵六"],
          },
        ],
      });
      render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
      await waitFor(() =>
        expect(lifecycle.editorProps?.onMemoryTagClick).toBeDefined(),
      );
      act(() => lifecycle.editorProps?.onMemoryTagClick?.("赵六"));
      const result = await screen.findByRole("button", {
        name: /Tagged memory/,
      });
      fireEvent.click(result);
      await waitFor(() =>
        expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
          "agent:agent-a",
          existing.path,
        ),
      );
      expect(lifecycle.openTab).not.toHaveBeenCalled();
      expect(lifecycle.loadMemoryFile).not.toHaveBeenCalled();
      expect(lifecycle.setTabContent).not.toHaveBeenCalled();
      expect(lifecycle.tabs).toEqual(tabs);
      expect(result).toHaveAttribute("aria-current", "true");
    },
  );

  it.each([undefined, "project", "project:/other"] as const)(
    "does not reuse or highlight an unrelated project file, root: %s",
    async (workspaceRoot) => {
      const existing: EditorTab = {
        path: workspaceRoot?.startsWith("project:")
          ? `${workspaceRoot}::resources/orion.md`
          : "resources/orion.md",
        displayPath: "resources/orion.md",
        source: "workspace",
        workspaceRoot,
        content: "Unsaved project file",
        dirty: true,
      };
      lifecycle.tabs = [existing];
      lifecycle.activeTabPath = existing.path;
      vi.spyOn(agentsApi, "getMemoryTagFiles").mockResolvedValue({
        tag: "赵六",
        total_files: 1,
        page: 1,
        page_size: 50,
        items: [
          {
            path: "resources/orion.md",
            source: "workspace",
            relative_path: "resources/orion.md",
            name: "Tagged memory",
            description: "",
            modified_at: 1700000000,
            memory_tags: ["赵六"],
          },
        ],
      });
      render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
      await waitFor(() =>
        expect(lifecycle.editorProps?.onMemoryTagClick).toBeDefined(),
      );
      act(() => lifecycle.editorProps?.onMemoryTagClick?.("赵六"));
      const result = await screen.findByRole("button", {
        name: /Tagged memory/,
      });
      expect(result).not.toHaveAttribute("aria-current");
      fireEvent.click(result);
      await waitFor(() =>
        expect(lifecycle.openTab).toHaveBeenCalledWith(
          "agent:agent-a",
          expect.objectContaining({
            path: "workspace-root::resources/orion.md",
            workspaceRoot: "workspace",
          }),
        ),
      );
      expect(lifecycle.tabs).toEqual([existing]);
    },
  );

  it("loads and saves profile files using the workspace agent", async () => {
    lifecycle.tabs = [
      {
        path: "profile::HEARTBEAT.md",
        displayPath: "HEARTBEAT.md",
        content: "before",
        dirty: false,
        source: "profile",
      },
    ];
    lifecycle.activeTabPath = "profile::HEARTBEAT.md";
    lifecycle.loadFile.mockResolvedValue({ content: "before" });
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await waitFor(() =>
      expect(lifecycle.loadFile).toHaveBeenCalledWith(
        "HEARTBEAT.md",
        "agent-a",
      ),
    );
    await act(async () => {
      await lifecycle.editorProps?.onSaveFile("profile::HEARTBEAT.md", "after");
    });
    expect(lifecycle.saveFile).toHaveBeenCalledWith(
      "HEARTBEAT.md",
      "after",
      "agent-a",
    );
  });

  it("rebuilds the Session navigator and editor watch host", () => {
    const scope = {
      kind: "session" as const,
      agentId: "agent-a",
      sessionId: "session-a",
      chatId: "chat-a",
    };
    render(<FilesWorkspace scope={scope} />);

    expect(lifecycle.navigatorMounted).toHaveBeenCalledTimes(1);
    expect(lifecycle.editorMounted).toHaveBeenCalledTimes(1);

    act(() => notifyProjectDirectoryChanged(scope));

    expect(lifecycle.clearProjectTabs).toHaveBeenCalledWith(
      "session:agent-a:session-a",
    );
    expect(lifecycle.navigatorUnmounted).toHaveBeenCalledTimes(1);
    expect(lifecycle.navigatorMounted).toHaveBeenCalledTimes(2);
    expect(lifecycle.editorUnmounted).toHaveBeenCalledTimes(1);
    expect(lifecycle.editorMounted).toHaveBeenCalledTimes(2);
  });

  it("saves with the loaded ETag and stores the returned version", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "before",
        dirty: true,
        source: "workspace",
        etag: "v1",
      },
    ];
    lifecycle.activeTabPath = "notes.md";
    lifecycle.saveFileContent.mockResolvedValue({
      path: "notes.md",
      size: 5,
      etag: "v2",
    });

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await act(async () => {
      await lifecycle.editorProps?.onSaveFile("notes.md", "after");
    });

    expect(lifecycle.saveFileContent).toHaveBeenCalledWith(
      "notes.md",
      "after",
      "v1",
      undefined,
      undefined,
      undefined,
    );
    expect(lifecycle.setTabEtag).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
      "v2",
    );
  });

  it("revalidates the restored active text tab", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "before",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.activeTabPath = "notes.md";
    lifecycle.loadFileText.mockResolvedValue({
      content: "after",
      etag: "v2",
    });

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);

    await waitFor(() =>
      expect(lifecycle.setTabContent).toHaveBeenCalledWith(
        "agent:agent-a",
        "notes.md",
        "after",
      ),
    );
  });

  it("revalidates a clean text tab when it is selected", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "before",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockResolvedValue({
      content: "after",
      etag: "v2",
    });

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => lifecycle.editorProps?.onTabSelect("notes.md"));

    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
    );
    await waitFor(() =>
      expect(lifecycle.setTabContent).toHaveBeenCalledWith(
        "agent:agent-a",
        "notes.md",
        "after",
      ),
    );
  });

  it("revalidates an existing tab selected from the navigator", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "before",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockResolvedValue({
      content: "after",
      etag: "v2",
    });

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => {
      lifecycle.navigatorProps?.onSelect({
        source: "workspace",
        path: "notes.md",
      });
    });

    await waitFor(() =>
      expect(lifecycle.setTabContent).toHaveBeenCalledWith(
        "agent:agent-a",
        "notes.md",
        "after",
      ),
    );
  });

  it("does not overwrite a tab that becomes dirty during revalidation", async () => {
    let finishLoad:
      | ((value: { content: string; etag: string }) => void)
      | null = null;
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "before",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockReturnValue(
      new Promise((resolve) => {
        finishLoad = resolve;
      }),
    );

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => lifecycle.editorProps?.onTabSelect("notes.md"));
    lifecycle.tabs[0].dirty = true;
    lifecycle.tabs[0].content = "local edit";
    await act(async () => {
      finishLoad?.({ content: "agent edit", etag: "v2" });
    });

    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
    expect(lifecycle.setTabEtag).not.toHaveBeenCalled();
  });

  it("ignores an older revalidation that finishes last", async () => {
    const finishLoads: Array<
      (value: { content: string; etag: string }) => void
    > = [];
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "before",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishLoads.push(resolve);
        }),
    );

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => lifecycle.editorProps?.onTabSelect("notes.md"));
    act(() => lifecycle.editorProps?.onTabSelect("notes.md"));
    await waitFor(() => expect(finishLoads).toHaveLength(2));

    await act(async () => {
      finishLoads[1]({ content: "newest", etag: "v3" });
    });
    await act(async () => {
      finishLoads[0]({ content: "older", etag: "v2" });
    });

    expect(lifecycle.setTabContent).toHaveBeenCalledOnce();
    expect(lifecycle.setTabContent).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
      "newest",
    );
    expect(lifecycle.setTabEtag).toHaveBeenCalledOnce();
    expect(lifecycle.setTabEtag).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
      "v3",
    );
  });

  it("preserves state for identical content and non-text tabs", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "unchanged",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
      {
        path: "image.png",
        content: "",
        dirty: false,
        source: "workspace",
        previewKind: "image",
      },
    ];
    lifecycle.loadFileText.mockResolvedValue({
      content: "unchanged",
      etag: "v2",
    });
    lifecycle.getFileMetadata.mockImplementation(async (path: string) => ({
      path,
      size: 5,
      modified_at: "",
      preview_kind: path === "image.png" ? "image" : "text",
      etag: "v2",
    }));

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => lifecycle.editorProps?.onTabSelect("notes.md"));
    await waitFor(() => expect(lifecycle.loadFileText).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(lifecycle.getFileMetadata).toHaveBeenCalledTimes(2),
    );
    await waitFor(() =>
      expect(lifecycle.setTabEtag).toHaveBeenCalledWith(
        "agent:agent-a",
        "image.png",
        "v2",
      ),
    );
    lifecycle.setTabContent.mockClear();
    act(() => lifecycle.editorProps?.onTabSelect("image.png"));

    expect(lifecycle.getFileMetadata).toHaveBeenCalledTimes(2);
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it("closes every other tab and activates the tab used for the action", () => {
    lifecycle.tabs = [
      { path: "one.md", content: "", dirty: false },
      { path: "two.md", content: "", dirty: false },
      { path: "three.md", content: "", dirty: false },
    ];
    lifecycle.activeTabPath = "one.md";

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => lifecycle.editorProps?.onCloseOtherTabs("two.md"));

    expect(lifecycle.closeTab.mock.calls).toEqual([
      ["agent:agent-a", "one.md"],
      ["agent:agent-a", "three.md"],
    ]);
    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "two.md",
    );
  });

  it("switches between the editor and the memory graph", () => {
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);

    act(() => lifecycle.navigatorProps?.onShowMemoryGraph("wiki"));
    expect(screen.getByText("memory-graph:agent-a:wiki")).toBeInTheDocument();
    expect(screen.queryByText("editor")).not.toBeInTheDocument();

    act(() => lifecycle.navigatorProps?.onShowFiles());
    expect(screen.getByText("editor")).toBeInTheDocument();
  });

  it("switches mobile panes without closing or changing a dirty tab", () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "local edit",
        dirty: true,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.activeTabPath = "notes.md";

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    const workspace = screen
      .getByText("navigator")
      .closest("[data-mobile-pane]");

    expect(workspace).toHaveAttribute("data-mobile-pane", "document");
    fireEvent.click(screen.getByLabelText("files.navigator"));
    expect(workspace).toHaveAttribute("data-mobile-pane", "navigator");
    expect(screen.getByText("editor")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("files.openFilesLabel"));
    expect(workspace).toHaveAttribute("data-mobile-pane", "document");
    expect(lifecycle.closeTab).not.toHaveBeenCalled();
    expect(lifecycle.setTabDirty).not.toHaveBeenCalled();
    expect(lifecycle.editorUnmounted).not.toHaveBeenCalled();
    expect(lifecycle.tabs[0]).toMatchObject({
      content: "local edit",
      dirty: true,
    });
  });

  it("keeps Coding Mode source control mutually exclusive at 390px", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 390,
    });
    lifecycle.codingMode = true;
    lifecycle.tabs = [
      {
        path: "notes.md",
        displayPath: "notes.md",
        content: "local edit",
        dirty: true,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.activeTabPath = "notes.md";

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    const workspace = screen.getByText("editor").closest("[data-mobile-pane]");

    expect(workspace).toHaveAttribute("data-mobile-pane", "document");
    fireEvent.click(
      within(
        screen.getByRole("navigation", { name: "files.workspace" }),
      ).getByLabelText("files.sourceControl"),
    );
    expect(workspace).toHaveAttribute("data-mobile-pane", "source");
    expect(screen.getByText("git")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("files.openFilesLabel"));
    expect(workspace).toHaveAttribute("data-mobile-pane", "document");
    expect(screen.getByText("editor")).toBeInTheDocument();
    expect(lifecycle.closeTab).not.toHaveBeenCalled();
    expect(lifecycle.setTabDirty).not.toHaveBeenCalled();
    expect(lifecycle.editorUnmounted).not.toHaveBeenCalled();
    expect(lifecycle.tabs[0]).toMatchObject({
      content: "local edit",
      dirty: true,
    });

    fireEvent.click(
      within(
        screen.getByRole("navigation", { name: "files.workspace" }),
      ).getByLabelText("files.sourceControl"),
    );
    fireEvent.click(screen.getByLabelText("files.navigator"));
    expect(workspace).toHaveAttribute("data-mobile-pane", "navigator");
    expect(screen.getByText("navigator")).toBeInTheDocument();
  });

  it("returns to the document pane when an existing file is selected", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "before",
        dirty: true,
        source: "workspace",
        previewKind: "text",
      },
    ];

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    const workspace = screen
      .getByText("navigator")
      .closest("[data-mobile-pane]");
    fireEvent.click(screen.getByLabelText("files.navigator"));
    await act(async () => {
      lifecycle.navigatorProps?.onSelect({
        source: "workspace",
        path: "notes.md",
      });
    });

    expect(workspace).toHaveAttribute("data-mobile-pane", "document");
    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
    );
  });

  it("opens a new navigator selection in the document pane", async () => {
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    const workspace = screen
      .getByText("navigator")
      .closest("[data-mobile-pane]");

    expect(workspace).toHaveAttribute("data-mobile-pane", "navigator");
    await act(async () => {
      lifecycle.navigatorProps?.onSelect({
        source: "workspace",
        path: "notes.md",
      });
    });

    expect(workspace).toHaveAttribute("data-mobile-pane", "document");
    expect(lifecycle.openTab).toHaveBeenCalledWith(
      "agent:agent-a",
      expect.objectContaining({
        path: "notes.md",
        previewKind: "text",
      }),
    );
  });

  it("returns to the navigator after the final tab closes", () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "before",
        dirty: false,
        source: "workspace",
      },
    ];
    lifecycle.activeTabPath = "notes.md";

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    const workspace = screen
      .getByText("navigator")
      .closest("[data-mobile-pane]");
    act(() => lifecycle.editorProps?.onTabClose("notes.md"));

    expect(workspace).toHaveAttribute("data-mobile-pane", "navigator");
    expect(lifecycle.closeTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
    );
  });

  it("opens the section-relative path supplied by the memory graph", async () => {
    lifecycle.tabs = [{ path: "daily::a.md", content: "", dirty: false }];
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);

    act(() => lifecycle.navigatorProps?.onShowMemoryGraph("wiki"));
    await act(async () => {
      lifecycle.memoryGraphProps?.onOpenFile("daily", "a.md");
    });

    expect(screen.getByText("editor")).toBeInTheDocument();
    await waitFor(() =>
      expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
        "agent:agent-a",
        "daily::a.md",
      ),
    );
  });
});
