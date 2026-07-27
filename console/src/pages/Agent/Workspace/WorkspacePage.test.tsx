import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";

import WorkspacePage from "./index";

const mocks = vi.hoisted(() => ({
  openWorkspaceButton: vi.fn(),
}));

vi.mock("./components", () => ({
  useAgentsData: () => ({
    files: [],
    selectedFile: null,
    dailyMemories: [],
    expandedMemory: false,
    fileContent: "",
    workspacePath: "",
    hasChanges: false,
    enabledFiles: [],
    setFileContent: vi.fn(),
    fetchFiles: vi.fn(),
    handleFileClick: vi.fn(),
    handleDailyMemoryClick: vi.fn(),
    toggleExpandedMemory: vi.fn(),
    handleSave: vi.fn(),
    handleReset: vi.fn(),
    handleToggleFileEnabled: vi.fn(),
    handleReorderFiles: vi.fn(),
  }),
  FileListPanel: () => <div>file-list</div>,
  FileEditor: () => <div>file-editor</div>,
  OpenWorkspaceButton: ({
    workspacePath,
  }: {
    workspacePath: string | null;
  }) => {
    mocks.openWorkspaceButton(workspacePath);
    return <div data-testid="open-workspace-path">{workspacePath}</div>;
  },
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => ({
    selectedAgent: "default",
    agents: [
      {
        id: "default",
        workspace_dir: "C:\\Users\\tester\\.qwenpaw\\workspaces\\default",
      },
    ],
  }),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      loading: vi.fn(),
      success: vi.fn(),
      error: vi.fn(),
      destroy: vi.fn(),
    },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("WorkspacePage", () => {
  it("uses the selected agent path when the core file list is empty", () => {
    renderWithProviders(<WorkspacePage />);

    expect(screen.getByTestId("open-workspace-path")).toHaveTextContent(
      "C:\\Users\\tester\\.qwenpaw\\workspaces\\default",
    );
  });
});
