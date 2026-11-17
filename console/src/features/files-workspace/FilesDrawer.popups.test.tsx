import { renderWithProviders } from "@/test/common_setup";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatProjectDirectoryApi } from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { workspaceApi } from "../../api/modules/workspace";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import FilesDrawer from "./FilesDrawer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("./useMemoryTagSupport", () => ({
  useMemoryTagSupport: () => false,
  useMemoryFileConfig: () => ({ config: null }),
}));

vi.mock("../../pages/Coding/TabbedEditor", () => ({
  default: () => <div>editor</div>,
}));

vi.mock("../../pages/Coding/GitPanel", () => ({ default: () => null }));
vi.mock("./MemoryGraphView", () => ({ default: () => null }));

function renderWorkspaceDrawer() {
  return renderWithProviders(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <section data-testid="chat-background">
        <button type="button">Background action</button>
      </section>
      <FilesDrawer
        state={{ kind: "workspace", trigger: null }}
        dispatch={vi.fn()}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
          chatId: "chat-1",
        }}
      />
    </ConfigProvider>,
  );
}

describe("FilesDrawer workspace popups", () => {
  beforeEach(() => {
    useCodingTabsStore.setState({
      tabsByAgent: {},
      activeTabByAgent: {},
      diffsByAgent: {},
    });
    vi.spyOn(projectDirectoryApi, "get").mockResolvedValue({
      path: "/projects/alpha",
      name: "alpha",
      is_workspace_default: false,
      workspace_dir: "/workspace",
    });
    vi.spyOn(chatProjectDirectoryApi, "get").mockResolvedValue({
      project_dir: "/projects/alpha",
      source: "session",
      exists: true,
      agent_project_dir: null,
    });
    vi.spyOn(chatProjectDirectoryApi, "getProjectDirs").mockResolvedValue({
      project_dirs: [
        {
          path: "/projects/alpha",
          label: null,
          exists: true,
          nested_with: null,
          is_workspace: false,
        },
      ],
      source: "session",
      agent_project_dir: null,
    });
    vi.spyOn(workspaceApi, "listDirectory").mockResolvedValue({
      directory: "",
      entries: [],
      has_more: false,
      next_cursor: null,
    });
    vi.spyOn(workspaceApi, "listFiles").mockResolvedValue([]);
    vi.spyOn(workspaceApi, "getSystemPromptFiles").mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("keeps a retained directory menu interactive after entering fullscreen", async () => {
    const user = userEvent.setup();
    renderWorkspaceDrawer();
    const switcher = await screen.findByRole("button", {
      name: "files.switchRoot",
    });
    await user.click(switcher);
    const menu = await screen.findByRole("menu");
    expect(menu.closest("[inert]")).toBeNull();
    await user.click(switcher);
    await waitFor(() => expect(menu).not.toBeVisible());
    expect(menu).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    const drawer = screen.getByRole("dialog", { name: "files.title" });
    const background = screen.getByTestId("chat-background");
    expect(background).toHaveAttribute("inert");
    await user.click(switcher);
    expect(await screen.findByRole("menu")).toBe(menu);
    expect(menu.closest("[inert]")).toBeNull();
    expect(drawer).toContainElement(menu);

    await user.click(within(menu).getByRole("menuitem", { name: /workspace/ }));
    await waitFor(() => {
      expect(
        screen.getByRole("complementary", { name: "files.navigator" }),
      ).toHaveAttribute("data-root", "workspace");
    });
    expect(background).toHaveAttribute("inert");
    await user.click(
      screen.getByRole("button", { name: "files.exitFullscreen" }),
    );
    expect(background).not.toHaveAttribute("inert");
  });

  it("keeps keyboard menu focus inside fullscreen", async () => {
    const user = userEvent.setup();
    renderWorkspaceDrawer();
    const switcher = await screen.findByRole("button", {
      name: "files.switchRoot",
    });
    await user.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    await user.click(switcher);
    const menu = await screen.findByRole("menu");
    switcher.focus();
    fireEvent.keyDown(switcher, { key: "Tab", keyCode: 9 });
    await waitFor(() =>
      expect(menu.contains(document.activeElement)).toBe(true),
    );
    expect(
      screen.getByRole("dialog", { name: "files.title" }),
    ).toContainElement(document.activeElement as HTMLElement);
    expect(document.activeElement?.closest("[inert]")).toBeNull();
    fireEvent.keyDown(document.activeElement!, {
      key: "Escape",
      keyCode: 27,
      which: 27,
    });
    await waitFor(() => expect(menu).not.toBeVisible());
    expect(switcher).toHaveFocus();
    expect(screen.getByRole("dialog", { name: "files.title" })).toHaveAttribute(
      "aria-modal",
      "true",
    );
    await user.keyboard("{Escape}");
    expect(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    ).toHaveFocus();
    expect(screen.getByTestId("chat-background")).not.toHaveAttribute("inert");
  });

  it("keeps directory change confirmation inside the fullscreen boundary", async () => {
    useCodingTabsStore.setState({
      tabsByAgent: {
        "session:default:session-1": [
          {
            path: "draft.md",
            content: "unsaved",
            dirty: true,
            source: "workspace",
            workspaceRoot: "project",
          },
        ],
      },
    });
    vi.spyOn(projectDirectoryApi, "list").mockResolvedValue([]);
    vi.spyOn(projectDirectoryApi, "browseDirs").mockResolvedValue({
      current: "/projects/alpha",
      parent: "/projects",
      dirs: [],
    });
    const user = userEvent.setup();
    renderWorkspaceDrawer();
    const switcher = await screen.findByRole("button", {
      name: "files.switchRoot",
    });
    await user.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    const drawer = screen.getByRole("dialog", { name: "files.title" });
    await user.click(switcher);
    await user.click(
      await screen.findByRole("menuitem", {
        name: "files.manageDirs",
      }),
    );
    const pathInput = await screen.findByPlaceholderText(
      "projectDirectory.pathPlaceholder",
    );
    expect(drawer).toContainElement(pathInput);
    fireEvent.change(pathInput, { target: { value: "/projects/beta" } });
    await user.click(screen.getByRole("button", { name: "common.apply" }));
    const [confirmationTitle] = await screen.findAllByText(
      "files.changeDirectoryTitle",
    );
    const confirmation =
      confirmationTitle.closest<HTMLElement>('[role="dialog"]')!;
    expect(confirmation.closest("[inert]")).toBeNull();
    expect(drawer).toContainElement(confirmation);
    await user.click(
      within(confirmation).getByRole("button", {
        name: "common.cancel",
      }),
    );
    await waitFor(() => expect(confirmation).not.toBeInTheDocument());
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(screen.getByTestId("chat-background")).toHaveAttribute("inert");
  });
});
