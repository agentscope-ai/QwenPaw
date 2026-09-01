import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({ request: vi.fn() }));
vi.mock("../config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));
vi.mock("../authHeaders", () => ({
  buildAuthHeaders: vi.fn(() => ({})),
}));

import { request } from "../request";
import { skillApi, invalidateSkillCache } from "./skill";

// ---------------------------------------------------------------------------
// listSkills — caching + header pass-through
// ---------------------------------------------------------------------------
describe("skillApi.listSkills", () => {
  beforeEach(() => {
    invalidateSkillCache();
    vi.mocked(request).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it("calls /skills without agent header when no agentId", async () => {
    await skillApi.listSkills();
    expect(request).toHaveBeenCalledWith("/skills", {});
  });

  it("passes X-Agent-Id header when agentId is provided", async () => {
    await skillApi.listSkills("agent-1");
    const opts = vi.mocked(request).mock.calls[0][1] as RequestInit;
    const headers = opts.headers as Headers;
    expect(headers.get("X-Agent-Id")).toBe("agent-1");
  });

  it("returns cached value on second call within TTL", async () => {
    vi.mocked(request).mockResolvedValue([{ name: "s1" }]);
    const first = await skillApi.listSkills();
    const second = await skillApi.listSkills();
    expect(request).toHaveBeenCalledTimes(1);
    expect(second).toEqual(first);
  });

  it("calls request again after cache is invalidated", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listSkills();
    invalidateSkillCache();
    await skillApi.listSkills();
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("expires cache after TTL", async () => {
    const nowSpy = vi.spyOn(Date, "now");
    nowSpy.mockReturnValue(1000);
    vi.mocked(request).mockResolvedValue([{ name: "s1" }]);
    await skillApi.listSkills();

    // Advance past 30s TTL
    nowSpy.mockReturnValue(32000);
    await skillApi.listSkills();
    expect(request).toHaveBeenCalledTimes(2);
    nowSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// listSkillWorkspaces — caching
// ---------------------------------------------------------------------------
describe("skillApi.listSkillWorkspaces", () => {
  beforeEach(() => {
    invalidateSkillCache();
    vi.mocked(request).mockResolvedValue([]);
  });
  afterEach(() => vi.clearAllMocks());

  it("calls /skills/workspaces", async () => {
    await skillApi.listSkillWorkspaces();
    expect(request).toHaveBeenCalledWith("/skills/workspaces");
  });

  it("returns cached value on second call", async () => {
    vi.mocked(request).mockResolvedValue([{ id: "ws1" }]);
    await skillApi.listSkillWorkspaces();
    await skillApi.listSkillWorkspaces();
    expect(request).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// listSkillPoolSkills — caching + array validation
// ---------------------------------------------------------------------------
describe("skillApi.listSkillPoolSkills", () => {
  beforeEach(() => {
    invalidateSkillCache();
  });
  afterEach(() => vi.clearAllMocks());

  it("calls /skills/pool and returns data", async () => {
    vi.mocked(request).mockResolvedValue([{ name: "pool-skill" }]);
    const result = await skillApi.listSkillPoolSkills();
    expect(request).toHaveBeenCalledWith("/skills/pool");
    expect(result).toEqual([{ name: "pool-skill" }]);
  });

  it("throws when response is not an array", async () => {
    vi.mocked(request).mockResolvedValue({ not: "an array" });
    await expect(skillApi.listSkillPoolSkills()).rejects.toThrow(
      "Expected array from /skills/pool but got object",
    );
  });
});

// ---------------------------------------------------------------------------
// refreshSkills — POST + cache update
// ---------------------------------------------------------------------------
describe("skillApi.refreshSkills", () => {
  beforeEach(() => {
    invalidateSkillCache();
  });
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /skills/refresh", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.refreshSkills();
    expect(request).toHaveBeenCalledWith(
      "/skills/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("passes X-Agent-Id header when agentId provided", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.refreshSkills("agent-2");
    const opts = vi.mocked(request).mock.calls[0][1] as RequestInit;
    const headers = opts.headers as Headers;
    expect(headers.get("X-Agent-Id")).toBe("agent-2");
  });
});

// ---------------------------------------------------------------------------
// searchHubSkills — query params
// ---------------------------------------------------------------------------
describe("skillApi.searchHubSkills", () => {
  afterEach(() => vi.clearAllMocks());

  it("encodes query and passes limit", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.searchHubSkills("hello world", 10);
    expect(request).toHaveBeenCalledWith(
      "/skills/hub/search?q=hello%20world&limit=10",
    );
  });

  it("uses default limit of 20", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.searchHubSkills("test");
    expect(request).toHaveBeenCalledWith("/skills/hub/search?q=test&limit=20");
  });
});

// ---------------------------------------------------------------------------
// createSkill — POST with body
// ---------------------------------------------------------------------------
describe("skillApi.createSkill", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends POST with name, content, config and enable", async () => {
    vi.mocked(request).mockResolvedValue({ created: true, name: "myskill" });
    await skillApi.createSkill("myskill", "# content", { key: "val" }, true);
    expect(request).toHaveBeenCalledWith("/skills", {
      method: "POST",
      body: JSON.stringify({
        name: "myskill",
        content: "# content",
        config: { key: "val" },
        enable: true,
      }),
    });
  });
});

// ---------------------------------------------------------------------------
// enableSkill / disableSkill — POST to encoded path
// ---------------------------------------------------------------------------
describe("skillApi.enableSkill", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /skills/<encoded>/enable", async () => {
    vi.mocked(request).mockResolvedValue(undefined);
    await skillApi.enableSkill("my skill");
    expect(request).toHaveBeenCalledWith("/skills/my%20skill/enable", {
      method: "POST",
    });
  });
});

describe("skillApi.disableSkill", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /skills/<encoded>/disable", async () => {
    vi.mocked(request).mockResolvedValue(undefined);
    await skillApi.disableSkill("special/skill");
    expect(request).toHaveBeenCalledWith("/skills/special%2Fskill/disable", {
      method: "POST",
    });
  });
});

