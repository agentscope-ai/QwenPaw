import { request } from "../request";
import type { ChannelConfig, SingleChannelConfig } from "../types";

/**
 * Localized text: either a plain string, or a mapping from locale code
 * (e.g. "zh-CN", "en-US", "zh", "en") to the display string.
 * Plain strings are shown as-is; dict values are resolved against the
 * current UI language with graceful fallback (see resolveLocalized).
 */
export type LocalizedText = string | Record<string, string>;

export interface ChannelConfigField {
  name: string;
  label: LocalizedText;
  type: "text" | "password" | "number" | "switch" | "select";
  required?: boolean;
  placeholder?: LocalizedText;
  help?: LocalizedText;
  default?: unknown;
  options?: string[];
}

export interface ChannelSchema {
  label: string;
  description: string;
  plugin_id: string;
  config_fields: ChannelConfigField[];
  icon?: string;
  doc_url?: LocalizedText;
}

export const channelApi = {
  listChannelTypes: () => request<string[]>("/config/channels/types"),

  listChannels: () => request<ChannelConfig>("/config/channels"),

  listChannelSchemas: () =>
    request<Record<string, ChannelSchema>>("/config/channels/schemas"),

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
