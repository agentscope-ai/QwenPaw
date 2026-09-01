import { describe, expect, it } from "vitest";

import en from "./en.json";
import zh from "./zh.json";

describe("Settings Center copy", () => {
  it("uses feature-oriented sidebar group names", () => {
    expect(zh.settingsCenter.groups).toMatchObject({
      agentConfiguration: "智能体配置",
      global: "全局设置",
    });
    expect(zh.settingsCenter.sidebarGroups).toMatchObject({
      agentConfiguration: "智能体配置",
      plugins: "插件功能",
    });
    expect(en.settingsCenter.groups).toMatchObject({
      agentConfiguration: "Agent configuration",
      global: "Global settings",
    });
    expect(en.settingsCenter.sidebarGroups).toMatchObject({
      agentConfiguration: "Agent configuration",
      plugins: "Plugin features",
    });
  });
});