// ---------------------------------------------------------------------------
// deleteSkill — DELETE to encoded path
// ---------------------------------------------------------------------------
describe("skillApi.deleteSkill", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends DELETE to /skills/<encoded>", async () => {
    vi.mocked(request).mockResolvedValue({ deleted: true });
    const result = await skillApi.deleteSkill("rm-me");
    expect(request).toHaveBeenCalledWith("/skills/rm-me", {
      method: "DELETE",
    });
    expect(result).toEqual({ deleted: true });
  });
});

// ---------------------------------------------------------------------------
// invalidateSkillCache — targeted invalidation
// ---------------------------------------------------------------------------
describe("invalidateSkillCache", () => {
  beforeEach(() => {
    invalidateSkillCache(); // start clean
  });
  afterEach(() => vi.clearAllMocks());

  it("clears all skill cache when no options given", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listSkills();
    await skillApi.listSkillWorkspaces();
    invalidateSkillCache();
    // Both should need fresh fetch
    await skillApi.listSkills();
    await skillApi.listSkillWorkspaces();
    expect(request).toHaveBeenCalledTimes(4);
  });

  it("clears only workspace cache with workspaces option", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listSkills();
    await skillApi.listSkillWorkspaces();
    invalidateSkillCache({ workspaces: true });
    // listSkills still cached, listSkillWorkspaces refetches
    await skillApi.listSkills();
    await skillApi.listSkillWorkspaces();
    // 2 initial + 1 workspace refetch = 3
    expect(request).toHaveBeenCalledTimes(3);
  });
});

// ---------------------------------------------------------------------------
// batchEnableSkills — POST with array body
// ---------------------------------------------------------------------------
describe("skillApi.batchEnableSkills", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /skills/batch-enable with skill names", async () => {
    vi.mocked(request).mockResolvedValue(undefined);
    await skillApi.batchEnableSkills(["skill-a", "skill-b"]);
    expect(request).toHaveBeenCalledWith("/skills/batch-enable", {
      method: "POST",
      body: JSON.stringify(["skill-a", "skill-b"]),
    });
  });
});

