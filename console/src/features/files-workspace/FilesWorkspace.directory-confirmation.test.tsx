import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import {
  chatProjectDirectoryApi,
  type ChatProjectDirs,
  type ProjectDirEntry,
} from "../../api/modules/chatProjectDirectory";
import { projectDirectoryApi } from "../../api/modules/projectDirectory";
import { workspaceApi } from "../../api/modules/workspace";
import { useCodingTabsStore } from "../../stores/codingTabsStore";
import { setPendingProjectDirectory } from "../project-directory/pendingProjectDirectory";
import { notifyProjectDirectoryChanged } from "../project-directory/projectDirectoryChangeEvent";
import FilesWorkspace from "./FilesWorkspace";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../stores/codingModeStore", () => ({
  useCodingMode: () => ({ codingMode: false }),
}));

vi.mock("./useMemoryTagSupport", () => ({
  useMemoryFileConfig: () => ({ config: null }),
}));

vi.mock("../../pages/Coding/TabbedEditor", () => ({
  default: () => <div>editor</div>,
}));

vi.mock("../../pages/Coding/GitPanel", () => ({ default: () => null }));
vi.mock("./MemoryGraphView", () => ({ default: () => null }));

const scope = {
  kind: "session" as const,
  agentId: "agent-a",
  sessionId: "session-a",
  chatId: "chat-a",
};

const boundDirs: ProjectDirEntry[] = ["alpha", "beta"].map((name) => ({
  path: `/projects/${name}`,
  label: null,
  exists: true,
  nested_with: null,
  is_workspace: false,
}));

async function openDirectoryPanel() {
  fireEvent.click(
    await screen.findByRole("button", { name: "files.switchRoot" }),
  );
  fireEvent.click(await screen.findByText("files.manageDirs"));
  return screen.findByPlaceholderText("projectDirectory.pathPlaceholder");
}

async function confirmDirectories() {
  await act(async () => {
    setPendingProjectDirectory(scope.agentId, scope.sessionId, null);
    notifyProjectDirectoryChanged(scope, { preserveTabs: true });
  });
}

