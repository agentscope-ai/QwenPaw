import { describe, expect, it } from "vitest";

import { localeTag, stringKeys, translate } from "./strings";
import { buildAppStatusModel } from "./status";

describe("string tables", () => {
  it("has a non-empty translation for every key in both languages", () => {
    for (const key of stringKeys()) {
      expect(translate("en", key), `en:${key}`).toBeTruthy();
      expect(translate("zh", key), `zh:${key}`).toBeTruthy();
    }
  });

  it("interpolates named parameters", () => {
    expect(
      translate("en", "session.actionFailed", {
        action: "pin",
        detail: "boom",
      }),
    ).toBe("Could not pin the dialogue. boom");
    expect(
      translate("zh", "status.detail.sourcesReady", { ready: 2, total: 3 }),
    ).toBe("2/3 个数据源就绪");
  });

  it("maps languages to BCP 47 locale tags", () => {
    expect(localeTag("zh")).toBe("zh-CN");
    expect(localeTag("en")).toBe("en-US");
  });
});

describe("buildAppStatusModel localization", () => {
  it("keeps English labels by default", () => {
    const model = buildAppStatusModel(undefined, undefined);
    expect(model.label).toBe("Checking");
    expect(model.categories.map((category) => category.label)).toEqual([
      "Core",
      "Data",
      "Graph",
      "Skills",
    ]);
  });

  it("renders Chinese labels when asked", () => {
    const model = buildAppStatusModel(undefined, undefined, "", "zh");
    expect(model.label).toBe("检查中");
    expect(model.categories.map((category) => category.label)).toEqual([
      "核心",
      "数据",
      "图谱",
      "技能",
    ]);
    expect(model.detail).toBe("Context 服务不可用");
  });
});