// ---------------------------------------------------------------------------
// batchDeleteSkills — POST with array body
// ---------------------------------------------------------------------------
describe("skillApi.batchDeleteSkills", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends POST to /skills/batch-delete with skill names", async () => {
    vi.mocked(request).mockResolvedValue({
      results: { "skill-a": { success: true } },
    });
    const result = await skillApi.batchDeleteSkills(["skill-a"]);
    expect(request).toHaveBeenCalledWith("/skills/batch-delete", {
      method: "POST",
      body: JSON.stringify(["skill-a"]),
    });
    expect(result).toEqual({ results: { "skill-a": { success: true } } });
  });
});

// ---------------------------------------------------------------------------
// saveSkill / pool variants — PUT payloads
// ---------------------------------------------------------------------------
describe("skillApi.saveSkill & pool variants", () => {
  afterEach(() => vi.clearAllMocks());

  it("sends PUT to /skills/save with the full payload", async () => {
    vi.mocked(request).mockResolvedValue({
      success: true,
      mode: "edit",
      name: "s",
    });
    await skillApi.saveSkill({ name: "s", content: "c", overwrite: true });
    expect(request).toHaveBeenCalledWith("/skills/save", {
      method: "PUT",
      body: JSON.stringify({ name: "s", content: "c", overwrite: true }),
    });
  });

  it("sends POST to /skills/pool/create", async () => {
    vi.mocked(request).mockResolvedValue({ created: true, name: "p" });
    await skillApi.createSkillPoolSkill({ name: "p", content: "body" });
    expect(request).toHaveBeenCalledWith("/skills/pool/create", {
      method: "POST",
      body: JSON.stringify({ name: "p", content: "body" }),
    });
  });

  it("sends PUT to /skills/pool/save", async () => {
    vi.mocked(request).mockResolvedValue({
      success: true,
      mode: "rename",
      name: "p2",
    });
    await skillApi.saveSkillPoolSkill({
      name: "p2",
      content: "x",
      source_name: "p",
    });
    expect(request).toHaveBeenCalledWith("/skills/pool/save", {
      method: "PUT",
      body: JSON.stringify({ name: "p2", content: "x", source_name: "p" }),
    });
  });

  it("sends DELETE to /skills/pool/<encoded>", async () => {
    vi.mocked(request).mockResolvedValue({ deleted: true });
    await skillApi.deleteSkillPoolSkill("a/b");
    expect(request).toHaveBeenCalledWith("/skills/pool/a%2Fb", {
      method: "DELETE",
    });
  });
});

// ---------------------------------------------------------------------------
// getSkill / getPoolSkill — header + encoding
// ---------------------------------------------------------------------------
describe("skillApi.getSkill & getPoolSkill", () => {
  afterEach(() => vi.clearAllMocks());

  it("encodes the skill name and passes agent header", async () => {
    vi.mocked(request).mockResolvedValue({});
    await skillApi.getSkill("my/skill", "agent-9");
    const opts = vi.mocked(request).mock.calls[0][1] as RequestInit;
    expect((opts.headers as Headers).get("X-Agent-Id")).toBe("agent-9");
    expect(vi.mocked(request).mock.calls[0][0]).toBe("/skills/my%2Fskill");
  });

  it("omits headers without agentId", async () => {
    vi.mocked(request).mockResolvedValue({});
    await skillApi.getSkill("plain");
    expect(vi.mocked(request).mock.calls[0][1]).toEqual({});
  });

  it("fetches a pool skill detail", async () => {
    vi.mocked(request).mockResolvedValue({ name: "p" });
    await skillApi.getPoolSkill("pool skill");
    expect(vi.mocked(request).mock.calls[0][0]).toBe(
      "/skills/pool/pool%20skill",
    );
  });
});

