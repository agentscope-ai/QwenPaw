import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesWorkspace from "./FilesWorkspace";
import { notifyProjectDirectoryChanged } from "../project-directory/projectDirectoryChangeEvent";

const lifecycle = vi.hoisted(() => ({
  clearProjectTabs: vi.fn(),
  closeTab: vi.fn(),
  editorMounted: vi.fn(),
  editorUnmounted: vi.fn(),
  navigatorMounted: vi.fn(),
  navigatorUnmounted: vi.fn(),
  navigatorProps: null as {
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
    memoryScope: "public" | "private";
    memoryScopes: Array<{
      scope: "public" | "private";
      can_edit: boolean;
      index_state: string;
    }>;
    onMemoryScopeChange: (scope: "public" | "private") => void;
    onRebuildMemoryIndex: () => Promise<void>;
    canEditProjectFiles: boolean;
    canEditAgentFiles: boolean;
  } | null,
  memoryGraphProps: null as {
    onOpenFile: (section: "daily" | "digest", path: string) => void;
  } | null,
  saveFileContent: vi.fn(),
  saveMemoryFile: vi.fn(),
  tabsByScope: null as Record<string, Array<{
    path: string; content: string; dirty: boolean; source: "daily";
  }>> | null,
  setTabEtag: vi.fn(),
  setActiveTab: vi.fn(),
  observedScopeKeys: [] as string[],
  getMemoryScopes: vi.fn(),
  rebuildMemoryIndex: vi.fn(),
  getAgentRunningConfigAccess: vi.fn(),
  tabs: [] as Array<{
    path: string;
    displayPath?: string;
    content: string;
    dirty: boolean;
    source?: "workspace";
    etag?: string;
    readOnly?: boolean;
  }>,
  activeTabPath: "",
  editorProps: null as {
    onCloseOtherTabs: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
  } | null,
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("../../stores/codingTabsStore", () => ({
  useTabsForScope: (scopeKey: string) => {
    lifecycle.observedScopeKeys.push(scopeKey);
    return lifecycle.tabsByScope?.[scopeKey] ?? lifecycle.tabs;
  },
  useActiveTabPathForScope: (scopeKey: string) => {
    lifecycle.observedScopeKeys.push(scopeKey);
    return lifecycle.activeTabPath;
  },
  useCodingTabsStore: () => ({
    clearProjectTabs: lifecycle.clearProjectTabs,
    closeTab: lifecycle.closeTab,
    openTab: vi.fn(),
    setActiveTab: lifecycle.setActiveTab,
    setTabContent: vi.fn(),
    setTabDirty: vi.fn(),
    setTabEtag: lifecycle.setTabEtag,
  }),
}));

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    saveFileContent: lifecycle.saveFileContent,
    saveMemoryFile: lifecycle.saveMemoryFile,
  },
}));

vi.mock("../../api/modules/agent", () => ({
  agentApi: {
    getMemoryScopes: lifecycle.getMemoryScopes,
    rebuildMemoryIndex: lifecycle.rebuildMemoryIndex,
    getAgentRunningConfigAccess: lifecycle.getAgentRunningConfigAccess,
  },
}));

vi.mock("./FilesNavigator", () => ({
  default: function MockFilesNavigator(props: {
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
    memoryScope: "public" | "private";
    memoryScopes: Array<{
      scope: "public" | "private";
      can_edit: boolean;
      index_state: string;
    }>;
    onMemoryScopeChange: (scope: "public" | "private") => void;
    onRebuildMemoryIndex: () => Promise<void>;
    canEditProjectFiles: boolean;
    canEditAgentFiles: boolean;
  }) {
    lifecycle.navigatorProps = props;
    useEffect(() => {
      lifecycle.navigatorMounted();
      return () => lifecycle.navigatorUnmounted();
    }, []);
    const selected = props.memoryScopes.find(
      (item) => item.scope === props.memoryScope,
    );
    return (
      <div>
        <button onClick={() => props.onMemoryScopeChange("public")}>
          公共记忆
        </button>
        {props.memoryScopes.some((item) => item.scope === "private") && (
          <button onClick={() => props.onMemoryScopeChange("private")}>
            我的记忆
          </button>
        )}
        <span>{selected?.index_state}</span>
        {selected?.can_edit && (
          <button onClick={() => void props.onRebuildMemoryIndex()}>
            重建索引
          </button>
        )}
      </div>
    );
  },
}));

vi.mock("./MemoryGraphView", () => ({
  default: (props: {
    agentId: string;
    memoryScope: "public" | "private";
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
    tabs: Array<{ content: string }>;
    onCloseOtherTabs: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
  }) {
    lifecycle.editorProps = props;
    useEffect(() => {
      lifecycle.editorMounted();
      return () => lifecycle.editorUnmounted();
    }, []);
    return <div>editor{props.tabs?.map((tab) => tab.content).join("|")}</div>;
  },
}));

