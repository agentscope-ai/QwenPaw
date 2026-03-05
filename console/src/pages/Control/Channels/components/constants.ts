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
  console: "Console",
  voice: "Twilio",
};

// Get channel label - returns built-in label or formatted custom name
export function getChannelLabel(key: string): string {
  if (CHANNEL_LABELS[key]) {
    return CHANNEL_LABELS[key];
  }
  // Format custom channel name: my_channel -> My Channel
  return key
    .split(/[_-]/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
