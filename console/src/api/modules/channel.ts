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

  getChannelQrcode: (channel: string, params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<{ qrcode_img: string; poll_token: string }>(
      `/config/channels/${encodeURIComponent(channel)}/qrcode${qs}`,
    );
  },

  getChannelQrcodeStatus: (
    channel: string,
    token: string,
    params?: Record<string, string>,
  ) => {
    const extra = params ? "&" + new URLSearchParams(params).toString() : "";
    return request<{
      status: string;
      credentials: Record<string, string>;
    }>(
      `/config/channels/${encodeURIComponent(
        channel,
      )}/qrcode/status?token=${encodeURIComponent(token)}${extra}`,
    );
  },
};
