import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import { invoke, isTauri } from "@/test/tauri-mock";

import { OpenWorkspaceButton } from "./OpenWorkspaceButton";

const mocks = vi.hoisted(() => ({
  messageError: vi.fn(),
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { error: mocks.messageError },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@agentscope-ai/design", () => ({
  Button: (
    props: React.ButtonHTMLAttributes<HTMLButtonElement> & {
      icon?: React.ReactNode;
      loading?: boolean;
    },
  ) => {
    const buttonProps = { ...props };
    const { children, icon } = buttonProps;
    delete buttonProps.loading;
    delete buttonProps.icon;
    delete buttonProps.children;
    return (
      <button {...buttonProps}>
        {icon}
        {children}
      </button>
    );
  },
}));

describe("OpenWorkspaceButton", () => {
  beforeEach(() => {
    isTauri.mockReturnValue(true);
    invoke.mockReset();
    invoke.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
    delete (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  });

  it("opens the current workspace through the Tauri command", async () => {
    const user = userEvent.setup();
    const workspacePath = "C:\\Users\\tester\\.qwenpaw\\workspaces\\default";
    renderWithProviders(<OpenWorkspaceButton workspacePath={workspacePath} />);

    await user.click(
      screen.getByRole("button", {
        name: "workspace.openInFileManager",
      }),
    );

    expect(invoke).toHaveBeenCalledWith("open_workspace_directory", {
      path: workspacePath,
    });
  });

  it("stays hidden outside the Tauri desktop runtime", () => {
    isTauri.mockReturnValue(false);

    renderWithProviders(<OpenWorkspaceButton workspacePath="C:\\workspace" />);

    expect(
      screen.queryByRole("button", {
        name: "workspace.openInFileManager",
      }),
    ).not.toBeInTheDocument();
  });

  it("is disabled until the workspace path is available", () => {
    renderWithProviders(<OpenWorkspaceButton workspacePath={null} />);

    expect(
      screen.getByRole("button", {
        name: "workspace.openInFileManager",
      }),
    ).toBeDisabled();
  });

  it("reports command failures and restores the button", async () => {
    const user = userEvent.setup();
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    invoke.mockRejectedValue(new Error("permission denied"));
    renderWithProviders(<OpenWorkspaceButton workspacePath="C:\\workspace" />);

    const button = screen.getByRole("button", {
      name: "workspace.openInFileManager",
    });
    await user.click(button);

    await waitFor(() => {
      expect(mocks.messageError).toHaveBeenCalledWith("workspace.openFailed");
    });
    expect(button).not.toBeDisabled();
    expect(warnSpy).toHaveBeenCalledOnce();
  });

  it("ignores repeated clicks while the command is pending", async () => {
    const user = userEvent.setup();
    let resolveInvoke: (() => void) | undefined;
    invoke.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveInvoke = resolve;
        }),
    );
    renderWithProviders(<OpenWorkspaceButton workspacePath="C:\\workspace" />);

    const button = screen.getByRole("button", {
      name: "workspace.openInFileManager",
    });
    await user.dblClick(button);

    expect(invoke).toHaveBeenCalledOnce();
    resolveInvoke?.();
    await waitFor(() => expect(button).not.toBeDisabled());
  });
});
