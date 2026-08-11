import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import SessionProjectDirectory from "./SessionProjectDirectory";
import {
  getPendingProjectDirs,
  setPendingProjectDirectory,
} from "./pendingProjectDirectory";

// i18n is not initialised in the test env, so react-i18next's t() returns
// the key itself. Queries below match on key names rather than copy.
const MANAGE = /projectDirectory\.manageAria/;
const CHOOSE_FOLDER = /projectDirectory\.chooseFolder/;
const RESTORE = /projectDirectory\.restoreDefault/;
const MAKE_PRIMARY = /projectDirectory\.makePrimary/;
const APPLY = "common.apply";
const REMOVE = "projectDirectory.remove";
const ROW_NAME = "projectDirectory.renameAria";
const PROJECT_NAME = "projectDirectory.projectNameLabel";

const mocks = vi.hoisted(() => ({
  browseDirs: vi.fn(),
  getAgent: vi.fn(),
  setAgent: vi.fn(),
  listProjects: vi.fn(),
  getProjectDirs: vi.fn(),
  setProjectDirs: vi.fn(),
  clearProjectDirs: vi.fn(),
  pickDirectory: vi.fn(),
  nativePickerAvailable: vi.fn(),
  cancelled: Symbol("pick-cancelled"),
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: {
    browseDirs: mocks.browseDirs,
    get: mocks.getAgent,
    set: mocks.setAgent,
    list: mocks.listProjects,
    nativePickerAvailable: vi.fn(),
    openNativePicker: vi.fn(),
  },
}));

vi.mock("../../api/modules/chatProjectDirectory", () => ({
  chatProjectDirectoryApi: {
    getProjectDirs: mocks.getProjectDirs,
    setProjectDirs: mocks.setProjectDirs,
    clearProjectDirs: mocks.clearProjectDirs,
    get: vi.fn(),
    set: vi.fn(),
    clear: vi.fn(),
  },
}));

vi.mock("../../utils/pickDirectory", () => ({
  PICK_CANCELLED: mocks.cancelled,
  pickDirectory: mocks.pickDirectory,
  isNativeDirectoryPickerAvailable: mocks.nativePickerAvailable,
}));

const agentScope = { kind: "agent" as const, agentId: "default" };
const sessionScope = {
  kind: "session" as const,
  agentId: "default",
  chatId: "chat-1",
  sessionId: "session-1",
};
const pendingScope = {
  kind: "session" as const,
  agentId: "default",
  sessionId: "session-1",
};

const SESSION_MULTI = {
  project_dirs: [
    { path: "/repos/main-app", label: null, exists: true, nested_with: null },
    {
      path: "/repos/backend",
      label: "backend API",
      exists: true,
      nested_with: null,
    },
  ],
  source: "session" as const,
  agent_project_dir: null,
  project_name: "My App",
  project_name_is_custom: true,
};

const INHERITED_LIST = {
  project_dirs: [
    { path: "/repos/parent", label: null, exists: true, nested_with: null },
  ],
  source: "inherited" as const,
  agent_project_dir: null,
  project_name: "parent",
  project_name_is_custom: false,
};

const AGENT_DEFAULT = {
  project_dirs: [
    {
      path: "/repos/agent-default",
      label: null,
      exists: true,
      nested_with: null,
    },
  ],
  source: "agent" as const,
  agent_project_dir: "/repos/agent-default",
  project_name: "agent-default",
  project_name_is_custom: false,
};

