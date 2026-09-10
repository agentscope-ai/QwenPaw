import { describe, expect, it } from "vitest";

import en from "./en.json";
import id from "./id.json";
import ja from "./ja.json";
import ptBR from "./pt-BR.json";
import ru from "./ru.json";
import vi from "./vi.json";
import zh from "./zh.json";

const localeEntries = { en, id, ja, "pt-BR": ptBR, ru, vi, zh };

function getKeyPaths(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === "object" && !Array.isArray(child)) {
      return getKeyPaths(child, path);
    }
    return path;
  });
}

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

  it.each(Object.entries(localeEntries))(
    "%s includes every Settings Center key",
    (_locale, messages) => {
      expect(getKeyPaths(messages.settingsCenter).sort()).toEqual(
        getKeyPaths(en.settingsCenter).sort(),
      );
      expect(messages.nav.moreSettings).toBeTruthy();
      expect(messages.sidebar.more).toBeTruthy();
      expect(messages.chat.newTask).toBeTruthy();
      expect(Object.keys(messages.sidebar.quickMenu).sort()).toEqual(
        Object.keys(en.sidebar.quickMenu).sort(),
      );
    },
  );
});
