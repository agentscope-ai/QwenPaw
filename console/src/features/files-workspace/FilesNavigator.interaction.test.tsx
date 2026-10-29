import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import FilesNavigator from "./FilesNavigator";
import type { DirectoryEntry, DirectoryPage, FileTarget } from "./types";

const mocks = vi.hoisted(() => ({
  getProjectDirectory: vi.fn(),
  getSystemPromptFiles: vi.fn(),
  listDirectory: vi.fn(),
  listFiles: vi.fn(),
  listMemoryFiles: vi.fn(),
  setSystemPromptFiles: vi.fn(),
  fileGlyphRender: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) => {
      const labels: Record<string, string> = {
        "files.workspace": "Workspace",
        "files.profile": "Profile",
        "files.daily": "Daily",
        "files.digest": "Digest",
        "files.memoryTagsLabel": "Tags",
        "files.upload": "Upload",
        "files.addSystemPrompt": "Add from workspace",
        "files.addSystemPromptTitle": "Add a system prompt file",
        "files.addSystemPromptDescription": "Choose a file",
        "files.searchSystemPromptFiles": "Search files",
        "files.noSystemPromptCandidates": "No files",
      };
      if (key === "files.promptToggle") return `Toggle ${values?.name}`;
      return labels[key] ?? key;
    },
  }),
}));

vi.mock("../../api/modules/workspace", () => ({
  UploadConflictError: class extends Error {},
  workspaceApi: {
    getSystemPromptFiles: mocks.getSystemPromptFiles,
    listDirectory: mocks.listDirectory,
    listFiles: mocks.listFiles,
    listMemoryFiles: mocks.listMemoryFiles,
    setSystemPromptFiles: mocks.setSystemPromptFiles,
  },
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: { get: mocks.getProjectDirectory },
}));

vi.mock("../../stores/codingTabsStore", () => ({
  useCodingTabsStore: {
    getState: () => ({
      clearProjectTabs: vi.fn(),
      diffsByAgent: {},
      tabsByAgent: {},
    }),
  },
}));

vi.mock("../project-directory/SessionProjectDirectory", () => ({
  default: () => <span>Project</span>,
}));

vi.mock("./FileGlyph", () => ({
  default: ({ name }: { name: string }) => {
    mocks.fileGlyphRender(name);
    return <span data-file-glyph={name} />;
  },
}));

const mdFile = (filename: string) => ({
  filename,
  size: 10,
  created_time: "2026-01-01T00:00:00Z",
  modified_time: "2026-01-01T00:00:00Z",
});

function renderNavigator({
  onSelect = vi.fn(),
  selectedPath = "",
}: {
  onSelect?: (target: FileTarget) => void;
  selectedPath?: string;
} = {}) {
  return render(
    <FilesNavigator
      selectedPath={selectedPath}
      onSelect={onSelect}
      activeMemoryGraphRoot={null}
      onShowMemoryGraph={vi.fn()}
      onShowFiles={vi.fn()}
      scope={{ kind: "agent", agentId: "default" }}
    />,
  );
}

async function openProfile() {
  fireEvent.click(await screen.findByRole("tab", { name: "Profile" }));
}

function entry(
  path: string,
  kind: "file" | "directory" = "file",
): DirectoryEntry {
  return {
    name: path.split("/").pop()!,
    path,
    kind,
    size: null,
    modified_at: "2026-10-09T00:00:00Z",
    preview_kind: kind,
  };
}

