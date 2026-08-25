import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/request";
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

function chatNotFound(): ApiError {
  return new ApiError(404, 'Chat not found - {"detail":"Chat not found"}');
}

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

  // A chat id outlives its ownership: it stays in the URL across an agent
  // switch, and it survives a deletion made in another tab. Chat endpoints are
  // scoped to the agent of the request, so the read answers 404 — the agent
  // default is the right answer for the agent now in view, and the caller must
  // not see a rejection it would report as a page error.
  it("falls back to the agent default when the chat is not found", async () => {
    mockGetProjectDirs.mockRejectedValue(chatNotFound());

    const snapshot = await loadSessionProjectDirs("other", "s1", CHAT_ID);

    expect(snapshot.dirs).toEqual([
      {
        path: "/agents/default/workspace",
        label: null,
        exists: true,
        nested_with: null,
        is_workspace: true,
      },
    ]);
    expect(snapshot.source).toBe("workspace_fallback");
    expect(snapshot.agentProjectDir).toBeNull();
  });

  it("falls back when the chat vanishes between the two reads", async () => {
    mockGetProjectDirs.mockResolvedValue({
      project_dirs: [],
      source: "workspace_fallback",
      agent_project_dir: null,
    });
    mockGetChatDir.mockRejectedValue(chatNotFound());

    const snapshot = await loadSessionProjectDirs("other", "s1", CHAT_ID);

    expect(snapshot.source).toBe("workspace_fallback");
    expect(mockGetAgentDir).toHaveBeenCalledTimes(1);
  });

  it("prefers a pending pick over the agent default on fallback", async () => {
    mockGetProjectDirs.mockRejectedValue(chatNotFound());
    mockGetPending.mockReturnValue({
      dirs: [{ path: "/projects/picked", label: "picked" }],
    });

    const snapshot = await loadSessionProjectDirs("other", "s1", CHAT_ID);

    expect(snapshot.dirs.map((dir) => dir.path)).toEqual(["/projects/picked"]);
    expect(snapshot.source).toBe("session");
    expect(mockGetAgentDir).not.toHaveBeenCalled();
  });

  it("propagates failures that are not a missing chat", async () => {
    mockGetProjectDirs.mockRejectedValue(new ApiError(500, "boom"));

    await expect(
      loadSessionProjectDirs("default", "s1", CHAT_ID),
    ).rejects.toThrow("boom");
    expect(mockGetAgentDir).not.toHaveBeenCalled();
  });
});
