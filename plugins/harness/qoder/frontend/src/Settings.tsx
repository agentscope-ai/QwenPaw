import { getHost, type HarnessSettingsProps } from "@qwenpaw/plugin-sdk";
import { Settings as HarnessSettings } from "../../../_shared/ui/Settings";
import { localMessages } from "./locale";

const host = getHost().host;
const React = host.React;

export function Settings(props: HarnessSettingsProps) {
  return (
    <HarnessSettings
      {...props}
      backendId="qoder"
      providerName="Qoder"
      text={localMessages(host.useLocale())}
      loginMode="external"
    />
  );
}
