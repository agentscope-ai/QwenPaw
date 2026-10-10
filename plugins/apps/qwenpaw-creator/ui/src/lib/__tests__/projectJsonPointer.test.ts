import { describe, expect, it } from "vitest";
import {
  projectJsonPointer,
  readProjectPointer,
} from "@/lib/projectJsonPointer";

const root = {
  timelines: {
    items: {
      "timeline:main": {
        elements_by_id: {
          "r2v-window": {
            creation: { storyboard_prompt: "暖色餐厅窗外的橘猫" },
          },
        },
      },
    },
  },
  list: [{ id: "a" }, { id: "b" }],
};

describe("readProjectPointer", () => {
  it("reads a nested string field built by projectJsonPointer", () => {
    const pointer = projectJsonPointer(
      "timelines",
      "items",
      "timeline:main",
      "elements_by_id",
      "r2v-window",
      "creation",
      "storyboard_prompt",
    );
    expect(readProjectPointer(root, pointer)).toEqual({
      present: true,
      value: "暖色餐厅窗外的橘猫",
    });
  });

  it("reads through array indices", () => {
    expect(readProjectPointer(root, "/list/1/id")).toEqual({
      present: true,
      value: "b",
    });
  });

  it("reports an absent field without throwing", () => {
    expect(
      readProjectPointer(root, "/timelines/items/timeline:main/missing"),
    ).toEqual({ present: false, value: undefined });
  });

  it("reports an out-of-range array index as absent", () => {
    expect(readProjectPointer(root, "/list/9/id")).toEqual({
      present: false,
      value: undefined,
    });
  });

  it("rejects pointers that do not start with a slash", () => {
    expect(readProjectPointer(root, "timelines")).toEqual({
      present: false,
      value: undefined,
    });
  });

  it("decodes escaped ~1 and ~0 segments", () => {
    const escaped = { "a/b": { "c~d": "value" } };
    expect(readProjectPointer(escaped, "/a~1b/c~0d")).toEqual({
      present: true,
      value: "value",
    });
  });

  it("only resolves own properties, never the prototype chain", () => {
    for (const pointer of ["/list/__proto__", "/timelines/constructor"]) {
      expect(readProjectPointer(root, pointer)).toEqual({
        present: false,
        value: undefined,
      });
    }
  });

  it("requires canonical decimal array indices", () => {
    for (const pointer of ["/list/01/id", "/list/ 1/id", "/list//id"]) {
      expect(readProjectPointer(root, pointer)).toEqual({
        present: false,
        value: undefined,
      });
    }
    expect(readProjectPointer(root, "/list/0/id")).toEqual({
      present: true,
      value: "a",
    });
  });
});
