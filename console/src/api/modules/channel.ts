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

  startWhatsappPair: (phone?: string) =>
    request<{ status: string; pair_code?: string; qr_image?: string; phone?: string }>(
      `/config/channels/whatsapp/pair${phone ? `?phone=${encodeURIComponent(phone)}` : ""}`,
      { method: "POST" },
    ),
  checkWhatsappPairStatus: () =>
    request<{ status: string; pair_code?: string; qr_image?: string }>(
      "/config/channels/whatsapp/pair/status",
    ),
  stopWhatsappPair: () =>
    request<{ status: string }>("/config/channels/whatsapp/pair/stop", { method: "POST" }),
  getWhatsappQrcode: () =>
    request<{ status: string; qr_image?: string }>(
      "/config/channels/whatsapp/qrcode",
      { method: "POST" },
    ),
  unbindWhatsapp: () =>
    request<{ status: string; detail?: string }>(
      "/config/channels/whatsapp/unbind",
      { method: "POST" },
    ),
  getWhatsappStatus: () =>
    request<{ linked: boolean; phone?: string }>("/config/channels/whatsapp/status"),

};
