import { detectLang } from "../lib/lang";
import { PLUGIN_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";

const LOGO =
  "https://img.alicdn.com/imgextra/i3/O1CN019jgrYq1DuurD1Z7JA_!!6000000000277-2-tps-1024-1024.png";

const descriptions: Record<string, string> = {
  zh: "基于 DAG 任务图分阶段推进复杂数据分析。请在左上角切换到 DataPaw Agent 后使用；任务计划会在对话中实时更新。",
  en: "Multi-step data analysis via a DAG task graph. Switch to the DataPaw agent in the top-left dropdown; task plans update live in chat.",
  ja: "DAG タスクグラフで段階的にデータ分析を進めます。左上で DataPaw Agent に切り替えてください。",
  ru: "Пошаговый анализ данных через DAG. Переключитесь на агента DataPaw в выпадающем списке слева вверху.",
};

function resolveDescription(locale?: string): string | undefined {
  if (!isDatapawAgentSelected()) return undefined;
  const lang = (locale || detectLang()).split("-")[0];
  return descriptions[lang] || descriptions.en;
}

function resolveNick(): string | undefined {
  return isDatapawAgentSelected() ? "DataPaw" : undefined;
}

function resolveAvatar(): string | undefined {
  return isDatapawAgentSelected() ? LOGO : undefined;
}

export function patchWelcomeAndTheme(): void {
  const chat = (
    window as {
      QwenPaw?: {
        chat?: {
          welcome?: {
            set?: (
              pluginId: string,
              partial: Record<string, unknown>,
            ) => unknown;
          };
          response?: {
            set?: (
              pluginId: string,
              partial: Record<string, unknown>,
            ) => unknown;
          };
        };
      };
    }
  ).QwenPaw?.chat;

  let appliedWithChatSdk = false;
  if (chat?.welcome?.set) {
    chat.welcome.set(PLUGIN_ID, {
      description: resolveDescription,
      nick: resolveNick,
      avatar: resolveAvatar,
    });
    appliedWithChatSdk = true;
  }
  if (chat?.response?.set) {
    chat.response.set(PLUGIN_ID, {
      nick: resolveNick,
      avatar: resolveAvatar,
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
          getDescription?: () => string;
        };
      }
    | undefined;
  const provider = configModule?.configProvider;
  if (!provider?.getConfig) {
    console.warn("[datapaw] configProvider not found — skipping welcome/theme patch");
    return;
  }

  const originalGetConfig = provider.getConfig.bind(provider);
  const originalGetDescription = provider.getDescription?.bind(provider);

  provider.getDescription = () =>
    isDatapawAgentSelected()
      ? descriptions[detectLang()] || descriptions.en
      : originalGetDescription?.() || "";

  provider.getConfig = (t: (k: string) => string) => {
    const base = originalGetConfig(t) as Record<string, unknown>;
    if (!isDatapawAgentSelected()) return base;

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