vi.mock("../../pages/Coding/GitPanel", () => ({
  default: () => <div>git</div>,
}));

describe("FilesWorkspace directory changes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lifecycle.tabs = [];
    lifecycle.tabsByScope = null;
    lifecycle.activeTabPath = "";
    lifecycle.editorProps = null;
    lifecycle.navigatorProps = null;
    lifecycle.memoryGraphProps = null;
    lifecycle.observedScopeKeys = [];
    lifecycle.getMemoryScopes.mockResolvedValue({
      agent_id: "agent-a",
      scopes: [
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
      ],
    });
    lifecycle.rebuildMemoryIndex.mockResolvedValue({ status: "completed" });
    lifecycle.getAgentRunningConfigAccess.mockResolvedValue({
      agent_id: "agent-a",
      access_role: "user",
      can_view: true,
      can_edit: false,
      can_edit_project_files: true,
      can_edit_workspace_files: false,
      is_governance: false,
      visibility: "public",
      owner_user_id: "owner-a",
    });
  });

  it("isolates editor state between Agent documents and outputs", () => {
    render(
      <FilesWorkspace
        scope={{ kind: "agent", agentId: "agent-a" }}
        rootDirectory="产物"
      />,
    );

    expect(lifecycle.observedScopeKeys).toContain("agent:agent-a:产物:memory:public");
  });

  it("uses separate workbench state for public and private memory", async () => {
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await waitFor(() => expect(lifecycle.navigatorProps?.memoryScopes).toHaveLength(2));
    const publicKey = lifecycle.observedScopeKeys[lifecycle.observedScopeKeys.length - 1];
    act(() => lifecycle.navigatorProps?.onMemoryScopeChange("private"));
    const privateKey = lifecycle.observedScopeKeys[lifecycle.observedScopeKeys.length - 1];
    expect(privateKey).not.toBe(publicKey);
    act(() => lifecycle.navigatorProps?.onMemoryScopeChange("public"));
    expect(lifecycle.observedScopeKeys[lifecycle.observedScopeKeys.length - 1]).toBe(publicKey);
  });

  it("restores the matching memory content before saving after a scope switch", async () => {
    lifecycle.tabsByScope = {
      "agent:agent-a:memory:public": [{
        path: "daily::same.md", content: "public content", dirty: false, source: "daily",
      }],
      "agent:agent-a:memory:private": [{
        path: "daily::same.md", content: "private content", dirty: true, source: "daily",
      }],
    };
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    await waitFor(() => expect(lifecycle.navigatorProps?.memoryScopes).toHaveLength(2));
    expect(screen.getByText("editorpublic content")).toBeInTheDocument();
    act(() => lifecycle.navigatorProps?.onMemoryScopeChange("private"));
    expect(screen.getByText("editorprivate content")).toBeInTheDocument();
    expect(screen.queryByText("editorpublic content")).not.toBeInTheDocument();
    await act(async () => lifecycle.editorProps?.onSaveFile("daily::same.md", "private edit"));
    expect(lifecycle.saveMemoryFile).toHaveBeenCalledWith("same.md", "private edit", "daily", "private", undefined);
    act(() => lifecycle.navigatorProps?.onMemoryScopeChange("public"));
    expect(screen.getByText("editorpublic content")).toBeInTheDocument();
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
      undefined,
    );
    expect(lifecycle.setTabEtag).toHaveBeenCalledWith(
      "agent:agent-a:memory:public",
      "notes.md",
      "v2",
    );
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
      ["agent:agent-a:memory:public", "one.md"],
      ["agent:agent-a:memory:public", "three.md"],
    ]);
    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a:memory:public",
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
        "agent:agent-a:memory:public",
        "daily::a.md",
      ),
    );
  });

  it("switches memory scope and only exposes rebuild for editable scope", async () => {
    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);

    await screen.findByText("公共记忆");
    expect(screen.queryByText("重建索引")).not.toBeInTheDocument();

    act(() => screen.getByText("我的记忆").click());
    expect(await screen.findByText("needs_reindex")).toBeInTheDocument();
    expect(screen.getByText("重建索引")).toBeInTheDocument();

    await act(async () => screen.getByText("重建索引").click());
    expect(lifecycle.rebuildMemoryIndex).toHaveBeenCalledWith(
      "agent-a",
      "private",
    );
  });

  it("invalidates persisted editable tabs when the Agent is use-only", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "stale editable content",
        dirty: false,
        source: "workspace",
        readOnly: false,
      },
    ];

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);

    await waitFor(() =>
      expect(lifecycle.clearProjectTabs).toHaveBeenCalledWith("agent:agent-a:memory:public"),
    );
    expect(lifecycle.navigatorProps?.canEditProjectFiles).toBe(true);
    expect(lifecycle.navigatorProps?.canEditAgentFiles).toBe(false);
  });
});
