// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TabbedEditor from "./TabbedEditor";
import { useAgentStore } from "../../stores/agentStore";
import { useCodingTabsStore } from "../../stores/codingTabsStore";

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
  const tabs = useCodingTabsStore((state) => state.tabsByAgent.default ?? []);
  const activeTabPath = useCodingTabsStore(
    (state) => state.activeTabByAgent.default ?? "",
  );
  const store = useCodingTabsStore();

  return (
    <TabbedEditor
      tabs={tabs}
      activeTabPath={activeTabPath}
      onTabSelect={(path) => store.setActiveTab("default", path)}
      onTabClose={(path) => store.closeTab("default", path)}
      onTabDirtyChange={(path, dirty) =>
        store.setTabDirty("default", path, dirty)
      }
      onTabContentChange={(path, content) =>
        store.setTabContent("default", path, content)
      }
      onSaveFile={onSaveFile}
    />
  );
}

describe("TabbedEditor diff resolution", () => {
  beforeEach(() => {
    useAgentStore.setState({ selectedAgent: "default", agents: [] });
    useCodingTabsStore.setState({
      tabsByAgent: {
        default: [{ path: "hello.txt", content: "original", dirty: false }],
      },
      activeTabByAgent: { default: "hello.txt" },
      diffsByAgent: {
        default: {
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
        useCodingTabsStore.getState().diffsByAgent.default,
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
