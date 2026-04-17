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

  // ── Signal device-link flow ──────────────────────────────────────────
  // Spawns `signal-cli link`, returns a PNG QR + link URL. Status polling
  // flips from "waiting_qr" to "linked" when the user scans in Signal.
  startSignalLink: (device_name?: string) =>
    request<{
      status: string;
      qr_image?: string;
      link_url?: string;
    }>("/config/channels/signal/link", {
      method: "POST",
      body: JSON.stringify({ device_name: device_name || "QwenPaw" }),
    }),
  checkSignalLinkStatus: () =>
    request<{
      status: string;
      qr_image?: string;
      link_url?: string;
      phone?: string;
      uuid?: string;
      error?: string;
    }>("/config/channels/signal/link/status"),
  stopSignalLink: () =>
    request<{ status: string }>(
      "/config/channels/signal/link/stop",
      { method: "POST" },
    ),
  unbindSignal: () =>
    request<{ status: string; detail?: string }>(
      "/config/channels/signal/unbind",
      { method: "POST" },
    ),
  getSignalStatus: () =>
    request<{
      linked: boolean;
      phone?: string | null;
      uuid?: string | null;
      error?: string;
    }>("/config/channels/signal/status"),
  listSignalContacts: () =>
    request<{
      contacts: Array<{ number: string; uuid: string; name: string }>;
    }>("/config/channels/signal/contacts"),
  listSignalGroups: () =>
    request<{ groups: Array<{ id: string; blocked: boolean }> }>(
      "/config/channels/signal/groups",
    ),
};
