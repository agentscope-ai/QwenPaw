import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { skillApi, invalidateSkillCache } from "./skill";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import { getApiToken, setApiAuthMode, setAuthToken } from "../config";
import { agentsApi } from "./agents";
import { clearAccessSession } from "../authSession";

function identity(id: string) {
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id, username: id, platform_role: "member" } as never,
    accessToken: `session-${id}`,
  });
  setApiAuthMode("multi_user");
  setAuthToken(`session-${id}`);
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [
      { id: "a", enabled: true, access_role: "owner", can_edit: true },
    ] as never,
  });
}
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });

describe("skill transport identity isolation", () => {
  beforeEach(() => {
    identity("alice");
    invalidateSkillCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearAccessSession();
  });

  it("does not reuse the previous actor's installed skills for the same Agent", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json([{ name: "alice-private" }]))
      .mockResolvedValueOnce(json([{ name: "bob-private" }]));
    vi.stubGlobal("fetch", fetch);
    await skillApi.listSkills("a");
    identity("bob");
    expect(await skillApi.listSkills("a")).toEqual([{ name: "bob-private" }]);
  });

  it("rejects late results after a session ends and cannot repopulate the next session cache", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<Response>((r) => {
              resolve = r;
            }),
        )
        .mockResolvedValue(json([{ name: "fresh" }])),
    );
    const pending = skillApi.listSkills("a");
    const result = pending.then(
      () => "leaked",
      () => "discarded",
    );
    clearAccessSession();
    identity("alice");
    resolve(json([{ name: "stale" }]));
    expect(await result).toBe("discarded");
    expect(await skillApi.listSkills("a")).toEqual([{ name: "fresh" }]);
  });

  it("does not refresh or replay a stale write after a late 401", async () => {
    let resolve!: (value: Response) => void;
    const fetch = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((r) => {
            resolve = r;
          }),
      )
      .mockResolvedValue(json({}));
    vi.stubGlobal("fetch", fetch);
    const pending = skillApi.enableSkill("demo").then(
      () => "leaked",
      () => "discarded",
    );
    identity("bob");
    resolve(new Response("", { status: 401 }));
    expect(await pending).toBe("discarded");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("discards late data even when the Agent switches A to B to A", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<Response>((r) => {
              resolve = r;
            }),
        )
        .mockResolvedValue(json([{ name: "fresh-a" }])),
    );
    const pending = skillApi.listSkills("a").then(
      () => "leaked",
      () => "discarded",
    );
    useAgentStore.setState({ selectedAgent: "b" });
    useAgentStore.setState({ selectedAgent: "a" });
    resolve(json([{ name: "old-a" }]));
    expect(await pending).toBe("discarded");
    expect(await skillApi.listSkills("a")).toEqual([{ name: "fresh-a" }]);
  });

  it("retries an expired skill write with T2 while retaining the captured Agent", async () => {
    const sent: Array<{ token: string | null; agent: string | null }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, options: RequestInit) => {
        if (url === "/api/auth/refresh")
          return json({ token: "T2", username: "alice" });
        const headers = new Headers(options.headers);
        sent.push({
          token: headers.get("Authorization"),
          agent: headers.get("X-Agent-Id"),
        });
        return headers.get("Authorization") === "Bearer T2"
          ? new Response(null, { status: 204 })
          : new Response("", { status: 401 });
      }),
    );
    const outcome = await skillApi.enableSkill("demo").then(
      () => "enabled",
      () => "failed",
    );
    expect(sent).toEqual([
      { token: "Bearer session-alice", agent: "a" },
      { token: "Bearer T2", agent: "a" },
    ]);
    expect(outcome).toBe("enabled");
  });

  it.each(["scoped skill", "admin auxiliary"])(
    "preserves B session when %s is waiting for A refresh",
    async (kind) => {
      let finishRefresh!: (value: Response) => void;
      let entered!: () => void;
      const refreshing = new Promise<void>((resolve) => {
        entered = resolve;
      });
      const calls: string[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          calls.push(url);
          if (url === "/api/auth/refresh") {
            entered();
            return new Promise<Response>((resolve) => {
              finishRefresh = resolve;
            });
          }
          return new Response("", { status: 401 });
        }),
      );
      const previousLocation = Object.getOwnPropertyDescriptor(
        window,
        "location",
      )!;
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { pathname: "/skills", search: "", hash: "", href: "/skills" },
      });
      try {
        const pending = (
          kind === "scoped skill"
            ? skillApi.enableSkill("demo")
            : agentsApi.listAdminAgents()
        ).then(
          () => "accepted",
          () => "discarded",
        );
        await refreshing;
        clearAccessSession();
        identity("bob");
        finishRefresh(json({ token: "stale-A-token", username: "alice" }));
        expect(await pending).toBe("discarded");
        expect(getApiToken()).toBe("session-bob");
        expect(window.location.href).toBe("/skills");
        expect(calls).toEqual([
          kind === "scoped skill"
            ? "/api/skills/demo/enable"
            : "/api/admin/agents",
          "/api/auth/refresh",
        ]);
      } finally {
        Object.defineProperty(window, "location", previousLocation);
      }
    },
  );

  it("sends authentication and captured Agent with optimize streams and surfaces server errors", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response('data: {"error":"synthetic_business_error"}\n'),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(
      skillApi.streamOptimizeSkill(
        "text",
        vi.fn(),
        new AbortController().signal,
      ),
    ).rejects.toThrow("synthetic_business_error");
    const headers = new Headers(fetch.mock.calls[0][1].headers);
    expect(headers.get("Authorization")).toBe("Bearer session-alice");
    expect(headers.get("X-Agent-Id")).toBe("a");
  });
});
