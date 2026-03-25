import { request } from "../request";
import type {
  ChannelConfig,
  SingleChannelConfig,
  WechatQrStartRequest,
  WechatQrStartResponse,
  WechatQrWaitRequest,
  WechatQrWaitResponse,
} from "../types";

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

  startWechatQrLogin: (body: WechatQrStartRequest = {}) =>
    request<WechatQrStartResponse>("/wechat/login/qr/start", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  waitWechatQrLogin: (body: WechatQrWaitRequest) =>
    request<WechatQrWaitResponse>("/wechat/login/qr/wait", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
