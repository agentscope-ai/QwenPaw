import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import SessionProjectDirectory from "./SessionProjectDirectory";

const {
  mockBrowseDirs,
  mockGetSessionDirectory,
  mockListProjects,
  mockSetSessionDirectory,
} = vi.hoisted(() => ({
  mockBrowseDirs: vi.fn(),
  mockGetSessionDirectory: vi.fn(),
  mockListProjects: vi.fn(),
  mockSetSessionDirectory: vi.fn(),
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: {
    browseDirs: mockBrowseDirs,
    get: vi.fn(),
    list: mockListProjects,
    set: vi.fn(),
  },
}));

vi.mock("../../api/modules/chatProjectDirectory", () => ({
  chatProjectDirectoryApi: {
    clear: vi.fn(),
    get: mockGetSessionDirectory,
    set: mockSetSessionDirectory,
  },
}));

const scope = {
  kind: "session" as const,
  agentId: "default",
  chatId: "chat-1",
  sessionId: "session-1",
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
      project_dir: "/projects/agentscope",
      source: "session",
      agent_project_dir: "/projects/agentscope",
      exists: true,
    });
    mockListProjects.mockResolvedValue(projects);
    mockBrowseDirs.mockResolvedValue({
      current: "/projects",
      parent: "/",
      dirs: [{ name: "custom", path: "/projects/custom" }],
    });
  });

  it("shows a removable path chip for a selected recent project", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );

    const clearButton = await screen.findByRole("button", {
      name: "projectDirectory.clearSelection",
    });
    expect(
      document.querySelector(".ant-popover-placement-topRight"),
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

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );
    await user.click(await screen.findByRole("button", { name: /custom/ }));

    expect(
      screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toHaveValue("/projects/custom");
    expect(screen.getByRole("button", { name: /agentscope/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("uses Apply as the only confirmation after directory navigation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );
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

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );
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

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );
    await waitFor(() => {
      expect(mockBrowseDirs).toHaveBeenCalledWith(
        "/projects/agentscope",
        false,
      );
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
    let resolvers: Array<{
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

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );

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
      project_dir: "/projects/runtime",
      source: "session",
      agent_project_dir: "/projects/agentscope",
      exists: true,
    });
    renderWithProviders(<SessionProjectDirectory scope={scope} />);

    await user.click(
      await screen.findByRole("button", {
        name: "projectDirectory.sessionTitle",
      }),
    );
    await user.click(await screen.findByRole("button", { name: /runtime/ }));
    await user.click(screen.getByRole("button", { name: "common.apply" }));

    await waitFor(() => {
      expect(mockSetSessionDirectory).toHaveBeenCalledWith(
        "chat-1",
        "/projects/runtime",
      );
    });
  });
});
