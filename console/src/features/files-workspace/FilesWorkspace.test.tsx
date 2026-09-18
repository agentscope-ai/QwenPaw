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
  getFileMetadata: vi.fn(),
  loadFileText: vi.fn(),
  navigatorMounted: vi.fn(),
  navigatorUnmounted: vi.fn(),
  navigatorProps: null as {
    onSelect: (target: { source: string; path: string }) => void;
    onShowMemoryGraph: (root: "wiki" | "procedure" | "personal") => void;
    onShowFiles: () => void;
  } | null,
  memoryGraphProps: null as {
    onOpenFile: (section: "daily" | "digest", path: string) => void;
  } | null,
  saveFileContent: vi.fn(),
  setTabContent: vi.fn(),
  setTabEtag: vi.fn(),
  setActiveTab: vi.fn(),
  tabs: [] as Array<{
    path: string;
    displayPath?: string;
    content: string;
    dirty: boolean;
    source?: "workspace";
    etag?: string;
    previewKind?: "text" | "image" | "pdf" | "csv" | "binary";
  }>,
  activeTabPath: "",
  editorProps: null as {
    onCloseOtherTabs: (path: string) => void;
    onTabSelect: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
  } | null,
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("../../stores/codingTabsStore", () => ({
  useTabsForScope: () => lifecycle.tabs,
  useActiveTabPathForScope: () => lifecycle.activeTabPath,
  useCodingTabsStore: () => ({
    clearProjectTabs: lifecycle.clearProjectTabs,
    closeTab: lifecycle.closeTab,
    openTab: vi.fn(),
    setActiveTab: lifecycle.setActiveTab,
    setTabContent: lifecycle.setTabContent,
    setTabDirty: vi.fn(),
    setTabEtag: lifecycle.setTabEtag,
  }),
}));

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    saveFileContent: lifecycle.saveFileContent,
    getFileMetadata: lifecycle.getFileMetadata,
    loadFileText: lifecycle.loadFileText,
  },
}));

vi.mock("./FilesNavigator", () => ({
  default: function MockFilesNavigator(props: {
    onSelect: (target: { source: string; path: string }) => void;
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
    onTabSelect: (path: string) => void;
    onSaveFile: (path: string, content: string) => Promise<void>;
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

describe("tab content revalidation", () => {
  const scope = { kind: "agent" as const, agentId: "agent-a" };

  beforeEach(() => {
    vi.clearAllMocks();
    lifecycle.tabs = [];
    lifecycle.activeTabPath = "";
    lifecycle.editorProps = null;
    lifecycle.navigatorProps = null;
    lifecycle.getFileMetadata.mockResolvedValue({
      preview_kind: "text",
      etag: "m1",
    });
  });

  it("refetches content when a navigator click re-activates an existing text tab", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "old",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockResolvedValue({ content: "new", etag: "v2" });

    render(<FilesWorkspace scope={scope} />);
    await act(async () => {
      lifecycle.navigatorProps?.onSelect({
        source: "workspace",
        path: "notes.md",
      });
    });

    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
    );
    expect(lifecycle.loadFileText).toHaveBeenCalledWith(
      "notes.md",
      undefined,
      undefined,
      undefined,
    );
    await waitFor(() =>
      expect(lifecycle.setTabContent).toHaveBeenCalledWith(
        "agent:agent-a",
        "notes.md",
        "new",
      ),
    );
  });

  it("never refetches or clobbers a dirty tab", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "user edit",
        dirty: true,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockResolvedValue({
      content: "agent rewrite",
      etag: "v2",
    });

    render(<FilesWorkspace scope={scope} />);
    await act(async () => {
      lifecycle.navigatorProps?.onSelect({
        source: "workspace",
        path: "notes.md",
      });
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
    );
    expect(lifecycle.loadFileText).not.toHaveBeenCalled();
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it("keeps identical content untouched while still refreshing the etag", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "same",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.loadFileText.mockResolvedValue({ content: "same", etag: "v2" });

    render(<FilesWorkspace scope={scope} />);
    await act(async () => {
      lifecycle.navigatorProps?.onSelect({
        source: "workspace",
        path: "notes.md",
      });
    });

    await waitFor(() =>
      expect(lifecycle.setTabEtag).toHaveBeenCalledWith(
        "agent:agent-a",
        "notes.md",
        "v2",
      ),
    );
    expect(lifecycle.setTabContent).not.toHaveBeenCalled();
  });

  it("skips revalidation for image tabs (their preview remounts)", async () => {
    lifecycle.tabs = [
      {
        path: "shot.png",
        content: "",
        dirty: false,
        source: "workspace",
        previewKind: "image",
      },
    ];
    lifecycle.getFileMetadata.mockResolvedValue({
      preview_kind: "image",
      etag: "m1",
    });

    render(<FilesWorkspace scope={scope} />);
    // The mount hydration loads empty-content tabs exactly once; tab
    // activation must not add anything on top of it.
    await waitFor(() =>
      expect(lifecycle.getFileMetadata).toHaveBeenCalledTimes(1),
    );
    await act(async () => {
      lifecycle.editorProps?.onTabSelect("shot.png");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "shot.png",
    );
    expect(lifecycle.getFileMetadata).toHaveBeenCalledTimes(1);
    expect(lifecycle.loadFileText).not.toHaveBeenCalled();
    // One call is the mount hydration of the empty-content tab; a second
    // would mean activation tried to revalidate a preview-kind tab.
    expect(lifecycle.setTabContent).toHaveBeenCalledTimes(1);
  });

  it("revalidates the newly selected editor tab", async () => {
    lifecycle.tabs = [
      {
        path: "a.md",
        content: "A",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
      {
        path: "b.md",
        content: "old-b",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.activeTabPath = "a.md";
    lifecycle.loadFileText.mockImplementation(async (path: string) =>
      path === "b.md"
        ? { content: "new-b", etag: "e2" }
        : { content: "A", etag: "e1" },
    );

    render(<FilesWorkspace scope={scope} />);
    await act(async () => {
      lifecycle.editorProps?.onTabSelect("b.md");
    });

    expect(lifecycle.loadFileText).toHaveBeenCalledWith(
      "b.md",
      undefined,
      undefined,
      undefined,
    );
    await waitFor(() =>
      expect(lifecycle.setTabContent).toHaveBeenCalledWith(
        "agent:agent-a",
        "b.md",
        "new-b",
      ),
    );
  });

  it("revalidates the restored active tab once on mount (drawer reopen)", async () => {
    lifecycle.tabs = [
      {
        path: "notes.md",
        content: "old",
        dirty: false,
        source: "workspace",
        previewKind: "text",
      },
    ];
    lifecycle.activeTabPath = "notes.md";
    lifecycle.loadFileText.mockResolvedValue({ content: "new", etag: "v2" });

    render(<FilesWorkspace scope={scope} />);

    await waitFor(() =>
      expect(lifecycle.setTabContent).toHaveBeenCalledWith(
        "agent:agent-a",
        "notes.md",
        "new",
      ),
    );
    expect(lifecycle.setActiveTab).toHaveBeenCalledWith(
      "agent:agent-a",
      "notes.md",
    );
  });
});
