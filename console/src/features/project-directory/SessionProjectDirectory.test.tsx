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
