import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesNavigator from "./FilesNavigator";

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
        "common.refresh": "Refresh",
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

describe("FilesNavigator system prompt interactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    mocks.setSystemPromptFiles.mockImplementation(async (files) => files);
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

  it("refreshes expanded nested folders without collapsing them", async () => {
    let includeNewFile = false;
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.listDirectory.mockImplementation(async (path: string) => ({
      entries:
        path === ""
          ? [{ name: "parent", path: "parent", kind: "directory" }]
          : path === "parent"
          ? [{ name: "nested", path: "parent/nested", kind: "directory" }]
          : [
              {
                name: "before.txt",
                path: "parent/nested/before.txt",
                kind: "file",
              },
              ...(includeNewFile
                ? [
                    {
                      name: "after.txt",
                      path: "parent/nested/after.txt",
                      kind: "file",
                    },
                  ]
                : []),
            ],
      next_cursor: null,
      has_more: false,
    }));

    renderNavigator();
    fireEvent.click(await screen.findByRole("button", { name: "parent" }));
    fireEvent.click(await screen.findByRole("button", { name: "nested" }));
    expect(await screen.findByText("before.txt")).toBeInTheDocument();

    includeNewFile = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("after.txt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "parent" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("button", { name: "nested" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("ignores a stale folder response after refresh", async () => {
    let resolveInitial: ((page: unknown) => void) | undefined;
    let folderRequests = 0;
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.listDirectory.mockImplementation((path: string) => {
      if (path === "") {
        return Promise.resolve({
          entries: [{ name: "folder", path: "folder", kind: "directory" }],
          next_cursor: null,
          has_more: false,
        });
      }
      folderRequests += 1;
      if (folderRequests === 1) {
        return new Promise((resolve) => {
          resolveInitial = resolve;
        });
      }
      return Promise.resolve({
        entries: [{ name: "new.txt", path: "folder/new.txt", kind: "file" }],
        next_cursor: null,
        has_more: false,
      });
    });

    renderNavigator();
    fireEvent.click(await screen.findByRole("button", { name: "folder" }));
    await waitFor(() => expect(folderRequests).toBe(1));

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("new.txt")).toBeInTheDocument();

    await act(async () => {
      resolveInitial?.({
        entries: [{ name: "old.txt", path: "folder/old.txt", kind: "file" }],
        next_cursor: null,
        has_more: false,
      });
    });
    expect(screen.getByText("new.txt")).toBeInTheDocument();
    expect(screen.queryByText("old.txt")).not.toBeInTheDocument();
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
