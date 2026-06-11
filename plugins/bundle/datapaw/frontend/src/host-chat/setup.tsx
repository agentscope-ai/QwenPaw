import type { ComponentType } from "react";
import { FetchDataToolAdapter } from "../pages/Chat/components/FetchDataBlock";
import { PluginI18nProvider } from "./plugin-i18n";
import { patchHostSessionApi } from "../hostSessionApiPatch";
import { installFetchPatch } from "./fetch-patch";
import { setupHostChatIntegration } from "../plugin-host";
import { PLUGIN_ID } from "../plugin/constants";

function wrapWithI18n(Component: ComponentType<any>) {
  return function Wrapped(props: any) {
    return (
      <PluginI18nProvider>
        <Component {...props} />
      </PluginI18nProvider>
    );
  };
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

  setupHostChatIntegration();

}
