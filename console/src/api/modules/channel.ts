import { request } from "../request";
import type { ChannelConfig, SingleChannelConfig } from "../types";

export const channelApi = {
  listChannelTypes: () => request<string[]>("/config/channels/types"),

  listChannels: () => request<ChannelConfig>("/config/channels"),

  updateChannels: (body: ChannelConfig) =>
    request<ChannelConfig>("/config/channels", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getChannelConfig: (channelName: string) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
    ),

  updateChannelConfig: (channelName: string, body: SingleChannelConfig) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    ),

  getWeixinQrcode: () =>
    request<{ qrcode_img: string; qrcode: string }>(
      "/config/channels/weixin/qrcode",
    ),

  getWeixinQrcodeStatus: (qrcode: string) =>
    request<{ status: string; bot_token: string; base_url: string }>(
      `/config/channels/weixin/qrcode/status?qrcode=${encodeURIComponent(
        qrcode,
      )}`,
    ),
};
