import { describe, expect, it } from "vitest";

import type { GateInstanceConfig } from "@/api/types";
import {
  buildCustomLoopMode,
  hasDuplicateLoopModeName,
  reorderCustomGates,
} from "./AgentLoopCard";

describe("buildCustomLoopMode", () => {
  it("creates multiple custom modes with unique tab identity", () => {
    const first = buildCustomLoopMode([], "Research", "research", "safe", 1);
    const second = buildCustomLoopMode(
      [first],
      "Research Copy",
      "research",
      "quality",
      2,
    );

    expect(first.id).toBe("research");
    expect(second.id).toBe("research-2");
    expect(second.slash_command).toBe("research-2");
    expect(second.gates.map((gate) => gate.type)).toEqual([
      "iteration",
      "token_budget",
      "doom_loop",
      "completion_rubric",
    ]);
    expect(second.gates[second.gates.length - 1]?.params.max_evaluations).toBe(
      3,
    );
  });
});

describe("reorderCustomGates", () => {
  it("uses the visible pipeline order as the source of truth", () => {
    const gates = [
      { id: "one", type: "iteration" },
      { id: "two", type: "tool_call_budget" },
      { id: "three", type: "doom_loop" },
    ].map(
      (gate) =>
        ({
          ...gate,
          enabled: true,
          params: {},
        }) as GateInstanceConfig,
    );

    expect(reorderCustomGates(gates, 2, 0).map((gate) => gate.id)).toEqual([
      "three",
      "one",
      "two",
    ]);
  });
});

describe("hasDuplicateLoopModeName", () => {
  it("ignores surrounding whitespace and letter case", () => {
    const mode = buildCustomLoopMode([], "Research", "research", "safe", 1);

    expect(hasDuplicateLoopModeName([mode], " research ")).toBe(true);
    expect(hasDuplicateLoopModeName([mode], "Quality")).toBe(false);
    expect(hasDuplicateLoopModeName([mode], "Research", 0)).toBe(false);
  });
});
