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

function Harness({
  onSaveFile,
}: {
  onSaveFile: (path: string, content: string) => Promise<void>;
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
