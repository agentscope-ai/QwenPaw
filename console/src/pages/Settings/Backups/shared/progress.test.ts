import { describe, it, expect, vi } from "vitest";
import type { BackupProgressEvent } from "@/api/types/backup";
import { handleBackupProgressEvent } from "./progress";

const t = vi.fn((key: string, params?: Record<string, unknown>) =>
  params ? `${key}:${JSON.stringify(params)}` : key,
);

describe("handleBackupProgressEvent", () => {
  it("maps start to progress 0 + starting key", () => {
    t.mockClear();
    const result = handleBackupProgressEvent(
      { type: "start", total_agents: 3, percent: 0 },
      t,
    );
    expect(result).toEqual({ progress: 0, msg: "backup.progressStarting" });
    expect(t).toHaveBeenCalledWith("backup.progressStarting");
  });

  it("maps agent to event.percent and increments index by 1", () => {
    t.mockClear();
    const event: BackupProgressEvent = {
      type: "agent",
      agent_id: "a1",
      index: 2,
      total: 5,
      percent: 40,
    };
    const result = handleBackupProgressEvent(event, t);
    expect(result.progress).toBe(40);
    expect(t).toHaveBeenCalledWith("backup.progressAgent", {
      index: 3,
      total: 5,
    });
    expect(result.msg).toBe('backup.progressAgent:{"index":3,"total":5}');
  });

  it("maps saving to event.percent + saving key", () => {
    t.mockClear();
    const result = handleBackupProgressEvent(
      { type: "saving", percent: 80 },
      t,
    );
    expect(result).toEqual({ progress: 80, msg: "backup.progressSaving" });
  });

  it("maps done to progress 100 + done key", () => {
    t.mockClear();
    const result = handleBackupProgressEvent(
      { type: "done", percent: 100, meta: {} as any },
      t,
    );
    expect(result).toEqual({ progress: 100, msg: "backup.progressDone" });
  });

  it("returns empty msg and progress 0 for unknown event types", () => {
    t.mockClear();
    const result = handleBackupProgressEvent(
      { type: "error", message: "boom" } as unknown as BackupProgressEvent,
      t,
    );
    expect(result).toEqual({ progress: 0, msg: "" });
    expect(t).not.toHaveBeenCalled();
  });
});
