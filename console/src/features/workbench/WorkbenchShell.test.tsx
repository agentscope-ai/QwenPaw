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
  tabs: [] as Array<{
    path: string;
    displayPath?: string;
    content: string;
    dirty: boolean;
  }>,
  activeFilePath: "",
  diffs: {} as Record<string, unknown>,
  closeTab: vi.fn(),
  setActiveFile: vi.fn(),
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: mocks.codingMode }),
}));

vi.mock("../../stores/codingTabsStore", () => ({
  useTabsForScope: () => mocks.tabs,
  useActiveTabPathForScope: () => mocks.activeFilePath,
  useDiffsForScope: () => mocks.diffs,
  useCodingTabsStore: () => ({
    closeTab: mocks.closeTab,
    setActiveTab: mocks.setActiveFile,
  }),
}));

vi.mock("../files-workspace/FilesWorkspace", () => ({
  default: ({
    initialTarget,
    navigatorOpen,
    onFileActivated,
    showBreadcrumbs,
    showEditorTabs,
    toolbarTrailing,
    workspaceOnly,
  }: {
    initialTarget?: { path: string };
    navigatorOpen?: boolean;
    onFileActivated?: (path: string) => void;
    showBreadcrumbs?: boolean;
    showEditorTabs?: boolean;
    toolbarTrailing?: React.ReactNode;
    workspaceOnly?: boolean;
  }) => (
    <div
      data-testid="files-capability"
      data-navigator-open={String(navigatorOpen)}
      data-show-breadcrumbs={String(showBreadcrumbs)}
      data-show-editor-tabs={String(showEditorTabs)}
      data-workspace-only={String(workspaceOnly)}
    >
      {initialTarget?.path}
      <button type="button" onClick={() => onFileActivated?.("src/app.ts")}>
        activate-file
      </button>
      {toolbarTrailing}
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
    mocks.tabs = [];
    mocks.activeFilePath = "";
    mocks.diffs = {};
    mocks.closeTab.mockReset();
    mocks.setActiveFile.mockReset();
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
      fileTreeOpen: true,
    });
    expect(screen.getByTestId("files-capability")).toHaveAttribute(
      "data-show-editor-tabs",
      "false",
    );
    expect(screen.getByTestId("files-capability")).toHaveAttribute(
      "data-show-breadcrumbs",
      "true",
    );
  });

  it("restores open tabs and the active capability for the session", async () => {
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["files", "tools"],
      activeTab: "tools",
      fileTreeOpen: false,
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
      fileTreeOpen: false,
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
    expect(screen.getByTestId("files-capability")).toHaveAttribute(
      "data-navigator-open",
      "false",
    );
  });

  it("closes one panel without closing the Workbench", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["files", "tools"],
      activeTab: "files",
      fileTreeOpen: false,
    });
    renderWithProviders(<WorkbenchShell scope={scope} onClose={onClose} />);

    await user.click(
      screen.getAllByRole("button", { name: "workbench.closePanel" })[0],
    );

    expect(onClose).not.toHaveBeenCalled();
    expect(readStoredWorkbenchLayout(layoutKey)).toEqual({
      openTabs: ["files"],
      activeTab: "files",
      fileTreeOpen: false,
    });
  });

  it("restores a different layout when the session changes", async () => {
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["tools"],
      activeTab: "tools",
      fileTreeOpen: false,
    });
    storeWorkbenchLayout(workbenchLayoutStorageKey("default", "session-2"), {
      openTabs: ["terminal"],
      activeTab: "terminal",
      fileTreeOpen: false,
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
      fileTreeOpen: false,
    });
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(readStoredWorkbenchLayout(layoutKey)).toEqual({
        openTabs: [],
        activeTab: null,
        fileTreeOpen: false,
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

  it("renders restored files as top-level resource tabs", async () => {
    mocks.tabs = [
      {
        path: "src/app.ts",
        displayPath: "src/app.ts",
        content: "",
        dirty: true,
      },
    ];
    mocks.activeFilePath = "src/app.ts";
    storeWorkbenchLayout(layoutKey, {
      openTabs: ["files", "changes"],
      activeTab: "file:src/app.ts",
      fileTreeOpen: false,
    });

    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "app.ts" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByTestId("files-capability")).toBeInTheDocument();
    expect(screen.getByTestId("files-capability")).toHaveAttribute(
      "data-show-editor-tabs",
      "false",
    );
  });

  it("opens the file tree on the right only when requested", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkbenchShell scope={scope} onClose={vi.fn()} />);

    const launcherTreeButton = screen.getByRole("button", {
      name: "files.navigator",
    });
    await user.click(launcherTreeButton);

    expect(await screen.findByTestId("files-capability")).toHaveAttribute(
      "data-navigator-open",
      "true",
    );
    expect(
      screen
        .getByRole("button", { name: "files.navigator" })
        .closest('[data-testid="files-capability"]'),
    ).not.toBeNull();
    expect(readStoredWorkbenchLayout(layoutKey)).toEqual({
      openTabs: ["files"],
      activeTab: "files",
      fileTreeOpen: true,
    });
  });
});
