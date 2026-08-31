import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilesNavigator from "./FilesNavigator";

const mocks = vi.hoisted(() => ({
  getProjectDirectory: vi.fn(),
  getSystemPromptFiles: vi.fn(),
  listDirectory: vi.fn(),
  listFiles: vi.fn(),
  setSystemPromptFiles: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { name?: string }) => {
      const labels: Record<string, string> = {
        "files.profile": "Profile",
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
    mocks.setSystemPromptFiles.mockImplementation(async (files) => files);
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
