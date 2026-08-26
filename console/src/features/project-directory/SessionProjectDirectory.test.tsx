import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { chatProjectDirectoryApi } from "../../api/modules/chatProjectDirectory";
import { ApiError } from "../../api/request";
import SessionProjectDirectory from "./SessionProjectDirectory";

const {
  mockBrowseDirs,
  mockCreateDirectory,
  mockGetSessionDirectory,
  mockListProjects,
  mockSetSessionDirectory,
} = vi.hoisted(() => ({
  mockBrowseDirs: vi.fn(),
  mockCreateDirectory: vi.fn(),
  mockGetSessionDirectory: vi.fn(),
  mockListProjects: vi.fn(),
  mockSetSessionDirectory: vi.fn(),
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: {
    browseDirs: mockBrowseDirs,
    createDirectory: mockCreateDirectory,
    get: mockGetSessionDirectory,
    list: mockListProjects,
    set: mockSetSessionDirectory,
  },
}));

vi.mock("../../api/modules/chatProjectDirectory", () => ({
  chatProjectDirectoryApi: {
    clearProjectDirs: vi.fn(),
    get: vi.fn(),
    getProjectDirs: vi.fn(),
    setProjectDirs: vi.fn(),
  },
}));

// The single-path picker these tests drive (path field, clear button,
// recent-project selection, Apply) lives on AGENT scope. Session scope
// binds an ordered list of directories instead, so it has no path field.
const scope = { kind: "agent" as const, agentId: "default" };

const sessionScope = {
  kind: "session" as const,
  agentId: "default",
  sessionId: "s1",
  chatId: "ceb44050-d815-43f1-9212-c6b9a2054295",
};

const projects = [
  {
    path: "/projects/agentscope",
    name: "agentscope",
    is_git: true,
    is_active: true,
  },
  {
    path: "/projects/runtime",
    name: "runtime",
    is_git: true,
    is_active: false,
  },
];

