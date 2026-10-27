import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useEffect } from "react";
import type { DiffOnMount } from "@monaco-editor/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import type { FileChangeEvent } from "../../hooks/useWorkspaceWatch";
import FilesWorkspace from "./FilesWorkspace";

const SCOPE_KEY = "agent:agent-a";
const TAB_PATH = "notes.md";
const scope = { kind: "agent" as const, agentId: "agent-a" };
const harness = vi.hoisted(() => ({
  loadFileText: vi.fn(),
  saveFileContent: vi.fn(),
  editDiff: (() => {}) as (content: string) => void,
  watch: (() => {}) as (events: FileChangeEvent[]) => void,
}));

vi.mock("../../monacoSetup", () => ({}));
vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: true }),
}));
vi.mock("../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: vi.fn(), success: vi.fn() } }),
}));
vi.mock("../../hooks/useWorkspaceWatch", () => ({
  useWorkspaceWatch: (callback: typeof harness.watch) => {
    harness.watch = callback;
  },
}));
vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    getFileMetadata: vi.fn(async () => ({ preview_kind: "text", etag: "v3" })),
    loadFileText: harness.loadFileText,
    saveFileContent: harness.saveFileContent,
  },
}));
vi.mock("./FilesNavigator", () => ({ default: () => null }));
vi.mock("./MemoryGraphView", () => ({ default: () => null }));
vi.mock("../../pages/Coding/GitPanel", () => ({ default: () => null }));
vi.mock("../../pages/Coding/FilePreview", () => ({
  default: () => null,
  isPreviewable: () => false,
}));
vi.mock("@monaco-editor/react", () => ({
  default: ({ value }: { value: string }) => <div>{value}</div>,
  DiffEditor: function MockDiffEditor({
    original,
    modified,
    onMount,
  }: {
    original: string;
    modified: string;
    onMount: DiffOnMount;
  }) {
    useEffect(() => {
      let value = modified;
      let listener = () => {};
      harness.editDiff = (content) => {
        value = content;
        listener();
      };
      const editor = {
        getModifiedEditor: () => ({
          getValue: () => value,
          onDidChangeModelContent: (callback: () => void) => {
            listener = callback;
            return { dispose: () => {} };
          },
        }),
        getLineChanges: () => [],
        onDidUpdateDiff: () => ({ dispose: () => {} }),
      };
      onMount(
        editor as unknown as Parameters<DiffOnMount>[0],
        {} as Parameters<DiffOnMount>[1],
      );
      // Mount once, as Monaco does; edits go through its model listener.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return (
      <div data-testid="diff">
        {original} / {modified}
      </div>
    );
  },
}));

function seedDiff(active = TAB_PATH) {
  useCodingTabsStore.setState({
    tabsByAgent: {
      [SCOPE_KEY]: [
        {
          path: TAB_PATH,
          content: "original",
          dirty: false,
          source: "workspace",
          previewKind: "text",
          etag: "v2",
        },
        { path: "other.txt", content: "other", dirty: false },
      ],
    },
    activeTabByAgent: { [SCOPE_KEY]: active },
    diffsByAgent: {
      [SCOPE_KEY]: {
        [TAB_PATH]: { original: "original", modified: "agent edit v2" },
      },
    },
  });
}

function currentTab() {
  return useCodingTabsStore.getState().tabsByAgent[SCOPE_KEY][0];
}

function currentDiff() {
  return useCodingTabsStore.getState().diffsByAgent[SCOPE_KEY][TAB_PATH];
}

describe("FilesWorkspace pending diff refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    harness.loadFileText.mockReset();
    harness.loadFileText.mockResolvedValue({
      content: "agent edit v3",
      etag: "v3",
    });
    harness.saveFileContent.mockResolvedValue({ etag: "saved" });
    seedDiff();
  });

  it.each(["reopen", "activate"])(
    "keeps the latest disk content after %s with a pending diff",
    async (mode) => {
      seedDiff(mode === "activate" ? "other.txt" : TAB_PATH);
      harness.loadFileText.mockResolvedValueOnce({
        content: "agent edit v2",
        etag: "v2",
      });
      const firstView = render(<FilesWorkspace scope={scope} />);
      if (mode === "reopen") {
        await waitFor(() =>
          expect(harness.loadFileText).toHaveBeenCalledOnce(),
        );
        firstView.unmount();
        render(<FilesWorkspace scope={scope} />);
      } else {
        fireEvent.click(screen.getByRole("tab", { name: /notes.md/ }));
      }

      await waitFor(() => expect(currentTab().etag).toBe("v3"));
      expect(currentDiff()).toEqual({
        original: "original",
        modified: "agent edit v3",
      });
      fireEvent.click(
        screen.getByRole("button", { name: /keepAll|全部保留/i }),
      );

      await waitFor(() => {
        expect(harness.saveFileContent).toHaveBeenCalledWith(
          TAB_PATH,
          "agent edit v3",
          "v3",
          undefined,
          undefined,
          undefined,
        );
      });
      await waitFor(() => expect(currentDiff()).toBeUndefined());
    },
  );

  it("preserves edits made in the diff editor before reopening", async () => {
    harness.loadFileText.mockResolvedValue({
      content: "agent edit v2",
      etag: "v2",
    });
    const view = render(<FilesWorkspace scope={scope} />);
    await waitFor(() => expect(harness.loadFileText).toHaveBeenCalledOnce());
    fireEvent.click(
      screen.getByRole("button", { name: /^files.edit$|^编辑$/i }),
    );
    act(() => harness.editDiff("user edit"));
    expect(currentTab().dirty).toBe(true);
    view.unmount();
    harness.loadFileText.mockResolvedValue({
      content: "agent edit v3",
      etag: "v3",
    });

    render(<FilesWorkspace scope={scope} />);

    await act(async () => {});
    expect(currentDiff().modified).toBe("user edit");
    expect(currentTab()).toMatchObject({ etag: "v2", dirty: true });
    expect(harness.loadFileText).toHaveBeenCalledOnce();
  });

  it.each(["edit", "update", "resolve", "create"])(
    "rejects a refresh when the pending diff changes during the request: %s",
    async (change) => {
      let finish!: (loaded: { content: string; etag: string }) => void;
      harness.loadFileText.mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      if (change === "create") {
        useCodingTabsStore.getState().removeDiff(SCOPE_KEY, TAB_PATH);
      }
      render(<FilesWorkspace scope={scope} />);
      await waitFor(() => expect(harness.loadFileText).toHaveBeenCalledOnce());
      if (change === "edit") {
        fireEvent.click(
          screen.getByRole("button", { name: /^files.edit$|^编辑$/i }),
        );
      }
      act(() => {
        const store = useCodingTabsStore.getState();
        if (change === "edit") {
          harness.editDiff("user edit");
        } else if (change === "update") {
          store.updateDiffOriginal(SCOPE_KEY, TAB_PATH, "accepted hunk");
        } else if (change === "resolve") {
          store.removeDiff(SCOPE_KEY, TAB_PATH);
        } else {
          store.setDiff(SCOPE_KEY, TAB_PATH, {
            original: "original",
            modified: "new diff",
          });
        }
      });
      const expectedDiff = currentDiff();
      await act(async () => finish({ content: "agent edit v3", etag: "v3" }));

      expect(currentTab().etag).toBe("v2");
      expect(currentDiff()).toBe(expectedDiff);
    },
  );

  it.each([true, false])(
    "rejects an older watcher response (existing diff: %s)",
    async (hasDiff) => {
      if (!hasDiff)
        useCodingTabsStore.getState().removeDiff(SCOPE_KEY, TAB_PATH);
      harness.loadFileText.mockResolvedValueOnce({
        content: "agent edit v2",
        etag: "v2",
      });
      render(<FilesWorkspace scope={scope} />);
      await waitFor(() => expect(currentTab().content).toBe("agent edit v2"));
      let finish!: (loaded: { content: string; etag: string }) => void;
      harness.loadFileText.mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      act(() => harness.watch([{ path: TAB_PATH, change: "modified" }]));
      await waitFor(() =>
        expect(harness.loadFileText).toHaveBeenCalledTimes(2),
      );

      fireEvent.click(screen.getByRole("tab", { name: /notes.md/ }));
      await waitFor(() => expect(currentTab().etag).toBe("v3"));
      await act(async () => finish({ content: "agent edit v2", etag: "v2" }));

      if (hasDiff) expect(currentDiff().modified).toBe("agent edit v3");
      else expect(currentDiff()).toBeUndefined();
      expect(currentTab().etag).toBe("v3");
    },
  );

  it("hydrates a restored diff and ignores the older parallel response", async () => {
    useCodingTabsStore.getState().setTabContent(SCOPE_KEY, TAB_PATH, "");
    useCodingTabsStore.getState().setDiff(SCOPE_KEY, TAB_PATH, {
      original: "original",
      modified: null,
    });
    const responses: Array<
      (loaded: { content: string; etag: string }) => void
    > = [];
    harness.loadFileText.mockImplementation(
      () =>
        new Promise((resolve) => {
          responses.push(resolve);
        }),
    );
    render(<FilesWorkspace scope={scope} />);
    await waitFor(() => expect(responses).toHaveLength(2));
    await act(async () =>
      responses[1]({ content: "agent edit v3", etag: "v3" }),
    );
    await act(async () =>
      responses[0]({ content: "agent edit v2", etag: "v2" }),
    );

    expect(currentDiff()).toEqual({
      original: "original",
      modified: "agent edit v3",
    });
    expect(currentTab()).toMatchObject({
      content: "agent edit v3",
      etag: "v3",
    });
  });
});
