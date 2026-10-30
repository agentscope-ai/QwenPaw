import { describe, expect, it } from "vitest";
import { parseMemoryTags } from "./markdown";

describe("memory tag parsing", () => {
  it.each([
    'memory_tags: ["赵六", "Orion"]',
    "memory_tags:\n- 赵六\n- Orion",
    "memory_tags:\n  - 赵六\n  - Orion # comment",
  ])("supports YAML lists: %s", (frontmatter) => {
    expect(parseMemoryTags(`---\n${frontmatter}\n---\nBody`)).toEqual([
      "赵六",
      "Orion",
    ]);
  });

  it("preserves quoted punctuation and applies the indexed file tag limit", () => {
    expect(
      parseMemoryTags('---\nmemory_tags: ["A: B", "C#", 2026, extra]\n---\n'),
    ).toEqual(["A:_B", "C#", "2026"]);
  });

  it("ignores invalid values and deduplicates display casing", () => {
    expect(
      parseMemoryTags(
        '---\nmemory_tags: [false, null, {}, [], "!!", "ORION", orion, "赵六"]\n---\n',
      ),
    ).toEqual(["ORION", "赵六"]);
  });

  it("keeps integer tags exact and excludes YAML floats like the index", () => {
    expect(
      parseMemoryTags(
        "---\nmemory_tags: [1.0, 1.0e+3, 9007199254740993, 2026]\n---\n",
      ),
    ).toEqual(["9007199254740993", "2026"]);
  });

  it.each([
    "No frontmatter",
    "---\nmemory_tags: Orion\n---\n",
    "---\nmemory_tags: [broken\n---\n",
  ])("keeps invalid metadata from breaking file previews", (content) => {
    expect(parseMemoryTags(content)).toEqual([]);
  });
});
