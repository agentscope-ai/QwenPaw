/**
 * Register DataPaw chat sender toolbar (data source + plan mode) in the host
 * chat input via `window.QwenPaw.chat.sender.addPrefix`.
 */
import ChatSenderToolbar from "@/pages/Chat/components/ChatSenderToolbar";
import { ChatToolbarI18nProvider } from "../lib/chat-toolbar-i18n";
import { isDatapawAgentSelected } from "../lib/agent";
import { PLUGIN_ID } from "../lib/constants";
import type { HostBundle } from "../types";

const SENDER_TOOLBAR_PREFIX_ID = "datapaw-chat-sender-toolbar";

function useDatapawAgentSelected(React: HostBundle["React"]): boolean {
  const { useSyncExternalStore } = React;
  return useSyncExternalStore(
    (cb) => {
      const onStorage = () => cb();
      window.addEventListener("storage", onStorage);
      const timer = window.setInterval(cb, 800);
      return () => {
        window.removeEventListener("storage", onStorage);
        window.clearInterval(timer);
      };
    },
    isDatapawAgentSelected,
    () => false,
  );
}

export function registerChatSenderToolbar(host: HostBundle): void {
  const chat = (
    window as {
      QwenPaw?: {
        chat?: {
          sender?: {
            addPrefix: (
              pluginId: string,
              node: unknown,
              opts?: { id?: string; order?: number },
            ) => { dispose: () => void };
          };
        };
      };
    }
  ).QwenPaw?.chat;

  if (!chat?.sender?.addPrefix) {
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.chat.sender.addPrefix missing — chat toolbar skipped`,
    );
    return;
  }

  const { React } = host;

  function ChatSenderToolbarPrefix() {
    const active = useDatapawAgentSelected(React);
    if (!active) return null;

    return React.createElement(
      "div",
      {
        className: "datapaw-chat-sender-toolbar",
        "data-datapaw-chat-sender-toolbar": true,
      },
      React.createElement(
        ChatToolbarI18nProvider,
        null,
        React.createElement(ChatSenderToolbar),
      ),
    );
  }

  chat.sender.addPrefix(
    PLUGIN_ID,
    React.createElement(ChatSenderToolbarPrefix as React.ComponentType),
    { id: SENDER_TOOLBAR_PREFIX_ID, order: 10 },
  );
}
