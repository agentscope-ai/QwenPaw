import type { TFunction } from "i18next";

// Channel key type - now accepts any string for custom channels
export type ChannelKey = string;

// Built-in channel labels
export const CHANNEL_LABELS: Record<string, string> = {
  imessage: "iMessage",
  discord: "Discord",
  dingtalk: "DingTalk",
  feishu: "Feishu",
  qq: "QQ",
  telegram: "Telegram",
  slack: "Slack",
  mqtt: "MQTT",
  mattermost: "Mattermost",
  matrix: "Matrix",
  console: "Console",
  voice: "Twilio",
  sip: "SIP",
  wecom: "WeCom",
  xiaoyi: "XiaoYi",
  wechat: "WeChat",
  onebot: "OneBot",
  yuanbao: "Yuanbao",
};

function formatCustomChannelKey(key: string): string {
  return key
    .split(/[_-]/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Per-locale strings under `channels.channelNames.*`; missing keys use `defaultValue` (English labels).
export function getChannelLabel(key: string, t?: TFunction): string {
  const english = CHANNEL_LABELS[key] ?? formatCustomChannelKey(key);
  if (t) {
    return t(`channels.channelNames.${key}`, { defaultValue: english });
  }
  return english;
}

const LOOPBACK_HOSTNAMES = new Set(["localhost"]);
const IPV4_LOOPBACK_RE = /^127(\.\d{1,3}){3}$/;
const IPV6_LOOPBACK_RE = /^(?:0*:)+0*1$/;

/**
 * Whether a listen address only accepts connections from the local machine.
 *
 * Mirrors `is_loopback_host` in `src/qwenpaw/utils/http.py`, which stays
 * authoritative; this copy only drives form validation. Unspecified
 * addresses such as `0.0.0.0`, `::` and the empty string bind every
 * interface and are therefore not loopback.
 */
export function isLoopbackHost(host: string): boolean {
  const candidate = (host ?? "")
    .trim()
    .replace(/^\[|\]$/g, "")
    .toLowerCase()
    .replace(/\.$/, "");
  if (!candidate) return false;
  if (LOOPBACK_HOSTNAMES.has(candidate)) return true;
  if (IPV4_LOOPBACK_RE.test(candidate)) return true;
  return IPV6_LOOPBACK_RE.test(candidate);
}
