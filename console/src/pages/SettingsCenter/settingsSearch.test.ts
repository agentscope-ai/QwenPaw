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
  settingsSearchPath,
  settingsSearchTarget,
  searchChannelNames,
  settingsSearchLabel,
  searchToolNames,
  settingsSearchUnavailableReason,
} from "./settingsSearch";

const resources = { en, zh, ja, ru, "pt-BR": pt, id, vi };

describe("settings search", () => {
  it.each(Object.entries(resources))(
    "indexes translated settings in %s",
    async (language, translations) => {
      const i18n = i18next.createInstance();
      await i18n.init({
        lng: language,
        fallbackLng: "en",
        resources: {
          en: { translation: en },
          [language]: { translation: translations },
        },
      });
      for (const [page, keys] of Object.entries(SETTINGS_SEARCH_KEYS)) {
        for (const key of keys) {
          expect(i18n.exists(key), `${language}: ${key}`).toBe(true);
          expect(i18n.t(key), `${language}: ${key}`).not.toMatch(/{{.+?}}/);
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

  it("explains fields unavailable for the active context strategy or memory backend", () => {
    const t = ((key: string) => key) as import("i18next").TFunction;
    expect(
      settingsSearchUnavailableReason(
        "agent-config",
        "agentConfig.toolResultCompactRecentN",
        { strategy: "scroll" },
        t,
      ),
    ).toBe("settingsCenter.searchNativeContextOnly");
    expect(
      settingsSearchUnavailableReason(
        "agent-config",
        "agentConfig.toolResultCompactRecentN",
        { strategy: "native" },
        t,
      ),
    ).toBeUndefined();
    expect(
      settingsSearchUnavailableReason(
        "agent-config",
        "agentConfig.historyRetentionDays",
        { strategy: "native" },
        t,
      ),
    ).toBe("settingsCenter.searchScrollContextOnly");
    expect(
      settingsSearchUnavailableReason(
        "agent-config",
        "agentConfig.embeddingModelName",
        { memoryBackend: "none" },
        t,
      ),
    ).toBe("settingsCenter.searchReMeOnly");
    expect(
      settingsSearchUnavailableReason(
        "agent-config",
        "agentConfig.memoryManagerBackend",
        { memoryBackend: "none" },
        t,
      ),
    ).toBeUndefined();
  });

  it("finds current field names, legacy aliases and contextual settings", async () => {
    const i18n = i18next.createInstance();
    await i18n.init({
      lng: "zh",
      resources: { zh: { translation: zh }, en: { translation: en } },
    });
    for (const [page, query, key, context] of [
      ["models", "最大输入长度", "models.maxInputLengthLabel", "模型"],
      ["models", "单次输出上限", "models.maxTokensLabel", "模型"],
      ["agent-config", "运行配置 上下文", "runtimeDesign.context", "运行配置"],
      [
        "agent-config",
        "上下文保留阈值",
        "agentConfig.contextCompactReserveRatio",
        "运行配置",
      ],
      ["general", "控制台基准字号", "settingsCenter.uiFontSize", "通用"],
      ["mcp", "MCP 启动命令", "mcp.form.command", "MCP"],
      ["acp", "ACP 环境变量", "acp.env", "ACP"],
      ["heartbeat", "开始时间", "heartbeat.activeStart", "心跳"],
      ["security", "扫描超时", "security.skillScanner.timeout", "安全"],
      [
        "voice",
        "本地 Whisper",
        "voiceTranscription.providerTypeLocalWhisper",
        "语音转写",
      ],
    ])
      expect(searchSettingsItems(page, query, i18n.t, context)).toContain(key);
    expect(
      searchSettingsItems("agent-config", "最大输入长度", i18n.t),
    ).not.toContain("agentConfig.maxInputLength");
    expect(
      settingsSearchTarget("marketplace", "pluginManager.officialTitle", i18n.t)
        .query,
    ).toEqual({ tab: "plugins", view: "official" });
    expect(
      settingsSearchTarget(
        "agent-config",
        "agentConfig.embeddingDimensions",
        i18n.t,
      ).query,
    ).toEqual({ tab: "remeLightMemory" });
    expect(
      settingsSearchTarget("models", "models.manageModels", i18n.t).targetId,
    ).toBe("models.manageModels");
    expect(settingsSearchLabel("skills.uploadSkill", i18n.t)).toBe(
      i18n.t("skills.uploadZip"),
    );
    expect(
      searchToolNames("web_search", i18n.t, "工具")[0].target.targetId,
    ).toBe("tool:web_search");
  });

  it("finds the missing fields and combines page, group and field names", async () => {
    const i18n = i18next.createInstance();
    await i18n.init({
      lng: "zh",
      resources: { zh: { translation: zh }, en: { translation: en } },
    });
    for (const [page, query, key, context] of [
      ["agent-config", "主模型", "models.primaryModel", "运行配置"],
      [
        "agent-config",
        "模型 子智能体模型",
        "modelSelector.subagentModel",
        "运行配置",
      ],
      ["cron-jobs", "执行模型", "cronJobs.executionModel", "定时任务"],
      ["cron-jobs", "定时任务 时区", "cronJobs.scheduleTimezone", "定时任务"],
      ["channels", "频道 白名单", "channels.whitelist", "频道"],
      ["acp", "ACP Node 路径", "acp.nodePath", "ACP"],
    ])
      expect(searchSettingsItems(page, query, i18n.t, context)).toContain(key);
    expect(settingsSearchPath("cronJobs.scheduleTimezone", i18n.t)).toEqual([
      "调度类型",
    ]);
    expect(
      settingsSearchTarget("cron-jobs", "cronJobs.executionModel", i18n.t),
    ).toMatchObject({
      surface: "cron-job",
      tabId: "delivery",
      targetId: "cronJobs.executionModel",
    });
    expect(
      settingsSearchTarget("channels", "channels.blacklist", i18n.t),
    ).toMatchObject({ surface: "channel-acl", tabId: "blacklist" });
    for (const query of ["飞书", "Feishu", "feishu"]) {
      expect(
        searchChannelNames(query, i18n.t, "频道").some(
          (item) => item.target.channelKey === "feishu",
        ),
      ).toBe(true);
    }
  });
});
