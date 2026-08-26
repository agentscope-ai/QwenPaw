import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadSessionProjectDirs } from "./loadSessionProjectDirs";

const { mockGetProjectDirs, mockGetChatDir, mockGetAgentDir, mockGetPending } =
  vi.hoisted(() => ({
    mockGetProjectDirs: vi.fn(),
    mockGetChatDir: vi.fn(),
    mockGetAgentDir: vi.fn(),
    mockGetPending: vi.fn(),
  }));

vi.mock("../../api/modules/chatProjectDirectory", () => ({
  chatProjectDirectoryApi: {
    getProjectDirs: mockGetProjectDirs,
    get: mockGetChatDir,
  },
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: { get: mockGetAgentDir },
}));

vi.mock("./pendingProjectDirectory", () => ({
  getPendingProjectDirs: mockGetPending,
}));

const CHAT_ID = "ceb44050-d815-43f1-9212-c6b9a2054295";

describe("loadSessionProjectDirs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetPending.mockReturnValue(null);
    mockGetAgentDir.mockResolvedValue({
      path: "/agents/default/workspace",
      exists: true,
      is_workspace_default: true,
    });
  });

  it("returns the directories bound to the chat", async () => {
    mockGetProjectDirs.mockResolvedValue({
      project_dirs: [
        {
          path: "/projects/agentscope",
          label: null,
          exists: true,
          nested_with: null,
          is_workspace: false,
        },
      ],
      source: "session",
      agent_project_dir: "/projects/runtime",
    });

    const snapshot = await loadSessionProjectDirs("default", "s1", CHAT_ID);

    expect(snapshot.dirs.map((dir) => dir.path)).toEqual([
      "/projects/agentscope",
    ]);
    expect(snapshot.source).toBe("session");
    expect(mockGetAgentDir).not.toHaveBeenCalled();
  });

  it("propagates chat directory failures", async () => {
    mockGetProjectDirs.mockRejectedValue(new Error("boom"));

    await expect(
      loadSessionProjectDirs("default", "s1", CHAT_ID),
    ).rejects.toThrow("boom");
    expect(mockGetAgentDir).not.toHaveBeenCalled();
  });

  it("skips chat queries for a new conversation and uses the agent default", async () => {
    const snapshot = await loadSessionProjectDirs("other", "new");

    expect(mockGetProjectDirs).not.toHaveBeenCalled();
    expect(mockGetChatDir).not.toHaveBeenCalled();
    expect(mockGetAgentDir).toHaveBeenCalledTimes(1);
    expect(snapshot.dirs[0].path).toBe("/agents/default/workspace");
    expect(snapshot.source).toBe("workspace_fallback");
  });
});
