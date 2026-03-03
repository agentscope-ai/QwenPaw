import type { ChannelConfig } from "../../../../api/types";

export type ChannelKey = keyof ChannelConfig;

export const CHANNEL_LABELS: Record<ChannelKey, string> = {
  imessage: "iMessage",
  discord: "Discord",
  dingtalk: "DingTalk",
  feishu: "Feishu",
  qq: "QQ",
  telegram: "Telegram",
  console: "Console",
};
