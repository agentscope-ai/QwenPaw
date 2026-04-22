/** Predefined background colors for letter-avatar icons. */
const LETTER_ICON_COLORS: Record<string, string> = {
  console: "#FF7F16",
  onebot: "#6ECB63",
  dingtalk: "#3370FF",
  feishu: "#3370FF",
  qq: "#12B7F5",
  telegram: "#2AABEE",
  discord: "#5865F2",
  wecom: "#07C160",
  weixin: "#07C160",
  mqtt: "#660066",
  mattermost: "#0058CC",
  matrix: "#0DBD8B",
  imessage: "#34C759",
  voice: "#F44336",
  xiaoyi: "#CF1322",
};

/** A palette of fallback colors for channels without a predefined color. */
const FALLBACK_COLORS = [
  "#FF6B6B",
  "#4ECDC4",
  "#45B7D1",
  "#96CEB4",
  "#FFEAA7",
  "#DDA0DD",
  "#98D8C8",
  "#F7DC6F",
  "#BB8FCE",
  "#85C1E9",
  "#F0B27A",
  "#82E0AA",
];

/** Get the background color for a channel's letter-avatar icon. */
export function getChannelLetterColor(channelKey: string): string {
  if (LETTER_ICON_COLORS[channelKey]) {
    return LETTER_ICON_COLORS[channelKey];
  }
  // Deterministic fallback based on string hash
  let hash = 0;
  for (let i = 0; i < channelKey.length; i++) {
    hash = ((hash << 5) - hash + channelKey.charCodeAt(i)) | 0;
  }
  return FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];
}

/** Get the display letter(s) for a channel's letter-avatar icon. */
export function getChannelLetter(channelKey: string): string {
  return channelKey.charAt(0).toUpperCase();
}