const agentProject = {
  path: "/projects/agentscope",
  name: "agentscope",
  is_workspace_default: false,
  workspace_dir: "/home/me/.qwenpaw/workspaces/default",
  exists: true,
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
    sessionStorage.clear();
    mocks.getProjectDirs.mockResolvedValue(SESSION_MULTI);
    mocks.setProjectDirs.mockResolvedValue(SESSION_MULTI);
    mocks.clearProjectDirs.mockResolvedValue(AGENT_DEFAULT);
    mocks.getAgent.mockResolvedValue(agentProject);
    mocks.setAgent.mockResolvedValue(agentProject);
    mocks.listProjects.mockResolvedValue(projects);
    mocks.browseDirs.mockResolvedValue({
      current: "/projects",
      parent: "/",
      dirs: [{ name: "custom", path: "/projects/custom" }],
    });
    mocks.nativePickerAvailable.mockResolvedValue(true);
    mocks.pickDirectory.mockResolvedValue(mocks.cancelled);
  });

  const openPanel = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("button", { name: MANAGE }));
  };

  const enabledChooseButton = async () => {
    const button = await screen.findByRole("button", { name: CHOOSE_FOLDER });
    await waitFor(() => expect(button).toBeEnabled());
    return button;
  };

  describe("agent scope (single directory)", () => {
    it("applies a selected recent project via the agent endpoint", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={agentScope} />);

      await user.click(
        await screen.findByRole("button", {
          name: "projectDirectory.agentTitle",
        }),
      );
      // Switch to the non-active recent project, then apply.
      await user.click(await screen.findByRole("button", { name: /runtime/ }));
      await user.click(screen.getByRole("button", { name: APPLY }));

      await waitFor(() => {
        expect(mocks.setAgent).toHaveBeenCalledWith("/projects/runtime");
      });
    });

    it("clears back to the workspace default", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={agentScope} />);

      await user.click(
        await screen.findByRole("button", {
          name: "projectDirectory.agentTitle",
        }),
      );
      await user.click(
        await screen.findByRole("button", {
          name: "projectDirectory.useWorkspace",
        }),
      );

      await waitFor(() => {
        expect(mocks.setAgent).toHaveBeenCalledWith(null);
      });
    });
  });

  describe("session scope: collapsed card", () => {
    it("shows the project name, count badge and session tag", async () => {
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

      expect(await screen.findByLabelText(PROJECT_NAME)).toHaveValue("My App");
      expect(await screen.findByText("·2")).toBeInTheDocument();
      expect(
        screen.getByText("projectDirectory.tagSession"),
      ).toBeInTheDocument();
    });

    it("shows unbound text when nothing is bound", async () => {
      mocks.getProjectDirs.mockResolvedValue({
        project_dirs: [],
        source: "workspace_fallback",
        agent_project_dir: null,
        project_name: null,
        project_name_is_custom: false,
      });
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);

      expect(
        await screen.findByText("projectDirectory.unboundShort"),
      ).toBeInTheDocument();
    });

    it("flags a missing primary directory", async () => {
      mocks.getProjectDirs.mockResolvedValue({
        project_dirs: [
          {
            path: "/repos/gone",
            label: null,
            exists: false,
            nested_with: null,
          },
        ],
        source: "session",
        agent_project_dir: null,
        project_name: "gone",
        project_name_is_custom: false,
      });
      const { container } = renderWithProviders(
        <SessionProjectDirectory scope={sessionScope} />,
      );

      await waitFor(() => {
        expect(
          container.querySelector('[data-missing="true"]'),
        ).toBeInTheDocument();
      });
    });
  });

  describe("session scope: the directory list", () => {
    it("renders every entry, marking only the first as primary", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      const names = await screen.findAllByLabelText(ROW_NAME);
      expect(names.map((el) => (el as HTMLInputElement).value)).toEqual([
        "main-app",
        "backend API",
      ]);
      expect(screen.getByText("/repos/backend")).toBeInTheDocument();
      expect(screen.getAllByText("projectDirectory.primaryTag")).toHaveLength(
        1,
      );
      expect(
        screen.getAllByRole("button", { name: MAKE_PRIMARY }),
      ).toHaveLength(1);
    });

    it("commits a reordered list on Apply (make-primary)", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      await user.click(
        await screen.findByRole("button", { name: MAKE_PRIMARY }),
      );
      await user.click(screen.getByRole("button", { name: APPLY }));

      await waitFor(() => {
        expect(mocks.setProjectDirs).toHaveBeenCalledWith(
          "chat-1",
          [
            { path: "/repos/backend", label: "backend API" },
            { path: "/repos/main-app", label: null },
          ],
          "My App",
        );
      });
    });

    it("commits a removal on Apply", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      const removes = await screen.findAllByRole("button", { name: REMOVE });
      await user.click(removes[1]);
      await user.click(screen.getByRole("button", { name: APPLY }));

      await waitFor(() => {
        expect(mocks.setProjectDirs).toHaveBeenCalledWith(
          "chat-1",
          [{ path: "/repos/main-app", label: null }],
          "My App",
        );
      });
    });

    it("restores the default by clearing the override", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      await user.click(await screen.findByRole("button", { name: RESTORE }));

      await waitFor(() => {
        expect(mocks.clearProjectDirs).toHaveBeenCalledWith("chat-1");
      });
    });
  });

  describe("session scope: adding a directory", () => {
    it("adds the folder chosen from the OS dialog and saves it", async () => {
      mocks.pickDirectory.mockResolvedValue("/repos/picked");
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      await user.click(await enabledChooseButton());
      await screen.findByText("/repos/picked");
      await user.click(screen.getByRole("button", { name: APPLY }));

      await waitFor(() => {
        expect(mocks.setProjectDirs).toHaveBeenCalledWith(
          "chat-1",
          [
            { path: "/repos/main-app", label: null },
            { path: "/repos/backend", label: "backend API" },
            { path: "/repos/picked", label: null },
          ],
          "My App",
        );
      });
    });

    it("cancelling the dialog changes nothing", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      await user.click(await enabledChooseButton());

      await waitFor(() => expect(mocks.pickDirectory).toHaveBeenCalled());
      expect(screen.queryByText("/repos/picked")).not.toBeInTheDocument();
    });

    it("rejects a duplicate path", async () => {
      mocks.pickDirectory.mockResolvedValue("/repos/main-app");
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      await user.click(await enabledChooseButton());

      expect(
        await screen.findByText("projectDirectory.duplicate"),
      ).toBeInTheDocument();
      // No third row was added.
      expect(screen.getAllByLabelText(ROW_NAME)).toHaveLength(2);
    });
  });

  describe("session scope: restore-default enablement by source", () => {
    it("is enabled for a session override", async () => {
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      expect(
        await screen.findByRole("button", { name: RESTORE }),
      ).toBeEnabled();
    });

    it("is disabled for an inherited list", async () => {
      mocks.getProjectDirs.mockResolvedValue(INHERITED_LIST);
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      expect(
        await screen.findByRole("button", { name: RESTORE }),
      ).toBeDisabled();
    });

    it("is disabled for an agent default", async () => {
      mocks.getProjectDirs.mockResolvedValue(AGENT_DEFAULT);
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={sessionScope} />);
      await openPanel(user);

      expect(
        await screen.findByRole("button", { name: RESTORE }),
      ).toBeDisabled();
    });
  });

  describe("session scope: pending flow (no chat id yet)", () => {
    it("renders the pending list and saves additions locally", async () => {
      setPendingProjectDirectory(
        "default",
        "session-1",
        [{ path: "/pending/a", label: null }],
        null,
      );
      mocks.pickDirectory.mockResolvedValue("/pending/b");
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={pendingScope} />);

      // The card shows the pending tag.
      expect(
        await screen.findByText("projectDirectory.tagPending"),
      ).toBeInTheDocument();

      await openPanel(user);
      await user.click(await enabledChooseButton());
      await screen.findByText("/pending/b");
      await user.click(screen.getByRole("button", { name: APPLY }));

      await waitFor(() => {
        expect(getPendingProjectDirs("default", "session-1")).toEqual({
          dirs: [
            { path: "/pending/a", label: null },
            { path: "/pending/b", label: null },
          ],
          name: null,
        });
      });
      // No chat exists yet, so no chat API call is made.
      expect(mocks.setProjectDirs).not.toHaveBeenCalled();
    });

    it("restoring the default clears the pending value", async () => {
      setPendingProjectDirectory(
        "default",
        "session-1",
        [{ path: "/pending/a", label: null }],
        null,
      );
      const user = userEvent.setup();
      renderWithProviders(<SessionProjectDirectory scope={pendingScope} />);
      await openPanel(user);

      await user.click(await screen.findByRole("button", { name: RESTORE }));

      await waitFor(() => {
        expect(getPendingProjectDirs("default", "session-1")).toBeNull();
      });
      expect(mocks.clearProjectDirs).not.toHaveBeenCalled();
    });
  });
});
