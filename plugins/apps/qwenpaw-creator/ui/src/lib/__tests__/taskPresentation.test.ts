import { describe, expect, it } from "vitest";
import { taskErrorMessage, taskProgressPercent } from "@/lib/taskPresentation";

describe("durable Task presentation", () => {
  it("converts normalized Runtime progress into a bounded percentage", () => {
    expect(taskProgressPercent(0)).toBe(0);
    expect(taskProgressPercent(0.42)).toBe(42);
    expect(taskProgressPercent(1)).toBe(100);
    expect(taskProgressPercent(null)).toBeNull();
  });

  it("surfaces the real per-item remote ingest failure", () => {
    expect(
      taskErrorMessage(
        {
          kind: "ASSET_INGEST_FAILED",
          items: [{ name: "large.mp4", error: "远程素材下载连接超时" }],
        },
        "素材处理失败（FAILED）",
      ),
    ).toBe("远程素材下载连接超时");
  });

  it("falls back to direct structured messages and terminal status text", () => {
    expect(
      taskErrorMessage({ message: "provider rejected input" }, "任务失败"),
    ).toBe("provider rejected input");
    expect(taskErrorMessage(null, "任务失败")).toBe("任务失败");
  });
});
