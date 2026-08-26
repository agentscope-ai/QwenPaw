import { describe, it, expect } from "vitest";
import { buildLoopSlashSuggestions } from "./loopSlashSuggestions";
import type { LoopModeInfo } from "../../stores/loopStore";

const t = (key: string) => {
  if (key === "loop.modes.goal.description")
    return "设定目标并持续推进直到完成。";
  if (key === "loop.modes.omp.description") return "并行任务执行引擎";
  return key;
};

describe("buildLoopSlashSuggestions (#5031)", () => {
  const modes: LoopModeInfo[] = [
    {
      id: "goal",
      name: "goal",
      slash_command: "goal",
      description: "Set a goal and work until it is done.",
      source: "builtin",
    },
    {
      id: "omp",
      name: "omp",
      slash_command: "omp",
      description: "Parallel task execution engine\n\nUsage: /omp <task>",
      source: "builtin",
    },
    {
      id: "no-slash",
      name: "no-slash",
      slash_command: "",
      description: "Mode without slash command",
      source: "builtin",
    },
  ];

  it("slash command 提交后显示的是 /goal 而非 SKILL.md 展开内容", () => {
    const reserved = new Set<string>();
    const suggestions = buildLoopSlashSuggestions(modes, reserved, t, "zh");

    const goalSuggestion = suggestions.find((s) => s.value === "goal");
    expect(goalSuggestion).toBeDefined();
    // 关键断言：command 是 /goal，不是 SKILL.md 展开后的多行内容
    expect(goalSuggestion!.command).toBe("/goal");
    // description 只取第一行摘要，不包含 Usage 等多行展开
    expect(goalSuggestion!.description).not.toContain("\n");
    expect(goalSuggestion!.description).toBe("设定目标并持续推进直到完成。");
  });

  it("每个有 slash_command 的 mode 生成一条建议，command 以 / 开头", () => {
    const reserved = new Set<string>();
    const suggestions = buildLoopSlashSuggestions(modes, reserved, t, "en");

    // no-slash 没有 slash_command，应被过滤
    expect(suggestions).toHaveLength(2);
    expect(suggestions.every((s) => s.command.startsWith("/"))).toBe(true);
  });

  it("已被 reservedCommands 占用的命令不出现在建议中", () => {
    const reserved = new Set(["goal"]);
    const suggestions = buildLoopSlashSuggestions(modes, reserved, t, "en");

    expect(suggestions.find((s) => s.value === "goal")).toBeUndefined();
    expect(suggestions).toHaveLength(1);
    expect(suggestions[0].command).toBe("/omp");
  });

  it("description 不包含 SKILL.md 的完整展开内容（多行文本只取首行）", () => {
    const reserved = new Set<string>();
    const suggestions = buildLoopSlashSuggestions(modes, reserved, t, "en");

    const ompSuggestion = suggestions.find((s) => s.value === "omp");
    expect(ompSuggestion).toBeDefined();
    // omp 的 description 有多行（含 Usage:），但建议只取首行
    expect(ompSuggestion!.description).not.toContain("Usage:");
    expect(ompSuggestion!.description).not.toContain("\n");
  });
});
