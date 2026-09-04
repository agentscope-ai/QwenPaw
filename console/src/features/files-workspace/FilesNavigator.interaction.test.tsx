import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesNavigator from "./FilesNavigator";

const mocks = vi.hoisted(() => ({
  getProjectDirectory: vi.fn(),
  getSystemPromptFiles: vi.fn(),
  listDirectory: vi.fn(),
  listFiles: vi.fn(),
  listMemoryFiles: vi.fn(),
  setSystemPromptFiles: vi.fn(),
  uploadFiles: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) => {
      const labels: Record<string, string> = {
        "files.profile": "Profile",
        "files.daily": "Daily",
        "files.digest": "Knowledge Base",
        "files.agentSourceNotice":
          "The Agent normally reads only Markdown (.md) files here.",
        "files.addSystemPrompt": "Add from workspace",
        "files.addSystemPromptTitle": "Add a system prompt file",
        "files.addSystemPromptDescription": "Choose a file",
        "files.searchSystemPromptFiles": "Search files",
        "files.noSystemPromptCandidates": "No files",
        "files.sourceEmpty": "No files",
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
    uploadFiles: mocks.uploadFiles,
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
    mocks.setSystemPromptFiles.mockImplementation(async (files) => files);
    mocks.listMemoryFiles.mockResolvedValue([]);
    mocks.uploadFiles.mockResolvedValue({ files: [] });
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

  it("shows unselected Markdown files in the Agent profile source", async () => {
    mocks.listFiles.mockResolvedValue([mdFile("custom.md")]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.listDirectory.mockImplementation((path: string) =>
      Promise.resolve({
        entries:
          path === ""
            ? [
                {
                  name: "custom.md",
                  path: "custom.md",
                  kind: "file",
                  size: 10,
                  modified_at: "2026-01-01T00:00:00Z",
                  preview_kind: "text",
                },
              ]
            : [],
        next_cursor: null,
        has_more: false,
      }),
    );

    renderNavigator();
    await openProfile();

    expect(await screen.findByText("custom.md")).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: "Toggle custom.md" }),
    ).not.toBeInTheDocument();
  });

  it("does not show configuration subdirectories in the Agent profile source", async () => {
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.listDirectory.mockImplementation((path: string) =>
      Promise.resolve({
        entries:
          path === ""
            ? [
                {
                  name: "memory",
                  path: "memory",
                  kind: "directory",
                  size: null,
                  modified_at: "2026-01-01T00:00:00Z",
                  preview_kind: "directory",
                },
              ]
            : [],
        next_cursor: null,
        has_more: false,
      }),
    );

    renderNavigator();
    await openProfile();

    await waitFor(() =>
      expect(screen.queryByText("memory")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("No files")).toBeInTheDocument();
  });

  it("uploads a default-root daily file into the Agent memory directory", async () => {
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    const { container } = renderNavigator();
    fireEvent.click(await screen.findByRole("tab", { name: "Daily" }));
    const input =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["daily"], "2026-08-26.md", {
      type: "text/markdown",
    });

    fireEvent.change(input!, { target: { files: [file] } });

    await waitFor(() =>
      expect(mocks.uploadFiles).toHaveBeenCalledWith(
        [file],
        "memory",
        undefined,
        undefined,
        "workspace",
        undefined,
        true,
      ),
    );
  });

  it("uploads a knowledge-base file into the Agent digest directory", async () => {
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    const { container } = renderNavigator();
    fireEvent.click(await screen.findByRole("tab", { name: "Knowledge Base" }));
    const input =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["knowledge"], "reference.md", {
      type: "text/markdown",
    });

    fireEvent.change(input!, { target: { files: [file] } });

    await waitFor(() =>
      expect(mocks.uploadFiles).toHaveBeenCalledWith(
        [file],
        "digest",
        undefined,
        undefined,
        "workspace",
        undefined,
        true,
      ),
    );
  });

  it("shows non-Markdown Agent knowledge-base files as unsupported", async () => {
    mocks.listFiles.mockResolvedValue([]);
    mocks.getSystemPromptFiles.mockResolvedValue([]);
    mocks.listDirectory.mockImplementation((path: string) =>
      Promise.resolve({
        entries:
          path === "digest"
            ? [
                {
                  name: "reference.pdf",
                  path: "digest/reference.pdf",
                  kind: "file",
                  size: 10,
                  modified_at: "2026-01-01T00:00:00Z",
                  preview_kind: "pdf",
                },
              ]
            : [],
        next_cursor: null,
        has_more: false,
      }),
    );

    renderNavigator();
    fireEvent.click(await screen.findByRole("tab", { name: "Knowledge Base" }));

    const file = await screen.findByText("reference.pdf");
    expect(file.closest("button")?.className).toContain("agentUnsupportedFile");
    expect(
      screen.getByText(/Markdown \(.md\) files here/i),
    ).toBeInTheDocument();
    expect(mocks.listDirectory).toHaveBeenCalledWith(
      "digest",
      undefined,
      200,
      undefined,
      "workspace",
    );
  });
});
