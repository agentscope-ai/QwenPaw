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
