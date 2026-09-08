import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import SessionProjectDirectory from "./SessionProjectDirectory";

const {
  mockBrowseDirs,
  mockCreateDirectory,
  mockGetSessionDirectory,
  mockUseIsMobile,
  mockListProjects,
  mockSetSessionDirectory,
  mockClearProjectDirs,
  mockGetChatDirectory,
  mockGetProjectDirs,
  mockSetProjectDirs,
} = vi.hoisted(() => ({
  mockBrowseDirs: vi.fn(),
  mockCreateDirectory: vi.fn(),
  mockGetSessionDirectory: vi.fn(),
  mockUseIsMobile: vi.fn(() => false),
  mockListProjects: vi.fn(),
  mockSetSessionDirectory: vi.fn(),
  mockClearProjectDirs: vi.fn(),
  mockGetChatDirectory: vi.fn(),
  mockGetProjectDirs: vi.fn(),
  mockSetProjectDirs: vi.fn(),
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
    clearProjectDirs: mockClearProjectDirs,
    get: mockGetChatDirectory,
    getProjectDirs: mockGetProjectDirs,
    setProjectDirs: mockSetProjectDirs,
  },
}));

vi.mock("../../hooks/useIsMobile", () => ({
  useIsMobile: mockUseIsMobile,
}));

// The single-path picker these tests drive (path field, clear button,
// recent-project selection, Apply) lives on AGENT scope. Session scope
// binds an ordered list of directories; its own direct path input shares the
// queued path with the picker (see the session scope suite below).
const scope = { kind: "agent" as const, agentId: "default" };

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
    mockUseIsMobile.mockReturnValue(false);
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

  it("renders a single icon trigger in compact mode", async () => {
    renderWithProviders(
      <SessionProjectDirectory
        className="mobile-control"
        compact
        scope={scope}
      />,
    );

    const trigger = await screen.findByRole("button", {
      name: "projectDirectory.agentTitle",
    });
    expect(trigger).toHaveClass("mobile-control");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger.querySelectorAll("svg")).toHaveLength(1);
    expect(trigger).not.toHaveTextContent("agentscope");
  });

  it("uses a bottom drawer on mobile without a path tooltip", async () => {
    mockUseIsMobile.mockReturnValue(true);
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory compact scope={scope} />);

    const trigger = await screen.findByRole("button", {
      name: "projectDirectory.agentTitle",
    });
    await user.hover(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.click(trigger);

    expect(
      await screen.findByRole("dialog", {
        name: "projectDirectory.agentTitle",
      }),
    ).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(
      document.querySelector(".ant-popover, .qwenpaw-popover"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "common.close",
      }),
    );

    await waitFor(() => {
      expect(trigger).toHaveAttribute("aria-expanded", "false");
    });
  });

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
});

