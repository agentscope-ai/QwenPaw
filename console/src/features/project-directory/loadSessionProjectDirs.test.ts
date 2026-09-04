import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSessionProjectDirs } from "./loadSessionProjectDirs";

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
  sessionStorage.removeItem("qwenpaw-agent-storage");
  vi.unstubAllGlobals();
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
