/** Local icon URLs for channel logos — shared by Channel settings cards and Chat session list. */
export const CHANNEL_ICON_URLS: Record<string, string> = {
  dingtalk: "/icons/channels/dingtalk.png",
  voice: "/icons/channels/voice.png",
  qq: "/icons/channels/qq.png",
  feishu: "/icons/channels/feishu.png",
  xiaoyi: "/icons/channels/xiaoyi.png",
  telegram: "/icons/channels/telegram.png",
  mqtt: "/icons/channels/mqtt.png",
  imessage: "/icons/channels/imessage.png",
  discord: "/icons/channels/discord.png",
  mattermost: "/icons/channels/mattermost.png",
  matrix: "/icons/channels/matrix.png",
  console: "/icons/channels/console.png",
  wecom: "/icons/channels/wecom.png",
  weixin: "/icons/channels/weixin.png",
};

export const CHANNEL_DEFAULT_ICON_URL = "/icons/channels/default.png";

export function getChannelIconUrl(channelKey: string): string {
  return CHANNEL_ICON_URLS[channelKey] ?? CHANNEL_DEFAULT_ICON_URL;
}
