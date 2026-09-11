import { describe, expect, it } from "vitest";

import type { LoopModeInfo } from "../stores/loopStore";
import {
  firstLoopDescriptionMarkdown,
  resolveLoopModeDescriptionMarkdown,
  resolveLoopModeName,
} from "./loopModeDescription";

const t = (key: string) => {
  if (key === "loop.modes.goal.description") {
    return "设定目标并持续推进直到完成。";
  }
  if (key === "loop.modes.goal.name") {
    return "目标";
  }
  return key;
};

describe("firstLoopDescriptionMarkdown", () => {
  it("keeps the first non-empty line including Markdown markers", () => {
    expect(
      firstLoopDescriptionMarkdown(
        "**UltraQA** — automated QA cycle engine\n\nUsage:\n",
      ),
    ).toBe("**UltraQA** — automated QA cycle engine");
  });
});

describe("resolveLoopModeDescriptionMarkdown", () => {
  it("uses Console i18n for builtin modes", () => {
    const goal: Pick<
      LoopModeInfo,
      "id" | "source" | "description" | "description_i18n"
    > = {
      id: "goal",
      source: "builtin",
      description: "Set a goal and work until it is done.",
    };
    expect(resolveLoopModeDescriptionMarkdown(goal, t, "zh")).toBe(
      "设定目标并持续推进直到完成。",
    );
  });

  it("uses description_i18n for plugins when present", () => {
    const omp: Pick<
      LoopModeInfo,
      "id" | "source" | "description" | "description_i18n"
    > = {
      id: "plugin:ultrawork",
      source: "plugin",
      description: "**Ultrawork** — parallel task execution engine\n\nUsage",
      description_i18n: {
        en: "**Ultrawork** — parallel task execution engine",
        "zh-CN": "**Ultrawork** — 并行任务执行引擎",
      },
    };
    expect(resolveLoopModeDescriptionMarkdown(omp, t, "zh")).toBe(
      "**Ultrawork** — 并行任务执行引擎",
    );
    expect(resolveLoopModeDescriptionMarkdown(omp, t, "en")).toBe(
      "**Ultrawork** — parallel task execution engine",
    );
  });

  it("falls back to API description when plugin has no i18n map", () => {
    const other: Pick<
      LoopModeInfo,
      "id" | "source" | "description" | "description_i18n"
    > = {
      id: "plugin:a2a",
      source: "plugin",
      description: "List or call remote A2A agents",
    };
    expect(resolveLoopModeDescriptionMarkdown(other, t, "zh")).toBe(
      "List or call remote A2A agents",
    );
  });
});

describe("resolveLoopModeName", () => {
  it("uses Console i18n for builtin names", () => {
    expect(
      resolveLoopModeName(
        { id: "goal", name: "goal", source: "builtin" },
        t,
        "zh",
      ),
    ).toBe("目标");
  });

  it("uses name_i18n for plugins", () => {
    expect(
      resolveLoopModeName(
        {
          id: "plugin:ralph",
          name: "ralph",
          source: "plugin",
          name_i18n: { en: "Ralph", "zh-CN": "Ralph" },
        },
        t,
        "zh",
      ),
    ).toBe("Ralph");
  });
});
