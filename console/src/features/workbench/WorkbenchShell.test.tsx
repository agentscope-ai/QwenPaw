import { renderWithProviders } from "@/test/common_setup";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import WorkbenchShell from "./WorkbenchShell";

const mocks = vi.hoisted(() => ({
  codingMode: true,
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: mocks.codingMode }),
}));

vi.mock("../files-workspace/FilesWorkspace", () => ({
  default: ({ initialTarget }: { initialTarget?: { path: string } }) => (
    <div data-testid="files-capability">{initialTarget?.path}</div>
  ),
}));

vi.mock("../../pages/Coding/GitPanel", () => ({
  default: () => <div data-testid="changes-capability" />,
}));

const scope = {
  kind: "session" as const,
  agentId: "default",
  sessionId: "session-1",
};

describe("WorkbenchShell", () => {
  afterEach(() => {
    localStorage.clear();
    mocks.codingMode = true;
  });

  it("restores the active capability within the current session", async () => {
    localStorage.setItem("qwenpaw-workbench-tab:default:session-1", "tools");
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: /tools|工具/i })).toHaveAttribute(
      "aria-current",
      "page",
    );

    await user.click(screen.getByRole("button", { name: /terminal|终端/i }));
    expect(
      localStorage.getItem("qwenpaw-workbench-tab:default:session-1"),
    ).toBe("terminal");
  });

  it("opens a selected resource in Files regardless of the stored tab", async () => {
    localStorage.setItem("qwenpaw-workbench-tab:default:session-1", "tools");
    renderWithProviders(
      <WorkbenchShell
        initialTarget={{ source: "workspace", path: "src/app.ts" }}
        scope={scope}
        onClose={vi.fn()}
      />,
    );

    expect(await screen.findByTestId("files-capability")).toHaveTextContent(
      "src/app.ts",
    );
    expect(screen.getByRole("button", { name: /files|文件/i })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("restores a different active capability when the session changes", async () => {
    localStorage.setItem("qwenpaw-workbench-tab:default:session-1", "tools");
    localStorage.setItem("qwenpaw-workbench-tab:default:session-2", "terminal");
    const { rerender } = renderWithProviders(
      <WorkbenchShell scope={scope} onClose={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: /tools|工具/i })).toHaveAttribute(
      "aria-current",
      "page",
    );

    rerender(
      <WorkbenchShell
        scope={{ ...scope, sessionId: "session-2" }}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /terminal|终端/i }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("does not expose repository changes outside Coding Mode", async () => {
    mocks.codingMode = false;
    localStorage.setItem("qwenpaw-workbench-tab:default:session-1", "changes");
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: /changes|变更/i }),
    ).toBeDisabled();
    expect(await screen.findByTestId("files-capability")).toBeInTheDocument();
    expect(screen.queryByTestId("changes-capability")).not.toBeInTheDocument();
  });

  it("does not open Changes against the wrong directory before chat creation", () => {
    renderWithProviders(
      <WorkbenchShell
        scope={{ ...scope, projectDirOverride: "/tmp/pending-project" }}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /changes|变更/i }),
    ).toBeDisabled();
  });

  it("closes from the shell header", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchShell scope={scope} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: /close|关闭/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
