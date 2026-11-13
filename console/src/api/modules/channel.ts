import { request } from "../request";
import type { ChannelConfig, SingleChannelConfig } from "../types";
import { installPlugin, repairPluginDependencies } from "./plugin";

export type ChannelRequestScope = { agentId: string; signal?: AbortSignal };
export type ChannelAuthProvenance = {
  agentId: string;
  channel: string;
  token: string;
};
export type ChannelSaveJob = Readonly<{
  agentId: string;
  channel: string;
  body: Record<string, unknown>;
  authSession?: string;
  formRevision: number;
}>;

const requestScope = (scope?: ChannelRequestScope | string) => {
  if (typeof scope === "string")
    return scope ? { headers: { "X-Agent-Id": scope } } : {};
  return scope
    ? { headers: { "X-Agent-Id": scope.agentId }, signal: scope.signal }
    : {};
};

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
  type: "text" | "password" | "number" | "switch" | "select" | "json";
  json_type?: "object" | "array";
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
  owner?: string;
  form_kind?: string;
  process_mode?: string;
  availability?: string;
  qrcode_available?: boolean;
  global_enabled?: boolean;
  diagnostic?: string;
  repair?: {
    action: "install" | "enable" | "repair";
    plugin_id: string;
    source?: string;
  };
}

export interface ChannelConflictAgent {
  agent_id: string;
  agent_name: string;
}

export interface ChannelConflictResponse {
  conflict: boolean;
  agents: ChannelConflictAgent[];
}

export const channelApi = {
  repairChannel: (repair: NonNullable<ChannelSchema["repair"]>) => {
    const id = encodeURIComponent(repair.plugin_id);
    if (repair.action === "install") {
      if (!repair.source)
        return Promise.reject(new Error("Plugin install source is missing"));
      return installPlugin(repair.source);
    }
    if (repair.action === "repair")
      return repairPluginDependencies(repair.plugin_id);
    return request(`/plugins/${id}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled: true }),
    });
  },
  listChannelTypes: (scope?: ChannelRequestScope | string) =>
    request<string[]>("/config/channels/types", requestScope(scope)),

  listChannels: (scope?: ChannelRequestScope | string) =>
    request<ChannelConfig>("/config/channels", requestScope(scope)),

  listChannelSchemas: (scope?: ChannelRequestScope | string) =>
    request<Record<string, ChannelSchema>>(
      "/config/channels/schemas",
      requestScope(scope),
    ),

  updateChannels: (body: ChannelConfig) =>
    request<ChannelConfig>("/config/channels", {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getChannelConfig: (channelName: string) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
    ),

  updateChannelConfig: (
    channelName: string,
    body: SingleChannelConfig,
    agentId?: string,
    authSession?: string,
  ) =>
    request<SingleChannelConfig>(
      `/config/channels/${encodeURIComponent(channelName)}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
        headers: {
          ...(agentId ? { "X-Agent-Id": agentId } : {}),
          ...(authSession !== undefined
            ? { "X-Channel-Auth-Session": authSession }
            : {}),
        },
      },
    ),

  checkChannelConflict: (
    channelName: string,
    body: SingleChannelConfig,
    agentId?: string,
  ) =>
    request<ChannelConflictResponse>(
      `/config/channels/${encodeURIComponent(channelName)}/conflict-check`,
      {
        method: "POST",
        body: JSON.stringify(body),
        ...(agentId ? { headers: { "X-Agent-Id": agentId } } : {}),
      },
    ),

  getChannelQrcode: (
    channel: string,
    params?: Record<string, string>,
    scope?: ChannelRequestScope,
  ) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<{ qrcode_img: string; poll_token: string }>(
      `/config/channels/${encodeURIComponent(channel)}/qrcode${qs}`,
      { ...requestScope(scope), timeout: 40000 },
    );
  },

  getChannelQrcodeStatus: (
    channel: string,
    token: string,
    params?: Record<string, string>,
    scope?: ChannelRequestScope,
  ) => {
    const extra = params ? "&" + new URLSearchParams(params).toString() : "";
    return request<{
      status: string;
      credentials: Record<string, string>;
    }>(
      `/config/channels/${encodeURIComponent(
        channel,
      )}/qrcode/status?token=${encodeURIComponent(token)}${extra}`,
      { ...requestScope(scope), timeout: 70000 },
    );
  },

  cancelChannelQrcode: (
    channel: string,
    token: string,
    scope: ChannelRequestScope,
  ) =>
    request<void>(
      `/config/channels/${encodeURIComponent(
        channel,
      )}/qrcode?token=${encodeURIComponent(token)}`,
      { method: "DELETE", ...requestScope(scope) },
    ),
};
