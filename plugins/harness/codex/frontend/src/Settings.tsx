import { getHost, type HarnessSettingsProps } from "@qwenpaw/plugin-sdk";
import { Settings as HarnessSettings } from "../../../_shared/ui/Settings";
import { localMessages } from "./locale";

const host = getHost().host;
const React = host.React;

export function Settings(props: HarnessSettingsProps) {
  return (
    <HarnessSettings
      {...props}
      backendId="codex"
      providerName="Codex"
      text={localMessages(host.useLocale())}
      loginMode="browser"
      canDisconnect={(status) => status.account?.type === "chatgpt"}
    />
  );
}
