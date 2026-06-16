import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { WorkspaceProtectableFilePickerModal } from "./WorkspaceProtectableFilePickerModal";

const mockBrowse = vi.fn();

vi.mock("../api/client", () => ({
  fileBaselineApi: {
    browseWorkspaceProtectableFiles: (...args: unknown[]) => mockBrowse(...args),
  },
}));

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Button: antd.Button,
    Modal: antd.Modal,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("WorkspaceProtectableFilePickerModal", () => {
  beforeEach(() => {
    mockBrowse.mockResolvedValue({
      agent_id: "default",
      workspace_label: "default",
      current_path: "skills",
      parent_path: "",
      default_path: "skills",
      entries: [
        {
          name: "weather",
          type: "dir",
          rel_path: "skills/weather",
        },
      ],
    });
  });

  it("opens on skills directory when shown", async () => {
    renderWithProviders(
      <WorkspaceProtectableFilePickerModal
        open
        protectedPaths={["SOUL.md"]}
        onClose={() => undefined}
        onAdd={async () => undefined}
      />,
    );

    await waitFor(() => {
      expect(mockBrowse).toHaveBeenCalledWith("skills");
    });

    expect(
      screen.getByText("security.integrityProtection.workspacePickerTitle"),
    ).toBeInTheDocument();
    expect(screen.getByText("weather")).toBeInTheDocument();
  });
});
