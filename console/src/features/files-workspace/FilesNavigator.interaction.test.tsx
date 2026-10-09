import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesNavigator from "./FilesNavigator";
import type { DirectoryEntry, DirectoryPage } from "./types";

const mocks = vi.hoisted(() => ({
  getProjectDirectory: vi.fn(),
  getSystemPromptFiles: vi.fn(),
  listDirectory: vi.fn(),
  listFiles: vi.fn(),
  listMemoryFiles: vi.fn(),
  setSystemPromptFiles: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) => {
      const labels: Record<string, string> = {
        "files.workspace": "Workspace",
        "files.profile": "Profile",
        "files.daily": "Daily",
        "files.digest": "Digest",
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

const mdFile = (filename: string) => ({
  filename,
  size: 10,
  created_time: "2026-01-01T00:00:00Z",
  modified_time: "2026-01-01T00:00:00Z",
});

function renderNavigator() {
  return render(
    <FilesNavigator
      selectedPath=""
      onSelect={vi.fn()}
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
  });

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
    fireEvent.click(await screen.findByRole("button", { name: "folder" }));
    fireEvent.click(await screen.findByRole("button", { name: "nested" }));
    await screen.findByText("old.txt");
    updated = true;
    refresh();
    await screen.findByText("after.txt");
    await screen.findByText("new.txt");
    expect(screen.queryByText("before.txt")).not.toBeInTheDocument();
    expect(screen.queryByText("old.txt")).not.toBeInTheDocument();
    for (const name of ["folder", "nested"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute(
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
    const folder = await screen.findByRole("button", {
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
    fireEvent.click(await screen.findByRole("button", { name: "folder" }));
    await screen.findByText("first.txt");
    fireEvent.click(screen.getByRole("button", { name: "files.loadMore" }));
    await screen.findByText("before.txt");
    updated = true;
    mocks.listDirectory.mockClear();
    refresh();
    await screen.findByText("after.txt");
    expect(screen.getByRole("button", { name: "folder" })).toHaveAttribute(
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
        fireEvent.click(await screen.findByRole("button", { name: "folder" }));
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
    const folder = await screen.findByRole("button", {
      name: "folder",
    });
    fireEvent.click(folder);
    fireEvent.click(await screen.findByRole("button", { name: "nested" }));
    await screen.findByText("before.txt");
    fireEvent.click(folder);
    refresh();
    fireEvent.click(folder);
    await screen.findByText("before.txt");
    expect(screen.getByRole("button", { name: "nested" })).toHaveAttribute(
      "aria-expanded",
      "true",
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
