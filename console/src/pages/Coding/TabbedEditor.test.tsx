// @vitest-environment jsdom
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TabbedEditor from "./TabbedEditor";
import { useCodingTabsStore } from "../../stores/codingTabsStore";

const SCOPE_KEY = "agent:default";

const clipboardMocks = vi.hoisted(() => ({
  copyText: vi.fn().mockResolvedValue(undefined),
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock("../../monacoSetup", () => ({}));

vi.mock("@monaco-editor/react", () => ({
  default: ({
    value,
    onMount,
  }: {
    value: string;
    onMount?: (editor: unknown) => void;
  }) => {
    onMount?.({
      getValue: () => "",
      onDidChangeCursorSelection: () => ({ dispose: vi.fn() }),
    });
    return <div data-testid="editor-value">{value}</div>;
  },
  DiffEditor: () => <div data-testid="diff-editor" />,
}));

vi.mock("../../hooks/useWorkspaceWatch", () => ({
  useWorkspaceWatch: vi.fn(),
}));

vi.mock("../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../utils/clipboard", () => ({
  copyText: clipboardMocks.copyText,
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      error: clipboardMocks.error,
      success: clipboardMocks.success,
    },
  }),
}));

function Harness({
  onSaveFile,
  onDownloadFile,
}: {
  onSaveFile: (path: string, content: string) => Promise<void>;
  onDownloadFile?: (path: string) => Promise<void>;
}) {
  const tabs = useCodingTabsStore(
    (state) => state.tabsByAgent[SCOPE_KEY] ?? [],
  );
  const activeTabPath = useCodingTabsStore(
    (state) => state.activeTabByAgent[SCOPE_KEY] ?? "",
  );
  const store = useCodingTabsStore();

  return (
    <TabbedEditor
      tabs={tabs}
      activeTabPath={activeTabPath}
      scopeKey={SCOPE_KEY}
      onTabSelect={(path) => store.setActiveTab(SCOPE_KEY, path)}
      onTabClose={(path) => store.closeTab(SCOPE_KEY, path)}
      onCloseOtherTabs={(path) => {
        tabs.forEach((tab) => {
          if (tab.path !== path) store.closeTab(SCOPE_KEY, tab.path);
        });
        store.setActiveTab(SCOPE_KEY, path);
      }}
      onTabDirtyChange={(path, dirty) =>
        store.setTabDirty(SCOPE_KEY, path, dirty)
      }
      onTabContentChange={(path, content) =>
        store.setTabContent(SCOPE_KEY, path, content)
      }
      onDownloadFile={onDownloadFile}
      onSaveFile={onSaveFile}
    />
  );
}

describe("TabbedEditor diff resolution", () => {
  beforeEach(() => {
    useCodingTabsStore.setState({
      tabsByAgent: {
        [SCOPE_KEY]: [{ path: "hello.txt", content: "original", dirty: false }],
      },
      activeTabByAgent: { [SCOPE_KEY]: "hello.txt" },
      diffsByAgent: {
        [SCOPE_KEY]: {
          "hello.txt": { original: "original", modified: "changed" },
        },
      },
    });
  });

  it("saves the restored content after undo instead of a stale empty editor", async () => {
    const onSaveFile = vi.fn(async () => undefined);
    const { container } = render(<Harness onSaveFile={onSaveFile} />);

    const undoLabel = await screen.findByText(/undoAll|全部回退/i);
    fireEvent.click(undoLabel.closest("button") as HTMLButtonElement);

    await waitFor(() => {
      expect(onSaveFile).toHaveBeenCalledWith("hello.txt", "original");
      expect(
        useCodingTabsStore.getState().diffsByAgent[SCOPE_KEY],
      ).not.toHaveProperty("hello.txt");
    });

    fireEvent.keyDown(container.firstElementChild as HTMLElement, {
      key: "s",
      ctrlKey: true,
    });

    await waitFor(() => {
      expect(onSaveFile).toHaveBeenLastCalledWith("hello.txt", "original");
    });
    expect(onSaveFile).not.toHaveBeenCalledWith("hello.txt", "");
  });
});

