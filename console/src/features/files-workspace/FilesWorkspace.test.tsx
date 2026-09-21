import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesWorkspace from "./FilesWorkspace";
import { notifyProjectDirectoryChanged } from "../project-directory/projectDirectoryChangeEvent";
import type { EditorTab } from "../../stores/codingTabsStore";

const lifecycle = vi.hoisted(() => ({
  clearProjectTabs: vi.fn(),
  closeTab: vi.fn(),
  editorMounted: vi.fn(),
  editorUnmounted: vi.fn(),
  navigatorMounted: vi.fn(),
  navigatorUnmounted: vi.fn(),
  navigatorProps: null as {
    onSelect: (target: { source: "workspace"; path: string }) => void;
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
  } | null,
  memoryGraphProps: null as {
    onOpenFile: (section: "daily" | "digest", path: string) => void;
  } | null,
  getFileMetadata: vi.fn(),
  loadFileText: vi.fn(),
  loadMemoryFile: vi.fn(),
  saveFileContent: vi.fn(),
  setTabContent: vi.fn(),
  setTabEtag: vi.fn(),
  setActiveTab: vi.fn(),
  tabs: [] as EditorTab[],
  activeTabPath: "",
  editorProps: null as {
    onCloseOtherTabs: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
    onTabSelect: (path: string) => void;
  } | null,
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("../../stores/codingTabsStore", () => {
  const useCodingTabsStore = Object.assign(
    () => ({
      clearProjectTabs: lifecycle.clearProjectTabs,
      closeTab: lifecycle.closeTab,
      openTab: vi.fn(),
      setActiveTab: lifecycle.setActiveTab,
      setTabContent: lifecycle.setTabContent,
      setTabDirty: vi.fn(),
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
    loadMemoryFile: lifecycle.loadMemoryFile,
    saveFileContent: lifecycle.saveFileContent,
  },
}));

vi.mock("./FilesNavigator", () => ({
  default: function MockFilesNavigator(props: {
    onSelect: (target: { source: "workspace"; path: string }) => void;
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
  }) {
    lifecycle.navigatorProps = props;
    useEffect(() => {
      lifecycle.navigatorMounted();
      return () => lifecycle.navigatorUnmounted();
    }, []);
    return <div>navigator</div>;
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
    onCloseOtherTabs: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
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
