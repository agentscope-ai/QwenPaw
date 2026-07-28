import { act, render } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesWorkspace from "./FilesWorkspace";
import { notifyProjectDirectoryChanged } from "../project-directory/projectDirectoryChangeEvent";

const lifecycle = vi.hoisted(() => ({
  clearProjectTabs: vi.fn(),
  editorMounted: vi.fn(),
  editorUnmounted: vi.fn(),
  navigatorMounted: vi.fn(),
  navigatorUnmounted: vi.fn(),
  saveFileContent: vi.fn(),
  setTabEtag: vi.fn(),
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
    closeTab: vi.fn(),
    openTab: vi.fn(),
    setActiveTab: vi.fn(),
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
  default: function MockFilesNavigator() {
    useEffect(() => {
      lifecycle.navigatorMounted();
      return () => lifecycle.navigatorUnmounted();
    }, []);
    return <div>navigator</div>;
  },
}));

vi.mock("../../pages/Coding/TabbedEditor", () => ({
  default: function MockTabbedEditor(props: {
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
});