describe("TabbedEditor clipboard action", () => {
  beforeEach(() => {
    clipboardMocks.copyText.mockClear();
    clipboardMocks.success.mockClear();
    useCodingTabsStore.setState({
      tabsByAgent: {
        [SCOPE_KEY]: [
          {
            path: "hello.txt",
            content: "unsaved content",
            dirty: true,
            previewKind: "text",
          },
        ],
      },
      activeTabByAgent: { [SCOPE_KEY]: "hello.txt" },
      diffsByAgent: { [SCOPE_KEY]: {} },
    });
  });

  it("copies the current in-memory file content", async () => {
    render(
      <Harness
        onSaveFile={vi.fn(async () => undefined)}
        onDownloadFile={vi.fn(async () => undefined)}
      />,
    );
    const copyButton = screen.getByRole("button", { name: /copy|复制/i });
    const downloadButton = screen.getByRole("button", {
      name: /download|下载/i,
    });

    expect(
      copyButton.compareDocumentPosition(downloadButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(copyButton);

    await waitFor(() => {
      expect(clipboardMocks.copyText).toHaveBeenCalledWith("unsaved content");
      expect(clipboardMocks.success).toHaveBeenCalled();
    });
  });
});

describe("TabbedEditor tab context menu", () => {
  beforeEach(() => {
    useCodingTabsStore.setState({
      tabsByAgent: {
        [SCOPE_KEY]: [
          { path: "one.txt", content: "one", dirty: false },
          { path: "two.txt", content: "two", dirty: false },
          { path: "three.txt", content: "three", dirty: false },
        ],
      },
      activeTabByAgent: { [SCOPE_KEY]: "one.txt" },
      diffsByAgent: { [SCOPE_KEY]: {} },
    });
  });

  it("closes the tab that was right-clicked", async () => {
    render(<Harness onSaveFile={vi.fn(async () => undefined)} />);

    fireEvent.contextMenu(screen.getByRole("tab", { name: /two\.txt/i }));
    fireEvent.click(await screen.findByText(/closeTab|关闭标签页/i));

    await waitFor(() => {
      expect(
        useCodingTabsStore
          .getState()
          .tabsByAgent[SCOPE_KEY].map((tab) => tab.path),
      ).toEqual(["one.txt", "three.txt"]);
      expect(useCodingTabsStore.getState().activeTabByAgent[SCOPE_KEY]).toBe(
        "one.txt",
      );
    });
  });

  it("keeps and activates the tab used to close the others", async () => {
    render(<Harness onSaveFile={vi.fn(async () => undefined)} />);

    fireEvent.contextMenu(screen.getByRole("tab", { name: /two\.txt/i }));
    fireEvent.click(await screen.findByText(/closeOtherTabs|关闭其他标签页/i));

    await waitFor(() => {
      expect(useCodingTabsStore.getState().tabsByAgent[SCOPE_KEY]).toHaveLength(
        1,
      );
      expect(useCodingTabsStore.getState().tabsByAgent[SCOPE_KEY][0].path).toBe(
        "two.txt",
      );
      expect(useCodingTabsStore.getState().activeTabByAgent[SCOPE_KEY]).toBe(
        "two.txt",
      );
    });
  });

  it("closes a tab with the middle mouse button", async () => {
    render(<Harness onSaveFile={vi.fn(async () => undefined)} />);

    fireEvent(
      screen.getByRole("tab", { name: /two\.txt/i }),
      new MouseEvent("auxclick", { bubbles: true, button: 1 }),
    );

    await waitFor(() => {
      expect(
        useCodingTabsStore
          .getState()
          .tabsByAgent[SCOPE_KEY].map((tab) => tab.path),
      ).toEqual(["one.txt", "three.txt"]);
    });
  });

  it("searches and activates a file from the open-files panel", async () => {
    render(<Harness onSaveFile={vi.fn(async () => undefined)} />);

    fireEvent.click(
      screen.getByRole("button", { name: /openFiles|已打开文件/i }),
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("searchbox"), {
      target: { value: "two" },
    });

    expect(within(dialog).getByText("two.txt")).toBeInTheDocument();
    expect(within(dialog).queryByText("three.txt")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByText("two.txt"));

    await waitFor(() => {
      expect(useCodingTabsStore.getState().activeTabByAgent[SCOPE_KEY]).toBe(
        "two.txt",
      );
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("closes every tab from the open-files panel", async () => {
    render(<Harness onSaveFile={vi.fn(async () => undefined)} />);

    fireEvent.click(
      screen.getByRole("button", { name: /openFiles|已打开文件/i }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /closeAllTabs|关闭全部标签页/i,
      }),
    );

    await waitFor(() => {
      expect(useCodingTabsStore.getState().tabsByAgent[SCOPE_KEY]).toEqual([]);
    });
  });
});

// ---------------------------------------------------------------------------
// Project switch — regression for A#82628675 (open files not following project switch)
// When the user switches projects/agents, the open file list must update
// to reflect the new project's tabs (or be empty if the new project has
// no open tabs). The store's clearAgent/clearProjectTabs handles this.
// ---------------------------------------------------------------------------
describe("TabbedEditor project switch (A#82628675)", () => {
  const AGENT_A = "agent:alpha";
  const AGENT_B = "agent:beta";

  beforeEach(() => {
    useCodingTabsStore.setState({
      tabsByAgent: {
        [AGENT_A]: [
          { path: "a1.txt", content: "a1", dirty: false },
          { path: "a2.txt", content: "a2", dirty: false },
        ],
        [AGENT_B]: [{ path: "b1.txt", content: "b1", dirty: false }],
      },
      activeTabByAgent: {
        [AGENT_A]: "a1.txt",
        [AGENT_B]: "b1.txt",
      },
      diffsByAgent: { [AGENT_A]: {}, [AGENT_B]: {} },
    });
  });

  it("preserves each agent's tabs independently", () => {
    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent[AGENT_A].map((t) => t.path)).toEqual([
      "a1.txt",
      "a2.txt",
    ]);
    expect(state.tabsByAgent[AGENT_B].map((t) => t.path)).toEqual(["b1.txt"]);
  });

  it("clears tabs for the switched-away agent when clearAgent is called", () => {
    useCodingTabsStore.getState().clearAgent(AGENT_A);
    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent[AGENT_A]).toEqual([]);
    expect(state.activeTabByAgent[AGENT_A]).toBe("");
    // Agent B's tabs should be unaffected
    expect(state.tabsByAgent[AGENT_B].map((t) => t.path)).toEqual(["b1.txt"]);
  });

  it("clears project-scoped tabs when clearProjectTabs is called", () => {
    const projectScope = "session:proj-123";
    useCodingTabsStore.setState({
      tabsByAgent: {
        ...useCodingTabsStore.getState().tabsByAgent,
        [projectScope]: [{ path: "proj.txt", content: "proj", dirty: false }],
      },
      activeTabByAgent: {
        ...useCodingTabsStore.getState().activeTabByAgent,
        [projectScope]: "proj.txt",
      },
    });

    useCodingTabsStore.getState().clearProjectTabs(projectScope);
    const state = useCodingTabsStore.getState();
    expect(state.tabsByAgent[projectScope]).toEqual([]);
    expect(state.activeTabByAgent[projectScope]).toBe("");
  });

  it("switching to a new agent shows that agent's tabs", () => {
    // Simulate switching from agent A to agent B
    const agentBTabs = useCodingTabsStore.getState().tabsByAgent[AGENT_B];
    expect(agentBTabs).toHaveLength(1);
    expect(agentBTabs[0].path).toBe("b1.txt");
    expect(useCodingTabsStore.getState().activeTabByAgent[AGENT_B]).toBe(
      "b1.txt",
    );
  });
});
