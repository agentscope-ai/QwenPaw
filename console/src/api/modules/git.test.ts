import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { gitApi } from "./git";
import { request } from "../request";

describe("gitApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("status calls GET /workspace/git/status", async () => {
    const status = { branch: "main", changes: [], ahead: 0, behind: 0 };
    vi.mocked(request).mockResolvedValue(status);
    const result = await gitApi.status();
    expect(request).toHaveBeenCalledWith("/workspace/git/status");
    expect(result).toEqual(status);
  });

  it("branches calls GET /workspace/git/branches", async () => {
    const branches = [{ name: "main", current: true, remote: false }];
    vi.mocked(request).mockResolvedValue(branches);
    const result = await gitApi.branches();
    expect(request).toHaveBeenCalledWith("/workspace/git/branches");
    expect(result).toEqual(branches);
  });

  it("checkout sends POST with branch and create=false by default", async () => {
    await gitApi.checkout("feature/x");
    expect(request).toHaveBeenCalledWith("/workspace/git/checkout", {
      method: "POST",
      body: JSON.stringify({ branch: "feature/x", create: false }),
    });
  });

  it("checkout sends create=true when create flag set", async () => {
    await gitApi.checkout("feature/y", true);
    expect(request).toHaveBeenCalledWith("/workspace/git/checkout", {
      method: "POST",
      body: JSON.stringify({ branch: "feature/y", create: true }),
    });
  });

  it("diff with no args produces empty query string", async () => {
    await gitApi.diff();
    expect(request).toHaveBeenCalledWith("/workspace/git/diff?");
  });

  it("diff with path and staged adds both params", async () => {
    await gitApi.diff("src/a.ts", true);
    expect(request).toHaveBeenCalledWith(
      "/workspace/git/diff?path=src%2Fa.ts&staged=true",
    );
  });

  it("diff with all params adds path, staged and untracked", async () => {
    await gitApi.diff("src/b.ts", true, true);
    expect(request).toHaveBeenCalledWith(
      "/workspace/git/diff?path=src%2Fb.ts&staged=true&untracked=true",
    );
  });

  it("stage sends POST with paths body", async () => {
    await gitApi.stage(["a.ts", "b.ts"]);
    expect(request).toHaveBeenCalledWith("/workspace/git/stage", {
      method: "POST",
      body: JSON.stringify({ paths: ["a.ts", "b.ts"] }),
    });
  });

  it("commit sends POST with message body", async () => {
    await gitApi.commit("fix: handle null");
    expect(request).toHaveBeenCalledWith("/workspace/git/commit", {
      method: "POST",
      body: JSON.stringify({ message: "fix: handle null" }),
    });
  });

  it("log uses default limit of 20", async () => {
    await gitApi.log();
    expect(request).toHaveBeenCalledWith("/workspace/git/log?limit=20");
  });

  it("commitDiff URL-encodes hash containing slash", async () => {
    await gitApi.commitDiff("abc/def");
    expect(request).toHaveBeenCalledWith(
      `/workspace/git/commit-diff?commit_hash=${encodeURIComponent("abc/def")}`,
    );
    expect(request).toHaveBeenCalledWith(
      "/workspace/git/commit-diff?commit_hash=abc%2Fdef",
    );
  });

  it("revert sends POST with commit_hash body", async () => {
    await gitApi.revert("abc123");
    expect(request).toHaveBeenCalledWith("/workspace/git/revert", {
      method: "POST",
      body: JSON.stringify({ commit_hash: "abc123" }),
    });
  });
});