describe("SessionProjectDirectory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSessionDirectory.mockResolvedValue({
      path: "/projects/agentscope",
      name: "agentscope",
      is_workspace_default: false,
      exists: true,
    });
    mockListProjects.mockResolvedValue(projects);
    mockBrowseDirs.mockResolvedValue({
      current: "/projects",
      parent: "/",
      dirs: [{ name: "custom", path: "/projects/custom" }],
    });
    mockCreateDirectory.mockResolvedValue({
      name: "reports",
      path: "/projects/reports",
    });
  });

  const openPanel = async (user: ReturnType<typeof userEvent.setup>) =>
    user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.agentTitle",
      }),
    );

  it("shows a removable path chip for a selected recent project", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);

    const clearButton = await screen.findByRole("button", {
      name: "projectDirectory.clearSelection",
    });
    expect(
      document.querySelector(".ant-popover-placement-rightTop"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /agentscope/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(clearButton);

    expect(
      screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toHaveValue("");
    expect(screen.getByRole("button", { name: /agentscope/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("clears the recent selection when a browsed directory is chosen", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);
    await user.click(await screen.findByRole("button", { name: /custom/ }));

    expect(
      screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toHaveValue("/projects/custom");
    expect(screen.getByRole("button", { name: /agentscope/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("creates a folder in the browsed directory and selects it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);
    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.createDirectory",
      }),
    );
    await user.type(
      screen.getByPlaceholderText("projectDirectory.directoryNamePlaceholder"),
      "reports",
    );
    await user.click(screen.getByRole("button", { name: "common.confirm" }));

    await waitFor(() => {
      expect(mockCreateDirectory).toHaveBeenCalledWith("/projects", "reports");
      expect(
        screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
      ).toHaveValue("/projects/reports");
    });
    expect(mockBrowseDirs).toHaveBeenLastCalledWith("/projects", false);
  });

  it("uses Apply as the only confirmation after directory navigation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);
    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.parentDirectory",
      }),
    );

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
      ).toHaveValue("/projects");
    });
    expect(
      screen.queryByText("projectDirectory.chooseCurrentDirectory"),
    ).not.toBeInTheDocument();
  });

  it("does not restore a stale recent selection after manual editing", async () => {
    const user = userEvent.setup();
    let resolveProjects: (value: typeof projects) => void = () => undefined;
    mockListProjects.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveProjects = resolve;
        }),
    );
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);
    const input = await screen.findByPlaceholderText(
      "projectDirectory.pathPlaceholder",
    );
    await user.clear(input);
    await user.type(input, "/projects/manual");
    act(() => resolveProjects(projects));

    await waitFor(() => {
      expect(input).toHaveValue("/projects/manual");
      expect(
        screen.getByRole("button", { name: /agentscope/ }),
      ).toHaveAttribute("aria-pressed", "false");
    });
  });

  it("re-browses the current directory when hidden folders are toggled", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);
    await waitFor(() => {
      // Opens on the home directory, not inside the current project.
      expect(mockBrowseDirs).toHaveBeenCalledWith("~", false);
    });

    await user.click(
      screen.getByRole("button", {
        name: "codingMode.openDirHiddenFolders",
      }),
    );

    await waitFor(() => {
      expect(mockBrowseDirs).toHaveBeenLastCalledWith("/projects", true);
    });
    expect(screen.getByRole("button", { name: /agentscope/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("discards stale browse responses when toggle completes out of order", async () => {
    const user = userEvent.setup();

    // We will control resolve order manually.
    const resolvers: Array<{
      resolve: (v: {
        current: string;
        parent: string;
        dirs: { name: string; path: string }[];
      }) => void;
      showHidden: boolean;
    }> = [];
    mockBrowseDirs.mockImplementation(
      (_path: string | undefined, showHidden: boolean) =>
        new Promise((resolve) => {
          resolvers.push({
            resolve: resolve as never,
            showHidden,
          });
        }),
    );

    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);

    // Wait for the initial browse request (show_hidden=false).
    await waitFor(() => {
      expect(resolvers.length).toBeGreaterThanOrEqual(1);
    });

    // Toggle hidden ON → second request (show_hidden=true).
    await user.click(
      screen.getByRole("button", {
        name: "codingMode.openDirHiddenFolders",
      }),
    );

    await waitFor(() => {
      expect(resolvers.length).toBeGreaterThanOrEqual(2);
    });

    // Resolve in REVERSE order: true first, then false.
    const trueReq = resolvers.find((r) => r.showHidden)!;
    const falseReq = resolvers.find((r) => !r.showHidden)!;

    act(() => {
      trueReq.resolve({
        current: "/projects",
        parent: "/",
        dirs: [
          { name: ".secret", path: "/projects/.secret" },
          { name: "custom", path: "/projects/custom" },
        ],
      });
    });

    // After the newer (true) response resolves, .secret should be visible.
    await waitFor(() => {
      expect(screen.getByText(".secret")).toBeInTheDocument();
    });

    // Now resolve the stale false request.
    act(() => {
      falseReq.resolve({
        current: "/projects",
        parent: "/",
        dirs: [{ name: "custom", path: "/projects/custom" }],
      });
    });

    // The stale response must NOT overwrite the newer result.
    // The toggle button should still show pressed=true and .secret should remain.
    expect(
      screen.getByRole("button", { name: "codingMode.openDirHiddenFolders" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(".secret")).toBeInTheDocument();
  });

  it("applies the path that owns the visible selection state", async () => {
    const user = userEvent.setup();
    mockSetSessionDirectory.mockResolvedValue({
      path: "/projects/runtime",
      name: "runtime",
      is_workspace_default: false,
      exists: true,
    });
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await openPanel(user);
    await user.click(await screen.findByRole("button", { name: /runtime/ }));
    await user.click(screen.getByRole("button", { name: "common.apply" }));

    await waitFor(() => {
      expect(mockSetSessionDirectory).toHaveBeenCalledWith("/projects/runtime");
    });
  });

  // A chat id outlives its chat: it stays in the URL across an agent switch,
  // and it survives a deletion made in another tab. Both answer 404, and the
  // panel refreshes on every scope change — so this must degrade to the agent
  // default instead of leaving a rejection for the page to report.
  it("shows the agent default when the session chat is gone", async () => {
    vi.mocked(chatProjectDirectoryApi.getProjectDirs).mockRejectedValue(
      new ApiError(404, "Chat not found"),
    );

    renderWithProviders(
      <SessionProjectDirectory scope={sessionScope} showFullPath />,
    );

    await waitFor(() => {
      expect(mockGetSessionDirectory).toHaveBeenCalled();
    });
    expect(
      await screen.findByText("/projects/agentscope", { exact: false }),
    ).toBeInTheDocument();
  });

  it("keeps an unexpected read failure inside the panel", async () => {
    vi.mocked(chatProjectDirectoryApi.getProjectDirs).mockRejectedValue(
      new ApiError(500, "directory service exploded"),
    );

    renderWithProviders(<SessionProjectDirectory scope={sessionScope} open />);

    expect(
      await screen.findByText("directory service exploded"),
    ).toBeInTheDocument();
  });

  it("clears a read failure after the current scope refresh succeeds", async () => {
    vi.mocked(chatProjectDirectoryApi.getProjectDirs)
      .mockRejectedValueOnce(new ApiError(500, "directory service exploded"))
      .mockResolvedValueOnce({
        project_dirs: [
          {
            path: "/projects/recovered",
            label: null,
            exists: true,
            nested_with: null,
            is_workspace: false,
          },
        ],
        source: "session",
        agent_project_dir: "/projects/agentscope",
      });

    const view = renderWithProviders(
      <SessionProjectDirectory scope={sessionScope} open />,
    );
    expect(
      await screen.findByText("directory service exploded"),
    ).toBeInTheDocument();

    view.rerender(
      <SessionProjectDirectory
        scope={{ ...sessionScope, sessionId: "s2" }}
        open
      />,
    );

    expect(await screen.findByText("/projects/recovered")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.queryByText("directory service exploded"),
      ).not.toBeInTheDocument();
    });
  });

  it("ignores a failed refresh from the previous scope", async () => {
    let rejectPrevious: (error: Error) => void = () => undefined;
    vi.mocked(chatProjectDirectoryApi.getProjectDirs)
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            rejectPrevious = reject;
          }),
      )
      .mockResolvedValueOnce({
        project_dirs: [
          {
            path: "/projects/current",
            label: null,
            exists: true,
            nested_with: null,
            is_workspace: false,
          },
        ],
        source: "session",
        agent_project_dir: "/projects/agentscope",
      });

    const view = renderWithProviders(
      <SessionProjectDirectory scope={sessionScope} open />,
    );
    await waitFor(() => {
      expect(chatProjectDirectoryApi.getProjectDirs).toHaveBeenCalledTimes(1);
    });

    view.rerender(
      <SessionProjectDirectory
        scope={{ ...sessionScope, sessionId: "s2" }}
        open
      />,
    );
    expect(await screen.findByText("/projects/current")).toBeInTheDocument();

    await act(async () => {
      rejectPrevious(new ApiError(500, "stale failure"));
      await Promise.resolve();
    });
    expect(screen.queryByText("stale failure")).not.toBeInTheDocument();
  });

  it("ignores a successful refresh from the previous scope", async () => {
    let resolvePrevious: (value: {
      project_dirs: Array<{
        path: string;
        label: null;
        exists: boolean;
        nested_with: null;
        is_workspace: boolean;
      }>;
      source: "session";
      agent_project_dir: string;
    }) => void = () => undefined;
    vi.mocked(chatProjectDirectoryApi.getProjectDirs)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolvePrevious = resolve;
          }),
      )
      .mockResolvedValueOnce({
        project_dirs: [
          {
            path: "/projects/current",
            label: null,
            exists: true,
            nested_with: null,
            is_workspace: false,
          },
        ],
        source: "session",
        agent_project_dir: "/projects/agentscope",
      });

    const view = renderWithProviders(
      <SessionProjectDirectory scope={sessionScope} open />,
    );
    await waitFor(() => {
      expect(chatProjectDirectoryApi.getProjectDirs).toHaveBeenCalledTimes(1);
    });
    view.rerender(
      <SessionProjectDirectory
        scope={{ ...sessionScope, sessionId: "s2" }}
        open
      />,
    );
    expect(await screen.findByText("/projects/current")).toBeInTheDocument();

    await act(async () => {
      resolvePrevious({
        project_dirs: [
          {
            path: "/projects/previous",
            label: null,
            exists: true,
            nested_with: null,
            is_workspace: false,
          },
        ],
        source: "session",
        agent_project_dir: "/projects/agentscope",
      });
      await Promise.resolve();
    });

    expect(screen.getByText("/projects/current")).toBeInTheDocument();
    expect(screen.queryByText("/projects/previous")).not.toBeInTheDocument();
  });
});