describe("SessionProjectDirectory session scope direct path input (#7588)", () => {
  const sessionScope = {
    kind: "session" as const,
    agentId: "default",
    sessionId: "sess-1",
    chatId: "chat-1",
  };
  const boundDirs = [
    {
      path: "/projects/alpha",
      label: null,
      exists: true,
      nested_with: null,
      is_workspace: false,
    },
    {
      path: "/projects/beta",
      label: null,
      exists: true,
      nested_with: null,
      is_workspace: false,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseIsMobile.mockReturnValue(false);
    mockListProjects.mockResolvedValue([]);
    mockBrowseDirs.mockResolvedValue({
      current: "/projects",
      parent: "/",
      dirs: [{ name: "custom", path: "/projects/custom" }],
    });
    mockGetProjectDirs.mockResolvedValue({
      project_dirs: boundDirs,
      source: "session",
      agent_project_dir: null,
    });
    mockSetProjectDirs.mockImplementation(
      async (_chatId: string, entries: { path: string }[]) => ({
        project_dirs: entries.map((entry) => ({
          path: entry.path,
          label: null,
          exists: true,
          nested_with: null,
          is_workspace: false,
        })),
        source: "session",
        agent_project_dir: null,
      }),
    );
  });

  const openSessionPanel = async (user: ReturnType<typeof userEvent.setup>) =>
    user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );

  const getPathInput = async () =>
    screen.findByPlaceholderText("projectDirectory.pathPlaceholder");

  it("shows a direct path input on session scope", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);

    expect(await getPathInput()).toBeInTheDocument();
  });

  it("pastes a POSIX path + Enter switches the primary, keeping other dirs", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(await getPathInput(), "/home/user/deep/project{Enter}");

    await waitFor(() => {
      expect(mockSetProjectDirs).toHaveBeenCalledWith("chat-1", [
        { path: "/home/user/deep/project", label: null },
        { path: "/projects/alpha", label: null },
        { path: "/projects/beta", label: null },
      ]);
    });
    // The always-live trigger already advertises the new primary.
    expect(
      screen.getByRole("button", { name: "projectDirectory.sessionTitle" }),
    ).toHaveTextContent("project");
    // A successful switch closes the panel (its overlay keeps a frozen copy
    // while closed), so reopen it to read the live state: the committed
    // primary is listed first and the input is cleared.
    await openSessionPanel(user);
    expect(
      screen.getAllByText("/home/user/deep/project").length,
    ).toBeGreaterThanOrEqual(1);
    expect(await getPathInput()).toHaveValue("");
  });

  it("trims surrounding whitespace before switching", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(await getPathInput(), "  /projects/typed  {Enter}");

    await waitFor(() => {
      expect(mockSetProjectDirs).toHaveBeenCalledWith("chat-1", [
        { path: "/projects/typed", label: null },
        { path: "/projects/alpha", label: null },
        { path: "/projects/beta", label: null },
      ]);
    });
  });

  it("passes Windows absolute paths through without canonicalization", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(
      await getPathInput(),
      "C:\\Users\\test\\deep\\project{Enter}",
    );

    await waitFor(() => {
      expect(mockSetProjectDirs).toHaveBeenCalledWith("chat-1", [
        { path: "C:\\Users\\test\\deep\\project", label: null },
        { path: "/projects/alpha", label: null },
        { path: "/projects/beta", label: null },
      ]);
    });
  });

  it("fills the direct input when a browsed directory is picked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.click(await screen.findByRole("button", { name: /custom/ }));

    expect(await getPathInput()).toHaveValue("/projects/custom");
    expect(mockSetProjectDirs).not.toHaveBeenCalled();
  });

  it("makes an already-bound typed path the primary", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(await getPathInput(), "/projects/beta{Enter}");

    await waitFor(() => {
      expect(mockSetProjectDirs).toHaveBeenCalledWith("chat-1", [
        { path: "/projects/beta", label: null },
        { path: "/projects/alpha", label: null },
      ]);
    });
  });

  it("shows a backend error without polluting the bound list", async () => {
    const user = userEvent.setup();
    mockSetProjectDirs.mockRejectedValueOnce(
      new Error("Not a directory: /nope"),
    );
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(await getPathInput(), "/nope{Enter}");

    await waitFor(() => {
      expect(mockSetProjectDirs).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByText("Not a directory: /nope"),
    ).toBeInTheDocument();
    // Previously bound directories are still rendered.
    expect(screen.getByTitle("/projects/alpha")).toBeInTheDocument();
    expect(screen.getByTitle("/projects/beta")).toBeInTheDocument();
  });

  it("does nothing destructive on Enter with the current primary", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(await getPathInput(), "/projects/alpha{Enter}");

    // No request: the primary is already bound first.
    expect(mockSetProjectDirs).not.toHaveBeenCalled();
    // The queue is dismissed without dropping any binding.
    expect(await getPathInput()).toHaveValue("");
  });

  it("does not switch on blur", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    await user.type(await getPathInput(), "/projects/typed");
    await user.tab();

    expect(mockSetProjectDirs).not.toHaveBeenCalled();
  });

  it("does not switch on Enter with an empty input", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

    await openSessionPanel(user);
    const input = await getPathInput();
    input.focus();
    await user.keyboard("{Enter}");

    expect(mockSetProjectDirs).not.toHaveBeenCalled();
  });
});
