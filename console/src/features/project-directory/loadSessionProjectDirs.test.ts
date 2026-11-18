import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSessionProjectDirs } from "./loadSessionProjectDirs";
import { setPendingProjectDirectory } from "./pendingProjectDirectory";

vi.mock("../../api/config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
  getApiToken: () => "",
  clearAuthToken: vi.fn(),
}));

const selectAgent = (agentId: string) =>
  sessionStorage.setItem(
    "qwenpaw-agent-storage",
    JSON.stringify({ state: { selectedAgent: agentId } }),
  );

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("new session directory persistence", () => {
  it.each(["/projects/custom", "C:\\Users\\test\\project"])(
    "keeps the pending directory %s after the Chat ID is allocated",
    async (path) => {
      setPendingProjectDirectory("agent-a", "chat-a", [{ path, label: null }]);
      const fetchSpy = vi.fn(
        async (url: string) =>
          new Response(
            JSON.stringify(
              url.endsWith("/project-dirs")
                ? {
                    project_dirs: [],
                    source: "workspace_fallback",
                    agent_project_dir: null,
                  }
                : {
                    project_dir: "/agent-a/workspace",
                    source: "workspace_fallback",
                    exists: true,
                    agent_project_dir: null,
                  },
            ),
            { headers: { "content-type": "application/json" } },
          ),
      );
      vi.stubGlobal("fetch", fetchSpy);

      const snapshot = await loadSessionProjectDirs(
        "agent-a",
        "chat-a",
        "chat-a",
      );

      expect(snapshot.source).toBe("session");
      expect(snapshot.dirs[0].path).toBe(path);
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("reads the persisted list after the pending choice is confirmed", async () => {
    setPendingProjectDirectory("agent-a", "chat-a", [
      { path: "/projects/custom", label: null },
    ]);
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          project_dirs: [
            {
              path: "/projects/custom",
              label: "Saved project",
              exists: true,
              nested_with: null,
              is_workspace: false,
            },
          ],
          source: "session",
          agent_project_dir: null,
        }),
        { headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    await loadSessionProjectDirs("agent-a", "chat-a", "chat-a");
    expect(fetchSpy).not.toHaveBeenCalled();

    setPendingProjectDirectory("agent-a", "chat-a", null);
    const saved = await loadSessionProjectDirs("agent-a", "chat-a", "chat-a");

    expect(saved.dirs[0].label).toBe("Saved project");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});

describe("session directory request ownership", () => {
  it.each(["before the read", "while the read is pending"])(
    "keeps both directory endpoints bound to the Chat's Agent when switching %s",
    async (switchTiming) => {
      let resolvePlural!: (response: Response) => void;
      const plural = new Promise<Response>((resolve) => {
        resolvePlural = resolve;
      });
      const fetchSpy = vi
        .fn()
        .mockReturnValueOnce(plural)
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              project_dir: "/agent-a/workspace",
              source: "workspace_fallback",
              agent_project_dir: null,
              exists: true,
            }),
            { headers: { "content-type": "application/json" } },
          ),
        );
      vi.stubGlobal("fetch", fetchSpy);
      selectAgent(switchTiming === "before the read" ? "agent-b" : "agent-a");

      const pending = loadSessionProjectDirs("agent-a", "runtime-a", "chat-a");
      selectAgent("agent-b");
      resolvePlural(
        new Response(
          JSON.stringify({
            project_dirs: [],
            source: "workspace_fallback",
            agent_project_dir: null,
          }),
          { headers: { "content-type": "application/json" } },
        ),
      );

      expect((await pending).dirs[0].path).toBe("/agent-a/workspace");
      expect(fetchSpy.mock.calls.map(([url]) => url)).toEqual([
        "/api/chats/chat-a/project-dirs",
        "/api/chats/chat-a/project-dir",
      ]);
      for (const [, options] of fetchSpy.mock.calls) {
        expect(new Headers(options.headers).get("X-Agent-Id")).toBe("agent-a");
      }
    },
  );
});
