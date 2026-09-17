import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { projectDirectoryApi } from "@/api/modules/projectDirectory";
import ProjectSelectModal from ".";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../stores/projectDirectoryStore", () => ({
  useProjectDir: () => ({
    projectDir: null,
    workspaceDir: "/workspace",
    setProjectDir: vi.fn(),
  }),
}));

describe("ProjectSelectModal governance targeting", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("resets the governed agent project directory", async () => {
    const set = vi.spyOn(projectDirectoryApi, "set").mockResolvedValue({
      path: "/workspace",
      name: "workspace",
      is_workspace_default: true,
    });
    const context = {
      agentId: "governed-agent",
      governance: true,
    };

    renderWithProviders(
      <ProjectSelectModal
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        requestContext={context}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "codingMode.confirmBtn" }),
    );

    await waitFor(() => expect(set).toHaveBeenCalledWith(null, context));
  });

  it("keeps the modal state unchanged and shows the backend error when reset fails", async () => {
    vi.spyOn(projectDirectoryApi, "set").mockRejectedValue(
      new Error("project failed"),
    );
    const onConfirm = vi.fn();

    renderWithProviders(
      <ProjectSelectModal
        open
        onClose={vi.fn()}
        onConfirm={onConfirm}
        requestContext={{ agentId: "governed-agent", governance: true }}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "codingMode.confirmBtn" }),
    );

    expect(await screen.findByText("project failed")).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