function page(
  entries: DirectoryEntry[],
  cursor: string | null = null,
): DirectoryPage {
  return {
    directory: "",
    entries,
    next_cursor: cursor,
    has_more: cursor !== null,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function refresh() {
  fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
}

describe("FilesNavigator interactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listDirectory.mockReset();
    mocks.getProjectDirectory.mockResolvedValue({
      path: "/project",
      workspace_dir: "/workspace",
    });
    mocks.listDirectory.mockResolvedValue({
      entries: [],
      next_cursor: null,
      has_more: false,
    });
    mocks.listMemoryFiles.mockResolvedValue([]);
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.setSystemPromptFiles.mockImplementation(async (files) => files);
    mocks.fileGlyphRender.mockClear();
  });

  it("keeps Tags in the same navigation bar and returns to the file tree", async () => {
    function UnifiedNavigator() {
      const [tagsActive, setTagsActive] = useState(false);
      return (
        <FilesNavigator
          selectedPath=""
          onSelect={vi.fn()}
          activeMemoryGraphRoot={null}
          onShowMemoryGraph={vi.fn()}
          onShowFiles={() => setTagsActive(false)}
          memoryTagsActive={tagsActive}
          memoryTagsPanel={<div>Tag results</div>}
          onShowMemoryTags={() => setTagsActive(true)}
          scope={{ kind: "agent", agentId: "default" }}
        />
      );
    }
    render(<UnifiedNavigator />);
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Workspace",
      "Profile",
      "Daily",
      "Digest",
      "Tags",
    ]);
    fireEvent.click(screen.getByRole("tab", { name: "Tags" }));
    expect(screen.getByRole("tab", { name: "Tags" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Workspace" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.getByText("Tag results")).toBeVisible();
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Daily" }));
    expect(screen.getByRole("tab", { name: "Daily" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByText("Tag results")).not.toBeInTheDocument();
    expect(screen.getByRole("tree")).toBeVisible();
    await waitFor(() => expect(mocks.listMemoryFiles).toHaveBeenCalled());
  });

  it("shows loading instead of an empty state while the root request is pending", async () => {
    const pending = deferred<DirectoryPage>();
    mocks.listDirectory.mockReturnValueOnce(pending.promise);
    renderNavigator();
    expect(screen.getByRole("tree")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("common.loading")).toBeInTheDocument();
    expect(screen.queryByText("files.sourceEmpty")).not.toBeInTheDocument();
    await act(async () => pending.resolve(page([entry("ready.txt")])));
    expect(screen.getByText("ready.txt")).toBeInTheDocument();
    expect(screen.getByRole("tree")).toHaveAttribute("aria-busy", "false");
  });

  it("separates root errors from empty states and retries an empty root", async () => {
    mocks.listDirectory.mockRejectedValueOnce(new Error("Root unavailable"));
    renderNavigator();
    const alert = await screen.findByRole("alert");
    expect(screen.queryByText("files.sourceEmpty")).not.toBeInTheDocument();
    expect(alert).toHaveTextContent("files.listFailed");
    expect(screen.queryByText("files.loadFailed")).not.toBeInTheDocument();
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    await openProfile();
    expect(await screen.findByText("files.sourceEmpty")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Workspace" }));
    fireEvent.click(
      within(screen.getByRole("alert")).getByRole("button", {
        name: "common.retry",
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    expect(await screen.findByText("files.sourceEmpty")).toBeInTheDocument();
    expect(mocks.listDirectory).toHaveBeenCalledTimes(2);
  });

  it("retries a child first-page error without refreshing the root", async () => {
    let attempts = 0;
    mocks.listDirectory.mockImplementation(async (path: string) => {
      if (!path) return page([entry("folder", "directory")]);
      if (attempts++ === 0) throw new Error("Child unavailable");
      return page([entry("folder/ready.txt")]);
    });
    renderNavigator();
    fireEvent.click(await screen.findByRole("treeitem", { name: "folder" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("files.listFailed");
    fireEvent.click(
      within(alert).getByRole("button", { name: "common.retry" }),
    );
    await screen.findByText("ready.txt");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: "folder" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(
      mocks.listDirectory.mock.calls.filter(([path]) => !path),
    ).toHaveLength(1);
  });

  it.each(["", "folder"])(
    "retries a failed page for %s with the same cursor and cached files",
    async (directory) => {
      const pending = deferred<DirectoryPage>();
      let pageAttempts = 0;
      mocks.listDirectory.mockImplementation(
        async (path: string, cursor?: string) => {
          if (path !== directory) return page([entry("folder", "directory")]);
          if (!cursor) return page([entry("before.txt")], "next-page");
          if (pageAttempts++ === 0) throw new Error("Page unavailable");
          return pending.promise;
        },
      );
      renderNavigator();
      if (directory)
        fireEvent.click(
          await screen.findByRole("treeitem", { name: "folder" }),
        );
      await screen.findByText("before.txt");
      fireEvent.click(screen.getByRole("button", { name: "files.loadMore" }));
      await screen.findByRole("alert");
      if (directory) {
        const folder = screen.getByRole("treeitem", { name: "folder" });
        fireEvent.click(folder);
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
        fireEvent.click(folder);
      }
      fireEvent.click(
        within(screen.getByRole("alert")).getByRole("button", {
          name: "common.retry",
        }),
      );
      expect(screen.getByText("before.txt")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "files.loadMore" }),
      ).toBeDisabled();
      await act(async () => pending.resolve(page([entry("after.txt")])));
      expect(screen.getByText("before.txt")).toBeInTheDocument();
      expect(screen.getByText("after.txt")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        mocks.listDirectory.mock.calls.filter(([path]) => path === directory),
      ).toEqual([
        [directory, undefined, 200, undefined, "project", undefined],
        [directory, "next-page", 200, undefined, "project", undefined],
        [directory, "next-page", 200, undefined, "project", undefined],
      ]);
    },
  );

  it.each(["", "folder"])(
    "retries a failed refresh for %s by rebuilding all cached pages",
    async (directory) => {
      let updated = false;
      let refreshedPageAttempts = 0;
      mocks.listDirectory.mockImplementation(
        async (path: string, cursor?: string) => {
          if (path !== directory) return page([entry("folder", "directory")]);
          if (!cursor)
            return page(
              [entry(updated ? "fresh-first.txt" : "old-first.txt")],
              updated ? "fresh-cursor" : "old-cursor",
            );
          if (updated && refreshedPageAttempts++ === 0)
            throw new Error("Refreshed page unavailable");
          return page([entry(updated ? "fresh-second.txt" : "old-second.txt")]);
        },
      );
      renderNavigator();
      if (directory)
        fireEvent.click(
          await screen.findByRole("treeitem", { name: "folder" }),
        );
      await screen.findByText("old-first.txt");
      fireEvent.click(screen.getByRole("button", { name: "files.loadMore" }));
      await screen.findByText("old-second.txt");
      updated = true;
      mocks.listDirectory.mockClear();
      refresh();
      const alert = await screen.findByRole("alert");
      expect(screen.getByText("old-first.txt")).toBeInTheDocument();
      expect(screen.getByText("old-second.txt")).toBeInTheDocument();
      expect(screen.queryByText("fresh-first.txt")).not.toBeInTheDocument();
      fireEvent.click(
        within(alert).getByRole("button", { name: "common.retry" }),
      );
      await screen.findByText("fresh-second.txt");
      expect(screen.getByText("fresh-first.txt")).toBeInTheDocument();
      expect(screen.queryByText("old-first.txt")).not.toBeInTheDocument();
      expect(screen.queryByText("old-second.txt")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        mocks.listDirectory.mock.calls
          .filter(([path]) => path === directory)
          .map(([, cursor]) => cursor),
      ).toEqual([undefined, "fresh-cursor", undefined, "fresh-cursor"]);
      if (directory)
        expect(
          screen.getByRole("treeitem", { name: "folder" }),
        ).toHaveAttribute("aria-expanded", "true");
    },
  );

  it("refreshes nested expanded directories without losing expansion", async () => {
    let updated = false;
    mocks.listDirectory.mockImplementation(async (path: string) => {
      if (!path) return page([entry("folder", "directory")]);
      if (path === "folder")
        return page([
          entry("folder/nested", "directory"),
          entry(updated ? "folder/after.txt" : "folder/before.txt"),
        ]);
      return page([
        entry(updated ? "folder/nested/new.txt" : "folder/nested/old.txt"),
      ]);
    });
    renderNavigator();
    fireEvent.click(await screen.findByRole("treeitem", { name: "folder" }));
    fireEvent.click(await screen.findByRole("treeitem", { name: "nested" }));
    await screen.findByText("old.txt");
    updated = true;
    refresh();
    await screen.findByText("after.txt");
    await screen.findByText("new.txt");
    expect(screen.queryByText("before.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("old.txt")).not.toBeInTheDocument();
    for (const name of ["folder", "nested"]) {
      expect(screen.getByRole("treeitem", { name })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    }
  });

  it("invalidates collapsed directories without eagerly fetching them", async () => {
    let updated = false;
    mocks.listDirectory.mockImplementation(async (path: string) =>
      !path
        ? page([entry("folder", "directory")])
        : page([entry(updated ? "folder/after.txt" : "folder/before.txt")]),
    );
    renderNavigator();
    const folder = await screen.findByRole("treeitem", {
      name: "folder",
    });
    fireEvent.click(folder);
    await screen.findByText("before.txt");
    fireEvent.click(folder);
    updated = true;
    mocks.listDirectory.mockClear();
    refresh();
    await waitFor(() =>
      expect(screen.getByRole("tree")).toHaveAttribute("aria-busy", "false"),
    );
    expect(mocks.listDirectory.mock.calls.every(([path]) => path === "")).toBe(
      true,
    );
    fireEvent.click(folder);
    await screen.findByText("after.txt");
  });

  it("rebuilds loaded root and child pages with fresh cursors", async () => {
    let updated = false;
    mocks.listDirectory.mockImplementation(
      async (path: string, cursor?: string) => {
        if (!path)
          return cursor
            ? page([entry("folder", "directory")])
            : page([entry("root.txt")], updated ? "new-root" : "old-root");
        return cursor
          ? page([entry(updated ? "folder/after.txt" : "folder/before.txt")])
          : page(
              [entry("folder/first.txt")],
              updated ? "new-child" : "old-child",
            );
      },
    );
    renderNavigator();
    fireEvent.click(
      await screen.findByRole("button", { name: "files.loadMore" }),
    );
    fireEvent.click(await screen.findByRole("treeitem", { name: "folder" }));
    await screen.findByText("first.txt");
    fireEvent.click(screen.getByRole("button", { name: "files.loadMore" }));
    await screen.findByText("before.txt");
    updated = true;
    mocks.listDirectory.mockClear();
    refresh();
    await screen.findByText("after.txt");
    expect(screen.getByRole("treeitem", { name: "folder" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(mocks.listDirectory).toHaveBeenCalledWith(
      "",
      "new-root",
      200,
      undefined,
      "project",
      undefined,
    );
    expect(mocks.listDirectory).toHaveBeenCalledWith(
      "folder",
      "new-child",
      200,
      undefined,
      "project",
      undefined,
    );
    expect(
      screen.queryByRole("button", { name: "files.loadMore" }),
    ).not.toBeInTheDocument();
  });

  it.each(["", "folder"])(
    "ignores stale pagination responses for %s",
    async (directory) => {
      const old = deferred<DirectoryPage>();
      let updated = false;
      mocks.listDirectory.mockImplementation(
        async (path: string, cursor?: string) => {
          if (path === directory) {
            if (cursor) return old.promise;
            return page(
              [
                entry(
                  `${path ? `${path}/` : ""}${
                    updated ? "fresh.txt" : "before.txt"
                  }`,
                ),
              ],
              updated ? null : "old-cursor",
            );
          }
          return page([entry("folder", "directory")]);
        },
      );
      renderNavigator();
      if (directory)
        fireEvent.click(
          await screen.findByRole("treeitem", { name: "folder" }),
        );
      await screen.findByText("before.txt");
      fireEvent.click(screen.getByRole("button", { name: "files.loadMore" }));
      updated = true;
      refresh();
      await screen.findByText("fresh.txt");
      await act(async () =>
        old.resolve(page([entry("stale.txt")], "stale-cursor")),
      );
      expect(screen.queryByText("stale.txt")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "files.loadMore" }),
      ).not.toBeInTheDocument();
    },
  );

  it("restores nested expansion after a parent is collapsed and reopened", async () => {
    mocks.listDirectory.mockImplementation(async (path: string) =>
      page([
        !path
          ? entry("folder", "directory")
          : path === "folder"
          ? entry("folder/nested", "directory")
          : entry("folder/nested/before.txt"),
      ]),
    );
    renderNavigator();
    const folder = await screen.findByRole("treeitem", {
      name: "folder",
    });
    fireEvent.click(folder);
    fireEvent.click(await screen.findByRole("treeitem", { name: "nested" }));
    await screen.findByText("before.txt");
    fireEvent.click(folder);
    refresh();
    fireEvent.click(folder);
    await screen.findByText("before.txt");
    expect(screen.getByRole("treeitem", { name: "nested" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("exposes a roving ARIA tree and supports tree-view keyboard navigation", async () => {
    const onSelect = vi.fn();
    mocks.listDirectory.mockImplementation(async (path: string) => {
      if (!path)
        return page([entry("folder", "directory"), entry("sibling.txt")]);
      if (path === "folder")
        return page([
          entry("folder/child.txt"),
          entry("folder/nested", "directory"),
        ]);
      return page([entry("folder/nested/deep.txt")]);
    });
    renderNavigator({ onSelect, selectedPath: "sibling.txt" });

    const folder = await screen.findByRole("treeitem", { name: "folder" });
    const sibling = screen.getByRole("treeitem", { name: "sibling.txt" });
    expect(folder).toHaveAttribute("aria-level", "1");
    expect(folder).toHaveAttribute("aria-expanded", "false");
    expect(folder).toHaveAttribute("aria-selected", "false");
    expect(folder).toHaveAttribute("tabindex", "0");
    expect(sibling).toHaveAttribute("aria-level", "1");
    expect(sibling).not.toHaveAttribute("aria-expanded");
    expect(sibling).toHaveAttribute("aria-selected", "true");
    expect(sibling).toHaveAttribute("tabindex", "-1");

    act(() => folder.focus());
    fireEvent.keyDown(folder, { key: "ArrowRight" });
    const child = await screen.findByRole("treeitem", { name: "child.txt" });
    const nested = screen.getByRole("treeitem", { name: "nested" });
    expect(folder).toHaveAttribute("aria-expanded", "true");
    expect(child).toHaveAttribute("aria-level", "2");
    expect(folder).toHaveFocus();

    fireEvent.keyDown(folder, { key: "ArrowRight" });
    expect(child).toHaveFocus();
    fireEvent.keyDown(child, { key: "ArrowDown" });
    expect(nested).toHaveFocus();
    fireEvent.keyDown(nested, { key: "ArrowRight" });
    const deep = await screen.findByRole("treeitem", { name: "deep.txt" });
    fireEvent.keyDown(nested, { key: "ArrowRight" });
    expect(deep).toHaveFocus();
    fireEvent.keyDown(deep, { key: "ArrowLeft" });
    expect(nested).toHaveFocus();
    fireEvent.keyDown(nested, { key: "ArrowLeft" });
    expect(nested).toHaveAttribute("aria-expanded", "false");
    expect(nested).toHaveFocus();
    fireEvent.keyDown(nested, { key: "ArrowLeft" });
    expect(folder).toHaveFocus();

    fireEvent.keyDown(folder, { key: "End" });
    expect(sibling).toHaveFocus();
    fireEvent.keyDown(sibling, { key: "Home" });
    expect(folder).toHaveFocus();
    fireEvent.keyDown(folder, { key: "ArrowDown" });
    expect(child).toHaveFocus();
    fireEvent.keyDown(child, { key: "ArrowUp" });
    expect(folder).toHaveFocus();

    fireEvent.keyDown(folder, { key: "Enter" });
    expect(folder).toHaveAttribute("aria-expanded", "false");
    act(() => sibling.focus());
    fireEvent.keyDown(sibling, { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith({
      source: "workspace",
      path: "sibling.txt",
      root: "project",
    });
  });

  it("keeps exactly one tree item tabbable for a 72-node fixture", async () => {
    mocks.listDirectory.mockResolvedValue(
      page(
        Array.from({ length: 72 }, (_, index) =>
          entry(`file-${String(index).padStart(2, "0")}.txt`),
        ),
      ),
    );
    renderNavigator();

    const items = await screen.findAllByRole("treeitem");
    expect(items).toHaveLength(72);
    expect(items.filter((item) => item.tabIndex === 0)).toHaveLength(1);
    expect(items.filter((item) => item.tabIndex === -1)).toHaveLength(71);
  });

  it("isolates unchanged workspace leaves across refresh renders", async () => {
    let modified = false;
    mocks.listDirectory.mockImplementation(async () =>
      page([
        entry("stable.txt"),
        {
          ...entry("changed.txt"),
          modified_at: modified
            ? "2026-10-10T00:00:00Z"
            : "2026-10-09T00:00:00Z",
        },
      ]),
    );
    renderNavigator();
    await screen.findByRole("treeitem", { name: "stable.txt" });
    await waitFor(() =>
      expect(screen.getByRole("tree")).toHaveAttribute("aria-busy", "false"),
    );
    mocks.fileGlyphRender.mockClear();
    modified = true;

    refresh();
    await waitFor(() => expect(mocks.listDirectory).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByRole("tree")).toHaveAttribute("aria-busy", "false"),
    );

    expect(mocks.fileGlyphRender.mock.calls).toEqual([["changed.txt"]]);
  });

  it("restores a tab stop when a focused nested file disappears", async () => {
    let updated = false;
    mocks.listDirectory.mockImplementation(async (path: string) =>
      !path
        ? page([entry("folder", "directory")])
        : page([entry(updated ? "folder/after.txt" : "folder/before.txt")]),
    );
    renderNavigator();

    const folder = await screen.findByRole("treeitem", { name: "folder" });
    fireEvent.click(folder);
    const before = await screen.findByRole("treeitem", {
      name: "before.txt",
    });
    act(() => before.focus());
    expect(before).toHaveAttribute("tabindex", "0");

    updated = true;
    refresh();
    await screen.findByRole("treeitem", { name: "after.txt" });
    expect(screen.queryByRole("treeitem", { name: "before.txt" })).toBeNull();
    const items = screen.getAllByRole("treeitem");
    expect(items.filter((item) => item.tabIndex === 0)).toHaveLength(1);
    expect(items.filter((item) => item.tabIndex === -1)).toHaveLength(
      items.length - 1,
    );
  });

  it("shows upload only in the workspace tab", async () => {
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);

    renderNavigator();
    expect(
      await screen.findByRole("button", { name: "Upload" }),
    ).toBeInTheDocument();

    for (const tab of ["Profile", "Daily", "Digest"]) {
      fireEvent.click(screen.getByRole("tab", { name: tab }));
      expect(
        screen.queryByRole("button", { name: "Upload" }),
      ).not.toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("tab", { name: "Workspace" }));
    expect(screen.getByRole("button", { name: "Upload" })).toBeInTheDocument();
  });

  it("can add a custom prompt again after disabling it", async () => {
    mocks.listFiles.mockResolvedValue([
      mdFile("AGENTS.md"),
      mdFile("custom.md"),
      mdFile("notes.md"),
    ]);
    mocks.getSystemPromptFiles.mockResolvedValue(["AGENTS.md", "custom.md"]);

    renderNavigator();
    await openProfile();

    fireEvent.click(
      await screen.findByRole("switch", { name: "Toggle custom.md" }),
    );
    await waitFor(() =>
      expect(mocks.setSystemPromptFiles).toHaveBeenCalledWith(["AGENTS.md"]),
    );
    await waitFor(() =>
      expect(screen.queryByText("custom.md")).not.toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Add from workspace" }));
    fireEvent.click(await screen.findByRole("button", { name: /custom\.md/ }));

    await waitFor(() =>
      expect(mocks.setSystemPromptFiles).toHaveBeenLastCalledWith([
        "AGENTS.md",
        "custom.md",
      ]),
    );
    expect(
      await screen.findByRole("switch", { name: "Toggle custom.md" }),
    ).toBeInTheDocument();
  });
});
