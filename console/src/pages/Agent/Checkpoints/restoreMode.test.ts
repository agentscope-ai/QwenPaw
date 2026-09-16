import { describe, expect, it } from "vitest";
import type { CheckpointStatus } from "@/api/types/checkpoints";
import { restoreCreatesNewChat } from "./restoreMode";

const status = (
  restore_mode?: CheckpointStatus["restore_mode"],
): CheckpointStatus => ({
  auto_enabled: true,
  has_checkpoints: true,
  scope: "agent_workspace",
  restore_mode,
});

describe("checkpoint restore mode", () => {
  it("只在后端明确声明 new_chat 时显示新会话语义", () => {
    expect(restoreCreatesNewChat(status("new_chat"))).toBe(true);
    expect(restoreCreatesNewChat(status("in_place"))).toBe(false);
  });

  it("旧后端缺少模式字段时安全回退到原位恢复提示", () => {
    expect(restoreCreatesNewChat(status())).toBe(false);
    expect(restoreCreatesNewChat(null)).toBe(false);
  });
});
