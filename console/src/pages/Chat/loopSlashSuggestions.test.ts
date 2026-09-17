import { describe, expect, it } from "vitest";

import type { LoopModeInfo } from "../../stores/loopStore";
import { buildLoopSlashSuggestions } from "./loopSlashSuggestions";

const t = (key: string) => {
  if (key === "loop.modes.goal.description") {
    return "设定目标并持续推进直到完成。";
  }
  return key;
};

describe("buildLoopSlashSuggestions", () => {
  const modes: LoopModeInfo[] = [
    {
      id: "goal",
      name: "goal",
      slash_command: "goal",
      description: "Set a goal and work until it is done.",
      source: "builtin",
    },
    {
      id: "plugin:ultrawork",
      name: "ultrawork",
      slash_command: "ultrawork",
      description: "**Ultrawork** — parallel\n\nUsage",
      source: "plugin",
      description_i18n: {
        en: "**Ultrawork** — parallel",
        "zh-CN": "**Ultrawork** — 并行",
      },
    },
  ];

  it("resolves plugin descriptions for the active language", () => {
    expect(buildLoopSlashSuggestions(modes, new Set(), t, "zh")).toEqual([
      {
        command: "/goal",
        value: "goal",
        description: "设定目标并持续推进直到完成。",
      },
      {
        command: "/ultrawork",
        value: "ultrawork",
        description: "**Ultrawork** — 并行",
      },
    ]);
  });
});
