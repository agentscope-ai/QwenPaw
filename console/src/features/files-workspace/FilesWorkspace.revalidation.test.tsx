import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useCodingTabsStore,
  type EditorTab,
} from "../../stores/codingTabsStore";
import FilesWorkspace from "./FilesWorkspace";

const SCOPE_KEY = "agent:agent-a";
const TAB_PATH = "notes.md";

const harness = vi.hoisted(() => ({
  editorProps: null as {
    onSaveFile: (path: string, content: string) => Promise<void>;
    onTabContentChange: (path: string, content: string) => void;
    onTabDirtyChange: (path: string, dirty: boolean) => void;
    onTabSelect: (path: string) => void;
  } | null,
  getFileMetadata: vi.fn(),
  loadFileText: vi.fn(),
  saveFileContent: vi.fn(),
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    getFileMetadata: harness.getFileMetadata,
    loadFileText: harness.loadFileText,
    loadMemoryFile: vi.fn(),
    saveFileContent: harness.saveFileContent,
  },
}));

vi.mock("./FilesNavigator", () => ({
  default: () => <div>navigator</div>,
}));

vi.mock("./MemoryGraphView", () => ({
  default: () => <div>memory graph</div>,
}));

vi.mock("../../pages/Coding/TabbedEditor", () => ({
  default: (props: NonNullable<typeof harness.editorProps>) => {
    harness.editorProps = props;
    return <div>editor</div>;
  },
}));

vi.mock("../../pages/Coding/GitPanel", () => ({
  default: () => <div>git</div>,
}));

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function openCleanTab(active: boolean) {
  const tab: EditorTab = {
    path: TAB_PATH,
    displayPath: TAB_PATH,
    content: "before",
    dirty: false,
    source: "workspace",
    previewKind: "text",
    etag: "v1",
  };
  useCodingTabsStore.setState({
    tabsByAgent: { [SCOPE_KEY]: [tab] },
    activeTabByAgent: { [SCOPE_KEY]: active ? TAB_PATH : "" },
    diffsByAgent: {},
  });
}

function currentTab() {
  return useCodingTabsStore.getState().tabsByAgent[SCOPE_KEY][0];
}

describe("FilesWorkspace revalidation lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    harness.editorProps = null;
    harness.getFileMetadata.mockResolvedValue({
      path: TAB_PATH,
      size: 6,
      modified_at: "",
      preview_kind: "text",
      etag: "v1",
    });
    harness.loadFileText.mockReset();
    harness.saveFileContent.mockReset();
    useCodingTabsStore.setState({
      tabsByAgent: {},
      activeTabByAgent: {},
      diffsByAgent: {},
    });
  });

  it("keeps reopened unsaved edits when an old instance responds", async () => {
    const oldLoad = createDeferred<{ content: string; etag: string }>();
    const reopenedLoad = createDeferred<{
      content: string;
      etag: string;
    }>();
    harness.loadFileText
      .mockReturnValueOnce(oldLoad.promise)
      .mockReturnValueOnce(reopenedLoad.promise);
    openCleanTab(true);

    const firstView = render(
      <FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />,
    );
    await waitFor(() => expect(harness.loadFileText).toHaveBeenCalledOnce());
    firstView.unmount();

    const reopenedView = render(
      <FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />,
    );
    await waitFor(() => expect(harness.loadFileText).toHaveBeenCalledTimes(2));
    act(() => {
      harness.editorProps?.onTabContentChange(TAB_PATH, "unsaved local edit");
      harness.editorProps?.onTabDirtyChange(TAB_PATH, true);
    });

    await act(async () => {
      oldLoad.resolve({ content: "old server response", etag: "old" });
      await oldLoad.promise;
    });

    expect(currentTab()).toMatchObject({
      content: "unsaved local edit",
      dirty: true,
      etag: "v1",
    });

    await act(async () => {
      reopenedLoad.resolve({ content: "new response", etag: "new" });
      await reopenedLoad.promise;
    });
    expect(currentTab()).toMatchObject({
      content: "unsaved local edit",
      dirty: true,
      etag: "v1",
    });
    reopenedView.unmount();
  });

  it("keeps saved content when an earlier refresh responds", async () => {
    const refresh = createDeferred<{ content: string; etag: string }>();
    harness.loadFileText.mockReturnValue(refresh.promise);
    harness.saveFileContent.mockResolvedValue({
      path: TAB_PATH,
      size: 16,
      etag: "v2",
    });
    openCleanTab(false);

    render(<FilesWorkspace scope={{ kind: "agent", agentId: "agent-a" }} />);
    act(() => harness.editorProps?.onTabSelect(TAB_PATH));
    await waitFor(() => expect(harness.loadFileText).toHaveBeenCalledOnce());
    act(() => {
      harness.editorProps?.onTabContentChange(TAB_PATH, "saved local edit");
      harness.editorProps?.onTabDirtyChange(TAB_PATH, true);
    });
    await act(async () => {
      await harness.editorProps?.onSaveFile(TAB_PATH, "saved local edit");
      harness.editorProps?.onTabDirtyChange(TAB_PATH, false);
    });

    expect(currentTab()).toMatchObject({
      content: "saved local edit",
      dirty: false,
      etag: "v2",
    });

    await act(async () => {
      refresh.resolve({ content: "before", etag: "v1" });
      await refresh.promise;
    });

    expect(currentTab()).toMatchObject({
      content: "saved local edit",
      dirty: false,
      etag: "v2",
    });
  });
});