describe("FilesWorkspace directory confirmation", () => {
  beforeEach(() => {
    sessionStorage.clear();
    let savedDirs = boundDirs;
    useCodingTabsStore.setState({
      tabsByAgent: {},
      activeTabByAgent: {},
      diffsByAgent: {},
    });
    setPendingProjectDirectory(scope.agentId, scope.sessionId, boundDirs);
    vi.spyOn(projectDirectoryApi, "get").mockResolvedValue({
      path: "/projects/alpha",
      name: "alpha",
      is_workspace_default: false,
      workspace_dir: "/workspace",
    });
    vi.spyOn(projectDirectoryApi, "list").mockResolvedValue([]);
    vi.spyOn(projectDirectoryApi, "browseDirs").mockResolvedValue({
      current: "/projects",
      parent: "/",
      dirs: [],
    });
    vi.spyOn(chatProjectDirectoryApi, "get").mockImplementation(async () => ({
      project_dir: savedDirs[0].path,
      source: "session",
      exists: true,
      agent_project_dir: null,
    }));
    vi.spyOn(chatProjectDirectoryApi, "getProjectDirs").mockImplementation(
      async () => ({
        project_dirs: savedDirs,
        source: "session",
        agent_project_dir: null,
      }),
    );
    vi.spyOn(chatProjectDirectoryApi, "setProjectDirs").mockImplementation(
      async (_chatId, entries) => {
        savedDirs = entries.map((entry) => ({
          ...boundDirs[0],
          ...entry,
          label: entry.label ?? null,
        }));
        return {
          project_dirs: savedDirs,
          source: "session",
          agent_project_dir: null,
        };
      },
    );
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
    sessionStorage.clear();
  });

  it("keeps a typed path open while refreshing confirmed directories", async () => {
    renderWithProviders(<FilesWorkspace scope={scope} />);
    const input = await openDirectoryPanel();
    fireEvent.change(input, { target: { value: "/projects/unsaved" } });
    vi.mocked(workspaceApi.listDirectory).mockClear();
    vi.mocked(chatProjectDirectoryApi.getProjectDirs).mockClear();

    await confirmDirectories();

    expect(
      screen.queryByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toHaveValue("/projects/unsaved");
    expect(
      screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toBe(input);
    await waitFor(() => {
      expect(workspaceApi.listDirectory).toHaveBeenCalled();
      expect(chatProjectDirectoryApi.getProjectDirs).toHaveBeenCalledWith(
        "chat-a",
        "agent-a",
      );
    });
  });

  it.each(["remove", "make primary", "add"])(
    "keeps an unsaved %s in the nested directory panel",
    async (edit) => {
      renderWithProviders(<FilesWorkspace scope={scope} />);
      const input = await openDirectoryPanel();
      let paths: string[];
      if (edit === "remove") {
        fireEvent.click(
          screen.getAllByRole("button", { name: "projectDirectory.remove" })[1],
        );
        paths = ["/projects/alpha"];
      } else if (edit === "make primary") {
        fireEvent.click(
          screen.getByRole("button", { name: "projectDirectory.makePrimary" }),
        );
        paths = ["/projects/beta", "/projects/alpha"];
      } else {
        fireEvent.change(input, { target: { value: "/projects/unsaved" } });
        fireEvent.click(
          screen.getByRole("button", { name: "projectDirectory.add" }),
        );
        paths = ["/projects/alpha", "/projects/beta", "/projects/unsaved"];
      }

      await confirmDirectories();
      fireEvent.click(screen.getByRole("button", { name: "common.apply" }));

      await waitFor(() =>
        expect(chatProjectDirectoryApi.setProjectDirs).toHaveBeenCalledWith(
          "chat-a",
          paths.map((path) => ({ path, label: null })),
        ),
      );
      await openDirectoryPanel();
      expect(
        screen.getAllByRole("button", { name: "projectDirectory.remove" }),
      ).toHaveLength(paths.length);
      const navigator = screen.getByRole("complementary", {
        name: "files.navigator",
      });
      expect(within(navigator).getByText(paths[0])).toBeInTheDocument();
      const rows = screen.getAllByRole("listitem");
      expect(rows).toHaveLength(paths.length);
      paths.forEach((path, index) => {
        expect(within(rows[index]).getByText(path)).toBeInTheDocument();
      });
    },
  );

  it("keeps edits made while the confirmation lookup is pending", async () => {
    renderWithProviders(<FilesWorkspace scope={scope} />);
    const input = await openDirectoryPanel();
    let resolve!: (value: ChatProjectDirs) => void;
    const confirmationLookup = new Promise<ChatProjectDirs>((res) => {
      resolve = res;
    });
    vi.mocked(chatProjectDirectoryApi.getProjectDirs)
      .mockClear()
      .mockReturnValueOnce(confirmationLookup)
      .mockReturnValueOnce(confirmationLookup);

    await confirmDirectories();
    await waitFor(() =>
      expect(chatProjectDirectoryApi.getProjectDirs).toHaveBeenCalledTimes(2),
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "projectDirectory.remove" })[1],
    );
    fireEvent.change(input, { target: { value: "/projects/unsaved" } });
    await act(async () => {
      resolve({
        project_dirs: boundDirs,
        source: "session",
        agent_project_dir: null,
      });
    });

    expect(
      screen.getByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toBe(input);
    expect(input).toHaveValue("/projects/unsaved");
    fireEvent.click(screen.getByRole("button", { name: "common.apply" }));
    await waitFor(() =>
      expect(chatProjectDirectoryApi.setProjectDirs).toHaveBeenCalledWith(
        "chat-a",
        [
          { path: "/projects/alpha", label: null },
          { path: "/projects/unsaved", label: null },
        ],
      ),
    );
  });

  it("refreshes saved root labels without closing an unedited panel", async () => {
    renderWithProviders(<FilesWorkspace scope={scope} />);
    await openDirectoryPanel();
    vi.mocked(chatProjectDirectoryApi.getProjectDirs).mockResolvedValue({
      project_dirs: [{ ...boundDirs[0], label: "Confirmed project" }],
      source: "session",
      agent_project_dir: null,
    });

    await confirmDirectories();

    expect(
      screen.queryByPlaceholderText("projectDirectory.pathPlaceholder"),
    ).toBeInTheDocument();
    const navigator = screen.getByRole("complementary", {
      name: "files.navigator",
    });
    expect(
      await within(navigator).findByText("Confirmed project"),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "projectDirectory.remove" }),
    ).toHaveLength(1);
  });

  it.each(["resolve", "reject"])(
    "keeps confirmed root details when an older lookup finishes with %s",
    async (outcome) => {
      setPendingProjectDirectory(scope.agentId, scope.sessionId, null);
      let resolve!: (value: ChatProjectDirs) => void;
      let reject!: (reason: Error) => void;
      const olderLookup = new Promise<ChatProjectDirs>((res, rej) => {
        resolve = res;
        reject = rej;
      });
      const initial: ChatProjectDirs = {
        project_dirs: boundDirs,
        source: "session",
        agent_project_dir: null,
      };
      vi.mocked(chatProjectDirectoryApi.getProjectDirs)
        .mockResolvedValueOnce(initial)
        .mockReturnValueOnce(olderLookup);
      renderWithProviders(<FilesWorkspace scope={scope} />);
      await waitFor(() =>
        expect(chatProjectDirectoryApi.getProjectDirs).toHaveBeenCalledTimes(2),
      );
      vi.mocked(chatProjectDirectoryApi.getProjectDirs).mockResolvedValue({
        ...initial,
        project_dirs: [{ ...boundDirs[0], label: "Confirmed project" }],
      });

      await confirmDirectories();
      const navigator = screen.getByRole("complementary", {
        name: "files.navigator",
      });
      await within(navigator).findByText("Confirmed project");
      await act(async () => {
        if (outcome === "resolve") resolve(initial);
        else reject(new Error("Older directory lookup failed"));
      });

      expect(
        within(navigator).getByText("Confirmed project"),
      ).toBeInTheDocument();
    },
  );
});
