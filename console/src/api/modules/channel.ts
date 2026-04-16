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

  getChannelConfig: (channelName: string, agentId?: string) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
      agentId ? { headers: { "X-Agent-Id": agentId } } : undefined,
    ),

  updateChannelConfig: (
    channelName: string,
    body: SingleChannelConfig,
    agentId?: string,
  ) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
        ...(agentId ? { headers: { "X-Agent-Id": agentId } } : {}),
      },
    ),

  getChannelQrcode: (channel: string) =>
    request<{ qrcode_img: string; poll_token: string }>(
      `/config/channels/${encodeURIComponent(channel)}/qrcode`,
    ),

  getChannelQrcodeStatus: (channel: string, token: string) =>
    request<{
      status: string;
      credentials: Record<string, string>;
    }>(
      `/config/channels/${encodeURIComponent(
        channel,
      )}/qrcode/status?token=${encodeURIComponent(token)}`,
    ),
};
