/** CDN URLs for channel logos — used as primary icon with letter-avatar fallback. */
export const CHANNEL_ICON_URLS: Record<string, string> = {
  dingtalk:
    "https://gw.alicdn.com/imgextra/i4/O1CN01g1u9vB1KdEreWzDdv_!!6000000001186-2-tps-400-400.png",
  voice:
    "https://gw.alicdn.com/imgextra/i1/O1CN016SJ9AO1SpA6L3j0KH_!!6000000002295-2-tps-400-400.png",
  qq: "https://gw.alicdn.com/imgextra/i3/O1CN014wGNgd27PsTzAyrcj_!!6000000007790-2-tps-400-400.png",
  feishu:
    "https://gw.alicdn.com/imgextra/i4/O1CN01jsn08m225euyUoaFN_!!6000000007069-2-tps-400-400.png",
  xiaoyi:
    "https://gw.alicdn.com/imgextra/i1/O1CN01EPS9Z81OKhIEcwpCd_!!6000000001687-2-tps-476-476.png",
  telegram:
    "https://gw.alicdn.com/imgextra/i2/O1CN0100jIva25Dqqq1VqJN_!!6000000007493-2-tps-400-400.png",
  mqtt: "https://gw.alicdn.com/imgextra/i2/O1CN0117Adu3282o9G5ZNCd_!!6000000007875-2-tps-400-400.png",
  imessage:
    "https://gw.alicdn.com/imgextra/i1/O1CN016pwG4m1uEntwJKsGl_!!6000000006006-2-tps-400-400.png",
  discord:
    "https://gw.alicdn.com/imgextra/i4/O1CN01BQFnBu21PWTtKbPmU_!!6000000006977-2-tps-400-400.png",
  mattermost:
    "https://gw.alicdn.com/imgextra/i2/O1CN01A2bvSh1eVig4fDBEF_!!6000000003877-2-tps-400-400.png",
  matrix:
    "https://gw.alicdn.com/imgextra/i2/O1CN01Q8i1P826mUQG4dCAs_!!6000000007704-2-tps-400-400.png",
  console:
    "https://gw.alicdn.com/imgextra/i3/O1CN01L3azqd1XIi7O2jumZ_!!6000000002901-2-tps-400-400.png",
  wecom:
    "https://gw.alicdn.com/imgextra/i1/O1CN01HWtzmr1hkK9beQICJ_!!6000000004315-2-tps-400-400.png",
  weixin:
    "https://gw.alicdn.com/imgextra/i4/O1CN01GsAob11fkfDWVIb3R_!!6000000004045-2-tps-400-400.png",
  onebot:
    "https://gw.alicdn.com/imgextra/i3/O1CN01xqM0EN1oKrRiAFX3K_!!6000000005207-2-tps-400-400.png",
};

/** Get the CDN icon URL for a channel, or undefined if none exists. */
export function getChannelIconUrl(channelKey: string): string | undefined {
  return CHANNEL_ICON_URLS[channelKey];
}

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
