/**
 * DataPaw plugin — host `/chat` integration (CloudPaw-style).
 *
 * This bundle patches the host `Chat/index` module so task graph cards,
 * SSE interception, and fetch_data render inside `/chat` messages (no
 * `/plugin/datapaw` route or fixed top-right cron bubbles).
 */

import en from "./locales/en.json";
import zh from "./locales/zh.json";
import ja from "./locales/ja.json";
import ru from "./locales/ru.json";

import { PLUGIN_ID } from "./plugin/constants";

const DATAPAW_AGENT_ID = PLUGIN_ID;
const FIRST_INSTALL_KEY = "datapaw-first-install";
const LAST_USED_KEY = "qwenpaw-last-used-agent";
const STORAGE_KEY = "qwenpaw-agent-storage";

function ensureDefaultAgent(): void {
  if (localStorage.getItem(FIRST_INSTALL_KEY)) return;

  localStorage.setItem(FIRST_INSTALL_KEY, "true");

  function writeAgentToStorage(): void {
    localStorage.setItem(LAST_USED_KEY, DATAPAW_AGENT_ID);
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        parsed.state = parsed.state || {};
        parsed.state.selectedAgent = DATAPAW_AGENT_ID;
        localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      } else {
        localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            version: 0,
            state: {
              selectedAgent: DATAPAW_AGENT_ID,
              agents: [],
              lastChatIdByAgent: {},
            },
          }),
        );
      }
    } catch {
      /* ignore */
    }
    try {
      const sessionRaw = sessionStorage.getItem(STORAGE_KEY);
      if (sessionRaw) {
        const parsed = JSON.parse(sessionRaw);
        parsed.state = parsed.state || {};
        parsed.state.selectedAgent = DATAPAW_AGENT_ID;
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      }
    } catch {
      /* ignore */
    }
  }

  writeAgentToStorage();
  window.addEventListener("beforeunload", writeAgentToStorage, { once: true });
  window.location.reload();
}

type DatapawLocaleRoot = {
  taskGraph?: Record<string, string>;
  agent?: { datapaw?: string; datapawHelp?: string };
};

function sliceDatapawTranslations(
  full: DatapawLocaleRoot,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (full.taskGraph) out.taskGraph = full.taskGraph;
  if (full.agent?.datapaw || full.agent?.datapawHelp) {
    out.agent = {
      ...(full.agent.datapaw ? { datapaw: full.agent.datapaw } : {}),
      ...(full.agent.datapawHelp ? { datapawHelp: full.agent.datapawHelp } : {}),
    };
  }
  return out;
}

function registerDatapawLocales(): void {
  const bundles = {
    en: sliceDatapawTranslations(en as DatapawLocaleRoot),
    zh: sliceDatapawTranslations(zh as DatapawLocaleRoot),
    ja: sliceDatapawTranslations(ja as DatapawLocaleRoot),
    ru: sliceDatapawTranslations(ru as DatapawLocaleRoot),
  };

  const QP = window as {
    QwenPaw?: {
      registerI18n?: (
        pluginId: string,
        b: Record<string, Record<string, unknown>>,
      ) => void;
    };
  };

  if (QP.QwenPaw?.registerI18n) {
    QP.QwenPaw.registerI18n(PLUGIN_ID, bundles);
    return;
  }

  // Host without registerI18n: merge into the global i18next instance used by
  // react-i18next (same module the host already initialized).
  import("i18next")
    .then((mod) => {
      const i18n = mod.default;
      for (const [lng, resource] of Object.entries(bundles)) {
        i18n.addResourceBundle(lng, "translation", resource, true, true);
      }
    })
    .catch(() => {
      console.warn(`[${PLUGIN_ID}] failed to merge i18n bundles`);
    });
}

function patchWelcomeAndTheme(): void {
  const LOGO =
    "https://img.alicdn.com/imgextra/i3/O1CN019jgrYq1DuurD1Z7JA_!!6000000000277-2-tps-1024-1024.png";

  const descriptions: Record<string, string> = {
    zh: "基于 DAG 任务图分阶段推进复杂数据分析。请在左上角切换到 DataPaw Agent 后使用；任务面板会在对话右侧实时更新。",
    en: "Multi-step data analysis via a DAG task graph. Switch to the DataPaw agent in the top-left dropdown; the task panel updates live on the right during chat.",
    ja: "DAG タスクグラフで段階的にデータ分析を進めます。左上で DataPaw Agent に切り替えてください。",
    ru: "Пошаговый анализ данных через DAG. Переключитесь на агента DataPaw в выпадающем списке слева вверху.",
  };

  function resolveDescription(locale?: string): string {
    const stored = localStorage.getItem("language") || "";
    const lang = (locale || stored || navigator.language || "en").split("-")[0];
    return descriptions[lang] || descriptions.en;
  }

  const chat = window.QwenPaw?.chat;

  let appliedWithChatSdk = false;
  if (chat?.welcome?.set) {
    chat.welcome.set(PLUGIN_ID, {
      description: resolveDescription,
      nick: "DataPaw",
      avatar: LOGO,
    });
    appliedWithChatSdk = true;
  }
  if (chat?.response?.set) {
    chat.response.set(PLUGIN_ID, {
      nick: "DataPaw",
      avatar: LOGO,
    });
    appliedWithChatSdk = true;
  }
  if (appliedWithChatSdk) return;

  const modules = (window as { QwenPaw?: { modules?: Record<string, unknown> } })
    .QwenPaw?.modules;
  if (!modules) return;

  const configModule = modules["Chat/OptionsPanel/defaultConfig"] as
    | {
        configProvider?: {
          getConfig: (t: (k: string) => string) => Record<string, unknown>;
          getGreeting?: () => string;
          getDescription?: () => string;
          getPrompts?: () => Array<{ label?: string; value: string }>;
        };
      }
    | undefined;
  const provider = configModule?.configProvider;
  if (!provider?.getConfig) return;

  const originalGetConfig = provider.getConfig.bind(provider);

  function detectLang(): string {
    const stored = localStorage.getItem("language") || "";
    if (stored) return stored.split("-")[0];
    return (navigator.language || "en").split("-")[0];
  }

  provider.getDescription = () =>
    descriptions[detectLang()] || descriptions.en;

  provider.getConfig = (t: (k: string) => string) => {
    const base = originalGetConfig(t) as Record<string, unknown>;
    const welcome = (base.welcome as Record<string, unknown>) || {};
    const theme = (base.theme as Record<string, unknown>) || {};
    const leftHeader = (theme.leftHeader as Record<string, unknown>) || {};
    return {
      ...base,
      theme: {
        ...theme,
        leftHeader: {
          ...leftHeader,
          title: "Work with DataPaw",
        },
      },
      welcome: {
        ...welcome,
        nick: "DataPaw",
        avatar: LOGO,
      },
    };
  };
}

/** Lightweight helpers when the user stays on the host `/chat` page. */
export function setupHostChatIntegration(): void {
  const QP = (window as { QwenPaw?: { host?: unknown } }).QwenPaw;
  if (!QP?.host) {
    console.warn(`[${PLUGIN_ID}] window.QwenPaw.host missing — skipping`);
    return;
  }

  registerDatapawLocales();
  patchWelcomeAndTheme();
  ensureDefaultAgent();
}
