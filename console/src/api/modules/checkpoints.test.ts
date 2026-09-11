import { beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "../request";
import { checkpointsApi } from "./checkpoints";

vi.mock("../request", () => ({ request: vi.fn() }));

describe("checkpointsApi", () => {
  beforeEach(() => vi.mocked(request).mockReset());

  it("previews a restore without changing its pinned commit", async () => {
    vi.mocked(request).mockResolvedValue({});
    const body = {
      commit: "a".repeat(40),
      session_id: "session",
      user_id: "user",
      channel: "console",
      include_memory: true,
      include_files: false,
    };

    await checkpointsApi.previewRestore(body);

    expect(request).toHaveBeenCalledWith(
      "/workspace/checkpoints/restore/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  });

  it("sends selected files only to the confirm endpoint", async () => {
    vi.mocked(request).mockResolvedValue({});
    const body = {
      commit: "b".repeat(40),
      session_id: "session",
      user_id: "user",
      channel: "console",
      include_memory: false,
      include_files: true,
      files: ["src/app.ts"],
    };

    await checkpointsApi.restore(body);

    expect(request).toHaveBeenCalledWith(
      "/workspace/checkpoints/restore",
      expect.objectContaining({ body: JSON.stringify(body) }),
    );
  });

  it("uses retention GC by default and compact GC only when explicit", async () => {
    vi.mocked(request).mockResolvedValue({});

    await checkpointsApi.previewGc();
    await checkpointsApi.gc({ compact: true });

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/workspace/checkpoints/gc/preview",
      expect.objectContaining({ body: "{}" }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/workspace/checkpoints/gc",
      expect.objectContaining({ body: JSON.stringify({ compact: true }) }),
    );
  });

  it("reads and updates automatic cleanup settings", async () => {
    vi.mocked(request).mockResolvedValue({});
    const settings = {
      gc_keep_count: 30,
      gc_keep_days: 14,
      pre_restore_retention_days: 5,
    };

    await checkpointsApi.getGcSettings();
    await checkpointsApi.updateGcSettings(settings);

    expect(request).toHaveBeenNthCalledWith(
      1,
      "/workspace/checkpoints/gc/settings",
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/workspace/checkpoints/gc/settings",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify(settings),
      }),
    );
  });
});
