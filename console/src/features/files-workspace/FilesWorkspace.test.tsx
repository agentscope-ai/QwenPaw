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
  } | null,
  memoryGraphProps: null as {
    onOpenFile: (section: "daily" | "digest", path: string) => void;
  } | null,
  saveFileContent: vi.fn(),
  setTabEtag: vi.fn(),
  setActiveTab: vi.fn(),
  tabs: [] as Array<{
    path: string;
    displayPath?: string;
    content: string;
    dirty: boolean;
    source?: "workspace";
    etag?: string;
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
  useTabsForScope: () => lifecycle.tabs,
  useActiveTabPathForScope: () => lifecycle.activeTabPath,
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
  },
}));

vi.mock("./FilesNavigator", () => ({
  default: function MockFilesNavigator(props: {
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