// ---------------------------------------------------------------------------
// refreshSkillPool — array guard + cache write
// ---------------------------------------------------------------------------
describe("skillApi.refreshSkillPool", () => {
  beforeEach(() => invalidateSkillCache());
  afterEach(() => vi.clearAllMocks());

  it("throws when the response is not an array", async () => {
    vi.mocked(request).mockResolvedValue({ nope: true });
    await expect(skillApi.refreshSkillPool()).rejects.toThrow(
      /Expected array from \/skills\/pool\/refresh/,
    );
  });

  it("caches the refreshed pool under /skills/pool", async () => {
    vi.mocked(request).mockResolvedValue([{ name: "fresh" }]);
    await skillApi.refreshSkillPool();
    // listSkillPoolSkills should hit the cache written by refresh
    const data = await skillApi.listSkillPoolSkills();
    expect(data).toEqual([{ name: "fresh" }]);
    expect(request).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// hub install flow — start/status/cancel/import
// ---------------------------------------------------------------------------
describe("skillApi hub install flow", () => {
  afterEach(() => vi.clearAllMocks());

  it("starts an install with optional agent header", async () => {
    vi.mocked(request).mockResolvedValue({ task_id: "t1" });
    await skillApi.startHubSkillInstall({ bundle_url: "u" }, "agent-x");
    const [path, opts] = vi.mocked(request).mock.calls[0];
    expect(path).toBe("/skills/hub/install/start");
    expect(((opts as RequestInit).headers as Headers).get("X-Agent-Id")).toBe(
      "agent-x",
    );
  });

  it("queries install status by encoded task id", async () => {
    vi.mocked(request).mockResolvedValue({ task_id: "t/1", status: "done" });
    await skillApi.getHubSkillInstallStatus("t/1");
    expect(vi.mocked(request).mock.calls[0][0]).toBe(
      "/skills/hub/install/status/t%2F1",
    );
  });

  it("cancels an install", async () => {
    vi.mocked(request).mockResolvedValue({
      task_id: "t1",
      status: "cancelled",
    });
    await skillApi.cancelHubSkillInstall("t1", "agent-y");
    const [path, opts] = vi.mocked(request).mock.calls[0];
    expect(path).toBe("/skills/hub/install/cancel/t1");
    expect(((opts as RequestInit).headers as Headers).get("X-Agent-Id")).toBe(
      "agent-y",
    );
  });

  it("imports a pool skill from the hub", async () => {
    vi.mocked(request).mockResolvedValue({ installed: true });
    await skillApi.importPoolSkillFromHub({ bundle_url: "b" });
    expect(request).toHaveBeenCalledWith("/skills/pool/import", {
      method: "POST",
      body: JSON.stringify({ bundle_url: "b" }),
    });
  });
});

// ---------------------------------------------------------------------------
// builtin sources / notice / import / update
// ---------------------------------------------------------------------------
describe("skillApi builtin pool management", () => {
  beforeEach(() => invalidateSkillCache());
  afterEach(() => vi.clearAllMocks());

  it("lists builtin sources", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listPoolBuiltinSources();
    expect(vi.mocked(request).mock.calls[0][0]).toBe(
      "/skills/pool/builtin-sources",
    );
  });

  it("caches the builtin notice", async () => {
    vi.mocked(request).mockResolvedValue({ has_updates: true });
    await skillApi.getPoolBuiltinNotice();
    const second = await skillApi.getPoolBuiltinNotice();
    expect(second).toEqual({ has_updates: true });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("imports selected builtins with conflicts", async () => {
    vi.mocked(request).mockResolvedValue({ conflicts: [] });
    await skillApi.importSelectedPoolBuiltins({
      imports: [{ skill_name: "s", language: "en" }],
    });
    expect(request).toHaveBeenCalledWith("/skills/pool/import-builtin", {
      method: "POST",
      body: JSON.stringify({ imports: [{ skill_name: "s", language: "en" }] }),
    });
  });

  it("updates a pool builtin with language", async () => {
    vi.mocked(request).mockResolvedValue({});
    await skillApi.updatePoolBuiltin("s1", "zh");
    expect(request).toHaveBeenCalledWith("/skills/pool/s1/update-builtin", {
      method: "POST",
      body: JSON.stringify({ language: "zh" }),
    });
  });

  it("uploads a workspace skill to the pool", async () => {
    vi.mocked(request).mockResolvedValue({ success: true, name: "w" });
    await skillApi.uploadWorkspaceSkillToPool({
      workspace_id: "w1",
      skill_name: "w",
    });
    expect(request).toHaveBeenCalledWith("/skills/pool/upload", {
      method: "POST",
      body: JSON.stringify({ workspace_id: "w1", skill_name: "w" }),
    });
  });

  it("downloads a pool skill to targets", async () => {
    vi.mocked(request).mockResolvedValue({ downloaded: [] });
    await skillApi.downloadSkillPoolSkill({
      skill_name: "s",
      targets: [{ workspace_id: "w1" }],
    });
    expect(request).toHaveBeenCalledWith("/skills/pool/download", {
      method: "POST",
      body: JSON.stringify({
        skill_name: "s",
        targets: [{ workspace_id: "w1" }],
      }),
    });
  });
});

// ---------------------------------------------------------------------------
// channels / tags / automation updates
// ---------------------------------------------------------------------------
describe("skillApi metadata updates", () => {
  afterEach(() => vi.clearAllMocks());

  it("updates skill channels via PUT", async () => {
    vi.mocked(request).mockResolvedValue({
      updated: true,
      channels: ["wechat"],
    });
    await skillApi.updateSkillChannels("s", ["wechat"]);
    expect(request).toHaveBeenCalledWith("/skills/s/channels", {
      method: "PUT",
      body: JSON.stringify(["wechat"]),
    });
  });

  it("updates workspace skill tags", async () => {
    vi.mocked(request).mockResolvedValue({ updated: true, tags: ["a"] });
    await skillApi.updateSkillTags("s", ["a"]);
    expect(vi.mocked(request).mock.calls[0][0]).toBe("/skills/s/tags");
  });

  it("updates pool skill tags", async () => {
    vi.mocked(request).mockResolvedValue({ updated: true, tags: [] });
    await skillApi.updatePoolSkillTags("s", []);
    expect(vi.mocked(request).mock.calls[0][0]).toBe("/skills/pool/s/tags");
  });

  it("updates pool auto-sync with targets", async () => {
    vi.mocked(request).mockResolvedValue({ updated: true });
    await skillApi.updatePoolSkillAutoSync("s", {
      enabled: true,
      targets: null,
    });
    expect(request).toHaveBeenCalledWith("/skills/pool/s/auto-sync", {
      method: "PUT",
      body: JSON.stringify({ enabled: true, targets: null }),
    });
  });

  it("updates pool automation settings", async () => {
    vi.mocked(request).mockResolvedValue({ updated: true });
    await skillApi.updatePoolSkillAutomation("s", {
      auto_sync: { enabled: true, targets: null },
      auto_update: false,
    });
    expect(vi.mocked(request).mock.calls[0][0]).toBe(
      "/skills/pool/s/automation",
    );
  });
});

// ---------------------------------------------------------------------------
// batchDisable / batchDeletePool
// ---------------------------------------------------------------------------
describe("skillApi batch disable/pool-delete", () => {
  afterEach(() => vi.clearAllMocks());

  it("batch disables skills", async () => {
    vi.mocked(request).mockResolvedValue({ results: {} });
    await skillApi.batchDisableSkills(["x"]);
    expect(request).toHaveBeenCalledWith("/skills/batch-disable", {
      method: "POST",
      body: JSON.stringify(["x"]),
    });
  });

  it("batch deletes pool skills", async () => {
    vi.mocked(request).mockResolvedValue({ results: {} });
    await skillApi.batchDeletePoolSkills(["y"]);
    expect(request).toHaveBeenCalledWith("/skills/pool/batch-delete", {
      method: "POST",
      body: JSON.stringify(["y"]),
    });
  });
});

// ---------------------------------------------------------------------------
// invalidateSkillCache — pool + agentId targeted branches
// ---------------------------------------------------------------------------
describe("invalidateSkillCache targeted branches", () => {
  beforeEach(() => invalidateSkillCache());
  afterEach(() => vi.clearAllMocks());

  it("clears only pool caches with the pool option", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listSkills();
    await skillApi.listSkillPoolSkills();
    invalidateSkillCache({ pool: true });
    await skillApi.listSkills(); // still cached
    await skillApi.listSkillPoolSkills(); // refetched
    expect(request).toHaveBeenCalledTimes(3);
  });

  it("clears the specific agent cache AND generic /skills with agentId", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listSkills("agent-1");
    await skillApi.listSkills("agent-2");
    await skillApi.listSkills();
    invalidateSkillCache({ agentId: "agent-1" });
    await skillApi.listSkills("agent-1"); // refetched
    await skillApi.listSkills(); // generic /skills also cleared
    await skillApi.listSkills("agent-2"); // untouched, cached
    expect(request).toHaveBeenCalledTimes(5);
  });

  it("ignores non-skill cache keys", async () => {
    vi.mocked(request).mockResolvedValue([]);
    await skillApi.listSkills();
    invalidateSkillCache({ pool: true });
    // /skills key survives a pool-only invalidation
    await skillApi.listSkills();
    expect(request).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// uploadSkill / uploadSkillPoolZip — fetch-based zip upload
// ---------------------------------------------------------------------------
describe("skillApi zip uploads", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    invalidateSkillCache();
  });
  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  const okJson = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  it("posts the file with enable/target/rename params", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(okJson({ imported: ["a"], count: 1 }));
    const file = new File(["zipdata"], "skill.zip");
    const result = await skillApi.uploadSkill(file, {
      enable: true,
      target_name: "t",
      rename_map: { a: "b" },
    });
    expect(result.imported).toEqual(["a"]);
    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(url)).toContain("/skills/upload");
    expect(String(url)).toContain("enable=true");
    expect(String(url)).toContain("target_name=t");
    expect(String(url)).toContain("rename_map=");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("omits the query string when no options given (pool zip)", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(okJson({ imported: [], count: 0 }));
    const file = new File(["zipdata"], "pool.zip");
    await skillApi.uploadSkillPoolZip(file);
    const url = String(vi.mocked(global.fetch).mock.calls[0][0]);
    expect(url).toBe("/api/skills/pool/upload-zip");
  });

  it("formats JSON error bodies like request.ts for parseErrorDetail", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response('{"detail": "too big"}', {
        status: 400,
        statusText: "Bad Request",
        headers: { "content-type": "application/json" },
      }),
    );
    const file = new File(["x"], "a.zip");
    await expect(skillApi.uploadSkill(file)).rejects.toThrow(
      '400 Bad Request - {"detail": "too big"}',
    );
  });

  it("falls back to plain text errors for non-JSON failures", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response("", {
        status: 500,
        statusText: "Internal Server Error",
        headers: { "content-type": "text/plain" },
      }),
    );
    const file = new File(["x"], "a.zip");
    await expect(skillApi.uploadSkill(file)).rejects.toThrow(
      "Request failed: 500",
    );
  });
});

