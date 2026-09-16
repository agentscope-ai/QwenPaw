import { renderWithProviders } from "@/test/common_setup";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import WorkbenchShell from "./WorkbenchShell";
import {
  readStoredWorkbenchLayout,
  storeWorkbenchLayout,
  workbenchLayoutStorageKey,
} from "./workbenchPreferences";

const mocks = vi.hoisted(() => ({
  codingMode: true,
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: mocks.codingMode }),
}));

vi.mock("../files-workspace/FilesWorkspace", () => ({
  default: ({
    initialTarget,
    workspaceOnly,
  }: {
    initialTarget?: { path: string };
    workspaceOnly?: boolean;
  }) => (
    <div
      data-testid="files-capability"
      data-workspace-only={String(workspaceOnly)}
    >
      {initialTarget?.path}
    </div>
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

const layoutKey = workbenchLayoutStorageKey("default", "session-1");

describe("WorkbenchShell", () => {
  afterEach(() => {
    localStorage.clear();
    mocks.codingMode = true;
  });

  it("starts empty without rendering a capability", () => {
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    expect(screen.queryByTestId("files-capability")).not.toBeInTheDocument();
    expect(screen.queryByTestId("changes-capability")).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "workbench.addPanel" }),
    ).not.toHaveLength(0);
  });

  it("adds and activates a capability from the launcher", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    await user.click(
      screen.getAllByRole("button", { name: "workbench.addPanel" })[0],
    );
    await user.click(await screen.findByText("workbench.files"));

    expect(await screen.findByTestId("files-capability")).toBeInTheDocument();
    expect(screen.getByTestId("files-capability")).toHaveAttribute(
      "data-workspace-only",
      "true",
    );
    expect(readStoredWorkbenchLayout(layoutKey)).toEqual({
      openTabs: ["files"],
      activeTab: "files",
    });
  });

  it("restores open tabs and the active capability for the session", async () => {
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["files", "tools"],
      activeTab: "tools",
    });
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: "workbench.tools" }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.queryByTestId("files-capability")).not.toBeInTheDocument();
  });

  it("opens a selected resource in Files", async () => {
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["tools"],
      activeTab: "tools",
    });
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
    expect(
      screen.getByRole("button", { name: "workbench.files" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("closes one panel without closing the Workbench", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["files", "tools"],
      activeTab: "files",
    });
    renderWithProviders(<WorkbenchShell scope={scope} onClose={onClose} />);

    await user.click(
      screen.getAllByRole("button", { name: "workbench.closePanel" })[0],
    );

    expect(onClose).not.toHaveBeenCalled();
    expect(readStoredWorkbenchLayout(layoutKey)).toEqual({
      openTabs: ["tools"],
      activeTab: "tools",
    });
  });

  it("restores a different layout when the session changes", async () => {
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["tools"],
      activeTab: "tools",
    });
    storeWorkbenchLayout(workbenchLayoutStorageKey("default", "session-2"), {
      openTabs: ["terminal"],
      activeTab: "terminal",
    });
    const { rerender } = renderWithProviders(
      <WorkbenchShell scope={scope} onClose={vi.fn()} />,
    );

    rerender(
      <WorkbenchShell
        scope={{ ...scope, sessionId: "session-2" }}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "workbench.terminal" }),
      ).toHaveAttribute("aria-current", "page");
    });
  });

  it("removes Changes when Coding Mode becomes unavailable", async () => {
    mocks.codingMode = false;
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["changes"],
      activeTab: "changes",
    });
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(readStoredWorkbenchLayout(layoutKey)).toEqual({
        openTabs: [],
        activeTab: null,
      });
    });
    expect(screen.queryByTestId("changes-capability")).not.toBeInTheDocument();
  });

  it("closes the complete Workbench from the header", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchShell scope={scope} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "common.close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
