import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { invoke, isTauri } from "@/test/tauri-mock";
import WorkspaceOpenButton from "./index";

const mocks = vi.hoisted(() => ({
  messageError: vi.fn(),
  storeState: {
    selectedAgent: "default",
    agents: [
      {
        id: "default",
        name: "Default",
        description: "",
        workspace_dir: "C:\\Users\\tester\\.qwenpaw\\workspaces\\default",
        enabled: true,
      },
    ],
  },
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: mocks.messageError },
  }),
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: () => mocks.storeState,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("WorkspaceOpenButton", () => {
  beforeEach(() => {
    isTauri.mockReturnValue(true);
    invoke.mockReset();
    invoke.mockResolvedValue(undefined);
    mocks.storeState.selectedAgent = "default";
    mocks.storeState.agents[0].workspace_dir =
      "C:\\Users\\tester\\.qwenpaw\\workspaces\\default";
  });

  afterEach(() => {
    vi.clearAllMocks();
    delete (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  });

  it("opens the selected agent workspace through Tauri", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkspaceOpenButton />);

    await user.click(screen.getByRole("button", { name: "nav.workspace" }));

    expect(invoke).toHaveBeenCalledWith("open_workspace_directory", {
      path: "C:\\Users\\tester\\.qwenpaw\\workspaces\\default",
    });
  });

  it("stays hidden in the browser console", () => {
    isTauri.mockReturnValue(false);

    renderWithProviders(<WorkspaceOpenButton />);

    expect(
      screen.queryByRole("button", { name: "nav.workspace" }),
    ).not.toBeInTheDocument();
  });

  it("disables the action when the selected agent has no workspace", () => {
    mocks.storeState.agents[0].workspace_dir = "";

    renderWithProviders(<WorkspaceOpenButton />);

    expect(
      screen.getByRole("button", { name: "nav.workspace" }),
    ).toBeDisabled();
  });

  it("reports a native command failure without throwing", async () => {
    const user = userEvent.setup();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    invoke.mockRejectedValue(new Error("permission denied"));
    renderWithProviders(<WorkspaceOpenButton />);

    await user.click(screen.getByRole("button", { name: "nav.workspace" }));

    await waitFor(() => {
      expect(mocks.messageError).toHaveBeenCalledWith("common.operationFailed");
    });
    expect(warnSpy).toHaveBeenCalled();
  });
});
