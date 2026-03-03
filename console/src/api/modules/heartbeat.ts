import { request } from "../request";
import type { HeartbeatConfig } from "../types/heartbeat";

export const heartbeatApi = {
  getHeartbeatConfig: () => request<HeartbeatConfig>("/config/heartbeat"),

  updateHeartbeatConfig: (body: HeartbeatConfig) =>
    request<HeartbeatConfig>("/config/heartbeat", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
