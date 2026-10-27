/**
 * Contract tests for the `checkpointsApi` members that the existing
 * `checkpoints.test.ts` deliberately leaves out: `status`, `graph`, `setAuto`,
 * `snapshot` and `reset`.
 *
 * Division of labour (no overlap with the existing file):
 *   - `checkpoints.test.ts` pins restore preview / restore confirm / GC preview
 *     / GC run / GC settings read + update.
 *   - this file pins the status + graph reads, the auto-checkpoint switch, the
 *     manual snapshot POST, and the destructive `reset` DELETE.
 *
 * The existing file is left untouched on purpose - a second test file for the
 * same module is an established pattern in this repo, and it removes any chance
 * of clobbering somebody else's lines while appending.
 *
 * Assertions are about the frontend contract only: the exact path (including
 * how the `limit` query parameter is interpolated), the HTTP verb, the serialised
 * body, the long timeout used by the destructive operations, and AbortSignal
 * forwarding. Backend behaviour is out of scope.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { request } from "../request";
import { checkpointsApi } from "./checkpoints";

vi.mock("../request", () => ({ request: vi.fn() }));

const BASE = "/workspace/checkpoints";

describe("checkpointsApi.status", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("GETs the status endpoint with no options when no signal is given", async () => {
    const status = { auto_enabled: true, count: 4 };
    vi.mocked(request).mockResolvedValue(status);

    await expect(checkpointsApi.status()).resolves.toEqual(status);
    expect(request).toHaveBeenCalledWith(`${BASE}/status`, {
      signal: undefined,
    });
  });

  it("forwards the caller AbortSignal so polling can be cancelled", async () => {
    vi.mocked(request).mockResolvedValue({});
    const controller = new AbortController();

    await checkpointsApi.status(controller.signal);

    expect(request).toHaveBeenCalledWith(`${BASE}/status`, {
      signal: controller.signal,
    });
  });

  it("propagates a request rejection to the caller", async () => {
    vi.mocked(request).mockRejectedValueOnce(new Error("aborted"));

    await expect(checkpointsApi.status()).rejects.toThrow("aborted");
  });
});

describe("checkpointsApi.graph", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("defaults the limit query parameter to 500", async () => {
    vi.mocked(request).mockResolvedValue({ nodes: [], edges: [] });

    await checkpointsApi.graph();

    expect(request).toHaveBeenCalledWith(`${BASE}/graph?limit=500`, {
      signal: undefined,
    });
  });

  it("interpolates an explicit limit into the query string", async () => {
    vi.mocked(request).mockResolvedValue({ nodes: [], edges: [] });

    await checkpointsApi.graph(25);

    expect(request).toHaveBeenCalledWith(`${BASE}/graph?limit=25`, {
      signal: undefined,
    });
  });

  it("passes a zero limit through instead of falling back to the default", async () => {
    vi.mocked(request).mockResolvedValue({ nodes: [], edges: [] });

    // `limit = 500` is a default parameter, so an explicit 0 must survive it.
    await checkpointsApi.graph(0);

    expect(request).toHaveBeenCalledWith(`${BASE}/graph?limit=0`, {
      signal: undefined,
    });
  });

  it("forwards both an explicit limit and an AbortSignal", async () => {
    vi.mocked(request).mockResolvedValue({ nodes: [], edges: [] });
    const controller = new AbortController();

    await checkpointsApi.graph(1000, controller.signal);

    expect(request).toHaveBeenCalledWith(`${BASE}/graph?limit=1000`, {
      signal: controller.signal,
    });
  });

  it("resolves with the parsed graph payload", async () => {
    const graph = { nodes: [{ id: "a" }], edges: [] };
    vi.mocked(request).mockResolvedValue(graph);

    await expect(checkpointsApi.graph(2)).resolves.toEqual(graph);
  });
});

describe("checkpointsApi.setAuto", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("PATCHes the auto endpoint with enabled true", async () => {
    vi.mocked(request).mockResolvedValue({ auto_enabled: true });

    await checkpointsApi.setAuto(true);

    expect(request).toHaveBeenCalledWith(`${BASE}/auto`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: true }),
    });
  });

  it("PATCHes the auto endpoint with enabled false", async () => {
    vi.mocked(request).mockResolvedValue({ auto_enabled: false });

    await checkpointsApi.setAuto(false);

    // A falsy flag must still be serialised, never dropped.
    expect(request).toHaveBeenCalledWith(`${BASE}/auto`, {
      method: "PATCH",
      body: JSON.stringify({ enabled: false }),
    });
  });

  it("resolves with the server echo of the new switch state", async () => {
    vi.mocked(request).mockResolvedValue({ auto_enabled: true });

    await expect(checkpointsApi.setAuto(true)).resolves.toEqual({
      auto_enabled: true,
    });
  });

  it("does not send a timeout override for the switch", async () => {
    vi.mocked(request).mockResolvedValue({ auto_enabled: true });

    await checkpointsApi.setAuto(true);

    const init = vi.mocked(request).mock.calls[0][1] as Record<string, unknown>;
    expect(init.timeout).toBeUndefined();
  });
});

describe("checkpointsApi.snapshot", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("POSTs the four required identity fields verbatim", async () => {
    vi.mocked(request).mockResolvedValue({ ref: "refs/ckpt/1", commit: "c1" });
    const body = {
      session_id: "session-1",
      user_id: "user-1",
      channel: "console",
      name: "before upgrade",
    };

    await checkpointsApi.snapshot(body);

    expect(request).toHaveBeenCalledWith(`${BASE}/snapshot`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  });

  it("keeps key order stable because JSON.stringify follows insertion order", async () => {
    vi.mocked(request).mockResolvedValue({ ref: "r", commit: "c" });

    await checkpointsApi.snapshot({
      name: "n",
      channel: "telegram",
      user_id: "u",
      session_id: "s",
    });

    expect(request).toHaveBeenCalledWith(
      `${BASE}/snapshot`,
      expect.objectContaining({
        body: JSON.stringify({
          name: "n",
          channel: "telegram",
          user_id: "u",
          session_id: "s",
        }),
      }),
    );
  });

  it("serialises a non-ASCII snapshot name without escaping it away", async () => {
    vi.mocked(request).mockResolvedValue({ ref: "r", commit: "c" });
    const body = {
      session_id: "s",
      user_id: "u",
      channel: "console",
      name: "升级前备份 🗂️",
    };

    await checkpointsApi.snapshot(body);

    const init = vi.mocked(request).mock.calls[0][1] as { body: string };
    expect(JSON.parse(init.body)).toEqual(body);
    expect(init.body).toContain("升级前备份");
  });

  it("resolves with the created ref and commit", async () => {
    vi.mocked(request).mockResolvedValue({
      ref: "refs/ckpt/9",
      commit: "deadbeef",
    });

    await expect(
      checkpointsApi.snapshot({
        session_id: "s",
        user_id: "u",
        channel: "console",
        name: "n",
      }),
    ).resolves.toEqual({ ref: "refs/ckpt/9", commit: "deadbeef" });
  });

  it("propagates a failed snapshot instead of swallowing it", async () => {
    vi.mocked(request).mockRejectedValueOnce(new Error("checkpoint failed"));

    await expect(
      checkpointsApi.snapshot({
        session_id: "s",
        user_id: "u",
        channel: "console",
        name: "n",
      }),
    ).rejects.toThrow("checkpoint failed");
  });
});

describe("checkpointsApi.reset", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("DELETEs the collection root - not a sub-path", async () => {
    vi.mocked(request).mockResolvedValue({ reset: true, auto_enabled: false });

    await checkpointsApi.reset();

    expect(request).toHaveBeenCalledWith(BASE, {
      method: "DELETE",
      timeout: 120_000,
    });
  });

  it("sends no body with the destructive verb", async () => {
    vi.mocked(request).mockResolvedValue({ reset: true, auto_enabled: true });

    await checkpointsApi.reset();

    const init = vi.mocked(request).mock.calls[0][1] as Record<string, unknown>;
    expect(init.body).toBeUndefined();
  });

  it("pins the long timeout so a slow prune is not cut short", async () => {
    vi.mocked(request).mockResolvedValue({ reset: true, auto_enabled: true });

    await checkpointsApi.reset();

    expect(request).toHaveBeenCalledWith(
      BASE,
      expect.objectContaining({ timeout: 120_000 }),
    );
  });

  it("resolves with both flags reported by the server", async () => {
    vi.mocked(request).mockResolvedValue({ reset: true, auto_enabled: false });

    await expect(checkpointsApi.reset()).resolves.toEqual({
      reset: true,
      auto_enabled: false,
    });
  });

  it("propagates a failed reset", async () => {
    vi.mocked(request).mockRejectedValueOnce(new Error("reset refused"));

    await expect(checkpointsApi.reset()).rejects.toThrow("reset refused");
  });
});
