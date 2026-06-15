import type { ComponentType } from "react";
import { useEffect, useState } from "react";
import { FetchDataToolAdapter } from "../pages/Chat/components/FetchDataBlock";
import ChatSenderToolbar from "../pages/Chat/components/ChatSenderToolbar";
import { PluginI18nProvider } from "./plugin-i18n";
import { patchHostSessionApi } from "../hostSessionApiPatch";
import { installFetchPatch } from "./fetch-patch";
import { isDatapawAgentSelected } from "./fetch-patch";
import { setupHostChatIntegration } from "../plugin-host";
import { PLUGIN_ID } from "../plugin/constants";

const SENDER_TOOLBAR_PREFIX_ID = "datapaw-chat-sender-toolbar";
const SENDER_TOOLBAR_INSTALLED_KEY = "__datapawDataSourceSenderPrefixInstalled";

function wrapWithI18n(Component: ComponentType<any>) {
  return function Wrapped(props: any) {
    return (
      <PluginI18nProvider>
        <Component {...props} />
      </PluginI18nProvider>
    );
  };
}

function DatapawChatSenderToolbarPrefix() {
  const [active, setActive] = useState(isDatapawAgentSelected);

  useEffect(() => {
    const tick = () => setActive(isDatapawAgentSelected());
    tick();
    window.addEventListener("storage", tick);
    const timer = window.setInterval(tick, 800);
    return () => {
      window.removeEventListener("storage", tick);
      window.clearInterval(timer);
    };
  }, []);

  if (!active) return null;

  return (
    <PluginI18nProvider>
      <ChatSenderToolbar />
    </PluginI18nProvider>
  );
}

function registerChatSenderToolbar(): void {
  const win = window as Window & Record<string, boolean | undefined>;
  if (win[SENDER_TOOLBAR_INSTALLED_KEY]) return;

  const sender = window.QwenPaw?.chat?.sender;
  if (!sender?.addPrefix) {
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.chat.sender.addPrefix missing — data source selector skipped`,
    );
    return;
  }

  sender.addPrefix(
    PLUGIN_ID,
    <DatapawChatSenderToolbarPrefix />,
    { id: SENDER_TOOLBAR_PREFIX_ID, order: 10 },
  );
  win[SENDER_TOOLBAR_INSTALLED_KEY] = true;
}

export function setupDataPawHostChat(): void {
  const QP = window.QwenPaw;
  if (!QP?.host) {
    console.warn(`[${PLUGIN_ID}] window.QwenPaw.host missing — skipping`);
    return;
  }

  patchHostSessionApi();
  installFetchPatch();

  QP.registerToolRender?.(PLUGIN_ID, {
    fetch_data: wrapWithI18n(FetchDataToolAdapter),
  });

  registerChatSenderToolbar();
  setupHostChatIntegration();

}
