import { describe, expect, it } from "vitest";
import i18next from "i18next";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import ja from "@/locales/ja.json";
import ru from "@/locales/ru.json";
import pt from "@/locales/pt-BR.json";
import id from "@/locales/id.json";
import vi from "@/locales/vi.json";
import {
  matchesSettingsSearch,
  searchSettingsItems,
  SETTINGS_SEARCH_KEYS,
} from "./settingsSearch";

const resources = { en, zh, ja, ru, "pt-BR": pt, id, vi };

describe("settings search", () => {
  it.each(Object.entries(resources))(
    "indexes translated settings in %s",
    async (language, translations) => {
      const i18n = i18next.createInstance();
      await i18n.init({
        lng: language,
        fallbackLng: false,
        resources: { [language]: { translation: translations } },
      });
      for (const [page, keys] of Object.entries(SETTINGS_SEARCH_KEYS)) {
        for (const key of keys) {
          expect(i18n.exists(key), `${language}: ${key}`).toBe(true);
          expect(searchSettingsItems(page, i18n.t(key), i18n.t)).toContain(key);
        }
      }
    },
  );

  it("finds sidebar and individual preferences without their page title", async () => {
    const i18n = i18next.createInstance();
    await i18n.init({
      lng: "zh",
      resources: { zh: { translation: zh }, en: { translation: en } },
    });
    expect(searchSettingsItems("general", "侧边栏", i18n.t)).toContain(
      "settingsCenter.pages.navigation",
    );
    expect(searchSettingsItems("general", "主题", i18n.t)).toContain(
      "sidebar.settings.theme",
    );
    expect(searchSettingsItems("general", "sidebar", i18n.t)).toContain(
      "settingsCenter.pages.navigation",
    );
    expect(searchSettingsItems("general", "not-a-setting", i18n.t)).toEqual([]);
  });

  it("normalizes case, whitespace and full-width Latin characters", () => {
    expect(matchesSettingsSearch("  ａｐｉ  KEY  ", "Provider API key")).toBe(
      true,
    );
    expect(matchesSettingsSearch("API secret", "Provider API key")).toBe(false);
  });
});