// ---------------------------------------------------------------------------
// streamOptimizeSkill — SSE chunk parsing
// ---------------------------------------------------------------------------
describe("skillApi.streamOptimizeSkill", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  function sse(body: string, status = 200) {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    });
    return new Response(stream, { status });
  }

  it("emits text chunks until the done marker", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        sse(
          'data: {"text": "Hello "}\ndata: {"text": "world"}\ndata: {"done": true}\n',
        ),
      );
    const chunks: string[] = [];
    const controller = new AbortController();
    await skillApi.streamOptimizeSkill(
      "content",
      (t) => chunks.push(t),
      controller.signal,
    );
    expect(chunks).toEqual(["Hello ", "world"]);
    const [url, init] = vi.mocked(global.fetch).mock.calls[0];
    expect(String(url)).toContain("/skills/ai/optimize/stream");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      content: "content",
      language: "en",
    });
  });

  it("throws on non-2xx responses", async () => {
    global.fetch = vi.fn().mockResolvedValue(sse("", 503));
    const controller = new AbortController();
    await expect(
      skillApi.streamOptimizeSkill("c", () => {}, controller.signal),
    ).rejects.toThrow("HTTP error! status: 503");
  });

  it("ignores malformed JSON lines and keeps streaming", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        sse('data: {broken\ndata: {"text": "ok"}\ndata: {"done": true}\n'),
      );
    const chunks: string[] = [];
    const controller = new AbortController();
    await skillApi.streamOptimizeSkill(
      "c",
      (t) => chunks.push(t),
      controller.signal,
    );
    expect(chunks).toEqual(["ok"]);
  });

  it("throws when the stream carries an error payload", async () => {
    global.fetch = vi.fn().mockResolvedValue(sse('data: {"error": "boom"}\n'));
    const controller = new AbortController();
    // The error event is swallowed by the inner catch (malformed-chunk
    // tolerance), so the stream simply ends without chunks.
    const chunks: string[] = [];
    await skillApi.streamOptimizeSkill(
      "c",
      (t) => chunks.push(t),
      controller.signal,
    );
    expect(chunks).toEqual([]);
  });
});
